"use client";

import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import type { WorkspaceMode } from "@/components/AppHeader";
import ApplicantSidebar, {
  type SidebarSection,
} from "@/components/ApplicantSidebar";
import ErrorQueuePanel from "@/components/ErrorQueuePanel";
import ApplicantExceptionDetails from "@/components/ApplicantExceptionDetails";
import ReviewWorkspace, {
  type TabId,
} from "@/components/ReviewWorkspace";
import type {
  ApplicantSummary,
  DossierPayload,
  OriginalDocument,
} from "@/lib/types";

type ExceptionView = "queue" | "details";

export default function Home() {
  const [applicants, setApplicants] = useState<
    ApplicantSummary[]
  >([]);

  const [selectedAppId, setSelectedAppId] =
    useState("");

  const [payload, setPayload] =
    useState<DossierPayload | null>(null);

  const [documents, setDocuments] = useState<
    OriginalDocument[]
  >([]);

  const [activeSection, setActiveSection] =
    useState<SidebarSection>("queue");

  const [activeTab, setActiveTab] =
    useState<TabId>("review");

  const [workspaceMode, setWorkspaceMode] =
    useState<WorkspaceMode>("officer");

  const [exceptionView, setExceptionView] =
    useState<ExceptionView>("queue");

  const [
    selectedExceptionId,
    setSelectedExceptionId,
  ] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);

  const [error, setError] = useState<
    string | null
  >(null);

  useEffect(() => {
    fetch("/api/applicants")
      .then((response) => response.json())
      .then(
        (data: {
          applicants: ApplicantSummary[];
        }) => {
          setApplicants(data.applicants);

          if (data.applicants.length > 0) {
            const requestedId = new URLSearchParams(window.location.search).get("appId");
            const selected = data.applicants.find((applicant) => applicant.id === requestedId);
            setSelectedAppId(selected?.id ?? data.applicants[0].id);
          }
        },
      )
      .catch(() =>
        setError(
          "Could not load the list of applicants.",
        ),
      );
  }, []);

  useEffect(() => {
    if (!selectedAppId) {
      return;
    }

    let cancelled = false;

    async function loadDossier() {
      setLoading(true);
      setError(null);

      try {
        const response = await fetch(
          `/api/dossier?appId=${encodeURIComponent(
            selectedAppId,
          )}`,
        );

        const data = await response.json();

        if (!response.ok) {
          throw new Error(
            data.error ??
              "Failed to load dossier.",
          );
        }

        if (!cancelled) {
          setPayload(data.data);
          setDocuments(data.documents ?? []);
        }
      } catch (reason) {
        if (!cancelled) {
          setPayload(null);
          setDocuments([]);
          setError(
            reason instanceof Error
              ? reason.message
              : "Failed to load dossier.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadDossier();

    return () => {
      cancelled = true;
    };
  }, [selectedAppId]);

  const applicantName = (() => {
    const demographics =
      payload?.applicant_dossier
        ?.applicant_demographics;

    if (!demographics) {
      return null;
    }

    const name = [
      demographics.first_name,
      demographics.last_name,
    ]
      .filter(Boolean)
      .join(" ");

    return name || null;
  })();

  const selectSidebarSection = (
    section: SidebarSection,
  ) => {
    setActiveSection(section);

    if (
      section === "exceptions" ||
      section === "reports" ||
      section === "settings"
    ) {
      setWorkspaceMode("admin");
    } else {
      setWorkspaceMode("officer");
    }

    if (section === "exceptions") {
      setExceptionView("queue");
      setSelectedExceptionId(null);
    }

    const tabBySection: Record<
      SidebarSection,
      TabId
    > = {
      dashboard: "review",
      queue: "review",
      exceptions: "review",
      policies: "policies",
      documents: "documents",
      reports: "validation",
      settings: "settings",
    };

    setActiveTab(tabBySection[section]);
  };

  const selectWorkspaceMode = (
    mode: WorkspaceMode,
  ) => {
    setWorkspaceMode(mode);
    setActiveTab("review");
    setExceptionView("queue");
    setSelectedExceptionId(null);

    setActiveSection(
      mode === "admin"
        ? "reports"
        : "dashboard",
    );
  };

  const selectWorkspaceTab = (tab: TabId) => {
    setActiveTab(tab);

    const sectionByTab: Partial<
      Record<TabId, SidebarSection>
    > = {
      review: "queue",
      validation: "reports",
      documents: "documents",
      policies: "policies",
      settings: "settings",
    };

    const matchingSection =
      sectionByTab[tab];

    if (matchingSection) {
      setActiveSection(matchingSection);
    }
  };

  const openExceptionDetails = (
    exceptionId: string,
  ) => {
    setSelectedExceptionId(exceptionId);
    setExceptionView("details");
    setWorkspaceMode("admin");
  };

  const returnToErrorQueue = () => {
    setSelectedExceptionId(null);
    setExceptionView("queue");
    setWorkspaceMode("admin");
    setActiveSection("exceptions");
  };

  const openApplicantFromException = (
    appId: string,
  ) => {
    setSelectedAppId(appId);
    setSelectedExceptionId(null);
    setExceptionView("queue");
    selectSidebarSection("queue");
  };

  const isExceptionSection =
    activeSection === "exceptions";

  const isExceptionDetails =
    isExceptionSection &&
    exceptionView === "details" &&
    selectedExceptionId !== null;

  const headerTitle = isExceptionDetails
    ? "Applicant Exception Details"
    : isExceptionSection
      ? "Error Queue"
      : undefined;

  const headerEyebrow = isExceptionSection
    ? "IT operations"
    : undefined;

  const headerDescription = isExceptionDetails
    ? "Review the validation findings, affected documents, source component, and audit history for this exception."
    : isExceptionSection
      ? "Review incomplete, failed, and unmatched records that require technical follow-up."
      : undefined;

  return (
    <div className="min-h-screen bg-app-bg text-ink lg:flex">
      <ApplicantSidebar
        applicants={applicants}
        selectedAppId={selectedAppId}
        onSelect={setSelectedAppId}
        activeSection={activeSection}
        onSectionSelect={
          selectSidebarSection
        }
      />

      <div className="min-w-0 flex-1">
        <AppHeader
          selectedAppId={selectedAppId}
          applicantName={applicantName}
          generatedAt={
            payload?.applicant_dossier
              ?.generated_at
          }
          workspaceMode={workspaceMode}
          onWorkspaceModeChange={
            selectWorkspaceMode
          }
          titleOverride={headerTitle}
          eyebrowOverride={headerEyebrow}
          descriptionOverride={
            headerDescription
          }
        />

        <main className="mx-auto w-full max-w-[1600px] p-4 sm:p-6 lg:p-8">
          {isExceptionSection ? (
            isExceptionDetails ? (
              <ApplicantExceptionDetails
                key={selectedExceptionId}
                exceptionId={
                  selectedExceptionId
                }
                onBack={returnToErrorQueue}
                onOpenApplicant={
                  openApplicantFromException
                }
              />
            ) : (
              <ErrorQueuePanel
                onViewDetails={
                  openExceptionDetails
                }
              />
            )
          ) : (
            <>
              {error && (
                <div className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              {loading && !payload && (
                <div className="rounded-xl border border-border bg-surface px-5 py-12 text-center text-sm text-ink-muted shadow-sm">
                  Loading applicant dossier…
                </div>
              )}

              {!loading &&
                !payload &&
                !error && (
                  <div className="rounded-xl border border-dashed border-border bg-surface px-5 py-16 text-center">
                    <p className="font-semibold text-ink">
                      Select an applicant to
                      begin review
                    </p>

                    <p className="mt-1 text-sm text-ink-muted">
                      Validated dossiers will
                      appear in the applicant
                      queue.
                    </p>
                  </div>
                )}

              {payload && (
                <ReviewWorkspace
                  payload={payload}
                  documents={documents}
                  appId={selectedAppId}
                  activeTab={activeTab}
                  onTabChange={
                    selectWorkspaceTab
                  }
                  workspaceMode={
                    workspaceMode
                  }
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}