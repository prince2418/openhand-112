"""Triage one call and print a dispatch card.

    python scripts/triage_demo.py "Sector 22 market mein aag lagi hai, do log upar fase hain"
    python scripts/triage_demo.py --image photo.jpg "accident at Tribune Chowk"
    python scripts/triage_demo.py --audio call.wav
    python scripts/triage_demo.py --baseline "..."     # keyword baseline, no API key needed
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from csafe.triage.baseline import keyword_extract  # noqa: E402
from csafe.triage.client import FakeTriage, GeminiTriage  # noqa: E402
from csafe.triage.pipeline import triage_call  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("transcript", nargs="?", default=None)
ap.add_argument("--image"); ap.add_argument("--audio")
ap.add_argument("--lat", type=float); ap.add_argument("--lng", type=float)
ap.add_argument("--baseline", action="store_true"); ap.add_argument("--json", action="store_true")
a = ap.parse_args()
client = FakeTriage(keyword_extract) if a.baseline else GeminiTriage()
r = triage_call(client, {"id": "demo", "transcript": a.transcript, "image": a.image, "audio": a.audio,
                         "phone_lat": a.lat, "phone_lng": a.lng})
if a.json:
    print(json.dumps(r, indent=2, ensure_ascii=False)); sys.exit()
x, d, loc = r["extract"], r["decision"], r["location"]
print(f"\n  {d['priority']}  {x['incident_type'].replace('_', ' ').upper()}   send: {', '.join(d['units']) or 'nobody'}")
print(f"  {x['summary_en']}")
print(f"  where: {loc['label']}" + (f" ({loc['lat']:.5f}, {loc['lng']:.5f})" if loc["resolved"] else ""))
print(f"  why:   {'; '.join(d['reasons'])}")
if d["needs_human_review"]:
    print(f"  REVIEW: {'; '.join(d['review_reasons'])}")
if x["missing_info"]:
    print(f"  ask:   {'; '.join(x['missing_info'])}")
print(f"  [{r['meta']['model']}, {r['meta']['latency_s']} s]\n")
