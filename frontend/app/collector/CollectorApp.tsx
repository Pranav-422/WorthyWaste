"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, get, logout, postForm } from "@/lib/api";
import { kg, mmss, parseTs, rupees, shortDate } from "@/lib/format";
import { t, voice, type Lang } from "@/lib/i18n";
import { getLocation } from "@/lib/location";
import { speak, speakMessage } from "@/lib/speech";
import type { CollectorProfile, Material, Message, SaleRequest, Transaction } from "@/lib/types";
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
            onSent={(r) => {
              setActive(r);
              setScreen("waiting");
              speak(voice.waiting[lang], lang);
            }}
          />
        )}
        {screen === "waiting" && active && (
          <Waiting
            request={active}
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
  onSent: (r: SaleRequest) => void;
}) {
  const [material, setMaterial] = useState("plastic");
  const [est, setEst] = useState(28);
  const [photo, setPhoto] = useState<{ blob: Blob; preview: string } | null>(null);
  const [camera, setCamera] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<{ msg: string; rule?: string | null } | null>(null);

  async function send(p = photo) {
    if (!p) return;
    setSending(true);
    setError(null);
    const loc = await getLocation(demo ? "demo" : "gps");
    const f = new FormData();
    f.set("collector_id", String(collectorId));
    f.set("material", material);
    f.set("est_kg", String(est));
    f.set("lat", String(loc.lat));
    f.set("lng", String(loc.lng));
    f.set("photo", p.blob, "scrap.jpg");
    try {
      const r = await postForm<SaleRequest>("/requests", f);
      lastPhoto = p;
      onSent(r);
    } catch (e) {
      const err = e as ApiError;
      const msg = err.rule === "duplicate_photo" ? t(lang, "dupPhoto") : err.message;
      setError({ msg, rule: err.rule });
      if (err.rule === "duplicate_photo") speak(t(lang, "dupPhoto") + (lang === "hi" ? "। " : ". ") + t(lang, "dupPhotoHelp"), lang);
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="flex-1 space-y-5 px-4 pb-6">
      {error && (
        <div role="alert" className="animate-pop flex items-start gap-3 rounded-2xl bg-brick p-4 text-white">
          <StopIcon className="h-7 w-7 shrink-0" />
          <div>
            <p className="text-lg font-semibold">{error.msg}</p>
            {error.rule === "duplicate_photo" && <p className="text-sm opacity-90">{t(lang, "dupPhotoHelp")}</p>}
          </div>
        </div>
      )}

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
        {demo && lastPhoto && !photo && (
          <button onClick={() => send(lastPhoto!)} className="mt-2 w-full text-center text-xs text-slate underline">
            Demo: resend the previous photo
          </button>
        )}
      </section>

      <div className="flex gap-3">
        <button onClick={onCancel} className="h-14 flex-1 rounded-2xl border border-line bg-paper font-semibold">
          ✕
        </button>
        <button
          onClick={() => send()}
          disabled={!photo || sending}
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

// ---------- Waiting for the dealer ----------

function Waiting({
  request,
  qr,
  lang,
  onDone,
  onCancel,
}: {
  request: SaleRequest;
  qr: string;
  lang: Lang;
  onDone: (tx: Transaction) => void;
  onCancel: () => void;
}) {
  const [req, setReq] = useState(request);
  const [now, setNow] = useState(() => Date.now());
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

  if (status === "expired" || status === "rejected") {
    return (
      <main className="flex-1 space-y-4 px-4">
        <div className="rounded-2xl bg-brick p-5 text-white">
          <p className="text-lg font-semibold">{t(lang, "expired")}</p>
        </div>
        <button onClick={onCancel} className="h-14 w-full rounded-2xl bg-leaf font-semibold text-white">
          {t(lang, "done")}
        </button>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col items-center gap-4 px-4 pb-6 text-center">
      <h2 className="text-2xl font-semibold">{t(lang, "showQr")}</h2>
      <QrCode value={qr} size={260} className="rounded-2xl bg-white p-3 shadow" />
      {status === "open" ? (
        <p className="text-slate">
          {t(lang, "expiresIn")} <b className="font-display text-2xl text-ink tabular">{mmss(left)}</b>
        </p>
      ) : (
        <p className="flex items-center gap-2 rounded-full bg-leaf-soft px-4 py-2 font-semibold text-leaf-dark">
          <CheckIcon className="h-5 w-5" />
          {status === "accepted" && t(lang, "accepted")}
          {status === "weighed" && `${t(lang, "weighed")} · ${kg(req.scale_kg ?? 0)}`}
          {status === "paying" && t(lang, "paying")}
        </p>
      )}
      <p className="text-sm text-slate tabular">
        {kg(req.est_kg)} · #{req.id}
      </p>
      <button onClick={onCancel} className="mt-auto text-sm text-slate underline">
        ← {lang === "hi" ? "वापस" : "Back"}
      </button>
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
