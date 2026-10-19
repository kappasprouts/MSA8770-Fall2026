import { NextResponse } from "next/server";
import { listOriginalDocuments, loadDossier } from "@/lib/dossier";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const appId = new URL(request.url).searchParams.get("appId");

  if (!appId) {
    return NextResponse.json({ error: "appId query parameter is required." }, { status: 400 });
  }

  const data = await loadDossier(appId);

  if (!data) {
    return NextResponse.json({ error: `No dossier found for applicant "${appId}".` }, { status: 404 });
  }

  const documents = await listOriginalDocuments(appId, data);

  return NextResponse.json({ data, documents });
}
