# WorthyWaste — demo video: setup and script

Length ≈ 4:30. Record in two takes (the collector login is shared, so Phase 1 and Phase 2 can't be on screen together). Voice-over in English for Satin's judges; the Hindi lines are what the apps themselves say.

## Before recording (10 minutes)

1. **Reset demo data** (production): log in as Satin (9812000001 / 1234) → bottom of the left menu → *Reset demo data*. Wait ~20 s. This brings in Sunil, Anita, the hotel and the team login.
2. Chrome, one window per role, 1080p, hide bookmarks bar, zoom 100%, notifications off.
3. Log in once in each window (PIN 1234 everywhere):

   | Window | Role tab | Phone |
   | --- | --- | --- |
   | Phone-size, left | Collector | 9810000001 (Meena) — Take 1 · 9810000006 (Sunil) — Take 2 |
   | Phone-size, middle | Dealer · Home | 9811000001 (Raju) — Take 1 · 9814000001 (Anita) — Take 2 |
   | Wide, right | Satin · Team | 9812000001 (Priya) — Take 1 · 9813000001 (Team) — Take 2 |

4. Open **`https://worthywaste.vercel.app/demo`** for Take 1 and **`/demo/doorstep`** for Take 2. Both use `?demo=1` inside, so the location is fixed and the shortcuts work.
5. Turn sound on: the collector app speaks Hindi. Record system audio plus your mic, mic a bit lower during the Hindi lines.
6. Do one dry run. If you do the sale twice, reset again; a repeated photo is (correctly) refused.

## Take 1 — Waste pickers (≈ 2:15)

| Time | On screen | Say |
| --- | --- | --- |
| 0:00 | Landing page, slow scroll to "They earn every day. Nothing records it." | "India has millions of waste pickers. They earn every day, but nothing records it. So banks can't lend to them, and brands can't prove where their plastic went." |
| 0:20 | Collector app (Meena) | "This is Meena. She collects scrap and sells it to a kabadi shop. The app speaks Hindi, uses big icons, and works on a basic phone." |
| 0:30 | *नई बिक्री* → shop is pre-selected → plastic → 28 kg → *Demo: fake the AI answer* = plastic → photo → *भेजें* | "She picks her shop, the material and the weight, and takes a live photo. No gallery, so she can't upload an old one." |
| 0:55 | Dealer (Raju): tap Meena's request → *Demo: simulate a successful scan* | "Raju sees only requests sent to him. A sale is private between the two of them. He scans her QR, and both phones' GPS must be within 50 metres." |
| 1:10 | *Weigh* → 27.4 kg | "The scale sets the weight, not a person. 27.4 kilos against her estimate of 28." |
| 1:20 | Confirm material → *Approve and pay ₹340* | "He confirms what's in the sack and pays by UPI. No payment, no record." |
| 1:35 | Meena's phone: ₹340, voice plays | "Meena hears it in Hindi: three hundred and forty rupees received." |
| 1:45 | Collector → *नई बिक्री* → *Demo: resend the previous photo* | "Fraud check one: the same photo again. Refused." |
| 1:55 | *Demo: fake the AI answer* = cardboard → send | "Fraud check two: Gemini looks at the photo. If it disagrees with her choice, we warn her first. We never let the AI block a sale on its own." |
| 2:05 | Satin → Fraud flags → circular payment | "Satin sees the rest. Here a dealer's payout came straight back to the collector within two hours." |
| 2:15 | Satin → Collectors → Meena → score 642, five inputs → *Starter loan unlocked ₹5,000* | "Every verified sale feeds an explainable score. 642 out of 900, with the reason for each input. She's now eligible for a group-backed starter loan." |

## Take 2 — Phase 2: from the household (≈ 2:00)

| Time | On screen | Say |
| --- | --- | --- |
| 2:30 | Landing page, "From the household, too" | "Waste is created at home, so Phase 2 starts there. Door-to-door garbage collectors have the same problem: steady work, no record." |
| 2:40 | Sunil's route (15 of 30 homes done) | "This is Sunil. His round is 30 homes. Every door has a QR sticker." |
| 2:50 | *दरवाज़े का QR स्कैन करें* → *Demo: simulate scanning* → B-204 → *अलग-अलग* → *दर्ज करें* | "He scans the door, GPS must match the home, and he marks the waste separated or mixed. One pickup per home per day." |
| 3:05 | Done screen: +₹5, "home got 5 points" | "He earns five rupees for the pickup, and the home earns points for separating." |
| 3:15 | Anita's Green Wallet: today's pickup, WhatsApp message | "Anita gets a WhatsApp straight away. It's also the 24-hour notice that UPI AutoPay requires." |
| 3:25 | Tap *Demo: run tomorrow's AutoPay now* | "Next day her bank is debited by AutoPay: ₹5.50, five for Sunil and fifty paise for us. We never hold her money, so no wallet licence is needed." |
| 3:40 | Points card → redeem | "Separate your waste, shrink your bill: a hundred points take five rupees off the fee." |
| 3:50 | *पिकअप नहीं हुआ?* (use a second take, or just show the button) | "If Sunil scans a door but doesn't pick up, one tap and nothing is charged. Three of those in a week flags him." |
| 4:00 | Satin → Sunil → "Starter loan unlocked" | "And Sunil's pickups build the same score. Satin gets a second new borrower group, without a single scrap sale." |
| 4:10 | Team dashboard → Revenue | "For us, five streams: a fifty-paise fee per pickup, a lead fee on every Satin loan, compliance reports for hotels and societies, a Pro plan for dealers, and insurance commission." |
| 4:25 | Wards & collection | "And the ward view shows coverage, segregation rates and homes missed for two days." |
| 4:35 | Landing page | "One verified record, from the home to the recycler. WorthyWaste." |

## Tips

- Keep the Hindi audio on: it's the part judges remember.
- Mention on screen that rates and fees are pilot assumptions.
- Don't show the login page with phone numbers; log in before you start recording.
- If something fails mid-take: *Reset demo data*, log in again, retake. Don't edit around it.
- Prices to say out loud only as "pilot assumptions": ₹5 pickup fee, ₹0.50 platform fee, ₹999 compliance, ₹199 Pro, ₹49 insurance.
