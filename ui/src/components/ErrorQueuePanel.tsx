"use client";

import { useEffect, useMemo, useState } from "react";
import type { ExceptionRecord } from "@/lib/exception-types";
import { exceptionPriorityTone, exceptionSourceLabel, exceptionStatusLabel, formatExceptionDate } from "@/lib/exception-display";
import { requestJson } from "@/lib/http";
import RequestState from "./RequestState";
import WorkspaceIcon from "./WorkspaceIcon";
import styles from "./eaos.module.css";
import details from "./exceptions.module.css";

export default function ErrorQueuePanel({ onViewDetails }: {
  onViewDetails: (exceptionId: string) => void;
}) {
  const [records, setRecords] = useState<ExceptionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("ALL");
  const [severity, setSeverity] = useState("ALL");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    requestJson<{ exceptions: ExceptionRecord[] }>("/api/exceptions", { signal: controller.signal })
      .then(body => { if (!controller.signal.aborted) setRecords(body.exceptions); })
      .catch(reason => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Could not load exceptions.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);

  function refreshQueue() {
    setLoading(true);
    setRecords([]);
    setError("");
    setAttempt(value => value + 1);
  }

  const categories = useMemo(() => [...new Set(records.map(item => item.category))].sort(), [records]);
  const filtered = useMemo(() => records.filter(item => {
    const matchesSearch = [item.applicantId ?? "", item.applicantName, item.category, item.summary,
      item.status, exceptionSourceLabel(item.source), ...item.affectedDocuments, ...item.findings]
      .join(" ").toLowerCase().includes(search.trim().toLowerCase());
    return matchesSearch && (category === "ALL" || item.category === category) && (severity === "ALL" || item.severity === severity);
  }), [records, search, category, severity]);
  const metric = (value: number) => loading || error ? "—" : value;

  return (
    <>
      <section className={`${styles.card} ${details.intro}`} aria-labelledby="triage-heading">
        <WorkspaceIcon name="errors" />
        <div>
          <h2 id="triage-heading">Technical exception triage</h2>
          <p>Investigate ingestion failures, AI validation errors, and unmatched uploads. Missing student materials and application fields remain in application processing.</p>
        </div>
      </section>

      <div className={styles.metrics} aria-label="Exception totals">
        <div className={styles.metric}><small>Open exceptions</small><strong>{metric(records.length)}</strong><p className={styles.help}>IT-actionable system errors</p></div>
        <div className={styles.metric}><small>High priority</small><strong>{metric(records.filter(item => item.severity === "HIGH" || item.severity === "CRITICAL").length)}</strong><p className={styles.help}>Review these first</p></div>
        <div className={styles.metric}><small>AI validation failures</small><strong>{metric(records.filter(item => item.source === "SUMMARIZER").length)}</strong><p className={styles.help}>Summarizer handoffs</p></div>
        <div className={styles.metric}><small>Orphaned uploads</small><strong>{metric(records.filter(item => item.source === "ORPHAN_INTAKE").length)}</strong><p className={styles.help}>Awaiting applicant match</p></div>
      </div>

      <section className={styles.card} aria-labelledby="queue-heading">
        <div className={details.cardHeader}>
          <div>
            <h2 id="queue-heading">Error Queue</h2>
            <p className={styles.help}>Select an exception to review its findings, affected documents, and audit history.</p>
          </div>
          <button type="button" onClick={refreshQueue} className={styles.secondaryButton} disabled={loading}>Refresh queue</button>
        </div>

        <div className={styles.controls}>
          <label className={`${styles.fieldLabel} ${details.searchField}`}>
            Search exceptions
            <input type="search" value={search} onChange={event => setSearch(event.target.value)}
              placeholder="Applicant, issue, or document" className={styles.input} disabled={loading || Boolean(error)} />
          </label>
          <label className={styles.fieldLabel}>
            Issue type
            <select value={category} onChange={event => setCategory(event.target.value)} aria-label="Filter by category" className={styles.select} disabled={loading || Boolean(error)}>
              <option value="ALL">All issue types</option>
              {categories.map(value => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label className={styles.fieldLabel}>
            Priority
            <select value={severity} onChange={event => setSeverity(event.target.value)} aria-label="Filter by priority" className={styles.select} disabled={loading || Boolean(error)}>
              <option value="ALL">All priorities</option>
              {(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const).map(value => <option key={value} value={value}>{exceptionStatusLabel(value)}</option>)}
            </select>
          </label>
        </div>

        {loading ? <RequestState kind="loading" title="Loading exception records…" />
          : error ? <RequestState kind="error" title="The error queue could not be loaded" description={error} onRetry={refreshQueue} />
          : !filtered.length ? <RequestState kind="empty" title={records.length ? "No exceptions match these filters" : "No IT system errors found"}
            description={records.length ? "Try a different search, issue type, or priority." : "There are no technical exceptions to review."} />
          : <div className={styles.tableWrap}>
            <table className={`${styles.table} ${details.queueTable}`}>
              <caption>Showing {filtered.length} of {records.length} exception(s)</caption>
              <thead><tr>
                {["Applicant", "Issue", "Source", "Priority", "Status", "Updated", "Action"].map(label => <th key={label} scope="col">{label}</th>)}
              </tr></thead>
              <tbody>{filtered.map(item => <tr key={item.id}>
                <td><p className={styles.strong}>{item.applicantId ?? "No applicant ID"}</p><p className={styles.muted}>{item.applicantName}</p></td>
                <td><p className={styles.strong}>{item.category}</p><p className={`${styles.muted} ${details.summary}`}>{item.summary}</p></td>
                <td className={styles.muted}>{exceptionSourceLabel(item.source)}</td>
                <td><span className={`${styles.pill} ${styles[exceptionPriorityTone(item.severity)]}`}>{exceptionStatusLabel(item.severity)}</span></td>
                <td><span className={styles.pill}>{exceptionStatusLabel(item.status)}</span></td>
                <td className={`${styles.muted} ${details.timestamp}`}>{formatExceptionDate(item.updatedAt)}</td>
                <td><button type="button" onClick={() => onViewDetails(item.id)} className={styles.button} aria-label={`View details for ${item.applicantId ?? item.applicantName}`}>View Details</button></td>
              </tr>)}</tbody>
            </table>
          </div>}
      </section>
    </>
  );
}
