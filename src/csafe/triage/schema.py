"""What Gemini must return for every call. Facts only: no priority, no diagnosis."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

IncidentType = Literal[
    "road_accident", "fire", "medical", "crime_violent", "crime_property",
    "crowd", "waterlogging", "other_emergency", "non_emergency",
]
Hazard = Literal["gas", "electric", "chemical", "vehicle_fuel", "water_rising", "structure_collapse"]
Vulnerable = Literal["child", "elderly", "pregnant", "disabled"]
Language = Literal["hindi", "punjabi", "english", "mixed", "other"]
Unit = Literal["police", "ambulance", "fire"]


class Extract(BaseModel):
    """Facts stated in the call. Unknown -> null/false/empty; never guessed."""
    incident_type: IncidentType = Field(description="main incident")
    secondary_types: list[IncidentType] = Field(default_factory=list, description="other incidents in the same call")
    location_text: Optional[str] = Field(None, description="location as the caller described it, in English")
    sector: Optional[int] = Field(None, description="Chandigarh sector number if the caller said one, else null")
    landmark: Optional[str] = Field(None, description="named landmark, e.g. 'Tribune Chowk', 'PGI', else null")
    people_injured: Optional[int] = Field(None, description="number of injured people if stated or clearly implied")
    unconscious_or_not_breathing: bool = Field(False, description="anyone unconscious, not breathing or unresponsive")
    immediate_life_threat: bool = Field(False, description="caller describes a condition that can kill within minutes: cardiac arrest, choking, severe bleeding, poisoning or overdose, drowning, electrocution, severe burns, attempted suicide")
    people_trapped: bool = Field(False, description="anyone trapped in a vehicle, building, lift or water")
    violence_ongoing: bool = Field(False, description="assault, weapon or threat happening now")
    fire_or_smoke: bool = Field(False, description="flames or smoke reported")
    hazards: list[Hazard] = Field(default_factory=list)
    vulnerable: list[Vulnerable] = Field(default_factory=list)
    caller_language: Language = "other"
    summary_en: str = Field(description="one plain English sentence a dispatcher can read in 3 seconds")
    missing_info: list[str] = Field(default_factory=list, description="the most important facts the dispatcher should still ask")
    confidence: float = Field(0.5, ge=0, le=1, description="how sure you are of incident_type and location")


class Decision(BaseModel):
    """What the rules decide from an Extract (plus repeat-call context)."""
    priority: Literal["P1", "P2", "P3", "P4"]
    units: list[Unit]
    reasons: list[str]
    needs_human_review: bool
    review_reasons: list[str] = Field(default_factory=list)


class CCTVCheck(BaseModel):
    """What a CCTV frame shows, checked against the call. Facts visible in the image only; never guessed."""
    shows_incident: Literal["yes", "no", "unclear"] = Field(description="does the frame show the incident described in the report?")
    seen_type: IncidentType = Field(description="what kind of incident the frame shows (non_emergency if nothing is happening)")
    what_is_seen: str = Field(description="one or two plain English sentences on what is visible")
    people_visible: Optional[int] = Field(None, description="approximate number of people visible")
    injured_visible: bool = Field(False, description="someone visibly injured, lying on the road or not moving")
    fire_or_smoke: bool = Field(False, description="flames or smoke visible")
    weapon_visible: bool = Field(False, description="knife, gun, rod or other weapon visible")
    violence_visible: bool = Field(False, description="fighting, assault or someone being dragged visible")
    crowd_building: bool = Field(False, description="a large or growing crowd, crush risk")
    vehicles_involved: Optional[int] = Field(None, description="number of vehicles involved in a crash, if any")
    road_blocked: bool = Field(False, description="the carriageway is blocked")
    hazards: list[Hazard] = Field(default_factory=list, description="visible hazards")
    looks_stale_or_unrelated: bool = Field(False, description="the image looks old, staged, a screenshot of something else, or not a street camera")
    confidence: float = Field(description="0-1, how sure you are about what the frame shows")


class Advisory(BaseModel):
    """Public traffic advisory for waterlogging, written from the plan's facts only."""
    english: str = Field(description="Advisory in plain English, at most 70 words")
    hindi: str = Field(description="The same advisory in Hindi (Devanagari), at most 70 words")
    punjabi: str = Field(description="The same advisory in Punjabi (Gurmukhi), at most 70 words")
    sms: str = Field(description="English SMS, at most 160 characters")
