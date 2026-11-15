import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";
import { NextRequest, NextResponse } from "next/server.js";
import * as crypto from "../src/lib/auth-crypto.mjs";

const require = createRequire(import.meta.url);
function load(path, aliases = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const loaded = { exports: {} };
  new Function("require", "module", "exports", compiled)(name => Object.hasOwn(aliases, name) ? aliases[name] : require(name), loaded, loaded.exports);
  return loaded.exports;
}
const policy = load("../src/lib/auth-policy.ts");

test("permissions match every cell in the supplied role matrix", () => {
  const expected = {
    ADMISSIONS_OFFICER: [true, true, false, true, false],
    DEAN: [false, true, true, true, false], IT_SUPPORT: [false, false, false, false, true],
  };
  for (const [role, allowed] of Object.entries(expected)) {
    assert.deepEqual(["processing", "review", "decisions", "statistics", "errors"].map(p => policy.canAccess(role, p)), allowed);
  }
  assert.equal(policy.canAccess(undefined, "review"), false);
  assert.equal(policy.isRole("OFFICER"), false);
  assert.equal(policy.pagePermission("/error-queue/incident-1"), "errors");
  assert.equal(policy.pagePermission("/"), null);
});

test("login preserves applicant query parameters and rejects external or recursive redirects", () => {
  assert.equal(policy.safeReturnTo("/applicant-review?appId=APP_012"), "/applicant-review?appId=APP_012");
  for (const value of [null, ["/statistics"], "//evil.test", "https://evil.test", "/\\evil.test", "/login", "/api/documents", "/%2f%2fevil.test", "/statistics\n"]) {
    assert.equal(policy.safeReturnTo(value), "/");
  }
});

test("passwords use salted hashes and sessions use unpredictable opaque tokens", async () => {
  const first = await crypto.hashPassword("test-password");
  const second = await crypto.hashPassword("test-password");
  assert.notEqual(first, second);
  assert.equal(await crypto.verifyPassword("test-password", first), true);
  assert.equal(await crypto.verifyPassword("wrong-password", first), false);
  for (const hash of [null, "test-password", "scrypt$bad$bad", first + "$extra"]) assert.equal(await crypto.verifyPassword("test-password", hash), false);
  const token = crypto.newSessionToken();
  assert.match(token, /^[a-f0-9]{64}$/);
  assert.notEqual(token, crypto.newSessionToken());
  assert.notEqual(crypto.tokenHash(token), token);
});

test("session lookup uses a hashed token and checks active account, expiry and role", async () => {
  let calls = 0;
  let row = { user_id: "USR001", full_name: "Officer", role: "ADMISSIONS_OFFICER" };
  const sessions = load("../src/lib/auth-session.ts", {
    "./db": { pool: { query: async (sql, values) => {
      calls++; assert.match(sql, /expires_at > NOW\(\)/); assert.match(sql, /is_active = TRUE/);
      assert.equal(values[0], crypto.tokenHash("a".repeat(64))); return { rows: row ? [row] : [] };
    } } }, "./auth-policy": policy, "./auth-crypto.mjs": crypto,
  });
  assert.equal(await sessions.sessionUser("forged-role-cookie"), null);
  assert.equal(calls, 0);
  assert.equal((await sessions.sessionUser("a".repeat(64))).userId, "USR001");
  row = { ...row, role: "ADMIN" };
  assert.equal(await sessions.sessionUser("a".repeat(64)), null);
  row = null;
  assert.equal(await sessions.sessionUser("a".repeat(64)), null);
});

test("API authentication fails closed, distinguishes 401/403, and rejects cross-origin writes", async () => {
  let user = null;
  let offline = false;
  const auth = load("../src/lib/auth.ts", {
    "next/headers": { cookies: async () => ({ get: () => ({ value: "token" }) }) },
    "./auth-policy": policy, "./auth-session": { SESSION_COOKIE: "rsu_session", sessionUser: async () => { if (offline) throw Error("offline"); return user; } },
  });
  assert.equal((await auth.authorizeApi("review")).response.status, 401);
  user = { userId: "IT", role: "IT_SUPPORT" };
  assert.equal((await auth.authorizeApi("review")).response.status, 403);
  assert.equal((await auth.authorizeApi("errors")).response, null);
  const req = origin => new Request("http://localhost/api/chat", { method: "POST", headers: origin ? { origin } : {} });
  assert.equal((await auth.authorizeApi("errors", req("https://evil.test"))).response.status, 403);
  assert.equal((await auth.authorizeApi("errors", req(null))).response.status, 403);
  assert.equal((await auth.authorizeApi("errors", req("http://localhost"))).response, null);
  offline = true;
  assert.equal((await auth.authorizeApi("errors")).response.status, 503);
});

const routes = [
  ["applicants", "GET", "review"], ["applicants/review-queue", "GET", "processing"],
  ["applicants/final-decision-queue", "GET", "decisions"], ["ingestion/batch-status", "GET", "processing"],
  ["exceptions", "GET", "errors"], ["statistics", "GET", "statistics"],
  ["dossier", "GET", "review"], ["documents", "GET", "review"], ["chat", "POST", "review"],
  ["applicants/[id]/recommendation", "GET", "review"], ["applicants/[id]/recommendation", "PUT", "review"],
  ["applicants/[id]/final-decision", "PUT", "decisions"],
];
test("every existing data handler checks permission before touching applicant data or upstream services", async () => {
  const touched = () => { throw Error("Sensitive service accessed before authorization"); };
  for (const [path, method, permission] of routes) {
    for (const status of [401, 403, 503]) {
      let called = false;
      const response = NextResponse.json({ error: "denied" }, { status });
      const route = load(`../src/app/api/${path}/route.ts`, {
        "@/lib/auth": { authorizeApi: async (required, request) => {
          called = true; assert.equal(required, permission);
          if (method !== "GET") assert.equal(request.method, method);
          return { user: null, response };
        } },
        "@/lib/dossier": new Proxy({}, { get: () => touched }),
        "@/lib/statistics": {}, "@/lib/it-exceptions.mjs": {},
      });
      const actual = await route[method](new Request(`http://localhost/api/${path}`, { method }), { params: Promise.resolve({ id: "APP_TEST" }) });
      assert.equal(called, true); assert.equal(actual, response);
    }
  }
  const collect = folder => readdirSync(folder, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? collect(new URL(`${entry.name}/`, folder)) : entry.name === "route.ts" ? [new URL(entry.name, folder)] : []);
  const dataRoutes = collect(new URL("../src/app/api/", import.meta.url)).filter(url => !url.pathname.includes("/auth/"));
  assert.equal(dataRoutes.length, new Set(routes.map(([path]) => path)).size, "New APIs must be added to the permission coverage");
});

test("protected page routing preserves the destination and denies the wrong role", async () => {
  let user = null;
  const proxy = load("../src/proxy.ts", {
    "./lib/auth-policy": policy, "./lib/auth-session": { SESSION_COOKIE: "rsu_session", sessionUser: async () => user },
  }).proxy;
  const request = new NextRequest("http://localhost/applicant-review?appId=APP_012");
  const login = await proxy(request);
  assert.equal(new URL(login.headers.get("location")).searchParams.get("returnTo"), "/applicant-review?appId=APP_012");
  user = { role: "IT_SUPPORT" };
  assert.equal((await proxy(request)).headers.get("location"), "http://localhost/access-denied");
  user = { role: "DEAN" };
  assert.equal((await proxy(request)).headers.get("x-middleware-next"), "1");
});

test("review audit events identify the authenticated user instead of accepting a submitted actor", async () => {
  for (const [path, field] of [["recommendation", "recommendation"], ["final-decision", "final_decision"]]) {
    let audit;
    const client = { release() {}, query: async (sql, values) => {
      if (sql.includes("INSERT INTO audit_logs")) audit = values;
      return { rowCount: 1, rows: [{ appId: "APP_TEST" }] };
    } };
    const route = load(`../src/app/api/applicants/[id]/${path}/route.ts`, {
      "@/lib/auth": { authorizeApi: async () => ({ user: { userId: "REAL_ACTOR", role: "DEAN" }, response: null }) },
      "@/lib/dossier": { pool: { connect: async () => client } },
    });
    const response = await route.PUT(new Request("http://localhost/api/test", { method: "PUT", body: JSON.stringify({ [field]: "ACCEPT", actor: "spoofed" }) }), { params: Promise.resolve({ id: "APP_TEST" }) });
    assert.equal(response.status, 200);
    assert.equal(audit[3], "REAL_ACTOR");
    assert.equal(JSON.parse(audit[4]).authentication, "AUTHENTICATED_SESSION");
    assert.equal(JSON.parse(audit[4]).user_role, "DEAN");
  }
});
