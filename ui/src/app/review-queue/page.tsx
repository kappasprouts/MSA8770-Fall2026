"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import EaosShell from "@/components/EaosShell";
import RequestState from "@/components/RequestState";
import StatusBadge from "@/components/StatusBadge";
import styles from "@/components/eaos.module.css";
import { type ApplicantRow, dossierHref, getReviewQueue } from "@/lib/eaos-api";
import { requestJson } from "@/lib/http";
import { type BatchState, hasReviewableDossier, parseBatchStatus, statusLabel } from "@/lib/review-state";

const PAGE_SIZE = 20;

export default function ReviewQueuePage() {
  const [rows, setRows] = useState<ApplicantRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("ALL");
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [batchAttempt, setBatchAttempt] = useState(0);
  const [batch, setBatch] = useState<BatchState>({ kind: "loading" });
  const ledgerHeading = useRef<HTMLHeadingElement>(null);

  function refreshBatch() { setBatch({ kind: "loading" }); setBatchAttempt(value => value + 1); }
  function refreshQueue() {
    setLoading(true); setRows([]); setError(""); setPage(1); setAttempt(value => value + 1); refreshBatch();
  }

  useEffect(() => {
    const controller = new AbortController();
    requestJson<unknown>("/api/ingestion/batch-status", { signal: controller.signal })
      .then(parseBatchStatus)
      .then(value => { if (!controller.signal.aborted) setBatch(value); })
      .catch(() => { if (!controller.signal.aborted) setBatch({ kind: "unavailable" }); });
    return () => controller.abort();
  }, [batchAttempt]);

  useEffect(() => {
    const controller = new AbortController();
    getReviewQueue(controller.signal)
      .then(data => { if (!controller.signal.aborted) setRows(data); })
      .catch(err => { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load applicants."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);

  const statuses = useMemo(() => [...new Set(rows.map(row => row.applicationStatus))].sort(), [rows]);
  const filtered = useMemo(() => rows.filter(row => {
    const matches = [row.appId, row.firstName, row.lastName, row.intendedMajor ?? ""].join(" ").toLowerCase().includes(search.trim().toLowerCase());
    return matches && (status === "ALL" || row.applicationStatus === status);
  }), [rows, search, status]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageStart = (currentPage - 1) * PAGE_SIZE;
  const pageEnd = Math.min(pageStart + PAGE_SIZE, filtered.length);
  const pageRows = filtered.slice(pageStart, pageEnd);
  const count = (value: string) => rows.filter(row => row.applicationStatus === value).length;
  const metric = (value: number) => loading || error ? "—" : value;

  function changePage(nextPage: number) {
    setPage(Math.max(1, Math.min(nextPage, pageCount)));
    ledgerHeading.current?.focus({ preventScroll: true });
    ledgerHeading.current?.scrollIntoView({ block: "start" });
  }

  return (
    <EaosShell title="Admissions Processing Dashboard" subtitle="Track applications, packet completeness, and dossier availability." role="Application processing">
      <section className={styles.metrics} aria-label="Application counts" aria-busy={loading}>
        <div className={styles.metric}><small>All applicants</small><strong>{metric(rows.length)}</strong></div>
        <div className={styles.metric}><small>Dossier ready</small><strong>{metric(count("DOSSIER_READY"))}</strong></div>
        <div className={styles.metric}><small>Reviewed</small><strong>{metric(count("REVIEWED"))}</strong></div>
        <div className={styles.metric}><small>Final decision recorded</small><strong>{metric(count("FINAL_DECISION_RECORDED"))}</strong></div>
        <div className={styles.metric}><small>Awaiting materials</small><strong>{metric(count("AWAITING_MATERIALS"))}</strong></div>
        <div className={styles.metric}><small>Incomplete</small><strong>{metric(count("INCOMPLETE"))}</strong></div>
      </section>
      <section className={styles.card} aria-labelledby="batch-heading">
        <h2 id="batch-heading">Latest ingestion batch</h2>
        <div role="status">
          {batch.kind === "loading" && <p>Checking batch status…</p>}
          {batch.kind === "unavailable" && <><p className={styles.strong}>Batch status unavailable</p><p className={styles.help}>The ingestion service could not be reached or returned an unreadable status. Applicant records can still be reviewed.</p></>}
          {batch.kind === "none" && <><p className={styles.strong}>No batch recorded in this server session</p><p className={styles.help}>The ingestion service is available but has no saved batch result for its current session.</p></>}
          {batch.kind === "completed" && <><p className={styles.strong}>Batch completed · {new Date(batch.executedAt).toLocaleString()}</p><p className={styles.help}>Affected applicants: {batch.affected ?? "Unavailable"}.</p></>}
          {batch.kind === "other" && <p className={styles.strong}>Batch status: {statusLabel(batch.status)}</p>}
        </div>
        {batch.kind === "unavailable" && <button className={styles.secondaryButton} type="button" onClick={refreshBatch} style={{ marginTop: 12 }}>Retry batch status</button>}
        <p className={styles.footnote}>Dashboard counts cover all applicant records, across batches.</p>
        {!loading && !error && count("READY_FOR_REVIEW") > 0 && <p className={styles.help}>{count("READY_FOR_REVIEW")} application(s) are awaiting dossier generation.</p>}
      </section>
      <section className={styles.card} aria-labelledby="ledger-heading" aria-busy={loading}>
        <h2 id="ledger-heading" ref={ledgerHeading} tabIndex={-1}>Applicant Processing Ledger</h2>
        <div className={styles.controls}>
          <input className={styles.input} aria-label="Search applicants" placeholder="Search by ID, name, or major…" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} disabled={loading || Boolean(error)} />
          <select className={styles.select} aria-label="Filter by status" value={status} onChange={event => { setStatus(event.target.value); setPage(1); }} disabled={loading || Boolean(error)}>
            <option value="ALL">All statuses</option>
            {status !== "ALL" && !statuses.includes(status) && <option value={status}>{statusLabel(status)}</option>}
            {statuses.map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}
          </select>
          <button type="button" className={styles.secondaryButton} onClick={refreshQueue} disabled={loading}>{loading ? "Loading…" : "Refresh"}</button>
        </div>
        {loading ? <RequestState kind="loading" title="Loading applicants…" />
          : error ? <RequestState kind="error" title="Applicant records could not be loaded" description={error} onRetry={refreshQueue} />
            : rows.length === 0 ? <RequestState kind="empty" title="No applicant records yet" description="Applications will appear here after ingestion." />
              : filtered.length === 0 ? <RequestState kind="empty" title="No applicants match these filters" actionLabel="Clear filters" onRetry={() => { setSearch(""); setStatus("ALL"); setPage(1); }} />
                : <><div className={styles.tableWrap} tabIndex={0} role="region" aria-label="Applicant processing ledger">
                  <table className={`${styles.table} ${styles.processingTable}`}>
                    <caption>Showing {pageStart + 1}–{pageEnd} of {filtered.length} applicant(s){filtered.length !== rows.length && ` (filtered from ${rows.length})`}</caption>
                    <thead><tr>{["Applicant ID", "Applicant", "Intended Major", "Application Status", "Final Decision", "Action"].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
                    <tbody>{pageRows.map(row => <tr key={row.appId}>
                      <td className={styles.strong}>{row.appId}</td><td>{[row.firstName, row.lastName].filter(Boolean).join(" ") || "Unavailable"}</td>
                      <td>{row.intendedMajor || "Unavailable"}</td><td><StatusBadge status={row.applicationStatus} /></td><td>{row.finalDecision ? <StatusBadge status={row.finalDecision} decision /> : <span className={styles.muted} aria-label="No final decision recorded">—</span>}</td>
                      <td>{hasReviewableDossier(row.applicationStatus) ? <Link className={styles.secondaryButton} href={dossierHref(row.appId)} aria-label={`Open dossier for ${row.appId}`}>Open dossier →</Link> : <span className={styles.muted} aria-label="Dossier not available">—</span>}</td>
                    </tr>)}</tbody>
                  </table>
                </div>
                  <nav className={styles.pagination} aria-label="Applicant ledger pages">
                    <span className={styles.muted}>20 applicants per page</span>
                    <div className={styles.paginationControls}>
                      <button type="button" className={styles.secondaryButton} disabled={currentPage === 1} onClick={() => changePage(currentPage - 1)}>Previous</button>
                      <span className={styles.muted} role="status" aria-live="polite" aria-atomic="true">Page {currentPage} of {pageCount}</span>
                      <button type="button" className={styles.secondaryButton} disabled={currentPage === pageCount} onClick={() => changePage(currentPage + 1)}>Next</button>
                    </div>
                  </nav>
                </>}
        <p className={styles.footnote}>Dossiers remain available after review and after a final decision is recorded.</p>
      </section>
    </EaosShell>
  );
}
