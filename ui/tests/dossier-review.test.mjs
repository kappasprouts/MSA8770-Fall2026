import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createHash, randomUUID } from "node:crypto";
import { Readable } from "node:stream";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
const require = createRequire(import.meta.url);
function load(path, aliases = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const result = { exports: {} };
  new Function("require", "module", "exports", code)(name => Object.hasOwn(aliases, name) ? aliases[name] : require(name), result, result.exports);
  return result.exports;
}
const guards = load("../src/lib/dossier-review.ts");
const id = randomUUID();
const context = value => ({ params: Promise.resolve({ id: value }) });
const body = { candidateHash: "a".repeat(64), action: guards.REVIEW_ACTION, decision: "APPROVE", reviewer: "Officer demo", reason: "Sources checked", confirmed: true, evidenceReviewed: true };
const request = value => new Request("http://localhost/api/dossier-reviews", { method: "PUT", body: JSON.stringify(value) });
function decisionRoute(pool) { return load("../src/app/api/dossier-reviews/[id]/route.ts", { "next/server": { NextResponse: Response }, "@/lib/dossier": { pool }, "@/lib/dossier-review": guards }); }

test("published dossiers load their linked run rather than a newer unrelated run", async () => {
  const previous = globalThis.__pgPool;
  let calls = 0;
  globalThis.__pgPool = { query: async (sql, args) => {
    calls++;
    if (calls === 1) return { rowCount: 1, rows: [{ app_id: "APP_050", publication_request_id: id, publication_run_id: 7, publication_hash: body.candidateHash, publication_reviewer: "Officer" }] };
    assert.match(sql, /id=\$2/); assert.deepEqual(args, ["APP_050", 7]);
    return { rows: [{ id: 7, run_status: "DOSSIER_READY", validation: { passed: true } }] };
  } };
  try {
    const helpers = load("../src/lib/dossier.ts", { pg: { Pool: class {} }, minio: { Client: class {} } });
    const result = await helpers.loadDossier("APP_050");
    assert.equal(result.run.id, 7);
    assert.equal(result.publication.request_id, id);
  } finally { globalThis.__pgPool = previous; }
});

test("published structured review notes render without React object-child errors", () => {
  const aliases = { "./eaos.module.css": { default: {} } };
  for (const name of ["ApplicantInfoCard", "SnapshotCard", "PolicyChecksCard", "EvidenceLinks"]) aliases[`./dossier/${name}`] = { default: () => null };
  const Panel = load("../src/components/DossierPanel.tsx", aliases).default;
  const html = renderToStaticMarkup(React.createElement(Panel, { payload: { applicant_dossier: { review_notes: [{ section: "academic", category: "other", note: "Source conflict retained" }] } }, onViewEvidence() {} }));
  assert.match(html, /academic \/ other \/ Source conflict retained/);
});

test("missing decisions, confirmation, scope and reviewer never reach storage", async () => {
  const route = decisionRoute({ query() { assert.fail("Invalid decision reached storage"); } });
  for (const value of [null, {}, { ...body, decision: undefined }, { ...body, confirmed: false }, { ...body, candidateHash: "wrong" },
    { ...body, action: "ADMIT" }, { ...body, reviewer: " " }, { ...body, evidenceReviewed: undefined }]) {
    assert.equal((await route.PUT(request(value), context(id))).status, 400);
  }
});

test("automatic dossier provenance does not invent a human approval", () => {
  const Snapshot = load("../src/components/dossier/SnapshotCard.tsx", { "@/lib/review-state": load("../src/lib/review-state.ts") }).default;
  const html = renderToStaticMarkup(React.createElement(Snapshot, { payload: {
    publication: { request_id: id, generation_run_id: 1, mode: "AUTOMATIC", reviewer: null },
    run: { id: 1, run_status: "DOSSIER_READY", validation: { passed: true } }, applicant_dossier: {},
  } }));
  assert.match(html, /No human approval was recorded/);
  assert.doesNotMatch(html, /approval by null/);
});

test("source viewer uses saved bucket/key and checks bytes against the saved version", async () => {
  const bytes = Buffer.from("%PDF-1.4 synthetic source");
  let digest = createHash("sha256").update(bytes).digest("hex");
  const route = load("../src/app/api/dossier-reviews/[id]/documents/route.ts", {
    "next/server": { NextResponse: Response }, "@/lib/dossier-review": guards,
    "@/lib/dossier": { MINIO_BUCKET: "default", pool: { query: async () => ({ rows: [{ documents: [{ filename: "transcript.pdf", key: "old/source.pdf", bucket: "archive", sha256: digest }] }] }) },
      minioClient: { getObject: async (bucket, key) => { assert.equal(bucket, "archive"); assert.equal(key, "old/source.pdf"); return Readable.from([bytes]); } } },
  });
  const req = new Request("http://localhost/api/source?file=transcript.pdf");
  assert.equal((await route.GET(req, context(id))).status, 200);
  digest = "0".repeat(64);
  assert.equal((await route.GET(req, context(id))).status, 409);
});

test("actual decision route publishes through the PostgreSQL transaction and recovers replay", { skip: !process.env.POSTGRES_DB }, async () => {
  const { Client } = require("pg");
  const client = new Client({ host: process.env.POSTGRES_HOST, port: Number(process.env.POSTGRES_PORT), database: process.env.POSTGRES_DB, user: process.env.POSTGRES_USER, password: process.env.POSTGRES_PASSWORD });
  await client.connect();
  const schema = "checkpoint_ui_test_" + randomUUID().replaceAll("-", "");
  try {
    await client.query(`CREATE SCHEMA ${schema}`);
    await client.query(`SET search_path=${schema},public`);
    await client.query("CREATE TABLE applicants(app_id varchar(64) PRIMARY KEY,status text,officer_recommendation text,final_decision text,documents jsonb DEFAULT '[]')");
    await client.query("INSERT INTO applicants(app_id,status) VALUES ('APP_050','READY_FOR_REVIEW')");
    await client.query("CREATE TABLE policy_chunks(policy_id text,content text)");
    await client.query("CREATE TABLE dossier_generation_runs(id bigserial PRIMARY KEY,app_id text,run_status text,validation jsonb)");
    await client.query("CREATE TABLE summary_audit_log(app_id text,event text,details jsonb)");
    await client.query(`CREATE TABLE applicant_dossier(app_id varchar(64) PRIMARY KEY,applicant_demographics jsonb,academic_profile jsonb,engagement_profile jsonb,recommendation_profile jsonb,supplemental_essay_profile jsonb,strengths jsonb,review_notes jsonb,policy_assessment jsonb,holistic_assessment text,evidence_map jsonb,generated_at timestamptz,updated_at timestamptz)`);
    await client.query(readFileSync(new URL("../../storage/migrations/20261031_durable_dossier_review.sql", import.meta.url), "utf8"));
    const candidate = { app_id: "APP_050", applicant_demographics: {}, academic_profile: {}, engagement_profile: {}, recommendation_profile: {}, supplemental_essay_profile: {}, strengths: [], review_notes: [], policy_assessment: [], holistic_assessment: "Factual summary", evidence_map: [] };
    await client.query("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES ('APP_050','REVIEW_PENDING','{\"passed\":true}')");
    const review = (await client.query("SELECT stage_dossier_review('APP_050',1,$1,checkpoint_input_snapshot('APP_050'),'v1',clock_timestamp()+interval '1 day') AS result", [candidate])).rows[0].result;
    const route = decisionRoute({ query: (...args) => client.query(...args) });
    const decision = { ...body, candidateHash: review.candidate_hash };
    assert.equal((await route.GET(new Request("http://localhost"), context(review.id))).status, 200);
    assert.equal((await route.PUT(request(decision), context(review.id))).status, 200);
    const replay = await (await route.PUT(request(decision), context(review.id))).json();
    assert.equal(replay.replayed, true);
    assert.equal((await client.query("SELECT count(*)::int AS n FROM dossier_publication_receipts")).rows[0].n, 1);
    assert.equal((await client.query("SELECT count(*)::int AS n FROM applicant_dossier")).rows[0].n, 1);
  } finally {
    await client.query("ROLLBACK");
    await client.query("SET search_path=public");
    assert.match(schema, /^checkpoint_ui_test_[a-f0-9]+$/);
    await client.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`);
    await client.end();
  }
});

test("recommendation uses the separate exception draft and stale displayed versions cannot submit", () => {
  const row = { appId: "APP_050", canEdit: true, applicationStatus: "REVIEW_PENDING", recommendation: null, notes: "",
    version: { requestId: id, candidateHash: body.candidateHash, state: "REVIEW_PENDING", requiresEvidenceReview: true,
      reasons: ["Source scores conflict"], expiresAt: "2026-11-05T12:00:00Z" } };
  let states = [row, "", "", false, "", "", false, false, 0];
  const Panel = load("../src/components/OfficerRecommendationPanel.tsx", {
    react: { ...React, useState: () => [states.shift(), () => {}], useEffect: () => {} },
    "@/components/RequestState": { default: () => null }, "@/lib/eaos-api": {}, "@/lib/http": {},
    "@/lib/recommendation": load("../src/lib/recommendation.ts"), "./eaos.module.css": { default: {} },
  }).default;
  const html = renderToStaticMarkup(React.createElement(Panel, { appId: "APP_050" }));
  assert.match(html, /Open Exceptions/);
  assert.doesNotMatch(html, /Source scores conflict|Needs correction|Reviewer name|Exception resolution \/ correction needed/);
  assert.match(html, /type="submit" disabled=""/);
  states = [row, "ACCEPT", "Reason", false, "", "", false, false, 0];
  const resolution = { reviewer: "Officer", reason: "Resolved", confirmed: true, evidenceReviewed: true };
  const stale = renderToStaticMarkup(React.createElement(Panel, { appId: "APP_050", exceptionResolution: resolution, dossierVersion: { requestId: randomUUID(), candidateHash: body.candidateHash } }));
  assert.match(stale, /The dossier changed after this page loaded/);
  assert.match(stale, /type="submit" disabled=""/);
  states = [row, "ACCEPT", "Reason", false, "", "", false, false, 0];
  const ready = renderToStaticMarkup(React.createElement(Panel, { appId: "APP_050", exceptionResolution: resolution, dossierVersion: { requestId: id, candidateHash: body.candidateHash } }));
  assert.match(ready, /Save resolution and recommendation/);
  assert.doesNotMatch(ready, /type="submit" disabled=""/);
});

test("exceptions panel owns reasons, source inspection and scoped resolution controls", () => {
  const Panel = load("../src/components/ApplicantExceptionsPanel.tsx", {
    "@/lib/recommendation": load("../src/lib/recommendation.ts"), "@/lib/http": {},
    "./eaos.module.css": { default: {} }, "./exceptions.module.css": { default: {} },
  }).default;
  const props = { appId: "APP_050", checkpoint: { request_id: id, candidate_hash: body.candidateHash, state: "REVIEW_PENDING",
    reasons: ["Source scores conflict"], expires_at: "2026-11-05T12:00:00Z", requires_evidence_review: true },
    dossier: { review_notes: [{ section: "academic", note: "SAT sources disagree" }] },
    resolution: { reviewer: "", reason: "", confirmed: false, evidenceReviewed: false }, canEdit: true, busy: false,
    onChange() {}, onBusyChange() {}, onOpenDocuments() {}, onContinue() {},
  };
  const html = renderToStaticMarkup(React.createElement(Panel, props));
  for (const text of ["Source scores conflict", "SAT sources disagree", "Inspect original documents", "Reviewer name", "verified the flagged evidence", "Both are saved together", "Needs correction", "does not reject the applicant"]) assert.ok(html.includes(text));
  assert.match(html, /disabled="">Continue to recommendation/);
  const closed = renderToStaticMarkup(React.createElement(Panel, { ...props, checkpoint: { ...props.checkpoint, state: "ESCALATED", outcome_reason: "Deadline expired; regenerate" } }));
  assert.match(closed, /Deadline expired; regenerate/);
  assert.doesNotMatch(closed, /<input|<textarea/);
});

test("recommendation submits the exception-tab draft atomically and refuses an incomplete draft", async () => {
  const row = { appId: "APP_050", canEdit: true, applicationStatus: "REVIEW_PENDING", recommendation: null, notes: "",
    version: { requestId: id, candidateHash: body.candidateHash, state: "REVIEW_PENDING", requiresEvidenceReview: true } };
  let states, captured, saved = 0;
  const Panel = load("../src/components/OfficerRecommendationPanel.tsx", {
    react: { ...React, useState: () => [states.shift(), () => {}], useEffect() {}, useRef: value => ({ current: value }) },
    "@/components/RequestState": { default: () => null },
    "@/lib/eaos-api": { async saveOfficerReview(...args) { captured = args; return { ...row, recommendation: "WAITLIST" }; } },
    "@/lib/recommendation": load("../src/lib/recommendation.ts"), "./eaos.module.css": { default: {} },
  }).default;
  function findForm(node) {
    if (Array.isArray(node)) return node.map(findForm).find(Boolean);
    if (!React.isValidElement(node)) return null;
    return node.type === "form" ? node : findForm(node.props.children);
  }
  async function submit(resolution) {
    states = [row, "WAITLIST", "Human recommendation reasoning", false, "", "", false, false, 0];
    const tree = Panel({ appId: "APP_050", dossierVersion: { requestId: id, candidateHash: body.candidateHash },
      exceptionResolution: resolution, onSaved() { saved++; } });
    await findForm(tree).props.onSubmit({ preventDefault() {} });
  }
  await submit({ reviewer: "Officer", reason: "Compared sources", confirmed: false, evidenceReviewed: true });
  assert.equal(captured, undefined);
  const resolution = { reviewer: "Officer", reason: "Compared sources", confirmed: true, evidenceReviewed: true };
  await submit(resolution);
  assert.equal(captured[0], "APP_050"); assert.equal(captured[1], "WAITLIST");
  assert.equal(captured[2], "Human recommendation reasoning");
  assert.deepEqual(captured[4], row.version); assert.deepEqual(captured[5], resolution);
  assert.equal(saved, 1);
});

test("actual integrated review atomically resolves exceptions and recommends, with version checks and replay", { skip: !process.env.POSTGRES_DB }, async t => {
  const { Client } = require("pg");
  const client = new Client({ host: process.env.POSTGRES_HOST, port: Number(process.env.POSTGRES_PORT), database: process.env.POSTGRES_DB, user: process.env.POSTGRES_USER, password: process.env.POSTGRES_PASSWORD });
  await client.connect();
  const schema = "checkpoint_ui_test_" + randomUUID().replaceAll("-", "");
  const previous = globalThis.__pgPool;
  try {
    await client.query(`CREATE SCHEMA ${schema}`);
    await client.query(`SET search_path=${schema},public`);
    await client.query(`CREATE TABLE applicants(app_id varchar(64) PRIMARY KEY,status text,officer_recommendation text,
      officer_recommendation_notes text,officer_recommendation_updated_at timestamptz,final_decision text,updated_at timestamptz,
      documents jsonb DEFAULT '[]',superscored_sat_score integer)`);
    await client.query("INSERT INTO applicants(app_id,status,documents) VALUES ('APP_050','READY_FOR_REVIEW',$1)", [JSON.stringify([{ filename: "transcript.pdf", minio_bucket: "archive", minio_key: "saved.pdf", sha256: "a".repeat(64), exists: true }])]);
    await client.query("CREATE TABLE policy_chunks(policy_id text,content text)");
    await client.query(`CREATE TABLE dossier_generation_runs(id bigserial PRIMARY KEY,app_id text,run_status text,validation jsonb,
      documents_sent jsonb,documents_withheld jsonb,created_at timestamptz,attempts integer,runtime_seconds numeric,policies_retrieved jsonb)`);
    await client.query("CREATE TABLE summary_audit_log(app_id text,event text,details jsonb)");
    await client.query("CREATE TABLE audit_logs(id uuid PRIMARY KEY,applicant_id text,action text,actor text,details jsonb,created_at timestamptz)");
    await client.query(`CREATE TABLE applicant_dossier(app_id varchar(64) PRIMARY KEY,applicant_demographics jsonb,academic_profile jsonb,engagement_profile jsonb,recommendation_profile jsonb,supplemental_essay_profile jsonb,strengths jsonb,review_notes jsonb,policy_assessment jsonb,holistic_assessment text,evidence_map jsonb,generated_at timestamptz,updated_at timestamptz)`);
    for (const migration of ["20261031_durable_dossier_review.sql", "20261101_integrated_exception_review.sql", "20261101_integrated_exception_review.sql"]) await client.query(readFileSync(new URL(`../../storage/migrations/${migration}`, import.meta.url), "utf8"));
    const candidate = { app_id: "APP_050", applicant_demographics: {}, academic_profile: {}, engagement_profile: {}, recommendation_profile: {}, supplemental_essay_profile: {}, strengths: [], review_notes: [{ note: "Score sources conflict" }], policy_assessment: [], holistic_assessment: "Factual summary", evidence_map: [] };
    await client.query("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES ('APP_050','REVIEW_PENDING','{\"passed\":true,\"requires_human_verification\":true}')");
    const review = (await client.query("SELECT route_dossier_candidate('APP_050',1,$1,checkpoint_input_snapshot('APP_050'),'v1',clock_timestamp()+interval '1 day') AS result", [candidate])).rows[0].result;
    const pool = { query: (...args) => client.query(...args), connect: async () => ({ query: (...args) => client.query(...args), release() {} }) };
    const rec = load("../src/app/api/applicants/[id]/recommendation/route.ts", { "next/server": { NextResponse: Response }, "@/lib/dossier": { pool }, "@/lib/recommendation": load("../src/lib/recommendation.ts") });
    const initial = await (await rec.GET(null, context("APP_050"))).json();
    assert.equal(initial.version.state, "REVIEW_PENDING"); assert.equal(initial.canEdit, true);
    // The actual human endpoint can load the draft; published-only consumers cannot.
    globalThis.__pgPool = pool;
    const helpers = load("../src/lib/dossier.ts", { pg: { Pool: class {} }, minio: { Client: class {} } });
    assert.equal(await helpers.loadDossier("APP_050"), null);
    const draft = await helpers.loadDossier("APP_050", true);
    assert.equal(draft.review_checkpoint.request_id, review.id);
    assert.equal(draft.review_checkpoint.requires_evidence_review, true);
    assert.equal(draft.applicant_dossier.holistic_assessment, candidate.holistic_assessment);
    assert.match((await helpers.listOriginalDocuments("APP_050", draft))[0].sourceUrl, new RegExp(`/dossier-reviews/${review.id}/documents`));
    const input = { recommendation: "WAITLIST", notes: "Human admissions reasoning", version: initial.version,
      resolution: { reviewer: "Officer demo", reason: "Compared original sources; recorded authoritative score and uncertainty", confirmed: true, evidenceReviewed: true } };
    assert.equal((await rec.PUT(request({ ...input, resolution: undefined }), context("APP_050"))).status, 409);
    assert.equal((await rec.PUT(request({ ...input, version: { ...input.version, candidateHash: "0".repeat(64) } }), context("APP_050"))).status, 409);
    assert.equal((await rec.PUT(request({ ...input, resolution: { ...input.resolution, confirmed: false } }), context("APP_050"))).status, 400);
    assert.equal((await rec.PUT(request({ ...input, resolution: { ...input.resolution, evidenceReviewed: false } }), context("APP_050"))).status, 400);
    await client.query("ALTER TABLE audit_logs ADD CONSTRAINT fail_combined_save CHECK(false) NOT VALID");
    t.mock.method(console, "error", () => {});
    assert.equal((await rec.PUT(request(input), context("APP_050"))).status, 500);
    assert.equal((await client.query("SELECT state FROM dossier_review_requests")).rows[0].state, "REVIEW_PENDING");
    assert.equal((await client.query("SELECT count(*)::int AS n FROM dossier_publication_receipts")).rows[0].n, 0);
    assert.equal((await client.query("SELECT officer_recommendation FROM applicants")).rows[0].officer_recommendation, null);
    await client.query("ALTER TABLE audit_logs DROP CONSTRAINT fail_combined_save");
    assert.equal((await rec.PUT(request(input), context("APP_050"))).status, 200);
    // Simulate a lost response: replay the same explicit resolution and recommendation.
    assert.equal((await rec.PUT(request(input), context("APP_050"))).status, 200);
    assert.equal((await client.query("SELECT count(*)::int AS n FROM dossier_publication_receipts")).rows[0].n, 1);
    assert.deepEqual((await client.query("SELECT status,officer_recommendation,final_decision FROM applicants")).rows[0], { status: "REVIEWED", officer_recommendation: "WAITLIST", final_decision: null });
    assert.equal((await (await rec.GET(null, context("APP_050"))).json()).version.reason, input.resolution.reason);
    await client.query("UPDATE applicants SET superscored_sat_score=1599");
    assert.equal((await rec.PUT(request(input), context("APP_050"))).status, 409);
    // A modern clean dossier supports normal recommendation without exception fields.
    await client.query("INSERT INTO applicants(app_id,status) VALUES ('APP_051','READY_FOR_REVIEW')");
    const clean = { ...candidate, app_id: "APP_051", review_notes: [] };
    const runId = (await client.query("INSERT INTO dossier_generation_runs(app_id,run_status,validation) VALUES ('APP_051','REVIEW_PENDING','{\"passed\":true}') RETURNING id")).rows[0].id;
    const automatic = (await client.query("SELECT route_dossier_candidate('APP_051',$1,$2,checkpoint_input_snapshot('APP_051'),'v1',clock_timestamp()+interval '1 day') AS result", [runId, clean])).rows[0].result;
    assert.equal(automatic.review_mode, "AUTOMATIC");
    const cleanReview = await (await rec.GET(null, context("APP_051"))).json();
    assert.equal((await rec.PUT(request({ recommendation: "ACCEPT", notes: "Normal single-pass review" }), context("APP_051"))).status, 409);
    assert.equal((await rec.PUT(request({ recommendation: "ACCEPT", notes: "Normal single-pass review", version: cleanReview.version }), context("APP_051"))).status, 200);
    const evidence = {};
    for (const [table, columns] of [["applicants", "app_id,status,officer_recommendation,final_decision"],
      ["dossier_review_requests", "id,app_id,state,review_mode,decision,reviewer,reason,candidate_hash,generation_run_id"],
      ["applicant_dossier", "app_id,publication_request_id"], ["dossier_publication_receipts", "request_id,app_id,candidate_hash"]]) {
      evidence[table] = (await client.query(`SELECT ${columns} FROM ${table} ORDER BY app_id`)).rows;
    }
    t.diagnostic("integrated_receiver_snapshot: " + JSON.stringify(evidence));
  } finally {
    globalThis.__pgPool = previous;
    await client.query("ROLLBACK"); await client.query("SET search_path=public");
    assert.match(schema, /^checkpoint_ui_test_[a-f0-9]+$/);
    await client.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`); await client.end();
  }
});
