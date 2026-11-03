"use client";

import { useEffect, useState } from "react";
import RequestState from "@/components/RequestState";
import styles from "./recommendation.module.css";
import { type FinalDecision, type ReviewerRecommendation, getRecommendation, submitRecommendation } from "@/lib/eaos-api";
import { decisionLabel, recommendationLabel } from "@/lib/review-state";

const OPTIONS: { value: FinalDecision; title: string; description: string; tone: string }[] = [
  { value: "ACCEPT", title: "Recommend Accept", description: "Strong fit for Riverview. Advance for admission.", tone: styles.accept },
  { value: "WAITLIST", title: "Recommend Waitlist", description: "Qualified, but hold pending class space.", tone: styles.waitlist },
  { value: "DECLINE", title: "Recommend Decline", description: "Does not meet admission criteria this cycle.", tone: styles.decline },
];

function OptionIcon({ value }: { value: FinalDecision }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {value === "ACCEPT" && <path d="m6 12.5 4 4 8-9" />}
      {value === "WAITLIST" && <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l2.5 2" /></>}
      {value === "DECLINE" && <path d="m7 7 10 10M17 7 7 17" />}
    </svg>
  );
}

function formatSavedAt(value: string | null): string | null {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function RecommendationPanel({ appId, applicantName }: { appId: string; applicantName: string | null }) {
  const [saved, setSaved] = useState<ReviewerRecommendation | null>(null);
  const [loadError, setLoadError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [choice, setChoice] = useState<FinalDecision | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [justSaved, setJustSaved] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getRecommendation(appId, controller.signal)
      .then(result => {
        if (controller.signal.aborted) return;
        setSaved(result);
        setChoice(result.recommendation);
      })
      .catch(error => { if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : "Could not load the recommendation."); });
    return () => controller.abort();
  }, [appId, attempt]);

  if (loadError) {
    return <RequestState kind="error" title="Recommendation could not be loaded" description={loadError} onRetry={() => { setLoadError(""); setAttempt(value => value + 1); }} />;
  }
  if (!saved) return <RequestState kind="loading" title="Loading recommendation…" />;

  const locked = Boolean(saved.finalDecision);
  const ineligible = !locked && saved.applicationStatus !== "DOSSIER_READY";
  const disabled = locked || ineligible || saving;
  const dirty = choice !== saved.recommendation;
  const savedAt = formatSavedAt(saved.recommendedAt);
  const savedTone = OPTIONS.find(option => option.value === saved.recommendation)?.tone ?? "";

  function pick(value: FinalDecision) {
    setChoice(value);
    setConfirmed(false);
    setSaveError("");
    setJustSaved(false);
  }

  function discard() {
    if (!saved) return;
    setChoice(saved.recommendation);
    setConfirmed(false);
    setSaveError("");
  }

  async function save() {
    if (!choice || !dirty || !confirmed || disabled) return;
    setSaving(true);
    setSaveError("");
    setJustSaved(false);
    try {
      const result = await submitRecommendation(appId, choice);
      setSaved(result);
      setChoice(result.recommendation);
      setConfirmed(false);
      setJustSaved(true);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "The recommendation could not be saved. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="recommendation-heading" aria-busy={saving}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Reviewer recommendation</p>
          <h2 id="recommendation-heading">What do you recommend{applicantName ? ` for ${applicantName}` : ""}?</h2>
          <p className={styles.subtitle}>Advisory only. The Dean of Admissions reviews your recommendation and records the final decision.</p>
        </div>
        <div className={`${styles.statusChip} ${saved.recommendation ? savedTone : styles.empty}`}>
          <span className={styles.statusDot} aria-hidden="true" />
          <span>
            <strong>{recommendationLabel(saved.recommendation)}</strong>
            <small>{savedAt ? `Saved ${savedAt}` : "Not yet submitted"}</small>
          </span>
        </div>
      </header>

      {locked && <div className={styles.banner} role="status"><strong>Final decision recorded: {decisionLabel(saved.finalDecision)}.</strong> The recommendation is locked and kept for the record.</div>}
      {ineligible && <div className={styles.banner} role="status"><strong>Recommendations open once the dossier is ready.</strong> This applicant is not yet eligible for review.</div>}

      <fieldset className={styles.options} disabled={disabled}>
        <legend className={styles.srOnly}>Recommendation</legend>
        {OPTIONS.map(option => {
          const selected = choice === option.value;
          return (
            <label key={option.value} className={`${styles.option} ${option.tone} ${selected ? styles.selected : ""}`}>
              <input type="radio" name={`recommendation-${appId}`} value={option.value} checked={selected} onChange={() => pick(option.value)} />
              <span className={styles.optionIcon}><OptionIcon value={option.value} /></span>
              <span className={styles.optionText}>
                <strong>{option.title}</strong>
                <span>{option.description}</span>
              </span>
              <span className={styles.check} aria-hidden="true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
              </span>
            </label>
          );
        })}
      </fieldset>

      <label className={`${styles.confirm} ${confirmed ? styles.confirmChecked : ""}`}>
        <input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={disabled || !choice || !dirty} />
        <span className={styles.confirmIcon} aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
        </span>
        <span>
          <strong>I confirm I submitted a confidential recommendation</strong>
          <small>Shared only with the Dean of Admissions for the final decision.</small>
        </span>
      </label>

      {saveError && <div className={styles.errorMessage} role="alert">{saveError}</div>}

      <footer className={styles.footer}>
        <p className={styles.footerNote} role="status">
          {justSaved && !dirty ? <span className={styles.savedNote}>✓ Recommendation saved and shared with the Dean.</span>
            : dirty && choice && !confirmed ? "Tick the confirmation to submit."
            : dirty ? "You have unsaved changes."
              : locked ? "No further changes can be made."
                : "You can revise this until the Dean records a final decision."}
        </p>
        <div className={styles.actions}>
          {dirty && saved.recommendation && <button type="button" className={styles.secondary} onClick={discard} disabled={saving}>Discard changes</button>}
          <button type="button" className={styles.primary} onClick={save} disabled={!choice || !dirty || !confirmed || disabled}>
            {saving ? "Saving…" : saved.recommendation ? "Update recommendation" : "Submit recommendation"}
          </button>
        </div>
      </footer>
    </section>
  );
}
