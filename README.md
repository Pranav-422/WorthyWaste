# WorthyWaste

Verified scrap sales become a waste picker's credit score and traceable recycling data, with Satin as the lender.
This is the SANKALP Round 1 demo: PRD R1–R7, plus the IVR path (R8) and recycler mass balance (R11).

Specs: `WorthyWaste — PRD.md`, `WorthyWaste — Tech Spec.md`, `WorthyWaste — Design Doc.md`.

## Run it

```bash
# 1. API (FastAPI + SQLite). Seeds demo data on first start.
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt    # macOS/Linux: .venv/bin/pip
WW_SCRIPTED=1 .venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload --reload-dir app

# 2. Front end (Next.js + Tailwind), in another terminal
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. `/demo` shows two phones and the Satin laptop side by side for recording.

| Route | Who | |
| --- | --- | --- |
| `/collector?id=1` | Meena (collector) | QR card, new sale, waiting, ₹ received, score |
| `/dealer?id=1` | Raju Kabadi Store | Request queue, scan, weigh, approve and pay, today, sell to recycler |
| `/satin` | Satin branch manager | Overview, collectors, profile + eligibility, fraud flags, groups, impact |

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
| UPI | `MockUpi`, webhook after 1 s | Aggregator collect/payout + signed webhook (`PaymentAdapter`) |
| Voice / WhatsApp / IVR | Stored messages, spoken by the browser | IVR + WhatsApp Business provider (`MessageAdapter`) |
| KYC | Skipped; ID stored only as a salted hash | Run through Satin (`KycAdapter`) |
| Photo check | Real perceptual hash (`imagehash`), Hamming ≤ 6 over 30 days | Same |
| Fraud rules, score v1, eligibility | Real, per Tech Spec | Thresholds tuned on pilot data |

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q
cd frontend && npm test          # voice composition, and that every segment it can ask for exists
```

`tests/test_demo_flow.py` runs the whole click path against a fresh database and asserts ₹340, the duplicate-photo block,
score 642 and the unlocked ₹5,000 loan. If you change the seed, this test tells you whether the script still holds.

## Deploy

- **API → Render.** New → Blueprint → pick this repo; `render.yaml` sets everything up. The free plan sleeps after
  15 idle minutes and its disk is wiped on restart, so the API re-seeds fresh demo data on each cold start.
  Open `/health` a minute before recording to wake it.
- **Front end → Vercel**, root directory `frontend`, with `API_URL` set to the Render URL at build time
  (rewrites are fixed at build): `vercel deploy --prod --cwd frontend --build-env API_URL=https://<api>.onrender.com`.

`POST /api/demo/reset` is open on purpose for the demo; set `WW_ALLOW_RESET=0` on any non-demo deployment.
