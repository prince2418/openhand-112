"""Predict and monitor (forecast, live watch, van moves) and the open-platform layer (outbox, CAP, open data)."""
import os
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["GEMINI_API_KEY"] = ""


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from csafe.api import server
    server.gemini = None
    c = TestClient(server.app)
    c.post("/api/reset")
    server.world.hour = lambda: 17
    return c, server


def test_erlang_b():
    from csafe.api.watch import erlang_b
    assert erlang_b(0.0, 3) == 0.0
    assert abs(erlang_b(1.0, 1) - 0.5) < 1e-9          # textbook value
    assert erlang_b(5.0, 3) > erlang_b(5.0, 6)          # more units, less chance all are busy


def test_outlook(client):
    c, _ = client
    o = c.get("/api/predict/outlook").json()
    assert len(o["rows"]) == 6 and o["rows"][0]["hour"] == "17:00"
    p = o["rows"][0]["services"]["police"]
    assert p["low"] <= p["expected"] <= p["high"]
    assert 8 <= p["expected"] <= 30                       # ~300 calls a day, evening share
    assert len(o["zones"]) == 8 and all(z["why"] for z in o["zones"])
    s = o["skill"]
    assert s["hit_pct"] > s["area_pct"] * 1.5             # far better than random
    assert s["hit_pct"] <= s["best_hit_pct"] + 2          # can't beat knowing the truth (bar noise)


def test_spread_and_cluster(client):
    c, server = client
    w = c.get("/api/watch").json()
    spread = [a for a in w["alerts"] if a["kind"] == "prepare"]
    assert spread, "vans parked two to a station should trigger a spread suggestion at the evening peak"
    a = spread[0]
    for m in a["action"]["moves"]:
        assert c.post(f"/api/units/{m['unit']}/reposition", json={"lat": m["lat"], "lng": m["lng"]}).status_code == 200
    server.world.watcher._cache = (0.0, None)
    cov = c.get("/api/watch").json()["coverage"]
    assert cov["now"] >= a["moves"][0]["gain"] + 50         # vans in transit already count from their new spot
    assert not any(x["kind"] == "coverage" for x in c.get("/api/watch").json()["alerts"])
    # three different incidents close together within minutes: unusual
    for t in ["Sector 29 light point pe do bike takra gayi, ek ladka ghayal pada hai",
              "ITI Sector 29 ke paas jhagda ho raha hai, log dande se maar rahe hai",
              "Tribune Chowk ke paas ek gaadi mein aag lag gayi hai, dhuan nikal raha hai"]:
        assert c.post("/api/calls", data={"transcript": t}).status_code == 200
    server.world.watcher._cache = (0.0, None)
    cl = [x for x in c.get("/api/watch").json()["alerts"] if x["kind"] == "cluster"]
    assert cl and cl[0]["observed"] == 3 and cl[0]["p"] < 0.01


def test_outbox_cap_open_data(client):
    c, server = client
    inc = next(iter(server.world.incidents.values()))
    rec = inc.recommendation or {}
    unit = next(r["best"]["unit"] for r in rec.values() if r.get("best"))
    assert c.post(f"/api/incidents/{inc.id}/dispatch", json={"units": [unit]}).status_code == 200
    msgs = c.get("/api/dpi/outbox").json()["messages"]
    what = {m["what"] for m in msgs}
    assert {"Incident record", "Dispatch order", "Unit move order"} <= what
    assert all(m["simulated"] for m in msgs)
    assert all("transcript" not in str(m["payload"]) for m in msgs)
    # open data: no caller words, place on a grid
    g = c.get("/api/open/incidents.geojson").json()
    f = g["features"][0]
    assert "transcript" not in f["properties"] and "summary" not in f["properties"]
    lng, lat = f["geometry"]["coordinates"]
    assert abs(lat / 0.005 - round(lat / 0.005)) < 1e-6
    assert c.get("/api/open/incidents.csv").text.startswith("id,hour,type")
    # CAP 1.2 from a rain plan
    assert c.get("/api/dpi/cap/flood.xml").status_code == 404
    assert c.post("/api/flood/start", json={"scenario": "jul2023"}).status_code == 200
    x = c.get("/api/dpi/cap/flood.xml")
    assert x.status_code == 200
    root = ET.fromstring(x.text)
    ns = {"c": "urn:oasis:names:tc:emergency:cap:1.2"}
    assert root.find("c:status", ns).text == "Exercise"
    infos = root.findall("c:info", ns)
    assert {i.find("c:language", ns).text for i in infos} == {"en-IN", "hi-IN", "pa-IN"}
    assert infos[0].find("c:area/c:circle", ns) is not None
    assert c.post("/api/dpi/cap/flood/send").json()["format"] == "xml"
    assert len(c.get("/api/dpi/catalogue").json()["interfaces"]) >= 8
