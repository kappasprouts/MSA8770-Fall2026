export interface EvidenceItem {
  document?: string;
  page?: number | string;
  quote?: string;
}

export interface ProfileSection {
  summary?: string;
  evidence?: EvidenceItem[];
  [key: string]: unknown;
}

export interface StrengthItem {
  strength?: string;
  evidence?: EvidenceItem[];
}

export interface PolicyAssessmentItem {
  policy_id?: string;
  title?: string;
  criterion?: string;
  alignment?: string;
  assessment?: string;
  findings?: string;
  evidence?: EvidenceItem[];
}

export interface ApplicantDemographics {
  first_name?: string;
  last_name?: string;
  name_of_hs?: string;
  country?: string;
  region?: string;
  intended_major?: string;
  intended_program?: string;
  application_type?: string;
  residency_status?: string;
  application_status?: string;
  admission_year?: number;
  admission_term?: string;
  [key: string]: unknown;
}

export interface ApplicantDossier {
  app_id?: string;
  applicant_demographics?: ApplicantDemographics;
  academic_profile?: ProfileSection;
  engagement_profile?: ProfileSection;
  recommendation_profile?: ProfileSection;
  supplemental_essay_profile?: ProfileSection;
  strengths?: Array<StrengthItem | string>;
  policy_assessment?: PolicyAssessmentItem[];
  review_notes?: string[];
  holistic_assessment?: string;
  evidence_map?: EvidenceItem[];
  generated_at?: string;
  updated_at?: string;
}

export interface ValidationCall {
  section?: string;
  attempt?: number;
  usage?: { prompt_tokens?: number; output_tokens?: number; seconds?: number };
  errors?: string[];
}

export interface RunValidation {
  passed?: boolean;
  failed_sections?: Record<string, string[]>;
  calls?: ValidationCall[];
}

export interface RunInfo {
  app_id?: string;
  run_status?: string;
  runtime_seconds?: number;
  attempts?: number;
  policies_retrieved?: { policy_id?: string; title?: string; similarity?: number; query?: string }[];
  documents_sent?: Record<string, number[]>;
  documents_withheld?: Record<string, string>;
  validation?: RunValidation;
  failed_output?: {
    completed_sections?: Record<string, unknown>;
    failed_sections?: Record<string, { errors?: string[]; output?: unknown }>;
  };
}

export interface DossierPayload {
  run?: RunInfo;
  applicant_dossier?: ApplicantDossier;
}

export interface OriginalDocument {
  file: string;
  label: string;
  pages: number[] | null;
  access: "sent" | "withheld";
  reason?: string;
}

export interface ApplicantSummary {
  id: string;
}

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
