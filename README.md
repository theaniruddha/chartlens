# ChartLens

## Patient-context intelligence and documentation validation

**ChartLens is a synthetic-data prototype for a patient-context sidecar that helps clinicians find relevant information faster, identify meaningful changes across the chart, and validate AI-generated documentation against patient-specific evidence.**

Clinicians often have only a short window (PCP's have 1 to 3 minutes on avg in Canada) to understand a patient. Relevant information can be spread across encounters, observations, medications, conditions, prior notes, plans, and other connected systems.a

ChartLens explores how a deterministic signal layer and bounded agentic reasoning can collect that context, investigate meaningful changes, and present the result for review while keeping the clinician in control.

> **Prototype, not a clinical product.** All data is synthetic. The system does not diagnose, prescribe, assign urgency, or recommend patient contact.

---

## The problem

A clinician may spend valuable time moving between parts of an EHR to reconstruct a patient's current picture.

Some information is easy to find individually:

- a lab result
- a medication
- a diagnosis
- a prior note
- a plan

The harder problem is seeing how those pieces relate.

For example:

- A single lab value may not look unusual, while the **trend** is changing meaningfully.
- Two measurements may move together in a way that deserves review.
- A current condition may provide context for a changing observation.
- A prior plan or deferral may change how a current finding should be interpreted.
- An ambient scribe may produce a fluent note that contains a changed value, medication, duration, or terminology.
- Information may exist in connected systems, but the clinician still has to spend time finding and assembling it.

ChartLens is a prototype exploring how to reduce that information-hunting burden without adding another workflow for the clinician.

---

# Where ChartLens fits

## Workflow 1: Patient-context sidecar

```text
EHR / labs / medications / prior notes / other connected sources
                              |
                              v
                         ChartLens
                              |
              +---------------+----------------+
              | Patient-context intelligence   |
              |                                |
              | • Short-term changes           |
              | • Longitudinal trends          |
              | • Combined / aligned signals   |
              | • Conditions and medications   |
              | • Prior notes and plans        |
              | • Evidence and provenance      |
              | • Potential gaps                |
              +---------------+----------------+
                              |
                              v
                 Concise evidence-backed view
                              |
                              v
                    Clinician / staff review
                              |
                              v
                   Documentation / downstream
                       clinical workflows
```

ChartLens is designed as a **sidecar layer** beside the EHR. It brings relevant information from existing systems into one reviewable context.

In a production setting, the input layer could connect to available HL7, FHIR, EHR, laboratory, medication, and other clinical interfaces. This prototype uses synthetic data and a normalized internal model instead.

---

## Workflow 2: Ambient documentation validation

ChartLens can also sit downstream of voice, ambient scribe, or TTS-based documentation.

```text
Patient conversation
        |
        v
Voice / ambient scribe / TTS
        |
        v
Draft clinical note
        |
        v
     ChartLens
        |
        v
+--------------------------------+
| Patient-specific validation    |
|                                |
| • Does it align with the chart?|
| • Did transcription change     |
|   something important?         |
| • Are values consistent?       |
| • Are medications correct?     |
| • Are conditions relevant?     |
| • Are important trends missed? |
| • Are plans unresolved?        |
+--------------------------------+
        |
        v
Evidence-linked review
        |
        v
Clinician decides
```

Ambient documentation creates the draft note. ChartLens adds a patient-specific validation step before the note is finalized. It checks whether the generated documentation is consistent with the available record.

For example, if speech is converted into a fluent note but a medication, value, duration, or clinical term differs from the available patient record, the system can flag the discrepancy for review.

The same validation layer could run alongside autocomplete or voice-driven documentation and return review points inside the existing workflow.

---

# What the prototype demonstrates

## 1. Patient-specific note review

**Does the draft note align with the available patient record?**

ChartLens compares note content with structured and reference evidence and can identify:

- medication mismatches
- allergy conflicts
- indication mismatches
- values that disagree with the chart
- unsupported or missing information
- coverage gaps
- unresolved plans

Findings are evidence-linked and include source dates and limitations.

## 2. Cross-signal investigation

**What could be missed when information is reviewed one record at a time?**

The prototype tracks deterministic signals such as:

- deltas
- trends
- freshness
- aligned trends
- metric series
- conditions
- medications
- plans
- prior notes

The agent starts from deterministic signals and investigates whether an unusual or potentially important change is:

- isolated or persistent
- part of a longer-term pattern
- related to another observation
- associated with a medication or condition
- reflected in a prior plan
- potentially introduced by AI-assisted documentation
- missing the evidence needed for review

```text
Deterministic signals
        |
        v
Anomaly / meaningful change
        |
        v
Agent forms a bounded hypothesis
        |
        v
Investigates related evidence
        |
        +--> trends
        +--> observations
        +--> medications
        +--> conditions
        +--> plans
        +--> prior notes
        |
        v
Evidence reconciliation
        |
        v
Evidence-backed review item
        |
        v
Clinician decides
```

The prototype performs **cross-signal correlation and evidence synthesis**. It does not perform causal inference.

The agent can investigate validated domain relationships and surface the relevant patient evidence. For example, a clinic-defined medication signal pack could associate a newly documented medication with relevant patient measurements and check whether those measurements are present, current, changing, or inconsistent with the record. The clinician reviews the result and decides what to do.

## 3. Documentation linting

The note editor has two validation tiers.

**Fast**

Deterministic, patient-context checks for:

- medication conflicts
- allergy conflicts
- indication/reference mismatches
- values that differ from the chart
- values outside known reference ranges
- results not found in connected records
- symptoms without a corresponding plan

**Full**

Adds a bounded model call for semantic cases such as:

- open-vocabulary complaints
- asserted diagnoses missing from the problem list
- vague statements

The model must anchor its comments to text in the draft. Unanchorable findings are discarded.

---

# A concrete example

Suppose the chart contains:

```text
HbA1c:
6.2 -> 6.9 -> 7.8

Condition:
Type 2 diabetes
```

A note says:

```text
Assessment:
A1c stable.

Plan:
Continue omeprazole for cholesterol.
```

ChartLens can independently identify:

```text
1. Possible chart-value mismatch
   "stable" conflicts with the observed trend.

2. Medication mismatch
   omeprazole was not found in connected records.

3. Indication mismatch
   the stated purpose does not match the local drug reference.
```

The result contains:

```text
Finding
Evidence
Confidence
Source
Limitation
```

The clinician decides what to do.

---

# Why deterministic signals + agents?

The architecture gives deterministic logic and semantic reasoning different jobs.

### Deterministic layer

Examples:

- calculate a trend
- calculate a delta
- determine freshness
- compare a value with a reference
- identify matching evidence
- enforce budgets
- validate schemas
- verify evidence IDs

### Agentic layer

The agent is useful when the question becomes:

> "Which of these signals are worth investigating together?"

It can:

- form typed hypotheses
- select from bounded tools
- investigate related signals
- inspect plans and history
- respect documented deferrals
- stop when evidence is sufficient

### LLM layer

The LLM is deliberately narrow.

It is used for semantic tasks where deterministic logic is insufficient, such as interpreting whether wording like "stable" is consistent with a derived trend.

The design principle is:

> **Use deterministic logic for measurable signals. Use agents to investigate relationships. Use LLMs for semantic judgment.**

---

# Unintrusive by design

The clinician interacts with the review result, not the underlying agent.

The intended interaction is closer to a sidecar:

```text
Clinician workflow
       |
       +---- continues normally
       |
       +---- relevant evidence appears when warranted
                       |
                       v
               Review if useful
                       |
                       v
                    Decide
```

The system surfaces **evidence-backed items** when there is enough signal to warrant review.

Agent execution is bounded in graph state:

- maximum 9 tool calls
- maximum depth 2
- maximum 3 investigated branches
- maximum 4 review items

When the budget is exhausted, the system suppresses the partial finding.

---

# Potential extensions

The current prototype focuses on the patient-context and validation layer.

The same foundation could support additional clinic or specialty capabilities.

### EHR and clinical data integration

Connect the context layer to:

- HL7 interfaces
- FHIR resources
- EHR systems
- laboratory systems
- medication systems
- prior documentation
- other clinical data sources

### Specialty-specific signal packs

A clinic could define the domain signals that matter to its workflow.

For example:

```text
Primary care
    -> chronic disease trends
    -> medication history
    -> preventive care context

Cardiology
    -> longitudinal cardiac measurements
    -> medication context
    -> related observations

Diabetes care
    -> glucose / HbA1c trends
    -> medication context
    -> longitudinal changes
```

The architecture can keep the **signal computation and domain rules deterministic**, while the agent decides which available signals warrant investigation.

### Longitudinal patient context

Maintain both:

- **short-term context**: what changed recently
- **long-term context**: what has been changing over months or years

This can help distinguish a new change from an established patient pattern.

### Ambient documentation validation

The validation layer could operate after:

- ambient scribing
- voice-to-text
- TTS-based documentation
- autocomplete
- other AI-assisted note generation

It could check whether generated content is consistent with patient-specific evidence before the clinician accepts it.

Examples include possible transcription changes to:

- medication names
- doses or measurements
- dates or durations
- anatomical terms
- symptoms or other patient-specific terminology

The goal is to detect when generated documentation conflicts with available patient evidence and give the clinician a focused review point.

### Domain-specific signal packs

A clinic or specialty could define deterministic relationships that are useful for longitudinal tracking.

For example:

```text
Medication / event added
        |
        v
Relevant patient signals identified
        |
        v
Track over time
        |
        +--> expected data present?
        +--> data current?
        +--> meaningful change?
        +--> related signals changing?
        +--> conflicting evidence?
        |
        v
Surface only when review is warranted
```

A medication-related signal could connect a newly documented therapy with measurements relevant to that therapy. The system could then track whether those measurements are present, current, and changing in the patient's record.

For example, a validated domain rule could associate a medication such as candesartan with relevant potassium and renal-function measurements. The system could track whether those measurements are available, current, and changing, then surface a review item when the configured evidence condition is met. It would not generate a generic alert each time the medication appears.

The design principle is **non-intrusive monitoring of patient-specific evidence**. The system should add context when it has useful patient-specific information, not repeat general clinical knowledge.

### Longer-term data-finder agents

A natural extension is an agent whose job is to **find and reconcile the evidence needed for a clinical workflow**.

For example:

```text
Clinical workflow / question
            |
            v
      Required evidence
            |
            v
       Data-finder agent
            |
            +--> EHR
            +--> labs
            +--> medications
            +--> prior notes
            +--> other connected sources
            |
            v
   Reconcile dates / duplicates /
   missing or conflicting evidence
            |
            v
       Evidence bundle
            |
            v
       Clinician review
```

This can support longitudinal workflows while keeping clinical decisions with the clinician.

These are **future product directions**. They are not part of the current prototype.

---

# A possible downstream RCM connection

ChartLens does not currently perform coding.

The broader idea is that better upstream clinical context and documentation can provide better inputs to downstream workflows.

```text
Patient encounter
       |
       v
Patient-context intelligence
       |
       v
More complete / consistent documentation
       |
       v
Clinical coding workflow
       |
       v
ICD / CPT / modifiers
       |
       v
RCM
```

This creates a potential bridge between clinical documentation intelligence and downstream revenue-cycle workflows without making the current prototype responsible for coding decisions.

---

# Trust and safety boundaries

ChartLens is intentionally conservative.

It:

- uses synthetic data only
- does not diagnose
- does not prescribe
- does not assign urgency
- does not recommend contacting patients
- does not treat missing information as a negative finding
- reports absent information as **"not found in connected records"**
- attaches evidence IDs, source dates, and limitations to findings
- rejects forbidden wording at output time
- fails closed when evidence is insufficient

The prototype supports clinician review. Clinical decisions remain with the clinician.

---

# Privacy-oriented architecture

The prototype also applies data minimization. Most model calls can operate without raw clinical text.

Most analysis operates on derived signals, categories, and evidence IDs.

```text
Clinical records
      |
      v
Deterministic processing
      |
      v
Derived signals
      |
      +------> deterministic findings
      |
      v
Minimum context required
      |
      v
Semantic model call
```

Current model paths:

| Call | Input | Raw note text |
|---|---|---|
| Semantic verification | metric + derived slope/delta | No |
| Signal synthesis | derived signals + categories + evidence IDs | No |
| Deep note lint | draft note + compact context | Yes |
| Playground generation | constrained synthetic inputs | No |

The deep lint tier is the only analysis path that intentionally sends the draft note to the model.

For a production deployment with real clinical data, appropriate privacy, security, access control, audit, retention, residency, and vendor controls would still need to be implemented and validated.

---

# Prototype boundaries

This is a **product and engineering prototype**. It is not a production clinical system.

The prototype uses:

- synthetic patient data
- a normalized PostgreSQL model
- local/reference clinical data
- bounded agent execution
- deterministic signal analysis
- optional LLM semantic reasoning

Current prototype boundaries:

- production EHR connectivity
- production HL7/FHIR interfaces
- clinical decision support
- clinical coding recommendations
- validated clinical outcomes
- production PHI handling
- autonomous clinical actions

---

# Architecture

```text
backend/
  app/
    analytics/       # deterministic signals: delta, slope, freshness, trend alignment
    db/              # session, patient-scoped repository, fixture loader
    models/          # normalized clinical data model
    note_review/     # extract -> retrieve -> compare -> verify
    investigator/    # LangGraph supervisor + specialist nodes
    providers/       # provider-neutral LLM gateway
    reference/       # local drug + metric reference data
    schemas/         # typed review items + evidence validation
    tools/           # bounded semantic tools
    api/             # FastAPI routes
  alembic/           # migrations
  fixtures/patients  # synthetic patients + expected outcomes
  tests/             # unit, regression, isolation, budget and semantic tests

frontend/
  React + Vite + TypeScript
```

## Core architecture

```text
                    Patient data
                         |
                         v
                Normalized data model
                         |
                         v
              Deterministic signal layer
                         |
             +-----------+-----------+
             |                       |
             v                       v
        Note Review             Investigator
             |                       |
             v                       v
       Evidence retrieval      Typed hypotheses
             |                       |
             v                       v
      Semantic verification    Bounded tools
             |                       |
             +-----------+-----------+
                         |
                         v
               Evidence validation
                         |
                         v
                 Clinician review
```

---

# Quality and evaluation

Evaluation is built into the system.

The synthetic fixtures double as test oracles. Each patient contains expected and prohibited outcomes, including:

- medication and allergy conflicts
- rising/stable trends
- aligned trends
- resolved vs unresolved plans
- explicit deferrals
- missing coverage
- irrelevant-signal suppression

Current test suite:

```bash
cd backend
uv run pytest -q
uv run ruff check app tests scripts
uv run mypy app

cd ../frontend
npm run typecheck
npm run build
```

The current suite contains **136 tests**.

The agent also produces a deterministic coverage report showing which record domains were examined and which hypotheses were investigated, suppressed, or skipped.

---

# Observability

LangSmith tracing is optional.

When enabled, the investigation exposes:

```text
Investigation
    |
    +-- LangGraph node
    |
    +-- tool call
    |
    +-- model call
    |
    +-- evidence / result
```

Tracing is opt-in because traces leave the local machine.

The prototype uses synthetic data only.

---

# Run locally

## Prerequisites

- PostgreSQL
- `uv`
- Node 20+

The included setup script can create the PostgreSQL role, databases, and pgvector extension.

```bash
cp .env.example .env

cd backend
uv sync
uv run alembic upgrade head
uv run python scripts/load_fixtures.py
uv run uvicorn app.main:app --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at:

```text
http://localhost:5173
```

The API runs at:

```text
http://localhost:8000
```

---

# Providers

The application uses one provider-neutral gateway.

Supported configurations:

```text
mock
ollama
ollama_cloud
groq
```

The mock provider is the default so the project can run without an external model key.

The tested cloud configuration uses Ollama Cloud with `gemma4:31b`.

---

# API

| Route | Purpose |
|---|---|
| `POST /v1/patients/{id}/notes/review` | Evidence-linked note review |
| `POST /v1/patients/{id}/investigate` | Bounded patient investigation |
| `POST /v1/patients/{id}/notes/lint` | Inline note linting |
| `GET /v1/patients/{id}/context` | Patient context |
| `GET /v1/investigations/{run_id}` | Investigation result and optional trace |
| `GET /v1/patients` | Patient list |
| `POST /v1/patients/{id}/evidence` | Evidence lookup |
| `GET /health` | Liveness and provider status |

---

# Example

A draft note can contain:

```text
Assessment: A1c stable.

Plan:
- Continue omeprazole for cholesterol.
```

while the synthetic chart contains a rising HbA1c trend and no matching medication record.

ChartLens returns evidence-linked review items. The clinician remains responsible for the note and any clinical decision.

Example categories:

```text
chart_value_mismatch
medication_mismatch
indication_mismatch
```

The clinician reviews the evidence and decides what to change.

---

# What this prototype is really demonstrating

ChartLens demonstrates a pattern for **trustworthy, low-friction clinical AI**:

```text
Fragmented clinical information
            |
            v
     Deterministic signals
            |
            v
      Bounded investigation
            |
            v
       Evidence synthesis
            |
            v
     Patient-aware validation
            |
            v
      Concise clinician view
            |
            v
       Human decision
```

The longer-term idea is a **patient-context intelligence layer** that quietly maintains useful clinical context, follows meaningful signals over time, and sits beside the workflows clinicians already use.

The agent investigates when a signal warrants attention. The intended experience is selective and low-noise.

The prototype currently demonstrates this workflow:

- detect a potentially meaningful signal
- investigate its context
- connect related evidence
- validate AI-generated documentation
- show why the system surfaced it
- leave the decision with the clinician

A production implementation would require validated clinical workflows, real interoperability, clinical evaluation, security controls, and domain collaboration.

---

## Status

**Prototype / demonstration**

Built to explore:

- patient-context intelligence
- longitudinal and short-term signal tracking
- cross-signal investigation
- evidence-grounded agentic workflows
- AI-generated note validation
- bounded agents
- deterministic + LLM hybrid reasoning
- privacy-oriented model context minimization
- evaluation and regression testing

All clinical data in this repository is synthetic.
