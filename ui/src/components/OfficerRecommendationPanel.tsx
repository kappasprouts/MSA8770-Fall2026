"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import RequestState from "@/components/RequestState";
import { getOfficerReview, saveOfficerReview } from "@/lib/eaos-api";
import { MAX_RECOMMENDATION_NOTES, RECOMMENDATIONS, recommendationLabel, type OfficerRecommendation, type OfficerReview } from "@/lib/recommendation";
import styles from "./eaos.module.css";

export default function OfficerRecommendationPanel({ appId }: { appId: string }) {
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
    if (!recommendation || !saved?.canEdit || saving) return;
    const controller = new AbortController();
    saveRequest.current = controller;
    setSaving(true); setSaveError(""); setSuccess(false);
    try {
      const review = await saveOfficerReview(appId, recommendation, notes, controller.signal);
      if (!controller.signal.aborted) { setSaved(review); setSuccess(true); }
    } catch (error) {
      if (!controller.signal.aborted) setSaveError(error instanceof Error ? error.message : "Could not save the recommendation.");
    } finally {
      if (!controller.signal.aborted) setSaving(false);
    }
  }

  const changed = recommendation !== (saved?.recommendation || "") || notes !== (saved?.notes || "");
  return <section className={`${styles.card} ${styles.recommendationSection}`} aria-labelledby="officer-recommendation-heading" aria-busy={loading || saving}>
    <h2 id="officer-recommendation-heading">Officer&apos;s Recommendation</h2>
    <p className={styles.help}>Save your recommendation and reasoning for the final decision reviewer.</p>
    {loading ? <RequestState kind="loading" title="Loading officer recommendation…" />
      : loadError ? <RequestState kind="error" title="Recommendation unavailable" description={loadError} onRetry={reload} />
        : <form onSubmit={save}>
          {saved?.recommendation && <p className={styles.help}>Saved recommendation: <strong>{recommendationLabel(saved.recommendation)}</strong></p>}
          {saved && !saved.canEdit && <p className={styles.help}>Recommendations can be edited when the dossier is ready and no final decision has been recorded.</p>}
          <fieldset className={styles.decisionFields} disabled={saving || !saved?.canEdit}>
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
          {success && <div className={styles.success} role="status">Recommendation saved. It is now available on Final Decisions.</div>}
          <div className={styles.actionRow}><button className={styles.button} type="submit" disabled={!saved?.canEdit || !recommendation || !changed || saving}>{saving ? "Saving…" : "Save Recommendation"}</button></div>
        </form>}
  </section>;
}
