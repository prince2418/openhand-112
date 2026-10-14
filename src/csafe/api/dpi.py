"""Digital public infrastructure: OpenHand as a building block that other city systems plug into.

  Outbox     : every message the system would send to (or receive from) another agency, with the standard
               it uses and the exact payload. In this prototype nothing leaves the computer: each message is
               marked SIMULATED, but the payloads are what a live link would carry.
  CAP        : public alerts as OASIS Common Alerting Protocol 1.2 XML, the format NDMA's SACHET gateway
               (C-DOT) uses for SMS and cell-broadcast alerts. status=Exercise, so no gateway treats it as real.
  Open data  : anonymised incident records (no caller words, place rounded to a ~550 m grid, time to the hour)
               as GeoJSON and CSV, the kind of file data.gov.in publishes.
  Catalogue  : each interface, who owns the other side, the format, our endpoint, and what is real vs simulated.
"""
from __future__ import annotations

import csv
import io
import itertools
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

IST = timezone(timedelta(hours=5, minutes=30))
SENDER = "openhand112@chandigarh.example"
GRID = 0.005          # degrees: ~550 m north-south, ~480 m east-west at Chandigarh


def _now_iso() -> str:
    return datetime.now(IST).replace(microsecond=0).isoformat()


class Outbox:
    def __init__(self, cap: int = 300):
        self.items: list[dict] = []
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.cap = cap

    def send(self, direction: str, party: str, what: str, standard: str, summary: str, payload, fmt: str = "json") -> dict:
        with self._lock:
            m = dict(id=f"MSG-{next(self._ids):05d}", at=_now_iso(), wall=time.time(), direction=direction, party=party, what=what,
                     standard=standard, summary=summary, format=fmt, simulated=True,
                     payload=payload if fmt != "json" else json.loads(json.dumps(payload, default=str)))
            self.items.append(m)
            del self.items[:-self.cap]
            return m

    def list(self, since: int = 0, limit: int = 60) -> list[dict]:
        with self._lock:
            out = [m for m in self.items if int(m["id"][4:]) > since]
            return out[-limit:][::-1]

    def clear(self):
        with self._lock:
            self.items.clear()


# ---------- CAP 1.2 ----------
CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"


def cap_alert(identifier: str, event: str, headline: dict, description: dict, instruction: dict, areas: list[dict],
              category: str = "Transport", urgency: str = "Immediate", severity: str = "Moderate", certainty: str = "Observed",
              expires_h: float = 3.0, status: str = "Exercise", references: str | None = None) -> str:
    """One CAP 1.2 alert with an <info> block per language. areas: [{desc, lat, lng, radius_km}]."""
    ET.register_namespace("", CAP_NS)
    q = lambda t: f"{{{CAP_NS}}}{t}"  # noqa: E731
    a = ET.Element(q("alert"))
    sent = datetime.now(IST).replace(microsecond=0)
    for tag, val in (("identifier", identifier), ("sender", SENDER), ("sent", sent.isoformat()), ("status", status),
                     ("msgType", "Update" if references else "Alert"), ("scope", "Public")):
        ET.SubElement(a, q(tag)).text = val
    if references:
        ET.SubElement(a, q("references")).text = references
    ET.SubElement(a, q("note")).text = "Hackathon prototype (OpenHand 112). Exercise only: not an official alert."
    for lang, code in (("english", "en-IN"), ("hindi", "hi-IN"), ("punjabi", "pa-IN")):
        if not headline.get(lang):
            continue
        info = ET.SubElement(a, q("info"))
        for tag, val in (("language", code), ("category", category), ("event", event), ("urgency", urgency), ("severity", severity),
                         ("certainty", certainty), ("expires", (sent + timedelta(hours=expires_h)).isoformat()),
                         ("senderName", "Chandigarh Traffic Police (prototype)"), ("headline", headline[lang][:160]),
                         ("description", description.get(lang) or description.get("english", "")),
                         ("instruction", instruction.get(lang) or instruction.get("english", ""))):
            ET.SubElement(info, q(tag)).text = val
        for ar in areas:
            area = ET.SubElement(info, q("area"))
            ET.SubElement(area, q("areaDesc")).text = ar["desc"]
            ET.SubElement(area, q("circle")).text = f"{ar['lat']:.5f},{ar['lng']:.5f} {ar.get('radius_km', 0.3):.2f}"
    ET.indent(a, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(a, encoding="unicode")


def flood_cap(world, advisory: dict | None = None) -> str | None:
    """CAP alert for the waterlogging plan at the current moment: one area per closed or soon-closing road."""
    fl = world.flood
    if fl.run is None:
        return None
    p = fl.plan()
    acts = [a for a in p["actions"] if a["kind"] in ("close", "preclose")]
    spots = {s["id"]: s for s in p["spots"]}
    areas = [dict(desc=a["title"].replace("Close ", "").replace("Get ready to close ", "").split(" at ")[0],
                  lat=spots[a["spot"]]["lat"], lng=spots[a["spot"]]["lng"], radius_km=0.3) for a in acts]
    if not areas:
        areas = [dict(desc=s["name"], lat=s["lat"], lng=s["lng"], radius_km=0.3) for s in p["spots"] if s["level"] == "divert"]
    if not areas:
        return None
    adv = advisory or fl.template(fl.advisory_facts())
    closed = [a for a in acts if a["kind"] == "close"]
    head = {"english": f"Waterlogging: {len(closed)} road{'s' if len(closed) != 1 else ''} closed in Chandigarh" if closed
            else "Waterlogging: roads may close soon in Chandigarh",
            "hindi": "जलभराव: चंडीगढ़ में सड़कें बंद" if closed else "जलभराव: चंडीगढ़ में सड़कें जल्द बंद हो सकती हैं",
            "punjabi": "ਪਾਣੀ ਭਰਨਾ: ਚੰਡੀਗੜ੍ਹ ਵਿੱਚ ਸੜਕਾਂ ਬੰਦ" if closed else "ਪਾਣੀ ਭਰਨਾ: ਚੰਡੀਗੜ੍ਹ ਵਿੱਚ ਸੜਕਾਂ ਜਲਦੀ ਬੰਦ ਹੋ ਸਕਦੀਆਂ ਹਨ"}
    instr = {"english": "Do not drive through standing water. Use the diversions shown by traffic police. Emergency: dial 112.",
             "hindi": "पानी भरी सड़क पर गाड़ी न चलाएँ। ट्रैफिक पुलिस के बताए रास्ते लें। आपात स्थिति में 112 डायल करें।",
             "punjabi": "ਪਾਣੀ ਵਾਲੀ ਸੜਕ 'ਤੇ ਗੱਡੀ ਨਾ ਚਲਾਓ। ਟ੍ਰੈਫਿਕ ਪੁਲਿਸ ਦੇ ਦੱਸੇ ਰਸਤੇ ਵਰਤੋ। ਐਮਰਜੈਂਸੀ ਲਈ 112।"}
    return cap_alert(f"CHD-WL-{fl.meta['id']}-{p['now'].replace(':', '')}", "Waterlogging road closure", head,
                     {k: adv.get(k, "") for k in ("english", "hindi", "punjabi")}, instr, areas,
                     category="Transport", certainty="Observed" if closed else "Likely", severity="Moderate")


# ---------- open data ----------
def open_records(world) -> list[dict]:
    rows = []
    for i in sorted(world.incidents.values(), key=lambda x: x.t):
        x, d = i.triage["extract"], i.triage["decision"]
        o = i.outcome or {}
        when = datetime.fromtimestamp(world.t0_wall + i.t / world.demo_speed, IST)
        rows.append(dict(id=i.id, hour=when.strftime("%Y-%m-%dT%H:00+05:30"), type=x["incident_type"], priority=d["priority"],
                         services=",".join(sorted({world.units[u].kind for u in i.units})) or "none",
                         cell_lat=round(round(i.lat / GRID) * GRID, 3) if i.lat is not None else None,
                         cell_lng=round(round(i.lng / GRID) * GRID, 3) if i.lng is not None else None,
                         sector=int(world.flood.sector_of_node[i.node]) if i.node is not None else None,
                         calls=i.calls, first_on_scene_s=o.get("first_on_scene_s"), target_met=o.get("all_targets_met"),
                         status=i.status))
    return rows


def open_geojson(world) -> dict:
    feats = [dict(type="Feature", geometry=dict(type="Point", coordinates=[r["cell_lng"], r["cell_lat"]]) if r["cell_lat"] else None,
                  properties={k: v for k, v in r.items() if k not in ("cell_lat", "cell_lng")}) for r in open_records(world)]
    return dict(type="FeatureCollection", name="openhand112_incidents_anonymised", features=feats,
                metadata=dict(licence="CC BY 4.0 (proposed)", generated=_now_iso(),
                              privacy="No caller words, names or numbers. Place rounded to a ~550 m grid cell, time to the hour. "
                                      "A live feed would also hold back any cell-hour with fewer than 3 incidents.",
                              simulated=True))


def open_csv(world) -> str:
    rows = open_records(world)
    buf = io.StringIO()
    cols = ["id", "hour", "type", "priority", "services", "cell_lat", "cell_lng", "sector", "calls", "first_on_scene_s", "target_met", "status"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


# ---------- catalogue ----------
CATALOGUE = [
    dict(dir="in", system="112 call intake", owner="ERSS-112 (MHA; Chandigarh Police control room)", format="JSON over HTTPS",
         endpoint="POST /api/calls", status="works in demo", live="ERSS forwards the call record and caller audio; we return priority, units and location."),
    dict(dir="in", system="CCTV frames", owner="ICCC, Chandigarh Smart City", format="JPEG + camera ID",
         endpoint="POST /api/cctv/alert · POST /api/incidents/{id}/cctv", status="works in demo (frames uploaded by hand)",
         live="ICCC video system pushes a frame when its own analytics or an operator flags a camera."),
    dict(dir="in", system="Rain now and next 12 h", owner="IMD / Open-Meteo", format="JSON",
         endpoint="POST /api/flood/start {scenario: live}", status="works when online", live="Swap to IMD's nowcast feed when access is granted."),
    dict(dir="out", system="Dispatch order to the vehicle", owner="PCR / 108 / fire control rooms", format="JSON over the CAD link",
         endpoint="outbox: Dispatch order", status="simulated", live="Same payload to the mobile data terminal in each vehicle."),
    dict(dir="out", system="Green corridor at junctions", owner="Traffic police / ICCC signal control", format="JSON, one message per junction with a time window",
         endpoint="POST /api/incidents/{id}/notify-traffic", status="simulated (acknowledgements are simulated)",
         live="Adaptive signal controllers or the traffic post's handset receive each window."),
    dict(dir="out", system="Hospital pre-alert", owner="GMCH-32, GMSH-16, PGIMER emergency", format="JSON (no caller identity)",
         endpoint="outbox: Hospital pre-alert", status="simulated", live="Ambulance ETA and triage summary to the receiving emergency department."),
    dict(dir="out", system="Public alert (SMS and cell broadcast)", owner="NDMA SACHET (C-DOT)", format="OASIS CAP 1.2 XML",
         endpoint="GET /api/dpi/cap/flood.xml", status="file generated; not sent", live="Submitted to the state's SACHET account as an Exercise first, then Actual."),
    dict(dir="out", system="Open data", owner="data.gov.in / Chandigarh open data portal", format="GeoJSON, CSV",
         endpoint="GET /api/open/incidents.geojson · .csv", status="works in demo", live="Daily file, cell-hours with fewer than 3 incidents held back."),
    dict(dir="out", system="Close-out record", owner="ERSS-112", format="JSON", endpoint="outbox: Incident closed", status="simulated",
         live="Response times and outcome written back to the ERSS case."),
]
