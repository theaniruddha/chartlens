import { Sparkline } from "./Sparkline";
import type { PatientContext } from "../types";

export function PatientContextPanel({
  context,
  loading,
  onEvidenceClick,
}: {
  context: PatientContext | null;
  loading: boolean;
  onEvidenceClick: (ids: string[]) => void;
}) {
  if (loading) {
    return (
      <div className="skeleton-stack">
        <div className="skeleton" style={{ width: "50%" }} />
        <div className="skeleton" style={{ width: "80%" }} />
        <div className="skeleton" style={{ width: "70%" }} />
        <div className="skeleton" style={{ width: "60%" }} />
      </div>
    );
  }
  if (!context) {
    return (
      <div className="empty-state">
        <p>No patient selected.</p>
        <p className="muted">Choose a patient to see their connected records.</p>
      </div>
    );
  }
  const { brief, snapshots, history, medications_allergies, recent_notes, visits, active_deferrals } =
    context;
  return (
    <div className="context-panel">
      <section>
        <h4>Metric history</h4>
        {snapshots.length === 0 && <p className="muted">No metrics in connected records.</p>}
        <table className="metrics-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>History</th>
              <th>Latest</th>
              <th>Δ/month</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {snapshots.map((s) => (
              <tr key={s.evidence_id}>
                <td>
                  <strong>{s.display}</strong>
                  <div className="muted">{s.n_points ?? 0} results</div>
                </td>
                <td>
                  <Sparkline points={history[s.metric_code] ?? []} slope={s.slope_per_month} />
                </td>
                <td>
                  {s.latest_value ?? "—"} {s.unit ?? ""}
                  <div className="muted">{s.latest_time?.slice(0, 10)}</div>
                </td>
                <td className={slopeClass(s.slope_per_month)}>
                  {s.slope_per_month != null ? s.slope_per_month.toFixed(2) : "—"}
                </td>
                <td>
                  <button className="link" onClick={() => onEvidenceClick([s.evidence_id])}>
                    open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="context-cols">
        <section>
          <h4>Conditions</h4>
          <ul className="fact-list">
            {brief.active_conditions.map((c) => (
              <li key={c.evidence_id}>
                {c.display}
                <button className="link" onClick={() => onEvidenceClick([c.evidence_id])}>
                  #
                </button>
              </li>
            ))}
            {brief.active_conditions.length === 0 && <li className="muted">none recorded</li>}
          </ul>

          <h4>Medications</h4>
          <ul className="fact-list">
            {medications_allergies.medications.map((m) => (
              <li key={m.evidence_id}>
                {m.name} {m.dose} {m.frequency}
                <span className={`pill pill-${m.status}`}>{m.status}</span>
                <button className="link" onClick={() => onEvidenceClick([m.evidence_id])}>
                  #
                </button>
              </li>
            ))}
            {medications_allergies.medications.length === 0 && (
              <li className="muted">none recorded</li>
            )}
          </ul>

          <h4>Allergies</h4>
          <ul className="fact-list">
            {medications_allergies.allergies.map((a) => (
              <li key={a.evidence_id}>
                <span className="allergy">{a.substance}</span>
                {a.reaction ? ` — ${a.reaction}` : ""} {a.severity ? `(${a.severity})` : ""}
              </li>
            ))}
            {medications_allergies.allergies.length === 0 && (
              <li className="muted">none recorded</li>
            )}
          </ul>

          {active_deferrals.length > 0 && (
            <>
              <h4>Active deferrals</h4>
              <ul className="fact-list">
                {active_deferrals.map((d) => (
                  <li key={d.evidence_id}>
                    <span className="pill pill-deferred">{d.topic}</span> until{" "}
                    {d.deferred_until?.slice(0, 10) ?? "unspecified"}
                    {d.reason ? <span className="muted"> — {d.reason}</span> : null}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section>
          <h4>Visit timeline</h4>
          {(!visits || visits.length === 0) && <p className="muted">No visits recorded.</p>}
          <div className="timeline">
            {visits?.map((v) => (
              <div className="timeline-entry" key={v.evidence_id}>
                <div className="timeline-dot visit" />
                <div className="timeline-body">
                  <div className="muted">
                    {v.time?.slice(0, 10)} · {v.encounter_type?.replace(/_/g, " ") ?? "visit"}{" "}
                    <button className="link" onClick={() => onEvidenceClick([v.evidence_id])}>
                      open
                    </button>
                  </div>
                  {v.reason && <p>{v.reason}</p>}
                </div>
              </div>
            ))}
          </div>

          <h4>Note timeline</h4>
          {recent_notes.length === 0 && <p className="muted">No prior notes.</p>}
          <div className="timeline">
            {recent_notes.map((n) => (
              <div className="timeline-entry" key={n.evidence_id}>
                <div className="timeline-dot" />
                <div className="timeline-body">
                  <div className="muted">
                    {n.time?.slice(0, 10)} · {n.note_type}{" "}
                    <button className="link" onClick={() => onEvidenceClick([n.evidence_id])}>
                      open
                    </button>
                  </div>
                  <p>{n.snippet}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function slopeClass(slope: number | null): string {
  if (slope == null || Math.abs(slope) < 0.01) return "muted";
  return slope > 0 ? "slope-up" : "slope-down";
}
