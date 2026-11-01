"use client";

import { useRef, useState, type ReactNode } from "react";
import ApplicantOverview from "./ApplicantOverview";
import DossierPanel from "./DossierPanel";
import DocumentsPanel from "./DocumentsPanel";
import OfficerRecommendationPanel from "./OfficerRecommendationPanel";
import ApplicantExceptionsPanel from "./ApplicantExceptionsPanel";
import ChatPanel from "./ChatPanel";
import WorkspaceIcon from "./WorkspaceIcon";
import { resolveEvidenceDocument, type DocumentSelection } from "@/lib/review-workspace";
import { recommendationLabel, type RecommendationState, type ExceptionResolution } from "@/lib/recommendation";
import type { DossierPayload, EvidenceItem, OriginalDocument } from "@/lib/types";
import styles from "./eaos.module.css";

export default function ApplicantReviewWorkspace({ appId, payload, documents, header, recommendation, onRecommendationStateChange, onReviewSaved }: { appId: string; payload: DossierPayload; documents: OriginalDocument[]; header: ReactNode; recommendation: RecommendationState; onRecommendationStateChange: (state: RecommendationState) => void; onReviewSaved?: () => void }) {
  const [selection, setSelection] = useState<DocumentSelection | null>(null);
  const [sourceError, setSourceError] = useState("");
  const [resolution, setResolution] = useState<ExceptionResolution>({ reviewer: "", reason: "", confirmed: false, evidenceReviewed: false });
  const [exceptionSaving, setExceptionSaving] = useState(false);
  const documentsSection = useRef<HTMLElement>(null);
  const exceptionsSection = useRef<HTMLElement>(null);
  const recommendationSection = useRef<HTMLElement>(null);
  const hasExceptions = Boolean(payload.review_checkpoint);

  function goTo(section: HTMLElement | null) {
    section?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    section?.focus({ preventScroll: true });
  }

  function viewEvidence(item: EvidenceItem) {
    const target = resolveEvidenceDocument(item, documents);
    setSourceError(target ? "" : `The cited source ${item.document || "document"} is not listed for this applicant. Choose an available original document below.`);
    if (target) setSelection(target);
    goTo(documentsSection.current);
  }

  const status = recommendation.loading ? "Loading recommendation…" : recommendation.saving ? "Saving review…" : recommendation.error ? "Recommendation unavailable" : recommendation.dirty ? "Unsaved review changes" : recommendation.saved ? `Recommendation: ${recommendationLabel(recommendation.saved)}` : "No recommendation saved";

  return <div className={styles.reviewWorkspace}>
    <div className={styles.reviewHeaderCard}>
      {header}
      <div className={styles.reviewShortcuts} aria-label="Review sections">
        {hasExceptions && <button type="button" className={`${styles.secondaryButton} ${styles.exceptionShortcut}`} onClick={() => goTo(exceptionsSection.current)}><WorkspaceIcon name="errors" />Exceptions</button>}
        <button type="button" className={styles.button} onClick={() => goTo(recommendationSection.current)}>{recommendation.saved || !recommendation.canEdit ? "View recommendation" : "Write recommendation"}</button>
      </div>
    </div>

    {hasExceptions && <div className={styles.reviewAlert} role="status"><strong>This draft has exceptions to review.</strong><span>Check the original documents, then resolve the exceptions before saving a recommendation.</span><button type="button" className={styles.secondaryButton} onClick={() => goTo(exceptionsSection.current)}>Review exceptions</button></div>}

    <div className={styles.reviewComparison}>
      <section className={styles.reviewColumn} aria-labelledby="review-dossier-heading">
        <div className={styles.reviewColumnHeading}><h2 id="review-dossier-heading">Applicant Dossier</h2><span>↕ Scroll</span></div>
        <div className={styles.reviewColumnBody}>
          <ApplicantOverview payload={payload} onViewEvidence={viewEvidence} />
          <details className={styles.fullDossier}><summary>Full dossier details</summary><DossierPanel payload={payload} onViewEvidence={viewEvidence} /></details>
        </div>
      </section>
      <section ref={documentsSection} className={`${styles.reviewColumn} ${styles.reviewDocuments}`} aria-labelledby="review-documents-heading" tabIndex={-1}>
        <div className={styles.reviewColumnHeading}><h2 id="review-documents-heading">Original Documents</h2><span>↕ Scroll</span></div>
        <div className={styles.reviewColumnBody}>
          {sourceError && <div className={styles.notice} role="status">{sourceError}</div>}
          <DocumentsPanel appId={appId} documents={documents} selection={selection} onSelect={value => { setSelection(value); setSourceError(""); }} />
        </div>
      </section>
    </div>

    {!hasExceptions && <section className={styles.chatSection} aria-label="Applicant Q&A"><ChatPanel appId={appId} /></section>}

    {payload.review_checkpoint && <section ref={exceptionsSection} className={styles.reviewActionSection} aria-label="Applicant exceptions" tabIndex={-1}>
      <ApplicantExceptionsPanel appId={appId} checkpoint={payload.review_checkpoint} dossier={payload.applicant_dossier}
        resolution={resolution} onChange={setResolution} canEdit={recommendation.canEdit && !recommendation.error}
        busy={recommendation.saving || exceptionSaving} onBusyChange={setExceptionSaving}
        onOpenDocuments={() => goTo(documentsSection.current)} onContinue={() => goTo(recommendationSection.current)} onSaved={onReviewSaved} />
    </section>}

    <section ref={recommendationSection} className={styles.reviewActionSection} aria-label="Officer recommendation" tabIndex={-1}>
      <OfficerRecommendationPanel appId={appId} onStateChange={onRecommendationStateChange} onSaved={onReviewSaved}
        exceptionResolution={hasExceptions ? resolution : undefined} exceptionSaving={exceptionSaving} onOpenExceptions={() => goTo(exceptionsSection.current)}
        dossierVersion={payload.review_checkpoint ? { requestId: payload.review_checkpoint.request_id, candidateHash: payload.review_checkpoint.candidate_hash }
          : payload.publication ? { requestId: payload.publication.request_id, candidateHash: payload.publication.candidate_hash } : null} />
    </section>
    <div className={styles.reviewFooter}><span className={styles.help} role="status" aria-live="polite">{status}</span></div>
  </div>;
}
