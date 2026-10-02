"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, get, post } from "@/lib/api";
import { kg, rupees, shortDate, timeAgo } from "@/lib/format";
import type { CollectorProfile, Flag, MassBalance } from "@/lib/types";
import { BarList, ColumnChart } from "@/components/BarChart";
import { ScoreInputs, ScoreMeter } from "@/components/ScoreMeter";
import { CheckIcon, Logo, MaterialIcon, StopIcon } from "@/components/icons";

type View = "overview" | "collectors" | "flags" | "groups" | "impact";

type Overview = {
  collectors: number;
  active_collectors: number;
  tonnes_month: number;
  upi_share: number;
  loans: { n: number; principal: number; on_time: number; due: number };
  eligible_now: number;
  open_flags: number;
  by_material: { material: string; label_en: string; co2e_per_kg: number | null; kg: number; paid: number }[];
  co2e_kg_month: number;
  kg_by_week: { week_start: string; value: number }[];
  dealers: { id: number; shop_name: string; reputation: number; mass_balance: MassBalance }[];
};

type CollectorRow = {
  id: number;
  name: string;
  group_name: string | null;
  score: number | null;
  sales: number;
  total_kg: number;
  open_flags: number;
  basic_phone: number;
  created_at: string;
};

type Group = {
  id: number;
  name: string;
  city: string;
  members: { id: number; name: string; group_guarantee: number; score: number | null; loan_status: string | null; repayment: string }[];
};

export function SatinApp() {
  const [view, setView] = useState<View>("overview");
  const [openCollector, setOpenCollector] = useState<number | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [collectors, setCollectors] = useState<CollectorRow[]>([]);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);

  const refresh = useCallback(async () => {
    const [o, c, f, g] = await Promise.all([
      get<Overview>("/satin/overview"),
      get<CollectorRow[]>("/collectors"),
      get<Flag[]>("/flags"),
      get<Group[]>("/groups"),
    ]);
    setOverview(o);
    setCollectors(c);
    setFlags(f);
    setGroups(g);
  }, []);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, 5000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  const openFlags = flags.filter((f) => f.status === "open");
  const nav: [View, string, number?][] = [
    ["overview", "Overview"],
    ["collectors", "Collectors", collectors.length],
    ["flags", "Fraud flags", openFlags.length],
    ["groups", "Groups"],
    ["impact", "Impact"],
  ];

  return (
    <div className="min-h-dvh bg-paper lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="border-b border-line bg-ink text-kraft lg:sticky lg:top-0 lg:h-dvh lg:border-0">
        <div className="flex items-center gap-2 px-5 py-4">
          <Logo className="h-8 w-8" />
          <div>
            <p className="font-display text-lg font-semibold leading-none">WorthyWaste</p>
            <p className="text-xs opacity-70">Satin branch view</p>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:overflow-visible">
          {nav.map(([k, label, n]) => (
            <button
              key={k}
              onClick={() => {
                setView(k);
                setOpenCollector(null);
              }}
              className={`flex shrink-0 items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm font-medium ${
                view === k && !openCollector ? "bg-white/12 text-white" : "text-kraft/80 hover:bg-white/6"
              }`}
            >
              {label}
              {n ? (
                <span className={`rounded-full px-2 text-xs tabular ${k === "flags" ? "bg-brick text-white" : "bg-white/15"}`}>{n}</span>
              ) : null}
            </button>
          ))}
        </nav>
        <button
          onClick={async () => {
            if (!confirm("Reset all demo data?")) return;
            await post("/demo/reset");
            setOpenCollector(null);
            refresh();
          }}
          className="mx-5 mb-4 hidden text-xs text-kraft/50 underline lg:block"
        >
          Reset demo data
        </button>
      </aside>

      <main className="min-w-0 px-4 py-6 lg:px-8">
        {openCollector ? (
          <CollectorDetail id={openCollector} onBack={() => setOpenCollector(null)} onChanged={refresh} />
        ) : (
          <>
            {view === "overview" && overview && (
              <OverviewView o={overview} flags={openFlags} onFlags={() => setView("flags")} onCollector={setOpenCollector} />
            )}
            {view === "collectors" && <CollectorsView rows={collectors} onOpen={setOpenCollector} />}
            {view === "flags" && <FlagsView flags={flags} onChanged={refresh} onCollector={setOpenCollector} />}
            {view === "groups" && <GroupsView groups={groups} onOpen={setOpenCollector} />}
            {view === "impact" && overview && <ImpactView o={overview} />}
          </>
        )}
      </main>
    </div>
  );
}

function PageTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {sub && <p className="text-sm text-slate">{sub}</p>}
    </div>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "brick" | "marigold" }) {
  return (
    <div className="rounded-2xl border border-line bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate">{label}</p>
      <p className={`mt-1 font-display text-3xl font-bold tabular ${tone === "brick" ? "text-brick" : ""}`}>{value}</p>
      {sub && <p className="text-xs text-slate">{sub}</p>}
    </div>
  );
}

// ---------- Overview ----------

function OverviewView({
  o,
  flags,
  onFlags,
  onCollector,
}: {
  o: Overview;
  flags: Flag[];
  onFlags: () => void;
  onCollector: (id: number) => void;
}) {
  const onTime = o.loans.due ? Math.round((o.loans.on_time / o.loans.due) * 100) : null;
  return (
    <>
      <PageTitle title="Overview" sub="Delhi pilot · last 30 days · every record backed by scale weight, GPS match and UPI payment" />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Tile label="Active collectors" value={`${o.active_collectors} / ${o.collectors}`} sub="sold on 8+ days this month" />
        <Tile label="Verified tonnes" value={`${o.tonnes_month.toFixed(2)} t`} sub={`${Math.round(o.upi_share * 100)}% paid by UPI`} />
        <Tile
          label="Loans"
          value={`${o.loans.n}`}
          sub={`${rupees(o.loans.principal)} disbursed${onTime != null ? ` · ${onTime}% on time` : ""} · ${o.eligible_now} eligible now`}
        />
        <Tile label="Open fraud flags" value={`${o.open_flags}`} tone={o.open_flags ? "brick" : undefined} sub="needs review" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[3fr_2fr]">
        <section className="rounded-2xl border border-line bg-white p-4">
          <h2 className="font-semibold">Verified kg per week</h2>
          <p className="mb-2 text-xs text-slate">All collectors, scale-weighed and paid</p>
          <ColumnChart
            data={o.kg_by_week.map((w) => ({ label: shortDate(w.week_start + " 00:00:00"), value: w.value, detail: `Week of ${shortDate(w.week_start + " 00:00:00")}` }))}
            format={(v) => `${Math.round(v)} kg`}
          />
        </section>
        <section className="rounded-2xl border border-line bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold">Latest fraud flags</h2>
            <button onClick={onFlags} className="text-sm text-leaf underline">
              All flags
            </button>
          </div>
          <ul className="space-y-2">
            {flags.slice(0, 4).map((f) => (
              <li key={f.id} className="rounded-xl border-l-4 border-brick bg-brick-soft/60 p-3 text-sm">
                <p className="font-semibold text-brick">{f.rule_label}</p>
                <p>{f.detail}</p>
                {f.collector_id && (
                  <button onClick={() => onCollector(f.collector_id!)} className="mt-1 text-xs text-slate underline">
                    {f.collector_name}
                  </button>
                )}
              </li>
            ))}
            {flags.length === 0 && <p className="text-sm text-slate">No open flags.</p>}
          </ul>
        </section>
      </div>

      <section className="mt-4 rounded-2xl border border-line bg-white p-4">
        <h2 className="mb-3 font-semibold">Dealers · mass balance (30 days)</h2>
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-slate">
            <tr>
              <th className="py-2 font-medium">Dealer</th>
              <th className="font-medium">Reputation</th>
              <th className="text-right font-medium">Bought</th>
              <th className="text-right font-medium">Sold to recyclers</th>
              <th className="text-right font-medium">Gap</th>
            </tr>
          </thead>
          <tbody>
            {o.dealers.map((d) => {
              const bad = d.mass_balance.gap_pct != null && d.mass_balance.gap_pct > 15;
              return (
                <tr key={d.id} className="border-t border-line">
                  <td className="py-2 font-medium">{d.shop_name}</td>
                  <td className="tabular">{d.reputation}</td>
                  <td className="text-right tabular">{kg(Math.round(d.mass_balance.bought_kg))}</td>
                  <td className="text-right tabular">{kg(Math.round(d.mass_balance.sold_kg))}</td>
                  <td className={`text-right font-semibold tabular ${bad ? "text-brick" : "text-leaf"}`}>
                    {d.mass_balance.gap_pct != null ? `${d.mass_balance.gap_pct}%` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </>
  );
}

// ---------- Collectors ----------

function CollectorsView({ rows, onOpen }: { rows: CollectorRow[]; onOpen: (id: number) => void }) {
  return (
    <>
      <PageTitle title="Collectors" sub="Only collectors who gave voice consent are shown to Satin" />
      <div className="overflow-x-auto rounded-2xl border border-line bg-white">
        <table className="w-full min-w-[640px] text-sm">
          <thead className="bg-kraft/50 text-left text-xs uppercase tracking-wide text-slate">
            <tr>
              <th className="px-4 py-3 font-medium">Collector</th>
              <th className="font-medium">Group</th>
              <th className="text-right font-medium">Score</th>
              <th className="text-right font-medium">Sales</th>
              <th className="text-right font-medium">Total kg</th>
              <th className="px-4 text-right font-medium">Flags</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} onClick={() => onOpen(r.id)} className="cursor-pointer border-t border-line hover:bg-kraft/30">
                <td className="px-4 py-3 font-medium">
                  {r.name}
                  <span className="block text-xs font-normal text-slate">since {shortDate(r.created_at)}</span>
                </td>
                <td className="text-slate">{r.group_name ?? "—"}</td>
                <td className="text-right font-display text-lg font-semibold tabular">{r.score ?? "—"}</td>
                <td className="text-right tabular">{r.sales}</td>
                <td className="text-right tabular">{Math.round(r.total_kg).toLocaleString("en-IN")}</td>
                <td className="px-4 text-right">
                  {r.open_flags ? <span className="rounded-full bg-brick px-2 py-0.5 text-xs font-semibold text-white">{r.open_flags}</span> : <span className="text-slate">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function CollectorDetail({ id, onBack, onChanged }: { id: number; onBack: () => void; onChanged: () => void }) {
  const [p, setP] = useState<CollectorProfile | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = useCallback(() => get<CollectorProfile>(`/collectors/${id}`).then(setP), [id]);
  useEffect(() => {
    load();
  }, [load]);
  if (!p) return <p className="text-slate">Loading…</p>;
  const c = p.collector;
  const el = p.eligibility;
  const activeLoan = p.loans.find((l) => l.status === "active");

  return (
    <>
      <button onClick={onBack} className="mb-3 text-sm text-slate">
        ← Back
      </button>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">{c.name}</h1>
          <p className="text-sm text-slate">
            {c.group_name} · {c.city} · joined {shortDate(c.created_at)} · {c.basic_phone ? "basic phone" : "smartphone"} · ID verified via e-Shram (hash only)
          </p>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(320px,2fr)_3fr]">
        <section className="space-y-4">
          <div className="rounded-2xl border border-line bg-white p-5">
            <div className="grid place-items-center">
              <ScoreMeter score={p.score?.score ?? 300} size={260} />
              <p className="text-xs text-slate">Score v1 · rule-based · recomputed {p.score && timeAgo(p.score.computed_at)}</p>
            </div>
            {p.score && (
              <div className="mt-4">
                <ScoreInputs inputs={p.score.inputs} />
              </div>
            )}
          </div>
        </section>

        <section className="space-y-4">
          <div className={`rounded-2xl border-2 p-5 ${el.eligible ? "border-leaf bg-leaf-soft/50" : "border-line bg-white"}`}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate">Loan eligibility · cycle {el.cycle}</p>
                <p className="font-display text-2xl font-semibold">
                  {activeLoan
                    ? `Loan running · ${rupees(activeLoan.principal)}`
                    : el.eligible
                      ? `Starter loan unlocked · ${rupees(el.limit)}`
                      : "Not yet eligible"}
                </p>
              </div>
              {el.eligible && (
                <button
                  onClick={async () => {
                    try {
                      await post("/loans", { collector_id: id });
                      setMsg(`${rupees(el.limit)} group-backed loan recorded for ${c.name}.`);
                      load();
                      onChanged();
                    } catch (e) {
                      setMsg((e as ApiError).message);
                    }
                  }}
                  className="h-12 rounded-xl bg-leaf px-5 font-semibold text-white"
                >
                  Disburse {rupees(el.limit)}
                </button>
              )}
            </div>
            <ul className="mt-3 grid gap-1 text-sm sm:grid-cols-2">
              {el.checks.map((ch) => (
                <li key={ch.key} className="flex items-center gap-2">
                  {ch.ok ? <CheckIcon className="h-4 w-4 shrink-0 text-leaf" /> : <StopIcon className="h-4 w-4 shrink-0 text-brick" />}
                  <span>
                    {ch.label} <span className="text-slate">· {ch.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
            {msg && <p className="mt-3 rounded-lg bg-white p-2 text-sm">{msg}</p>}
          </div>

          <div className="rounded-2xl border border-line bg-white p-4">
            <h2 className="font-semibold">Verified income per week</h2>
            <p className="mb-2 text-xs text-slate">Last 12 weeks · UPI-paid sales only</p>
            <ColumnChart
              data={p.income_by_week.map((w) => ({ label: shortDate(w.week_start + " 00:00:00"), value: w.value, detail: `Week of ${shortDate(w.week_start + " 00:00:00")}` }))}
              format={(v) => rupees(v)}
              height={160}
            />
          </div>

          {p.flags.length > 0 && (
            <div className="rounded-2xl border border-line bg-white p-4">
              <h2 className="mb-2 font-semibold">Fraud flags</h2>
              {p.flags.map((f) => (
                <p key={f.id} className="border-t border-line py-2 text-sm first:border-0">
                  <b className="text-brick">{f.rule}</b> · {f.status} — {f.detail}
                </p>
              ))}
            </div>
          )}

          <div className="rounded-2xl border border-line bg-white">
            <h2 className="px-4 pt-4 font-semibold">Sales history</h2>
            <table className="w-full text-sm">
              <tbody>
                {p.transactions.slice(0, 10).map((t) => (
                  <tr key={t.id} className="border-t border-line first:border-0">
                    <td className="py-2 pl-4">
                      <MaterialIcon code={t.material} className="h-6 w-6 text-leaf" />
                    </td>
                    <td>
                      {t.label_en}
                      <span className="block text-xs text-slate">{t.shop_name}</span>
                    </td>
                    <td className="text-slate">{shortDate(t.created_at)}</td>
                    <td className="text-right tabular">{kg(t.scale_kg)}</td>
                    <td className="pr-4 text-right font-semibold tabular">{rupees(t.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </>
  );
}

// ---------- Fraud flags ----------

function FlagsView({ flags, onChanged, onCollector }: { flags: Flag[]; onChanged: () => void; onCollector: (id: number) => void }) {
  const [filter, setFilter] = useState<"open" | "all">("open");
  const shown = filter === "open" ? flags.filter((f) => f.status === "open") : flags;
  return (
    <>
      <PageTitle title="Fraud flags" sub="Each flag names the rule that fired and its evidence. Confirming freezes loan eligibility and lowers the dealer's reputation." />
      <div className="mb-3 flex gap-2">
        {(["open", "all"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium ${filter === k ? "bg-ink text-white" : "border border-line bg-white"}`}
          >
            {k === "open" ? "Open" : "All"}
          </button>
        ))}
      </div>
      <ul className="space-y-3">
        {shown.map((f) => (
          <li key={f.id} className={`rounded-2xl border bg-white p-4 ${f.status === "open" ? "border-brick/40" : "border-line opacity-75"}`}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm font-semibold text-brick">
                  <StopIcon className="h-4 w-4" /> {f.rule_label}
                  <span className="font-normal text-slate">· {timeAgo(f.created_at)}</span>
                </p>
                <p className="mt-1 text-base">{f.detail}</p>
                <p className="mt-1 text-xs text-slate">
                  {f.collector_name && (
                    <button onClick={() => onCollector(f.collector_id!)} className="underline">
                      {f.collector_name}
                    </button>
                  )}
                  {f.collector_name && f.shop_name && " · "}
                  {f.shop_name}
                </p>
                {f.evidence && Object.keys(f.evidence).length > 0 && (
                  <details className="mt-2 text-xs">
                    <summary className="cursor-pointer text-slate">Evidence</summary>
                    <pre className="mt-1 overflow-x-auto rounded-lg bg-kraft/50 p-2">{JSON.stringify(f.evidence, null, 2)}</pre>
                  </details>
                )}
              </div>
              {f.status === "open" ? (
                <div className="flex gap-2">
                  <button
                    onClick={() => post(`/flags/${f.id}`, { status: "confirmed" }).then(onChanged)}
                    className="h-10 rounded-lg bg-brick px-4 text-sm font-semibold text-white"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => post(`/flags/${f.id}`, { status: "dismissed" }).then(onChanged)}
                    className="h-10 rounded-lg border border-line px-4 text-sm font-semibold"
                  >
                    Dismiss
                  </button>
                </div>
              ) : (
                <span className="rounded-full bg-kraft px-3 py-1 text-xs font-semibold capitalize">{f.status}</span>
              )}
            </div>
          </li>
        ))}
        {shown.length === 0 && <p className="text-slate">Nothing here.</p>}
      </ul>
    </>
  );
}

// ---------- Groups ----------

function GroupsView({ groups, onOpen }: { groups: Group[]; onOpen: (id: number) => void }) {
  return (
    <>
      <PageTitle title="Groups" sub="First loans are backed by the collector's waste-picker group (joint liability)" />
      {groups.map((g) => (
        <section key={g.id} className="mb-4 rounded-2xl border border-line bg-white">
          <div className="p-4">
            <h2 className="text-lg font-semibold">{g.name}</h2>
            <p className="text-sm text-slate">{g.city} · {g.members.length} members</p>
          </div>
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-slate">
              <tr className="border-t border-line">
                <th className="px-4 py-2 font-medium">Member</th>
                <th className="font-medium">Guarantee</th>
                <th className="text-right font-medium">Score</th>
                <th className="font-medium pl-6">Loan</th>
                <th className="px-4 text-right font-medium">On-time</th>
              </tr>
            </thead>
            <tbody>
              {g.members.map((m) => (
                <tr key={m.id} onClick={() => onOpen(m.id)} className="cursor-pointer border-t border-line hover:bg-kraft/30">
                  <td className="px-4 py-2 font-medium">{m.name}</td>
                  <td>{m.group_guarantee ? <span className="text-leaf">Recorded</span> : <span className="text-brick">Missing</span>}</td>
                  <td className="text-right tabular">{m.score ?? "—"}</td>
                  <td className="pl-6 capitalize">{m.loan_status ?? "—"}</td>
                  <td className="px-4 text-right tabular">{m.repayment === "0/0" ? "—" : m.repayment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </>
  );
}

// ---------- Impact ----------

function ImpactView({ o }: { o: Overview }) {
  const total = o.by_material.reduce((s, m) => s + m.kg, 0);
  const [code, setCode] = useState("");
  const [trace, setTrace] = useState<null | { batch: { code: string; shop_name: string; material: string; total_kg: number }; sales: { collector_ref: string; scale_kg: number; created_at: string }[]; recycler_sale: { recycler_name: string; kg: number; invoice_ref: string } | null }>(null);
  const [err, setErr] = useState<string | null>(null);

  return (
    <>
      <PageTitle title="Impact" sub="Last 30 days · CO₂e shown for PET only, where the factor is defensible" />
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
        <Tile label="Recovered & traced" value={`${(total / 1000).toFixed(2)} t`} sub="scale-weighed, UPI-paid" />
        <Tile label="CO₂e avoided (PET)" value={`${o.co2e_kg_month.toLocaleString("en-IN")} kg`} sub="1.5 kg CO₂e per kg PET recycled (indicative)" />
        <Tile label="Paid to collectors" value={rupees(o.by_material.reduce((s, m) => s + m.paid, 0))} sub="income now on record" />
      </div>
      <section className="mt-4 rounded-2xl border border-line bg-white p-4">
        <h2 className="mb-3 font-semibold">Kilos by material</h2>
        <BarList data={o.by_material.map((m) => ({ label: m.label_en, value: m.kg }))} format={(v) => `${Math.round(v).toLocaleString("en-IN")} kg`} />
      </section>
      <section className="mt-4 rounded-2xl border border-line bg-white p-4">
        <h2 className="font-semibold">Trace a batch</h2>
        <p className="mb-2 text-xs text-slate">What a recycler or brand sees: pseudonymised collectors, no names or phone numbers</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setErr(null);
            try {
              setTrace(await get(`/batches/${encodeURIComponent(code.trim())}`));
            } catch (x) {
              setTrace(null);
              setErr((x as ApiError).message);
            }
          }}
          className="flex gap-2"
        >
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="WW-D01-PLA-…" className="h-10 min-w-0 flex-1 rounded-lg border border-line px-3 font-mono text-sm" />
          <button className="h-10 rounded-lg bg-ink px-4 text-sm font-semibold text-white">Trace</button>
        </form>
        {err && <p className="mt-2 text-sm text-brick">{err}</p>}
        {trace && (
          <div className="mt-3 text-sm">
            <p>
              <b>{trace.batch.code}</b> · {trace.batch.shop_name} · {kg(Math.round(trace.batch.total_kg))} from {trace.sales.length} verified sales
              {trace.recycler_sale && ` → ${trace.recycler_sale.recycler_name} (${kg(trace.recycler_sale.kg)}, invoice ${trace.recycler_sale.invoice_ref})`}
            </p>
            <ul className="mt-2 max-h-48 overflow-y-auto font-mono text-xs text-slate">
              {trace.sales.map((s, i) => (
                <li key={i}>
                  {s.created_at} · {s.collector_ref} · {s.scale_kg} kg
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </>
  );
}
