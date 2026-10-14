"""Turn what the caller said into map coordinates, using only places we have verified pins for.

Order: (1) the caller's phone location if the call carries one (ERSS receives this from the phone
network), (2) a known landmark named in the call, (3) a known point in the stated sector (about 1 km
accuracy at worst). Otherwise unresolved -> the dispatcher must confirm. We never invent a point.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

# common spoken names -> names in our data files
ALIASES = {
    "pgi": "PGIMER", "pgimer": "PGIMER", "gmch": "GMCH-32", "sector 32 hospital": "GMCH-32",
    "gmsh": "GMSH-16", "sector 16 hospital": "GMSH-16", "civil hospital manimajra": "Civil Hospital Manimajra",
    "tribune chowk": "Tribune Chowk", "isbt 43": "ISBT Sector 43", "isbt-43": "ISBT Sector 43",
    "kalagram": "Kalagram light point", "housing board": "Housing Board light point",
    "hallomajra": "Hallomajra light point", "milk colony": "Milk Colony (Dhanas) light point",
    "poultry farm": "Poultry Farm Chowk", "mauli jagran": "PS Mauli Jagran", "manimajra": "PS Manimajra",
    "it park": "PS IT Park", "maloya": "PS Maloya", "sarangpur": "PS Sarangpur", "burail": "Burail village",
    "industrial area": "PS Industrial Area (Phase 1)", "sadar bazar": "Sadar Bazar Sector 19",
    "shastri market": "Shastri Market Sector 22", "grain market": "Grain Market Sector 26",
    # Hindi (Devanagari) and Punjabi (Gurmukhi) spellings of the same places
    "पीजीआई": "PGIMER", "ਪੀਜੀਆਈ": "PGIMER", "ट्रिब्यून चौक": "Tribune Chowk", "ਟ੍ਰਿਬਿਊਨ ਚੌਕ": "Tribune Chowk",
    "हल्लोमाजरा": "Hallomajra light point", "हल्लो माजरा": "Hallomajra light point", "ਹੱਲੋਮਾਜਰਾ": "Hallomajra light point",
    "कलाग्राम": "Kalagram light point", "ਕਲਾਗ੍ਰਾਮ": "Kalagram light point", "हाउसिंग बोर्ड": "Housing Board light point",
    "मनीमाजरा": "PS Manimajra", "ਮਨੀਮਾਜਰਾ": "PS Manimajra", "मौली जागरां": "PS Mauli Jagran", "ਮੌਲੀ ਜਾਗਰਾਂ": "PS Mauli Jagran",
    "बुड़ैल": "Burail village", "ਬੁੜੈਲ": "Burail village", "मलोया": "PS Maloya", "ਮਲੋਇਆ": "PS Maloya",
    "धनास": "Milk Colony (Dhanas) light point", "ਧਨਾਸ": "Milk Colony (Dhanas) light point", "सारंगपुर": "PS Sarangpur", "ਸਾਰੰਗਪੁਰ": "PS Sarangpur",
}


@dataclass
class Place:
    lat: float | None
    lng: float | None
    method: str          # phone | landmark | road | crossing | sector | unresolved
    label: str
    road: str | None = None          # a named road the caller mentioned: the map highlights it for the dispatcher

    @property
    def resolved(self) -> bool:
        return self.lat is not None


def _gazetteer() -> dict[str, tuple[float, float]]:
    g = {}
    for f, col in (("data/stations.csv", "name"), ("data/hotspots_geocoded.csv", "name"),
                   ("data/hospitals_google.csv", "name")):
        p = ROOT / f
        if p.exists():
            df = pd.read_csv(p)
            for _, r in df.iterrows():
                g[str(r[col])] = (float(r["lat"]), float(r["lng"]))
    return g


GAZ = _gazetteer()


# Chandigarh's sectors sit on a regular grid. Column by column (north to south), then the two western sectors.
# We fit that grid to the verified pins we have (police stations, hospitals): every pin lands within ~750 m of
# its sector's fitted centre (median ~370 m), so the centre is a fair "somewhere in Sector N" point.
_GRID_COLS = [[12, 14, 25, 38, 40, 55], [11, 15, 24, 37, 41, 54], [10, 16, 23, 36, 42, 53], [9, 17, 22, 35, 43, 52],
              [8, 18, 21, 34, 44, 51], [7, 19, 20, 33, 45, 50], [26, 27, 30, 32, 46, 49], [None, 28, 29, 31, 47, 48]]
_GRID = {s: (c, r) for c, col in enumerate(_GRID_COLS) for r, s in enumerate(col) if s}
_GRID.update({39: (-1, 4), 56: (-1, 5)})


def _sector_points() -> dict[int, tuple[str, tuple[float, float]]]:
    pins = {}
    for name, ll in GAZ.items():
        m = re.search(r"Sector (\d+)", name)
        if m:
            pins.setdefault(int(m.group(1)), (name, ll))
    known = [(s, ll) for s, (_, ll) in pins.items() if s in _GRID]
    out = {s: (n, ll) for s, (n, ll) in pins.items() if s not in _GRID}   # e.g. Sector 3: keep its pin
    if len(known) >= 6:
        import numpy as np
        X = np.array([[*_GRID[s], 1.0] for s, _ in known])
        A, *_ = np.linalg.lstsq(X, np.array([ll for _, ll in known]), rcond=None)
        for s, (c, r) in _GRID.items():
            lat, lng = np.array([c, r, 1.0]) @ A
            out[s] = ("centre", (round(float(lat), 5), round(float(lng), 5)))
    else:
        out.update(pins)
    return out


SECTOR_POINTS = _sector_points()


def lookup(name: str) -> tuple[float, float] | None:
    """Exact name, else the gazetteer entry that starts with it ("PGIMER" -> "PGIMER (Sector 12)")."""
    if name in GAZ:
        return GAZ[name]
    hits = [k for k in GAZ if k.startswith(name)]
    return GAZ[hits[0]] if hits else None


# Named arterial roads (V2 roads) from our OSM graph, with the ways callers say them (English, Hindi, Punjabi).
def _load_roads() -> dict[str, list[tuple[float, float]]]:
    p = ROOT / "data/roads.json"
    if not p.exists():
        return {}
    import json
    return {k: [tuple(x) for x in v["points"]] for k, v in json.loads(p.read_text()).items()}


ROADS = _load_roads()
ROAD_ALIASES = {
    "Jan Marg": ["jan marg", "janmarg", "jan maarg", "जन मार्ग", "जनमार्ग", "ਜਨ ਮਾਰਗ"],
    "Madhya Marg": ["madhya marg", "madhya maarg", "madya marg", "madhy marg", "मध्य मार्ग", "ਮੱਧ ਮਾਰਗ", "ਮਧ ਮਾਰਗ"],
    "Dakshin Marg": ["dakshin marg", "dakshan marg", "dakshin maarg", "दक्षिण मार्ग", "ਦੱਖਣ ਮਾਰਗ", "ਦਕਸ਼ਿਣ ਮਾਰਗ"],
    "Purv Marg": ["purv marg", "purva marg", "poorv marg", "purab marg", "पूर्व मार्ग", "ਪੂਰਵ ਮਾਰਗ"],
    "Uttar Marg": ["uttar marg", "uttar maarg", "उत्तर मार्ग", "ਉੱਤਰ ਮਾਰਗ"],
    "Himalaya Marg": ["himalaya marg", "himalya marg", "himalay marg", "हिमालय मार्ग", "ਹਿਮਾਲਿਆ ਮਾਰਗ"],
    "Vidya Marg": ["vidya marg", "vidhya marg", "विद्या मार्ग", "ਵਿਦਿਆ ਮਾਰਗ"],
    "Pashchim Marg": ["pashchim marg", "paschim marg", "पश्चिम मार्ग", "ਪੱਛਮ ਮਾਰਗ"],
    "Sarovar Path": ["sarovar path", "सरोवर पथ", "ਸਰੋਵਰ ਪਥ"],
    "Chandi Path": ["chandi path", "चंडी पथ", "ਚੰਡੀ ਪਥ"],
    "Udyan Path": ["udyan path", "उद्यान पथ", "ਉਦਯਾਨ ਪਥ"],
    "Sukhna Path": ["sukhna path", "सुखना पथ", "ਸੁਖਨਾ ਪਥ"],
    "Udyog Path": ["udyog path", "उद्योग पथ", "ਉਦਯੋਗ ਪਥ"],
    "Vigyan Path": ["vigyan path", "विज्ञान पथ", "ਵਿਗਿਆਨ ਪਥ"],
    "Shanti Path": ["shanti path", "शांति पथ", "ਸ਼ਾਂਤੀ ਪਥ"],
    "NH5": ["nh5", "nh 5", "nh-5", "highway", "zirakpur road", "kalka road"],
}
SECTORS_RE = re.compile(r"(?:sector|sec|सेक्टर|ਸੈਕਟਰ)\s*-?\s*(\d{1,2})(?:\s*(?:and|aur|or|&|/|,|ਅਤੇ|और|te|ate|-)\s*(?:sector\s*)?(\d{1,2}))?", re.I)


def _m(a: tuple[float, float], b: tuple[float, float]) -> float:
    import math
    return math.hypot((a[0] - b[0]) * 111_320, (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0])))


def roads_in(text: str) -> list[str]:
    t = text.lower()
    return [r for r, al in ROAD_ALIASES.items() if r in ROADS and any(a in t for a in al)]


def sectors_in(text: str) -> list[int]:
    out = []
    for m in SECTORS_RE.finditer(text):
        out += [int(g) for g in m.groups() if g]
    return [s for s in dict.fromkeys(out) if s in SECTOR_POINTS]


def _on_road(road: str, near: tuple[float, float], max_m: float = 1500) -> tuple[float, float] | None:
    pts = ROADS.get(road) or []
    best = min(pts, key=lambda p: _m(p, near), default=None)
    return best if best is not None and _m(best, near) <= max_m else None


def _crossing(r1: str, r2: str, max_m: float = 200) -> tuple[float, float] | None:
    best, d = None, max_m
    for a in ROADS.get(r1, []):
        for b in ROADS.get(r2, []):
            dd = _m(a, b)
            if dd < d:
                best, d = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), dd
    return best


def _load_landmarks() -> list[tuple[str, list[str], tuple[float, float], bool]]:
    """data/landmarks.csv: famous places callers name. Exact lat/lng (from Google Maps) when filled in; otherwise an
    approximate point from `approx_from` (sector:N centre, pin:<name in our data>, crossing:<road>|<road>), shown
    as approx. Rows with neither are skipped until someone adds coordinates."""
    p = ROOT / "data/landmarks.csv"
    if not p.exists():
        return []
    out = []
    df = pd.read_csv(p, dtype=str).fillna("")
    if "source" not in df:
        df["source"] = ""
    for _, r in df.iterrows():
        aliases = [a.strip().lower() for a in r["aliases"].split("|") if a.strip()] + [r["name"].lower()]
        ll, approx = None, False
        if r["lat"] and r["lng"]:
            ll = (float(r["lat"]), float(r["lng"]))
        elif r["approx_from"].startswith("point:"):
            la, ln = r["approx_from"][6:].split(",")
            ll, approx = (float(la), float(ln)), True
        elif r["approx_from"].startswith("sector:"):
            n = int(r["approx_from"].split(":")[1])
            ll, approx = (SECTOR_POINTS[n][1] if n in SECTOR_POINTS else None), True
        elif r["approx_from"].startswith("pin:"):
            ll, approx = lookup(r["approx_from"][4:]), True
        elif r["approx_from"].startswith("crossing:"):
            a, b = r["approx_from"][9:].split("|")
            ll, approx = _crossing(a, b), True
        if ll:
            out.append((r["name"], aliases, ll, approx))
    return out


def _says(text: str, alias: str) -> bool:
    """Whole-word match for Roman-script names (so "pu" can't match "pucho"); substring for Indic scripts."""
    return re.search(rf"\b{re.escape(alias)}\b", text) is not None if alias.isascii() else alias in text


LANDMARKS = _load_landmarks()


def resolve(sector: int | None, landmark: str | None, location_text: str | None,
            phone_latlng: tuple[float, float] | None = None) -> Place:
    if phone_latlng:
        return Place(*phone_latlng, "phone", "caller's phone location")
    text = " ".join(t for t in (landmark, location_text) if t).lower()
    for alias, name in ALIASES.items():
        if alias in text and (ll := lookup(name)):
            return Place(*ll, "landmark", name)
    # longest alias first, so "sector 17 plaza" wins over a bare "sector 17"
    hits = sorted(((len(a), nm, ll, ap) for nm, als, ll, ap in LANDMARKS for a in als if _says(text, a)), reverse=True)
    if hits:
        _, nm, ll, ap = hits[0]
        return Place(*ll, "landmark", f"{nm} (approx.)" if ap else nm)
    roads = roads_in(text)
    secs = sectors_in(text) or ([sector] if sector in SECTOR_POINTS else [])
    if len(roads) >= 2 and (ll := _crossing(roads[0], roads[1])):
        return Place(*ll, "crossing", f"{roads[0]} and {roads[1]} crossing", road=roads[0])
    if roads and secs:
        pts = [SECTOR_POINTS[s][1] for s in secs]
        near = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        if ll := _on_road(roads[0], near):
            where = " and ".join(f"Sector {s}" for s in secs)
            return Place(*ll, "road", f"{roads[0]} near {where} (approx.)", road=roads[0])
    if roads:  # a road but no point on it: the dispatcher picks the spot; the map highlights the road
        return Place(None, None, "unresolved", f"somewhere on {roads[0]}: confirm the exact spot", road=roads[0])
    if sector in SECTOR_POINTS:
        name, ll = SECTOR_POINTS[sector]
        how = "centre of sector, approx." if name == "centre" else f"approx., via {name}"
        return Place(*ll, "sector", f"Sector {sector} ({how})")
    return Place(None, None, "unresolved", "location not resolved")
