// Run with: npm test   (Node's built-in runner; Node 22.18+ strips the types)
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { composeSaleConfirmation, type SaleMeta } from "../lib/voiceCompose.ts";

const sale = (amount: number, kg: number, credits: number, material = "plastic"): SaleMeta => ({
  kind: "sale_confirmation",
  amount,
  kg,
  material,
  credits,
});

test("Hindi: ₹340 for 27.4 kg plastic, 27 credits", () => {
  assert.deepEqual(composeSaleConfirmation("hi", sale(340, 27.4, 27)), [
    "n-3", "w-sau", "n-40", "w-rupaye-mile",
    "n-27", "w-dashamlav", "n-4", "w-kilo", "m-plastic",
    "w-khaate-mein", "n-27", "w-credit-jude",
  ]);
});

test("English: ₹1,205 for 50 kg wire, 50 credits", () => {
  assert.deepEqual(composeSaleConfirmation("en", sale(1205, 50, 50, "wire")), [
    "n-1", "w-thousand", "n-2", "w-hundred", "n-5", "w-rupees-received",
    "n-50", "w-kilos-of", "m-wire",
    "n-50", "w-credits-added",
  ]);
});

test("unvoiceable inputs fall back", () => {
  assert.equal(composeSaleConfirmation("hi", sale(150000, 10, 10)), null);
  assert.equal(composeSaleConfirmation("hi", sale(100, 10, 10, "gold")), null);
});

test("every composed segment has an audio file", () => {
  const root = join(import.meta.dirname, "..", "public", "audio", "seg");
  const materials = ["plastic", "cardboard", "metal", "paper", "wire", "glass"];
  for (const lang of ["hi", "en"] as const) {
    const seen = new Set<string>();
    for (let amount = 0; amount < 100000; amount += amount < 2000 ? 1 : 97) {
      const kg = (amount % 1000) / 10;
      for (const k of composeSaleConfirmation(lang, sale(amount, kg, amount % 500, materials[amount % 6]))!) seen.add(k);
    }
    for (const k of seen) assert.ok(existsSync(join(root, lang, `${k}.mp3`)), `missing ${lang}/${k}.mp3`);
  }
});
