import { Sparkline } from "./Sparkline";
import type { ReviewItem, SeriesPoint } from "../types";

const CATEGORY_LABELS: Record<string, string> = {
  medication_mismatch: "Medication mismatch",
  allergy_conflict: "Allergy conflict",
  chart_value_mismatch: "Wording vs records",
  coverage_gap: "Not found in records",
  unresolved_plan: "Unresolved plan",
  trend: "Trend",
  dual_trend: "Dual trend",
  deferred_topic: "Deferred topic",
  symptom_followup: "Symptom follow-up",
  indication_mismatch: "Indication vs reference",
};

function metricCodesFor(item: ReviewItem): string[] {
  // snapshot evidence ids follow "<pid>-snap-<metric_code>"
  return item.evidence_ids
    .filter((e) => e.includes("-snap-"))
    .map((e) => e.split("-snap-")[1]);
}

export function ItemCard({
  item,
  history,
  onEvidenceClick,
}: {
  item: ReviewItem;
  history?: Record<string, SeriesPoint[]>;
  onEvidenceClick: (ids: string[]) => void;
}) {
  const codes = history ? metricCodesFor(item) : [];
  return (
    <div className={`card cat-${item.category}`}>
      <div className="card-head">
        <span className="badge">{CATEGORY_LABELS[item.category] ?? item.category}</span>
        <span className={`confidence conf-${item.confidence}`}>{item.confidence} confidence</span>
        {item.deferral_state && (
          <span className="badge deferred">deferral {item.deferral_state}</span>
        )}
      </div>
      <div className="card-body">
        <div className="card-text">
          <h4>{item.title}</h4>
          <p>{item.message}</p>
        </div>
        {codes.length > 0 && (
          <div className="card-sparks">
            {codes.map(
              (c) =>
                history?.[c] &&
                history[c].length > 1 && (
                  <div key={c} className="card-spark">
                    <Sparkline points={history[c]} />
                    <span className="spark-label">{c}</span>
                  </div>
                )
            )}
          </div>
        )}
      </div>
      <div className="card-foot">
        <div className="evidence-chips">
          {item.evidence_ids.map((id) => (
            <button key={id} className="chip chip-evidence" onClick={() => onEvidenceClick([id])}>
              {id}
            </button>
          ))}
        </div>
        {item.source_dates.length > 0 && (
          <span className="dates">{item.source_dates.join(" · ")}</span>
        )}
      </div>
      <details className="limitations">
        <summary>Limitations</summary>
        <p>{item.limitations}</p>
      </details>
    </div>
  );
}
