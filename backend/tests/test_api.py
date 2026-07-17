def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_patients(client):
    r = client.get("/v1/patients")
    assert r.status_code == 200
    assert len(r.json()["patients"]) >= 10


def test_context(client):
    r = client.get("/v1/patients/p03/context")
    assert r.status_code == 200
    body = r.json()
    assert body["brief"]["patient_id"] == "p03"
    assert any(s["metric_code"] == "hba1c" for s in body["snapshots"])


def test_note_review_endpoint(client, fixture_data):
    r = client.post(
        "/v1/patients/p01/notes/review",
        json={"current_note": fixture_data["p01"]["current_note"]},
    )
    assert r.status_code == 200
    cards = r.json()["cards"]
    assert [c["category"] for c in cards] == ["medication_mismatch"]


def test_investigate_and_fetch_run(client, fixture_data):
    r = client.post(
        "/v1/patients/p03/investigate",
        json={"current_note": fixture_data["p03"]["current_note"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["category"] == "trend"
    run_id = body["run_id"]

    r2 = client.get(f"/v1/investigations/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["run_id"] == run_id
    assert "steps" not in r2.json()

    r3 = client.get(f"/v1/investigations/{run_id}?include_steps=true")
    assert r3.status_code == 200
    assert r3.json()["steps"]


def test_unknown_patient_404(client):
    assert client.get("/v1/patients/ghost/context").status_code == 404
    assert (
        client.post("/v1/patients/ghost/notes/review", json={"current_note": "x"}).status_code
        == 404
    )


def test_unknown_run_404(client):
    assert client.get("/v1/investigations/run-nope").status_code == 404


def test_no_prompts_exposed(client, fixture_data):
    r = client.post(
        "/v1/patients/p01/notes/review",
        json={"current_note": fixture_data["p01"]["current_note"]},
    )
    text = r.text.lower()
    assert "you are" not in text  # no leaked system prompts
    assert "respond with json" not in text
