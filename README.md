# ChartLens

Synthetic-data-only clinician helper with two engines:

1. **Note Review** — detects likely note/chart mismatches, missing plan items, coverage gaps,
   and explicit deferrals. Deterministic retrieval + comparison; a model is used only to verify
   ambiguous semantic conflicts.
2. **Patient Investigator** — a bounded LangGraph agent (supervisor + specialist nodes) that
   scans deterministic signals, forms typed hypotheses, investigates trends / related signals /
   plans / note history, respects documented deferrals, and returns an evidence-backed review
   checklist.

**Boundaries**: synthetic data only. It never diagnoses, prescribes, assigns urgency, or
suggests contacting patients. Absent data is always reported as
*"not found in connected records"*. Every output item carries evidence IDs, source dates, and
limitations. A wording validator rejects forbidden vocabulary at emit time.

## Stack

Python 3.12+ · FastAPI · LangGraph · PostgreSQL · SQLAlchemy + Alembic · Pydantic v2 ·
React + Vite + TypeScript · LLM providers via one OpenAI-compatible gateway
(Mock / Ollama / Ollama Cloud / Groq — MockProvider is used automatically when no keys are set).

## Layout

```
backend/
  app/
    analytics/      # deterministic: delta, OLS slope, freshness, dual-trend alignment
    db/             # session, patient-scoped repository, fixture loader
    models/         # 14 normalized tables (evidence IDs = source_resource_id)
    note_review/    # extract -> retrieve -> compare -> verify -> max 3 cards
    investigator/   # LangGraph supervisor graph + run persistence
    providers/      # provider-neutral LLM gateway
    schemas/        # ReviewItem + wording/evidence validator
    tools/          # the 12 allowed semantic tools (bounded JSON)
    api/            # FastAPI routes
  alembic/          # migrations
  fixtures/patients # 10 hand-authored synthetic patients + expected outcomes
  tests/            # unit, fixtures-as-oracles, isolation, budgets, semantic paths, live LLM, importer, API
frontend/           # single workbench page (Vite + React + TS)
```

## Run locally

Prerequisites: PostgreSQL 16 running with databases `chartlens` and `chartlens_test`
(see `.env.example` for the connection URLs), `uv`, Node 20+.

```bash
# 0) configure
cp .env.example .env          # adjust DATABASE_URL if needed

# 1) backend setup
cd backend
uv sync
uv run alembic upgrade head
uv run python scripts/load_fixtures.py   # loads the 10 synthetic patients

# 2) run the API
uv run uvicorn app.main:app --port 8000

# 3) frontend (second terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5173 (proxies /v1 to :8000)
```

If PostgreSQL is not installed system-wide, a rootless portable install works:

```bash
# one-time
mkdir -p ~/.local/pg16 && curl -sL https://github.com/theseus-rs/postgresql-binaries/releases/download/16.4.0/postgresql-16.4.0-x86_64-unknown-linux-gnu.tar.gz | tar xz -C ~/.local/pg16 --strip-components=1
~/.local/pg16/bin/initdb -D ~/.local/pg16/data -U chartlens --auth=trust -E UTF8
# each session
~/.local/pg16/bin/pg_ctl -D ~/.local/pg16/data -o "-p 5433" -l ~/.local/pg16/pg.log start
~/.local/pg16/bin/createdb -h localhost -p 5433 -U chartlens chartlens
~/.local/pg16/bin/createdb -h localhost -p 5433 -U chartlens chartlens_test
```

## API

| Route | Purpose |
|---|---|
| `POST /v1/patients/{id}/notes/review` | max 3 evidence-linked correction cards |
| `POST /v1/patients/{id}/investigate` | bounded investigation, max 4 review items |
| `GET /v1/patients/{id}/context` | compact patient context for the workbench |
| `GET /v1/investigations/{run_id}` | run result; `?include_steps=true` adds the dev trace |
| `GET /v1/patients` | patient list for the selector |
| `POST /v1/patients/{id}/evidence` | resolve evidence IDs for the drawer |
| `GET /health` | liveness + active provider |

## Agent budgets

Max 9 tool calls, max depth 2, max 3 investigated branches, max 4 items — enforced in graph
state (not prompts) and covered by tests. Stop reasons: `evidence_sufficient`, `completed`,
`no_hypotheses`, `budget_exhausted`, `branch_budget_exhausted`.

## Tracing (LangSmith)

Set `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` in `.env` and the whole
investigation is traced: a `chartlens.investigate` root span, each LangGraph
node beneath it, and every model call (`chartlens.llm.complete_json`,
`chartlens.semantic_verify`, `chartlens.link_signals`) with patient/run ids as
metadata. `GET /health` reports `"tracing": "langsmith"` when it is live.

`LANGSMITH_ENDPOINT` must match the deployment your key belongs to — a US-cloud
key against `aws.api.smith.langchain.com` returns 403 and every export is
dropped silently. Default is US cloud (`https://api.smith.langchain.com`).
Traces leave the machine, which is why this is opt-in; synthetic data only.

## Providers

Set `LLM_PROVIDER` to `mock` (default), `ollama`, `ollama_cloud`, or `groq` plus the matching
key in `.env`. The tested cloud setup is `LLM_PROVIDER=ollama_cloud` with
`OLLAMA_MODEL=gemma4:31b`. The model is used for exactly two bounded, stateless calls:

1. **Semantic verification** — yes/no/unsure on ambiguous wording conflicts
   (e.g. draft says "A1c stable" while records show +0.2/month).
2. **Signal synthesis** — one compact call over *derived* signals only (slopes, deltas,
   categories — never raw notes) that links movements together; output is evidence-gated
   (metric references must map to real snapshot evidence) and wording-validated.

Provider failures degrade to `unsure`/no-synthesis, so only deterministic findings are ever
emitted without a working model. Raw prompts and completions never appear in API responses.

Each investigate response also carries a **coverage report** — a deterministic checklist of
every record domain pulled in (counts, staleness, hypotheses investigated/suppressed/skipped,
tools used) so the reviewer can see nothing was silently skipped.

## Tests & quality gates

```bash
cd backend
uv run pytest -q          # 105 tests incl. live model tests (needs chartlens_test database)
uv run ruff check app tests scripts
uv run mypy app
cd ../frontend
npm run typecheck && npm run build
```

Fixtures double as oracles: each of the 10 synthetic patients bundles chart rows, a draft
note, and the exact categories each engine must (and must not) emit — including deferral
suppression, resolved vs unresolved plans, and irrelevant-signal suppression.

## Inline note linting

The draft editor checks the note as you write, Grammarly-style, in two tiers:

- **fast** (`POST /v1/patients/{ref}/notes/lint`, `mode: fast`) — deterministic,
  ~20 ms, runs ~0.7 s after typing pauses. Span-anchored flags for allergy
  conflicts, medication mismatches, indication-vs-reference, values that differ
  from the chart, values outside the citable metric reference ranges
  (`ref-metric-<code>`), results not found in connected records, and symptom
  mentions with no plan item.
- **full** (`mode: full`) — adds one stateless model call (~1 s warm) over the
  draft plus a compact chart context. Catches open-vocabulary complaints
  ("less sleep" -> sleep problem), asserted diagnoses missing from the problem
  list (one-click "Add to problem list"), and vague statements. The model must
  quote the text it comments on; unanchorable quotes and forbidden wording are
  dropped. The "Deep check" toggle controls this tier — it is the only place
  raw note text reaches the model. `LINT_MODEL` overrides the model used.

Every dismissed flag is remembered per patient (`annotation_events`) and never
shown again; the accept/dismiss stream is stored as practice data for later
fine-tuning.

## Drug reference

`app/reference/drugs.py` is a small local reference table for the synthetic
world. It is reference data, not patient data, and it does three things:

1. **vocabulary** — the drug/brand names the note extractor recognizes
   (septra, bactrim, ambien, ... resolve to a canonical name),
2. **class membership** — a charted allergy is matched to a drug named in a
   note via shared *specific* class (septra <-> sulfa). Generic classes like
   "antibiotic" never imply cross-reactivity, so a penicillin allergy does not
   flag azithromycin,
3. **typical use** — the purpose stated in a note ("septra ... for sleep") is
   compared with what the drug is normally used for.

Every entry is citable: `ref-drug-<canonical>` resolves in the evidence drawer
like any chart record. The table holds no dosing and no recommendations — an
`indication_mismatch` card reports that documentation and the reference
disagree, and says nothing about what to do. Findings are emitted only when
both the drug and the stated purpose are known; anything unknown stays silent.

## Patient identifiers

Patients carry an internal `patient_id` and a human-facing `mrn`. Every
`/v1/patients/{ref}` route accepts either — the API resolves the reference and
scopes everything to the internal id. Fixture MRNs look like `MRN-24003`;
Synthea patients keep their FHIR MR identifier.

## Clinician notes

`POST /v1/patients/{ref}/notes` persists a note into the chart
(source_system `clinician`); the workbench has a "Save note to chart" button.
Saved notes immediately count as prior notes for both engines.

## Playground (simulate history & scenarios)

The Playground tab injects synthetic data for a patient, tagged
`source_system=playground`, then lets you reanalyze:

- `POST /v1/patients/{ref}/playground/scenario` — free-text scenario
  ("cholesterol borderline high, patient complaining about tiredness and
  tooth pain") converted by the model into lab values, conditions, and a
  symptom note. Every field is validated locally (known metrics, plausible
  ranges) before storage; symptoms land in a note that the investigator's
  symptom check picks up.

- `POST /v1/patients/{ref}/playground/generate` — the model (gemma4:31b when
  configured) proposes values only; dates, bounds, and evidence IDs are always
  computed locally, and a series that doesn't actually carry the requested
  trend is regenerated deterministically.
- `POST /v1/patients/{ref}/playground/observations` — add manual results.
- `DELETE /v1/patients/{ref}/playground` — remove all playground rows.

Snapshots are rebuilt after every change, so the agent sees the new signals on
the next run. "Clear playground data" removes playground observations, notes,
and conditions in one step.

### Trend detection notes

Trend classification uses a 24-month recency window (old history informs
latest values but cannot dilute a recent change) and per-metric slope
thresholds (`SLOPE_THRESHOLDS`), including hemoglobin/glucose/potassium.
Symptom mentions in notes (tiredness, tooth pain, dizziness, ...) that no plan
item addresses are flagged as `symptom_followup` items with note evidence.

## Synthea (optional importer)

Synthea stays outside the core: it is only an importer into the same schema.

```bash
bash scripts/run_synthea.sh 3 Massachusetts   # downloads a portable JRE + jar on first run
cd backend && uv run python scripts/import_synthea.py
```

The importer maps FHIR R4 bundles (Patient, Encounter, Condition,
AllergyIntolerance, MedicationRequest, Observation, Procedure, CarePlan,
DocumentReference notes) into the normalized tables. Numeric observations are
kept when their LOINC code maps to a known metric (see `LOINC_METRICS`);
unmapped ones are counted and skipped. Re-importing a bundle is a no-op.
Snapshots are rebuilt per imported patient. Imported patients appear in the
workbench like any other.

## PostgreSQL 17 + pgvector

`bash scripts/setup_pg17.sh` (needs sudo, one time) creates the role +
databases on port 5432 and enables pgvector. The app runs against whichever
`DATABASE_URL` is configured; pgvector is enabled in readiness for semantic
note retrieval behind `search_prior_notes`.

## Deferred (intentionally)

- Synthea importer (only after MVP per spec; same normalized schema)
- Embeddings / vector search (PostgreSQL full-text search is sufficient for fixtures)
- Async/background investigations (response already matches the run resource shape)
- LangSmith tracing wiring beyond env passthrough; auth; multi-page UI
