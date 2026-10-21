
'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import EaosShell from '../../components/EaosShell';
import styles from '../../components/eaos.module.css';
import {
  ApplicantRow,
  dossierHref,
  getReviewQueue,
} from '../../lib/eaos-api';

function badgeClass(status: string): string {
  switch (status.toUpperCase()) {
    case 'DOSSIER_READY':
      return `${styles.pill} ${styles.ready}`;

    case 'AWAITING_MATERIALS':
    case 'PENDING':
      return `${styles.pill} ${styles.pending}`;

    default:
      return styles.pill;
  }
}

export default function ReviewQueuePage() {
  const [rows, setRows] = useState<ApplicantRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('ALL');
  const [refreshKey, setRefreshKey] = useState(0);

  const [processingDate, setProcessingDate] = useState('');
  const [affectedCount, setAffectedCount] = useState<number | null>(null);
  const [batchMessage, setBatchMessage] = useState('');

  function refreshQueue() {
    setLoading(true);
    setError('');
    setRefreshKey(k => k + 1);
  }

  useEffect(() => {
    let active = true;

    async function loadBatchStatus() {
      try {
        const response = await fetch('/api/ingestion/batch-status', {
          cache: 'no-store',
        });

        if (!response.ok) {
          throw new Error('Batch status unavailable');
        }

        const data = await response.json();

        if (!active) return;

        if (data.status === 'COMPLETED' && data.executed_at) {
          const date = new Date(data.executed_at);

          if (Number.isNaN(date.getTime())) {
            throw new Error('Invalid batch timestamp');
          }

          setProcessingDate(
            date.toLocaleString('en-US', {
              weekday: 'long',
              month: 'long',
              day: 'numeric',
              year: 'numeric',
              hour: 'numeric',
              minute: '2-digit',
            })
          );

          setAffectedCount(
            Array.isArray(data.affected_ids)
              ? data.affected_ids.length
              : null
          );

          setBatchMessage('');
        } else {
          setProcessingDate('');
          setAffectedCount(null);
          setBatchMessage('No batch execution recorded in this server session.');
        }
      } catch {
        if (active) {
          setProcessingDate('');
          setAffectedCount(null);
          setBatchMessage('Batch status is currently unavailable.');
        }
      }
    }

    loadBatchStatus();

    return () => {
      active = false;
    };
  }, [refreshKey]);

  useEffect(() => {
    let active = true;

    getReviewQueue()
      .then(data => {
        if (active) {
          setRows(data);
        }
      })
      .catch(err => {
        if (active) {
          setError(
            err instanceof Error ? err.message : String(err)
          );
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [refreshKey]);

  // Dashboard statistics from all PostgreSQL applicants.
  const dossierCount = rows.filter(
    r => r.applicationStatus === 'DOSSIER_READY'
  ).length;

  const awaitingCount = rows.filter(
    r => r.applicationStatus === 'AWAITING_MATERIALS'
  ).length;

  const incompleteCount = rows.filter(
    r => r.applicationStatus === 'INCOMPLETE'
  ).length;

  const intermediateCount = rows.filter(
    r => r.applicationStatus === 'READY_FOR_REVIEW'
  ).length;

  // Applicant table search and status filters.
  const statuses = useMemo(
    () =>
      Array.from(
        new Set(rows.map(r => r.applicationStatus))
      ).sort(),
    [rows]
  );

  const filtered = useMemo(
    () =>
      rows.filter(r => {
        const match = [
          r.appId,
          r.firstName,
          r.lastName,
          r.intendedMajor || '',
        ]
          .join(' ')
          .toLowerCase()
          .includes(search.trim().toLowerCase());

        return (
          match &&
          (status === 'ALL' ||
            r.applicationStatus === status)
        );
      }),
    [rows, search, status]
  );

  return (
    <EaosShell
      title="Admissions Processing Dashboard"
      subtitle="Overnight ingestion and applicant processing results."
      role="Admissions Officer"
    >
      <section className={styles.card}>

        <h2>
          {processingDate
            ? `Last ingestion batch completed on ${processingDate}`
            : 'Last ingestion batch: No execution recorded'}
        </h2>

        <p className={styles.footnote}>
          {batchMessage ||
            `Affected applicant IDs in latest batch: ${affectedCount ?? '—'}.`}
            {' '}Dashboard statistics reflect current PostgreSQL applicant
            records, not exclusively the latest batch.
        </p>

        <div className={styles.metrics}>
          <div className={styles.metric}>
            <small>
              Total number of applications processed
              2026–2027
            </small>
            <strong>
              {loading || error ? '—' : rows.length}
            </strong>
          </div>

          <div className={styles.metric}>
            <small>Dossier Ready</small>
            <strong>
              {loading || error ? '—' : dossierCount}
            </strong>
          </div>

          <div className={styles.metric}>
            <small>Awaiting Materials</small>
            <strong>
              {loading || error ? '—' : awaitingCount}
            </strong>
          </div>

          <div className={styles.metric}>
            <small>Incomplete</small>
            <strong>
              {loading || error ? '—' : incompleteCount}
            </strong>
          </div>
        </div>

        {!loading && !error && intermediateCount > 0 && (
          <p className={styles.footnote}>
            {intermediateCount} application(s) remain in
            READY_FOR_REVIEW, an intermediate pipeline
            status awaiting dossier generation.
          </p>
        )}
      </section>

      <section className={styles.card}>
        <h2>Applicant Processing Ledger</h2>

        <div className={styles.controls}>
          <input
            className={styles.input}
            aria-label="Search applicants"
            placeholder="Search by ID, name, or major..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />

          <select
            className={styles.select}
            aria-label="Filter by status"
            value={status}
            onChange={e => setStatus(e.target.value)}
          >
            <option value="ALL">All statuses</option>

            {statuses.map(s => (
              <option value={s} key={s}>
                {s.replaceAll('_', ' ')}
              </option>
            ))}
          </select>

          <button
            type="button"
            className={styles.secondaryButton}
            onClick={refreshQueue}
          >
            Refresh
          </button>
        </div>

        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        {loading ? (
          <p className={styles.empty}>
            Loading applicants...
          </p>
        ) : (
          !error && (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Applicant ID</th>
                    <th>Applicant</th>
                    <th>Intended Major</th>
                    <th>Application Status</th>
                    <th>Final Decision</th>
                    <th>Action</th>
                  </tr>
                </thead>

                <tbody>
                  {filtered.map(r => (
                    <tr key={r.appId}>
                      <td className={styles.strong}>
                        {r.appId}
                      </td>

                      <td>
                        {`${r.firstName} ${r.lastName}`.trim() ||
                          '—'}
                      </td>

                      <td>
                        {r.intendedMajor || '—'}
                      </td>

                      {/* Application Status */}
                      <td>
                        <span className={badgeClass(r.applicationStatus)}>
                          {r.applicationStatus.replaceAll('_', ' ')}
                        </span>
                      </td>

                      <td>
                        {r.finalDecision ? (
                          <span className={`${styles.pill} ${styles.done}`}>
                            {r.finalDecision === 'WAITLIST'
                                ? 'WAITLISTED'
                            : r.finalDecision === 'ACCEPT'
                                ? 'ACCEPTED'
                                : 'DECLINED'}
                          </span>
                              ) : (
                          <span className={`${styles.pill} ${styles.pending}`}>
                              NOT DECIDED
                          </span>
                          )}
                      </td>

                      <td>
                        {r.applicationStatus ===
                        'DOSSIER_READY' ? (
                          <Link
                            className={
                              styles.secondaryButton
                            }
                            href={dossierHref(r.appId)}
                          >
                            Open dossier →
                          </Link>
                        ) : (
                          <span>—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {filtered.length === 0 && (
                <p className={styles.empty}>
                  No applicants match these filters.
                </p>
              )}
            </div>
          )
        )}

        <p className={styles.footnote}>
          Applicant records are retrieved from PostgreSQL
          through the Next.js API. Dossier links are
          available for applicants whose dossiers have
          been generated.
        </p>
      </section>
    </EaosShell>
  );
}
