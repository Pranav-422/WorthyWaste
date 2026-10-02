/** Semicircular 300–900 gauge. The number is the hero; the arc gives the range. */
export function ScoreMeter({ score, size = 220, dark = false }: { score: number; size?: number; dark?: boolean }) {
  const frac = Math.max(0, Math.min(1, (score - 300) / 600));
  const r = 80;
  const cx = 100;
  const cy = 96;
  const arc = (f: number) => {
    const a = Math.PI * (1 - f);
    return [cx + r * Math.cos(a), cy - r * Math.sin(a)] as const;
  };
  const [x, y] = arc(frac);
  const track = dark ? "rgba(255,255,255,0.18)" : "#E2D5B8";
  return (
    <svg viewBox="0 0 200 116" width={size} height={(size * 116) / 200} role="img" aria-label={`Score ${score} out of 900`}>
      <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke={track} strokeWidth="14" strokeLinecap="round" />
      <path
        d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x} ${y}`}
        fill="none"
        stroke="#1E7F4F"
        strokeWidth="14"
        strokeLinecap="round"
      />
      <circle cx={x} cy={y} r="9" fill="#fff" stroke="#1E7F4F" strokeWidth="4" />
      <text x={cx} y={cy - 14} textAnchor="middle" className="font-display tabular" fontSize="44" fontWeight="700" fill={dark ? "#fff" : "#1C2B22"}>
        {score}
      </text>
      <text x={cx - r} y={cy + 18} textAnchor="middle" fontSize="11" fill={dark ? "#cfd8d2" : "#5B6B63"}>300</text>
      <text x={cx + r} y={cy + 18} textAnchor="middle" fontSize="11" fill={dark ? "#cfd8d2" : "#5B6B63"}>900</text>
    </svg>
  );
}

/** The five score inputs with their weights and one-line reasons (Design principle 5: show the why). */
export function ScoreInputs({ inputs }: { inputs: Record<string, { value: number; weight: number; label: string; why: string }> }) {
  return (
    <ul className="space-y-3">
      {Object.entries(inputs).map(([k, v]) => {
        const pts = Math.round(v.value * v.weight * 600);
        const max = Math.round(v.weight * 600);
        return (
          <li key={k}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="font-semibold">
                {v.label} <span className="font-normal text-slate">· {Math.round(v.weight * 100)}%</span>
              </span>
              <span className="tabular text-slate">
                <span className="font-semibold text-ink">{pts}</span> / {max} pts
              </span>
            </div>
            <div className="mt-1 h-2 rounded-full bg-kraft-deep">
              <div className="h-2 rounded-full bg-leaf" style={{ width: `${v.value * 100}%` }} />
            </div>
            <p className="mt-1 text-xs text-slate">{v.why}</p>
          </li>
        );
      })}
    </ul>
  );
}
