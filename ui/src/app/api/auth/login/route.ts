import { NextRequest, NextResponse } from "next/server";
import { pool } from "@/lib/db";
import { checkOrigin } from "@/lib/auth";
import { canAccess, isRole, pagePermission, safeReturnTo } from "@/lib/auth-policy";
import { DUMMY_PASSWORD_HASH, newSessionToken, tokenHash, verifyPassword } from "@/lib/auth-crypto.mjs";
import { SESSION_COOKIE, SESSION_SECONDS } from "@/lib/auth-session";

export async function POST(request: NextRequest) {
  const rejected = checkOrigin(request);
  if (rejected) return rejected;
  let body;
  try { body = await request.json(); }
  catch { return NextResponse.json({ error: "Invalid sign-in request." }, { status: 400 }); }
  const userId = typeof body?.userId === "string" ? body.userId.trim().toUpperCase() : "";
  const password = body?.password;
  if (!userId || userId.length > 20 || typeof password !== "string" || !password || password.length > 1024) {
    return NextResponse.json({ error: "Enter your User ID and password." }, { status: 400 });
  }
  try {
    const { rows: attempts } = await pool.query(
      `INSERT INTO auth_login_attempts (account_key, attempts) VALUES ($1, 1)
       ON CONFLICT (account_key) DO UPDATE SET
         attempts = CASE WHEN auth_login_attempts.window_started_at < NOW() - INTERVAL '15 minutes' THEN 1 ELSE auth_login_attempts.attempts + 1 END,
         window_started_at = CASE WHEN auth_login_attempts.window_started_at < NOW() - INTERVAL '15 minutes' THEN NOW() ELSE auth_login_attempts.window_started_at END
       RETURNING attempts, window_started_at`, [tokenHash(userId)],
    );
    if (attempts[0].attempts > 10) {
      const seconds = Math.max(1, Math.ceil((new Date(attempts[0].window_started_at).getTime() + 900_000 - Date.now()) / 1000));
      return NextResponse.json({ error: "Too many sign-in attempts. Please try again in 15 minutes." }, { status: 429, headers: { "Retry-After": String(seconds) } });
    }
    const { rows } = await pool.query(
      "SELECT user_id, role, is_active, password_hash FROM system_users WHERE user_id = $1", [userId],
    );
    const user = rows[0];
    const valid = await verifyPassword(password, user?.password_hash ?? DUMMY_PASSWORD_HASH);
    if (!valid || !user?.is_active || !isRole(user.role)) {
      return NextResponse.json({ error: "Invalid User ID or password. Please try again." }, { status: 401 });
    }
    const token = newSessionToken();
    // Rotate the browser's previous session and remove expired records.
    await pool.query("DELETE FROM auth_sessions WHERE token_hash = $1 OR expires_at <= NOW()", [tokenHash(request.cookies.get(SESSION_COOKIE)?.value ?? "")]);
    await pool.query("INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES ($1, $2, NOW() + INTERVAL '8 hours')", [tokenHash(token), user.user_id]);
    await pool.query("DELETE FROM auth_login_attempts WHERE account_key = $1 OR window_started_at < NOW() - INTERVAL '15 minutes'", [tokenHash(userId)]);
    const destination = safeReturnTo(body.returnTo);
    const permission = pagePermission(new URL(destination, request.url).pathname);
    const response = NextResponse.json({ redirectTo: permission && !canAccess(user.role, permission) ? "/access-denied" : destination }, { headers: { "Cache-Control": "no-store" } });
    response.cookies.set(SESSION_COOKIE, token, {
      httpOnly: true, sameSite: "lax", path: "/", maxAge: SESSION_SECONDS,
      secure: request.nextUrl.protocol === "https:" || process.env.NODE_ENV === "production",
    });
    return response;
  } catch {
    return NextResponse.json({ error: "Sign-in service is unavailable. Please try again." }, { status: 503 });
  }
}
