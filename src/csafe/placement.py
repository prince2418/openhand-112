"""Where should idle units wait? Greedy maximum-coverage placement, weighted by incident risk.

Pick k standby nodes so that as much incident risk as possible is reachable within a time
limit; once everything is covered, keep adding units where they cut the risk-weighted average
travel time the most.
"""
from __future__ import annotations

import numpy as np

from .network import RoadNet


def greedy_cover(M: np.ndarray, weights: np.ndarray, k: int, reach_s: float) -> np.ndarray:
    """M: (candidates, N) travel seconds. Returns k candidate row indices (distinct)."""
    reach = M <= reach_s
    covered = np.zeros(M.shape[1], dtype=bool)
    best = np.full(M.shape[1], np.inf)
    chosen: list[int] = []
    for _ in range(k):
        gain = (reach & ~covered) @ weights
        gain[chosen] = -1.0
        c = int(np.argmax(gain))
        if gain[c] <= 1e-12:  # nothing left to cover: reduce weighted average travel time instead
            saving = (np.maximum(best[None, :] - M, 0.0) * weights).sum(axis=1) if np.isfinite(best).any() \
                else -(M * weights).sum(axis=1)
            saving[chosen] = -np.inf
            c = int(np.argmax(saving))
        chosen.append(c)
        covered |= reach[c]
        best = np.minimum(best, M[c])
    return np.array(chosen, dtype=int)


def rebalance_stations(net: RoadNet, stations: np.ndarray, weights: np.ndarray, k: int) -> np.ndarray:
    """Keep units at the existing stations, but share them out by forecast demand.

    Each station's catchment = the road nodes it reaches fastest. Every station keeps at least one
    unit (if k allows); extra units go one at a time to the station with the highest demand per
    unit (D'Hondt). Returns k station node indices (with repeats).
    """
    stations = np.unique(np.asarray(stations, dtype=int))
    M = net.travel_times_from(stations)
    demand = np.bincount(M.argmin(axis=0), weights=weights, minlength=len(stations))
    if k < len(stations):  # fewer units than stations: pick the stations that cover the most risk
        return stations[np.argsort(-demand)[:k]]
    n = np.ones(len(stations), dtype=int)
    for _ in range(k - len(stations)):
        n[np.argmax(demand / (n + 1))] += 1
    return np.repeat(stations, n)


def best_new_sites(net: RoadNet, existing: np.ndarray, weights: np.ndarray, n_new: int, reach_s: float,
                   n_candidates: int = 600, seed: int = 0) -> np.ndarray:
    """Where to build n_new stations, given the existing ones: greedy on risk newly reachable in time."""
    cand = net.spread_nodes(min(n_candidates, net.n), seed=seed)
    M = net.travel_times_from(cand)
    covered = (net.travel_times_from(np.unique(existing)) <= reach_s).any(axis=0)
    chosen: list[int] = []
    for _ in range(n_new):
        gain = ((M <= reach_s) & ~covered) @ weights
        gain[chosen] = -1.0
        c = int(np.argmax(gain))
        chosen.append(c)
        covered |= M[c] <= reach_s
    return cand[chosen]


def optimise_placement(net: RoadNet, weights: np.ndarray, k: int, reach_s: float,
                       n_candidates: int = 600, seed: int = 0) -> np.ndarray:
    """k standby nodes (graph node indices). Candidates are spread evenly over the city.

    reach_s is in the same (unscaled) units as the travel-time matrix: pass
    (target - call handling) / (speed_scale * typical traffic multiplier).
    """
    cand = net.spread_nodes(min(n_candidates, net.n), seed=seed)
    M = net.travel_times_from(cand)
    return cand[greedy_cover(M, weights, k, reach_s)]


def mexclp(net: RoadNet, weights: np.ndarray, k: int, reach_s: float, busy_p: float,
           n_candidates: int = 600, seed: int = 0) -> np.ndarray:
    """Maximum Expected Covering Location Problem (Daskin 1983), the textbook ambulance-placement model.

    Each unit is busy with probability busy_p, so a place covered by c units is served in time with
    probability 1 - busy_p**c. Units may share a site. Solved greedily (Daskin's own heuristic): add
    the site with the largest gain in expected covered demand, k times.
    """
    cand = net.spread_nodes(min(n_candidates, net.n), seed=seed)
    reach = net.travel_times_from(cand) <= reach_s
    count = np.zeros(net.n)
    chosen: list[int] = []
    for _ in range(k):
        gain = reach @ (weights * (1 - busy_p) * busy_p ** count)
        c = int(np.argmax(gain))
        chosen.append(c)
        count += reach[c]
    return cand[chosen]
