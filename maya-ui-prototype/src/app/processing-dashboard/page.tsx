"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import PortalNav from "@/components/PortalNav";

type ApplicantRow = {
  app_id: string; first_name: string; last_name: string;
  intended_major: string | null; status: string;
  final_decision: string | null; has_dossier: boolean;
};

function statusLabel(value: string | null | undefined) {
  if (!value) return "Not recorded";
  return value.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, letter => letter.toUpperCase());
}

export default function ProcessingDashboard() {
  const [rows, setRows] = useState<ApplicantRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("ALL");
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/processing-dashboard", { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Unable to load applicants");
      setRows(body.applicants);
    } catch (err) { setError(err instanceof Error ? err.message : "Request failed"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const count = (status: string) => rows.filter(row => row.status === status).length;
  const filtered = useMemo(() => rows.filter(row => {
    const found = [row.app_id, row.first_name, row.last_name, row.intended_major ?? ""].join(" ").toLowerCase().includes(search.toLowerCase());
    return found && (filter === "ALL" || row.status === filter);
  }), [rows,search,filter]);
  const statuses = [...new Set(rows.map(row => row.status))].sort();
  return <div className="min-h-screen bg-[#F5F7FB] text-[#17213B] md:flex">
    <PortalNav />
    <main className="mx-auto w-full max-w-7xl space-y-5 p-4 md:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-widest text-[#526E9C]">Application processing</p><h1 className="mt-2 text-2xl font-bold text-[#102A4D]">Admissions Processing Dashboard</h1><p className="mt-2 text-sm text-[#68738B]">Track applications, packet completeness, and dossier availability.</p></div><Link href="/applicant-review" className="rounded-lg border border-[#D8E3EF] bg-white px-4 py-2 text-sm font-semibold text-[#2D5E96] hover:bg-[#EEF5FC]">Open Applicant Review →</Link></div>
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Application counts">
        {[["All applicants",rows.length],["Dossier ready",rows.filter(row => row.has_dossier).length],["Awaiting materials",count("AWAITING_MATERIALS")],["Incomplete",count("INCOMPLETE")]].map(([name,value]) => <div key={name} className="rounded-xl border border-[#DDE3EE] bg-white p-5 shadow-[0_3px_15px_rgba(16,42,77,.035)]"><p className="text-xs text-[#68738B]">{name}</p><p className="mt-2 text-3xl font-bold text-[#102A4D]">{loading ? "—" : error ? "—" : value}</p></div>)}
      </section>
      <section className="rounded-xl border border-[#DDE3EE] bg-white p-5 shadow-[0_3px_15px_rgba(16,42,77,.035)]"><h2 className="font-semibold">Latest ingestion batch</h2><p className="mt-3 text-sm text-[#667590]">Batch execution status is not connected to this prototype view. The ledger below reads live applicant records from PostgreSQL.</p><p className="mt-2 text-xs text-[#74819A]">{!loading && !error ? `${count("READY_FOR_REVIEW")} applicant(s) await dossier generation.` : ""}</p></section>
      <section className="rounded-xl border border-[#DDE3EE] bg-white p-5 shadow-[0_3px_15px_rgba(16,42,77,.035)]"><h2 className="font-semibold">Applicant Processing Ledger</h2>
        <div className="mt-4 flex flex-wrap gap-2"><input aria-label="Search applicants" className="min-w-48 flex-1 rounded-md border border-[#D9E3EF] bg-[#F7F9FC] px-3 py-2 text-sm" placeholder="Search by ID, name, or major…" value={search} onChange={event=>setSearch(event.target.value)}/><select aria-label="Filter by application status" className="rounded-md border border-[#D9E3EF] bg-[#F7F9FC] px-3 py-2 text-sm outline-offset-2 focus-visible:outline-[#386CA6]" value={filter} onChange={event=>setFilter(event.target.value)}><option value="ALL">All statuses</option>{statuses.map(s=><option key={s} value={s}>{statusLabel(s)}</option>)}</select><button type="button" onClick={()=>void refresh()} className="rounded-md border border-[#D9E3EF] bg-white px-4 py-2 text-sm text-[#2D5E96]">Refresh</button></div>
        {loading ? <p className="py-10 text-sm">Loading applicant records…</p> : error ? <p role="alert" className="py-6 text-sm text-red-700">{error}</p> : rows.length === 0 ? <p className="py-8 text-sm">No applications have been ingested yet.</p> : <div className="mt-5 overflow-x-auto"><table className="w-full text-left text-sm"><caption className="mb-3 text-left text-xs text-[#68738B]">{filtered.length} of {rows.length} applicant(s)</caption><thead className="bg-[#EAF1FA] text-xs uppercase text-[#254669]"><tr>{["Applicant ID","Applicant","Intended Major","Application Status","Final Decision","Action"].map(label=><th key={label} className="px-3 py-3">{label}</th>)}</tr></thead><tbody>{filtered.map(row=><tr key={row.app_id} className="border-b border-[#E6ECF4] hover:bg-[#F7FAFF]"><td className="px-3 py-3 font-bold">{row.app_id}</td><td className="px-3 py-3">{row.first_name} {row.last_name}</td><td className="px-3 py-3">{row.intended_major ?? "—"}</td><td className="px-3 py-3"><span className="rounded-full bg-[#EDF3FB] px-2 py-1 text-xs font-medium text-[#315A85]">{statusLabel(row.status)}</span></td><td className="px-3 py-3">{statusLabel(row.final_decision)}</td><td className="px-3 py-3">{row.has_dossier ? <Link className="font-semibold text-[#255E9C] underline" href={`/applicant-review?appId=${encodeURIComponent(row.app_id)}`}>Open dossier →</Link> : <span className="text-[#74819A]">Not available</span>}</td></tr>)}</tbody></table></div>}
        <p className="mt-4 text-xs text-[#74819A]">Dossier links are available only when a generated dossier exists.</p>
      </section>
    </main>
  </div>;
}
