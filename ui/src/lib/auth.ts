import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { canAccess, type Permission } from "./auth-policy";
import { SESSION_COOKIE, sessionUser } from "./auth-session";

export async function currentUser() {
  return sessionUser((await cookies()).get(SESSION_COOKIE)?.value);
}

export function checkOrigin(request: Request): NextResponse | null {
  const origin = request.headers.get("origin");
  if (!origin || origin !== new URL(request.url).origin) {
    return NextResponse.json({ error: "Please submit this request from the admissions portal." }, { status: 403 });
  }
  return null;
}

export async function authorizeApi(permission: Permission, request?: Request) {
  if (request && !["GET", "HEAD"].includes(request.method)) {
    const response = checkOrigin(request);
    if (response) return { user: null, response };
  }
  try {
    const user = await currentUser();
    if (!user) return { user: null, response: NextResponse.json({ error: "Please sign in to continue." }, { status: 401 }) };
    if (!canAccess(user.role, permission)) return { user: null, response: NextResponse.json({ error: "You are not authorized to access this resource." }, { status: 403 }) };
    return { user, response: null };
  } catch {
    return { user: null, response: NextResponse.json({ error: "Sign-in service is unavailable. Please try again." }, { status: 503 }) };
  }
}
