import type { ApplicantSummary } from "@/lib/types";
import styles from "./eaos.module.css";

export default function AppHeader({ applicants, selectedAppId, onSelect, applicantName, disabled, placeholder = "No saved dossiers" }: {
  applicants: ApplicantSummary[];
  selectedAppId: string;
  onSelect: (appId: string) => void;
  applicantName: string | null;
  disabled?: boolean;
  placeholder?: string;
}) {
  return (
    <section className={`${styles.card} ${styles.applicantHeader}`} aria-label="Selected applicant">
      <div>
        <p className={styles.eyebrow}>Applicant dossier</p>
        <h2>{selectedAppId || "Select an applicant"}{applicantName && <span className={styles.applicantName}> · {applicantName}</span>}</h2>
        <p className={styles.help}>Original documents and AI-assisted summaries for human review.</p>
      </div>
      <label className={styles.selectorLabel}>
        Applicant
        <select className={styles.select} value={selectedAppId} onChange={event => onSelect(event.target.value)} disabled={disabled}>
          {!applicants.some(applicant => applicant.id === selectedAppId) && <option value={selectedAppId}>{selectedAppId || placeholder}</option>}
          {applicants.map(applicant => <option key={applicant.id} value={applicant.id}>{applicant.id}</option>)}
        </select>
      </label>
    </section>
  );
}
