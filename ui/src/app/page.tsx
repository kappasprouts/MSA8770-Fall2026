"use client";

import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import DossierPanel from "@/components/DossierPanel";
import DocumentsPanel from "@/components/DocumentsPanel";
import ChatPanel from "@/components/ChatPanel";
import type { ApplicantSummary, DossierPayload, OriginalDocument } from "@/lib/types";

export default function Home() {
  const [applicants, setApplicants] = useState<ApplicantSummary[]>([]);
  const [selectedAppId, setSelectedAppId] = useState("");
  const [payload, setPayload] = useState<DossierPayload | null>(null);
  const [documents, setDocuments] = useState<OriginalDocument[]>([]);
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

  return (
    <div className="flex h-screen flex-col bg-app-bg text-ink">
      <AppHeader
        applicants={applicants}
        selectedAppId={selectedAppId}
        onSelect={setSelectedAppId}
        applicantName={applicantName}
      />

      <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading && !payload && (
          <div className="rounded-lg border border-border bg-surface px-4 py-3 text-sm text-ink-muted">
            Loading applicant dossier…
          </div>
        )}

        {payload && (
          <>
            <div className="grid grid-cols-1 gap-4 lg:h-[52vh] lg:grid-cols-2">
              <DossierPanel payload={payload} />
              <DocumentsPanel appId={selectedAppId} documents={documents} />
            </div>

            <div className="h-[50vh] shrink-0">
              <ChatPanel key={selectedAppId} appId={selectedAppId} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}
