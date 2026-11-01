import { isItActionable } from "@/lib/it-exceptions.mjs";
import type { PoolClient } from "pg";
import { createHash } from "node:crypto";
import type { ItCommand } from "./it-actions";
export type ItDb = Pick<PoolClient, "query">;
import type {
  ExceptionAuditEvent,
  ExceptionRecord,
  ExceptionSeverity,
} from "@/lib/exception-types";



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
  if (text.includes("AI_VALIDATION") || text.includes("VALIDATION FAILED")) {
    return "AI Validation Failure";
  }
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

export async function detectItExceptions(db: ItDb): Promise<ExceptionRecord[]> {
    // Also used under a single transaction client; its queries must be sequential.
    const applicantResult = await db.query(`
        SELECT
          a.app_id,
          a.first_name,
          a.last_name,
          a.intended_major,
          a.status, a.final_decision, a.officer_recommendation,
          encode(sha256(convert_to(checkpoint_input_snapshot(a.app_id)::text,'UTF8')),'hex') AS source_version,
          a.documents,
          a.updated_at,
          EXISTS (
            SELECT 1 FROM applicant_dossier d WHERE d.app_id = a.app_id
          ) AS has_dossier,
          latest_audit.id AS audit_id, latest_run.id AS run_id,
          latest_audit.action AS audit_action,
          latest_audit.details AS audit_details,
          latest_audit.created_at AS audit_created_at,
          COALESCE(history.events, '[]'::json) AS audit_history,
          latest_run.run_status,
          latest_run.validation AS run_validation,
          latest_run.created_at AS run_created_at
        FROM applicants a
        LEFT JOIN LATERAL (
          SELECT id, action, details, created_at
          FROM audit_logs
          WHERE applicant_id = a.app_id AND action NOT LIKE 'IT_EXCEPTION_%'
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
          SELECT id, run_status, validation, created_at
          FROM dossier_generation_runs
          WHERE app_id = a.app_id
          ORDER BY created_at DESC, id DESC
          LIMIT 1
        ) latest_run ON TRUE
        WHERE a.status IN ('ERROR', 'PROCESSING_ERROR', 'AGENT_ERROR', 'AI_VALIDATION_FAILED', 'HUMAN_REVIEW_AI_FAILED')
        OR COALESCE(latest_run.run_status, '') IN (
          'AI_VALIDATION_FAILED', 'AGENT_ERROR', 'HUMAN_REVIEW_AI_FAILED', 'ERROR'
        )
        ORDER BY a.updated_at DESC, a.app_id;
      `);
    const orphanResult = await db.query(`
        SELECT id, filename, minio_key, detected_app_id, sha256, ingested_at
        FROM orphan_documents
        WHERE NOT EXISTS (SELECT 1 FROM document_records d JOIN applicants a ON a.app_id=d.applicant_id
          WHERE d.minio_object_key=orphan_documents.minio_key AND d.sha256_checksum=orphan_documents.sha256
          AND EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(a.documents,'[]')) doc
            WHERE COALESCE(doc->>'minio_key',doc->>'object_key')=d.minio_object_key
              AND COALESCE(doc->>'sha256',doc->>'sha256_checksum')=d.sha256_checksum AND doc->>'exists'='true'))
        ORDER BY ingested_at DESC
        LIMIT 100;
      `);

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
          ["AI_VALIDATION_FAILED", "AGENT_ERROR", "HUMAN_REVIEW_AI_FAILED", "ERROR"].includes(runStatus) ? runStatus : row.status;
        const auditAction =
          typeof row.audit_action === "string" ? row.audit_action : "";
        const source: ExceptionRecord["source"] =
          ["AI_VALIDATION_FAILED", "AGENT_ERROR", "HUMAN_REVIEW_AI_FAILED", "ERROR"].includes(runStatus)
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
          sourceVersion: row.source_version, failureRunId: row.run_id ?? null,
          eventId: source === "SUMMARIZER" ? String(row.run_id ?? "") : row.audit_id ?? null,
          retryAllowed: !row.final_decision && !row.officer_recommendation,
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

    // Defense in depth: never surface student-remediable missing fields,
    // missing materials, or upload replacement requests in the IT queue.
    const itApplicantExceptions = applicantExceptions.filter((record) =>
      isItActionable(record),
    );

    const orphanExceptions: ExceptionRecord[] = orphanResult.rows.map(
      (row) => ({
        id: `orphan-${row.id}`, sourceVersion: row.sha256, objectKey:row.minio_key, eventId: row.id, retryAllowed: false,
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

    return [...itApplicantExceptions, ...orphanExceptions].map(record => ({ ...record, active: true,
      fingerprint: createHash("sha256").update(JSON.stringify([record.id,record.status,record.eventId,
        record.sourceVersion,record.findings])).digest("hex"),
    }));
}

type CaseRow = { id: string; exception_key: string; fingerprint: string; snapshot: ExceptionRecord; state: string;
  owner: string | null; revision: number; resolution_evidence: Record<string, unknown> | null };

export async function listItCases(db: ItDb): Promise<ExceptionRecord[]> {
  const detected=await detectItExceptions(db);
  const saved=await db.query<CaseRow>("SELECT * FROM it_exception_cases ORDER BY updated_at DESC LIMIT 500");
  const events=await db.query("SELECT case_id,action,actor,note,created_at FROM it_exception_actions ORDER BY created_at DESC LIMIT 2000");
  const jobs=await db.query("SELECT * FROM it_retry_jobs ORDER BY created_at DESC LIMIT 500");
  const workers=await db.query("SELECT ingestion_enabled FROM it_retry_workers WHERE last_seen>now()-interval '45 seconds'");
  function decorate(record: ExceptionRecord, c?: CaseRow): ExceptionRecord {
    return { ...record, ...(c ? { caseId: c.id, caseState: c.state, revision: c.revision, owner: c.owner,
      resolutionEvidence: c.resolution_evidence,
      actions: events.rows.filter(e => e.case_id===c.id).map(e => ({ action:e.action, actor:e.actor, note:e.note, createdAt:e.created_at })),
      retryJob: jobs.rows.find(j => j.case_id===c.id) ?? null } : { caseState:"OPEN",revision:0,actions:[] }),
      workerAvailable: workers.rows.some(w => record.source==="SUMMARIZER" || (record.source==="INGESTION" && w.ingestion_enabled)),
    };
  }
  return [
    ...detected.map(r => decorate(r,saved.rows.find(c => c.exception_key===r.id && c.fingerprint===r.fingerprint))),
    ...saved.rows.filter(c => !detected.some(r => r.id===c.exception_key && r.fingerprint===c.fingerprint))
      .map(c => decorate({ ...c.snapshot, id:`case-${c.id}`, active:false },c)),
  ];
}

export async function getItCase(db: ItDb, id: string) {
  const records=await listItCases(db);
  const direct=records.find(r => r.id===id || `case-${r.caseId}`===id);
  if (direct) return direct;
  const previous=await db.query("SELECT id FROM it_exception_cases WHERE exception_key=$1 ORDER BY updated_at DESC LIMIT 1",[id]);
  return records.find(r => r.caseId===previous.rows[0]?.id);
}

export async function verifyItReceiver(db: ItDb, record: ExceptionRecord): Promise<Record<string, unknown> | null> {
  if (record.source==="SUMMARIZER") {
    const { rows } = await db.query(`SELECT g.id AS generation_run_id,g.run_status,r.id AS request_id,r.state,a.status AS applicant_status
      FROM applicants a JOIN dossier_generation_runs g ON g.app_id=a.app_id
      JOIN dossier_review_requests r ON r.generation_run_id=g.id
      WHERE a.app_id=$1 AND g.id>$2 AND g.validation->'passed'='true'::jsonb
      AND g.run_status IN ('DOSSIER_READY','REVIEW_PENDING') AND r.state IN ('PUBLISHED','REVIEW_PENDING')
      AND r.input_snapshot=checkpoint_input_snapshot(a.app_id)
      AND g.id=(SELECT id FROM dossier_generation_runs WHERE app_id=a.app_id ORDER BY created_at DESC,id DESC LIMIT 1)
      AND (r.state='REVIEW_PENDING' OR EXISTS(SELECT 1 FROM applicant_dossier d WHERE d.app_id=a.app_id AND d.publication_request_id=r.id))`,
      [record.applicantId,record.failureRunId ?? 0]);
    return rows[0] ?? null;
  }
  if (record.source==="INGESTION") {
    const { rows } = await db.query(`SELECT a.app_id,a.status,l.id AS manifest_audit_id,l.details->>'processing_status' AS gate_status
      FROM applicants a JOIN LATERAL (SELECT id,details FROM audit_logs WHERE applicant_id=a.app_id AND action='MANIFEST_EVALUATED'
      ORDER BY created_at DESC,id DESC LIMIT 1) l ON true
      WHERE a.app_id=$1 AND l.id::text IS DISTINCT FROM $2 AND a.status NOT IN ('ERROR','PROCESSING_ERROR','AGENT_ERROR','AI_VALIDATION_FAILED','HUMAN_REVIEW_AI_FAILED')
      AND l.details->>'processing_status' IN ('READY_FOR_REVIEW','INCOMPLETE','AWAITING_MATERIALS')`, [record.applicantId,record.eventId]);
    return rows[0] ?? null;
  }
  const { rows } = await db.query(`SELECT d.applicant_id,d.minio_object_key,d.sha256_checksum FROM document_records d JOIN applicants a ON a.app_id=d.applicant_id
    WHERE d.sha256_checksum=$1 AND d.filename=ANY($2::text[]) AND d.minio_object_key=$3 AND EXISTS (
      SELECT 1 FROM jsonb_array_elements(COALESCE(a.documents,'[]')) doc
      WHERE COALESCE(doc->>'minio_key',doc->>'object_key')=d.minio_object_key
      AND COALESCE(doc->>'sha256',doc->>'sha256_checksum')=d.sha256_checksum AND doc->>'exists'='true')`,
    [record.sourceVersion,record.affectedDocuments,record.objectKey]);
  return rows.length===1 ? rows[0] : null;
}

export class ItActionError extends Error { constructor(message: string, public status = 409) { super(message); } }

// The caller owns BEGIN/COMMIT/ROLLBACK. No model or external service runs in the HTTP request.
export async function applyItAction(db: ItDb, id: string, command: ItCommand) {
  await db.query("SELECT pg_advisory_xact_lock(hashtext($1))", [command.commandId]);
  const prior = await db.query("SELECT result,request=$2::jsonb AS same FROM it_exception_actions WHERE command_id=$1", [command.commandId,{ id,...command }]);
  if (prior.rows[0]) {
    if (!prior.rows[0].same) throw new ItActionError("This command ID was already used for another action.");
    return { ...prior.rows[0].result, replayed:true };
  }
  let record = await getItCase(db,id);
  if (!record) throw new ItActionError("Exception not found; reload the queue.",404);
  if (record.applicantId && record.source!=="ORPHAN_INTAKE") await db.query("SELECT 1 FROM applicants WHERE app_id=$1 FOR UPDATE", [record.applicantId]);
  if (record.source==="ORPHAN_INTAKE") await db.query("SELECT 1 FROM orphan_documents WHERE id=$1 FOR UPDATE", [record.eventId]);
  record = await getItCase(db,id);
  if (!record || record.fingerprint!==command.fingerprint) throw new ItActionError("The underlying error changed. Reload before taking action.");
  const key = record.caseId ? (await db.query("SELECT exception_key FROM it_exception_cases WHERE id=$1", [record.caseId])).rows[0].exception_key : record.id;
  await db.query(`INSERT INTO it_exception_cases(exception_key,fingerprint,applicant_id,source,snapshot)
    VALUES($1,$2,$3,$4,$5) ON CONFLICT(exception_key,fingerprint) DO NOTHING`, [key,record.fingerprint,record.source==="ORPHAN_INTAKE" ? null : record.applicantId,record.source,record]);
  const c: CaseRow = (await db.query("SELECT * FROM it_exception_cases WHERE exception_key=$1 AND fingerprint=$2 FOR UPDATE", [key,record.fingerprint])).rows[0];
  if (c.revision!==command.revision) throw new ItActionError("Another person or worker updated this case. Reload saved state.");
  if (["RESOLVED","SUPERSEDED"].includes(c.state)) throw new ItActionError("This incident is closed. A new failure needs its own case.");
  let state=c.state, owner=c.owner, evidence: Record<string,unknown> | null=null, jobId: string | null=null;
  if (command.action==="CLAIM") { state="IN_PROGRESS"; owner=command.actor; }
  if (command.action==="HANDOFF") { state="WAITING"; owner=command.owner; }
  if (command.action==="REQUEST_RETRY") {
    if (!record.active || !record.retryAllowed || !record.workerAvailable || record.source==="ORPHAN_INTAKE")
      throw new ItActionError("Retry is unavailable: use a current technical failure without a human disposition and an available worker.");
    if ((await db.query("SELECT 1 FROM it_retry_jobs WHERE applicant_id=$1 AND state IN ('QUEUED','RUNNING','NEEDS_RECHECK')", [record.applicantId])).rowCount)
      throw new ItActionError("This applicant already has an active or unconfirmed retry. Recheck its outcome first.");
    jobId=(await db.query(`INSERT INTO it_retry_jobs(case_id,command_id,applicant_id,source,source_version,failure_run_id)
      VALUES($1,$2,$3,$4,$5,$6) RETURNING id`, [c.id,command.commandId,record.applicantId,record.source,record.sourceVersion,record.failureRunId])).rows[0].id;
    state="WAITING"; owner=owner || command.actor;
  }
  if (command.action==="VERIFY_RESOLVED") {
    await db.query("LOCK TABLE policy_chunks IN SHARE MODE");
    if ((await db.query("SELECT 1 FROM it_retry_jobs WHERE case_id=$1 AND state IN ('QUEUED','RUNNING')", [c.id])).rowCount)
      throw new ItActionError("Wait for the saved retry to finish before verifying resolution.");
    evidence=await verifyItReceiver(db,record);
    if (!evidence) {
      const released=await db.query("UPDATE it_retry_jobs SET state='FAILED',finished_at=now(),result=$2 WHERE case_id=$1 AND state='NEEDS_RECHECK' RETURNING id",
        [c.id,{verified:false,message:"Receiver rechecked; no validated success found. Case remains open; a new explicit retry may be requested."}]);
      if (!released.rowCount) throw new ItActionError("The receiving system does not yet confirm a correction. The case remains open.");
      state="IN_PROGRESS";
    } else {
      state="RESOLVED";
      await db.query("UPDATE it_retry_jobs SET state='SUCCEEDED',finished_at=now(),result=$2 WHERE case_id=$1 AND state='NEEDS_RECHECK'",[c.id,evidence]);
    }
  }
  const result={ caseId:c.id, state, revision:c.revision+1, jobId, evidence, replayed:false };
  await db.query("UPDATE it_exception_cases SET state=$2,owner=$3,revision=revision+1,updated_at=now(),resolution_evidence=COALESCE($4,resolution_evidence) WHERE id=$1", [c.id,state,owner,evidence]);
  await db.query(`INSERT INTO it_exception_actions(command_id,case_id,action,actor,note,request,result)
    VALUES($1,$2,$3,$4,$5,$6,$7)`,[command.commandId,c.id,command.action,command.actor,command.note,{id,...command},result]);
  // Orphans have no applicant foreign key. Their action history is retained above.
  if (record.applicantId && record.source!=="ORPHAN_INTAKE") await db.query(`INSERT INTO audit_logs(id,applicant_id,action,actor,details,created_at)
    VALUES(gen_random_uuid(),$1,$2,$3,$4,now())`,[record.applicantId,`IT_EXCEPTION_${command.action}`,command.actor,
      { case_id:c.id,note:command.note,job_id:jobId,evidence,authentication:"SIMULATED_FOR_PROTOTYPE" }]);
  return result;
}
