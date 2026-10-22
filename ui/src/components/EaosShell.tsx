"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import styles from "./eaos.module.css";
import Logo from "./Logo";
import WorkspaceIcon from "./WorkspaceIcon";

const navigation = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/review-queue", label: "Processing dashboard", icon: "processing" },
  { href: "/applicant-review", label: "Applicant review", icon: "review" },
  { href: "/final-decisions", label: "Final decisions", icon: "decisions" },
] as const;

export default function EaosShell({ title, subtitle, role, children }: {
  title: string; subtitle: string; role: string; children: ReactNode;
}) {
  const pathname = usePathname();
  return <div className={styles.shell}>
    <a className={styles.skipLink} href="#main-content">Skip to content</a>
    <aside className={styles.sidebar}>
      <Link href="/" className={styles.brand} aria-label="Riverview State University admissions home">
        <Logo className="h-12 w-12 shrink-0" /><span><strong>Riverview State University</strong><small>Admissions workspace</small></span>
      </Link>
      <p className={styles.navLabel}>WORKSPACE</p>
      <nav aria-label="Main navigation" className={styles.navigation}>
        {navigation.map(item => <Link key={item.href} href={item.href} aria-current={pathname === item.href ? "page" : undefined}
          className={`${styles.navLink} ${pathname === item.href ? styles.active : ""}`}>
          <WorkspaceIcon name={item.icon} />{item.label}
        </Link>)}
      </nav>
      <p className={styles.sidebarNote}>Human-led review<br />AI summaries support your review. Final decisions require human approval.</p>
    </aside>
    <div className={styles.main}>
      <header className={styles.topbar}><span>Admissions management</span><span className={styles.role}>{role}</span></header>
      <main id="main-content" tabIndex={-1} className={styles.content}>
        <div className={styles.heading}><h1>{title}</h1><p>{subtitle}</p></div>
        {children}
      </main>
    </div>
  </div>;
}
