import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";
import type {
  ExceptionAuditEvent,
  ExceptionRecord,
  ExceptionSeverity,
} from "@/lib/types";

export const dynamic = "force-dynamic";

type JsonObject = Record<string, unknown>;

function asObject(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is string => typeof item === "string" && item.length > 0,
      )
    : [];
}

function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function severityFor(
  status: string,
  source: ExceptionRecord["source"],
): ExceptionSeverity {
  if (
    source === "ORPHAN_INTAKE" ||
    status === "ERROR" ||
    status.includes("AI_VALIDATION_FAILED") ||
    status === "HUMAN_REVIEW_AI_FAILED" ||
    status === "AGENT_ERROR"
  ) {
    return "HIGH";
  }

  if (status === "REPLACEMENT_REQUESTED" || status === "INCOMPLETE") {
    return "HIGH";
  }

  if (status === "AWAITING_MATERIALS" || status === "COUNSELOR_REVIEW") {
    return "MEDIUM";
  }

  return "LOW";
}

function classify(status: string, action: string, findings: string[]): string {
  const text = `${status} ${action} ${findings.join(" ")}`.toUpperCase();

  if (text.includes("DUPLICATE")) return "Duplicate Document";
  if (
    text.includes("UNREADABLE") ||
    text.includes("INTEGRITY") ||
    text.includes("REPLACEMENT")
  ) {
    return "Unreadable or Invalid Document";
  }
  if (text.includes("MISSING_DOCUMENT") || status === "AWAITING_MATERIALS") {
    return "Missing Material";
  }
  if (text.includes("MISSING_FIELD") || status === "INCOMPLETE") {
    return "Incomplete Metadata";
  }
  if (text.includes("AI_VALIDATION") || text.includes("VALIDATION FAILED")) {
    return "AI Validation Failure";
  }
  if (text.includes("COUNSELOR")) return "Counselor Review";
  if (text.includes("DATE") || text.includes("CONFLICT")) {
    return "Conflicting Information";
  }
  if (text.includes("COURSE") || text.includes("AMBIGU")) {
    return "Ambiguous Coursework";
  }
  return "Processing Error";
}

function validationFindings(value: unknown): string[] {
  const validation = asObject(value);
  const failed = asObject(validation.failed_sections);

  return Object.entries(failed).flatMap(([section, errors]) =>
    stringArray(errors).map((error) => `${humanize(section)}: ${error}`),
  );
}

export async function GET() {
  try {
    const [applicantResult, orphanResult] = await Promise.all([
      pool.query(`
        SELECT
          a.app_id,
          a.first_name,
          a.last_name,
          a.intended_major,
          a.status,
          a.documents,
          a.updated_at,
          EXISTS (
            SELECT 1 FROM applicant_dossier d WHERE d.app_id = a.app_id
          ) AS has_dossier,
          latest_audit.action AS audit_action,
          latest_audit.details AS audit_details,
          latest_audit.created_at AS audit_created_at,
          COALESCE(history.events, '[]'::json) AS audit_history,
          latest_run.run_status,
          latest_run.validation AS run_validation,
          latest_run.created_at AS run_created_at
        FROM applicants a
        LEFT JOIN LATERAL (
          SELECT action, details, created_at
          FROM audit_logs
          WHERE applicant_id = a.app_id
          ORDER BY created_at DESC
          LIMIT 1
        ) latest_audit ON TRUE
        LEFT JOIN LATERAL (
          SELECT json_agg(json_build_object(
            'action', item.action,
            'actor', item.actor,
            'details', item.details,
            'createdAt', item.created_at
          ) ORDER BY item.created_at DESC) AS events
          FROM (
            SELECT action, actor, details, created_at
            FROM audit_logs
            WHERE applicant_id = a.app_id
            ORDER BY created_at DESC
            LIMIT 8
          ) item
        ) history ON TRUE
        LEFT JOIN LATERAL (
          SELECT run_status, validation, created_at
          FROM dossier_generation_runs
          WHERE app_id = a.app_id
          ORDER BY created_at DESC
          LIMIT 1
        ) latest_run ON TRUE
        WHERE a.status IN (
          'AWAITING_MATERIALS', 'INCOMPLETE', 'ERROR',
          'COUNSELOR_REVIEW', 'REPLACEMENT_REQUESTED', 'HUMAN_REVIEW'
        )
        OR COALESCE(latest_run.run_status, '') IN (
          'AI_VALIDATION_FAILED', 'AGENT_ERROR', 'HUMAN_REVIEW_AI_FAILED'
        )
        ORDER BY a.updated_at DESC, a.app_id;
      `),
      pool.query(`
        SELECT id, filename, minio_key, detected_app_id, sha256, ingested_at
        FROM orphan_documents
        ORDER BY ingested_at DESC
        LIMIT 100;
      `),
    ]);

    const applicantExceptions: ExceptionRecord[] = applicantResult.rows.map(
      (row) => {
        const details = asObject(row.audit_details);
        const documents: JsonObject[] = Array.isArray(row.documents)
          ? row.documents.map(asObject)
          : [];
        const missingDocuments = stringArray(details.missing_documents);
        const missingFields = stringArray(details.missing_fields);
        const errors = stringArray(details.errors);
        const documentErrors = documents.flatMap((document) => {
          const filename =
            typeof document.filename === "string"
              ? document.filename
              : "Unknown document";
          const error =
            typeof document.error_message === "string"
              ? document.error_message
              : null;

          return document.is_readable === false || error
            ? [`${filename}: ${error ?? "Document is unreadable."}`]
            : [];
        });
        const runFindings = validationFindings(row.run_validation);
        const findings = [
          ...missingDocuments.map(
            (item) => `Missing required document: ${humanize(item)}`,
          ),
          ...missingFields.map(
            (item) => `Missing required field: ${humanize(item)}`,
          ),
          ...errors,
          ...documentErrors,
          ...runFindings,
        ];
        const runStatus =
          typeof row.run_status === "string" ? row.run_status : "";
        const status =
          runStatus && runStatus !== "DOSSIER_READY" ? runStatus : row.status;
        const auditAction =
          typeof row.audit_action === "string" ? row.audit_action : "";
        const source: ExceptionRecord["source"] =
          runStatus && runStatus !== "DOSSIER_READY"
            ? "SUMMARIZER"
            : "INGESTION";
        const affectedDocuments = Array.from(
          new Set([
            ...missingDocuments.map((item) => `${item}.pdf`),
            ...documents
              .filter(
                (document) =>
                  document.is_readable === false || document.error_message,
              )
              .map((document) => String(document.filename)),
          ]),
        );

        return {
          id: `applicant-${row.app_id}-${source.toLowerCase()}`,
          applicantId: row.app_id,
          applicantName:
            `${row.first_name ?? ""} ${row.last_name ?? ""}`.trim() ||
            row.app_id,
          intendedMajor: row.intended_major ?? null,
          status,
          category: classify(status, auditAction, findings),
          severity: severityFor(status, source),
          source,
          summary:
            findings[0] ?? `${humanize(status)} requires human review.`,
          findings: findings.length
            ? findings
            : [`The ${humanize(status)} workflow status requires review.`],
          affectedDocuments,
          updatedAt:
            row.run_created_at ?? row.audit_created_at ?? row.updated_at ?? null,
          hasDossier: Boolean(row.has_dossier),
          auditHistory: (Array.isArray(row.audit_history)
            ? row.audit_history
            : []) as ExceptionAuditEvent[],
        };
      },
    );

    const orphanExceptions: ExceptionRecord[] = orphanResult.rows.map(
      (row) => ({
        id: `orphan-${row.id}`,
        applicantId: row.detected_app_id ?? null,
        applicantName: row.detected_app_id
          ? `Possible match: ${row.detected_app_id}`
          : "Unmatched document",
        intendedMajor: null,
        status: "ORPHAN_DOCUMENT",
        category: "Orphan Document",
        severity: "MEDIUM",
        source: "ORPHAN_INTAKE",
        summary: `${row.filename} could not be matched to an applicant record.`,
        findings: [
          "The file is retained in MinIO and recorded in PostgreSQL until a matching application is available.",
          `Storage key: ${row.minio_key}`,
          `SHA-256: ${row.sha256}`,
        ],
        affectedDocuments: [row.filename],
        updatedAt: row.ingested_at ?? null,
        hasDossier: false,
        auditHistory: [],
      }),
    );

    return NextResponse.json({
      exceptions: [...applicantExceptions, ...orphanExceptions],
    });
  } catch (error) {
    console.error("Exception triage error:", error);
    return NextResponse.json(
      { error: "Failed to load exception triage data." },
      { status: 500 },
    );
  }
}
