'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import styles from './eaos.module.css';
import Logo from './Logo';

export default function EaosShell({ title, subtitle, role, children }: { title: string; subtitle: string; role: string; children: ReactNode }) {
  const pathname = usePathname();
  return <div className={styles.shell}>
    <aside className={styles.sidebar}>
      <div className={styles.brand}><Logo className="h-12 w-12 shrink-0" /><span><strong>Riverview State University</strong><small>Applicant Review · EAOS</small></span></div>
      <div className={styles.navLabel}>WORKSPACE</div>
      <nav aria-label="Main navigation">
        <Link className={`${styles.navLink} ${pathname === '/review-queue' ? styles.active : ''}`} href="/review-queue">▤ &nbsp; Review Queue</Link>
        <Link className={`${styles.navLink} ${pathname === '/final-decisions' ? styles.active : ''}`} href="/final-decisions">✓ &nbsp; Final Decisions</Link>
      </nav>
      <div className={styles.sidebarNote}>Additional EAOS screens can be added here later. Navigation is not an authorization control.</div>
    </aside>
    <main className={styles.main}>
      <header className={styles.topbar}><span>Riverview State University · Admissions Management</span><span className={styles.role}>{role}</span></header>
      <div className={styles.content}>
        <div className={styles.heading}><div><h1>{title}</h1><p>{subtitle}</p></div></div>
        {children}
      </div>
    </main>
  </div>;
}
