import { NextResponse } from "next/server";
import { listApplicants } from "@/lib/dossier";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json({ applicants: await listApplicants() });
  } catch (error) {
    console.error("Applicant list unavailable:", error);
    return NextResponse.json({ error: "Applicant records are unavailable. Check the data service and try again." }, { status: 503 });
  }
}
