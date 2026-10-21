import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const { rows } = await pool.query(`
      SELECT
        app_id AS "appId",
        first_name AS "firstName",
        last_name AS "lastName",
        intended_major AS "intendedMajor",
        status AS "applicationStatus",
        final_decision AS "finalDecision",
        updated_at AS "lastUpdated"
      FROM applicants
        WHERE status = 'DOSSIER_READY'
        AND final_decision IS NULL
      ORDER BY app_id;
    `);

    return NextResponse.json({ applicants: rows });
  } catch (error) {
    console.error("Final decision queue error:", error);

    return NextResponse.json(
      { error: "Failed to load final decision queue" },
      { status: 500 }
    );
  }
}
