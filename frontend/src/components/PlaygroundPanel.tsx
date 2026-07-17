import { useState } from "react";
import { api } from "../api";
import type { PlaygroundObservation, PlaygroundResult } from "../types";

const METRICS = [
  "hba1c",
  "sbp",
  "dbp",
  "weight",
  "ldl",
  "egfr",
  "creatinine",
  "potassium",
  "glucose",
  "hemoglobin",
];

export function PlaygroundPanel({
  patientId,
  observations,
  onChanged,
  onReanalyze,
  busy,
}: {
  patientId: string;
  observations: PlaygroundObservation[];
  onChanged: () => void;
  onReanalyze: () => void;
  busy: boolean;
}) {
  const [scenario, setScenario] = useState("");
  const [scenarioSummary, setScenarioSummary] = useState<string | null>(null);
  const [metric, setMetric] = useState("hba1c");
  const [trend, setTrend] = useState<"rising" | "falling" | "stable">("rising");
  const [nPoints, setNPoints] = useState(4);
  const [monthsBack, setMonthsBack] = useState(12);
  const [startValue, setStartValue] = useState<string>("");
  const [manualValue, setManualValue] = useState<string>("");
  const [manualDate, setManualDate] = useState<string>("");
  const [working, setWorking] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<PlaygroundResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!patientId) {
    return (
      <div className="empty-state">
        <p>No patient selected.</p>
        <p className="muted">Pick a patient, then simulate lab history here.</p>
      </div>
    );
  }

  async function simulateScenario() {
    if (!scenario.trim()) return;
    setWorking("scenario");
    setError(null);
    setScenarioSummary(null);
    try {
      const r = await api.playgroundScenario(patientId, scenario);
      const parts = [];
      if (r.inserted.length) parts.push(`${r.inserted.length} lab results`);
      if (r.conditions.length)
        parts.push(`${r.conditions.length} condition${r.conditions.length > 1 ? "s" : ""}`);
      if (r.note_evidence_id) parts.push(`1 note (${r.note_evidence_id})`);
      setScenarioSummary(parts.length ? `Added ${parts.join(", ")}.` : "Nothing usable extracted.");
      setLastResult(r);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(null);
    }
  }

  async function generate() {
    setWorking("generate");
    setError(null);
    try {
      const result = await api.playgroundGenerate(patientId, {
        metric_code: metric,
        trend,
        n_points: nPoints,
        months_back: monthsBack,
        start_value: startValue ? Number(startValue) : null,
      });
      setLastResult(result);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(null);
    }
  }

  async function addManual() {
    if (!manualValue) return;
    setWorking("manual");
    setError(null);
    try {
      const result = await api.playgroundAdd(patientId, [
        {
          metric_code: metric,
          value: Number(manualValue),
          clinical_time: manualDate ? new Date(manualDate).toISOString() : null,
        },
      ]);
      setLastResult(result);
      setManualValue("");
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(null);
    }
  }

  async function clearAll() {
    setWorking("clear");
    setError(null);
    try {
      await api.playgroundClear(patientId);
      setLastResult(null);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(null);
    }
  }

  return (
    <div className="playground">
      <p className="muted">
        Inject synthetic historical labs for this patient (tagged <code>playground</code>), then
        reanalyze to see how the agent picks up the new signals. Nothing here touches fixture or
        imported data — clear it any time.
      </p>
      {error && <div className="error">{error}</div>}

      <div className="pg-form">
        <h4>Describe a scenario</h4>
        <textarea
          className="scenario-input"
          rows={3}
          value={scenario}
          onChange={(e) => setScenario(e.target.value)}
          placeholder={
            "e.g. cholesterol borderline high, has diabetes but A1c normal, " +
            "patient complaining about tiredness and tooth pain"
          }
        />
        <button
          className="primary"
          disabled={working !== null || !scenario.trim()}
          onClick={simulateScenario}
        >
          {working === "scenario" ? "Simulating…" : "Simulate scenario with model"}
        </button>
        <span className="muted pg-hint">
          The model converts your description into lab values, conditions, and a symptom note —
          all validated locally before anything is stored.
        </span>
        {scenarioSummary && <p className="ok">{scenarioSummary}</p>}
      </div>

      <div className="pg-form">
        <h4>Generate a series</h4>
        <div className="pg-row">
          <label>
            Metric
            <select value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRICS.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            Trend
            <select value={trend} onChange={(e) => setTrend(e.target.value as typeof trend)}>
              <option value="rising">rising</option>
              <option value="falling">falling</option>
              <option value="stable">stable</option>
            </select>
          </label>
          <label>
            Points
            <input
              type="number"
              min={2}
              max={12}
              value={nPoints}
              onChange={(e) => setNPoints(Number(e.target.value))}
            />
          </label>
          <label>
            Span (months)
            <input
              type="number"
              min={1}
              max={36}
              value={monthsBack}
              onChange={(e) => setMonthsBack(Number(e.target.value))}
            />
          </label>
          <label>
            Start near (optional)
            <input
              type="number"
              placeholder="auto"
              value={startValue}
              onChange={(e) => setStartValue(e.target.value)}
            />
          </label>
        </div>
        <button className="primary" disabled={working !== null} onClick={generate}>
          {working === "generate" ? "Generating…" : "Generate with model"}
        </button>
        <span className="muted pg-hint">
          The model proposes values only; dates, bounds, and IDs are computed locally. Falls back
          to a deterministic generator if the model output is implausible.
        </span>
      </div>

      <div className="pg-form">
        <h4>Add a single result</h4>
        <div className="pg-row">
          <label>
            Value
            <input
              type="number"
              value={manualValue}
              onChange={(e) => setManualValue(e.target.value)}
              placeholder="e.g. 7.4"
            />
          </label>
          <label>
            Date
            <input
              type="date"
              value={manualDate}
              onChange={(e) => setManualDate(e.target.value)}
            />
          </label>
          <button disabled={working !== null || !manualValue} onClick={addManual}>
            {working === "manual" ? "Adding…" : `Add ${metric}`}
          </button>
        </div>
      </div>

      {lastResult && (
        <div className="pg-result">
          <span className="chip chip-green">
            inserted {lastResult.inserted.length} · generator: {lastResult.generator ?? "manual"}
          </span>
          {lastResult.values && (
            <code className="pg-values">{lastResult.values.join(" → ")}</code>
          )}
        </div>
      )}

      <div className="pg-list">
        <div className="section-head">
          <h4>Playground data on chart ({observations.length})</h4>
          <div>
            <button
              disabled={observations.length === 0 || working !== null}
              onClick={clearAll}
            >
              {working === "clear" ? "Clearing…" : "Clear playground data"}
            </button>
          </div>
        </div>
        {observations.length === 0 && (
          <p className="muted">None yet — generated or manual results will appear here.</p>
        )}
        {observations.length > 0 && (
          <table className="metrics-table">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
                <th>Date</th>
                <th>Evidence ID</th>
              </tr>
            </thead>
            <tbody>
              {observations.map((o) => (
                <tr key={o.evidence_id}>
                  <td>{o.metric_code}</td>
                  <td>
                    {o.value} {o.unit ?? ""}
                  </td>
                  <td>{o.clinical_time?.slice(0, 10)}</td>
                  <td>
                    <code>{o.evidence_id}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="pg-reanalyze">
        <button className="primary" disabled={busy || observations.length === 0} onClick={onReanalyze}>
          Reanalyze patient with this data
        </button>
      </div>
    </div>
  );
}
