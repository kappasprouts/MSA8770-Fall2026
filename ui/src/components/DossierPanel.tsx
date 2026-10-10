import type { DossierPayload } from "@/lib/types";
import ApplicantInfoCard from "./dossier/ApplicantInfoCard";
import SummaryCard from "./dossier/SummaryCard";
import SnapshotCard from "./dossier/SnapshotCard";
import PolicyChecksCard from "./dossier/PolicyChecksCard";
import EvidenceCard from "./dossier/EvidenceCard";

export default function DossierPanel({ payload }: { payload: DossierPayload }) {
  const dossier = payload.applicant_dossier;

  if (!dossier) {
    return (
      <div className="flex h-full flex-col rounded-xl border border-border bg-surface">
        <div className="border-b border-border bg-panel-header px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Applicant Dossier</h2>
        </div>
        <div className="p-4 text-sm text-ink-muted">
          No validated dossier is available yet for this applicant.
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border bg-panel-header px-4 py-3">
        <h2 className="text-sm font-semibold text-ink">Applicant Dossier</h2>
        <span className="text-xs text-ink-muted">↕ Scroll</span>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        <ApplicantInfoCard dossier={dossier} />

        {dossier.holistic_assessment && <SummaryCard text={dossier.holistic_assessment} />}

        <SnapshotCard payload={payload} />

        {dossier.policy_assessment && dossier.policy_assessment.length > 0 && (
          <PolicyChecksCard items={dossier.policy_assessment} />
        )}

        {dossier.strengths && dossier.strengths.length > 0 && (
          <EvidenceCard strengths={dossier.strengths} />
        )}
      </div>
    </div>
  );
}
