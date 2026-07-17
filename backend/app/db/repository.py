"""Patient-scoped repository.

Every read goes through ChartRepository, which binds a patient_id at
construction. Nothing above this layer ever writes its own WHERE clause,
so cross-patient leakage is structurally impossible.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
from app.timeutil import utc_iso


class PatientNotFoundError(Exception):
    pass


class ChartRepository:
    def __init__(self, session: Session, patient_id: str):
        self.session = session
        self.patient_id = patient_id

    def _scoped(self, model, *order_by, limit: int | None = None):
        stmt = select(model).where(model.patient_id == self.patient_id)
        if order_by:
            stmt = stmt.order_by(*order_by)
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def patient(self) -> Patient:
        p = self.session.scalar(select(Patient).where(Patient.patient_id == self.patient_id))
        if p is None:
            raise PatientNotFoundError(self.patient_id)
        return p

    def encounters(self, limit: int = 10) -> list[Encounter]:
        return self._scoped(Encounter, Encounter.clinical_time.desc(), limit=limit)

    def active_conditions(self) -> list[Condition]:
        return [
            c
            for c in self._scoped(Condition, Condition.clinical_time.desc())
            if c.clinical_status == "active"
        ]

    def allergies(self) -> list[Allergy]:
        return self._scoped(Allergy, Allergy.clinical_time.desc())

    def medications(self, active_only: bool = True) -> list[Medication]:
        meds = self._scoped(Medication, Medication.clinical_time.desc())
        return [m for m in meds if m.status == "active"] if active_only else meds

    def observations_for_metric(self, metric_code: str, limit: int = 24) -> list[Observation]:
        """Most recent `limit` observations, returned in chronological order."""
        stmt = (
            select(Observation)
            .where(
                Observation.patient_id == self.patient_id,
                Observation.metric_code == metric_code,
            )
            .order_by(Observation.clinical_time.desc())
            .limit(limit)
        )
        return list(reversed(list(self.session.scalars(stmt))))

    def distinct_metric_codes(self) -> list[str]:
        stmt = (
            select(Observation.metric_code, func.max(Observation.display))
            .where(Observation.patient_id == self.patient_id)
            .group_by(Observation.metric_code)
        )
        return [row[0] for row in self.session.execute(stmt)]

    def metric_snapshots(self, metric_codes: list[str] | None = None) -> list[MetricSnapshot]:
        snaps = self._scoped(MetricSnapshot)
        if metric_codes:
            snaps = [s for s in snaps if s.metric_code in metric_codes]
        return snaps

    def procedures(self, limit: int = 20) -> list[Procedure]:
        return self._scoped(Procedure, Procedure.clinical_time.desc(), limit=limit)

    def orders(self, limit: int = 20) -> list[Order]:
        return self._scoped(Order, Order.clinical_time.desc(), limit=limit)

    def care_plans(self, limit: int = 20) -> list[CarePlan]:
        return self._scoped(CarePlan, CarePlan.clinical_time.desc(), limit=limit)

    def notes(self, limit: int = 10, before: datetime | None = None) -> list[Note]:
        stmt = select(Note).where(Note.patient_id == self.patient_id)
        if before is not None:
            stmt = stmt.where(Note.clinical_time < before)
        stmt = stmt.order_by(Note.clinical_time.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def search_notes(self, query: str, limit: int = 3) -> list[tuple[Note, float]]:
        """PostgreSQL full-text search over this patient's notes."""
        ts_query = func.plainto_tsquery("english", query)
        rank = func.ts_rank(Note.search_vector, ts_query)
        stmt = (
            select(Note, rank)
            .where(Note.patient_id == self.patient_id, Note.search_vector.op("@@")(ts_query))
            .order_by(rank.desc())
            .limit(limit)
        )
        return [(row[0], float(row[1])) for row in self.session.execute(stmt)]

    def active_deferrals(self) -> list[Deferral]:
        return [
            d
            for d in self._scoped(Deferral, Deferral.clinical_time.desc())
            if d.status == "active"
        ]

    def evidence_by_ids(self, evidence_ids: list[str]) -> list[dict]:
        """Resolve source_resource_ids to bounded detail dicts, patient-scoped."""
        out: list[dict] = []
        models: list[tuple[Any, str]] = [
            (Condition, "condition"),
            (Allergy, "allergy"),
            (Medication, "medication"),
            (Observation, "observation"),
            (Procedure, "procedure"),
            (Order, "order"),
            (CarePlan, "care_plan"),
            (Note, "note"),
            (Deferral, "deferral"),
            (MetricSnapshot, "metric_snapshot"),
            (Encounter, "encounter"),
        ]
        for model, kind in models:
            stmt = select(model).where(
                model.patient_id == self.patient_id,
                model.source_resource_id.in_(evidence_ids),
            )
            for row in self.session.scalars(stmt):
                out.append(_evidence_detail(row, kind))
        return out


def _evidence_detail(row, kind: str) -> dict:
    detail: dict = {
        "evidence_id": row.source_resource_id,
        "kind": kind,
        "clinical_time": utc_iso(row.clinical_time),
        "source_system": row.source_system,
    }
    for attr in (
        "display",
        "name",
        "substance",
        "reaction",
        "severity",
        "dose",
        "frequency",
        "value",
        "unit",
        "metric_code",
        "status",
        "clinical_status",
        "description",
        "topic",
        "reason",
        "note_type",
        "order_type",
    ):
        v = getattr(row, attr, None)
        if v is not None:
            detail[attr] = v
    text = getattr(row, "text", None)
    if text:
        detail["snippet"] = text[:400]
    if kind == "deferral" and getattr(row, "deferred_until", None):
        detail["deferred_until"] = utc_iso(row.deferred_until)
    return detail
