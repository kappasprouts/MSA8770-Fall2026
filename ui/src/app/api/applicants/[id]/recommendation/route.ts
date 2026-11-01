import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import type { PoolClient } from "pg";
import { pool } from "@/lib/dossier";
import { isOfficerRecommendation, MAX_RECOMMENDATION_NOTES, validExceptionResolution } from "@/lib/recommendation";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ id: string }> };

export async function GET(_request: NextRequest, context: Context) {
  const { id } = await context.params;
  try {
    await pool.query("SELECT reconcile_dossier_reviews($1)", [id]);
    const { rows } = await pool.query(`
      SELECT app_id AS "appId", officer_recommendation AS recommendation,
        COALESCE(officer_recommendation_notes, '') AS notes,
        officer_recommendation_updated_at AS "updatedAt",
        status AS "applicationStatus",
        (status IN ('DOSSIER_READY', 'REVIEWED', 'REVIEW_PENDING') AND final_decision IS NULL) AS "canEdit"
      FROM applicants WHERE app_id = $1
    `, [id]);
    if (!rows[0]) return NextResponse.json({ error: "Applicant not found." }, { status: 404 });
    const { rows: versions } = await pool.query(`SELECT id AS "requestId", candidate_hash AS "candidateHash", state,
      requires_evidence_review AS "requiresEvidenceReview", exception_reasons AS reasons, expires_at AS "expiresAt",
      outcome_reason AS "outcomeReason", reviewer, reason, input_snapshot=checkpoint_input_snapshot(app_id) AS fresh
      FROM dossier_review_requests WHERE app_id=$1 ORDER BY requested_at DESC LIMIT 1`, [id]);
    if (versions[0]) {
      rows[0].version = versions[0];
      if (!versions[0].fresh || !["PUBLISHED", "REVIEW_PENDING"].includes(versions[0].state)) rows[0].canEdit = false;
    }
    return NextResponse.json(rows[0]);
  } catch (error) {
    console.error("Officer recommendation load error:", error);
    return NextResponse.json({ error: "Could not load the officer recommendation." }, { status: 500 });
  }
}

export async function PUT(request: NextRequest, context: Context) {
  const { id } = await context.params;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON request." }, { status: 400 });
  }
  if (!body || typeof body !== "object" || !("recommendation" in body) ||
    !isOfficerRecommendation(body.recommendation)) {
    return NextResponse.json({ error: "Choose Accept, Reject, or Waitlist." }, { status: 400 });
  }
  if (!("notes" in body) || typeof body.notes !== "string" || body.notes.length > MAX_RECOMMENDATION_NOTES) {
    return NextResponse.json({ error: `Notes must be text of at most ${MAX_RECOMMENDATION_NOTES.toLocaleString("en-US")} characters.` }, { status: 400 });
  }
  const resolution = "resolution" in body ? body.resolution : undefined;
  if (resolution !== undefined && !validExceptionResolution(resolution)) {
    return NextResponse.json({ error: "An explicit exception resolution, reviewer, reason and confirmation are required." }, { status: 400 });
  }

  let client: PoolClient | undefined;
  try {
    client = await pool.connect();
    await client.query("BEGIN");
    const locked = await client.query("SELECT * FROM applicants WHERE app_id=$1 FOR UPDATE", [id]);
    if (!locked.rows[0] || locked.rows[0].final_decision) {
      await client.query("ROLLBACK");
      return NextResponse.json({ error: "This applicant is unavailable for review or already has a final decision." }, { status: 409 });
    }
    await client.query("LOCK TABLE policy_chunks IN SHARE MODE");
    await client.query("SELECT reconcile_dossier_reviews($1)", [id]);
    const versionResult = await client.query(`SELECT *, input_snapshot=checkpoint_input_snapshot(app_id) AS fresh
      FROM dossier_review_requests WHERE app_id=$1 ORDER BY requested_at DESC LIMIT 1 FOR UPDATE`, [id]);
    const version = versionResult.rows[0];
    if (version) {
      const scope = "version" in body ? body.version as Record<string, unknown> | null : null;
      if (!scope || scope.requestId !== version.id || scope.candidateHash !== version.candidate_hash || !version.fresh ||
          !["REVIEW_PENDING", "PUBLISHED"].includes(version.state)) {
        await client.query("ROLLBACK");
        return NextResponse.json({ error: "The dossier version changed, expired, or needs correction. Reload the applicant before recommending." }, { status: 409 });
      }
      if (version.state === "REVIEW_PENDING" && !validExceptionResolution(resolution)) {
        await client.query("ROLLBACK");
        return NextResponse.json({ error: "Resolve the identified exceptions before saving your recommendation." }, { status: 409 });
      }
      if (validExceptionResolution(resolution)) {
        const result = await client.query("SELECT decide_dossier_review($1,$2,'PUBLISH_ADVISORY_DOSSIER','APPROVE',$3,$4,$5,$6) AS result",
          [version.id, version.candidate_hash, resolution.reviewer, resolution.reason, resolution.confirmed, resolution.evidenceReviewed]);
        if (result.rows[0].result.error) {
          await client.query("ROLLBACK");
          return NextResponse.json({ error: result.rows[0].result.error }, { status: result.rows[0].result.status });
        }
      }
    } else if (resolution !== undefined) {
      await client.query("ROLLBACK");
      return NextResponse.json({ error: "There is no saved exception request for this applicant." }, { status: 409 });
    }
    // The eligibility check and update share a row lock with final-decision writes.
    const { rows } = await client.query(`
      UPDATE applicants SET officer_recommendation = $1,
        officer_recommendation_notes = $2, officer_recommendation_updated_at = NOW(),
        status = 'REVIEWED', updated_at = NOW()
      WHERE app_id = $3 AND status IN ('DOSSIER_READY', 'REVIEWED') AND final_decision IS NULL
      RETURNING app_id AS "appId", officer_recommendation AS recommendation,
        officer_recommendation_notes AS notes, officer_recommendation_updated_at AS "updatedAt",
        status AS "applicationStatus",
        TRUE AS "canEdit"
    `, [body.recommendation, body.notes, id]);
    if (!rows[0]) {
      await client.query("ROLLBACK");
      return NextResponse.json({ error: "This applicant is unavailable for review or already has a final decision. Reload the recommendation to see the current state." }, { status: 409 });
    }
    await client.query(`
      INSERT INTO audit_logs (id, applicant_id, action, actor, details, created_at)
      VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
    `, [randomUUID(), id, "OFFICER_RECOMMENDATION_SAVED", "officer_simulated", JSON.stringify({
      recommendation: body.recommendation, notes: body.notes,
      status: "REVIEWED",
      source: "APPLICANT_REVIEW_UI", authentication: "SIMULATED_FOR_PROTOTYPE",
      request_id: version?.id ?? null, candidate_hash: version?.candidate_hash ?? null,
      exception_resolution: resolution ?? null,
    })]);
    await client.query("COMMIT");
    if (version) rows[0].version = { requestId: version.id, candidateHash: version.candidate_hash,
      state: "PUBLISHED", requiresEvidenceReview: version.requires_evidence_review,
      reasons: version.exception_reasons, expiresAt: version.expires_at,
      reviewer: validExceptionResolution(resolution) ? resolution.reviewer : version.reviewer,
      reason: validExceptionResolution(resolution) ? resolution.reason : version.reason };
    return NextResponse.json(rows[0]);
  } catch (error) {
    await client?.query("ROLLBACK").catch(() => {});
    console.error("Officer recommendation save error:", error);
    return NextResponse.json({ error: "Could not save the officer recommendation. Please try again." }, { status: 500 });
  } finally {
    client?.release();
  }
}
