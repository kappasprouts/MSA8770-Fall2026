
"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import styles from "./eaos.module.css";
import Logo from "./Logo";
import WorkspaceIcon from "./WorkspaceIcon";

const navigation = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/review-queue", label: "Processing Dashboard", icon: "processing" },
  { href: "/applicant-review", label: "Applicant Review", icon: "review" },
  { href: "/final-decisions", label: "Final Decisions", icon: "decisions" },
  { href: "/statistics", label: "Summary Statistics", icon: "statistics" },
] as const;

export default function EaosShell({
  title,
  subtitle,
  role,
  children,
}: {
  title: string;
  subtitle: string;
  role: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const isHome = pathname === "/";

  function goBack() {
  if (window.history.length > 1) {
    router.back();
  } else {
    router.push("/");
  }
}

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main-content">
        Skip to content
      </a>

      <aside className={styles.sidebar}>
        <Link
          href="/"
          className={styles.brand}
          aria-label="Riverview State University home"
        >
          <Logo className="h-12 w-12 shrink-0" />
          <span>
            <strong>Riverview State University</strong>
          </span>
        </Link>

        {!isHome && (
          <div className={styles.sidebarPhoto}>
            <Image
              src="/rsu-sidebar-building.png"
              alt="University building beneath a purple sunset"
              width={200}
              height={125}
              style={{ width: "100%", height: "auto" }}
            />
          </div>
        )}

        <nav aria-label="Main navigation" className={styles.navigation}>
          {navigation.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={pathname === item.href ? "page" : undefined}
              className={`${styles.navLink} ${
                pathname === item.href ? styles.active : ""
              }`}
            >
              <WorkspaceIcon name={item.icon} />
              {item.label}
            </Link>
          ))}

          <div className={`${styles.navLink} ${styles.comingSoon}`}>
            <span aria-hidden="true">🎧</span>
            <span>
              Tech Support
              <small>Coming Soon</small>
            </span>
          </div>
        </nav>
      </aside>

      <div className={styles.main}>
        {!isHome && (
          <header className={styles.topbar}>
            <button
              type="button"
              className={styles.backButton}
              onClick={goBack}
            >
              ← Back to Previous Screen
            </button>
            <span className={styles.role}>{role}</span>
          </header>
        )}

        <main
          id="main-content"
          tabIndex={-1}
          className={styles.content}
        >
          {!isHome && (
            <div className={styles.heading}>
              <h1>{title === "Statistics" ? "Summary Statistics" : title}</h1>
              <p>{subtitle}</p>
            </div>
          )}

          {children}
        </main>
      </div>
    </div>
  );
}
