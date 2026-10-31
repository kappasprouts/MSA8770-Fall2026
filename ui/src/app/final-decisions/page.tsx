"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import EaosShell from "@/components/EaosShell";
import RequestState from "@/components/RequestState";
import StatusBadge from "@/components/StatusBadge";
import styles from "@/components/eaos.module.css";
import { type ApplicantRow, type FinalDecision, dossierHref, getFinalDecisionData, submitFinalDecision } from "@/lib/eaos-api";
import { type DecisionTotals, decisionLabel } from "@/lib/review-state";
import { recommendationLabel } from "@/lib/recommendation";

export default function FinalDecisionsPage() {
  const [rows, setRows] = useState<ApplicantRow[]>([]);
  const [totals, setTotals] = useState<DecisionTotals | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [success, setSuccess] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [decision, setDecision] = useState<FinalDecision | "">("");
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getFinalDecisionData(controller.signal)
      .then(data => { if (!controller.signal.aborted) { setRows(data.applicants); setTotals(data.totals); } })
      .catch(err => { if (!controller.signal.aborted) setLoadError(err instanceof Error ? err.message : "Could not load the decision queue."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);

  const filtered = useMemo(() => rows.filter(row => `${row.appId} ${row.firstName} ${row.lastName}`.toLowerCase().includes(search.trim().toLowerCase())), [rows, search]);
  const selected = !loading && !loadError ? rows.find(row => row.appId === selectedId) : undefined;
  const metric = (value?: number) => loading || loadError || value === undefined ? "—" : value;

  function refreshQueue() {
    setLoading(true); setRows([]); setTotals(null); setLoadError(""); setDecision(""); setConfirming(false); setAttempt(value => value + 1);
  }
  function chooseApplicant(id: string) {
    setSelectedId(id); setDecision(""); setConfirming(false); setSuccess(""); setSaveError("");
  }
  async function saveDecision() {
    if (!selected || !decision || !confirming || selected.finalDecision || saving) return;
    setSaving(true); setSaveError(""); setSuccess("");
    try {
      await submitFinalDecision(selected.appId, decision);
      setSuccess(`${decisionLabel(decision)} decision recorded for ${[selected.firstName, selected.lastName].filter(Boolean).join(" ") || selected.appId} (${selected.appId}).`);
      setSelectedId(""); refreshQueue();
    } catch (err) { setSaveError(err instanceof Error ? err.message : "The decision could not be saved. Please try again."); }
    finally { setSaving(false); }
  }

  return (
    <EaosShell title="Final Admission Decisions" subtitle="Record the Dean of Admissions' authorized decision after human review." role="Decision recording">
      <section className={styles.metrics} aria-label="Decision counts" aria-busy={loading}>
        <div className={styles.metric}><small>Ready for decision</small><strong>{metric(totals?.awaiting)}</strong></div>
        <div className={styles.metric}><small>Decisions recorded</small><strong>{metric(totals?.recorded)}</strong></div>
        <div className={styles.metric}><small>All applicants</small><strong>{metric(totals?.total)}</strong></div>
      </section>
      <p className={styles.footnote}>Recorded decisions are counted across all applicant records. The queue below contains applicants awaiting a decision.</p>
      {!loading && !loadError && !totals && <RequestState kind="empty" title="System-wide totals are unavailable" description="The queue is available, but this service did not provide complete decision counts." />}
      {success && <div className={styles.success} role="status">{success}</div>}
      <div className={styles.decisionGrid} style={{ marginTop: 20 }}>
        <section className={styles.card} aria-labelledby="decision-queue-heading" aria-busy={loading}>
          <h2 id="decision-queue-heading">Select Applicant</h2>
          <div className={styles.controls}>
            <input className={styles.input} aria-label="Search applicants" placeholder="Search applicant ID or name…" value={search} onChange={event => setSearch(event.target.value)} disabled={loading || saving || Boolean(loadError)} />
            <button className={styles.secondaryButton} type="button" onClick={refreshQueue} disabled={loading || saving}>{loading ? "Loading…" : "Refresh"}</button>
          </div>
          {loading ? <RequestState kind="loading" title="Loading decision queue…" />
            : loadError ? <RequestState kind="error" title="Decision queue could not be loaded" description={loadError} onRetry={refreshQueue} />
              : rows.length === 0 ? <RequestState kind="empty" title="No applicants awaiting a decision" description="Applicants with ready or reviewed dossiers appear here until a final decision is recorded." />
                : filtered.length === 0 ? <RequestState kind="empty" title="No applicants match this search" actionLabel="Clear search" onRetry={() => setSearch("")} />
                  : <div className={styles.tableWrap} role="region" aria-label="Applicants awaiting a final decision" tabIndex={0}>
                    <table className={`${styles.table} ${styles.decisionTable}`}>
                      <caption>{filtered.length} applicant(s) shown</caption>
                      <thead><tr><th scope="col">Applicant</th><th scope="col">Officer recommendation</th><th scope="col">Final decision</th><th scope="col">Action</th></tr></thead>
                      <tbody>{filtered.map(row => <tr key={row.appId} aria-selected={row.appId === selectedId}>
                        <td><div className={styles.strong}>{[row.firstName, row.lastName].filter(Boolean).join(" ") || row.appId}</div><div className={styles.muted}>{row.appId}</div></td>
                        <td>{row.officerRecommendation ? <span className={`${styles.pill} ${styles.done}`}>{recommendationLabel(row.officerRecommendation)}</span> : <span className={styles.muted} aria-label="No officer recommendation recorded">—</span>}</td>
                        <td>{row.finalDecision ? <StatusBadge status={row.finalDecision} decision /> : <span className={styles.muted} aria-label="No final decision recorded">—</span>}</td>
                        <td><button type="button" className={styles.secondaryButton} onClick={() => chooseApplicant(row.appId)} disabled={saving} aria-label={`View decision form for ${row.appId}`}>View</button></td>
                      </tr>)}</tbody>
                    </table>
                  </div>}
        </section>
        <section className={styles.card} aria-labelledby="record-decision-heading" aria-busy={saving}>
          <h2 id="record-decision-heading">Record Dean&apos;s Decision</h2>
          {!selected ? <p className={styles.help}>Select an applicant from the loaded queue to begin.</p> : <>
            <div className={styles.infoLine}><span>Applicant</span><strong>{[selected.firstName, selected.lastName].filter(Boolean).join(" ") || selected.appId}</strong></div>
            <div className={styles.infoLine}><span>Applicant ID</span><strong>{selected.appId}</strong></div>
            <div className={styles.infoLine}><span>Officer recommendation</span><strong>{selected.officerRecommendation ? recommendationLabel(selected.officerRecommendation) : "—"}</strong></div>
            <div className={styles.infoLine}><span>Officer comments / notes</span><p className={styles.notesText}>{selected.officerRecommendationNotes || "—"}</p></div>
            <div className={styles.infoLine}><span>Existing final decision</span><strong>{selected.finalDecision ? decisionLabel(selected.finalDecision) : "—"}</strong></div>
            <Link href={dossierHref(selected.appId)} className={styles.secondaryButton} style={{ marginTop: 16 }}>Review applicant dossier →</Link>
            {selected.finalDecision ? <p className={styles.help}>A final decision is already recorded. An authorized correction workflow is required to change it.</p> : <>
              <fieldset className={styles.decisionFields} disabled={saving}>
                <legend className={styles.fieldLabel}>Dean&apos;s approved final decision</legend>
                <div className={styles.radioRow}>{(["ACCEPT", "WAITLIST", "DECLINE"] as const).map(value => <label className={styles.radioLabel} key={value}>
                  <input type="radio" name="decision" checked={decision === value} onChange={() => { setDecision(value); setConfirming(false); setSaveError(""); }} />
                  {value.charAt(0) + value.slice(1).toLowerCase()}
                </label>)}</div>
                <label className={styles.radioLabel} style={{ marginTop: 16 }}><input type="checkbox" checked={confirming} onChange={event => setConfirming(event.target.checked)} />I confirm this is the Dean&apos;s approved final decision.</label>
              </fieldset>
              <div className={styles.actionRow}><button type="button" className={styles.button} disabled={!decision || !confirming || saving} onClick={saveDecision}>{saving ? "Saving…" : "Submit Final Decision"}</button></div>
            </>}
          </>}
          {saveError && <div className={styles.error} role="alert" style={{ marginTop: 16 }}>{saveError}</div>}
        </section>
      </div>
    </EaosShell>
  );
}
