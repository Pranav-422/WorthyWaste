"""Pre-records the collector app's voice prompts so they play even on phones without a Hindi
speech voice. Each clip is keyed by the exact on-screen text; anything not listed here falls back
to the browser's speech engine.

    backend/.venv/Scripts/python scripts/make_audio.py          # only what is missing
    backend/.venv/Scripts/python scripts/make_audio.py --all     # re-record everything

Needs network: uses Microsoft's neural voices via edge-tts. Only these fixed prompts are sent.

By default existing files are left alone. TTS is not reproducible, so re-recording a prompt whose
text has not changed would rewrite hundreds of identical-sounding mp3s and bury the real change in
the diff. A new or edited prompt gets a new filename (the name is a hash of its text), so it is
picked up either way.
"""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import edge_tts

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "audio"
MANIFEST = ROOT / "frontend" / "lib" / "audio-clips.json"

VOICES = {"hi": "hi-IN-SwaraNeural", "en": "en-IN-NeerjaNeural"}

FORCE = "--all" in sys.argv

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

# The photo check disagreed with the material the collector picked (CollectorApp → PhotoWarning).
# One line per material, plus one for the cases with no material to name — a mixed load, nothing
# recyclable, or a photo of a screen. Keys must match mismatchByMaterial in frontend/lib/i18n.ts.
MISMATCH_TAIL_HI = " — सही चुनें या फिर से फ़ोटो लें"
MISMATCH_TAIL_EN = " — pick the right one or take the photo again"
MISMATCH_HEADS = {
    "hi": {
        "plastic": "ये प्लास्टिक बोतल लग रही है",
        "cardboard": "ये गत्ता लग रहा है",
        "metal": "ये डिब्बे या टिन लग रहे हैं",
        "paper": "ये अखबार लग रहा है",
        "wire": "ये तार लग रहा है",
        "glass": "ये कांच लग रहा है",
        None: "फ़ोटो आपके चुने हुए कबाड़ से मेल नहीं खा रही",
    },
    "en": {
        "plastic": "This looks like plastic bottles",
        "cardboard": "This looks like cardboard",
        "metal": "This looks like cans or tin",
        "paper": "This looks like newspaper",
        "wire": "This looks like wire",
        "glass": "This looks like glass",
        None: "This photo does not match the scrap you picked",
    },
}

for _lang, _heads in MISMATCH_HEADS.items():
    _tail = MISMATCH_TAIL_HI if _lang == "hi" else MISMATCH_TAIL_EN
    _spoken_tail = _tail.split("— ")[1]
    if _lang == "en":
        _spoken_tail = _spoken_tail[0].upper() + _spoken_tail[1:]
    for _head in _heads.values():
        # The em dash is a pause, not a word: the spoken form uses a full stop instead.
        CLIPS.append((_lang, _head + _tail, f"{_head}. {_spoken_tail}"))


# Segments for sale confirmations of any amount, joined in the browser (frontend/lib/voiceCompose.ts).
# Keys must match voiceCompose.ts; material labels must match backend/app/db.py MATERIALS.
HI_NUMBERS = (
    "एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
    "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस "
    "छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस "
    "अड़तालीस उनचास पचास इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ "
    "तिरसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर "
    "छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी "
    "नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पंचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
assert len(HI_NUMBERS) == 99
EN_ONES = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
           "sixteen seventeen eighteen nineteen").split()
EN_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()

SEGMENTS = {
    "hi": {
        **{f"n-{i}": w for i, w in enumerate(HI_NUMBERS, start=1)},
        "w-shunya": "शून्य", "w-sau": "सौ", "w-hazaar": "हज़ार", "w-dashamlav": "दशमलव",
        "w-rupaye-mile": "रुपये मिले।", "w-kilo": "किलो", "w-khaate-mein": "आपके खाते में",
        "w-credit-jude": "क्रेडिट जुड़ गए।",
        "m-plastic": "प्लास्टिक बोतल।", "m-cardboard": "गत्ता।", "m-metal": "डिब्बे और टिन।",
        "m-paper": "अखबार।", "m-wire": "तार।", "m-glass": "कांच।",
    },
    "en": {
        **{f"n-{i}": w for i, w in enumerate(EN_ONES, start=1)},
        **{f"n-{(i + 2) * 10}": w for i, w in enumerate(EN_TENS)},
        "w-zero": "zero", "w-hundred": "hundred", "w-thousand": "thousand", "w-point": "point",
        "w-rupees-received": "rupees received for", "w-kilos-of": "kilos of", "w-credits-added": "credits added.",
        "m-plastic": "plastic bottles.", "m-cardboard": "cardboard.", "m-metal": "cans and tin.",
        "m-paper": "newspaper.", "m-wire": "wire.", "m-glass": "glass.",
    },
}


async def make_segments():
    for lang, segs in SEGMENTS.items():
        d = OUT / "seg" / lang
        d.mkdir(parents=True, exist_ok=True)
        made = 0
        for key, text in segs.items():
            path = d / f"{key}.mp3"
            if path.exists() and not FORCE:
                continue
            await edge_tts.Communicate(text, VOICES[lang]).save(str(path))
            made += 1
        print(f"{lang}: {len(segs)} segments, {made} recorded")


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    await make_segments()
    manifest = {}
    for lang, text, spoken in CLIPS:
        name = f"{lang}-{hashlib.sha1(text.encode()).hexdigest()[:10]}.mp3"
        manifest[text] = f"/audio/{name}"
        if (OUT / name).exists() and not FORCE:
            continue
        await edge_tts.Communicate(spoken or text, VOICES[lang], rate="-5%").save(str(OUT / name))
        print(f"{name}  {text}")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
