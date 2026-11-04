import styles from "./eaos.module.css";

export default function RequestState({ kind, title, description, onRetry, actionLabel = "Try again" }: {
  kind: "loading" | "error" | "empty"; title: string; description?: string; onRetry?: () => void; actionLabel?: string;
}) {
  return (
    <div className={`${styles.feedback} ${kind === "error" ? styles.error : styles.notice}`}
      role={kind === "error" ? "alert" : "status"}>
      <div><p className={styles.feedbackTitle}>{title}</p>{description && <p className={styles.help}>{description}</p>}</div>
      {onRetry && <button type="button" className={styles.secondaryButton} onClick={onRetry}>{actionLabel}</button>}
    </div>
  );
}
