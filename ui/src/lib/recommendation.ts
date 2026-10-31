export const RECOMMENDATIONS = ["ACCEPT", "REJECT", "WAITLIST"] as const;
export type OfficerRecommendation = typeof RECOMMENDATIONS[number];
export const MAX_RECOMMENDATION_NOTES = 10_000;

export interface OfficerReview {
  appId: string;
  recommendation: OfficerRecommendation | null;
  notes: string;
  updatedAt: string | null;
  canEdit: boolean;
}

export interface RecommendationState {
  loading: boolean;
  saving: boolean;
  dirty: boolean;
  saved: OfficerRecommendation | null;
  canEdit: boolean;
  error: boolean;
}

export const INITIAL_RECOMMENDATION_STATE: RecommendationState = { loading: true, saving: false, dirty: false, saved: null, canEdit: false, error: false };

export function isOfficerRecommendation(value: unknown): value is OfficerRecommendation {
  return RECOMMENDATIONS.some(option => option === value);
}

export function recommendationLabel(value: OfficerRecommendation | null): string {
  return value ? { ACCEPT: "Accept", REJECT: "Reject", WAITLIST: "Waitlist" }[value] : "Not recorded";
}
