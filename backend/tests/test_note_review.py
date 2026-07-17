from datetime import UTC, datetime

import pytest

from app.db.loader import load_fixture, materialize_snapshots
from app.note_review.engine import review_note
from app.providers.gateway import MockProvider

PATIENT_IDS = [f"p{i:02d}" for i in range(1, 11)]


@pytest.mark.parametrize("pid", PATIENT_IDS)
def test_fixture_expectations(session, fixture_data, pid):
    data = fixture_data[pid]
    result = review_note(session, pid, data["current_note"], MockProvider())
    got = sorted(c["category"] for c in result["cards"])
    assert got == sorted(data["expected"]["note_review"]), f"{pid}: {result['cards']}"


@pytest.mark.parametrize("pid", PATIENT_IDS)
def test_every_card_has_evidence_and_limitations(session, fixture_data, pid):
    data = fixture_data[pid]
    result = review_note(session, pid, data["current_note"], MockProvider())
    for card in result["cards"]:
        assert card["evidence_ids"], card
        assert card["limitations"], card
        assert card["confidence"] in ("high", "medium", "low")
    assert len(result["cards"]) <= 3


def test_deferral_suppresses_unresolved_plan(session, fixture_data):
    # p08 has an unresolved colonoscopy plan AND an active deferral -> no card.
    data = fixture_data["p08"]
    result = review_note(session, "p08", data["current_note"], MockProvider())
    assert result["cards"] == []


def test_expired_deferral_does_not_suppress(session):
    expired = {
        "patient": {"patient_id": "t-exp", "name": "Expired Deferral (synthetic)"},
        "notes": [
            {
                "source_resource_id": "t-exp-note-1",
                "note_type": "progress",
                "clinical_time": "2025-06-01T10:00:00Z",
                "text": "Plan:\n- Schedule colonoscopy for screening.",
            }
        ],
        "deferrals": [
            {
                "source_resource_id": "t-exp-def-1",
                "topic": "colonoscopy",
                "deferred_until": "2025-12-01T00:00:00Z",
                "status": "active",
                "clinical_time": "2025-06-01T10:00:00Z",
            }
        ],
    }
    load_fixture(session, expired)
    session.flush()
    materialize_snapshots(session, "t-exp")
    result = review_note(
        session,
        "t-exp",
        "Subjective: routine visit.\nPlan:\n- Follow up in 1 year.",
        MockProvider(),
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )
    assert [c["category"] for c in result["cards"]] == ["unresolved_plan"]


def test_unknown_patient_raises(session):
    from app.db.repository import PatientNotFoundError

    with pytest.raises(PatientNotFoundError):
        review_note(session, "nope", "text", MockProvider())


def test_draft_note_deferral_suppresses_unresolved_plan(session):
    # p07 has an unresolved colonoscopy plan; a draft that documents the
    # deferral itself should not get an unresolved_plan card for it.
    note = (
        "Subjective: Feels well.\n"
        "Patient declines colonoscopy at this time; defer discussion for 6 months.\n"
        "Plan:\n- Recheck CBC in 3 months."
    )
    result = review_note(session, "p07", note, MockProvider())
    assert all(c["category"] != "unresolved_plan" for c in result["cards"])


def test_source_dates_are_utc_exact(session, fixture_data):
    # Regression: tz-local truncation used to shift 2026-05-20 to 2026-05-19.
    result = review_note(session, "p01", fixture_data["p01"]["current_note"], MockProvider())
    card = result["cards"][0]
    assert card["source_dates"] == ["2026-05-20"]
    assert "2026-05-20" in card["message"]


def test_allergy_conflict_matches_by_drug_class(session):
    from app.db.loader import load_fixture
    from app.playground import rebuild_snapshots

    load_fixture(
        session,
        {
            "patient": {"patient_id": "t-sulfa", "name": "Sulfa Allergy (synthetic)"},
            "encounters": [
                {"source_resource_id": "t-sulfa-enc-1", "clinical_time": "2026-07-01T10:00:00Z"}
            ],
            "allergies": [
                {
                    "source_resource_id": "t-sulfa-alg-1",
                    "substance": "sulfa drugs",
                    "reaction": "rash",
                    "status": "active",
                    "clinical_time": "2020-01-01T00:00:00Z",
                }
            ],
        },
    )
    session.flush()
    rebuild_snapshots(session, "t-sulfa")
    result = review_note(
        session, "t-sulfa", "Asked to take septra medicine for sleep.", MockProvider()
    )
    # both the charted allergy and the stated purpose are wrong here
    categories = [c["category"] for c in result["cards"]]
    assert categories == ["allergy_conflict", "indication_mismatch"]
    card = result["cards"][0]
    assert card["evidence_ids"] == ["t-sulfa-alg-1"]
    assert "sulfa" in card["message"]


def test_unrelated_antibiotic_not_flagged_by_penicillin_allergy(session):
    # p02 has a penicillin allergy; azithromycin shares only the generic
    # "antibiotic" class and must not conflict.
    result = review_note(
        session, "p02", "Plan:\n- Start azithromycin 250 mg.", MockProvider()
    )
    assert all(c["category"] != "allergy_conflict" for c in result["cards"])


def test_penicillin_allergy_still_flags_amoxicillin(session):
    result = review_note(
        session, "p02", "Plan:\n- Start amoxicillin 500 mg.", MockProvider()
    )
    assert [c["category"] for c in result["cards"]] == ["allergy_conflict"]


def test_indication_mismatch_flags_wrong_stated_purpose(session):
    result = review_note(
        session,
        "p09",
        "Subjective: trouble sleeping.\nAsked to take septra medicine for sleep.",
        MockProvider(),
    )
    assert [c["category"] for c in result["cards"]] == ["indication_mismatch"]
    card = result["cards"][0]
    assert card["confidence"] == "medium"
    assert card["evidence_ids"] == ["ref-drug-sulfamethoxazole-trimethoprim"]
    assert "sleep" in card["message"] and "infection" in card["message"]


def test_indication_match_is_silent(session):
    # right drug for the stated purpose -> nothing to say
    for note in (
        "Asked to take septra for a urinary tract infection.",
        "Take zolpidem for sleep.",
        "Continue losartan for blood pressure.",
    ):
        result = review_note(session, "p09", note, MockProvider())
        assert all(c["category"] != "indication_mismatch" for c in result["cards"]), note


def test_indication_silent_when_purpose_or_drug_unknown(session):
    # duration is not a purpose; unknown drugs have no reference entry
    for note in (
        "Plan:\n- Start amoxicillin 500 mg three times daily for 10 days.",
        "Plan:\n- Start obscuramycin for sleep.",
        "Plan:\n- Start metformin 500 mg twice daily.",
    ):
        result = review_note(session, "p09", note, MockProvider())
        assert all(c["category"] != "indication_mismatch" for c in result["cards"]), note


def test_indication_evidence_resolves_to_reference_entry(session):
    from app.db.repository import ChartRepository
    from app.tools.semantic_tools import get_evidence_details

    repo = ChartRepository(session, "p09")
    out = get_evidence_details(repo, ["ref-drug-sulfamethoxazole-trimethoprim"])
    assert len(out["evidence"]) == 1
    entry = out["evidence"][0]
    assert entry["kind"] == "drug_reference"
    assert entry["typical_use"] == "infection"
    assert "septra" in entry["also_known_as"]
    assert entry["source_system"] == "chartlens_drug_reference"


def test_unknown_reference_id_resolves_to_nothing(session):
    from app.db.repository import ChartRepository
    from app.tools.semantic_tools import get_evidence_details

    repo = ChartRepository(session, "p09")
    assert get_evidence_details(repo, ["ref-drug-not-a-drug"])["evidence"] == []
