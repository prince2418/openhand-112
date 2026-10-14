"""Group calls about the same incident so repeat calls raise priority (lesson from Itaewon, 2022:
11 calls over ~4 hours, only 4 dispatches). Same type group + close in space and time = same incident."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

WINDOW_S = 30 * 60
RADIUS_M = 400
GROUP = {"road_accident": "road", "fire": "fire", "medical": "medical", "crime_violent": "crime",
         "crime_property": "crime", "crowd": "crowd", "waterlogging": "water", "other_emergency": "other",
         "non_emergency": "none"}


@dataclass
class Cluster:
    group: str
    lat: float | None
    lng: float | None
    key: str | None          # sector/landmark text when no coordinates
    last_t: float
    call_ids: list = field(default_factory=list)


def _dist_m(a, b):
    return 111_190 * math.hypot(a[0] - b[0], (a[1] - b[1]) * math.cos(math.radians(a[0])))


class RepeatTracker:
    def __init__(self):
        self.clusters: list[Cluster] = []

    def add(self, call_id, t: float, incident_type: str, lat=None, lng=None, key: str | None = None) -> int:
        """Register a call; return how many calls (including this one) concern the same incident."""
        g = GROUP.get(incident_type, "other")
        if g == "none":
            return 1
        for c in self.clusters:
            if c.group != g or t - c.last_t > WINDOW_S:
                continue
            same = (lat is not None and c.lat is not None and _dist_m((lat, lng), (c.lat, c.lng)) <= RADIUS_M) or \
                   (key is not None and key == c.key)
            if same:
                c.call_ids.append(call_id); c.last_t = t
                return len(c.call_ids)
        self.clusters.append(Cluster(g, lat, lng, key, t, [call_id]))
        return 1
