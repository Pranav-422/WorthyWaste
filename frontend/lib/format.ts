// "Money feels real": rupees and kilos always together, numerals even in Hindi.

export const rupees = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

export const kg = (n: number) => `${Number.isInteger(n) ? n : n.toFixed(1)} kg`;

/** Backend timestamps are UTC "YYYY-MM-DD HH:MM:SS". */
export const parseTs = (s: string) => new Date(s.replace(" ", "T") + "Z");

export function timeAgo(s: string, now = Date.now()) {
  const sec = Math.max(0, Math.round((now - parseTs(s).getTime()) / 1000));
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h ago`;
  return `${Math.floor(sec / 86400)} d ago`;
}

export function shortDate(s: string) {
  return parseTs(s).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function shortTime(s: string) {
  return parseTs(s).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

export function mmss(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export const tonnes = (kgVal: number) => `${(kgVal / 1000).toFixed(2)} t`;

/** A walking distance a collector can judge: "250 m", "1.4 km". */
export function metres(m: number): string {
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}
