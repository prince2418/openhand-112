"""Event-driven dispatch simulation and the three dispatch policies we compare.

Policies
  nearest_distance : free unit with the smallest straight-line distance (what the control room
                     does today: "CAD sends the nearest unit")
  nearest_eta      : free unit with the smallest expected road travel time (GPS/ETA dispatch)
  coverage         : among the best few units by ETA, if any will still arrive within the target
                     time, send the one whose departure leaves the city best covered; otherwise
                     send the fastest.

Every incident carries fixed random draws (service time, travel-time noise), so policies are
compared on identical incidents.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .demand import Incidents, tod_multiplier
from .network import RoadNet

POLICIES = ("nearest_distance", "nearest_eta", "coverage")


@dataclass
class Fleet:
    name: str
    home: np.ndarray   # (U,) node index of each unit's base
    M: np.ndarray      # (U, N) base travel seconds from the unit's base to every node
    D: np.ndarray      # (U, N) straight-line metres from the unit's base to every node

    @property
    def n_units(self) -> int:
        return len(self.home)


def make_fleet(net: RoadNet, home: np.ndarray, name: str = "fleet") -> Fleet:
    home = np.asarray(home, dtype=int)
    uniq, inv = np.unique(home, return_inverse=True)
    return Fleet(name, home, net.travel_times_from(uniq)[inv], net.straight_line_from(uniq)[inv])


@dataclass
class Result:
    response_s: np.ndarray  # call-to-arrival, includes any wait for a free unit
    wait_s: np.ndarray
    unit: np.ndarray
    dispatch_t: np.ndarray
    release_t: np.ndarray   # when the unit is free again


def simulate(fleet: Fleet, inc: Incidents, policy: str, *, weights: np.ndarray,
             speed_scale: float = 1.0, delay_s: float = 60.0, target_s: float = 300.0,
             k_candidates: int = 3, mult_fn: Callable = tod_multiplier) -> Result:
    """Run one policy over one incident stream.

    speed_scale multiplies all travel times (calibration knob). delay_s is call handling before
    dispatch. target_s is the response-time target the coverage policy tries to protect.
    """
    if policy not in POLICIES:
        raise ValueError(policy)
    U, n = fleet.n_units, len(inc)
    free_at = np.zeros(U)
    resp, wait, unit_used = np.zeros(n), np.zeros(n), np.zeros(n, dtype=int)
    disp_t, rel_t = np.zeros(n), np.zeros(n)
    travel_allowance = target_s - delay_s  # travel time that still meets the target

    for i in range(n):
        t, node = inc.t[i], inc.node[i]
        td = max(t, free_at.min())               # wait for a unit if all are busy (first come, first served)
        free = np.flatnonzero(free_at <= td)
        scale = speed_scale * mult_fn(int((td % 86400) // 3600))
        eta = fleet.M[free, node] * scale        # expected travel seconds per free unit

        if policy == "nearest_distance":
            pick = int(np.argmin(fleet.D[free, node]))
        elif policy == "nearest_eta" or len(free) == 1:
            pick = int(np.argmin(eta))
        else:  # coverage
            order = np.argsort(eta)[:k_candidates]
            on_time = [c for c in order if (td - t) + delay_s + eta[c] <= target_s]
            if on_time:
                reach = fleet.M[free] * scale <= travel_allowance   # (free units, N): who covers each node
                sole = reach.sum(axis=0) == 1                       # nodes covered by exactly one free unit
                loss = {c: weights[sole & reach[c]].sum() for c in on_time}
                pick = min(on_time, key=lambda c: (loss[c], eta[c]))
            else:
                pick = int(order[0])

        u = int(free[pick])
        real_travel = eta[pick] * inc.noise[i]
        resp[i] = (td - t) + delay_s + real_travel
        wait[i] = td - t
        unit_used[i], disp_t[i] = u, td
        rel_t[i] = td + delay_s + real_travel + inc.service_s[i] + eta[pick]  # eta[pick] again = drive back to base
        free_at[u] = rel_t[i]

    return Result(resp, wait, unit_used, disp_t, rel_t)


def calibrate_speed(fleet: Fleet, inc: Incidents, *, weights: np.ndarray, target_mean_s: float,
                    delay_s: float = 60.0, lo: float = 0.3, hi: float = 3.0, tol_s: float = 1.0) -> float:
    """Find the travel-time scale at which the nearest-distance policy has the target mean response."""
    for _ in range(40):
        mid = (lo + hi) / 2
        m = simulate(fleet, inc, "nearest_distance", weights=weights, speed_scale=mid, delay_s=delay_s).response_s.mean()
        if abs(m - target_mean_s) < tol_s:
            return mid
        lo, hi = (mid, hi) if m < target_mean_s else (lo, mid)
    return (lo + hi) / 2
