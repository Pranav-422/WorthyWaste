"use client";

export type Coords = { lat: number; lng: number; accuracy: number | null; source: "gps" | "demo" };

// Raju Kabadi Store — where the scripted demo takes place.
export const DEMO_SPOT = { lat: 28.67312, lng: 77.28654 };

export type LocationFailure = "denied" | "unavailable" | "timeout";

/** Thrown instead of quietly pretending to know where the phone is. */
export class LocationError extends Error {
  constructor(public reason: LocationFailure) {
    super(reason);
    this.name = "LocationError";
  }
}

/**
 * Real GPS, or a fixed point in demo mode.
 *
 * Outside demo mode this rejects rather than falling back to the demo spot. The location decides
 * whether a collector and a dealer are judged to be standing together, so a guess here would either
 * wave a fraud check through or block an honest sale with no explanation. The caller shows the
 * person what went wrong instead.
 */
export function getLocation(mode: "gps" | "demo" | "far"): Promise<Coords> {
  if (mode === "demo") return Promise.resolve({ ...DEMO_SPOT, accuracy: null, source: "demo" });
  if (mode === "far") return Promise.resolve({ lat: DEMO_SPOT.lat + 0.009, lng: DEMO_SPOT.lng, accuracy: null, source: "demo" });
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) return reject(new LocationError("unavailable"));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy, source: "gps" }),
      (e) => reject(new LocationError(e.code === e.PERMISSION_DENIED ? "denied" : e.code === e.TIMEOUT ? "timeout" : "unavailable")),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 10000 },
    );
  });
}
