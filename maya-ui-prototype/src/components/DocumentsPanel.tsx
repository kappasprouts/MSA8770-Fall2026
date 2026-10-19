"use client";

import { useState } from "react";
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
  const [selectedFile, setSelectedFile] = useState(documents[0]?.file ?? "");

  const selected = documents.find((document) => document.file === selectedFile) ?? documents[0];

  if (documents.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface-alt px-5 py-14 text-center">
        <p className="font-semibold text-ink">No source documents found</p>
        <p className="mt-1 text-sm text-ink-muted">No document records are available for this applicant.</p>
      </div>
    );
  }

  return (
    <div className="grid min-h-[620px] gap-5 lg:grid-cols-[330px_minmax(0,1fr)]">
      <div className="rounded-xl border border-border bg-surface-alt p-3">
        <div className="px-2 pb-3 pt-1">
          <h3 className="font-semibold text-ink">Source documents</h3>
          <p className="mt-1 text-xs text-ink-muted">{documents.length} files attached to {appId}</p>
        </div>
        <div className="space-y-2">
          {documents.map((doc) => {
            const active = doc.file === selected?.file;
            return (
              <button
                key={doc.file}
                type="button"
                onClick={() => setSelectedFile(doc.file)}
                className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left transition ${
                  active ? "border-accent bg-white shadow-sm" : "border-transparent hover:border-border hover:bg-white"
                }`}
              >
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-red-50 text-[10px] font-bold text-red-600">
                  PDF
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-ink">{doc.label}</span>
                  <span className="mt-0.5 block text-xs text-ink-muted">
                    {doc.access === "withheld"
                      ? "Human-only document"
                      : doc.pages
                        ? `${doc.pages.length} page${doc.pages.length === 1 ? "" : "s"} analyzed`
                        : "Available for review"}
                  </span>
                </span>
                <span className={`h-2 w-2 shrink-0 rounded-full ${doc.access === "withheld" ? "bg-amber-500" : "bg-emerald-500"}`} />
              </button>
            );
          })}
        </div>
      </div>

      {selected && (
        <div className="overflow-hidden rounded-xl border border-border bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
            <div>
              <p className="font-semibold text-ink">{selected.label}</p>
              <p className="mt-0.5 text-xs text-ink-muted">
                {selected.access === "withheld" ? selected.reason ?? "Withheld from AI analysis" : "Included in AI analysis"}
              </p>
            </div>
            <a
              href={documentUrl(appId, selected.file)}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-border bg-surface-alt px-3 py-2 text-xs font-semibold text-accent hover:bg-panel-header"
            >
              Open full PDF ↗
            </a>
          </div>
          <iframe
            src={`${documentUrl(appId, selected.file)}#toolbar=1&navpanes=0`}
            title={selected.label}
            className="h-[550px] w-full bg-slate-100"
          />
        </div>
      )}
    </div>
  );
}
