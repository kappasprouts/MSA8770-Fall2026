
"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import styles from "./eaos.module.css";
import Logo from "./Logo";
import WorkspaceIcon from "./WorkspaceIcon";

const navigation = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/review-queue", label: "Processing Dashboard", icon: "processing" },
  { href: "/applicant-review", label: "Applicant Review", icon: "review" },
  { href: "/final-decisions", label: "Final Decisions", icon: "decisions" },
  { href: "/statistics", label: "Summary Statistics", icon: "statistics" },
  { href: "/error-queue", label: "IT Error Queue", icon: "errors" },
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
  const [compactSidebar, setCompactSidebar] = useState(false);

  function goBack() {
  if (window.history.length > 1) {
    router.back();
  } else {
    router.push("/");
  }
}

  return (
    <div className={`${styles.shell} ${compactSidebar ? styles.compactSidebarShell : ""}`}>
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

        {!isHome && !compactSidebar && (
          <div className={styles.sidebarPhoto}>
            <Image
              src="/rsu-sidebar-building.png"
              alt="University building beneath a purple sunset"
              width={200}
              height={125}
              sizes="(max-width: 760px) calc(100vw - 32px), 200px"
              style={{ width: "100%", height: "auto" }}
            />
          </div>
        )}

        <nav aria-label="Main navigation" className={styles.navigation}>
          {navigation.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={(pathname === item.href || pathname.startsWith(item.href + "/")) ? "page" : undefined}
              title={compactSidebar ? item.label : undefined}
              aria-label={item.label}
              className={`${styles.navLink} ${
                (pathname === item.href || pathname.startsWith(item.href + "/")) ? styles.active : ""
              }`}
            >
              <WorkspaceIcon name={item.icon} />
              <span className={styles.navText}>{item.label}</span>
            </Link>
          ))}
        </nav>

        <button
          type="button"
          className={styles.sidebarToggle}
          onClick={() => setCompactSidebar(value => !value)}
          aria-label={compactSidebar ? "Expand sidebar" : "Collapse sidebar"}
          title={compactSidebar ? "Expand sidebar" : "Collapse sidebar"}
        >
          <WorkspaceIcon name={compactSidebar ? "expand" : "collapse"} />
        </button>
      </aside>

      <div className={styles.main}>
        {!isHome && (
          <header className={styles.topbar}>
            <button
              type="button"
              className={styles.backButton}
              onClick={goBack}
              aria-label="Back to previous screen"
              title="Back to previous screen"
            >
              <WorkspaceIcon name="back" />
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
