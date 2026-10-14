"""Sovereign mode (local Gemma via Ollama), the India-language test set, and the any-city engine."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["GEMINI_API_KEY"] = ""


def _fake_post(path, body):
    from csafe.triage.baseline import keyword_extract
    assert path == "/api/chat" and body["options"]["temperature"] == 0 and body["stream"] is False
    assert isinstance(body["format"], dict)                       # structured output: the JSON schema
    text = body["messages"][1]["content"].split("CALL TRANSCRIPT:\n", 1)[-1]
    return {"message": {"content": "```json\n" + keyword_extract(text).model_dump_json() + "\n```"}}


def test_local_gemma_same_interface():
    from csafe.triage.local import LocalGemmaTriage
    from csafe.triage.pipeline import triage_call
    t = LocalGemmaTriage(model="gemma3:4b", _post=_fake_post)
    r = triage_call(t, {"id": "x", "transcript": "Sector 22 market mein aag lagi hai, do log upar fase hain, call 9876543210"})
    assert r["decision"]["priority"] == "P1" and r["meta"]["engine"] == "local" and r["meta"]["model"] == "gemma3:4b (local)"
    assert "phone" in r["meta"]["redacted"]                       # redaction runs before the local model too
    with pytest.raises(RuntimeError):
        t.extract("hello", audio=b"RIFF")                         # voice clips need Gemini
    st = LocalGemmaTriage(host="http://127.0.0.1:9").status()     # nothing listening: a clear reason, no crash
    assert st["ok"] is False and "Ollama" in st["reason"]


def test_engine_switch(monkeypatch):
    from fastapi.testclient import TestClient
    from csafe.api import server
    from csafe.triage.local import LocalGemmaTriage
    c = TestClient(server.app)
    assert c.post("/api/ai", json={"engine": "gemini"}).status_code == 400          # no key in tests
    local = LocalGemmaTriage(model="gemma3:4b", _post=_fake_post)
    monkeypatch.setattr(local, "status", lambda: {"ok": True, "model": "gemma3:4b", "host": "test"})
    monkeypatch.setattr(server, "local_ai", local)
    e = c.post("/api/ai", json={"engine": "local"}).json()
    assert e["active"] == "local" and c.get("/api/health").json()["triage"] == "local"
    c.post("/api/reset")
    inc = c.post("/api/calls", data={"transcript": "Sector 38 market ke paas accident, ek aadmi behosh hai"}).json()["incident"]
    assert inc["triage"]["meta"]["engine"] == "local" and inc["triage"]["decision"]["priority"] == "P1"
    monkeypatch.setattr(server, "gemini", None)
    monkeypatch.setattr(server, "ENGINE", "none")


def test_india_set():
    rows = [json.loads(l) for l in (ROOT / "data/triage_eval/calls_india.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 32 and len({r["id"] for r in rows}) == 32
    langs = {r["lang"] for r in rows}
    assert langs == {"ta", "te", "kn", "ml", "bn", "mr", "gu", "or"}
    assert all(sum(r["lang"] == l for r in rows) == 4 for l in langs)
    for r in rows:
        L = r["label"]
        assert L["priority_ok"] and set(L["units_required"]) <= {"police", "ambulance", "fire"}


def test_city_engine_and_api():
    from fastapi.testclient import TestClient
    from csafe.api import server
    c = TestClient(server.app)
    rows = c.get("/api/cities").json()["cities"]
    chd = next(r for r in rows if r["slug"] == "chandigarh")
    assert chd["junctions"] > 10000 and chd["police_stations"] >= 10
    assert chd["pcr"]["standby_pct"] > chd["pcr"]["today_pct"]
    full = c.get("/api/cities/chandigarh").json()
    assert len(full["pcr"]["standby_points"]) == full["vans"] and full["cells"]
    assert c.get("/api/cities/no-such-city").status_code == 404
