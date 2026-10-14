"""Keyword fallback: reads a call when Gemini can't, and the baseline Gemini must beat.
Keywords cover English, Hindi (Devanagari and Roman) and Punjabi (Gurmukhi and Roman).

It is built to FAIL SAFE: a 112 fallback must never call a real emergency "not an emergency".
  - "not an emergency" only when the caller says so plainly (a bill, a complaint, an enquiry) AND no danger word appears;
  - a call it can't classify becomes "unclear emergency": police sent, low confidence, so a dispatcher must check it;
  - a service the caller asks for by name (ambulance, police, fire brigade) is always sent;
  - words for killing, death or shooting mean a threat to life (P1)."""
from __future__ import annotations

import re

from .fastpath import sexual_violence_alert
from .schema import Extract

KW = {
    "fire": ["fire", "smoke", "burning", "aag", "aagg", "dhuan", "dhuaan", "आग", "धुआं", "धुआँ", "जल रह", "ਅੱਗ", "ਧੂੰਆਂ", "ਧੂੰਆ", "agg", "dhuan"],
    "road_accident": ["accident", "collision", "crash", "hit by", "takkar", "ठोक", "टक्कर", "एक्सीडेंट", "ਹਾਦਸਾ", "ਟੱਕਰ", "ਐਕਸੀਡੈਂਟ", "hadsa", "bike", "truck"],
    "medical": ["heart", "chest pain", "breathing", "delivery", "labour", "seizure", "fits", "dil", "दिल", "सांस", "बेहोश", "ਦਿਲ", "ਸਾਹ", "ਬੇਹੋਸ਼", "behosh", "saans", "pregnant", "dard"],
    "crime_violent": ["fight", "beating", "beaten", "knife", "gun", "shot", "shooting", "assault", "attack", "murder", "kill", "stabbed",
                      "maar", "mar diya", "maar diya", "mara", "maara", "maari", "pita", "peet", "kutt", "kuttya", "chaku", "chhura", "goli",
                      "firing", "katl", "qatl", "jhagda", "jhagra", "ladai", "danga", "लड़ाई", "मार", "पीट", "चाकू", "गोली", "हत्या", "कत्ल",
                      "झगड़ा", "ਲੜਾਈ", "ਕੁੱਟ", "ਮਾਰ", "ਚਾਕੂ", "ਗੋਲੀ", "ਕਤਲ", "harass", "chhed",
                      "rape", "raped", "balatkar", "molest", "sexual", "बलात्कार", "छेड़", "ਬਲਾਤਕਾਰ", "ਛੇੜ"],
    "crime_property": ["theft", "stolen", "snatch", "robbery", "burglar", "chori", "chor", "chain", "चोरी", "चोर", "छीन", "ਚੋਰੀ", "ਚੋਰ", "ਖੋਹ"],
    "crowd": ["crowd", "stampede", "crush", "bheed", "bhid", "भीड़", "भगदड़", "ਭੀੜ", "ਭਗਦੜ", "dhakka"],
    "waterlogging": ["water", "flood", "paani", "pani", "पानी", "बाढ़", "ਪਾਣੀ", "ਹੜ੍ਹ", "underpass", "drain", "nala"],
}
# death or killing: always a threat to life
DEATH = ["dead", "died", "dying", "killed", "murder", "shot", "mar gaya", "mar gayi", "mar gaye", "mar diya", "maar diya", "maar dala",
         "maar daala", "maut", "lash", "laash", "jaan", "मर गया", "मर गई", "मार दिया", "मार डाला", "मौत", "लाश", "हत्या", "ਮਰ ਗਿਆ",
         "ਮਾਰ ਦਿੱਤਾ", "ਮੌਤ", "ਲਾਸ਼", "ਕਤਲ", "goli", "गोली", "ਗੋਲੀ"]
# the caller asks for a service by name: send it
ASK = {
    "ambulance": ["ambulance", "ambulence", "108", "doctor", "hospital", "एम्बुलेंस", "एंबुलेंस", "ਐਂਬੂਲੈਂਸ", "ਐਂਬੂਲੈਂਸ"],
    "police": ["police", "pulis", "polis", "100", "पुलिस", "ਪੁਲਿਸ", "ਪੁਲੀਸ"],
    "fire": ["fire brigade", "fire engine", "damkal", "दमकल", "फायर ब्रिगेड", "ਫਾਇਰ ਬ੍ਰਿਗੇਡ"],
}
# only these make a call "not an emergency", and only if no danger word appears
NON_EMERGENCY = ["bill", "complaint", "shikayat", "enquiry", "inquiry", "information", "jaankari", "number chahiye", "timing",
                 "certificate", "passport", "verification", "wrong number", "galti se", "prank", "mazaak", "बिल", "शिकायत",
                 "जानकारी", "ਬਿੱਲ", "ਸ਼ਿਕਾਇਤ", "ਜਾਣਕਾਰੀ"]
URGENT = ["help", "bachao", "bachaao", "jaldi", "emergency", "urgent", "please come", "बचाओ", "जल्दी", "ਬਚਾਓ", "ਜਲਦੀ"]
UNCONSCIOUS = ["unconscious", "not breathing", "not responding", "not moving", "hilda nahi", "hil nahi raha", "behosh", "saans nahi", "बेहोश", "सांस नहीं", "ਬੇਹੋਸ਼", "ਸਾਹ ਨਹੀਂ", "hil nahi", "हिल नहीं"]
TRAPPED = ["trapped", "stuck", "fasa", "fase", "fasi", "phasa", "phase hue", "phasi", "phassya", "fasya", "फंस", "फँस", "ਫਸ", "andar reh", "can't get out", "lift"]
INJURED = ["injured", "blood", "bleeding", "hurt", "khoon", "chot", "zakhmi", "घायल", "खून", "चोट", "ਜ਼ਖਮੀ", "ਖੂਨ", "ਸੱਟ", "ghayal"]
NUM = r"(?:sector|sec|सेक्टर|ਸੈਕਟਰ)\s*-?\s*(\d{1,2})"


def _has(t: str, w: str) -> bool:
    """Roman-script keywords match whole words only ("aag" must not match "bhaag"); Indic scripts by substring."""
    return re.search(rf"\b{re.escape(w)}", t) is not None if w.isascii() else w in t


def keyword_extract(text: str) -> Extract:
    t = text.lower()
    has = lambda ws: any(_has(t, w) for w in ws)  # noqa: E731
    scores = {k: sum(_has(t, w) for w in ws) for k, ws in KW.items()}
    asked = [k for k, ws in ASK.items() if has(ws)]
    death = has(DEATH)
    if death:
        scores["crime_violent"] += 1
    if sexual_violence_alert(text):
        scores["crime_violent"] += 2
    best = max(scores, key=scores.get)
    danger = scores[best] > 0 or death or bool(asked) or has(INJURED + UNCONSCIOUS + TRAPPED)
    if scores[best] > 0:
        itype = best
    elif has(INJURED + UNCONSCIOUS):
        itype = "medical"           # someone hurt or collapsed, nothing else said: treat as medical
    elif has(NON_EMERGENCY) and not danger:
        itype = "non_emergency"
    else:
        itype = "other_emergency"   # can't tell what it is: treat it as an emergency and make a dispatcher check
    second = []
    if itype == "medical" and scores["medical"] == 0:
        second.append("other_emergency")   # inferred only from "bleeding"/"unconscious": send police too, to be safe
    if "ambulance" in asked and itype != "medical":
        second.append("medical")
    if "fire" in asked and itype != "fire":
        second.append("fire")
    if "police" in asked and itype not in ("crime_violent", "crime_property", "road_accident", "crowd"):
        second.append("other_emergency")
    m = re.search(NUM, t)
    n = re.search(r"(\d+|ek|do|teen|char|dono)\s*(?:log|logo|logon|people|persons|aadmi|admi|bande|jane|ਲੋਕ|लोग|लोगों)", t)
    words = {"ek": 1, "do": 2, "dono": 2, "teen": 3, "char": 4}
    count = (int(n.group(1)) if n.group(1).isdigit() else words.get(n.group(1))) if n else None
    hurt = has(INJURED) or death or itype == "crime_violent"
    injured = (count or 1) if hurt else None
    conf = 0.9 if scores[best] > 1 else 0.6 if scores[best] else 0.5 if itype == "non_emergency" else 0.3
    return Extract(
        incident_type=itype, secondary_types=second, sector=int(m.group(1)) if m else None,
        location_text=text,  # the location resolver scans it for known landmarks
        people_injured=injured, unconscious_or_not_breathing=has(UNCONSCIOUS),
        immediate_life_threat=death, people_trapped=has(TRAPPED), fire_or_smoke=scores["fire"] > 0,
        violence_ongoing=scores["crime_violent"] > 0 and not has(["kal", "yesterday", "pichle", "last week"]),
        summary_en=f"keyword reading: {itype.replace('_', ' ')}" + (f", caller asks for {', '.join(asked)}" if asked else "")
                   + (f", sexual violence or harassment reported ({sv})" if (sv := sexual_violence_alert(text)) else "")
                   + (", urgent" if has(URGENT) else ""),
        confidence=min(conf, 0.55) if itype == "other_emergency" else conf,
    )
