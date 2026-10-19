"use client";

import { useState } from "react";
import type { ApplicantDossier } from "@/lib/types";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="text-ink-muted">{label}</span>
      <span className="text-right font-medium text-ink">{value}</span>
    </div>
  );
}

export default function ApplicantInfoCard({ dossier }: { dossier: ApplicantDossier }) {
  const [expanded, setExpanded] = useState(false);

  const demo = dossier.applicant_demographics ?? {};
  const academic = dossier.academic_profile ?? {};
  const facts = (academic.document_facts ?? {}) as Record<string, unknown>;

  const name = [demo.first_name, demo.last_name].filter(Boolean).join(" ") || "Unknown applicant";

  const str = (value: unknown) => (value === null || value === undefined || value === "" ? "—" : String(value));

  return (
    <div className="rounded-xl border border-border bg-surface p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">Applicant profile</p>
          <h3 className="mt-1 text-lg font-semibold text-ink">{name}</h3>
        </div>
        <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">
          {str(demo.application_status ?? "Ready for review")}
        </span>
      </div>

      <div className="divide-y divide-border">
        <Row label="High School" value={str(demo.name_of_hs)} />
        <Row label="Application Type" value={str(demo.application_type)} />
        <Row label="Residency" value={str(demo.residency_status)} />
        <Row label="Intended Major" value={str(demo.intended_major ?? demo.intended_program)} />
        <Row label="Unweighted GPA" value={str(facts.unweighted_gpa ?? academic.gpa)} />
        <Row label="Weighted GPA" value={str(facts.weighted_gpa)} />
        <Row label="SAT (Superscore)" value={str(facts.sat_superscore ?? academic.sat_total)} />

        {expanded && (
          <>
            <Row label="ACT (Superscore)" value={str(facts.act_superscore)} />
            <Row label="Class Rank" value={str(facts.class_rank)} />
            <Row label="Expected Graduation" value={str(facts.expected_graduation)} />
            <Row label="Country" value={str(demo.country)} />
            <Row label="Region" value={str(demo.region)} />
            <Row
              label="Admission Term"
              value={[demo.admission_term, demo.admission_year].filter(Boolean).join(" ") || "—"}
            />
          </>
        )}
      </div>

      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="mt-3 text-xs font-semibold text-accent hover:underline"
      >
        {expanded ? "View less ↑" : "View more ↓"}
      </button>
    </div>
  );
}
