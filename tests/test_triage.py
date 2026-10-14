"""Triage tests that run offline: a fake Gemini client stands in for the API."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from csafe.triage.client import FakeTriage, GeminiTriage, parse_json  # noqa: E402
from csafe.triage.location import resolve  # noqa: E402
from csafe.triage.pipeline import triage_call  # noqa: E402
from csafe.triage.repeat import RepeatTracker  # noqa: E402
from csafe.triage.rules import decide  # noqa: E402
from csafe.triage.schema import Extract  # noqa: E402


def X(**kw):
    base = dict(incident_type="road_accident", summary_en="test", confidence=0.9)
    return Extract(**(base | kw))


# ---------- rules: facts -> priority and units ----------

@pytest.mark.parametrize("facts, priority, units", [
    (dict(unconscious_or_not_breathing=True, people_injured=1), "P1", ["ambulance", "police"]),       # c01
    (dict(incident_type="fire", fire_or_smoke=True, people_trapped=True), "P1", ["ambulance", "fire", "police"]),  # c02
    (dict(incident_type="crime_property"), "P3", ["police"]),                                           # c13
    (dict(incident_type="non_emergency"), "P4", []),                                                    # c05
    (dict(incident_type="medical", immediate_life_threat=True), "P1", ["ambulance"]),                   # c49 poison
    (dict(incident_type="road_accident", people_injured=0), "P3", ["police"]),                          # c47 minor
    (dict(incident_type="waterlogging", people_trapped=True), "P1", ["fire", "police"]),                # c07
    (dict(incident_type="other_emergency", hazards=["gas"]), "P1", ["fire", "police"]),                 # c10
    (dict(incident_type="crowd", people_injured=1), "P1", ["ambulance", "police"]),                     # c09
    (dict(incident_type="other_emergency", people_trapped=True, hazards=["structure_collapse"]), "P1", ["fire", "police"]),
])
def test_rules(facts, priority, units):
    d = decide(X(**facts))
    assert d.priority == priority and d.units == units and d.reasons


def test_repeat_calls_raise_priority_but_never_above_p1():
    x = X(incident_type="crowd")
    assert decide(x, repeat_calls=1).priority == "P2"
    assert decide(x, repeat_calls=3).priority == "P1"
    assert decide(X(unconscious_or_not_breathing=True), repeat_calls=5).priority == "P1"


def test_review_flags():
    assert decide(X(confidence=0.3)).needs_human_review
    assert "location" in decide(X(), location_resolved=False).review_reasons[0]
    assert decide(X(incident_type="non_emergency", fire_or_smoke=True)).needs_human_review
    assert not decide(X(), location_resolved=True).needs_human_review


# ---------- repeat-call tracker (Itaewon lesson) ----------

def test_tracker_groups_same_place_and_type_within_window():
    tr = RepeatTracker()
    assert tr.add("a", 0, "crowd", 30.75, 76.80) == 1
    assert tr.add("b", 300, "crowd", 30.7510, 76.8005) == 2          # ~120 m away, 5 min later
    assert tr.add("c", 600, "fire", 30.7510, 76.8005) == 1           # different type
    assert tr.add("d", 900, "crowd", 30.80, 76.70) == 1              # far away
    assert tr.add("e", 900 + 31 * 60, "crowd", 30.75, 76.80) == 1    # too late: new incident
    assert tr.add("f", 0, "crowd", key="sector 23") == 1 and tr.add("g", 60, "crowd", key="sector 23") == 2


# ---------- location: phone > landmark > sector > unresolved ----------

def test_location_order_and_no_invented_points():
    assert resolve(22, "PGI", None, phone_latlng=(30.7, 76.8)).method == "phone"
    p = resolve(None, "PGI emergency", None)
    assert p.method == "landmark" and abs(p.lat - 30.765) < 0.01
    assert resolve(17, None, "near the plaza").method == "sector"
    q = resolve(99, None, "somewhere near the big tree")
    assert not q.resolved and q.lat is None


# ---------- Gemini client: parsing, retry on rate limit, fallback ----------

GOOD = dict(incident_type="fire", fire_or_smoke=True, sector=22, summary_en="Shop fire in Sector 22", confidence=0.8)


class FakeModels:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return SimpleNamespace(text=step)


def make_client(script):
    fm = FakeModels(script)
    return GeminiTriage(_client=SimpleNamespace(models=fm), model="primary", fallback="gemma", max_retries=2), fm


def test_client_retries_server_overload_503(monkeypatch):
    monkeypatch.setattr("csafe.triage.client.time.sleep", lambda s: None)
    c, fm = make_client([RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand"), json.dumps(GOOD)])
    x, meta = c.extract("fire")
    assert meta["model"] == "primary" and meta["attempts"] == 2


def test_client_skips_missing_model_in_chain(monkeypatch):
    monkeypatch.setattr("csafe.triage.client.time.sleep", lambda s: None)
    fm = FakeModels([RuntimeError("503 UNAVAILABLE"), RuntimeError("503 UNAVAILABLE"),
                     RuntimeError("404 NOT_FOUND models/x"), json.dumps(GOOD)])
    c = GeminiTriage(_client=SimpleNamespace(models=fm), model="primary", fallback="x,backup", max_retries=2)
    x, meta = c.extract("fire")
    assert fm.calls == ["primary", "primary", "x", "backup"] and meta["model"] == "backup"


def test_client_structured_success(monkeypatch):
    c, fm = make_client([json.dumps(GOOD)])
    x, meta = c.extract("Sector 22 market mein aag")
    assert x.incident_type == "fire" and x.sector == 22 and meta["model"] == "primary" and fm.calls == ["primary"]


def test_client_retries_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr("csafe.triage.client.time.sleep", lambda s: None)
    c, fm = make_client([RuntimeError("429 RESOURCE_EXHAUSTED"), json.dumps(GOOD)])
    x, meta = c.extract("fire")
    assert meta["attempts"] == 2 and fm.calls == ["primary", "primary"]


def test_client_falls_back_to_gemma_on_bad_output():
    c, fm = make_client(["not json at all", "Here you go:\n```json\n" + json.dumps(GOOD) + "\n```"])
    x, meta = c.extract("fire")
    assert meta["model"] == "gemma" and fm.calls == ["primary", "gemma"] and x.sector == 22


def test_client_raises_when_everything_fails():
    c, _ = make_client(["{}", "{}"])  # valid JSON but missing required fields
    with pytest.raises(RuntimeError, match="all models failed"):
        c.extract("x")


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


# ---------- pipeline end to end ----------

def test_pipeline_escalates_third_call_about_same_crowd():
    fake = FakeTriage(lambda t: dict(incident_type="crowd", landmark="Sukhna Lake", summary_en="crowd", confidence=0.9))
    tr = RepeatTracker()
    out = [triage_call(fake, {"id": i, "t": 60 * i, "transcript": "bheed"}, tr) for i in range(3)]
    assert [o["decision"]["priority"] for o in out] == ["P2", "P2", "P1"] and out[2]["repeat_calls"] == 3


def test_client_steps_down_on_400():
    """A model that rejects thinking_budget or response_schema (400) must still work via the simpler request formats."""
    import json as _json
    from csafe.triage.client import GeminiTriage

    good = _json.dumps({"incident_type": "road_accident", "summary_en": "x", "confidence": 0.9})

    class R:  # fake response
        def __init__(self, t): self.text = t

    class Models:
        def __init__(self): self.calls = 0
        def generate_content(self, model, contents, config):
            self.calls += 1
            if getattr(config, "thinking_config", None) is not None or getattr(config, "response_schema", None) is not None:
                raise RuntimeError("400 INVALID_ARGUMENT. Request contains an invalid argument.")
            return R(good)

    class C:
        def __init__(self): self.models = Models()

    c = C()
    g = GeminiTriage(_client=c, model="m1", fallback="")
    x, meta = g.extract("accident")
    assert x.incident_type == "road_accident" and meta["model"] == "m1"
    first = c.models.calls
    g.extract("accident again")
    assert c.models.calls - first == 1          # remembered the working format, no more failed attempts


def test_client_gives_up_within_budget():
    """With a 2 s budget, a model stuck on 429s must give up in ~2 s instead of backing off for a minute."""
    import time as _t
    import pytest as _pytest
    from csafe.triage.client import GeminiTriage

    class Models:
        def generate_content(self, model, contents, config):
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota")

    class C:
        models = Models()

    g = GeminiTriage(_client=C(), model="m1", fallback="m2", max_retries=4, budget_s=2)
    t0 = _t.time()
    with _pytest.raises(RuntimeError):
        g.extract("accident")
    assert _t.time() - t0 < 3.5


def test_famous_places_and_sexual_assault():
    from csafe.triage.location import resolve
    from csafe.triage.rules import decide
    from csafe.triage.schema import Extract
    p = resolve(None, "Nexus Elante Mall", None)
    assert p.resolved and p.label.startswith("Elante Mall")
    assert resolve(None, None, "matka chowk pe accident").label.startswith("Matka Chowk")
    assert not resolve(None, None, "pucho usse").resolved          # "pu" alias must not fire inside a word
    x = Extract(incident_type="crime_violent", summary_en="Caller reported a rape at the mall.", confidence=0.9)
    d = decide(x)
    assert d.priority == "P1" and "ambulance" in d.units and "police" in d.units


def test_fast_path_words_and_spellings():
    from csafe.triage.fastpath import sexual_violence_alert as a
    for t in ["balatkaar hogya hai jan marg pe", "blaatkaar", "ladki ke saath zyaadti hui", "लड़की के साथ दुष्कर्म हुआ",
              "ਕੁੜੀ ਨਾਲ ਜਬਰ ਜਨਾਹ ਹੋਇਆ", "koi ladki ka peecha kar raha hai", "someone is following her", "acid attack hua",
              "बस में छेड़छाड़ हो रही है", "a man is groping women in the bus"]:
        assert a(t), t
    for t in ["sector 22 mein accident", "heart attack aaya hai", "her bike is stolen", "chain snatch hui",
              "pareshan hoon bill se", "she is not breathing"]:
        assert a(t) is None, t


def test_personal_data_is_removed_before_the_model():
    from csafe.triage.redact import redact
    t, kinds = redact("Mera naam Rahul Sharma hai, number 98765 43210, office 0172-2740000, car CH01AB1234, "
                      "aadhaar 1234 5678 9012, mail rahul@gmail.com. Sector 22 mein accident, 2 log ghayal")
    for secret in ("Rahul", "98765", "2740000", "CH01AB1234", "9012", "gmail"):
        assert secret not in t, secret
    assert "Sector 22" in t and "2 log ghayal" in t
    assert {"phone", "name", "vehicle", "aadhaar", "email"} <= set(kinds)
