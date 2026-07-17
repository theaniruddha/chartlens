from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SourcedClinicalMixin


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mrn: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    birth_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sex: Mapped[str | None] = mapped_column(String(16))
    source_system: Mapped[str] = mapped_column(String(32), default="fixture")


class Encounter(Base, SourcedClinicalMixin):
    __tablename__ = "encounters"

    encounter_type: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)


class Condition(Base, SourcedClinicalMixin):
    __tablename__ = "conditions"

    code: Mapped[str | None] = mapped_column(String(32))
    display: Mapped[str] = mapped_column(String(256))
    clinical_status: Mapped[str] = mapped_column(String(32), default="active")


class Allergy(Base, SourcedClinicalMixin):
    __tablename__ = "allergies"

    substance: Mapped[str] = mapped_column(String(128))
    reaction: Mapped[str | None] = mapped_column(String(256))
    severity: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="active")


class Medication(Base, SourcedClinicalMixin):
    __tablename__ = "medications"

    name: Mapped[str] = mapped_column(String(128))
    dose: Mapped[str | None] = mapped_column(String(64))
    route: Mapped[str | None] = mapped_column(String(32))
    frequency: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="active")


class Observation(Base, SourcedClinicalMixin):
    __tablename__ = "observations"

    metric_code: Mapped[str] = mapped_column(String(64), index=True)
    display: Mapped[str] = mapped_column(String(128))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    value_text: Mapped[str | None] = mapped_column(String(256))


class Procedure(Base, SourcedClinicalMixin):
    __tablename__ = "procedures"

    code: Mapped[str | None] = mapped_column(String(32))
    display: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="completed")


class Order(Base, SourcedClinicalMixin):
    __tablename__ = "orders"

    order_type: Mapped[str] = mapped_column(String(64))
    display: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="active")


class CarePlan(Base, SourcedClinicalMixin):
    __tablename__ = "care_plans"

    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="active")
    topic: Mapped[str | None] = mapped_column(String(64), index=True)


class MetricSnapshot(Base, SourcedClinicalMixin):
    """Materialized per-metric summary, populated at fixture-load time."""

    __tablename__ = "metric_snapshots"

    metric_code: Mapped[str] = mapped_column(String(64), index=True)
    display: Mapped[str] = mapped_column(String(128))
    latest_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    latest_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_value: Mapped[float | None] = mapped_column(Float)
    delta: Mapped[float | None] = mapped_column(Float)
    slope_per_month: Mapped[float | None] = mapped_column(Float)
    n_points: Mapped[int | None] = mapped_column()
