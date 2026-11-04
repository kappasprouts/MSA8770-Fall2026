import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { pool } from "@/lib/dossier";

export const dynamic = "force-dynamic";

const ALLOWED_RECOMMENDATIONS = [
  "ACCEPT",
  "WAITLIST",
  "DECLINE",
] as const;

const MAX_NOTE_LENGTH = 1000;

const SELECT_RECOMMENDATION = `
  SELECT
    app_id AS "appId",
    status AS "applicationStatus",
    final_decision AS "finalDecision",
    reviewer_recommendation AS "recommendation",
    reviewer_recommendation_note AS "note",
    reviewer_recommended_at AS "recommendedAt"
  FROM applicants
  WHERE app_id = $1
`;

export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id: appId } = await context.params;

  try {
    const { rows } = await pool.query(SELECT_RECOMMENDATION, [appId]);

    if (rows.length === 0) {
      return NextResponse.json(
        { error: "Applicant not found" },
        { status: 404 }
      );
    }

    return NextResponse.json(rows[0]);
  } catch (error) {
    console.error("Recommendation load error:", error);

    return NextResponse.json(
      { error: "Failed to load reviewer recommendation" },
      { status: 500 }
    );
  }
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id: appId } = await context.params;

  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON request" },
      { status: 400 }
    );
  }

  const fields =
    body !== null && typeof body === "object"
      ? (body as Record<string, unknown>)
      : {};
  const recommendation = fields.recommendation;
  const rawNote = fields.note ?? null;

  if (
    typeof recommendation !== "string" ||
    !ALLOWED_RECOMMENDATIONS.some(value => value === recommendation)
  ) {
    return NextResponse.json(
      { error: "Invalid recommendation" },
      { status: 400 }
    );
  }

  if (rawNote !== null && typeof rawNote !== "string") {
    return NextResponse.json(
      { error: "Invalid recommendation note" },
      { status: 400 }
    );
  }

  const note = rawNote?.trim() || null;

  if (note && note.length > MAX_NOTE_LENGTH) {
    return NextResponse.json(
      { error: `Rationale must be ${MAX_NOTE_LENGTH} characters or fewer.` },
      { status: 400 }
    );
  }

  const client = await pool.connect();

  try {
    await client.query("BEGIN");

    const previous = await client.query(
      `SELECT reviewer_recommendation FROM applicants WHERE app_id = $1 FOR UPDATE`,
      [appId]
    );

    // A recommendation can be revised until the Dean records the final decision.
    const result = await client.query(
      `
      UPDATE applicants
      SET reviewer_recommendation = $1,
          reviewer_recommendation_note = $2,
          reviewer_recommended_at = NOW(),
          updated_at = NOW()
      WHERE app_id = $3
        AND status = 'DOSSIER_READY'
        AND final_decision IS NULL
      RETURNING app_id
      `,
      [recommendation, note, appId]
    );

    if (result.rowCount !== 1) {
      await client.query("ROLLBACK");

      return NextResponse.json(
        {
          error:
            "Applicant is not eligible, not found, or already has a final decision.",
        },
        { status: 409 }
      );
    }

    await client.query(
      `
      INSERT INTO audit_logs
        (id, applicant_id, action, actor, details, created_at)
      VALUES
        ($1, $2, $3, $4, $5::jsonb, NOW())
      `,
      [
        randomUUID(),
        appId,
        "REVIEWER_RECOMMENDATION_RECORDED",
        "reviewer_simulated",
        JSON.stringify({
          recommendation,
          previous_recommendation:
            previous.rows[0]?.reviewer_recommendation ?? null,
          has_note: Boolean(note),
          source: "EAOS_UI_3",
          authentication: "SIMULATED_FOR_PROTOTYPE",
        }),
      ]
    );

    const { rows } = await client.query(SELECT_RECOMMENDATION, [appId]);

    await client.query("COMMIT");

    return NextResponse.json(rows[0]);
  } catch (error) {
    await client.query("ROLLBACK");

    console.error("Recommendation save error:", error);

    return NextResponse.json(
      { error: "Failed to save reviewer recommendation" },
      { status: 500 }
    );
  } finally {
    client.release();
  }
}
