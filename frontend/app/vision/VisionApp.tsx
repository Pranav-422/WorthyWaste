"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ACTION_LABEL, AgentTrace } from "@/components/AgentTrace";
import { Logo } from "@/components/icons";
import { LiveCamera } from "@/components/LiveCamera";
import { ApiError, post, postForm } from "@/lib/api";
import type { VisionRun } from "@/lib/types";

const SAMPLES = [
  { src: "/vision-samples/separated.jpg", label: "Two heaps" },
  { src: "/vision-samples/mixed.jpg", label: "One mixed heap" },
  { src: "/vision-samples/blurry.jpg", label: "Blurry photo" },
];

const STAGES: [string, string][] = [
  ["decode", "Decode"],
  ["quality", "Quality gate"],
  ["colour", "White balance + CLAHE"],
  ["faces", "Face blur (YuNet)"],
  ["segment", "GrabCut + watershed"],
  ["superpixels", "SLIC superpixels"],
  ["classify", "MobileNetV2 + classifier"],
  ["annotate", "Annotate"],
];

type Marked = "separated" | "mixed" | "none";

export function VisionApp() {
  const [image, setImage] = useState<{ blob: Blob; preview: string } | null>(null);
  const [camera, setCamera] = useState(false);
  const [marked, setMarked] = useState<Marked>("separated");
  const [attempt, setAttempt] = useState(1);
  const [run, setRun] = useState<VisionRun | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deleted, setDeleted] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  function pick(blob: Blob) {
    if (image) URL.revokeObjectURL(image.preview);
    setImage({ blob, preview: URL.createObjectURL(blob) });
    setCamera(false);
    setError(null);
  }

  async function sample(src: string) {
    pick(await (await fetch(src)).blob());
  }

  async function analyze() {
    if (!image) return;
    setBusy("Analysing on AWS…");
    setError(null);
    setDeleted(false);
    try {
      const f = new FormData();
      f.set("photo", image.blob, "photo.jpg");
      if (marked !== "none") f.set("marked", marked);
      f.set("attempt", String(attempt));
      const r = await postForm<VisionRun>("/vision/analyze", f);
      setRun(r);
      setAttempt(r.action === "recapture" ? attempt + 1 : 1);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function review(approve: boolean) {
    if (!run) return;
    setBusy("Saving your decision…");
    try {
      setRun(await post<VisionRun>(`/vision/runs/${run.run_id}/review`, { approve }));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    if (!run) return;
    setBusy("Deleting…");
    try {
      await fetch(`/api/vision/runs/${run.run_id}`, { method: "DELETE" }).then((r) => {
        if (!r.ok) throw new ApiError(r.status, "Could not delete");
      });
      setRun(null);
      setDeleted(true);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  const res = run?.result;
  const total = res?.timings_ms?.total ?? 0;

  return (
    <div className="min-h-dvh bg-kraft">
      <header className="mx-auto flex max-w-3xl items-center gap-3 px-4 py-4">
        <Link href="/" className="flex items-center gap-2 font-display text-lg font-bold">
          <Logo className="h-8 w-8" /> WorthyWaste
        </Link>
        <span className="ml-auto rounded-full bg-ink px-3 py-1 text-xs font-semibold text-kraft">OpenCV 5 · AWS Lambda</span>
      </header>

      <main className="mx-auto max-w-3xl space-y-4 px-4 pb-12">
        <section>
          <h1 className="font-display text-3xl leading-tight font-bold">Is this waste separated?</h1>
          <p className="mt-1 text-slate">
            A door-to-door collector photographs each home&apos;s waste. The camera checks whether wet and dry are kept apart, and an agent
            decides what happens: accept, ask for a retake, or hand it to a person.
          </p>
        </section>

        <section className="space-y-3 rounded-3xl border border-line bg-paper p-4">
          <h2 className="font-semibold">1 · Photo</h2>
          {camera ? (
            <LiveCamera label="Take photo" onCapture={(blob) => pick(blob)} />
          ) : image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={image.preview} alt="Your photo" className="max-h-80 w-full rounded-2xl bg-kraft object-contain" />
          ) : (
            <div className="flex aspect-[4/3] max-h-64 w-full items-center justify-center rounded-2xl border-2 border-dashed border-line text-slate">
              No photo yet
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => fileRef.current?.click()} className="h-11 rounded-xl bg-ink px-4 font-semibold text-white">
              Upload photo
            </button>
            <button onClick={() => setCamera((c) => !c)} className="h-11 rounded-xl border border-ink px-4 font-semibold">
              {camera ? "Close camera" : "Use camera"}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])}
            />
          </div>
          <div>
            <p className="text-xs text-slate">Or try a sample:</p>
            <div className="mt-1 grid grid-cols-3 gap-2">
              {SAMPLES.map((s) => (
                <button key={s.src} onClick={() => sample(s.src)} className="overflow-hidden rounded-xl border border-line bg-white text-left">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={s.src} alt="" className="aspect-[4/3] w-full object-cover" />
                  <span className="block px-2 py-1 text-xs font-semibold">{s.label}</span>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="space-y-3 rounded-3xl border border-line bg-paper p-4">
          <h2 className="font-semibold">2 · What did the collector mark?</h2>
          <div className="grid grid-cols-3 gap-2" role="radiogroup">
            {(["separated", "mixed", "none"] as Marked[]).map((m) => (
              <button
                key={m}
                role="radio"
                aria-checked={marked === m}
                onClick={() => setMarked(m)}
                className={`h-11 rounded-xl border-2 text-sm font-semibold ${marked === m ? "border-leaf bg-leaf text-white" : "border-line bg-white"}`}
              >
                {m === "none" ? "Nothing" : m[0].toUpperCase() + m.slice(1)}
              </button>
            ))}
          </div>
          <p className="text-xs text-slate">The agent compares this with what the camera sees. Marked separated + camera sure it is mixed → a person decides.</p>
          <button
            onClick={analyze}
            disabled={!image || !!busy}
            className="h-14 w-full rounded-2xl bg-leaf text-lg font-semibold text-white shadow-[0_4px_0_#155c39] disabled:opacity-40"
          >
            {busy ?? (attempt > 1 ? `Check again (photo ${attempt})` : "Check the photo")}
          </button>
          {error && (
            <p role="alert" className="rounded-xl bg-brick-soft px-3 py-2 text-sm font-semibold text-brick">
              {error}
            </p>
          )}
          {deleted && <p className="rounded-xl bg-leaf-soft px-3 py-2 text-sm font-semibold text-leaf-dark">Deleted: the run and both photos are gone from AWS.</p>}
        </section>

        {run && (
          <>
            <section className="space-y-3 rounded-3xl border border-line bg-paper p-4" aria-live="polite">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold">3 · Result</h2>
                <span className={`rounded-full px-3 py-1 text-sm font-semibold ${ACTION_LABEL[run.action].tone}`}>{ACTION_LABEL[run.action].text}</span>
                {run.outcome && <span className="rounded-full bg-ink px-3 py-1 text-sm font-semibold text-white">Decided: {run.outcome}</span>}
              </div>
              <p className="text-lg font-semibold">{run.message}</p>
              {(run.image_urls.annotated || run.image_urls.safe) && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={run.image_urls.annotated ?? run.image_urls.safe} alt="Annotated result: heaps outlined, parts coloured by class" className="w-full rounded-2xl" />
              )}
              {res && (
                <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                  <Stat label="Verdict" value={res.verdict ? res.verdict[0].toUpperCase() + res.verdict.slice(1) : "Not judged"} />
                  <Stat label="Confidence" value={res.status === "ok" && res.confidence !== undefined ? `${Math.round(res.confidence * 100)}%` : "—"} />
                  <Stat label="Sharpness" value={res.quality ? `${res.quality.sharpness}` : "—"} hint="Laplacian variance, min 60" />
                  <Stat label="Brightness" value={res.quality ? `${res.quality.brightness}` : "—"} hint="45–235" />
                  <Stat label="Heaps" value={String(res.heaps?.length ?? 0)} />
                  <Stat label="Faces blurred" value={String(res.faces_blurred ?? 0)} />
                  <Stat label="Pipeline" value={`${Math.round(total)} ms`} />
                  <Stat label="Round trip" value={run.latency_ms ? `${Math.round(run.latency_ms)} ms` : "—"} hint="inside Lambda" />
                </dl>
              )}
              {res?.status !== "ok" && res?.quality?.problems?.length ? (
                <p className="text-sm text-brick">Problems: {res.quality.problems.join(", ").replaceAll("_", " ")}</p>
              ) : null}
              {run.status === "pending_approval" && (
                <div className="rounded-2xl bg-brick-soft p-3">
                  <p className="font-semibold text-brick">You are the reviewer. The collector said separated; the camera is sure it is mixed.</p>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <button onClick={() => review(true)} disabled={!!busy} className="h-12 rounded-xl bg-brick font-semibold text-white">
                      Mixed: no points, flag
                    </button>
                    <button onClick={() => review(false)} disabled={!!busy} className="h-12 rounded-xl border-2 border-ink bg-white font-semibold">
                      Separated: release points
                    </button>
                  </div>
                </div>
              )}
              {run.action === "recapture" && (
                <button onClick={() => (setImage(null), setCamera(true))} className="h-12 w-full rounded-xl bg-marigold font-semibold text-ink">
                  Retake photo
                </button>
              )}
            </section>

            {!!res?.heaps?.length && (
              <section className="rounded-3xl border border-line bg-paper p-4">
                <h2 className="font-semibold">Heaps</h2>
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-xs sm:text-sm">
                    <thead className="text-left text-xs text-slate">
                      <tr>
                        <th className="py-1">#</th>
                        <th>Mostly</th>
                        <th>Other class</th>
                        <th>Sure</th>
                        <th>Parts</th>
                        <th>Verdict</th>
                      </tr>
                    </thead>
                    <tbody>
                      {res.heaps.map((h, i) => (
                        <tr key={i} className="border-t border-line tabular">
                          <td className="py-1.5">{i + 1}</td>
                          <td>{h.label === "organic" ? "Wet" : "Dry"}</td>
                          <td>{Math.round(h.minority * 100)}%</td>
                          <td>{Math.round(h.sure_share * 100)}%</td>
                          <td>{h.parts.length}</td>
                          <td className={h.mixed ? "font-semibold text-brick" : "text-leaf-dark"}>{h.mixed ? "Mixed" : "Pure"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-xs text-slate">A heap is mixed when the other class holds ≥ 12% of the area the classifier is sure about (p ≥ 0.75).</p>
              </section>
            )}

            {total > 0 && (
              <section className="rounded-3xl border border-line bg-paper p-4">
                <h2 className="font-semibold">OpenCV pipeline · {Math.round(total)} ms</h2>
                <ul className="mt-2 space-y-1.5">
                  {STAGES.filter(([k]) => res?.timings_ms[k] !== undefined).map(([k, label]) => (
                    <li key={k} className="grid grid-cols-[9.5rem_1fr_3.5rem] items-center gap-2 text-sm">
                      <span className="truncate">{label}</span>
                      <span className="h-2.5 rounded-full bg-kraft-deep">
                        <span className="block h-full rounded-full bg-leaf" style={{ width: `${Math.max(2, (100 * (res?.timings_ms[k] ?? 0)) / total)}%` }} />
                      </span>
                      <span className="text-right text-xs tabular text-slate">{Math.round(res?.timings_ms[k] ?? 0)} ms</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section className="rounded-3xl border border-line bg-paper p-4">
              <h2 className="mb-3 font-semibold">Agent trace</h2>
              <AgentTrace trace={run.trace} />
            </section>

            <section className="flex flex-wrap items-center gap-3 rounded-3xl border border-line bg-paper p-4 text-sm">
              <p className="flex-1 text-slate">
                Stored on AWS (S3 + DynamoDB) face-blurred, never the original; deleted automatically after 30 days. Run{" "}
                <code className="text-xs">{run.run_id.slice(0, 8)}</code>
              </p>
              <button onClick={remove} disabled={!!busy} className="h-10 rounded-xl border border-brick px-3 font-semibold text-brick">
                Delete my data
              </button>
            </section>
          </>
        )}

        <p className="text-center text-xs text-slate">
          Limits: trained on public single-object photos (organic vs recyclable), not yet on Indian doorstep photos. Use as a check, not a judge.{" "}
          <Link href="/" className="underline">
            About WorthyWaste
          </Link>
        </p>
      </main>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl bg-kraft/60 p-2">
      <dt className="text-[11px] text-slate">{label}</dt>
      <dd className="font-display text-lg font-bold tabular">{value}</dd>
      {hint && <dd className="text-[10px] text-slate">{hint}</dd>}
    </div>
  );
}
