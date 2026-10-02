import Link from "next/link";
import { Logo } from "@/components/icons";

const apps = [
  { href: "/collector?id=1", title: "Collector", who: "Meena Devi", what: "QR card, new sale, credits, score" },
  { href: "/dealer?id=1", title: "Dealer", who: "Raju Kabadi Store", what: "Scan, weigh, approve and pay" },
  { href: "/satin", title: "Satin", who: "Branch manager", what: "Scores, eligibility, fraud flags" },
];

export default function Home() {
  return (
    <main className="kraft flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-3xl">
        <div className="flex items-center gap-3">
          <Logo className="h-12 w-12" />
          <div>
            <h1 className="text-4xl font-bold">WorthyWaste</h1>
            <p className="text-slate">Your scrap is your credit score.</p>
          </div>
        </div>
        <div className="mt-8 grid gap-3 sm:grid-cols-3">
          {apps.map((a) => (
            <Link key={a.href} href={a.href} className="rounded-2xl border border-line bg-paper p-5 shadow-sm hover:border-leaf">
              <p className="font-display text-2xl font-semibold">{a.title}</p>
              <p className="text-sm font-medium text-leaf">{a.who}</p>
              <p className="mt-2 text-sm text-slate">{a.what}</p>
            </Link>
          ))}
        </div>
        <Link href="/demo" className="mt-4 flex h-14 items-center justify-center rounded-2xl bg-leaf text-lg font-semibold text-white">
          Open the demo stage (two phones and a laptop)
        </Link>
      </div>
    </main>
  );
}
