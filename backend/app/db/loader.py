"""Idempotent fixture loader: wipes and reloads all synthetic patients,
then materializes metric_snapshots from observations."""

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.analytics.trends import SeriesPoint, classify_trend
from app.models import (
    Allergy,
    CarePlan,
    Condition,
    Deferral,
    Encounter,
    Medication,
    MetricSnapshot,
    Note,
    Observation,
    Order,
    Patient,
    Procedure,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "patients"

_SECTION_MODELS = {
    "encounters": Encounter,
    "conditions": Condition,
    "allergies": Allergy,
    "medications": Medication,
    "observations": Observation,
    "procedures": Procedure,
    "orders": Order,
    "care_plans": CarePlan,
    "notes": Note,
    "deferrals": Deferral,
}

_DT_FIELDS = ("clinical_time", "recorded_time", "deferred_until", "birth_date")


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_all_fixtures(session: Session, fixtures_dir: Path = FIXTURES_DIR) -> list[str]:
    wipe(session)
    patient_ids = []
    for path in sorted(fixtures_dir.glob("*.json")):
        data = json.loads(path.read_text())
        patient_ids.append(load_fixture(session, data))
    session.flush()
    for pid in patient_ids:
        materialize_snapshots(session, pid)
    session.flush()
    return patient_ids


def wipe(session: Session) -> None:
    for model in [*(reversed(list(_SECTION_MODELS.values()))), MetricSnapshot, Patient]:
        session.execute(delete(model))


def load_fixture(session: Session, data: dict) -> str:
    p = data["patient"]
    session.add(
        Patient(
            patient_id=p["patient_id"],
            mrn=p.get("mrn"),
            name=p["name"],
            birth_date=_parse_dt(p.get("birth_date")),
            sex=p.get("sex"),
        )
    )
    session.flush()
    for section, model in _SECTION_MODELS.items():
        for row in data.get(section, []):
            kwargs = dict(row)
            for f in _DT_FIELDS:
                if f in kwargs:
                    kwargs[f] = _parse_dt(kwargs[f])
            kwargs.setdefault("patient_id", p["patient_id"])
            kwargs.setdefault("recorded_time", kwargs.get("clinical_time"))
            session.add(model(**kwargs))
    return p["patient_id"]


def materialize_snapshots(session: Session, patient_id: str) -> None:
    from app.db.repository import ChartRepository

    repo = ChartRepository(session, patient_id)
    for code in repo.distinct_metric_codes():
        obs = repo.observations_for_metric(code)
        pts = [
            SeriesPoint(time=o.clinical_time, value=o.value)
            for o in obs
            if o.value is not None and o.clinical_time is not None
        ]
        trend = classify_trend(code, pts)
        session.add(
            MetricSnapshot(
                patient_id=patient_id,
                source_resource_id=f"{patient_id}-snap-{code}",
                source_system="derived",
                metric_code=code,
                display=obs[-1].display if obs else code,
                latest_value=trend.latest_value,
                unit=obs[-1].unit if obs else None,
                latest_time=trend.latest_time,
                previous_value=trend.previous_value,
                delta=trend.delta,
                slope_per_month=trend.slope_per_month,
                n_points=trend.n_points,
                clinical_time=trend.latest_time,
                recorded_time=trend.latest_time,
            )
        )
