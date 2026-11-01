import type { EvidenceItem, OriginalDocument } from "./types";

export const REVIEW_TABS = [
  { id: "overview", label: "Overview" }, { id: "dossier", label: "Dossier" },
  { id: "documents", label: "Documents" }, { id: "recommendation", label: "Recommendation" },
] as const;
export type ReviewTab = typeof REVIEW_TABS[number]["id"] | "exceptions";
export function applicantReviewTabs(hasExceptions: boolean): { id: ReviewTab; label: string }[] {
  return REVIEW_TABS.flatMap(tab => tab.id === "recommendation" && hasExceptions
    ? [{ id: "exceptions" as ReviewTab, label: "Exceptions" }, tab] : [tab]);
}
export type DocumentSelection = { file: string; page: number };

export function resolveEvidenceDocument(evidence: EvidenceItem, documents: OriginalDocument[]): DocumentSelection | null {
  const filename = (value: string) => value.replaceAll("\\", "/").split("/").pop()?.toLowerCase() ?? "";
  const requested = evidence.document ? filename(evidence.document) : "";
  if (!requested) return null;
  const match = documents.find(document => filename(document.file) === requested);
  if (!match) return null;
  const page = Number(evidence.page);
  return { file: match.file, page: Number.isInteger(page) && page > 0 ? page : 1 };
}
