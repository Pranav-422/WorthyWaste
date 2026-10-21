import type { AgentAction, TraceStep } from "@/lib/types";

const KIND: Record<TraceStep["kind"], { label: string; dot: string }> = {
  perception: { label: "Saw", dot: "bg-[#2563eb]" },
  decision: { label: "Decided", dot: "bg-marigold" },
  action: { label: "Did", dot: "bg-leaf" },
  human: { label: "Person", dot: "bg-brick" },
};

const SHOWN = ["why", "verdict", "confidence", "status", "heaps", "faces_blurred", "latency_ms", "attempt", "error", "note", "threshold"];

function value(k: string, v: unknown): string {
  if (k === "confidence" || k === "threshold") return `${Math.round(Number(v) * 100)}%`;
  if (k === "latency_ms") return `${Math.round(Number(v))} ms`;
  return String(v);
}

/** The agent's perception → decision → action steps, as a timeline. */
export function AgentTrace({ trace }: { trace: TraceStep[] }) {
  return (
    <ol className="relative space-y-3 border-l-2 border-line pl-5">
      {trace.map((s, i) => (
        <li key={i} className="relative">
          <span className={`absolute top-1.5 -left-[27px] h-3 w-3 rounded-full ring-4 ring-paper ${KIND[s.kind]?.dot ?? "bg-slate"}`} />
          <p className="text-[11px] font-semibold tracking-wide text-slate uppercase">
            {KIND[s.kind]?.label ?? s.kind}
          </p>
          <p className="font-semibold leading-snug">{s.title}</p>
          <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-slate">
            {SHOWN.filter((k) => s[k] !== undefined && s[k] !== null && s[k] !== "").map((k) => (
              <span key={k}>
                {k.replace("_", " ")}: <b className="text-ink tabular">{value(k, s[k])}</b>
              </span>
            ))}
          </p>
        </li>
      ))}
    </ol>
  );
}

export const ACTION_LABEL: Record<AgentAction, { text: string; tone: string }> = {
  accept: { text: "Accepted", tone: "bg-leaf text-white" },
  recapture: { text: "Retake photo", tone: "bg-marigold text-ink" },
  needs_approval: { text: "Needs a person", tone: "bg-brick text-white" },
  accept_unverified: { text: "Recorded, unverified", tone: "bg-kraft-deep text-ink" },
};
