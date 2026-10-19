export default function Logo({ className = "h-10 w-10" }: { className?: string }) {
  return (
    <svg viewBox="0 0 72 72" className={className} xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="36" cy="36" r="34" fill="#FFFFFF" stroke="#FFFFFF" strokeWidth="2" />
      <circle cx="36" cy="36" r="30" fill="#12284B" stroke="#DCE6F5" strokeWidth="1.5" />
      <circle cx="36" cy="36" r="26" fill="none" stroke="#FFFFFF" strokeOpacity="0.8" strokeWidth="1" />

      <path d="M20 25 L36 17 L52 25 Z" fill="#FFFFFF" />
      <rect x="21" y="27" width="30" height="3" rx="1" fill="#FFFFFF" />
      <rect x="24" y="31" width="4" height="12" rx="0.8" fill="#FFFFFF" />
      <rect x="34" y="31" width="4" height="12" rx="0.8" fill="#FFFFFF" />
      <rect x="44" y="31" width="4" height="12" rx="0.8" fill="#FFFFFF" />
      <rect x="21" y="43" width="30" height="3" rx="1" fill="#FFFFFF" />

      <path d="M17 50 C23 46 28 46 34 50 C40 54 46 54 55 49" fill="none" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" />
      <path d="M18 55 C24 51 29 51 35 55 C41 59 47 59 54 54" fill="none" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
