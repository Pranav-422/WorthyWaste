"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, get, logout, post } from "@/lib/api";
import { rupees, shortDate, timeAgo } from "@/lib/format";
import type { OpsOverview } from "@/lib/types";
import { ColumnChart } from "@/components/BarChart";
import { Logo } from "@/components/icons";

type View = "revenue" | "wards";

type RevenueRow = { id: number; stream: string; amount: number; note: string | null; created_at: string };

// Whole rupees for totals; paise where they matter (a ₹0.50 pickup fee must not read as ₹1).
const money = (n: number) =>
  `${n < 0 ? "−" : ""}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: Math.abs(n) < 100 && n % 1 ? 2 : 0 })}`;
const week = (d: string) => shortDate(d + " 00:00:00");

/**
 * The WorthyWaste team's dashboard: how the business earns (every stream from the pilot plan) and how
 * door-to-door collection is going ward by ward. Satin sees borrowers; this is our own P&L and ops.
 */
export function OpsApp({ demo }: { demo: boolean }) {
  const [view, setView] = useState<View>("revenue");
  const [o, setO] = useState<OpsOverview | null>(null);
  const [recent, setRecent] = useState<RevenueRow[]>([]);
  const [note, setNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [ov, rev] = await Promise.all([get<OpsOverview>("/ops/overview"), get<{ recent: RevenueRow[] }>("/ops/revenue")]);
    setO(ov);
    setRecent(rev.recent);
  }, []);
  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, 8000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  const bill = async (force: boolean) => {
    try {
      const r = await post<{ paid: number }>("/ops/billing/run", { force });
      setNote(`${r.paid} fee${r.paid === 1 ? "" : "s"} debited by AutoPay.`);
      refresh();
    } catch (e) {
      setNote((e as ApiError).message);
    }
  };

  return (
    <div className="min-h-dvh bg-paper lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="border-b border-line bg-ink text-kraft lg:sticky lg:top-0 lg:h-dvh lg:border-0">
        <div className="flex items-center gap-2 px-5 py-4">
          <Logo className="h-8 w-8" />
          <div>
            <p className="font-display text-lg font-semibold leading-none">WorthyWaste</p>
            <p className="text-xs opacity-70">Team view</p>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible">
          {(
            [
              ["revenue", "Revenue"],
              ["wards", "Wards & collection"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setView(k)}
              className={`shrink-0 rounded-lg px-3 py-2 text-left text-sm font-medium ${view === k ? "bg-white/12 text-white" : "text-kraft/80 hover:bg-white/6"}`}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="mx-5 mb-4 hidden lg:block">
          <button onClick={() => logout("ops")} className="text-xs text-kraft/70 underline">
            Log out
          </button>
        </div>
      </aside>

      <main className="min-w-0 px-4 py-6 lg:px-8">
        {note && <p className="mb-4 rounded-xl bg-ink p-3 text-sm text-kraft">{note}</p>}
        {!o ? <p className="text-slate">Loading…</p> : view === "revenue" ? <RevenueView o={o} recent={recent} /> : <WardsView o={o} demo={demo} onBill={bill} />}
      </main>
    </div>
  );
}

function PageTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-3xl font-semibold">{title}</h1>
      {sub && <p className="text-sm text-slate">{sub}</p>}
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "brick" | "leaf" }) {
  return (
    <div className="rounded-2xl border border-line bg-white p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate">{label}</p>
      <p className={`font-display text-3xl font-bold tabular ${tone === "brick" ? "text-brick" : tone === "leaf" ? "text-leaf" : ""}`}>{value}</p>
      {sub && <p className="text-xs text-slate">{sub}</p>}
    </div>
  );
}

const HOW: Record<string, string> = {
  pickup_fee: "₹0.50 on every door-to-door pickup, paid by the household with the collector's fee",
  loan_lead: "1% of each Satin loan we originate (verified, scored borrower)",
  compliance: "₹999/month per bulk generator for the day-by-day SWM compliance report",
  dealer_pro: "₹199/month per kabadi dealer for purchase bills and statements",
  insurance: "15% commission on ₹49/month accident + hospital cover",
  rewards: "Points households redeemed against fees — our cost until brands sponsor rewards",
};

function RevenueView({ o, recent }: { o: OpsOverview; recent: RevenueRow[] }) {
  const r = o.revenue;
  const earning = r.streams.filter((s) => s.stream !== "rewards");
  const max = Math.max(1, ...earning.map((s) => s.month));
  return (
    <>
      <PageTitle title="Revenue" sub="Pilot · last 30 days · all prices are pilot assumptions to agree with partners" />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Tile label="Net revenue · 30 days" value={money(r.net_month)} tone="leaf" sub={`${money(r.net_total)} since launch`} />
        <Tile label="Dealers on Pro" value={`${o.dealers_pro} / ${o.dealers}`} />
        <Tile label="Insured collectors" value={`${o.policies}`} />
        <Tile label="Bulk generators on compliance" value={`${o.bulk_subscribed}`} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[3fr_2fr]">
        <section className="rounded-2xl border border-line bg-white p-4">
          <h2 className="font-semibold">By stream · last 30 days</h2>
          <ul className="mt-3 space-y-3">
            {r.streams.map((s) => (
              <li key={s.stream}>
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="font-semibold">{s.label}</span>
                  <span className={`tabular font-semibold ${s.month < 0 ? "text-brick" : ""}`}>{money(s.month)}</span>
                </div>
                {s.stream !== "rewards" && (
                  <div className="mt-1 h-2 rounded-full bg-kraft-deep">
                    <div className="h-2 rounded-full bg-leaf" style={{ width: `${(Math.max(0, s.month) / max) * 100}%` }} />
                  </div>
                )}
                <p className="mt-0.5 text-xs text-slate">{HOW[s.stream]}</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-2xl border border-line bg-white p-4">
          <h2 className="font-semibold">Net revenue per week</h2>
          <p className="mb-2 text-xs text-slate">Last 12 weeks</p>
          <ColumnChart data={r.weekly.map((w) => ({ label: week(w.week_start), value: w.value, detail: `Week of ${week(w.week_start)}` }))} format={(v) => money(v)} height={200} />
        </section>
      </div>

      <section className="mt-4 rounded-2xl border border-line bg-white">
        <h2 className="px-4 pt-4 font-semibold">Latest entries</h2>
        <table className="w-full text-sm">
          <tbody>
            {recent.slice(0, 15).map((e) => (
              <tr key={e.id} className="border-t border-line first:border-0">
                <td className="py-2 pl-4 font-medium">{r.streams.find((s) => s.stream === e.stream)?.label ?? e.stream}</td>
                <td className="text-slate">{e.note}</td>
                <td className="text-slate">{timeAgo(e.created_at)}</td>
                <td className={`pr-4 text-right font-semibold tabular ${e.amount < 0 ? "text-brick" : ""}`}>{money(e.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function WardsView({ o, demo, onBill }: { o: OpsOverview; demo: boolean; onBill: (force: boolean) => void }) {
  const homes = o.wards.reduce((s, w) => s + w.homes, 0);
  const picked = o.wards.reduce((s, w) => s + w.picked_today, 0);
  const mandates = o.wards.reduce((s, w) => s + w.mandates, 0);
  return (
    <>
      <PageTitle title="Wards & collection" sub={`Door-to-door collection · ${shortDate(o.day + " 00:00:00")} · every pickup a QR scan at the door with GPS`} />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Tile label="Homes picked up today" value={`${picked} / ${homes}`} />
        <Tile label="On AutoPay" value={`${homes ? Math.round((100 * mandates) / homes) : 0}%`} sub={`${mandates} homes`} />
        <Tile label="Fees due" value={rupees(o.dues)} tone={o.dues ? "brick" : undefined} sub="no mandate or over limit" />
        <Tile label="Points liability" value={rupees(o.points_liability)} sub="unredeemed points, at face value" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[3fr_2fr]">
        <section className="rounded-2xl border border-line bg-white p-4">
          <h2 className="font-semibold">Homes separating their waste</h2>
          <p className="mb-2 text-xs text-slate">Share of pickups marked separated, per week</p>
          <ColumnChart data={o.separated_by_week.map((w) => ({ label: week(w.week_start), value: w.value, detail: `Week of ${week(w.week_start)}` }))} format={(v) => `${v}%`} />
        </section>
        <section className="rounded-2xl border border-line bg-white p-4">
          <h2 className="mb-2 font-semibold">Billing</h2>
          <p className="text-sm text-slate">
            AutoPay debits each fee a day after the pickup (the WhatsApp at pickup is the 24-hour notice) and monthly-plan
            fees after the month ends. A daily job runs this in the pilot.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button onClick={() => onBill(false)} className="h-11 rounded-xl bg-leaf px-4 font-semibold text-white">
              Run due debits
            </button>
            {demo && (
              <button onClick={() => onBill(true)} className="h-11 rounded-xl border border-line px-4 text-sm">
                Demo: debit everything now
              </button>
            )}
          </div>
        </section>
      </div>

      <section className="mt-4 overflow-x-auto rounded-2xl border border-line bg-white">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-kraft/50 text-left text-xs uppercase tracking-wide text-slate">
            <tr>
              <th className="px-4 py-3 font-medium">Ward</th>
              <th className="text-right font-medium">Homes</th>
              <th className="text-right font-medium">Bulk</th>
              <th className="text-right font-medium">Today</th>
              <th className="text-right font-medium">Separated · 30 d</th>
              <th className="px-4 text-right font-medium">AutoPay</th>
            </tr>
          </thead>
          <tbody>
            {o.wards.map((w) => (
              <tr key={w.ward} className="border-t border-line">
                <td className="px-4 py-3 font-medium">{w.ward}</td>
                <td className="text-right tabular">{w.homes}</td>
                <td className="text-right tabular">{w.bulk}</td>
                <td className="text-right tabular">{w.picked_today}</td>
                <td className="text-right tabular">{w.separated_pct_30d ?? "—"}%</td>
                <td className="px-4 text-right tabular">{w.mandates}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <section className="rounded-2xl border border-line bg-white">
          <h2 className="px-4 pt-4 font-semibold">Door-to-door collectors</h2>
          <table className="w-full text-sm">
            <tbody>
              {o.collectors.map((c) => (
                <tr key={c.id} className="border-t border-line first:border-0">
                  <td className="py-2 pl-4 font-medium">{c.name}</td>
                  <td className="tabular">
                    {c.today}/{c.homes} today
                  </td>
                  <td className="tabular text-slate">score {c.score ?? "—"}</td>
                  <td className="pr-4 text-right">
                    {c.open_flags > 0 && <span className="rounded-full bg-brick px-2 py-0.5 text-xs font-semibold text-white">{c.open_flags} flag</span>}
                    {c.disputes_30d > 0 && <span className="ml-1 text-xs text-slate">{c.disputes_30d} disputed</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="rounded-2xl border border-line bg-white">
          <h2 className="px-4 pt-4 font-semibold">Missed for 2+ days</h2>
          <ul className="max-h-72 overflow-y-auto">
            {o.missed.map((m) => (
              <li key={m.id} className="flex justify-between border-t border-line px-4 py-2 text-sm first:border-0">
                <span>
                  {m.name}
                  <span className="block text-xs text-slate">{m.collector_name}</span>
                </span>
                <span className="text-xs text-brick">{m.last_day ? `last ${shortDate(m.last_day + " 00:00:00")}` : "never"}</span>
              </li>
            ))}
            {o.missed.length === 0 && <li className="px-4 py-3 text-sm text-slate">Every home picked up in the last two days.</li>}
          </ul>
        </section>
      </div>
    </>
  );
}
