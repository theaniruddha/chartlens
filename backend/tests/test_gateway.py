from app.config import Settings
from app.providers.gateway import (
    MockProvider,
    _parse_json_object,
    build_provider,
    link_signals,
    semantic_verify,
)


class FakeProvider:
    name = "fake"

    def __init__(self, response: dict):
        self.response = response

    def complete_json(self, system: str, user: str) -> dict:
        return self.response


def test_parse_json_object_plain():
    assert _parse_json_object('{"answer": "yes"}') == {"answer": "yes"}


def test_parse_json_object_wrapped_in_prose():
    out = _parse_json_object('Sure! Here it is: {"answer": "no", "rationale": "x"} hope it helps')
    assert out["answer"] == "no"


def test_parse_json_object_garbage_degrades_to_unsure():
    assert _parse_json_object("not json at all")["answer"] == "unsure"


def test_build_provider_defaults_to_mock():
    s = Settings(llm_provider="groq", groq_api_key="")  # no key -> mock
    assert build_provider(s).name == "mock"
    s = Settings(llm_provider="mock")
    assert build_provider(s).name == "mock"


def test_build_provider_ollama_cloud():
    s = Settings(llm_provider="ollama_cloud", ollama_cloud_api_key="k", ollama_model="gemma4:31b")
    p = build_provider(s)
    assert p.name == "ollama_cloud"
    assert p.model == "gemma4:31b"  # type: ignore[attr-defined]
    assert p.base_url.startswith("https://ollama.com")  # type: ignore[attr-defined]


def test_semantic_verify_normalizes_bad_answers():
    out = semantic_verify(FakeProvider({"answer": "MAYBE?"}), "q", {})
    assert out["answer"] == "unsure"
    out = semantic_verify(MockProvider(), "q", {})
    assert out["answer"] == "unsure"


def test_link_signals_gates_forbidden_wording():
    bad = FakeProvider(
        {"links": [{"note": "Order an urgent test now.", "evidence_ids": ["snap-1"]}]}
    )
    signals = [{"evidence_id": "snap-1", "metric_code": "hba1c"}]
    assert link_signals(bad, signals, []) is None


def test_link_signals_accepts_clean_links():
    good = FakeProvider(
        {
            "links": [
                {
                    "note": "Available records show weight and A1c moving together.",
                    "evidence_ids": ["snap-1", "snap-2"],
                }
            ]
        }
    )
    signals = [
        {"evidence_id": "snap-1", "metric_code": "hba1c"},
        {"evidence_id": "snap-2", "metric_code": "weight"},
    ]
    out = link_signals(good, signals, [])
    assert out is not None and len(out["links"]) == 1


def test_link_signals_drops_unknown_evidence():
    fabricating = FakeProvider(
        {"links": [{"note": "Available records show a pattern.", "evidence_ids": ["made-up"]}]}
    )
    signals = [{"evidence_id": "snap-1", "metric_code": "hba1c"}]
    assert link_signals(fabricating, signals, []) is None


def test_link_signals_malformed_output():
    assert link_signals(FakeProvider({"links": "nope"}), [], []) is None
    assert link_signals(FakeProvider({}), [], []) is None
