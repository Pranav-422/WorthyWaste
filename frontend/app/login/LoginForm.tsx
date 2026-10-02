"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, post } from "@/lib/api";
import { Logo, StopIcon } from "@/components/icons";

type Role = "collector" | "dealer";

// Seeded sample accounts (backend/app/seed.py, PIN 1234).
const DEMO: Record<Role, { name: string; phone: string; note: string }[]> = {
  collector: [
    { name: "Meena Devi", phone: "9810000001", note: "Demo hero · score 642 after a sale" },
    { name: "Sunita Kumari", phone: "9810000002", note: "New · loan unlocks in 11 sales" },
    { name: "Lakshmi Bai", phone: "9810000003", note: "Repaid first loan" },
  ],
  dealer: [
    { name: "Raju Kabadi Store", phone: "9811000001", note: "Demo dealer · balanced books" },
    { name: "Gupta Scrap Traders", phone: "9811000002", note: "Has a mass-balance flag" },
  ],
};

const COPY = {
  collector: { tab: "Collector", tabHi: "कबाड़ बेचने वाले", title: "नमस्ते! लॉग इन करें", sub: "Log in to sell scrap and see your score" },
  dealer: { tab: "Dealer", tabHi: "कबाड़ी दुकान", title: "Dealer login", sub: "Scan, weigh and pay collectors by UPI" },
};

export function LoginForm({ initialRole }: { initialRole: Role }) {
  const router = useRouter();
  const [role, setRole] = useState<Role>(initialRole);
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e?: React.FormEvent, p = phone, k = pin) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/login", { role, phone: p, pin: k });
      router.replace(`/${role}`);
      router.refresh();
    } catch (err) {
      setError((err as ApiError).message);
      setBusy(false);
    }
  }

  const switchRole = (r: Role) => {
    setRole(r);
    setPhone("");
    setPin("");
    setError(null);
    router.replace(`/login?role=${r}`, { scroll: false });
  };

  const c = COPY[role];

  return (
    <main className="kraft flex min-h-dvh flex-col items-center px-4 py-8">
      <Link href="/" className="flex items-center gap-2">
        <Logo className="h-10 w-10" />
        <span className="font-display text-2xl font-bold">WorthyWaste</span>
      </Link>

      <div className="mt-6 w-full max-w-md rounded-3xl border border-line bg-paper p-5 shadow-sm sm:p-7">
        <div role="tablist" aria-label="Who are you?" className="grid grid-cols-2 gap-1 rounded-2xl bg-kraft-deep/60 p-1">
          {(["collector", "dealer"] as const).map((r) => (
            <button
              key={r}
              role="tab"
              aria-selected={role === r}
              onClick={() => switchRole(r)}
              className={`rounded-xl px-3 py-2.5 text-center leading-tight ${role === r ? "bg-white shadow-sm" : "text-slate"}`}
            >
              <span className="block font-semibold">{COPY[r].tab}</span>
              <span className="block text-xs">{COPY[r].tabHi}</span>
            </button>
          ))}
        </div>

        <h1 className="mt-6 text-2xl font-semibold">{c.title}</h1>
        <p className="text-sm text-slate">{c.sub}</p>

        <form onSubmit={submit} className="mt-5 space-y-4">
          <label className="block">
            <span className="text-sm font-semibold">
              Phone number <span className="font-normal text-slate">· फ़ोन नंबर</span>
            </span>
            <div className="mt-1 flex h-14 items-center rounded-2xl border-2 border-line bg-white focus-within:border-leaf">
              <span className="pl-4 pr-2 text-lg text-slate">+91</span>
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value.replace(/\D/g, "").slice(0, 10))}
                inputMode="numeric"
                autoComplete="tel-national"
                placeholder="98100 00001"
                required
                minLength={10}
                className="h-full min-w-0 flex-1 rounded-r-2xl bg-transparent pr-4 text-lg tracking-wide outline-none tabular"
                aria-label="Phone number"
              />
            </div>
          </label>

          <label className="block">
            <span className="text-sm font-semibold">
              4-digit PIN <span className="font-normal text-slate">· पिन</span>
            </span>
            <input
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 4))}
              inputMode="numeric"
              type="password"
              autoComplete="current-password"
              placeholder="••••"
              required
              minLength={4}
              className="mt-1 h-14 w-full rounded-2xl border-2 border-line bg-white px-4 text-center text-2xl tracking-[0.6em] outline-none focus:border-leaf"
              aria-label="PIN"
            />
          </label>

          {error && (
            <p role="alert" className="flex items-center gap-2 rounded-xl bg-brick-soft p-3 text-sm font-semibold text-brick">
              <StopIcon className="h-5 w-5 shrink-0" /> {error}
            </p>
          )}

          <button
            disabled={busy || phone.length !== 10 || pin.length !== 4}
            className="h-14 w-full rounded-2xl bg-leaf text-lg font-semibold text-white shadow-[0_4px_0_#155c39] disabled:opacity-40"
          >
            {busy ? "…" : role === "collector" ? "लॉग इन · Log in" : "Log in"}
          </button>
        </form>
      </div>

      <section className="mt-5 w-full max-w-md rounded-3xl border border-dashed border-line bg-paper/70 p-5">
        <p className="text-sm font-semibold">Sample accounts · PIN 1234</p>
        <p className="text-xs text-slate">Demo data only. Tap one to log in.</p>
        <ul className="mt-3 space-y-2">
          {DEMO[role].map((a) => (
            <li key={a.phone}>
              <button
                disabled={busy}
                onClick={() => {
                  setPhone(a.phone);
                  setPin("1234");
                  submit(undefined, a.phone, "1234");
                }}
                className="flex w-full items-center justify-between gap-3 rounded-2xl border border-line bg-white px-4 py-3 text-left hover:border-leaf"
              >
                <span>
                  <span className="block font-semibold">{a.name}</span>
                  <span className="block text-xs text-slate">{a.note}</span>
                </span>
                <span className="font-mono text-sm text-slate">{a.phone}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <p className="mt-6 text-xs text-slate">
        Satin branch view needs no login in this demo: <Link href="/satin" className="underline">open dashboard</Link>
      </p>
    </main>
  );
}
