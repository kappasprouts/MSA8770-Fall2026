import type { ApplicantSummary, DossierPayload, RunInfo, ValidationCall } from "./types";

const STATUS_LABELS: Record<string, string> = {
  DOSSIER_READY: "Dossier ready", READY_FOR_REVIEW: "Awaiting dossier",
  REVIEWED: "Reviewed", FINAL_DECISION_RECORDED: "Final decision recorded",
  AWAITING_MATERIALS: "Awaiting materials", INCOMPLETE: "Incomplete",
  AI_VALIDATION_FAILED: "Validation failed", HUMAN_REVIEW_AI_FAILED: "Needs human review",
  AGENT_ERROR: "Generation failed", ERROR: "Processing error", PENDING: "Pending", UNKNOWN: "Unknown",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replaceAll("_", " ").toLowerCase().replace(/^./, c => c.toUpperCase());
}

export function decisionLabel(decision: string | null): string {
  return ({ ACCEPT: "Accepted", WAITLIST: "Waitlisted", DECLINE: "Declined" } as Record<string, string>)[decision ?? ""] ?? "Not recorded";
}

/** Saved dossiers remain accessible throughout human review and finalization. */
export function hasReviewableDossier(status: string): boolean {
  return ["DOSSIER_READY", "REVIEWED", "FINAL_DECISION_RECORDED"].includes(status);
}

export function parseApplicantSummaries(value: unknown): ApplicantSummary[] {
  const list = (value as { applicants?: unknown } | null)?.applicants;
  if (!Array.isArray(list) || list.some(item => !item || typeof item.id !== "string" || !item.id)) {
    throw new Error("The applicant list could not be read. Please try again.");
  }
  return list.map(item => ({ id: item.id }));
}

/** Never render cached applicant content under a different selection. */
export function isDossierForApplicant(payload: DossierPayload | null, appId: string): boolean {
  return Boolean(appId && payload?.applicant_dossier?.app_id === appId &&
    (!payload.run?.app_id || payload.run.app_id === appId));
}

export function latestRunCheckState(run: RunInfo): "passed" | "failed" | "unknown" {
  if (run.validation?.passed === false || /FAIL|ERROR|STOPPED/.test(run.run_status ?? "")) return "failed";
  if (run.run_status === "DOSSIER_READY" && run.validation?.passed === true) return "passed";
  return "unknown";
}

/** Count the final recorded attempt for each section, rather than counting retries as outputs. */
export function latestSectionChecks(run: RunInfo) {
  const sections = new Map<string, ValidationCall>();
  const calls = Array.isArray(run.validation?.calls) ? run.validation.calls : [];
  for (const call of calls) {
    if (!call || typeof call.section !== "string" || !call.section) continue;
    const previous = sections.get(call.section);
    if (!previous || (call.attempt ?? 0) >= (previous.attempt ?? 0)) sections.set(call.section, call);
  }
  const checked = [...sections.values()].filter(call => Array.isArray(call.errors));
  return { passed: checked.filter(call => call.errors!.length === 0).length, total: checked.length };
}

export interface DecisionTotals { awaiting: number; recorded: number; total: number }

export function parseDecisionTotals(value: unknown): DecisionTotals | null {
  if (!value || typeof value !== "object") return null;
  const totals = value as DecisionTotals;
  if (![totals.awaiting, totals.recorded, totals.total].every(n => Number.isSafeInteger(n) && n >= 0)) return null;
  if (totals.awaiting + totals.recorded > totals.total) return null;
  return { awaiting: totals.awaiting, recorded: totals.recorded, total: totals.total };
}

export type BatchState =
  | { kind: "loading" | "unavailable" | "none" }
  | { kind: "completed"; executedAt: string; affected: number | null }
  | { kind: "other"; status: string };

export function parseBatchStatus(value: unknown): BatchState {
  const data = value as { status?: unknown; executed_at?: unknown; affected_ids?: unknown } | null;
  if (data?.status === "NO_PREVIOUS_RUN") return { kind: "none" };
  if (data?.status === "COMPLETED") {
    if (typeof data.executed_at !== "string" || !Number.isFinite(Date.parse(data.executed_at))) throw new Error("Batch completion timestamp is unavailable.");
    return { kind: "completed", executedAt: data.executed_at, affected: Array.isArray(data.affected_ids) ? data.affected_ids.length : null };
  }
  if (typeof data?.status === "string" && data.status) return { kind: "other", status: data.status };
  throw new Error("Batch status is unavailable.");
}
