
import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { pool } from "@/lib/dossier";

export const dynamic = "force-dynamic";

const ALLOWED_DECISIONS = [
  "ACCEPT",
  "WAITLIST",
  "DECLINE",
] as const;

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

  const decision =
    body !== null &&
    typeof body === "object" &&
    "final_decision" in body
      ? body.final_decision
      : undefined;

  if (
    typeof decision !== "string" ||
    !ALLOWED_DECISIONS.some(value => value === decision)
  ) {
    return NextResponse.json(
      { error: "Invalid final decision" },
      { status: 400 }
    );
  }

  const client = await pool.connect();

  try {
    await client.query("BEGIN");

    const result = await client.query(
      `
      UPDATE applicants
      SET final_decision = $1,
          updated_at = NOW()
      WHERE app_id = $2
        AND status = 'DOSSIER_READY'
        AND final_decision IS NULL
      RETURNING app_id
      `,
      [decision, appId]
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
        "FINAL_DECISION_RECORDED",
        "dean_simulated",
        JSON.stringify({
          final_decision: decision,
          previous_final_decision: null,
          source: "EAOS_UI_3",
          authentication: "SIMULATED_FOR_PROTOTYPE",
        }),
      ]
    );

    await client.query("COMMIT");

    return NextResponse.json({
      success: true,
      appId,
      final_decision: decision,
    });
  } catch (error) {
    await client.query("ROLLBACK");

    console.error("Final decision error:", error);

    return NextResponse.json(
      { error: "Failed to save final decision" },
      { status: 500 }
    );
  } finally {
    client.release();
  }
}
