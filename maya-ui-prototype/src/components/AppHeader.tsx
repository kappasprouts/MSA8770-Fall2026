export type WorkspaceMode = "officer" | "admin";

export default function AppHeader({
  selectedAppId,
  applicantName,
  generatedAt,
  workspaceMode,
  onWorkspaceModeChange,
}: {
  selectedAppId: string;
  applicantName: string | null;
  generatedAt?: string;
  workspaceMode: WorkspaceMode;
  onWorkspaceModeChange: (mode: WorkspaceMode) => void;
}) {
  const generatedLabel = generatedAt
    ? new Date(generatedAt).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : "Development dossier";

  return (
    <header className="border-b border-border bg-white px-4 py-5 sm:px-6 lg:px-8">
      <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">Applicant review</p>
            {selectedAppId && (
              <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-700">
                Human review required
              </span>
            )}
          </div>
          <h1 className="mt-1 truncate text-2xl font-bold tracking-tight text-ink sm:text-3xl">
            {selectedAppId || "Admissions workspace"}
            {applicantName && <span className="font-normal text-ink-muted"> · {applicantName}</span>}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            {selectedAppId ? `Dossier generated ${generatedLabel}` : "Choose a validated dossier from the applicant queue."}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-surface-alt p-1.5">
          <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.13em] text-ink-muted">Workspace view</p>
          <div className="flex gap-1" role="group" aria-label="Choose workspace view">
            <button
              type="button"
              onClick={() => onWorkspaceModeChange("officer")}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left transition ${
                workspaceMode === "officer" ? "bg-white text-ink shadow-sm" : "text-ink-muted hover:text-ink"
              }`}
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-violet-100 text-[11px] font-bold text-violet-700">AO</span>
              <span className="hidden sm:block">
                <span className="block text-xs font-semibold">Officer View</span>
                <span className="block text-[10px] text-ink-muted">Review applicants</span>
              </span>
            </button>
            <button
              type="button"
              onClick={() => onWorkspaceModeChange("admin")}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-left transition ${
                workspaceMode === "admin" ? "bg-[#102A4D] text-white shadow-sm" : "text-ink-muted hover:text-ink"
              }`}
            >
              <span className={`flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold ${workspaceMode === "admin" ? "bg-white/15 text-white" : "bg-blue-100 text-blue-800"}`}>IT</span>
              <span className="hidden sm:block">
                <span className="block text-xs font-semibold">IT Admin View</span>
                <span className={`block text-[10px] ${workspaceMode === "admin" ? "text-blue-100/75" : "text-ink-muted"}`}>System diagnostics</span>
              </span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
