"""Runs an investigation, persisting the run and every step."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.repository import ChartRepository
from app.investigator.graph import build_graph
from app.models import InvestigationRun, InvestigationStep
from app.tracing import trace_metadata


def run_investigation(
    session: Session,
    patient_id: str,
    current_note: str = "",
    encounter_id: str | None = None,
    provider=None,
) -> dict:
    repo = ChartRepository(session, patient_id)
    repo.patient()  # raises PatientNotFoundError early

    run_id = f"run-{uuid.uuid4().hex[:12]}"
    run = InvestigationRun(
        run_id=run_id, patient_id=patient_id, encounter_id=encounter_id, status="running"
    )
    session.add(run)
    session.flush()

    graph = build_graph(repo, provider)
    state = graph.invoke(
        {"patient_id": patient_id, "current_note": current_note},
        config={
            "recursion_limit": 50,
            "run_name": "chartlens.investigate",
            **trace_metadata(patient_id=patient_id, run_id=run_id, encounter_id=encounter_id),
        },
    )

    for i, step in enumerate(state["steps"]):
        session.add(
            InvestigationStep(
                run_id=run_id,
                step_index=i,
                node=step["node"],
                action=step["action"],
                detail=step.get("detail"),
                payload_json=step.get("payload"),
            )
        )
    result = {
        "run_id": run_id,
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "status": "completed",
        "stop_reason": state["stop_reason"],
        "tool_calls_used": state["tool_calls_used"],
        "items": state["items"],
        "coverage_report": state.get("coverage_report"),
        "signal_synthesis": state.get("signal_synthesis"),
    }
    run.status = "completed"
    run.finished_at = datetime.now(UTC)
    run.tool_calls_used = state["tool_calls_used"]
    run.stop_reason = state["stop_reason"]
    run.result_json = result
    session.flush()
    return result


def get_run(session: Session, run_id: str, include_steps: bool = False) -> dict | None:
    from sqlalchemy import select

    run = session.scalar(select(InvestigationRun).where(InvestigationRun.run_id == run_id))
    if run is None:
        return None
    out = dict(run.result_json or {})
    out.setdefault("run_id", run.run_id)
    out.setdefault("patient_id", run.patient_id)
    out["status"] = run.status
    if include_steps:
        steps = session.scalars(
            select(InvestigationStep)
            .where(InvestigationStep.run_id == run_id)
            .order_by(InvestigationStep.step_index)
        )
        out["steps"] = [
            {
                "step_index": s.step_index,
                "node": s.node,
                "action": s.action,
                "detail": s.detail,
                "payload": s.payload_json,
            }
            for s in steps
        ]
    return out
