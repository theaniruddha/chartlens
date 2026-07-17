from app.playground import (
    add_observations,
    clear_playground,
    generate_series,
    list_playground,
    series_to_observations,
)


class SeriesProvider:
    name = "fake_series"

    def complete_json(self, system: str, user: str) -> dict:
        return {"values": [6.0, 6.8, 7.6, 8.4]}


class GarbageProvider:
    name = "fake_garbage"

    def complete_json(self, system: str, user: str) -> dict:
        return {"values": ["a lot", None, 1e12, -5]}


def test_generate_series_deterministic_by_default():
    values, generator = generate_series(None, "hba1c", "rising", 4, 12)
    assert generator == "deterministic"
    assert len(values) == 4
    assert values[-1] > values[0]


def test_generate_series_uses_model_when_available():
    values, generator = generate_series(SeriesProvider(), "hba1c", "rising", 4, 12)
    assert generator == "fake_series"
    assert values == [6.0, 6.8, 7.6, 8.4]


def test_generate_series_rejects_bad_model_output():
    values, generator = generate_series(GarbageProvider(), "hba1c", "rising", 4, 12)
    assert generator == "deterministic"  # fell back
    assert all(isinstance(v, float) for v in values)


def test_playground_roundtrip_updates_snapshots(session):
    values, _ = generate_series(None, "ldl", "rising", 4, 12)
    obs = series_to_observations(values, "ldl", 12)
    result = add_observations(session, "p10", obs)
    assert len(result["inserted"]) == 4
    snap = next(s for s in result["snapshots"] if s["metric_code"] == "ldl")
    assert snap["direction"] == "rising"
    assert snap["n_points"] == 4

    rows = list_playground(session, "p10")
    assert len(rows) == 4
    assert all(r["evidence_id"].startswith("pg-") for r in rows)

    removed = clear_playground(session, "p10")
    assert removed == 4
    assert list_playground(session, "p10") == []


def test_playground_data_flows_into_investigator(session, fixture_data):
    from app.investigator.runner import run_investigation

    values, _ = generate_series(None, "hba1c", "rising", 4, 10)
    add_observations(session, "p10", series_to_observations(values, "hba1c", 10))
    try:
        result = run_investigation(session, "p10", "")
        assert "trend" in [i["category"] for i in result["items"]]
    finally:
        clear_playground(session, "p10")


def test_mrn_lookup_and_save_note(client, fixture_data):
    # MRN resolves to the same patient as the internal id
    r = client.get("/v1/patients/MRN-24003/context")
    assert r.status_code == 200
    assert r.json()["brief"]["patient_id"] == "p03"
    assert r.json()["brief"]["mrn"] == "MRN-24003"

    # persist a clinician note via MRN, then it shows up in context
    r = client.post(
        "/v1/patients/MRN-24003/notes",
        json={"text": "Reviewed trends today. Plan:\n- Recheck A1c in 3 months."},
    )
    assert r.status_code == 200
    evidence_id = r.json()["evidence_id"]
    r = client.get("/v1/patients/p03/context")
    notes = r.json()["recent_notes"]
    assert any(n["evidence_id"] == evidence_id for n in notes)
    saved = next(n for n in notes if n["evidence_id"] == evidence_id)
    assert saved["source_system"] == "clinician"


def test_playground_endpoints(client):
    r = client.post(
        "/v1/patients/p10/playground/generate",
        json={"metric_code": "sbp", "trend": "rising", "n_points": 4, "months_back": 8},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["inserted"]) == 4
    assert body["generator"] in ("deterministic", "mock") or body["generator"]

    r = client.get("/v1/patients/p10/context")
    assert len(r.json()["playground_observations"]) == 4

    r = client.delete("/v1/patients/p10/playground")
    assert r.status_code == 200
    assert r.json()["removed"] == 4


class ScenarioProvider:
    name = "fake_scenario"

    def complete_json(self, system: str, user: str) -> dict:
        return {
            "observations": [
                {"metric_code": "ldl", "value": 148, "months_ago": 1},
                {"metric_code": "hba1c", "value": 5.6, "months_ago": 2},
                {"metric_code": "nonsense", "value": 1, "months_ago": 0},
                {"metric_code": "ldl", "value": 99999, "months_ago": 0},
            ],
            "conditions": [{"display": "Type 2 diabetes mellitus", "status": "active"}],
            "note_text": "Patient complains of tiredness and tooth pain.",
        }


def test_scenario_requires_real_provider():
    from app.playground import scenario_from_text
    from app.providers.gateway import MockProvider

    assert scenario_from_text(MockProvider(), "whatever") is None


def test_scenario_validates_and_applies(session):
    from app.playground import apply_scenario, clear_playground, scenario_from_text

    scenario = scenario_from_text(ScenarioProvider(), "cholesterol borderline high...")
    assert scenario is not None
    assert len(scenario["observations"]) == 2  # nonsense metric + absurd value dropped
    assert scenario["conditions"][0]["display"] == "Type 2 diabetes mellitus"

    result = apply_scenario(session, "t-scenario" if False else "p04", scenario)
    try:
        assert len(result["inserted"]) == 2
        assert result["note_evidence_id"].startswith("pgn-")
        assert result["conditions"][0]["evidence_id"].startswith("pgc-")
    finally:
        removed = clear_playground(session, "p04")
        assert removed == 4  # 2 obs + 1 note + 1 condition


def test_scenario_symptoms_flagged_by_investigator(session):
    from app.investigator.runner import run_investigation
    from app.playground import apply_scenario, clear_playground, scenario_from_text

    scenario = scenario_from_text(ScenarioProvider(), "tired patient with tooth pain")
    apply_scenario(session, "p04", scenario)
    try:
        result = run_investigation(session, "p04", "")
        cats = [i["category"] for i in result["items"]]
        assert "symptom_followup" in cats
        symptom_items = [i for i in result["items"] if i["category"] == "symptom_followup"]
        titles = " ".join(i["title"] for i in symptom_items)
        assert "tooth pain" in titles or "tiredness" in titles
        for item in symptom_items:
            assert item["evidence_ids"]
    finally:
        clear_playground(session, "p04")


def test_symptom_addressed_by_plan_not_flagged(session):
    from app.investigator.runner import run_investigation
    from app.playground import apply_scenario, clear_playground, scenario_from_text

    scenario = scenario_from_text(ScenarioProvider(), "tired patient")
    apply_scenario(session, "p04", scenario)
    try:
        note = (
            "Subjective: tiredness and tooth pain discussed.\n"
            "Plan:\n- Refer for tooth pain evaluation.\n- Work up tiredness with labs."
        )
        result = run_investigation(session, "p04", note)
        assert all(i["category"] != "symptom_followup" for i in result["items"])
    finally:
        clear_playground(session, "p04")
