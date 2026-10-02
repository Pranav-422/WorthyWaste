"use client";

import { useState } from "react";

type Datum = { label: string; value: number; detail?: string };

/**
 * Single-series column chart: one hue (leaf), thin bars with 4px rounded tops anchored to the
 * baseline, recessive grid, hover tooltip with hit targets taller than the bars.
 */
export function ColumnChart({ data, format, height = 180 }: { data: Datum[]; format: (v: number) => string; height?: number }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  const nice = niceMax(max);
  const W = 600;
  const H = height;
  const padL = 64;
  const padB = 22;
  const padT = 8;
  const plotW = W - padL - 4;
  const plotH = H - padB - padT;
  const step = plotW / data.length;
  const bw = Math.min(36, step * 0.6);
  const ticks = [0, nice / 2, nice];

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Column chart">
        {ticks.map((t) => {
          const y = padT + plotH - (t / nice) * plotH;
          return (
            <g key={t}>
              <line x1={padL} x2={W - 4} y1={y} y2={y} stroke="#E2D5B8" strokeWidth={1} />
              <text x={padL - 6} y={y + 4} textAnchor="end" fontSize="11" fill="#5B6B63" className="tabular">
                {format(t)}
              </text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const h = (d.value / nice) * plotH;
          const x = padL + i * step + (step - bw) / 2;
          const y = padT + plotH - h;
          const r = Math.min(4, h);
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} tabIndex={0}>
              <rect x={padL + i * step} y={padT} width={step} height={plotH + padB} fill="transparent" />
              {h > 0 && (
                <path
                  d={`M${x},${padT + plotH} V${y + r} Q${x},${y} ${x + r},${y} H${x + bw - r} Q${x + bw},${y} ${x + bw},${y + r} V${padT + plotH} Z`}
                  fill={hover === null || hover === i ? "#1E7F4F" : "#8FBFA3"}
                />
              )}
              {(i === 0 || i === data.length - 1 || data.length <= 8) && (
                <text x={x + bw / 2} y={H - 6} textAnchor="middle" fontSize="11" fill="#5B6B63">
                  {d.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 rounded-lg bg-ink px-3 py-2 text-xs text-white shadow"
          style={{ left: `${((padL + hover * step + step / 2) / W) * 100}%`, top: 0 }}
        >
          <p className="opacity-70">{data[hover].detail ?? data[hover].label}</p>
          <p className="font-semibold tabular">{format(data[hover].value)}</p>
        </div>
      )}
    </div>
  );
}

/** Horizontal bars for a part-to-whole by category (single hue; identity is the row label). */
export function BarList({ data, format }: { data: Datum[]; format: (v: number) => string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className="space-y-2">
      {data.map((d) => (
        <li key={d.label} className="grid grid-cols-[7.5rem_1fr_auto] items-center gap-3 text-sm" title={d.detail}>
          <span className="truncate">{d.label}</span>
          <span className="h-2.5 rounded-r-[4px] bg-leaf" style={{ width: `${(d.value / max) * 100}%` }} />
          <span className="tabular text-slate">{format(d.value)}</span>
        </li>
      ))}
    </ul>
  );
}

function niceMax(v: number) {
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * exp >= v) return m * exp;
  return 10 * exp;
}
