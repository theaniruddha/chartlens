import type { TraceStep } from "../types";

export function TraceDrawer({
  open,
  steps,
  onClose,
}: {
  open: boolean;
  steps: TraceStep[];
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div className="drawer trace">
      <div className="drawer-head">
        <h3>Investigation trace (dev)</h3>
        <button onClick={onClose}>Close</button>
      </div>
      {steps.length === 0 && <p className="muted">No steps recorded.</p>}
      <ol>
        {steps.map((s) => (
          <li key={s.step_index}>
            <strong>{s.node}</strong> → {s.action}
            {s.detail ? <span className="muted"> {s.detail}</span> : null}
            <details>
              <summary>payload</summary>
              <pre>{JSON.stringify(s.payload, null, 2)}</pre>
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}
