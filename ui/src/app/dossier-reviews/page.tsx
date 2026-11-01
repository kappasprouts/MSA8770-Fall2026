import { redirect } from "next/navigation";
import { pool } from "@/lib/dossier";

export default async function Page({ searchParams }: { searchParams: Promise<{ requestId?: string | string[] }> }) {
  const { requestId } = await searchParams;
  const id = Array.isArray(requestId) ? requestId[0] : requestId;
  if (id && /^[a-f0-9-]{36}$/i.test(id)) {
    const { rows } = await pool.query("SELECT app_id FROM dossier_review_requests WHERE id=$1", [id]);
    if (rows[0]) redirect(`/applicant-review?appId=${encodeURIComponent(rows[0].app_id)}`);
  }
  redirect("/applicant-review");
}
