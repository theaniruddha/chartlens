from app.note_review.extract import extract_note_facts


def test_medication_actions():
    facts = extract_note_facts(
        "Medications: Continue metformin 500 mg.\nPlan:\n- Start amoxicillin 500 mg.\n"
        "- Stopped lisinopril."
    )
    actions = {m.name: m.action for m in facts.med_mentions}
    assert actions["metformin"] == "continue"
    assert actions["amoxicillin"] == "start"
    assert actions["lisinopril"] == "stop"


def test_metric_claims_value_and_qualifier():
    facts = extract_note_facts("A1c was 7.2 today. Last potassium was normal.")
    claims = {c.metric_code: c for c in facts.metric_claims}
    assert claims["hba1c"].value == 7.2
    assert claims["potassium"].qualifier == "normal"


def test_metric_mention_without_claim_ignored():
    facts = extract_note_facts("Plan:\n- Recheck A1c in 3 months.")
    assert facts.metric_claims == []


def test_plan_items_inline_and_block():
    facts = extract_note_facts(
        "Anemia work-up. Plan:\n- Schedule colonoscopy to evaluate.\n- Recheck CBC in 3 months."
    )
    topics = [p.topic for p in facts.plan_items]
    assert "colonoscopy" in topics


def test_deferral_sentences():
    facts = extract_note_facts("Patient declines colonoscopy at this time; defer for 6 months.")
    assert len(facts.deferrals) >= 1
    assert facts.deferrals[0].topic == "colonoscopy"


def test_symptom_extraction():
    facts = extract_note_facts(
        "Patient complains of tiredness and tooth pain. Also reports feeling dizzy."
    )
    cats = {s.category for s in facts.symptoms}
    assert cats == {"fatigue", "dental_pain", "dizziness"}


def test_symptom_phrase_preferred_over_substring():
    facts = extract_note_facts("Reports tooth pain since last week.")
    assert facts.symptoms[0].term == "tooth pain"


def test_open_vocabulary_drug_and_phrasal_action():
    # Regression: "septra" was invisible (closed lexicon) and "asked to take"
    # was not an action, so nothing reached the comparison layer.
    facts = extract_note_facts(
        "Subjective: trouble sleeping.\nAsked to take septra medicine for sleep."
    )
    assert len(facts.med_mentions) == 1
    mention = facts.med_mentions[0]
    assert mention.term == "septra"
    assert mention.name == "sulfamethoxazole-trimethoprim"  # canonical
    assert mention.action == "start"


def test_brand_names_resolve_to_canonical():
    facts = extract_note_facts(
        "Plan:\n- Start Bactrim DS.\n- Take Ambien at night.\n- Continue Lipitor."
    )
    resolved = {m.name: m.action for m in facts.med_mentions}
    assert resolved["sulfamethoxazole-trimethoprim"] == "start"
    assert resolved["zolpidem"] == "start"
    assert resolved["atorvastatin"] == "continue"


def test_longer_drug_name_wins_over_substring():
    facts = extract_note_facts("Plan:\n- Start amoxicillin-clavulanate 875 mg.")
    assert [m.name for m in facts.med_mentions] == ["amoxicillin-clavulanate"]
