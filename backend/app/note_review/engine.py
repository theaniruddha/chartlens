"""Note Review engine: extract → retrieve → compare deterministically →
verify ambiguous semantic conflicts with the model → max 3 correction cards."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.repository import ChartRepository
from app.note_review.extract import NoteFacts, extract_note_facts
from app.providers.gateway import LLMProvider, semantic_verify
from app.reference.drugs import (
    NON_SPECIFIC_CLASSES,
    classes_for_allergy_substance,
    classes_for_drug,
    display_name,
    reference_evidence_id,
    use_label,
    uses_for_drug,
)
from app.schemas.items import DEFAULT_LIMITATIONS, ReviewItem, validate_item
from app.timeutil import utc_date
from app.tools.semantic_tools import get_followup_resolution, get_recent_plan_candidates

MAX_CARDS = 3

TOPIC_LABELS = {
    "colonoscopy": "colonoscopy follow-up",
    "mammogram": "mammogram follow-up",
    "a1c_followup": "A1c recheck",
    "lipid_followup": "lipid recheck",
    "bp_followup": "blood pressure recheck",
    "renal_followup": "renal lab recheck",
    "imaging_followup": "imaging follow-up",
    "medication_review": "medication review",
    "vaccination": "vaccination follow-up",
    "weight_management": "weight follow-up",
    "other": "follow-up item",
}

# Relative tolerance for numeric note-claim vs latest chart value.
VALUE_TOLERANCE = 0.15


def _new_id() -> str:
    return f"card-{uuid.uuid4().hex[:10]}"


def _date(dt) -> list[str]:
    d = utc_date(dt)
    return [d] if d else []


def _active_deferral_topics(repo: ChartRepository, now: datetime) -> dict[str, object]:
    out: dict[str, object] = {}
    for d in repo.active_deferrals():
        if d.deferred_until is None or d.deferred_until > now:
            out[d.topic] = d
    return out


def review_note(
    session: Session,
    patient_id: str,
    current_note: str,
    provider: LLMProvider,
    encounter_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    repo = ChartRepository(session, patient_id)
    repo.patient()  # raises PatientNotFoundError early
    facts = extract_note_facts(current_note)

    cards: list[ReviewItem] = []
    cards += _check_allergy_conflicts(repo, facts)
    cards += _check_medication_mismatches(repo, facts)
    cards += _check_indication_mismatches(facts)
    cards += _check_value_mismatches_and_claims(repo, facts, provider)
    cards += _check_coverage_gaps(repo, facts)
    cards += _check_unresolved_plans(repo, facts, now)

    cards = [validate_item(c) for c in cards[:MAX_CARDS]]
    return {
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "cards": [c.model_dump() for c in cards],
        "note_facts": _facts_summary(facts),
        "generated_at": now.isoformat(),
    }


def _facts_summary(facts: NoteFacts) -> dict:
    return {
        "medications_mentioned": [
            {"name": m.name, "action": m.action} for m in facts.med_mentions
        ],
        "metric_claims": [
            {"metric_code": c.metric_code, "value": c.value, "qualifier": c.qualifier}
            for c in facts.metric_claims
        ],
        "plan_items": [{"text": p.text, "topic": p.topic} for p in facts.plan_items],
        "deferral_mentions": [{"topic": d.topic, "sentence": d.sentence} for d in facts.deferrals],
    }


def _check_allergy_conflicts(repo: ChartRepository, facts: NoteFacts) -> list[ReviewItem]:
    """A drug named in the note conflicts with a charted allergy when the two
    share a specific class (e.g. septra <-> sulfa). Both sides are mapped to
    classes via the local drug reference; the allergy record is the evidence."""
    items = []
    charted = [
        (a, set(classes_for_allergy_substance(a.substance)))
        for a in repo.allergies()
        if a.status == "active"
    ]
    for mention in facts.med_mentions:
        if mention.action not in ("start", "continue"):
            continue
        drug_classes = set(classes_for_drug(mention.name))
        if not drug_classes:
            continue
        for allergy, allergy_classes in charted:
            shared = (drug_classes & allergy_classes) - NON_SPECIFIC_CLASSES
            if not shared:
                continue
            class_label = sorted(shared)[0].replace("_", " ")
            drug_label = display_name(mention.term or mention.name)
            items.append(
                ReviewItem(
                    item_id=_new_id(),
                    category="allergy_conflict",
                    title="Possible allergy documentation conflict",
                    message=(
                        f"A possible documentation mismatch was detected: the draft note "
                        f"mentions {drug_label}, which the connected drug reference lists "
                        f"in the {class_label} class, and available records show an active "
                        f"{allergy.substance} allergy"
                        + (f" ({allergy.reaction})" if allergy.reaction else "")
                        + ". Consider reviewing the allergy list against this note."
                    ),
                    confidence="high",
                    evidence_ids=[allergy.source_resource_id],
                    source_dates=_date(allergy.clinical_time),
                    limitations=DEFAULT_LIMITATIONS,
                )
            )
            break
    return items


def _check_medication_mismatches(repo: ChartRepository, facts: NoteFacts) -> list[ReviewItem]:
    items = []
    from app.reference.drugs import canonical_name

    chart_meds = {canonical_name(m.name): m for m in repo.medications(active_only=False)}
    for mention in facts.med_mentions:
        if mention.action != "continue":
            continue
        med = chart_meds.get(mention.name)
        as_written = mention.term or mention.name
        if med is not None and med.status != "active":
            items.append(
                ReviewItem(
                    item_id=_new_id(),
                    category="medication_mismatch",
                    title="Medication list mismatch",
                    message=(
                        f"A possible documentation mismatch was detected: the draft note "
                        f"continues {as_written}, but available records show it as "
                        f"{med.status}"
                        + (
                            f" as of {utc_date(med.clinical_time)}"
                            if med.clinical_time
                            else ""
                        )
                        + ". Consider reviewing the medication list."
                    ),
                    confidence="high",
                    evidence_ids=[med.source_resource_id],
                    source_dates=_date(med.clinical_time),
                    limitations=DEFAULT_LIMITATIONS,
                )
            )
        elif med is None:
            items.append(
                ReviewItem(
                    item_id=_new_id(),
                    category="medication_mismatch",
                    title="Medication not found in connected records",
                    message=(
                        f"The draft note continues {as_written}, but this medication "
                        f"was "
                        f"not found in connected records. Consider reviewing the "
                        f"medication list."
                    ),
                    confidence="medium",
                    evidence_ids=[_fallback_evidence(repo)],
                    source_dates=[],
                    limitations=DEFAULT_LIMITATIONS,
                )
            )
    return items


def _check_indication_mismatches(facts: NoteFacts) -> list[ReviewItem]:
    """The purpose stated in the note vs what the drug reference lists the drug
    for. Reference-backed, so the finding cites the reference entry; silent
    whenever either side is unknown."""
    items = []
    for mention in facts.med_mentions:
        if not mention.stated_purpose:
            continue
        uses = uses_for_drug(mention.name)
        if not uses or mention.stated_purpose in uses:
            continue
        listed = ", ".join(use_label(u) for u in uses)
        items.append(
            ReviewItem(
                item_id=_new_id(),
                category="indication_mismatch",
                title=f"Possible indication mismatch: {mention.term or mention.name}",
                message=(
                    f"A possible documentation mismatch was detected: the draft note gives "
                    f"the purpose of {display_name(mention.term or mention.name)} as "
                    f"'{mention.purpose_text}', and the connected drug reference lists it "
                    f"for {listed}. Consider reviewing the documented indication."
                ),
                confidence="medium",
                evidence_ids=[reference_evidence_id(mention.name)],
                source_dates=[],
                limitations=(
                    "Compared against a local drug reference for synthetic data, not a "
                    "formulary; the reference lists typical use only and may not cover "
                    "every legitimate use. Records were not otherwise consulted for this item."
                ),
            )
        )
    return items


def _fallback_evidence(repo: ChartRepository) -> str:
    """Anchor evidence for absence findings: most recent encounter, else note."""
    encounters = repo.encounters(limit=1)
    if encounters:
        return encounters[0].source_resource_id
    notes = repo.notes(limit=1)
    if notes:
        return notes[0].source_resource_id
    return f"patient:{repo.patient_id}"


def _check_value_mismatches_and_claims(
    repo: ChartRepository, facts: NoteFacts, provider: LLMProvider
) -> list[ReviewItem]:
    items = []
    snaps = {s.metric_code: s for s in repo.metric_snapshots()}
    for claim in facts.metric_claims:
        snap = snaps.get(claim.metric_code)
        if snap is None or snap.latest_value is None:
            continue  # coverage handled separately
        if claim.value is not None:
            if abs(claim.value - snap.latest_value) > VALUE_TOLERANCE * abs(snap.latest_value):
                items.append(
                    ReviewItem(
                        item_id=_new_id(),
                        category="chart_value_mismatch",
                        title=f"Possible {snap.display} value mismatch",
                        message=(
                            f"A possible documentation mismatch was detected: the draft note "
                            f"cites {snap.display} {claim.value}, and available records show "
                            f"{snap.latest_value} {snap.unit or ''} as the most recent value. "
                            f"Consider reviewing which value is current."
                        ),
                        confidence="high",
                        evidence_ids=[snap.source_resource_id],
                        source_dates=_date(snap.latest_time),
                        limitations=DEFAULT_LIMITATIONS,
                    )
                )
        elif claim.qualifier in ("normal", "stable", "controlled") and (
            snap.slope_per_month is not None and snap.n_points and snap.n_points >= 3
        ):
            # Ambiguous semantic conflict: "stable/normal" wording vs a moving trend.
            from app.analytics.trends import DEFAULT_SLOPE_THRESHOLD, SLOPE_THRESHOLDS

            threshold = SLOPE_THRESHOLDS.get(claim.metric_code, DEFAULT_SLOPE_THRESHOLD)
            if abs(snap.slope_per_month) > threshold:
                verdict = semantic_verify(
                    provider,
                    question=(
                        f"The draft note describes {snap.display} as '{claim.qualifier}'. "
                        f"Do the records contradict that wording?"
                    ),
                    context={
                        "metric": snap.display,
                        "latest_value": snap.latest_value,
                        "delta": snap.delta,
                        "slope_per_month": snap.slope_per_month,
                        "n_points": snap.n_points,
                    },
                )
                if verdict["answer"] == "yes":
                    items.append(
                        ReviewItem(
                            item_id=_new_id(),
                            category="chart_value_mismatch",
                            title=f"Wording may not match {snap.display} records",
                            message=(
                                f"A possible documentation mismatch was detected: the draft "
                                f"note describes {snap.display} as '{claim.qualifier}', and "
                                f"available records show a change of about "
                                f"{round(snap.slope_per_month, 2)} {snap.unit or ''}/month "
                                f"across {snap.n_points} results. Consider reviewing the "
                                f"wording against the recent values."
                            ),
                            confidence="medium",
                            evidence_ids=[snap.source_resource_id],
                            source_dates=_date(snap.latest_time),
                            limitations=DEFAULT_LIMITATIONS,
                        )
                    )
    return items


def _check_coverage_gaps(repo: ChartRepository, facts: NoteFacts) -> list[ReviewItem]:
    items = []
    covered = set(repo.distinct_metric_codes())
    for claim in facts.metric_claims:
        if claim.metric_code not in covered:
            items.append(
                ReviewItem(
                    item_id=_new_id(),
                    category="coverage_gap",
                    title=f"{claim.raw_term.capitalize()} result not found in connected records",
                    message=(
                        f"The draft note references {claim.raw_term}"
                        + (f" as '{claim.qualifier}'" if claim.qualifier else "")
                        + ", but no matching result was found in connected records. "
                        "Consider reviewing whether this value is documented elsewhere."
                    ),
                    confidence="high",
                    evidence_ids=[_fallback_evidence(repo)],
                    source_dates=[],
                    limitations=DEFAULT_LIMITATIONS,
                )
            )
    return items


def _check_unresolved_plans(
    repo: ChartRepository, facts: NoteFacts, now: datetime
) -> list[ReviewItem]:
    items = []
    current_topics = {p.topic for p in facts.plan_items if p.topic}
    # Topics the draft note itself defers are treated as addressed, not missing.
    draft_deferred = {d.topic for d in facts.deferrals if d.topic}
    deferred = _active_deferral_topics(repo, now)
    seen: set[str] = set()
    for cand in get_recent_plan_candidates(repo)["candidates"]:
        topic = cand["topic"]
        if (
            not topic
            or topic in seen
            or topic in current_topics
            or topic in deferred
            or topic in draft_deferred
        ):
            continue
        seen.add(topic)
        resolution = get_followup_resolution(repo, topic, since=cand["note_time"])
        if not resolution["resolved"]:
            label = TOPIC_LABELS.get(topic, topic)
            when = (cand["note_time"] or "")[:10]
            items.append(
                ReviewItem(
                    item_id=_new_id(),
                    category="unresolved_plan",
                    title=f"Earlier plan item may be unresolved: {label}",
                    message=(
                        f"A prior note from {when} includes a plan item about {label}, and no "
                        f"matching completion was found in connected records since that date. "
                        f"Consider reviewing its status."
                    ),
                    confidence="high",
                    evidence_ids=[cand["evidence_id"]],
                    source_dates=[when] if when else [],
                    limitations=DEFAULT_LIMITATIONS,
                )
            )
    return items
