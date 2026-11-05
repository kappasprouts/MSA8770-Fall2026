export default function SummaryCard({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-card-green-border bg-card-green-bg p-4">
      <h3 className="mb-2 text-sm font-semibold text-card-green-text">AI Summary</h3>
      <p className="text-sm leading-relaxed text-ink">{text}</p>
    </div>
  );
}
