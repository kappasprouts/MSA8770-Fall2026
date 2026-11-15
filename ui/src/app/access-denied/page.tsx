import Link from "next/link";
import EaosShell from "@/components/EaosShell";
import styles from "@/components/eaos.module.css";

export default function AccessDeniedPage() {
  return <EaosShell title="Access Denied" subtitle="You are not authorized to access this page." role="Access denied">
    <section className={styles.card}>
      <h2>This workspace is restricted to another role.</h2>
      <p className={styles.help}>Return to Home to choose a workspace available to your account. You can also sign out and use a different university account.</p>
      <Link href="/" className={styles.button} style={{ marginTop: 20 }}>Return to Home</Link>
    </section>
  </EaosShell>;
}
