import path from "node:path";
import { NextResponse } from "next/server";
import { getDocumentObjectKey, minioClient, MINIO_BUCKET } from "@/lib/dossier";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const appId = params.get("appId") ?? "";
  const file = params.get("file") ?? "";

  const safeAppId = appId.replace(/[^a-zA-Z0-9_-]/g, "");
  const safeFile = path.basename(file);

  if (!safeAppId || !safeFile.toLowerCase().endsWith(".pdf")) {
    return NextResponse.json({ error: "Invalid appId or file." }, { status: 400 });
  }

  const objectKey = await getDocumentObjectKey(safeAppId, safeFile);

  if (!objectKey) {
    return NextResponse.json({ error: "Document not found." }, { status: 404 });
  }

  try {
    const stream = await minioClient.getObject(MINIO_BUCKET, objectKey);
    const chunks: Buffer[] = [];

    for await (const chunk of stream) {
      chunks.push(chunk as Buffer);
    }

    const buffer = Buffer.concat(chunks);

    return new NextResponse(new Uint8Array(buffer), {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `inline; filename="${safeFile}"`,
        "Cache-Control": "private, max-age=60",
      },
    });
  } catch {
    return NextResponse.json(
      { error: `Could not fetch "${objectKey}" from MinIO bucket "${MINIO_BUCKET}".` },
      { status: 502 }
    );
  }
}
