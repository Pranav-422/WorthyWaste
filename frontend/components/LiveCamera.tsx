"use client";

import { useEffect, useRef, useState } from "react";
import { CameraIcon } from "./icons";

/**
 * Live camera only — no gallery picker (PRD R1). Captures a frame to JPEG, downscaled so uploads
 * stay small on 2G/3G. If the browser has no camera access we say so instead of opening a gallery.
 */
export function LiveCamera({ onCapture, label }: { onCapture: (blob: Blob, preview: string) => void; label: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [state, setState] = useState<"starting" | "live" | "unavailable">("starting");

  useEffect(() => {
    let cancelled = false;
    (navigator.mediaDevices?.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false }) ??
      Promise.reject(new Error("no camera")))
      .then((stream) => {
        if (cancelled) return stream.getTracks().forEach((t) => t.stop());
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
        setState("live");
      })
      .catch(() => setState("unavailable"));
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  function capture() {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const scale = Math.min(1, 720 / v.videoWidth);
    const c = document.createElement("canvas");
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext("2d")!.drawImage(v, 0, 0, c.width, c.height);
    const preview = c.toDataURL("image/jpeg", 0.8);
    c.toBlob((b) => b && onCapture(b, preview), "image/jpeg", 0.8);
    streamRef.current?.getTracks().forEach((t) => t.stop());
  }

  return (
    <div className="relative overflow-hidden rounded-2xl bg-ink aspect-[4/3]">
      <video ref={videoRef} playsInline muted className="h-full w-full object-cover" />
      {state === "starting" && <p className="absolute inset-0 grid place-items-center text-kraft/80">Starting camera…</p>}
      {state === "unavailable" && (
        <p className="absolute inset-0 grid place-items-center p-6 text-center text-kraft">
          Camera not available. Allow camera access (needs https or localhost).
        </p>
      )}
      {state === "live" && (
        <button
          onClick={capture}
          aria-label={label}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 grid h-18 w-18 place-items-center rounded-full border-4 border-white bg-leaf text-white shadow-lg active:scale-95"
        >
          <CameraIcon className="h-8 w-8" />
        </button>
      )}
    </div>
  );
}
