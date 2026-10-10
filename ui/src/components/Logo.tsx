export default function Logo({ className = "h-10 w-10" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 72" className={className} xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id="rsuShield" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#8B5CF6" />
          <stop offset="100%" stopColor="#5B21B6" />
        </linearGradient>
      </defs>
      <path
        d="M32 2 L60 12 V34 C60 52 48 64 32 70 C16 64 4 52 4 34 V12 Z"
        fill="url(#rsuShield)"
        stroke="#D4AF37"
        strokeWidth="2"
      />
      <path
        d="M32 7 L55 15.5 V34 C55 48.5 45.5 58.5 32 64 C18.5 58.5 9 48.5 9 34 V15.5 Z"
        fill="none"
        stroke="#D4AF37"
        strokeOpacity="0.55"
        strokeWidth="1"
      />
      <text
        x="32"
        y="39"
        textAnchor="middle"
        fontFamily="Georgia, 'Times New Roman', serif"
        fontWeight="700"
        fontSize="20"
        fill="#FFFFFF"
      >
        RSU
      </text>
      <path
        d="M20 46 L32 51 L44 46"
        stroke="#D4AF37"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
