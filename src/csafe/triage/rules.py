"""Deterministic, auditable rules: facts -> priority and units.

P1 life threat now | P2 urgent, harm likely | P3 needs a response, no immediate danger | P4 not an emergency.
Every rule that fires is recorded in `reasons`, so a dispatcher (or auditor) can see why.
"""
from __future__ import annotations

from .schema import Decision, Extract

REVIEW_CONFIDENCE = 0.6
REPEAT_ESCALATE_AT = 3  # this many calls about the same incident raise priority one level (Itaewon lesson)
_ORDER = ["P1", "P2", "P3", "P4"]
# A reported sexual assault is P1 even when the attacker has gone: the victim needs medical care and evidence
# preserved now, and the attacker may still be nearby. Read from the model's English summary (deterministic match).
SEXUAL_ASSAULT = ("rape", "raped", "sexual assault", "sexually assaulted", "sexual abuse", "molest", "gang rape",
                  "sexual violence", "harass", "eve teas", "stalk", "grop", "acid attack", "acid thrown")


def sexual_assault(x: Extract) -> bool:
    s = f" {x.summary_en or ''} {' '.join(x.vulnerable)} ".lower()
    return x.incident_type in ("crime_violent", "other_emergency") and any(k in s for k in SEXUAL_ASSAULT)


def priority_of(x: Extract) -> tuple[str, list[str]]:
    p1 = []
    if x.unconscious_or_not_breathing:
        p1.append("someone unconscious or not breathing")
    if x.immediate_life_threat:
        p1.append("life-threatening condition described")
    if x.people_trapped:
        p1.append("people trapped")
    if x.violence_ongoing:
        p1.append("violence happening now")
    if sexual_assault(x):
        p1.append("sexual assault reported: the victim needs police and medical care now")
    if (x.people_injured or 0) >= 3:
        p1.append("3+ injured")
    if {"gas", "chemical", "structure_collapse"} & set(x.hazards):
        p1.append("dangerous hazard: " + ", ".join(sorted({"gas", "chemical", "structure_collapse"} & set(x.hazards))))
    if x.incident_type == "crowd" and (x.people_injured or 0) >= 1:
        p1.append("injuries in a crowd")
    if p1:
        return "P1", p1
    if x.incident_type == "non_emergency":
        return "P4", ["not an emergency"]
    p2 = []
    if (x.people_injured or 0) >= 1:
        p2.append("injured person")
    if x.fire_or_smoke or x.incident_type == "fire":
        p2.append("fire or smoke")
    if x.incident_type == "road_accident" and x.people_injured != 0:
        p2.append("road accident, injuries not ruled out")
    if x.incident_type in ("medical", "crime_violent", "crowd"):
        p2.append(f"{x.incident_type.replace('_', ' ')}")
    if {"electric", "vehicle_fuel", "water_rising"} & set(x.hazards):
        p2.append("hazard: " + ", ".join(sorted({"electric", "vehicle_fuel", "water_rising"} & set(x.hazards))))
    if x.vulnerable:
        p2.append("vulnerable person: " + ", ".join(x.vulnerable))
    if p2:
        return "P2", p2
    return "P3", [f"{x.incident_type.replace('_', ' ')}, no immediate danger stated"]


def units_of(x: Extract) -> list[str]:
    types = {x.incident_type, *x.secondary_types}
    u = set()
    if types & {"road_accident", "crime_violent", "crime_property", "crowd"} or x.violence_ongoing:
        u.add("police")
    if (x.people_injured or 0) > 0 or x.unconscious_or_not_breathing or x.immediate_life_threat or "medical" in types \
            or sexual_assault(x) \
            or (x.people_trapped and types & {"road_accident", "fire", "crowd"}):
        u.add("ambulance")
    if x.fire_or_smoke or "fire" in types or set(x.hazards) & {"gas", "chemical", "structure_collapse", "vehicle_fuel"} \
            or (x.people_trapped and types & {"road_accident", "waterlogging", "fire", "other_emergency"}):
        u.add("fire")  # fire service also does rescue (cutting, water, collapse)
    if types & {"waterlogging", "other_emergency"}:
        u.add("police")  # traffic diversion / cordon; the municipal team is notified separately
    if "fire" in u and "police" not in u and types & {"fire", "road_accident"}:
        u.add("police")  # crowd and traffic control at fires
    if x.incident_type == "non_emergency" and not (x.people_injured or x.people_trapped or x.fire_or_smoke):
        u = set()
    return sorted(u)


def decide(x: Extract, repeat_calls: int = 1, location_resolved: bool = True) -> Decision:
    pri, reasons = priority_of(x)
    if repeat_calls >= REPEAT_ESCALATE_AT and pri != "P1":
        pri = _ORDER[_ORDER.index(pri) - 1]
        reasons = reasons + [f"{repeat_calls} calls about the same place: raised one level"]
    review = []
    if x.confidence < REVIEW_CONFIDENCE:
        review.append(f"low model confidence ({x.confidence:.2f})")
    if not location_resolved and x.incident_type != "non_emergency":
        review.append("location not resolved: confirm with caller or phone location")
    if x.incident_type == "other_emergency":
        review.append("incident type unclear")
    if x.incident_type == "non_emergency" and (x.people_injured or x.people_trapped or x.fire_or_smoke
                                               or x.violence_ongoing or x.immediate_life_threat):
        review.append("marked non-emergency but danger facts present")
    return Decision(priority=pri, units=units_of(x), reasons=reasons, needs_human_review=bool(review), review_reasons=review)
