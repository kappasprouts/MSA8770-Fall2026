"use client";

import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import type { WorkspaceMode } from "@/components/AppHeader";
import ApplicantSidebar, { type SidebarSection } from "@/components/ApplicantSidebar";
import ReviewWorkspace, { type TabId } from "@/components/ReviewWorkspace";
import type { ApplicantSummary, DossierPayload, OriginalDocument } from "@/lib/types";

export default function Home() {
  const [applicants, setApplicants] = useState<ApplicantSummary[]>([]);
  const [selectedAppId, setSelectedAppId] = useState("");
  const [payload, setPayload] = useState<DossierPayload | null>(null);
  const [documents, setDocuments] = useState<OriginalDocument[]>([]);
  const [activeSection, setActiveSection] = useState<SidebarSection>("queue");
  const [activeTab, setActiveTab] = useState<TabId>("review");
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("officer");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/applicants")
      .then((res) => res.json())
      .then((data: { applicants: ApplicantSummary[] }) => {
        setApplicants(data.applicants);

        if (data.applicants.length > 0) {
          setSelectedAppId(data.applicants[0].id);
        }
      })
      .catch(() => setError("Could not load the list of applicants."));
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
        const res = await fetch(`/api/dossier?appId=${encodeURIComponent(selectedAppId)}`);
        const data = await res.json();

        if (!res.ok) {
          throw new Error(data.error ?? "Failed to load dossier.");
        }

        if (!cancelled) {
          setPayload(data.data);
          setDocuments(data.documents ?? []);
        }
      } catch (err) {
        if (!cancelled) {
          setPayload(null);
          setDocuments([]);
          setError(err instanceof Error ? err.message : "Failed to load dossier.");
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
    const demo = payload?.applicant_dossier?.applicant_demographics;

    if (!demo) {
      return null;
    }

    const name = [demo.first_name, demo.last_name].filter(Boolean).join(" ");
    return name || null;
  })();

  const selectSidebarSection = (section: SidebarSection) => {
    setActiveSection(section);

    if (section === "reports" || section === "settings") {
      setWorkspaceMode("admin");
    } else {
      setWorkspaceMode("officer");
    }

    const tabBySection: Record<SidebarSection, TabId> = {
      dashboard: "review",
      queue: "review",
      policies: "policies",
      documents: "documents",
      reports: "validation",
      settings: "settings",
    };

    setActiveTab(tabBySection[section]);
  };

  const selectWorkspaceMode = (mode: WorkspaceMode) => {
    setWorkspaceMode(mode);
    setActiveTab("review");
    setActiveSection(mode === "admin" ? "reports" : "dashboard");
  };

  const selectWorkspaceTab = (tab: TabId) => {
    setActiveTab(tab);

    const sectionByTab: Partial<Record<TabId, SidebarSection>> = {
      review: "queue",
      validation: "reports",
      documents: "documents",
      policies: "policies",
      settings: "settings",
    };

    if (sectionByTab[tab]) {
      setActiveSection(sectionByTab[tab]);
    }
  };

  return (
    <div className="min-h-screen bg-app-bg text-ink lg:flex">
      <ApplicantSidebar
        applicants={applicants}
        selectedAppId={selectedAppId}
        onSelect={setSelectedAppId}
        activeSection={activeSection}
        onSectionSelect={selectSidebarSection}
      />

      <div className="min-w-0 flex-1">
        <AppHeader
          selectedAppId={selectedAppId}
          applicantName={applicantName}
          generatedAt={payload?.applicant_dossier?.generated_at}
          workspaceMode={workspaceMode}
          onWorkspaceModeChange={selectWorkspaceMode}
        />

        <main className="mx-auto w-full max-w-[1600px] p-4 sm:p-6 lg:p-8">
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

          {!loading && !payload && !error && (
            <div className="rounded-xl border border-dashed border-border bg-surface px-5 py-16 text-center">
              <p className="font-semibold text-ink">Select an applicant to begin review</p>
              <p className="mt-1 text-sm text-ink-muted">Validated dossiers will appear in the applicant queue.</p>
            </div>
          )}

          {payload && (
            <ReviewWorkspace
              payload={payload}
              documents={documents}
              appId={selectedAppId}
              activeTab={activeTab}
              onTabChange={selectWorkspaceTab}
              workspaceMode={workspaceMode}
            />
          )}
        </main>
      </div>
    </div>
  );
}
