"use client";

import { useState } from "react";
import { post } from "@/lib/api";
import { rupees, shortDate } from "@/lib/format";
import type { InsuranceStatus } from "@/lib/types";
import { CheckIcon } from "./icons";

/**
 * Accident and hospital cover through a partner insurer, premium auto-debited monthly. Offered in the
 * collector's own app, next to their score: the same verified income that unlocks a loan makes them
 * insurable. (Pilot product; the partner and the premium are assumptions.)
 */
export function InsuranceCard({ status, lang, onChanged }: { status: InsuranceStatus; lang: "hi" | "en"; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const p = status.policy;
  const o = status.offer;
  const hi = lang === "hi";

  if (p) {
    return (
      <div className="flex items-start gap-3 rounded-2xl border border-line bg-paper p-4">
        <CheckIcon className="mt-0.5 h-5 w-5 shrink-0 text-leaf" />
        <div className="text-sm">
          <p className="font-semibold">{hi ? `बीमा चालू · ${rupees(p.cover)} तक` : `Insured · cover up to ${rupees(p.cover)}`}</p>
          <p className="text-slate">
            {hi ? `दुर्घटना और अस्पताल · ${rupees(p.monthly_premium)}/महीना · ${shortDate(p.started_at)} से` : `Accident and hospital · ${rupees(p.monthly_premium)}/month · since ${shortDate(p.started_at)}`}
          </p>
        </div>
      </div>
    );
  }
  return (
    <div className="rounded-2xl border-2 border-dashed border-leaf bg-paper p-4">
      <p className="font-semibold">{hi ? `${rupees(o.cover)} का बीमा, सिर्फ़ ${rupees(o.monthly_premium)}/महीना` : `${rupees(o.cover)} cover for ${rupees(o.monthly_premium)}/month`}</p>
      <p className="text-sm text-slate">{hi ? "दुर्घटना और अस्पताल का खर्च। हर महीने अपने आप कटेगा।" : "Accident and hospital costs. Paid monthly by AutoPay."}</p>
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await post("/collectors/me/insurance").catch(() => {});
          setBusy(false);
          onChanged();
        }}
        className="mt-3 h-12 w-full rounded-xl bg-leaf font-semibold text-white disabled:opacity-50"
      >
        {busy ? "…" : hi ? "बीमा लें" : "Get covered"}
      </button>
      <p className="mt-2 text-center text-[11px] text-slate">{o.partner}</p>
    </div>
  );
}
