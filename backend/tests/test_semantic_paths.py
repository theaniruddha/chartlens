"""Model-dependent paths, exercised with fake providers (no network)."""

from app.investigator.runner import run_investigation
from app.note_review.engine import review_note


class YesProvider:
    name = "fake_yes"

    def complete_json(self, system: str, user: str) -> dict:
        return {"answer": "yes", "rationale": "records show movement"}


class LinkingProvider:
    name = "fake_linker"

    def complete_json(self, system: str, user: str) -> dict:
        return {
            "links": [
                {
                    "note": "Available records show these metrics moving together.",
                    "evidence_ids": ["p05-snap-hba1c", "p05-snap-weight"],
                },
                {"note": "Hallucinated reference.", "evidence_ids": ["not-a-real-id"]},
            ]
        }


def test_stable_wording_vs_rising_trend_flagged_when_model_confirms(session):
    # p03's chart shows a rising A1c; a draft claiming "A1c stable" is an
    # ambiguous semantic conflict that goes to the model.
    note = "Assessment: A1c stable on current therapy.\nPlan:\n- Recheck A1c in 3 months."
    result = review_note(session, "p03", note, YesProvider())
    categories = [c["category"] for c in result["cards"]]
    assert "chart_value_mismatch" in categories
    card = next(c for c in result["cards"] if c["category"] == "chart_value_mismatch")
    assert card["confidence"] == "medium"
    assert card["evidence_ids"] == ["p03-snap-hba1c"]


def test_stable_wording_not_flagged_with_mock(session):
    from app.providers.gateway import MockProvider

    note = "Assessment: A1c stable on current therapy.\nPlan:\n- Recheck A1c in 3 months."
    result = review_note(session, "p03", note, MockProvider())
    assert all(c["category"] != "chart_value_mismatch" for c in result["cards"])


def test_signal_synthesis_evidence_gated(session, fixture_data):
    result = run_investigation(
        session, "p05", fixture_data["p05"]["current_note"], provider=LinkingProvider()
    )
    synth = result["signal_synthesis"]
    assert synth is not None
    assert len(synth["links"]) == 1  # hallucinated-evidence link dropped
    link = synth["links"][0]
    assert set(link["evidence_ids"]) == {"p05-snap-hba1c", "p05-snap-weight"}


def test_signal_synthesis_absent_with_mock(session, fixture_data):
    result = run_investigation(session, "p05", fixture_data["p05"]["current_note"])
    assert result["signal_synthesis"] is None
