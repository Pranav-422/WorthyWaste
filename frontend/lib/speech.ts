"use client";

import clips from "./audio-clips.json";

// Voice on every screen. Fixed prompts play pre-recorded clips (scripts/make_audio.py) because many
// phones and laptops ship without a Hindi speech voice; anything else uses the browser's engine.
// The pilot plays recorded prompts through the IVR / WhatsApp provider instead.

let current: HTMLAudioElement | null = null;

export function speak(text: string, lang: "hi" | "en" = "hi") {
  if (typeof window === "undefined") return;
  current?.pause();
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();

  const clip = (clips as Record<string, string>)[text];
  if (clip) {
    current = new Audio(clip);
    current.play().catch(() => synth(text, lang));
    return;
  }
  synth(text, lang);
}

function synth(text: string, lang: "hi" | "en") {
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
