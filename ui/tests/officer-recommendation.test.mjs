import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
function loadTypeScript(path, aliases = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: {
    jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const loaded = { exports: {} };
  new Function("require", "module", "exports", compiled)(
    name => Object.hasOwn(aliases, name) ? aliases[name] : require(name), loaded, loaded.exports,
  );
  return loaded.exports;
}
const recommendations = loadTypeScript("../src/lib/recommendation.ts");
const review = loadTypeScript("../src/lib/review-state.ts");
const http = loadTypeScript("../src/lib/http.ts");
const api = loadTypeScript("../src/lib/eaos-api.ts", { "./http": http, "./review-state": review, "./recommendation": recommendations });
const routePath = "../src/app/api/applicants/[id]/recommendation/route.ts";
const context = id => ({ params: Promise.resolve({ id }) });
const request = body => new Request("http://localhost/api/applicants/APP_A/recommendation", { method: "PUT", body: JSON.stringify(body) });
function loadRoute(pool, path = routePath) {
  return loadTypeScript(path, { "@/lib/dossier": { pool }, "@/lib/recommendation": recommendations, "next/server": { NextResponse: Response } });
}

test("invalid recommendations, malformed JSON, and non-text/oversized notes never reach storage", async () => {
  const route = loadRoute({ connect() { assert.fail("Invalid requests must not acquire a database connection"); } });
  for (const body of [null, [], {}, { recommendation: "DECLINE", notes: "" }, { recommendation: "accept", notes: "" },
    { recommendation: "ACCEPT" }, { recommendation: "ACCEPT", notes: null }, { recommendation: "ACCEPT", notes: 12 },
    { recommendation: "WAITLIST", notes: "x".repeat(10_001) }]) {
    assert.equal((await route.PUT(request(body), context("APP_A"))).status, 400);
  }
  assert.equal((await route.PUT(new Request("http://localhost", { method: "PUT", body: "{" }), context("APP_A"))).status, 400);
});

test("API adapter carries recommendation and multiline notes without confusing them with final decisions", async t => {
  const row = api.normalizeApplicant({ app_id: "APP_A", officer_recommendation: "REJECT", officer_recommendation_notes: "First line\nSecond line", final_decision: null });
  assert.equal(row.officerRecommendation, "REJECT");
  assert.equal(row.officerRecommendationNotes, "First line\nSecond line");
  assert.equal(row.finalDecision, null);
  assert.equal(api.normalizeApplicant({ appId: "APP_B" }).officerRecommendation, null);
  const saved = { appId: "APP / A", recommendation: "WAITLIST", notes: "First line\nSecond line", updatedAt: "2026-10-30T12:00:00Z", canEdit: true };
  t.mock.method(globalThis, "fetch", async (url, init) => {
    assert.match(url, /APP%20%2F%20A\/recommendation$/);
    if (init.method === "PUT") assert.deepEqual(JSON.parse(init.body), { recommendation: "WAITLIST", notes: saved.notes });
    return Response.json(saved);
  });
  assert.deepEqual(await api.saveOfficerReview(saved.appId, "WAITLIST", saved.notes), saved);
  assert.deepEqual(await api.getOfficerReview(saved.appId), saved);
});

test("database connection failures return a readable save error", async t => {
  t.mock.method(console, "error", () => {});
  const route = loadRoute({ async connect() { throw new Error("offline"); } });
  const response = await route.PUT(request({ recommendation: "ACCEPT", notes: "" }), context("APP_A"));
  assert.equal(response.status, 500);
  assert.match((await response.json()).error, /Could not save/);
});

test("details panel shows recommendation and safely escaped multiline notes before the final decision controls", () => {
  const row = api.normalizeApplicant({ appId: "APP_A", firstName: "Example", officerRecommendation: "REJECT", officerRecommendationNotes: "Line one\n<script>example</script>" });
  const states = [[row], { awaiting: 1, recorded: 0, total: 1 }, false, "", "", "", "APP_A", "", "", false, false, 0];
  const Page = loadTypeScript("../src/app/final-decisions/page.tsx", {
    react: { ...React, useState: () => [states.shift(), () => {}], useEffect: () => {}, useMemo: callback => callback() },
    "next/link": { default: ({ children }) => React.createElement("a", {}, children) },
    "@/components/EaosShell": { default: ({ children }) => React.createElement("main", {}, children) },
    "@/components/RequestState": { default: () => null },
    "@/components/StatusBadge": { default: ({ status }) => React.createElement("span", {}, review.decisionLabel(status)) },
    "@/components/eaos.module.css": { default: {} }, "@/lib/eaos-api": api, "@/lib/review-state": review, "@/lib/recommendation": recommendations,
  }).default;
  const html = renderToStaticMarkup(React.createElement(Page));
  assert.match(html, /Officer recommendation<\/th><th scope="col">Final decision/);
  assert.match(html, /Officer recommendation<\/span><strong>Reject/);
  assert.match(html, /Line one\n&lt;script&gt;example&lt;\/script&gt;/);
  assert.ok(html.indexOf("Officer comments / notes") < html.indexOf("Dean&#x27;s approved final decision"));
});

test("real PostgreSQL migration, saves, queue propagation, finalization, and audit rollback", { skip: !process.env.POSTGRES_DB }, async t => {
  const { Client } = require("pg");
  const client = new Client({ host: process.env.POSTGRES_HOST, port: Number(process.env.POSTGRES_PORT),
    database: process.env.POSTGRES_DB, user: process.env.POSTGRES_USER, password: process.env.POSTGRES_PASSWORD });
  await client.connect();
  try {
    // Session-local tables shadow the real data, including all writes and audit events.
    await client.query(`CREATE TEMP TABLE applicants (
      app_id text PRIMARY KEY, first_name text, last_name text, intended_major text,
      status text, final_decision text, updated_at timestamptz
    )`);
    await client.query(`CREATE TEMP TABLE audit_logs (
      id text PRIMARY KEY, applicant_id text, action text, actor text, details jsonb, created_at timestamptz
    )`);
    await client.query(`CREATE TEMP TABLE dossier_review_requests (
      id uuid, app_id text, candidate_hash text, state text, input_snapshot jsonb,
      requested_at timestamptz, requires_evidence_review boolean, exception_reasons jsonb,
      expires_at timestamptz, outcome_reason text, reviewer text, reason text
    )`);
    const migration = readFileSync(new URL("../../storage/migrations/20261030_officer_recommendation.sql", import.meta.url), "utf8");
    await client.query(migration);
    await client.query(migration);
    const lifecycleMigration = readFileSync(new URL("../../storage/migrations/20261031_review_lifecycle_statuses.sql", import.meta.url), "utf8");
    await client.query(`INSERT INTO applicants (app_id, status, officer_recommendation, final_decision, updated_at) VALUES
      ('LEGACY_R', 'DOSSIER_READY', 'WAITLIST', NULL, '2026-10-30T12:00:00Z'),
      ('LEGACY_F', 'DOSSIER_READY', 'REJECT', 'ACCEPT', '2026-10-30T12:00:00Z'),
      ('LEGACY_D', 'READY_FOR_REVIEW', NULL, 'WAITLIST', '2026-10-30T12:00:00Z'),
      ('UNREVIEWED', 'DOSSIER_READY', NULL, NULL, '2026-10-30T12:00:00Z')`);
    await client.query(lifecycleMigration);
    await client.query(lifecycleMigration);
    const backfilled = (await client.query('SELECT * FROM applicants ORDER BY app_id')).rows;
    assert.deepEqual(backfilled.map(row => row.status), ['FINAL_DECISION_RECORDED', 'FINAL_DECISION_RECORDED', 'REVIEWED', 'DOSSIER_READY']);
    assert.equal(backfilled[1].officer_recommendation, 'REJECT');
    assert.equal(backfilled[1].final_decision, 'ACCEPT');
    for (const row of backfilled) assert.equal(row.updated_at.toISOString(), '2026-10-30T12:00:00.000Z');
    await client.query('DELETE FROM applicants');
    await client.query(`INSERT INTO applicants (app_id, status) VALUES ('APP_A', 'DOSSIER_READY'), ('APP_B', 'READY_FOR_REVIEW')`);
    const pool = { query: (...args) => client.query(...args), connect: async () => ({ query: (...args) => client.query(...args), release() {} }) };
    const route = loadRoute(pool);
    const initial = await (await route.GET(null, context("APP_A"))).json();
    assert.deepEqual(initial, { appId: "APP_A", recommendation: null, notes: "", updatedAt: null, canEdit: true, applicationStatus: "DOSSIER_READY" });
    assert.equal((await route.GET(null, context("MISSING"))).status, 404);
    assert.equal((await route.PUT(request({ recommendation: "ACCEPT", notes: "" }), context("APP_B"))).status, 409);
    assert.equal((await route.PUT(request({ recommendation: "ACCEPT", notes: "" }), context("MISSING"))).status, 409);

    for (const recommendation of recommendations.RECOMMENDATIONS) {
      const response = await route.PUT(request({ recommendation, notes: "Reasoning\nWith a second line & <text>" }), context("APP_A"));
      assert.equal(response.status, 200);
      const saved = await response.json();
      assert.equal(saved.recommendation, recommendation);
      assert.ok(saved.updatedAt);
      assert.equal(saved.applicationStatus, "REVIEWED");
      assert.equal(saved.canEdit, true);
      assert.equal((await client.query("SELECT status FROM applicants WHERE app_id='APP_A'")).rows[0].status, "REVIEWED");
    }
    // Empty notes are optional and can replace previously saved notes.
    assert.equal((await route.PUT(request({ recommendation: "WAITLIST", notes: "" }), context("APP_A"))).status, 200);
    const saved = { recommendation: "REJECT", notes: "Reasoning\nWith a second line & <text>" };
    await route.PUT(request(saved), context("APP_A"));
    const reloaded = await (await route.GET(null, context("APP_A"))).json();
    assert.equal(reloaded.notes, saved.notes);
    const queue = loadRoute(pool, "../src/app/api/applicants/final-decision-queue/route.ts");
    const data = await (await queue.GET()).json();
    assert.equal(data.applicants[0].officerRecommendation, "REJECT");
    assert.equal(data.applicants[0].officerRecommendationNotes, saved.notes);
    assert.equal(data.applicants[0].finalDecision, null);
    assert.equal(data.applicants[0].applicationStatus, "REVIEWED");
    assert.deepEqual(data.totals, { awaiting: 1, recorded: 0, total: 2 });
    assert.equal((await client.query("SELECT COUNT(*)::int AS count FROM audit_logs")).rows[0].count, 5);

    // An audit failure rolls the entire save back, preserving the previous review.
    await client.query("ALTER TABLE audit_logs ADD CONSTRAINT fail_audit CHECK (action <> 'OFFICER_RECOMMENDATION_SAVED') NOT VALID");
    t.mock.method(console, "error", () => {});
    await client.query("INSERT INTO applicants (app_id, status) VALUES ('APP_C', 'DOSSIER_READY')");
    assert.equal((await route.PUT(request({ recommendation: "ACCEPT", notes: "First save should roll back" }), context("APP_C"))).status, 500);
    assert.deepEqual((await client.query("SELECT status, officer_recommendation FROM applicants WHERE app_id='APP_C'")).rows[0], { status: "DOSSIER_READY", officer_recommendation: null });
    await client.query("DELETE FROM applicants WHERE app_id='APP_C'");
    assert.equal((await route.PUT(request({ recommendation: "ACCEPT", notes: "Should roll back" }), context("APP_A"))).status, 500);
    assert.deepEqual(await (await route.GET(null, context("APP_A"))).json(), reloaded);
    await client.query("ALTER TABLE audit_logs DROP CONSTRAINT fail_audit");

    const finalRoute = loadRoute(pool, "../src/app/api/applicants/[id]/final-decision/route.ts");
    await client.query("ALTER TABLE audit_logs ADD CONSTRAINT fail_final_audit CHECK (action <> 'FINAL_DECISION_RECORDED') NOT VALID");
    assert.equal((await finalRoute.PUT(request({ final_decision: "ACCEPT" }), context("APP_A"))).status, 500);
    assert.deepEqual((await client.query("SELECT status, final_decision FROM applicants WHERE app_id='APP_A'")).rows[0], { status: "REVIEWED", final_decision: null });
    await client.query("ALTER TABLE audit_logs DROP CONSTRAINT fail_final_audit");
    const finalizedResponse = await finalRoute.PUT(request({ final_decision: "WAITLIST" }), context("APP_A"));
    assert.equal(finalizedResponse.status, 200);
    assert.equal((await finalizedResponse.json()).applicationStatus, "FINAL_DECISION_RECORDED");
    assert.deepEqual((await client.query("SELECT status, final_decision FROM applicants WHERE app_id='APP_A'")).rows[0], { status: "FINAL_DECISION_RECORDED", final_decision: "WAITLIST" });
    assert.equal((await finalRoute.PUT(request({ final_decision: "ACCEPT" }), context("APP_A"))).status, 409);
    assert.equal((await route.PUT(request({ recommendation: "ACCEPT", notes: "Too late" }), context("APP_A"))).status, 409);
    const finalized = await (await route.GET(null, context("APP_A"))).json();
    assert.equal(finalized.canEdit, false);
    assert.equal(finalized.applicationStatus, "FINAL_DECISION_RECORDED");
    assert.equal(finalized.recommendation, "REJECT");
    assert.equal(finalized.notes, saved.notes);
    const after = await (await queue.GET()).json();
    assert.equal(after.applicants.length, 0);
    assert.equal(after.totals.recorded, 1);
  } finally {
    await client.end();
  }
});
