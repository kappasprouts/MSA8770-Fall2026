"use client";

import type { DossierPayload, OriginalDocument } from "@/lib/types";
import type { WorkspaceMode } from "./AppHeader";
import ChatPanel from "./ChatPanel";
import DocumentsPanel from "./DocumentsPanel";
import DossierPanel from "./DossierPanel";
import OfficerActionPanel from "./OfficerActionPanel";
import PolicyChecksCard from "./dossier/PolicyChecksCard";
import SnapshotCard from "./dossier/SnapshotCard";

export type TabId = "review" | "validation" | "documents" | "policies" | "questions" | "action" | "settings";

const OFFICER_TABS: Array<{ id: TabId; label: string }> = [
  { id: "review", label: "Applicant Overview" },
  { id: "questions", label: "Officer Q&A" },
  { id: "action", label: "Officer Action" },
  { id: "documents", label: "Documents" },
  { id: "policies", label: "Policy Guidance" },
];

const ADMIN_TABS: Array<{ id: TabId; label: string }> = [
  { id: "review", label: "Run Overview" },
  { id: "validation", label: "Validation Details" },
  { id: "documents", label: "Document Processing" },
  { id: "policies", label: "Policy Retrieval" },
];

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-xl border border-border bg-white px-4 py-3 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">{label}</p>
      <p className="mt-1 text-xl font-bold text-ink">{value}</p>
      <p className="mt-0.5 text-xs text-ink-muted">{detail}</p>
    </div>
  );
}

export default function ReviewWorkspace({
  payload,
  documents,
  appId,
  activeTab,
  onTabChange,
  workspaceMode,
}: {
  payload: DossierPayload;
  documents: OriginalDocument[];
  appId: string;
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  workspaceMode: WorkspaceMode;
}) {
  const run = payload.run ?? {};
  const dossier = payload.applicant_dossier;
  const calls = run.validation?.calls?.length ?? run.attempts ?? 0;
  const policies = Array.isArray(dossier?.policy_assessment) ? dossier.policy_assessment.length : 0;
  const passedCalls = run.validation?.calls?.filter((call) => !call.errors?.length).length ?? 0;
  const totalCalls = run.validation?.calls?.length ?? 0;
  const validationFailed = run.validation?.passed === false;
  const applicationType = dossier?.applicant_demographics?.application_type ?? "Application";
  const tabItems = workspaceMode === "admin" ? ADMIN_TABS : OFFICER_TABS;

  return (
    <section className="space-y-5">
      {workspaceMode === "admin" ? (
        <>
          <div className="rounded-xl border border-blue-200 bg-blue-50 px-5 py-4">
            <p className="text-sm font-semibold text-blue-900">IT administration dashboard</p>
            <p className="mt-1 text-sm text-blue-700">Technical run metrics and validation diagnostics for system monitoring. These values are not admissions recommendations.</p>
          </div>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Metric label="Processing time" value={run.runtime_seconds ? `${Number(run.runtime_seconds).toFixed(1)}s` : "—"} detail="Latest summarizer run" />
            <Metric label="Model calls" value={String(calls || "—")} detail="Including retry attempts" />
            <Metric label="Policies retrieved" value={String(policies || run.policies_retrieved?.length || "—")} detail="Applied to this dossier" />
            <Metric label="Validated outputs" value={totalCalls ? `${passedCalls}/${totalCalls}` : dossier ? "Complete" : "—"} detail="Schema and evidence checks" />
          </div>
        </>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <OfficerStatus label="Review status" value={validationFailed ? "Needs officer attention" : "Ready for review"} detail="Human decision required" tone={validationFailed ? "warn" : "pass"} />
          <OfficerStatus label="Application" value={String(applicationType)} detail={dossier?.applicant_demographics?.intended_major as string || dossier?.applicant_demographics?.intended_program as string || "Program not listed"} />
          <OfficerStatus label="Source documents" value={`${documents.length} available`} detail="Open and verify originals" />
          <OfficerStatus label="Recommended next step" value="Review and act" detail="Ask questions before recording action" tone="accent" />
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border border-border bg-white shadow-sm">
        <div className="overflow-x-auto border-b border-border bg-surface-alt px-3">
          <div className="flex min-w-max gap-1" role="tablist" aria-label="Applicant review sections">
            {tabItems.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => onTabChange(tab.id)}
                className={`border-b-2 px-4 py-4 text-sm font-semibold transition ${
                  activeTab === tab.id
                    ? "border-accent text-accent"
                    : "border-transparent text-ink-muted hover:text-ink"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="p-4 sm:p-6">
          {activeTab === "review" && workspaceMode === "officer" && (
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-2">
                <button type="button" onClick={() => onTabChange("questions")} className="group rounded-xl border border-violet-200 bg-violet-50 p-5 text-left transition hover:border-accent hover:shadow-sm">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-violet-700">Officer Q&amp;A</p>
                  <h3 className="mt-2 text-lg font-semibold text-ink">Ask a question about this applicant</h3>
                  <p className="mt-1 text-sm leading-6 text-ink-muted">Explore academics, recommendations, activities, or inconsistencies using the available dossier evidence.</p>
                  <span className="mt-4 inline-flex text-sm font-semibold text-accent group-hover:underline">Open Q&amp;A →</span>
                </button>
                <button type="button" onClick={() => onTabChange("action")} className="group rounded-xl border border-blue-200 bg-blue-50 p-5 text-left transition hover:border-[#244E7D] hover:shadow-sm">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Human decision step</p>
                  <h3 className="mt-2 text-lg font-semibold text-ink">Record the next review action</h3>
                  <p className="mt-1 text-sm leading-6 text-ink-muted">Send to a second reader, request further review, escalate an exception, or record a preliminary recommendation.</p>
                  <span className="mt-4 inline-flex text-sm font-semibold text-[#244E7D] group-hover:underline">Open officer action →</span>
                </button>
              </div>
              <DossierPanel payload={payload} showValidation={false} />
            </div>
          )}
          {activeTab === "review" && workspaceMode === "admin" && (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
              <SnapshotCard payload={payload} />
              <div className="rounded-xl border border-border bg-surface p-5">
                <h3 className="text-base font-semibold text-ink">Latest pipeline run</h3>
                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                  <AdminFact label="Run status" value={run.run_status ?? "Unavailable"} />
                  <AdminFact label="Applicant ID" value={run.app_id ?? appId} />
                  <AdminFact label="Model attempts" value={String(run.attempts ?? calls ?? "—")} />
                  <AdminFact label="Documents sent" value={String(Object.keys(run.documents_sent ?? {}).length)} />
                  <AdminFact label="Documents withheld" value={String(Object.keys(run.documents_withheld ?? {}).length)} />
                  <AdminFact label="Validation" value={run.validation?.passed ? "Passed" : "Failed / review required"} />
                </dl>
              </div>
            </div>
          )}
          {activeTab === "validation" && (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
              <SnapshotCard payload={payload} />
              <div className="rounded-xl border border-border bg-surface p-5">
                <h3 className="text-base font-semibold text-ink">Validation record</h3>
                <p className="mt-1 text-sm text-ink-muted">
                  Each section is checked against its response schema and source-document evidence.
                </p>
                <div className="mt-4 space-y-3">
                  {(run.validation?.calls ?? []).length === 0 && (
                    <p className="rounded-lg bg-surface-alt px-4 py-3 text-sm text-ink-muted">
                      No detailed validation calls were stored for this development dossier.
                    </p>
                  )}
                  {(run.validation?.calls ?? []).map((call, index) => {
                    const passed = !call.errors?.length;
                    return (
                      <div key={`${call.section}-${call.attempt}-${index}`} className="flex gap-3 rounded-xl border border-border p-4">
                        <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${passed ? "bg-status-pass" : "bg-status-fail"}`} />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="font-semibold capitalize text-ink">{call.section ?? "Model output"}</p>
                            <p className="text-xs text-ink-muted">
                              Attempt {call.attempt ?? 1} · {call.usage?.seconds ? `${call.usage.seconds.toFixed(1)}s` : "time unavailable"}
                            </p>
                          </div>
                          <p className={`mt-1 text-sm ${passed ? "text-status-pass" : "text-status-fail"}`}>
                            {passed ? "Passed validation" : call.errors?.join(" ")}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
          {activeTab === "documents" && <DocumentsPanel appId={appId} documents={documents} />}
          {activeTab === "policies" && (
            <div className="mx-auto max-w-5xl">
              {Array.isArray(dossier?.policy_assessment) && dossier.policy_assessment.length > 0 ? (
                <PolicyChecksCard items={dossier.policy_assessment} detailed />
              ) : (
                <p className="rounded-xl border border-border bg-surface p-5 text-sm text-ink-muted">
                  No policy assessments are available for this applicant.
                </p>
              )}
            </div>
          )}
          {activeTab === "questions" && workspaceMode === "officer" && <div className="h-[650px]"><ChatPanel key={appId} appId={appId} /></div>}
          {activeTab === "action" && workspaceMode === "officer" && <OfficerActionPanel appId={appId} />}
          {activeTab === "settings" && (
            <div className="mx-auto max-w-3xl rounded-xl border border-border bg-surface p-6">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">Workspace settings</p>
              <h3 className="mt-2 text-lg font-semibold text-ink">Configuration remains simulated</h3>
              <p className="mt-2 text-sm leading-6 text-ink-muted">
                Production settings for user roles, review queues, notifications, and retention controls are planned for a later milestone. No configuration changes are persisted from this prototype.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function OfficerStatus({ label, value, detail, tone = "neutral" }: { label: string; value: string; detail: string; tone?: "neutral" | "pass" | "warn" | "accent" }) {
  const valueColor = tone === "pass" ? "text-emerald-700" : tone === "warn" ? "text-amber-700" : tone === "accent" ? "text-accent" : "text-ink";
  return (
    <div className="rounded-xl border border-border bg-white px-4 py-3 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">{label}</p>
      <p className={`mt-1 text-base font-bold ${valueColor}`}>{value}</p>
      <p className="mt-1 text-xs text-ink-muted">{detail}</p>
    </div>
  );
}

function AdminFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface-alt px-4 py-3">
      <dt className="text-xs font-medium text-ink-muted">{label}</dt>
      <dd className="mt-1 font-semibold text-ink">{value}</dd>
    </div>
  );
}
