"""Playground: inject synthetic historical observations for a patient to
simulate how the agent handles new information.

Rows are tagged source_system="playground" so they can be listed and cleared
without touching fixture or imported data. Series values may come from the
model (bounded: it returns numbers only — dates, IDs, and bounds are computed
here) or from a deterministic generator when no provider is configured.
"""

import json
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics.trends import SLOPE_THRESHOLDS, SeriesPoint, classify_trend
from app.db.repository import ChartRepository
from app.models import Allergy, Condition, MetricSnapshot, Note, Observation
from app.timeutil import utc_iso

MAX_BATCH = 24
MAX_GENERATED_POINTS = 12

METRIC_DEFAULTS: dict[str, dict] = {
    "hba1c": {"display": "Hemoglobin A1c", "unit": "%", "base": 6.0, "min": 3.5, "max": 15.0},
    "sbp": {
        "display": "Systolic blood pressure", "unit": "mmHg", "base": 122.0,
        "min": 70, "max": 250,
    },
    "dbp": {
        "display": "Diastolic blood pressure", "unit": "mmHg", "base": 78.0,
        "min": 40, "max": 150,
    },
    "weight": {"display": "Body weight", "unit": "kg", "base": 80.0, "min": 30, "max": 250},
    "ldl": {"display": "LDL cholesterol", "unit": "mg/dL", "base": 110.0, "min": 20, "max": 400},
    "egfr": {"display": "eGFR", "unit": "mL/min", "base": 90.0, "min": 5, "max": 140},
    "creatinine": {"display": "Creatinine", "unit": "mg/dL", "base": 1.0, "min": 0.2, "max": 12},
    "potassium": {"display": "Potassium", "unit": "mmol/L", "base": 4.2, "min": 2.0, "max": 8.0},
    "glucose": {"display": "Glucose", "unit": "mg/dL", "base": 100.0, "min": 30, "max": 600},
    "hemoglobin": {"display": "Hemoglobin", "unit": "g/dL", "base": 13.5, "min": 4, "max": 22},
}


def rebuild_snapshots(session: Session, patient_id: str) -> None:
    """Drop and re-materialize this patient's metric snapshots."""
    from app.db.loader import materialize_snapshots

    session.execute(delete(MetricSnapshot).where(MetricSnapshot.patient_id == patient_id))
    session.flush()
    materialize_snapshots(session, patient_id)
    session.flush()


def add_observations(session: Session, patient_id: str, observations: list[dict]) -> dict:
    inserted = []
    for obs in observations[:MAX_BATCH]:
        code = str(obs["metric_code"]).lower().strip()[:64]
        defaults = METRIC_DEFAULTS.get(code, {})
        clinical_time = obs.get("clinical_time")
        if isinstance(clinical_time, str):
            clinical_time = datetime.fromisoformat(clinical_time.replace("Z", "+00:00"))
        clinical_time = clinical_time or datetime.now(UTC)
        row = Observation(
            patient_id=patient_id,
            metric_code=code,
            display=obs.get("display") or defaults.get("display", code),
            value=float(obs["value"]),
            unit=obs.get("unit") or defaults.get("unit"),
            clinical_time=clinical_time,
            recorded_time=datetime.now(UTC),
            source_system="playground",
            source_resource_id=f"pg-{uuid.uuid4().hex[:12]}",
        )
        session.add(row)
        inserted.append(row)
    session.flush()
    rebuild_snapshots(session, patient_id)
    return {
        "inserted": [
            {
                "evidence_id": r.source_resource_id,
                "metric_code": r.metric_code,
                "value": r.value,
                "unit": r.unit,
                "clinical_time": utc_iso(r.clinical_time),
            }
            for r in inserted
        ],
        "snapshots": _snapshot_summaries(session, patient_id),
    }


def generate_series(
    provider: Any,
    metric_code: str,
    trend: str,
    n_points: int,
    months_back: int,
    start_value: float | None = None,
) -> tuple[list[float], str]:
    """Return (values, generator) — model-generated when a real provider is
    configured, deterministic otherwise. Values are validated and clamped;
    everything else (dates, IDs) is always computed locally."""
    n = max(2, min(n_points, MAX_GENERATED_POINTS))
    defaults = METRIC_DEFAULTS.get(metric_code, {"base": 100.0, "min": 0.0, "max": 10000.0})
    base = start_value if start_value is not None else defaults["base"]

    if provider is not None and getattr(provider, "name", "mock") != "mock":
        values = _model_series(provider, metric_code, trend, n, months_back, base, defaults)
        if values is not None:
            return values, provider.name
    return _deterministic_series(metric_code, trend, n, months_back, base), "deterministic"


def _model_series(
    provider: Any, metric_code: str, trend: str, n: int, months_back: int, base: float,
    defaults: dict,
) -> list[float] | None:
    threshold = SLOPE_THRESHOLDS.get(metric_code, 0.5)
    system = (
        "You generate SYNTHETIC lab series for a test sandbox. "
        f'Respond with JSON only: {{"values": [<{n} numbers>]}}. '
        "Values must be clinically plausible for the metric and follow the "
        "requested trend smoothly with small realistic variation."
    )
    user = json.dumps(
        {
            "metric": metric_code,
            "unit": defaults.get("unit"),
            "trend": trend,
            "n_points": n,
            "span_months": months_back,
            "start_around": base,
            "plausible_range": [defaults.get("min"), defaults.get("max")],
            "minimum_change_per_month_if_trending": round(2 * threshold, 3),
        }
    )
    result = provider.complete_json(system, user)
    values = result.get("values")
    if not isinstance(values, list) or len(values) != n:
        return None
    try:
        nums = [float(v) for v in values]
    except (TypeError, ValueError):
        return None
    lo, hi = defaults.get("min", -1e9), defaults.get("max", 1e9)
    if any(not math.isfinite(v) or v < lo or v > hi for v in nums):
        return None
    # The series must actually carry the requested signal, or the sandbox
    # can't demonstrate anything: reject sub-threshold "trends".
    overall_slope = (nums[-1] - nums[0]) / max(months_back, 1)
    if trend == "rising" and overall_slope <= threshold:
        return None
    if trend == "falling" and overall_slope >= -threshold:
        return None
    if trend == "stable" and abs(overall_slope) > threshold:
        return None
    return [round(v, 2) for v in nums]


def _deterministic_series(
    metric_code: str, trend: str, n: int, months_back: int, base: float
) -> list[float]:
    threshold = SLOPE_THRESHOLDS.get(metric_code, 0.5)
    slope = {"rising": 2.5 * threshold, "falling": -2.5 * threshold, "stable": 0.0}.get(trend, 0.0)
    defaults = METRIC_DEFAULTS.get(metric_code, {})
    lo, hi = defaults.get("min", -1e9), defaults.get("max", 1e9)
    step_months = months_back / max(n - 1, 1)
    values = []
    for i in range(n):
        jitter = 0.15 * threshold * math.sin(i * 2.1)
        v = base + slope * step_months * i + jitter
        values.append(round(min(max(v, lo), hi), 2))
    return values


def series_to_observations(
    values: list[float], metric_code: str, months_back: int
) -> list[dict]:
    n = len(values)
    now = datetime.now(UTC)
    step = timedelta(days=(months_back * 30.44) / max(n - 1, 1))
    first = now - step * (n - 1)
    return [
        {
            "metric_code": metric_code,
            "value": v,
            "clinical_time": (first + step * i).isoformat(),
        }
        for i, v in enumerate(values)
    ]


MAX_SCENARIO_OBS = 10
MAX_SCENARIO_CONDITIONS = 3
MAX_SCENARIO_ALLERGIES = 3


def scenario_from_text(provider: Any, description: str) -> dict | None:
    """One bounded model call: free-text scenario -> structured records.

    The model proposes metric values, condition names, and a short note; every
    field is validated against known metrics and plausible ranges here, and
    anything invalid is dropped. Returns None when nothing usable came back.
    """
    if provider is None or getattr(provider, "name", "mock") == "mock":
        return None
    system = (
        "You convert a clinician's SYNTHETIC test-scenario description into "
        "structured records for a sandbox. Respond with JSON only:\n"
        '{"observations": [{"metric_code": "<code>", "value": <number>, '
        '"months_ago": <0-36>}], '
        '"conditions": [{"display": "<condition name>", "status": "active"|"resolved"}], '
        '"allergies": [{"substance": "<substance>", "reaction": "<reaction or empty>"}], '
        '"note_text": "<short clinical note capturing symptoms/complaints, or empty>"}\n'
        f"Allowed metric_code values: {sorted(METRIC_DEFAULTS)}. "
        "Use realistic values (e.g. 'borderline high cholesterol' -> ldl around "
        "130-155). Put symptoms and complaints into note_text as plain "
        "sentences, not observations. Max "
        f"{MAX_SCENARIO_OBS} observations, {MAX_SCENARIO_CONDITIONS} conditions."
    )
    result = provider.complete_json(system, description[:2000])
    scenario: dict = {
        "observations": [], "conditions": [], "allergies": [], "note_text": ""
    }

    for obs in (result.get("observations") or [])[:MAX_SCENARIO_OBS]:
        if not isinstance(obs, dict):
            continue
        code = str(obs.get("metric_code", "")).lower().strip()
        defaults = METRIC_DEFAULTS.get(code)
        if defaults is None:
            continue
        try:
            value = float(obs.get("value"))  # type: ignore[arg-type]
            months_ago = float(obs.get("months_ago") or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or not defaults["min"] <= value <= defaults["max"]:
            continue
        months_ago = min(max(months_ago, 0.0), 36.0)
        scenario["observations"].append(
            {"metric_code": code, "value": round(value, 2), "months_ago": months_ago}
        )

    for cond in (result.get("conditions") or [])[:MAX_SCENARIO_CONDITIONS]:
        if not isinstance(cond, dict):
            continue
        display = str(cond.get("display", "")).strip()[:100]
        if len(display) < 3:
            continue
        status = "active" if str(cond.get("status", "active")) == "active" else "resolved"
        scenario["conditions"].append({"display": display, "status": status})

    for alg in (result.get("allergies") or [])[:MAX_SCENARIO_ALLERGIES]:
        if not isinstance(alg, dict):
            continue
        substance = str(alg.get("substance", "")).strip()[:100]
        if len(substance) < 3:
            continue
        reaction = str(alg.get("reaction") or "").strip()[:100] or None
        scenario["allergies"].append({"substance": substance, "reaction": reaction})

    note_text = str(result.get("note_text") or "").strip()[:2000]
    scenario["note_text"] = note_text

    if not (
        scenario["observations"]
        or scenario["conditions"]
        or scenario["allergies"]
        or note_text
    ):
        return None
    return scenario


def apply_scenario(session: Session, patient_id: str, scenario: dict) -> dict:
    now = datetime.now(UTC)
    obs_payload = [
        {
            "metric_code": o["metric_code"],
            "value": o["value"],
            "clinical_time": (now - timedelta(days=o["months_ago"] * 30.44)).isoformat(),
        }
        for o in scenario["observations"]
    ]
    inserted_conditions = []
    for cond in scenario["conditions"]:
        row = Condition(
            patient_id=patient_id,
            display=cond["display"],
            clinical_status=cond["status"],
            clinical_time=now,
            recorded_time=now,
            source_system="playground",
            source_resource_id=f"pgc-{uuid.uuid4().hex[:12]}",
        )
        session.add(row)
        inserted_conditions.append(
            {"evidence_id": row.source_resource_id, "display": row.display,
             "status": row.clinical_status}
        )
    inserted_allergies = []
    for alg in scenario.get("allergies", []):
        allergy_row = Allergy(
            patient_id=patient_id,
            substance=alg["substance"],
            reaction=alg["reaction"],
            status="active",
            clinical_time=now,
            recorded_time=now,
            source_system="playground",
            source_resource_id=f"pga-{uuid.uuid4().hex[:12]}",
        )
        session.add(allergy_row)
        inserted_allergies.append(
            {
                "evidence_id": allergy_row.source_resource_id,
                "substance": allergy_row.substance,
                "reaction": allergy_row.reaction,
            }
        )
    note_evidence_id = None
    if scenario["note_text"]:
        note = Note(
            patient_id=patient_id,
            note_type="progress",
            text=scenario["note_text"],
            clinical_time=now,
            recorded_time=now,
            source_system="playground",
            source_resource_id=f"pgn-{uuid.uuid4().hex[:12]}",
        )
        session.add(note)
        note_evidence_id = note.source_resource_id
    session.flush()
    result = (
        add_observations(session, patient_id, obs_payload)
        if obs_payload
        else {"inserted": [], "snapshots": _snapshot_summaries(session, patient_id)}
    )
    if not obs_payload:
        rebuild_snapshots(session, patient_id)
    result["conditions"] = inserted_conditions
    result["allergies"] = inserted_allergies
    result["note_evidence_id"] = note_evidence_id
    result["note_text"] = scenario["note_text"]
    return result


def list_playground(session: Session, patient_id: str) -> list[dict]:
    rows = session.scalars(
        select(Observation)
        .where(
            Observation.patient_id == patient_id,
            Observation.source_system == "playground",
        )
        .order_by(Observation.clinical_time.asc())
    )
    return [
        {
            "evidence_id": r.source_resource_id,
            "metric_code": r.metric_code,
            "display": r.display,
            "value": r.value,
            "unit": r.unit,
            "clinical_time": utc_iso(r.clinical_time),
        }
        for r in rows
    ]


def clear_playground(session: Session, patient_id: str) -> int:
    removed = 0
    for model in (Observation, Note, Condition, Allergy):
        result = session.execute(
            delete(model).where(
                model.patient_id == patient_id,
                model.source_system == "playground",
            )
        )
        removed += getattr(result, "rowcount", 0) or 0
    session.flush()
    rebuild_snapshots(session, patient_id)
    return removed


def _snapshot_summaries(session: Session, patient_id: str) -> list[dict]:
    repo = ChartRepository(session, patient_id)
    out = []
    for snap in repo.metric_snapshots():
        obs = repo.observations_for_metric(snap.metric_code)
        pts = [
            SeriesPoint(time=o.clinical_time, value=o.value)
            for o in obs
            if o.value is not None and o.clinical_time is not None
        ]
        trend = classify_trend(snap.metric_code, pts)
        out.append(
            {
                "metric_code": snap.metric_code,
                "display": snap.display,
                "latest_value": snap.latest_value,
                "slope_per_month": snap.slope_per_month,
                "n_points": snap.n_points,
                "direction": trend.direction,
            }
        )
    return out
