"""Pre-records the collector app's voice prompts so they play even on phones without a Hindi
speech voice. Each clip is keyed by the exact on-screen text; anything not listed here falls back
to the browser's speech engine.

    backend/.venv/Scripts/python scripts/make_audio.py

Needs network: uses Microsoft's neural voices via edge-tts. Only these fixed prompts are sent.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "audio"
MANIFEST = ROOT / "frontend" / "lib" / "audio-clips.json"

VOICES = {"hi": "hi-IN-SwaraNeural", "en": "en-IN-NeerjaNeural"}

# (lang, text as the app passes it to speak(), text as it should be spoken)
CLIPS = [
    # Screen instructions (lib/i18n.ts → voice)
    ("hi", "नई बिक्री के लिए हरा बटन दबाएँ।", None),
    ("en", "Press the green button to make a new sale.", None),
    ("hi", "कबाड़ चुनें, वज़न खिसकाएँ, फिर फ़ोटो लेकर भेजें।", None),
    ("en", "Pick the scrap, slide to the weight, take a photo and send.", None),
    ("hi", "डीलर को अपना QR कार्ड दिखाएँ।", "डीलर को अपना क्यू आर कार्ड दिखाएँ।"),
    ("en", "Show your QR card to the dealer.", None),
    # Duplicate photo (CollectorApp → NewSale)
    ("hi", "यह फ़ोटो पहले इस्तेमाल हो चुकी है। अभी के कबाड़ की नई फ़ोटो लें।", None),
    ("en", "This photo was already used. Take a fresh photo of today's scrap.", None),
    # Scripted demo confirmation (backend services.confirmation_text for ₹340 · 27.4 kg plastic)
    ("hi", "₹340 मिले — 27.4 किलो प्लास्टिक बोतल। आपके खाते में 27 क्रेडिट जुड़ गए।",
     "तीन सौ चालीस रुपये मिले। सत्ताईस दशमलव चार किलो प्लास्टिक बोतल। आपके खाते में सत्ताईस क्रेडिट जुड़ गए।"),
    ("en", "₹340 received for 27.4 kg plastic bottles. 27 credits added.",
     "Three hundred and forty rupees received for twenty-seven point four kilos of plastic bottles. "
     "Twenty-seven credits added."),
]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for lang, text, spoken in CLIPS:
        name = f"{lang}-{hashlib.sha1(text.encode()).hexdigest()[:10]}.mp3"
        await edge_tts.Communicate(spoken or text, VOICES[lang], rate="-5%").save(str(OUT / name))
        manifest[text] = f"/audio/{name}"
        print(f"{name}  {text}")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
