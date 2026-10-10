import type { OriginalDocument } from "@/lib/types";

function documentUrl(appId: string, file: string) {
  return `/api/documents?appId=${encodeURIComponent(appId)}&file=${encodeURIComponent(file)}`;
}

export default function DocumentsPanel({
  appId,
  documents,
}: {
  appId: string;
  documents: OriginalDocument[];
}) {
  return (
    <div className="flex h-full min-h-0 flex-col rounded-xl border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border bg-panel-header px-4 py-3">
        <h2 className="text-sm font-semibold text-ink">Original Documents</h2>
        <span className="text-xs text-ink-muted">↕ Scroll</span>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {documents.length === 0 && (
          <p className="text-sm text-ink-muted">No source documents found on disk for this applicant.</p>
        )}

        {documents.map((doc) => {
          const url = documentUrl(appId, doc.file);
          const previewUrl = `${url}#toolbar=0&navpanes=0&scrollbar=0`;

          return (
            <div key={doc.file} className="rounded-xl border border-border bg-surface-alt p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-red-100 text-xs font-bold text-red-600">
                    PDF
                  </span>
                  <div>
                    <p className="text-sm font-medium text-ink">{doc.label}</p>
                    <p className="text-xs text-ink-muted">
                      {doc.pages ? `${doc.pages.length} page${doc.pages.length === 1 ? "" : "s"}` : "—"}
                      {doc.access === "withheld" && (
                        <span className="ml-2 text-status-warn">Withheld from AI</span>
                      )}
                    </p>
                  </div>
                </div>

                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="shrink-0 text-xs font-medium text-accent hover:underline"
                >
                  View Full ↗
                </a>
              </div>

              {doc.access === "withheld" && doc.reason && (
                <p className="mb-2 text-xs text-ink-muted">Reason: {doc.reason}</p>
              )}

              <iframe
                src={previewUrl}
                title={doc.label}
                className="h-44 w-full rounded-md border border-border bg-white"
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
