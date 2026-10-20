'use client';
import { useEffect, useMemo, useState } from 'react';
import EaosShell from '../../components/EaosShell';
import styles from '../../components/eaos.module.css';
import { ApplicantRow, FinalDecision, getFinalDecisionQueue, submitFinalDecision } from '../../lib/eaos-api';

export default function FinalDecisionsPage() {
  const [rows, setRows] = useState<ApplicantRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [decision, setDecision] = useState<FinalDecision | ''>('');
  const [search, setSearch] = useState('');
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    let active = true; setLoading(true); setError('');
    getFinalDecisionQueue().then(data => { if (active) setRows(data); }).catch(err => { if (active) setError(err instanceof Error ? err.message : String(err)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refreshKey]);
  const filtered = useMemo(() => rows.filter(r => `${r.appId} ${r.firstName} ${r.lastName}`.toLowerCase().includes(search.toLowerCase())), [rows, search]);
  const selected = rows.find(r => r.appId === selectedId);
  const undecided = rows.filter(r => !r.finalDecision).length;
  function chooseApplicant(id: string) {
    setSelectedId(id); setDecision(''); setConfirming(false); setSuccess(''); setError('');
  }
  async function saveDecision() {
    if (!selected || !decision || !confirming || selected.finalDecision) return;
    setSaving(true); setError(''); setSuccess('');
    try {
      await submitFinalDecision(selected.appId, decision);
      setSuccess(
  `       ${decision.charAt(0) + decision.slice(1).toLowerCase()} decision recorded for ${selected.firstName} ${selected.lastName} (${selected.appId}).`
            );
      setSelectedId(''); setDecision(''); setConfirming(false); setRefreshKey(k => k + 1);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setSaving(false); }
  }
  return <EaosShell title="Final Admission Decisions" subtitle="Record the Dean of Admissions' authorized decision for each applicant." role="Dean's Admin Assistant">
    <div className={styles.metrics}>
      <div className={styles.metric}><small>Applicants in decision queue</small><strong>{rows.length}</strong></div>
      <div className={styles.metric}><small>Awaiting final decision</small><strong>{undecided}</strong></div>
      <div className={styles.metric}><small>Decision recorded</small><strong>{rows.length - undecided}</strong></div>
    </div>
    {error && <div className={styles.error} role="alert">{error}</div>}
    {success && <div className={styles.success} role="status">{success}</div>}
    <div className={styles.decisionGrid}>
      <section className={styles.card}>
        <h2>Select Applicant</h2>
        <div className={styles.controls}><input className={styles.input} aria-label="Search applicants" placeholder="Search applicant ID or name..." value={search} onChange={e => setSearch(e.target.value)}/><button className={styles.secondaryButton} type="button" onClick={() => setRefreshKey(k => k + 1)}>Refresh</button></div>
        {loading ? <p className={styles.empty}>Loading applicants...</p> : <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Applicant</th><th>Final Decision</th><th>Action</th></tr></thead><tbody>{filtered.map(r => <tr key={r.appId}><td><div className={styles.strong}>{`${r.firstName} ${r.lastName}`.trim() || r.appId}</div><div className={styles.muted}>{r.appId}</div></td><td><span className={`${styles.pill} ${r.finalDecision ? styles.done : styles.pending}`}>{r.finalDecision || 'NOT RECORDED'}</span></td><td><button type="button" className={styles.secondaryButton} onClick={() => chooseApplicant(r.appId)}>View</button></td></tr>)}</tbody></table>{!filtered.length && <p className={styles.empty}>No matching applicants.</p>}</div>}
      </section>
      <section className={styles.card}>
        <h2>Record Dean's Decision</h2>
        {!selected ? <p className={styles.empty}>Select an applicant from the queue to begin.</p> : <>
          <div className={styles.infoLine}><span>Applicant</span><strong>{`${selected.firstName} ${selected.lastName}`.trim() || selected.appId}</strong></div>
          <div className={styles.infoLine}><span>Applicant ID</span><strong>{selected.appId}</strong></div>
          <div className={styles.infoLine}><span>Application Status</span><strong>{selected.applicationStatus.replaceAll('_', ' ')}</strong></div>
          <div className={styles.infoLine}><span>Existing Final Decision</span><strong>{selected.finalDecision || 'Not recorded'}</strong></div>
          {selected.finalDecision ? <p className={styles.help}>This applicant already has a final decision. Changes must use a separate authorized correction workflow; this screen does not overwrite recorded decisions.</p> : <>
            <p className={styles.fieldLabel} style={{marginTop:20}}>Dean's final decision</p>
            <div className={styles.radioRow}>{(['ACCEPT','WAITLIST','DECLINE'] as const).map(v => <label className={styles.radioLabel} key={v}><input type="radio" name="decision" checked={decision === v} onChange={() => {setDecision(v);setConfirming(false);}}/>{v.charAt(0) + v.slice(1).toLowerCase()}</label>)}</div>
            <p className={styles.help}>Please select the final admission decision authorized by the Dean.</p>
            <label className={styles.radioLabel} style={{marginTop:18}}><input type="checkbox" checked={confirming} onChange={e => setConfirming(e.target.checked)}/> I confirm this is the Dean's approved final decision.</label>
            <div className={styles.actionRow}><button type="button" className={styles.button} disabled={!decision || !confirming || saving} onClick={saveDecision}>{saving ? 'Saving...' : 'Submit Final Decision'}</button></div>
          </>}
        </>}
      </section>
    </div>
    <p className={styles.footnote}>Final admission decisions are saved as part of the applicant's admission record.</p>
  </EaosShell>;
}
