# WorthyWaste — Technical Specification

Oct 2, 2026 · @Pranav

Three front ends (collector, dealer, Satin dashboard) share one backend that records sales, scores collectors and flags fraud. The Round 1 demo runs on mock integrations; the pilot swaps in real UPI, scale, IVR and KYC behind the same interfaces.

## Architecture

All three apps talk to one FastAPI backend; nothing outside it touches the database.

&#91;embedded content: system architecture · 3 apps, 4 backend services, storage and providers\]

The Transaction API runs fraud rules inline at each step; the score engine recomputes nightly from stored transactions.

## Tech stack

One stack for both stages; the pilot only swaps adapters and the database.

| Layer | Round 1 demo | Pilot |
| --- | --- | --- |
| Front end | Next.js + Tailwind, three routes: `/collector`, `/dealer`, `/satin` | Same, plus a PWA for dealers' Android phones |
| Backend | FastAPI (Python) | Same |
| Database | SQLite with seeded mock data | PostgreSQL (with PostGIS for GPS checks) |
| Photo checks | Perceptual hash with the `imagehash` library | Same, hashes stored per photo |
| Scale | Simulated reading with a "weigh" button | Bluetooth scale via Android BLE or Web Bluetooth |
| Payments | Mock UPI success screen | A payment aggregator's UPI collect and payout APIs |
| Voice / WhatsApp | Prerecorded confirmation text | IVR + WhatsApp Business API provider |
| Hosting | Vercel (front end) + Render or Railway (API) | Cloud VM in an Indian region |

## Data model

A sale request becomes a transaction only once payment succeeds; everything else hangs off that row.

| Table | Key fields | Notes |
| --- | --- | --- |
| `collectors` | id, name, phone, id\_type, id\_ref\_hash, group\_id, qr\_token, consent\_at, created\_at | ID stored as a hash, never raw |
| `groups` | id, name, leader\_id, city | Waste-picker group or SHG; backs first loans |
| `dealers` | id, shop\_name, phone, lat, lng, scale\_id, reputation, created\_at | One registered scale per dealer |
| `sale_requests` | id, collector\_id, material, est\_kg, photo\_url, photo\_phash, lat, lng, status, expires\_at | status: open, accepted, weighed, expired, rejected |
| `transactions` | id, request\_id, dealer\_id, scale\_kg, rate\_per\_kg, amount, upi\_ref, dealer\_lat, dealer\_lng, batch\_id, created\_at | Created only after UPI success |
| `batches` | id, dealer\_id, material, total\_kg, recycler\_sale\_id | Groups transactions sold on together |
| `recycler_sales` | id, dealer\_id, recycler\_name, kg, invoice\_ref, sold\_at | Basis for mass balance |
| `scores` | collector\_id, score, inputs\_json, computed\_at | Inputs stored so every score is explainable |
| `loans` | id, collector\_id, group\_id, principal, tenure\_m, status, repaid\_on\_time | Mirror of Satin's record; Satin is source of truth |
| `fraud_flags` | id, entity\_type, entity\_id, rule, detail, status, created\_at | status: open, confirmed, dismissed |

## API endpoints

Each step of the transaction is its own call, so every check runs at the step it guards.

| Method + path | Caller | Does | Checks run |
| --- | --- | --- | --- |
| `POST /requests` | Collector app | Creates a sale request with material, est\_kg, photo, GPS | Photo hash vs recent hashes; expiry set to +15 min |
| `POST /requests/{id}/accept` | Dealer app | Dealer scans collector QR and accepts | GPS distance under about 50 m; request still open |
| `POST /requests/{id}/weigh` | Dealer app / scale | Records scale\_kg from the scale | Gap vs est\_kg over 10% → flag; volume outlier check |
| `POST /requests/{id}/approve` | Dealer app | Starts UPI payment | Request accepted and weighed |
| `POST /payments/webhook` | Payment provider | On success, creates the transaction and credits | Circular-flow check on the UPI counterparties |
| `POST /ivr/confirm` | IVR provider | Basic-phone collector confirms a dealer-started sale | Caller ID matches the collector |
| `POST /recycler-sales` | Dealer app | Logs a bulk sale and links batches | Runs mass balance for that dealer |
| `GET /collectors/{id}/score` | Satin dashboard | Returns score, inputs and loan eligibility | — |
| `GET /flags?status=open` | Satin dashboard | Lists open fraud flags with reasons | — |
| `POST /scores/recompute` | Nightly job | Recomputes all scores | — |

## Credit score v1

A weighted sum of five inputs, each scaled to 0–1, mapped to 300–900. The weights are v1 assumptions the pilot will recalibrate against repayment.

```latex
\text{score} = 300 + 600\,(0.30A + 0.25C + 0.15T + 0.10D + 0.20R)
```

| Input | Meaning | Formula (0–1) | Weight |
| --- | --- | --- | --- |
| A | Activity | active selling days in last 30 ÷ 26, capped at 1 | 0.30 |
| C | Consistency | 1 − coefficient of variation of the last 3 months' income, clipped to 0–1 | 0.25 |
| T | Tenure | months on platform ÷ 12, capped at 1 | 0.15 |
| D | Dealer spread | distinct verified dealers ÷ 3, capped at 1 | 0.10 |
| R | Repayment | on-time instalments ÷ due instalments; 0.5 (neutral) before any loan | 0.20 |

**Eligibility rule** (checked before the score): at least 30 days on platform and 20 verified sales, no open confirmed fraud flag, and a group guarantee recorded. The first loan is about ₹5,000; the limit steps up after each cycle repaid on time.

Every score is stored with its inputs, so Satin can see why a collector scored what they did.

## Fraud rules engine

Rules run at the step they guard; each one blocks or writes a flag with its reason. Thresholds are starting values to tune in the pilot.

| Rule | Logic | Threshold | Action |
| --- | --- | --- | --- |
| Duplicate photo | Hamming distance between perceptual hashes of new photo and photos from the last 30 days | Distance ≤ 6 | Block request |
| Location mismatch | Distance between collector and dealer GPS at accept | > 50 m | Block accept |
| Weight gap | \|scale\_kg − est\_kg\| ÷ est\_kg | > 10% | Use scale weight; flag if repeated 3+ times in 7 days |
| Volume outlier | Collector's daily kg vs physical cap for their equipment | > 150 kg/day on a hand cart | Flag |
| Circular payment | Money from dealer to collector returns to the dealer, or to a linked UPI ID, within a short window | Within 48 h | Flag both parties |
| Pair frequency | Same dealer–collector pair vs that dealer's normal pattern | > 3× dealer's median per pair | Flag |
| Mass balance | Dealer kg bought vs kg sold to recyclers over 30 days | Bought exceeds sold by > 15% | Flag dealer |
| Request expiry | Request not accepted in time | 15 min | Expire |

A confirmed flag freezes loan eligibility for the people involved and lowers the dealer's reputation.

## Integrations, security and privacy

Every integration sits behind an adapter interface, so the demo's mocks and the pilot's real providers are swappable.

| Integration | Adapter | Demo | Pilot |
| --- | --- | --- | --- |
| UPI payments | `PaymentAdapter` | Mock success after 1 s | Payment aggregator, webhook-confirmed |
| Scale | `ScaleAdapter` | Random reading near est\_kg | BLE scale paired to the dealer's phone |
| IVR / WhatsApp | `MessageAdapter` | On-screen message | IVR and WhatsApp Business API provider |
| KYC | `KycAdapter` | Skipped | Run through Satin, the regulated lender |

**Security and privacy**

- ID numbers stored only as salted hashes; no raw Aadhaar in our database.
- Consent recorded (voice clip reference + timestamp) before any data leaves the platform.
- Brands receive pseudonymised batch data only; collector identity never leaves the system.
- Role-based access: collectors see their own data, dealers their own log, Satin only consented collectors.
- Photos stored in a private bucket with signed URLs; GPS kept at transaction level only.
- Lending data flows through Satin under the RBI Digital Lending Directions, 2025; data handling designed for the DPDP Act. Exact clauses to be checked before pilot.

## Build plan

The demo must show one full transaction and two caught frauds end to end; submit by Sunday 8 PM to leave a buffer before the 11:59 PM deadline.

**Friday evening — foundation**

- [ ] Next.js app with three routes and a shared layout
- [ ] FastAPI with SQLite; seed 5 collectors, 2 dealers, 60 past transactions
- [ ] `POST /requests`, `/accept`, `/weigh`, `/approve` with mock adapters

**Saturday — the flow and the brains**

- [ ] Collector screens: QR card, new request, wallet, score
- [ ] Dealer screens: incoming requests, weigh, approve, UPI success, log
- [ ] Score v1 and eligibility rule, computed from seeded history
- [ ] Fraud rules: duplicate photo, weight gap, circular payment, mass balance
- [ ] Satin dashboard: collector list, score breakdown, open flags, tonnes chart

**Sunday — polish and record**

- [ ] Scripted demo data so the recording runs the same every take
- [ ] Deploy (Vercel + Render) and test on a phone
- [ ] Record the transaction and both fraud catches for the video
- [ ] Screenshots for the deck
