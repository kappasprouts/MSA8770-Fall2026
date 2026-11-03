import test from "node:test";
import assert from "node:assert/strict";
import { isItActionable } from "../src/lib/it-exceptions.mjs";
const row = (status, findings = [], source = "INGESTION") => ({ status, findings, source });
test("student missing material is not an IT incident", () => {
  assert.equal(isItActionable(row("AWAITING_MATERIALS", ["Missing required document: Transcript"])), false);
  assert.equal(isItActionable(row("INCOMPLETE", ["Missing required field: admission term"])), false);
  assert.equal(isItActionable(row("REPLACEMENT_REQUESTED")), false);
  assert.equal(isItActionable(row("ERROR", ["Missing required document: Transcript"])), false);
});
test("technical errors and orphan intake remain available to IT", () => {
  assert.equal(isItActionable(row("AGENT_ERROR")), true);
  assert.equal(isItActionable(row("AI_VALIDATION_FAILED", ["Citation mismatch"], "SUMMARIZER")), true);
  assert.equal(isItActionable(row("PROCESSING_ERROR")), true);
  assert.equal(isItActionable(row("ORPHAN_DOCUMENT", [], "ORPHAN_INTAKE")), true);
});
test("unknown workflow status is not automatically a technical error", () => {
  assert.equal(isItActionable(row("READY_FOR_REVIEW")), false);
  assert.equal(isItActionable(row("HUMAN_REVIEW")), false);
});
