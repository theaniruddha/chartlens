import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Annotation, EvidenceDetail } from "../types";

const SEVERITY_LABEL: Record<string, string> = {
  error: "conflict",
  warn: "check",
  info: "note",
};

const CATEGORY_LABELS: Record<string, string> = {
  allergy_conflict: "Allergy conflict",
  medication_mismatch: "Medication mismatch",
  chart_value_mismatch: "Differs from chart",
  indication_mismatch: "Indication vs reference",
  value_range: "Outside reference range",
  coverage_gap: "Not found in records",
  symptom_followup: "Complaint without plan",
  unresolved_complaint: "Complaint without plan",
  new_dx: "Not on problem list",
  ambiguity: "May need detail",
};

export function LintEditor({
  patientId,
  note,
  onNoteChange,
  disabled,
  onEvidenceClick,
  onProblemAdded,
}: {
  patientId: string;
  note: string;
  onNoteChange: (v: string) => void;
  disabled: boolean;
  onEvidenceClick: (ids: string[]) => void;
  onProblemAdded: () => void;
}) {
  const [live, setLive] = useState(true);
  const [deep, setDeep] = useState(true);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [status, setStatus] = useState<string>("");
  const [active, setActive] = useState<Annotation | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const fastTimer = useRef<number | undefined>(undefined);
  const fullTimer = useRef<number | undefined>(undefined);
  const seq = useRef(0);
  const noteRef = useRef(note);
  noteRef.current = note;

  const runLint = useCallback(
    async (mode: "fast" | "full") => {
      const text = noteRef.current;
      if (!patientId || !live || text.trim().length < 8) {
        setAnnotations([]);
        return;
      }
      const mySeq = ++seq.current;
      try {
        const r = await api.lintNote(patientId, text, mode);
        if (mySeq !== seq.current || text !== noteRef.current) return; // stale
        setAnnotations(r.annotations);
        setStatus(
          mode === "full" && r.model
            ? `checked with ${r.model} · ${r.duration_ms} ms`
            : `checked · ${r.duration_ms} ms`
        );
      } catch {
        /* linting must never disturb writing */
      }
    },
    [patientId, live]
  );

  // reset on patient switch
  useEffect(() => {
    setAnnotations([]);
    setActive(null);
    setStatus("");
  }, [patientId]);

  function scheduleLint() {
    window.clearTimeout(fastTimer.current);
    window.clearTimeout(fullTimer.current);
    fastTimer.current = window.setTimeout(() => runLint("fast"), 700);
    if (deep) fullTimer.current = window.setTimeout(() => runLint("full"), 2500);
  }

  function handleChange(v: string) {
    onNoteChange(v);
    setActive(null);
    scheduleLint();
  }

  function handlePaste() {
    window.clearTimeout(fastTimer.current);
    window.clearTimeout(fullTimer.current);
    window.setTimeout(() => runLint(deep ? "full" : "fast"), 50);
  }

  function syncScroll() {
    if (textRef.current && backdropRef.current) {
      backdropRef.current.scrollTop = textRef.current.scrollTop;
      backdropRef.current.scrollLeft = textRef.current.scrollLeft;
    }
  }

  // Clicking inside the textarea: if the caret lands in an annotated span,
  // open that annotation's popover.
  function handleCaret() {
    const pos = textRef.current?.selectionStart ?? -1;
    const hit = annotations.find((a) => pos >= a.start && pos <= a.end);
    setActive(hit ?? null);
  }

  async function dismiss(a: Annotation) {
    setAnnotations((prev) => prev.filter((x) => x.annotation_id !== a.annotation_id));
    setActive(null);
    try {
      await api.annotationDecision(patientId, a.category, a.quote, "dismissed", noteRef.current);
    } catch {
      /* non-fatal */
    }
  }

  async function addToProblemList(a: Annotation) {
    if (!a.suggestion) return;
    try {
      await api.addProblem(patientId, a.suggestion);
      await api.annotationDecision(patientId, a.category, a.quote, "accepted", noteRef.current);
      setAnnotations((prev) => prev.filter((x) => x.annotation_id !== a.annotation_id));
      setActive(null);
      onProblemAdded();
    } catch {
      /* surfaced via context reload failure elsewhere */
    }
  }

  // Build highlighted segments (position order, skip overlaps).
  const ordered = [...annotations].sort((x, y) => x.start - y.start);
  const segments: { text: string; ann?: Annotation }[] = [];
  let cursor = 0;
  for (const a of ordered) {
    if (a.start < cursor || a.end > note.length) continue;
    if (a.start > cursor) segments.push({ text: note.slice(cursor, a.start) });
    segments.push({ text: note.slice(a.start, a.end), ann: a });
    cursor = a.end;
  }
  if (cursor < note.length) segments.push({ text: note.slice(cursor) });

  return (
    <div className="lint-wrap">
      <div className="lint-editor">
        <div ref={backdropRef} className="lint-backdrop" aria-hidden="true">
          {segments.map((seg, i) =>
            seg.ann ? (
              <mark
                key={i}
                className={`lint-mark sev-${seg.ann.severity} ${
                  active?.annotation_id === seg.ann.annotation_id ? "active" : ""
                }`}
              >
                {seg.text}
              </mark>
            ) : (
              <span key={i}>{seg.text}</span>
            )
          )}
          {"\n"}
        </div>
        <textarea
          ref={textRef}
          value={note}
          disabled={disabled}
          onChange={(e) => handleChange(e.target.value)}
          onPaste={handlePaste}
          onScroll={syncScroll}
          onClick={handleCaret}
          onKeyUp={(e) => {
            if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) handleCaret();
          }}
          placeholder={
            disabled
              ? "Select a patient first."
              : "Write or paste the draft note…\n\nSubjective: …\nMedications: …\nAssessment: …\nPlan:\n- …"
          }
          rows={16}
          spellCheck={false}
        />
      </div>

      <div className="lint-bar">
        <label className="lint-toggle">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
          Live checks
        </label>
        <label className="lint-toggle" title="Sends the draft text to the model for deeper checks">
          <input
            type="checkbox"
            checked={deep}
            disabled={!live}
            onChange={(e) => setDeep(e.target.checked)}
          />
          Deep check (model)
        </label>
        <span className="muted lint-status">{status}</span>
        {annotations.length > 0 && (
          <span className="chip chip-amber">{annotations.length} flags</span>
        )}
      </div>

      {active && (
        <div className={`lint-popover sev-${active.severity}`}>
          <div className="card-head">
            <span className="badge">{CATEGORY_LABELS[active.category] ?? active.category}</span>
            <span className="muted">
              {SEVERITY_LABEL[active.severity]} · {active.confidence} ·{" "}
              {active.source === "model" ? "model" : "records"}
            </span>
          </div>
          <p>{active.message}</p>
          <div className="card-foot">
            {active.evidence_ids.length > 0 && (
              <div className="evidence-chips">
                {active.evidence_ids.map((id) => (
                  <button key={id} className="chip chip-evidence" onClick={() => onEvidenceClick([id])}>
                    {id}
                  </button>
                ))}
              </div>
            )}
            <div className="lint-actions">
              {active.actions.includes("add_to_problem_list") && (
                <button className="primary" onClick={() => addToProblemList(active)}>
                  Add "{active.suggestion}" to problem list
                </button>
              )}
              <button onClick={() => dismiss(active)}>Dismiss</button>
            </div>
          </div>
        </div>
      )}

      {annotations.length > 0 && !active && (
        <div className="lint-list">
          {annotations.map((a) => (
            <button key={a.annotation_id} className="lint-item" onClick={() => setActive(a)}>
              <span className={`lint-dot sev-${a.severity}`} />
              <span className="lint-quote">"{a.quote.slice(0, 32)}{a.quote.length > 32 ? "…" : ""}"</span>
              <span className="muted">{CATEGORY_LABELS[a.category] ?? a.category}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export type { EvidenceDetail };
