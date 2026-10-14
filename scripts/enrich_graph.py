"""Raw OSM drive graph -> graph with travel times, keeping the largest strongly connected component.

    python scripts/enrich_graph.py data/chandigarh.graphml data/chandigarh_enriched.graphml

Only ~0.1% of Chandigarh's roads carry a speed limit in OSM, so speeds are imputed from road class (km/h).
These are ASSUMPTIONS; run_benchmark.py rescales them so that the simulated baseline matches the published
average response time.
"""
import sys

import networkx as nx
import osmnx as ox

SPEEDS = {"trunk": 60, "trunk_link": 40, "primary": 50, "primary_link": 35, "secondary": 45, "secondary_link": 30,
          "tertiary": 40, "tertiary_link": 30, "unclassified": 30, "residential": 30, "living_street": 15}

G = ox.load_graphml(sys.argv[1])
G = G.subgraph(max(nx.strongly_connected_components(G), key=len)).copy()
G = ox.add_edge_travel_times(ox.add_edge_speeds(G, hwy_speeds=SPEEDS, fallback=30))
ox.save_graphml(G, sys.argv[2])
print(f"nodes={G.number_of_nodes()} edges={G.number_of_edges()}")
