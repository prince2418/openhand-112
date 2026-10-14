"""Score call triage on the labelled test set (data/triage_eval/calls.jsonl).

    python scripts/eval_triage.py --baseline          # keyword baseline, runs offline
    python scripts/eval_triage.py --live              # Gemini (needs GEMINI_API_KEY in .env)
    python scripts/eval_triage.py --live --rpm 8      # stay under free-tier rate limits
    python scripts/eval_triage.py --local             # Gemma on this computer via Ollama (sovereign mode), no rate limit
    python scripts/eval_triage.py --live --set india  # calls in 8 more Indian languages (data/triage_eval/calls_india.jsonl)

Safety metrics first:
  P1 recall      share of truly critical calls rated P1 (missing these costs lives)
  under-triage   share of calls rated less urgent than every acceptable priority
  missed units   share of calls where a required unit (police/ambulance/fire) was not sent
Also: incident-type accuracy, over-triage, over-dispatch, sector and flag accuracy, by language.
The test calls are written by us, not real 112 calls: treat scores as a sanity check, not a field result.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from csafe.triage.baseline import keyword_extract  # noqa: E402
from csafe.triage.client import FakeTriage, GeminiTriage  # noqa: E402
from csafe.triage.pipeline import triage_call  # noqa: E402

RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def score(records: list[dict], calls: list[dict]) -> dict:
    lab = {c["id"]: c["label"] for c in calls}
    lang = {c["id"]: c["lang"] for c in calls}
    m = defaultdict(list)
    per_lang = defaultdict(lambda: defaultdict(list))
    rows = []
    for r in records:
        L, cid = lab[r["id"]], r["id"]
        if r.get("error"):
            m["valid"].append(0); rows.append({"id": cid, "error": r["error"]}); continue
        m["valid"].append(1)
        x, d = r["extract"], r["decision"]
        ok_type = x["incident_type"] in L["incident_type_ok"]
        p, ok_p = d["priority"], L["priority_ok"]
        under = RANK[p] > max(RANK[q] for q in ok_p)
        over = RANK[p] < min(RANK[q] for q in ok_p)
        missed = sorted(set(L["units_required"]) - set(d["units"]))
        extra = sorted(set(d["units"]) - set(L["units_required"]))
        m["type_ok"].append(ok_type); m["priority_ok"].append(p in ok_p)
        m["under"].append(under); m["over"].append(over)
        m["missed_units"].append(bool(missed)); m["extra_units"].append(len(extra))
        if ok_p == ["P1"]:
            m["p1_recall"].append(p == "P1")
        if p == "P1":
            m["p1_precision"].append("P1" in ok_p)
        if L["sector"] is not None:
            m["sector_ok"].append(x["sector"] == L["sector"])
        for flag, key in (("trapped", "people_trapped"), ("unconscious", "unconscious_or_not_breathing")):
            if L[flag] is not None:
                m[f"{flag}_ok"].append(bool(x[key]) == L[flag])
        if L["life_threat"]:
            m["life_threat_recall"].append(bool(x.get("immediate_life_threat")))
        m["located"].append(r["location"]["resolved"]); m["review"].append(d["needs_human_review"])
        m["latency_s"].append(r["meta"]["latency_s"])
        for k in ("type_ok", "under", "missed_units"):
            per_lang[lang[cid]][k].append(m[k][-1])
        if not ok_type or under or over or missed or p not in ok_p:
            rows.append({"id": cid, "lang": lang[cid], "type": x["incident_type"], "type_ok": L["incident_type_ok"],
                         "priority": p, "priority_ok": ok_p, "missed_units": missed, "extra_units": extra,
                         "summary": x["summary_en"], "reasons": d["reasons"]})

    def pct(v):
        return round(100 * sum(v) / len(v), 1) if v else None
    lat = sorted(m["latency_s"])
    out = {
        "calls": len(records), "valid_output_pct": pct(m["valid"]),
        "p1_recall_pct": pct(m["p1_recall"]), "p1_n": len(m["p1_recall"]),
        "p1_precision_pct": pct(m["p1_precision"]),
        "under_triage_pct": pct(m["under"]), "over_triage_pct": pct(m["over"]),
        "priority_ok_pct": pct(m["priority_ok"]), "incident_type_ok_pct": pct(m["type_ok"]),
        "missed_units_pct": pct(m["missed_units"]),
        "extra_units_per_call": round(sum(m["extra_units"]) / max(1, len(m["extra_units"])), 2),
        "sector_ok_pct": pct(m["sector_ok"]), "trapped_ok_pct": pct(m["trapped_ok"]),
        "unconscious_ok_pct": pct(m["unconscious_ok"]), "life_threat_recall_pct": pct(m["life_threat_recall"]),
        "location_resolved_pct": pct(m["located"]), "sent_for_review_pct": pct(m["review"]),
        "latency_mean_s": round(sum(lat) / len(lat), 2) if lat else None,
        "latency_p90_s": lat[int(0.9 * (len(lat) - 1))] if lat else None,
        "by_language": {k: {kk: pct(vv) for kk, vv in v.items()} | {"n": len(v["type_ok"])} for k, v in sorted(per_lang.items())},
    }
    return {"summary": out, "errors": rows}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--baseline", action="store_true")
    g.add_argument("--live", action="store_true")
    g.add_argument("--local", action="store_true", help="Gemma via Ollama on this computer")
    ap.add_argument("--set", choices=["core", "india"], default="core", help="core: 52 Hindi/Punjabi/English calls; india: other Indian languages")
    ap.add_argument("--model", default=None, help="local model name, e.g. gemma3:12b (default: LOCAL_MODEL or gemma3:4b)")
    ap.add_argument("--rpm", type=float, default=8, help="max requests per minute in --live mode")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    src = ROOT / ("data/triage_eval/calls.jsonl" if a.set == "core" else "data/triage_eval/calls_india.jsonl")
    calls = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
    calls = calls[: a.limit] if a.limit else calls
    if a.local:
        from csafe.triage.local import LocalGemmaTriage
        client = LocalGemmaTriage(model=a.model)
        st = client.status()
        if not st["ok"]:
            sys.exit(st["reason"])
        print(f"Sovereign mode: {client.model} on this computer", flush=True)
    else:
        client = FakeTriage(keyword_extract) if a.baseline else GeminiTriage()
    name = "keyword_baseline" if a.baseline else ("local" if a.local else "gemini")
    records = []
    for i, c in enumerate(calls):
        t0 = time.time()
        try:
            records.append(triage_call(client, c))
        except Exception as e:  # noqa: BLE001 - one failed call must not stop the evaluation
            records.append({"id": c["id"], "error": f"{type(e).__name__}: {e}"})
        print(f"[{i + 1}/{len(calls)}] {c['id']} {records[-1].get('decision', {}).get('priority', 'ERROR')}", flush=True)
        if a.live and i < len(calls) - 1:
            time.sleep(max(0.0, 60 / a.rpm - (time.time() - t0)))
    res = score(records, calls)
    out = Path(a.out or ROOT / (f"results/triage_{name}.json" if a.set == "core" else f"results/triage_india_{name}.json"))
    out.parent.mkdir(exist_ok=True)
    model = getattr(client, "model", None) if not a.baseline else None
    out.write_text(json.dumps({"system": name, "model": model, "set": a.set, **res, "records": records}, indent=2, ensure_ascii=False))
    s = res["summary"]
    print(f"\n{name}: {s['calls']} calls")
    for k in ("valid_output_pct", "p1_recall_pct", "under_triage_pct", "missed_units_pct", "incident_type_ok_pct",
              "priority_ok_pct", "over_triage_pct", "p1_precision_pct", "extra_units_per_call", "sector_ok_pct",
              "trapped_ok_pct", "unconscious_ok_pct", "life_threat_recall_pct", "location_resolved_pct",
              "sent_for_review_pct", "latency_mean_s"):
        print(f"  {k:24s} {s[k]}")
    print("  by language:", json.dumps(s["by_language"]))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
