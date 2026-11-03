import { requestJson } from "./http";
import { parseDecisionTotals, type DecisionTotals } from "./review-state";

/** Next.js API adapter; optional URL overrides support external deployments. */
export type ApplicationStatus = string;
export type FinalDecision = 'ACCEPT' | 'WAITLIST' | 'DECLINE';

export interface ApplicantRow {
  appId: string;
  firstName: string;
  lastName: string;
  intendedMajor: string | null;
  applicationStatus: ApplicationStatus;
  finalDecision: FinalDecision | null;
  reviewerRecommendation: FinalDecision | null;
  reviewerRecommendationNote: string | null;
  lastUpdated: string | null;
}

export interface ReviewerRecommendation {
  appId: string;
  applicationStatus: ApplicationStatus;
  finalDecision: FinalDecision | null;
  recommendation: FinalDecision | null;
  note: string | null;
  recommendedAt: string | null;
}

const BASE_URL = (
  process.env.NEXT_PUBLIC_EAOS_API_BASE_URL || ''
).replace(/\/$/, '');

const QUEUE_PATH = process.env.NEXT_PUBLIC_EAOS_REVIEW_QUEUE_PATH || '/api/applicants/review-queue';
const FINAL_QUEUE_PATH = process.env.NEXT_PUBLIC_EAOS_FINAL_QUEUE_PATH || '/api/applicants/final-decision-queue';
const FINAL_DECISION_PATH = process.env.NEXT_PUBLIC_EAOS_FINAL_DECISION_PATH || '/api/applicants/{id}/final-decision';

function asObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Expected an applicant object.');
  return value as Record<string, unknown>;
}
function get(obj: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) if (obj[key] !== undefined && obj[key] !== null) return obj[key];
  return null;
}
function asText(value: unknown): string | null { return value === null || value === undefined ? null : String(value); }
function normalizeDecision(value: unknown): FinalDecision | null {
  const s = asText(value)?.toUpperCase();
  return s === 'ACCEPT' || s === 'WAITLIST' || s === 'DECLINE' ? s : null;
}
export function normalizeApplicant(raw: unknown): ApplicantRow {
  const r = asObject(raw);
  const id = asText(get(r, 'app_id', 'App_ID', 'appId', 'CAID', 'caid'));
  if (!id) throw new Error('Applicant record missing app_id/CAID.');
  return {
    appId: id,
    firstName: asText(get(r, 'first_name', 'First_Name', 'firstName')) || '',
    lastName: asText(get(r, 'last_name', 'Last_Name', 'lastName')) || '',
    intendedMajor: asText(get(r, 'intended_major', 'Intended_Major', 'intendedMajor')),
    applicationStatus: asText(get(r, 'application_status', 'Application_Status', 'applicationStatus')) || 'UNKNOWN',
    finalDecision: normalizeDecision(get(r, 'final_decision', 'Final_Decision', 'finalDecision')),
    reviewerRecommendation: normalizeDecision(get(r, 'reviewer_recommendation', 'reviewerRecommendation')),
    reviewerRecommendationNote: asText(get(r, 'reviewer_recommendation_note', 'reviewerRecommendationNote')),
    lastUpdated: asText(get(r, 'last_updated', 'Last_Updated', 'lastUpdated')),
  };
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  return requestJson<unknown>(`${BASE_URL}${path}`, { ...init, headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers } });
}
function extractRows(payload: unknown): ApplicantRow[] {
  const list = Array.isArray(payload) ? payload : get(asObject(payload), 'applicants', 'items', 'results', 'queue');
  if (!Array.isArray(list)) throw new Error('Expected an array of applicants, or an object with applicants/items/results/queue.');
  return list.map(normalizeApplicant);
}
export async function getReviewQueue(signal?: AbortSignal): Promise<ApplicantRow[]> {
  return extractRows(await request(QUEUE_PATH, { signal }));
}
export async function getFinalDecisionQueue(): Promise<ApplicantRow[]> {
  return (await getFinalDecisionData()).applicants;
}
export async function getFinalDecisionData(signal?: AbortSignal): Promise<{ applicants: ApplicantRow[]; totals: DecisionTotals | null }> {
  const data = await request(FINAL_QUEUE_PATH, { signal });
  return {
    applicants: extractRows(data),
    totals: parseDecisionTotals(Array.isArray(data) ? null : asObject(data).totals),
  };
}
export async function submitFinalDecision(appId: string, decision: FinalDecision): Promise<void> {
  const path = FINAL_DECISION_PATH.replace('{id}', encodeURIComponent(appId));
  await request(path, { method: 'PUT', body: JSON.stringify({ final_decision: decision }) });
}

function normalizeRecommendation(raw: unknown): ReviewerRecommendation {
  const r = asObject(raw);
  return {
    appId: asText(get(r, 'appId', 'app_id')) || '',
    applicationStatus: asText(get(r, 'applicationStatus', 'status')) || 'UNKNOWN',
    finalDecision: normalizeDecision(get(r, 'finalDecision', 'final_decision')),
    recommendation: normalizeDecision(get(r, 'recommendation', 'reviewer_recommendation')),
    note: asText(get(r, 'note', 'reviewer_recommendation_note')),
    recommendedAt: asText(get(r, 'recommendedAt', 'reviewer_recommended_at')),
  };
}
export async function getRecommendation(appId: string, signal?: AbortSignal): Promise<ReviewerRecommendation> {
  return normalizeRecommendation(await request(`/api/applicants/${encodeURIComponent(appId)}/recommendation`, { signal }));
}
export async function submitRecommendation(appId: string, recommendation: FinalDecision): Promise<ReviewerRecommendation> {
  return normalizeRecommendation(await request(`/api/applicants/${encodeURIComponent(appId)}/recommendation`, {
    method: 'PUT', body: JSON.stringify({ recommendation }),
  }));
}

/** Canonical applicant dossier route; the home page redirects legacy bookmarks. */
export function dossierHref(appId: string): string {
  return `/applicant-review?appId=${encodeURIComponent(appId)}`;
}
