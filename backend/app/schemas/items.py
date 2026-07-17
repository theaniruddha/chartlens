"""Shared output item shape for Note Review cards and Investigator review items,
plus the validator that gates every emitted item."""

import re

from pydantic import BaseModel, Field

CATEGORIES = [
    "medication_mismatch",
    "allergy_conflict",
    "chart_value_mismatch",
    "coverage_gap",
    "unresolved_plan",
    "trend",
    "dual_trend",
    "deferred_topic",
    "symptom_followup",
    "indication_mismatch",
]

# Scanned over generated title/message only (never over quoted evidence,
# which lives in the evidence drawer).
_FORBIDDEN = re.compile(
    r"\b(diagnos\w*|prescrib\w*|urgent\w*|critical\w*|order(?:s|ed|ing)?|"
    r"treat(?:ment)?|contact (?:the )?patient|call (?:the )?patient)\b",
    re.IGNORECASE,
)


class ReviewItem(BaseModel):
    item_id: str
    category: str
    title: str
    message: str
    confidence: str = Field(pattern="^(high|medium|low)$")
    evidence_ids: list[str] = Field(min_length=1)
    source_dates: list[str] = Field(default_factory=list)
    limitations: str
    deferral_state: str | None = None


class ForbiddenWordingError(ValueError):
    pass


def contains_forbidden_wording(text: str) -> bool:
    return _FORBIDDEN.search(text) is not None


def validate_item(item: ReviewItem) -> ReviewItem:
    for field_name in ("title", "message"):
        text = getattr(item, field_name)
        m = _FORBIDDEN.search(text)
        if m:
            raise ForbiddenWordingError(
                f"forbidden wording {m.group(0)!r} in {field_name}: {text!r}"
            )
    if item.category not in CATEGORIES:
        raise ValueError(f"unknown category {item.category}")
    if not item.evidence_ids:
        raise ValueError("item missing evidence_ids")
    return item


DEFAULT_LIMITATIONS = (
    "Based only on connected synthetic records; the draft note was compared as text. "
    "Absence of a record means it was not found in connected records, "
    "not that it did not happen."
)
