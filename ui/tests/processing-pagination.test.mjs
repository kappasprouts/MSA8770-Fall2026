import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("../src/app/review-queue/page.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;

function applicants(count) {
  return Array.from({ length: count }, (_, index) => ({
    appId: `APP_${String(index + 1).padStart(3, "0")}`, firstName: `Applicant ${index + 1}`, lastName: "Example",
    intendedMajor: "Biology", applicationStatus: index < 20 ? "DOSSIER_READY" : "INCOMPLETE", finalDecision: null,
  }));
}

function* elements(value) {
  if (Array.isArray(value)) {
    for (const child of value) yield* elements(child);
  } else if (React.isValidElement(value)) {
    yield value;
    yield* elements(value.props.children);
  }
}

// Drive the actual page's controls and state without adding browser-test dependencies.
function ledger(rows) {
  const state = [rows, false, "", "", "ALL", 1, 0, 0, { kind: "none" }];
  let cursor = 0;
  const aliases = {
    react: { ...React, useEffect() {}, useMemo: callback => callback(), useRef: () => ({ current: null }),
      useState() {
        const index = cursor++;
        return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
      },
    },
    "next/link": { default: ({ children, ...props }) => React.createElement("a", props, children) },
    "@/components/EaosShell": { default: ({ children }) => React.createElement("main", {}, children) },
    "@/components/RequestState": { default: ({ title }) => React.createElement("p", {}, title) },
    "@/components/StatusBadge": { default: ({ status }) => React.createElement("span", {}, status) },
    "@/components/eaos.module.css": { default: {} },
    "@/lib/eaos-api": { dossierHref: id => `/applicant-review?appId=${id}` },
    "@/lib/http": {}, "@/lib/review-state": { statusLabel: value => value },
  };
  const loaded = { exports: {} };
  new Function("require", "module", "exports", compiled)(
    name => Object.hasOwn(aliases, name) ? aliases[name] : require(name), loaded, loaded.exports,
  );
  function render() { cursor = 0; return loaded.exports.default(); }
  function find(predicate) { return [...elements(render())].find(predicate); }
  return {
    html: () => renderToStaticMarkup(render()),
    ids: () => [...elements(render())].filter(node => node.type === "tr" && node.key).map(node => node.key),
    button: name => find(node => node.type === "button" && node.props.children === name),
    field: label => find(node => node.props["aria-label"] === label),
    loaded: nextRows => { state[0] = nextRows; state[1] = false; },
  };
}

test("ledger caps each page at 20 and handles a partial last page with bounded navigation", () => {
  const view = ledger(applicants(45));
  assert.equal(view.ids().length, 20);
  assert.deepEqual([view.ids()[0], view.ids().at(-1)], ["APP_001", "APP_020"]);
  assert.equal(view.button("Previous").props.disabled, true);
  assert.equal(view.button("Next").props.disabled, false);
  assert.match(view.html(), /Showing 1–20 of 45 applicant\(s\)/);
  assert.match(view.html(), /Page 1 of 3/);
  assert.match(view.html(), /All applicants<\/small><strong>45<\/strong>/);

  view.button("Next").props.onClick();
  assert.deepEqual([view.ids()[0], view.ids().at(-1)], ["APP_021", "APP_040"]);
  view.button("Next").props.onClick();
  assert.equal(view.ids().length, 5);
  assert.deepEqual([view.ids()[0], view.ids().at(-1)], ["APP_041", "APP_045"]);
  assert.equal(view.button("Next").props.disabled, true);
  assert.match(view.html(), /Showing 41–45 of 45 applicant\(s\)/);
  view.button("Previous").props.onClick();
  assert.equal(view.ids()[0], "APP_021");
});

test("search covers every applicant and resets pagination", () => {
  const view = ledger(applicants(45));
  view.button("Next").props.onClick();
  view.field("Search applicants").props.onChange({ target: { value: "APP_045" } });
  assert.deepEqual(view.ids(), ["APP_045"]);
  assert.match(view.html(), /Showing 1–1 of 1 applicant\(s\) \(filtered from 45\)/);
  assert.equal(view.button("Previous").props.disabled, true);
  view.field("Search applicants").props.onChange({ target: { value: "" } });
  assert.equal(view.ids()[0], "APP_001");
  assert.match(view.html(), /Page 1 of 3/);
});

test("status filters paginate the full matching set and reset to the first page", () => {
  const view = ledger(applicants(45));
  view.button("Next").props.onClick();
  view.button("Next").props.onClick();
  view.field("Filter by status").props.onChange({ target: { value: "INCOMPLETE" } });
  assert.deepEqual([view.ids()[0], view.ids().at(-1)], ["APP_021", "APP_040"]);
  assert.match(view.html(), /Showing 1–20 of 25 applicant\(s\) \(filtered from 45\)/);
  assert.match(view.html(), /Page 1 of 2/);
  view.button("Next").props.onClick();
  assert.equal(view.ids().length, 5);
  view.field("Filter by status").props.onChange({ target: { value: "ALL" } });
  assert.equal(view.ids()[0], "APP_001");
});

test("exact multiples, one-page lists, empty results, refresh, and shrinking data keep valid page bounds", () => {
  const exact = ledger(applicants(40));
  exact.button("Next").props.onClick();
  assert.equal(exact.ids().length, 20);
  assert.equal(exact.button("Next").props.disabled, true);
  assert.match(exact.html(), /Page 2 of 2/);
  exact.loaded(applicants(5));
  assert.equal(exact.ids().length, 5);
  assert.match(exact.html(), /Page 1 of 1/);

  const single = ledger(applicants(20));
  assert.equal(single.button("Previous").props.disabled, true);
  assert.equal(single.button("Next").props.disabled, true);
  single.field("Search applicants").props.onChange({ target: { value: "no match" } });
  assert.equal(single.ids().length, 0);
  assert.equal(single.button("Next"), undefined);
  assert.match(single.html(), /No applicants match these filters/);
  assert.match(ledger([]).html(), /No applicant records yet/);

  const refreshed = ledger(applicants(45));
  refreshed.button("Next").props.onClick();
  refreshed.button("Refresh").props.onClick();
  assert.equal(refreshed.button("Next"), undefined);
  refreshed.loaded(applicants(45));
  assert.equal(refreshed.ids()[0], "APP_001");
  assert.match(refreshed.html(), /Page 1 of 3/);
});
