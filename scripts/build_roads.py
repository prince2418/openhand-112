"""Named arterial roads from our OSM graph -> data/roads.json (points along each road), for reading places
like "Jan Marg near Sector 17" or "Jan Marg and Madhya Marg crossing" in a call.  python scripts/build_roads.py"""
import json
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
CANON = {"Himalya Marg": "Himalaya Marg", "Parv Marg": "Purv Marg"}
KEEP = {"Jan Marg", "Madhya Marg", "Dakshin Marg", "Purv Marg", "Uttar Marg", "Himalaya Marg", "Vidya Marg", "Pashchim Marg",
        "Sarovar Path", "Chandi Path", "Udyan Path", "Sukhna Path", "Udyog Path", "Vigyan Path", "Shanti Path", "NH5"}

G = nx.read_graphml(ROOT / "data/chandigarh_enriched.graphml")
roads: dict[str, dict] = {}
for u, v, d in G.edges(data=True):
    raw = d.get("name")
    names = []
    if raw:
        names = [n.strip(" '[]") for n in raw.split(",")] if raw.startswith("[") else [raw]
    for n in names:
        n = CANON.get(n, n)
        if n not in KEEP:
            continue
        for node in (u, v):
            nd = G.nodes[node]
            roads.setdefault(n, {})[node] = [round(float(nd["y"]), 5), round(float(nd["x"]), 5)]
out = {n: {"points": list(p.values()), "nodes": list(p.keys())} for n, p in roads.items()}
(ROOT / "data/roads.json").write_text(json.dumps(out))
print({n: len(v["points"]) for n, v in out.items()})
