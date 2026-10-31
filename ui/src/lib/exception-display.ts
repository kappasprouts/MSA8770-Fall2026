import type { ExceptionRecord, ExceptionSeverity } from "./exception-types";

export function formatExceptionDate(value: string | null): string {
  if (!value) return "Timestamp unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export function exceptionStatusLabel(value: string): string {
  return value.replaceAll("_", " ").toLowerCase()
    .replace(/\b\w/g, character => character.toUpperCase()).replace(/\bAi\b/g, "AI");
}

export function exceptionSourceLabel(source: ExceptionRecord["source"]): string {
  if (source === "ORPHAN_INTAKE") return "Orphan intake";
  if (source === "SUMMARIZER") return "Summarizing agent";
  return "Ingestion gate";
}

/** Use the workspace's existing semantic status colors for technical priority. */
export function exceptionPriorityTone(severity: ExceptionSeverity): "failed" | "pending" | "done" {
  if (severity === "CRITICAL" || severity === "HIGH") return "failed";
  return severity === "MEDIUM" ? "pending" : "done";
}
