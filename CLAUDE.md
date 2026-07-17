# CLAUDE.md

## Goal
Build a synthetic-data-only clinician helper with two parts:
1. **Note Review**: detect likely note/chart mismatches, ambiguity, missing plan items, and explicit deferrals.
2. **Patient Investigator**: a bounded LangGraph agent that searches patient history, checks trends and related signals, respects documented deferrals, and returns a small evidence-backed review checklist.

## Boundaries
- Synthetic data only.
- Do not diagnose, prescribe, order tests, assign urgency, or contact patients.
- Do not use claims, HL7, CPT, web search, or arbitrary SQL.
- Say **"not found in connected records"**, never claim something did not happen.
- Every output item must include evidence IDs, dates, and limitations.

## Stack
- Python 3.12
- FastAPI
- LangGraph
- PostgreSQL
- SQLAlchemy + Alembic
- Pydantic v2
- React + Vite + TypeScript
- Providers via OpenAI-compatible interface: Mock, Ollama, Ollama Cloud, Groq
- Optional LangSmith tracing via env vars

## Build Priorities
1. Deterministic analytics first: joins, deltas, slope, OLS slope, freshness, data quality, dual-trend alignment.
2. Note Review as retrieval + comparison + light semantic verification.
3. Patient Investigator as bounded supervisor + specialist nodes.
4. API and UI in the same MVP.
5. Synthea importer only after the MVP works on hand-authored fixtures.

## Data Model
Use normalized tables with `patient_id` and optional `encounter_id`:
- patients
- encounters
- conditions
- allergies
- medications
- observations
- procedures
- orders
- care_plans
- notes
- metric_snapshots
- deferrals
- investigation_runs
- investigation_steps

Keep `clinical_time`, `recorded_time`, `source_system`, `source_resource_id`, and `raw_source_json`.

## Required Engines
### Note Review
Input: `patient_id`, optional `encounter_id`, `current_note`
Flow:
- extract structured note facts and deferrals
- retrieve relevant chart facts and up to 3 prior note snippets
- compare deterministically
- use model only to verify ambiguous semantic conflicts
- return max 3 evidence-linked correction cards

### Patient Investigator
Input: `patient_id`, optional `encounter_id`, `current_note`, note facts/deferrals
Flow:
- load compact patient context
- scan deterministic signals
- create typed hypotheses
- use LangGraph supervisor to choose next bounded actions
- investigate trends, related signals, plans, note history
- apply deferral suppression
- evidence gate everything
- return max 4 evidence-linked review items

## Agent Rules
- Supervisor is the only routing agent.
- No recursive agent spawning.
- Only semantic tools, never raw SQL.
- Max 9 tool calls, max depth 2, max 3 parallel branches.
- Stop if evidence is sufficient, missing, unchanged after one deepen, or budget expires.

## Allowed Tools
- `get_patient_brief`
- `get_coverage`
- `get_metric_snapshots`
- `get_metric_series`
- `get_related_metric_snapshots`
- `get_active_conditions`
- `get_medications_and_allergies`
- `get_recent_plan_candidates`
- `get_followup_resolution`
- `search_prior_notes`
- `get_note_evidence`
- `get_evidence_details`

All tools must return bounded structured JSON.

## Output Rules
Each correction/review item must have:
- `item_id`
- `category`
- `title`
- `message`
- `confidence`
- `evidence_ids`
- `source_dates`
- `limitations`
- `deferral_state` if applicable

Allowed wording:
- "Consider reviewing..."
- "Available records show..."
- "A possible documentation mismatch was detected..."
- "This topic appears to have been deferred..."

Forbidden wording:
- diagnose / diagnosis claims
- prescribe / order / urgent / critical
- treatment advice
- patient-contact advice

## API
- `POST /v1/patients/{patient_id}/notes/review`
- `POST /v1/patients/{patient_id}/investigate`
- `GET /v1/patients/{patient_id}/context`
- `GET /v1/investigations/{run_id}`
- `GET /health`

## UI
One workbench page:
- patient selector
- current note editor
- Note Review action
- Investigate Patient action
- right-side tabs: Note Review / Patient Context
- evidence drawer
- developer-only trace drawer

## Fixtures and Tests
Start with 8 to 10 hand-authored synthetic patients covering:
- medication conflict
- allergy conflict
- rising trend
- stable trend
- dual aligned trend
- resolved plan
- unresolved plan
- explicit deferral
- missing coverage
- irrelevant signal suppression

Quality gates:
- Ruff, mypy, pytest, frontend typecheck/build all pass.
- No patient cross-join leakage.
- Every output has evidence IDs.
- Budgets and stop conditions tested.
- Use MockProvider if env vars are missing.

## Synthea
Do not start with Synthea.
Add it only after the full MVP works on fixtures.
Treat it as an importer into the same normalized schema.
