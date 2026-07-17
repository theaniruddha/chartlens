"""No patient cross-join leakage: everything is scoped by ChartRepository."""

from app.db.repository import ChartRepository
from app.tools.semantic_tools import TOOLS, get_evidence_details, search_prior_notes


def test_repository_rows_are_scoped(session):
    repo_p01 = ChartRepository(session, "p01")
    meds = repo_p01.medications(active_only=False)
    assert meds and all(m.patient_id == "p01" for m in meds)
    assert all(n.patient_id == "p01" for n in repo_p01.notes())


def test_evidence_lookup_cannot_cross_patients(session):
    repo_p01 = ChartRepository(session, "p01")
    stolen = get_evidence_details(repo_p01, ["p02-alg-1", "p03-obs-hba1c-1"])
    assert stolen["evidence"] == []


def test_note_search_is_scoped(session):
    repo_p03 = ChartRepository(session, "p03")
    hits = search_prior_notes(repo_p03, "colonoscopy")
    assert hits["hits"] == []  # p07's colonoscopy note must not leak
    repo_p07 = ChartRepository(session, "p07")
    hits = search_prior_notes(repo_p07, "colonoscopy")
    assert hits["found"] and all(h["evidence_id"].startswith("p07") for h in hits["hits"])


def test_all_tools_return_bounded_json(session):
    repo = ChartRepository(session, "p03")
    args: dict[str, dict] = {
        "get_metric_series": {"metric_code": "hba1c"},
        "get_related_metric_snapshots": {"metric_code": "hba1c"},
        "get_followup_resolution": {"topic": "a1c_followup"},
        "search_prior_notes": {"query": "a1c"},
        "get_note_evidence": {"note_id": "p03-note-1"},
        "get_evidence_details": {"evidence_ids": ["p03-obs-hba1c-1"]},
    }
    import json

    for name, tool in TOOLS.items():
        result = tool(repo, **args.get(name, {}))
        assert isinstance(result, dict)
        json.dumps(result)  # must be JSON-serializable
