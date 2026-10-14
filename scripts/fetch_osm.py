"""Fetch Chandigarh emergency facilities from OpenStreetMap -> chandigarh_stations_osm.csv

Run once on a machine with internet (Google Colab works):
    !pip install osmnx pandas
    !python fetch_osm.py
then download chandigarh_stations_osm.csv.

Uses a bounding box instead of a place name, so it does not depend on how
OSM geocodes "Chandigarh". The box is the extent of the road graph we validated.
"""
import os
import sys

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry import box

# (west, south, east, north), same extent as chandigarh.graphml
BBOX = (76.7076, 30.6697, 76.8478, 30.7912)
TAGS = {
    "amenity": ["fire_station", "police", "hospital"],
    "emergency": ["ambulance_station"],
}
KEEP = ["kind", "name", "operator", "addr:sector", "addr:street", "lat", "lng", "osm_type", "osm_id"]


def classify(row) -> str | None:
    """Single label per feature. Fire/ambulance win over generic tags."""
    if row.get("amenity") == "fire_station":
        return "fire"
    if row.get("emergency") == "ambulance_station":
        return "ambulance_station"
    if row.get("amenity") == "police":
        return "police"
    if row.get("amenity") == "hospital":
        return "hospital"
    return None


def build_table(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Turn the raw OSM GeoDataFrame into a flat table with one lat/lng per feature."""
    df = gdf.reset_index()
    # osmnx 1.x names the index columns element_type/osmid, 2.x element/id
    df = df.rename(columns={"element_type": "osm_type", "element": "osm_type", "osmid": "osm_id", "id": "osm_id"})
    # centroids in a projected CRS (UTM 43N) so building polygons give accurate points
    proj = df.to_crs(32643)
    proj["geometry"] = proj.geometry.centroid
    pts = proj.to_crs(4326)
    df["lat"], df["lng"] = pts.geometry.y.values, pts.geometry.x.values
    df["kind"] = df.apply(classify, axis=1)
    df = df[df["kind"].notna()]
    cols = [c for c in KEEP if c in df.columns]
    return pd.DataFrame(df[cols]).sort_values(["kind", "name"], na_position="last").reset_index(drop=True)


# Public Overpass servers. If one is blocked or slow on your network, the next is tried.
# Set OVERPASS_URL="https://.../api" to put your own server first.
MIRRORS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


def download() -> gpd.GeoDataFrame:
    urls = ([os.environ["OVERPASS_URL"]] if os.environ.get("OVERPASS_URL") else []) + MIRRORS
    ox.settings.requests_timeout = 90
    for url in urls:
        ox.settings.overpass_url = url
        print(f"trying {url} ...", flush=True)
        try:
            return ox.features_from_polygon(box(*BBOX), TAGS)
        except Exception as exc:  # network errors differ by osmnx/requests version
            print(f"  failed: {type(exc).__name__}", flush=True)
    sys.exit("All Overpass servers failed from this network. Try a phone hotspot or a VPN, or use Google Colab.")


def main() -> None:
    gdf = download()
    out = build_table(gdf)
    out.to_csv("chandigarh_stations_osm.csv", index=False)
    print(out.groupby("kind").size())
    print("rows without a name:", int(out["name"].isna().sum()))
    print(out[out.kind.isin(["fire", "ambulance_station"])].to_string(index=False))


if __name__ == "__main__":
    main()
