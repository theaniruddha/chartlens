"""Citable reference ranges for the metrics ChartLens tracks.

Same contract as the drug reference: reference data, not patient data, with a
stable evidence id (`ref-metric-<code>`) that resolves in the evidence drawer.
A value outside the range is surfaced as a documentation prompt ("confirm this
is recorded as intended"), never as an interpretation — wording stays inside
the allowed vocabulary and the range itself is the cited evidence.
"""

METRIC_REFERENCE: dict[str, dict] = {
    "sbp": {"display": "Systolic blood pressure", "low": 90, "high": 140, "unit": "mmHg"},
    "dbp": {"display": "Diastolic blood pressure", "low": 60, "high": 90, "unit": "mmHg"},
    "hba1c": {"display": "Hemoglobin A1c", "low": 4.0, "high": 6.5, "unit": "%"},
    "ldl": {"display": "LDL cholesterol", "low": None, "high": 130, "unit": "mg/dL"},
    "glucose": {"display": "Glucose", "low": 70, "high": 140, "unit": "mg/dL"},
    "potassium": {"display": "Potassium", "low": 3.5, "high": 5.2, "unit": "mmol/L"},
    "creatinine": {"display": "Creatinine", "low": 0.6, "high": 1.3, "unit": "mg/dL"},
    "egfr": {"display": "eGFR", "low": 60, "high": None, "unit": "mL/min"},
    "hemoglobin": {"display": "Hemoglobin", "low": 12.0, "high": 17.5, "unit": "g/dL"},
}


def range_for_metric(code: str) -> dict | None:
    return METRIC_REFERENCE.get(code)


def out_of_range(code: str, value: float) -> str | None:
    """Returns 'above'/'below' when the value sits outside the reference range."""
    ref = METRIC_REFERENCE.get(code)
    if ref is None:
        return None
    if ref["high"] is not None and value > ref["high"]:
        return "above"
    if ref["low"] is not None and value < ref["low"]:
        return "below"
    return None


def range_label(code: str) -> str:
    ref = METRIC_REFERENCE[code]
    low, high, unit = ref["low"], ref["high"], ref["unit"]
    if low is not None and high is not None:
        return f"{low}–{high} {unit}"
    if high is not None:
        return f"up to {high} {unit}"
    return f"at least {low} {unit}"


def reference_evidence_id(code: str) -> str:
    return f"ref-metric-{code}"


def reference_evidence(evidence_id: str) -> dict | None:
    if not evidence_id.startswith("ref-metric-"):
        return None
    code = evidence_id.removeprefix("ref-metric-")
    ref = METRIC_REFERENCE.get(code)
    if ref is None:
        return None
    return {
        "evidence_id": evidence_id,
        "kind": "metric_reference",
        "clinical_time": None,
        "source_system": "chartlens_metric_reference",
        "display": ref["display"],
        "typical_range": range_label(code),
        "limitations": (
            "Typical adult range for synthetic data; lab- and patient-specific "
            "ranges vary. Not an interpretation of any individual result."
        ),
    }
