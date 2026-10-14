"""Waterlogging: the water model, its checks against reported floods, and the plan in the live app."""
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["GEMINI_API_KEY"] = ""

from csafe import flood as F  # noqa: E402


@pytest.fixture(scope="module")
def spots():
    s = F.load_spots()
    F.calibrate(s)
    return s


def test_ordinary_rain_floods_nothing_and_2023_list_is_reproduced(spots):
    c = F.holdout_check(spots)
    assert c["shower_closed"] == 0 and c["shower_diverted"] == 0
    assert c["heavy_closed"] == 0
    # held out of fitting: the traffic police avoid-list of 9 Jul 2023
    assert c["t23_diverted_or_closed"] >= c["t23_listed"] - 1


def test_fitted_storm_floods_the_reported_places(spots):
    rep = [s for s in spots if "T24" in s.sources]
    peak = F.simulate(np.array(F.E24), rep).max(axis=0)
    assert (peak >= F.DIVERT_CM).all()


def test_pumps_never_make_it_worse(spots):
    r = F.run(F.SCENARIOS["jul2023"]["hourly"], spots, "08:30")
    assert r["closed_hours"] <= r["closed_hours_no_pump"]
    for s in r["spots"]:
        assert max(s["depth"]) <= max(s["depth_no_pump"]) + 1e-9


def test_more_rain_more_water(spots):
    a = F.simulate(np.array([30, 30, 0, 0]), spots).max()
    b = F.simulate(np.array([50, 50, 0, 0]), spots).max()
    assert b > a


def test_synthetic_monsoons_near_imd_normal():
    S = F.synthetic_seasons(60)
    st = F.rain_stats(S)
    assert 650 < st["season_mm_mean"] < 1050      # IMD normal 844.9 mm


def test_live_rain_parsing(monkeypatch):
    now = datetime(2026, 8, 10, 15, 20)
    times = [f"2026-08-09T{h:02d}:00" for h in range(24)] + [f"2026-08-10T{h:02d}:00" for h in range(24)] + [f"2026-08-11T{h:02d}:00" for h in range(24)]
    mm = [0.0] * 72
    mm[24 + 15] = 22.0
    body = json.dumps({"hourly": {"time": times, "precipitation": mm}}).encode()
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(body))
    live = F.fetch_live(now=now)
    assert live["hourly"][live["now_index"]] == 22.0 and live["now_index"] == 24 and len(live["hourly"]) == 37


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from csafe.api import server
    server.gemini = None
    return server, TestClient(server.app)


def test_plan_closes_roads_and_routes_go_around(client):
    server, c = client
    p = c.post("/api/flood/start", json={"scenario": "jul2023"}).json()
    assert p["counts"]["close"] >= 3
    closes = [a for a in p["actions"] if a["kind"] == "close"]
    assert closes and all(a["barricades"] for a in closes)
    assert any(a["diversion"] and a["diversion"]["path"] for a in closes)
    w = server.world
    shut = [n for n, v in w.flood.node_level.items() if v >= 3]
    # a unit sent past a closed spot never drives through it
    inc_call = {"transcript": "Sector 22 market mein aadmi behosh hai"}
    r = c.post("/api/calls", data=inc_call).json()["incident"]
    d = c.post(f"/api/incidents/{r['id']}/dispatch", json={}).json()
    assert d["status"] == "dispatched"
    shut_pts = {(round(float(w.net.lon[n]), 5), round(float(w.net.lat[n]), 5)) for n in shut}
    for u in d["units"]:
        pts = {(round(x, 5), round(y, 5)) for x, y in w.units[u].route}
        assert not (pts & shut_pts), "route drives through a closed, flooded spot"
    st = c.get("/api/state").json()["conditions"]["flood"]
    assert st["closed"] == p["counts"]["close"] and st["seg_closed"]


def test_incident_inside_flood_is_reachable(client):
    server, c = client
    w = server.world
    shut = [n for n, v in w.flood.node_level.items() if v >= 3]
    assert shut
    t = w._target(shut[0])
    assert t not in shut
    assert np.isfinite(w.net.times_to(t)).sum() > 1000


def test_scrub_pumps_and_advisory(client):
    server, c = client
    p0 = c.post("/api/flood/apply", json={"step": 0}).json()
    assert p0["counts"]["close"] == 0
    off = c.post("/api/flood/apply", json={"step": 60, "pumps": False}).json()
    on = c.post("/api/flood/apply", json={"step": 60, "pumps": True}).json()
    assert off["counts"]["close"] >= on["counts"]["close"]
    a = c.post("/api/flood/advisory").json()
    assert a["by"] == "template" and "112" in a["advisory"]["english"] and len(a["advisory"]["sms"]) <= 160
    assert c.post("/api/flood/start", json={"scenario": "custom", "mm_h": 0, "hours": 2}).status_code == 400
    assert c.delete("/api/flood").json() == {"active": False}
    assert c.get("/api/state").json()["conditions"]["flood"] is None


def test_risk_table(client):
    server, c = client
    r = c.get("/api/flood/risk").json()
    assert len(r["rows"]) == len(server.world.flood.spots)
    assert r["rows"][0]["closures_per_season"] >= r["rows"][-1]["closures_per_season"]
    assert r["info"]["real"] in (True, False)
