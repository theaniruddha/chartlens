import pytest

from app.schemas.items import (
    DEFAULT_LIMITATIONS,
    ForbiddenWordingError,
    ReviewItem,
    validate_item,
)


def _item(**overrides) -> ReviewItem:
    base = dict(
        item_id="card-x",
        category="trend",
        title="A1c trend in available records",
        message="Available records show a change. Consider reviewing this trend.",
        confidence="high",
        evidence_ids=["p03-snap-hba1c"],
        source_dates=["2026-07-08"],
        limitations=DEFAULT_LIMITATIONS,
    )
    base.update(overrides)
    return ReviewItem(**base)


def test_valid_item_passes():
    validate_item(_item())


@pytest.mark.parametrize(
    "bad",
    [
        "This suggests a diagnosis of diabetes.",
        "Consider prescribing insulin.",
        "This is urgent.",
        "Critical value detected.",
        "Consider ordering a lipid panel.",
        "Recommend treatment with metformin.",
        "Please contact the patient today.",
    ],
)
def test_forbidden_wording_rejected(bad):
    with pytest.raises(ForbiddenWordingError):
        validate_item(_item(message=bad))


def test_missing_evidence_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _item(evidence_ids=[])


def test_unknown_category_rejected():
    with pytest.raises(ValueError):
        validate_item(_item(category="nonsense"))
