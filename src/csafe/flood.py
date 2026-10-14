"""Waterlogging: how deep the water gets at Chandigarh's known flood spots, and when to divert or close.

The model is deliberately simple and every number in it is labelled:

* Drains. MC says the storm drains were designed for 15 mm/h of rain in the northern sectors (Phase I,
  sectors 1-30) and 20 mm/h in the southern ones (Tribune, 12 Aug 2024). Rain above that rate ponds.
* Ponding. Water collects at a low spot from the road around it, so 1 mm of rain above drain capacity
  raises the water there by `gain` cm (ASSUMPTION per kind of place: underpass 1.1, chowk 0.6, road 0.5,
  market 0.55, low-lying colony 0.45).
* Full drains. After a long wet spell the drains and choes run full and take less: after 80 mm in 12 h,
  capacity falls linearly to half at 200 mm (ASSUMPTION; matches reports that the 2023 deluge flooded far
  more places than its peak hourly rate alone would).
* Draining. When rain falls below capacity, water drains at `recede` cm/h (ASSUMPTION: 6, colonies 3,
  underpasses 8), and an MC pump team adds PUMP_CM_H.
* From the reports (see calibrate): a spot named by more sources drains worse, and one city-wide ponding
  scale is fitted to the places reported waterlogged on 11 Aug 2024. The 9 Jul 2023 list is held out.

Depth thresholds (ASSUMPTIONS, from common road-flooding guidance; cars stall around 30 cm):
  watch  >= 5 cm   send an MC team, warn traffic
  divert >= 15 cm  public traffic diverted; emergency vehicles may pass at walking pace (links 3x slower)
  close  >= 30 cm  closed to everyone (ambulance and PCR ground clearance); routes go around
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

DESIGN_MM_H = {"north": 15.0, "south": 20.0}        # MC via Tribune, 12 Aug 2024
WATCH_CM, DIVERT_CM, CLOSE_CM = 5.0, 15.0, 30.0
LEVELS = ("clear", "watch", "divert", "close")
GAIN = {"underpass": 1.1, "chowk": 0.6, "road": 0.5, "market": 0.55, "colony": 0.45}
RECEDE = {"underpass": 8.0, "chowk": 6.0, "road": 6.0, "market": 5.0, "colony": 3.0}
PUMP_CM_H = 4.0          # ASSUMPTION: one high-capacity dewatering pump on ~2,000 m2 of ponded road
MC_TEAMS = 18            # "18 special flood control teams" (MC, Tribune 4 Sep 2025)
SAT_START_MM, SAT_FULL_MM = 80.0, 200.0
STEP_H = 0.25
DIVERT_SLOW = 3.0        # emergency vehicles through 15-30 cm of water: links take 3x as long (ASSUMPTION)
K_GRID = np.round(np.arange(0.3, 2.51, 0.05), 2)
FIT = {"gain_scale": 1.0}   # set by calibrate()

# IMD monsoon normals for Chandigarh, mm: Jun and Jul from IMD via Tribune (Oct 2025, LPA 844.9 mm for the season);
# Aug and Sep split the remainder (ASSUMPTION) so the four months add up to 844.9.
NORMAL_MM = {6: 155.5, 7: 273.2, 8: 285.5, 9: 130.7}
RAIN_DAYS = {6: 6, 7: 13, 8: 13, 9: 6}   # rainy days (>= 2.5 mm) per month, ASSUMPTION close to IMD climatology


@dataclass
class Spot:
    id: str
    name: str
    kind: str
    lat: float
    lng: float
    radius_m: float
    sources: list[str]
    events: list[str]
    accuracy: str
    region: str = "north"
    f: float = 1.0
    nodes: list[int] = field(default_factory=list)

    @property
    def capacity(self) -> float:
        return DESIGN_MM_H[self.region] * self.f


def load_spots(net=None, path: Path = ROOT / "data/waterlogging_spots.csv") -> list[Spot]:
    from .triage.location import SECTOR_POINTS
    df = pd.read_csv(path).fillna("")
    secs = sorted(SECTOR_POINTS)
    cen = np.array([SECTOR_POINTS[s][1] for s in secs])
    spots = []
    for r in df.itertuples():
        # region by nearest sector: Phase I (1-30) north, Phase II/III south
        k = int(np.argmin((cen[:, 0] - r.lat) ** 2 + ((cen[:, 1] - r.lng) * math.cos(math.radians(r.lat))) ** 2))
        region = "north" if secs[k] <= 30 else "south"
        s = Spot(r.id, r.name, r.kind, float(r.lat), float(r.lng), float(r.radius_m), str(r.sources).split(),
                 [e for e in str(r.events).split() if e], r.accuracy, region)
        if net is not None:
            xy = net._xy([s.lat], [s.lng])[0]
            nodes = set(net._tree.query_ball_point(xy, s.radius_m))
            j = int(net.snap(s.lat, s.lng)[0])        # always include the nearest road node and what's around it
            nodes |= set(net._tree.query_ball_point(net._xy([net.lat[j]], [net.lon[j]])[0], min(120.0, s.radius_m)))
            s.nodes = sorted(int(n) for n in nodes)
        spots.append(s)
    return spots


# ---------- rain profiles ----------

def _expand(hourly: np.ndarray) -> np.ndarray:
    """Hourly mm -> per-step rate in mm/h (constant within the hour)."""
    return np.repeat(np.asarray(hourly, float), int(round(1 / STEP_H)))


def _pad(h: list[float], total: int = 24) -> list[float]:
    return list(h) + [0.0] * max(0, total - len(h))


def _scale_to(h: list[float], total: float) -> list[float]:
    s = sum(h)
    return [round(x * total / s, 1) for x in h]


# Reconstructed hourly profiles: the published totals are real, the hour-by-hour split is our reconstruction.
E24 = _pad([0, 0, 5, 6, 10, 45, 40, 15, 5, 3.7], 24)                 # 11 Aug 2024 from 07:00: 129.7 mm, 110 mm 11:30-14:30
E23 = _pad(_scale_to([4, 6, 8, 10, 14, 18, 22, 26, 30, 28, 24, 20, 16, 14, 12, 12, 14, 10, 8, 6, 5, 4, 3, 4], 322.2) + [0] * 6, 30)

SCENARIOS = {
    "shower": dict(label="Short shower: 12 mm in an hour", start="16:00", hourly=_pad([12], 8),
                   note="An ordinary monsoon shower. Drains should cope everywhere."),
    "heavy": dict(label="Heavy spell: 25 mm/h for 2 hours", start="15:00", hourly=_pad([8, 25, 25, 6], 10),
                  note="Above design capacity in every sector for two hours."),
    "orange": dict(label="IMD orange alert day: ~150 mm (very heavy)", start="10:00",
                   hourly=_pad(_scale_to([3, 6, 10, 18, 32, 38, 22, 10, 6, 4, 3, 2], 150), 24),
                   note="IMD 'very heavy rain' is 115.6-204.4 mm in 24 h. Hour-by-hour split is an example."),
    "aug2024": dict(label="Replay: 11 Aug 2024 (129.7 mm; 110 mm in 3 h)", start="07:00", hourly=E24,
                    note="Totals from IMD via Tribune (12 Aug 2024). Hourly split reconstructed."),
    "jul2023": dict(label="Replay: 8-9 Jul 2023 (322.2 mm in 24 h, record)", start="08:30", hourly=E23,
                    note="322.2 mm in 24 h, highest since records (IMD via Tribune, 9 Jul 2023). Hourly split reconstructed."),
}


# ---------- the water model ----------

def simulate(hourly: np.ndarray, spots: list[Spot], f: np.ndarray | None = None,
             pump_from: np.ndarray | None = None, d0: np.ndarray | None = None) -> np.ndarray:
    """Water depth (cm) at each spot after every STEP_H. hourly: (H,) or (B, H) mm per hour.
    pump_from: (S,) step index from which a pump team works at each spot (inf = none)."""
    R = _expand(hourly) if np.ndim(hourly) == 1 else np.repeat(np.asarray(hourly, float), int(round(1 / STEP_H)), axis=1)
    batch = R.ndim == 2
    R2 = R if batch else R[None, :]
    B, T = R2.shape
    S = len(spots)
    cap = np.array([DESIGN_MM_H[s.region] for s in spots]) * (np.array([s.f for s in spots]) if f is None else f)
    gain = np.array([GAIN[s.kind] for s in spots]) * FIT["gain_scale"]
    rec = np.array([RECEDE[s.kind] for s in spots])
    pump = np.full(S, np.inf) if pump_from is None else np.asarray(pump_from, float)
    win = int(round(12 / STEP_H))
    csum = np.concatenate([np.zeros((B, 1)), np.cumsum(R2 * STEP_H, axis=1)], axis=1)
    d = np.zeros((B, S)) if d0 is None else np.broadcast_to(d0, (B, S)).astype(float).copy()
    out = np.empty((B, T, S))
    for t in range(T):
        p12 = csum[:, t + 1] - csum[:, max(0, t + 1 - win)]
        sat = np.clip(1 - (p12 - SAT_START_MM) / (SAT_FULL_MM - SAT_START_MM) * 0.5, 0.5, 1.0)
        c = cap[None, :] * sat[:, None]
        r = R2[:, t][:, None]
        rise = gain[None, :] * np.maximum(0.0, r - c)
        fall = rec[None, :] * np.clip(1 - r / c, 0, 1) + np.where(t >= pump, PUMP_CM_H, 0.0)[None, :]
        d = np.clip(d + (rise - fall) * STEP_H, 0, 150)
        out[:, t] = d
    return out if batch else out[0]


def level(depth) -> np.ndarray:
    d = np.asarray(depth)
    return np.select([d >= CLOSE_CM, d >= DIVERT_CM, d >= WATCH_CM], [3, 2, 1], 0)


def calibrate(spots: list[Spot]) -> dict:
    """Two things come from the reports, nothing else is tuned:
    1. Drain condition f per spot: a place named in more independent reports drains worse
       (1 report: 1.0 x design, 2: 0.9, 3+: 0.8).
    2. One city-wide ponding scale, fitted: the SMALLEST scale at which every place reported waterlogged on
       11 Aug 2024 (Tribune) reaches 'divert' depth in the replay of that storm (the flooded underpass: 'close'). Smallest = the fewest
       closures consistent with what happened, so the model does not over-warn.
    The 9 Jul 2023 traffic-police list is not used here; it is the held-out check (holdout_check)."""
    for s in spots:
        s.f = {1: 1.0, 2: 0.9}.get(len(s.sources), 0.8)
    reported = [s for s in spots if "T24" in s.sources]
    FIT["gain_scale"] = float(K_GRID[-1])
    for k in K_GRID:
        FIT["gain_scale"] = float(k)
        peak = simulate(np.array(E24), reported).max(axis=0)
        need = np.array([CLOSE_CM if s.kind == "underpass" else DIVERT_CM for s in reported])   # "underpass flooded"
        if (peak >= need).all():
            break
    return {"gain_scale": FIT["gain_scale"], "f": {s.id: s.f for s in spots}, "fitted_on": [s.name for s in reported]}


def holdout_check(spots: list[Spot]) -> dict:
    """The 9 Jul 2023 traffic police list against the 2023 replay, and false alarms in a plain shower."""
    listed = [s for s in spots if "T23" in s.sources]
    d23 = simulate(np.array(E23), spots).max(axis=0)
    hit = [s.name for s, d in zip(spots, d23) if "T23" in s.sources and d >= DIVERT_CM]
    shower = simulate(np.array(SCENARIOS["shower"]["hourly"]), spots).max(axis=0)
    heavy = simulate(np.array(SCENARIOS["heavy"]["hourly"]), spots).max(axis=0)
    return {"t23_listed": len(listed), "t23_diverted_or_closed": len(hit), "t23_closed": int(sum(1 for s, d in zip(spots, d23) if "T23" in s.sources and d >= CLOSE_CM)),
            "shower_closed": int((shower >= CLOSE_CM).sum()), "shower_diverted": int((shower >= DIVERT_CM).sum()),
            "heavy_closed": int((heavy >= CLOSE_CM).sum()), "heavy_diverted": int((heavy >= DIVERT_CM).sum()), "spots": len(spots)}


# ---------- rain history ----------

def synthetic_seasons(n: int = 60, seed: int = 11) -> np.ndarray:
    """(n, 122*24) hourly mm for Jun-Sep, from a simple weather generator matched to IMD monthly normals:
    wet days by a two-state Markov chain, wet-day totals from a gamma mixed with a rare very-wet regime, and
    each day's rain packed into one storm of 2-12 h with a peaked shape (monsoon rain is bursty)."""
    rng = np.random.default_rng(seed)
    days = [(6, 30), (7, 31), (8, 31), (9, 30)]
    out = np.zeros((n, 122 * 24))
    for i in range(n):
        h = 0
        wet = False
        for m, nd in days:
            p = RAIN_DAYS[m] / nd
            mean = NORMAL_MM[m] / RAIN_DAYS[m]
            for _ in range(nd):
                p_now = min(0.95, p * (1.3 if wet else 0.85))
                wet = rng.random() < p_now
                if wet:
                    if rng.random() < 0.015:                       # very-wet regime (deluge days)
                        amt = rng.gamma(3.0, 45.0)
                    else:
                        amt = rng.gamma(0.75, mean * 0.95 / 0.75)
                    dur = int(np.clip(rng.integers(2, 6) + amt / 35, 2, 14))
                    shape = np.exp(-0.5 * ((np.arange(dur) - rng.uniform(0.3, 0.6) * (dur - 1)) / max(0.6, dur / 4.5)) ** 2)
                    start = int(rng.choice(24 - min(dur, 23)))
                    out[i, h + start:h + start + dur] += amt * shape / shape.sum()
                h += 24
    return out[:, :122 * 24]


def history(path: Path = ROOT / "data/rain_history_openmeteo.csv") -> tuple[np.ndarray, dict]:
    """Monsoon seasons of hourly rain: real Open-Meteo/ERA5 data if scripts/fetch_rain.py has been run,
    else the synthetic generator. Returns (seasons, info)."""
    if path.exists():
        df = pd.read_csv(path, parse_dates=["time"])
        df = df[df["time"].dt.month.isin([6, 7, 8, 9])]
        seasons = []
        for y, g in df.groupby(df["time"].dt.year):
            v = g["mm"].fillna(0).to_numpy()
            if len(v) >= 120 * 24:
                seasons.append(v[:122 * 24] if len(v) >= 122 * 24 else np.pad(v, (0, 122 * 24 - len(v))))
        if seasons:
            years = sorted(df["time"].dt.year.unique())
            return np.array(seasons), {"source": f"Open-Meteo historical weather (ERA5 reanalysis), {years[0]}-{years[-1]}",
                                       "real": True, "seasons": len(seasons),
                                       "caveat": "Reanalysis averages over ~10-30 km, so it smooths short bursts: real hourly peaks are higher."}
    S = synthetic_seasons()
    return S, {"source": "Synthetic monsoons matched to IMD monthly normals (no open hourly station data for Chandigarh)",
               "real": False, "seasons": len(S),
               "caveat": "Run scripts/fetch_rain.py on a machine with internet to replace this with 1995-2025 reanalysis data."}


def rain_stats(seasons: np.ndarray) -> dict:
    daily = seasons.reshape(len(seasons), -1, 24).sum(axis=2)
    return {"season_mm_mean": round(float(seasons.sum(axis=1).mean()), 1),
            "max_day_mm_median": round(float(np.median(daily.max(axis=1))), 1),
            "max_day_mm_p90": round(float(np.percentile(daily.max(axis=1), 90)), 1),
            "max_hour_mm_median": round(float(np.median(seasons.max(axis=1))), 1),
            "seasons_over_250mm_day": round(float((daily.max(axis=1) >= 250).mean()), 3)}


def _events(mask: np.ndarray, gap_steps: int) -> int:
    """Count separate runs of True, merging runs closer than gap_steps."""
    idx = np.flatnonzero(mask)
    if not len(idx):
        return 0
    return int(1 + (np.diff(idx) > gap_steps).sum())


def risk_table(spots: list[Spot], seasons: np.ndarray, info: dict) -> dict:
    D = simulate(seasons, spots)                                # (B, T, S)
    gap = int(round(6 / STEP_H))
    rows = []
    for k, s in enumerate(spots):
        closed = D[:, :, k] >= CLOSE_CM
        div = D[:, :, k] >= DIVERT_CM
        ev_c = [_events(closed[b], gap) for b in range(len(seasons))]
        ev_d = [_events(div[b], gap) for b in range(len(seasons))]
        rows.append(dict(id=s.id, name=s.name, kind=s.kind, region=s.region, f=s.f, capacity_mm_h=round(s.capacity, 1),
                         closures_per_season=round(float(np.mean(ev_c)), 2), p_closure=round(float(np.mean(np.array(ev_c) > 0)), 2),
                         diversions_per_season=round(float(np.mean(ev_d)), 2),
                         hours_closed_per_season=round(float(closed.sum(axis=1).mean() * STEP_H), 1),
                         burst_to_close_mm_h=burst_to_close(s), sources=s.sources, accuracy=s.accuracy))
    rows.sort(key=lambda r: (-r["closures_per_season"], -r["diversions_per_season"]))
    return {"rows": rows, "info": info, "rain": rain_stats(seasons), "check": holdout_check(spots),
            "thresholds_cm": {"watch": WATCH_CM, "divert": DIVERT_CM, "close": CLOSE_CM},
            "design_mm_h": DESIGN_MM_H, "pump_cm_h": PUMP_CM_H, "teams": MC_TEAMS}


def burst_to_close(s: Spot) -> float:
    """Rain rate (mm/h) that, falling for one hour on dry ground, takes this spot to closure depth."""
    lo, hi = 0.0, 200.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if simulate(np.array([mid, 0, 0]), [s]).max() >= CLOSE_CM:
            hi = mid
        else:
            lo = mid
    return round(hi, 1)


# ---------- a run: rain -> depth timeline -> pump teams ----------

def clock_labels(start: str | datetime, n_steps: int) -> list[str]:
    t0 = start if isinstance(start, datetime) else datetime.strptime(start, "%H:%M")
    return [(t0 + timedelta(hours=i * STEP_H)).strftime("%H:%M") for i in range(n_steps)]


def assign_teams(depth: np.ndarray, spots: list[Spot], teams: int = MC_TEAMS, lead_h: float = 0.5,
                 weight: np.ndarray | None = None) -> np.ndarray:
    """Send the MC pump teams where the water will be worst: rank spots by forecast peak depth x importance,
    each team arrives lead_h before its spot first reaches 'watch' (or at once if it's already there).
    Returns the step index each spot gets a pump from (inf = no team)."""
    peak = depth.max(axis=0)
    w = np.ones(len(spots)) if weight is None else weight
    order = np.argsort(-(peak * w))
    out = np.full(len(spots), np.inf)
    lead = int(round(lead_h / STEP_H))
    for k in order[:teams]:
        if peak[k] < WATCH_CM:
            break
        first = int(np.argmax(depth[:, k] >= WATCH_CM))
        out[k] = max(0, first - lead)
    return out


def run(hourly: list[float], spots: list[Spot], start: str | datetime, now_step: int = 0,
        weight: np.ndarray | None = None) -> dict:
    h = np.asarray(hourly, float)
    no_pumps = simulate(h, spots)
    pump_from = assign_teams(no_pumps, spots, weight=weight)
    pump_from = np.where(np.isfinite(pump_from), np.maximum(pump_from, now_step), np.inf)
    with_pumps = simulate(h, spots, pump_from=pump_from)
    T = with_pumps.shape[0]
    labels = clock_labels(start, T + 1)
    lv = level(with_pumps)
    spots_out = []
    for k, s in enumerate(spots):
        d = with_pumps[:, k]
        closed = np.flatnonzero(lv[:, k] == 3)
        spots_out.append(dict(
            id=s.id, peak_cm=round(float(d.max()), 1), peak_at=labels[int(d.argmax()) + 1],
            peak_no_pump_cm=round(float(no_pumps[:, k].max()), 1),
            hours_closed=round(len(closed) * STEP_H, 2), hours_closed_no_pump=round(float((no_pumps[:, k] >= CLOSE_CM).sum() * STEP_H), 2),
            team_from=labels[int(pump_from[k])] if np.isfinite(pump_from[k]) else None,
            team_step=int(pump_from[k]) if np.isfinite(pump_from[k]) else None,
            depth=[round(float(x), 1) for x in d], level=[int(x) for x in lv[:, k]],
            depth_no_pump=[round(float(x), 1) for x in no_pumps[:, k]], level_no_pump=[int(x) for x in level(no_pumps[:, k])]))
    return {"step_h": STEP_H, "labels": labels[1:], "rain_hourly": [round(float(x), 1) for x in h], "spots": spots_out,
            "teams_used": int(np.isfinite(pump_from).sum()), "teams": MC_TEAMS,
            "closed_hours": round(float((with_pumps >= CLOSE_CM).sum() * STEP_H), 1),
            "closed_hours_no_pump": round(float((no_pumps >= CLOSE_CM).sum() * STEP_H), 1),
            "peak_closed": int((with_pumps >= CLOSE_CM).sum(axis=1).max()) if T else 0,
            "design_mm_h": DESIGN_MM_H}


# ---------- live rain (Open-Meteo, free, no key) ----------

OPEN_METEO = ("https://api.open-meteo.com/v1/forecast?latitude=30.7333&longitude=76.7794&hourly=precipitation"
              "&past_days=1&forecast_days=2&timezone=Asia%2FKolkata")


def fetch_live(timeout: float = 8.0, now: datetime | None = None) -> dict:
    """Last 24 h of rain plus the next 12 h for central Chandigarh from Open-Meteo (blends IMD-assimilated
    global models; free for non-commercial use, no key). Raises on network failure."""
    import urllib.request
    with urllib.request.urlopen(OPEN_METEO, timeout=timeout) as r:      # noqa: S310 - fixed https URL
        data = json.loads(r.read().decode())
    times = [datetime.fromisoformat(t) for t in data["hourly"]["time"]]
    mm = [float(x or 0) for x in data["hourly"]["precipitation"]]
    now = now or datetime.now()
    i_now = max(i for i, t in enumerate(times) if t <= now)
    a, b = max(0, i_now - 24), min(len(mm), i_now + 13)
    return {"start": times[a], "hourly": mm[a:b], "now_index": i_now - a, "fetched": now.strftime("%d %b %H:%M"),
            "past24_mm": round(sum(mm[a:i_now + 1]), 1), "next12_mm": round(sum(mm[i_now + 1:b]), 1)}
