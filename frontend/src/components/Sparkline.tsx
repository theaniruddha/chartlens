import type { SeriesPoint } from "../types";

export function Sparkline({
  points,
  width = 132,
  height = 36,
  slope,
}: {
  points: SeriesPoint[];
  width?: number;
  height?: number;
  slope?: number | null;
}) {
  const vals = points.filter((p) => p.value != null) as (SeriesPoint & { value: number })[];
  if (vals.length < 2) {
    return <span className="spark-empty">{vals.length === 1 ? `${vals[0].value}` : "—"}</span>;
  }
  const pad = 4;
  const min = Math.min(...vals.map((p) => p.value));
  const max = Math.max(...vals.map((p) => p.value));
  const range = max - min || 1;
  const xs = vals.map((_, i) => pad + (i * (width - 2 * pad)) / (vals.length - 1));
  const ys = vals.map((p) => height - pad - ((p.value - min) / range) * (height - 2 * pad));
  const d = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  const moving = slope != null && Math.abs(slope) > 0.001;
  const color = !moving ? "var(--spark-flat)" : slope! > 0 ? "var(--spark-up)" : "var(--spark-down)";
  const areaD = `${d} L${xs[xs.length - 1].toFixed(1)},${height - 1} L${xs[0].toFixed(1)},${height - 1} Z`;
  return (
    <svg
      className="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="metric history"
    >
      <path d={areaD} fill={color} opacity={0.09} />
      <path d={d} fill="none" stroke={color} strokeWidth={1.8} strokeLinecap="round" />
      {xs.map((x, i) => (
        <circle key={i} cx={x} cy={ys[i]} r={i === xs.length - 1 ? 3 : 1.7} fill={color} />
      ))}
    </svg>
  );
}
