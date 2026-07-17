"""Live model-dependent paths against the real Ollama Cloud provider.

These hit the network with gemma4:31b. They skip automatically when no
OLLAMA_CLOUD_API_KEY is configured, so offline/CI runs stay green.
Run just these with:  uv run pytest tests/test_live_llm.py -v
"""

import pytest

from app.config import Settings
from app.investigator.runner import run_investigation
from app.note_review.engine import review_note
from app.providers.gateway import OpenAICompatProvider, link_signals, semantic_verify
from app.schemas.items import contains_forbidden_wording

pytestmark = pytest.mark.live

LIVE_MODEL = "gemma4:31b"


@pytest.fixture(scope="module")
def live_provider():
    s = Settings()
    if not s.ollama_cloud_api_key:
        pytest.skip("no OLLAMA_CLOUD_API_KEY configured")
    return OpenAICompatProvider(
        "ollama_cloud", f"{s.ollama_base_url}/v1", LIVE_MODEL, s.ollama_cloud_api_key
    )


def test_live_verify_flags_contradiction(live_provider):
    out = semantic_verify(
        live_provider,
        question=(
            "The draft note describes Hemoglobin A1c as 'stable'. "
            "Do the records contradict that wording?"
        ),
        context={
            "metric": "Hemoglobin A1c",
            "latest_value": 8.0,
            "delta": 0.8,
            "slope_per_month": 0.2,
            "n_points": 3,
        },
    )
    assert out["answer"] == "yes", out
    assert out["rationale"]


def test_live_verify_accepts_consistent_wording(live_provider):
    out = semantic_verify(
        live_provider,
        question=(
            "The draft note describes systolic blood pressure as 'stable'. "
            "Do the records contradict that wording?"
        ),
        context={
            "metric": "Systolic blood pressure",
            "latest_value": 126.0,
            "delta": -2.0,
            "slope_per_month": 0.05,
            "n_points": 3,
        },
    )
    # A clearly flat series must never be flagged as contradicting "stable".
    assert out["answer"] != "yes", out


def test_live_link_signals_bounded_and_clean(live_provider):
    out = link_signals(
        live_provider,
        signals=[
            {"evidence_id": "snap-hba1c", "metric_code": "hba1c", "slope_per_month": 0.2,
             "delta": 0.8, "n_points": 3, "unit": "%"},
            {"evidence_id": "snap-weight", "metric_code": "weight", "slope_per_month": 1.0,
             "delta": 4.0, "n_points": 3, "unit": "kg"},
            {"evidence_id": "snap-sbp", "metric_code": "sbp", "slope_per_month": 0.05,
             "delta": -2.0, "n_points": 3, "unit": "mmHg"},
        ],
        findings=[
            {"category": "dual_trend", "metric_code": "hba1c", "topic": None,
             "evidence_ids": ["snap-hba1c", "snap-weight"]}
        ],
    )
    assert out is not None, "expected at least one clean link from a clear dual-trend"
    assert 1 <= len(out["links"]) <= 3
    known = {"snap-hba1c", "snap-weight", "snap-sbp"}
    for link in out["links"]:
        assert not contains_forbidden_wording(link["note"])
        assert set(link["evidence_ids"]) <= known


def test_live_note_review_stable_wording_vs_rising_a1c(session, live_provider):
    note = "Assessment: A1c stable on current therapy.\nPlan:\n- Recheck A1c in 3 months."
    result = review_note(session, "p03", note, live_provider)
    categories = [c["category"] for c in result["cards"]]
    assert "chart_value_mismatch" in categories, result["cards"]
    card = next(c for c in result["cards"] if c["category"] == "chart_value_mismatch")
    assert card["confidence"] == "medium"
    assert card["evidence_ids"] == ["p03-snap-hba1c"]


def test_live_investigation_synthesis_evidence_gated(session, fixture_data, live_provider):
    """Whatever the live model emits, nothing unsafe or unsourced may escape.

    A `None` synthesis is a legitimate outcome: the model occasionally phrases
    a link with forbidden wording (e.g. "diagnosis of ..."), and the validator
    then drops it. The gate holding is the property under test; the happy path
    is covered deterministically in test_semantic_paths.py.
    """
    result = run_investigation(
        session, "p05", fixture_data["p05"]["current_note"], provider=live_provider
    )
    assert [i["category"] for i in result["items"]] == ["dual_trend"]
    synth = result["signal_synthesis"]
    if synth is None:
        return
    assert synth["provider"] == "ollama_cloud"
    assert synth["links"], "a present synthesis must carry at least one link"
    for link in synth["links"]:
        assert not contains_forbidden_wording(link["note"])
        assert link["evidence_ids"], link
        # every cited id must belong to this patient's records
        assert all(e.startswith("p05-") for e in link["evidence_ids"])


def test_live_provider_failure_degrades_safely():
    bad = OpenAICompatProvider("ollama_cloud", "https://ollama.com/v1", LIVE_MODEL, "invalid-key")
    out = semantic_verify(bad, "any question", {})
    assert out["answer"] == "unsure"
    assert "provider error" in out["rationale"]
