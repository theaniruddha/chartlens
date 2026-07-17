import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { CoveragePanel } from "./components/CoveragePanel";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { ItemCard } from "./components/ItemCard";
import { LintEditor } from "./components/LintEditor";
import { PatientContextPanel } from "./components/PatientContextPanel";
import { PlaygroundPanel } from "./components/PlaygroundPanel";
import { SignalMap } from "./components/SignalMap";
import { TraceDrawer } from "./components/TraceDrawer";
import type {
  EvidenceDetail,
  InvestigationResult,
  NoteReviewResult,
  PatientContext,
  PatientRef,
  SessionRun,
} from "./types";

const SHOW_TRACE = import.meta.env.VITE_SHOW_TRACE !== "false";

type Tab = "findings" | "context" | "map" | "playground";

export default function App() {
  const [patients, setPatients] = useState<PatientRef[]>([]);
  const [patientId, setPatientId] = useState("");
  const [note, setNote] = useState("");
  const [context, setContext] = useState<PatientContext | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [review, setReview] = useState<NoteReviewResult | null>(null);
  const [investigation, setInvestigation] = useState<InvestigationResult | null>(null);
  const [tab, setTab] = useState<Tab>("findings");
  const [busy, setBusy] = useState<"review" | "investigate" | "all" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState<string>("");
  const [runs, setRuns] = useState<SessionRun[]>([]);

  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidence, setEvidence] = useState<EvidenceDetail[]>([]);
  const [mapEvidence, setMapEvidence] = useState<Map<string, EvidenceDetail>>(new Map());
  const [traceOpen, setTraceOpen] = useState(false);
  const [traceSteps, setTraceSteps] = useState<InvestigationResult["steps"]>([]);

  useEffect(() => {
    api
      .listPatients()
      .then((r) => setPatients(r.patients))
      .catch((e) => setError(`Could not load patients — is the API running? ${e}`));
    fetch("/health")
      .then((r) => r.json())
      .then((h) => setProvider(h.provider))
      .catch(() => setProvider("offline"));
  }, []);

  useEffect(() => {
    if (!patientId) {
      setContext(null);
      return;
    }
    setContextLoading(true);
    setContext(null);
    setReview(null);
    setInvestigation(null);
    setMapEvidence(new Map());
    setNoteSaved(null);
    setNote("");
    api
      .getContext(patientId)
      .then(setContext)
      .catch((e) => setError(String(e)))
      .finally(() => setContextLoading(false));
  }, [patientId]);

  const allItems = useMemo(
    () => [...(review?.cards ?? []), ...(investigation?.items ?? [])],
    [review, investigation]
  );

  // Pre-fetch evidence details for the signal map whenever findings change.
  useEffect(() => {
    const ids = Array.from(new Set(allItems.flatMap((i) => i.evidence_ids))).slice(0, 20);
    if (ids.length === 0 || !patientId) return;
    api
      .getEvidence(patientId, ids)
      .then((r) => setMapEvidence(new Map(r.evidence.map((e) => [e.evidence_id, e]))))
      .catch(() => undefined);
  }, [allItems, patientId]);

  const recordRun = useCallback(
    (rev: NoteReviewResult | null, inv: InvestigationResult | null) => {
      const p = patients.find((x) => x.patient_id === patientId);
      setRuns((prev) =>
        [
          {
            id: `${Date.now()}`,
            at: new Date().toLocaleTimeString(),
            patientId,
            patientName: p?.name ?? patientId,
            review: rev,
            investigation: inv,
          },
          ...prev,
        ].slice(0, 12)
      );
    },
    [patients, patientId]
  );

  async function runAll() {
    if (!patientId) return;
    setBusy("all");
    setError(null);
    try {
      const [rev, inv] = await Promise.all([
        note.trim() ? api.reviewNote(patientId, note) : Promise.resolve(null),
        api.investigate(patientId, note),
      ]);
      setReview(rev);
      setInvestigation(inv);
      recordRun(rev, inv);
      setTab("findings");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function runReviewOnly() {
    if (!patientId || !note.trim()) return;
    setBusy("review");
    setError(null);
    try {
      const rev = await api.reviewNote(patientId, note);
      setReview(rev);
      recordRun(rev, investigation);
      setTab("findings");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function runInvestigateOnly() {
    if (!patientId) return;
    setBusy("investigate");
    setError(null);
    try {
      const inv = await api.investigate(patientId, note);
      setInvestigation(inv);
      recordRun(review, inv);
      setTab("findings");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  const [noteSaved, setNoteSaved] = useState<string | null>(null);

  async function saveNoteToChart() {
    if (!patientId || !note.trim()) return;
    setBusy("review");
    setError(null);
    try {
      const r = await api.saveNote(patientId, note);
      setNoteSaved(r.evidence_id);
      await reloadContext();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function reloadContext() {
    if (!patientId) return;
    try {
      setContext(await api.getContext(patientId));
    } catch (e) {
      setError(String(e));
    }
  }

  async function reanalyzeFromPlayground() {
    await reloadContext();
    await runAll();
  }

  function restoreRun(run: SessionRun) {
    if (run.patientId !== patientId) setPatientId(run.patientId);
    // restore after context loads; results are self-contained
    setTimeout(() => {
      setReview(run.review);
      setInvestigation(run.investigation);
      setTab("findings");
    }, 0);
  }

  async function openEvidence(ids: string[]) {
    setEvidenceOpen(true);
    setEvidenceLoading(true);
    try {
      const r = await api.getEvidence(patientId, ids);
      setEvidence(r.evidence);
    } catch (e) {
      setError(String(e));
      setEvidence([]);
    } finally {
      setEvidenceLoading(false);
    }
  }

  async function openTrace() {
    if (!investigation) return;
    try {
      const r = await api.getInvestigation(investigation.run_id, true);
      setTraceSteps(r.steps ?? []);
      setTraceOpen(true);
    } catch (e) {
      setError(String(e));
    }
  }

  const brief = context?.brief;
  const findingsCount = allItems.length;

  return (
    <div className="workbench">
      <header>
        <div className="brand">
          <h1>ChartLens</h1>
          <span className="tagline">chart copilot · synthetic data only</span>
        </div>
        <select value={patientId} onChange={(e) => setPatientId(e.target.value)}>
          <option value="">Select patient…</option>
          {patients.map((p) => (
            <option key={p.patient_id} value={p.patient_id}>
              {p.mrn ?? p.patient_id} — {p.name}
            </option>
          ))}
        </select>
        {brief && (
          <div className="patient-chips">
            {brief.mrn && <span className="chip chip-mrn">{brief.mrn}</span>}
            <span className="chip">{brief.sex ?? "?"}</span>
            <span className="chip">b. {brief.birth_date?.slice(0, 10) ?? "?"}</span>
            <span className="chip chip-blue">{brief.active_conditions.length} conditions</span>
            <span className="chip chip-green">{brief.active_medication_count} meds</span>
            <span className={`chip ${brief.allergy_count > 0 ? "chip-red" : ""}`}>
              {brief.allergy_count} allergies
            </span>
            {context && context.active_deferrals.length > 0 && (
              <span className="chip chip-purple">
                {context.active_deferrals.length} deferral
                {context.active_deferrals.length > 1 ? "s" : ""}
              </span>
            )}
          </div>
        )}
        <span className={`provider-badge ${provider === "offline" ? "off" : ""}`}>
          model: {provider || "…"}
        </span>
      </header>

      {error && (
        <div className="error">
          <span>{error}</span>
          <button className="link" onClick={() => setError(null)}>
            dismiss
          </button>
        </div>
      )}

      <main>
        <section className="editor">
          <div className="panel-title">
            <h3>Draft note</h3>
            {review && (
              <span className="muted">
                parsed: {review.note_facts.medications_mentioned.length} meds ·{" "}
                {review.note_facts.plan_items.length} plan items ·{" "}
                {review.note_facts.deferral_mentions.length} deferrals
              </span>
            )}
          </div>
          <LintEditor
            patientId={patientId}
            note={note}
            onNoteChange={setNote}
            disabled={!patientId}
            onEvidenceClick={openEvidence}
            onProblemAdded={reloadContext}
          />
          <div className="actions">
            <button className="primary" disabled={!patientId || busy !== null} onClick={runAll}>
              {busy === "all" ? <span className="spinner" /> : null}
              {busy === "all" ? "Running copilot…" : "Run copilot"}
            </button>
            <button
              disabled={!patientId || !note.trim() || busy !== null}
              onClick={runReviewOnly}
              title="Note Review only"
            >
              {busy === "review" ? "Reviewing…" : "Review only"}
            </button>
            <button
              disabled={!patientId || busy !== null}
              onClick={runInvestigateOnly}
              title="Patient Investigator only"
            >
              {busy === "investigate" ? "Investigating…" : "Investigate only"}
            </button>
            <button
              disabled={!patientId || !note.trim() || busy !== null}
              onClick={saveNoteToChart}
              title="Persist this note into the chart; future analyses treat it as a prior note"
            >
              Save note to chart
            </button>
          </div>
          {noteSaved && (
            <p className="ok save-confirm">
              ✓ Saved to chart as <code>{noteSaved}</code> — it is now part of the record history.
            </p>
          )}

          {runs.length > 0 && (
            <div className="run-history">
              <h4>This session</h4>
              {runs.map((r) => (
                <button key={r.id} className="run-entry" onClick={() => restoreRun(r)}>
                  <span className="run-time">{r.at}</span>
                  <span className="run-patient">{r.patientId}</span>
                  <span className="muted">
                    {(r.review?.cards.length ?? 0) + (r.investigation?.items.length ?? 0)} findings
                    {r.investigation ? ` · ${r.investigation.tool_calls_used} calls` : ""}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="results">
          <div className="tabs">
            <button className={tab === "findings" ? "active" : ""} onClick={() => setTab("findings")}>
              Findings{findingsCount > 0 ? ` (${findingsCount})` : ""}
            </button>
            <button className={tab === "context" ? "active" : ""} onClick={() => setTab("context")}>
              Patient Context
            </button>
            <button className={tab === "map" ? "active" : ""} onClick={() => setTab("map")}>
              Signal Map
            </button>
            <button
              className={tab === "playground" ? "active" : ""}
              onClick={() => setTab("playground")}
            >
              Playground
              {context && context.playground_observations.length > 0
                ? ` (${context.playground_observations.length})`
                : ""}
            </button>
          </div>

          {tab === "findings" && (
            <div>
              {busy && (
                <div className="skeleton-stack">
                  <div className="skeleton" style={{ width: "90%", height: 72 }} />
                  <div className="skeleton" style={{ width: "90%", height: 72 }} />
                </div>
              )}

              {!busy && !review && !investigation && (
                <div className="empty-state">
                  <p>Nothing analyzed yet.</p>
                  <p className="muted">
                    Write a draft note and press <strong>Run copilot</strong>. Note Review checks
                    the draft against the chart; the Investigator digs through history and links
                    signals together. Every finding is evidence-linked.
                  </p>
                </div>
              )}

              {!busy && review && (
                <>
                  <div className="section-head">
                    <h3>Note review</h3>
                    <span className="muted">{review.cards.length} of max 3 cards</span>
                  </div>
                  {review.cards.length === 0 && (
                    <p className="ok">✓ No documentation issues detected in connected records.</p>
                  )}
                  {review.cards.map((c) => (
                    <ItemCard
                      key={c.item_id}
                      item={c}
                      history={context?.history}
                      onEvidenceClick={openEvidence}
                    />
                  ))}
                </>
              )}

              {!busy && investigation && (
                <>
                  <div className="section-head">
                    <h3>Investigation</h3>
                    <span className="muted">
                      run {investigation.run_id}
                      {SHOW_TRACE && (
                        <>
                          {" · "}
                          <button className="link" onClick={openTrace}>
                            trace
                          </button>
                        </>
                      )}
                    </span>
                  </div>
                  {investigation.items.length === 0 && (
                    <p className="ok">✓ No review items — no concerning signals in connected records.</p>
                  )}
                  {investigation.items.map((i) => (
                    <ItemCard
                      key={i.item_id}
                      item={i}
                      history={context?.history}
                      onEvidenceClick={openEvidence}
                    />
                  ))}

                  {investigation.signal_synthesis && (
                    <div className="synthesis">
                      <div className="section-head">
                        <h4>Signal synthesis</h4>
                        <span className="muted">
                          {investigation.signal_synthesis.provider} · derived signals only
                        </span>
                      </div>
                      {investigation.signal_synthesis.links.map((l, i) => (
                        <div className="synthesis-link" key={i}>
                          <p>{l.note}</p>
                          <div className="evidence-chips">
                            {l.evidence_ids.map((id) => (
                              <button
                                key={id}
                                className="chip chip-evidence"
                                onClick={() => openEvidence([id])}
                              >
                                {id}
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                      <p className="muted small">{investigation.signal_synthesis.limitations}</p>
                    </div>
                  )}

                  {investigation.coverage_report && (
                    <CoveragePanel
                      report={investigation.coverage_report}
                      toolCalls={investigation.tool_calls_used}
                      stopReason={investigation.stop_reason}
                    />
                  )}
                </>
              )}
            </div>
          )}

          {tab === "context" && (
            <PatientContextPanel
              context={context}
              loading={contextLoading}
              onEvidenceClick={openEvidence}
            />
          )}

          {tab === "map" && (
            <SignalMap items={allItems} evidence={mapEvidence} onEvidenceClick={openEvidence} />
          )}

          {tab === "playground" && (
            <PlaygroundPanel
              patientId={patientId}
              observations={context?.playground_observations ?? []}
              onChanged={reloadContext}
              onReanalyze={reanalyzeFromPlayground}
              busy={busy !== null}
            />
          )}
        </section>
      </main>

      <EvidenceDrawer
        open={evidenceOpen}
        loading={evidenceLoading}
        evidence={evidence}
        onClose={() => setEvidenceOpen(false)}
      />
      <TraceDrawer open={traceOpen} steps={traceSteps ?? []} onClose={() => setTraceOpen(false)} />
    </div>
  );
}
