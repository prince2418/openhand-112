"""Remove personal data from a call before it goes to any AI model (India's Digital Personal Data Protection
Act, 2023: share only what the purpose needs). Triage needs what happened and where, not who called.

Removed: phone numbers, Aadhaar and PAN numbers, email addresses, vehicle registration numbers, bank/card
numbers, and names introduced as "my name is ..." / "mera naam ... hai". The original stays on the local
server for the dispatcher; only the redacted text leaves it.
"""
from __future__ import annotations

import re

_PATTERNS = [
    ("aadhaar", re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    ("card", re.compile(r"(?<!\d)(?:\d[\s-]?){13,19}(?!\d)")),
    ("phone", re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?[6-9](?:[\s-]?\d){9}(?!\d)")),
    ("phone", re.compile(r"(?<!\d)0\d{2,4}[\s-]?\d{6,8}(?!\d)")),     # landlines, e.g. 0172-2740000
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("pan", re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b")),
    # Indian number plates: CH 01 AB 1234, PB65AX1234, HR-03-T-4567
    ("vehicle", re.compile(r"\b[A-Za-z]{2}[\s-]?\d{1,2}[\s-]?[A-Za-z]{0,3}[\s-]?\d{4}\b")),
]
_NAME = re.compile(
    r"(?i)\b(my name is|i am|this is|mera naam|mera nam|main|mai|ਮੇਰਾ ਨਾਮ|मेरा नाम)\s+"
    r"([A-Zऀ-ॿ਀-੿][\wऀ-ॿ਀-੿]+(?:\s+[A-Z][\w]+)?)"
    r"(?=\s+(?:hai|hoon|hun|ਹੈ|है|हूँ|हूं|bol raha|bol rahi|speaking)|[,.]|$)")


def redact(text: str | None) -> tuple[str | None, list[str]]:
    """(redacted text, kinds of data removed)."""
    if not text:
        return text, []
    found: list[str] = []
    out = text
    for kind, pat in _PATTERNS:
        out, n = pat.subn(f"[{kind} removed]", out)
        if n:
            found.append(kind)
    out, n = _NAME.subn(lambda m: f"{m.group(1)} [name removed]", out)
    if n:
        found.append("name")
    return out, found
