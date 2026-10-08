"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, get, logout, post, postForm } from "@/lib/api";
import { rupees, shortDate, shortTime } from "@/lib/format";
import { type Coords, getLocation, LocationError } from "@/lib/location";
import { speak } from "@/lib/speech";
import type { CollectorProfile, PickupResult, Route, RouteHome } from "@/lib/types";
import { InsuranceCard } from "@/components/InsuranceCard";
import { LiveCamera } from "@/components/LiveCamera";
import { QrScanner } from "@/components/QrScanner";
import { ScoreMeter } from "@/components/ScoreMeter";
import { CheckIcon, Logo, QrIcon, SpeakerIcon, StopIcon } from "@/components/icons";

type Lang = "hi" | "en";
type Tab = "route" | "earnings" | "score";
type Screen = { kind: "home" } | { kind: "scan" } | { kind: "mark"; door: Door } | { kind: "done"; result: PickupResult };
/** A door the collector is standing at: a scanned (or typed) QR, or in demo mode a home picked from the route. */
type Door = { qr: string; name?: string } | { householdId: number; name: string };

const L = (lang: Lang, hi: string, en: string) => (lang === "hi" ? hi : en);

/**
 * The door-to-door collector's app (Phase 2). Same login and score as a waste picker, but the work is
 * a route of doors: scan the QR on the door, mark the waste separated or mixed, move on. Every scan is
 * a verified working day and a fee from the household's Green Wallet.
 */
export function DoorApp({ profile, demo, reload }: { profile: CollectorProfile; demo: boolean; reload: () => void }) {
  const c = profile.collector;
  const [lang, setLang] = useState<Lang>(c.language);
  const [tab, setTab] = useState<Tab>("route");
  const [screen, setScreen] = useState<Screen>({ kind: "home" });
  const [route, setRoute] = useState<Route | null>(null);

  const loadRoute = useCallback(() => get<Route>("/collectors/me/route").then(setRoute).catch(() => {}), []);
  useEffect(() => {
    const first = setTimeout(loadRoute, 0);
    const id = setInterval(loadRoute, 8000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [loadRoute]);

  const back = () => {
    setScreen({ kind: "home" });
    loadRoute();
    reload();
  };

  return (
    <div className="kraft min-h-dvh">
      <div className="mx-auto flex min-h-dvh max-w-md flex-col">
        <header className="flex items-center gap-3 px-4 pt-4 pb-2">
          <Logo className="h-9 w-9" />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-slate">{L(lang, "घर-घर कलेक्शन", "Door-to-door")}</p>
            <p className="truncate font-display text-lg font-semibold leading-tight">{c.name}</p>
          </div>
          <button onClick={() => logout("collector")} className="h-11 rounded-full px-2 text-xs text-slate underline">
            {L(lang, "बाहर", "Log out")}
          </button>
          <button
            onClick={() => setLang(lang === "hi" ? "en" : "hi")}
            className="h-11 rounded-full border border-line bg-paper px-4 text-sm font-semibold"
            aria-label="Change language"
          >
            {lang === "hi" ? "EN" : "हिं"}
          </button>
          <button
            onClick={() => speak(L(lang, "दरवाज़े का QR स्कैन करें, फिर बताएँ कचरा अलग था या मिला-जुला।", "Scan the QR on the door, then say whether the waste was separated or mixed."), lang)}
            className="grid h-11 w-11 place-items-center rounded-full bg-ink text-kraft"
            aria-label="Read this screen aloud"
          >
            <SpeakerIcon className="h-5 w-5" />
          </button>
        </header>

        {screen.kind === "home" && (
          <>
            <main className="flex-1 space-y-4 px-4 pb-4">
              {tab === "route" && <RouteTab route={route} lang={lang} onScan={() => setScreen({ kind: "scan" })} />}
              {tab === "earnings" && <EarningsTab route={route} profile={profile} lang={lang} />}
              {tab === "score" && <ScoreTab profile={profile} lang={lang} reload={reload} />}
            </main>
            <nav className="sticky bottom-0 grid grid-cols-3 border-t border-line bg-paper/95 backdrop-blur">
              {(
                [
                  ["route", L(lang, "आज का राउंड", "Today's round")],
                  ["earnings", L(lang, "कमाई", "Earnings")],
                  ["score", L(lang, "स्कोर", "Score")],
                ] as const
              ).map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setTab(k)}
                  className={`h-16 text-sm font-semibold ${tab === k ? "text-leaf" : "text-slate"}`}
                  aria-current={tab === k}
                >
                  <span className={`mx-auto mb-1 block h-1 w-8 rounded-full ${tab === k ? "bg-leaf" : "bg-transparent"}`} />
                  {label}
                </button>
              ))}
            </nav>
          </>
        )}
        {screen.kind === "scan" && (
          <ScanDoor
            lang={lang}
            demo={demo}
            pending={(route?.homes ?? []).filter((h) => !h.today_status)}
            onDoor={(door) => setScreen({ kind: "mark", door })}
            onCancel={back}
          />
        )}
        {screen.kind === "mark" && (
          <MarkPickup
            door={screen.door}
            lang={lang}
            demo={demo}
            onDone={(result) => {
              setScreen({ kind: "done", result });
              const pts = result.points;
              speak(
                L(
                  lang,
                  `${result.household.name} दर्ज हो गया। ${rupees(result.fee.fee)} आपकी कमाई में जुड़े।${pts ? ` घर को ${pts} पॉइंट मिले।` : ""}`,
                  `${result.household.name} recorded. ${rupees(result.fee.fee)} added to your earnings.${pts ? ` The home got ${pts} points.` : ""}`,
                ),
                lang,
              );
            }}
            onCancel={back}
          />
        )}
        {screen.kind === "done" && <Done result={screen.result} lang={lang} onNext={() => setScreen({ kind: "scan" })} onHome={back} />}
      </div>
    </div>
  );
}

// ---------- Today's round ----------

function RouteTab({ route, lang, onScan }: { route: Route | null; lang: Lang; onScan: () => void }) {
  if (!route) return <p className="text-slate">…</p>;
  const total = route.homes.length;
  return (
    <>
      <button
        onClick={onScan}
        className="flex h-20 w-full items-center justify-center gap-3 rounded-2xl bg-leaf text-xl font-semibold text-white shadow-[0_4px_0_#155c39] active:translate-y-0.5 active:shadow-[0_2px_0_#155c39]"
      >
        <QrIcon className="h-8 w-8" /> {L(lang, "दरवाज़े का QR स्कैन करें", "Scan a door")}
      </button>

      <section className="rounded-3xl bg-ink p-5 text-kraft">
        <p className="text-sm opacity-80">{L(lang, "आज", "Today")}</p>
        <p className="font-display text-4xl font-bold tabular">
          {route.done} <span className="text-xl font-semibold opacity-70">/ {total} {L(lang, "घर", "homes")}</span>
        </p>
        <div className="mt-3 h-2 rounded-full bg-white/15">
          <div className="h-2 rounded-full bg-marigold" style={{ width: `${total ? (route.done / total) * 100 : 0}%` }} />
        </div>
        <p className="mt-2 text-sm tabular">
          {route.separated} {L(lang, "घरों ने कचरा अलग दिया", "separated")} · {L(lang, "आज की कमाई", "earned today")}{" "}
          <b className="text-marigold">{rupees(route.earnings.today)}</b>
        </p>
      </section>

      <ul className="rounded-2xl border border-line bg-paper">
        {route.homes.map((h) => (
          <li key={h.id} className="flex items-center gap-3 border-t border-line px-4 py-3 first:border-0">
            <span
              className={`grid h-8 w-8 shrink-0 place-items-center rounded-full ${
                h.today_status === "done" ? (h.today_segregation === "separated" ? "bg-leaf text-white" : "bg-marigold text-ink") : "bg-kraft-deep text-slate"
              }`}
            >
              {h.today_status === "done" ? <CheckIcon className="h-4 w-4" /> : h.kind === "bulk" ? "🏨" : "🏠"}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{h.name}</p>
              <p className="text-xs text-slate">
                {h.today_status === "done"
                  ? h.today_segregation === "separated"
                    ? L(lang, "अलग मिला", "Separated")
                    : L(lang, "मिला-जुला", "Mixed")
                  : h.today_status === "disputed"
                    ? L(lang, "घर ने शिकायत की", "Household disputed")
                    : h.last_day
                      ? `${L(lang, "पिछली बार", "Last")} ${shortDate(h.last_day + " 00:00:00")}`
                      : L(lang, "अभी बाकी", "Pending")}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

// ---------- Scan the door ----------

function ScanDoor({
  lang,
  demo,
  pending,
  onDoor,
  onCancel,
}: {
  lang: Lang;
  demo: boolean;
  pending: RouteHome[];
  onDoor: (d: Door) => void;
  onCancel: () => void;
}) {
  const [manual, setManual] = useState("");
  const handled = useRef(false);
  const onResult = useCallback(
    (text: string) => {
      if (handled.current) return;
      handled.current = true;
      onDoor({ qr: text.trim().toUpperCase() });
    },
    [onDoor],
  );

  return (
    <main className="flex-1 space-y-4 px-4 pb-6">
      <h2 className="text-center text-2xl font-semibold">{L(lang, "दरवाज़े का QR स्कैन करें", "Scan the QR on the door")}</h2>
      <QrScanner onResult={onResult} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (manual) onResult(manual);
        }}
        className="flex gap-2"
      >
        <input
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder={L(lang, "या कोड लिखें, जैसे WWH-…", "Or type the code, e.g. WWH-…")}
          className="h-12 min-w-0 flex-1 rounded-xl border border-line bg-white px-3 font-mono uppercase"
          aria-label="Door code"
        />
        <button className="h-12 rounded-xl bg-ink px-4 font-semibold text-white">OK</button>
      </form>
      {demo && pending.length > 0 && (
        <label className="flex items-center justify-center gap-2 text-xs text-slate">
          Demo: simulate scanning
          <select
            defaultValue=""
            onChange={(e) => {
              const h = pending.find((x) => x.id === Number(e.target.value));
              if (h) onDoor({ householdId: h.id, name: h.name });
            }}
            className="max-w-[60%] rounded-lg border border-line bg-paper px-2 py-1"
            aria-label="Demo door"
          >
            <option value="" disabled>
              pick a door…
            </option>
            {pending.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <button onClick={onCancel} className="h-12 w-full rounded-2xl border border-line bg-paper font-semibold">
        ✕ {L(lang, "वापस", "Back")}
      </button>
    </main>
  );
}

// ---------- Separated or mixed ----------

function MarkPickup({
  door,
  lang,
  demo,
  onDone,
  onCancel,
}: {
  door: Door;
  lang: Lang;
  demo: boolean;
  onDone: (r: PickupResult) => void;
  onCancel: () => void;
}) {
  const [segregation, setSegregation] = useState<"separated" | "mixed" | null>(null);
  const [photo, setPhoto] = useState<{ blob: Blob; preview: string } | null>(null);
  const [camera, setCamera] = useState(false);
  const [loc, setLoc] = useState<Coords | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const simulated = "householdId" in door;

  useEffect(() => {
    let live = true;
    getLocation(demo ? "demo" : "gps").then(
      (c) => live && setLoc(c),
      (e) =>
        live &&
        setError(
          e instanceof LocationError && e.reason === "timeout"
            ? L(lang, "जगह नहीं मिल पाई — खुली जगह पर जाकर दोबारा कोशिश करें", "Could not find your location — step outside and try again")
            : L(lang, "फ़ोन की जगह (GPS) बंद है — दरवाज़े पर होना ज़रूरी है", "Location is off — you must be at the door"),
        ),
    );
    return () => {
      live = false;
    };
  }, [demo, lang]);

  async function submit() {
    if (!segregation || !loc) return;
    setBusy(true);
    setError(null);
    try {
      let r: PickupResult;
      if ("householdId" in door) {
        r = await post<PickupResult>("/demo/pickups/simulate-scan", { household_id: door.householdId, segregation, lat: loc.lat, lng: loc.lng });
      } else {
        const f = new FormData();
        f.set("door_qr", door.qr);
        f.set("segregation", segregation);
        f.set("lat", String(loc.lat));
        f.set("lng", String(loc.lng));
        if (photo) f.set("photo", photo.blob, "waste.jpg");
        r = await postForm<PickupResult>("/pickups", f);
      }
      onDone(r);
    } catch (e) {
      const err = e as ApiError;
      const known: Record<string, [string, string]> = {
        already_picked_today: ["इस घर का कचरा आज पहले ही ले लिया गया है", "This door was already picked up today"],
        gps_far_from_home: ["आप इस घर से दूर हैं — दरवाज़े पर जाकर स्कैन करें", "You are too far from this home — scan at the door"],
        not_on_route: ["यह घर आपके राउंड में नहीं है", "This door is not on your route"],
        unknown_door: ["यह QR किसी रजिस्टर्ड घर का नहीं है", "This QR is not a registered door"],
        duplicate_photo: ["यह फ़ोटो पहले इस्तेमाल हो चुकी है — नई फ़ोटो लें", "This photo was already used — take a new one"],
      };
      const k = err.rule ? known[err.rule] : undefined;
      setError(k ? L(lang, k[0], k[1]) : err.message);
      speak(k ? L(lang, k[0], k[1]) : err.message, lang);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex-1 space-y-4 px-4 pb-6">
      {error && (
        <div role="alert" className="animate-pop flex items-start gap-3 rounded-2xl bg-brick p-4 text-white">
          <StopIcon className="h-7 w-7 shrink-0" />
          <p className="text-lg font-semibold">{error}</p>
        </div>
      )}
      <p className="rounded-2xl bg-ink px-4 py-3 text-kraft">
        <span className="text-xs opacity-70">{L(lang, "दरवाज़ा", "Door")}</span>
        <span className="block font-display text-lg font-semibold leading-tight">{door.name ?? ("qr" in door ? door.qr : "")}</span>
      </p>

      <h2 className="text-lg font-semibold">{L(lang, "कचरा कैसा मिला?", "How was the waste?")}</h2>
      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={() => setSegregation("separated")}
          aria-pressed={segregation === "separated"}
          className={`flex min-h-32 flex-col items-center justify-center gap-2 rounded-2xl border-4 p-3 text-center font-semibold ${
            segregation === "separated" ? "border-leaf bg-leaf text-white" : "border-leaf/40 bg-paper text-leaf-dark"
          }`}
        >
          <span className="text-4xl">🟢🔵</span>
          {L(lang, "अलग-अलग (गीला / सूखा)", "Separated (wet / dry)")}
        </button>
        <button
          onClick={() => setSegregation("mixed")}
          aria-pressed={segregation === "mixed"}
          className={`flex min-h-32 flex-col items-center justify-center gap-2 rounded-2xl border-4 p-3 text-center font-semibold ${
            segregation === "mixed" ? "border-marigold bg-marigold text-ink" : "border-marigold/50 bg-paper text-ink"
          }`}
        >
          <span className="text-4xl">🟤</span>
          {L(lang, "मिला-जुला", "Mixed")}
        </button>
      </div>

      {!simulated && (
        <section>
          {photo ? (
            <div className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={photo.preview} alt="Waste photo" className="aspect-[4/3] w-full rounded-2xl object-cover" />
              <button onClick={() => (setPhoto(null), setCamera(true))} className="absolute right-3 bottom-3 rounded-full bg-ink/80 px-4 py-2 text-sm font-semibold text-white">
                {L(lang, "दोबारा लें", "Retake")}
              </button>
            </div>
          ) : camera ? (
            <LiveCamera label={L(lang, "फ़ोटो लें", "Take a photo")} onCapture={(blob, preview) => (setPhoto({ blob, preview }), setCamera(false))} />
          ) : (
            <button onClick={() => setCamera(true)} className="flex h-14 w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-leaf bg-paper font-semibold text-leaf">
              📷 {L(lang, "सूखे कचरे की फ़ोटो (ज़रूरी नहीं)", "Photo of the dry waste (optional)")}
            </button>
          )}
        </section>
      )}

      <div className="flex gap-3">
        <button onClick={onCancel} className="h-14 flex-1 rounded-2xl border border-line bg-paper font-semibold">
          ✕
        </button>
        <button
          onClick={submit}
          disabled={!segregation || !loc || busy}
          className="h-14 flex-[3] rounded-2xl bg-leaf text-lg font-semibold text-white disabled:opacity-40"
        >
          {busy ? "…" : !loc && !error ? L(lang, "जगह देख रहे हैं…", "Finding location…") : L(lang, "दर्ज करें", "Record pickup")}
        </button>
      </div>
    </main>
  );
}

function Done({ result, lang, onNext, onHome }: { result: PickupResult; lang: Lang; onNext: () => void; onHome: () => void }) {
  const sep = result.pickup.segregation === "separated";
  return (
    <main className="flex flex-1 flex-col items-center gap-5 px-4 pb-6 text-center">
      <div className="animate-pop mt-6 w-full rounded-3xl bg-leaf p-6 text-white shadow-[0_6px_0_#155c39]">
        <CheckIcon className="mx-auto h-14 w-14" />
        <p className="mt-2 font-display text-2xl font-semibold">{result.household.name}</p>
        <p className="mt-1 text-lg">{sep ? L(lang, "कचरा अलग मिला", "Separated") : L(lang, "मिला-जुला", "Mixed")}</p>
        <p className="mt-4 font-display text-5xl font-extrabold tabular text-marigold">+{rupees(result.fee.fee)}</p>
        <p className="text-sm opacity-90">{L(lang, "आपकी कमाई में जुड़े", "added to your earnings")}</p>
        {result.points > 0 && (
          <p className="mx-auto mt-3 w-fit rounded-full bg-white/20 px-4 py-1 text-sm font-semibold">
            {L(lang, `घर को +${result.points} पॉइंट`, `Home earned +${result.points} points`)}
          </p>
        )}
      </div>
      <button onClick={onNext} className="h-16 w-full rounded-2xl bg-leaf text-lg font-semibold text-white">
        {L(lang, "अगला दरवाज़ा", "Next door")}
      </button>
      <button onClick={onHome} className="text-sm text-slate underline">
        {L(lang, "राउंड देखें", "Back to the round")}
      </button>
    </main>
  );
}

// ---------- Earnings and score ----------

function EarningsTab({ route, profile, lang }: { route: Route | null; profile: CollectorProfile; lang: Lang }) {
  const weeks = profile.income_by_week.slice(-4);
  const last4 = weeks.reduce((s, w) => s + w.value, 0);
  return (
    <section className="space-y-3">
      <div className="rounded-3xl bg-ink p-5 text-kraft">
        <p className="text-sm opacity-80">{L(lang, "इस महीने मिला", "Paid this month")}</p>
        <p className="font-display text-4xl font-bold text-marigold tabular">{rupees(route?.earnings.month_paid ?? 0)}</p>
        <p className="text-sm tabular">
          + {rupees(route?.earnings.month_pending ?? 0)} {L(lang, "आने वाला (घरों के AutoPay से)", "on its way (households' AutoPay)")}
        </p>
      </div>
      <div className="rounded-2xl border border-line bg-paper p-4 text-sm">
        <p>
          {L(lang, "पिछले 4 हफ़्ते की पक्की कमाई", "Verified income, last 4 weeks")}: <b className="tabular">{rupees(last4)}</b>
        </p>
        <p className="mt-1 text-xs text-slate">{L(lang, "हर पिकअप का रिकॉर्ड आपके लोन स्कोर में जुड़ता है", "Every pickup counts towards your loan score")}</p>
      </div>
      <div className="rounded-2xl border border-line bg-paper">
        <p className="px-4 pt-3 text-sm font-semibold">{L(lang, "हाल के पिकअप", "Recent pickups")}</p>
        <ul>
          {(route?.recent ?? []).map((p) => (
            <li key={p.id} className="flex items-center gap-3 border-t border-line px-4 py-3 first:border-0">
              <span className={`h-3 w-3 shrink-0 rounded-full ${p.status === "disputed" ? "bg-brick" : p.segregation === "separated" ? "bg-leaf" : "bg-marigold"}`} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{p.name}</p>
                <p className="text-xs text-slate">
                  {shortTime(p.created_at)} ·{" "}
                  {p.status === "disputed" ? L(lang, "घर ने मना किया", "disputed") : p.fee_status === "paid" ? L(lang, "पैसा मिला", "paid") : L(lang, "आने वाला", "on its way")}
                </p>
              </div>
              <p className={`text-sm font-semibold tabular ${p.status === "disputed" ? "text-slate line-through" : ""}`}>{p.fee != null ? rupees(p.fee) : "—"}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function ScoreTab({ profile, lang, reload }: { profile: CollectorProfile; lang: Lang; reload: () => void }) {
  const el = profile.eligibility;
  return (
    <section className="space-y-3">
      <div className="grid place-items-center rounded-3xl border border-line bg-paper p-5">
        {profile.score && <ScoreMeter score={profile.score.score} />}
        {el.eligible ? (
          <p className="mt-2 flex items-center gap-2 rounded-full bg-leaf-soft px-4 py-2 font-semibold text-leaf-dark">
            <CheckIcon className="h-5 w-5" /> {L(lang, "पहला लोन खुल गया", "Starter loan unlocked")} · {rupees(el.limit)}
          </p>
        ) : (
          <p className="mt-2 text-center text-sm">{el.checks.filter((c) => !c.ok).map((c) => c.label).join(" · ")}</p>
        )}
      </div>
      {profile.score && (
        <div className="rounded-2xl border border-line bg-paper p-4">
          <ul className="space-y-3">
            {Object.entries(profile.score.inputs).map(([k, v]) => (
              <li key={k}>
                <p className="text-sm font-semibold">{inputLabel(k, lang)}</p>
                <div className="mt-1 h-3 rounded-full bg-kraft-deep">
                  <div className="h-3 rounded-full bg-leaf" style={{ width: `${v.value * 100}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      <InsuranceCard status={profile.insurance} lang={lang} onChanged={reload} />
    </section>
  );
}

function inputLabel(k: string, lang: Lang) {
  const hi: Record<string, string> = { A: "रोज़ का काम", C: "कमाई में स्थिरता", T: "कितने समय से", D: "कितने घर", R: "लोन चुकाना" };
  const en: Record<string, string> = { A: "Working days", C: "Steady income", T: "Time on WorthyWaste", D: "Homes served", R: "Repayment" };
  return (lang === "hi" ? hi : en)[k];
}
