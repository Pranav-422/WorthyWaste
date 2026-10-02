// Material pictograms. Placeholders for the real-photo icons the Design Doc calls for.

type P = { className?: string };
const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2.2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  viewBox: "0 0 48 48",
};

export function MaterialIcon({ code, className }: { code: string } & P) {
  switch (code) {
    case "plastic":
      return (
        <svg {...base} className={className} aria-hidden>
          <path d="M20 5h8v5l3 5v26a3 3 0 0 1-3 3h-8a3 3 0 0 1-3-3V15l3-5z" />
          <path d="M17 22h14M17 32h14" />
        </svg>
      );
    case "cardboard":
      return (
        <svg {...base} className={className} aria-hidden>
          <path d="M6 16l18-8 18 8v20l-18 8-18-8z" />
          <path d="M6 16l18 8 18-8M24 24v20M15 12l18 8" />
        </svg>
      );
    case "metal":
      return (
        <svg {...base} className={className} aria-hidden>
          <ellipse cx="24" cy="10" rx="11" ry="4" />
          <path d="M13 10v28c0 2.2 4.9 4 11 4s11-1.8 11-4V10" />
          <path d="M13 18c0 2.2 4.9 4 11 4s11-1.8 11-4" />
        </svg>
      );
    case "paper":
      return (
        <svg {...base} className={className} aria-hidden>
          <path d="M8 10h26v28a4 4 0 0 0 4 4H12a4 4 0 0 1-4-4z" />
          <path d="M34 18h6v20a4 4 0 0 1-4 4" />
          <path d="M14 17h14M14 24h14M14 31h8" />
        </svg>
      );
    case "wire":
      return (
        <svg {...base} className={className} aria-hidden>
          <ellipse cx="24" cy="24" rx="15" ry="15" />
          <ellipse cx="24" cy="24" rx="10" ry="10" />
          <ellipse cx="24" cy="24" rx="5" ry="5" />
          <path d="M39 24h5" />
        </svg>
      );
    case "glass":
      return (
        <svg {...base} className={className} aria-hidden>
          <path d="M17 5h14v6l-2 3v3c4 2 6 5 6 9v13a4 4 0 0 1-4 4H17a4 4 0 0 1-4-4V26c0-4 2-7 6-9v-3l-2-3z" />
          <path d="M14 30h20" />
        </svg>
      );
    default:
      return <svg {...base} className={className} aria-hidden><circle cx="24" cy="24" r="16" /></svg>;
  }
}

/** Rupee whose stroke is a recycling loop, inside a bale tag. */
export function Logo({ className }: P) {
  return (
    <svg viewBox="0 0 48 48" className={className} aria-hidden>
      <path d="M8 6h24l10 10v26H8z" fill="#1E7F4F" />
      <circle cx="33" cy="13" r="2.4" fill="#EFE6D2" />
      <g fill="none" stroke="#F2A900" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 18h16M16 24h16" />
        <path d="M22 18c6 0 6 9 0 9h-5l11 10" />
      </g>
      <path d="M30 33.5l-2 3.5 4 .5" fill="none" stroke="#F2A900" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function SpeakerIcon({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M4 9h4l5-4v14l-5-4H4z" fill="currentColor" />
      <path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12" />
    </svg>
  );
}

export function CameraIcon({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M4 7h3l2-3h6l2 3h3a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z" />
      <circle cx="12" cy="13" r="4" />
    </svg>
  );
}

export function CheckIcon({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

export function StopIcon({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6M12 16.5v.5" />
    </svg>
  );
}

export function QrIcon({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <path d="M14 14h3v3h-3zM18 18h3v3h-3zM14 20h2M20 14v2" />
    </svg>
  );
}

export function ScaleIcon({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <rect x="3" y="8" width="18" height="12" rx="2" />
      <path d="M7 8V6h10v2M12 14l3-3" />
    </svg>
  );
}
