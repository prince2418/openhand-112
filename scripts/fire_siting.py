"""Where should Chandigarh's next fire stations go? Fire tenders need stations, so instead of free
standby points we ask: given today's 7 stations, which 1-2 new sites add the most risk reachable in
5 minutes, and how does the MC's 2017 plan (Sector 53, IT Park) compare?

    python scripts/fire_siting.py [--sector53 LAT,LNG]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT))
from csafe.demand import generate, scenario_weights  # noqa: E402
from csafe.metrics import paired_diff, summarize  # noqa: E402
from csafe.network import RoadNet  # noqa: E402
from csafe.placement import best_new_sites  # noqa: E402
from csafe.sim import make_fleet, simulate  # noqa: E402
from run_benchmark import DELAY_S, HOURLY_PROFILE, SCENARIOS, load_bases, tod_multiplier  # noqa: E402

IT_PARK = (30.72771, 76.84099)  # proxy: PS IT Park pin (user, Google Maps); the planned fire site is unpublished


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sector53", help="lat,lng of the planned Sector 53 site, if known")
    ap.add_argument("--scale", type=float, default=None, help="travel-time scale (default: from results/benchmark.json)")
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--days", type=int, default=60)
    a = ap.parse_args()
    scale = a.scale or json.loads((ROOT / "results/benchmark.json").read_text())["speed_scale"]
    net = RoadNet.from_graphml(str(ROOT / "data/chandigarh_enriched.graphml"))
    cfg = SCENARIOS["fire"]
    w = scenario_weights(net, "fire", str(ROOT / "data/hotspots_geocoded.csv"))
    st, _ = load_bases(str(ROOT / "data/stations.csv"), ["fire"], net)
    typical = float((HOURLY_PROFILE * tod_multiplier(np.arange(24))).sum())
    reach = (cfg["target_s"] - DELAY_S) / (scale * typical)
    today = np.repeat(st, 2)                                  # 2 tenders per station (ASSUMPTION)
    best = best_new_sites(net, st, w, 2, reach)                # NB: uses the demand layer itself (siting is long-term planning)
    options = {"today: 7 stations": today,
               "+1 best new site": np.r_[today, best[:1]],
               "+2 best new sites": np.r_[today, best]}
    plan = [net.snap(np.array([IT_PARK[0]]), np.array([IT_PARK[1]]))[0]]
    if a.sector53:
        la, lo = map(float, a.sector53.split(","))
        plan.append(net.snap(np.array([la]), np.array([lo]))[0])
    options[f"+MC 2017 plan ({'IT Park, Sector 53' if a.sector53 else 'IT Park only; Sector 53 pin missing'})"] = np.r_[today, plan]
    streams = [generate(w, cfg["rate"], a.days, seed=s, mean_service_s=cfg["service_s"]) for s in range(a.seeds)]
    day = np.concatenate([i.day + s * a.days for s, i in enumerate(streams)])
    res = {}
    for k, homes in options.items():
        f = make_fleet(net, homes)
        res[k] = np.concatenate([simulate(f, i, "nearest_eta", weights=w, speed_scale=scale, delay_s=DELAY_S,
                                          target_s=cfg["target_s"]).response_s for i in streams])
    # static coverage too (share of fire risk within 5 min of the nearest station), no simulation noise
    out = {"scale": scale, "best_sites": [[float(net.lat[n]), float(net.lon[n])] for n in best], "options": {}}
    base = res["today: 7 stations"]
    for k, r in res.items():
        cover = float(w[(net.travel_times_from(np.unique(options[k])) <= reach).any(axis=0)].sum())
        s = summarize(r, (cfg["target_s"],)); d = paired_diff(base, r, day, cfg["target_s"]) if k != "today: 7 stations" else None
        out["options"][k] = {"risk_within_5min_pct": round(100 * cover, 1), **s, "vs_today": d}
        extra = f"  vs today {d['within_pct_points']:+.1f} pts [{d['within_ci95'][0]:+.1f}, {d['within_ci95'][1]:+.1f}]" if d else ""
        print(f"{k:52s} risk in 5-min reach {100*cover:5.1f}% | calls reached in 5 min {s['within_5min_pct']:5.1f}%{extra}")
    print("best new sites (lat, lng):", [tuple(round(x, 5) for x in p) for p in out["best_sites"]])
    (ROOT / "results/fire_siting.json").write_text(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
