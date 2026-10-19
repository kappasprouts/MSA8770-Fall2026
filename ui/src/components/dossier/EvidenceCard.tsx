"use client";

import { useState } from "react";
import type { StrengthItem } from "@/lib/types";

const VISIBLE_COUNT = 4;

export default function EvidenceCard({ strengths }: { strengths: StrengthItem[] }) {
  const [expanded, setExpanded] = useState(false);

  if (!strengths.length) {
    return null;
  }

  const visible = expanded ? strengths : strengths.slice(0, VISIBLE_COUNT);

  return (
    <div className="rounded-xl border border-card-pink-border bg-card-pink-bg p-4">
      <h3 className="mb-3 text-sm font-semibold text-card-pink-text">Key Evidence &amp; Citations</h3>

      <ul className="list-disc space-y-1.5 pl-4 text-sm text-ink">
        {visible.map((item, idx) => (
          <li key={idx}>{item.strength}</li>
        ))}
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
