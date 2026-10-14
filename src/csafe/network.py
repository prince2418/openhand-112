"""Road network: sparse travel-time graph, snapping, travel-time and distance matrices."""
from __future__ import annotations

import networkx as nx
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

EARTH_R = 6_371_000.0

# importance order, most important first; *_link roads count as their parent class
HIGHWAY_ORDER = ["trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"]


def _hw_class(value) -> str:
    v = value[0] if isinstance(value, (list, tuple)) else value
    v = str(v).replace("_link", "")
    return v if v in HIGHWAY_ORDER else "residential"


class RoadNet:
    """Directed road graph as a sparse matrix of travel times in seconds."""

    def __init__(self, G: nx.MultiDiGraph):
        self.G = G
        self.nodes = list(G.nodes)
        self.index = {n: i for i, n in enumerate(self.nodes)}
        n = len(self.nodes)
        self.lat = np.array([float(G.nodes[v]["y"]) for v in self.nodes])
        self.lon = np.array([float(G.nodes[v]["x"]) for v in self.nodes])

        best: dict[tuple[int, int], float] = {}
        rank = np.full(n, len(HIGHWAY_ORDER) - 1)  # best (lowest) rank of any incident road
        for u, v, d in G.edges(data=True):
            key = (self.index[u], self.index[v])
            t = float(d["travel_time"])
            if key not in best or t < best[key]:
                best[key] = t
            r = HIGHWAY_ORDER.index(_hw_class(d.get("highway", "residential")))
            rank[key[0]] = min(rank[key[0]], r)
            rank[key[1]] = min(rank[key[1]], r)
        rows, cols = zip(*best.keys())
        self.A = sp.csr_matrix((list(best.values()), (rows, cols)), shape=(n, n))
        self.node_class = np.array([HIGHWAY_ORDER[r] for r in rank])

        self._lat0 = float(self.lat.mean())
        self._tree = cKDTree(self._xy(self.lat, self.lon))

    @classmethod
    def from_graphml(cls, path: str) -> "RoadNet":
        import osmnx as ox

        return cls(ox.load_graphml(path))

    def _xy(self, lat, lon) -> np.ndarray:
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        x = np.radians(lon) * np.cos(np.radians(self._lat0)) * EARTH_R
        y = np.radians(lat) * EARTH_R
        return np.column_stack([x, y])

    @property
    def n(self) -> int:
        return len(self.nodes)

    def snap(self, lat, lon) -> np.ndarray:
        """Nearest graph node index for each (lat, lon)."""
        _, idx = self._tree.query(self._xy(np.atleast_1d(lat), np.atleast_1d(lon)))
        return np.asarray(idx, dtype=int)

    def snap_distance_m(self, lat, lon) -> np.ndarray:
        d, _ = self._tree.query(self._xy(np.atleast_1d(lat), np.atleast_1d(lon)))
        return d

    def travel_times_from(self, src: np.ndarray) -> np.ndarray:
        """(len(src), n) seconds along the fastest path from each source node to every node."""
        return dijkstra(self.A, directed=True, indices=np.asarray(src, dtype=int))

    def straight_line_from(self, src: np.ndarray) -> np.ndarray:
        """(len(src), n) great-circle metres from each source node to every node."""
        src = np.asarray(src, dtype=int)
        la1, lo1 = np.radians(self.lat[src])[:, None], np.radians(self.lon[src])[:, None]
        la2, lo2 = np.radians(self.lat)[None, :], np.radians(self.lon)[None, :]
        a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
        return 2 * EARTH_R * np.arcsin(np.sqrt(a))

    def spread_nodes(self, k: int, seed: int = 0) -> np.ndarray:
        """k nodes spread evenly over the city (farthest-first). DEV PLACEMENT ONLY."""
        rng = np.random.default_rng(seed)
        xy = self._xy(self.lat, self.lon)
        chosen = [int(rng.integers(self.n))]
        d = np.linalg.norm(xy - xy[chosen[0]], axis=1)
        while len(chosen) < k:
            nxt = int(np.argmax(d))
            chosen.append(nxt)
            d = np.minimum(d, np.linalg.norm(xy - xy[nxt], axis=1))
        return np.array(chosen, dtype=int)


# ---- routing helpers used by the live app -------------------------------------------------------

def _times_to(self: RoadNet, dst: int) -> np.ndarray:
    """Seconds from every node TO dst (one Dijkstra on the reversed graph)."""
    if not hasattr(self, "_AT"):
        self._AT = self.A.T.tocsr()
    return dijkstra(self._AT, directed=True, indices=int(dst))


def _route(self: RoadNet, src: int, dst: int) -> list[int]:
    """Fastest path as a list of node indices (empty if unreachable)."""
    dist, pred = dijkstra(self.A, directed=True, indices=int(src), return_predecessors=True)
    if not np.isfinite(dist[dst]):
        return []
    path, v = [int(dst)], int(dst)
    while v != src:
        v = int(pred[v])
        if v < 0:
            return []
        path.append(v)
    return path[::-1]


def _path_geometry(self: RoadNet, path: list[int]) -> tuple[list[list[float]], list[float]]:
    """[lng, lat] points along the path (using OSM edge shapes where present) and cumulative base seconds
    at each path node."""
    coords, cum, t = [], [0.0], 0.0
    for a, b in zip(path[:-1], path[1:]):
        u, v = self.nodes[a], self.nodes[b]
        data = min(self.G[u][v].values(), key=lambda d: float(d["travel_time"]))
        t += float(data["travel_time"]); cum.append(t)
        geom = data.get("geometry")
        pts = list(geom.coords) if geom is not None and hasattr(geom, "coords") else [(self.lon[a], self.lat[a]), (self.lon[b], self.lat[b])]
        if coords and pts and [round(pts[0][0], 7), round(pts[0][1], 7)] == [round(coords[-1][0], 7), round(coords[-1][1], 7)]:
            pts = pts[1:]
        coords.extend([[float(x), float(y)] for x, y in pts])
    if not coords and path:
        coords = [[float(self.lon[path[0]]), float(self.lat[path[0]])]]
    return coords, cum


def _m(a, b) -> float:
    """Metres between two [lng, lat] points (equirectangular; fine at city scale)."""
    k = np.cos(np.radians((a[1] + b[1]) / 2))
    return float(np.hypot((b[0] - a[0]) * k, b[1] - a[1]) * 111_320)


def _path_timed(self: RoadNet, path: list[int]) -> tuple[list[list[float]], list[float], list[float]]:
    """Like path_geometry, but with base seconds and metres at every geometry point: each edge's travel
    time is spread along its shape by distance, so a unit moves faster on arterials than in lanes."""
    coords: list[list[float]] = []
    secs: list[float] = []
    mets: list[float] = []
    t = d = 0.0
    for a, b in zip(path[:-1], path[1:]):
        u, v = self.nodes[a], self.nodes[b]
        data = min(self.G[u][v].values(), key=lambda e: float(e["travel_time"]))
        geom = data.get("geometry")
        pts = [list(map(float, p)) for p in geom.coords] if geom is not None and hasattr(geom, "coords") \
            else [[float(self.lon[a]), float(self.lat[a])], [float(self.lon[b]), float(self.lat[b])]]
        seg = [_m(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        L = sum(seg) or 1.0
        tt = float(data["travel_time"])
        if not coords:
            coords.append(pts[0]); secs.append(t); mets.append(d)
        acc = 0.0
        for i, sl in enumerate(seg):
            acc += sl
            coords.append(pts[i + 1]); secs.append(t + tt * acc / L); mets.append(d + acc)
        t += tt; d += L
    if not coords and path:
        coords, secs, mets = [[float(self.lon[path[0]]), float(self.lat[path[0]])]], [0.0], [0.0]
    return coords, secs, mets


RoadNet.path_timed = _path_timed
RoadNet.times_to = _times_to
RoadNet.route = _route
RoadNet.path_geometry = _path_geometry
