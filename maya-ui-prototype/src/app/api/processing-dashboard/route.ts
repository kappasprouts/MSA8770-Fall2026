import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";

export const dynamic = "force-dynamic";

// This endpoint lists ALL applicants, unlike /api/applicants which lists dossiers only.
export async function GET() {
  try {
    const { rows } = await pool.query<{
      app_id: string; first_name: string; last_name: string;
      intended_major: string | null; status: string; final_decision: string | null;
      has_dossier: boolean;
    }>(`SELECT a.app_id, a.first_name, a.last_name, a.intended_major,
                 a.status, a.final_decision,
                 EXISTS (SELECT 1 FROM applicant_dossier d WHERE d.app_id = a.app_id) AS has_dossier
          FROM applicants a ORDER BY a.app_id`);
    return NextResponse.json({ applicants: rows }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("Processing dashboard query failed", error);
    return NextResponse.json({ error: "Could not load applicant processing records." }, { status: 503 });
  }
}
