export interface ReviewItem {
  item_id: string;
  category: string;
  title: string;
  message: string;
  confidence: string;
  evidence_ids: string[];
  source_dates: string[];
  limitations: string;
  deferral_state?: string | null;
}

export interface NoteReviewResult {
  patient_id: string;
  cards: ReviewItem[];
  note_facts: {
    medications_mentioned: { name: string; action: string | null }[];
    metric_claims: { metric_code: string; value: number | null; qualifier: string | null }[];
    plan_items: { text: string; topic: string | null }[];
    deferral_mentions: { topic: string | null; sentence: string }[];
  };
  generated_at: string;
}

export interface CoverageReport {
  domains: Record<string, number>;
  stale_metrics: string[];
  hypotheses_total: number;
  hypotheses_investigated: number;
  hypotheses_suppressed: number;
  hypotheses_skipped: number;
  tools_used: string[];
  limitations: string;
}

export interface SignalSynthesis {
  provider: string;
  links: { note: string; metric_codes: string[]; evidence_ids: string[] }[];
  limitations: string;
}

export interface InvestigationResult {
  run_id: string;
  patient_id: string;
  status: string;
  stop_reason: string;
  tool_calls_used: number;
  items: ReviewItem[];
  coverage_report?: CoverageReport | null;
  signal_synthesis?: SignalSynthesis | null;
  steps?: TraceStep[];
}

export interface TraceStep {
  step_index: number;
  node: string;
  action: string;
  detail: string | null;
  payload: unknown;
}

export interface PatientRef {
  patient_id: string;
  mrn: string | null;
  name: string;
}

export interface PlaygroundObservation {
  evidence_id: string;
  metric_code: string;
  display?: string;
  value: number;
  unit: string | null;
  clinical_time: string | null;
}

export interface Annotation {
  annotation_id: string;
  category: string;
  severity: "error" | "warn" | "info";
  start: number;
  end: number;
  quote: string;
  message: string;
  evidence_ids: string[];
  confidence: string;
  source: "deterministic" | "model";
  actions: string[];
  suggestion?: string | null;
}

export interface LintResult {
  annotations: Annotation[];
  mode: string;
  model: string | null;
  duration_ms: number;
}

export interface PlaygroundResult {
  inserted: PlaygroundObservation[];
  snapshots: { metric_code: string; direction: string; n_points: number }[];
  generator?: string;
  values?: number[];
}

export interface EvidenceDetail {
  evidence_id: string;
  kind: string;
  clinical_time: string | null;
  [key: string]: unknown;
}

export interface SeriesPoint {
  evidence_id: string;
  value: number | null;
  unit: string | null;
  time: string | null;
}

export interface MetricSnapshot {
  evidence_id: string;
  metric_code: string;
  display: string;
  latest_value: number | null;
  unit: string | null;
  latest_time: string | null;
  delta: number | null;
  slope_per_month: number | null;
  n_points: number | null;
}

export interface PatientContext {
  brief: {
    patient_id: string;
    name: string;
    sex: string | null;
    birth_date: string | null;
    mrn?: string | null;
    active_conditions: { evidence_id: string; display: string }[];
    active_medication_count: number;
    allergy_count: number;
    last_encounter: { evidence_id: string; type: string | null; time: string | null } | null;
  };
  coverage: {
    metrics: { metric_code: string; n_points: number; latest_time: string | null; stale: boolean }[];
    note_count: number;
  };
  snapshots: MetricSnapshot[];
  history: Record<string, SeriesPoint[]>;
  medications_allergies: {
    medications: {
      evidence_id: string;
      name: string;
      dose: string | null;
      frequency: string | null;
      status: string;
    }[];
    allergies: {
      evidence_id: string;
      substance: string;
      reaction: string | null;
      severity: string | null;
    }[];
  };
  recent_notes: {
    evidence_id: string;
    note_type: string;
    time: string | null;
    snippet: string;
    source_system?: string;
  }[];
  visits: {
    evidence_id: string;
    encounter_type: string | null;
    reason: string | null;
    time: string | null;
    source_system?: string;
  }[];
  playground_observations: PlaygroundObservation[];
  active_deferrals: {
    evidence_id: string;
    topic: string;
    deferred_until: string | null;
    reason: string | null;
  }[];
}

export interface SessionRun {
  id: string;
  at: string;
  patientId: string;
  patientName: string;
  review: NoteReviewResult | null;
  investigation: InvestigationResult | null;
}
