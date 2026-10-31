import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import type { PoolClient } from "pg";
import { pool } from "@/lib/dossier";
import { isOfficerRecommendation, MAX_RECOMMENDATION_NOTES } from "@/lib/recommendation";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ id: string }> };

export async function GET(_request: NextRequest, context: Context) {
  const { id } = await context.params;
  try {
    const { rows } = await pool.query(`
      SELECT app_id AS "appId", officer_recommendation AS recommendation,
        COALESCE(officer_recommendation_notes, '') AS notes,
        officer_recommendation_updated_at AS "updatedAt",
        (status = 'DOSSIER_READY' AND final_decision IS NULL) AS "canEdit"
      FROM applicants WHERE app_id = $1
    `, [id]);
    if (!rows[0]) return NextResponse.json({ error: "Applicant not found." }, { status: 404 });
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

  let client: PoolClient | undefined;
  try {
    client = await pool.connect();
    await client.query("BEGIN");
    // The eligibility check and update share a row lock with final-decision writes.
    const { rows } = await client.query(`
      UPDATE applicants SET officer_recommendation = $1,
        officer_recommendation_notes = $2, officer_recommendation_updated_at = NOW(), updated_at = NOW()
      WHERE app_id = $3 AND status = 'DOSSIER_READY' AND final_decision IS NULL
      RETURNING app_id AS "appId", officer_recommendation AS recommendation,
        officer_recommendation_notes AS notes, officer_recommendation_updated_at AS "updatedAt",
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
      source: "APPLICANT_REVIEW_UI", authentication: "SIMULATED_FOR_PROTOTYPE",
    })]);
    await client.query("COMMIT");
    return NextResponse.json(rows[0]);
  } catch (error) {
    await client?.query("ROLLBACK").catch(() => {});
    console.error("Officer recommendation save error:", error);
    return NextResponse.json({ error: "Could not save the officer recommendation. Please try again." }, { status: 500 });
  } finally {
    client?.release();
  }
}
