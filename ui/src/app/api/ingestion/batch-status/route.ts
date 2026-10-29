import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch(
      "http://127.0.0.1:8000/ingestion/batch/status",
      { cache: "no-store", signal: AbortSignal.timeout(5000) }
    );

    if (!response.ok) {
      throw new Error(`FastAPI returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Failed to retrieve batch status:", error);

    return NextResponse.json(
      { error: "Batch status is currently unavailable." },
      { status: 503 }
    );
  }
}
