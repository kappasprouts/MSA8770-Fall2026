import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";
import { listItCases } from "@/lib/it-exception-store";
export const dynamic = "force-dynamic";
export async function GET() {
  try { return NextResponse.json({ exceptions: await listItCases(pool) }); }
  catch (error) {
    console.error("IT exception load failed:", error);
    return NextResponse.json({ error: "Could not load the IT queue. Check the database and IT-action migration." }, { status: 503 });
  }
}
