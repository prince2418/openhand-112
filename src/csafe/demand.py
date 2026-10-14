"""Synthetic demand: where and when incidents happen. Every constant here is an ASSUMPTION.

Real Chandigarh incident-level data is not public, so the generator is calibrated only to
published totals (calls per day) and the shape below. Replace HOURLY_PROFILE / CLASS_WEIGHT
if better data becomes available.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .network import RoadNet

# share of daily calls per hour (index = hour of day); normalised below
_RAW_HOURLY = np.array([
    0.022, 0.017, 0.014, 0.013, 0.015, 0.022, 0.034, 0.050, 0.061, 0.064, 0.062, 0.060,
    0.058, 0.055, 0.052, 0.053, 0.058, 0.066, 0.070, 0.068, 0.056, 0.044, 0.034, 0.026,
])
HOURLY_PROFILE = _RAW_HOURLY / _RAW_HOURLY.sum()

# relative incident intensity by the most important road touching a node
CLASS_WEIGHT = {
    "trunk": 4.0, "primary": 4.0, "secondary": 3.0, "tertiary": 1.5,
    "unclassified": 1.0, "residential": 1.0, "living_street": 0.5,
}

# travel-time multiplier by hour (>1 = slower than free flow)
_TOD = np.array([0.85] * 6 + [1.0] * 2 + [1.35] * 3 + [1.1] * 6 + [1.4] * 4 + [0.95] * 3)


def tod_multiplier(hour) -> np.ndarray | float:
    return _TOD[np.asarray(hour, dtype=int) % 24] if np.ndim(hour) else float(_TOD[int(hour) % 24])


def flat_multiplier(hour):
    """No time-of-day effect (used in tests)."""
    return np.ones_like(hour, dtype=float) if np.ndim(hour) else 1.0


def node_weights(net: RoadNet, hotspots: list[tuple[float, float, float]] | None = None,
                 sigma_m: float = 400.0) -> np.ndarray:
    """Probability that an incident happens at each node (sums to 1).

    hotspots: optional list of (lat, lng, multiplier); each adds a Gaussian bump.
    """
    w = np.array([CLASS_WEIGHT[c] for c in net.node_class], dtype=float)
    if hotspots:
        xy = net._xy(net.lat, net.lon)
        for lat, lng, mult in hotspots:
            h = net._xy([lat], [lng])[0]
            d2 = ((xy - h) ** 2).sum(axis=1)
            w = w * (1 + (mult - 1) * np.exp(-d2 / (2 * sigma_m**2)))
    return w / w.sum()


def load_hotspots(csv: str, types: tuple[str, ...]) -> list[tuple[float, float]]:
    """(lat, lng) of hotspots of the given types from data/hotspots_geocoded.csv."""
    import pandas as pd

    df = pd.read_csv(csv)
    df = df[df["type"].isin(types)].dropna(subset=["lat", "lng"])
    return list(zip(df["lat"], df["lng"]))


# Multipliers chosen so the generated incidents match a published share (see scenario_weights).
CRASH_HOTSPOT_MULT = 7.0   # -> ~10% of crash demand within 500 m of the 4 official black spots
FIRE_HOTSPOT_MULT = 3.0    # anecdotal fire sites: a mild bump only (ASSUMPTION)
AMBULANCE_TRAUMA_SHARE = 0.25  # share of ambulance calls that are road trauma (ASSUMPTION)


def scenario_weights(net: RoadNet, kind: str, hotspots_csv: str | None = None) -> np.ndarray:
    """Where incidents of each service happen. Every choice below is an ASSUMPTION, labelled.

    pcr       : all police calls (not only crashes) -> busier roads get more, no crash hotspots
    crash     : road crashes -> road class, plus the four 2023-25 official black spots, sized so
                ~10% of demand falls within 500 m of them (published: 24 of 228 deaths, 10.5%)
    ambulance : mostly medical calls at homes -> road-node density as a population proxy,
                plus a trauma share drawn from the crash layer
    fire      : buildings -> node density, mild bumps at reported fire-risk sites
    """
    density = np.ones(net.n) / net.n  # Chandigarh's sector grid: road nodes track built-up area
    if kind == "pcr":
        return node_weights(net)
    if kind == "crash":
        spots = _black_spots(hotspots_csv) if hotspots_csv else []
        return node_weights(net, [(la, lo, CRASH_HOTSPOT_MULT) for la, lo in spots], sigma_m=250)
    if kind == "ambulance":
        crash = scenario_weights(net, "crash", hotspots_csv)
        w = (1 - AMBULANCE_TRAUMA_SHARE) * density + AMBULANCE_TRAUMA_SHARE * crash
        return w / w.sum()
    if kind == "fire":
        spots = load_hotspots(hotspots_csv, ("fire",)) if hotspots_csv else []
        return _bumps(net, density, spots, FIRE_HOTSPOT_MULT, sigma_m=300)
    raise ValueError(kind)


def _black_spots(csv: str) -> list[tuple[float, float]]:
    """The four official 2023-25 black spots (the Hallomajra stretch counted once)."""
    import pandas as pd

    df = pd.read_csv(csv)
    keep = df["name"].str.contains("Hallomajra light point|Kalagram|Housing Board|Milk Colony", regex=True)
    return list(zip(df.loc[keep, "lat"], df.loc[keep, "lng"]))


def _bumps(net: RoadNet, base: np.ndarray, spots, mult: float, sigma_m: float) -> np.ndarray:
    w = base.copy()
    if spots:
        xy = net._xy(net.lat, net.lon)
        for la, lo in spots:
            d2 = ((xy - net._xy([la], [lo])[0]) ** 2).sum(axis=1)
            w = w * (1 + (mult - 1) * np.exp(-d2 / (2 * sigma_m**2)))
    return w / w.sum()


@dataclass
class Incidents:
    t: np.ndarray          # arrival time, seconds from start
    node: np.ndarray       # node index
    service_s: np.ndarray  # time on scene (fixed per incident, so policies are compared fairly)
    noise: np.ndarray      # realised / expected travel time (fixed per incident)

    def __len__(self) -> int:
        return len(self.t)

    @property
    def day(self) -> np.ndarray:
        return (self.t // 86400).astype(int)


def generate(weights: np.ndarray, rate_per_day: float, days: int, seed: int,
             mean_service_s: float, noise_sigma: float = 0.15) -> Incidents:
    """Poisson arrivals by hour of day; node drawn from `weights`."""
    rng = np.random.default_rng(seed)
    times = []
    for d in range(days):
        counts = rng.poisson(rate_per_day * HOURLY_PROFILE)
        for h, c in enumerate(counts):
            times.append(d * 86400 + h * 3600 + rng.uniform(0, 3600, c))
    t = np.sort(np.concatenate(times))
    n = len(t)
    node = rng.choice(len(weights), size=n, p=weights)
    service = rng.exponential(mean_service_s, n)
    noise = rng.lognormal(mean=-0.5 * noise_sigma**2, sigma=noise_sigma, size=n)  # mean 1
    return Incidents(t=t, node=node, service_s=service, noise=noise)


def estimate_weights(net: RoadNet, history_nodes: np.ndarray, prior: np.ndarray,
                     sigma_m: float = 500.0, prior_share: float = 0.2) -> np.ndarray:
    """Demand FORECAST learned from past incidents: counts per node, smoothed over space, blended with a prior.

    This is what a placement optimiser may use in practice. It never sees the weights the simulator
    draws test incidents from, so its advantage cannot come from knowing the answer.
    """
    import scipy.sparse as sp
    from scipy.spatial import cKDTree

    xy = net._xy(net.lat, net.lon)
    tree = cKDTree(xy)
    d = tree.sparse_distance_matrix(tree, 3 * sigma_m, output_type="coo_matrix")
    K = sp.coo_matrix((np.exp(-(d.data**2) / (2 * sigma_m**2)), (d.row, d.col)), shape=d.shape).tocsr()
    K = K + sp.identity(net.n, format="csr")  # distance-0 pairs are dropped by the sparse matrix
    counts = np.bincount(history_nodes, minlength=net.n).astype(float)
    smooth = K @ counts
    smooth = smooth / smooth.sum() if smooth.sum() > 0 else prior
    est = (1 - prior_share) * smooth + prior_share * prior
    return est / est.sum()
