"""Offline test of the OSM script's table logic, using fake OSM features shaped like osmnx 2.x output."""
import sys
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_osm  # noqa: E402


def fake_features():
    idx = pd.MultiIndex.from_tuples([("node", 1), ("way", 2), ("node", 3), ("way", 4), ("node", 5)], names=["element", "id"])
    square = Polygon([(76.78, 30.74), (76.7804, 30.74), (76.7804, 30.7404), (76.78, 30.7404)])
    return gpd.GeoDataFrame(
        {
            "amenity": ["fire_station", "police", None, "hospital", "clinic"],
            "emergency": [None, None, "ambulance_station", None, None],
            "name": ["Fire Station Sector 17", "PS Sector 3", None, "GMSH-16", "Some clinic"],
        },
        geometry=[Point(76.7840, 30.7410), square, Point(76.7716, 30.7497), Point(76.7716, 30.7497), Point(76.79, 30.75)],
        index=idx,
        crs=4326,
    )


def test_table_labels_and_coordinates():
    out = fetch_osm.build_table(fake_features())
    kinds = dict(zip(out["name"].fillna("(unnamed)"), out["kind"]))
    assert kinds["Fire Station Sector 17"] == "fire"
    assert kinds["PS Sector 3"] == "police"
    assert kinds["GMSH-16"] == "hospital"
    assert kinds["(unnamed)"] == "ambulance_station"
    assert "Some clinic" not in kinds  # clinics are not requested
    ps = out[out["name"] == "PS Sector 3"].iloc[0]
    assert abs(ps["lat"] - 30.7402) < 1e-4 and abs(ps["lng"] - 76.7802) < 1e-4  # polygon centroid
    assert out[["lat", "lng"]].notna().all().all()


def test_osmnx1_index_names_also_work():
    g = fake_features()
    g.index.names = ["element_type", "osmid"]
    out = fetch_osm.build_table(g)
    assert "osm_id" in out.columns and len(out) == 4
