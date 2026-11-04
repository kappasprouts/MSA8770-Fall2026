"use client";

import { useEffect, useState } from "react";
import type {
  ExceptionRecord,
  ExceptionSeverity,
} from "@/lib/exception-types";

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

function sourceLabel(
  source: ExceptionRecord["source"],
): string {
  if (source === "ORPHAN_INTAKE") {
    return "Orphan intake";
  }

  if (source === "SUMMARIZER") {
    return "Summarizing agent";
  }

  return "Ingestion gate";
}

function severityClasses(
  severity: ExceptionSeverity,
): string {
  const classes: Record<ExceptionSeverity, string> = {
    CRITICAL: "border-red-200 bg-red-50 text-red-700",
    HIGH: "border-orange-200 bg-orange-50 text-orange-700",
    MEDIUM: "border-amber-200 bg-amber-50 text-amber-700",
    LOW: "border-blue-200 bg-blue-50 text-blue-700",
  };

  return classes[severity];
}

function DetailFact({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 py-3 text-sm">
      <dt className="text-ink-muted">{label}</dt>

      <dd className="max-w-[65%] text-right font-semibold text-ink">
        {value}
      </dd>
    </div>
  );
}

export default function ApplicantExceptionDetails({
  exceptionId,
  onBack,
  onOpenApplicant,
}: {
  exceptionId: string;
  onBack: () => void;
  onOpenApplicant: (appId: string) => void;
}) {
  const [record, setRecord] =
    useState<ExceptionRecord | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    
    fetch("/api/exceptions", {
      cache: "no-store",
    })
      .then(async (response) => {
        const body = await response.json();

        if (!response.ok) {
          throw new Error(
            body.error ??
              "Failed to load the exception record.",
          );
        }

        return body as {
          exceptions: ExceptionRecord[];
        };
      })
      .then((body) => {
        if (!active) return;

        const selectedRecord = body.exceptions.find(
          (item) => item.id === exceptionId,
        );

        if (!selectedRecord) {
          throw new Error(
            `Exception "${exceptionId}" could not be found.`,
          );
        }

        setRecord(selectedRecord);
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
  }, [exceptionId]);

  if (loading) {
    return (
      <section className="rounded-2xl border border-border bg-white px-6 py-20 text-center shadow-sm">
        <p className="text-sm font-semibold text-ink">
          Loading exception details…
        </p>

        <p className="mt-1 text-sm text-ink-muted">
          Retrieving the findings and audit history.
        </p>
      </section>
    );
  }

  if (error || !record) {
    return (
      <section className="space-y-4">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-2 text-sm font-semibold text-accent hover:underline"
        >
          <span aria-hidden="true">←</span>
          Back to Error Queue
        </button>

        <div
          className="rounded-2xl border border-red-200 bg-red-50 px-6 py-8 text-red-700"
          role="alert"
        >
          <h1 className="text-lg font-semibold">
            Exception details unavailable
          </h1>

          <p className="mt-2 text-sm">
            {error ||
              "The selected exception could not be loaded."}
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-5">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 text-sm font-semibold text-accent transition hover:underline"
      >
        <span aria-hidden="true">←</span>
        Back to Error Queue
      </button>

      <div className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-border bg-white px-6 py-5 shadow-sm">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">
            Technical exception record
          </p>

          <h1 className="mt-1 text-2xl font-semibold text-ink">
            Applicant Exception Details
          </h1>

          <p className="mt-2 text-sm text-ink-muted">
            {record.applicantId ?? "Unmatched record"}
            {" · "}
            {record.applicantName}
          </p>
        </div>

        <span
          className={`rounded-full border px-3 py-1.5 text-xs font-bold ${severityClasses(
            record.severity,
          )}`}
        >
          {record.severity} priority
        </span>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.6fr)]">
        <div className="space-y-5">
          <section className="rounded-2xl border border-border bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">
                  Exception category
                </p>

                <h2 className="mt-1 text-xl font-semibold text-ink">
                  {record.category}
                </h2>
              </div>

              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700">
                {displayStatus(record.status)}
              </span>
            </div>

            <div className="mt-5 rounded-xl border border-border bg-surface-alt p-4">
              <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-ink-muted">
                Why the application was routed
              </h3>

              <p className="mt-2 text-sm leading-6 text-ink">
                {record.summary}
              </p>
            </div>
          </section>

          <section className="rounded-2xl border border-border bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-ink">
              Validation findings
            </h2>

            <p className="mt-1 text-sm text-ink-muted">
              Findings generated by the component that
              stopped the application.
            </p>

            {record.findings.length > 0 ? (
              <ul className="mt-4 space-y-3">
                {record.findings.map(
                  (finding, index) => (
                    <li
                      key={`${finding}-${index}`}
                      className="flex gap-3 rounded-xl border border-border bg-surface-alt px-4 py-3"
                    >
                      <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-100 text-xs font-bold text-accent">
                        {index + 1}
                      </span>

                      <span className="text-sm leading-6 text-ink">
                        {finding}
                      </span>
                    </li>
                  ),
                )}
              </ul>
            ) : (
              <p className="mt-4 rounded-xl border border-border bg-surface-alt px-4 py-4 text-sm text-ink-muted">
                No detailed validation findings were
                provided.
              </p>
            )}
          </section>

          <section className="rounded-2xl border border-border bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-ink">
              Affected documents
            </h2>

            <p className="mt-1 text-sm text-ink-muted">
              Documents associated with the exception.
            </p>

            {record.affectedDocuments.length > 0 ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {record.affectedDocuments.map(
                  (document) => (
                    <span
                      key={document}
                      className="rounded-lg border border-border bg-surface-alt px-3 py-2 text-xs font-medium text-ink"
                    >
                      {document}
                    </span>
                  ),
                )}
              </div>
            ) : (
              <p className="mt-4 rounded-xl border border-border bg-surface-alt px-4 py-4 text-sm text-ink-muted">
                No specific document was associated with
                this exception.
              </p>
            )}
          </section>

          <section className="rounded-2xl border border-border bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-ink">
              Audit history
            </h2>

            <p className="mt-1 text-sm text-ink-muted">
              Recent events recorded for this exception.
            </p>

            {record.auditHistory.length > 0 ? (
              <ol className="mt-5 space-y-4 border-l-2 border-violet-100 pl-5">
                {record.auditHistory.map(
                  (event, index) => (
                    <li
                      key={`${event.action}-${event.createdAt}-${index}`}
                      className="relative"
                    >
                      <span className="absolute -left-[25px] top-1 h-3 w-3 rounded-full border-2 border-white bg-accent" />

                      <p className="text-sm font-semibold text-ink">
                        {displayStatus(event.action)}
                      </p>

                      <p className="mt-1 text-xs text-ink-muted">
                        {event.actor}
                        {" · "}
                        {formatDate(event.createdAt)}
                      </p>
                    </li>
                  ),
                )}
              </ol>
            ) : (
              <p className="mt-4 rounded-xl border border-border bg-surface-alt px-4 py-4 text-sm text-ink-muted">
                No audit events are available.
              </p>
            )}
          </section>
        </div>

        <aside className="space-y-5">
          <section className="rounded-2xl border border-border bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-ink">
              Exception summary
            </h2>

            <dl className="mt-4 divide-y divide-border rounded-xl border border-border">
              <DetailFact
                label="Applicant"
                value={
                  record.applicantId ??
                  "Unmatched record"
                }
              />

              <DetailFact
                label="Applicant name"
                value={
                  record.applicantName ||
                  "Not provided"
                }
              />

              <DetailFact
                label="Workflow status"
                value={displayStatus(record.status)}
              />

              <DetailFact
                label="Detected by"
                value={sourceLabel(record.source)}
              />

              <DetailFact
                label="Priority"
                value={record.severity}
              />

              <DetailFact
                label="Last event"
                value={formatDate(record.updatedAt)}
              />

              <DetailFact
                label="Follow-up owner"
                value="Ingestion / IT team"
              />
            </dl>
          </section>

          <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5">
            <h2 className="font-semibold text-blue-950">
              Recommended technical action
            </h2>

            <p className="mt-2 text-sm leading-6 text-blue-800">
              Review the validation findings and affected
              documents. Correct the underlying source,
              matching, or model-output problem before
              rerunning the affected workflow step.
            </p>
          </section>

          {record.hasDossier &&
            record.applicantId && (
              <button
                type="button"
                onClick={() =>
                  onOpenApplicant(
                    record.applicantId as string,
                  )
                }
                className="w-full rounded-xl bg-[#6d28d9] px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-[#5b21b6]"
              >
                Open available applicant dossier
              </button>
            )}

          <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
            <h2 className="font-semibold text-amber-950">
              Human review required
            </h2>

            <p className="mt-2 text-xs leading-5 text-amber-800">
              This screen does not automatically change
              applicant records or rerun the pipeline.
              Technical staff must verify the correction,
              preserve the audit trail, and initiate the
              appropriate retry or handoff.
            </p>
          </section>
        </aside>
      </div>
    </section>
  );
}