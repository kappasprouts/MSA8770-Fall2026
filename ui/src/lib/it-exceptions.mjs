/** IT operations triage policy. Student-correctable incomplete packets and
 * missing fields are NOT system errors. Keep this check server-side. */
const techFailures = new Set([
  "ERROR", "PROCESSING_ERROR", "AGENT_ERROR", "AI_VALIDATION_FAILED",
  "HUMAN_REVIEW_AI_FAILED", "PIPELINE_ERROR", "SUMMARIZER_ERROR",
]);
const studentOnly = new Set([
  "INCOMPLETE", "AWAITING_MATERIALS", "REPLACEMENT_REQUESTED",
  "COUNSELOR_REVIEW", "MISSING_FIELDS", "MISSING_MATERIALS",
]);
export function isItActionable(record) {
  if (record.source === "ORPHAN_INTAKE") return true; // back-office reconciliation
  const status = String(record.status ?? "").toUpperCase();
  if (studentOnly.has(status)) return false;
  if (!techFailures.has(status)) return false;
  const findings = Array.isArray(record.findings) ? record.findings : [];
  const messages = findings.map(x => String(x).toLowerCase());
  const studentIssue = /missing required (document|field)|missing (material|transcript|recommendation)|upload replacement|please resubmit/i;
  // A generic ERROR with only missing-material findings is an application
  // issue, not a system incident. An explicit AI/agent failure remains IT-owned.
  if (status === "ERROR" && messages.length > 0 && messages.every(x => studentIssue.test(x))) return false;
  return true;
}
