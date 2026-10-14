"""Run OpenHand's response engine on any Indian city in a few minutes, from OpenStreetMap alone.

    python3 scripts/add_city.py "Lucknow, Uttar Pradesh, India"
    python3 scripts/add_city.py "Bhubaneswar, Odisha, India" --vans 40
    python3 scripts/add_city.py "Chandigarh, India" --slug chandigarh \
        --graphml data/chandigarh_enriched.graphml --stations data/stations.csv      # no download: reuse our files

Needs internet (OpenStreetMap's Overpass servers) unless --graphml and --stations are given. Writes
cities/<slug>/summary.json, which the app shows in the Open platform tab ("Any city, any state").

What it does, with the SAME code the Chandigarh app uses:
  1. road network (OSM drive graph), speeds imputed from road class, travel times calibrated as in Chandigarh
  2. police stations, fire stations and hospitals from OSM
  3. where calls are likely (road-class model; no city's incident data is public)
  4. 5-minute PCR reach with vans waiting at police stations vs at MEXCLP standby points (same vans)
  5. fire-station reach and the 2 best new fire-station sites; hospitals within 10 minutes
Every number is a MODEL of that city: OSM coverage of police/fire stations varies by city, van counts and
speeds are assumptions (both written into the summary). It shows that the engine runs anywhere, and what a
city should check first. It is not a measured result.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from csafe.demand import HOURLY_PROFILE, scenario_weights, tod_multiplier  # noqa: E402
from csafe.network import RoadNet  # noqa: E402
from csafe.placement import best_new_sites, mexclp  # noqa: E402

SPEEDS = {"trunk": 60, "trunk_link": 40, "primary": 50, "primary_link": 35, "secondary": 45, "secondary_link": 30,
          "tertiary": 40, "tertiary_link": 30, "unclassified": 30, "residential": 30, "living_street": 15}
TAGS = {"amenity": ["fire_station", "police", "hospital"], "emergency": ["ambulance_station"]}
CALL_HANDLING_S = 60
PCR_TARGET_S, FIRE_TARGET_S, HOSPITAL_S = 300, 300, 600
VANS_PER_STATION = 2          # ASSUMPTION, as in Chandigarh (31 vans on duty across the city's police stations)
BUSY_P = 300 * (1500 + 600) / (31 * 86400)   # share of time a van is busy: Chandigarh's load, assumed elsewhere


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.split(",")[0].lower()).strip("-")


def speed_scale() -> float:
    try:
        return float(json.loads((ROOT / "results/benchmark.json").read_text())["speed_scale"])
    except Exception:  # noqa: BLE001
        return 0.912


def download(place: str, out: Path, radius_km: float | None = None):
    import networkx as nx
    import osmnx as ox
    from fetch_osm import MIRRORS, build_table
    ox.settings.requests_timeout = 180
    last = None
    for url in MIRRORS:
        ox.settings.overpass_url = url
        try:
            print(f"roads: downloading {place} from {url} …", flush=True)
            try:
                if radius_km is not None:
                    raise ValueError("radius requested, not a Polygon boundary")
                G = ox.graph_from_place(place, network_type="drive")
                area = dict(kind="place")
            except Exception as e:  # noqa: BLE001 - some names geocode to a point, not a boundary
                if "olygon" not in str(e) and radius_km is None:
                    raise
                lat, lng = ox.geocode(place)
                print(f"  no city boundary in OSM; using {radius_km or 8} km around {lat:.4f}, {lng:.4f}", flush=True)
                G = ox.graph_from_point((lat, lng), dist=(radius_km or 8) * 1000, network_type="drive")
                area = dict(kind="point", lat=lat, lng=lng, dist=(radius_km or 8) * 1000)
            G = G.subgraph(max(nx.strongly_connected_components(G), key=len)).copy()
            G = ox.add_edge_travel_times(ox.add_edge_speeds(G, hwy_speeds=SPEEDS, fallback=30))
            print("stations: downloading police, fire, hospitals …", flush=True)
            gdf = ox.features_from_place(place, TAGS) if area["kind"] == "place" else \
                ox.features_from_point((area["lat"], area["lng"]), TAGS, dist=area["dist"])
            st = build_table(gdf)
            ox.save_graphml(G, out / "roads.graphml")
            return G, st
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  failed: {type(e).__name__}: {str(e)[:160]}", flush=True)
    sys.exit(f"Could not download {place} ({last}). Check the name on openstreetmap.org, or try another network.")


def cells(net: RoadNet, w: np.ndarray, today: np.ndarray, plan: np.ndarray, size_deg: float = 0.006) -> list[dict]:
    """~650 m grid cells with the share of expected calls reached in 5 min, today vs with standby points."""
    gi = np.floor(net.lat / size_deg).astype(int), np.floor(net.lon / size_deg).astype(int)
    out = {}
    for i in range(net.n):
        k = (gi[0][i], gi[1][i])
        a = out.setdefault(k, [0.0, 0.0, 0.0])
        a[0] += w[i]; a[1] += w[i] * today[i]; a[2] += w[i] * plan[i]
    res = []
    for (a, b), (tot, t, p) in out.items():
        if tot <= 0:
            continue
        res.append(dict(lat=round((a + .5) * size_deg, 5), lng=round((b + .5) * size_deg, 5), size=size_deg,
                        weight=round(tot * 100, 4), today=round(t / tot, 3), plan=round(p / tot, 3)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("place", help='OSM place name, e.g. "Lucknow, Uttar Pradesh, India"')
    ap.add_argument("--slug", default=None)
    ap.add_argument("--state", default=None, help="state or UT, for the table (default: from the place name)")
    ap.add_argument("--vans", type=int, default=None, help=f"PCR vans on duty (default {VANS_PER_STATION} per police station)")
    ap.add_argument("--radius-km", type=float, default=None, help="use a circle of this radius around the place instead of its boundary")
    ap.add_argument("--graphml", default=None, help="use this enriched road graph instead of downloading")
    ap.add_argument("--stations", default=None, help="use this stations CSV (kind,name,lat,lng) instead of downloading")
    a = ap.parse_args()
    t_start = time.time()
    slug = a.slug or slugify(a.place)
    out = ROOT / "cities" / slug
    out.mkdir(parents=True, exist_ok=True)

    import pandas as pd
    if a.graphml and a.stations:
        import osmnx as ox
        G, st = ox.load_graphml(a.graphml), pd.read_csv(a.stations)
        source = "local files"
    else:
        G, st = download(a.place, out, a.radius_km)
        source = "OpenStreetMap (downloaded " + datetime.now(timezone.utc).strftime("%Y-%m-%d") + ")"
    t_dl = time.time() - t_start
    net = RoadNet(G)
    km = sum(float(d.get("length", 0)) for _, _, d in G.edges(data=True)) / 1000 / 2   # two directions per street
    print(f"road network: {net.n:,} junctions, ~{km:,.0f} km of road", flush=True)

    kinds = st["kind"].astype(str)
    police = st[kinds == "police"]
    fire = st[kinds.isin(["fire"])]
    hosp = st[kinds.isin(["hospital", "ambulance_base", "ambulance_station"])]
    if len(police) == 0:
        sys.exit("No police stations found in OSM for this place: the city's OSM data is too thin for this check.")
    pol_nodes = np.unique(net.snap(police["lat"].to_numpy(), police["lng"].to_numpy()))
    vans = a.vans or VANS_PER_STATION * len(police)
    scale = speed_scale()
    typical = float((HOURLY_PROFILE * tod_multiplier(np.arange(24))).sum())
    k = scale * typical                                  # seconds of model travel time -> real seconds
    reach = (PCR_TARGET_S - CALL_HANDLING_S) / k

    # where calls come from: road-class model (busier roads, more calls), the same as Chandigarh's default
    w_pcr = scenario_weights(net, "pcr")
    w_den = np.ones(net.n) / net.n                       # built-up area proxy for fire and medical calls
    from scipy.sparse.csgraph import dijkstra
    t_st = dijkstra(net.A, directed=True, indices=pol_nodes, min_only=True)
    cov_today = t_st <= reach
    ncand = int(max(150, min(600, 3.0e7 / net.n)))
    print(f"standby: placing {vans} vans (MEXCLP, {ncand} candidate points) …", flush=True)
    pts = mexclp(net, w_pcr, vans, reach, busy_p=min(0.9, BUSY_P), n_candidates=ncand)
    t_pl = dijkstra(net.A, directed=True, indices=np.unique(pts), min_only=True)
    cov_plan = t_pl <= reach

    res = dict(slug=slug, place=a.place, name=a.place.split(",")[0].strip(),
               state=a.state or (a.place.split(",")[1].strip() if a.place.count(",") >= 2 else None),
               source=source, generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               junctions=net.n, road_km=round(km), police_stations=int(len(police)), fire_stations=int(len(fire)),
               hospitals=int(len(hosp)), vans=vans,
               pcr=dict(target_min=5, today_pct=round(float(w_pcr[cov_today].sum() * 100), 1),
                        standby_pct=round(float(w_pcr[cov_plan].sum() * 100), 1),
                        standby_points=[dict(lat=round(float(net.lat[p]), 5), lng=round(float(net.lon[p]), 5)) for p in pts]))
    res["pcr"]["gain_pts"] = round(res["pcr"]["standby_pct"] - res["pcr"]["today_pct"], 1)

    if len(fire):
        f_nodes = np.unique(net.snap(fire["lat"].to_numpy(), fire["lng"].to_numpy()))
        f_reach = (FIRE_TARGET_S - CALL_HANDLING_S) / k
        tf = dijkstra(net.A, directed=True, indices=f_nodes, min_only=True)
        new = best_new_sites(net, f_nodes, w_den, 2, f_reach, n_candidates=ncand)
        tf2 = dijkstra(net.A, directed=True, indices=np.unique(np.concatenate([f_nodes, new])), min_only=True)
        res["fire"] = dict(target_min=5, today_pct=round(float(w_den[tf <= f_reach].sum() * 100), 1),
                           with_2_new_pct=round(float(w_den[tf2 <= f_reach].sum() * 100), 1),
                           new_sites=[dict(lat=round(float(net.lat[p]), 5), lng=round(float(net.lon[p]), 5)) for p in new])
    if len(hosp):
        h_nodes = np.unique(net.snap(hosp["lat"].to_numpy(), hosp["lng"].to_numpy()))
        th = dijkstra(net.A, directed=True, indices=h_nodes, min_only=True)
        res["hospital"] = dict(within_min=10, pct=round(float(w_den[th <= HOSPITAL_S / k].sum() * 100), 1))

    res["stations"] = [dict(kind=str(r.kind), name=None if pd.isna(r.name) else str(r.name), lat=round(float(r.lat), 5), lng=round(float(r.lng), 5))
                       for r in st.itertuples() if str(r.kind) in ("police", "fire", "hospital", "ambulance_base", "ambulance_station")]
    res["cells"] = cells(net, w_pcr, cov_today, cov_plan)
    res["bounds"] = [[round(float(net.lon.min()), 4), round(float(net.lat.min()), 4)], [round(float(net.lon.max()), 4), round(float(net.lat.max()), 4)]]
    res["center"] = [round(float(np.median(net.lon)), 4), round(float(np.median(net.lat)), 4)]
    res["assumptions"] = [
        f"{vans} PCR vans on duty" + ("" if a.vans else f" ({VANS_PER_STATION} per police station found in OSM)"),
        "Calls follow road class (busier roads, more calls); no incident data used",
        f"Road speeds from road class, scaled by Chandigarh's calibration ({scale:.3f}) and an all-day traffic average",
        "Police, fire and hospital locations as mapped in OpenStreetMap: missing stations make 'today' look worse",
        "All vans free (no calls in progress)",
    ]
    res["seconds"] = dict(download=round(t_dl), analysis=round(time.time() - t_start - t_dl), total=round(time.time() - t_start))
    (out / "summary.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    p = res["pcr"]
    print(f"\n{res['name']}: {res['police_stations']} police stations, {vans} vans, {res['fire_stations']} fire stations, {res['hospitals']} hospitals")
    print(f"  calls a PCR van reaches in 5 min: {p['today_pct']}% at police stations -> {p['standby_pct']}% at standby points ({p['gain_pts']:+} points)")
    if "fire" in res:
        print(f"  fire: {res['fire']['today_pct']}% within 5 min -> {res['fire']['with_2_new_pct']}% with 2 new stations")
    if "hospital" in res:
        print(f"  hospitals within 10 min drive: {res['hospital']['pct']}% of the city")
    print(f"  done in {res['seconds']['total']} s -> {out / 'summary.json'}")


if __name__ == "__main__":
    main()
