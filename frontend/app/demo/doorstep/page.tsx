import type { Metadata } from "next";

export const metadata: Metadata = { title: "WorthyWaste · Doorstep demo" };

// Phase 2 demo: Sunil (door-to-door collector) at Anita's door, with the team dashboard alongside.
// Log in as Sunil (collector), Anita (household) and the WorthyWaste team in this browser first; each
// role keeps its own cookie, so the three can run side by side. Sunil and Meena share the collector
// cookie, so this stage and the scrap-sale stage (/demo) are recorded separately.
function Phone({ src, label }: { src: string; label: string }) {
  return (
    <figure className="flex flex-col items-center gap-2">
      <div className="h-[760px] w-[360px] overflow-hidden rounded-[44px] border-[10px] border-ink bg-ink shadow-2xl">
        <iframe src={src} title={label} className="h-full w-full rounded-[34px] bg-paper" allow="camera; geolocation; microphone" />
      </div>
      <figcaption className="text-sm font-semibold text-kraft">{label}</figcaption>
    </figure>
  );
}

export default function Doorstep() {
  return (
    <main className="flex min-h-dvh items-start gap-6 overflow-x-auto bg-[#14201a] p-6">
      <Phone src="/collector?demo=1" label="Door-to-door collector · Sunil" />
      <Phone src="/household?demo=1" label="Household · Anita, B-204" />
      <figure className="flex min-w-[900px] flex-1 flex-col items-center gap-2">
        <div className="h-[760px] w-full overflow-hidden rounded-xl border-[10px] border-ink bg-ink shadow-2xl">
          <iframe src="/ops?demo=1" title="WorthyWaste team dashboard" className="h-full w-full bg-paper" />
        </div>
        <figcaption className="text-sm font-semibold text-kraft">WorthyWaste team · revenue and wards</figcaption>
      </figure>
    </main>
  );
}
