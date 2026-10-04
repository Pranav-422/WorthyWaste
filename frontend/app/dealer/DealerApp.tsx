"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, get, logout, post } from "@/lib/api";
import { kg, rupees, shortTime, timeAgo } from "@/lib/format";
import { getLocation, LocationError } from "@/lib/location";
import type { Batch, Dealer, Material, MassBalance, SaleRequest, Transaction } from "@/lib/types";
import { QrScanner } from "@/components/QrScanner";
import { CheckIcon, Logo, MaterialIcon, QrIcon, ScaleIcon, StopIcon } from "@/components/icons";

type Tab = "queue" | "today" | "sell";
type Step =
  | { kind: "scan"; req: SaleRequest }
  | { kind: "weigh"; req: SaleRequest; distance: number | null }
  | { kind: "pay"; req: SaleRequest; weigh: WeighResult }
  | { kind: "paying"; req: SaleRequest; amount: number }
  | { kind: "paid"; tx: Transaction; name: string }
  | { kind: "ivr" };

type WeighResult = {
  /** The collector's choice, which the dealer confirms or corrects before paying. */
  material: string;
  scale_kg: number;
  scale_source: string;
  rate_per_kg: number;
  amount: number;
  gap_pct: number;
  gap_warning: boolean;
  flags: number[];
};

/** What the backend's pay_amount does, so the button shows what will actually be paid. */
const payAmount = (scaleKg: number, ratePerKg: number) => Math.round(scaleKg * ratePerKg);

// ---------- Photo check badge ----------

/**
 * What the photo check made of the collector's photo, in one line the dealer can read at a glance.
 * "unchecked" shows nothing: the dealer has the scrap in front of them, and a missing AI answer is
 * not information about the load.
 */
function AiBadge({ req, materials, className = "" }: { req: SaleRequest; materials: Material[]; className?: string }) {
  const verdict = req.ai_verdict;
  if (!verdict || verdict === "unchecked") return null;
  const label = materials.find((m) => m.code === req.ai_material)?.label_en.toLowerCase() ?? req.ai_material;
  const pct = req.ai_confidence == null ? null : `${Math.round(req.ai_confidence * 100)}%`;
  const tone =
    verdict === "mismatch"
      ? "bg-brick-soft text-brick"
      : verdict === "uncertain"
        ? "bg-marigold-soft text-ink"
        : "bg-leaf-soft text-leaf-dark";
  const text =
    req.ai_real_scene === 0
      ? "AI: looks like a photo of a screen"
      : verdict === "mismatch"
        ? req.ai_material === "not_scrap"
          ? "AI: does not look like scrap"
          : `AI: looks like ${label}${pct ? ` (${pct})` : ""}`
        : verdict === "uncertain"
          ? `AI: not sure${label && req.ai_material !== "mixed" ? ` — maybe ${label}` : ", looks mixed"}`
          : `AI: matches ${label}${pct ? ` (${pct})` : ""}`;
  return (
    <span className={`inline-block rounded-lg px-2 py-0.5 text-xs font-semibold ${tone} ${className}`}>{text}</span>
  );
}

type DealerProfile = {
  dealer: Dealer;
  today: { material: string; label_en: string; sales: number; kg: number; paid: number }[];
  log: Transaction[];
  open_batches: Batch[];
  recycler_sales: { id: number; recycler_name: string; material: string; kg: number; invoice_ref: string; sold_at: string }[];
  mass_balance: MassBalance;
};

export function DealerApp({ dealerId, demo }: { dealerId: number; demo: boolean }) {
  const [profile, setProfile] = useState<DealerProfile | null>(null);
  const [queue, setQueue] = useState<SaleRequest[]>([]);
  const [tab, setTab] = useState<Tab>("queue");
  const [step, setStep] = useState<Step | null>(null);
  const [locMode, setLocMode] = useState<"demo" | "far" | "gps">(demo ? "demo" : "gps");
  const [materials, setMaterials] = useState<Material[]>([]);

  const loadProfile = useCallback(() => get<DealerProfile>(`/dealers/${dealerId}`).then(setProfile), [dealerId]);

  useEffect(() => {
    get<Material[]>("/materials").then(setMaterials);
  }, []);

  useEffect(() => {
    loadProfile();
    const poll = () => get<SaleRequest[]>(`/dealers/${dealerId}/queue`).then(setQueue).catch(() => {});
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, [dealerId, loadProfile]);

  if (!profile) return <div className="grid min-h-dvh place-items-center text-slate">…</div>;
  const d = profile.dealer;
  const close = () => {
    setStep(null);
    loadProfile();
  };

  return (
    <div className="min-h-dvh bg-paper">
      <div className="mx-auto flex min-h-dvh max-w-md flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-white px-4 py-3">
          <Logo className="h-8 w-8" />
          <div className="min-w-0 flex-1">
            <p className="truncate font-display text-lg font-semibold leading-tight">{d.shop_name}</p>
            <p className="text-xs text-slate">
              Reputation <b className="text-ink">{d.reputation}</b> · {d.scale_id}
            </p>
          </div>
          {demo && (
            <select
              value={locMode}
              onChange={(e) => setLocMode(e.target.value as typeof locMode)}
              className="rounded-lg border border-line bg-paper px-2 py-1 text-xs"
              aria-label="Demo location"
            >
              <option value="demo">📍 At shop</option>
              <option value="far">📍 1 km away</option>
              <option value="gps">📍 Real GPS</option>
            </select>
          )}
          <button onClick={() => logout("dealer")} className="text-xs text-slate underline">
            Log out
          </button>
        </header>

        {step ? (
          <Flow step={step} setStep={setStep} dealer={d} locMode={locMode} demo={demo} materials={materials} onClose={close} />
        ) : (
          <>
            <main className="flex-1 px-4 py-4">
              {tab === "queue" && (
                <Queue
                  queue={queue}
                  materials={materials}
                  onPick={(req) => resume(req, setStep)}
                  onIvr={() => setStep({ kind: "ivr" })}
                />
              )}
              {tab === "today" && <Today profile={profile} />}
              {tab === "sell" && <Sell profile={profile} onDone={loadProfile} />}
            </main>
            <nav className="sticky bottom-0 grid grid-cols-3 border-t border-line bg-white">
              {(
                [
                  ["queue", `Requests${queue.length ? ` (${queue.length})` : ""}`],
                  ["today", "Today"],
                  ["sell", "Sell to recycler"],
                ] as const
              ).map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setTab(k)}
                  className={`h-14 text-sm font-semibold ${tab === k ? "text-leaf" : "text-slate"}`}
                  aria-current={tab === k}
                >
                  {label}
                </button>
              ))}
            </nav>
          </>
        )}
      </div>
    </div>
  );
}

function resume(req: SaleRequest, setStep: (s: Step) => void) {
  if (req.status === "open") setStep({ kind: "scan", req });
  else setStep({ kind: "weigh", req, distance: req.gps_distance_m });
}

// ---------- Queue ----------

function Queue({
  queue,
  materials,
  onPick,
  onIvr,
}: {
  queue: SaleRequest[];
  materials: Material[];
  onPick: (r: SaleRequest) => void;
  onIvr: () => void;
}) {
  return (
    <div className="space-y-3">
      {queue.length === 0 && (
        <div className="rounded-2xl border border-dashed border-line p-8 text-center text-slate">
          No requests yet. A collector picks your shop and their request appears here.
        </div>
      )}
      {queue.map((r) => (
        <button
          key={r.id}
          onClick={() => onPick(r)}
          className="animate-pop flex w-full items-center gap-3 rounded-2xl border border-line bg-white p-3 text-left shadow-sm active:scale-[0.99]"
        >
          {r.photo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={r.photo_url} alt="" className="h-16 w-16 rounded-xl object-cover" />
          ) : (
            <div className="grid h-16 w-16 place-items-center rounded-xl bg-kraft">
              <MaterialIcon code={r.material} className="h-9 w-9 text-leaf" />
            </div>
          )}
          <div className="min-w-0 flex-1">
            <p className="font-semibold">{r.collector_name}</p>
            <p className="text-sm text-slate tabular">
              {r.label_en} · ~{kg(r.est_kg)}
            </p>
            <p className="text-xs text-slate">
              {timeAgo(r.created_at)}
              {r.distance_m != null && ` · ${r.distance_m} m`}
              {r.channel === "ivr" && " · basic phone"}
            </p>
            <AiBadge req={r} materials={materials} className="mt-1" />
          </div>
          <span
            className={`flex items-center gap-1 rounded-xl px-3 py-2 text-sm font-semibold ${
              r.status === "open" ? "bg-leaf text-white" : "bg-marigold-soft text-ink"
            }`}
          >
            {r.status === "open" ? (
              <>
                <QrIcon className="h-4 w-4" /> Scan
              </>
            ) : (
              "Continue"
            )}
          </span>
        </button>
      ))}
      <button onClick={onIvr} className="w-full rounded-2xl border border-line bg-white p-3 text-sm font-semibold text-slate">
        ☎ Collector has a basic phone — start sale for them
      </button>
    </div>
  );
}

// ---------- Sale flow ----------

function Flow({
  step,
  setStep,
  dealer,
  locMode,
  demo,
  materials,
  onClose,
}: {
  step: Step;
  setStep: (s: Step) => void;
  dealer: Dealer;
  locMode: "demo" | "far" | "gps";
  demo: boolean;
  materials: Material[];
  onClose: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(
        e instanceof LocationError
          ? e.reason === "denied"
            ? "This phone's location is turned off. Allow it in settings — the sale needs to show you and the collector are together."
            : "Could not read this phone's location. Step into the open and try again."
          : (e as ApiError).message,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex flex-1 flex-col gap-4 px-4 py-4">
      <button onClick={onClose} className="self-start text-sm text-slate">
        ← Back to requests
      </button>
      {error && (
        <div role="alert" className="animate-pop flex items-start gap-3 rounded-2xl bg-brick p-4 text-white">
          <StopIcon className="h-6 w-6 shrink-0" />
          <p className="font-semibold">{error}</p>
        </div>
      )}
      {step.kind === "scan" && (
        <ScanStep
          req={step.req}
          busy={busy}
          demo={demo}
          materials={materials}
          onToken={(token) =>
            run(async () => {
              const loc = await getLocation(locMode);
              const req = await post<SaleRequest>(`/requests/${step.req.id}/accept`, {
                dealer_id: dealer.id,
                qr_token: token,
                lat: loc.lat,
                lng: loc.lng,
              });
              setStep({ kind: "weigh", req: { ...step.req, ...req }, distance: req.gps_distance_m });
            })
          }
          onSimulate={() =>
            run(async () => {
              // The server holds the collector's QR token — dealers are never told it — so the
              // simulated scan has to be accepted there. 404s unless WW_DEMO_MODE=1.
              const loc = await getLocation(locMode);
              const req = await post<SaleRequest>(`/demo/requests/${step.req.id}/simulate-scan`, {
                lat: loc.lat,
                lng: loc.lng,
              });
              setStep({ kind: "weigh", req: { ...step.req, ...req }, distance: req.gps_distance_m });
            })
          }
        />
      )}
      {step.kind === "weigh" && (
        <WeighStep
          req={step.req}
          distance={step.distance}
          busy={busy}
          demo={demo}
          materials={materials}
          onWeigh={(mode) =>
            run(async () => {
              const w = await post<WeighResult & { request: SaleRequest }>(`/requests/${step.req.id}/weigh`, { dealer_id: dealer.id, mode });
              setStep({ kind: "pay", req: { ...step.req, ...w.request }, weigh: w });
            })
          }
        />
      )}
      {step.kind === "pay" && (
        <PayStep
          req={step.req}
          w={step.weigh}
          busy={busy}
          materials={materials}
          onReweigh={() => setStep({ kind: "weigh", req: step.req, distance: step.req.gps_distance_m })}
          onPay={(confirmed, amount) =>
            run(async () => {
              await post(`/requests/${step.req.id}/approve`, { dealer_id: dealer.id, material: confirmed });
              setStep({ kind: "paying", req: step.req, amount });
            })
          }
        />
      )}
      {step.kind === "paying" && <Paying req={step.req} amount={step.amount} onPaid={(tx) => setStep({ kind: "paid", tx, name: step.req.collector_name ?? "" })} />}
      {step.kind === "paid" && <Paid tx={step.tx} name={step.name} onClose={onClose} />}
      {step.kind === "ivr" && (
        <IvrStep
          dealer={dealer}
          busy={busy}
          demo={demo}
          run={run}
          onAccepted={(req) => setStep({ kind: "weigh", req, distance: 0 })}
        />
      )}
    </main>
  );
}

function ScanStep({
  req,
  busy,
  demo,
  materials,
  onToken,
  onSimulate,
}: {
  req: SaleRequest;
  busy: boolean;
  demo: boolean;
  materials: Material[];
  onToken: (t: string) => void;
  onSimulate: () => void;
}) {
  const [manual, setManual] = useState("");
  const [scanning, setScanning] = useState(true);
  const handled = useRef(false);
  const onResult = useCallback(
    (text: string) => {
      if (handled.current) return;
      handled.current = true;
      setScanning(false);
      onToken(text.trim());
    },
    [onToken],
  );

  return (
    <>
      <div className="flex items-center gap-3">
        <MaterialIcon code={req.material} className="h-10 w-10 text-leaf" />
        <div>
          <p className="font-display text-xl font-semibold">{req.collector_name}</p>
          <p className="text-sm text-slate">
            {req.label_en} · ~{kg(req.est_kg)}
          </p>
          <AiBadge req={req} materials={materials} className="mt-1" />
        </div>
      </div>
      <p className="text-center font-semibold">Scan the collector&apos;s QR card</p>
      {scanning && !busy ? <QrScanner onResult={onResult} /> : <div className="grid aspect-square place-items-center rounded-2xl bg-kraft text-slate">Checking location…</div>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (manual) {
            handled.current = false;
            onResult(manual.toUpperCase());
          }
        }}
        className="flex gap-2"
      >
        <input
          value={manual}
          onChange={(e) => setManual(e.target.value)}
          placeholder="Or type card number, e.g. WWC-…"
          className="h-12 min-w-0 flex-1 rounded-xl border border-line bg-white px-3 font-mono uppercase"
        />
        <button className="h-12 rounded-xl bg-ink px-4 font-semibold text-white">OK</button>
      </form>
      {demo && (
        <button
          onClick={() => {
            handled.current = true;
            setScanning(false);
            onSimulate();
          }}
          className="text-xs text-slate underline"
        >
          Demo: simulate a successful scan
        </button>
      )}
    </>
  );
}

function WeighStep({
  req,
  distance,
  busy,
  demo,
  materials,
  onWeigh,
}: {
  req: SaleRequest;
  distance: number | null;
  busy: boolean;
  demo: boolean;
  materials: Material[];
  onWeigh: (mode: "normal" | "overstated") => void;
}) {
  return (
    <>
      <div className="animate-pop flex items-center gap-2 rounded-2xl bg-leaf p-4 text-white">
        <CheckIcon className="h-7 w-7" />
        <p className="text-lg font-semibold">
          Location matched{distance != null && <span className="font-normal opacity-90"> · {Math.round(distance)} m apart</span>}
        </p>
      </div>
      <div className="rounded-3xl bg-ink p-6 text-center text-white">
        <p className="text-sm uppercase tracking-widest opacity-70">Scale</p>
        <p className="font-display text-7xl font-bold tabular opacity-40">--.-</p>
        <p className="mt-2 text-sm opacity-70">Estimate {kg(req.est_kg)}</p>
      </div>
      {req.photo_url && (
        <div className="flex items-start gap-3 rounded-2xl border border-line bg-white p-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={req.photo_url} alt="The collector's photo of this load" className="h-20 w-20 rounded-xl object-cover" />
          <div className="min-w-0">
            <p className="text-sm">
              Collector chose <b>{req.label_en ?? req.material}</b>
            </p>
            <AiBadge req={req} materials={materials} className="mt-1" />
            {req.ai_notes && <p className="mt-1 text-xs text-slate">{req.ai_notes}</p>}
          </div>
        </div>
      )}
      <button
        onClick={() => onWeigh("normal")}
        disabled={busy}
        className="flex h-16 items-center justify-center gap-2 rounded-2xl bg-leaf text-xl font-semibold text-white disabled:opacity-50"
      >
        <ScaleIcon className="h-6 w-6" /> {busy ? "Reading scale…" : "Weigh"}
      </button>
      <p className="text-center text-xs text-slate">Weight comes from the scale. Manual entry is disabled.</p>
      {demo && (
        <button onClick={() => onWeigh("overstated")} disabled={busy} className="text-xs text-slate underline">
          Demo: weigh a load the collector over-estimated
        </button>
      )}
    </>
  );
}

function useCountUp(target: number, ms = 900) {
  const [v, setV] = useState(0);
  useEffect(() => {
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - p, 3);
      setV(target * eased + (p < 1 ? Math.sin(now / 40) * 0.3 * (1 - p) : 0));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

function PayStep({
  req,
  w,
  busy,
  materials,
  onPay,
  onReweigh,
}: {
  req: SaleRequest;
  w: WeighResult;
  busy: boolean;
  materials: Material[];
  onPay: (material: string, amount: number) => void;
  onReweigh: () => void;
}) {
  const shown = useCountUp(w.scale_kg);
  const settled = Math.abs(shown - w.scale_kg) < 0.05;
  // Pre-selected: the collector's choice. The dealer has the scrap in their hands, so theirs is the
  // answer that sets the rate, the money and the batch — one tap to confirm, one to correct.
  const [confirmed, setConfirmed] = useState(w.material);
  const rate = materials.find((m) => m.code === confirmed)?.rate_per_kg ?? w.rate_per_kg;
  const amount = payAmount(w.scale_kg, rate);
  const changed = confirmed !== w.material;
  return (
    <>
      <div className={`rounded-3xl p-6 text-center text-white ${w.gap_warning ? "bg-brick" : "bg-ink"}`}>
        <p className="text-sm uppercase tracking-widest opacity-70">Scale · {w.scale_source}</p>
        <p className="font-display text-8xl font-bold leading-none tabular">{shown.toFixed(1)}</p>
        <p className="text-2xl font-semibold">kg</p>
        <p className="mt-3 text-sm opacity-80 tabular">
          Estimate {kg(req.est_kg)} · gap {w.gap_pct}%
        </p>
      </div>
      {w.gap_warning ? (
        <div className="flex items-start gap-3 rounded-2xl border-2 border-brick bg-brick-soft p-4 text-brick">
          <StopIcon className="h-6 w-6 shrink-0" />
          <p className="text-sm font-semibold">
            Scale differs from the estimate by more than 10%. The scale weight is used; repeated gaps are flagged for Satin.
          </p>
        </div>
      ) : (
        <p className="flex items-center justify-center gap-2 text-sm font-semibold text-leaf">
          <CheckIcon className="h-5 w-5" /> Within 10% of estimate
        </p>
      )}
      <section>
        <p className="mb-2 text-sm font-semibold">
          Confirm what you are buying
          <span className="font-normal text-slate"> · collector chose {req.label_en ?? w.material}</span>
        </p>
        <div className="grid grid-cols-3 gap-2">
          {materials.map((m) => (
            <button
              key={m.code}
              onClick={() => setConfirmed(m.code)}
              aria-pressed={confirmed === m.code}
              className={`flex min-h-20 flex-col items-center justify-center gap-1 rounded-xl border-2 p-1 text-center text-xs font-semibold ${
                confirmed === m.code ? "border-leaf bg-leaf-soft text-leaf-dark" : "border-line bg-white text-ink"
              }`}
            >
              <MaterialIcon code={m.code} className="h-7 w-7" />
              {m.label_en}
              <span className="font-normal text-slate">₹{m.rate_per_kg}/kg</span>
            </button>
          ))}
        </div>
        {changed && (
          <p className="mt-2 rounded-xl bg-marigold-soft p-2 text-xs font-semibold text-ink">
            You are buying this as {materials.find((m) => m.code === confirmed)?.label_en}, not the{" "}
            {req.label_en ?? w.material} the collector chose. Satin sees the difference.
          </p>
        )}
      </section>
      <p className="text-center text-slate tabular">
        {kg(w.scale_kg)} × ₹{rate}/kg
      </p>
      <button
        onClick={() => onPay(confirmed, amount)}
        disabled={busy || !settled}
        className="h-18 rounded-2xl bg-leaf text-2xl font-bold text-white shadow-[0_4px_0_#155c39] disabled:opacity-50"
      >
        Approve and pay {rupees(amount)}
      </button>
      <button onClick={onReweigh} className="text-sm text-slate underline">
        Weigh again
      </button>
    </>
  );
}

function Paying({ req, amount, onPaid }: { req: SaleRequest; amount: number; onPaid: (tx: Transaction) => void }) {
  const onPaidRef = useRef(onPaid);
  useEffect(() => {
    onPaidRef.current = onPaid;
  }, [onPaid]);
  useEffect(() => {
    let done = false;
    const id = setInterval(async () => {
      const r = await get<{ transaction: Transaction | null }>(`/requests/${req.id}`).catch(() => null);
      if (r?.transaction && !done) {
        done = true;
        onPaidRef.current(r.transaction);
      }
    }, 500);
    return () => clearInterval(id);
  }, [req.id]);
  return (
    <div className="grid flex-1 place-items-center text-center">
      <div>
        <div className="mx-auto h-16 w-16 animate-spin rounded-full border-4 border-leaf-soft border-t-leaf" />
        <p className="mt-4 text-xl font-semibold">Paying {rupees(amount)} by UPI…</p>
        <p className="text-sm text-slate">to {req.collector_name}</p>
      </div>
    </div>
  );
}

function Paid({ tx, name, onClose }: { tx: Transaction; name: string; onClose: () => void }) {
  return (
    <div className="flex flex-1 flex-col items-center gap-4 text-center">
      <div className="animate-pop mt-6 grid h-24 w-24 place-items-center rounded-full bg-leaf text-white">
        <CheckIcon className="h-14 w-14" />
      </div>
      <p className="font-display text-5xl font-bold tabular">{rupees(tx.amount)}</p>
      <p className="text-lg">
        paid to <b>{name}</b> · {kg(tx.scale_kg)}
      </p>
      <dl className="w-full rounded-2xl border border-line bg-white p-4 text-left text-sm">
        <div className="flex justify-between py-1">
          <dt className="text-slate">UPI ref</dt>
          <dd className="font-mono">{tx.upi_ref}</dd>
        </div>
        <div className="flex justify-between py-1">
          <dt className="text-slate">Time</dt>
          <dd>{shortTime(tx.created_at)}</dd>
        </div>
        <div className="flex justify-between py-1">
          <dt className="text-slate">Credits to collector</dt>
          <dd>+{tx.credits}</dd>
        </div>
      </dl>
      <button onClick={onClose} className="mt-auto h-14 w-full rounded-2xl bg-ink font-semibold text-white">
        Next request
      </button>
    </div>
  );
}

function IvrStep({
  dealer,
  busy,
  demo,
  run,
  onAccepted,
}: {
  dealer: Dealer;
  busy: boolean;
  demo: boolean;
  run: (fn: () => Promise<void>) => Promise<void>;
  onAccepted: (req: SaleRequest) => void;
}) {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [token, setToken] = useState("WWC-SUNITA02");
  const [material, setMaterial] = useState("paper");
  const [est, setEst] = useState(12);
  const [call, setCall] = useState<{ request: SaleRequest; ivr_prompt: string; calling: string } | null>(null);

  useEffect(() => {
    get<Material[]>("/materials").then(setMaterials);
  }, []);

  if (call) {
    return (
      <div className="space-y-4">
        <div className="rounded-2xl bg-ink p-5 text-white">
          <p className="text-sm opacity-70">☎ IVR calling {call.calling}</p>
          <p className="mt-2 text-lg">“{call.ivr_prompt}”</p>
        </div>
        <p className="text-center text-sm text-slate">Waiting for the collector to press 1 on their phone…</p>
        {!demo && (
          <p className="text-center text-xs text-slate">
            The IVR provider confirms the keypress itself; this screen updates when it does.
          </p>
        )}
        {demo && (
          <button
            disabled={busy}
            onClick={() =>
              run(async () => {
                // The real /ivr/confirm needs the provider's signature and the collector's caller
                // ID. This stands in for the keypress; it 404s unless WW_DEMO_MODE=1.
                const req = await post<SaleRequest>(`/demo/requests/${call.request.id}/ivr-confirm`);
                onAccepted({ ...call.request, ...req });
              })
            }
            className="h-14 w-full rounded-2xl border-2 border-dashed border-slate font-semibold text-slate"
          >
            Demo: collector presses 1
          </button>
        )}
      </div>
    );
  }

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        run(async () => setCall(await post("/ivr/start", { dealer_id: dealer.id, qr_token: token.toUpperCase(), material, est_kg: est })));
      }}
    >
      <p className="font-display text-xl font-semibold">Sale for a basic-phone collector</p>
      <p className="text-sm text-slate">Scan or type their printed card. They confirm by pressing 1 on an IVR call.</p>
      <input value={token} onChange={(e) => setToken(e.target.value)} className="h-12 w-full rounded-xl border border-line bg-white px-3 font-mono uppercase" aria-label="Card number" />
      <select value={material} onChange={(e) => setMaterial(e.target.value)} className="h-12 w-full rounded-xl border border-line bg-white px-3" aria-label="Material">
        {materials.map((m) => (
          <option key={m.code} value={m.code}>
            {m.label_en}
          </option>
        ))}
      </select>
      <input type="number" min={1} value={est} onChange={(e) => setEst(Number(e.target.value))} className="h-12 w-full rounded-xl border border-line bg-white px-3" aria-label="Estimated kg" />
      <button disabled={busy} className="h-14 w-full rounded-2xl bg-leaf font-semibold text-white">
        Start IVR confirmation
      </button>
    </form>
  );
}

// ---------- Today ----------

function Today({ profile }: { profile: DealerProfile }) {
  const totalKg = profile.today.reduce((s, r) => s + r.kg, 0);
  const totalPaid = profile.today.reduce((s, r) => s + r.paid, 0);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-2xl bg-ink p-4 text-white">
          <p className="text-xs opacity-70">Bought today</p>
          <p className="font-display text-3xl font-bold tabular">{kg(Math.round(totalKg * 10) / 10)}</p>
        </div>
        <div className="rounded-2xl bg-marigold-soft p-4">
          <p className="text-xs text-slate">Paid by UPI</p>
          <p className="font-display text-3xl font-bold tabular">{rupees(totalPaid)}</p>
        </div>
      </div>
      {profile.today.map((r) => (
        <div key={r.material} className="flex items-center gap-3 rounded-xl border border-line bg-white p-3">
          <MaterialIcon code={r.material} className="h-8 w-8 text-leaf" />
          <p className="flex-1 font-medium">{r.label_en}</p>
          <p className="text-right text-sm tabular">
            <b>{kg(Math.round(r.kg * 10) / 10)}</b>
            <br />
            <span className="text-slate">{rupees(r.paid)}</span>
          </p>
        </div>
      ))}
      <p className="pt-2 text-sm font-semibold">Recent purchases</p>
      <ul className="divide-y divide-line rounded-xl border border-line bg-white">
        {profile.log.slice(0, 15).map((t) => (
          <li key={t.id} className="flex items-center justify-between px-3 py-2 text-sm">
            <span>
              {t.collector_name}
              <span className="block text-xs text-slate">
                {t.label_en} · {timeAgo(t.created_at)}
              </span>
            </span>
            <span className="text-right tabular">
              {rupees(t.amount)}
              <span className="block text-xs text-slate">{kg(t.scale_kg)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------- Sell to recycler ----------

function Sell({ profile, onDone }: { profile: DealerProfile; onDone: () => void }) {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [kgSold, setKgSold] = useState("");
  const [recycler, setRecycler] = useState("GreenLoop Recyclers, Bawana");
  const [invoice, setInvoice] = useState("");
  const [result, setResult] = useState<string | null>(null);
  const mb = profile.mass_balance;
  const gapBad = mb.gap_pct != null && mb.gap_pct > 15;

  return (
    <div className="space-y-4">
      <div className={`rounded-2xl p-4 ${gapBad ? "bg-brick-soft text-brick" : "bg-leaf-soft text-leaf-dark"}`}>
        <p className="text-xs font-semibold uppercase tracking-wide">Mass balance · 30 days</p>
        <p className="mt-1 text-sm text-ink tabular">
          Bought <b>{kg(Math.round(mb.bought_kg))}</b> · Sold <b>{kg(Math.round(mb.sold_kg))}</b>
          {mb.gap_pct != null && <> · gap <b>{mb.gap_pct}%</b></>}
        </p>
        {gapBad && <p className="mt-1 text-xs font-semibold">Over 15% — log your recycler sales so purchases reconcile.</p>}
      </div>

      <p className="text-sm font-semibold">Open batches</p>
      {profile.open_batches.length === 0 && <p className="text-sm text-slate">No open batches.</p>}
      {profile.open_batches.map((b) => (
        <button
          key={b.id}
          onClick={() => {
            setBatch(b);
            setKgSold(String(b.total_kg.toFixed(1)));
            setResult(null);
          }}
          className={`flex w-full items-center gap-3 rounded-xl border-2 bg-white p-3 text-left ${batch?.id === b.id ? "border-leaf" : "border-line"}`}
        >
          <MaterialIcon code={b.material} className="h-8 w-8 text-leaf" />
          <span className="flex-1">
            <span className="font-medium">{b.label_en}</span>
            <span className="block font-mono text-xs text-slate">{b.code}</span>
          </span>
          <span className="font-semibold tabular">{kg(Math.round(b.total_kg * 10) / 10)}</span>
        </button>
      ))}

      {batch && (
        <form
          className="space-y-2 rounded-2xl border border-line bg-white p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await post<{ mass_balance: MassBalance; flag_id: number | null }>("/recycler-sales", {
              dealer_id: profile.dealer.id,
              recycler_name: recycler,
              material: batch.material,
              kg: Number(kgSold),
              invoice_ref: invoice || `INV-${Date.now() % 100000}`,
            });
            setResult(
              r.flag_id
                ? `Logged. Mass-balance gap still ${r.mass_balance.gap_pct}% — flagged for review.`
                : `Logged. Batch ${batch.code} is now traceable to the recycler.`,
            );
            setBatch(null);
            onDone();
          }}
        >
          <p className="font-semibold">Sell {batch.label_en}</p>
          <input value={recycler} onChange={(e) => setRecycler(e.target.value)} className="h-11 w-full rounded-lg border border-line px-3" aria-label="Recycler" />
          <input value={kgSold} onChange={(e) => setKgSold(e.target.value)} inputMode="decimal" className="h-11 w-full rounded-lg border border-line px-3" aria-label="Kg sold" />
          <input value={invoice} onChange={(e) => setInvoice(e.target.value)} placeholder="Invoice number" className="h-11 w-full rounded-lg border border-line px-3" />
          <button className="h-12 w-full rounded-xl bg-leaf font-semibold text-white">Log sale</button>
        </form>
      )}
      {result && <p className="rounded-xl bg-leaf-soft p-3 text-sm text-leaf-dark">{result}</p>}

      {profile.recycler_sales.length > 0 && (
        <>
          <p className="text-sm font-semibold">Recent recycler sales</p>
          <ul className="divide-y divide-line rounded-xl border border-line bg-white text-sm">
            {profile.recycler_sales.map((s) => (
              <li key={s.id} className="flex justify-between px-3 py-2">
                <span>
                  {s.recycler_name}
                  <span className="block text-xs text-slate">
                    {s.material} · {s.invoice_ref}
                  </span>
                </span>
                <span className="tabular">{kg(s.kg)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
