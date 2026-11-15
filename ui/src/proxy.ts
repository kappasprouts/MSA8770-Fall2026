import { NextRequest, NextResponse } from "next/server";
import { canAccess, pagePermission } from "./lib/auth-policy";
import { SESSION_COOKIE, sessionUser } from "./lib/auth-session";

export async function proxy(request: NextRequest) {
  const permission = pagePermission(request.nextUrl.pathname);
  if (!permission) return NextResponse.next();
  let user;
  try { user = await sessionUser(request.cookies.get(SESSION_COOKIE)?.value); }
  catch { return new NextResponse("Sign-in service is unavailable. Please try again.", { status: 503, headers: { "Cache-Control": "no-store" } }); }
  if (!user) {
    const url = new URL("/login", request.url);
    url.searchParams.set("returnTo", request.nextUrl.pathname + request.nextUrl.search);
    return NextResponse.redirect(url);
  }
  if (!canAccess(user.role, permission)) return NextResponse.redirect(new URL("/access-denied", request.url));
  const response = NextResponse.next();
  response.headers.set("Cache-Control", "private, no-store");
  return response;
}

export const config = {
  matcher: ["/review-queue/:path*", "/applicant-review/:path*", "/final-decisions/:path*", "/statistics/:path*", "/error-queue/:path*"],
};
