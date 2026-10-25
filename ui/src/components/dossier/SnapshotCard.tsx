import type { DossierPayload } from "@/lib/types";
import { latestRunCheckState, latestSectionChecks } from "@/lib/review-state";

function StatusDot({ tone }: { tone: "passed" | "failed" | "unknown" }) {
  const color = { passed: "bg-status-pass", failed: "bg-status-fail", unknown: "bg-status-muted" }[tone];
  return <span aria-hidden="true" className={`inline-block h-2 w-2 shrink-0 rounded-full ${color}`} />;
}

export default function SnapshotCard({ payload }: { payload: DossierPayload }) {
  const run = payload.run ?? {};
  const dossier = payload.applicant_dossier;
  const verdict = latestRunCheckState(run);
  const sections = latestSectionChecks(run);
  const policies = Array.isArray(dossier?.policy_assessment) ? dossier.policy_assessment : [];
  const aligned = policies.filter(item => item.alignment === "aligned").length;
  const notApplicable = policies.filter(item => item.alignment === "not_applicable").length;
  const latestLabel = verdict === "passed" ? "Passed" : verdict === "failed" ? "Failed" : "Unknown";
  const savedDate = dossier?.updated_at ?? dossier?.generated_at;
  const dateLabel = (value?: string | null) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : "Unavailable";

  return (
    <section className="rounded-xl border border-card-purple-border bg-card-purple-bg p-4" aria-label="Validation and policy snapshot">
      <h3 className="mb-3 text-sm font-semibold text-card-purple-text">Validation &amp; Policy Snapshot</h3>
      <dl className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <dt className="flex items-center gap-2 text-ink-muted"><StatusDot tone="unknown" />Saved dossier validation</dt>
          <dd className="font-medium text-ink">Unknown</dd>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <dt className="flex items-center gap-2 text-ink-muted"><StatusDot tone={verdict} />Latest run validation</dt>
          <dd className="font-medium text-ink">{latestLabel}</dd>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <dt className="text-ink-muted">Latest run section checks</dt>
          <dd className="font-medium text-ink">{sections.total ? `${sections.passed}/${sections.total} passed` : "Unknown"}</dd>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <dt className="text-ink-muted">Saved policy assessments</dt>
          <dd className="font-medium text-ink">{policies.length ? `${aligned}/${policies.length} aligned` : "Unavailable"}</dd>
        </div>
      </dl>
      <p className="mt-3 text-xs leading-relaxed text-ink-muted">The saved dossier has no recorded link to a validation run. The latest run&apos;s checks do not establish validation of this saved version.</p>
      {notApplicable > 0 && <p className="mt-2 text-xs text-ink-muted">{notApplicable} policy check(s) are not applicable.</p>}
      <p className="mt-2 text-xs text-ink-muted">Saved dossier updated: {dateLabel(savedDate)}<br />Latest stored run: {dateLabel(run.created_at)}{run.id ? ` · Run ${run.id}` : ""}</p>
      <p className="mt-3 text-xs text-ink-muted">Automated checks support human review; they do not prove every generated claim is correct.</p>
    </section>
  );
}
