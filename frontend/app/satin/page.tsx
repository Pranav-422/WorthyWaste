import type { Metadata } from "next";
import { requireSession } from "@/lib/session";
import { SatinApp } from "./SatinApp";

export const metadata: Metadata = { title: "WorthyWaste · Satin" };

export default async function Page() {
  // The dashboard reads collectors' personal data, reviews fraud flags and disburses money, so the
  // page is gated here and every endpoint behind it is gated again in the API.
  const id = await requireSession("satin");

  // "Reset demo data" needs the X-Demo-Key secret. Handing it to the browser is deliberate and
  // narrow: only a signed-in branch manager ever receives it, and only when the server has reset
  // switched on at all. Nothing else in the app sees it.
  const demoKey = process.env.WW_ALLOW_RESET === "1" ? (process.env.WW_DEMO_KEY ?? null) : null;

  return <SatinApp key={id} demoKey={demoKey} />;
}
