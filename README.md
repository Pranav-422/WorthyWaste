# WorthyWaste

Verified scrap sales become a waste picker's credit score and traceable recycling data, with Satin as the lender.
This is the SANKALP Round 1 demo: PRD R1–R7, plus the IVR path (R8) and recycler mass balance (R11).

Specs: `WorthyWaste — PRD.md`, `WorthyWaste — Tech Spec.md`, `WorthyWaste — Design Doc.md`.

## Run it

```bash
# 1. API (FastAPI; SQLite locally, Postgres when DATABASE_URL is set). Seeds demo data on first start.
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt    # macOS/Linux: .venv/bin/pip
WW_SCRIPTED=1 WW_DEMO_MODE=1 WW_ALLOW_RESET=1 WW_DEMO_KEY=local-demo-key \
  WW_PROVIDER_SECRET=local-provider-secret \
  .venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload --reload-dir app

# 2. Front end (Next.js + Tailwind), in another terminal. The demo shortcuts and the Satin
#    "Reset demo data" button need the same switches on this side.
cd frontend
WW_DEMO_MODE=1 WW_ALLOW_RESET=1 WW_DEMO_KEY=local-demo-key npm run dev
```

Everything works without those switches; you just get the app as production sees it — no simulated
scan, no scripted photo check, real GPS, and no reset button. See the [environment variables](#environment-variables)
table for what each one does.

Open http://localhost:3000. The API lives under `/api` (health check: `/api/health`, docs: `/api/docs`).

| Route | Who | |
| --- | --- | --- |
| `/` | Everyone | Public web page: problem, how it works, who it serves, fraud checks, score |
| `/login` | Collectors, dealers and Satin | Phone + 4-digit PIN, with tap-to-fill sample accounts |
| `/collector` | Logged-in collector | QR card, new sale, waiting, ₹ received, score |
| `/dealer` | Logged-in dealer | Request queue, scan, weigh, approve and pay, today, sell to recycler |
| `/satin` | Satin branch manager | Overview, collectors, profile + eligibility, fraud flags, groups, impact |
| `/demo` | Recording | Two phones and the Satin laptop side by side (log in inside each phone once) |

**Sample logins** (seeded, PIN `1234` for all):

| Role | Account | Phone |
| --- | --- | --- |
| Collector | Meena Devi (demo hero) | 9810000001 |
| Collector | Sunita Kumari (new, not yet eligible) | 9810000002 |
| Collector | Lakshmi Bai (repaid a loan) | 9810000003 |
| Dealer | Raju Kabadi Store (demo dealer) | 9811000001 |
| Dealer | Gupta Scrap Traders (mass-balance flag) | 9811000002 |
| Satin | Priya Sharma (branch manager, Narela) | 9812000001 |

Login sets an httpOnly cookie per role (`ww_collector`, `ww_dealer`, `ww_satin`), so a collector, a dealer and
the branch manager can all be signed in in the same browser — which is how `/demo` works. The API checks the
cookie on every action, a collector or dealer can act only as themselves, and every Satin endpoint needs the
Satin session: `/flags`, `/flags/{id}`, `/loans`, `/groups`, `/satin/overview`, `/scores/recompute`,
`/collectors` and `/batches/{code}`. A collector's full profile is for that collector or for Satin.

**Dealers never receive a collector's `qr_token`, `phone` or `upi_vpa`** — they get a name and a group, which is
what serving the person in front of them needs. That is also why the demo's "simulate scan" runs on the server
(`POST /api/demo/requests/{id}/simulate-scan`): the QR token the scan would read never leaves the backend.

**A sale is between one collector and one dealer.** The collector picks the shop when they raise the request —
`GET /api/dealers/nearby` lists registered shops within 5 km, nearest first, with the one they sold to last
preselected, carrying only a name and a distance. The request is stored against that shop, so it appears in that
dealer's queue and nowhere else; every other dealer gets **404** from `/requests/{id}`, accept, weigh and
approve, because 403 would confirm the sale exists. The collector follows their own side at
`GET /api/collectors/me/requests` and can withdraw a request with `POST /api/requests/{id}/cancel` while it is
still open. Satin sees a collector's completed sales — what scores, flags and loans are built from — but not
ones still in flight.

`WW_SCRIPTED=1` makes the simulated scale read est × 0.978, so 28 kg always becomes 27.4 kg and every take matches the script.

**Demo shortcuts** — the dealer's simulated scan, over-estimated load and location menu, and the collector's
"resend the previous photo", fixed location and scripted photo check — appear only when the server has
`WW_DEMO_MODE=1` **and** the URL asks for them with `?demo=1`. A visitor cannot add an environment variable to a
URL, so production never shows them; the query parameter lets one deployment be shown either way while
recording. The API enforces the same switch independently, so a hand-made request cannot reach a shortcut the
page hides. Without the shortcuts the collector app sends real GPS and says so plainly if location is refused.

**Reset demo data** is at the bottom of the Satin sidebar, visible only to a signed-in branch manager. It needs
`WW_ALLOW_RESET=1` and `X-Demo-Key: $WW_DEMO_KEY`; without both, `POST /api/demo/reset` answers 403.

## Demo click path (Design Doc)

1. Collector: *नई बिक्री* → shop *Raju Kabadi Store · 0 m दूर · पिछली बार यहीं* (preselected) → plastic
   → 28 kg → take photo → *भेजें*.
   With GEMINI_API_KEY set the photo check is real: photograph actual plastic bottles. A photo of a screen,
   a printout or a laptop's test camera is (correctly) flagged as not a real scene. If you are recording
   without real scrap to hand, pick *Demo: photo check sees* → `plastic` before taking the photo.
2. Dealer: tap Meena's request → scan her QR (or *Demo: simulate a successful scan*) → "Location matched".
   Her waiting screen ticks *भेजा → स्वीकार → तौला → पैसा मिला* as he goes.
3. Dealer: *Weigh* → 27.4 kg vs 28 kg estimate, within 10%.
4. Dealer: confirm the material (pre-selected: *Plastic bottles*, the collector's choice) → *Approve and pay ₹340*
   → mock UPI succeeds after 1 s.
5. Collector: marigold "₹340 मिले · 27.4 kg" with voice.
6. Fraud 1: collector → *नई बिक्री* → *Demo: resend the previous photo* → "यह फ़ोटो पहले इस्तेमाल हो चुकी है".
7. Fraud 2: collector → *नई बिक्री* → plastic → *Demo: photo check sees* → `cardboard` → take a photo → *भेजें*
   → "ये गत्ता लग रहा है — सही चुनें या फिर से फ़ोटो लें", spoken, with *Change material* and *Send anyway*.
8. Fraud 3: Satin → Fraud flags → "Circular payment: ₹340 returned to Gupta Scrap Traders within 2 h…".
9. Satin → Collectors → Meena → score **642**, five inputs shown → *Starter loan unlocked · ₹5,000*.

Also seeded: a volume outlier (Farida, 180 kg in one day) and a mass-balance gap (Gupta, 32%).

Loan eligibility is held while a flag about a completed sale or payment (weight gap, volume outlier, circular
payment, pair frequency, photo mismatch) is open; Satin confirming or dismissing it decides. A duplicate photo is
refused before any money moves, so it is logged for Satin but only freezes eligibility once confirmed, which is
why Meena stays eligible after step 6 — and a single photo mismatch is only recorded, never flagged, so step 7
does not freeze her either.
The dealer's location menu has a "1 km away" option, which shows the GPS block.

## Photo check

The duplicate-photo hash catches a photo used twice. It cannot tell whether the photo shows what the collector
said it shows, so a second check reads the photo itself.

`POST /requests` re-encodes the JPEG with Pillow — which writes pixels only, so the EXIF a phone embeds,
including its GPS tags, is dropped from both what we send and what we store — and asks a `PhotoVerifier`
(`backend/app/adapters.py`) for strict JSON: `material`, `confidence` 0–1, `real_scene`, `approx_quantity`,
`notes`. `GeminiPhotoVerifier` calls Google's Gemini API over plain REST when `GEMINI_API_KEY` is set;
without a key the mock answers "unavailable", which is also what every test gets.

The model is sent a 512 px copy at quality 80 — enough to tell cardboard from plastic, and much faster than the
768 px copy the dealer sees. Each attempt gets 15 s, a 429, a 503 or a dropped connection buys one retry after
~1 s, and the whole check is bounded at 20 s so a slow model can never push the request towards the 60 s
function limit. A 400 is not retried; it would only fail again.

**A failing photo check must not look like a passing one.** Every failure logs the model, the HTTP code,
Google's own `error.status` and the latency — never the key, never the image — and the last one is kept in
memory and shown on `/api/health`:

```json
{ "photo_check": "GeminiPhotoVerifier", "photo_check_model": "gemini-3.5-flash-lite",
  "photo_check_last_ms": 4820, "photo_check_last_error": null }
```

| Verdict | When | What happens |
| --- | --- | --- |
| `match` | same material as the collector picked, confidence ≥ 0.8 | nothing; a quiet green badge for the dealer |
| `mismatch` | a different material ≥ 0.8, or `not_scrap`, or `real_scene` false | the collector is warned **once** before sending |
| `uncertain` | anything else, including a genuinely `mixed` load | goes through, badged "AI: not sure" |
| `unchecked` | no key, a timeout, bad JSON, an unknown material, a broken adapter | goes through, no badge |

**An AI guess never refuses a sale.** On a mismatch the collector sees one screen: their choice beside what the
photo check saw, the reason spoken in Hindi or English, and two ways out — *Change material*, or *Send anyway*,
which sends it as a mismatch and records that on the request. The dealer then sees the photo, the collector's
choice and the badge ("AI: looks like cardboard (87%)"), and **confirms the material in one tap before paying**.
Their answer sets the rate, so the amount paid, the credits' batch and the traceable record all follow the
person who had the scrap in their hands.

The `photo_mismatch` rule turns that into a flag only when there is a pattern:

| Trigger | Action |
| --- | --- |
| one AI mismatch | recorded on `sale_requests.ai_verdict`, no flag |
| 3+ mismatches in 7 days | flag on the collector, holds loan eligibility until Satin decides |
| the dealer confirms a different material than the collector chose | flag on that sale, holds eligibility |

Satin's flag card shows the photo, the collector's choice, the AI verdict and the dealer's confirmation side by
side, because the flag is a disagreement about what was in the sack and Satin is the one who settles it.

## Voice

Phones and laptops often have no Hindi speech voice, so the collector app never relies on one:

- Fixed prompts and the scripted ₹340 confirmation play whole pre-recorded clips (`frontend/lib/audio-clips.json`).
- A sale confirmation of any other amount is joined from recorded segments (numbers 1–99, सौ, हज़ार, दशमलव,
  material names) by `frontend/lib/voiceCompose.ts`, with the silence between them trimmed.
- The photo-check warning is recorded per material, in both languages, so "ये गत्ता लग रहा है" plays as speech
  rather than silence.
- Anything else falls back to the browser's speech engine. If you change a prompt in `lib/i18n.ts` or the confirmation
text in `backend/app/services.py`, regenerate the clips (needs network, `pip install edge-tts`):

```bash
backend/.venv/Scripts/python scripts/make_audio.py          # records only what is missing
backend/.venv/Scripts/python scripts/make_audio.py --all     # re-records everything
```

Existing files are left alone by default: TTS is not reproducible, so re-recording an unchanged prompt would
rewrite 150-odd identical-sounding mp3s and bury the real change. A new or edited prompt gets a new filename
either way, because the name is a hash of its text. `npm test` fails if a prompt the app can speak has no clip.

## What's real and what's mocked

| Piece | Demo | Pilot swap |
| --- | --- | --- |
| Scale | `SimulatedScale` | BLE scale (`ScaleAdapter`) |
| UPI | `MockUpi`, settles ~1 s after approve, on the next status check | Aggregator collect/payout + signed webhook (`PaymentAdapter`) |
| Voice / WhatsApp / IVR | Stored messages, spoken by the browser | IVR + WhatsApp Business provider (`MessageAdapter`) |
| KYC | Skipped; ID stored only as a salted hash | Run through Satin (`KycAdapter`) |
| Duplicate photo | Real perceptual hash (`app/phash.py`, same output as `imagehash`), Hamming ≤ 6 over 30 days | Same |
| Photo vs material | Real Gemini call when `GEMINI_API_KEY` is set (`PhotoVerifier`); "unchecked" without a key | Same, thresholds tuned on pilot photos |
| Login | Phone + PIN (PBKDF2), signed session cookie | OTP via the SMS provider; rate limits in the database |
| Fraud rules, score v1, eligibility | Real, per Tech Spec | Thresholds tuned on pilot data |

## Environment variables

Nothing here has a permissive default: a missing secret always means "refuse", never "allow".

| Name | Needed by | What it does | Without it |
| --- | --- | --- | --- |
| `WW_SECRET` | api + web | Signs login sessions; both services must share it | A dev-only fallback locally; **required** in production |
| `DATABASE_URL` | api | Postgres (Neon on Vercel); `POSTGRES_URL` also accepted | Falls back to local SQLite |
| `WW_SCRIPTED` | api | Scripted scale (28 kg → 27.4 kg), so every take matches | Random reading near the estimate |
| `GEMINI_API_KEY` | api | Turns on the real photo check | Every photo comes back `unchecked` |
| `GEMINI_MODEL` | api | Model id for the photo check | Defaults to `gemini-3.5-flash-lite` |
| `WW_PROVIDER_SECRET` | api | HMAC key for `X-Provider-Signature` on `/payments/webhook`, `/upi/observed`, `/ivr/confirm` | Those three endpoints refuse every call (401) |
| `WW_DEMO_MODE` | api + web | Lets the demo shortcuts exist, when the URL also says `?demo=1` | No shortcuts; real GPS and the real photo check |
| `WW_ALLOW_RESET` | api + web | Allows `POST /api/demo/reset` at all | Reset answers 403 |
| `WW_DEMO_KEY` | api + web | The `X-Demo-Key` that reset requires | Reset answers 403 |

`WW_DEMO_MODE`, `WW_ALLOW_RESET` and `WW_DEMO_KEY` go to both services: the API decides what a request may do,
and the web app decides what to put on screen. The two checks are independent on purpose.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q
cd frontend && npm test          # voice composition, and that every prompt it can speak has a clip
cd frontend && npm run lint && npx tsc --noEmit && npx next build
```

The backend tests pin the env they need themselves (`tests/conftest.py`), including leaving `GEMINI_API_KEY`
unset, so no test calls the network.

| File | Covers |
| --- | --- |
| `test_demo_flow.py` | The whole click path on a fresh database: ₹340, the duplicate-photo block, score **642**, the unlocked ₹5,000 loan, logins and sessions. If you change the seed, this is the test that tells you whether the script still holds. |
| `test_photo_check.py` | Each verdict; "send anyway" records without blocking; a timeout or a crashing verifier leaves a sale `unchecked` rather than refused; 3 mismatches in 7 days hold the loan; a dealer override changes the material, the amount, the batch and what Satin sees |
| `test_security.py` | Reset without the key; Satin endpoints without a Satin session; provider endpoints without a signature; each demo shortcut with `WW_DEMO_MODE` off |
| `test_concurrency.py` | Double accept, double approve, a replayed webhook, a repeated IVR keypress, and the conditional updates themselves |
| `test_private_sale.py` | Picking a shop within 5 km; that another dealer gets 404 from every route for a sale that is not theirs; each queue holding only its own; the collector's status list through to paid; cancel; what Satin does and does not see |
| `test_photo_reliability.py` | The photo check against a fake HTTP layer: a retried rate limit, two timeouts becoming "unchecked" with the reason on `/api/health`, the 512 px image, the configured model id, and that health never carries the key |
| `test_review_fixes.py` | The setup lock is released, the photo check runs outside the lock and the transaction, and Satin staff are backfilled on an older database |

The same tests run against Postgres when `DATABASE_URL` is set. Without installing Postgres, PGlite works:

```bash
npx @electric-sql/pglite-socket --port=55432 --max-connections=8 &     # in-memory Postgres
DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable"   backend/.venv/Scripts/python -m pytest -q backend/tests
```

`--max-connections=8` matters: the two-thread accept test opens a connection per thread, and PGlite serves one
connection at a time by default. PGlite also runs transactions one at a time, so those two threads really overlap
only against a real Postgres — which is why the guarded updates have a direct test as well, and why the
double-accept check is re-run on the preview deploy.

## Deploy (Vercel only)

One Vercel project runs both halves with [Vercel Services](https://vercel.com/docs/services) (beta, all plans).
The root `vercel.json` defines a `web` service (Next.js, `frontend/`) and an `api` service (FastAPI, `backend/`),
and routes `/api/*` to the API and everything else to the web app, on one domain. Data lives in Postgres.

1. **Create the project.** Import `Pranav-422/WorthyWaste` at vercel.com/new and keep the **root directory as the
   repo root**, so Vercel reads `vercel.json` and builds both services.
2. **Add Postgres.** Project → Storage → Create → **Neon** (Vercel Marketplace) → connect it to the project. This adds
   `DATABASE_URL` for all environments; the API also accepts `POSTGRES_URL`.
3. **Set environment variables** (Project → Settings → Environment Variables, all environments):

   | Name | Value | Why |
   | --- | --- | --- |
   | `WW_SECRET` | 32+ random characters, e.g. `openssl rand -hex 32` | Signs login sessions. Shared by both services, so the web app can check them. Required in production. |
   | `WW_SCRIPTED` | `1` | Scripted scale (28 kg → 27.4 kg), so the recording matches every take |
   | `WW_PROVIDER_SECRET` | 32+ random characters | HMAC key for the payment and IVR webhooks. Without it those endpoints refuse everything. |
   | `WW_DEMO_KEY` | 32+ random characters | The `X-Demo-Key` that `POST /api/demo/reset` requires |
   | `WW_ALLOW_RESET` | `1` for the demo, unset otherwise | Allows reset at all; with `WW_DEMO_KEY` it also puts the button in the Satin sidebar |
   | `WW_DEMO_MODE` | `1` for the recording, unset otherwise | Lets the demo shortcuts exist on URLs that ask with `?demo=1` |
   | `GEMINI_API_KEY` | from Google AI Studio | Turns on the photo check. Without it photos come back `unchecked` and nothing breaks. |
   | `GEMINI_MODEL` | optional, e.g. `gemini-3.5-flash` | Overrides the default `gemini-3.5-flash-lite` |

   `WW_SECRET`, `WW_DEMO_MODE`, `WW_ALLOW_RESET` and `WW_DEMO_KEY` are read by **both** services, so add them
   without restricting them to one. `GEMINI_*` and `WW_PROVIDER_SECRET` are only read by the API.

4. **Deploy.** Push to `main`, or run `vercel deploy --prod` from the repo root. On first start the API creates its
   tables and seeds the demo data (an advisory lock stops two cold starts from seeding twice).
5. **Check:** `/api/health` should report `"db": "postgres"`; then log in with the sample accounts above.

Notes:

- Photos are stored in Postgres (`photos` table), because function instances don't share a disk. They are
  re-encoded first, so the EXIF a phone embeds — including its GPS tags — never reaches the database.
- The mock UPI payment settles when the app next checks the request, since serverless functions don't run background timers.
- Several instances run at once, so no in-process lock can keep a sale consistent. Every state change is a
  conditional `UPDATE ... WHERE id = ? AND <expected status>` that answers 409 when it matches no row; that is
  what stops one request being accepted or paid twice.
- To try the Services setup locally without a Vercel login: `npx vercel dev -L` from the repo root.
