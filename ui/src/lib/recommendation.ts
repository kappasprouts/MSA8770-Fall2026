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

export function isOfficerRecommendation(value: unknown): value is OfficerRecommendation {
  return RECOMMENDATIONS.some(option => option === value);
}

export function recommendationLabel(value: OfficerRecommendation | null): string {
  return value ? { ACCEPT: "Accept", REJECT: "Reject", WAITLIST: "Waitlist" }[value] : "Not recorded";
}
