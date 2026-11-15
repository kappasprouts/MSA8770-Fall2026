
"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useSessionUser } from "./AuthProvider";
import { canAccess, pagePermission, ROLE_LABELS } from "@/lib/auth-policy";
import { requestJson } from "@/lib/http";
import styles from "./eaos.module.css";
import Logo from "./Logo";
import WorkspaceIcon from "./WorkspaceIcon";

const navigation = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/review-queue", label: "Processing Dashboard", icon: "processing" },
  { href: "/applicant-review", label: "Applicant Review", icon: "review" },
  { href: "/final-decisions", label: "Final Decisions", icon: "decisions" },
  { href: "/statistics", label: "Summary Statistics", icon: "statistics" },
  { href: "/error-queue", label: "IT Error Queue", icon: "processing" },
] as const;

// Where "Back to Previous Screen" leads from each top-level screen; unlisted screens go Home.
const previousScreen: Record<string, string> = {
  "/review-queue": "/",
  "/applicant-review": "/review-queue",
  "/final-decisions": "/",
  "/statistics": "/",
  "/error-queue": "/",
};

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
  const user = useSessionUser();
  const [signingOut, setSigningOut] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  async function signOut() {
    setSigningOut(true); setSignOutError("");
    try {
      await requestJson("/api/auth/logout", { method: "POST" });
      router.replace("/");
      router.refresh();
    } catch (error) {
      setSignOutError(error instanceof Error ? error.message : "Could not sign out.");
      setSigningOut(false);
    }
  }

  // Step back through the workflow instead of following browser history:
  // nested screens (e.g. /error-queue/[id]) return to their parent list, and
  // top-level screens return to the screen listed in previousScreen.
  function goBack() {
    const segments = pathname.split("/").filter(Boolean);
    if (segments.length > 1) {
      router.push(`/${segments[0]}`);
      return;
    }
    const target = previousScreen[pathname] ?? "/";
    const permission = pagePermission(target);
    router.push(permission && !canAccess(user?.role, permission) ? "/" : target);
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
          {navigation.filter(item => {
            const permission = pagePermission(item.href);
            return !user || !permission || canAccess(user.role, permission);
          }).map((item) => (
            <Link
              key={item.href}
              href={item.href}
              aria-current={(pathname === item.href || pathname.startsWith(item.href + "/")) ? "page" : undefined}
              className={`${styles.navLink} ${
                (pathname === item.href || pathname.startsWith(item.href + "/")) ? styles.active : ""
              }`}
            >
              <WorkspaceIcon name={item.icon} />
              {item.label}
            </Link>
          ))}


        </nav>
        <div className={styles.account}>
          {user ? <>
            <strong>{user.fullName}</strong>
            <span>{ROLE_LABELS[user.role]} · {user.userId}</span>
            <button type="button" className={styles.secondaryButton} onClick={signOut} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign Out"}</button>
            {signOutError && <p role="alert">{signOutError}</p>}
          </> : <Link href="/login" className={styles.secondaryButton}>Sign In</Link>}
        </div>
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
            <span className={styles.role}>{user ? ROLE_LABELS[user.role] : role}</span>
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
