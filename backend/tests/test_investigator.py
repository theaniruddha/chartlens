import pytest

import app.investigator.graph as graph_mod
from app.db.loader import load_fixture, materialize_snapshots
from app.investigator.runner import get_run, run_investigation

PATIENT_IDS = [f"p{i:02d}" for i in range(1, 11)]


@pytest.mark.parametrize("pid", PATIENT_IDS)
def test_fixture_expectations(session, fixture_data, pid):
    data = fixture_data[pid]
    result = run_investigation(session, pid, data["current_note"])
    got = sorted(i["category"] for i in result["items"])
    assert got == sorted(data["expected"]["investigator"]), f"{pid}: {result['items']}"
    assert result["tool_calls_used"] <= graph_mod.MAX_TOOL_CALLS
    assert len(result["items"]) <= graph_mod.MAX_ITEMS
    for item in result["items"]:
        assert item["evidence_ids"], item
        assert item["limitations"], item


def test_deferred_item_carries_deferral_state(session, fixture_data):
    result = run_investigation(session, "p08", fixture_data["p08"]["current_note"])
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["category"] == "deferred_topic"
    assert item["deferral_state"] == "active"
    assert "p08-def-1" in item["evidence_ids"]


def test_run_persisted_with_steps(session, fixture_data):
    result = run_investigation(session, "p03", fixture_data["p03"]["current_note"])
    session.commit()
    run = get_run(session, result["run_id"], include_steps=True)
    assert run is not None
    assert run["status"] == "completed"
    assert run["steps"], "steps should be persisted"
    nodes = {s["node"] for s in run["steps"]}
    assert "supervisor" in nodes
    assert "finalize" in nodes


def test_tool_budget_stops_investigation(session, fixture_data, monkeypatch):
    monkeypatch.setattr(graph_mod, "MAX_TOOL_CALLS", 3)
    result = run_investigation(session, "p03", fixture_data["p03"]["current_note"])
    assert result["stop_reason"] == "budget_exhausted"
    assert result["tool_calls_used"] <= 3
    for item in result["items"]:
        assert item["evidence_ids"]


def test_branch_budget_limits_parallel_hypotheses(session, monkeypatch):
    # Generous tool budget so the branch cap is what stops the run.
    monkeypatch.setattr(graph_mod, "MAX_TOOL_CALLS", 20)
    # Four unrelated rising metrics -> four trend hypotheses -> only 3 investigated.
    obs = []
    metrics = {"hba1c": (6.0, 0.4), "sbp": (120.0, 4.0), "ldl": (100.0, 8.0), "egfr": (90.0, -3.0)}
    for code, (base, step) in metrics.items():
        for i, month in enumerate(["2026-01", "2026-03", "2026-05"]):
            obs.append(
                {
                    "source_resource_id": f"t-br-{code}-{i}",
                    "metric_code": code,
                    "display": code.upper(),
                    "value": base + step * i * 2,
                    "unit": "u",
                    "clinical_time": f"{month}-01T00:00:00Z",
                }
            )
    load_fixture(
        session,
        {"patient": {"patient_id": "t-br", "name": "Branch Budget (synthetic)"},
         "observations": obs},
    )
    session.flush()
    materialize_snapshots(session, "t-br")
    result = run_investigation(session, "t-br", "")
    assert result["stop_reason"] == "branch_budget_exhausted"
    assert len(result["items"]) == 3


def test_no_raw_prompts_in_result(session, fixture_data):
    result = run_investigation(session, "p03", fixture_data["p03"]["current_note"])
    text = str(result).lower()
    assert "system prompt" not in text
    assert "chain of thought" not in text


def test_coverage_report_present_and_complete(session, fixture_data):
    result = run_investigation(session, "p03", fixture_data["p03"]["current_note"])
    report = result["coverage_report"]
    assert report is not None
    for domain in ("conditions", "medications_active", "allergies", "notes", "metrics_tracked"):
        assert domain in report["domains"]
    assert report["hypotheses_total"] >= 1
    assert "get_metric_snapshots" in report["tools_used"]


def test_draft_deferral_suppresses_plan_hypothesis(session, fixture_data):
    note = (
        "Patient declines colonoscopy at this time; defer for 6 months.\n"
        "Plan:\n- Recheck CBC in 3 months."
    )
    result = run_investigation(session, "p07", note)
    assert all(i["category"] != "unresolved_plan" for i in result["items"])
    # Draft deferrals do not fabricate chart-deferral items either.
    assert all(i["category"] != "deferred_topic" for i in result["items"])
    assert result["coverage_report"]["hypotheses_suppressed"] >= 1
