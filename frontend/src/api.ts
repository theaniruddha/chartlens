import type {
  EvidenceDetail,
  LintResult,
  InvestigationResult,
  NoteReviewResult,
  PatientContext,
  PatientRef,
  PlaygroundResult,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listPatients: () => request<{ patients: PatientRef[] }>("/v1/patients"),
  getContext: (pid: string) => request<PatientContext>(`/v1/patients/${pid}/context`),
  reviewNote: (pid: string, currentNote: string) =>
    request<NoteReviewResult>(`/v1/patients/${pid}/notes/review`, {
      method: "POST",
      body: JSON.stringify({ current_note: currentNote }),
    }),
  investigate: (pid: string, currentNote: string) =>
    request<InvestigationResult>(`/v1/patients/${pid}/investigate`, {
      method: "POST",
      body: JSON.stringify({ current_note: currentNote }),
    }),
  getInvestigation: (runId: string, includeSteps: boolean) =>
    request<InvestigationResult>(
      `/v1/investigations/${runId}?include_steps=${includeSteps}`
    ),
  saveNote: (pid: string, text: string, noteType = "progress") =>
    request<{ evidence_id: string; saved: boolean }>(`/v1/patients/${pid}/notes`, {
      method: "POST",
      body: JSON.stringify({ text, note_type: noteType }),
    }),
  playgroundGenerate: (
    pid: string,
    body: {
      metric_code: string;
      trend: string;
      n_points: number;
      months_back: number;
      start_value: number | null;
    }
  ) =>
    request<PlaygroundResult>(`/v1/patients/${pid}/playground/generate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  playgroundAdd: (
    pid: string,
    observations: { metric_code: string; value: number; clinical_time: string | null }[]
  ) =>
    request<PlaygroundResult>(`/v1/patients/${pid}/playground/observations`, {
      method: "POST",
      body: JSON.stringify({ observations }),
    }),
  lintNote: (pid: string, text: string, mode: "fast" | "full") =>
    request<LintResult>(`/v1/patients/${pid}/notes/lint`, {
      method: "POST",
      body: JSON.stringify({ text, mode }),
    }),
  annotationDecision: (
    pid: string,
    category: string,
    quote: string,
    decision: "accepted" | "dismissed",
    noteText: string
  ) =>
    request<{ recorded: boolean }>(`/v1/patients/${pid}/annotations/decision`, {
      method: "POST",
      body: JSON.stringify({ category, quote, decision, note_text: noteText }),
    }),
  addProblem: (pid: string, display: string) =>
    request<{ evidence_id: string; added: boolean }>(`/v1/patients/${pid}/problem-list`, {
      method: "POST",
      body: JSON.stringify({ display }),
    }),
  playgroundScenario: (pid: string, description: string) =>
    request<PlaygroundResult & { conditions: { evidence_id: string; display: string }[]; note_evidence_id: string | null; note_text: string }>(
      `/v1/patients/${pid}/playground/scenario`,
      { method: "POST", body: JSON.stringify({ description }) }
    ),
  playgroundClear: (pid: string) =>
    request<{ removed: number }>(`/v1/patients/${pid}/playground`, { method: "DELETE" }),
  getEvidence: (pid: string, evidenceIds: string[]) =>
    request<{ evidence: EvidenceDetail[] }>(`/v1/patients/${pid}/evidence`, {
      method: "POST",
      body: JSON.stringify({ evidence_ids: evidenceIds }),
    }),
};
