import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";
import { buildStatistics, parseStatisticsFilters, type StatisticsRow } from "@/lib/statistics";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  let filters;
  try { filters = parseStatisticsFilters(new URL(request.url).searchParams); }
  catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "Invalid filters." }, { status: 400 }); }
  try {
    // One database snapshot; the latest manifest result avoids counting historical missing documents.
    // No applicant identifiers, contact details, or source rows are returned to the browser.
    const { rows } = await pool.query<StatisticsRow>(`
      SELECT a.admission_year, a.admission_term, a.intended_major, a.status, a.final_decision,
        a.gender, a.ethnicity, a.country, a.region, a.name_of_hs,
        a.unweighted_gpa, a.weighted_gpa, a.superscored_sat_score, a.sat_math, a.sat_ebrw,
        a.superscored_act_score, a.act_composite, a.total_aps, a.total_ibs, a.create_date_time,
        gate.details AS gate
      FROM applicants a
      LEFT JOIN (
        SELECT DISTINCT ON (applicant_id) applicant_id, details
        FROM audit_logs
        WHERE action IN ('MANIFEST_EVALUATED', 'MANIFEST_REEVALUATED')
        ORDER BY applicant_id, created_at DESC, id DESC
      ) gate ON gate.applicant_id = a.app_id
    `);
    return NextResponse.json(buildStatistics(rows, filters), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("Statistics query failed:", error);
    return NextResponse.json({ error: "Summary statistics could not be loaded. Check the database connection and try again." }, { status: 503 });
  }
}
