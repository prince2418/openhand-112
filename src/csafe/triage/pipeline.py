"""One call in -> one dispatch-ready record out."""
from __future__ import annotations

from .location import resolve
from .redact import redact
from .repeat import RepeatTracker
from .rules import decide


def triage_call(client, call: dict, tracker: RepeatTracker | None = None) -> dict:
    """call: {"id", "t" (seconds), "transcript", optional "image", "audio", "phone_lat", "phone_lng"}"""
    # personal data (phone, Aadhaar, names, plates) never leaves the server: the model gets a redacted copy
    text, removed = redact(call.get("transcript"))
    x, meta = client.extract(text, image=call.get("image"), audio=call.get("audio"))
    meta = dict(meta, redacted=removed)
    phone = (call["phone_lat"], call["phone_lng"]) if call.get("phone_lat") is not None else None
    place = resolve(x.sector, x.landmark, x.location_text, phone)
    n = 1
    if tracker is not None:
        key = (x.landmark or "").lower() or (f"sector {x.sector}" if x.sector else None)
        n = tracker.add(call.get("id"), call.get("t", 0.0), x.incident_type, place.lat, place.lng, key)
    d = decide(x, repeat_calls=n, location_resolved=place.resolved)
    return {"id": call.get("id"), "extract": x.model_dump(), "location": place.__dict__ | {"resolved": place.resolved},
            "repeat_calls": n, "decision": d.model_dump(), "meta": meta}
