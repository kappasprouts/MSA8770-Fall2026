import { NextResponse } from "next/server";
import { pool } from "@/lib/dossier";
import { parseItAction } from "@/lib/it-actions";
import { applyItAction, getItCase, ItActionError } from "@/lib/it-exception-store";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ id: string }> };
export async function GET(_request: Request, context: Context) {
  try {
    const record=await getItCase(pool,(await context.params).id);
    return record ? NextResponse.json({ record }) : NextResponse.json({error:"Exception not found."},{status:404});
  } catch { return NextResponse.json({error:"The saved IT case is unavailable."},{status:503}); }
}
export async function PUT(request: Request, context: Context) {
  let body: unknown;
  try { body=await request.json(); } catch { return NextResponse.json({error:"Invalid JSON."},{status:400}); }
  const command=parseItAction(body);
  if (!command) return NextResponse.json({error:"Choose an action and provide actor, note, current version and required confirmation."},{status:400});
  const client=await pool.connect().catch(()=>null);
  if (!client) return NextResponse.json({error:"The data service is unavailable. No action was submitted."},{status:503});
  try {
    await client.query("BEGIN");
    const result=await applyItAction(client,(await context.params).id,command);
    await client.query("COMMIT");
    return NextResponse.json(result);
  } catch (error) {
    await client.query("ROLLBACK").catch(()=>{});
    return NextResponse.json({error:error instanceof ItActionError ? error.message : "Action outcome unconfirmed. Reload saved state or replay the same command before retrying."},
      {status:error instanceof ItActionError ? error.status : 503});
  } finally { client.release(); }
}
