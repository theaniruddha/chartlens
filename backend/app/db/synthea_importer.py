"""Optional Synthea importer: FHIR R4 bundles -> the existing normalized schema.

Strictly an importer — no API or graph changes. Each Synthea patient becomes a
normal patient row (patient_id "syn-<uuid>", MRN from the FHIR MR identifier),
and only resources that map onto the existing tables are imported. Numeric
observations are kept when their LOINC code maps to a known metric_code;
everything imported carries source_system="synthea" and the original resource
id inside source_resource_id, with the raw resource in raw_source_json.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import (
    Allergy,
    CarePlan,
    Condition,
    Encounter,
    Medication,
    Note,
    Observation,
    Patient,
    Procedure,
)

# LOINC -> ChartLens metric_code
LOINC_METRICS = {
    "4548-4": ("hba1c", "Hemoglobin A1c"),
    "8480-6": ("sbp", "Systolic blood pressure"),
    "8462-4": ("dbp", "Diastolic blood pressure"),
    "29463-7": ("weight", "Body weight"),
    "18262-6": ("ldl", "LDL cholesterol"),
    "2089-1": ("ldl", "LDL cholesterol"),
    "38483-4": ("creatinine", "Creatinine"),
    "2160-0": ("creatinine", "Creatinine"),
    "33914-3": ("egfr", "eGFR"),
    "98979-8": ("egfr", "eGFR"),
    "2823-3": ("potassium", "Potassium"),
    "6298-4": ("potassium", "Potassium"),
    "2339-0": ("glucose", "Glucose"),
    "2345-7": ("glucose", "Glucose"),
    "718-7": ("hemoglobin", "Hemoglobin"),
}


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(concept: dict | None) -> str:
    if not concept:
        return ""
    if concept.get("text"):
        return concept["text"]
    codings = concept.get("coding", [])
    return codings[0].get("display", "") if codings else ""


def _loinc(concept: dict | None) -> str | None:
    for coding in (concept or {}).get("coding", []):
        if "loinc" in (coding.get("system") or "").lower():
            return coding.get("code")
    return None


def _sid(resource: dict) -> str:
    return f"syn-{resource.get('id', '')}"[:128]


class BundleStats(dict):
    def bump(self, key: str) -> None:
        self[key] = self.get(key, 0) + 1


def import_bundle(session: Session, bundle: dict) -> tuple[str | None, BundleStats]:
    """Import one Synthea FHIR bundle. Returns (patient_id, stats)."""
    stats = BundleStats()
    resources = [e.get("resource", {}) for e in bundle.get("entry", [])]
    patient_res = next((r for r in resources if r.get("resourceType") == "Patient"), None)
    if patient_res is None:
        return None, stats

    patient_id = f"syn-{patient_res['id']}"[:64]
    if session.query(Patient).filter_by(patient_id=patient_id).first():
        return patient_id, stats  # idempotent: already imported

    names = patient_res.get("name", [{}])
    # Synthea appends digits to names to mark them as synthetic; strip for display.
    parts = [
        re.sub(r"\d+", "", part)
        for part in names[0].get("given", []) + [names[0].get("family", "")]
    ]
    name = " ".join(p for p in parts if p).strip() or "Unknown"
    mrn = None
    for ident in patient_res.get("identifier", []):
        codes = [c.get("code") for c in ident.get("type", {}).get("coding", [])]
        if "MR" in codes:
            mrn = _format_mrn(ident.get("value"))
            break
    if mrn is None:
        mrn = _format_mrn(patient_res["id"])
    session.add(
        Patient(
            patient_id=patient_id,
            mrn=mrn[:64] if mrn else None,
            name=f"{name} (synthea)"[:128],
            birth_date=_dt(patient_res.get("birthDate")),
            sex=patient_res.get("gender"),
            source_system="synthea",
        )
    )
    session.flush()
    stats.bump("patients")

    common = {"patient_id": patient_id, "source_system": "synthea"}
    for r in resources:
        rtype = r.get("resourceType")
        try:
            if rtype == "Encounter":
                session.add(
                    Encounter(
                        **common,
                        source_resource_id=_sid(r),
                        encounter_id=_sid(r)[:64],
                        encounter_type=_text((r.get("type") or [{}])[0])[:64] or None,
                        reason=_text((r.get("reasonCode") or [{}])[0]) or None,
                        clinical_time=_dt((r.get("period") or {}).get("start")),
                        recorded_time=_dt((r.get("period") or {}).get("start")),
                        raw_source_json=_slim(r),
                    )
                )
                stats.bump("encounters")
            elif rtype == "Condition":
                status = _text(r.get("clinicalStatus")) or (
                    (r.get("clinicalStatus") or {}).get("coding", [{}])[0].get("code", "active")
                )
                session.add(
                    Condition(
                        **common,
                        source_resource_id=_sid(r),
                        code=_loinc(r.get("code")) or _first_code(r.get("code")),
                        display=_text(r.get("code"))[:256],
                        clinical_status="active" if "active" in status.lower() else "resolved",
                        clinical_time=_dt(r.get("onsetDateTime") or r.get("recordedDate")),
                        recorded_time=_dt(r.get("recordedDate")),
                        raw_source_json=_slim(r),
                    )
                )
                stats.bump("conditions")
            elif rtype == "AllergyIntolerance":
                reactions = r.get("reaction", [])
                reaction_text = (
                    _text(reactions[0].get("manifestation", [{}])[0]) if reactions else None
                )
                session.add(
                    Allergy(
                        **common,
                        source_resource_id=_sid(r),
                        substance=_text(r.get("code"))[:128],
                        reaction=reaction_text[:256] if reaction_text else None,
                        severity=(reactions[0].get("severity") if reactions else None),
                        status="active",
                        clinical_time=_dt(r.get("recordedDate")),
                        recorded_time=_dt(r.get("recordedDate")),
                        raw_source_json=_slim(r),
                    )
                )
                stats.bump("allergies")
            elif rtype == "MedicationRequest":
                med_status = r.get("status", "active")
                session.add(
                    Medication(
                        **common,
                        source_resource_id=_sid(r),
                        name=_text(r.get("medicationCodeableConcept"))[:128],
                        status="active" if med_status == "active" else "stopped",
                        clinical_time=_dt(r.get("authoredOn")),
                        recorded_time=_dt(r.get("authoredOn")),
                        raw_source_json=_slim(r),
                    )
                )
                stats.bump("medications")
            elif rtype == "Observation":
                mapped = LOINC_METRICS.get(_loinc(r.get("code")) or "")
                value = (r.get("valueQuantity") or {}).get("value")
                if mapped and value is not None:
                    session.add(
                        Observation(
                            **common,
                            source_resource_id=_sid(r),
                            metric_code=mapped[0],
                            display=mapped[1],
                            value=float(value),
                            unit=(r.get("valueQuantity") or {}).get("unit"),
                            clinical_time=_dt(
                                r.get("effectiveDateTime") or r.get("issued")
                            ),
                            recorded_time=_dt(r.get("issued")),
                            raw_source_json=_slim(r),
                        )
                    )
                    stats.bump("observations")
                else:
                    stats.bump("observations_skipped")
            elif rtype == "Procedure":
                session.add(
                    Procedure(
                        **common,
                        source_resource_id=_sid(r),
                        code=_first_code(r.get("code")),
                        display=_text(r.get("code"))[:256],
                        status=r.get("status", "completed")[:32],
                        clinical_time=_dt(
                            (r.get("performedPeriod") or {}).get("start")
                            or r.get("performedDateTime")
                        ),
                        raw_source_json=_slim(r),
                    )
                )
                stats.bump("procedures")
            elif rtype == "CarePlan":
                categories = r.get("category", [])
                session.add(
                    CarePlan(
                        **common,
                        source_resource_id=_sid(r),
                        description=(
                            _text(categories[0]) if categories else r.get("title", "care plan")
                        )[:2000],
                        status=r.get("status", "active")[:32],
                        clinical_time=_dt((r.get("period") or {}).get("start")),
                        raw_source_json=_slim(r),
                    )
                )
                stats.bump("care_plans")
            elif rtype == "DocumentReference":
                text = _decode_note(r)
                if text:
                    session.add(
                        Note(
                            **common,
                            source_resource_id=_sid(r),
                            note_type="clinical_note",
                            text=text[:20000],
                            clinical_time=_dt(r.get("date")),
                            recorded_time=_dt(r.get("date")),
                        )
                    )
                    stats.bump("notes")
        except Exception:  # noqa: BLE001 - one bad resource must not sink the bundle
            stats.bump(f"errors_{rtype}")
    session.flush()
    return patient_id, stats


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _format_mrn(raw: str | None) -> str | None:
    """Synthea uses a raw UUID as the MR identifier, which reads as noise in a
    patient picker. Render UUIDs as a short MRN; leave real MRNs untouched.
    The full UUID is still the internal patient_id."""
    if not raw:
        return None
    value = str(raw).strip()
    if not _UUID_RE.match(value):
        return value[:64]
    return f"MRN-S{value.replace('-', '')[:8].upper()}"


def _first_code(concept: dict | None) -> str | None:
    codings = (concept or {}).get("coding", [])
    return codings[0].get("code", "")[:32] if codings else None


def _slim(resource: dict) -> dict:
    """Keep raw source bounded: drop bulky narrative/extension blocks."""
    return {
        k: v
        for k, v in resource.items()
        if k not in ("text", "extension", "contained") and not isinstance(v, bytes)
    }


def _decode_note(r: dict) -> str | None:
    import base64

    for content in r.get("content", []):
        data = (content.get("attachment") or {}).get("data")
        if data:
            try:
                return base64.b64decode(data).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                return None
    return None


def import_directory(session: Session, fhir_dir: Path) -> dict:
    """Import every non-metadata bundle in a Synthea fhir output directory,
    then rebuild metric snapshots for each imported patient."""
    from app.playground import rebuild_snapshots

    imported: list[str] = []
    totals = BundleStats()
    for path in sorted(fhir_dir.glob("*.json")):
        if path.name.startswith(("hospitalInformation", "practitionerInformation")):
            continue
        bundle = json.loads(path.read_text())
        patient_id, stats = import_bundle(session, bundle)
        if patient_id:
            imported.append(patient_id)
        for k, v in stats.items():
            totals[k] = totals.get(k, 0) + v
    for pid in imported:
        rebuild_snapshots(session, pid)
    return {"patients": imported, "counts": dict(totals)}
