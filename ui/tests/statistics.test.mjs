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
const stats = loadTypeScript("../src/lib/statistics.ts");
const validGate = { missing_documents: [], missing_fields: [], error_count: 0, ready_for_review: true };
const fixtures = [
  { admission_year: 2026, admission_term: "F", intended_major: "Biology", status: "DOSSIER_READY", final_decision: "ACCEPT", unweighted_gpa: "4.00", superscored_sat_score: 1600, total_aps: 10, total_ibs: 0, gender: "Female", country: "USA", create_date_time: "2026-01-01T12:30:00Z", gate: validGate },
  { admission_year: 2026, admission_term: "F", intended_major: "Biology", status: "AGENT_ERROR", final_decision: "DECLINE", unweighted_gpa: "3", sat_math: 600, sat_ebrw: 600, superscored_act_score: 32, total_aps: 0, create_date_time: "2026-03-04T00:00:00Z", gate: validGate },
  { admission_year: 2025, admission_term: "S", intended_major: "History", status: "AWAITING_MATERIALS", unweighted_gpa: 2, act_composite: 20, total_aps: 4, gate: { missing_documents: ["transcript", "transcript", "recommendation_letter_1"], missing_fields: [], error_count: 0 }, create_date_time: "2025-02-31" },
  { admission_year: 2025, admission_term: "S", intended_major: "History", status: "INCOMPLETE", final_decision: "WAITLIST", unweighted_gpa: 0, total_aps: null, gate: { missing_documents: ["transcript"], missing_fields: ["email"], error_count: 0 } },
  { admission_year: 2026, admission_term: "F", status: "PENDING", unweighted_gpa: "", superscored_sat_score: 0, superscored_act_score: "", total_aps: -1, create_date_time: "ambiguous date" },
];

test("all applicant records contribute, independent of dossier or decision availability", () => {
  const data = stats.buildStatistics(fixtures);
  assert.equal(data.total, 5);
  assert.equal(data.complete, 2, "An agent failure does not turn a passed packet into an incomplete packet");
  assert.equal(data.recorded, 3);
  assert.equal(data.withoutDecision, 2);
  assert.equal(data.accepted, 1);
  assert.equal(data.testSubmitters, 3, "An applicant with both test types is counted once");
  assert.equal(data.decisions.reduce((sum, i) => sum + i.count, 0), 5);
  assert.equal(data.completeness.reduce((sum, i) => sum + i.count, 0), 5);
  assert.equal(data.programs.find(i => i.label === stats.UNKNOWN_LABEL).count, 1);
  assert.equal(data.genders.find(i => i.label === stats.UNKNOWN_LABEL).count, 4);
  assert.equal(data.missingDocuments.find(i => i.label === "Transcript").count, 2, "A repeated missing document counts once per packet");
});

test("academic values preserve real zeros, reject invalid scores, and calculate interpolated percentiles", () => {
  const data = stats.buildStatistics(fixtures), gpa = data.academics.find(m => m.key === "gpa");
  assert.equal(gpa.count, 4);
  assert.equal(gpa.missing, 1);
  assert.equal(gpa.mean, 2.25);
  assert.equal(gpa.median, 2.5);
  assert.equal(gpa.q1, 1.5);
  assert.equal(gpa.q3, 3.25);
  assert.equal(data.academics.find(m => m.key === "sat").mean, 1400);
  assert.equal(data.academics.find(m => m.key === "ap").count, 3);
  for (const metric of data.academics.filter(m => m.histogram.length)) assert.equal(metric.histogram.reduce((n, b) => n + b.count, 0), metric.count);
  const boundaries = stats.buildStatistics([400, 800, 1000, 1200, 1400, 1600].map(superscored_sat_score => ({ superscored_sat_score })));
  assert.deepEqual(boundaries.academics.find(m => m.key === "sat").histogram.map(i => i.count), [1, 1, 1, 1, 2]);
  const invalid = stats.buildStatistics([{ unweighted_gpa: 5, total_aps: 2.5, superscored_sat_score: true, act_composite: 37 }]);
  for (const m of invalid.academics) assert.equal(m.count, 0);
});

test("cohort filters apply to every chart and comparison while options retain the full pool", () => {
  const filters = { year: "2026", term: "F", major: "Biology", decision: "ACCEPT" };
  const data = stats.buildStatistics(fixtures, filters);
  assert.equal(data.total, 1);
  assert.equal(data.academics[0].mean, 4);
  assert.equal(data.totalRecords, 5);
  assert.equal(data.options.years.length, 2);
  assert.equal(data.cohorts.cycle.length, 1);
  assert.equal(data.cohorts.program.length, 1);
  assert.equal(data.cohorts.cycle[0].recorded, 1);
  assert.equal(data.trend.reduce((n, i) => n + i.count, 0), 1);
  assert.equal(stats.buildStatistics(fixtures, { ...stats.EMPTY_FILTERS, major: stats.UNKNOWN }).total, 1);
  assert.equal(stats.buildStatistics(fixtures, { ...stats.EMPTY_FILTERS, decision: "UNRECORDED" }).total, 2);
  const empty = stats.buildStatistics(fixtures, { ...filters, major: "No such program" });
  assert.equal(empty.total, 0);
  assert.equal(empty.academics[0].mean, null);
  assert.equal(stats.percentage(0, 0), null);
  assert.equal(stats.percentage(0, 5), 0);
});

test("application trends use valid source dates, preserve empty months, and exclude import times", () => {
  const data = stats.buildStatistics(fixtures);
  assert.deepEqual(data.trend, [{ label: "2026-01", count: 1 }, { label: "2026-02", count: 0 }, { label: "2026-03", count: 1 }]);
  assert.equal(data.trendUndated, 3);
  const noSource = stats.buildStatistics([{ created_at: "2026-01-01" }]);
  assert.deepEqual(noSource.trend, []);
  assert.equal(noSource.trendUndated, 1);
});

test("filter parsing and CSV export handle hostile text without exposing source applicant fields", () => {
  assert.throws(() => stats.parseStatisticsFilters(new URLSearchParams("year=2026%27+OR+1=1")));
  assert.throws(() => stats.parseStatisticsFilters(new URLSearchParams("decision=oops")));
  assert.throws(() => stats.parseStatisticsFilters(new URLSearchParams({ major: "a".repeat(151) })));
  const data = stats.buildStatistics([{ ...fixtures[0], app_id: "SECRET_ID", email: "secret@example.com", intended_major: ' =HYPERLINK("bad")' }]);
  const csv = stats.statisticsCsv(data);
  assert.match(csv, /'=HYPERLINK\(""bad""\)/);
  assert.doesNotMatch(csv, /SECRET_ID|secret@example/);
  assert.match(csv, /Median GPA/);
  assert.match(csv, /25th percentile/);
});

test("statistics endpoint validates first, returns aggregate-only results, and distinguishes outages", async () => {
  let called = 0, sql = "";
  const route = loadTypeScript("../src/app/api/statistics/route.ts", {
    "@/lib/statistics": stats,
    "@/lib/dossier": { pool: { query: async query => { called++; sql = query; return { rows: fixtures }; } } },
  });
  const invalid = await route.GET(new Request("http://localhost/api/statistics?decision=bad"));
  assert.equal(invalid.status, 400);
  assert.equal(called, 0);
  const response = await route.GET(new Request("http://localhost/api/statistics?year=2026"));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal((await response.json()).total, 3);
  assert.match(sql, /DISTINCT ON \(applicant_id\)/);
  assert.match(sql, /MANIFEST_REEVALUATED/);
  assert.match(sql, /created_at DESC/);
  const failed = loadTypeScript("../src/app/api/statistics/route.ts", {
    "@/lib/statistics": stats, "@/lib/dossier": { pool: { query: async () => { throw new Error("offline"); } } },
  });
  const oldLog = console.error; console.error = () => {};
  try { const response = await failed.GET(new Request("http://localhost/api/statistics")); assert.equal(response.status, 503); assert.match((await response.json()).error, /database connection/); }
  finally { console.error = oldLog; }
});

test("populated charts render accessible values, unknown categories, sample sizes, and useful links", () => {
  const styles = new Proxy({}, { get: (_target, prop) => prop });
  const charts = loadTypeScript("../src/components/statistics/Charts.tsx", { "@/lib/statistics": stats, "./statistics.module.css": styles });
  const view = loadTypeScript("../src/components/statistics/StatisticsDashboard.tsx", {
    "@/lib/statistics": stats, "./Charts": charts, "./statistics.module.css": styles,
    "@/components/EaosShell": { default: () => null }, "@/components/RequestState": { default: () => null },
    "@/lib/http": {}, "next/link": { default: ({ children, ...props }) => React.createElement("a", props, children) },
  });
  const html = renderToStaticMarkup(React.createElement(view.StatisticsContent, {
    data: stats.buildStatistics(fixtures), academicKey: "gpa", geography: "regions", comparison: "cycle",
    onAcademicChange() {}, onGeographyChange() {}, onComparisonChange() {}, onProgramSelect() {},
  }));
  for (const text of ["Admissions overview", "Academic distributions", "Geographic representation", "Cohort comparisons", "Unknown / not reported", "n =", "Middle 50%", "Missing required documents", "Gender", "Ethnicity"]) assert.ok(html.includes(text), text);
  assert.match(html, /role="img"/);
  assert.match(html, /aria-pressed="true"/);
  assert.match(html, /href="\/final-decisions"/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test("real statistics SQL uses the latest manifest per applicant without multiplying pool counts", { skip: !process.env.POSTGRES_DB }, async () => {
  const { Client } = require("pg");
  const client = new Client({ host: process.env.POSTGRES_HOST, port: Number(process.env.POSTGRES_PORT),
    database: process.env.POSTGRES_DB, user: process.env.POSTGRES_USER, password: process.env.POSTGRES_PASSWORD });
  const source = readFileSync(new URL("../src/app/api/statistics/route.ts", import.meta.url), "utf8");
  const sql = source.match(/pool\.query<StatisticsRow>\(`([\s\S]*?)`\)/)?.[1];
  assert.ok(sql);
  await client.connect();
  try {
    await client.query("BEGIN");
    await client.query(`CREATE TEMP TABLE applicants (
      app_id text, admission_year integer, admission_term text, intended_major text, status text, final_decision text,
      gender text, ethnicity text, country text, region text, name_of_hs text, unweighted_gpa numeric, weighted_gpa numeric,
      superscored_sat_score integer, sat_math integer, sat_ebrw integer, superscored_act_score integer, act_composite integer,
      total_aps integer, total_ibs integer, create_date_time text
    ) ON COMMIT DROP`);
    await client.query(`CREATE TEMP TABLE audit_logs (id text, applicant_id text, details jsonb, action text, created_at timestamptz) ON COMMIT DROP`);
    await client.query(`INSERT INTO applicants (app_id, admission_year, status, unweighted_gpa) VALUES
      ('A', 2026, 'AGENT_ERROR', 4), ('B', 2025, 'AWAITING_MATERIALS', 3), ('C', 2026, 'PENDING', NULL)`);
    await client.query(`INSERT INTO audit_logs VALUES
      ('1', 'A', '{"missing_documents":["transcript"],"missing_fields":[],"error_count":0}', 'MANIFEST_EVALUATED', '2026-01-01'),
      ('2', 'A', '{"missing_documents":[],"missing_fields":[],"error_count":0}', 'MANIFEST_REEVALUATED', '2026-02-01'),
      ('3', 'B', '{"missing_documents":["transcript"],"missing_fields":[],"error_count":0}', 'MANIFEST_EVALUATED', '2026-01-01')`);
    const { rows } = await client.query(sql), data = stats.buildStatistics(rows);
    assert.equal(rows.length, 3);
    assert.equal(data.complete, 1);
    assert.deepEqual(data.missingDocuments, [{ label: "Transcript", count: 1 }]);
    assert.equal(data.academics[0].mean, 3.5);
    await client.query("DELETE FROM applicants");
    assert.equal(stats.buildStatistics((await client.query(sql)).rows).total, 0);
  } finally { await client.query("ROLLBACK"); await client.end(); }
});
