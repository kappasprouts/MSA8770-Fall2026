import { Pool } from "pg";
import { Client as MinioClient } from "minio";

declare global {
  var __pgPool: Pool | undefined;
}

export const pool =
  global.__pgPool ??
  new Pool({
    host: process.env.POSTGRES_HOST ?? "localhost",
    port: Number(process.env.POSTGRES_PORT ?? 5432),
    database: process.env.POSTGRES_DB ?? "riverview_admissions",
    user: process.env.POSTGRES_USER ?? "postgres",
    password: process.env.POSTGRES_PASSWORD ?? "postgres",
  });

if (process.env.NODE_ENV !== "production") {
  global.__pgPool = pool;
}

const MINIO_ENDPOINT = process.env.MINIO_ENDPOINT ?? "localhost:9000";
const [MINIO_HOST, MINIO_PORT_STR] = MINIO_ENDPOINT.split(":");

export const MINIO_BUCKET = process.env.MINIO_BUCKET ?? "applicant-documents";

export const minioClient = new MinioClient({
  endPoint: MINIO_HOST,
  port: Number(MINIO_PORT_STR ?? 9000),
  useSSL: false,
  accessKey: process.env.MINIO_ACCESS_KEY ?? "minioadmin",
  secretKey: process.env.MINIO_SECRET_KEY ?? "minioadmin",
});

const DOCUMENT_LABELS: Record<string, string> = {
  "application_form.pdf": "Application Form",
  "common_app_application.pdf": "Common App Application",
  "transcript.pdf": "Transcript",
  "recommendation_letter_1.pdf": "Recommendation Letter 1",
  "recommendation_letter_2.pdf": "Recommendation Letter 2",
  "standardized_test_score.pdf": "Standardized Test Score",
  "activities_and_awards.pdf": "Activities & Awards",
  "advanced_coursework_and_ap_scores.pdf": "Advanced Coursework & AP Scores",
  "university_supplement.pdf": "University Supplement",
  "personal_statement.pdf": "Personal Statement",
};

export function humanizeDocumentName(filename: string): string {
  if (DOCUMENT_LABELS[filename]) {
    return DOCUMENT_LABELS[filename];
  }

  return filename
    .replace(/\.pdf$/i, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export interface OriginalDocument {
  file: string;
  label: string;
  pages: number[] | null;
  access: "sent" | "withheld";
  reason?: string;
}

interface ApplicantDocumentRecord {
  type?: string;
  filename: string;
  object_key: string;
}

const PROFILE_SECTIONS: { key: string; label: string }[] = [
  { key: "applicant_demographics", label: "Applicant Demographics" },
  { key: "academic_profile", label: "Academic Profile" },
  { key: "engagement_profile", label: "Engagement Profile" },
  { key: "recommendation_profile", label: "Recommendation Profile" },
  { key: "supplemental_essay_profile", label: "Supplemental Essay Profile" },
];

export interface ApplicantSummary {
  id: string;
}

interface Evidence {
  document?: string;
  page?: number | string;
  quote?: string;
}

export async function listApplicants(): Promise<ApplicantSummary[]> {
  const { rows } = await pool.query<{ app_id: string }>(
    "SELECT app_id FROM applicant_dossier ORDER BY app_id;"
  );

  return rows.map((row) => ({ id: row.app_id }));
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function loadDossier(appId: string): Promise<any | null> {
  const dossierResult = await pool.query(
    "SELECT * FROM applicant_dossier WHERE app_id = $1;",
    [appId]
  );

  if (dossierResult.rowCount === 0) {
    return null;
  }

  const d = dossierResult.rows[0];

  const runResult = await pool.query(
    "SELECT * FROM dossier_generation_runs WHERE app_id = $1 ORDER BY created_at DESC LIMIT 1;",
    [appId]
  );

  const r = runResult.rows[0] ?? {};

  return {
    run: {
      app_id: appId,
      run_status: r.run_status ?? "UNKNOWN",
      attempts: r.attempts ?? 0,
      runtime_seconds: r.runtime_seconds !== undefined ? Number(r.runtime_seconds) : 0,
      documents_sent: r.documents_sent ?? {},
      documents_withheld: r.documents_withheld ?? {},
      policies_retrieved: r.policies_retrieved ?? [],
      validation: r.validation ?? {},
      failed_output: r.failed_output ?? {},
    },
    applicant_dossier: {
      app_id: d.app_id,
      applicant_demographics: d.applicant_demographics,
      academic_profile: d.academic_profile,
      engagement_profile: d.engagement_profile,
      recommendation_profile: d.recommendation_profile,
      supplemental_essay_profile: d.supplemental_essay_profile,
      strengths: d.strengths,
      review_notes: d.review_notes,
      policy_assessment: d.policy_assessment,
      holistic_assessment: d.holistic_assessment,
      evidence_map: d.evidence_map,
      generated_at: d.generated_at,
      updated_at: d.updated_at,
    },
  };
}

async function getApplicantDocuments(
  appId: string
): Promise<ApplicantDocumentRecord[]> {
  const result = await pool.query(
    `SELECT documents
     FROM applicants
     WHERE app_id = $1;`,
    [appId]
  );

  if (result.rowCount === 0) {
    return [];
  }

  const documents = result.rows[0].documents;

  if (!Array.isArray(documents)) {
    return [];
  }

  return documents
    .filter(
      (doc) =>
        doc.exists === true &&
        typeof doc.filename === "string" &&
        typeof doc.minio_key === "string"
    )
    .map((doc) => ({
      type: doc.doc_type,
      filename: doc.filename,
      object_key: doc.minio_key,
    }));
}

export async function listOriginalDocuments(
  appId: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any
): Promise<OriginalDocument[]> {
  const documents = await getApplicantDocuments(appId);

  const run = data?.run ?? {};
  const sent: Record<string, number[]> = run.documents_sent ?? {};
  const withheld: Record<string, string> = run.documents_withheld ?? {};

  return documents
    .map(({ filename: file }) => {
      if (file in withheld) {
        return {
          file,
          label: humanizeDocumentName(file),
          pages: null,
          access: "withheld" as const,
          reason: withheld[file],
        };
      }

      return {
        file,
        label: humanizeDocumentName(file),
        pages: sent[file] ?? null,
        access: "sent" as const,
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label));
}

export async function getDocumentObjectKey(appId: string, filename: string): Promise<string | null> {
  const documents = await getApplicantDocuments(appId);
  const match = documents.find((doc) => doc.filename === filename);
  return match?.object_key ?? null;
}

function formatEvidence(evidence: Evidence[] = []): string {
  if (!evidence.length) {
    return "";
  }

  return evidence
    .map(
      (item) =>
        `  - ${item.document ?? "unknown document"}, p.${item.page ?? "?"}: "${item.quote ?? ""}"`
    )
    .join("\n");
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function buildDossierContext(data: any): string {
  const dossier = data?.applicant_dossier;
  const run = data?.run ?? {};
  const appId = run.app_id ?? dossier?.app_id ?? "Unknown";

  if (!dossier) {
    return `APPLICANT ID: ${appId}\nNo validated dossier is available for this applicant yet.`;
  }

  const lines: string[] = [`APPLICANT ID: ${appId}`];

  if (dossier.holistic_assessment) {
    lines.push("", "HOLISTIC ASSESSMENT:", dossier.holistic_assessment);
  }

  if (Array.isArray(dossier.strengths) && dossier.strengths.length) {
    lines.push("", "KEY STRENGTHS:");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    dossier.strengths.forEach((item: any, idx: number) => {
      lines.push(`${idx + 1}. ${item.strength ?? item}`);
      const evidenceText = formatEvidence(item.evidence);

      if (evidenceText) {
        lines.push(evidenceText);
      }
    });
  }

  for (const { key, label } of PROFILE_SECTIONS) {
    const section = dossier[key];

    if (!section) {
      continue;
    }

    lines.push("", `${label.toUpperCase()}:`);

    if (typeof section !== "object") {
      lines.push(String(section));
      continue;
    }

    if (section.summary) {
      lines.push(section.summary);
    }

    const details = Object.fromEntries(
      Object.entries(section).filter(([key2]) => key2 !== "summary" && key2 !== "evidence")
    );

    if (Object.keys(details).length) {
      lines.push(`Details: ${JSON.stringify(details)}`);
    }

    const evidenceText = formatEvidence(section.evidence);

    if (evidenceText) {
      lines.push("Evidence:");
      lines.push(evidenceText);
    }
  }

  if (Array.isArray(dossier.policy_assessment) && dossier.policy_assessment.length) {
    lines.push("", "POLICY ASSESSMENT:");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    dossier.policy_assessment.forEach((item: any) => {
      lines.push(
        `- ${item.policy_id ?? "?"} (${item.alignment ?? "unknown"}): ` +
          `${item.criterion ?? ""} — ${item.findings ?? ""}`
      );
    });
  }

  if (Array.isArray(dossier.review_notes) && dossier.review_notes.length) {
    lines.push("", "REVIEWER NOTES:");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    dossier.review_notes.forEach((note: any) => lines.push(`- ${note}`));
  }

  return lines.join("\n");
}

export function buildSystemPrompt(context: string): string {
  return [
    "You are an admissions-review assistant chatbot for Riverview State University.",
    "Answer questions only using the APPLICANT DOSSIER content provided below.",
    "If the dossier does not contain the answer, say so clearly instead of guessing or inventing information.",
    'When useful, cite the source document and page (for example: "per transcript.pdf, page 1").',
    "You are advisory only: never state, imply, or suggest an admission decision or recommendation.",
    "",
    "APPLICANT DOSSIER:",
    context,
  ].join("\n");
}
