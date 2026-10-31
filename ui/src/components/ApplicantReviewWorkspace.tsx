"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import ApplicantOverview from "./ApplicantOverview";
import DossierPanel from "./DossierPanel";
import DocumentsPanel from "./DocumentsPanel";
import OfficerRecommendationPanel from "./OfficerRecommendationPanel";
import ChatPanel from "./ChatPanel";
import { REVIEW_TABS, resolveEvidenceDocument, type DocumentSelection, type ReviewTab } from "@/lib/review-workspace";
import { recommendationLabel, type RecommendationState } from "@/lib/recommendation";
import type { DossierPayload, EvidenceItem, OriginalDocument } from "@/lib/types";
import styles from "./eaos.module.css";

export default function ApplicantReviewWorkspace({ appId, payload, documents, header, recommendation, onRecommendationStateChange }: { appId: string; payload: DossierPayload; documents: OriginalDocument[]; header: ReactNode; recommendation: RecommendationState; onRecommendationStateChange: (state: RecommendationState) => void }) {
  const [tab, setTab] = useState<ReviewTab>("overview");
  const [selection, setSelection] = useState<DocumentSelection | null>(null);
  const [documentsVisited, setDocumentsVisited] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [qaOpen, setQaOpen] = useState(false);
  const [qaVisited, setQaVisited] = useState(false);
  const tabs = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (qaOpen && !dialog.current?.open) dialog.current?.showModal();
    if (!qaOpen && dialog.current?.open) dialog.current.close();
  }, [qaOpen]);

  function chooseTab(value: ReviewTab, focus = false) {
    setTab(value);
    if (value === "documents") setDocumentsVisited(true);
    if (focus) tabs.current?.querySelector<HTMLButtonElement>(`#review-tab-${value}`)?.focus();
    tabs.current?.ownerDocument.defaultView?.scrollTo({ top: 0 });
  }
  function tabKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === "ArrowRight" ? (index + 1) % REVIEW_TABS.length : event.key === "ArrowLeft" ? (index + REVIEW_TABS.length - 1) % REVIEW_TABS.length : event.key === "Home" ? 0 : event.key === "End" ? REVIEW_TABS.length - 1 : null;
    if (next !== null) { event.preventDefault(); chooseTab(REVIEW_TABS[next].id, true); }
  }
  function viewEvidence(item: EvidenceItem) {
    const target = resolveEvidenceDocument(item, documents);
    setSourceError(target ? "" : `The cited source ${item.document || "document"} is not listed for this applicant. Choose an available original document below.`);
    if (target) setSelection(target);
    chooseTab("documents", true);
  }
  const status = recommendation.loading ? "Loading recommendation…" : recommendation.saving ? "Saving recommendation…" : recommendation.error ? "Recommendation unavailable" : recommendation.dirty ? "Unsaved recommendation" : recommendation.saved ? `Recommendation: ${recommendationLabel(recommendation.saved)}` : "No recommendation saved";
  return <div className={styles.reviewWorkspace}>
    <div className={styles.reviewContext}>
      <div className={styles.reviewIdentity}>{header}<button type="button" className={styles.secondaryButton} onClick={() => { setQaVisited(true); setQaOpen(true); }}>Ask Q&amp;A</button></div>
      <div className={styles.reviewTabs} ref={tabs} role="tablist" aria-label="Applicant review sections">{REVIEW_TABS.map((item, index) => <button key={item.id} id={`review-tab-${item.id}`} type="button" role="tab" aria-selected={tab === item.id} aria-controls={`review-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} className={styles.reviewTab} onKeyDown={event => tabKey(event, index)} onClick={() => chooseTab(item.id)}>{item.label}</button>)}</div>
    </div>
    <div className={styles.reviewPanels}>
      <section id="review-panel-overview" role="tabpanel" aria-labelledby="review-tab-overview" hidden={tab !== "overview"}><ApplicantOverview payload={payload} onViewEvidence={viewEvidence} onReadDossier={() => chooseTab("dossier", true)} /></section>
      <section id="review-panel-dossier" role="tabpanel" aria-labelledby="review-tab-dossier" hidden={tab !== "dossier"}><DossierPanel payload={payload} onViewEvidence={viewEvidence} /></section>
      <section id="review-panel-documents" role="tabpanel" aria-labelledby="review-tab-documents" hidden={tab !== "documents"}>{sourceError && <div className={styles.notice} role="status">{sourceError}</div>}{documentsVisited && <DocumentsPanel appId={appId} documents={documents} selection={selection} onSelect={value => { setSelection(value); setSourceError(""); }} />}</section>
      <section id="review-panel-recommendation" role="tabpanel" aria-labelledby="review-tab-recommendation" hidden={tab !== "recommendation"}><OfficerRecommendationPanel appId={appId} onStateChange={onRecommendationStateChange} /></section>
    </div>
    <div className={styles.reviewFooter}><span className={styles.help} role="status" aria-live="polite">{status}</span>{tab !== "recommendation" && <button type="button" className={styles.button} onClick={() => chooseTab("recommendation", true)}>{recommendation.saved || !recommendation.canEdit ? "View recommendation" : "Write recommendation"}</button>}</div>
    <dialog ref={dialog} className={styles.qaDialog} aria-labelledby="review-qa-heading" onClose={() => setQaOpen(false)}>
      <div className={styles.qaHeading}><div><h2 id="review-qa-heading">Applicant Q&amp;A</h2><p className={styles.help}>{appId} · Answers use this applicant&apos;s saved dossier.</p></div><button type="button" className={styles.secondaryButton} onClick={() => setQaOpen(false)}>Close</button></div>
      <div className={styles.qaConversation}>{qaVisited && <ChatPanel appId={appId} />}</div>
    </dialog>
  </div>;
}
