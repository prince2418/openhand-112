"""Fast path for sexual violence, harassment and other violence against women: police are sent the moment
the words are heard, without waiting for Gemini. Gemini still reads the call in the background.

Matching is deliberately broad: a false alarm costs one PCR trip; a delay can cost far more.
Roman-script (Hinglish / Punjabi in English letters) words are matched after normalising spelling, so
"balatkaar", "balaatkar" and "blatkar" all match "balatkar". Indic scripts are matched with nuktas removed.
Languages: English, Hindi, Punjabi (both scripts), Urdu, and the main Indian languages heard in the city.
"""
from __future__ import annotations

import re
import unicodedata

# ---- words that on their own mean sexual violence, harassment or violence against a woman ----
DIRECT_ROMAN = [
    # English
    "rape", "raped", "raping", "rapist", "gang rape", "gangrape", "sexual assault", "sexually assault", "sexual abuse",
    "sexually abuse", "sexual harass", "sexually harass", "molest", "harass", "eve teas", "eve-teas", "stalk", "grope",
    "groping", "indecent exposure", "flashing", "bad touch", "touched her", "touching her", "forced herself", "forced her",
    "acid attack", "acid thrown", "threw acid", "honour killing", "dowry",
    # Hinglish / Hindi in English letters
    "balatkar", "blatkar", "baltkar", "balatkari", "dushkarm", "dushkaram", "jyadti", "jiyadti", "zyadti", "zyaadti",
    "izzat lut", "izzat loot", "ijjat lut", "izzat pe hath", "izzat se khel", "galat kam", "galat harkat", "gandi harkat",
    "gande ishare", "ganda ishara", "ashlil", "ashleel", "yaun shoshan", "yon shoshan", "yaun utpidan", "sharirik shoshan",
    "chhed", "ched kar", "chhedkhani", "chedkhani", "chhedchhad", "chedchad", "chhed chhad", "chhedna", "chhed rahe",
    "chhed raha", "chheda", "kapde phad", "kapde fad", "kapde utar", "kapre phad", "nanga kar", "nangi", "jabardasti kiya",
    "zabardasti kiya", "jabardasti ki", "zabardasti ki", "jabardasti sambandh", "tezab", "tejab", "dahej",
    # Punjabi in English letters
    "jabar janah", "jabar-janah", "chherkhani", "chherchhar", "chhed chhaad", "kudi nu chhed", "izzat luti",
    # Urdu in English letters
    "zina bil jabr", "zina", "jinsi", "jinsi tashaddud", "hiraasa",
]
DIRECT_INDIC = [
    # Hindi (Devanagari)
    "बलात्कार", "दुष्कर्म", "रेप", "गैंगरेप", "गैंग रेप", "ज्यादती", "ज़्यादती", "यौन शोषण", "यौन उत्पीड़न", "यौन हिंसा",
    "शारीरिक शोषण", "छेड़छाड़", "छेड़खानी", "छेड़", "छेड़ा", "अश्लील", "इज्जत लूट", "इज़्ज़त लूट", "इज्जत पर हाथ", "गलत काम",
    "गलत हरकत", "गंदी हरकत", "गंदे इशारे", "कपड़े फाड़", "नंगा", "जबरदस्ती की", "ज़बरदस्ती की", "तेजाब", "तेज़ाब",
    "एसिड", "दहेज", "पीछा कर",
    # Punjabi (Gurmukhi)
    "ਬਲਾਤਕਾਰ", "ਜਬਰ ਜਨਾਹ", "ਜਬਰ-ਜਨਾਹ", "ਜਬਰਜਨਾਹ", "ਰੇਪ", "ਛੇੜਛਾੜ", "ਛੇੜਖਾਨੀ", "ਛੇੜ", "ਜਿਨਸੀ ਸ਼ੋਸ਼ਣ", "ਜਿਨਸੀ",
    "ਗਲਤ ਹਰਕਤ", "ਗੰਦੀ ਹਰਕਤ", "ਇੱਜ਼ਤ ਲੁੱਟ", "ਇੱਜਤ ਲੁੱਟ", "ਤੇਜ਼ਾਬ", "ਤੇਜਾਬ", "ਦਾਜ", "ਪਿੱਛਾ ਕਰ",
    # Urdu
    "زیادتی", "زنا بالجبر", "عصمت دری", "جنسی", "ہراساں", "چھیڑ", "تیزاب",
    # other Indian languages heard in the city
    "ধর্ষণ", "শ্লীলতাহানি", "যৌন",                 # Bengali
    "बलात्कार", "विनयभंग",                         # Marathi (Devanagari)
    "બળાત્કાર", "છેડતી",                           # Gujarati
    "ଧର୍ଷଣ",                                       # Odia
    "பாலியல்", "வன்கொடுமை", "கற்பழிப்பு",           # Tamil
    "అత్యాచారం", "లైంగిక",                          # Telugu
    "ಅತ್ಯಾಚಾರ", "ಲೈಂಗಿಕ",                            # Kannada
    "ബലാത്സംഗം", "പീഡന", "ലൈംഗിക",                  # Malayalam
]
# ---- a woman or girl named together with a threat also counts ----
FEMALE_ROMAN = ["ladki", "ladkiyan", "ladkiyon", "larki", "aurat", "auraton", "mahila", "girl", "woman", "women", "lady",
                "ladies", "bachi", "bacchi", "beti", "behen", "bahen", "didi", "biwi", "wife", "patni", "kudi", "kuri",
                "kudiyan", "zanana", "khatoon", "she", "her"]
FEMALE_INDIC = ["लड़की", "लडकी", "लड़कियों", "लड़कियां", "औरत", "महिला", "बच्ची", "बेटी", "बहन", "दीदी", "बीवी", "पत्नी",
                "ਕੁੜੀ", "ਕੁੜੀਆਂ", "ਔਰਤ", "ਮਹਿਲਾ", "ਬੱਚੀ", "ਧੀ", "ਭੈਣ", "ਪਤਨੀ", "لڑکی", "عورت", "خاتون"]
THREAT_ROMAN = ["picha", "pichha", "peecha", "following", "follow kar", "followed", "uthake", "utha ke", "utha liya",
                "utha le", "kidnap", "abduct", "agwa", "khinch", "kheench", "jabardasti", "zabardasti", "touch", "pakad",
                "pakda", "pakdi", "grab", "ghur", "kapde", "nanga", "car mein dal", "gadi mein dal", "gaddi vich",
                "van mein", "tang kar", "pareshan kar", "pareshaan kar", "bura bartav", "chu raha", "chhu raha", "chhua",
                "maar raha", "mar raha", "peet raha", "pit raha", "kutt", "jala", "jalaya", "bandh ke", "band kar ke",
                "chuk ke", "chukk", "le gaye", "le gya", "le gaya", "akeli", "sunsan"]
THREAT_INDIC = ["पीछा", "उठा", "अगवा", "अपहरण", "खींच", "ज़बरदस्ती", "जबरदस्ती", "छू", "पकड़", "कपड़े", "मार रहा", "पीट",
                "जला", "बंद कर", "ले गए", "परेशान", "ਪਿੱਛਾ", "ਚੁੱਕ", "ਅਗਵਾ", "ਖਿੱਚ", "ਜ਼ਬਰਦਸਤੀ", "ਜਬਰਦਸਤੀ", "ਫੜ",
                "ਕੁੱਟ", "ਮਾਰ ਰਿਹਾ", "ਲੈ ਗਏ", "ਤੰਗ"]

DIRECT = DIRECT_ROMAN + DIRECT_INDIC
FEMALE = FEMALE_ROMAN + FEMALE_INDIC
THREAT = THREAT_ROMAN + THREAT_INDIC


def norm(text: str) -> str:
    """Spelling-tolerant form. Roman: lower case, aa/ee/oo -> a/i/u, doubled letters collapsed, w->v, z->j,
    q->k, ph->f, ou->au. Indic: nuktas removed (ज़ -> ज, ਜ਼ -> ਜ)."""
    t = unicodedata.normalize("NFC", text.lower())
    t = t.replace("़", "").replace("਼", "")          # Devanagari and Gurmukhi nukta
    t = t.replace("ee", "i").replace("oo", "u").replace("ou", "au").replace("ph", "f")
    t = t.replace("w", "v").replace("z", "j").replace("q", "k")
    t = re.sub(r"([a-z])\1+", r"\1", t)                        # aa -> a, chh -> ch? no: only identical letters
    t = re.sub(r"[^\w\sऀ-෿؀-ۿ-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _has(t: str, w: str) -> bool:
    w = norm(w)
    if not w:
        return False
    return re.search(rf"(?<![a-z]){re.escape(w)}", t) is not None if w.isascii() else w in t


def sexual_violence_alert(text: str | None) -> str | None:
    """The words that triggered the alert, or None."""
    if not text:
        return None
    t = norm(text)
    for w in DIRECT:
        if _has(t, w):
            return w
    f = next((w for w in FEMALE if _has(t, w) and len(norm(w)) > 3), None)   # "she"/"her" alone are too weak
    th = next((w for w in THREAT if _has(t, w)), None)
    if th and not f:
        f = next((w for w in ("she", "her") if re.search(rf"\b{w}\b", t)), None)
    return f"{f} + {th}" if f and th else None
