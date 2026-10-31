export default function Logo({ className = "h-10 w-10" }: { className?: string }) {
  return (
    <svg viewBox="0 0 72 72" className={className} xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">
      <circle cx="36" cy="36" r="34" fill="var(--color-surface, #fffdf9)" stroke="var(--color-accent, #6d28d9)" strokeWidth="2" />
      <circle cx="36" cy="36" r="30" fill="var(--color-accent, #6d28d9)" stroke="var(--color-panel-header, #ede3f9)" strokeWidth="1.5" />
      <circle cx="36" cy="36" r="26" fill="none" stroke="var(--color-surface, #fffdf9)" strokeOpacity="0.8" strokeWidth="1" />

      <g fill="var(--color-surface, #fffdf9)">
        <path d="M20 25 L36 17 L52 25 Z" />
        <rect x="21" y="27" width="30" height="3" rx="1" />
        <rect x="24" y="31" width="4" height="12" rx="0.8" />
        <rect x="34" y="31" width="4" height="12" rx="0.8" />
        <rect x="44" y="31" width="4" height="12" rx="0.8" />
        <rect x="21" y="43" width="30" height="3" rx="1" />
      </g>

      <g fill="none" stroke="var(--color-surface, #fffdf9)" strokeWidth="2" strokeLinecap="round">
        <path d="M17 50 C23 46 28 46 34 50 C40 54 46 54 55 49" />
        <path d="M18 55 C24 51 29 51 35 55 C41 59 47 59 54 54" />
      </g>
    </svg>
  );
}
