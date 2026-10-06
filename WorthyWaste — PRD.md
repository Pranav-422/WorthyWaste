# WorthyWaste — Product Requirements Document

Oct 2, 2026 · @Pranav

WorthyWaste turns verified scrap sales into a credit score for waste pickers and traceable recycling data for brands, with Satin as the lending partner. This PRD defines what we build for the SANKALP Round 1 demo (due 4 Oct 2026) and for a 6-month pilot.

## Ideation

We chose WorthyWaste because it is the only idea that gives Satin a new borrower segment, has measurable climate impact, and can be demoed convincingly in three days.

| Idea | What it was | Verdict | Why |
| --- | --- | --- | --- |
| RainCheck | Auto-pause EMIs when satellite or weather data shows drought or flood | Dropped | Ground reality can differ from district-level data; region-wide pauses hurt Satin's cash flow; may count as restructuring under RBI rules; most Satin borrowers run small businesses, not farms |
| Carbon Kisan Network | Satin pools farmers into one carbon project; carbon income repays EMIs | Parked | Carbon-market details are hard to defend in Q&A |
| Thanda Ghar | Cool-roof loans for women home workers, EMI sized to hours regained | Parked | Strong story, weaker scale and data angle |
| GreenLedger AI | Clean-energy loans where EMI is below the fuel saved | Parked | Close to existing solar-loan products |
| **WorthyWaste** (was KachraCredit) | Verified scrap sales become a credit score + traceability data | **Chosen** | New segment for Satin, fits its group-lending model, measurable impact, few teams will pitch it |

**How the idea evolved.** The first version let collectors self-report sales. A teammate proposed two-party confirmation: the collector requests, the dealer approves. We kept that and made the proof stronger: the scale sets the weight, matching GPS shows both were present, and a UPI payment must exist for a record to count.

## Problem statement

**Waste pickers earn every day but have no record of it, so lenders can't serve them and brands can't trace what they recover.**

- India has an estimated 1.5–4 million informal waste pickers. They handle about 60–70% of urban recyclables, and about 70% of plastic recycling depends on them ([Down To Earth](https://www.downtoearth.org.in/waste/indias-waste-economy-runs-on-invisible-workers-climate-policy-keeps-forgetting-them)).
- Official estimates of plastic waste range from about 4 MT to about 9 MT a year, with recycling put anywhere between 13% and 60% ([CEEW](https://www.ceew.in/plastic-waste-recycling)). Nobody can trace what is actually recovered.
- Satin lends collateral-free to women through joint liability groups ([Satin](https://satincreditcare.com/product-portfolio/)), but has no data on this segment.

**Opportunity:** one verified transaction serves three parties at once. The collector gets income proof, Satin gets underwriting data, and brands get sourcing proof for EPR.

## Goals and non-goals

**Goals**

1. Create a fraud-resistant record of every scrap sale, verified by scale weight, GPS and UPI payment.
2. Turn those records into an explainable credit score that unlocks a first group-backed loan.
3. Give Satin a lender dashboard to see scores, eligibility and fraud flags.
4. Give recyclers and brands batch-level traceability data.
5. Work for collectors with basic phones and low literacy.

**Non-goals**

- We do not issue EPR certificates; only registered processors can.
- We are not a lender; Satin lends and holds the loans.
- We do not build a scrap marketplace or set scrap prices.
- No ML credit model in v1; the score is rule-based until the pilot gives repayment data.

## Personas

Three illustrative personas, to be checked against real interviews in the pilot.

| Persona | Who | Pain today | What WorthyWaste gives |
| --- | --- | --- | --- |
| **Meena, collector** | 34, collects about 25 kg a day, basic phone, member of a waste-picker group | Paid in cash, no records, borrows from a moneylender, can't buy a cart | Income proof, a score, a group-backed cart loan |
| **Raju, scrap dealer** | Runs a neighbourhood kabadi shop, buys from 40+ collectors, sells to a recycler | Paper billing, tight working capital, little trust from collectors | Digital billing, working-capital loans, UPI cashback, more collectors |
| **Priya, Satin branch manager** | Manages group loans in an urban area | No data to underwrite informal workers | A dashboard of verified income, scores, eligibility and fraud flags |

A fourth stakeholder, the **recycler or brand compliance team**, buys traceability data but has no in-app persona in v1.

## Requirements

P0 items are what the Round 1 demo must show; everything else is pilot or later.

| ID | User story | Acceptance criteria | Priority |
| --- | --- | --- | --- |
| R1 | As a collector, I raise a sale request with scrap type, estimated weight and a live photo | Icons for material types; camera only, no gallery; request expires in 15 min | P0 — Round 1 demo |
| R2 | As a dealer, I scan the collector's QR to accept a request | GPS of both phones within about 50 m, else blocked | P0 — Round 1 demo |
| R3 | As a dealer, I weigh on a connected scale and the weight auto-fills | Manual entry disabled; gap over 10% from estimate is flagged | P0 — Round 1 demo |
| R4 | As a dealer, I approve and pay by UPI in one step | No record is created without a successful payment | P0 — Round 1 demo |
| R5 | As a collector, I get credits and a confirmation in my language | Voice or WhatsApp message with amount, kg and material | P0 — Round 1 demo |
| R6 | As Satin, I see each collector's score, history and loan eligibility | Score 300–900 with the five inputs shown; eligibility follows the first-loan rule | P0 — Round 1 demo |
| R7 | As Satin, I see fraud flags with the reason | Duplicate photo, weight gap, circular payment, volume outlier, mass-balance gap | P0 — Round 1 demo |
| R8 | As a collector on a basic phone, I confirm a dealer-started sale by IVR | Press 1 to confirm; works without a smartphone | P1 — Pilot |
| R9 | As a collector, I hear my balance and score by giving a missed call | IVR reply in the local language | P1 — Pilot |
| R10 | As a group leader, I onboard members and back their first loan | KYC with Aadhaar or an alternative ID; group guarantee recorded | P1 — Pilot |
| R11 | As a recycler, I record bulk purchases so batches link back to collectors | Batch IDs reconcile with dealer purchases (mass balance) | P1 — Pilot |
| R12 | As a collector, I give consent before my data is shared | Voice opt-in recorded; brands see pseudonymised batch data only | P1 — Pilot |
| R13 | As a brand, I download a traceability report per tonne | Batch-level report, no personal data | P2 — Later |
| R14 | As a dealer, I apply for a working-capital loan in the app | Uses dealer reputation and volume history | P2 — Later |

## Scope

Round 1 needs a convincing clickable demo, not a production system.

| Stage | In scope | Out of scope |
| --- | --- | --- |
| Round 1 demo (by 4 Oct) | R1–R7 with mock data; simulated scale and UPI; one full transaction plus two caught frauds | Real payments, real KYC, real IVR |
| Pilot (6 months, 1 city) | Real UPI and Bluetooth scale, IVR, group onboarding, consent, recycler batch links (R8–R12) | Brand self-serve portal |
| Later | Brand reports, dealer loans, ML score once repayment data exists (R13–R14) | — |

## Success metrics

Targets are pilot hypotheses, to be set with Satin before launch.

| Metric | Why it matters | Pilot target |
| --- | --- | --- |
| Active collectors (sold at least 8 days in the month) | Adoption | 500 onboarded, majority active (to set) |
| Verified tonnes per month | Data volume and climate impact | Growing month on month |
| Share of sales paid by UPI | Proof quality | To set |
| Starter loans disbursed | Lending works | To set with Satin |
| On-time repayment rate | Score predicts risk | At or above Satin's group-loan baseline |
| Fraud flags confirmed vs raised | Checks are accurate, not noisy | To set |
| Traceability fee paid per tonne | Brands value the data | At least one paying recycler or brand |

## Phase 2: from the household to the recycler

**Every hand that waste passes through gets a verified record.** Phase 1 covers the middle of the chain (waste picker → dealer → recycler). Phase 2 adds the two ends that are missing: the household where waste is created, and the door-to-door garbage collector who picks it up.

### Why

- **Door-to-door garbage collectors** do daily, routine work, often through contractors and often paid irregularly. They face the same problem as waste pickers: steady income, no record. For Satin, that is a second new borrower segment.
- **Households** decide whether recyclables arrive clean and separated. Segregated dry waste is worth more to every collector, dealer and recycler downstream, but households have no reason to separate.
- **Municipalities (ULBs)** must show door-to-door coverage and segregation, but rarely have house-level data.
- **Brands** need to show their packaging was recovered (EPR). Source-level traces are stronger evidence than dealer-level ones.

One doorstep scan serves all four. The household gets a segregation record and rewards, the collector gets proof of work, the ULB gets coverage data, and the material is traced from the source.

### New personas

Illustrative, to be checked against interviews in the pilot ward.

| Persona | Who | Pain today | What WorthyWaste gives |
| --- | --- | --- | --- |
| **Sunil, door-to-door collector** | Drives a ULB or contractor garbage vehicle, covers about 300 homes a day | Wages late or in cash, no record of work done, no access to credit | Verified daily work log, income proof, a score and a group-backed loan |
| **Anita, household** | Runs a home in an RWA society, no time for apps | No reason to separate waste; doesn't know what happens to it | No app needed: a QR sticker on the door, a WhatsApp message per pickup, points she can redeem |
| **Ward officer, ULB** | Responsible for coverage and segregation in a ward | Paper registers, no way to see missed homes or unsegregated waste | A ward dashboard: homes covered, segregation rate, missed pickups |

### How it works

1. **Onboarding.** Each home gets a QR sticker on the door, linked to the address (no name needed). The household opts in once via WhatsApp.
2. **Pickup.** The collector scans the door QR. The app records GPS and time, and the collector marks *separated* or *mixed*, with a photo for dry waste. The same photo check used for waste pickers runs here.
3. **Household.** A WhatsApp message: "Aaj aapka kachra alag mila — +10 points". Points are redeemable for mobile recharge, local shop discounts, or brand offers.
4. **Collector.** Every verified pickup adds to their work record, which feeds the same score engine (activity, consistency, tenure) as waste pickers.
5. **Downstream.** Dry waste from the vehicle is weighed at the material recovery facility (MRF) or sold to a dealer, and enters the existing batch trace.

### Requirements

| ID | User story | Acceptance criteria | Priority |
| --- | --- | --- | --- |
| R15 | As a garbage collector, I scan a home's door QR at pickup | GPS within about 30 m of the registered home; one scan per home per day | P0 — Phase 2 pilot |
| R16 | As a garbage collector, I mark the waste separated or mixed, with a photo for dry waste | Photo check runs; same "never block on an AI guess" rule as R1 | P0 — Phase 2 pilot |
| R17 | As a household, I get a WhatsApp message and points for each separated pickup | No app install; message in the household's language | P0 — Phase 2 pilot |
| R18 | As a household, I redeem points | At least one redemption option (e.g. mobile recharge) in the pilot | P1 |
| R19 | As Satin, I see a garbage collector's work record and score | Same five-input score and eligibility rule as waste pickers | P0 — Phase 2 pilot |
| R20 | As a ward officer, I see coverage and segregation by street | Homes covered today, segregation rate, homes missed for 2+ days | P1 |
| R21 | As a brand, I sponsor household rewards for my packaging | Sponsored offers; report of recovered volume by ward | P2 |
| R22 | As a household, I control my data | Address-level only, no name; opt out by WhatsApp; ULB and brands see ward totals only | P0 — Phase 2 pilot |

### Fraud controls

| Risk | Control |
| --- | --- |
| Collector scans doors without picking up | GPS and time per scan; route plausibility (100 homes can't be scanned in 5 minutes); household can reply "no pickup today" |
| Collector and household collude to fake "separated" | Photo check; random spot checks; ward-level mass balance: separated dry waste scanned vs dry waste weighed at the MRF or sold to a dealer |
| QR stickers copied or moved | GPS must match the registered home; one scan per home per day |
| Points farming | Points cap per home per month; rewards only on separated pickups confirmed downstream |

### Revenue

| Who pays | For what |
| --- | --- |
| ULB | Ward dashboard and verified coverage data (Swachh Bharat Mission budgets), per home per month |
| Brands and recyclers | Source-level EPR traceability; sponsoring household rewards |
| Satin | Interest income from garbage collectors and, later, households (e.g. women's SHGs) |

### Pilot

One ward or one large RWA society: 1–2 collection vehicles, 200–300 homes, 3 months, alongside the Phase 1 waste-picker pilot in the same city.

| Metric | Why it matters | Target |
| --- | --- | --- |
| Homes scanned at least 5 days a week | Collectors actually use it | To set |
| Share of pickups marked separated | Behaviour change | Rising week on week |
| Households who redeem points | Rewards motivate | To set |
| Dry waste weighed vs scanned (mass balance) | Data is honest | Within 15% |
| Garbage collectors eligible for a first loan | Second borrower segment works | To set with Satin |

### Phase 2 open questions

- [ ] Which ULB or RWA will host the pilot ward, and who employs the collectors there (ULB or contractor)?
- [ ] What rewards can be funded at launch, and by whom (brand, ULB, or our margin)?
- [ ] Does the ULB already run a door-to-door tracking system we must integrate with rather than replace?

## Assumptions, risks and open questions

| Risk or assumption | Mitigation |
| --- | --- |
| Dealers prefer cash | UPI cashback at launch; loans only for on-platform dealers |
| Dealers resist a scale that exposes under-weighing | Working-capital loans, free billing, more collectors choose trusted dealers |
| Collectors lack smartphones or Aadhaar | QR card + IVR; e-Shram, voter ID or municipal waste-picker ID, verified by the group |
| Circular or fake sales | Circular UPI flow detection, pair-frequency checks, mass balance |
| Score is unproven | Rule-based v1, small group-backed loans, calibrate on pilot repayment data |
| Brands may not pay for traceability | Test the per-tonne fee in the pilot; lending alone must still work |
| Regulation (DPDP Act, RBI Digital Lending Directions, 2025) | Satin is the regulated lender; consent and pseudonymisation by design; clauses verified before any claim |

**Open questions**

- [ ] What is Satin's cost of funds and acceptable starter-loan size for this segment?
- [ ] Which city has a waste-picker group willing to partner?
- [ ] What traceability fee per tonne will a recycler pay?
- [ ] Exact video length and file limits on Satin's submission page?
