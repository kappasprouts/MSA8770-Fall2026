import Link from "next/link";
import { redirect } from "next/navigation";
import EaosShell from "@/components/EaosShell";
import WorkspaceIcon from "@/components/WorkspaceIcon";
import { dossierHref } from "@/lib/eaos-api";
import styles from "./home.module.css";

const destinations = [
  {
    href: "/review-queue",
    icon: "processing",
    title: "Processing dashboard",
    description: "Application statuses, batch processing, and dossier availability.",
  },
  {
    href: "/applicant-review",
    icon: "review",
    title: "Applicant review",
    description: "Saved dossiers, original documents, and dossier Q&A.",
  },
  {
    href: "/final-decisions",
    icon: "decisions",
    title: "Final decisions",
    description: "Pending decision queue and recording of authorized admissions decisions.",
  },
  {
    href: "/statistics",
    icon: "statistics",
    title: "Summary statistics",
    description: "Applicant pool, academic trends, decision progress, and cohort comparisons.",
  },
] as const;

export default async function Home({ searchParams }: PageProps<"/">) {
  const params = await searchParams;
  const appId = Array.isArray(params.appId) ? params.appId[0] : params.appId;
  // Keep saved dossier bookmarks working after introducing the home page.
  if (appId) redirect(dossierHref(appId));

  return (
    <EaosShell
      title="Admissions workspace"
      subtitle="Application processing, applicant review, and decision recording."
      role="Home"
    >
      <nav aria-label="Admissions workspaces" className={styles.workspaces}>
        <ul className={styles.destinations}>
          {destinations.map(destination => (
            <li key={destination.href}>
              <Link href={destination.href} className={styles.destination}>
                <span className={styles.icon}><WorkspaceIcon name={destination.icon} /></span>
                <div className={styles.details}>
                  <h2>{destination.title}</h2>
                  <p>{destination.description}</p>
                </div>
                <span className={styles.arrow} aria-hidden="true">→</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </EaosShell>
  );
}
