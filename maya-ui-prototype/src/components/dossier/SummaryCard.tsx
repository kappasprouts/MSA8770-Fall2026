export default function SummaryCard({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-card-green-border bg-card-green-bg p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-base font-semibold text-card-green-text">AI-assisted holistic summary</h3>
        <span className="rounded-full border border-card-green-border bg-white/70 px-2.5 py-1 text-[11px] font-semibold text-card-green-text">
          Advisory only
        </span>
      </div>
      <p className="mt-3 text-sm leading-6 text-ink">{text}</p>
    </div>
  );
}
