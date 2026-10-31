import type { DossierPayload, EvidenceItem } from "@/lib/types";
import SnapshotCard from "@/components/dossier/SnapshotCard";
import EvidenceLinks from "@/components/dossier/EvidenceLinks";
import styles from "./eaos.module.css";

export default function ApplicantOverview({ payload, onViewEvidence, onReadDossier }: { payload: DossierPayload; onViewEvidence: (item: EvidenceItem) => void; onReadDossier: () => void }) {
  const dossier = payload.applicant_dossier;
  const facts = (dossier?.academic_profile?.document_facts ?? {}) as Record<string, unknown>;
  const value = (key: string) => facts[key] === null || facts[key] === undefined || facts[key] === "" ? "—" : String(facts[key]);
  return <div className={styles.readingContent}>
    <dl className={styles.overviewFacts}><div><dt>Unweighted GPA</dt><dd>{value("unweighted_gpa")}</dd></div><div><dt>Weighted GPA</dt><dd>{value("weighted_gpa")}</dd></div><div><dt>SAT superscore</dt><dd>{value("sat_superscore")}</dd></div></dl>
    <section className={styles.card} aria-labelledby="overview-summary-heading"><h2 id="overview-summary-heading">Applicant overview</h2><p className={styles.readingText}>{dossier?.holistic_assessment || "No holistic summary is available in the saved dossier."}</p><div className={styles.actionRow}><button type="button" className={styles.secondaryButton} onClick={onReadDossier}>Read full dossier →</button></div></section>
    {!!dossier?.strengths?.length && <section className={styles.card} aria-labelledby="overview-evidence-heading"><h2 id="overview-evidence-heading">Key evidence</h2><ul className={styles.evidenceList}>{dossier.strengths.slice(0, 3).map((item, index) => <li key={index}><p>{item.strength}</p><EvidenceLinks evidence={item.evidence} onView={onViewEvidence} /></li>)}</ul></section>}
    <details className={styles.dossierSection}><summary>Validation and policy snapshot</summary><div className={styles.sectionBody}><SnapshotCard payload={payload} /></div></details>
  </div>;
}
