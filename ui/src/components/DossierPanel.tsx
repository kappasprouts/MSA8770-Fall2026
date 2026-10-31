import type { DossierPayload, EvidenceItem, ProfileSection } from "@/lib/types";
import ApplicantInfoCard from "./dossier/ApplicantInfoCard";
import SnapshotCard from "./dossier/SnapshotCard";
import PolicyChecksCard from "./dossier/PolicyChecksCard";
import EvidenceLinks from "./dossier/EvidenceLinks";
import styles from "./eaos.module.css";

function ProfileValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) return <ul className={styles.profileValues}>{value.map((item, index) => <li key={index}><ProfileValue value={item} /></li>)}</ul>;
  if (value && typeof value === "object") return <dl className={styles.nestedFacts}>{Object.entries(value).map(([key, item]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd><ProfileValue value={item} /></dd></div>)}</dl>;
  return <span>{value === null || value === undefined || value === "" ? "—" : typeof value === "boolean" ? value ? "Yes" : "No" : String(value)}</span>;
}

function Profile({ label, section, open = false, onViewEvidence }: { label: string; section?: ProfileSection; open?: boolean; onViewEvidence: (item: EvidenceItem) => void }) {
  if (!section) return null;
  const details = Object.entries(section).filter(([key, value]) => !["summary", "evidence"].includes(key) && value !== null && value !== undefined && value !== "" && (!Array.isArray(value) || value.length));
  return <details className={styles.dossierSection} open={open}><summary>{label}</summary><div className={styles.sectionBody}>
    {section.summary && <p className={styles.readingText}>{section.summary}</p>}
    {!!details.length && <dl className={styles.profileFacts}>{details.map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd><ProfileValue value={value} /></dd></div>)}</dl>}
    <EvidenceLinks evidence={section.evidence} onView={onViewEvidence} />
  </div></details>;
}

export default function DossierPanel({ payload, onViewEvidence }: { payload: DossierPayload; onViewEvidence: (item: EvidenceItem) => void }) {
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

  return <div className={styles.readingContent}>
    <div className={styles.readingIntro}><h2>Saved applicant dossier</h2><p className={styles.help}>AI-assisted summaries are advisory. Verify claims against the original documents.</p></div>
    <ApplicantInfoCard dossier={dossier} />
    <Profile label="Academic profile" section={dossier.academic_profile} open onViewEvidence={onViewEvidence} />
    <Profile label="Activities and engagement" section={dossier.engagement_profile} onViewEvidence={onViewEvidence} />
    <Profile label="Recommendation letters" section={dossier.recommendation_profile} onViewEvidence={onViewEvidence} />
    <Profile label="Supplemental essay profile" section={dossier.supplemental_essay_profile} onViewEvidence={onViewEvidence} />
    <details className={styles.dossierSection}><summary>Policy checks and validation</summary><div className={styles.sectionBody}><SnapshotCard payload={payload} />{!!dossier.policy_assessment?.length && <PolicyChecksCard items={dossier.policy_assessment} />}</div></details>
    {!!dossier.strengths?.length && <details className={styles.dossierSection}><summary>Key evidence and citations</summary><div className={styles.sectionBody}><ul className={styles.evidenceList}>{dossier.strengths.map((item, index) => <li key={index}><p>{item.strength}</p><EvidenceLinks evidence={item.evidence} onView={onViewEvidence} /></li>)}</ul></div></details>}
    {!!dossier.review_notes?.length && <details className={styles.dossierSection}><summary>Dossier review notes</summary><div className={styles.sectionBody}><ul className={styles.evidenceList}>{dossier.review_notes.map((note, index) => <li key={index}>{note}</li>)}</ul></div></details>}
  </div>;
}
