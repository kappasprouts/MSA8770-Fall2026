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
const review = loadTypeScript("../src/lib/review-state.ts");
const { requestJson } = loadTypeScript("../src/lib/http.ts");

test("a new selection never accepts the previous dossier or a mismatched run", () => {
  const saved = { applicant_dossier: { app_id: "APP_A" }, run: { app_id: "APP_A" } };
  assert.equal(review.isDossierForApplicant(saved, "APP_A"), true);
  assert.equal(review.isDossierForApplicant(saved, "APP_B"), false);
  assert.equal(review.isDossierForApplicant(null, "APP_B"), false);
  assert.equal(review.isDossierForApplicant({ ...saved, run: { app_id: "APP_B" } }, "APP_A"), false);
});

test("an empty applicant list differs from an unreadable or failed response", () => {
  assert.deepEqual(review.parseApplicantSummaries({ applicants: [] }), []);
  for (const value of [null, {}, { error: "offline" }, { applicants: [null] }, { applicants: [{ id: 1 }] }]) {
    assert.throws(() => review.parseApplicantSummaries(value));
  }
});

test("validation is unknown without an explicit successful run and failed states take precedence", () => {
  assert.equal(review.latestRunCheckState({}), "unknown");
  assert.equal(review.latestRunCheckState({ run_status: "DOSSIER_READY" }), "unknown");
  assert.equal(review.latestRunCheckState({ run_status: "DOSSIER_READY", validation: { passed: true } }), "passed");
  assert.equal(review.latestRunCheckState({ run_status: "AGENT_ERROR", validation: { passed: true } }), "failed");
  assert.equal(review.latestRunCheckState({ run_status: "DOSSIER_READY", validation: { passed: false } }), "failed");
});

test("section counts use final attempts and do not count missing errors as passed", () => {
  assert.deepEqual(review.latestSectionChecks({ validation: { calls: [
    { section: "academic", attempt: 1, errors: ["wrong page"] },
    { section: "academic", attempt: 2, errors: [] },
    { section: "academic", attempt: 1, errors: ["late earlier attempt"] },
    { section: "policy", attempt: 1, errors: [] },
    { section: "engagement", attempt: 1 },
  ] } }), { passed: 2, total: 2 });
  assert.deepEqual(review.latestSectionChecks({}), { passed: 0, total: 0 });
});

test("saved dossier markup never claims Complete merely because a dossier exists", () => {
  // Render the actual component without introducing a browser-test dependency.
  const Snapshot = loadTypeScript("../src/components/dossier/SnapshotCard.tsx", { "@/lib/review-state": review }).default;
  const html = renderToStaticMarkup(React.createElement(Snapshot, { payload: {
    applicant_dossier: { app_id: "APP_A" }, run: { run_status: "AI_VALIDATION_FAILED", validation: { passed: false } },
  } }));
  assert.match(html, /Saved dossier validation/);
  assert.match(html, /Unknown/);
  assert.match(html, /Failed/);
  assert.doesNotMatch(html, /Complete/);
  assert.match(html, /no recorded link/);
});

test("unavailable decision counts stay unknown while true zero remains zero", () => {
  assert.equal(review.parseDecisionTotals(null), null);
  assert.equal(review.parseDecisionTotals({ awaiting: 1 }), null);
  assert.equal(review.parseDecisionTotals({ awaiting: 1, recorded: -1, total: 5 }), null);
  assert.equal(review.parseDecisionTotals({ awaiting: 4, recorded: 4, total: 5 }), null);
  assert.deepEqual(review.parseDecisionTotals({ awaiting: 0, recorded: 0, total: 0 }), { awaiting: 0, recorded: 0, total: 0 });
});

test("batch states distinguish no recorded run, completion, other statuses, and bad data", () => {
  assert.deepEqual(review.parseBatchStatus({ status: "NO_PREVIOUS_RUN" }), { kind: "none" });
  assert.deepEqual(review.parseBatchStatus({ status: "COMPLETED", executed_at: "2026-10-21T12:00:00Z", affected_ids: [] }),
    { kind: "completed", executedAt: "2026-10-21T12:00:00Z", affected: 0 });
  assert.equal(review.parseBatchStatus({ status: "RUNNING" }).kind, "other");
  for (const value of [null, {}, { status: "COMPLETED", executed_at: "invalid" }]) assert.throws(() => review.parseBatchStatus(value));
});

test("JSON requests preserve service errors and reject unreadable responses", async t => {
  t.mock.method(globalThis, "fetch", async () => Response.json({ error: "Applicant records are unavailable." }, { status: 503 }));
  await assert.rejects(requestJson("/api/applicants"), /Applicant records are unavailable/);
  globalThis.fetch = async () => new Response("<html>upstream failed</html>", { status: 502 });
  await assert.rejects(requestJson("/api/applicants"), /request failed \(502\)/);
  globalThis.fetch = async () => new Response("not JSON");
  await assert.rejects(requestJson("/api/applicants"), /unexpected response/);
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await requestJson("/api/decision"), null);
});

test("cancelling a superseded request aborts the underlying fetch", async t => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", (_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
  const pending = requestJson("/api/dossier?appId=APP_A", { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
});

test("decision SQL counts recorded decisions outside the pending queue", { skip: !process.env.POSTGRES_DB }, async () => {
  const { Client } = createRequire(import.meta.url)("pg");
  const client = new Client({
    host: process.env.POSTGRES_HOST, port: Number(process.env.POSTGRES_PORT), database: process.env.POSTGRES_DB,
    user: process.env.POSTGRES_USER, password: process.env.POSTGRES_PASSWORD,
  });
  const route = readFileSync(new URL("../src/app/api/applicants/final-decision-queue/route.ts", import.meta.url), "utf8");
  const sql = route.match(/pool\.query\(`([\s\S]*?)`\)/)?.[1];
  assert.ok(sql, "Read the actual route's aggregation query");
  await client.connect();
  try {
    await client.query("BEGIN");
    // A session-local table shadows public.applicants; no applicant records are changed.
    await client.query(`CREATE TEMP TABLE applicants (
      app_id text, first_name text, last_name text, intended_major text,
      status text, final_decision text, updated_at timestamptz
    ) ON COMMIT DROP`);
    await client.query(`INSERT INTO applicants (app_id, status, final_decision) VALUES
      ('PENDING', 'DOSSIER_READY', NULL), ('RECORDED', 'READY_FOR_REVIEW', 'ACCEPT'),
      ('WAITING', 'AWAITING_MATERIALS', NULL), ('DECLINED', 'DOSSIER_READY', 'DECLINE')`);
    const { rows } = await client.query(sql);
    assert.deepEqual(rows[0].totals, { awaiting: 1, recorded: 2, total: 4 });
    assert.deepEqual(rows[0].applicants.map(row => row.appId), ["PENDING"]);
    await client.query("DELETE FROM applicants");
    assert.deepEqual((await client.query(sql)).rows[0], { applicants: [], totals: { awaiting: 0, recorded: 0, total: 0 } });
  } finally {
    await client.query("ROLLBACK");
    await client.end();
  }
});
