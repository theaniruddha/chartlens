import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import lint as lint_engine
from app import playground
from app.config import get_settings
from app.db.repository import ChartRepository
from app.db.session import get_session
from app.investigator.runner import get_run, run_investigation
from app.models import Condition, Note, Patient
from app.note_review.engine import review_note
from app.providers.gateway import build_lint_provider, build_provider
from app.timeutil import utc_iso
from app.tools.semantic_tools import (
    get_coverage,
    get_evidence_details,
    get_medications_and_allergies,
    get_metric_series,
    get_metric_snapshots,
    get_patient_brief,
)
from app.tracing import tracing_enabled

router = APIRouter()


class NoteReviewRequest(BaseModel):
    current_note: str = Field(min_length=1, max_length=20000)
    encounter_id: str | None = None


class InvestigateRequest(BaseModel):
    current_note: str = Field(default="", max_length=20000)
    encounter_id: str | None = None


class EvidenceRequest(BaseModel):
    evidence_ids: list[str] = Field(min_length=1, max_length=20)


class SaveNoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    note_type: str = Field(default="progress", max_length=64)


class ObservationIn(BaseModel):
    metric_code: str = Field(min_length=1, max_length=64)
    value: float
    display: str | None = Field(default=None, max_length=128)
    unit: str | None = Field(default=None, max_length=32)
    clinical_time: str | None = None


class AddObservationsRequest(BaseModel):
    observations: list[ObservationIn] = Field(min_length=1, max_length=playground.MAX_BATCH)


class LintRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    mode: str = Field(default="fast", pattern="^(fast|full)$")


class AnnotationDecisionRequest(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    quote: str = Field(min_length=1, max_length=500)
    decision: str = Field(pattern="^(accepted|dismissed)$")
    note_text: str = Field(default="", max_length=20000)


class ProblemListRequest(BaseModel):
    display: str = Field(min_length=3, max_length=100)


class ScenarioRequest(BaseModel):
    description: str = Field(min_length=5, max_length=2000)


class GenerateSeriesRequest(BaseModel):
    metric_code: str = Field(min_length=1, max_length=64)
    trend: str = Field(pattern="^(rising|falling|stable)$")
    n_points: int = Field(default=4, ge=2, le=playground.MAX_GENERATED_POINTS)
    months_back: int = Field(default=12, ge=1, le=36)
    start_value: float | None = None


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "provider": build_provider().name,
        "tracing": "langsmith" if tracing_enabled() else "off",
    }


@router.get("/v1/patients")
def list_patients(session: Session = Depends(get_session)) -> dict:
    patients = session.scalars(select(Patient).order_by(Patient.patient_id))
    return {
        "patients": [
            {"patient_id": p.patient_id, "mrn": p.mrn, "name": p.name} for p in patients
        ]
    }


@router.get("/v1/patients/{patient_ref}/context")
def patient_context(patient_ref: str, session: Session = Depends(get_session)) -> dict:
    repo, patient = _repo(session, patient_ref)
    notes = repo.notes(limit=5)
    snapshots = get_metric_snapshots(repo)["snapshots"]
    return {
        "brief": {**get_patient_brief(repo), "mrn": patient.mrn},
        "coverage": get_coverage(repo),
        "snapshots": snapshots,
        "history": {
            s["metric_code"]: get_metric_series(repo, s["metric_code"])["points"]
            for s in snapshots
        },
        "medications_allergies": get_medications_and_allergies(repo),
        "recent_notes": [
            {
                "evidence_id": n.source_resource_id,
                "note_type": n.note_type,
                "time": utc_iso(n.clinical_time),
                "snippet": n.text[:300],
                "source_system": n.source_system,
            }
            for n in notes
        ],
        "visits": [
            {
                "evidence_id": e.source_resource_id,
                "encounter_type": e.encounter_type,
                "reason": e.reason,
                "time": utc_iso(e.clinical_time),
                "source_system": e.source_system,
            }
            for e in repo.encounters(limit=20)
        ],
        "active_deferrals": [
            {
                "evidence_id": d.source_resource_id,
                "topic": d.topic,
                "deferred_until": utc_iso(d.deferred_until),
                "reason": d.reason,
            }
            for d in repo.active_deferrals()
        ],
        "playground_observations": playground.list_playground(session, repo.patient_id),
    }


@router.post("/v1/patients/{patient_ref}/notes/review")
def note_review(
    patient_ref: str, body: NoteReviewRequest, session: Session = Depends(get_session)
) -> dict:
    repo, _ = _repo(session, patient_ref)
    return review_note(
        session, repo.patient_id, body.current_note, build_provider(),
        encounter_id=body.encounter_id,
    )


@router.post("/v1/patients/{patient_ref}/investigate")
def investigate(
    patient_ref: str, body: InvestigateRequest, session: Session = Depends(get_session)
) -> dict:
    repo, _ = _repo(session, patient_ref)
    return run_investigation(
        session,
        repo.patient_id,
        current_note=body.current_note,
        encounter_id=body.encounter_id,
        provider=build_provider(),
    )


@router.post("/v1/patients/{patient_ref}/notes")
def save_note(
    patient_ref: str, body: SaveNoteRequest, session: Session = Depends(get_session)
) -> dict:
    """Persist a clinician note into the chart; future analyses see it as a
    prior note."""
    repo, _ = _repo(session, patient_ref)
    note = Note(
        patient_id=repo.patient_id,
        note_type=body.note_type,
        text=body.text,
        clinical_time=datetime.now(UTC),
        recorded_time=datetime.now(UTC),
        source_system="clinician",
        source_resource_id=f"note-{uuid.uuid4().hex[:12]}",
    )
    session.add(note)
    session.flush()
    return {
        "evidence_id": note.source_resource_id,
        "note_type": note.note_type,
        "clinical_time": utc_iso(note.clinical_time),
        "saved": True,
    }


@router.post("/v1/patients/{patient_ref}/notes/lint")
def lint_note(
    patient_ref: str, body: LintRequest, session: Session = Depends(get_session)
) -> dict:
    """Span-anchored inline annotations for a draft note. `fast` is
    deterministic-only; `full` adds one bounded model pass."""
    repo, _ = _repo(session, patient_ref)
    provider = build_lint_provider() if body.mode == "full" else None
    return lint_engine.lint_note(session, repo, body.text, mode=body.mode, provider=provider)


@router.post("/v1/patients/{patient_ref}/annotations/decision")
def annotation_decision(
    patient_ref: str, body: AnnotationDecisionRequest, session: Session = Depends(get_session)
) -> dict:
    repo, _ = _repo(session, patient_ref)
    return lint_engine.record_decision(
        session, repo.patient_id, body.category, body.quote, body.decision, body.note_text
    )


@router.post("/v1/patients/{patient_ref}/problem-list")
def add_problem(
    patient_ref: str, body: ProblemListRequest, session: Session = Depends(get_session)
) -> dict:
    """Accept action for a new-dx annotation: add a clinician-sourced condition."""
    repo, _ = _repo(session, patient_ref)
    row = Condition(
        patient_id=repo.patient_id,
        display=body.display,
        clinical_status="active",
        clinical_time=datetime.now(UTC),
        recorded_time=datetime.now(UTC),
        source_system="clinician",
        source_resource_id=f"cond-{uuid.uuid4().hex[:12]}",
    )
    session.add(row)
    session.flush()
    return {"evidence_id": row.source_resource_id, "display": row.display, "added": True}


@router.post("/v1/patients/{patient_ref}/playground/observations")
def playground_add(
    patient_ref: str, body: AddObservationsRequest, session: Session = Depends(get_session)
) -> dict:
    repo, _ = _repo(session, patient_ref)
    return playground.add_observations(
        session, repo.patient_id, [o.model_dump() for o in body.observations]
    )


@router.post("/v1/patients/{patient_ref}/playground/generate")
def playground_generate(
    patient_ref: str, body: GenerateSeriesRequest, session: Session = Depends(get_session)
) -> dict:
    repo, _ = _repo(session, patient_ref)
    values, generator = playground.generate_series(
        build_provider(), body.metric_code, body.trend, body.n_points, body.months_back,
        body.start_value,
    )
    obs = playground.series_to_observations(values, body.metric_code, body.months_back)
    result = playground.add_observations(session, repo.patient_id, obs)
    result["generator"] = generator
    result["values"] = values
    return result


@router.post("/v1/patients/{patient_ref}/playground/scenario")
def playground_scenario(
    patient_ref: str, body: ScenarioRequest, session: Session = Depends(get_session)
) -> dict:
    repo, _ = _repo(session, patient_ref)
    scenario = playground.scenario_from_text(build_provider(), body.description)
    if scenario is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Scenario simulation needs a configured model provider and a "
                "description it can convert into records."
            ),
        )
    return playground.apply_scenario(session, repo.patient_id, scenario)


@router.delete("/v1/patients/{patient_ref}/playground")
def playground_clear(patient_ref: str, session: Session = Depends(get_session)) -> dict:
    repo, _ = _repo(session, patient_ref)
    removed = playground.clear_playground(session, repo.patient_id)
    return {"removed": removed}


@router.get("/v1/investigations/{run_id}")
def investigation(
    run_id: str, include_steps: bool = False, session: Session = Depends(get_session)
) -> dict:
    show_steps = include_steps and get_settings().show_trace
    result = get_run(session, run_id, include_steps=show_steps)
    if result is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return result


@router.post("/v1/patients/{patient_ref}/evidence")
def evidence(
    patient_ref: str, body: EvidenceRequest, session: Session = Depends(get_session)
) -> dict:
    repo, _ = _repo(session, patient_ref)
    return get_evidence_details(repo, body.evidence_ids)


def _repo(session: Session, patient_ref: str) -> tuple[ChartRepository, Patient]:
    """Resolve a patient by internal ID or MRN; everything downstream uses the
    internal patient_id."""
    patient = session.scalar(
        select(Patient).where(
            (Patient.patient_id == patient_ref) | (Patient.mrn == patient_ref)
        )
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="patient not found")
    return ChartRepository(session, patient.patient_id), patient
