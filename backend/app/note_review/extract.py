"""Rule-first extraction of structured facts from a draft note.

Deterministic by design: a small lexicon of synthetic-world medications,
metric synonyms, and topic keywords. The model is never used for extraction,
only later for verifying ambiguous semantic conflicts.
"""

import re
from dataclasses import dataclass, field

from app.reference.drugs import DRUG_VOCABULARY, canonical_name, purpose_category

# Every drug/brand the extractor can recognize, longest first so that
# "amoxicillin-clavulanate" wins over "amoxicillin".
MED_LEXICON = DRUG_VOCABULARY

METRIC_SYNONYMS = {
    "hba1c": "hba1c",
    "a1c": "hba1c",
    "hemoglobin a1c": "hba1c",
    "blood pressure": "sbp",
    "bp": "sbp",
    "systolic": "sbp",
    "ldl": "ldl",
    "cholesterol": "ldl",
    "weight": "weight",
    "potassium": "potassium",
    "creatinine": "creatinine",
    "egfr": "egfr",
    "glucose": "glucose",
    "hemoglobin": "hemoglobin",
    "cbc": "hemoglobin",
}

TOPIC_KEYWORDS = {
    "colonoscopy": "colonoscopy",
    "mammogram": "mammogram",
    "a1c": "a1c_followup",
    "hba1c": "a1c_followup",
    "lipid": "lipid_followup",
    "ldl": "lipid_followup",
    "blood pressure": "bp_followup",
    "bp check": "bp_followup",
    "creatinine": "renal_followup",
    "renal": "renal_followup",
    "potassium": "renal_followup",
    "imaging": "imaging_followup",
    "x-ray": "imaging_followup",
    "mri": "imaging_followup",
    "medication review": "medication_review",
    "vaccin": "vaccination",
    "weight": "weight_management",
    "cbc": "other",
}

QUALIFIERS = ["normal", "stable", "controlled", "elevated", "high", "low", "improving", "worsening"]

# Symptom phrases worth flagging when no follow-up addresses them.
# Longest phrases first so "tooth pain" wins over substrings.
SYMPTOM_LEXICON: dict[str, str] = {
    "shortness of breath": "breathing_difficulty",
    "short of breath": "breathing_difficulty",
    "blurred vision": "vision_change",
    "blurry vision": "vision_change",
    "chest pain": "chest_discomfort",
    "tooth pain": "dental_pain",
    "dental pain": "dental_pain",
    "toothache": "dental_pain",
    "weight loss": "unintended_weight_change",
    "tiredness": "fatigue",
    "fatigue": "fatigue",
    "exhaustion": "fatigue",
    "tired": "fatigue",
    "dizziness": "dizziness",
    "dizzy": "dizziness",
    "headache": "headache",
    "numbness": "numbness",
    "tingling": "numbness",
}

SYMPTOM_LABELS: dict[str, str] = {
    "breathing_difficulty": "shortness of breath",
    "vision_change": "vision changes",
    "chest_discomfort": "chest discomfort",
    "dental_pain": "tooth pain",
    "unintended_weight_change": "weight change",
    "fatigue": "tiredness or fatigue",
    "dizziness": "dizziness",
    "headache": "headache",
    "numbness": "numbness or tingling",
}

# Phrases that assign an intent to a medication mention. Multi-word phrases
# must precede their single-word substrings.
_ACTION_WORDS = (
    r"(asked to take|advised to take|told to take|instructed to take|started on"
    r"|switched to|switch to|trial of|begin|beginning|began|initiate|initiated"
    r"|start|started|starting|prescribed|prescribe|given|give|recommend|recommended"
    r"|advised|take|taking|use|using|add|added|resume|resumed"
    r"|continue|continued|continuing|keep|maintain"
    r"|stop|stopped|stopping|discontinue|discontinued|hold|holding|taper)"
)

_START_PHRASES = (
    "asked to take", "advised to take", "told to take", "instructed to take",
    "started on", "switched to", "switch to", "trial of", "begin", "beginning",
    "began", "initiate", "initiated", "start", "prescribed", "prescribe",
    "given", "give", "recommend", "advised", "take", "taking", "use", "using",
    "add", "added", "resume",
)


@dataclass
class MedMention:
    name: str  # canonical name, for chart comparison
    action: str | None  # normalized: start | continue | stop | None
    term: str = ""  # the term as written in the note
    stated_purpose: str | None = None  # use category the note gives for it
    purpose_text: str | None = None  # that purpose as written
    start: int = -1  # character span of the drug term in the note
    end: int = -1


@dataclass
class MetricClaim:
    metric_code: str
    raw_term: str
    value: float | None = None
    qualifier: str | None = None
    start: int = -1  # span covering the term (and value, when present)
    end: int = -1


@dataclass
class PlanItem:
    text: str
    topic: str | None


@dataclass
class DeferralMention:
    topic: str | None
    sentence: str


@dataclass
class SymptomMention:
    term: str
    category: str
    start: int = -1
    end: int = -1


@dataclass
class NoteFacts:
    med_mentions: list[MedMention] = field(default_factory=list)
    metric_claims: list[MetricClaim] = field(default_factory=list)
    plan_items: list[PlanItem] = field(default_factory=list)
    deferrals: list[DeferralMention] = field(default_factory=list)
    symptoms: list[SymptomMention] = field(default_factory=list)


def _normalize_action(word: str | None) -> str | None:
    if not word:
        return None
    w = word.lower().strip()
    if w.startswith(("continu", "keep", "maintain")):
        return "continue"
    if w.startswith(("stop", "discontinu", "hold", "taper")):
        return "stop"
    if w.startswith(_START_PHRASES):
        return "start"
    return None


_PURPOSE_TRIGGER = re.compile(
    r"\b(?:for|to help with|to help|to treat|to manage|to cover)\b\s+"
    r"(?:the\s+|her\s+|his\s+|their\s+|a\s+)?([a-z0-9 ]{3,40})"
)


def _stated_purpose(low: str, start: int, end: int) -> tuple[str | None, str | None]:
    """Purpose the note gives for a drug, read from the sentence it sits in
    ("... take septra medicine for sleep" -> sleep)."""
    sentence_start = max(low.rfind(".", 0, start), low.rfind("\n", 0, start)) + 1
    tail_break = re.search(r"[.!?\n]", low[end:])
    sentence_end = end + (tail_break.start() if tail_break else len(low) - end)
    sentence = low[sentence_start:sentence_end]
    match = _PURPOSE_TRIGGER.search(sentence)
    if not match:
        return None, None
    hit = purpose_category(match.group(1))
    if not hit:
        return None, None
    category, phrase = hit
    return category, phrase


def topic_for_text(text: str) -> str | None:
    low = text.lower()
    for kw, topic in TOPIC_KEYWORDS.items():
        if kw in low:
            return topic
    return None


def extract_note_facts(text: str) -> NoteFacts:
    facts = NoteFacts()
    low = text.lower()

    claimed_spans: list[tuple[int, int]] = []
    seen_meds: set[str] = set()
    for med in MED_LEXICON:
        for m in re.finditer(rf"\b{re.escape(med)}\b", low):
            # Skip a term already covered by a longer match (e.g. "amoxicillin"
            # inside "amoxicillin-clavulanate").
            if any(start <= m.start() < end for start, end in claimed_spans):
                continue
            canonical = canonical_name(med)
            if canonical in seen_meds:
                continue
            claimed_spans.append((m.start(), m.end()))
            seen_meds.add(canonical)
            line_start = low.rfind("\n", 0, m.start()) + 1
            prefix = low[line_start : m.start()]
            action_match = None
            for am in re.finditer(_ACTION_WORDS, prefix):
                action_match = am.group(0)
            purpose, purpose_text = _stated_purpose(low, m.start(), m.end())
            facts.med_mentions.append(
                MedMention(
                    name=canonical,
                    action=_normalize_action(action_match),
                    term=med,
                    stated_purpose=purpose,
                    purpose_text=purpose_text,
                    start=m.start(),
                    end=m.end(),
                )
            )
            break  # one mention per drug is enough

    claimed: set[str] = set()

    # Compound blood pressure ("BP 178/110") claims both components.
    bp = re.search(r"\b(?:bp|blood pressure)\b[^\d\n]{0,12}(\d{2,3})\s*/\s*(\d{2,3})", low)
    if bp:
        claimed.update(("sbp", "dbp"))
        facts.metric_claims.append(
            MetricClaim(
                metric_code="sbp", raw_term="bp", value=float(bp.group(1)),
                start=bp.start(), end=bp.end(),
            )
        )
        facts.metric_claims.append(
            MetricClaim(
                metric_code="dbp", raw_term="bp", value=float(bp.group(2)),
                start=bp.start(), end=bp.end(),
            )
        )

    for syn, code in METRIC_SYNONYMS.items():
        for m in re.finditer(rf"\b{re.escape(syn)}\b", low):
            if code in claimed:
                break
            window = low[m.end() : m.end() + 40]
            value_m = re.match(r"(?:\s+(?:was|is|of|at|:))?\s*(\d+(?:\.\d+)?)", window)
            qualifier = next((q for q in QUALIFIERS if q in window), None)
            value = float(value_m.group(1)) if value_m else None
            if value is not None or qualifier is not None:
                claimed.add(code)
                span_end = m.end() + (value_m.end() if value_m else 0)
                facts.metric_claims.append(
                    MetricClaim(
                        metric_code=code, raw_term=syn, value=value, qualifier=qualifier,
                        start=m.start(), end=span_end,
                    )
                )
            break

    in_plan = False
    for line in text.splitlines():
        stripped = line.strip()
        plan_m = re.search(r"\bplan\s*:\s*(.*)$", stripped, re.IGNORECASE)
        if plan_m:
            in_plan = True
            rest = plan_m.group(1).strip()
            if rest:
                facts.plan_items.append(PlanItem(text=rest, topic=topic_for_text(rest)))
            continue
        if in_plan:
            bullet = re.match(r"^(?:[-*]|\d+[.)])\s*(.+)$", stripped)
            if bullet:
                item = bullet.group(1).strip()
                facts.plan_items.append(PlanItem(text=item, topic=topic_for_text(item)))
            elif stripped == "":
                continue
            else:
                in_plan = False

    seen_symptoms: set[str] = set()
    for phrase in sorted(SYMPTOM_LEXICON, key=len, reverse=True):
        sym_m = re.search(rf"\b{re.escape(phrase)}\b", low)
        if sym_m:
            category = SYMPTOM_LEXICON[phrase]
            if category not in seen_symptoms:
                seen_symptoms.add(category)
                facts.symptoms.append(
                    SymptomMention(
                        term=phrase, category=category,
                        start=sym_m.start(), end=sym_m.end(),
                    )
                )

    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if re.search(r"\b(declin\w*|defer\w*|postpon\w*)\b", sentence, re.IGNORECASE):
            facts.deferrals.append(
                DeferralMention(topic=topic_for_text(sentence), sentence=sentence.strip()[:200])
            )

    return facts
