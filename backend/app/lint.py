"""Inline note linting: span-anchored annotations over a draft note.

Two tiers, mirroring how the checks earn trust:

- **fast** — deterministic only. Re-uses the extraction layer (which now keeps
  character spans) and compares against the patient's chart plus the citable
  drug/metric references. Milliseconds; safe to run on a short typing pause.
- **full** — fast plus one stateless model call over the raw draft text and a
  compact chart context. The model must quote the exact text each remark is
  about; a quote that cannot be located in the note is dropped (the span-level
  analog of the evidence gate), and every message passes the forbidden-wording
  validator.

Every annotation the doctor dismisses is remembered per patient+quote, so the
same flag never nags twice — and the accept/dismiss log doubles as practice
data for later fine-tuning.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.repository import ChartRepository
from app.models import AnnotationEvent
from app.note_review.engine import VALUE_TOLERANCE
from app.note_review.extract import SYMPTOM_LABELS, extract_note_facts
from app.reference import metrics as metric_ref
from app.reference.drugs import (
    NON_SPECIFIC_CLASSES,
    classes_for_allergy_substance,
    classes_for_drug,
    display_name,
    reference_evidence_id,
    use_label,
    uses_for_drug,
)
from app.schemas.items import contains_forbidden_wording

MAX_ANNOTATIONS = 12
_SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}

ANNOTATION_CATEGORIES = {
    "allergy_conflict": "error",
    "medication_mismatch": "warn",
    "chart_value_mismatch": "warn",
    "indication_mismatch": "warn",
    "value_range": "warn",
    "coverage_gap": "info",
    "symptom_followup": "info",
    "unresolved_complaint": "info",
    "new_dx": "info",
    "ambiguity": "info",
}


def quote_key(category: str, quote: str) -> str:
    normalized = " ".join(quote.lower().split())
    return hashlib.sha1(f"{category}|{normalized}".encode()).hexdigest()


# Cues that a symptom named in the draft is already accounted for in the same
# sentence — resolved, negated, or re-attributed. When present, a complaint does
# not need a separate plan item, so we stay silent instead of nagging.
_RESOLUTION_CUES = (
    "resolved", "resolving", "no longer", "not there", "anymore",
    "gone", "cleared", "subsided", "settled", "improved", "improving",
    "better", "denies", "denied", "negative for", "ruled out", "rule out",
    "without", "no evidence", "was ", "turned out", "attributed to",
)

# Extra cues (on top of resolution) that mark an asserted diagnosis as tentative
# or historical rather than a confidently new active problem, so it should not
# be offered for the problem list.
_DIFFERENTIAL_CUES = (
    "likely", "possibly", "probably", "suspect", "suspected", "differential",
    " vs ", " vs.", "versus", "history of", "hx of", "prior", "past ", "query",
    "?", "consistent with", "concern for",
)


def _sentence_around(text: str, start: int, end: int) -> str:
    """Lowercased sentence containing text[start:end] (bounded by . ! ? or line)."""
    low = text.lower()
    left = max(low.rfind(".", 0, start), low.rfind("\n", 0, start),
               low.rfind("!", 0, start), low.rfind("?", 0, start)) + 1
    tail = min(
        (i for i in (low.find(c, end) for c in ".!?\n") if i != -1),
        default=len(low),
    )
    return low[left:tail]


def _annotation(
    category: str,
    start: int,
    end: int,
    quote: str,
    message: str,
    evidence_ids: list[str],
    source: str,
    confidence: str = "high",
    actions: list[str] | None = None,
    suggestion: str | None = None,
) -> dict | None:
    if contains_forbidden_wording(message):
        return None
    return {
        "annotation_id": f"ann-{uuid.uuid4().hex[:10]}",
        "category": category,
        "severity": ANNOTATION_CATEGORIES[category],
        "start": start,
        "end": end,
        "quote": quote,
        "message": message,
        "evidence_ids": evidence_ids,
        "confidence": confidence,
        "source": source,
        "actions": actions or ["dismiss"],
        "suggestion": suggestion,
    }


def fast_lint(session: Session, repo: ChartRepository, text: str) -> list[dict]:
    facts = extract_note_facts(text)
    annotations: list[dict | None] = []

    chart_meds = {}
    from app.reference.drugs import canonical_name

    for med in repo.medications(active_only=False):
        chart_meds[canonical_name(med.name)] = med
    charted_allergies = [
        (a, set(classes_for_allergy_substance(a.substance)))
        for a in repo.allergies()
        if a.status == "active"
    ]
    snapshots = {s.metric_code: s for s in repo.metric_snapshots()}
    covered_metrics = set(repo.distinct_metric_codes())

    for mention in facts.med_mentions:
        if mention.start < 0:
            continue
        span = (mention.start, mention.end, text[mention.start : mention.end])
        drug_label = display_name(mention.term or mention.name)

        if mention.action in ("start", "continue"):
            drug_classes = set(classes_for_drug(mention.name))
            for allergy, allergy_classes in charted_allergies:
                shared = (drug_classes & allergy_classes) - NON_SPECIFIC_CLASSES
                if shared:
                    annotations.append(
                        _annotation(
                            "allergy_conflict", *span,
                            message=(
                                f"Available records show an active {allergy.substance} "
                                f"allergy"
                                + (f" ({allergy.reaction})" if allergy.reaction else "")
                                + f"; {drug_label} is listed in the "
                                f"{sorted(shared)[0].replace('_', ' ')} class."
                            ),
                            evidence_ids=[allergy.source_resource_id],
                            source="deterministic",
                        )
                    )
                    break

        if mention.action == "continue":
            charted_med = chart_meds.get(mention.name)
            if charted_med is not None and charted_med.status != "active":
                annotations.append(
                    _annotation(
                        "medication_mismatch", *span,
                        message=(
                            f"Available records show {drug_label} as {charted_med.status}; "
                            f"the draft continues it. Consider reviewing the "
                            f"medication list."
                        ),
                        evidence_ids=[charted_med.source_resource_id],
                        source="deterministic",
                    )
                )
            elif charted_med is None:
                annotations.append(
                    _annotation(
                        "medication_mismatch", *span,
                        message=(
                            f"{drug_label} was not found in connected records. "
                            f"Consider reviewing the medication list."
                        ),
                        evidence_ids=[],
                        source="deterministic",
                        confidence="medium",
                    )
                )

        if mention.stated_purpose:
            uses = uses_for_drug(mention.name)
            if uses and mention.stated_purpose not in uses:
                listed = ", ".join(use_label(u) for u in uses)
                annotations.append(
                    _annotation(
                        "indication_mismatch", *span,
                        message=(
                            f"The draft gives the purpose of {drug_label} as "
                            f"'{mention.purpose_text}'; the connected drug reference "
                            f"lists it for {listed}."
                        ),
                        evidence_ids=[reference_evidence_id(mention.name)],
                        source="deterministic",
                        confidence="medium",
                    )
                )

    for claim in facts.metric_claims:
        if claim.start < 0:
            continue
        span = (claim.start, claim.end, text[claim.start : claim.end])
        snap = snapshots.get(claim.metric_code)

        if claim.metric_code not in covered_metrics:
            annotations.append(
                _annotation(
                    "coverage_gap", *span,
                    message=(
                        f"No {claim.raw_term} result was found in connected records. "
                        f"Consider reviewing whether this value is documented elsewhere."
                    ),
                    evidence_ids=[],
                    source="deterministic",
                    confidence="medium",
                )
            )
        elif (
            claim.value is not None
            and snap is not None
            and snap.latest_value is not None
            and abs(claim.value - snap.latest_value) > VALUE_TOLERANCE * abs(snap.latest_value)
        ):
            annotations.append(
                _annotation(
                    "chart_value_mismatch", *span,
                    message=(
                        f"Available records show {snap.display} {snap.latest_value} "
                        f"{snap.unit or ''} as the most recent result; the draft cites "
                        f"{claim.value}. Consider reviewing which value is current."
                    ),
                    evidence_ids=[snap.source_resource_id],
                    source="deterministic",
                )
            )

        if claim.value is not None:
            direction = metric_ref.out_of_range(claim.metric_code, claim.value)
            if direction:
                ref = metric_ref.range_for_metric(claim.metric_code)
                if ref is None:
                    continue
                annotations.append(
                    _annotation(
                        "value_range", *span,
                        message=(
                            f"The draft cites {ref['display']} {claim.value:g}; the "
                            f"connected reference lists a typical range of "
                            f"{metric_ref.range_label(claim.metric_code)}. Consider "
                            f"confirming this value is recorded as intended."
                        ),
                        evidence_ids=[metric_ref.reference_evidence_id(claim.metric_code)],
                        source="deterministic",
                        confidence="medium",
                    )
                )

    plan_text = " ".join(p.text.lower() for p in facts.plan_items)
    for sym in facts.symptoms:
        if sym.start < 0 or sym.term in plan_text:
            continue
        # Silent when the same sentence resolves, negates, or re-attributes it
        # ("chest pain ... not there anymore. Was heartburn.").
        sentence = _sentence_around(text, sym.start, sym.end)
        if any(cue in sentence for cue in _RESOLUTION_CUES):
            continue
        label = SYMPTOM_LABELS.get(sym.category, sym.term)
        annotations.append(
            _annotation(
                "symptom_followup",
                sym.start, sym.end, text[sym.start : sym.end],
                message=(
                    f"The draft mentions {label} without a matching plan item. "
                    f"Consider noting whether it was addressed."
                ),
                evidence_ids=[],
                source="deterministic",
                confidence="medium",
            )
        )

    deduped: list[dict] = []
    seen: set[tuple[str, int, int]] = set()
    for a in annotations:
        if a is None:
            continue
        key = (a["category"], a["start"], a["end"])
        if key in seen:
            continue  # e.g. compound BP: sbp+dbp share one span
        seen.add(key)
        deduped.append(a)
    return deduped


_LINT_SYSTEM = (
    "You review a SYNTHETIC clinical draft note for documentation gaps. "
    "Respond with JSON only:\n"
    '{"complaints": [{"quote": "<verbatim text from the note>", '
    '"label": "<short name for the complaint>", "addressed_in_plan": true|false}], '
    '"diagnoses": [{"quote": "<verbatim>", "name": "<condition name>"}], '
    '"ambiguities": [{"quote": "<verbatim>", "issue": "<one short neutral sentence>"}]}\n'
    "complaints: symptoms or problems the patient reports, in any wording. "
    "diagnoses: conditions the note asserts as present. "
    "ambiguities: statements too vague to act on (e.g. 'continue current meds' "
    "with no list). Max 4 per list. Quotes must be copied exactly from the "
    "note. Never suggest what to do clinically; do not use the words "
    "diagnosis, diagnose, treat, treatment, prescribe, order, urgent, critical."
)


def model_lint(
    provider: Any,
    session: Session,
    repo: ChartRepository,
    text: str,
    deterministic: list[dict],
) -> tuple[list[dict], str | None]:
    """One stateless model pass. Returns (annotations, model_name)."""
    if provider is None or getattr(provider, "name", "mock") == "mock":
        return [], None

    conditions = [c.display for c in repo.active_conditions()[:10]]
    context = {"active_conditions": conditions}
    result = provider.complete_json(_LINT_SYSTEM, json.dumps({"note": text, "chart": context}))

    taken_spans = [(a["start"], a["end"]) for a in deterministic]
    annotations: list[dict] = []

    def anchor(quote: str) -> tuple[int, int] | None:
        q = str(quote).strip()
        if len(q) < 3:
            return None
        idx = text.lower().find(q.lower())
        if idx < 0:
            return None
        span = (idx, idx + len(q))
        if any(s < span[1] and span[0] < e for s, e in taken_spans):
            return None  # already covered by a deterministic annotation
        return span

    for item in (result.get("complaints") or [])[:4]:
        if not isinstance(item, dict) or item.get("addressed_in_plan"):
            continue
        span = anchor(item.get("quote", ""))
        if span is None:
            continue
        if any(cue in _sentence_around(text, *span) for cue in _RESOLUTION_CUES):
            continue  # resolved/negated in the same sentence
        label = str(item.get("label", "this complaint"))[:60]
        ann = _annotation(
            "unresolved_complaint", span[0], span[1], text[span[0] : span[1]],
            message=(
                f"The draft mentions {label} without a matching plan item. "
                f"Consider noting whether it was addressed."
            ),
            evidence_ids=[],
            source="model",
            confidence="medium",
        )
        if ann:
            taken_spans.append(span)
            annotations.append(ann)

    active = [c.lower() for c in conditions]
    for item in (result.get("diagnoses") or [])[:4]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()[:100]
        if len(name) < 3:
            continue
        if any(name.lower() in c or c in name.lower() for c in active):
            continue  # already on the problem list
        span = anchor(item.get("quote", ""))
        if span is None:
            continue
        # Only offer confidently-asserted new problems. A tentative, historical,
        # or resolved mention ("was heartburn", "likely GERD") is not a new dx.
        sentence = _sentence_around(text, *span)
        if any(cue in sentence for cue in _RESOLUTION_CUES + _DIFFERENTIAL_CUES):
            continue
        ann = _annotation(
            "new_dx", span[0], span[1], text[span[0] : span[1]],
            message=(
                f"'{name}' is not on the problem list in connected records. "
                f"Consider whether it should be added."
            ),
            evidence_ids=[],
            source="model",
            confidence="medium",
            actions=["add_to_problem_list", "dismiss"],
            suggestion=name,
        )
        if ann:
            taken_spans.append(span)
            annotations.append(ann)

    for item in (result.get("ambiguities") or [])[:4]:
        if not isinstance(item, dict):
            continue
        issue = str(item.get("issue", "")).strip()[:200]
        span = anchor(item.get("quote", ""))
        if span is None or not issue:
            continue
        ann = _annotation(
            "ambiguity", span[0], span[1], text[span[0] : span[1]],
            message=issue,
            evidence_ids=[],
            source="model",
            confidence="low",
        )
        if ann:
            taken_spans.append(span)
            annotations.append(ann)

    return annotations, provider.name


def lint_note(
    session: Session,
    repo: ChartRepository,
    text: str,
    mode: str = "fast",
    provider: Any = None,
) -> dict:
    started = datetime.now(UTC)
    annotations = fast_lint(session, repo, text)
    model_name = None
    if mode == "full":
        model_annotations, model_name = model_lint(provider, session, repo, text, annotations)
        annotations.extend(model_annotations)

    dismissed = _dismissed_keys(session, repo.patient_id)
    annotations = [
        a for a in annotations if quote_key(a["category"], a["quote"]) not in dismissed
    ]
    annotations.sort(key=lambda a: (_SEVERITY_ORDER[a["severity"]], a["start"]))
    duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    return {
        "annotations": annotations[:MAX_ANNOTATIONS],
        "mode": mode,
        "model": model_name,
        "duration_ms": duration_ms,
    }


def _dismissed_keys(session: Session, patient_id: str) -> set[str]:
    rows = session.scalars(
        select(AnnotationEvent.quote_hash).where(
            AnnotationEvent.patient_id == patient_id,
            AnnotationEvent.decision == "dismissed",
        )
    )
    return set(rows)


def record_decision(
    session: Session,
    patient_id: str,
    category: str,
    quote: str,
    decision: str,
    note_text: str = "",
) -> dict:
    event = AnnotationEvent(
        patient_id=patient_id,
        category=category,
        quote=quote[:500],
        quote_hash=quote_key(category, quote),
        decision=decision,
        note_hash=hashlib.sha1(note_text.encode()).hexdigest() if note_text else None,
    )
    session.add(event)
    session.flush()
    return {"recorded": True, "decision": decision, "quote_hash": event.quote_hash}
