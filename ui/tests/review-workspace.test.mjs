import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
function load(path, aliases = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const loadedModule = { exports: {} };
  new Function("require", "module", "exports", compiled)(name => Object.hasOwn(aliases, name) ? aliases[name] : require(name), loadedModule, loadedModule.exports);
  return loadedModule.exports;
}
const workspace = load("../src/lib/review-workspace.ts");
const recommendations = load("../src/lib/recommendation.ts");
const documents = [
  { file: "transcript.pdf", label: "Transcript", pages: [1, 2], access: "sent" },
  { file: "CommonApp.pdf", label: "Common application", pages: [1, 2], access: "sent" },
  { file: "personal_statement.pdf", label: "Personal statement", pages: null, access: "withheld", reason: "Human review only" },
];

test("source links resolve the matching document and page without substituting an unrelated PDF", () => {
  assert.deepEqual(workspace.resolveEvidenceDocument({ document: "batch/TRANSCRIPT.pdf", page: "2" }, documents), { file: "transcript.pdf", page: 2 });
  assert.deepEqual(workspace.resolveEvidenceDocument({ document: "C:\\packet\\CommonApp.pdf", page: 0 }, documents), { file: "CommonApp.pdf", page: 1 });
  for (const page of [-4, 1.5, "invalid", undefined]) assert.equal(workspace.resolveEvidenceDocument({ document: "transcript.pdf", page }, documents).page, 1);
  assert.equal(workspace.resolveEvidenceDocument({ document: "unknown.pdf", page: 1 }, documents), null);
  assert.equal(workspace.resolveEvidenceDocument({}, documents), null);
});

test("repeated source citations produce one link for each document and page", () => {
  const Links = load("../src/components/dossier/EvidenceLinks.tsx", { "@/components/eaos.module.css": { default: {} } }).default;
  const html = renderToStaticMarkup(React.createElement(Links, { evidence: [
    { document: "transcript.pdf", page: 1, quote: "First fact" },
    { document: "Transcript.pdf", page: 1, quote: "Second fact" },
    { document: "transcript.pdf", page: 2 },
  ], onView() {} }));
  assert.equal((html.match(/<button/g) || []).length, 2);
  assert.match(html, /p. 1/);
  assert.match(html, /p. 2/);
});

test("document viewer renders one selected PDF, preserves cited pages, and labels human-only documents", () => {
  const hooks = { ...React, useEffect() {}, useRef: () => ({ current: null }), useState: initial => [initial, () => {}] };
  const Panel = load("../src/components/DocumentsPanel.tsx", { react: hooks, "./eaos.module.css": { default: {} } }).default;
  const html = renderToStaticMarkup(React.createElement(Panel, { appId: "APP / A", documents, selection: { file: "CommonApp.pdf", page: 2 }, onSelect() {} }));
  assert.equal((html.match(/<iframe/g) || []).length, 1);
  assert.match(html, /CommonApp.pdf#page=2&amp;zoom=page-width&amp;toolbar=1/);
  assert.match(html, /appId=APP%20%2F%20A/);
  assert.match(html, /<option value="CommonApp.pdf" selected=""/);
  assert.match(html, /Expand viewer/);
  const withheld = renderToStaticMarkup(React.createElement(Panel, { appId: "APP_A", documents, selection: { file: "personal_statement.pdf", page: 1 }, onSelect() {} }));
  assert.match(withheld, /Reserved for human review.*Human review only/);
  assert.match(renderToStaticMarkup(React.createElement(Panel, { appId: "APP_A", documents: [], selection: null, onSelect() {} })), /No source documents/);
});

function* elements(value) {
  if (Array.isArray(value)) { for (const item of value) yield* elements(item); }
  else if (React.isValidElement(value)) { yield value; yield* elements(value.props.children); }
}

function review() {
  const state = ["overview", null, false, "", false, false];
  let cursor = 0;
  const Overview = () => null, Dossier = () => null, Documents = () => null, Officer = () => null, Chat = () => null;
  const Component = load("../src/components/ApplicantReviewWorkspace.tsx", {
    react: { ...React, useEffect() {}, useRef: () => ({ current: null }), useState() {
      const index = cursor++;
      return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
    } },
    "./ApplicantOverview": { default: Overview }, "./DossierPanel": { default: Dossier }, "./DocumentsPanel": { default: Documents },
    "./OfficerRecommendationPanel": { default: Officer }, "./ChatPanel": { default: Chat },
    "@/lib/review-workspace": workspace, "@/lib/recommendation": recommendations, "./eaos.module.css": { default: {} },
  }).default;
  const props = { appId: "APP_A", payload: { applicant_dossier: { app_id: "APP_A" } }, documents, header: "Applicant header", recommendation: { ...recommendations.INITIAL_RECOMMENDATION_STATE, loading: false, canEdit: true }, onRecommendationStateChange() {} };
  function render() { cursor = 0; return Component(props); }
  const find = predicate => [...elements(render())].find(predicate);
  return {
    tab: id => find(node => node.props.id === `review-tab-${id}`),
    panel: id => find(node => node.props.id === `review-panel-${id}`),
    overview: () => find(node => node.type === Overview), documents: () => find(node => node.type === Documents),
    officer: () => find(node => node.type === Officer), chat: () => find(node => node.type === Chat),
    button: label => find(node => node.type === "button" && node.props.children === label),
    props, html: () => renderToStaticMarkup(render()),
  };
}

test("tabs have accessible relationships, keep the recommendation mounted, and lazily load documents", () => {
  const view = review();
  assert.equal(view.tab("overview").props["aria-selected"], true);
  assert.equal(view.panel("overview").props.hidden, false);
  assert.equal(view.panel("recommendation").props.hidden, true);
  const officer = view.officer();
  assert.ok(officer, "Recommendation state must stay mounted while its tab is hidden");
  assert.equal(view.documents(), undefined);
  view.tab("recommendation").props.onClick();
  assert.equal(view.panel("recommendation").props.hidden, false);
  view.tab("dossier").props.onClick();
  assert.equal(view.officer().type, officer.type);
  assert.equal(view.officer().props.appId, "APP_A");
  view.tab("documents").props.onClick();
  assert.ok(view.documents());
  view.documents().props.onSelect({ file: "CommonApp.pdf", page: 1 });
  view.tab("overview").props.onClick();
  view.tab("documents").props.onClick();
  assert.equal(view.documents().props.selection.file, "CommonApp.pdf");
  assert.equal(view.tab("documents").props["aria-controls"], view.panel("documents").props.id);
});

test("citation clicks open the cited source and missing sources show an explicit message", () => {
  const view = review();
  view.overview().props.onViewEvidence({ document: "CommonApp.pdf", page: 2 });
  assert.equal(view.panel("documents").props.hidden, false);
  assert.deepEqual(view.documents().props.selection, { file: "CommonApp.pdf", page: 2 });
  view.tab("overview").props.onClick();
  view.overview().props.onViewEvidence({ document: "missing.pdf", page: 2 });
  assert.match(view.html(), /cited source missing.pdf is not listed/);
});

test("arrow, Home, and End keys switch tabs; Q&A state stays mounted after closing", () => {
  const view = review();
  const key = (id, name) => view.tab(id).props.onKeyDown({ key: name, preventDefault() {} });
  key("overview", "ArrowLeft");
  assert.equal(view.tab("recommendation").props["aria-selected"], true);
  key("recommendation", "Home");
  assert.equal(view.tab("overview").props.tabIndex, 0);
  key("overview", "End");
  assert.equal(view.tab("recommendation").props.tabIndex, 0);
  assert.equal(view.chat(), undefined);
  view.button("Ask Q&A").props.onClick();
  assert.equal(view.chat().props.appId, "APP_A");
  view.button("Close").props.onClick();
  assert.ok(view.chat(), "Closing Q&A must preserve its conversation and draft input");
});
