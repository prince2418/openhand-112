# Research brief: Chandigarh emergency services data

**Prepared:** 12 October 2026. **For:** a research-capable AI assistant.
**Subject:** UT Chandigarh, India: fire, ambulance (108/102) and police (PCR) services.

---

## 0. Your job in one paragraph

We are building an open-source emergency-response simulator for Chandigarh. It already runs, but two kinds of inputs are guesses: **where the vehicles are actually stationed** and **how many fire and ambulance calls the city really gets**. Your job is to find verifiable facts for those, with sources, and to say plainly what cannot be found. **Accuracy matters more than completeness. Never invent a number or a coordinate. "Not found" is a valid and useful answer.**

Everything in section 5 marked *unverified* comes from another AI and may be wrong. Treat it as a lead to confirm or contradict, never as a fact.

---

## 1. Project context

### 1.1 The hackathon
- **Theme:** "Urban Safety for Chandigarh: AI for Digital Public Infrastructure of Chandigarh."
- **Brief:** predictive monitoring systems, emergency response optimisation, and real-time threat assessment for enhanced public security.
- **Rules:** all solutions must integrate Google AI (Gemini API, AI Studio, Vertex AI, Maps Platform, BigQuery, Firebase and similar). There is an optional bonus challenge for the **Best Open-Source AI Project**.
- **Team:** students. The submission deadline, team size and format are not yet known.

### 1.2 Our solution (decisions already made)

| Step | What it does |
|---|---|
| **Predict** | A risk forecast per sector and hour decides where ambulances, fire tenders and PCR vans should wait (pre-positioning). |
| **Understand** | Gemini reads 112 call transcripts (Hindi, Punjabi, English) and citizen photos and returns a structured incident: type, severity, location, units needed. |
| **Decide** | An optimiser picks which unit to send. Gemini only explains the choice. It never makes it. |
| **Clear the way** | The route and the junctions to clear are pushed to traffic police (a "green corridor" alert). |
| **Prove** | A public, reproducible simulation on the real road network compares our approach against the current one. |

**Scope decisions**
- **Build and measure:** road accidents and fire.
- **Show on the same pipeline:** crowd surge (event calendar, Seoul-style tiered thresholds) and waterlogging (rain forecast, photos, routing around flooded roads).
- **One slide only:** theft and thief search (a reachable-roads zone on the road graph, no face tracking, with the reporting-bias caveat).
- **Skipped:** face recognition and CCTV re-identification, crime prediction, edge AI, Earth Engine, Dialogflow.

**Known limits we state openly:** incident-level data is synthetic (it is not public); the road graph covers Chandigarh only; traffic-signal control is simulated; no real fire or ambulance logs.

### 1.3 What international research taught us (only the points that change what data we need)
- **Use the right metric.** A Dutch ambulance study found a smarter dispatch policy cut late arrivals by 18% but raised average response time by 37%. So our headline is the **share of incidents reached within a target time**, with mean and 90th percentile alongside.
- **ETA-based dispatch is already standard.** Roswell, Georgia sends the unit that can arrive fastest, "not always the closest." Our own control room reportedly sends the *nearest* unit (see section 5).
- **Unverified headline numbers are common.** Hangzhou's "ambulances 48.9% faster" and similar claims have no independent verification. We want real baselines to calibrate against, not marketing numbers.
- **Alert quality matters.** A Copenhagen trial of AI on emergency calls found higher sensitivity but only about 18% of its alerts were real cardiac arrests, and dispatcher recognition did not significantly improve. Our Gemini triage will be scored on precision and recall.

---

## 2. What has been built: the simulator

**Road network.** OpenStreetMap drive graph: 11,960 nodes, 30,731 edges. Bounding box: latitude 30.6697 to 30.7912, longitude 76.7076 to 76.8478. This is Chandigarh UT only. Mohali Phase 8 is about 1.2 km outside and Panchkula Sector 5 about 2.3 km outside. Only about 0.1% of roads carry a speed limit in OSM, so speeds are **imputed from road class** (30 km/h residential, 40 tertiary, 45 secondary, 50 primary, 60 trunk), then rescaled during calibration.

**Incidents.** Synthetic. Poisson arrivals with an assumed hourly pattern; location probability weighted by road class (arterials count 3 to 4 times a residential street); service time exponential; travel time carries 15% random noise. Every policy is compared on **identical** incidents.

**Policies compared**
1. `nearest_distance`: straight-line nearest free unit (what the control room reportedly does).
2. `nearest_eta`: fastest free unit by road travel time.
3. `coverage`: among the best few by ETA that still make the target, send the one that leaves the city best covered.
4. **Risk-based standby points:** same dispatch rule, but standby locations chosen from a demand forecast learned from past incidents.

**Calibration.** One travel-time scale factor is fitted so the simulated nearest-distance PCR baseline matches the published 4 min 32 s average. It came out at 0.975, so the imputed speeds were already close.

### 2.1 Assumptions currently in the code (this is the gap you are filling)

| Service | Units | Calls/day | Time on scene | Target | Status |
|---|---|---|---|---|---|
| PCR | 69 vehicles × 45% on duty = **31** | 300 (published: "over 300 calls a day") | 25 min | 5 min | fleet published; **on-duty share, scene time assumed** |
| Ambulance (108) | **6** | **60** | 45 min | 8 min | **fleet from launch era; calls/day and scene time are guesses** |
| Fire | **14** (7 stations × 2 tenders) | **8** | 60 min | 8 min | **tenders per station, calls/day and scene time are all guesses.** Used only in an exploratory sweep so far; fire is not yet a scenario in the main benchmark script. |

Plus: 60 s of call handling before dispatch (assumed). All unit placements so far are **evenly spread test placements, not real stations**.

### 2.2 First findings (test placement; these are not results)
- ETA dispatch beats straight-line nearest by about 2.7 percentage points in the share reached within 5 minutes (PCR), and about 0.13 min on the mean. Small.
- The coverage-aware rule never beat plain ETA dispatch.
- **Where units wait matters far more than the dispatch rule.** For 31 PCR units: 87.0% within 5 minutes with forecast-optimised standby points, vs 68.7% evenly spread and 74.8% for random nodes. This assumes demand concentrates on main roads like our generator does.
- **Ambulance results swing wildly with the call rate** (6 units, evenly spread, nearest-ETA): about **57%** within 8 minutes at 20 calls/day, **44%** at 40/day, **20%** at 80/day. We cannot say anything about ambulances until the real rate is known.

---

## 3. Why each item you find matters

| If you find... | It lets us... |
|---|---|
| Real station coordinates | replace the test placement and measure the gain over how things are actually arranged today |
| Vehicles per station and shifts | model real capacity instead of "2 tenders each, 45% on duty" |
| Fire and ambulance calls per day (and hourly pattern) | set realistic load; this decides whether ambulance and fire results are meaningful at all |
| Time on scene and hospital handover time | model how long units stay unavailable |
| Real response times for fire and 108 | calibrate each baseline the way we calibrated PCR |
| Dispatch workflow (who dispatches 101 and 108, GPS, nearest-unit rule) | describe the baseline honestly |
| Whether traffic signals are centrally controlled | decide whether the "green corridor" can be real or must be simulated |

---

## 4. Terms
- **PCR:** Police Control Room van or motorcycle (patrol and emergency response). **ERSS-112:** the unified emergency number and its control room. **108/102:** ambulance services (108 emergency, 102 patient transport).
- **CAD / AVL / MDT:** computer-aided dispatch, automatic vehicle location (GPS), mobile data terminal in a vehicle.
- **Unit:** one vehicle that can be dispatched independently.
- **ALP:** aerial ladder platform (fire). **BLS/ALS:** basic and advanced life support ambulances.

---

## 5. What is already known

### 5.1 Verified by reading the source
| Fact | Value | Source |
|---|---|---|
| PCR fleet | 57 four-wheelers + 12 motorcycles | [Tribune, 10 Oct 2026](https://www.tribuneindia.com/news/chandigarh/chandigarh-police-2nd-in-emergency-response-time-nationally) |
| ERSS-112 average response | 4 min 32 s (Jan to Sep 2026); 7 min 5 s in 2022 | same |
| Dispatch rule | CAD sends the **nearest unit**; GPS trackers and MDTs in vehicles | same |
| Call volume | over 300 calls a day | same |
| National rank | second, behind Himachal Pradesh (4 min 4 s) | same |
| Earlier fleet and time | 104 PCR vehicles (86 four-wheelers + 18 motorcycles), 5.6 min (Jan to Jul 2025), 6.31 min in 2024, national average 18.61 | [Tribune, 2025](https://www.tribuneindia.com/news/chandigarh/chandigarh-cops-quickest-to-respond-in-country-5-6-min-new-record) |
| Fire stations planned | Municipal Corporation decided to build two more, at Sector 53 and IT Park (reported 6 July 2017; status unknown) | [Tribune, 2017](https://www.tribuneindia.com/news/archive/chandigarh/chandigarh-to-have-2-more-fire-stations-in-sec-53-it-park-432971) |

**Open question:** why does the fleet fall from 104 (2025) to 69 (2026)? Different counting, a sale or retirement, or an error in one of the articles?

### 5.2 Unverified: compiled by another AI, to be checked
- **Fire stations (7):** Sector 17 (HQ, Main Road); Sector 11 (11B/11D, Main Road); Sector 32 (32C, Chandi Path); Sector 38 (38C); Manimajra (Modern Housing Board Complex); Industrial Area Phase I (MW Area, Purv Marg); Industrial Area Phase II (Ram Darbar side). Phone numbers differ between listings. The Chief Fire Officer's office is reportedly in MC Deluxe Building, Sector 17. Dial 101.
- **Ambulances (108):** only **6 vehicles at 6 stationing points**, from the launch era, with locations unpublished and current fleet unknown. Destination hospitals: PGIMER (Sector 12), GMCH-32, GMSH-16, Civil Hospital Sector 22, Civil Hospital Manimajra. 108 may now be dispatched through the 112 control room.
- **Police stations (16):** PS Sector 3, 11, 17, Sarangpur, 19, 26, 31, 34, 36, 39, Maloya, 49, Industrial Area, Manimajra, Mouli Jagran, IT Park; plus Women PS and Cyber Crime PS.
- **Police posts (17):** Lake, 24, PGI, 22, Neelam (Sector 17), ISBT-17, GH-16, GH-22, Bapu Dham (26), Burail, GMCH-32, 61, ISBT-43, Palsora, Dariya, Dhanas, Railway Station.
- **PCR structure:** control room at Police HQ, Sector 9; PCR unit at Police Lines, Sector 26; split into East, Central and South divisions.
- **Crashes (Tribune):** 2025: 191 crashes, 83 fatal, 86 deaths. 2023: 182 / 64 / 67. 2022: 237 / 79 / 83. 2024 deaths revised from 81 to 75.
- **Crash hotspots:** Kalagram light point and Housing Board light point (Madhya Marg), Milk Colony (Dhanas) light point (each reportedly 5 deaths in 5+ crashes, 2023 to 2025); Sector 46/47/48/49 light point (Vikas Marg); Airport light point to CRPF campus, Hallo Majra; Transport light point, Sector 26; Poultry Farm chowk to BSNL turn (Industrial Area); ISBT Sector 43 road.

---

## 6. The research tasks

Do these in priority order. For every item: the value, the source, and a confidence level. If Chandigarh data does not exist, say so and offer a clearly labelled proxy.

### Priority 1: call volumes and performance

| ID | Find | Preferred form | Acceptable fallback |
|---|---|---|---|
| **1A** | **Fire calls**: per year and per day, by type (fire, rescue, false alarm, special service); by station if available; monthly or hourly pattern | official annual figures | NCRB/ADSI fire-accident counts, news reports quoting the fire department, per-capita proxies from comparable cities (labelled) |
| **1B** | **Ambulance calls or trips** (108, 102, hospital-run): per year and per day, by type (road accident, medical, other); hourly pattern | NHM Chandigarh or health-department dashboards and replies | national 108 benchmarks (trips per ambulance per day), comparable UTs (labelled) |
| **1C** | **112 totals**: calls per day, and what share become police, fire and ambulance dispatches | ERSS dashboards, MHA or Chandigarh Police statements | state-level 112 statistics |
| **1D** | **Response performance for fire and 108**: average response time, share within a target (for example under 8 or 10 minutes), the official target | official reports, parliamentary replies | news reports |
| **1E** | **Current fleet**: fire tenders by type (water tender, foam, ALP, rescue) per station and in total; ambulances by type; whether the 108 count is still 6 | MC Chandigarh, NHM | news reports with dates |
| **1F** | **Service times**: average time on scene, and ambulance hospital handover time | any study or report | published Indian EMS studies (labelled) |

### Priority 2: real locations and deployment

| ID | Find | Notes |
|---|---|---|
| **2A** | Coordinates for the 7 fire stations | cross-check two sources |
| **2B** | Where the 6 108 ambulances are stationed, if published anywhere; coordinates of any stationing points | if only hospitals are known, give hospital coordinates and say so |
| **2C** | Coordinates for the 16 police stations and 17 posts | OSM and Google Maps both |
| **2D** | Units per station: fire tenders, ambulances, PCR vans or motorcycles per station or beat | |
| **2E** | PCR deployment: beats, shifts, and the fraction of the 69 (or 104) vehicles on duty at once | we assumed 45% |
| **2F** | Were the Sector 53 and IT Park fire stations ever built? Any other new stations since 2017? | |

### Priority 3: only if time allows
- **3A:** Coordinates of the crash hotspots listed in 5.2.
- **3B:** **Dispatch workflow:** who dispatches fire (101) and 108, whether those vehicles have GPS and are dispatched through a CAD, and whether they also use a nearest-unit rule.
- **3C:** **Traffic signals:** does Chandigarh have centrally controlled or adaptive signals (Smart City ICCC, ITMS)? How many junctions, and who controls them (Traffic Police, Chandigarh Smart City Limited)? Is there any emergency-vehicle priority today?

---

## 7. Where to look

**Official:** Municipal Corporation Chandigarh (fire and emergency services pages); Chandigarh Police and ERSS-112 pages; Chandigarh Administration, Health Department and NHM (108); the **Chandigarh Statistical Abstract** (Economic and Statistical Organisation); data.gov.in; NCRB "Accidental Deaths and Suicides in India" (fire accidents by city); Lok Sabha and Rajya Sabha questions on fire services or ambulances in UT Chandigarh; MHA and MoHFW reports; published RTI replies; emergency statistics from PGIMER, GMCH-32 and GMSH-16.

**Journalism:** The Tribune, Hindustan Times, Times of India, Indian Express, Dainik Bhaskar, Dainik Jagran. Hindi and Punjabi sources are welcome.

**Coordinates:** OpenStreetMap, Google Maps, Wikimapia. Cross-check at least two where possible.

**Search ideas (English and Hindi):** "Chandigarh fire department calls 2024 2025", "चंडीगढ़ फायर ब्रिगेड कॉल", "Chandigarh 108 ambulance trips per day", "Chandigarh fire tenders per station", "Chandigarh Statistical Abstract fire calls", "Rajya Sabha question fire stations Chandigarh", "Chandigarh ICCC adaptive traffic signals junctions".

---

## 8. Rules of evidence

1. Every figure needs a **source URL, publication date, the year the figure refers to, and a source type**: official, news, directory, RTI, or your inference.
2. **When sources conflict, list every value side by side.** Do not average or silently pick one.
3. Prefer 2023 to 2026 data and say when a figure is older.
4. **Coordinates:** five decimal places, a source link, and an accuracy label: `exact` (building verified), `approx`, or `sector_centroid`. A sector centroid can be about 600 m off, so use it only as a last resort and never label it exact. We snap coordinates to the road network and need roughly 300 m accuracy.
5. **Proxies** (other cities, national benchmarks) must be labelled "proxy, not Chandigarh" and must never be mixed into Chandigarh rows.
6. If something is not public, write **"not found"**, list where you searched, and **draft a three-line RTI question** naming the likely department and public information officer.
7. Do not repeat a number from section 5.2 as confirmed unless you found it yourself in a source.

---

## 9. Output format

Return plain-text tables, one row per item. Use these columns exactly.

**Table A: stations**
```
kind,name,sector_or_area,lat,lng,coord_source_url,coord_accuracy,units,unit_types,units_source_url,units_confidence,notes
```
- `kind`: fire, ambulance, police, post
- `coord_accuracy`: exact, approx, sector_centroid
- `units_confidence`: high, medium, low

**Table B: volumes and performance**
```
service,metric,value,unit,period,breakdown,source_url,source_type,confidence,notes
```
- `service`: fire, ambulance, police, 112
- `unit`: per_day, per_year, minutes, percent, count
- `source_type`: official, news, directory, RTI, proxy, inference
- `confidence`: high, medium, low

Then add, in this order:
1. **CONFLICTS:** every disagreement between sources, with both values.
2. **NOT FOUND:** each item you could not find, with where you searched.
3. **RTI DRAFTS:** three lines each, for the not-found items that matter most.
4. **KEY FINDINGS:** the five most important results in plain language.

---

## 10. If you can only do three things

1. Fire and ambulance **calls per day** for Chandigarh (1A, 1B), with the hourly pattern if possible.
2. **Coordinates and vehicle counts** for the 7 fire stations and the ambulance stationing points (2A, 2B, 2D, 1E).
3. Real **response times and fleet** for fire and 108 (1D, 1E).

Partial answers are useful. A confident wrong answer is worse than a gap.
