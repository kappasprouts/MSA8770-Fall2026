"use client";

import { useEffect, useMemo, useState } from "react";
import type { ExceptionRecord, ExceptionSeverity } from "@/lib/exception-types";

function formatDate(value: string | null): string {
  if (!value) return "Timestamp unavailable";

  const date = new Date(value);

  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
}

function displayStatus(value: string): string {
  return value.replaceAll("_", " ");
}

function sourceLabel(source: ExceptionRecord["source"]): string {
  if (source === "ORPHAN_INTAKE") return "Orphan intake";
  if (source === "SUMMARIZER") return "Summarizing agent";
  return "Ingestion gate";
}

function severityClasses(severity: ExceptionSeverity): string {
  const classes: Record<ExceptionSeverity, string> = {
    CRITICAL: "border-red-200 bg-red-50 text-red-700",
    HIGH: "border-orange-200 bg-orange-50 text-orange-700",
    MEDIUM: "border-amber-200 bg-amber-50 text-amber-700",
    LOW: "border-blue-200 bg-blue-50 text-blue-700",
  };

  return classes[severity];
}

function MetricCard({
  label,
  value,
  detail,
  tone = "default",
}: {
  label: string;
  value: number | string;
  detail: string;
  tone?: "default" | "alert" | "critical";
}) {
  const toneClasses =
    tone === "critical"
      ? "border-red-200 bg-red-50"
      : tone === "alert"
        ? "border-amber-200 bg-amber-50"
        : "border-border bg-white";

  return (
    <div className={`rounded-xl border px-4 py-3 shadow-sm ${toneClasses}`}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
        {label}
      </p>

      <p className="mt-1 text-2xl font-bold text-ink">{value}</p>

      <p className="mt-0.5 text-xs text-ink-muted">{detail}</p>
    </div>
  );
}

export default function ErrorQueuePanel({
  onViewDetails,
}: {
  onViewDetails: (exceptionId: string) => void;
}) {
  const [records, setRecords] = useState<ExceptionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("ALL");
  const [severity, setSeverity] = useState("ALL");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;

    fetch("/api/exceptions", { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json();

        if (!response.ok) {
          throw new Error(body.error ?? "Failed to load exceptions.");
        }

        return body as { exceptions: ExceptionRecord[] };
      })
      .then((body) => {
        if (!active) return;

        setRecords(body.exceptions);
        setError("");
      })
      .catch((reason) => {
        if (!active) return;

        setError(
          reason instanceof Error
            ? reason.message
            : String(reason),
        );
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

  const categories = useMemo(
    () =>
      Array.from(
        new Set(records.map((item) => item.category)),
      ).sort(),
    [records],
  );

  const filtered = useMemo(
    () =>
      records.filter((item) => {
        const matchesSearch = [
          item.applicantId ?? "",
          item.applicantName,
          item.category,
          item.summary,
          item.status,
          sourceLabel(item.source),
        ]
          .join(" ")
          .toLowerCase()
          .includes(search.trim().toLowerCase());

        const matchesCategory =
          category === "ALL" || item.category === category;

        const matchesSeverity =
          severity === "ALL" || item.severity === severity;

        return (
          matchesSearch &&
          matchesCategory &&
          matchesSeverity
        );
      }),
    [records, search, category, severity],
  );

  const highPriority = records.filter(
    (item) =>
      item.severity === "HIGH" ||
      item.severity === "CRITICAL",
  ).length;

  const summarizerCount = records.filter(
    (item) => item.source === "SUMMARIZER",
  ).length;

  const orphanCount = records.filter(
    (item) => item.source === "ORPHAN_INTAKE",
  ).length;

  function refreshQueue() {
    setLoading(true);
    setError("");
    setRefreshKey((value) => value + 1);
  }

  return (
    <section className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-violet-200 bg-violet-50 px-5 py-4">
        <div className="flex gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-accent shadow-sm">
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              aria-hidden="true"
            >
              <path d="M12 3 2.5 20h19L12 3Z" />
              <path d="M12 9v4M12 17h.01" />
            </svg>
          </span>

          <div>
            <p className="text-sm font-semibold text-violet-950">
              Technical exception triage
            </p>

            <p className="mt-1 max-w-4xl text-sm leading-6 text-violet-800">
              Investigate backend ingestion failures, AI validation errors, and unmatched storage records. Missing documents or application fields are handled by the student-facing workflow, not IT.
            </p>
          </div>
        </div>

        <span className="rounded-full border border-violet-200 bg-white px-3 py-1 text-xs font-semibold text-violet-700">
          IT support workflow
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard
          label="Open exceptions"
          value={loading || error ? "—" : records.length}
          detail="IT-actionable system errors"
          tone="alert"
        />

        <MetricCard
          label="High priority"
          value={loading || error ? "—" : highPriority}
          detail="Review these first"
          tone="critical"
        />

        <MetricCard
          label="AI validation failures"
          value={loading || error ? "—" : summarizerCount}
          detail="Summarizer handoffs"
        />

        <MetricCard
          label="Orphaned uploads"
          value={loading || error ? "—" : orphanCount}
          detail="Awaiting applicant match"
        />
      </div>

      {error && (
        <div
          className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          role="alert"
        >
          <p className="font-semibold">
            The error queue could not be loaded.
          </p>

          <p className="mt-1">{error}</p>

          <button
            type="button"
            onClick={refreshQueue}
            className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-2 text-xs font-semibold text-red-700 transition hover:bg-red-100"
          >
            Try again
          </button>
        </div>
      )}

      <section className="overflow-hidden rounded-2xl border border-border bg-white shadow-sm">
        <div className="border-b border-border px-5 py-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">
                Pipeline operations
              </p>

              <h2 className="mt-1 text-lg font-semibold text-ink">
                Error Queue
              </h2>

              <p className="mt-1 text-sm text-ink-muted">
                Select an exception to view its findings, affected
                documents, and audit history.
              </p>
            </div>

            <button
              type="button"
              onClick={refreshQueue}
              className="rounded-lg border border-border bg-white px-3 py-2 text-sm font-semibold text-ink transition hover:border-accent hover:text-accent"
            >
              Refresh queue
            </button>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(220px,1fr)_190px_150px]">
            <label>
              <span className="sr-only">
                Search exceptions
              </span>

              <input
                value={search}
                onChange={(event) =>
                  setSearch(event.target.value)
                }
                placeholder="Search applicant, issue, or document..."
                className="w-full rounded-lg border border-border bg-surface-alt px-3 py-2.5 text-sm text-ink outline-none placeholder:text-ink-muted focus:border-accent focus:ring-2 focus:ring-violet-100"
              />
            </label>

            <select
              value={category}
              onChange={(event) =>
                setCategory(event.target.value)
              }
              aria-label="Filter by category"
              className="rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-ink outline-none focus:border-accent"
            >
              <option value="ALL">All issue types</option>

              {categories.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>

            <select
              value={severity}
              onChange={(event) =>
                setSeverity(event.target.value)
              }
              aria-label="Filter by priority"
              className="rounded-lg border border-border bg-white px-3 py-2.5 text-sm text-ink outline-none focus:border-accent"
            >
              <option value="ALL">All priorities</option>

              {(
                [
                  "CRITICAL",
                  "HIGH",
                  "MEDIUM",
                  "LOW",
                ] as const
              ).map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
        </div>

        {loading ? (
          <p className="px-5 py-16 text-center text-sm text-ink-muted">
            Loading exception records…
          </p>
        ) : !error ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] border-collapse text-left text-sm">
              <thead className="bg-surface-alt text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
                <tr>
                  <th className="px-5 py-3">Applicant</th>
                  <th className="px-4 py-3">Issue</th>
                  <th className="px-4 py-3">Source</th>
                  <th className="px-4 py-3">Priority</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Updated</th>
                  <th className="px-5 py-3 text-right">
                    Action
                  </th>
                </tr>
              </thead>

              <tbody className="divide-y divide-border">
                {filtered.map((item) => (
                  <tr
                    key={item.id}
                    className="bg-white transition hover:bg-violet-50/60"
                  >
                    <td className="px-5 py-4">
                      <p className="font-semibold text-ink">
                        {item.applicantId ??
                          "No applicant ID"}
                      </p>

                      <p className="mt-0.5 text-xs text-ink-muted">
                        {item.applicantName}
                      </p>
                    </td>

                    <td className="px-4 py-4">
                      <p className="font-medium text-ink">
                        {item.category}
                      </p>

                      <p className="mt-0.5 max-w-[280px] truncate text-xs text-ink-muted">
                        {item.summary}
                      </p>
                    </td>

                    <td className="px-4 py-4 text-xs font-medium text-ink-muted">
                      {sourceLabel(item.source)}
                    </td>

                    <td className="px-4 py-4">
                      <span
                        className={`inline-flex rounded-full border px-2.5 py-1 text-[11px] font-bold ${severityClasses(
                          item.severity,
                        )}`}
                      >
                        {item.severity}
                      </span>
                    </td>

                    <td className="px-4 py-4">
                      <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-700">
                        {displayStatus(item.status)}
                      </span>
                    </td>

                    <td className="px-4 py-4 text-xs text-ink-muted">
                      {formatDate(item.updatedAt)}
                    </td>

                    <td className="px-5 py-4 text-right">
                      <button
                        type="button"
                        onClick={() =>
                          onViewDetails(item.id)
                        }
                        className="rounded-lg bg-[#6d28d9] px-3 py-2 text-xs font-semibold text-white transition hover:bg-[#5b21b6]"
                      >
                        View Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {!filtered.length && (
              <div className="px-5 py-14 text-center">
                <p className="font-semibold text-ink">
                  No IT system errors found
                </p>

                <p className="mt-1 text-sm text-ink-muted">
                  No exception records match the current
                  search and filters.
                </p>
              </div>
            )}
          </div>
        ) : null}
      </section>
    </section>
  );
}