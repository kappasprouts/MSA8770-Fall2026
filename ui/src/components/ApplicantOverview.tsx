import type { DossierPayload, EvidenceItem } from "@/lib/types";
import ApplicantInfoCard from "@/components/dossier/ApplicantInfoCard";
import SummaryCard from "@/components/dossier/SummaryCard";
import SnapshotCard from "@/components/dossier/SnapshotCard";
import PolicyChecksCard from "@/components/dossier/PolicyChecksCard";
import EvidenceCard from "@/components/dossier/EvidenceCard";
import styles from "./eaos.module.css";

export default function ApplicantOverview({ payload, onViewEvidence }: { payload: DossierPayload; onViewEvidence: (item: EvidenceItem) => void }) {
  const dossier = payload.applicant_dossier;
  if (!dossier) return <p className={styles.help}>No validated dossier is available yet for this applicant.</p>;

  return <div className="space-y-3">
    <ApplicantInfoCard dossier={dossier} />
    {dossier.holistic_assessment && <SummaryCard text={dossier.holistic_assessment} />}
    <SnapshotCard payload={payload} />
    {!!dossier.policy_assessment?.length && <PolicyChecksCard items={dossier.policy_assessment} />}
    {!!dossier.strengths?.length && <EvidenceCard strengths={dossier.strengths} onViewEvidence={onViewEvidence} />}
  </div>;
}
