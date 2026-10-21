# Submission video (≤ 5 min)

| Time | Section | On screen | Say |
| --- | --- | --- | --- |
| 0:00–0:20 | Team | Team names on a title card | Who we are, one line each |
| 0:20–0:55 | Problem | Mixed waste at a doorstep; landfill stat; collector app tap "separated" | Segregation is the law, but it is self-reported, and self-reporting gets gamed. Households earn points; collectors are paid per pickup. |
| 0:55–2:45 | Live demo | `/vision` on a phone: **Two heaps** sample → Accepted. **One mixed heap**, marked Separated → "Needs a person": play the reviewer → trace gets the human step. **Blurry** → Retake. Real camera photo. "Delete my data". Then `/ops` → Photo reviews card from a real collector pickup. | Each step is the agent: saw, decided, did. A risky action waits for a person. |
| 2:45–3:45 | Architecture | `docs/ARCHITECTURE.md` diagram; quick look at the CloudWatch dashboard `WorthyWaste-Vision` | Vercel app → Lambda (OpenCV 5: quality gate, CLAHE, YuNet blur, GrabCut + watershed, SLIC, MobileNetV2 + calibrated LR) → S3 + DynamoDB + CloudWatch. |
| 3:45–4:40 | Results | Tables from `TECHNICAL_REPORT.md` §7; two failure images from §8 | 93.4% per photo on 2,513 held-out photos; 87% separated-vs-mixed on 300 held-out scenes; 482 ms p50; ≈ $0.04 per 1,000 photos. Where it fails: touching heaps, colourful recyclables, food in plastic. |
| 4:40–5:00 | Responsible use + close | Privacy bullets | Faces blurred before storage, no original kept, 30-day deletion, never penalises anyone without a person. Next: label real pilot photos. |
