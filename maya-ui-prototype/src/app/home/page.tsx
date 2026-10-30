import Link from "next/link";
import Image from "next/image";
import PortalNav from "@/components/PortalNav";
import Logo from "@/components/Logo";

const workspaces = [
  { href: "/processing-dashboard", title: "Processing Dashboard", detail: "Track application progress, completeness, and dossier readiness.", icon: "▤" },
  { href: "/applicant-review", title: "Applicant Review & Error Queue", detail: "Review applicant evidence, AI summaries, and exceptions.", icon: "▣" },
];

export default function HomePage() {
  return (
    <div className="min-h-screen bg-[#F5F7FB] text-[#17213B] md:flex">
      <PortalNav />
      <main className="mx-auto w-full max-w-7xl p-5 md:p-8 lg:p-10">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div><p className="text-[11px] font-bold uppercase tracking-[.17em] text-[#526E9C]">RiverView State University / Admissions</p><h1 className="mt-2 text-2xl font-bold md:text-3xl">Welcome to the Admissions Workspace</h1><p className="mt-2 text-sm text-[#68738B]">A secure workspace for application processing and human review.</p></div>
          <span className="rounded-full border border-[#D8E5F3] bg-[#EFF5FC] px-4 py-2 text-xs font-semibold text-[#31557C]">Admissions Operations</span>
        </header>
        <section className="overflow-hidden rounded-2xl border border-[#DDE3EE] bg-white shadow-[0_8px_30px_rgba(16,42,77,.05)]">
          <div className="relative h-56 w-full sm:h-72 lg:h-80">
            <Image src="/rsu-homepage-sunset.png" alt="Riverview State University campus at sunset" fill priority sizes="(max-width: 768px) 100vw, 1200px" className="object-cover" />
            <div className="absolute inset-0 bg-gradient-to-t from-[#102A4D]/70 via-transparent to-transparent" />
            <div className="absolute bottom-5 left-6 flex items-center gap-3 text-white"><Logo className="h-12 w-12" /><div><p className="font-serif text-xl font-bold">RiverView State University</p><p className="text-xs font-semibold uppercase tracking-[.16em] text-blue-100">Admissions Review</p></div></div>
          </div>
          <div className="grid gap-6 p-6 lg:grid-cols-[1.75fr_1fr] lg:p-8">
            <div><h2 className="text-xl font-bold text-[#102A4D]">Welcome to RiverView State University</h2><p className="mt-3 max-w-2xl text-sm leading-7 text-[#58677F]">Riverview State University, founded in 1913, is committed to academic excellence, innovative research, and service to our diverse communities. We empower students to achieve their full potential and make a positive impact in an ever-changing world.</p></div>
            <aside className="rounded-xl border border-[#DDE7F5] bg-[#F5F8FE] p-5"><h3 className="text-base font-bold text-[#102A4D]">Our Mission</h3><p className="mt-3 text-sm leading-6 text-[#58677F]">To provide an inclusive, transformative education that prepares students to lead, serve, and create a better tomorrow.</p></aside>
          </div>
          <div className="border-t border-[#E6ECF4] px-6 py-7 lg:px-8"><h3 className="mb-4 text-xs font-bold uppercase tracking-[.15em] text-[#60728F]">Choose a workspace</h3><nav aria-label="Admissions workspaces" className="grid gap-4 md:grid-cols-2">
            {workspaces.map(item => <Link key={item.href} href={item.href} className="group flex items-center gap-4 rounded-xl border border-[#DAE4F0] bg-[#F7F9FD] p-5 transition hover:border-[#7DA6D2] hover:bg-[#EDF4FC] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#386CA6]"><span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#E3EDFA] text-2xl font-bold text-[#1B4C7D]" aria-hidden="true">{item.icon}</span><span className="flex-1"><span className="block text-sm font-bold text-[#102A4D]">{item.title}</span><span className="mt-1 block text-xs leading-5 text-[#60728F]">{item.detail}</span></span><span className="font-bold text-[#2B5E94]" aria-hidden="true">→</span></Link>)}
          </nav></div>
        </section>
        <p className="mt-5 text-xs text-[#74819A]">AI-assisted summaries are advisory. Final admissions decisions require authorized human review.</p>
      </main>
    </div>
  );
}
