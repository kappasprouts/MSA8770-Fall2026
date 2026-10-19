"use client";

import { useState } from "react";
import type { StrengthItem } from "@/lib/types";

const VISIBLE_COUNT = 4;

export default function EvidenceCard({ strengths }: { strengths: Array<StrengthItem | string> }) {
  const [expanded, setExpanded] = useState(false);

  if (!strengths.length) {
    return null;
  }

  const visible = expanded ? strengths : strengths.slice(0, VISIBLE_COUNT);

  return (
    <div className="rounded-xl border border-card-pink-border bg-card-pink-bg p-5">
      <h3 className="mb-3 text-base font-semibold text-card-pink-text">Key strengths and evidence</h3>

      <ul className="list-disc space-y-1.5 pl-4 text-sm text-ink">
        {visible.map((item, idx) => {
          const text = typeof item === "string" ? item : item.strength;
          const evidence = typeof item === "string" ? [] : item.evidence ?? [];
          return (
            <li key={idx}>
              <span>{text ?? "Evidence item"}</span>
              {evidence.length > 0 && (
                <span className="ml-2 text-xs text-ink-muted">
                  ({evidence[0].document ?? "source"}, p.{evidence[0].page ?? "?"})
                </span>
              )}
            </li>
          );
        })}
      </ul>

      {strengths.length > VISIBLE_COUNT && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-3 text-xs font-medium text-card-pink-text hover:underline"
        >
          {expanded ? "View less ↑" : `View all evidence (${strengths.length}) ↓`}
        </button>
      )}
    </div>
  );
}
