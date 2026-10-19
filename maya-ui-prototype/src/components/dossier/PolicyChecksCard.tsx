"use client";

import { useState } from "react";
import type { PolicyAssessmentItem } from "@/lib/types";

const ALIGNMENT_ICON: Record<string, string> = {
  aligned: "✅",
  partially_aligned: "⚠️",
  not_aligned: "⛔",
};

const ALIGNMENT_LABEL: Record<string, string> = {
  aligned: "Aligned",
  partially_aligned: "Partial",
  not_aligned: "Not aligned",
};

const VISIBLE_COUNT = 4;

export default function PolicyChecksCard({ items, detailed = false }: { items: PolicyAssessmentItem[]; detailed?: boolean }) {
  const [expanded, setExpanded] = useState(false);

  if (!items.length) {
    return null;
  }

  const visible = detailed || expanded ? items : items.slice(0, VISIBLE_COUNT);

  return (
    <div className="rounded-xl border border-card-amber-border bg-card-amber-bg p-5">
      <div className="mb-4">
        <h3 className="text-base font-semibold text-card-amber-text">Admissions policy checks</h3>
        <p className="mt-1 text-sm text-ink-muted">Rules retrieved for this applicant and the model&apos;s evidence-grounded alignment.</p>
      </div>

      <div className="space-y-3">
        {visible.map((item, idx) => (
          <div key={`${item.policy_id ?? idx}`} className="rounded-xl border border-card-amber-border/80 bg-white/70 p-4 text-sm">
            <div className="flex items-start justify-between gap-3">
              <span className="flex items-start gap-2 text-ink">
                <span>{ALIGNMENT_ICON[item.alignment ?? ""] ?? "➖"}</span>
                <span>
                  <span className="font-semibold">{item.policy_id ?? "Policy"}</span>
                  <span className="ml-2 text-ink-muted">{item.title ?? item.criterion}</span>
                </span>
              </span>
              <span className="shrink-0 rounded-full bg-surface-alt px-2.5 py-1 text-xs font-semibold text-ink-muted">
                {ALIGNMENT_LABEL[item.alignment ?? ""] ?? item.alignment ?? "—"}
              </span>
            </div>
            {(item.assessment || item.findings) && (
              <p className="mt-2 leading-6 text-ink-muted">{item.assessment ?? item.findings}</p>
            )}
            {item.evidence && item.evidence.length > 0 && (
              <p className="mt-2 text-xs text-ink-muted">
                Evidence: {item.evidence.map((entry) => `${entry.document ?? "source"} p.${entry.page ?? "?"}`).join("; ")}
              </p>
            )}
          </div>
        ))}
      </div>

      {!detailed && items.length > VISIBLE_COUNT && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-3 text-xs font-medium text-card-amber-text hover:underline"
        >
          {expanded ? "View less ↑" : `View all ${items.length} checks ↓`}
        </button>
      )}
    </div>
  );
}
