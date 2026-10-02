# WorthyWaste — Design Doc

Oct 2, 2026 · @Pranav

WorthyWaste is designed for a collector who may not read, a dealer serving a queue, and a branch manager who must trust the numbers. Each app speaks to its user: icons and voice for collectors, speed for dealers, evidence for Satin.

## Design principles

1. **Pictures before words.** Every collector action works from an icon and a voice prompt; text is a bonus, not a requirement.
2. **The scale is the hero.** The weight reading is the largest thing on the dealer's screen, because it is the proof.
3. **Money feels real.** Show rupees and kilos together, every time: "₹340 · 28 kg plastic".
4. **Two taps for a dealer.** Accept and approve must fit inside a busy queue; anything slower gets skipped.
5. **Show the why.** Every score and every fraud flag on Satin's dashboard comes with its reason in one line.
6. **Dignity, not charity.** Collectors are workers building a record, not beneficiaries; no pity imagery.

## Visual identity

The look borrows from the scrap yard itself: kraft paper, sorted bales, a marigold tag. It should feel like a ledger with warmth, not a fintech clone.

| Token | Value | Used for |
| --- | --- | --- |
| Leaf green | `#1E7F4F` | Primary actions, verified states, brand |
| Kraft | `#EFE6D2` | App backgrounds, cards on the collector app |
| Ink | `#1C2B22` | Text |
| Marigold | `#F2A900` | Money and credits, the "₹ received" moment |
| Brick | `#C2410C` | Fraud flags and errors only |
| Slate | `#5B6B63` | Secondary text, borders |

**Type.** Headings in Bricolage Grotesque for character; body in Noto Sans, which also covers Devanagari and Tamil, so local-language screens keep the same look.

**Logo idea.** A rupee symbol whose stroke is a recycling loop, set inside a tag shape like the tags on scrap bales.

**Voice.** Short, warm, specific. "₹340 received for 28 kg plastic" — never "Transaction successful."

## Key screens

Three screens carry the whole story; each gives one user the one thing they need to see.

&#91;embedded content: hero screens · collector credits, dealer weigh, Satin profile\]

Demo data is consistent across screens: 27.4 kg at ₹12.4/kg pays ₹340, and the five inputs produce a score of 642 under the v1 formula in the Tech Spec. Colours here are placeholders; the real palette is in Visual identity.

## Screen inventory

Fifteen screens in total; the starred ones appear in the demo video.

| App | Screen | What it shows |
| --- | --- | --- |
| Collector | QR card ★ | Photo, name, QR, group name; works printed too |
| Collector | New sale ★ | Six material icons, weight slider, camera button |
| Collector | Waiting | "Show your QR to the dealer" with a 15-min timer |
| Collector | Credits received ★ | Big ₹ amount, kg, material, play-voice button |
| Collector | My score | Score meter, "loan unlocks in N sales" progress |
| Dealer | Request queue ★ | Open requests nearby, scan QR button |
| Dealer | Weigh ★ | Live scale reading huge, estimate small, gap warning |
| Dealer | Approve and pay ★ | Amount = kg × rate, one UPI button |
| Dealer | Daily log | Today's kilos bought by material, total paid |
| Dealer | Sell to recycler | Bulk batch entry with invoice photo |
| Satin | Overview ★ | Active collectors, tonnes this month, loans, open flags |
| Satin | Collector profile ★ | Score with its five inputs, sales history, eligibility |
| Satin | Fraud flags ★ | Each flag, its rule, the evidence, confirm/dismiss |
| Satin | Group view | Members, group guarantee, repayment |
| Satin | Impact | Kilos by material, estimated CO₂e saved (PET only) |

## Designing for low literacy and basic phones

A collector must be able to use WorthyWaste without reading a single word.

- **Icons with real photos** of each material (bottle, carton, can, newspaper, wire, glass), not abstract symbols.
- **Voice on every screen:** a speaker button plays the screen's instruction in the chosen language.
- **Colour carries meaning once:** green means done, marigold means money, brick means stop. Never used decoratively.
- **Big targets:** buttons at least 56 px tall; one primary action per screen.
- **No-smartphone path:** a printed QR card, IVR confirmation ("press 1 to confirm ₹340 for 28 kg"), and a missed-call balance check.
- **Language first:** language picked on the first screen by tapping a spoken greeting, not a text list.
- **Numbers stay numerals:** ₹ and kg shown in numerals even in local-language screens, as collectors already read them on the scale.

## Demo click path

Two phones and a laptop side by side on screen; the recording runs this exact path every take.

1. **Collector phone:** open QR card → tap *New sale* → pick *Plastic* → slide to 28 kg → take photo → *Send*.
2. **Dealer phone:** request appears → *Scan QR* → green "Location matched".
3. **Dealer phone:** *Weigh* → scale shows 27.4 kg vs estimate 28 kg → within 10%, no warning.
4. **Dealer phone:** *Approve and pay ₹340* → UPI success.
5. **Collector phone:** marigold "₹340 received · 27.4 kg plastic" with voice playing.
6. **Fraud 1:** collector resends the same photo → brick banner "This photo was already used".
7. **Fraud 2, laptop:** Satin *Fraud flags* → "Circular payment: ₹340 returned to dealer within 2 h".
8. **Laptop:** open Meena's profile → score 642, five inputs shown → *Starter loan unlocked*.
