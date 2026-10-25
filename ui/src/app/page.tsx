
import Link from "next/link";
import Image from "next/image";
import { redirect } from "next/navigation";
import EaosShell from "@/components/EaosShell";
import WorkspaceIcon from "@/components/WorkspaceIcon";
import { dossierHref } from "@/lib/eaos-api";
import styles from "./home.module.css";

const destinations = [
  {
    href: "/review-queue",
    icon: "processing",
    title: "Processing Dashboard",
  },
  {
    href: "/applicant-review",
    icon: "review",
    title: "Applicant Review",
  },
  {
    href: "/final-decisions",
    icon: "decisions",
    title: "Final Decisions",
  },
  {
    href: "/statistics",
    icon: "statistics",
    title: "Summary Statistics",
  },
] as const;

export default async function Home({
  searchParams,
}: PageProps<"/">) {
  const params = await searchParams;
  const appId = Array.isArray(params.appId)
    ? params.appId[0]
    : params.appId;

  if (appId) {
    redirect(dossierHref(appId));
  }

  return (
    <EaosShell title="" subtitle="" role="Home">
      <div className={styles.homepage}>
        <div className={styles.hero}>
          <Image
            src="/rsu-homepage-sunset.png"
            alt="Riverview State University campus at sunset"
            fill
            priority
            unoptimized
            sizes="(max-width: 768px) 100vw, 85vw"
            className={styles.heroImage}
          />
        </div>


        <section className={styles.welcome}>
          <div className={styles.introduction}>
            <div className={styles.welcomeHeading}>
              <div className={styles.shield} aria-hidden="true">
                <span>RSU</span>
                <span className={styles.shieldChevron}>⌃</span>
              </div>

              <div>
                <h1>Welcome to Riverview State University</h1>
                <p>
                  Riverview State University, founded in 1913, is
                  committed to academic excellence, innovative
                  research, and service to our diverse communities.
                  We empower students to achieve their full
                  potential and make a positive impact in an
                  ever-changing world.
                </p>
              </div>
            </div>
          </div>

          <aside className={styles.mission}>
            <svg
              className={styles.missionIcon}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M3 9h18L12 3 3 9Z" />
              <path d="M5 10v9M9 10v9M15 10v9M19 10v9" />
              <path d="M2 21h20" />
            </svg>

            <div>
              <h2>Our Mission</h2>
              <p>
                To provide an inclusive, transformative education
                that prepares students to lead, serve, and create
                a better tomorrow.
              </p>
            </div>
          </aside>
        </section>

        <nav
          aria-label="Admissions workspaces"
          className={styles.workspaces}
        >
          {destinations.map((destination) => (
            <Link
              key={destination.href}
              href={destination.href}
              className={styles.destination}
            >
              <span className={styles.icon}>
                <WorkspaceIcon name={destination.icon} />
              </span>
              <span>{destination.title}</span>
            </Link>
          ))}

          <div
            className={`${styles.destination} ${styles.disabled}`}
            aria-label="Tech Support coming soon"
          >
            <span className={styles.icon}>
              <span aria-hidden="true">⚙</span>
            </span>
            <span>
              Tech Support
              <small>Coming Soon</small>
            </span>
          </div>
        </nav>
      </div>
    </EaosShell>
  );
}
