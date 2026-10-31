import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { isItActionable } from "../src/lib/it-exceptions.mjs";

const require = createRequire(import.meta.url);
function load(path, aliases = {}) {
  const compiled = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const loaded = { exports: {} };
  new Function("require", "module", "exports", compiled)(name => Object.hasOwn(aliases, name) ? aliases[name] : require(name), loaded, loaded.exports);
  return loaded.exports;
}

const display = load("../src/lib/exception-display.ts");
const wrapper = ({ children }) => React.createElement("div", {}, children);
const aliases = {
  "./eaos.module.css": { default: {} }, "./exceptions.module.css": { default: {} },
  "@/lib/exception-display": display, "@/lib/http": {},
  "./WorkspaceIcon": { default: () => null },
  "./RequestState": { default: ({ title, description }) => React.createElement("div", {}, title, description) },
};
function* elements(value) {
  if (Array.isArray(value)) { for (const child of value) yield* elements(child); }
  else if (React.isValidElement(value)) { yield value; yield* elements(value.props.children); }
}
function panel(path, states, props = {}) {
  let cursor = 0;
  const Component = load(path, { ...aliases, react: {
    ...React, useEffect() {}, useMemo: callback => callback(),
    useState() {
      const index = cursor++;
      return [states[index], value => { states[index] = typeof value === "function" ? value(states[index]) : value; }];
    },
  } }).default;
  function render() { cursor = 0; return Component(props); }
  return {
    all: () => [...elements(render())],
    find: predicate => [...elements(render())].find(predicate),
    html: () => renderToStaticMarkup(render()),
  };
}
const record = (id, extra = {}) => ({
  id, applicantId: id, applicantName: `Example ${id}`, intendedMajor: "Biology", status: "AI_VALIDATION_FAILED",
  category: "AI Validation Failure", severity: "HIGH", source: "SUMMARIZER", summary: "Citation mismatch",
  findings: ["Unsupported citation"], affectedDocuments: ["transcript.pdf"], updatedAt: null, hasDossier: true,
  auditHistory: [{ action: "AI_VALIDATION_FAILED", actor: "summarizing_agent", createdAt: "2026-10-31T12:00:00Z" }], ...extra,
});

test("queue search includes affected documents, combines filters, and opens the matching exception", () => {
  const rows = [record("APP_A"), record("APP_B", { severity: "LOW", affectedDocuments: ["essay.pdf"] }),
    record("orphan-1", { applicantId: null, source: "ORPHAN_INTAKE", severity: "MEDIUM", category: "Orphan Document" })];
  let selected;
  const view = panel("../src/components/ErrorQueuePanel.tsx", [rows, false, "", "", "ALL", "ALL", 0], { onViewDetails: id => { selected = id; } });
  const ids = () => view.all().filter(node => node.type === "tr" && node.key).map(node => node.key);
  assert.equal(ids().length, 3);
  view.find(node => node.type === "input").props.onChange({ target: { value: " essay.pdf " } });
  assert.deepEqual(ids(), ["APP_B"]);
  view.find(node => node.props["aria-label"] === "View details for APP_B").props.onClick();
  assert.equal(selected, "APP_B");
  view.find(node => node.type === "input").props.onChange({ target: { value: "" } });
  view.find(node => node.props["aria-label"] === "Filter by category").props.onChange({ target: { value: "AI Validation Failure" } });
  view.find(node => node.props["aria-label"] === "Filter by priority").props.onChange({ target: { value: "HIGH" } });
  assert.deepEqual(ids(), ["APP_A"]);
  view.find(node => node.props["aria-label"] === "Filter by priority").props.onChange({ target: { value: "CRITICAL" } });
  assert.match(view.html(), /No exceptions match these filters/);
});

test("queue distinguishes loading, outages, and a true empty queue without showing stale rows", () => {
  const view = (rows, loading, error) => panel("../src/components/ErrorQueuePanel.tsx", [rows, loading, error, "", "ALL", "ALL", 0]);
  assert.match(view([], true, "").html(), /Loading exception records/);
  assert.match(view([], false, "").html(), /No IT system errors found/);
  const failed = view([record("STALE")], false, "Service unavailable");
  assert.match(failed.html(), /The error queue could not be loaded/);
  assert.doesNotMatch(failed.html(), /Example STALE/);
  assert.match(failed.html(), /<strong>—<\/strong>/);
  failed.find(node => node.type === "button" && node.props.children === "Refresh queue").props.onClick();
  assert.match(failed.html(), /Loading exception records/);
});

test("details retain findings, documents, audit history, back navigation, and conditional dossier access", () => {
  let opened;
  let backed = false;
  const props = { exceptionId: "APP_A", onBack: () => { backed = true; }, onOpenApplicant: id => { opened = id; } };
  const row = record("APP_A", { findings: ["Unsafe <script> content", "x".repeat(200)] });
  const view = panel("../src/components/ApplicantExceptionDetails.tsx", [row, false, "", 0], props);
  assert.match(view.html(), /Unsafe &lt;script&gt; content/);
  for (const text of ["Validation findings", "transcript.pdf", "Audit history", "summarizing_agent"]) assert.ok(view.html().includes(text));
  view.find(node => node.type === "button" && node.props.children === "Open available applicant dossier").props.onClick();
  assert.equal(opened, "APP_A");
  view.find(node => node.type === "button" && node.props.children !== "Open available applicant dossier").props.onClick();
  assert.equal(backed, true);
  const orphan = panel("../src/components/ApplicantExceptionDetails.tsx", [record("orphan", { applicantId: null, hasDossier: false, findings: [], affectedDocuments: [], auditHistory: [] }), false, "", 0], props);
  assert.doesNotMatch(orphan.html(), /Open available applicant dossier/);
  assert.match(orphan.html(), /No audit events are available/);
  assert.match(panel("../src/components/ApplicantExceptionDetails.tsx", [null, false, "Exception missing", 0], props).html(), /Exception details unavailable/);
});

test("nested exception routes keep IT navigation active and preserve all existing workspaces", () => {
  const Shell = load("../src/components/EaosShell.tsx", {
    "next/link": { default: ({ children, ...props }) => React.createElement("a", props, children) },
    "next/navigation": { usePathname: () => "/error-queue/applicant-APP_A-summarizer", useRouter: () => ({}) },
    "./eaos.module.css": { default: {} }, "./Logo": { default: () => null }, "./WorkspaceIcon": { default: () => null },
  }).default;
  const html = renderToStaticMarkup(React.createElement(Shell, { title: "Exception Details", subtitle: "", role: "IT administrator" }));
  for (const label of ["Home", "Processing Dashboard", "Applicant Review", "Final Decisions", "Summary Statistics", "IT Error Queue"]) assert.ok(html.includes(`aria-label="${label}"`));
  assert.equal((html.match(/aria-current="page"/g) ?? []).length, 1);
  assert.match(html, /href="\/error-queue" aria-current="page"/);
  assert.doesNotMatch(html, /coming soon/i);
});

test("queue and details routes encode IDs and use mi's canonical applicant link", () => {
  const pushed = [];
  const navigation = { useRouter: () => ({ push: path => pushed.push(path) }), useParams: () => ({ id: "exception A" }) };
  const http = load("../src/lib/http.ts");
  const review = load("../src/lib/review-state.ts");
  const recommendation = load("../src/lib/recommendation.ts");
  const api = load("../src/lib/eaos-api.ts", { "./http": http, "./review-state": review, "./recommendation": recommendation });
  const routeAliases = { "next/navigation": navigation, "@/components/EaosShell": { default: wrapper },
    "@/components/ErrorQueuePanel": { default: wrapper }, "@/components/ApplicantExceptionDetails": { default: wrapper }, "@/lib/eaos-api": api };
  const queue = load("../src/app/error-queue/page.tsx", routeAliases).default();
  queue.props.children.props.onViewDetails("orphan / A");
  assert.equal(pushed.pop(), "/error-queue/orphan%20%2F%20A");
  const detail = load("../src/app/error-queue/[id]/page.tsx", routeAliases).default().props.children;
  assert.equal(detail.key, "exception A");
  detail.props.onOpenApplicant("APP / A");
  assert.equal(pushed.pop(), "/applicant-review?appId=APP%20%2F%20A");
  detail.props.onBack();
  assert.equal(pushed.pop(), "/error-queue");
});

test("exception API preserves technical evidence and orphan records while excluding student-only findings", async () => {
  const applicant = (id, status, extra = {}) => ({ app_id: id, status, documents: [], audit_details: {}, ...extra });
  const pool = { async query(sql) {
    assert.match(sql.trim(), /^SELECT/);
    return { rows: sql.includes("FROM orphan_documents") ? [{ id: "orphan-id", filename: "unmatched.pdf", minio_key: "incoming/unmatched.pdf", sha256: "abc" }]
      : [applicant("APP_A", "ERROR", { run_status: "AI_VALIDATION_FAILED", run_validation: { failed_sections: { evidence: ["Citation mismatch"] } }, has_dossier: true }),
        applicant("APP_B", "ERROR", { audit_details: { missing_documents: ["transcript"] } })] };
  } };
  const route = load("../src/app/api/exceptions/route.ts", { "@/lib/dossier": { pool }, "@/lib/it-exceptions.mjs": { isItActionable }, "next/server": { NextResponse: Response } });
  const response = await route.GET();
  assert.equal(response.status, 200);
  const { exceptions } = await response.json();
  assert.deepEqual(exceptions.map(item => item.id), ["applicant-APP_A-summarizer", "orphan-orphan-id"]);
  assert.deepEqual(exceptions[0].findings, ["Evidence: Citation mismatch"]);
  assert.equal(exceptions[0].hasDossier, true);
  assert.equal(exceptions[1].applicantId, null);
  assert.deepEqual(exceptions[1].affectedDocuments, ["unmatched.pdf"]);
});
