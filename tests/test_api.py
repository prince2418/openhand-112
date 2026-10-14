"""End-to-end API test: a call comes in, gets triaged (keyword fallback, no key), a unit is
recommended, dispatched, drives, and the traffic-police alert lists junctions."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.pop("GEMINI_API_KEY", None)
os.environ["GEMINI_API_KEY"] = ""


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from csafe.api import server
    server.gemini = None
    return TestClient(server.app)


def test_call_to_dispatch_flow(client):
    r = client.post("/api/calls", data={"transcript": "Tribune Chowk pe accident, ek aadmi behosh hai, khoon beh raha hai"})
    assert r.status_code == 200, r.text
    inc = r.json()["incident"]
    assert inc["triage"]["note"].startswith("Triaged by the keyword fallback")
    assert inc["triage"]["decision"]["priority"] == "P1"
    assert inc["lat"] is not None, "Tribune Chowk is a known landmark"
    rec = inc["recommendation"]
    assert set(rec) == set(inc["triage"]["decision"]["units"])
    for kind, rr in rec.items():
        assert rr["best"]["eta_s"] <= rr["nearest_by_distance"]["eta_s"]  # fastest by road is never slower
    d = client.post(f"/api/incidents/{inc['id']}/dispatch", json={}).json()
    assert d["status"] == "dispatched" and d["units"] and d["corridor"]["routes"][0]["route"]
    st = client.get("/api/state").json()
    sent = [u for u in st["units"] if u["id"] in d["units"]]
    assert all(u["status"] == "en_route" for u in sent)
    a = client.post(f"/api/incidents/{inc['id']}/notify-traffic").json()
    assert a["incident"] == inc["id"]


def test_unknown_location_then_dispatcher_sets_it(client):
    r = client.post("/api/calls", data={"transcript": "please come fast, he is not breathing"}).json()["incident"]
    assert r["lat"] is None and r["recommendation"] is None and r["triage"]["decision"]["needs_human_review"]
    r2 = client.post(f"/api/incidents/{r['id']}/location", json={"lat": 30.7333, "lng": 76.7794}).json()
    assert r2["recommendation"]["ambulance"]["best"] is not None
    assert not any("location" in x for x in r2["triage"]["decision"]["review_reasons"])


def test_repeat_calls_merge_and_escalate(client):
    ids, pri = set(), []
    for i in range(3):
        j = client.post("/api/calls", data={"transcript": "Sector 23 mandir mein bheed bahut hai, dhakka mukki"}).json()
        ids.add(j["incident"]["id"]); pri.append(j["incident"]["triage"]["decision"]["priority"])
    assert len(ids) == 1 and j["merged"] and j["incident"]["calls"] == 3 and pri[-1] == "P1"


def test_layers_and_samples(client):
    assert client.get("/api/risk?kind=crash").json()["cells"]
    assert len(client.get("/api/samples").json()) == 84   # 52 Hindi/Punjabi/English + 32 in 8 more Indian languages
    assert len(client.get("/api/standby").json()["points"]) == 31
    assert client.post("/api/calls", data={"transcript": " "}).status_code == 400


def _fast_forward(client, sim_s):
    from csafe.api import server
    from csafe.api.world import DEMO_SPEED
    server.world.t0_wall -= sim_s / DEMO_SPEED


def test_incident_runs_to_a_close(client):
    inc = client.post("/api/calls", data={"transcript": "PGI ke bahar accident hua hai, ek aadmi behosh hai"}).json()["incident"]
    d = client.post(f"/api/incidents/{inc['id']}/dispatch", json={}).json()
    assert client.post(f"/api/incidents/{inc['id']}/close").status_code == 409   # can't close while units drive
    _fast_forward(client, 1500)                     # long enough to drive (< 25 min) and see the patient
    st = client.get("/api/state").json()
    i = next(x for x in st["incidents"] if x["id"] == inc["id"])
    assert i["status"] == "resolved" and i["outcome"]["first_on_scene_s"] >= 60
    assert set(i["outcome"]["per_unit_s"]) == set(d["units"])
    kinds = [e["kind"] for e in i["events"]]
    assert kinds[0] == "call" and "dispatch" in kinds and "arrive" in kinds and kinds[-1] in ("resolved", "clear")
    assert all(u["status"] in ("returning", "available") for u in st["units"] if u["id"] in d["units"])
    _fast_forward(client, 3000)
    st = client.get("/api/state").json()
    assert all(u["status"] == "available" for u in st["units"] if u["id"] in d["units"])


def test_dispatcher_closes_non_emergency(client):
    inc = client.post("/api/calls", data={"transcript": "mera bijli ka bill galat aaya hai, complaint karni hai"}).json()["incident"]
    assert inc["triage"]["decision"]["units"] == []
    c = client.post(f"/api/incidents/{inc['id']}/close").json()
    assert c["status"] == "resolved" and c["outcome"]["closed_by"] == "dispatcher"


def test_slow_gemini_falls_back_then_upgrades(client):
    """Gemini slower than the wait limit: keyword triage answers at once, Gemini's reading replaces it later."""
    import time as _t
    from csafe.api import server
    from csafe.triage.client import FakeTriage
    from csafe.triage.schema import Extract

    def slow(text):
        _t.sleep(1.5)
        return Extract(incident_type="medical", unconscious_or_not_breathing=True, immediate_life_threat=True,
                       landmark="PGIMER", summary_en="Man collapsed outside PGI, not breathing", confidence=0.95)
    old_g, old_w = server.gemini, server.GEMINI_WAIT_S
    server.gemini, server.GEMINI_WAIT_S = FakeTriage(slow), 0.3
    try:
        t0 = _t.time()
        inc = client.post("/api/calls", data={"transcript": "PGI ke bahar ek aadmi gir gaya hai"}).json()["incident"]
        assert _t.time() - t0 < 1.4 and "keyword fallback" in inc["triage"]["note"]
        _t.sleep(2.0)
        i = next(x for x in client.get("/api/state").json()["incidents"] if x["id"] == inc["id"])
        assert i["triage"]["extract"]["summary_en"].startswith("Man collapsed") and i["triage"]["decision"]["priority"] == "P1"
        assert i["triage"]["note"] is None and "replaced the keyword reading" in i["events"][-1]["text"]
    finally:
        server.gemini, server.GEMINI_WAIT_S = old_g, old_w


def test_gemini_keeps_retrying_in_background(client):
    """Gemini fails twice after the fallback answered; the background retries get its reading onto the card."""
    import time as _t
    from csafe.api import server
    from csafe.triage.client import FakeTriage
    from csafe.triage.schema import Extract
    n = {"calls": 0}

    def flaky(text):
        n["calls"] += 1
        _t.sleep(0.4)
        if n["calls"] < 3:
            raise RuntimeError("503 UNAVAILABLE high demand")
        return Extract(incident_type="crime_violent", violence_ongoing=True, people_injured=1, location_text="Jan Marg near Sector 17",
                       summary_en="Person bleeding on Jan Marg after an assault", confidence=0.9)
    saved = server.gemini, server.GEMINI_WAIT_S, server.RETRY_BASE_S
    server.gemini, server.GEMINI_WAIT_S, server.RETRY_BASE_S = FakeTriage(flaky), 0.1, 0.2
    try:
        inc = client.post("/api/calls", data={"transcript": "jan marg pe kisi ka khoon nikal raha hai"}).json()["incident"]
        assert inc["gemini"]["state"] == "trying" and inc["triage"]["location"]["road"] == "Jan Marg"
        for _ in range(40):
            _t.sleep(0.2)
            i = next(x for x in client.get("/api/state").json()["incidents"] if x["id"] == inc["id"])
            if i["gemini"]["state"] == "done":
                break
        assert i["gemini"]["state"] == "done" and i["gemini"]["attempt"] == 3
        assert i["triage"]["decision"]["priority"] == "P1" and i["lat"] is not None   # Gemini's place resolved on Jan Marg
    finally:
        server.gemini, server.GEMINI_WAIT_S, server.RETRY_BASE_S = saved


def test_sexual_violence_fast_path(client):
    """Rape/harassment words: police sent at once (no Gemini wait), ambulance only offered; no place yet -> sent
    the moment the dispatcher marks it."""
    import time as _t
    from csafe.api import server
    from csafe.triage.client import FakeTriage

    def never(text):
        _t.sleep(5)
        raise RuntimeError("503 UNAVAILABLE")
    saved = server.gemini, server.GEMINI_WAIT_S
    server.gemini, server.GEMINI_WAIT_S = FakeTriage(never), 20
    try:
        t0 = _t.time()
        inc = client.post("/api/calls", data={"transcript": "ek ladki ka rape hogya Elante mall mein"}).json()["incident"]
        assert _t.time() - t0 < 2, "must not wait for Gemini"
        st = client.get("/api/state").json()
        sent = [u for u in st["units"] if u["id"] in inc["units"]]
        assert inc["status"] == "dispatched" and inc["fast"] == "rape" and inc["triage"]["decision"]["priority"] == "P1"
        assert [u["kind"] for u in sent] == ["police"]
        assert inc["extra"] and "ambulance" in inc["extra"]
        # dispatcher adds the ambulance
        amb = inc["extra"]["ambulance"]["best"]["unit"]
        d = client.post(f"/api/incidents/{inc['id']}/dispatch", json={"units": [amb]}).json()
        assert amb in d["units"] and not d["extra"]
        # no place given: police go as soon as it is marked
        j = client.post("/api/calls", data={"transcript": "koi ladki ka peecha kar raha hai, bachao"}).json()["incident"]
        assert j["status"] == "new" and j["fast"]
        j2 = client.post(f"/api/incidents/{j['id']}/location", json={"lat": 30.7387, "lng": 76.7820}).json()
        assert j2["status"] == "dispatched" and len(j2["units"]) == 1 and j2["units"][0].startswith("P")
    finally:
        server.gemini, server.GEMINI_WAIT_S = saved


def test_what_if_controls_and_junction_windows(client):
    from csafe.api import server
    inc = client.post("/api/calls", data={"transcript": "Tribune Chowk pe accident, ek aadmi behosh hai"}).json()["incident"]
    eta0 = inc["recommendation"]["police"]["best"]["eta_s"]
    # fog: same unit, ~1.5x slower
    c = client.post("/api/conditions", json={"fog": True}).json()
    assert c["fog"]
    i = next(x for x in client.get("/api/state").json()["incidents"] if x["id"] == inc["id"])
    assert i["recommendation"]["police"]["best"]["eta_s"] >= 1.4 * eta0
    client.post("/api/conditions", json={"fog": False})
    # night shift: 20 PCR on duty
    c = client.post("/api/conditions", json={"night": True}).json()
    assert c["pcr_on_duty"] == 20 and client.get("/api/state").json()["free"]["police"] <= 20
    client.post("/api/conditions", json={"night": False})
    # close the road right in front of the best unit's route: ETA must not get faster, closure is listed
    w = server.world
    best = inc["recommendation"]["police"]["best"]["unit"]
    path = w.net.route(w.units[best].home, w.incidents[inc["id"]].node)
    mid = path[len(path) // 2]
    c = client.post("/api/closures", json={"lat": float(w.net.lat[mid]), "lng": float(w.net.lon[mid])}).json()
    assert c["closures"] and c["closures"][0]["segments"]
    i = next(x for x in client.get("/api/state").json()["incidents"] if x["id"] == inc["id"])
    r = i["recommendation"]["police"]
    assert r["best"] is None or r["best"]["unit"] != best or r["best"]["eta_s"] > eta0
    client.delete("/api/closures")
    # junction alerts: one per junction, each with its own window
    d = client.post(f"/api/incidents/{inc['id']}/dispatch", json={}).json()
    a = client.post(f"/api/incidents/{inc['id']}/notify-traffic").json()
    i = next(x for x in client.get("/api/state").json()["incidents"] if x["id"] == inc["id"])
    assert a["junctions"] == len(i["traffic"]) > 0
    assert all(p["status"] in ("scheduled", "sent", "cleared") for p in i["traffic"])
    assert i["traffic"] == sorted(i["traffic"], key=lambda p: p["unit_in_s"])


def test_cctv_check_and_camera_alert(client):
    """A camera frame can raise urgency/add units on a call, and a camera alert can open an incident by itself."""
    from csafe.api import server
    from csafe.triage.client import FakeTriage

    def frame(image, report):
        return {"shows_incident": "yes" if report else "unclear", "seen_type": "fire", "what_is_seen": "Smoke from a shop, a man lying on the road",
                "people_visible": 6, "injured_visible": True, "fire_or_smoke": True, "weapon_visible": False, "violence_visible": False,
                "crowd_building": False, "vehicles_involved": None, "road_blocked": False, "hazards": [], "looks_stale_or_unrelated": False,
                "confidence": 0.8}
    saved = server.gemini
    server.gemini = FakeTriage(lambda t: {"incident_type": "crime_property", "landmark": "Tribune Chowk", "summary_en": "x", "confidence": 0.9}, frame)
    try:
        inc = client.post("/api/calls", data={"transcript": "Tribune Chowk ke paas dukaan mein chori ho rahi hai"}).json()["incident"]
        assert inc["cameras"], "Tribune Chowk has cameras nearby"
        cam = inc["cameras"][0]["id"]
        r = client.post(f"/api/incidents/{inc['id']}/cctv", data={"camera_id": cam}, files={"image": ("f.jpg", b"\xff\xd8fake", "image/jpeg")})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["cctv"][0]["camera"] == cam and "fire" in j["triage"]["decision"]["units"] and "ambulance" in j["triage"]["decision"]["units"]
        # camera alert with no caller
        r = client.post("/api/cctv/alert", data={"camera_id": "CAM-010"}, files={"image": ("f.jpg", b"\xff\xd8fake", "image/jpeg")})
        a = r.json()["incident"]
        assert a["triage"]["location"]["method"] == "camera" and a["lat"] is not None and a["recommendation"]["fire"]["best"]
    finally:
        server.gemini = saved
    # without Gemini, frames can't be read
    r = client.post(f"/api/incidents/{inc['id']}/cctv", data={"camera_id": cam}, files={"image": ("f.jpg", b"x", "image/jpeg")})
    assert r.status_code == 503
