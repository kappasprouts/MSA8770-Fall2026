export type ExceptionSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export interface ExceptionAuditEvent {
  action: string;
  actor: string;
  details?: Record<string, unknown>;
  createdAt: string;
}

export interface ExceptionRecord {
  fingerprint?: string;
  sourceVersion?: string;
  objectKey?: string;
  failureRunId?: number | string | null;
  eventId?: string | null;
  active?: boolean;
  retryAllowed?: boolean;
  caseId?: string;
  caseState?: string;
  revision?: number;
  owner?: string | null;
  resolutionEvidence?: Record<string, unknown> | null;
  actions?: { action: string; actor: string; note: string; createdAt: string }[];
  retryJob?: { id: string; state: string; result?: Record<string, unknown>; created_at: string } | null;
  workerAvailable?: boolean;
  id: string;
  applicantId: string | null;
  applicantName: string;
  intendedMajor: string | null;
  status: string;
  category: string;
  severity: ExceptionSeverity;
  source: "INGESTION" | "SUMMARIZER" | "ORPHAN_INTAKE";
  summary: string;
  findings: string[];
  affectedDocuments: string[];
  updatedAt: string | null;
  hasDossier: boolean;
  auditHistory: ExceptionAuditEvent[];
}
