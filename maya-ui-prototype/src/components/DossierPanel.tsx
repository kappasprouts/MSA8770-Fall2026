import type { DossierPayload } from "@/lib/types";
import ApplicantInfoCard from "./dossier/ApplicantInfoCard";
import SummaryCard from "./dossier/SummaryCard";
import SnapshotCard from "./dossier/SnapshotCard";
import EvidenceCard from "./dossier/EvidenceCard";

export default function DossierPanel({ payload, showValidation = true }: { payload: DossierPayload; showValidation?: boolean }) {
  const dossier = payload.applicant_dossier;

  if (!dossier) {
    return (
      <div className="rounded-xl border border-border bg-surface p-5">
        <div className="text-sm text-ink-muted">
          No validated dossier is available yet for this applicant.
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(310px,.72fr)_minmax(0,1.28fr)]">
      <div className="space-y-5">
        <ApplicantInfoCard dossier={dossier} />
        {showValidation ? <SnapshotCard payload={payload} /> : <ReviewAttentionCard payload={payload} />}
      </div>

      <div className="space-y-5">
        {dossier.holistic_assessment && <SummaryCard text={dossier.holistic_assessment} />}

        <div className="grid gap-4 md:grid-cols-2">
          <ProfileSummary title="Academic profile" section={dossier.academic_profile} />
          <ProfileSummary title="Engagement profile" section={dossier.engagement_profile} />
          <ProfileSummary title="Recommendations" section={dossier.recommendation_profile} />
          <ProfileSummary title="University supplement" section={dossier.supplemental_essay_profile} />
        </div>

        {dossier.strengths && dossier.strengths.length > 0 && <EvidenceCard strengths={dossier.strengths} />}
      </div>
    </div>
  );
}

function ReviewAttentionCard({ payload }: { payload: DossierPayload }) {
  const validationPassed = payload.run?.validation?.passed;
  const reviewNotes = payload.applicant_dossier?.review_notes ?? [];

  return (
    <div className={`rounded-xl border p-5 ${validationPassed ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
      <p className={`text-sm font-semibold ${validationPassed ? "text-emerald-800" : "text-amber-900"}`}>
        {validationPassed ? "Application is ready for officer review" : "Officer attention is needed"}
      </p>
      <p className={`mt-2 text-sm leading-6 ${validationPassed ? "text-emerald-700" : "text-amber-800"}`}>
        {validationPassed
          ? "The available summaries passed automated checks. Confirm the supporting documents before recording an action."
          : "One or more AI-generated sections could not be fully verified. Use the source documents and Officer Q&A before recording an action."}
      </p>
      {reviewNotes.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-muted">
          {reviewNotes.slice(0, 3).map((note, index) => <li key={`${note}-${index}`}>{note}</li>)}
        </ul>
      )}
    </div>
  );
}

function ProfileSummary({ title, section }: { title: string; section: Record<string, unknown> | undefined }) {
  if (!section) return null;
  const classification = typeof section.classification === "string" ? section.classification : null;
  const summary = typeof section.summary === "string" ? section.summary : "No narrative summary was generated.";

  return (
    <article className="rounded-xl border border-border bg-white p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {classification && (
          <span className="rounded-full bg-violet-100 px-2.5 py-1 text-[11px] font-semibold text-violet-700">
            {classification}
          </span>
        )}
      </div>
      <p className="mt-3 text-sm leading-6 text-ink-muted">{summary}</p>
    </article>
  );
}
