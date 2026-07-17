import json
from pathlib import Path

from app.db.repository import ChartRepository
from app.db.synthea_importer import import_bundle
from app.investigator.runner import run_investigation
from app.playground import rebuild_snapshots

BUNDLE = json.loads(
    (Path(__file__).parent / "fixtures" / "synthea_sample_bundle.json").read_text()
)


def test_import_bundle_maps_resources(session):
    patient_id, stats = import_bundle(session, BUNDLE)
    assert patient_id == "syn-aaaa1111-2222-3333-4444-555566667777"
    assert stats["patients"] == 1
    assert stats["conditions"] == 1
    assert stats["medications"] == 1
    assert stats["observations"] == 3
    assert stats["observations_skipped"] == 1  # unmapped LOINC dropped
    assert stats["procedures"] == 1

    repo = ChartRepository(session, patient_id)
    patient = repo.patient()
    assert patient.name == "Test Synthea (synthea)"  # synthetic digits stripped
    assert patient.mrn == "SYN-MRN-0001"
    assert patient.source_system == "synthea"
    obs = repo.observations_for_metric("hba1c")
    assert [o.value for o in obs] == [6.3, 7.1, 7.9]
    assert all(o.source_system == "synthea" for o in obs)


def test_import_is_idempotent(session):
    pid1, _ = import_bundle(session, BUNDLE)
    pid2, stats2 = import_bundle(session, BUNDLE)
    assert pid1 == pid2
    assert stats2.get("patients", 0) == 0  # nothing re-imported


def test_imported_patient_flows_through_agent(session):
    patient_id, _ = import_bundle(session, BUNDLE)
    rebuild_snapshots(session, patient_id)
    result = run_investigation(session, patient_id, "")
    assert [i["category"] for i in result["items"]] == ["trend"]
    trend = result["items"][0]
    assert any("syn-obs-a1c" in e for e in trend["evidence_ids"])


def test_uuid_mrn_rendered_readable_real_mrn_untouched():
    from app.db.synthea_importer import _format_mrn

    # Synthea's real output uses a bare UUID as the MR identifier.
    assert _format_mrn("c57d2887-43b9-afa4-1a3d-30cd5fed0f21") == "MRN-SC57D2887"
    # An identifier that already looks like an MRN is left alone.
    assert _format_mrn("SYN-MRN-0001") == "SYN-MRN-0001"
    assert _format_mrn(None) is None
