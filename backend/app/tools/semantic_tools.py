"""The 12 allowed semantic tools. Every tool takes a patient-scoped
ChartRepository and returns a bounded, JSON-serializable dict. No raw SQL is
exposed anywhere above the repository."""

from datetime import datetime

from app.analytics.trends import RELATED_METRICS, is_stale
from app.db.repository import ChartRepository
from app.note_review.extract import extract_note_facts
from app.timeutil import utc_iso

MAX_SERIES_POINTS = 24
MAX_NOTES = 3


def _iso(dt: datetime | None) -> str | None:
    return utc_iso(dt)


def get_patient_brief(repo: ChartRepository) -> dict:
    p = repo.patient()
    encounters = repo.encounters(limit=1)
    return {
        "patient_id": p.patient_id,
        "name": p.name,
        "sex": p.sex,
        "birth_date": _iso(p.birth_date),
        "active_conditions": [
            {"evidence_id": c.source_resource_id, "display": c.display}
            for c in repo.active_conditions()[:10]
        ],
        "active_medication_count": len(repo.medications()),
        "allergy_count": len(repo.allergies()),
        "last_encounter": (
            {
                "evidence_id": encounters[0].source_resource_id,
                "type": encounters[0].encounter_type,
                "time": _iso(encounters[0].clinical_time),
            }
            if encounters
            else None
        ),
    }


def get_coverage(repo: ChartRepository) -> dict:
    codes = repo.distinct_metric_codes()
    snaps = {s.metric_code: s for s in repo.metric_snapshots()}
    return {
        "metrics": [
            {
                "metric_code": c,
                "n_points": snaps[c].n_points if c in snaps else 0,
                "latest_time": _iso(snaps[c].latest_time) if c in snaps else None,
                "stale": is_stale(c, snaps[c].latest_time) if c in snaps else True,
            }
            for c in sorted(codes)
        ],
        "note_count": len(repo.notes(limit=10)),
        "limitations": "Coverage reflects connected records only.",
    }


def get_metric_snapshots(repo: ChartRepository, metric_codes: list[str] | None = None) -> dict:
    snaps = repo.metric_snapshots(metric_codes)
    return {
        "snapshots": [
            {
                "evidence_id": s.source_resource_id,
                "metric_code": s.metric_code,
                "display": s.display,
                "latest_value": s.latest_value,
                "unit": s.unit,
                "latest_time": _iso(s.latest_time),
                "delta": s.delta,
                "slope_per_month": s.slope_per_month,
                "n_points": s.n_points,
            }
            for s in snaps[:20]
        ]
    }


def get_metric_series(repo: ChartRepository, metric_code: str) -> dict:
    obs = repo.observations_for_metric(metric_code, limit=MAX_SERIES_POINTS)
    return {
        "metric_code": metric_code,
        "points": [
            {
                "evidence_id": o.source_resource_id,
                "value": o.value,
                "unit": o.unit,
                "time": _iso(o.clinical_time),
            }
            for o in obs
        ],
        "found": bool(obs),
    }


def get_related_metric_snapshots(repo: ChartRepository, metric_code: str) -> dict:
    related_codes = RELATED_METRICS.get(metric_code, [])
    result = get_metric_snapshots(repo, related_codes) if related_codes else {"snapshots": []}
    return {"metric_code": metric_code, "related": result["snapshots"]}


def get_active_conditions(repo: ChartRepository) -> dict:
    return {
        "conditions": [
            {
                "evidence_id": c.source_resource_id,
                "display": c.display,
                "code": c.code,
                "since": _iso(c.clinical_time),
            }
            for c in repo.active_conditions()[:20]
        ]
    }


def get_medications_and_allergies(repo: ChartRepository) -> dict:
    return {
        "medications": [
            {
                "evidence_id": m.source_resource_id,
                "name": m.name,
                "dose": m.dose,
                "frequency": m.frequency,
                "status": m.status,
                "as_of": _iso(m.clinical_time),
            }
            for m in repo.medications(active_only=False)[:20]
        ],
        "allergies": [
            {
                "evidence_id": a.source_resource_id,
                "substance": a.substance,
                "reaction": a.reaction,
                "severity": a.severity,
                "status": a.status,
            }
            for a in repo.allergies()[:20]
        ],
    }


def get_recent_plan_candidates(repo: ChartRepository) -> dict:
    """Plan items and symptom mentions parsed from recent prior notes, plus
    structured care plans."""
    candidates = []
    symptoms = []
    for note in repo.notes(limit=MAX_NOTES + 2):
        facts = extract_note_facts(note.text)
        for item in facts.plan_items:
            candidates.append(
                {
                    "evidence_id": note.source_resource_id,
                    "note_time": _iso(note.clinical_time),
                    "plan_text": item.text[:200],
                    "topic": item.topic,
                    "origin": "note",
                }
            )
        for sym in facts.symptoms:
            symptoms.append(
                {
                    "evidence_id": note.source_resource_id,
                    "note_time": _iso(note.clinical_time),
                    "term": sym.term,
                    "category": sym.category,
                }
            )
    for cp in repo.care_plans(limit=10):
        if cp.status == "active":
            candidates.append(
                {
                    "evidence_id": cp.source_resource_id,
                    "note_time": _iso(cp.clinical_time),
                    "plan_text": cp.description[:200],
                    "topic": cp.topic,
                    "origin": "care_plan",
                }
            )
    return {"candidates": candidates[:15], "symptoms": symptoms[:10]}


_TOPIC_RESOLVERS: dict[str, dict] = {
    "colonoscopy": {"proc_kw": ["colonoscopy"], "metrics": []},
    "mammogram": {"proc_kw": ["mammogram"], "metrics": []},
    "a1c_followup": {"proc_kw": ["a1c"], "metrics": ["hba1c"]},
    "lipid_followup": {"proc_kw": ["lipid"], "metrics": ["ldl"]},
    "bp_followup": {"proc_kw": ["blood pressure"], "metrics": ["sbp"]},
    "renal_followup": {
        "proc_kw": ["renal", "metabolic"],
        "metrics": ["creatinine", "egfr", "potassium"],
    },
    "imaging_followup": {"proc_kw": ["x-ray", "mri", "ct", "imaging"], "metrics": []},
}


def get_followup_resolution(repo: ChartRepository, topic: str, since: str | None = None) -> dict:
    """Did anything in the chart resolve this plan topic after `since`?"""
    spec = _TOPIC_RESOLVERS.get(topic, {"proc_kw": [topic.replace("_", " ")], "metrics": []})
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None

    def after(t: datetime | None) -> bool:
        return t is not None and (since_dt is None or t > since_dt)

    resolvers = []
    for pr in repo.procedures():
        if after(pr.clinical_time) and any(kw in pr.display.lower() for kw in spec["proc_kw"]):
            resolvers.append(
                {"evidence_id": pr.source_resource_id, "kind": "procedure", "display": pr.display,
                 "time": _iso(pr.clinical_time)}
            )
    for od in repo.orders():
        if after(od.clinical_time) and any(kw in od.display.lower() for kw in spec["proc_kw"]):
            resolvers.append(
                {
                    "evidence_id": od.source_resource_id,
                    "kind": "order_record",
                    "display": od.display,
                    "time": _iso(od.clinical_time),
                }
            )
    for code in spec["metrics"]:
        for o in repo.observations_for_metric(code):
            if after(o.clinical_time):
                resolvers.append(
                    {"evidence_id": o.source_resource_id, "kind": "observation",
                     "display": o.display, "time": _iso(o.clinical_time)}
                )
    return {"topic": topic, "resolved": bool(resolvers), "resolvers": resolvers[:5]}


def search_prior_notes(repo: ChartRepository, query: str, k: int = MAX_NOTES) -> dict:
    hits = repo.search_notes(query, limit=min(k, MAX_NOTES))
    return {
        "query": query,
        "hits": [
            {
                "evidence_id": note.source_resource_id,
                "note_type": note.note_type,
                "time": _iso(note.clinical_time),
                "snippet": note.text[:300],
                "rank": round(rank, 4),
            }
            for note, rank in hits
        ],
        "found": bool(hits),
    }


def get_note_evidence(repo: ChartRepository, note_id: str) -> dict:
    details = repo.evidence_by_ids([note_id])
    return {"note": details[0] if details else None, "found": bool(details)}


def get_evidence_details(repo: ChartRepository, evidence_ids: list[str]) -> dict:
    """Resolve chart records (patient-scoped) and drug-reference entries."""
    from app.reference.drugs import reference_evidence as drug_ref
    from app.reference.metrics import reference_evidence as metric_ref

    ids = evidence_ids[:20]
    chart_ids = [e for e in ids if not e.startswith("ref-")]
    out = repo.evidence_by_ids(chart_ids) if chart_ids else []
    for eid in ids:
        if not eid.startswith("ref-"):
            continue
        entry = drug_ref(eid) or metric_ref(eid)
        if entry:
            out.append(entry)
    return {"evidence": out}


TOOLS = {
    "get_patient_brief": get_patient_brief,
    "get_coverage": get_coverage,
    "get_metric_snapshots": get_metric_snapshots,
    "get_metric_series": get_metric_series,
    "get_related_metric_snapshots": get_related_metric_snapshots,
    "get_active_conditions": get_active_conditions,
    "get_medications_and_allergies": get_medications_and_allergies,
    "get_recent_plan_candidates": get_recent_plan_candidates,
    "get_followup_resolution": get_followup_resolution,
    "search_prior_notes": search_prior_notes,
    "get_note_evidence": get_note_evidence,
    "get_evidence_details": get_evidence_details,
}
