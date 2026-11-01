export interface EvidenceItem {
  verification_status?: string;
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
  criterion?: string;
  alignment?: string;
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
  strengths?: StrengthItem[];
  policy_assessment?: PolicyAssessmentItem[];
  review_notes?: (string | { note?: string; section?: string; category?: string })[];
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
  id?: number | string | null;
  created_at?: string | null;
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
  publication?: { request_id: string; generation_run_id: number | string; candidate_hash: string; reviewer: string | null; decided_at: string | null; mode?: string } | null;
  review_checkpoint?: { request_id: string; candidate_hash: string; state: string; reasons: string[]; expires_at: string;
    requires_evidence_review?: boolean; outcome_reason?: string; documents: { filename: string }[] };
  run?: RunInfo;
  applicant_dossier?: ApplicantDossier;
}

export interface OriginalDocument {
  sourceUrl?: string;
  file: string;
  label: string;
  pages: number[] | null;
  access: "sent" | "withheld";
  reason?: string;
}

export interface ApplicantSummary {
  id: string;
}
