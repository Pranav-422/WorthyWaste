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
WW_SCRIPTED=1 .venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload --reload-dir app

# 2. Front end (Next.js + Tailwind), in another terminal
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The API lives under `/api` (health check: `/api/health`, docs: `/api/docs`).

| Route | Who | |
| --- | --- | --- |
| `/` | Everyone | Public web page: problem, how it works, who it serves, fraud checks, score |
| `/login` | Collectors and dealers | Phone + 4-digit PIN, with tap-to-fill sample accounts |
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

Login sets an httpOnly cookie per role (`ww_collector`, `ww_dealer`), so a collector and a dealer can be signed in
in the same browser. The API checks it on every collector and dealer action, and a user can act only as themselves.
The Satin dashboard has no login in this demo; it shows sample data only.

`WW_SCRIPTED=1` makes the simulated scale read est × 0.978, so 28 kg always becomes 27.4 kg and every take matches the script.
Add `&demo=0` to the collector or dealer URLs to hide the demo shortcuts and use real GPS.
**Reset demo data** is at the bottom of the Satin sidebar (or `POST /api/demo/reset`).

## Demo click path (Design Doc)

1. Collector: *नई बिक्री* → plastic → 28 kg → take photo → *भेजें*.
2. Dealer: tap Meena's request → scan her QR (or *Demo: simulate a successful scan*) → "Location matched".
3. Dealer: *Weigh* → 27.4 kg vs 28 kg estimate, within 10%.
4. Dealer: *Approve and pay ₹340* → mock UPI succeeds after 1 s.
5. Collector: marigold "₹340 मिले · 27.4 kg" with voice.
6. Fraud 1: collector → *नई बिक्री* → *Demo: resend the previous photo* → "यह फ़ोटो पहले इस्तेमाल हो चुकी है".
7. Fraud 2: Satin → Fraud flags → "Circular payment: ₹340 returned to Gupta Scrap Traders within 2 h…".
8. Satin → Collectors → Meena → score **642**, five inputs shown → *Starter loan unlocked · ₹5,000*.

Also seeded: a volume outlier (Farida, 180 kg in one day) and a mass-balance gap (Gupta, 32%).

Loan eligibility is held while a flag about a completed sale or payment (weight gap, volume outlier, circular
payment, pair frequency) is open; Satin confirming or dismissing it decides. A duplicate photo is refused before
any money moves, so it is logged for Satin but only freezes eligibility once confirmed, which is why Meena stays
eligible after step 6.
The dealer's location menu has a "1 km away" option, which shows the GPS block.

## Voice

Phones and laptops often have no Hindi speech voice, so the collector app never relies on one:

- Fixed prompts and the scripted ₹340 confirmation play whole pre-recorded clips (`frontend/lib/audio-clips.json`).
- A sale confirmation of any other amount is joined from recorded segments (numbers 1–99, सौ, हज़ार, दशमलव,
  material names) by `frontend/lib/voiceCompose.ts`, with the silence between them trimmed.
- Anything else falls back to the browser's speech engine. If you change a prompt in `lib/i18n.ts` or the confirmation
text in `backend/app/services.py`, regenerate the clips (needs network, `pip install edge-tts`):

```bash
backend/.venv/Scripts/python scripts/make_audio.py
```

## What's real and what's mocked

| Piece | Demo | Pilot swap |
| --- | --- | --- |
| Scale | `SimulatedScale` | BLE scale (`ScaleAdapter`) |
| UPI | `MockUpi`, settles ~1 s after approve, on the next status check | Aggregator collect/payout + signed webhook (`PaymentAdapter`) |
| Voice / WhatsApp / IVR | Stored messages, spoken by the browser | IVR + WhatsApp Business provider (`MessageAdapter`) |
| KYC | Skipped; ID stored only as a salted hash | Run through Satin (`KycAdapter`) |
| Photo check | Real perceptual hash (`app/phash.py`, same output as `imagehash`), Hamming ≤ 6 over 30 days | Same |
| Login | Phone + PIN (PBKDF2), signed session cookie | OTP via the SMS provider; rate limits in the database |
| Fraud rules, score v1, eligibility | Real, per Tech Spec | Thresholds tuned on pilot data |

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q
cd frontend && npm test          # voice composition, and that every segment it can ask for exists
```

`tests/test_demo_flow.py` runs the whole click path against a fresh database and asserts ₹340, the duplicate-photo block,
score 642 and the unlocked ₹5,000 loan, plus logins and sessions. If you change the seed, this test tells you whether
the script still holds.

The same tests run against Postgres when `DATABASE_URL` is set. Without installing Postgres, PGlite works:

```bash
npx @electric-sql/pglite-socket --port=55432 &       # in-memory Postgres
DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable"   backend/.venv/Scripts/python -m pytest -q backend/tests
```

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
   | `WW_ALLOW_RESET` | `1` for the demo, `0` otherwise | `POST /api/demo/reset` is open while this is `1` |

4. **Deploy.** Push to `main`, or run `vercel deploy --prod` from the repo root. On first start the API creates its
   tables and seeds the demo data (an advisory lock stops two cold starts from seeding twice).
5. **Check:** `/api/health` should report `"db": "postgres"`; then log in with the sample accounts above.

Notes:

- Photos are stored in Postgres (`photos` table), because function instances don't share a disk.
- The mock UPI payment settles when the app next checks the request, since serverless functions don't run background timers.
- To try the Services setup locally without a Vercel login: `npx vercel dev -L` from the repo root.
