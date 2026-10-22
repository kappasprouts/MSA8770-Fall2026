import { decisionLabel, statusLabel } from "@/lib/review-state";
import styles from "./eaos.module.css";

export default function StatusBadge({ status, decision = false }: { status: string | null; decision?: boolean }) {
  const tone = decision ? status ? styles.done : styles.pending
    : status === "DOSSIER_READY" ? styles.ready
      : /FAIL|ERROR|STOPPED/.test(status ?? "") ? styles.failed
        : status === "AWAITING_MATERIALS" || status === "INCOMPLETE" ? styles.pending : "";
  return <span className={`${styles.pill} ${tone}`}>{decision ? decisionLabel(status) : statusLabel(status ?? "UNKNOWN")}</span>;
}
