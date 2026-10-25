import { NextResponse } from "next/server";
import { listOriginalDocuments, loadDossier } from "@/lib/dossier";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const appId = new URL(request.url).searchParams.get("appId");

  if (!appId) {
    return NextResponse.json({ error: "appId query parameter is required." }, { status: 400 });
  }

  try {
    const data = await loadDossier(appId);
    if (!data) {
      return NextResponse.json({ error: `No saved dossier was found for ${appId}. Choose another applicant or check the processing dashboard.` }, { status: 404 });
    }
    const documents = await listOriginalDocuments(appId, data);
    return NextResponse.json({ data, documents });
  } catch (error) {
    console.error("Dossier unavailable:", error);
    return NextResponse.json({ error: "The dossier is unavailable. Check the data service and try again." }, { status: 503 });
  }
}
