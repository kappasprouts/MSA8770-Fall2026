"use client";

import { useEffect, useRef, useState } from "react";
import type { ApplicantDossier, DossierPayload } from "@/lib/types";
import { validExceptionResolution, type ExceptionResolution } from "@/lib/recommendation";
import { requestJson } from "@/lib/http";
import styles from "./eaos.module.css";
import fields from "./exceptions.module.css";

export default function ApplicantExceptionsPanel({ appId, checkpoint, dossier, resolution, onChange, canEdit, busy,
  onBusyChange, onOpenDocuments, onContinue, onSaved }: {
  appId: string; checkpoint: NonNullable<DossierPayload["review_checkpoint"]>; dossier?: ApplicantDossier;
  resolution: ExceptionResolution; onChange: (value: ExceptionResolution) => void; canEdit: boolean; busy: boolean;
  onBusyChange: (value: boolean) => void; onOpenDocuments: () => void; onContinue: () => void; onSaved?: () => void;
}) {
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  const pending = checkpoint.state === "REVIEW_PENDING";
  const ready = validExceptionResolution(resolution) && (!checkpoint.requires_evidence_review || resolution.evidenceReviewed);
  function change(value: Partial<ExceptionResolution>) { onChange({ ...resolution, ...value }); }
  async function withhold() {
    if (!pending || !canEdit || busy || !resolution.reviewer.trim() || !resolution.reason.trim() || !resolution.confirmed) return;
    const controller = new AbortController(); request.current = controller;
    onBusyChange(true); setError("");
    try {
      await requestJson(`/api/dossier-reviews/${encodeURIComponent(checkpoint.request_id)}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ candidateHash: checkpoint.candidate_hash, action: "PUBLISH_ADVISORY_DOSSIER",
          decision: "REJECT", reviewer: resolution.reviewer, reason: resolution.reason,
          confirmed: resolution.confirmed, evidenceReviewed: resolution.evidenceReviewed }),
      });
      if (!controller.signal.aborted) onSaved?.();
    } catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Outcome unconfirmed. Reload saved state before retrying."); }
    finally { if (!controller.signal.aborted) onBusyChange(false); }
  }
  return <section className={styles.card} aria-labelledby="applicant-exceptions-heading">
    <h2 id="applicant-exceptions-heading">Applicant exceptions</h2>
    <p className={styles.help}>{pending ? "Check the flagged sources and prepare your resolution here." : "This draft needs correction before use."}</p>
    <div className={styles.notice}>
      <ul>{(checkpoint.reasons?.length ? checkpoint.reasons : ["This saved draft requires a human check."]).map(reason => <li key={reason}>{reason}</li>)}</ul>
      {!!dossier?.review_notes?.length && <ul>{dossier.review_notes.map((note, i) => <li key={i}>{typeof note === "string" ? note : [note.section, note.note].filter(Boolean).join(": ")}</li>)}</ul>}
      {checkpoint.outcome_reason && <p>{checkpoint.outcome_reason}</p>}
      <p className={styles.help}>Unpublished draft · An unanswered or expired request never authorizes use.</p>
      <button type="button" className={styles.secondaryButton} onClick={onOpenDocuments}>Inspect original documents</button>
    </div>
    <details><summary>Draft version and deadline</summary><p className={styles.help}>{appId} · {checkpoint.candidate_hash}</p>
      <p className={styles.help}>Review deadline: {new Date(checkpoint.expires_at).toLocaleString()}</p></details>
    {pending && <fieldset className={`${styles.decisionFields} ${fields.actionFields}`} disabled={!canEdit || busy}>
      <legend>Exception resolution</legend>
      <label className={fields.actionField}>Reviewer name (simulated)<input className={`${styles.input} ${fields.actionControl}`} maxLength={200} value={resolution.reviewer} onChange={e => change({ reviewer: e.target.value })} /></label>
      <label className={fields.actionField}>Resolution / correction needed<textarea className={`${styles.textarea} ${fields.actionControl}`} maxLength={10000} value={resolution.reason} onChange={e => change({ reason: e.target.value, confirmed: false })} placeholder="Explain which source you checked and how the issue was resolved…" /></label>
      {checkpoint.requires_evidence_review && <label className={fields.actionConfirmation}><input type="checkbox" checked={resolution.evidenceReviewed} onChange={e => change({ evidenceReviewed: e.target.checked })} />I verified the flagged evidence against the original documents.</label>}
      <label className={fields.actionConfirmation}><input type="checkbox" checked={resolution.confirmed} onChange={e => change({ confirmed: e.target.checked })} />I confirm the resolution or correction request for this dossier version.</label>
      <p className={styles.help}>Your resolution is a draft until you save the recommendation. Both are saved together; continuing does not publish or approve anything.</p>
      <div className={styles.actionRow}>
        <button type="button" className={styles.secondaryButton} disabled={!resolution.reviewer.trim() || !resolution.reason.trim() || !resolution.confirmed} onClick={withhold}>Needs correction — withhold draft</button>
        <button type="button" className={styles.button} disabled={!ready} onClick={onContinue}>Continue to recommendation</button>
      </div>
      <p className={styles.help}>Withholding a draft does not reject the applicant and saves no admissions recommendation.</p>
    </fieldset>}
    {error && <div className={styles.error} role="alert">{error}<button type="button" className={styles.secondaryButton} onClick={onSaved}>Reload saved applicant</button></div>}
  </section>;
}
