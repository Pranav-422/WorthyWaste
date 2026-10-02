import type { Metadata } from "next";

export const metadata: Metadata = { title: "WorthyWaste · Demo stage" };

// Design Doc → Demo click path: two phones and a laptop side by side, recorded in one take.
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

export default function Demo() {
  return (
    <main className="flex min-h-dvh items-start gap-6 overflow-x-auto bg-[#14201a] p-6">
      <Phone src="/collector?id=1" label="Collector · Meena" />
      <Phone src="/dealer?id=1" label="Dealer · Raju Kabadi Store" />
      <figure className="flex min-w-[900px] flex-1 flex-col items-center gap-2">
        <div className="h-[760px] w-full overflow-hidden rounded-xl border-[10px] border-ink bg-ink shadow-2xl">
          <iframe src="/satin" title="Satin dashboard" className="h-full w-full bg-paper" />
        </div>
        <figcaption className="text-sm font-semibold text-kraft">Satin · branch dashboard</figcaption>
      </figure>
    </main>
  );
}
