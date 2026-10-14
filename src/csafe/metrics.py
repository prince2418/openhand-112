"""Metrics. Headline = share of incidents reached within a target time; mean and p90 reported too."""
from __future__ import annotations

import numpy as np


def summarize(resp_s: np.ndarray, targets_s=(300, 480)) -> dict:
    out = {"n": int(len(resp_s)), "mean_min": float(resp_s.mean() / 60),
           "p50_min": float(np.percentile(resp_s, 50) / 60), "p90_min": float(np.percentile(resp_s, 90) / 60)}
    for T in targets_s:
        out[f"within_{int(T // 60)}min_pct"] = float(100 * (resp_s <= T).mean())
    return out


def worst_sector(resp_s: np.ndarray, sector: np.ndarray, target_s: float, min_n: int = 150) -> dict:
    """The sector with the lowest share reached in time (sectors with at least min_n simulated calls), so a
    placement can't look good by quietly giving up on hard-to-reach areas."""
    best = None
    for s in np.unique(sector[sector > 0]):
        m = sector == s
        if m.sum() < min_n:
            continue
        pct = float(100 * (resp_s[m] <= target_s).mean())
        if best is None or pct < best["within_pct"]:
            best = {"sector": int(s), "within_pct": round(pct, 1), "n": int(m.sum()), "p90_min": round(float(np.percentile(resp_s[m], 90) / 60), 2)}
    return best or {}


def paired_diff(a: np.ndarray, b: np.ndarray, day: np.ndarray, target_s: float,
                n_boot: int = 2000, seed: int = 0) -> dict:
    """b minus a on identical incidents, with a 95% interval from resampling whole days.

    Returns the change in % within target and in mean response (minutes). Negative mean change = b faster.
    """
    rng = np.random.default_rng(seed)
    days = np.unique(day)
    ina, inb = (a <= target_s).astype(float), (b <= target_s).astype(float)
    per_day = np.array([[ina[day == d].sum(), inb[day == d].sum(), a[day == d].sum(), b[day == d].sum(), (day == d).sum()]
                        for d in days])

    def stat(rows):
        s = rows.sum(axis=0)
        return 100 * (s[1] - s[0]) / s[4], (s[3] - s[2]) / s[4] / 60

    point = stat(per_day)
    boots = np.array([stat(per_day[rng.integers(0, len(days), len(days))]) for _ in range(n_boot)])
    lo, hi = np.percentile(boots, [2.5, 97.5], axis=0)
    return {"within_pct_points": point[0], "within_ci95": (float(lo[0]), float(hi[0])),
            "mean_min": point[1], "mean_ci95": (float(lo[1]), float(hi[1]))}
