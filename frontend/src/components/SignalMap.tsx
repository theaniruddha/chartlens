import type { EvidenceDetail, ReviewItem } from "../types";

const CAT_COLORS: Record<string, string> = {
  medication_mismatch: "#b45309",
  allergy_conflict: "#b91c1c",
  chart_value_mismatch: "#b45309",
  coverage_gap: "#6b7280",
  unresolved_plan: "#0e7490",
  trend: "#1d4ed8",
  dual_trend: "#4338ca",
  deferred_topic: "#7c3aed",
  symptom_followup: "#be185d",
  indication_mismatch: "#a16207",
};

const KIND_ICONS: Record<string, string> = {
  medication: "Rx",
  allergy: "Al",
  observation: "Ob",
  metric_snapshot: "Tr",
  note: "Nt",
  deferral: "Df",
  encounter: "En",
  condition: "Cx",
  procedure: "Pr",
  order: "Or",
  care_plan: "Cp",
  drug_reference: "Ref",
};

export function SignalMap({
  items,
  evidence,
  onEvidenceClick,
}: {
  items: ReviewItem[];
  evidence: Map<string, EvidenceDetail>;
  onEvidenceClick: (ids: string[]) => void;
}) {
  if (items.length === 0) {
    return (
      <div className="empty-state">
        <p>No findings yet.</p>
        <p className="muted">
          Run the copilot — every finding will appear here, linked to the exact chart records
          that support it.
        </p>
      </div>
    );
  }

  const evidenceIds = Array.from(new Set(items.flatMap((i) => i.evidence_ids)));
  const rowH = 64;
  const leftX = 8;
  const leftW = 300;
  const rightX = 480;
  const rightW = 290;
  const height = Math.max(items.length, evidenceIds.length) * rowH + 24;
  const itemY = (i: number) =>
    12 + i * rowH + (Math.max(0, evidenceIds.length - items.length) * rowH) / 2;
  const evY = (i: number) =>
    12 + i * rowH + (Math.max(0, items.length - evidenceIds.length) * rowH) / 2;
  const evIndex = new Map(evidenceIds.map((id, i) => [id, i]));

  return (
    <div className="signal-map">
      <div className="signal-map-legend">
        <span>Findings</span>
        <span>Chart evidence</span>
      </div>
      <svg viewBox={`0 0 780 ${height}`} className="signal-map-svg" role="img">
        {items.flatMap((item, ii) =>
          item.evidence_ids.map((eid) => {
            const ei = evIndex.get(eid) ?? 0;
            const y1 = itemY(ii) + 22;
            const y2 = evY(ei) + 22;
            const x1 = leftX + leftW;
            const x2 = rightX;
            const mx = (x1 + x2) / 2;
            return (
              <path
                key={`${item.item_id}-${eid}`}
                d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
                fill="none"
                stroke={CAT_COLORS[item.category] ?? "#64748b"}
                strokeWidth={1.6}
                opacity={0.55}
              />
            );
          })
        )}
        {items.map((item, i) => (
          <g key={item.item_id} transform={`translate(${leftX},${itemY(i)})`}>
            <rect
              width={leftW}
              height={44}
              rx={8}
              fill="var(--node-bg)"
              stroke={CAT_COLORS[item.category] ?? "#64748b"}
              strokeWidth={1.5}
            />
            <text x={12} y={19} className="map-title">
              {item.title.length > 36 ? item.title.slice(0, 35) + "…" : item.title}
            </text>
            <text x={12} y={35} className="map-sub">
              {item.category.replaceAll("_", " ")} · {item.confidence}
            </text>
          </g>
        ))}
        {evidenceIds.map((eid, i) => {
          const detail = evidence.get(eid);
          const kind = detail?.kind ?? "record";
          const label =
            (detail?.display as string) ||
            (detail?.name as string) ||
            (detail?.substance as string) ||
            (detail?.topic as string) ||
            (detail?.note_type ? `${detail.note_type} note` : eid);
          const date = detail?.clinical_time?.slice(0, 10) ?? "";
          return (
            <g
              key={eid}
              transform={`translate(${rightX},${evY(i)})`}
              className="map-evidence"
              onClick={() => onEvidenceClick([eid])}
            >
              <rect width={rightW} height={44} rx={8} fill="var(--node-bg)" stroke="#b9c4d0" />
              <rect width={30} height={44} rx={8} fill="#eef2f6" />
              <text x={15} y={27} textAnchor="middle" className="map-kind">
                {KIND_ICONS[kind] ?? "•"}
              </text>
              <text x={40} y={19} className="map-title">
                {String(label).length > 30 ? String(label).slice(0, 29) + "…" : String(label)}
              </text>
              <text x={40} y={35} className="map-sub">
                {kind.replaceAll("_", " ")}
                {date ? ` · ${date}` : ""} · {eid}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="muted">Click any evidence node to open the full record.</p>
    </div>
  );
}
