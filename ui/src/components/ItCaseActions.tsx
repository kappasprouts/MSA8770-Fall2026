"use client";
import { useEffect, useRef, useState } from "react";
import type { ExceptionRecord } from "@/lib/exception-types";
import type { ItAction } from "@/lib/it-actions";
import { requestJson } from "@/lib/http";
import styles from "./eaos.module.css";
import details from "./exceptions.module.css";

export default function ItCaseActions({ record, onRefresh }: { record: ExceptionRecord; onRefresh: () => void }) {
  const [actor,setActor]=useState("");
  const [note,setNote]=useState("");
  const [owner,setOwner]=useState("");
  const [action,setAction]=useState<ItAction | "">("");
  const [confirmed,setConfirmed]=useState(false);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const submitted=useRef<{url:string;body:string} | null>(null);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return ()=>{alive.current=false;};},[]);
  const closed=["RESOLVED","SUPERSEDED"].includes(record.caseState ?? "OPEN");
  const busy=record.retryJob && ["QUEUED","RUNNING","NEEDS_RECHECK"].includes(record.retryJob.state);
  const canRetry=record.active!==false && record.retryAllowed && record.workerAvailable && !busy;
  async function submit(recover=false) {
    if (saving) return;
    if (!recover) {
      if (!action || !actor.trim() || !note.trim() || !record.fingerprint) return;
      submitted.current={url:`/api/exceptions/${encodeURIComponent(record.caseId ? `case-${record.caseId}` : record.id)}`,
        body:JSON.stringify({commandId:crypto.randomUUID(),fingerprint:record.fingerprint,revision:record.revision ?? 0,
          actor,note,action,owner,confirmed})};
    }
    if (!submitted.current) return;
    setSaving(true);setError("");
    try {
      await requestJson(submitted.current.url,{method:"PUT",headers:{"Content-Type":"application/json"},body:submitted.current.body});
      if (alive.current) { submitted.current=null;onRefresh(); }
    } catch (err) { if (alive.current) setError(err instanceof Error ? err.message : "Outcome unconfirmed. Reload saved state."); }
    finally { if (alive.current) setSaving(false); }
  }
  return <section className={`${styles.card} ${details.actionCard}`} aria-labelledby="it-case-actions-heading">
    <h2 id="it-case-actions-heading">Manage technical issue</h2>
    <p className={styles.help}>Case: {record.caseState || "OPEN"} · Owner: {record.owner || "Unassigned"}. Identity is simulated.</p>
    {record.active===false && <p className={styles.help}>This failure version is no longer detected. Recheck the receiving system before closing it.</p>}
    {record.retryJob && <div className={styles.notice} role="status"><strong>Retry: {record.retryJob.state}</strong>
      <p className={styles.help}>{String(record.retryJob.result?.message || (record.retryJob.state==="QUEUED" ? "Saved request; waiting for a worker. This is not a successful retry yet." : "Reload saved state to check progress."))}</p>
      <button type="button" className={styles.secondaryButton} onClick={onRefresh} disabled={saving}>Reload saved state</button></div>}
    {!!record.actions?.length && <details open><summary>Saved investigation notes</summary><ul>{record.actions.map((event,i)=><li key={i}>
      <strong>{event.action} · {event.actor}</strong><p style={{whiteSpace:"pre-wrap"}}>{event.note}</p><small>{new Date(event.createdAt).toLocaleString()}</small></li>)}</ul></details>}
    {record.resolutionEvidence && <details><summary>Verified outcome / last retry result</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify(record.resolutionEvidence,null,2)}</pre></details>}
    {!closed && <fieldset className={`${styles.decisionFields} ${details.actionFields}`} disabled={saving || Boolean(error)}>
      <legend>Save an IT action</legend>
      <label className={details.actionField}>Staff name (simulated)<input className={`${styles.input} ${details.actionControl}`} value={actor} maxLength={200} onChange={e=>setActor(e.target.value)} /></label>
      <label className={details.actionField}>Action<select className={`${styles.select} ${details.actionControl}`} value={action} onChange={e=>{setAction(e.target.value as ItAction);setConfirmed(false);}}>
        <option value="">Choose an action</option><option value="CLAIM">Claim investigation</option><option value="NOTE">Add investigation note</option>
        <option value="HANDOFF">Assign follow-up owner</option><option value="REQUEST_RETRY" disabled={!canRetry}>Request processing retry</option>
        <option value="VERIFY_RESOLVED">Recheck receiving system / verify resolution</option></select></label>
      {action==="HANDOFF" && <label className={details.actionField}>Follow-up owner<input className={`${styles.input} ${details.actionControl}`} maxLength={200} value={owner} onChange={e=>setOwner(e.target.value)} /></label>}
      <label className={details.actionField}>Investigation / correction notes<textarea className={`${styles.textarea} ${details.actionControl}`} value={note} maxLength={10000} onChange={e=>setNote(e.target.value)} /></label>
      {["REQUEST_RETRY","VERIFY_RESOLVED"].includes(action) && <label className={details.actionConfirmation}><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)} />I confirm this action for the displayed applicant and failure version.</label>}
      <div className={details.actionGuidance}><p className={styles.help}>{record.source==="ORPHAN_INTAKE" ? "Unmatched uploads need a verified applicant match by intake staff. Use notes and a handoff; this form does not attach a file to an applicant."
        : record.workerAvailable ? "A retry reruns only this applicant's affected processing step. Normal validation and admissions controls still apply."
        : "Processing retries are unavailable until a worker supporting this step is running. You can still investigate, assign follow-up, and verify an external correction."}</p>
      <p className={styles.help}>A case closes only after the receiving system confirms a correction. A note or queued retry cannot clear the failure.</p></div>
      <button type="button" className={`${styles.button} ${details.actionSubmit}`} onClick={()=>submit()} disabled={!action || !actor.trim() || !note.trim() || (action==="HANDOFF" && !owner.trim()) ||
        (["REQUEST_RETRY","VERIFY_RESOLVED"].includes(action) && !confirmed) || (action==="REQUEST_RETRY" && !canRetry)}>{saving ? "Saving…" : "Save IT action"}</button>
    </fieldset>}
    {error && <div className={styles.error} role="alert">{error}<div className={styles.actionRow}>
      <button type="button" className={styles.secondaryButton} disabled={saving} onClick={onRefresh}>Reload saved case</button>
      <button type="button" className={styles.secondaryButton} disabled={saving} onClick={()=>submit(true)}>Recover previous submission</button>
    </div></div>}
  </section>;
}
