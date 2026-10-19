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

export default function PolicyChecksCard({ items }: { items: PolicyAssessmentItem[] }) {
  const [expanded, setExpanded] = useState(false);

  if (!items.length) {
    return null;
  }

  const visible = expanded ? items : items.slice(0, VISIBLE_COUNT);

  return (
    <div className="rounded-xl border border-card-amber-border bg-card-amber-bg p-4">
      <h3 className="mb-3 text-sm font-semibold text-card-amber-text">Policy Checks</h3>

      <div className="space-y-2">
        {visible.map((item, idx) => (
          <div key={`${item.policy_id ?? idx}`} className="flex items-start justify-between gap-3 text-sm">
            <span className="flex items-start gap-2 text-ink">
              <span>{ALIGNMENT_ICON[item.alignment ?? ""] ?? "➖"}</span>
              <span>
                <span className="font-medium">{item.policy_id ?? "—"}</span>{" "}
                <span className="text-ink-muted">{item.criterion}</span>
              </span>
            </span>
            <span className="shrink-0 text-xs font-medium text-ink-muted">
              {ALIGNMENT_LABEL[item.alignment ?? ""] ?? item.alignment ?? "—"}
            </span>
          </div>
        ))}
      </div>

      {items.length > VISIBLE_COUNT && (
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
