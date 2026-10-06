import type { DossierPayload } from "@/lib/types";

function StatusDot({ tone }: { tone: "pass" | "warn" | "fail" | "muted" }) {
  const color = {
    pass: "bg-status-pass",
    warn: "bg-status-warn",
    fail: "bg-status-fail",
    muted: "bg-status-muted",
  }[tone];

  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export default function SnapshotCard({ payload }: { payload: DossierPayload }) {
  const run = payload.run ?? {};
  const dossier = payload.applicant_dossier;
  const validation = run.validation ?? {};
  const failedOutput = run.failed_output ?? {};

  const completed = Object.keys(failedOutput.completed_sections ?? {}).length;
  const failed = Object.keys(failedOutput.failed_sections ?? {}).length;
  const total = completed + failed;

  const sectionsLabel = dossier ? "Complete" : total ? `${completed}/${total}` : "—";
  const sectionsTone: "pass" | "warn" = dossier || failed === 0 ? "pass" : "warn";

  const policyAssessment = dossier?.policy_assessment ?? [];
  const aligned = policyAssessment.filter((item) => item.alignment === "aligned").length;
  const notAligned = policyAssessment.filter((item) => item.alignment === "not_aligned").length;
  const assessedTotal = policyAssessment.length;

  const policyTone: "pass" | "warn" | "fail" | "muted" = !assessedTotal
    ? "muted"
    : notAligned > 0
      ? "fail"
      : aligned === assessedTotal
        ? "pass"
        : "warn";

  const validationPassed = validation.passed ?? null;

  return (
    <div className="rounded-xl border border-card-purple-border bg-card-purple-bg p-4">
      <h3 className="mb-3 text-sm font-semibold text-card-purple-text">Validation &amp; Policy Snapshot</h3>

      <div className="space-y-2 text-sm">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-ink-muted">
            <StatusDot tone={sectionsTone} /> Validated sections
          </span>
          <span className="font-medium text-ink">{sectionsLabel}</span>
        </div>

        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-ink-muted">
            <StatusDot tone={policyTone} /> Policy alignment
          </span>
          <span className="font-medium text-ink">
            {assessedTotal ? `${aligned}/${assessedTotal} aligned` : "—"}
          </span>
        </div>

        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2 text-ink-muted">
            <StatusDot tone={validationPassed ? "pass" : "fail"} /> Full dossier validation
          </span>
          <span className="font-medium text-ink">
            {validationPassed === null ? "—" : validationPassed ? "Passed" : "Failed"}
          </span>
        </div>
      </div>

      <p className="mt-3 text-xs text-ink-muted">
        Advisory only — this is a factual status summary, not an admission recommendation.
      </p>
    </div>
  );
}
