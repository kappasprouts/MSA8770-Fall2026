import { NextResponse } from "next/server";
import { listApplicants } from "@/lib/dossier";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ applicants: await listApplicants() });
}
