"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, get, logout, post } from "@/lib/api";
import { parseTs, rupees, shortDate, shortTime } from "@/lib/format";
import { speak } from "@/lib/speech";
import type { ComplianceReport, HouseholdPickup, HouseholdView } from "@/lib/types";
import { QrCode } from "@/components/QrCode";
import { CheckIcon, Logo, SpeakerIcon } from "@/components/icons";

type Lang = "hi" | "en";
type Tab = "wallet" | "pickups" | "door";

const L = (lang: Lang, hi: string, en: string) => (lang === "hi" ? hi : en);
const paise = (n: number) => `₹${n.toLocaleString("en-IN", { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 })}`;

/**
 * Anita's Green Wallet (Phase 2): what her collection costs, what separating saves her, and a way to
 * say "no pickup today". The money is never held by us: AutoPay debits her own bank account a day
 * after each pickup, and the WhatsApp at pickup is the 24-hour notice.
 */
export function HouseholdApp({ demo }: { demo: boolean }) {
  const [v, setV] = useState<HouseholdView | null>(null);
  const [lang, setLang] = useState<Lang>("hi");
  const [tab, setTab] = useState<Tab>("wallet");
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(() => get<HouseholdView>("/households/me").then((x) => (setV(x), x)), []);
  useEffect(() => {
    load().then((x) => setLang(x.household.language));
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  if (!v) return <div className="grid min-h-dvh place-items-center bg-paper text-slate">…</div>;
  const h = v.household;

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setNote(null);
    try {
      await fn();
      setNote(ok);
    } catch (e) {
      setNote((e as ApiError).message);
    }
    load();
  };

  return (
    <div className="min-h-dvh bg-paper">
      <div className="mx-auto flex min-h-dvh max-w-md flex-col">
        <header className="flex items-center gap-3 px-4 pt-4 pb-2">
          <Logo className="h-9 w-9" />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-slate">{h.contact_name ?? L(lang, "नमस्ते", "Hello")}</p>
            <p className="truncate font-display text-lg font-semibold leading-tight">{h.name}</p>
          </div>
          <button onClick={() => logout("household")} className="h-11 rounded-full px-2 text-xs text-slate underline">
            {L(lang, "बाहर", "Log out")}
          </button>
          <button
            onClick={() => setLang(lang === "hi" ? "en" : "hi")}
            className="h-11 rounded-full border border-line bg-white px-4 text-sm font-semibold"
            aria-label="Change language"
          >
            {lang === "hi" ? "EN" : "हिं"}
          </button>
        </header>

        <main className="flex-1 space-y-4 px-4 pb-4">
          {note && (
            <p role="status" className="animate-pop rounded-xl bg-ink p-3 text-sm text-kraft">
              {note}
            </p>
          )}
          {tab === "wallet" && <WalletTab v={v} lang={lang} demo={demo} act={act} />}
          {tab === "pickups" && <PickupsTab v={v} lang={lang} act={act} />}
          {tab === "door" && <DoorTab v={v} lang={lang} act={act} />}
        </main>

        <nav className="sticky bottom-0 grid grid-cols-3 border-t border-line bg-white/95 backdrop-blur">
          {(
            [
              ["wallet", L(lang, "ग्रीन वॉलेट", "Green Wallet")],
              ["pickups", L(lang, "पिकअप", "Pickups")],
              ["door", h.kind === "bulk" ? L(lang, "रिपोर्ट", "Report") : L(lang, "दरवाज़े का QR", "Door QR")],
            ] as const
          ).map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)} className={`h-16 text-sm font-semibold ${tab === k ? "text-leaf" : "text-slate"}`} aria-current={tab === k}>
              <span className={`mx-auto mb-1 block h-1 w-8 rounded-full ${tab === k ? "bg-leaf" : "bg-transparent"}`} />
              {label}
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}

type Act = (fn: () => Promise<unknown>, ok: string) => Promise<void>;

// ---------- Green Wallet ----------

function WalletTab({ v, lang, demo, act }: { v: HouseholdView; lang: Lang; demo: boolean; act: Act }) {
  const w = v.wallet;
  const pts = v.points;
  const [limit, setLimit] = useState(w.mandate_limit || 300);
  const perPickup = w.fee_per_pickup + w.platform_fee;
  const redeemable = Math.floor(pts.balance / pts.redeem_step) * pts.redeem_step;
  const today = v.today;
  const toStreak = pts.streak_every - (pts.streak % pts.streak_every);

  return (
    <>
      {/* Today */}
      <section className={`rounded-3xl p-5 ${today ? (today.segregation === "separated" ? "bg-leaf text-white" : "bg-marigold text-ink") : "bg-kraft"}`}>
        <p className="text-sm opacity-80">{L(lang, "आज का पिकअप", "Today's pickup")}</p>
        {today ? (
          <>
            <p className="font-display text-2xl font-semibold">
              {today.status === "disputed"
                ? L(lang, "आपने शिकायत की", "You reported this")
                : today.segregation === "separated"
                  ? L(lang, `कचरा अलग मिला · +${today.points} पॉइंट`, `Separated · +${today.points} points`)
                  : L(lang, "मिला-जुला मिला · 0 पॉइंट", "Mixed · no points")}
            </p>
            <p className="text-sm opacity-90">
              {v.collector_name?.split(" ")[0]} · {shortTime(today.created_at)}
            </p>
          </>
        ) : (
          <p className="font-display text-2xl font-semibold">{L(lang, "अभी नहीं आए", "Not yet")}</p>
        )}
      </section>

      {/* Wallet */}
      <section className="rounded-3xl bg-ink p-5 text-kraft">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm opacity-80">{L(lang, "ग्रीन वॉलेट · इस महीने", "Green Wallet · this month")}</p>
            <p className="font-display text-4xl font-bold tabular text-marigold">{paise(w.spent_month)}</p>
          </div>
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${w.mandate_status === "active" ? "bg-leaf text-white" : "bg-brick text-white"}`}>
            {w.mandate_status === "active" ? "AutoPay ✓" : L(lang, "AutoPay बंद", "AutoPay off")}
          </span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
          <div>
            <dt className="opacity-70">{L(lang, "आने वाला", "Upcoming")}</dt>
            <dd className="font-semibold tabular">{paise(w.upcoming)}</dd>
          </div>
          <div>
            <dt className="opacity-70">{L(lang, "बाकी", "Due")}</dt>
            <dd className={`font-semibold tabular ${w.due ? "text-marigold" : ""}`}>{paise(w.due)}</dd>
          </div>
          <div>
            <dt className="opacity-70">{L(lang, "पॉइंट से छूट", "Points credit")}</dt>
            <dd className="font-semibold tabular">{paise(w.fee_credit)}</dd>
          </div>
          <div>
            <dt className="opacity-70">{L(lang, "महीने की सीमा", "Monthly limit")}</dt>
            <dd className="font-semibold tabular">{w.mandate_status === "active" ? rupees(w.mandate_limit) : "—"}</dd>
          </div>
        </dl>
        <p className="mt-3 text-xs opacity-70">
          {w.fee_plan === "monthly"
            ? L(lang, `महीने का प्लान: ${rupees(w.monthly_fee)}/महीना, जिस दिन पिकअप नहीं हुआ उसका पैसा नहीं`, `Monthly plan: ${rupees(w.monthly_fee)}/month, minus days without a pickup`)
            : L(lang, `हर पिकअप ${paise(perPickup)} (कलेक्टर ${paise(w.fee_per_pickup)} + सेवा ${paise(w.platform_fee)}), अगले दिन कटता है`, `${paise(perPickup)} per pickup (collector ${paise(w.fee_per_pickup)} + service ${paise(w.platform_fee)}), debited the next day`)}
        </p>
        {demo && (w.upcoming > 0 || w.due > 0) && (
          <button onClick={() => act(() => post("/demo/households/me/settle"), "Demo: AutoPay ran")} className="mt-2 text-xs text-kraft/70 underline">
            Demo: run tomorrow&apos;s AutoPay now
          </button>
        )}
      </section>

      {/* AutoPay */}
      <section className="rounded-2xl border border-line bg-white p-4">
        <p className="font-semibold">{w.mandate_status === "active" ? L(lang, "AutoPay की सीमा बदलें", "Change your AutoPay limit") : L(lang, "UPI AutoPay चालू करें", "Turn on UPI AutoPay")}</p>
        <p className="text-sm text-slate">
          {L(lang, "पैसा आपके बैंक में ही रहता है। हर कटौती से एक दिन पहले WhatsApp आता है।", "Your money stays in your bank. You get a WhatsApp a day before every debit.")}
        </p>
        <div className="mt-3 flex items-center gap-2">
          <span className="text-slate">₹</span>
          <input
            type="number"
            min={50}
            max={5000}
            step={50}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="h-12 w-28 rounded-xl border border-line px-3 text-lg tabular"
            aria-label="Monthly limit"
          />
          <span className="text-sm text-slate">/ {L(lang, "महीना", "month")}</span>
          <button
            onClick={() => act(() => post("/households/me/mandate", { limit }), L(lang, "AutoPay चालू है", "AutoPay is on"))}
            className="ml-auto h-12 rounded-xl bg-leaf px-4 font-semibold text-white"
          >
            {w.mandate_status === "active" ? L(lang, "बदलें", "Update") : L(lang, "चालू करें", "Turn on")}
          </button>
        </div>
      </section>

      {/* Points */}
      <section className="rounded-2xl border-2 border-leaf bg-leaf-soft/60 p-4">
        <div className="flex items-end justify-between">
          <div>
            <p className="text-sm font-semibold text-leaf-dark">{L(lang, "आपके पॉइंट", "Your points")}</p>
            <p className="font-display text-4xl font-bold tabular">{pts.balance}</p>
          </div>
          <p className="text-right text-sm">
            {L(lang, `${pts.streak} दिन लगातार अलग`, `${pts.streak} separated in a row`)}
            <span className="block text-xs text-slate">
              {L(lang, `${toStreak} और पर +${pts.streak_bonus} बोनस`, `+${pts.streak_bonus} bonus in ${toStreak} more`)}
            </span>
          </p>
        </div>
        <div className="mt-2 h-2 rounded-full bg-white">
          <div className="h-2 rounded-full bg-leaf" style={{ width: `${Math.min(100, (pts.earned_month / pts.monthly_cap) * 100)}%` }} />
        </div>
        <p className="mt-1 text-xs text-slate">
          {L(lang, `इस महीने ${pts.earned_month} / ${pts.monthly_cap} पॉइंट · हर अलग पिकअप पर ${pts.per_separated}`, `${pts.earned_month} of ${pts.monthly_cap} points this month · ${pts.per_separated} per separated pickup`)}
        </p>
        <button
          disabled={redeemable < pts.redeem_step}
          onClick={() =>
            act(
              () => post("/households/me/redeem", { points: redeemable }),
              L(lang, `${redeemable} पॉइंट से ${paise(redeemable * pts.value)} की छूट मिली`, `${paise(redeemable * pts.value)} off your next fees`),
            )
          }
          className="mt-3 h-12 w-full rounded-xl bg-leaf font-semibold text-white disabled:opacity-40"
        >
          {redeemable >= pts.redeem_step
            ? L(lang, `${redeemable} पॉइंट = ${paise(redeemable * pts.value)} फ़ीस में छूट`, `Use ${redeemable} points = ${paise(redeemable * pts.value)} off fees`)
            : L(lang, `${pts.redeem_step} पॉइंट पर छूट मिलेगी`, `Redeem from ${pts.redeem_step} points`)}
        </button>
        <p className="mt-2 text-center text-xs text-slate">{L(lang, "कचरा अलग करो, बिल कम करो", "Separate your waste, shrink your bill")}</p>
      </section>

      {/* Plan */}
      <section className="rounded-2xl border border-line bg-white p-4">
        <p className="mb-2 font-semibold">{L(lang, "फ़ीस का तरीका", "How you pay")}</p>
        <div className="grid grid-cols-2 gap-2">
          {(["per_pickup", "monthly"] as const).map((p) => (
            <button
              key={p}
              onClick={() => w.fee_plan !== p && act(() => post("/households/me/plan", { plan: p }), L(lang, "अगले पिकअप से लागू", "Applies from the next pickup"))}
              aria-pressed={w.fee_plan === p}
              className={`rounded-xl border-2 p-3 text-left text-sm ${w.fee_plan === p ? "border-leaf bg-leaf-soft" : "border-line"}`}
            >
              <b>{p === "per_pickup" ? L(lang, "हर पिकअप", "Per pickup") : L(lang, "महीने का", "Monthly")}</b>
              <span className="block text-xs text-slate">
                {p === "per_pickup" ? `${paise(perPickup)} ${L(lang, "हर बार", "each")}` : `${rupees(w.monthly_fee)} / ${L(lang, "महीना", "month")}`}
              </span>
            </button>
          ))}
        </div>
      </section>

      {v.messages.length > 0 && (
        <section className="rounded-2xl border border-line bg-white p-4">
          <p className="mb-2 text-sm font-semibold">WhatsApp</p>
          {v.messages.slice(0, 3).map((m) => (
            <button key={m.id} onClick={() => speak(m.text, lang)} className="flex w-full items-start gap-2 border-t border-line py-2 text-left text-sm first:border-0">
              <SpeakerIcon className="mt-0.5 h-4 w-4 shrink-0 text-leaf" />
              <span>{m.text}</span>
            </button>
          ))}
        </section>
      )}
    </>
  );
}

// ---------- Pickups ----------

const FEE_LABEL: Record<string, [string, string]> = {
  accrued: ["कल कटेगा", "debits tomorrow"],
  due: ["बाकी", "due"],
  paid: ["कट गया", "paid"],
  cancelled: ["नहीं कटेगा", "not charged"],
  refunded: ["वापस", "refunded"],
};

function PickupsTab({ v, lang, act }: { v: HouseholdView; lang: Lang; act: Act }) {
  return (
    <>
      <section className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-ink p-4 text-kraft">
          <p className="text-xs opacity-70">{L(lang, "इस महीने पिकअप", "Pickups this month")}</p>
          <p className="font-display text-3xl font-bold tabular">{v.month.pickups}</p>
        </div>
        <div className="rounded-2xl bg-leaf-soft p-4">
          <p className="text-xs text-slate">{L(lang, "अलग दिया", "Separated")}</p>
          <p className="font-display text-3xl font-bold tabular">
            {v.month.pickups ? Math.round((100 * v.month.separated) / v.month.pickups) : 0}%
          </p>
        </div>
      </section>
      <ul className="rounded-2xl border border-line bg-white">
        {v.pickups.map((p) => (
          <PickupRow key={p.id} p={p} lang={lang} act={act} />
        ))}
        {v.pickups.length === 0 && <li className="p-4 text-sm text-slate">{L(lang, "अभी कोई पिकअप नहीं", "No pickups yet")}</li>}
      </ul>
    </>
  );
}

function PickupRow({ p, lang, act }: { p: HouseholdPickup; lang: Lang; act: Act }) {
  const [confirming, setConfirming] = useState(false);
  const amount = (p.fee ?? 0) + (p.platform_fee ?? 0);
  const fee = p.fee_status ? FEE_LABEL[p.fee_status] : null;
  return (
    <li className="border-t border-line px-4 py-3 first:border-0">
      <div className="flex items-center gap-3">
        <span className={`h-3 w-3 shrink-0 rounded-full ${p.status === "disputed" ? "bg-brick" : p.segregation === "separated" ? "bg-leaf" : "bg-marigold"}`} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">
            {shortDate(p.day + " 00:00:00")} · {p.status === "disputed" ? L(lang, "शिकायत की", "Reported") : p.segregation === "separated" ? L(lang, "अलग", "Separated") : L(lang, "मिला-जुला", "Mixed")}
            {p.points > 0 && p.status === "done" && <span className="text-leaf"> · +{p.points}</span>}
          </p>
          <p className="text-xs text-slate">
            {shortTime(p.created_at)}
            {fee && ` · ${paise(amount)} ${L(lang, fee[0], fee[1])}`}
          </p>
        </div>
        {p.can_dispute && !confirming && (
          <button onClick={() => setConfirming(true)} className="rounded-lg border border-brick px-2 py-1 text-xs font-semibold text-brick">
            {L(lang, "पिकअप नहीं हुआ?", "No pickup?")}
          </button>
        )}
      </div>
      {confirming && p.can_dispute && (
        <div className="mt-2 flex items-center gap-2 rounded-xl bg-brick-soft p-2 text-sm">
          <span className="flex-1">{L(lang, "पक्का? पैसा नहीं कटेगा और पॉइंट वापस होंगे।", "Sure? You won't be charged and the points go back.")}</span>
          <button
            onClick={() => act(() => post(`/households/me/pickups/${p.id}/dispute`, { reason: "No pickup" }), L(lang, "शिकायत दर्ज हो गई", "Reported"))}
            className="rounded-lg bg-brick px-3 py-1.5 font-semibold text-white"
          >
            {L(lang, "हाँ", "Yes")}
          </button>
          <button onClick={() => setConfirming(false)} className="px-2 text-slate">
            ✕
          </button>
        </div>
      )}
    </li>
  );
}

// ---------- Door QR / compliance report ----------

function DoorTab({ v, lang, act }: { v: HouseholdView; lang: Lang; act: Act }) {
  const h = v.household;
  return (
    <>
      <section className="grid place-items-center rounded-3xl border border-line bg-white p-5 text-center">
        <p className="font-semibold">{L(lang, "दरवाज़े पर लगा QR", "The QR on your door")}</p>
        <QrCode value={h.door_qr} size={210} className="mt-3 rounded-xl bg-white p-2" />
        <p className="mt-2 font-mono text-xl font-bold tracking-widest">{h.door_qr}</p>
        <p className="mt-2 text-xs text-slate">
          {L(lang, "कलेक्टर दरवाज़े पर इसे स्कैन करते हैं। स्टिकर खो जाए तो यहीं से दिखा दें।", "Your collector scans this at the door. Lost the sticker? Show it from here.")}
        </p>
        <p className="mt-1 text-xs text-slate">
          {h.ward} · {L(lang, "कलेक्टर", "Collector")}: {v.collector_name ?? "—"}
        </p>
      </section>
      {v.compliance && <Compliance r={v.compliance} lang={lang} act={act} />}
    </>
  );
}

function Compliance({ r, lang, act }: { r: ComplianceReport; lang: Lang; act: Act }) {
  return (
    <section className="rounded-2xl border border-line bg-white p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{L(lang, "बल्क वेस्ट कंप्लायंस रिपोर्ट", "Bulk waste compliance report")}</p>
          <p className="text-xs text-slate">Solid Waste Management Rules, 2016 · {r.month}</p>
        </div>
        {r.subscribed && <span className="rounded-full bg-leaf-soft px-2 py-0.5 text-xs font-semibold text-leaf-dark">Pro</span>}
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl bg-kraft/60 p-2">
          <dt className="text-[11px] text-slate">{L(lang, "कचरा दिया", "Handed over")}</dt>
          <dd className="font-display text-xl font-bold tabular">
            {r.handed_over}/{r.days}
          </dd>
        </div>
        <div className="rounded-xl bg-kraft/60 p-2">
          <dt className="text-[11px] text-slate">{L(lang, "अलग", "Separated")}</dt>
          <dd className="font-display text-xl font-bold tabular">{r.separated_pct ?? "—"}%</dd>
        </div>
        <div className="rounded-xl bg-kraft/60 p-2">
          <dt className="text-[11px] text-slate">{L(lang, "छूटे दिन", "Missed")}</dt>
          <dd className={`font-display text-xl font-bold tabular ${r.missed.length ? "text-brick" : ""}`}>{r.missed.length}</dd>
        </div>
      </dl>
      {r.subscribed ? (
        <>
          <table className="mt-3 w-full text-xs">
            <tbody>
              {r.log.slice(-10).reverse().map((d) => (
                <tr key={d.day} className="border-t border-line">
                  <td className="py-1.5">{shortDate(d.day + " 00:00:00")}</td>
                  <td>{parseTs(d.created_at).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}</td>
                  <td>{d.status === "done" ? (d.segregation === "separated" ? "Separated" : "Mixed") : "Disputed"}</td>
                  <td className="text-right text-slate">{d.collector_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={() => window.print()} className="mt-3 h-11 w-full rounded-xl border border-line font-semibold">
            {L(lang, "रिपोर्ट प्रिंट / PDF", "Print / save as PDF")}
          </button>
        </>
      ) : (
        <button
          onClick={() => act(() => post("/households/me/compliance"), L(lang, "रिपोर्ट चालू हो गई", "Compliance report is on"))}
          className="mt-3 h-12 w-full rounded-xl bg-leaf font-semibold text-white"
        >
          {L(lang, `दिन-ब-दिन रिपोर्ट · ${rupees(r.monthly_fee)}/महीना`, `Day-by-day report · ${rupees(r.monthly_fee)}/month`)}
        </button>
      )}
      <p className="mt-2 flex items-center gap-1 text-[11px] text-slate">
        <CheckIcon className="h-3 w-3" /> {L(lang, "हर दिन का रिकॉर्ड QR स्कैन, GPS और समय से पक्का", "Every day verified by QR scan, GPS and time")}
      </p>
    </section>
  );
}
