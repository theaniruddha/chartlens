from datetime import datetime

from sqlalchemy import Computed, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SourcedClinicalMixin

# Controlled vocabulary for deferral/plan topics. Free text is never used for
# suppression matching.
TOPIC_VOCABULARY = [
    "colonoscopy",
    "mammogram",
    "a1c_followup",
    "lipid_followup",
    "bp_followup",
    "renal_followup",
    "imaging_followup",
    "medication_review",
    "vaccination",
    "weight_management",
    "other",
]


class Note(Base, SourcedClinicalMixin):
    __tablename__ = "notes"

    note_type: Mapped[str] = mapped_column(String(64), default="progress")
    text: Mapped[str] = mapped_column(Text)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )

    __table_args__ = (Index("ix_notes_search_vector", "search_vector", postgresql_using="gin"),)


class Deferral(Base, SourcedClinicalMixin):
    __tablename__ = "deferrals"

    topic: Mapped[str] = mapped_column(String(64), index=True)  # from TOPIC_VOCABULARY
    reason: Mapped[str | None] = mapped_column(Text)
    deferred_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_note_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="active")
