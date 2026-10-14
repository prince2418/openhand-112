"""Compare dispatch rules and standby placements on identical simulated incidents.

    python run_benchmark.py                       # real stations (data/stations.csv), all scenarios
    python run_benchmark.py --scenarios pcr --seeds 8
    python run_benchmark.py --sweep               # sensitivity to the assumptions that matter most

What is compared, per scenario (same incidents for every row):
  dispatch rules, units at today's stations : nearest_distance (today), nearest_eta, coverage
  standby placements, nearest_eta dispatch  : current (stations), spread (even), rebalanced
                                              (same stations, units shared by forecast demand),
                                              optimised (free standby points)

Every number in SCENARIOS is an ASSUMPTION unless marked PUBLISHED. See README.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from csafe.demand import HOURLY_PROFILE, estimate_weights, generate, scenario_weights, tod_multiplier  # noqa: E402
from csafe.metrics import paired_diff, summarize  # noqa: E402
from csafe.network import RoadNet  # noqa: E402
from csafe.placement import mexclp, optimise_placement, rebalance_stations  # noqa: E402
from csafe.metrics import worst_sector  # noqa: E402
from csafe.sim import POLICIES, calibrate_speed, make_fleet, simulate  # noqa: E402

SECTOR_OF_NODE = np.zeros(0, dtype=int)
DELAY_S = 60.0  # call handling before dispatch (ASSUMPTION; the published 4:32 is taken as call-to-arrival)

SCENARIOS = {
    # PCR: 57 four-wheelers + 12 motorcycles = 69 (PUBLISHED, Tribune 10 Oct 2026); ~45% on duty at once (ASSUMPTION)
    # >300 calls a day (PUBLISHED); 112 cases ~273/day 2022-26 (PUBLISHED totals); 4:32 average Jan-Sep 2026 (PUBLISHED)
    "pcr": dict(kinds=["police"], demand="pcr", units=31, rate=300, service_s=1500, target_s=300, calib_mean_s=272),
    # Fire: 7 stations (PUBLISHED, MC 2025); tenders per station, calls/day, time on scene: ASSUMPTIONS
    # (only published counts: 17-21 calls on Diwali night, a peak). Target 5 min: an 8-min target is met almost everywhere.
    "fire": dict(kinds=["fire"], demand="fire", units=14, rate=5, service_s=3600, target_s=300),
    # 108 ambulances: 6 vehicles c.2016 (PUBLISHED but dated), real stationing points unpublished ->
    # placed at the five 108 destination hospitals (ASSUMPTION). Calls/day and time per trip: ASSUMPTIONS.
    "ambulance": dict(kinds=["ambulance_base"], demand="ambulance", units=6, rate=40, service_s=2700, target_s=480),
}

SWEEPS = {  # the assumptions each result depends on most
    "pcr": ("units", [22, 31, 45]),
    "fire": ("rate", [2, 5, 10]),
    "ambulance": ("rate", [20, 40, 80]),
}


def _spots(csv: str) -> list[tuple[float, float]]:
    from csafe.demand import _black_spots
    return _black_spots(csv)


def _sector_of_node(net: RoadNet) -> np.ndarray:
    """Sector number for each road node: nearest fitted sector centre within 900 m, else 0 (outside the grid)."""
    from csafe.triage.location import SECTOR_POINTS
    secs = sorted(SECTOR_POINTS)
    c = np.array([SECTOR_POINTS[s][1] for s in secs])
    xy = net._xy(net.lat, net.lon)
    cxy = net._xy(c[:, 0], c[:, 1])
    d = np.sqrt(((xy[:, None, :] - cxy[None, :, :]) ** 2).sum(axis=2))
    j = d.argmin(axis=1)
    return np.where(d[np.arange(len(j)), j] <= 900, np.array(secs)[j], 0)


def load_bases(csv: str, kinds: list[str], net: RoadNet) -> tuple[np.ndarray, list[str]]:
    df = pd.read_csv(csv)
    df = df[df["kind"].isin(kinds)].dropna(subset=["lat", "lng"])
    if df.empty:
        raise SystemExit(f"no rows with kind in {kinds} in {csv}")
    lat, lng = df["lat"].to_numpy(), df["lng"].to_numpy()
    far = net.snap_distance_m(lat, lng) > 300
    if far.any():
        print(f"  warning: {', '.join(df['name'][far])} >300 m from the nearest road node", file=sys.stderr)
    return net.snap(lat, lng), df["name"].tolist()


def placements(net: RoadNet, cfg: dict, args, scale: float, forecast: np.ndarray) -> dict[str, np.ndarray]:
    k = cfg["units"]
    stations, _ = load_bases(args.stations, cfg["kinds"], net)
    typical = float((HOURLY_PROFILE * tod_multiplier(np.arange(24))).sum())
    reach = (cfg["target_s"] - DELAY_S) / (scale * typical)  # unscaled seconds that still meet the target
    return {
        "current": np.array([stations[i % len(stations)] for i in range(k)]),   # spread round-robin over stations
        "spread": net.spread_nodes(k, seed=1),
        "rebalanced": rebalance_stations(net, stations, forecast, k),
        "optimised": optimise_placement(net, forecast, k, reach),
        # textbook reference (Daskin's MEXCLP): same forecast, same reach, units busy with probability p
        "mexclp": mexclp(net, forecast, k, reach, busy_p=min(0.9, cfg["rate"] * (cfg["service_s"] + 600) / (k * 86400))),
    }


def run_scenario(name: str, cfg: dict, net: RoadNet, args, scale: float, full: bool = True,
                 truth: np.ndarray | None = None, history: np.ndarray | None = None) -> dict:
    """truth: where test incidents happen; history: where the past incidents the forecast learns from
    happened. Both default to the scenario's demand layer; passing different ones tests what happens
    when the forecast is wrong."""
    w = scenario_weights(net, cfg["demand"], args.hotspots) if truth is None else truth
    w_hist = w if history is None else history
    # the placement optimisers only see a forecast learned from past (simulated) incidents, never w itself
    hist = generate(w_hist, cfg["rate"], args.forecast_days, seed=5000, mean_service_s=cfg["service_s"]).node
    forecast = estimate_weights(net, hist, prior=np.ones(net.n) / net.n)
    places = placements(net, cfg, args, scale, forecast)
    fleets = {p: make_fleet(net, h, f"{name}_{p}") for p, h in places.items()}
    tgt = cfg["target_s"]
    streams = [generate(w, cfg["rate"], args.days, seed=s, mean_service_s=cfg["service_s"]) for s in range(args.seeds)]
    day = np.concatenate([inc.day + s * args.days for s, inc in enumerate(streams)])
    sec = SECTOR_OF_NODE[np.concatenate([inc.node for inc in streams])]

    def run(fleet, policy):
        rs = [simulate(fleet, inc, policy, weights=forecast, speed_scale=scale, delay_s=DELAY_S, target_s=tgt) for inc in streams]
        return np.concatenate([r.response_s for r in rs]), rs

    out = {"units": cfg["units"], "calls_per_day": cfg["rate"], "target_min": tgt / 60, "incidents": int(len(day))}
    base_resp, base_runs = run(fleets["current"], "nearest_distance")
    busy = sum(float((r.release_t - r.dispatch_t).sum()) for r in base_runs)
    out["utilisation_pct"] = round(100 * busy / (cfg["units"] * args.days * args.seeds * 86400), 1)
    out["queued_pct"] = round(100 * float(np.mean(np.concatenate([r.wait_s for r in base_runs]) > 0)), 1)

    resp = {"nearest_distance@current": base_resp}
    if full:
        for pol in ("nearest_eta", "coverage"):
            resp[f"{pol}@current"] = run(fleets["current"], pol)[0]
    for p in ("spread", "rebalanced", "mexclp", "optimised") if full else ("rebalanced", "mexclp", "optimised"):
        resp[f"nearest_eta@{p}"] = run(fleets[p], "nearest_eta")[0]
    if "nearest_eta@current" not in resp:
        resp["nearest_eta@current"] = run(fleets["current"], "nearest_eta")[0]

    out["rows"] = {k: summarize(v, (tgt,)) | {"worst_sector": worst_sector(v, sec, tgt)} for k, v in resp.items()}
    ref = resp["nearest_distance@current"]
    out["vs_today"] = {k: paired_diff(ref, v, day, tgt) for k, v in resp.items() if k != "nearest_distance@current"}
    eta = resp["nearest_eta@current"]
    out["vs_eta_at_stations"] = {k: paired_diff(eta, resp[k], day, tgt) for k in resp if k.startswith("nearest_eta@") and k != "nearest_eta@current"}
    # strongest simple reference: whichever non-optimised placement does best on these incidents
    refs = [k for k in resp if k.startswith("nearest_eta@") and k != "nearest_eta@optimised"]
    best = max(refs, key=lambda k: float(np.mean(resp[k] <= tgt)))
    out["best_reference"] = best
    out["optimised_vs_best_reference"] = paired_diff(resp[best], resp["nearest_eta@optimised"], day, tgt)
    out["optimised_vs_mexclp"] = paired_diff(resp["nearest_eta@mexclp"], resp["nearest_eta@optimised"], day, tgt)
    return out


def fmt(name: str, block: dict) -> str:
    tgt = int(block["target_min"])
    key = f"within_{tgt}min_pct"
    lines = [f"\n== {name}: {block['units']} units, {block['calls_per_day']}/day, target {tgt} min, "
             f"utilisation {block['utilisation_pct']}%, queued {block['queued_pct']}%",
             f"{'dispatch@placement':28s} {'in target %':>11s} {'median':>7s} {'p90 min':>8s} {'worst sector':>16s}   vs today: in-target pts [95% CI]"]
    for k, s in block["rows"].items():
        d = block["vs_today"].get(k)
        ci = f"{d['within_pct_points']:+6.2f} [{d['within_ci95'][0]:+.2f}, {d['within_ci95'][1]:+.2f}]" if d else "  (today's baseline)"
        ws = s.get("worst_sector") or {}
        wtxt = f"S{ws['sector']} {ws['within_pct']:.0f}%" if ws else "-"
        lines.append(f"{k:28s} {s[key]:11.1f} {s['p50_min']:7.2f} {s['p90_min']:8.2f} {wtxt:>16s}   {ci}")
    m = block["optimised_vs_mexclp"]
    lines.append(f"  optimised vs MEXCLP (textbook): {m['within_pct_points']:+.2f} pts [{m['within_ci95'][0]:+.2f}, {m['within_ci95'][1]:+.2f}]")
    d = block["optimised_vs_best_reference"]
    lines.append(f"  optimised vs strongest reference ({block['best_reference']}): {d['within_pct_points']:+.2f} pts "
                 f"[{d['within_ci95'][0]:+.2f}, {d['within_ci95'][1]:+.2f}], mean {d['mean_min']:+.2f} min")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="data/chandigarh_enriched.graphml")
    ap.add_argument("--stations", default="data/stations.csv")
    ap.add_argument("--hotspots", default="data/hotspots_geocoded.csv")
    ap.add_argument("--scenarios", default="pcr,fire,ambulance")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--forecast-days", type=int, default=90)
    ap.add_argument("--sweep", action="store_true", help="also vary the most important assumption per scenario")
    ap.add_argument("--robustness", action="store_true", help="PCR: test placements when real demand differs from the forecast")
    ap.add_argument("--demand-sweep", action="store_true", help="PCR: standby result under several demand models")
    ap.add_argument("--out", default="results/benchmark.json")
    args = ap.parse_args()

    net = RoadNet.from_graphml(args.graph)
    global SECTOR_OF_NODE
    SECTOR_OF_NODE = _sector_of_node(net)
    report: dict = {"stations": args.stations, "delay_s": DELAY_S, "days": args.days, "seeds": args.seeds, "scenarios": {}}

    # calibrate one city-wide travel-time scale: today's rule (nearest by distance) from today's police
    # stations must reproduce the published 4:32 average
    pcr = SCENARIOS["pcr"]
    stations, _ = load_bases(args.stations, pcr["kinds"], net)
    cur = np.array([stations[i % len(stations)] for i in range(pcr["units"])])
    w_pcr = scenario_weights(net, "pcr")
    calib = generate(w_pcr, pcr["rate"], 10, seed=900, mean_service_s=pcr["service_s"])
    scale = calibrate_speed(make_fleet(net, cur), calib, weights=w_pcr, target_mean_s=pcr["calib_mean_s"], delay_s=DELAY_S)
    report["speed_scale"] = round(scale, 3)
    print(f"calibrated travel-time scale = {scale:.3f} (1.0 = imputed OSM road-class speeds)")

    for name in args.scenarios.split(","):
        block = run_scenario(name, SCENARIOS[name], net, args, scale)
        report["scenarios"][name] = block
        print(fmt(name, block), flush=True)
        if args.sweep:
            param, values = SWEEPS[name]
            block["sweep"] = {}
            for v in values:
                if v == SCENARIOS[name][param]:
                    continue
                cfg = dict(SCENARIOS[name], **{param: v})
                b = run_scenario(name, cfg, net, args, scale, full=False)
                block["sweep"][f"{param}={v}"] = b
                print(fmt(f"{name} [{param}={v}]", b), flush=True)

    if args.robustness:
        # Our demand shape (busy roads get 4x a residential street) is an assumption. If real demand is
        # flatter, the placement gain shrinks; if the forecast learned the wrong shape, it may vanish.
        flat = np.ones(net.n) / net.n
        roads = scenario_weights(net, "pcr")
        report["robustness"] = {}
        for label, truth, history in (("flat demand, forecast learned it", flat, flat),
                                      ("flat demand, forecast learned busy-road shape (wrong)", flat, roads),
                                      ("busy-road demand, forecast learned flat shape (wrong)", roads, flat)):
            b = run_scenario("pcr", SCENARIOS["pcr"], net, args, scale, full=False, truth=truth, history=history)
            report["robustness"][label] = b
            print(fmt(f"pcr robustness: {label}", b), flush=True)

    if args.demand_sweep:
        # Where calls happen is our weakest assumption, so re-run the PCR comparison under several demand
        # models. Each time the forecast learns from that model's own past calls (as a real deployment would).
        from csafe.demand import node_weights, scenario_weights as sw
        crash_spots = [(la, lo, 20.0) for la, lo in _spots(args.hotspots)]
        models = {
            "busy roads (our default)": sw(net, "pcr"),
            "even over all streets (built-up area)": np.ones(net.n) / net.n,
            "crash-like, with black spots": sw(net, "crash", args.hotspots),
            "hotspot-heavy (black spots x20)": node_weights(net, crash_spots, sigma_m=300),
        }
        report["demand_sweep"] = {}
        for label, w in models.items():
            b = run_scenario("pcr", SCENARIOS["pcr"], net, args, scale, full=False, truth=w, history=w)
            report["demand_sweep"][label] = b
            print(fmt(f"pcr demand: {label}", b), flush=True)
        night = dict(SCENARIOS["pcr"], units=20)
        b = run_scenario("pcr", night, net, args, scale, full=False)
        report["demand_sweep"]["night shift (20 vans)"] = b
        print(fmt("pcr: night shift, 20 vans", b), flush=True)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, default=float))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
