// Every fixed prompt the collector app can speak must have a recorded clip, because many phones
// have no Hindi speech voice at all. Run with: npm test
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { mismatchMaterials, mismatchVoice, voice } from "../lib/i18n.ts";

const root = join(import.meta.dirname, "..");
const clips: Record<string, string> = JSON.parse(
  readFileSync(join(root, "lib", "audio-clips.json"), "utf8"),
);

function assertRecorded(text: string) {
  const url = clips[text];
  assert.ok(url, `no clip for: ${text}\n  add it to scripts/make_audio.py and re-run the script`);
  assert.ok(existsSync(join(root, "public", url)), `missing file ${url} for: ${text}`);
}

test("every screen instruction has a clip", () => {
  for (const line of Object.values(voice)) {
    assertRecorded(line.hi);
    assertRecorded(line.en);
  }
});

test("every photo-mismatch warning has a clip, in both languages", () => {
  // null, "mixed" and "not_scrap" all fall back to the one line with no material to name.
  const materials = [...mismatchMaterials, null, "mixed", "not_scrap"];
  for (const lang of ["hi", "en"] as const) {
    for (const m of materials) assertRecorded(mismatchVoice(lang, m));
  }
});

test("the material-specific warnings really are material-specific", () => {
  // A copy-paste slip here would voice "this looks like cardboard" for a plastic photo.
  const lines = mismatchMaterials.map((m) => mismatchVoice("hi", m));
  assert.equal(new Set(lines).size, lines.length);
  assert.ok(mismatchVoice("hi", "cardboard").includes("गत्ता"));
  assert.equal(mismatchVoice("hi", "mixed"), mismatchVoice("hi", null));
});
