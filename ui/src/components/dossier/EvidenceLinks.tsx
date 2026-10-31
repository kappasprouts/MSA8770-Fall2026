import type { EvidenceItem } from "@/lib/types";
import styles from "@/components/eaos.module.css";

export default function EvidenceLinks({ evidence, onView }: { evidence?: EvidenceItem[]; onView: (item: EvidenceItem) => void }) {
  const sources = [...new Map(evidence?.filter(item => item.document).map(item => [`${item.document?.toLowerCase()}|${item.page ?? ""}`, item])).values()];
  if (!sources?.length) return null;
  return <div className={styles.evidenceLinks}>{sources.map((item, index) => <button type="button" className={styles.sourceLink} key={index} onClick={() => onView(item)}>
    {item.document}{item.page ? ` · p. ${item.page}` : ""} ↗
  </button>)}</div>;
}
