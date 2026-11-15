// Run against a local running UI: node --env-file=.env.local tests/auth-integration.mjs
// Only uniquely named test users, an applicant, and their audit/session rows are changed.
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { hashPassword, tokenHash } from "../src/lib/auth-crypto.mjs";

const base = process.env.AUTH_TEST_BASE_URL ?? "http://localhost:3001";
if (!["localhost", "127.0.0.1"].includes(new URL(base).hostname)) throw Error("Run only against a local test server.");
const client = new pg.Client({
  host: process.env.POSTGRES_HOST, port: Number(process.env.POSTGRES_PORT ?? 5432),
  database: process.env.POSTGRES_DB, user: process.env.POSTGRES_USER, password: process.env.POSTGRES_PASSWORD,
});
const suffix = randomBytes(3).toString("hex").toUpperCase();
const appId = `AT${suffix}`;
const password = randomBytes(20).toString("hex");
const users = ["ADMISSIONS_OFFICER", "DEAN", "IT_SUPPORT"].map((role, i) => ({ id: `AUTH${suffix}${i}`, role }));
let checks = 0;
async function call(path, { cookie, method = "GET", body, origin = base } = {}) {
  const response = await fetch(base + path, { method, redirect: "manual", headers: {
    ...(cookie ? { cookie } : {}), ...(method !== "GET" ? { origin, "content-type": "application/json" } : {}),
  }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) });
  checks++; return response;
}
async function login(user, returnTo = "/") {
  const response = await call("/api/auth/login", { method: "POST", body: { userId: user.id, password, returnTo } });
  assert.equal(response.status, 200);
  const setCookie = response.headers.get("set-cookie");
  assert.match(setCookie, /HttpOnly/i); assert.match(setCookie, /SameSite=lax/i);
  return { cookie: setCookie.split(";")[0], redirectTo: (await response.json()).redirectTo };
}

await client.connect();
try {
  for (const user of users) await client.query("INSERT INTO system_users (user_id, full_name, email, role, password_hash) VALUES ($1,$2,$3,$4,$5)", [user.id, "Authentication test", `${user.id}@example.invalid`, user.role, await hashPassword(password)]);
  await client.query(`INSERT INTO applicants (app_id, first_name, status, admission_year, admission_term, ap_test_scores, ib_test_scores, activities, awards, hooks, documents, created_at, updated_at)
    VALUES ($1, 'Authentication test', 'DOSSIER_READY', 2026, 'F', '[]', '[]', '[]', '[]', '[]', '[]', NOW(), NOW())`, [appId]);
  assert.equal((await call("/")).status, 200);
  const protectedPage = await call(`/applicant-review?appId=${appId}`);
  assert.equal(protectedPage.status, 307);
  assert.equal(new URL(protectedPage.headers.get("location"), base).searchParams.get("returnTo"), `/applicant-review?appId=${appId}`);
  assert.equal((await call("/api/applicants")).status, 401);
  assert.equal((await call("/api/applicants", { cookie: "rsu_session=forged" })).status, 401);
  assert.equal((await call("/api/auth/login", { method: "POST", body: { userId: users[0].id, password: "wrong" } })).status, 401);
  assert.equal((await call("/api/auth/login", { method: "POST", origin: "https://evil.invalid", body: {} })).status, 403);

  const sessions = [];
  for (const user of users) sessions.push(await login(user));
  const [officer, dean, it] = sessions;
  assert.equal((await login(users[0], `/applicant-review?appId=${appId}`)).redirectTo, `/applicant-review?appId=${appId}`);
  assert.equal((await login(users[2], "/final-decisions")).redirectTo, "/access-denied");
  const reads = [
    ["/api/applicants", [200, 200, 403]],
    ["/api/applicants/review-queue", [200, 403, 403]],
    ["/api/applicants/final-decision-queue", [403, 200, 403]],
    ["/api/statistics", [200, 200, 403]], ["/api/exceptions", [403, 403, 200]],
    [`/api/applicants/${appId}/recommendation`, [200, 200, 403]],
    ["/api/dossier", [400, 400, 403]], ["/api/documents", [400, 400, 403]],
  ];
  for (const [path, statuses] of reads) for (let i = 0; i < 3; i++) assert.equal((await call(path, sessions[i])).status, statuses[i], `${users[i].role}: ${path}`);
  for (const [path, allowed] of [["/review-queue", [true,false,false]], ["/applicant-review", [true,true,false]], ["/final-decisions", [false,true,false]], ["/statistics", [true,true,false]], ["/error-queue", [false,false,true]], ["/error-queue/test", [false,false,true]]]) {
    for (let i = 0; i < 3; i++) {
      const result = await call(path, sessions[i]);
      assert.equal(result.status, allowed[i] ? 200 : 307, `${users[i].role}: ${path}`);
      if (!allowed[i]) assert.equal(new URL(result.headers.get("location"), base).pathname, "/access-denied");
    }
  }
  for (const session of [officer, it]) assert.equal((await call(`/api/applicants/${appId}/final-decision`, { ...session, method: "PUT", body: { final_decision: "ACCEPT" } })).status, 403);
  assert.equal((await call(`/api/applicants/${appId}/recommendation`, { ...it, method: "PUT", body: { recommendation: "ACCEPT" } })).status, 403);
  assert.equal((await call(`/api/applicants/${appId}/recommendation`, { ...officer, method: "PUT", body: { recommendation: "WAITLIST", actor: "spoof" } })).status, 200);
  assert.equal((await call(`/api/applicants/${appId}/final-decision`, { ...dean, method: "PUT", body: { final_decision: "ACCEPT", actor: "spoof" } })).status, 200);
  const { rows: audit } = await client.query("SELECT action, actor, details FROM audit_logs WHERE applicant_id=$1 ORDER BY created_at", [appId]);
  assert.equal(audit.length, 2); assert.equal(audit[0].actor, users[0].id); assert.equal(audit[1].actor, users[1].id);
  assert.equal(audit[0].details.authentication, "AUTHENTICATED_SESSION");
  await client.query("UPDATE system_users SET is_active = false WHERE user_id=$1", [users[0].id]);
  assert.equal((await call("/api/applicants", officer)).status, 401);
  assert.equal((await call("/api/auth/login", { method: "POST", body: { userId: users[0].id, password } })).status, 401);
  await client.query("UPDATE auth_sessions SET expires_at=NOW()-INTERVAL '1 second' WHERE user_id=$1", [users[2].id]);
  assert.equal((await call("/api/exceptions", it)).status, 401);
  assert.equal((await call("/api/auth/logout", { ...dean, method: "POST" })).status, 200);
  assert.equal((await call("/api/applicants", dean)).status, 401);
  const account = `LIMIT${suffix}`;
  for (let i = 0; i < 10; i++) assert.equal((await call("/api/auth/login", { method: "POST", body: { userId: account, password: "wrong" } })).status, 401);
  const limited = await call("/api/auth/login", { method: "POST", body: { userId: account, password: "wrong" } });
  assert.equal(limited.status, 429); assert.ok(Number(limited.headers.get("retry-after")) > 0);
  console.log(`Passed ${checks} live HTTP checks: role matrix, page routing, writes/audit, invalid/inactive accounts, expiry, logout and throttling.`);
} finally {
  await client.query("DELETE FROM audit_logs WHERE applicant_id=$1", [appId]);
  await client.query("DELETE FROM applicants WHERE app_id=$1", [appId]);
  for (const user of users) {
    await client.query("DELETE FROM system_users WHERE user_id=$1", [user.id]);
    await client.query("DELETE FROM auth_login_attempts WHERE account_key=$1", [tokenHash(user.id)]);
  }
  await client.query("DELETE FROM auth_login_attempts WHERE account_key=$1", [tokenHash(`LIMIT${suffix}`)]);
  await client.end();
}
