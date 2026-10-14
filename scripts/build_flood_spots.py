"""Build data/waterlogging_spots.csv: places in Chandigarh reported as waterlogged or flood-prone.

Every spot comes from a published report (codes below). Coordinates are worked out from what we have:
  * a point the user checked in Google Maps (landmarks.csv / hotspots_geocoded.csv)  -> accuracy "good"
  * a junction of sectors on Chandigarh's grid ("Sector 28/29 light point")            -> accuracy "approx"
    (the fitted sector grid from triage/location.py, then snapped to the nearest major road node)
  * a village / colony point from the AI-written list                                    -> "needs check"

Sources
  T23  Tribune, 9 Jul 2023: Chandigarh traffic police list of roads to avoid due to waterlogging (322.2 mm in 24 h)
  T24  Tribune, 12 Aug 2024: "110 mm rain in 3 hours throws life out of gear" (129.7 mm on 11 Aug 2024)
  MC25 Tribune, 4 Sep 2025: "MC identifies 25 flood-prone spots in UT" (14 named)
  W25  PTI via The Week, 20 Aug 2025: heavy rain, roads inundated (19 Aug 2025)

Run:  python3 scripts/build_flood_spots.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from csafe.network import RoadNet  # noqa: E402
from csafe.triage.location import _GRID, SECTOR_POINTS  # noqa: E402

# id, name, kind, where, sources, events (storms with rain data in which it was reported), radius_m
SPOTS = [
    ("tribune", "Tribune Chowk", "chowk", "point:30.70516,76.78931:good", "T23 MC25", "E23", 130),
    ("matka", "Matka Chowk (Sector 9/10/16/17)", "chowk", "point:30.7456,76.7816:good", "T23", "E23", 120),
    ("hirasingh", "Hira Singh Chowk (Sector 5/6/7/8)", "chowk", "grid:4.5,-0.5", "T23", "E23", 120),
    ("s3233", "Sector 32/33 small chowk", "chowk", "grid:5.5,3", "T23", "E23", 110),
    ("s2829", "Sector 28/29 light point", "chowk", "grid:7,1.5", "T23", "E23", 110),
    ("bapudham", "Bapu Dham light point", "chowk", "grid:6.6,-0.15", "T23", "E23", 110),
    ("s4041", "Sector 40/41 dividing road (towards 40-C)", "road", "grid:0.5,4", "T23 MC25", "E23", 140),
    ("s29chowk", "Sector 29/30/31/32 chowk", "chowk", "grid:6.5,2.5", "MC25", "", 120),
    ("s29iti", "Sector 29-C (ITI, steel market)", "market", "grid:7,2", "MC25 T24", "E24", 140),
    ("s7sports", "Near Sports Complex, Sector 7", "road", "grid:5,0", "MC25", "", 110),
    ("s49road", "Sector 4/9 dividing road", "road", "grid:3,-0.5", "MC25", "", 130),
    ("s58road", "Sector 5/8 dividing road", "road", "grid:4,-0.5", "MC25", "", 130),
    ("indph1", "Industrial Area Ph-I (cremation ground, old Colony No. 4)", "colony", "point:30.70661,76.80418:approx", "MC25", "", 200),
    ("rlyunder", "Industrial Area underpass to the railway station", "underpass", "point:30.7061,76.8120:needs check", "T24", "E24", 70),
    ("gurdwara20", "CTU workshop underpass, Gurdwara Chowk, Sector 20", "underpass", "grid:4.5,2.5", "MC25", "", 80),
    ("palika19", "Palika Bazar, Sector 19-C", "market", "point:30.72823,76.79283:approx", "MC25", "", 110),
    ("s25", "Sector 25 cremation ground area", "road", "grid:0,2", "MC25", "", 140),
    ("woollen38", "Woollen Market, Sector 38-C", "market", "grid:0,3", "MC25", "", 110),
    ("lic15", "LIC Colony, Sector 15-D", "colony", "grid:1,1", "MC25", "", 130),
    ("kajheri", "Kajheri village (near the gurdwara)", "colony", "point:30.7065,76.732:needs check", "MC25", "", 200),
    ("madhya26", "Madhya Marg near Sector 26", "road", "road:Madhya Marg@6,0", "T24", "E24", 150),
    ("rosegarden", "Rose Garden entry, Sector 16 (nullah overflow)", "road", "point:30.7483,76.7801:good", "T24", "E24", 100),
    ("hallomajra", "Hallomajra (low-lying)", "colony", "point:30.69155,76.80273:good", "T24", "E24", 220),
    ("s1115under", "Sector 11/15 underpass", "underpass", "grid:1,0.5", "W25", "", 80),
]


def grid_affine():
    """Affine map (column, row, 1) -> (lat, lng) from the fitted sector centres."""
    rows = [(_GRID[s], ll) for s, (how, ll) in SECTOR_POINTS.items() if s in _GRID and how == "centre"]
    X = np.array([[c, r, 1.0] for (c, r), _ in rows])
    Y = np.array([ll for _, ll in rows])
    A, *_ = np.linalg.lstsq(X, Y, rcond=None)
    return lambda c, r: tuple(float(v) for v in np.array([c, r, 1.0]) @ A)


def main():
    net = RoadNet.from_graphml(str(ROOT / "data/chandigarh_enriched.graphml"))
    major = np.isin(net.node_class, ["trunk", "primary", "secondary"])
    mxy = net._xy(net.lat[major], net.lon[major])
    midx = np.flatnonzero(major)
    roads = json.loads((ROOT / "data/roads.json").read_text())
    at = grid_affine()
    out = []
    for sid, name, kind, where, src, events, radius in SPOTS:
        how, spec = where.split(":", 1)
        if how == "point":
            a, b, acc = spec.split(":")[0].split(",") + [spec.split(":")[1]]
            lat, lng = float(a), float(b)
        elif how == "grid":
            c, r = map(float, spec.split(","))
            lat, lng = at(c, r)
            # a junction or dividing road is on a major road: snap to the nearest major-road node within 350 m
            # (markets and colonies stay at the sector point)
            d = np.linalg.norm(mxy - net._xy([lat], [lng])[0], axis=1)
            if kind in ("chowk", "road", "underpass") and d.min() < 350:
                j = midx[int(d.argmin())]
                lat, lng = float(net.lat[j]), float(net.lon[j])
            acc = "approx"
        else:  # road:Name@c,r -> the point of that road nearest the grid position
            rn, cr = spec.split("@")
            c, r = map(float, cr.split(","))
            p = np.array(at(c, r))
            pts = np.array(roads[rn]["points"], float)  # [lat, lng]
            k = int(np.argmin(((pts - p) ** 2).sum(axis=1)))
            lat, lng = float(pts[k, 0]), float(pts[k, 1])
            acc = "approx"
        snap = float(net.snap_distance_m(lat, lng)[0])
        out.append(dict(id=sid, name=name, kind=kind, lat=round(lat, 5), lng=round(lng, 5), radius_m=radius,
                        sources=src, events=events, accuracy=acc, snap_m=round(snap)))
        print(f"{sid:12s} {lat:.5f},{lng:.5f}  {acc:12s} road node {snap:.0f} m away")
    with open(ROOT / "data/waterlogging_spots.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"wrote {len(out)} spots")


if __name__ == "__main__":
    main()
