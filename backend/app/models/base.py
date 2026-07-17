from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourcedClinicalMixin:
    """Columns shared by every clinical-fact table.

    `source_resource_id` is the stable, fixture/import-assigned ID and doubles
    as the user-facing evidence ID. It must be unique per table.
    """

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("patients.patient_id"), index=True
    )
    encounter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    clinical_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_system: Mapped[str] = mapped_column(String(32), default="fixture")
    source_resource_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    raw_source_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class TextNoteMixin:
    text: Mapped[str] = mapped_column(Text, default="")
