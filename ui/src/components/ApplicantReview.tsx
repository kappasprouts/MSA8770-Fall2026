"use client";

import { useEffect, useRef, useState } from "react";
import EaosShell from "@/components/EaosShell";
import AppHeader from "@/components/AppHeader";
import DossierPanel from "@/components/DossierPanel";
import DocumentsPanel from "@/components/DocumentsPanel";
import ChatPanel from "@/components/ChatPanel";
import OfficerRecommendationPanel from "@/components/OfficerRecommendationPanel";
import RequestState from "@/components/RequestState";
import styles from "@/components/eaos.module.css";
import { requestJson } from "@/lib/http";
import { dossierHref } from "@/lib/eaos-api";
import { isDossierForApplicant, latestRunCheckState, parseApplicantSummaries } from "@/lib/review-state";
import type { ApplicantSummary, DossierPayload, OriginalDocument } from "@/lib/types";

type LoadedDossier = { data: DossierPayload; documents: OriginalDocument[] };

export default function ApplicantReview() {
  const [applicants, setApplicants] = useState<ApplicantSummary[]>([]);
  const [listState, setListState] = useState<"loading" | "ready" | "error">("loading");
  const [listError, setListError] = useState("");
  const [listAttempt, setListAttempt] = useState(0);
  const [selectedAppId, setSelectedAppId] = useState("");
  const [loaded, setLoaded] = useState<LoadedDossier | null>(null);
  const [dossierError, setDossierError] = useState<{ appId: string; message: string } | null>(null);
  const [dossierAttempt, setDossierAttempt] = useState(0);
  const dossierRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    requestJson<unknown>("/api/applicants", { signal: controller.signal })
      .then(parseApplicantSummaries)
      .then(list => {
        if (controller.signal.aborted) return;
        setApplicants(list);
        setListState("ready");
        const requested = new URLSearchParams(window.location.search).get("appId");
        setSelectedAppId(requested || list[0]?.id || "");
      })
      .catch(error => {
        if (!controller.signal.aborted) {
          setListError(error instanceof Error ? error.message : "Could not load applicants.");
          setListState("error");
        }
      });
    return () => controller.abort();
  }, [listAttempt]);

  useEffect(() => {
    if (!selectedAppId) return;
    const controller = new AbortController();
    dossierRequest.current = controller;
    requestJson<LoadedDossier>(`/api/dossier?appId=${encodeURIComponent(selectedAppId)}`, { signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        if (!isDossierForApplicant(result.data, selectedAppId)) throw new Error("The dossier did not match the selected applicant. Please try again.");
        setLoaded({ data: result.data, documents: Array.isArray(result.documents) ? result.documents : [] });
      })
      .catch(error => {
        if (!controller.signal.aborted) setDossierError({ appId: selectedAppId, message: error instanceof Error ? error.message : "Could not load the dossier." });
      });
    return () => controller.abort();
  }, [selectedAppId, dossierAttempt]);

  function selectApplicant(appId: string) {
    dossierRequest.current?.abort();
    setLoaded(null);
    setDossierError(null);
    setSelectedAppId(appId);
    window.history.replaceState(null, "", dossierHref(appId));
  }

  function retryDossier() {
    dossierRequest.current?.abort();
    setLoaded(null);
    setDossierError(null);
    setDossierAttempt(attempt => attempt + 1);
  }

  const current = loaded && isDossierForApplicant(loaded.data, selectedAppId) ? loaded : null;
  const error = dossierError?.appId === selectedAppId ? dossierError.message : null;
  const loadingDossier = Boolean(selectedAppId && !current && !error);
  const demographics = current?.data.applicant_dossier?.applicant_demographics;
  const name = demographics ? [demographics.first_name, demographics.last_name].filter(Boolean).join(" ") : null;
  const latestFailed = current && latestRunCheckState(current.data.run ?? {}) === "failed";

  return (
    <EaosShell title="Applicant Review" subtitle="Review saved dossiers alongside their original documents." role="Applicant review">
      <AppHeader applicants={applicants} selectedAppId={selectedAppId} onSelect={selectApplicant} applicantName={name || null} disabled={listState !== "ready" || applicants.length === 0} placeholder={listState === "loading" ? "Loading applicants…" : listState === "error" ? "Applicants unavailable" : "No saved dossiers"} />
      {listState === "loading" && <RequestState kind="loading" title="Loading applicants…" />}
      {listState === "error" && <RequestState kind="error" title="Applicants could not be loaded" description={listError} onRetry={() => { setListState("loading"); setListError(""); setListAttempt(attempt => attempt + 1); }} />}
      {listState === "ready" && applicants.length === 0 && !selectedAppId && <RequestState kind="empty" title="No saved dossiers yet" description="Applicants appear here after a dossier is saved. Check the processing dashboard for applications awaiting generation." />}
      {error && <RequestState kind="error" title={`Could not load ${selectedAppId}`} description={error} onRetry={retryDossier} />}
      {loadingDossier && <RequestState kind="loading" title={`Loading ${selectedAppId}…`} description="Documents and Q&A will be available when this applicant's dossier has loaded." />}
      {current && <>
        {latestFailed && <div className={styles.notice} role="status"><strong>The latest generation attempt failed.</strong><p className={styles.help}>The saved dossier remains available below. Its validation cannot be inferred from the latest attempt.</p></div>}
        <div className={styles.dossierGrid}>
          <DossierPanel payload={current.data} />
          <DocumentsPanel key={selectedAppId} appId={selectedAppId} documents={current.documents} />
        </div>
        <OfficerRecommendationPanel key={selectedAppId} appId={selectedAppId} />
        <div className={styles.chatSection}><ChatPanel key={selectedAppId} appId={selectedAppId} /></div>
      </>}
    </EaosShell>
  );
}
