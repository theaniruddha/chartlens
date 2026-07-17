"""Local drug reference for the synthetic world.

Three narrow jobs:
1. vocabulary — the names/brands the note extractor can recognize,
2. class membership — so a charted allergy can be matched to a drug named in a
   note (e.g. septra -> sulfa),
3. typical use — so a purpose stated in a note ("septra ... for sleep") can be
   compared against what this drug is normally used for.

This is reference data, not patient data, and it is citable: every entry has a
stable evidence id (`ref-drug-<canonical>`) that resolves in the evidence
drawer, so an indication finding can be traced to exactly what it relied on.
It never carries dosing or recommendations — findings compare documentation to
this table and say nothing about what should be done.
"""

# canonical name -> classes
DRUG_CLASSES: dict[str, list[str]] = {
    # antibiotics
    "penicillin": ["penicillin", "antibiotic"],
    "amoxicillin": ["penicillin", "antibiotic"],
    "ampicillin": ["penicillin", "antibiotic"],
    "amoxicillin-clavulanate": ["penicillin", "antibiotic"],
    "sulfamethoxazole-trimethoprim": ["sulfa", "antibiotic"],
    "azithromycin": ["macrolide", "antibiotic"],
    "erythromycin": ["macrolide", "antibiotic"],
    "clarithromycin": ["macrolide", "antibiotic"],
    "ciprofloxacin": ["fluoroquinolone", "antibiotic"],
    "levofloxacin": ["fluoroquinolone", "antibiotic"],
    "doxycycline": ["tetracycline", "antibiotic"],
    "cephalexin": ["cephalosporin", "antibiotic"],
    "ceftriaxone": ["cephalosporin", "antibiotic"],
    "clindamycin": ["antibiotic"],
    "metronidazole": ["antibiotic"],
    "nitrofurantoin": ["antibiotic"],
    "vancomycin": ["antibiotic"],
    # diabetes
    "metformin": ["biguanide"],
    "glipizide": ["sulfonylurea"],
    "glyburide": ["sulfonylurea"],
    "insulin glargine": ["insulin"],
    "insulin lispro": ["insulin"],
    "empagliflozin": ["sglt2"],
    "semaglutide": ["glp1"],
    "sitagliptin": ["dpp4"],
    # cardiovascular
    "lisinopril": ["ace_inhibitor"],
    "enalapril": ["ace_inhibitor"],
    "losartan": ["arb"],
    "valsartan": ["arb"],
    "amlodipine": ["calcium_channel_blocker"],
    "hydrochlorothiazide": ["thiazide", "sulfa"],
    "chlorthalidone": ["thiazide", "sulfa"],
    "furosemide": ["loop_diuretic", "sulfa"],
    "spironolactone": ["potassium_sparing_diuretic"],
    "metoprolol": ["beta_blocker"],
    "carvedilol": ["beta_blocker"],
    "atenolol": ["beta_blocker"],
    # lipids
    "atorvastatin": ["statin"],
    "simvastatin": ["statin"],
    "rosuvastatin": ["statin"],
    "ezetimibe": ["lipid_agent"],
    # anticoagulation / antiplatelet
    "warfarin": ["anticoagulant"],
    "apixaban": ["anticoagulant"],
    "rivaroxaban": ["anticoagulant"],
    "clopidogrel": ["antiplatelet"],
    "aspirin": ["nsaid", "antiplatelet", "salicylate"],
    # analgesia
    "ibuprofen": ["nsaid"],
    "naproxen": ["nsaid"],
    "celecoxib": ["nsaid", "sulfa"],
    "acetaminophen": ["analgesic"],
    "tramadol": ["opioid"],
    "oxycodone": ["opioid"],
    "morphine": ["opioid"],
    "codeine": ["opioid"],
    "gabapentin": ["neuropathic_agent"],
    # psych / sleep
    "sertraline": ["ssri"],
    "fluoxetine": ["ssri"],
    "escitalopram": ["ssri"],
    "citalopram": ["ssri"],
    "trazodone": ["sedating_antidepressant"],
    "mirtazapine": ["sedating_antidepressant"],
    "amitriptyline": ["tricyclic"],
    "zolpidem": ["sedative_hypnotic"],
    "lorazepam": ["benzodiazepine"],
    "melatonin": ["supplement"],
    # gi
    "omeprazole": ["ppi"],
    "pantoprazole": ["ppi"],
    "famotidine": ["h2_blocker"],
    "ondansetron": ["antiemetic"],
    # respiratory / allergy
    "albuterol": ["bronchodilator"],
    "montelukast": ["leukotriene_modifier"],
    "loratadine": ["antihistamine"],
    "cetirizine": ["antihistamine"],
    "diphenhydramine": ["antihistamine"],
    "prednisone": ["corticosteroid"],
    # other
    "levothyroxine": ["thyroid_hormone"],
    "ferrous sulfate": ["mineral_supplement"],
    "allopurinol": ["xanthine_oxidase_inhibitor"],
}

# canonical name -> what this drug is normally used for. Absent = unknown, and
# an unknown drug is never flagged.
DRUG_USES: dict[str, list[str]] = {
    "penicillin": ["infection"],
    "amoxicillin": ["infection"],
    "ampicillin": ["infection"],
    "amoxicillin-clavulanate": ["infection"],
    "sulfamethoxazole-trimethoprim": ["infection"],
    "azithromycin": ["infection"],
    "erythromycin": ["infection"],
    "clarithromycin": ["infection"],
    "ciprofloxacin": ["infection"],
    "levofloxacin": ["infection"],
    "doxycycline": ["infection", "acne"],
    "cephalexin": ["infection"],
    "ceftriaxone": ["infection"],
    "clindamycin": ["infection"],
    "metronidazole": ["infection"],
    "nitrofurantoin": ["infection"],
    "vancomycin": ["infection"],
    "metformin": ["diabetes"],
    "glipizide": ["diabetes"],
    "glyburide": ["diabetes"],
    "insulin glargine": ["diabetes"],
    "insulin lispro": ["diabetes"],
    "empagliflozin": ["diabetes", "heart_failure"],
    "semaglutide": ["diabetes", "weight"],
    "sitagliptin": ["diabetes"],
    "lisinopril": ["hypertension", "heart_failure", "kidney_protection"],
    "enalapril": ["hypertension", "heart_failure"],
    "losartan": ["hypertension", "kidney_protection"],
    "valsartan": ["hypertension", "heart_failure"],
    "amlodipine": ["hypertension"],
    "hydrochlorothiazide": ["hypertension", "edema"],
    "chlorthalidone": ["hypertension"],
    "furosemide": ["edema", "heart_failure"],
    "spironolactone": ["heart_failure", "edema", "hypertension"],
    "metoprolol": ["hypertension", "heart_rate", "heart_failure"],
    "carvedilol": ["heart_failure", "hypertension"],
    "atenolol": ["hypertension", "heart_rate"],
    "atorvastatin": ["lipids"],
    "simvastatin": ["lipids"],
    "rosuvastatin": ["lipids"],
    "ezetimibe": ["lipids"],
    "warfarin": ["anticoagulation"],
    "apixaban": ["anticoagulation"],
    "rivaroxaban": ["anticoagulation"],
    "clopidogrel": ["anticoagulation"],
    "aspirin": ["anticoagulation", "pain", "fever"],
    "ibuprofen": ["pain", "inflammation", "fever"],
    "naproxen": ["pain", "inflammation"],
    "celecoxib": ["pain", "inflammation"],
    "acetaminophen": ["pain", "fever"],
    "tramadol": ["pain"],
    "oxycodone": ["pain"],
    "morphine": ["pain"],
    "codeine": ["pain", "cough"],
    "gabapentin": ["neuropathic_pain", "seizure"],
    "sertraline": ["depression", "anxiety"],
    "fluoxetine": ["depression", "anxiety"],
    "escitalopram": ["depression", "anxiety"],
    "citalopram": ["depression", "anxiety"],
    "trazodone": ["sleep", "depression"],
    "mirtazapine": ["depression", "sleep"],
    "amitriptyline": ["depression", "neuropathic_pain", "sleep"],
    "zolpidem": ["sleep"],
    "lorazepam": ["anxiety", "sleep", "seizure"],
    "melatonin": ["sleep"],
    "omeprazole": ["acid_reflux"],
    "pantoprazole": ["acid_reflux"],
    "famotidine": ["acid_reflux"],
    "ondansetron": ["nausea"],
    "albuterol": ["asthma"],
    "montelukast": ["asthma", "allergy_symptoms"],
    "loratadine": ["allergy_symptoms"],
    "cetirizine": ["allergy_symptoms"],
    "diphenhydramine": ["allergy_symptoms", "sleep"],
    "prednisone": ["inflammation"],
    "levothyroxine": ["thyroid"],
    "ferrous sulfate": ["anemia"],
    "allopurinol": ["gout"],
}

USE_LABELS: dict[str, str] = {
    "infection": "infection",
    "diabetes": "diabetes",
    "hypertension": "blood pressure",
    "heart_failure": "heart failure",
    "kidney_protection": "kidney protection",
    "heart_rate": "heart rate",
    "lipids": "cholesterol",
    "anticoagulation": "blood clot prevention",
    "pain": "pain",
    "neuropathic_pain": "nerve pain",
    "inflammation": "inflammation",
    "fever": "fever",
    "sleep": "sleep",
    "depression": "depression",
    "anxiety": "anxiety",
    "acid_reflux": "acid reflux",
    "nausea": "nausea",
    "asthma": "asthma",
    "allergy_symptoms": "allergy symptoms",
    "thyroid": "thyroid",
    "anemia": "anemia",
    "gout": "gout",
    "seizure": "seizure",
    "weight": "weight",
    "edema": "fluid retention",
    "acne": "acne",
    "cough": "cough",
}

# Purpose phrases a note may state -> use category. Longest matched first.
PURPOSE_LEXICON: dict[str, str] = {
    "trouble sleeping": "sleep",
    "difficulty sleeping": "sleep",
    "insomnia": "sleep",
    "sleep": "sleep",
    "urinary tract infection": "infection",
    "sinus infection": "infection",
    "chest infection": "infection",
    "skin infection": "infection",
    "infection": "infection",
    "sinusitis": "infection",
    "bronchitis": "infection",
    "cellulitis": "infection",
    "pneumonia": "infection",
    "uti": "infection",
    "blood pressure": "hypertension",
    "hypertension": "hypertension",
    "cholesterol": "lipids",
    "lipids": "lipids",
    "diabetes": "diabetes",
    "blood sugar": "diabetes",
    "blood glucose": "diabetes",
    "depression": "depression",
    "low mood": "depression",
    "anxiety": "anxiety",
    "acid reflux": "acid_reflux",
    "heartburn": "acid_reflux",
    "reflux": "acid_reflux",
    "nausea": "nausea",
    "asthma": "asthma",
    "wheezing": "asthma",
    "allergies": "allergy_symptoms",
    "hay fever": "allergy_symptoms",
    "thyroid": "thyroid",
    "anemia": "anemia",
    "gout": "gout",
    "seizures": "seizure",
    "seizure": "seizure",
    "nerve pain": "neuropathic_pain",
    "neuropathy": "neuropathic_pain",
    "tooth pain": "pain",
    "toothache": "pain",
    "headache": "pain",
    "back pain": "pain",
    "knee pain": "pain",
    "joint pain": "pain",
    "pain": "pain",
    "fever": "fever",
    "swelling": "edema",
    "fluid retention": "edema",
    "blood clots": "anticoagulation",
    "clot": "anticoagulation",
    "atrial fibrillation": "anticoagulation",
    "afib": "anticoagulation",
    "cough": "cough",
    "inflammation": "inflammation",
}

# brand/shorthand -> canonical name
DRUG_ALIASES: dict[str, str] = {
    "septra": "sulfamethoxazole-trimethoprim",
    "bactrim": "sulfamethoxazole-trimethoprim",
    "sulfamethoxazole": "sulfamethoxazole-trimethoprim",
    "sulfamethoxazole/trimethoprim": "sulfamethoxazole-trimethoprim",
    "tmp-smx": "sulfamethoxazole-trimethoprim",
    "cotrimoxazole": "sulfamethoxazole-trimethoprim",
    "augmentin": "amoxicillin-clavulanate",
    "amoxicillin/clavulanate": "amoxicillin-clavulanate",
    "ambien": "zolpidem",
    "eliquis": "apixaban",
    "xarelto": "rivaroxaban",
    "coumadin": "warfarin",
    "jardiance": "empagliflozin",
    "ozempic": "semaglutide",
    "januvia": "sitagliptin",
    "lipitor": "atorvastatin",
    "crestor": "rosuvastatin",
    "zocor": "simvastatin",
    "zoloft": "sertraline",
    "prozac": "fluoxetine",
    "lexapro": "escitalopram",
    "prilosec": "omeprazole",
    "protonix": "pantoprazole",
    "tylenol": "acetaminophen",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
    "aleve": "naproxen",
    "lasix": "furosemide",
    "hctz": "hydrochlorothiazide",
    "synthroid": "levothyroxine",
    "glucophage": "metformin",
    "neurontin": "gabapentin",
    "hydrochlorothiazide/lisinopril": "hydrochlorothiazide",
}

# Free-text allergy substances -> class, so a chart allergy can be compared to
# a drug mentioned in a note. Longest keys are matched first.
ALLERGY_SUBSTANCE_CLASSES: dict[str, str] = {
    "sulfamethoxazole-trimethoprim": "sulfa",
    "sulfamethoxazole": "sulfa",
    "sulfonamide antibiotics": "sulfa",
    "sulfonamides": "sulfa",
    "sulfonamide": "sulfa",
    "sulfa drugs": "sulfa",
    "sulfa": "sulfa",
    "bactrim": "sulfa",
    "septra": "sulfa",
    "penicillin g": "penicillin",
    "penicillin v": "penicillin",
    "penicillins": "penicillin",
    "penicillin": "penicillin",
    "amoxicillin": "penicillin",
    "ampicillin": "penicillin",
    "cephalosporins": "cephalosporin",
    "cephalosporin": "cephalosporin",
    "cephalexin": "cephalosporin",
    "nsaids": "nsaid",
    "nsaid": "nsaid",
    "ibuprofen": "nsaid",
    "naproxen": "nsaid",
    "aspirin": "salicylate",
    "macrolides": "macrolide",
    "macrolide": "macrolide",
    "azithromycin": "macrolide",
    "erythromycin": "macrolide",
    "fluoroquinolones": "fluoroquinolone",
    "fluoroquinolone": "fluoroquinolone",
    "ciprofloxacin": "fluoroquinolone",
    "levofloxacin": "fluoroquinolone",
    "statins": "statin",
    "statin": "statin",
    "atorvastatin": "statin",
    "opioids": "opioid",
    "opiates": "opioid",
    "opioid": "opioid",
    "codeine": "opioid",
    "morphine": "opioid",
    "oxycodone": "opioid",
    "tetracyclines": "tetracycline",
    "doxycycline": "tetracycline",
    "vancomycin": "vancomycin",
    "metformin": "biguanide",
    "levothyroxine": "thyroid_hormone",
    "gabapentin": "neuropathic_agent",
}

# Classes too broad to imply cross-reactivity on their own: a penicillin
# allergy must not flag azithromycin just because both are "antibiotic".
NON_SPECIFIC_CLASSES: set[str] = {"antibiotic", "analgesic", "supplement"}

# Every recognizable token: canonical names + aliases.
DRUG_VOCABULARY: list[str] = sorted(
    set(DRUG_CLASSES) | set(DRUG_ALIASES), key=len, reverse=True
)


def canonical_name(term: str) -> str:
    """Map any recognized term (brand, shorthand, generic) to its canonical name."""
    t = term.lower().strip()
    return DRUG_ALIASES.get(t, t)


def classes_for_drug(term: str) -> list[str]:
    return DRUG_CLASSES.get(canonical_name(term), [])


def classes_for_allergy_substance(substance: str) -> list[str]:
    """Classes implied by a free-text allergy substance on the chart."""
    text = substance.lower().strip()
    hits: list[str] = []
    for key in sorted(ALLERGY_SUBSTANCE_CLASSES, key=len, reverse=True):
        if key in text:
            hits.append(ALLERGY_SUBSTANCE_CLASSES[key])
            break
    # A substance naming a specific drug also implies that drug's classes.
    hits.extend(classes_for_drug(text))
    return list(dict.fromkeys(hits))


def uses_for_drug(term: str) -> list[str]:
    return DRUG_USES.get(canonical_name(term), [])


def purpose_category(text: str) -> tuple[str, str] | None:
    """Map a stated purpose phrase to (category, phrase_as_written)."""
    low = text.lower()
    for phrase in sorted(PURPOSE_LEXICON, key=len, reverse=True):
        if phrase in low:
            return PURPOSE_LEXICON[phrase], phrase
    return None


def use_label(category: str) -> str:
    return USE_LABELS.get(category, category.replace("_", " "))


def reference_evidence_id(term: str) -> str:
    return f"ref-drug-{canonical_name(term)}"


def reference_evidence(evidence_id: str) -> dict | None:
    """Resolve a `ref-drug-*` id so reference-backed findings are inspectable
    in the evidence drawer, exactly like chart records."""
    if not evidence_id.startswith("ref-drug-"):
        return None
    canonical = evidence_id.removeprefix("ref-drug-")
    if canonical not in DRUG_CLASSES:
        return None
    brands = sorted(a for a, c in DRUG_ALIASES.items() if c == canonical)
    return {
        "evidence_id": evidence_id,
        "kind": "drug_reference",
        "clinical_time": None,
        "source_system": "chartlens_drug_reference",
        "display": canonical,
        "classes": ", ".join(DRUG_CLASSES.get(canonical, [])),
        "typical_use": ", ".join(use_label(u) for u in DRUG_USES.get(canonical, [])) or None,
        "also_known_as": ", ".join(brands) or None,
        "limitations": (
            "Local reference table for synthetic data; not a formulary and not "
            "a source of dosing or recommendations."
        ),
    }


def display_name(term: str) -> str:
    canonical = canonical_name(term)
    if canonical != term.lower().strip():
        return f"{term} ({canonical})"
    return term
