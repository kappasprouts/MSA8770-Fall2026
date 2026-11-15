export const ROLES = ["ADMISSIONS_OFFICER", "DEAN", "IT_SUPPORT"] as const;
export type Role = typeof ROLES[number];
export type Permission = "processing" | "review" | "decisions" | "statistics" | "errors";
export type SessionUser = { userId: string; fullName: string; role: Role };

export const ROLE_LABELS: Record<Role, string> = {
  ADMISSIONS_OFFICER: "Admissions Officer", DEAN: "Dean", IT_SUPPORT: "IT Support",
};

const permissions: Record<Permission, readonly Role[]> = {
  processing: ["ADMISSIONS_OFFICER"],
  review: ["ADMISSIONS_OFFICER", "DEAN"],
  decisions: ["DEAN"],
  statistics: ["ADMISSIONS_OFFICER", "DEAN"],
  errors: ["IT_SUPPORT"],
};

export function isRole(role: unknown): role is Role {
  return ROLES.some(value => value === role);
}

export function canAccess(role: Role | undefined, permission: Permission): boolean {
  return !!role && permissions[permission].includes(role);
}

export function pagePermission(pathname: string): Permission | null {
  const routes: Record<string, Permission> = {
    "/review-queue": "processing", "/applicant-review": "review",
    "/final-decisions": "decisions", "/statistics": "statistics", "/error-queue": "errors",
  };
  return routes[`/${pathname.split("/")[1]}`] ?? null;
}

// Only known portal pages can be used as a post-login destination.
export function safeReturnTo(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || /[\\\s\u0000-\u001f]/.test(value)) return "/";
  try {
    const url = new URL(value, "https://portal.invalid");
    if (url.origin !== "https://portal.invalid" || (url.pathname !== "/" && !pagePermission(url.pathname))) return "/";
    return url.pathname + url.search;
  } catch { return "/"; }
}
