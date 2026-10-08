import Link from "next/link";
import { CheckIcon, Logo, MaterialIcon, QrIcon, ScaleIcon } from "@/components/icons";

const STATS = [
  { value: "1.5–4 M", label: "informal waste pickers in India", src: "Down To Earth" },
  { value: "60–70%", label: "of urban recyclables pass through their hands", src: "Down To Earth" },
  { value: "0", label: "credit records for almost all of them", src: "No income proof, no credit history" },
];

const STEPS = [
  { icon: "camera", title: "Collector raises a sale", text: "Picks the material, slides to the weight, takes a live photo. Works on a basic phone through IVR too." },
  { icon: "qr", title: "Dealer scans the QR card", text: "Both phones must be within 50 m. The request expires in 15 minutes." },
  { icon: "scale", title: "The scale sets the weight", text: "Manual entry is off. A gap over 10% from the estimate is flagged." },
  { icon: "rupee", title: "UPI pays, the record counts", text: "No payment, no record. The collector hears ₹ and kg in their language." },
];

const WHO = [
  { who: "Collector", hi: "कबाड़ बेचने वाले", gets: ["Digital income proof", "A credit score from 300 to 900", "A group-backed first loan for a cart or baler"] },
  { who: "Dealer", hi: "कबाड़ी", gets: ["Free digital billing and daily log", "More collectors who trust the scale", "Working-capital loans (pilot)"] },
  { who: "Satin", hi: "Lender", gets: ["A new, verified borrower segment", "Explainable scores with their five inputs", "Fraud flags with the evidence"] },
  { who: "Recycler / brand", hi: "EPR", gets: ["Batch IDs traced from collector to recycler", "Mass balance across every dealer", "Pseudonymised data only"] },
];

const CHECKS = [
  "Duplicate-photo detection",
  "Live camera only",
  "GPS match within 50 m",
  "Requests expire in 15 min",
  "Scale weight, never typed",
  "Circular UPI payments",
  "Volume beyond a cart's capacity",
  "Mass balance per dealer",
];

const SCORE = [
  { k: "Activity", w: 30, d: "selling days in the last 30" },
  { k: "Consistency", w: 25, d: "steadiness of monthly income" },
  { k: "Repayment", w: 20, d: "instalments paid on time" },
  { k: "Tenure", w: 15, d: "months on the platform" },
  { k: "Dealer spread", w: 10, d: "distinct verified dealers" },
];

function StepIcon({ kind }: { kind: string }) {
  const cls = "h-7 w-7";
  if (kind === "qr") return <QrIcon className={cls} />;
  if (kind === "scale") return <ScaleIcon className={cls} />;
  if (kind === "camera") return <MaterialIcon code="plastic" className={cls} />;
  return <span className="font-display text-2xl font-bold leading-none">₹</span>;
}

export default function Home() {
  return (
    <div className="bg-paper text-ink">
      <header className="sticky top-0 z-10 border-b border-line/70 bg-paper/90 backdrop-blur">
        <nav className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <Link href="/" className="flex items-center gap-2">
            <Logo className="h-8 w-8" />
            <span className="font-display text-xl font-bold">WorthyWaste</span>
          </Link>
          <div className="ml-auto hidden items-center gap-5 text-sm text-slate md:flex">
            <a href="#how" className="hover:text-ink">How it works</a>
            <a href="#who" className="hover:text-ink">Who it serves</a>
            <a href="#trust" className="hover:text-ink">Fraud checks</a>
            <a href="#homes" className="hover:text-ink">Households</a>
            <Link href="/satin" className="hover:text-ink">Satin dashboard</Link>
          </div>
          <Link href="/login" className="ml-auto rounded-full bg-ink px-4 py-2 text-sm font-semibold text-white md:ml-2">
            Log in
          </Link>
        </nav>
      </header>

      {/* Hero */}
      <section className="kraft">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 md:grid-cols-[1.2fr_1fr] md:py-20">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full bg-paper px-3 py-1 text-xs font-semibold text-leaf-dark">
              <span className="h-2 w-2 rounded-full bg-leaf" /> SANKALP Round 1 · lending partner Satin
            </p>
            <h1 className="mt-4 text-5xl font-bold leading-[1.05] md:text-6xl">
              Your scrap is your <span className="text-leaf">credit score.</span>
            </h1>
            <p className="mt-3 font-display text-2xl text-slate">आपका कबाड़, आपकी साख।</p>
            <p className="mt-5 max-w-xl text-lg text-slate">
              Every scrap sale that is weighed on a scale, matched by GPS and paid by UPI becomes income proof for a waste
              picker, a borrower Satin can underwrite, and recycling a brand can trace.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link href="/login?role=collector" className="flex h-14 items-center rounded-2xl bg-leaf px-6 text-lg font-semibold text-white shadow-[0_4px_0_#155c39]">
                Collector login
              </Link>
              <Link href="/login?role=dealer" className="flex h-14 items-center rounded-2xl border-2 border-ink px-6 text-lg font-semibold">
                Dealer login
              </Link>
              <Link href="/demo" className="flex h-14 items-center px-2 text-lg font-semibold text-leaf-dark underline underline-offset-4">
                Watch the live demo →
              </Link>
            </div>
          </div>

          {/* Phone mock: the moment a sale lands */}
          <div className="mx-auto w-full max-w-[300px]" aria-hidden>
            <div className="rounded-[40px] border-[10px] border-ink bg-kraft p-4 shadow-2xl">
              <div className="flex items-center gap-2">
                <Logo className="h-7 w-7" />
                <div>
                  <p className="text-[10px] text-slate">नमस्ते</p>
                  <p className="font-display text-sm font-semibold">Meena Devi</p>
                </div>
              </div>
              <div className="mt-4 rounded-3xl bg-marigold p-5 text-center shadow-[0_5px_0_#c48900]">
                <p className="font-display text-5xl font-extrabold">₹340</p>
                <p className="font-semibold">मिले</p>
                <p className="mx-auto mt-3 w-fit rounded-xl bg-white/60 px-3 py-1 text-sm font-semibold">27.4 kg प्लास्टिक बोतल</p>
                <p className="mt-2 text-sm font-semibold">+27 क्रेडिट</p>
              </div>
              <div className="mt-4 rounded-2xl bg-paper p-3">
                <div className="flex items-baseline justify-between">
                  <p className="text-xs text-slate">Score</p>
                  <p className="font-display text-2xl font-bold">642</p>
                </div>
                <div className="mt-1 h-2 rounded-full bg-kraft-deep">
                  <div className="h-2 w-[57%] rounded-full bg-leaf" />
                </div>
                <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-leaf-dark">
                  <CheckIcon className="h-4 w-4" /> Starter loan unlocked · ₹5,000
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Problem */}
      <section className="mx-auto max-w-6xl px-4 py-14">
        <h2 className="max-w-2xl text-3xl font-bold">They earn every day. Nothing records it.</h2>
        <p className="mt-2 max-w-2xl text-slate">
          Paid in cash, waste pickers have no income proof, so moneylenders are the only option. Brands can&apos;t prove
          what was recovered, and lenders can&apos;t see a large, steady-income segment.
        </p>
        <div className="mt-8 grid gap-4 sm:grid-cols-3">
          {STATS.map((s) => (
            <div key={s.label} className="rounded-3xl border border-line bg-white p-6">
              <p className="font-display text-4xl font-bold tabular">{s.value}</p>
              <p className="mt-1">{s.label}</p>
              <p className="mt-3 text-xs text-slate">{s.src}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="border-y border-line bg-white">
        <div className="mx-auto max-w-6xl px-4 py-14">
          <h2 className="text-3xl font-bold">One sale, verified three ways</h2>
          <p className="mt-2 max-w-2xl text-slate">The collector requests, the dealer approves, and the scale, GPS and UPI payment prove it happened.</p>
          <ol className="mt-8 grid gap-4 md:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="relative rounded-3xl border border-line bg-paper p-6">
                <span className="absolute right-5 top-5 font-display text-4xl font-bold text-kraft-deep">{i + 1}</span>
                <span className="grid h-12 w-12 place-items-center rounded-2xl bg-leaf text-white">
                  <StepIcon kind={s.icon} />
                </span>
                <h3 className="mt-4 text-lg font-semibold">{s.title}</h3>
                <p className="mt-1 text-sm text-slate">{s.text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Who it serves */}
      <section id="who" className="mx-auto max-w-6xl px-4 py-14">
        <h2 className="text-3xl font-bold">Value for everyone in the chain</h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {WHO.map((w) => (
            <div key={w.who} className="rounded-3xl border border-line bg-white p-6">
              <p className="font-display text-xl font-semibold">{w.who}</p>
              <p className="text-sm text-slate">{w.hi}</p>
              <ul className="mt-4 space-y-2 text-sm">
                {w.gets.map((g) => (
                  <li key={g} className="flex gap-2">
                    <CheckIcon className="mt-0.5 h-4 w-4 shrink-0 text-leaf" /> {g}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      {/* Phase 2: from the household */}
      <section id="homes" className="border-y border-line bg-white">
        <div className="mx-auto max-w-6xl px-4 py-14">
          <p className="text-sm font-semibold uppercase tracking-wide text-leaf">New · door-to-door collection</p>
          <h2 className="mt-1 max-w-2xl text-3xl font-bold">From the household, too</h2>
          <p className="mt-2 max-w-2xl text-slate">
            The collector scans the QR on the door and marks the waste separated or mixed. The household&apos;s Green Wallet pays
            the fee by UPI AutoPay, separating earns points that cut the bill, and every pickup becomes the collector&apos;s
            verified income.
          </p>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {[
              ["Households", "घर / सोसाइटी", ["Green Wallet: AutoPay from your own bank, with a WhatsApp before every debit", "Points for separated waste, redeemed against the fee", "“No pickup today?” — one tap and nothing is charged"]],
              ["Door-to-door collectors", "घर-घर कलेक्टर", ["Paid for every verified pickup", "Pickups build the same credit score as scrap sales", "Accident and hospital cover"]],
              ["Societies, hotels, wards", "बल्क जनरेटर / वार्ड", ["Day-by-day compliance report for bulk generators", "Coverage and segregation by ward", "Missed homes flagged after two days"]],
            ].map(([who, hi, gets]) => (
              <div key={who as string} className="rounded-3xl border border-line bg-paper p-6">
                <p className="font-display text-xl font-semibold">{who}</p>
                <p className="text-sm text-slate">{hi}</p>
                <ul className="mt-4 space-y-2 text-sm">
                  {(gets as string[]).map((g) => (
                    <li key={g} className="flex gap-2">
                      <CheckIcon className="mt-0.5 h-4 w-4 shrink-0 text-leaf" /> {g}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/login?role=household" className="flex h-12 items-center rounded-2xl bg-leaf px-5 font-semibold text-white">Household login</Link>
            <Link href="/demo/doorstep" className="flex h-12 items-center px-2 font-semibold text-leaf-dark underline underline-offset-4">Watch the doorstep demo</Link>
          </div>
        </div>
      </section>

      {/* Trust: fraud + score */}
      <section id="trust" className="bg-ink text-kraft">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 md:grid-cols-2">
          <div>
            <h2 className="text-3xl font-bold text-white">Built so fraud doesn&apos;t pay</h2>
            <p className="mt-2 text-kraft/80">Every rule runs at the step it guards, and every flag reaches Satin with its evidence.</p>
            <ul className="mt-6 grid gap-2 sm:grid-cols-2">
              {CHECKS.map((c) => (
                <li key={c} className="flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm">
                  <CheckIcon className="h-4 w-4 shrink-0 text-marigold" /> {c}
                </li>
              ))}
            </ul>
            <p className="mt-4 text-sm text-kraft/70">Starter loans are small and grow only with on-time repayment.</p>
          </div>
          <div>
            <h2 className="text-3xl font-bold text-white">A score you can explain</h2>
            <p className="mt-2 text-kraft/80">300 to 900, rule-based in v1. It rewards consistency over volume, so it&apos;s hard to game.</p>
            <ul className="mt-6 space-y-3">
              {SCORE.map((s) => (
                <li key={s.k}>
                  <div className="flex justify-between text-sm">
                    <span className="font-semibold text-white">{s.k} <span className="font-normal text-kraft/70">· {s.d}</span></span>
                    <span className="tabular">{s.w}%</span>
                  </div>
                  <div className="mt-1 h-2 rounded-full bg-white/10">
                    <div className="h-2 rounded-full bg-leaf" style={{ width: `${(s.w / 30) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="kraft">
        <div className="mx-auto flex max-w-6xl flex-col items-start gap-5 px-4 py-14 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-3xl font-bold">Ready to sell, buy or lend?</h2>
            <p className="mt-1 text-slate">Log in with your phone number and PIN.</p>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link href="/login?role=collector" className="flex h-12 items-center rounded-2xl bg-leaf px-5 font-semibold text-white">Collector login</Link>
            <Link href="/login?role=dealer" className="flex h-12 items-center rounded-2xl border-2 border-ink px-5 font-semibold">Dealer login</Link>
            <Link href="/login?role=household" className="flex h-12 items-center rounded-2xl border-2 border-ink px-5 font-semibold">Household login</Link>
            <Link href="/satin" className="flex h-12 items-center px-2 font-semibold underline underline-offset-4">Satin dashboard</Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-6 text-sm text-slate">
          <Logo className="h-6 w-6" />
          <span>WorthyWaste · SANKALP Round 1 demo. Payments, scale and IVR are simulated; all data is sample data.</span>
        </div>
      </footer>
    </div>
  );
}
