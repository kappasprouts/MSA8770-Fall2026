"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Logo from "./Logo";

const links = [
  { href: "/home", label: "Home", icon: "⌂" },
  { href: "/processing-dashboard", label: "Processing Dashboard", icon: "▤" },
  { href: "/applicant-review", label: "Applicant Review & Error Queue", icon: "▣" },
];

export default function PortalNav() {
  const pathname = usePathname();
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  return (
    <aside className="flex w-full shrink-0 flex-col bg-[#102A4D] text-white md:sticky md:top-0 md:min-h-screen md:w-64 md:self-start">
      <Link href="/home" className="flex items-center gap-3 border-b border-white/10 px-5 py-5" aria-label="Riverview State University home">
        <Logo className="h-12 w-12 shrink-0" />
        <div><p className="font-serif text-base font-bold leading-tight">RiverView State</p>
          <p className="mt-1 text-[10px] font-semibold uppercase tracking-[.15em] text-blue-100/80">Admissions Review</p>
        </div>
      </Link>
      <nav aria-label="Admissions navigation" className="space-y-1 px-3 py-5">
        {links.map(link => <Link key={link.href} href={link.href}
          aria-current={isActive(link.href) ? "page" : undefined}
          className={`flex items-center gap-3 rounded-lg px-3 py-3 text-sm font-semibold transition ${isActive(link.href) ? "bg-[#2C5583] text-white" : "text-blue-100/90 hover:bg-white/10 hover:text-white"}`}>
          <span className="w-5 text-center text-base" aria-hidden="true">{link.icon}</span>{link.label}
        </Link>)}
      </nav>
      <div className="mt-auto border-t border-white/10 p-5"><p className="text-xs font-medium text-blue-200/70">Tech Support · Coming Soon</p><p className="mt-3 text-[11px] leading-5 text-blue-200/60">Human decisions remain with authorized admissions personnel.</p></div>
    </aside>
  );
}
