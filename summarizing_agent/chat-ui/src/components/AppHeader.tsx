import type { ApplicantSummary } from "@/lib/types";
import Logo from "./Logo";

export default function AppHeader({
  applicants,
  selectedAppId,
  onSelect,
  applicantName,
}: {
  applicants: ApplicantSummary[];
  selectedAppId: string;
  onSelect: (appId: string) => void;
  applicantName: string | null;
}) {
  return (
    <header className="flex items-center justify-between border-b border-border bg-panel-header px-5 py-3">
      <div className="flex items-center gap-3">
        <Logo className="h-12 w-12 shrink-0" />

        <div>
          <p className="text-base font-bold leading-tight text-ink">Riverview State University</p>
          <p className="text-xs font-semibold uppercase tracking-wide text-accent">Applicant Review</p>
          <h1 className="text-lg font-bold text-ink">
            {selectedAppId || "No applicant selected"}
            {applicantName && <span className="font-normal text-ink-muted"> &nbsp;|&nbsp; {applicantName}</span>}
          </h1>
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm text-ink-muted">
        Applicant
        <select
          value={selectedAppId}
          onChange={(event) => onSelect(event.target.value)}
          className="rounded-md border border-border bg-surface-alt px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none"
        >
          {applicants.length === 0 && <option value="">None found</option>}
          {applicants.map((applicant) => (
            <option key={applicant.id} value={applicant.id}>
              {applicant.id}
            </option>
          ))}
        </select>
      </label>
    </header>
  );
}
