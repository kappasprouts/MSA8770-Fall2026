import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    await pool.query("SELECT reconcile_dossier_reviews()");
    const { rows } = await pool.query(`SELECT id,app_id,state,candidate_hash,expires_at,requested_at,
      review_owner,escalation_owner FROM dossier_review_requests
      ORDER BY (state='REVIEW_PENDING') DESC,requested_at DESC LIMIT 100`);
    return NextResponse.json({ reviews: rows });
  } catch {
    return NextResponse.json({ error: "Dossier review is unavailable. Check the service and apply the durable-review migration." }, { status: 503 });
  }
}
