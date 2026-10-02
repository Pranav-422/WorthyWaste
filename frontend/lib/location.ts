"use client";

export type Coords = { lat: number; lng: number; accuracy: number | null; source: "gps" | "demo" };

// Raju Kabadi Store — where the scripted demo takes place.
export const DEMO_SPOT = { lat: 28.67312, lng: 77.28654 };

/**
 * Real GPS when available. In demo mode (or if GPS is denied) we report the demo spot so two
 * devices on one desk always "match"; the far-away option lets the demo show the location block.
 */
export function getLocation(mode: "gps" | "demo" | "far"): Promise<Coords> {
  if (mode === "demo") return Promise.resolve({ ...DEMO_SPOT, accuracy: null, source: "demo" });
  if (mode === "far") return Promise.resolve({ lat: DEMO_SPOT.lat + 0.009, lng: DEMO_SPOT.lng, accuracy: null, source: "demo" });
  return new Promise((resolve) => {
    if (!("geolocation" in navigator)) return resolve({ ...DEMO_SPOT, accuracy: null, source: "demo" });
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy, source: "gps" }),
      () => resolve({ ...DEMO_SPOT, accuracy: null, source: "demo" }),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 10000 },
    );
  });
}
