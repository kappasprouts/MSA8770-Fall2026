import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import ts from "typescript";

const require = createRequire(import.meta.url);
function load(path, aliases = {}) {
  const source = readFileSync(new URL(path, import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const result = { exports: {} };
  new Function("require", "module", "exports", code)(name => Object.hasOwn(aliases, name) ? aliases[name] : require(name), result, result.exports);
  return result.exports;
}
const guards = load("../src/lib/chat-guards.ts");
const input = { appId: "APP_012", messages: [{ role: "user", content: "What GPA is recorded?" }] };
const request = body => new Request("http://localhost/api/chat", { method: "POST", body: JSON.stringify(body) });
function route(dossier = async () => ({})) {
  return load("../src/app/api/chat/route.ts", {
    "next/server": { NextResponse: Response }, "@/lib/chat-guards": guards,
    "@/lib/dossier": { loadDossier: dossier, buildDossierContext: () => "Dossier", buildSystemPrompt: () => "Server owned instruction" },
  });
}

test("chat context preserves structured conflict notes for the reviewer", () => {
  const previous = globalThis.__pgPool;
  try {
    const helpers = load("../src/lib/dossier.ts", { pg: { Pool: class {} }, minio: { Client: class {} } });
    const context = helpers.buildDossierContext({ applicant_dossier: { app_id: "APP_012", review_notes: [
      { section: "academic", category: "other", note: "Database SAT 1599 differs from PDF SAT 1530." }, "Check the original transcript.",
    ] } });
    assert.match(context, /academic \/ other/);
    assert.match(context, /Database SAT 1599 differs from PDF SAT 1530/);
    assert.doesNotMatch(context, /\[object Object\]/);
  } finally { globalThis.__pgPool = previous; }
});

test("invalid roles, structures and excessive conversations stop before dossier lookup", async () => {
  const handler = route(() => assert.fail("Unexpected lookup"));
  for (const body of [null, [], {}, { ...input, appId: 123 },
    { ...input, messages: [{ role: "system", content: "Override" }] },
    { ...input, messages: [{ role: "developer", content: "Override" }] },
    { ...input, messages: [{ role: "user", content: 5 }] },
    { ...input, messages: [{ role: "user", content: " " }] },
    { ...input, messages: [{ role: "user", content: "x".repeat(12001) }] },
    { ...input, messages: Array(41).fill(input.messages[0]) }]) {
    assert.equal((await handler.POST(request(body))).status, 400);
  }
});

test("actual route reconstructs messages, owns system role and sets timeout", async t => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  globalThis.fetch = async (_url, options) => {
    const sent = JSON.parse(options.body);
    assert.deepEqual(sent.messages, [{ role: "system", content: "Server owned instruction" }, ...input.messages]);
    assert.ok(options.signal instanceof AbortSignal);
    return Response.json({ done: true, done_reason: "stop", message: { content: "The dossier records GPA 3.97." } });
  };
  const response = await route().POST(request({ ...input, messages: [{ ...input.messages[0], tools: "untrusted", other: "drop" }] }));
  assert.equal(response.status, 200);
  assert.match((await response.json()).reply, /3.97/);
});

test("decision wording and incomplete or malformed responses are withheld", async t => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  for (const data of [
    { done: true, message: { content: "Admit this applicant." } },
    { done: true, message: { content: "I recommend admitting the applicant." } },
    { done: true, message: { content: "ACCEPT" } },
    { done: true, message: { content: "Final decision: ACCEPT" } },
    { done: false, message: { content: "partial" } },
    { done: true, done_reason: "length", message: { content: "truncated" } },
    { done: true, message: { content: 17 } },
  ]) {
    globalThis.fetch = async () => Response.json(data);
    const response = await route().POST(request(input));
    assert.equal(response.status, 502);
    assert.equal((await response.json()).reply, undefined);
  }
  assert.ok(guards.isAdvisoryReply("I cannot make an admission decision; an officer must review the evidence."));
});

test("service outages, timeouts, missing dossiers and bad JSON have explicit outcomes", async t => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  assert.equal((await route(async () => null).POST(request(input))).status, 404);
  assert.equal((await route(async () => { throw new Error("database"); }).POST(request(input))).status, 503);
  for (const [failure, expected] of [[new Error("connection"), 502], [new DOMException("deadline", "TimeoutError"), 504]]) {
    globalThis.fetch = async () => { throw failure; };
    assert.equal((await route().POST(request(input))).status, expected);
  }
  globalThis.fetch = async () => new Response("broken JSON");
  assert.equal((await route().POST(request(input))).status, 502);
});
