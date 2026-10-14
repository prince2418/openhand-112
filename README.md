# OpenHand 112

**An open-source AI decision layer for India's 112 emergency response.** Built and tested on Chandigarh's real road
network; runs on any Indian city from OpenStreetMap. Google Gemini (cloud) or Gemma (open weights, on the state's own
computer) reads each call; fixed, auditable rules decide priority; the dispatcher always confirms.

Hackathon prototype for *Urban Safety for Chandigarh: AI for Digital Public Infrastructure*. Not an official service.
MIT licence.

## What it does

| Tab | What it does |
|---|---|
| **Live dispatch** | Gemini reads a 112 call (text, voice, photo) in 11 Indian languages and extracts facts; rules set P1–P4 and the units; the unit that arrives first **by road** is recommended; one click dispatches, draws the route, sends junction-by-junction green-corridor alerts and a hospital pre-alert; Gemini checks a CCTV frame against the call. |
| **Predict and monitor** | Next-6-hour call forecast with ranges, chance every ambulance is busy, the 8 sectors most likely to need help; a live watch that flags unusual clusters, surges and cover gaps and moves vans to standby points in one click. |
| **Rain and waterlogging** | Which of 24 known spots will flood under a rain forecast (live or historical), which roads to close or divert and when, pump teams; public advisory in English, Hindi and Punjabi. |
| **Open platform** | Cloud vs **sovereign mode** switch; every message to other agencies with its standard and payload; CAP 1.2 public alerts (NDMA SACHET format); anonymised open data; OpenAPI. |
| **Across India** | The same engine run on other cities with one command: 5-minute reach today vs with standby points, fire-station gaps, hospital reach. |
| **Evidence** | Benchmark, triage scores for three engines, Indian-language scores, flood-model check, limits. |

## Key results (read the labels)

| Result | Value | Basis |
|---|---|---|
| PCR calls reached within 5 min, vans at stations → forecast-based standby points | 66.0% → 92.6% (median 4.25 → 3.00 min) | Simulation on Chandigarh's real roads, 6 × 30 days, calibrated to the published 4 min 32 s |
| Life-threatening (P1) calls caught by Gemini triage | 23 of 23 (keyword baseline: 69.6%) | 52 test calls we wrote, Hindi/Punjabi/English |
| Calls rated less urgent than they were | Gemini 1.9% vs keyword 21.2% | same test set |
| Waterlogging: roads on the 9 Jul 2023 traffic-police list flagged | 7 of 7 | historical replay, not used for fitting |

Run `scripts/eval_triage.py --local` and `--set india` (below) to add sovereign-mode and Indian-language scores.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env            # paste a free Gemini key from Google AI Studio (optional: without it a keyword reader runs)
python run_app.py               # opens http://localhost:8001
```

### Sovereign mode: Gemma on your own computer

```bash
# install Ollama from https://ollama.com and open it, then:
ollama pull gemma3:4b           # ~3.3 GB; gemma3:12b is more accurate on 16 GB+ machines
python run_app.py               # then Open platform tab -> "Use Gemma on this computer"
# or start in sovereign mode:  TRIAGE_ENGINE=local python run_app.py
```
No call text, photo or camera frame leaves the machine. Voice clips still need cloud Gemini.

### Score the AI on the test calls

```bash
python scripts/eval_triage.py --live --rpm 8            # Gemini, 52 calls
python scripts/eval_triage.py --local                   # Gemma on this computer
python scripts/eval_triage.py --live --set india        # 32 calls in Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, Odia
python scripts/eval_triage.py --local --set india
python scripts/eval_triage.py --baseline [--set india]  # keyword reader, offline
```

### Run the engine on another city

```bash
python scripts/add_city.py "Lucknow, Uttar Pradesh, India"
python scripts/add_city.py "Bhubaneswar, Odisha, India" --vans 40
```
Downloads roads, police, fire and hospitals from OpenStreetMap, places standby points and writes
`cities/<slug>/summary.json` (shown in the *Across India* tab). A model of that city, not a measurement: OSM station
coverage varies and van counts are assumptions, both listed in the summary.

## Research benchmark

```bash
# 1. road graph (needs internet)
python -c "import osmnx as ox; G=ox.graph_from_place('Chandigarh, India', network_type='drive'); ox.save_graphml(G,'data/chandigarh.graphml')"
python scripts/enrich_graph.py data/chandigarh.graphml data/chandigarh_enriched.graphml
# 2. benchmark
python run_benchmark.py --stations data/stations.csv --optimise-placement
python -m pytest -q tests
```
Full results and caveats: `results/RESULTS.md`.

## What is compared (same incidents for every policy)
- `nearest_distance`: straight-line nearest free unit (published: the control room "sends the nearest unit")
- `nearest_eta`: fastest free unit by road travel time
- `coverage`: of the best few by ETA that still make the target, send the one that leaves the city best covered
- `--optimise-placement`: same dispatch rule, but standby points chosen by a risk forecast
Headline metric: share of incidents reached within the target time. Mean and 90th percentile are reported alongside.

## Published inputs vs assumptions
| Input | Value | Status |
|---|---|---|
| PCR fleet | 57 four-wheelers + 12 motorcycles | published (Tribune, 10 Oct 2026); an older report says 104 |
| PCR average response | 4 min 32 s (Jan-Sep 2026) | published; used only to calibrate the baseline |
| PCR calls | over 300 a day | published |
| Share of PCR units on duty | 45% | assumption |
| Ambulance (108) fleet | 6 | published, launch-era, may be out of date |
| Ambulance and fire call rates, service times | see `SCENARIOS` | assumption, no published source |
| Road speeds | imputed from road class | assumption |
| Where incidents happen, hourly pattern, traffic by hour | `demand.py` | assumption: incident-level data is not public |

## Limits
Synthetic incidents; Chandigarh only (no Mohali or Panchkula); units return to base after each call;
traffic-signal control is not modelled.

## Call triage (Gemini)

Gemini reads a 112 call (transcript in Hindi, Punjabi, English or a mix; audio; or a citizen photo) and
returns **facts only** (`src/csafe/triage/schema.py`). Fixed rules (`rules.py`) turn those facts into a
priority (P1 to P4) and the units to send, and record why. The model never sets urgency on its own, so a
model error cannot silently downgrade a call, and every decision is auditable.

- **Repeat calls:** three or more calls about the same incident (same type, within 400 m and 30 min)
  raise its priority one level (`repeat.py`). Itaewon 2022: 11 calls, 4 dispatches.
- **Location:** the caller's phone location if present, then a known landmark, then a known point in the
  stated sector. Otherwise the call is flagged for the dispatcher. We never invent coordinates.
- **Fallback:** on rate limits it retries, then falls back to Gemma through the same API.
- **Review flags:** low confidence, unresolved location, unclear type, or contradictory facts.

Setup: copy `.env.example` to `.env` and paste your Gemini key (free from AI Studio, no card needed).

    python scripts/triage_demo.py "Sector 22 market mein aag lagi hai, do log upar fase hain"
    python scripts/eval_triage.py --live --rpm 8      # labelled test set, about 7 minutes
    python scripts/eval_triage.py --baseline          # keyword baseline, offline

The test set (`data/triage_eval/calls.jsonl`) has 52 calls we wrote ourselves: Hindi, Punjabi (both
scripts and romanised), English and mixed, including pranks, fragments and trapped people. It is a sanity
check, not real 112 data. Safety metrics come first: P1 recall, under-triage and missed units.

## The app in detail

One command starts the API and the dashboard (the dashboard is pre-built in `web/dist`, so Node.js is
not needed to run it):

    pip install -r requirements.txt
    python run_app.py          # opens http://localhost:8001 when ready

**Live dispatch:** paste or pick a call (52 samples in Hindi, Punjabi, English), optionally add a photo
or audio clip (needs Gemini), and press *Triage call*. The card shows the facts Gemini found, the
priority and why, what to ask the caller, and for each unit type the free unit that arrives first by
road vs the nearest one on the map. *Dispatch* sends it: the route, its main-road junctions and their
timings appear, and *Alert traffic police* produces the green-corridor alert (simulated). Unknown
location: confirm with the caller and click the map. Repeat calls about the same place join the same
incident and raise its priority. Map layers: stations, black spots, crash risk this hour (model) and
the risk-based PCR standby points.

**Evidence:** the benchmark, fire-station siting and triage scores, with their limits.

The demo clock runs 10x real time so drives finish on stage (`DEMO_SPEED=1 python run_app.py` for real
time). Without a Gemini key the app still works, reading calls with the keyword fallback, and says so.

Editing the dashboard: `cd web && npm install && npm run dev` (proxies the API on :8001), then
`npm run build`. Basemap: OpenFreeMap vector tiles, falling back to OpenStreetMap raster tiles; no keys.

## Data and licences

- Road network and map data (c) OpenStreetMap contributors, under the Open Database Licence (ODbL 1.0). Basemap tiles: OpenFreeMap.
- Call triage uses Google Gemini through the Gemini API (Google's API terms). The Gemma fallback models are under the Gemma Terms of Use, which are separate from this project's MIT licence.
- Personal data (phone, Aadhaar, PAN, e-mail, vehicle numbers, stated names) is removed from each call before it reaches any model (`src/csafe/triage/redact.py`, India's DPDP Act 2023).
- Code: MIT (see LICENSE).

## What-if controls (live app)

Winter fog (all drives 1.5x slower), night shift (20 of 31 PCR on duty), and "close a road" (click a road; routes and arrival times go around it). Traffic-police alerts are sent junction by junction, each 2 minutes (simulated) before the unit reaches it; replies are simulated.

## Predict and monitor (live app tab)

Answers the theme's "predictive monitoring" directly: what the next hours should look like, and an alert when today doesn't match.

- **Next 6 hours.** Expected 112 calls per hour for PCR, ambulance and fire with an 80% range (Poisson), and how stretched each fleet will be: the chance that a new call finds every ambulance busy (Erlang B). Adjusted when fog or waterlogging is on (labelled assumptions).
- **Where, next hour.** The 8 sectors with the most expected calls, with the reason (crash black spot, crash-prone main roads, waterlogging forecast).
- **Does it work?** A hotspot forecast learned from 90 days of incidents is tested on the next 30 days it never saw: hit rate in the top 10% of the map and the Predictive Accuracy Index (Chainey et al. 2008), next to the best any forecast could do. On simulated crashes; the same code runs on ERSS records.
- **Live watch** (every few seconds, on every tab):
  - *Unusual cluster*: more incidents within 700 m than the forecast allows for that place and time (Poisson tail, p < 0.01). "Send 3 test calls" shows it.
  - *Surge*: more crashes, fires or medical calls city-wide than expected in the last hour.
  - *Get ready*: vans parked two to a station cover the same streets; send the extra ones to standby points (MEXCLP plan). At the evening peak this lifts 5-minute PCR cover from about 55% to over 90% of calls (model, all vans free).
  - *Cover gap*: when vans are busy, the sectors that lost 5-minute cover and the one move that wins back the most.
  - *Fleet low* and *Rain* (roads the waterlogging plan says will close within 2 hours).
  Each alert says what to do; moves are one click and the vans are shown driving there.

## Open platform: digital public infrastructure (live app tab)

OpenHand is built as a shared building block behind ERSS-112 and the ICCC, not as a standalone app.

- **Message log.** Every message the system would exchange with another agency, with its standard and exact payload: incident records and close-outs to ERSS-112, dispatch and move orders to vehicle terminals, green-corridor windows to traffic signal control, hospital pre-alerts (no caller identity), CCTV frames in from the ICCC, public alerts out. All marked **simulated**: nothing leaves the computer.
- **Public alerts in CAP 1.2** (`GET /api/dpi/cap/flood.xml`), the OASIS Common Alerting Protocol that NDMA's SACHET gateway (C-DOT) uses for SMS and cell-broadcast alerts. English, Hindi and Punjabi `<info>` blocks, one `<area>` circle per closed road, `status` = Exercise.
- **Open data** (`/api/open/incidents.geojson`, `.csv`): no caller words, place rounded to a ~550 m grid, time to the hour.
- **Interface catalogue** (`/api/dpi/catalogue`) and the full **OpenAPI reference** at `/docs`.
- Code: `src/csafe/api/dpi.py`, `src/csafe/api/watch.py`; tests: `tests/test_predict_dpi.py`.
