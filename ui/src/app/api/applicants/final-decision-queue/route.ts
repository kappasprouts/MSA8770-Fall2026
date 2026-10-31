import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const { rows } = await pool.query(`
      WITH pending AS (SELECT
        app_id AS "appId",
        first_name AS "firstName",
        last_name AS "lastName",
        intended_major AS "intendedMajor",
        status AS "applicationStatus",
        final_decision AS "finalDecision",
        officer_recommendation AS "officerRecommendation",
        officer_recommendation_notes AS "officerRecommendationNotes",
        updated_at AS "lastUpdated"
      FROM applicants
        WHERE status IN ('DOSSIER_READY', 'REVIEWED')
        AND final_decision IS NULL
      )
      SELECT
        COALESCE((SELECT json_agg(p ORDER BY p."appId") FROM pending p), '[]'::json) AS applicants,
        json_build_object(
          'awaiting', COUNT(*) FILTER (WHERE status IN ('DOSSIER_READY', 'REVIEWED') AND final_decision IS NULL),
          'recorded', COUNT(*) FILTER (WHERE final_decision IS NOT NULL),
          'total', COUNT(*)
        ) AS totals
      FROM applicants;
    `);

    // One SQL statement keeps the queue and system-wide totals in the same snapshot.
    return NextResponse.json(rows[0]);
  } catch (error) {
    console.error("Final decision queue error:", error);

    return NextResponse.json(
      { error: "Failed to load final decision queue" },
      { status: 500 }
    );
  }
}
