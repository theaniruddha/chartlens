from app.db.repository import ChartRepository
from app.lint import fast_lint, lint_note, quote_key, record_decision


class FakeLintModel:
    name = "fake_lint"

    def __init__(self, response: dict):
        self.response = response

    def complete_json(self, system: str, user: str) -> dict:
        return self.response


def _spans_valid(text: str, annotations: list[dict]) -> bool:
    return all(text[a["start"] : a["end"]] == a["quote"] for a in annotations)


def test_fast_lint_med_and_value_annotations(session):
    repo = ChartRepository(session, "p01")  # metformin stopped on chart
    text = (
        "Subjective: Feels well.\n"
        "Medications: Continue metformin 500 mg twice daily.\n"
        "BP today 178/110.\n"
        "Plan:\n- Recheck A1c in 3 months."
    )
    annotations = fast_lint(session, repo, text)
    cats = {a["category"] for a in annotations}
    assert "medication_mismatch" in cats
    assert "value_range" in cats  # 178 above the cited reference range
    assert _spans_valid(text, annotations)
    med = next(a for a in annotations if a["category"] == "medication_mismatch")
    assert text[med["start"] : med["end"]] == "metformin"
    assert med["evidence_ids"] == ["p01-med-1"]
    rng = next(a for a in annotations if a["category"] == "value_range")
    assert rng["evidence_ids"] == ["ref-metric-sbp"]
    # compound BP span must not produce duplicate annotations per category
    spans = [(a["category"], a["start"], a["end"]) for a in annotations]
    assert len(spans) == len(set(spans))


def test_fast_lint_symptom_and_silence(session):
    repo = ChartRepository(session, "p10")
    annotations = fast_lint(session, repo, "Subjective: tooth pain for two weeks.")
    assert [a["category"] for a in annotations] == ["symptom_followup"]
    # addressed in plan -> silent
    annotations = fast_lint(
        session, repo, "Subjective: tooth pain.\nPlan:\n- Refer for tooth pain evaluation."
    )
    assert annotations == []


def test_resolved_symptom_is_not_flagged(session):
    repo = ChartRepository(session, "p10")
    # bare mention -> flagged
    flagged = fast_lint(session, repo, "Subjective: chest pain today.")
    assert any(a["category"] == "symptom_followup" for a in flagged)
    # resolved/re-attributed in the same sentence -> silent
    for note in (
        "Follow up on chest pain and it is not there anymore. Was heartburn.",
        "Chest pain has resolved.",
        "Patient denies chest pain.",
        "Chest pain no longer present.",
    ):
        anns = fast_lint(session, repo, note)
        assert not any(a["category"] == "symptom_followup" for a in anns), note


def test_model_new_dx_skips_differential_mentions(session):
    repo = ChartRepository(session, "p10")
    text = "Reports chest pain. Was heartburn."
    fake = FakeLintModel(
        {
            "complaints": [],
            "diagnoses": [{"quote": "heartburn", "name": "Heartburn"}],
            "ambiguities": [],
        }
    )
    result = lint_note(session, repo, text, mode="full", provider=fake)
    assert not any(a["category"] == "new_dx" for a in result["annotations"])


def test_normal_values_not_flagged(session):
    repo = ChartRepository(session, "p04")
    annotations = fast_lint(session, repo, "BP today 124/78. Continue lisinopril 10 mg daily.")
    assert all(a["category"] != "value_range" for a in annotations)


def test_model_lint_quote_anchoring_and_gating(session):
    repo = ChartRepository(session, "p04")  # active: essential hypertension
    text = (
        "Patient reports less sleep lately.\n"
        "Assessment: new atrial fibrillation.\nPlan:\n- Follow up."
    )
    fake = FakeLintModel(
        {
            "complaints": [
                {
                    "quote": "less sleep lately",
                    "label": "reduced sleep",
                    "addressed_in_plan": False,
                },
                {"quote": "NOT IN THE NOTE AT ALL", "label": "ghost", "addressed_in_plan": False},
            ],
            "diagnoses": [
                {"quote": "new atrial fibrillation", "name": "Atrial fibrillation"},
                {"quote": "less sleep", "name": "Essential hypertension"},  # already listed
            ],
            "ambiguities": [{"quote": "Follow up.", "issue": "Consider ordering tests."}],
        }
    )
    result = lint_note(session, repo, text, mode="full", provider=fake)
    cats = [a["category"] for a in result["annotations"]]
    assert "unresolved_complaint" in cats
    assert "new_dx" in cats
    # unanchorable quote dropped, known condition dropped, forbidden wording dropped
    assert cats.count("new_dx") == 1
    assert "ambiguity" not in cats
    assert _spans_valid(text, result["annotations"])
    dx = next(a for a in result["annotations"] if a["category"] == "new_dx")
    assert dx["suggestion"] == "Atrial fibrillation"
    assert "add_to_problem_list" in dx["actions"]
    assert result["model"] == "fake_lint"


def test_full_mode_with_mock_is_deterministic_only(session):
    from app.providers.gateway import MockProvider

    repo = ChartRepository(session, "p10")
    result = lint_note(session, repo, "tooth pain again", mode="full", provider=MockProvider())
    assert result["model"] is None
    assert [a["category"] for a in result["annotations"]] == ["symptom_followup"]


def test_dismissal_memory_suppresses_repeat(session):
    repo = ChartRepository(session, "p10")
    text = "Subjective: tooth pain for two weeks."
    first = lint_note(session, repo, text, mode="fast")
    assert len(first["annotations"]) == 1
    ann = first["annotations"][0]
    record_decision(session, "p10", ann["category"], ann["quote"], "dismissed", text)
    second = lint_note(session, repo, text, mode="fast")
    assert second["annotations"] == []
    # accepted decisions do NOT suppress
    record_decision(session, "p10", "value_range", "BP 178/110", "accepted", text)
    assert quote_key("value_range", "BP 178/110") not in {
        quote_key(a["category"], a["quote"]) for a in second["annotations"]
    }


def test_lint_endpoint_and_problem_list_action(client):
    r = client.post(
        "/v1/patients/MRN-24001/notes/lint",
        json={"text": "Medications: Continue metformin 500 mg.", "mode": "fast"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "fast"
    assert any(a["category"] == "medication_mismatch" for a in body["annotations"])

    r = client.post(
        "/v1/patients/p04/problem-list", json={"display": "Atrial fibrillation"}
    )
    assert r.status_code == 200
    evidence_id = r.json()["evidence_id"]
    ctx = client.get("/v1/patients/p04/context").json()
    assert any(
        c["evidence_id"] == evidence_id and c["display"] == "Atrial fibrillation"
        for c in ctx["brief"]["active_conditions"]
    )

    r = client.post(
        "/v1/patients/p04/annotations/decision",
        json={"category": "new_dx", "quote": "new atrial fibrillation", "decision": "accepted"},
    )
    assert r.status_code == 200 and r.json()["recorded"]


def test_metric_reference_resolves_in_evidence_drawer(client):
    r = client.post(
        "/v1/patients/p04/evidence", json={"evidence_ids": ["ref-metric-sbp"]}
    )
    entry = r.json()["evidence"][0]
    assert entry["kind"] == "metric_reference"
    assert "90" in entry["typical_range"] and "140" in entry["typical_range"]
