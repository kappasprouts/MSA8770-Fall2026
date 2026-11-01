export const RECOMMENDATIONS = ["ACCEPT", "REJECT", "WAITLIST"] as const;
export type OfficerRecommendation = typeof RECOMMENDATIONS[number];
export const MAX_RECOMMENDATION_NOTES = 10_000;

export interface OfficerReview {
  appId: string;
  recommendation: OfficerRecommendation | null;
  notes: string;
  updatedAt: string | null;
  canEdit: boolean;
  applicationStatus: string;
  version?: { requestId: string; candidateHash: string; state: string; requiresEvidenceReview: boolean;
    reasons: string[]; expiresAt: string; outcomeReason?: string; reviewer?: string; reason?: string; fresh?: boolean };
}

export interface ExceptionResolution {
  reviewer: string; reason: string; confirmed: boolean; evidenceReviewed: boolean;
}

export function validExceptionResolution(value: unknown): value is ExceptionResolution {
  if (!value || typeof value !== "object") return false;
  const r = value as Record<string, unknown>;
  return typeof r.reviewer === "string" && r.reviewer.trim().length > 0 && r.reviewer.length <= 200 &&
    typeof r.reason === "string" && r.reason.trim().length > 0 && r.reason.length <= 10000 &&
    r.confirmed === true && typeof r.evidenceReviewed === "boolean";
}

export interface RecommendationState {
  loading: boolean;
  saving: boolean;
  dirty: boolean;
  saved: OfficerRecommendation | null;
  canEdit: boolean;
  error: boolean;
  applicationStatus: string | null;
}

export const INITIAL_RECOMMENDATION_STATE: RecommendationState = { loading: true, saving: false, dirty: false, saved: null, canEdit: false, error: false, applicationStatus: null };

export function isOfficerRecommendation(value: unknown): value is OfficerRecommendation {
  return RECOMMENDATIONS.some(option => option === value);
}

export function recommendationLabel(value: OfficerRecommendation | null): string {
  return value ? { ACCEPT: "Accept", REJECT: "Reject", WAITLIST: "Waitlist" }[value] : "Not recorded";
}
