"""Tests on tiny hand-built graphs, where the right answer is known by construction."""
import sys
from pathlib import Path

import networkx as nx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from csafe.demand import Incidents, flat_multiplier, generate  # noqa: E402
from csafe.metrics import paired_diff  # noqa: E402
from csafe.network import RoadNet  # noqa: E402
from csafe.sim import calibrate_speed, make_fleet, simulate  # noqa: E402


def build(nodes, edges):
    """nodes: {id: (lat, lng)}, edges: [(u, v, seconds)] added both ways."""
    G = nx.MultiDiGraph()
    for k, (lat, lng) in nodes.items():
        G.add_node(k, y=lat, x=lng)
    for u, v, s in edges:
        G.add_edge(u, v, travel_time=s, highway="residential")
        G.add_edge(v, u, travel_time=s, highway="residential")
    return RoadNet(G)


def one(node, t=0.0, service=0.0):
    return Incidents(np.array([t]), np.array([node]), np.array([service]), np.array([1.0]))


def line_net():
    # 0 - 1 - 2 - 3 - 4 - 5 - 6 ; units will sit at nodes 1 and 5
    nodes = {i: (30.70 + 0.001 * i, 76.78) for i in range(7)}
    edges = [(0, 1, 100), (1, 2, 90), (2, 3, 90), (3, 4, 100), (4, 5, 100), (5, 6, 100)]
    return build(nodes, edges)


def test_eta_policy_beats_straight_line_when_roads_differ():
    # A is closer as the crow flies but its road is slow; B is farther but fast
    net = build({0: (30.700, 76.780), 1: (30.710, 76.780), 2: (30.700, 76.800)}, [(0, 1, 600), (2, 1, 100)])
    fleet = make_fleet(net, [0, 2])  # unit 0 at A, unit 1 at B
    kw = dict(weights=np.ones(3) / 3, delay_s=0, mult_fn=flat_multiplier)
    r_dist = simulate(fleet, one(1), "nearest_distance", **kw)
    r_eta = simulate(fleet, one(1), "nearest_eta", **kw)
    assert r_dist.unit[0] == 0 and r_dist.response_s[0] == 600
    assert r_eta.unit[0] == 1 and r_eta.response_s[0] == 100


def test_coverage_policy_keeps_the_city_covered():
    net = line_net()
    fleet = make_fleet(net, [1, 5])
    w = np.array([0.40, 0.11, 0.11, 0.11, 0.11, 0.11, 0.05])  # node 0 matters most, and only unit 0 covers it
    kw = dict(weights=w, delay_s=0, target_s=300, mult_fn=flat_multiplier)
    eta = simulate(fleet, one(3), "nearest_eta", **kw)
    cov = simulate(fleet, one(3), "coverage", **kw)
    assert eta.unit[0] == 0 and eta.response_s[0] == 180      # fastest, but strips cover from the busy west end
    assert cov.unit[0] == 1 and cov.response_s[0] == 200      # 20 s slower, still on target, west end stays covered


def test_coverage_policy_falls_back_to_fastest_when_nobody_makes_target():
    net = line_net()
    fleet = make_fleet(net, [1, 5])
    kw = dict(weights=np.ones(7) / 7, delay_s=0, target_s=100, mult_fn=flat_multiplier)
    assert simulate(fleet, one(3), "coverage", **kw).unit[0] == 0


def test_second_incident_waits_for_the_only_unit():
    net = line_net()
    fleet = make_fleet(net, [1])
    inc = Incidents(np.array([0.0, 1.0]), np.array([2, 2]), np.array([1000.0, 0.0]), np.ones(2))
    r = simulate(fleet, inc, "nearest_eta", weights=np.ones(7) / 7, delay_s=0, mult_fn=flat_multiplier)
    # unit drives 90 s, serves 1000 s, drives 90 s back -> free at 1180; second call waited 1179 s, then drove 90 s
    assert r.release_t[0] == 1180
    assert abs(r.wait_s[1] - 1179) < 1e-9 and abs(r.response_s[1] - (1179 + 90)) < 1e-9


def test_no_unit_is_ever_double_booked():
    net = line_net()
    fleet = make_fleet(net, [1, 3, 5])
    w = np.ones(7) / 7
    inc = generate(w, rate_per_day=200, days=3, seed=4, mean_service_s=1200)
    for policy in ("nearest_distance", "nearest_eta", "coverage"):
        r = simulate(fleet, inc, policy, weights=w, delay_s=30)
        assert (r.response_s >= 30).all()
        for u in range(fleet.n_units):
            order = np.argsort(r.dispatch_t[r.unit == u])
            starts, ends = r.dispatch_t[r.unit == u][order], r.release_t[r.unit == u][order]
            assert (starts[1:] >= ends[:-1] - 1e-9).all(), f"{policy}: unit {u} double-booked"


def test_same_seed_same_incidents_and_different_seed_differs():
    w = np.ones(7) / 7
    a, b, c = (generate(w, 100, 2, s, 900) for s in (1, 1, 2))
    assert np.array_equal(a.t, b.t) and np.array_equal(a.node, b.node) and np.array_equal(a.noise, b.noise)
    assert len(a) != len(c) or not np.array_equal(a.t, c.t)


def test_calibration_recovers_a_known_scale():
    net = line_net()
    fleet = make_fleet(net, [1, 3, 5])
    w = np.ones(7) / 7
    inc = generate(w, 150, 5, seed=3, mean_service_s=900)
    target = simulate(fleet, inc, "nearest_distance", weights=w, speed_scale=1.7).response_s.mean()
    got = calibrate_speed(fleet, inc, weights=w, target_mean_s=target)
    assert abs(got - 1.7) < 0.02


def test_paired_diff_zero_for_identical_and_exact_for_constant_shift():
    a = np.random.default_rng(0).uniform(100, 600, 400)
    day = np.repeat(np.arange(8), 50)
    same = paired_diff(a, a, day, 300)
    assert same["within_pct_points"] == 0 and same["within_ci95"] == (0.0, 0.0)
    shifted = paired_diff(a, a - 60, day, 300)
    assert abs(shifted["mean_min"] + 1.0) < 1e-9 and shifted["within_pct_points"] > 0


def test_placement_goes_where_the_risk_is():
    from csafe.placement import greedy_cover

    net = line_net()
    M = net.travel_times_from(np.arange(7))
    w = np.array([0.30, 0.05, 0.05, 0.10, 0.05, 0.05, 0.40])
    picked = set(greedy_cover(M, w, k=2, reach_s=150).tolist())
    assert picked == {5, 1}  # node 5 covers 4-6 (risk .50), then node 1 covers 0-2 (risk .40)


def test_placement_with_spare_units_still_returns_distinct_nodes():
    from csafe.placement import greedy_cover

    net = line_net()
    M = net.travel_times_from(np.arange(7))
    picked = greedy_cover(M, np.ones(7) / 7, k=5, reach_s=10_000)  # everything already covered by the first pick
    assert len(set(picked.tolist())) == 5


def test_forecast_follows_history_and_never_returns_the_true_weights():
    from csafe.demand import estimate_weights

    net = line_net()
    prior = np.ones(7) / 7
    hist = np.array([0] * 80 + [1] * 15 + [6] * 5)
    est = estimate_weights(net, hist, prior, sigma_m=150, prior_share=0.2)
    assert abs(est.sum() - 1) < 1e-9 and est.argmax() == 0 and est[0] > est[6] > 0
    assert (est > 0).all()  # prior keeps unseen nodes possible


def test_rebalance_gives_every_station_a_unit_and_extras_to_the_busiest():
    from csafe.placement import rebalance_stations

    net = line_net()
    w = np.array([0.05, 0.05, 0.05, 0.05, 0.10, 0.30, 0.40])  # east end is busiest
    picked = rebalance_stations(net, np.array([1, 5]), w, k=5)
    counts = {s: int((picked == s).sum()) for s in (1, 5)}
    assert counts[1] >= 1 and counts[5] >= 1 and sum(counts.values()) == 5
    assert counts[5] > counts[1]


def test_rebalance_with_fewer_units_than_stations_picks_the_busiest():
    from csafe.placement import rebalance_stations

    net = line_net()
    w = np.array([0.6, 0.1, 0.1, 0.05, 0.05, 0.05, 0.05])
    assert rebalance_stations(net, np.array([1, 5]), w, k=1).tolist() == [1]


def test_scenario_weights_are_distributions_and_black_spots_get_more():
    from pathlib import Path as P
    from csafe.demand import scenario_weights

    net = line_net()
    for kind in ("pcr", "fire", "ambulance", "crash"):
        w = scenario_weights(net, kind)  # no hotspot file: still a valid distribution
        assert abs(w.sum() - 1) < 1e-9 and (w > 0).all()
    csv = P(__file__).resolve().parents[1] / "data" / "hotspots_geocoded.csv"
    if csv.exists():  # a black spot far from this toy line changes nothing; near it, it must add weight
        import pandas as pd
        tmp = P(__file__).with_name("_tmp_spots.csv")
        pd.DataFrame({"name": ["Kalagram light point"], "type": ["road_crash"], "lat": [30.703], "lng": [76.78]}).to_csv(tmp, index=False)
        try:
            w = scenario_weights(net, "crash", str(tmp))
            assert w.argmax() == 3
        finally:
            tmp.unlink()



def test_mexclp_and_worst_sector():
    from csafe.metrics import worst_sector
    from csafe.placement import mexclp
    net = line_net()
    w = np.zeros(net.n); w[0] = w[6] = 0.5            # all demand at the two ends
    pts = mexclp(net, w, 2, reach_s=150, busy_p=0.3, n_candidates=7)
    T = net.travel_times_from(pts)
    assert (T[:, 0] <= 150).any() and (T[:, 6] <= 150).any()   # one unit covers each end
    resp = np.array([100, 400, 100, 100, 500, 600.0])
    ws = worst_sector(resp, np.array([1, 1, 2, 2, 3, 3]), 300, min_n=2)
    assert ws["sector"] == 3 and ws["within_pct"] == 0.0
