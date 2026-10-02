"use client";

import clips from "./audio-clips.json";
import { composeSaleConfirmation, segUrl, type SaleMeta } from "./voiceCompose";

// Voice on every screen. Many phones and laptops ship without a Hindi speech voice, so:
//   1. fixed prompts play a whole pre-recorded clip (scripts/make_audio.py),
//   2. sale confirmations of any amount are joined from recorded number/word segments,
//   3. anything else falls back to the browser's speech engine.
// The pilot plays recorded prompts through the IVR / WhatsApp provider instead.

type Lang = "hi" | "en";

let current: HTMLAudioElement | null = null;
let ctx: AudioContext | null = null;
let playing: AudioBufferSourceNode[] = [];
let generation = 0;
const decoded = new Map<string, Promise<AudioBuffer>>();

function stopAll() {
  current?.pause();
  current = null;
  playing.forEach((s) => s.stop());
  playing = [];
  generation++;
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
}

export function speak(text: string, lang: Lang = "hi") {
  if (typeof window === "undefined") return;
  stopAll();
  const clip = (clips as Record<string, string>)[text];
  if (clip) {
    current = new Audio(clip);
    current.play().catch(() => synth(text, lang));
    return;
  }
  synth(text, lang);
}

/** Speak a stored message, voicing sale confirmations from segments when there's no whole clip. */
export function speakMessage(msg: { text: string; language: string; meta?: unknown }) {
  const lang: Lang = msg.language === "en" ? "en" : "hi";
  const meta = msg.meta as SaleMeta | null | undefined;
  if (!(clips as Record<string, string>)[msg.text] && meta?.kind === "sale_confirmation") {
    const keys = composeSaleConfirmation(lang, meta);
    if (keys) {
      stopAll();
      playSegments(keys.map((k) => segUrl(lang, k))).catch(() => synth(msg.text, lang));
      return;
    }
  }
  speak(msg.text, lang);
}

async function playSegments(urls: string[]) {
  const gen = generation;
  ctx ??= new AudioContext();
  if (ctx.state === "suspended") await ctx.resume();
  const ac = ctx;
  const buffers = await Promise.all(urls.map((u) => load(ac, u)));
  if (gen !== generation) return; // something else started speaking meanwhile
  let t = ac.currentTime + 0.05;
  for (const b of buffers) {
    const [start, end] = voicedRange(b);
    const src = ac.createBufferSource();
    src.buffer = b;
    src.connect(ac.destination);
    src.start(t, start, end - start);
    playing.push(src);
    t += end - start + 0.06;
  }
}

function load(ac: AudioContext, url: string) {
  let p = decoded.get(url);
  if (!p) {
    p = fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`audio ${r.status}`);
        return r.arrayBuffer();
      })
      .then((buf) => ac.decodeAudioData(buf));
    p.catch(() => decoded.delete(url));
    decoded.set(url, p);
  }
  return p;
}

/** Trim the leading/trailing silence TTS puts around each segment, keeping a little padding. */
function voicedRange(b: AudioBuffer): [number, number] {
  const data = b.getChannelData(0);
  const threshold = 0.02;
  let first = 0;
  while (first < data.length && Math.abs(data[first]) < threshold) first++;
  let last = data.length - 1;
  while (last > first && Math.abs(data[last]) < threshold) last--;
  if (last <= first) return [0, b.duration];
  const pad = 0.03 * b.sampleRate;
  const start = Math.max(0, first - pad) / b.sampleRate;
  const end = Math.min(data.length, last + pad) / b.sampleRate;
  return [start, end];
}

function synth(text: string, lang: Lang) {
  if (!("speechSynthesis" in window)) return;
  const s = window.speechSynthesis;
  const u = new SpeechSynthesisUtterance(text);
  const tag = lang === "hi" ? "hi-IN" : "en-IN";
  u.lang = tag;
  const voice = s.getVoices().find((v) => v.lang === tag) ?? s.getVoices().find((v) => v.lang.startsWith(lang));
  if (voice) u.voice = voice;
  u.rate = 0.95;
  s.speak(u);
}
