"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import RequestState from "@/components/RequestState";
import { getOfficerReview, saveOfficerReview } from "@/lib/eaos-api";
import { MAX_RECOMMENDATION_NOTES, RECOMMENDATIONS, recommendationLabel, type OfficerRecommendation, type OfficerReview, type RecommendationState, type ExceptionResolution, validExceptionResolution } from "@/lib/recommendation";
import styles from "./eaos.module.css";

export default function OfficerRecommendationPanel({ appId, onStateChange, onSaved, dossierVersion, exceptionResolution, exceptionSaving = false, onOpenExceptions }: { appId: string; onStateChange?: (state: RecommendationState) => void; onSaved?: () => void; dossierVersion?: { requestId: string; candidateHash: string } | null; exceptionResolution?: ExceptionResolution; exceptionSaving?: boolean; onOpenExceptions?: () => void }) {
  const [saved, setSaved] = useState<OfficerReview | null>(null);
  const [recommendation, setRecommendation] = useState<OfficerRecommendation | "">("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [success, setSuccess] = useState(false);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const saveRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getOfficerReview(appId, controller.signal)
      .then(review => {
        if (controller.signal.aborted) return;
        if (review.appId !== appId) throw new Error("The recommendation did not match the selected applicant.");
        setSaved(review); setRecommendation(review.recommendation || ""); setNotes(review.notes);
      })
      .catch(error => {
        if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : "Could not load the recommendation.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); saveRequest.current?.abort(); };
  }, [appId, attempt]);

  function reload() {
    setLoading(true); setLoadError(""); setSaveError(""); setSuccess(false); setAttempt(value => value + 1);
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!recommendation || !saved?.canEdit || versionMismatch || saving || exceptionSaving || !resolutionReady) return;
    const controller = new AbortController();
    saveRequest.current = controller;
    setSaving(true); setSaveError(""); setSuccess(false);
    try {
      const review = await saveOfficerReview(appId, recommendation, notes, controller.signal, saved.version,
        saved.version?.state === "REVIEW_PENDING" ? exceptionResolution : undefined);
      if (!controller.signal.aborted) { setSaved(review); setSuccess(true); onSaved?.(); }
    } catch (error) {
      if (!controller.signal.aborted) setSaveError(error instanceof Error ? error.message : "Could not save the recommendation.");
    } finally {
      if (!controller.signal.aborted) setSaving(false);
    }
  }

  const pending = saved?.version?.state === "REVIEW_PENDING";
  const versionMismatch = !loading && dossierVersion !== undefined &&
    ((dossierVersion?.requestId ?? null) !== (saved?.version?.requestId ?? null) ||
     (dossierVersion?.candidateHash ?? null) !== (saved?.version?.candidateHash ?? null));
  const resolutionReady = !pending || (validExceptionResolution(exceptionResolution) && (!saved?.version?.requiresEvidenceReview || exceptionResolution.evidenceReviewed));
  const changed = recommendation !== (saved?.recommendation || "") || notes !== (saved?.notes || "") || Boolean(pending && exceptionResolution && (exceptionResolution.reviewer || exceptionResolution.reason || exceptionResolution.confirmed || exceptionResolution.evidenceReviewed));
  useEffect(() => {
    onStateChange?.({ loading, saving: saving || exceptionSaving, dirty: !loading && changed, saved: saved?.recommendation ?? null, canEdit: Boolean(saved?.canEdit && !versionMismatch), error: Boolean(loadError || versionMismatch), applicationStatus: saved?.applicationStatus ?? null });
  }, [loading, saving, exceptionSaving, changed, saved, loadError, versionMismatch, onStateChange]);
  return <section className={`${styles.card} ${styles.recommendationSection}`} aria-labelledby="officer-recommendation-heading" aria-busy={loading || saving || exceptionSaving}>
    <h2 id="officer-recommendation-heading">Officer&apos;s Recommendation</h2>
    <p className={styles.help}>Save your recommendation and reasoning for the final decision reviewer.</p>
    {loading ? <RequestState kind="loading" title="Loading officer recommendation…" />
      : loadError ? <RequestState kind="error" title="Recommendation unavailable" description={loadError} onRetry={reload} />
        : <form onSubmit={save}>
          {versionMismatch && <div className={styles.error} role="alert">The dossier changed after this page loaded. Reload the applicant and review the current version before submitting.<button type="button" className={styles.secondaryButton} onClick={onSaved}>Reload applicant</button></div>}
          {saved?.recommendation && <p className={styles.help}>Saved recommendation: <strong>{recommendationLabel(saved.recommendation)}</strong></p>}
          {saved && !saved.canEdit && <p className={styles.help}>{saved.applicationStatus === "FINAL_DECISION_RECORDED" ? "A final decision has been recorded. The saved recommendation is read-only."
            : saved.version?.fresh === false ? "The registered applicant facts or policies changed. Generate a current dossier before recommending."
            : saved.version && !["REVIEW_PENDING", "PUBLISHED"].includes(saved.version.state) ? saved.version.outcomeReason || "This draft needs correction or regeneration before recommending."
            : "Recommendations can be edited for Dossier ready or Reviewed applications until a final decision is recorded."}</p>}
          <fieldset className={styles.decisionFields} disabled={saving || exceptionSaving || !saved?.canEdit || versionMismatch}>
            {pending && <div className={styles.notice}>
              <p>{resolutionReady ? "Exception resolution prepared. Save your recommendation to record the resolution and recommendation together." : "Complete the resolution in the Exceptions tab before saving your recommendation."}</p>
              <button type="button" className={styles.secondaryButton} onClick={onOpenExceptions}>{resolutionReady ? "Review exception resolution" : "Open Exceptions"}</button>
            </div>}
            {!pending && saved?.version?.reason && <p className={styles.help}>Saved exception resolution by {saved.version.reviewer}: {saved.version.reason}</p>}
            <legend className={styles.fieldLabel}>Recommended outcome</legend>
            <div className={styles.radioRow}>{RECOMMENDATIONS.map(value => <label className={styles.radioLabel} key={value}>
              <input type="radio" name="officer-recommendation" value={value} required checked={recommendation === value} onChange={() => { setRecommendation(value); setSuccess(false); }} />
              {recommendationLabel(value)}
            </label>)}</div>
            <label className={styles.recommendationNotes} htmlFor="officer-recommendation-notes">Comments / notes</label>
            <textarea id="officer-recommendation-notes" className={styles.textarea} rows={5} maxLength={MAX_RECOMMENDATION_NOTES} value={notes} onChange={event => { setNotes(event.target.value); setSuccess(false); }} placeholder="Explain why you recommend this outcome…" aria-describedby="officer-notes-help" />
            <p id="officer-notes-help" className={styles.help}>{notes.length.toLocaleString()} / {MAX_RECOMMENDATION_NOTES.toLocaleString()} characters</p>
          </fieldset>
          {saveError && <div className={styles.error} role="alert">{saveError}<button type="button" className={styles.secondaryButton} onClick={reload}>Reload saved recommendation</button></div>}
          {success && <div className={styles.success} role="status">Recommendation saved. Application marked Reviewed and available on Final Decisions.</div>}
          <div className={styles.actionRow}><button className={styles.button} type="submit" disabled={!saved?.canEdit || versionMismatch || !recommendation || !changed || saving || exceptionSaving || !resolutionReady}>{saving || exceptionSaving ? "Saving…" : pending ? "Save resolution and recommendation" : "Save Recommendation"}</button></div>
        </form>}
  </section>;
}
