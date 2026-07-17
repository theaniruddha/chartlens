import type { CoverageReport } from "../types";

const DOMAIN_LABELS: Record<string, string> = {
  conditions: "Active conditions",
  medications_active: "Active medications",
  medications_all: "All medications",
  allergies: "Allergies",
  metrics_tracked: "Metrics tracked",
  observations_metrics: "Metric types in chart",
  notes: "Notes scanned",
  care_plans: "Care plans",
  orders: "Order records",
  procedures: "Procedures",
  active_deferrals: "Active deferrals",
};

export function CoveragePanel({
  report,
  toolCalls,
  stopReason,
}: {
  report: CoverageReport;
  toolCalls: number;
  stopReason: string;
}) {
  return (
    <div className="coverage-panel">
      <div className="coverage-head">
        <h4>What was pulled in</h4>
        <span className="muted">
          {toolCalls} tool calls · stopped: {stopReason.replaceAll("_", " ")}
        </span>
      </div>
      <div className="coverage-grid">
        {Object.entries(report.domains).map(([key, count]) => (
          <div className="coverage-cell" key={key}>
            <span className={`coverage-count ${count === 0 ? "zero" : ""}`}>{count}</span>
            <span className="coverage-label">{DOMAIN_LABELS[key] ?? key}</span>
          </div>
        ))}
      </div>
      <div className="coverage-hyps">
        <span className="chip chip-blue">{report.hypotheses_total} hypotheses</span>
        <span className="chip chip-green">{report.hypotheses_investigated} investigated</span>
        {report.hypotheses_suppressed > 0 && (
          <span className="chip chip-purple">{report.hypotheses_suppressed} deferred/suppressed</span>
        )}
        {report.hypotheses_skipped > 0 && (
          <span className="chip chip-amber">{report.hypotheses_skipped} skipped (budget)</span>
        )}
      </div>
      {report.stale_metrics.length > 0 && (
        <p className="stale-warning">
          Freshness: {report.stale_metrics.join(", ")} may be out of date in connected records.
        </p>
      )}
      <details className="limitations">
        <summary>Tools used ({report.tools_used.length})</summary>
        <p>{report.tools_used.join(" · ")}</p>
        <p>{report.limitations}</p>
      </details>
    </div>
  );
}
