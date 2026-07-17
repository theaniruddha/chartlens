import type { EvidenceDetail } from "../types";

export function EvidenceDrawer({
  open,
  loading,
  evidence,
  onClose,
}: {
  open: boolean;
  loading: boolean;
  evidence: EvidenceDetail[];
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <div className="drawer">
      <div className="drawer-head">
        <h3>Evidence</h3>
        <button onClick={onClose}>Close</button>
      </div>
      {loading && <p className="muted">Loading…</p>}
      {!loading && evidence.length === 0 && (
        <p className="muted">Not found in connected records.</p>
      )}
      {evidence.map((e) => (
        <div className="evidence-item" key={e.evidence_id}>
          <div className="card-head">
            <span className="badge">{e.kind}</span>
            <code>{e.evidence_id}</code>
          </div>
          <dl>
            {Object.entries(e)
              .filter(([k]) => !["evidence_id", "kind"].includes(k))
              .map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd>
                </div>
              ))}
          </dl>
        </div>
      ))}
    </div>
  );
}
