import type { ApplicantSummary } from "@/lib/types";
import styles from "./eaos.module.css";

export default function AppHeader({ applicants, selectedAppId, onSelect, applicantName, description, disabled, placeholder = "No saved dossiers" }: {
  applicants: ApplicantSummary[];
  selectedAppId: string;
  onSelect: (appId: string) => void;
  applicantName: string | null;
  description?: string;
  disabled?: boolean;
  placeholder?: string;
}) {
  const index = applicants.findIndex(item => item.id === selectedAppId);
  return (
    <section className={styles.applicantHeader} aria-label="Selected applicant">
      <div>
        <h2>{applicantName || selectedAppId || "Select an applicant"}</h2>
        <p className={styles.help}>{description || "Select an applicant to review their saved dossier."}</p>
      </div>
      <div className={styles.applicantSelector}><button type="button" className={styles.secondaryButton} aria-label="Previous applicant" title="Previous applicant" disabled={disabled || index <= 0} onClick={() => onSelect(applicants[index - 1].id)}>←</button><label className={styles.selectorLabel}>
        Applicant
        <select className={styles.select} value={selectedAppId} onChange={event => onSelect(event.target.value)} disabled={disabled}>
          {!applicants.some(applicant => applicant.id === selectedAppId) && <option value={selectedAppId}>{selectedAppId || placeholder}</option>}
          {applicants.map(applicant => <option key={applicant.id} value={applicant.id}>{applicant.id}</option>)}
        </select>
      </label><button type="button" className={styles.secondaryButton} aria-label="Next applicant" title="Next applicant" disabled={disabled || index < 0 || index >= applicants.length - 1} onClick={() => onSelect(applicants[index + 1].id)}>→</button></div>
    </section>
  );
}
