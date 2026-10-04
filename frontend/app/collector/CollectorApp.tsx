"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, get, logout, post, postForm } from "@/lib/api";
import { kg, metres, mmss, parseTs, rupees, shortDate, shortTime } from "@/lib/format";
import { mismatchMaterials, mismatchVoice, t, voice, type Lang } from "@/lib/i18n";
import { type Coords, getLocation, LocationError } from "@/lib/location";
import { speak, speakMessage } from "@/lib/speech";
import type {
  CollectorProfile, Material, Message, MyRequest, NearbyDealer, PhotoMismatch, RequestStatus,
  SaleRequest, Transaction,
} from "@/lib/types";
import { LiveCamera } from "@/components/LiveCamera";
import { QrCode } from "@/components/QrCode";
import { ScoreMeter } from "@/components/ScoreMeter";
import { CheckIcon, Logo, MaterialIcon, SpeakerIcon, StopIcon } from "@/components/icons";

type Screen = "home" | "sale" | "waiting" | "received";
type Tab = "card" | "wallet" | "score";

export function CollectorApp({ collectorId, demo }: { collectorId: number; demo: boolean }) {
  const [profile, setProfile] = useState<CollectorProfile | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [lang, setLang] = useState<Lang>("hi");
  const [screen, setScreen] = useState<Screen>("home");
  const [tab, setTab] = useState<Tab>("card");
  const [active, setActive] = useState<SaleRequest | null>(null);
  const [activeShop, setActiveShop] = useState("");
  const [lastTx, setLastTx] = useState<Transaction | null>(null);

  const load = useCallback(async () => {
    const p = await get<CollectorProfile>(`/collectors/${collectorId}`);
    setProfile(p);
    return p;
  }, [collectorId]);

  useEffect(() => {
    get<CollectorProfile>(`/collectors/${collectorId}`).then((p) => {
      setProfile(p);
      setLang(p.collector.language);
    });
    get<Material[]>("/materials").then(setMaterials);
  }, [collectorId]);

  if (!profile) return <div className="kraft min-h-dvh grid place-items-center text-slate">…</div>;
  const c = profile.collector;
  const mat = (code: string) => materials.find((m) => m.code === code);
  const matLabel = (code: string) => (lang === "hi" ? mat(code)?.label_hi : mat(code)?.label_en) ?? code;

  return (
    <div className="kraft min-h-dvh">
      <div className="mx-auto flex min-h-dvh max-w-md flex-col">
        <header className="flex items-center gap-3 px-4 pt-4 pb-2">
          <Logo className="h-9 w-9" />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-slate">{t(lang, "homeHello")}</p>
            <p className="truncate font-display text-lg font-semibold leading-tight">{c.name}</p>
          </div>
          <button
            onClick={() => logout("collector")}
            className="h-11 rounded-full px-2 text-xs text-slate underline"
            aria-label="Log out"
          >
            {lang === "hi" ? "बाहर" : "Log out"}
          </button>
          <button
            onClick={() => setLang(lang === "hi" ? "en" : "hi")}
            className="h-11 rounded-full border border-line bg-paper px-4 text-sm font-semibold"
            aria-label="Change language"
          >
            {lang === "hi" ? "EN" : "हिं"}
          </button>
          <button
            onClick={() => speak(voice[screen === "sale" ? "sale" : screen === "waiting" ? "waiting" : "home"][lang], lang)}
            className="grid h-11 w-11 place-items-center rounded-full bg-ink text-kraft"
            aria-label="Read this screen aloud"
          >
            <SpeakerIcon className="h-5 w-5" />
          </button>
        </header>

        {screen === "home" && (
          <Home
            profile={profile}
            lang={lang}
            tab={tab}
            setTab={setTab}
            matLabel={matLabel}
            onNewSale={() => setScreen("sale")}
          />
        )}
        {screen === "sale" && (
          <NewSale
            collectorId={collectorId}
            materials={materials}
            lang={lang}
            demo={demo}
            onCancel={() => setScreen("home")}
            onSent={(r, shopName) => {
              setActive(r);
              setActiveShop(shopName);
              setScreen("waiting");
              speak(voice.waiting[lang], lang);
            }}
          />
        )}
        {screen === "waiting" && active && (
          <Waiting
            request={active}
            shopName={activeShop}
            qr={c.qr_token}
            lang={lang}
            onDone={(tx) => {
              setLastTx(tx);
              setScreen("received");
              load().then((p) => {
                const msg = p.messages[0];
                if (msg) speakMessage(msg);
              });
            }}
            onCancel={() => {
              setScreen("home");
              load();
            }}
          />
        )}
        {screen === "received" && lastTx && (
          <Received
            tx={lastTx}
            lang={lang}
            matLabel={matLabel}
            message={profile.messages[0]}
            onDone={() => {
              setScreen("home");
              setTab("wallet");
            }}
          />
        )}
      </div>
    </div>
  );
}

// ---------- Home: card / wallet / score ----------

const STATUS_TONE: Record<string, string> = {
  open: "bg-marigold-soft text-ink",
  accepted: "bg-marigold-soft text-ink",
  weighed: "bg-marigold-soft text-ink",
  paying: "bg-marigold-soft text-ink",
  completed: "bg-leaf-soft text-leaf-dark",
  expired: "bg-brick-soft text-brick",
  rejected: "bg-brick-soft text-brick",
  cancelled: "bg-kraft-deep text-slate",
  awaiting_ivr: "bg-marigold-soft text-ink",
};

function statusLabel(status: RequestStatus, lang: Lang): string {
  const key = {
    open: "stepSent", accepted: "stepAccepted", weighed: "stepWeighed", paying: "stepPaying",
    completed: "stepPaid", cancelled: "cancelled", expired: "expired", rejected: "expired",
    awaiting_ivr: "stepSent",
  }[status];
  return t(lang, key as Parameters<typeof t>[1]);
}

/** The collector's own sales and where each has got to — their side of the dealer's queue. */
function MyRequests({ lang, matLabel }: { lang: Lang; matLabel: (c: string) => string }) {
  const [rows, setRows] = useState<MyRequest[] | null>(null);

  useEffect(() => {
    const load = () => get<MyRequest[]>("/collectors/me/requests").then(setRows).catch(() => {});
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  if (!rows) return null;
  return (
    <div className="rounded-2xl border border-line bg-paper">
      <p className="px-4 pt-3 text-sm font-semibold">{t(lang, "myRequests")}</p>
      {rows.length === 0 && <p className="px-4 pb-3 text-sm text-slate">{t(lang, "noRequests")}</p>}
      <ul>
        {rows.slice(0, 8).map((r) => (
          <li key={r.id} className="flex items-center gap-3 border-t border-line px-4 py-3 first:border-0">
            <MaterialIcon code={r.dealer_material ?? r.material} className="h-8 w-8 text-leaf" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{r.shop_name ?? "—"}</p>
              <p className="text-xs text-slate">
                {matLabel(r.dealer_material ?? r.material)} · {kg(r.scale_kg ?? r.est_kg)} ·{" "}
                {shortTime(r.created_at)}
              </p>
            </div>
            <div className="text-right">
              <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_TONE[r.status] ?? ""}`}>
                {statusLabel(r.status, lang)}
              </span>
              {r.amount != null && <p className="mt-0.5 text-sm font-semibold tabular">{rupees(r.amount)}</p>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Home({
  profile,
  lang,
  tab,
  setTab,
  matLabel,
  onNewSale,
}: {
  profile: CollectorProfile;
  lang: Lang;
  tab: Tab;
  setTab: (t: Tab) => void;
  matLabel: (c: string) => string;
  onNewSale: () => void;
}) {
  const c = profile.collector;
  const [openedAt] = useState(() => Date.now());
  const monthAgo = openedAt - 30 * 86400_000;
  const month = profile.transactions.filter((x) => parseTs(x.created_at).getTime() >= monthAgo);
  const monthAmt = month.reduce((s, x) => s + x.amount, 0);
  const monthKg = month.reduce((s, x) => s + x.scale_kg, 0);

  return (
    <>
      <main className="flex-1 space-y-4 px-4 pb-4">
        <button
          onClick={onNewSale}
          className="flex h-20 w-full items-center justify-center gap-3 rounded-2xl bg-leaf text-xl font-semibold text-white shadow-[0_4px_0_#155c39] active:translate-y-0.5 active:shadow-[0_2px_0_#155c39]"
        >
          <span className="text-3xl leading-none">+</span> {t(lang, "newSale")}
        </button>

        {tab === "card" && (
          <section className="rounded-3xl border border-line bg-paper p-5 shadow-sm">
            <div className="flex items-start justify-between">
              <div>
                <p className="font-display text-xl font-semibold">{c.name}</p>
                <p className="text-sm text-slate">{c.group_name}</p>
              </div>
              <span className="rounded-full bg-marigold-soft px-3 py-1 text-sm font-semibold tabular">
                {c.credits} {t(lang, "credits")}
              </span>
            </div>
            <div className="mt-4 grid place-items-center">
              <QrCode value={c.qr_token} size={230} className="rounded-xl bg-white p-2" />
              <p className="mt-2 font-mono text-sm tracking-widest text-slate">{c.qr_token}</p>
            </div>
            <p className="mt-3 text-center text-xs text-slate">{t(lang, "cardHelp")}</p>
          </section>
        )}

        {tab === "wallet" && (
          <section className="space-y-3">
            <div className="rounded-3xl bg-ink p-5 text-kraft">
              <p className="text-sm opacity-80">{t(lang, "thisMonth")}</p>
              <p className="font-display text-4xl font-bold text-marigold tabular">{rupees(monthAmt)}</p>
              <p className="text-sm tabular">
                {kg(Math.round(monthKg))} · {month.length} {lang === "hi" ? "बिक्री" : "sales"} · {c.credits} {t(lang, "credits")}
              </p>
            </div>
            <MyRequests lang={lang} matLabel={matLabel} />
            {profile.messages.length > 0 && (
              <div className="rounded-2xl border border-line bg-paper p-4">
                <p className="mb-2 text-sm font-semibold">{t(lang, "messages")}</p>
                {profile.messages.slice(0, 3).map((m) => (
                  <button
                    key={m.id}
                    onClick={() => speakMessage(m)}
                    className="flex w-full items-start gap-2 border-t border-line py-2 text-left text-sm first:border-0"
                  >
                    <SpeakerIcon className="mt-0.5 h-4 w-4 shrink-0 text-leaf" />
                    <span>{m.text}</span>
                  </button>
                ))}
              </div>
            )}
            <div className="rounded-2xl border border-line bg-paper">
              <p className="px-4 pt-3 text-sm font-semibold">{t(lang, "recentSales")}</p>
              <ul>
                {profile.transactions.slice(0, 12).map((x) => (
                  <li key={x.id} className="flex items-center gap-3 border-t border-line px-4 py-3 first:border-0">
                    <MaterialIcon code={x.material} className="h-8 w-8 text-leaf" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{matLabel(x.material)}</p>
                      <p className="text-xs text-slate">
                        {shortDate(x.created_at)} · {x.shop_name}
                      </p>
                    </div>
                    <div className="text-right tabular">
                      <p className="font-semibold">{rupees(x.amount)}</p>
                      <p className="text-xs text-slate">{kg(x.scale_kg)}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        )}

        {tab === "score" && profile.score && (
          <section className="space-y-3">
            <div className="grid place-items-center rounded-3xl border border-line bg-paper p-5">
              <ScoreMeter score={profile.score.score} />
              {profile.eligibility.eligible ? (
                <p className="mt-2 flex items-center gap-2 rounded-full bg-leaf-soft px-4 py-2 font-semibold text-leaf-dark">
                  <CheckIcon className="h-5 w-5" /> {t(lang, "loanUnlocked")} · {rupees(profile.eligibility.limit)}
                </p>
              ) : (
                <LoanProgress profile={profile} lang={lang} />
              )}
            </div>
            <div className="rounded-2xl border border-line bg-paper p-4">
              <ul className="space-y-3">
                {Object.entries(profile.score.inputs).map(([k, v]) => (
                  <li key={k}>
                    <div className="flex justify-between text-sm">
                      <span className="font-semibold">{inputLabel(k, lang)}</span>
                    </div>
                    <div className="mt-1 h-3 rounded-full bg-kraft-deep">
                      <div className="h-3 rounded-full bg-leaf" style={{ width: `${v.value * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        )}
      </main>

      <nav className="sticky bottom-0 grid grid-cols-3 border-t border-line bg-paper/95 backdrop-blur">
        {(["card", "wallet", "score"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`h-16 text-sm font-semibold ${tab === k ? "text-leaf" : "text-slate"}`}
            aria-current={tab === k}
          >
            <span className={`mx-auto mb-1 block h-1 w-8 rounded-full ${tab === k ? "bg-leaf" : "bg-transparent"}`} />
            {t(lang, k === "card" ? "myCard" : k)}
          </button>
        ))}
      </nav>
    </>
  );
}

function inputLabel(k: string, lang: Lang) {
  const hi: Record<string, string> = { A: "रोज़ की बिक्री", C: "कमाई में स्थिरता", T: "कितने समय से", D: "कितने डीलर", R: "लोन चुकाना" };
  const en: Record<string, string> = { A: "Selling days", C: "Steady income", T: "Time on WorthyWaste", D: "Dealers", R: "Repayment" };
  return (lang === "hi" ? hi : en)[k];
}

function LoanProgress({ profile, lang }: { profile: CollectorProfile; lang: Lang }) {
  const n = profile.eligibility.sales_to_unlock;
  const done = 20 - n;
  return (
    <div className="mt-3 w-full">
      <div className="h-3 rounded-full bg-kraft-deep">
        <div className="h-3 rounded-full bg-marigold" style={{ width: `${(done / 20) * 100}%` }} />
      </div>
      <p className="mt-2 text-center text-sm">
        {n > 0 ? (
          <>
            <b className="tabular">{n}</b> {t(lang, "loanIn")}
          </>
        ) : (
          profile.eligibility.checks.filter((c) => !c.ok).map((c) => c.label).join(" · ")
        )}
      </p>
    </div>
  );
}

// ---------- New sale ----------

function NewSale({
  collectorId,
  materials,
  lang,
  demo,
  onCancel,
  onSent,
}: {
  collectorId: number;
  materials: Material[];
  lang: Lang;
  demo: boolean;
  onCancel: () => void;
  onSent: (r: SaleRequest, shopName: string) => void;
}) {
  const [material, setMaterial] = useState("plastic");
  const [est, setEst] = useState(28);
  const [photo, setPhoto] = useState<{ blob: Blob; preview: string } | null>(null);
  const [camera, setCamera] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<{ msg: string; help?: string; rule?: string | null } | null>(null);
  // The photo check disagreed. We hold the warning here rather than sending: the collector decides.
  const [warn, setWarn] = useState<{ ai: PhotoMismatch; photo: { blob: Blob; preview: string } } | null>(null);
  // Demo only: what the photo check should pretend to see, so the warning can be shown on stage.
  const [demoAi, setDemoAi] = useState("");
  // Where we are, and the shops we can reach from here. The location is resolved when the screen
  // opens rather than at send time, because it decides which shops are even on the list.
  const [loc, setLoc] = useState<Coords | null>(null);
  const [shops, setShops] = useState<NearbyDealer[] | null>(null);
  const [shopId, setShopId] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    getLocation(demo ? "demo" : "gps").then(
      (c) => live && setLoc(c),
      (e) => {
        if (!live) return;
        const timedOut = e instanceof LocationError && e.reason === "timeout";
        setError({
          msg: t(lang, timedOut ? "locationTimeout" : "locationDenied"),
          help: t(lang, timedOut ? "locationTimeoutHelp" : "locationDeniedHelp"),
          rule: "location_missing",
        });
      },
    );
    return () => {
      live = false;
    };
  }, [demo, lang]);

  useEffect(() => {
    if (!loc) return;
    let live = true;
    get<NearbyDealer[]>(`/dealers/nearby?lat=${loc.lat}&lng=${loc.lng}`).then((rows) => {
      if (!live) return;
      setShops(rows);
      // The shop they sold to last is the likely answer; otherwise the nearest one.
      setShopId(rows.find((r) => r.last_used)?.id ?? rows[0]?.id ?? null);
    }, () => live && setShops([]));
    return () => {
      live = false;
    };
  }, [loc]);

  async function send(p = photo, { confirmMismatch = false } = {}) {
    if (!p || !loc || shopId === null) return;
    setSending(true);
    setError(null);
    const f = new FormData();
    f.set("collector_id", String(collectorId));
    f.set("dealer_id", String(shopId));
    f.set("material", material);
    f.set("est_kg", String(est));
    f.set("lat", String(loc.lat));
    f.set("lng", String(loc.lng));
    f.set("photo", p.blob, "scrap.jpg");
    if (confirmMismatch) f.set("confirm_mismatch", "1");
    if (demo && demoAi) f.set("demo_ai_material", demoAi);
    try {
      const r = await postForm<SaleRequest>("/requests", f);
      lastPhoto = p;
      setWarn(null);
      onSent(r, shops?.find((x) => x.id === shopId)?.shop_name ?? "");
    } catch (e) {
      const err = e as ApiError;
      if (err.rule === "photo_mismatch") {
        const ai = err.evidence as unknown as PhotoMismatch;
        setWarn({ ai, photo: p });
        speak(mismatchVoice(lang, ai.material), lang);
        setSending(false);
        return;
      }
      const msg = err.rule === "duplicate_photo" ? t(lang, "dupPhoto") : err.message;
      setError({ msg, help: err.rule === "duplicate_photo" ? t(lang, "dupPhotoHelp") : undefined, rule: err.rule });
      if (err.rule === "duplicate_photo") speak(t(lang, "dupPhoto") + (lang === "hi" ? "। " : ". ") + t(lang, "dupPhotoHelp"), lang);
    } finally {
      setSending(false);
    }
  }

  if (warn) {
    return (
      <PhotoWarning
        ai={warn.ai}
        materials={materials}
        lang={lang}
        sending={sending}
        onChange={() => {
          setWarn(null);
          setPhoto(warn.photo);
        }}
        onSendAnyway={() => send(warn.photo, { confirmMismatch: true })}
      />
    );
  }

  return (
    <main className="flex-1 space-y-5 px-4 pb-6">
      {error && (
        <div role="alert" className="animate-pop flex items-start gap-3 rounded-2xl bg-brick p-4 text-white">
          <StopIcon className="h-7 w-7 shrink-0" />
          <div>
            <p className="text-lg font-semibold">{error.msg}</p>
            {error.help && <p className="text-sm opacity-90">{error.help}</p>}
          </div>
        </div>
      )}

      <section>
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-lg font-semibold">{t(lang, "chooseShop")}</h2>
          <button
            onClick={() => speak(voice.shop[lang], lang)}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-kraft"
            aria-label="Read this question aloud"
          >
            <SpeakerIcon className="h-4 w-4" />
          </button>
        </div>
        {shops === null ? (
          <p className="rounded-2xl border border-line bg-paper p-4 text-sm text-slate">…</p>
        ) : shops.length === 0 ? (
          <p className="rounded-2xl border border-line bg-paper p-4 text-sm text-slate">
            {t(lang, "noShopsNearby")}
          </p>
        ) : (
          <select
            value={shopId ?? ""}
            onChange={(e) => setShopId(Number(e.target.value))}
            className="h-16 w-full rounded-2xl border-2 border-line bg-paper px-4 text-lg font-semibold"
            aria-label={t(lang, "chooseShop")}
          >
            {shops.map((d) => (
              <option key={d.id} value={d.id}>
                {d.shop_name} · {metres(d.distance_m)} {t(lang, "away")}
                {d.last_used ? ` · ${t(lang, "lastUsed")}` : ""}
              </option>
            ))}
          </select>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">{t(lang, "whatScrap")}</h2>
        <div className="grid grid-cols-3 gap-2">
          {materials.map((m) => (
            <button
              key={m.code}
              onClick={() => setMaterial(m.code)}
              aria-pressed={material === m.code}
              className={`flex min-h-24 flex-col items-center justify-center gap-1 rounded-2xl border-2 p-2 text-center text-xs font-semibold ${
                material === m.code ? "border-leaf bg-leaf-soft text-leaf-dark" : "border-line bg-paper text-ink"
              }`}
            >
              <MaterialIcon code={m.code} className="h-10 w-10" />
              {lang === "hi" ? m.label_hi : m.label_en}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">{t(lang, "howMuch")}</h2>
        <div className="flex items-center gap-3 rounded-2xl border border-line bg-paper p-3">
          <button onClick={() => setEst((v) => Math.max(1, v - 1))} className="h-14 w-14 rounded-xl bg-kraft-deep text-2xl font-bold" aria-label="Less">
            −
          </button>
          <p className="flex-1 text-center font-display text-4xl font-bold tabular">
            {est} <span className="text-xl font-semibold text-slate">kg</span>
          </p>
          <button onClick={() => setEst((v) => Math.min(150, v + 1))} className="h-14 w-14 rounded-xl bg-kraft-deep text-2xl font-bold" aria-label="More">
            +
          </button>
        </div>
        <input
          type="range"
          min={1}
          max={100}
          value={est}
          onChange={(e) => setEst(Number(e.target.value))}
          className="mt-3 w-full accent-[#1E7F4F]"
          aria-label="Estimated weight in kg"
        />
      </section>

      <section>
        {photo ? (
          <div className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={photo.preview} alt="Scrap photo" className="aspect-[4/3] w-full rounded-2xl object-cover" />
            <button
              onClick={() => {
                setPhoto(null);
                setCamera(true);
              }}
              className="absolute right-3 bottom-3 rounded-full bg-ink/80 px-4 py-2 text-sm font-semibold text-white"
            >
              {t(lang, "retake")}
            </button>
          </div>
        ) : camera ? (
          <LiveCamera label={t(lang, "takePhoto")} onCapture={(blob, preview) => (setPhoto({ blob, preview }), setCamera(false))} />
        ) : (
          <button
            onClick={() => setCamera(true)}
            className="flex h-16 w-full items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-leaf bg-paper text-lg font-semibold text-leaf"
          >
            📷 {t(lang, "takePhoto")}
          </button>
        )}
        {demo && (
          <div className="mt-2 space-y-2">
            {lastPhoto && !photo && (
              <button onClick={() => send(lastPhoto!)} className="w-full text-center text-xs text-slate underline">
                Demo: resend the previous photo
              </button>
            )}
            <label className="flex items-center justify-center gap-2 text-xs text-slate">
              Demo: fake the AI answer
              <select
                value={demoAi}
                onChange={(e) => setDemoAi(e.target.value)}
                className="rounded-lg border border-line bg-paper px-2 py-1"
                aria-label="Demo photo check result"
              >
                <option value="">off — real AI</option>
                {mismatchMaterials.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
                <option value="not_scrap">not scrap</option>
              </select>
            </label>
          </div>
        )}
      </section>

      <div className="flex gap-3">
        <button onClick={onCancel} className="h-14 flex-1 rounded-2xl border border-line bg-paper font-semibold">
          ✕
        </button>
        <button
          onClick={() => send()}
          disabled={!photo || sending || shopId === null}
          className="h-14 flex-[3] rounded-2xl bg-leaf text-lg font-semibold text-white disabled:opacity-40"
        >
          {sending ? "…" : t(lang, "send")}
        </button>
      </div>
    </main>
  );
}

// Kept across screens so the demo can replay the "same photo again" fraud.
let lastPhoto: { blob: Blob; preview: string } | null = null;

/** What the photo check saw, in the collector's language. Falls back for the answers that are not
 *  one of the six materials: a mixed load, nothing recyclable, or a photo of a screen. */
function aiMaterialLabel(
  ai: { material: string | null; real_scene: boolean | null },
  materials: Material[],
  lang: Lang,
): string {
  if (ai.real_scene === false) return t(lang, "aiScreen");
  if (ai.material === "not_scrap") return t(lang, "aiNotScrap");
  if (ai.material === "mixed") return t(lang, "aiMixed");
  const m = materials.find((x) => x.code === ai.material);
  if (m) return lang === "hi" ? m.label_hi : m.label_en;
  return ai.material ?? "—";
}

// ---------- The photo check disagreed ----------

/**
 * Shown instead of sending, once. The AI is not allowed to refuse a sale — a collector who knows
 * what is in their sack can send it anyway, and the dealer and Satin see the disagreement. So there
 * are two doors out of this screen and neither of them is a dead end.
 */
function PhotoWarning({
  ai,
  materials,
  lang,
  sending,
  onChange,
  onSendAnyway,
}: {
  ai: PhotoMismatch;
  materials: Material[];
  lang: Lang;
  sending: boolean;
  onChange: () => void;
  onSendAnyway: () => void;
}) {
  const line = mismatchVoice(lang, ai.material);
  const chose = lang === "hi" ? ai.chose_label_hi : ai.chose_label_en;
  const pct = ai.confidence == null ? null : Math.round(ai.confidence * 100);
  // The spoken line is already in their language; the card has to match it. "cardboard" next to
  // "ये गत्ता लग रहा है" reads as two different answers.
  const seen = aiMaterialLabel(ai, materials, lang);

  return (
    <main className="flex flex-1 flex-col gap-4 px-4 pb-6">
      <div role="alert" className="animate-pop rounded-2xl bg-marigold p-5 text-ink">
        <p className="font-display text-2xl font-semibold leading-snug">{t(lang, "photoMismatch")}</p>
        <p className="mt-2 text-lg">{line}</p>
        <button
          onClick={() => speak(line, lang)}
          className="mt-3 flex items-center gap-2 rounded-full bg-ink px-4 py-2 text-sm font-semibold text-kraft"
        >
          <SpeakerIcon className="h-4 w-4" /> {lang === "hi" ? "फिर से सुनें" : "Play again"}
        </button>
      </div>

      <div className="flex items-center justify-center gap-4 rounded-2xl border border-line bg-paper p-4">
        <div className="text-center">
          <p className="text-xs text-slate">{t(lang, "youChose")}</p>
          <MaterialIcon code={ai.chose} className="mx-auto my-1 h-12 w-12 text-leaf" />
          <p className="text-sm font-semibold">{chose}</p>
        </div>
        <span className="text-2xl text-slate">≠</span>
        <div className="text-center">
          <p className="text-xs text-slate">{lang === "hi" ? "फ़ोटो में" : "In the photo"}</p>
          {ai.material && ai.material !== "not_scrap" ? (
            <MaterialIcon code={ai.material} className="mx-auto my-1 h-12 w-12 text-brick" />
          ) : (
            <StopIcon className="mx-auto my-1 h-12 w-12 text-brick" />
          )}
          <p className="text-sm font-semibold">
            {seen}
            {pct != null && <span className="font-normal text-slate"> · {pct}%</span>}
          </p>
        </div>
      </div>

      <button
        onClick={onChange}
        disabled={sending}
        className="h-16 rounded-2xl bg-leaf text-lg font-semibold text-white disabled:opacity-50"
      >
        {t(lang, "changeMaterial")}
      </button>
      <button
        onClick={onSendAnyway}
        disabled={sending}
        className="h-14 rounded-2xl border-2 border-line bg-paper font-semibold disabled:opacity-50"
      >
        {sending ? "…" : t(lang, "sendAnyway")}
      </button>
    </main>
  );
}

// ---------- Waiting for the dealer ----------

/** Sent → Accepted → Weighed → Paying → Paid, and where this request has got to. */
const TIMELINE = [
  { key: "stepSent", reached: ["open", "accepted", "weighed", "paying", "completed"] },
  { key: "stepAccepted", reached: ["accepted", "weighed", "paying", "completed"] },
  { key: "stepWeighed", reached: ["weighed", "paying", "completed"] },
  { key: "stepPaying", reached: ["paying", "completed"] },
  { key: "stepPaid", reached: ["completed"] },
] as const;

function Timeline({ status, lang }: { status: RequestStatus; lang: Lang }) {
  return (
    <ol className="w-full space-y-1">
      {TIMELINE.map((step, i) => {
        const done = (step.reached as readonly string[]).includes(status);
        const current = done && !(TIMELINE[i + 1]?.reached as readonly string[] | undefined)?.includes(status);
        return (
          <li key={step.key} className="flex items-center gap-3 text-left">
            <span
              className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-xs font-bold ${
                done ? "bg-leaf text-white" : "bg-kraft-deep text-slate"
              }`}
            >
              {done ? <CheckIcon className="h-4 w-4" /> : i + 1}
            </span>
            <span className={current ? "font-semibold" : done ? "" : "text-slate"}>{t(lang, step.key)}</span>
            {current && status !== "completed" && (
              <span className="h-2 w-2 animate-pulse rounded-full bg-leaf" aria-hidden />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Waiting({
  request,
  shopName,
  qr,
  lang,
  onDone,
  onCancel,
}: {
  request: SaleRequest;
  shopName: string;
  qr: string;
  lang: Lang;
  onDone: (tx: Transaction) => void;
  onCancel: () => void;
}) {
  const [req, setReq] = useState(request);
  const [now, setNow] = useState(() => Date.now());
  const [cancelling, setCancelling] = useState(false);
  const doneRef = useRef(false);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  }, [onDone]);

  useEffect(() => {
    const id = setInterval(async () => {
      setNow(Date.now());
      const r = await get<{ request: SaleRequest; transaction: Transaction | null }>(`/requests/${request.id}`).catch(() => null);
      if (!r) return;
      setReq(r.request);
      if (r.transaction && !doneRef.current) {
        doneRef.current = true;
        onDoneRef.current(r.transaction);
      }
    }, 1200);
    return () => clearInterval(id);
  }, [request.id]);

  const left = parseTs(req.expires_at).getTime() - now;
  const status = req.status;

  if (status === "expired" || status === "rejected" || status === "cancelled") {
    return (
      <main className="flex-1 space-y-4 px-4">
        <div className="rounded-2xl bg-brick p-5 text-white">
          <p className="text-lg font-semibold">
            {status === "cancelled" ? t(lang, "cancelled") : t(lang, "expired")}
          </p>
        </div>
        <button onClick={onCancel} className="h-14 w-full rounded-2xl bg-leaf font-semibold text-white">
          {t(lang, "done")}
        </button>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col items-center gap-4 px-4 pb-6 text-center">
      {shopName && (
        <p className="w-full rounded-2xl bg-ink px-4 py-3 text-kraft">
          <span className="text-xs opacity-70">{t(lang, "sellingTo")}</span>
          <span className="block font-display text-lg font-semibold leading-tight">{shopName}</span>
        </p>
      )}
      <h2 className="text-2xl font-semibold">{t(lang, "showQr")}</h2>
      <QrCode value={qr} size={220} className="rounded-2xl bg-white p-3 shadow" />
      {/* For a dealer whose camera can't read the QR (or a laptop): they type this instead. */}
      <p className="-mt-2 text-xs text-slate">
        {lang === "hi" ? "QR न पढ़ पाए तो डीलर ये कोड लिखें" : "If the QR won't scan, the dealer types this code"}
        <span className="mt-1 block font-mono text-2xl font-bold tracking-widest text-ink">{qr}</span>
      </p>
      {status === "open" && (
        <p className="text-slate">
          {t(lang, "expiresIn")} <b className="font-display text-2xl text-ink tabular">{mmss(left)}</b>
        </p>
      )}
      <div className="w-full rounded-2xl border border-line bg-paper p-4">
        <Timeline status={status} lang={lang} />
      </div>
      <p className="text-sm text-slate tabular">
        {kg(req.scale_kg ?? req.est_kg)} · #{req.id}
      </p>
      {status === "open" ? (
        <button
          onClick={async () => {
            setCancelling(true);
            await post<SaleRequest>(`/requests/${req.id}/cancel`).catch(() => {});
            setCancelling(false);
            onCancel();
          }}
          disabled={cancelling}
          className="mt-auto h-12 w-full rounded-2xl border-2 border-line bg-paper font-semibold text-brick disabled:opacity-50"
        >
          {cancelling ? "…" : t(lang, "cancel")}
        </button>
      ) : (
        <button onClick={onCancel} className="mt-auto text-sm text-slate underline">
          ← {lang === "hi" ? "वापस" : "Back"}
        </button>
      )}
    </main>
  );
}

// ---------- Credits received ----------

function Received({
  tx,
  lang,
  matLabel,
  message,
  onDone,
}: {
  tx: Transaction;
  lang: Lang;
  matLabel: (c: string) => string;
  message?: Message;
  onDone: () => void;
}) {
  return (
    <main className="flex flex-1 flex-col items-center gap-5 px-4 pb-6 text-center">
      <div className="animate-pop mt-6 w-full rounded-3xl bg-marigold p-6 text-ink shadow-[0_6px_0_#c48900]">
        <p className="font-display text-7xl font-extrabold tabular">{rupees(tx.amount)}</p>
        <p className="mt-1 text-lg font-semibold">{t(lang, "received")}</p>
        <div className="mx-auto mt-4 flex w-fit items-center gap-3 rounded-2xl bg-white/60 px-4 py-2">
          <MaterialIcon code={tx.material} className="h-9 w-9" />
          <p className="text-xl font-semibold tabular">
            {kg(tx.scale_kg)} {matLabel(tx.material)}
          </p>
        </div>
        <p className="mt-3 font-semibold">+{tx.credits} {t(lang, "credits")}</p>
      </div>
      {message && (
        <button onClick={() => speakMessage(message)} className="flex items-center gap-2 rounded-full bg-ink px-5 py-3 font-semibold text-kraft">
          <SpeakerIcon className="h-5 w-5" /> {lang === "hi" ? "फिर से सुनें" : "Play again"}
        </button>
      )}
      <p className="text-xs text-slate">UPI {tx.upi_ref}</p>
      <button onClick={onDone} className="mt-auto h-14 w-full rounded-2xl bg-leaf text-lg font-semibold text-white">
        {t(lang, "done")}
      </button>
    </main>
  );
}
