import type { ApplicantDossier, RunValidation } from "./types";

export const REVIEW_ACTION = "PUBLISH_ADVISORY_DOSSIER";
export const isReviewId = (value: string) => /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);

export interface ReviewRequest {
  id: string; app_id: string; state: string; candidate_hash: string; input_hash: string;
  pipeline_version: string; action: string; expires_at: string; requested_at: string;
  requires_evidence_review: boolean; review_owner: string; escalation_owner: string;
  candidate: ApplicantDossier; validation: RunValidation; reason?: string; reviewer?: string;
  outcome_reason?: string; decision?: string; generation_run_id: number;
  input_snapshot: { applicant: { documents: { filename: string; bucket?: string; key: string; sha256?: string }[] } };
}

export function parseReviewDecision(value: unknown) {
  if (!value || typeof value !== "object" || !("candidateHash" in value) ||
      !("action" in value) || value.action !== REVIEW_ACTION || !("decision" in value) ||
      !["APPROVE", "REJECT"].includes(String(value.decision)) ||
      typeof value.candidateHash !== "string" || !/^[a-f0-9]{64}$/.test(value.candidateHash) ||
      !("confirmed" in value) || value.confirmed !== true ||
      !("reviewer" in value) || typeof value.reviewer !== "string" || !value.reviewer.trim() || value.reviewer.length > 200 ||
      !("reason" in value) || typeof value.reason !== "string" || !value.reason.trim() || value.reason.length > 10000 ||
      !("evidenceReviewed" in value) || typeof value.evidenceReviewed !== "boolean") return null;
  return { candidateHash: value.candidateHash, action: REVIEW_ACTION, decision: value.decision,
    reviewer: value.reviewer.trim(), reason: value.reason.trim(), confirmed: true, evidenceReviewed: value.evidenceReviewed };
}
