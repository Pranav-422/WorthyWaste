import "server-only";

// The demo shortcuts — simulated QR scan, an over-estimated load, the dealer's location menu, the
// collector's fixed location and scripted photo check — exist only when BOTH are true:
//
//   * the server was started with WW_DEMO_MODE=1, and
//   * the URL asks for them with ?demo=1.
//
// The env var is what keeps them out of production: a visitor cannot add it to a URL. The query
// parameter is so the same deployment can be shown either way during a recording.
//
// The API enforces the same switch independently (backend/app/auth.py demo_mode), so a hand-made
// request cannot reach a shortcut the page would not show.

export function demoEnabled(searchParams: { demo?: string | string[] }): boolean {
  return process.env.WW_DEMO_MODE === "1" && searchParams.demo === "1";
}
