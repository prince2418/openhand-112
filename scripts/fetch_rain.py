"""Download real hourly rain for Chandigarh (1995-2025) from Open-Meteo's historical weather API (ERA5
reanalysis; free, no key, non-commercial use) into data/rain_history_openmeteo.csv. The app then uses it for
the waterlogging risk table instead of the synthetic monsoons.

Run on a computer with internet:   python3 scripts/fetch_rain.py
Caveat: reanalysis averages rain over a ~10-30 km cell, so short cloudbursts come out weaker than a rain
gauge would record. Hourly IMD station data for Chandigarh is not openly published.
"""
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data/rain_history_openmeteo.csv"
URL = ("https://archive-api.open-meteo.com/v1/archive?latitude=30.7333&longitude=76.7794"
       "&start_date={a}&end_date={b}&hourly=precipitation&timezone=Asia%2FKolkata")


def main(first: int = 1995, last: int = 2025):
    rows = []
    for y0 in range(first, last + 1, 5):
        y1 = min(last, y0 + 4)
        url = URL.format(a=f"{y0}-01-01", b=f"{y1}-12-31")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    d = json.loads(r.read().decode())
                break
            except Exception as e:  # noqa: BLE001
                print(f"  {y0}-{y1}: {e}; retrying", file=sys.stderr)
                time.sleep(5 * (attempt + 1))
        else:
            sys.exit(f"could not download {y0}-{y1}")
        rows += list(zip(d["hourly"]["time"], d["hourly"]["precipitation"]))
        print(f"{y0}-{y1}: {len(d['hourly']['time'])} hours")
        time.sleep(1)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "mm"])
        w.writerows(rows)
    print(f"wrote {OUT} ({len(rows)} hours). Restart run_app.py to use it.")


if __name__ == "__main__":
    main()
