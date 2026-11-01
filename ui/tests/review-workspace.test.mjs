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

test("the dossier restores the maria/integration card sequence with working evidence citations", () => {
  const Links = load("../src/components/dossier/EvidenceLinks.tsx", { "@/components/eaos.module.css": { default: {} } }).default;
  const Evidence = load("../src/components/dossier/EvidenceCard.tsx", { "./EvidenceLinks": { default: Links } }).default;
  const Info = () => null, Summary = () => null, Snapshot = () => null, Policy = () => null;
  const Overview = load("../src/components/ApplicantOverview.tsx", {
    "@/components/dossier/ApplicantInfoCard": { default: Info }, "@/components/dossier/SummaryCard": { default: Summary },
    "@/components/dossier/SnapshotCard": { default: Snapshot }, "@/components/dossier/PolicyChecksCard": { default: Policy },
    "@/components/dossier/EvidenceCard": { default: Evidence }, "./eaos.module.css": { default: {} },
  }).default;
  const payload = { applicant_dossier: { holistic_assessment: "Summary text", policy_assessment: [{ policy_id: "P1" }], strengths: [{ strength: "Strong coursework", evidence: [{ document: "transcript.pdf", page: 2 }] }] } };
  const tree = Overview({ payload, onViewEvidence() {} });
  const cards = [...elements(tree)].filter(node => [Info, Summary, Snapshot, Policy, Evidence].includes(node.type));
  assert.deepEqual(cards.map(node => node.type), [Info, Summary, Snapshot, Policy, Evidence]);
  const html = renderToStaticMarkup(cards[4]);
  assert.match(html, /Strong coursework/);
  assert.match(html, /transcript.pdf.*p. 2/);
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

function review(payload = { applicant_dossier: { app_id: "APP_A" } }) {
  const state = [null, "", { reviewer: "", reason: "", confirmed: false, evidenceReviewed: false }, false];
  let cursor = 0, refCursor = 0;
  const targets = Array.from({ length: 3 }, () => ({ scrolls: 0, focuses: 0, scrollIntoView() { this.scrolls++; }, focus() { this.focuses++; } }));
  const refs = targets.map(current => ({ current }));
  const Overview = () => null, Dossier = () => null, Documents = () => null, Officer = () => null, Chat = () => null, Exceptions = () => null;
  const Component = load("../src/components/ApplicantReviewWorkspace.tsx", {
    react: { ...React, useRef: () => refs[refCursor++], useState() {
      const index = cursor++;
      return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
    } },
    "./ApplicantOverview": { default: Overview }, "./DossierPanel": { default: Dossier }, "./DocumentsPanel": { default: Documents },
    "./OfficerRecommendationPanel": { default: Officer }, "./ChatPanel": { default: Chat }, "./WorkspaceIcon": { default: () => null },
    "./ApplicantExceptionsPanel": { default: Exceptions },
    "@/lib/review-workspace": workspace, "@/lib/recommendation": recommendations, "./eaos.module.css": { default: {} },
  }).default;
  const props = { appId: "APP_A", payload, documents, header: "Applicant header", recommendation: { ...recommendations.INITIAL_RECOMMENDATION_STATE, loading: false, canEdit: true }, onRecommendationStateChange() {} };
  function render() { cursor = 0; refCursor = 0; return Component(props); }
  const find = predicate => [...elements(render())].find(predicate);
  return {
    overview: () => find(node => node.type === Overview), documents: () => find(node => node.type === Documents),
    officer: () => find(node => node.type === Officer), chat: () => find(node => node.type === Chat),
    exceptions: () => find(node => node.type === Exceptions),
    button: label => find(node => node.type === "button" && node.props.children === label),
    props, targets, html: () => renderToStaticMarkup(render()),
  };
}

test("the restored reading layout shows dossier, documents and Q&A together with a mounted recommendation", () => {
  const view = review();
  assert.match(view.html(), /aria-labelledby="review-dossier-heading"/);
  assert.match(view.html(), /aria-labelledby="review-documents-heading"/);
  assert.equal(view.exceptions(), undefined);
  assert.ok(view.overview());
  assert.ok(view.documents());
  assert.ok(view.chat());
  assert.ok(view.officer());
  assert.match(view.html(), /Full dossier details/);
  assert.doesNotMatch(view.html(), /Read full dossier/);
  assert.equal(view.button("Dossier"), undefined);
  assert.equal(view.button("Original documents"), undefined);
  assert.equal(view.officer().props.appId, "APP_A");
  view.documents().props.onSelect({ file: "CommonApp.pdf", page: 1 });
  assert.equal(view.documents().props.selection.file, "CommonApp.pdf");
  view.button("Write recommendation").props.onClick();
  assert.equal(view.targets[2].scrolls, 1);
  assert.equal(view.targets[2].focuses, 1);
});

test("exception resolution remains linked to the recommendation and Q&A stays unavailable for drafts", () => {
  const view = review({ applicant_dossier: { app_id: "APP_A" }, review_checkpoint: {
    request_id: "request", candidate_hash: "hash", state: "REVIEW_PENDING", reasons: ["Scores conflict"],
  } });
  assert.ok(view.exceptions());
  assert.equal(view.chat(), undefined);
  assert.match(view.html(), /This draft has exceptions to review/);
  const draft = { reviewer: "Officer", reason: "Checked original sources", confirmed: true, evidenceReviewed: true };
  view.exceptions().props.onChange(draft);
  view.exceptions().props.onOpenDocuments();
  assert.equal(view.targets[0].scrolls, 1);
  assert.deepEqual(view.exceptions().props.resolution, draft);
  view.exceptions().props.onContinue();
  assert.equal(view.targets[2].scrolls, 1);
  assert.deepEqual(view.officer().props.exceptionResolution, draft);
  assert.deepEqual(view.officer().props.dossierVersion, { requestId: "request", candidateHash: "hash" });
  view.officer().props.onOpenExceptions();
  assert.equal(view.targets[1].scrolls, 1);
  view.props.payload = { applicant_dossier: { app_id: "APP_A" } };
  assert.equal(view.exceptions(), undefined);
  assert.ok(view.chat());
});

test("citation clicks select the cited PDF page and missing sources show an explicit message", () => {
  const view = review();
  view.overview().props.onViewEvidence({ document: "CommonApp.pdf", page: 2 });
  assert.deepEqual(view.documents().props.selection, { file: "CommonApp.pdf", page: 2 });
  assert.equal(view.targets[0].scrolls, 1);
  view.overview().props.onViewEvidence({ document: "missing.pdf", page: 2 });
  assert.match(view.html(), /cited source missing.pdf is not listed/);
  assert.deepEqual(view.documents().props.selection, { file: "CommonApp.pdf", page: 2 });
});

test("Q&A stays inline for published dossiers and full dossier details use the native expander", () => {
  const view = review();
  assert.equal(view.chat().props.appId, "APP_A");
  assert.match(view.html(), /<details><summary>Full dossier details<\/summary>/);
});
