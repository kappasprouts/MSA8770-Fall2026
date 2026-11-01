import { createHash } from "node:crypto";
import { NextResponse } from "next/server";
import { pool, minioClient, MINIO_BUCKET } from "@/lib/dossier";
import { isReviewId } from "@/lib/dossier-review";
export const dynamic = "force-dynamic";

export async function GET(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const file = new URL(request.url).searchParams.get("file");
  if (!isReviewId(id) || !file || !file.toLowerCase().endsWith(".pdf")) return NextResponse.json({ error: "Invalid document selection." }, { status: 400 });
  try {
    const { rows } = await pool.query("SELECT input_snapshot->'applicant'->'documents' AS documents FROM dossier_review_requests WHERE id=$1", [id]);
    const docs: { filename: string; bucket?: string; key: string; sha256?: string }[] = rows[0]?.documents ?? [];
    const matches = docs.filter(doc => doc.filename === file);
    if (matches.length !== 1 || !matches[0].key) return NextResponse.json({ error: "A unique saved source was not found." }, { status: 404 });
    const doc = matches[0];
    if (!doc.sha256 || !/^[a-f0-9]{64}$/i.test(doc.sha256)) return NextResponse.json({ error: "Source checksum is unavailable; reconcile the source before approving." }, { status: 409 });
    const stream = await minioClient.getObject(doc.bucket || MINIO_BUCKET, doc.key);
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const chunk of stream) {
      const bytes = Buffer.from(chunk);
      size += bytes.length;
      if (size > 15 * 1024 * 1024) { stream.destroy(); throw new Error("Oversized source"); }
      chunks.push(bytes);
    }
    const buffer = Buffer.concat(chunks);
    if (createHash("sha256").update(buffer).digest("hex") !== doc.sha256.toLowerCase()) return NextResponse.json({ error: "Source bytes changed. Do not approve; regenerate from reconciled inputs." }, { status: 409 });
    return new NextResponse(new Uint8Array(buffer), { headers: { "Content-Type": "application/pdf",
      "Content-Disposition": `inline; filename*=UTF-8''${encodeURIComponent(file)}`, "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "The saved source is unavailable; publication should remain pending." }, { status: 503 });
  }
}
