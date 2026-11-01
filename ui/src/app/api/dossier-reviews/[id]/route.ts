import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";
import { isReviewId, parseReviewDecision } from "@/lib/dossier-review";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ id: string }> };

export async function GET(_request: Request, context: Context) {
  const { id } = await context.params;
  if (!isReviewId(id)) return NextResponse.json({ error: "Invalid review ID." }, { status: 400 });
  try {
    await pool.query("SELECT reconcile_dossier_reviews()");
    const { rows } = await pool.query(`SELECT r.*, g.validation FROM dossier_review_requests r
      JOIN dossier_generation_runs g ON g.id=r.generation_run_id WHERE r.id=$1`, [id]);
    return rows[0] ? NextResponse.json(rows[0]) : NextResponse.json({ error: "Review not found." }, { status: 404 });
  } catch {
    return NextResponse.json({ error: "Could not load the saved review." }, { status: 503 });
  }
}

export async function PUT(request: Request, context: Context) {
  const { id } = await context.params;
  let body;
  try { body = parseReviewDecision(await request.json()); } catch { body = null; }
  if (!isReviewId(id) || !body) return NextResponse.json({ error: "An explicit scoped decision, confirmation, reviewer and reason are required." }, { status: 400 });
  try {
    const { rows } = await pool.query("SELECT decide_dossier_review($1,$2,$3,$4,$5,$6,$7,$8) AS result",
      [id,body.candidateHash,body.action,body.decision,body.reviewer,body.reason,body.confirmed,body.evidenceReviewed]);
    const result = rows[0].result;
    return NextResponse.json(result, { status: result.status });
  } catch {
    // The stored function's transaction rolls back on any failed receiver/audit
    // write. A retry after a lost response returns the durable receipt.
    return NextResponse.json({ error: "Decision outcome is unconfirmed. Reload this review before retrying; a committed outcome will show its saved receipt." }, { status: 503 });
  }
}
