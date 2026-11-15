import { NextRequest, NextResponse } from "next/server";
import { checkOrigin } from "@/lib/auth";
import { SESSION_COOKIE } from "@/lib/auth-session";
import { tokenHash } from "@/lib/auth-crypto.mjs";
import { pool } from "@/lib/db";

export async function POST(request: NextRequest) {
  const rejected = checkOrigin(request);
  if (rejected) return rejected;
  try {
    const token = request.cookies.get(SESSION_COOKIE)?.value;
    if (token) await pool.query("DELETE FROM auth_sessions WHERE token_hash = $1", [tokenHash(token)]);
    const response = NextResponse.json({ success: true }, { headers: { "Cache-Control": "no-store" } });
    response.cookies.set(SESSION_COOKIE, "", { httpOnly: true, sameSite: "lax", path: "/", maxAge: 0, secure: request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production" });
    return response;
  } catch {
    return NextResponse.json({ error: "Could not sign out. Please try again." }, { status: 503 });
  }
}
