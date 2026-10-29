"use client";

import { useMemo, useState } from "react";
import type { ApplicantSummary } from "@/lib/types";
import Logo from "./Logo";

export type SidebarSection = "dashboard" | "queue" | "exceptions" | "policies" | "documents" | "reports" | "settings";

const NAV_ITEMS: Array<{ id: SidebarSection; label: string; icon: "home" | "users" | "warning" | "policy" | "document" | "report" | "settings" }> = [
  { id: "queue", label: "Applicant Queue", icon: "users" },
  { id: "exceptions", label: "Error Queue", icon: "warning" },
  { id: "policies", label: "Policies", icon: "policy" },
  { id: "documents", label: "Documents", icon: "document" },
  { id: "reports", label: "Reports", icon: "report" },
  { id: "settings", label: "Settings", icon: "settings" },
];

function NavIcon({ name }: { name: (typeof NAV_ITEMS)[number]["icon"] }) {
  const paths = {
    home: <path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V10.5Z" />,
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
    warning: <><path d="M12 3 2.5 20h19L12 3Z" /><path d="M12 9v4M12 17h.01" /></>,
    policy: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h8M8 11h8M8 15h5" /></>,
    document: <><path d="M6 2h8l4 4v16H6z" /><path d="M14 2v6h6M9 13h6M9 17h6" /></>,
    report: <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V22H9.6v-.9A1.7 1.7 0 0 0 8.5 19.5a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.1 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H2V9.6h.9A1.7 1.7 0 0 0 4.5 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.1a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V2h4v.9A1.7 1.7 0 0 0 15.5 4.5a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.9 9c.1.4.3.7.6 1 .3.3.7.4 1.1.4h.4v4h-.9A1.7 1.7 0 0 0 19.4 15Z" /></>,
  };

  return <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export default function ApplicantSidebar({
  applicants,
  selectedAppId,
  onSelect,
  activeSection,
  onSectionSelect,
}: {
  applicants: ApplicantSummary[];
  selectedAppId: string;
  onSelect: (appId: string) => void;
  activeSection: SidebarSection;
  onSectionSelect: (section: SidebarSection) => void;
}) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => applicants.filter((applicant) => applicant.id.toLowerCase().includes(query.toLowerCase())),
    [applicants, query],
  );

  return (
    <aside className="flex w-full shrink-0 flex-col bg-[#102A4D] text-white lg:sticky lg:top-0 lg:h-screen lg:w-72">
      <div className="flex items-center gap-3 border-b border-white/10 px-5 py-5">
        <Logo className="h-13 w-13 shrink-0" />
        <div>
          <p className="font-serif text-lg font-bold leading-tight">RiverView State</p>
          <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-blue-100/80">
            Admissions Review
          </p>
        </div>
      </div>

      <nav className="space-y-1 border-b border-white/10 px-3 py-4" aria-label="Primary navigation">
        {NAV_ITEMS.map((item, index) => {
          const active = activeSection === item.id;
          return (
            <div key={item.id} className={index === NAV_ITEMS.length - 1 ? "border-t border-white/10 pt-3 mt-3" : ""}>
              <button
                type="button"
                onClick={() => onSectionSelect(item.id)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium transition ${
                  active ? "bg-[#244E7D] text-white shadow-sm" : "text-blue-50/80 hover:bg-white/8 hover:text-white"
                }`}
              >
                <NavIcon name={item.icon} />
                <span>{item.label}</span>
              </button>
            </div>
          );
        })}
      </nav>

      <div className="px-4 pt-5">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-100/70">Applicant queue</p>
          <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-white/75">{applicants.length}</span>
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search applicants..."
          className="mt-3 w-full rounded-lg border border-white/15 bg-white/8 px-3 py-2 text-sm text-white outline-none placeholder:text-white/45 focus:border-blue-200"
        />
      </div>

      <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-4" aria-label="Applicant queue">
        {filtered.length === 0 && (
          <p className="rounded-lg border border-white/10 px-3 py-4 text-center text-sm text-white/55">
            No applicants found
          </p>
        )}
        {filtered.map((applicant) => {
          const active = applicant.id === selectedAppId;
          return (
            <button
              key={applicant.id}
              type="button"
              onClick={() => {
                onSelect(applicant.id);
                onSectionSelect("queue");
              }}
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition ${
                active ? "bg-[#244E7D] text-white shadow-lg" : "text-white/80 hover:bg-white/10 hover:text-white"
              }`}
            >
              <span
                className={`flex h-9 w-9 items-center justify-center rounded-lg text-xs font-bold ${
                  active ? "bg-white/15 text-white" : "bg-white/10 text-white"
                }`}
              >
                {applicant.id.slice(-3)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold">{applicant.id}</span>
                <span className={`block text-xs ${active ? "text-blue-100/70" : "text-white/45"}`}>
                  Ready for officer review
                </span>
              </span>
              {active && <span className="rounded-full bg-red-500 px-2 py-0.5 text-[10px] font-bold">HR</span>}
            </button>
          );
        })}
      </nav>

      <div className="border-t border-white/10 p-4">
        <div className="rounded-xl bg-white/8 p-3 text-xs leading-relaxed text-white/60">
          <p className="font-semibold text-white/85">Human decision required</p>
          <p className="mt-1">AI summaries are advisory and never make the final admissions decision.</p>
        </div>
      </div>
    </aside>
  );
}
