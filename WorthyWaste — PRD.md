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
