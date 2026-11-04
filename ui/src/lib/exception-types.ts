export type ExceptionSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";

export interface ExceptionAuditEvent {
  action: string;
  actor: string;
  details?: Record<string, unknown>;
  createdAt: string;
}

export interface ExceptionRecord {
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
