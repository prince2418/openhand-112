# Benchmark results (synthetic incidents, real Chandigarh roads and stations)

Run: 6 seeds × 30 days per scenario. Calibrated travel-time scale **0.912** (today's rule from today's police stations reproduces the published 4:32). All incidents are synthetic; every assumption is listed in `run_benchmark.py`.

Rows: `dispatch rule @ standby placement`. `nearest_distance@current` = today's rule (CAD sends the nearest unit) from today's stations. CI = 95% day-block bootstrap, in percentage points of calls reached within target.

## PCR (31 of 69 vehicles on duty, 300 calls/day, 5-min target)

Utilisation 22.1%, calls that waited for a free unit 0.0%.

| dispatch@placement | reached in target | mean min | p90 min | vs today, pts [95% CI] |
|---|---|---|---|---|
| nearest_distance@current | 66.5% | 4.52 | 6.98 | baseline |
| nearest_eta@current | 68.6% | 4.41 | 6.81 | +2.1 [+1.9, +2.3] |
| coverage@current | 67.7% | 4.50 | 6.79 | +1.2 [+1.0, +1.5] |
| nearest_eta@spread | 73.7% | 4.16 | 6.43 | +7.2 [+6.7, +7.7] |
| nearest_eta@rebalanced | 70.0% | 4.38 | 6.67 | +3.5 [+3.2, +3.8] |
| nearest_eta@optimised | 87.7% | 3.42 | 5.24 | +21.2 [+20.8, +21.7] |

Optimised standby vs the strongest non-optimised placement (`nearest_eta@spread`): **+14.0 pts** [+13.7, +14.4].

Sensitivity to the key assumption:

- units=22: today 53.7% → optimised standby 76.1% (vs strongest reference +15.8 pts)
- units=45: today 70.8% → optimised standby 95.7% (vs strongest reference +22.4 pts)

## Fire (14 tenders at 7 stations, 5 calls/day, 5-min target)

Utilisation 1.7%, calls that waited for a free unit 0.0%.

| dispatch@placement | reached in target | mean min | p90 min | vs today, pts [95% CI] |
|---|---|---|---|---|
| nearest_distance@current | 53.1% | 5.13 | 8.08 | baseline |
| nearest_eta@current | 55.5% | 5.04 | 7.79 | +2.4 [+1.4, +3.4] |
| coverage@current | 55.5% | 5.05 | 7.79 | +2.4 [+1.4, +3.4] |
| nearest_eta@spread | 63.3% | 4.63 | 6.97 | +10.2 [+5.8, +14.5] |
| nearest_eta@rebalanced | 55.5% | 5.04 | 7.79 | +2.4 [+1.4, +3.4] |
| nearest_eta@optimised | 88.8% | 3.55 | 5.09 | +35.7 [+32.0, +39.4] |

Optimised standby vs the strongest non-optimised placement (`nearest_eta@spread`): **+25.5 pts** [+22.5, +28.7].

Sensitivity to the key assumption:

- rate=2: today 55.2% → optimised standby 89.0% (vs strongest reference +32.4 pts)
- rate=10: today 49.3% → optimised standby 87.9% (vs strongest reference +35.9 pts)

> Fire rows `spread` and `optimised` move tenders away from stations, which is not realistic (crews, equipment, water). They are upper bounds only; the realistic fire question is station siting, below.

## Ambulance (6 vehicles at the five 108 hospitals, 40 calls/day, 8-min target)

Utilisation 27.0%, calls that waited for a free unit 2.5%.

| dispatch@placement | reached in target | mean min | p90 min | vs today, pts [95% CI] |
|---|---|---|---|---|
| nearest_distance@current | 57.0% | 8.34 | 14.13 | baseline |
| nearest_eta@current | 57.8% | 8.27 | 13.99 | +0.8 [+0.3, +1.2] |
| coverage@current | 56.6% | 8.53 | 13.80 | -0.4 [-1.1, +0.3] |
| nearest_eta@spread | 49.0% | 9.37 | 14.93 | -8.0 [-9.4, -6.7] |
| nearest_eta@rebalanced | 63.1% | 7.65 | 12.66 | +6.0 [+5.3, +6.7] |
| nearest_eta@optimised | 79.3% | 6.44 | 10.31 | +22.3 [+21.1, +23.5] |

Optimised standby vs the strongest non-optimised placement (`nearest_eta@rebalanced`): **+16.3 pts** [+15.1, +17.4].

Sensitivity to the key assumption:

- rate=20: today 67.4% → optimised standby 88.9% (vs strongest reference +18.0 pts)
- rate=80: today 33.5% → optimised standby 47.9% (vs strongest reference +9.2 pts)

## PCR robustness: what if our demand assumption or forecast is wrong?

- flat demand, forecast learned it: optimised vs strongest reference **+20.0 pts** [+19.5, +20.5]
- flat demand, forecast learned busy-road shape (wrong): optimised vs strongest reference **+19.3 pts** [+18.8, +19.8]
- busy-road demand, forecast learned flat shape (wrong): optimised vs strongest reference **+18.5 pts** [+18.1, +19.0]

The gain barely moves, so it comes from where vans wait on the road network, not from predicting demand precisely.

## Fire: where should the next stations go? (`scripts/fire_siting.py`)

Fire tenders need stations, so free standby points are not realistic for fire. Instead: which new sites add the most risk reachable in 5 minutes? (2 tenders per existing station, 1 per new one; assumptions.)

| option | fire risk within 5 min | calls reached in 5 min | vs today, pts [95% CI] |
|---|---|---|---|
| today: 7 stations | 51.0% | 53.0% | baseline |
| +1 best new site | 65.3% | 65.0% | +12.0 [+10.7, +13.5] |
| +2 best new sites | 73.4% | 70.7% | +17.6 [+16.0, +19.3] |
| +MC 2017 plan (IT Park only; Sector 53 pin missing) | 53.0% | 54.7% | +1.7 [+1.1, +2.3] |

Best new sites (lat, lng): (30.71230, 76.74631), (30.72625, 76.79397).

## What these results do NOT show

- **Today's PCR positions are unknown.** We model 2 vans per police station. If vans already wait at well-spread points, calibrating to 4:32 gives almost the same baseline (66.2% in 5 min) and the same gain (+20.8 pts). But if they were already placed as well as our optimiser, 4:32 would simply mean roads ~25% slower than assumed, and the gain would vanish. The Google Maps route check below settles which.
- **All incidents are synthetic.** Locations follow road class (PCR), population proxy (ambulance, fire) and the 4 official black spots (crash); none of it is real incident data.
- **Ambulance and fire call volumes are assumptions**, hence the sweeps. At 80 ambulance calls/day, 6 vehicles are overloaded whatever the placement: that is a fleet-size problem.
- **ETA dispatch is the industry baseline, not our contribution.** It adds about 2 points over nearest-by-distance. The coverage-aware rule never beats it.
- Emergency vehicles' real speeds, traffic and signal priority are not modelled beyond a time-of-day multiplier.

## Pending check: are our road speeds right? (Google Maps, free)

Model drive times at 11 am on a weekday, for two calibrations. If Google's typical times are closer to the left number, today's vans are not already well placed and the PCR gain stands; closer to the right number, the gain shrinks towards zero.

| route | model min (scale 0.91) | model min (scale 1.25) |
|---|---|---|
| PS Sector 17 -> PGIMER | 6.2 | 8.4 |
| Fire Stn Sector 32 -> Tribune Chowk | 2.3 | 3.1 |
| PS Manimajra -> GMCH-32 | 8.8 | 12.1 |
| Fire Stn Sector 38 -> ISBT Sector 43 | 6.6 | 9.0 |
| PS Sector 3 -> Civil Hospital Sector 22 | 6.4 | 8.8 |
| Fire Stn Ind Area Ph-II -> Hallomajra light point | 3.3 | 4.5 |
| PS IT Park -> PS Sector 26 | 8.1 | 11.0 |
| PS Sector 39 -> PS Sector 11 | 11.0 | 15.0 |

## Update 13 Oct 2026: textbook baseline, distribution and demand sweep

Command: `python run_benchmark.py --robustness --demand-sweep` (6 seeds x 30 days, same calls for every row; 95 percent intervals from resampling whole days). Travel-time scale recalibrated to 0.901 after two police-station coordinates were corrected.

**MEXCLP (Daskin 1983), the textbook ambulance-location model, beat our first greedy planner, so the app now uses MEXCLP for standby points.**

| PCR arrangement | In 5 min | Median | 90% within | Worst-served sector |
|---|---|---|---|---|
| Today: nearest on the map, vans at stations | 66.0% | 4.25 min | 6.95 min | Sector 52: 14.3% |
| Fastest by road, vans at stations | 68.2% | 4.16 min | 6.74 min | Sector 52: 15.5% |
| Fastest by road, vans shared by demand | 68.9% | 4.19 min | 6.63 min | Sector 52: 16.4% |
| Fastest by road, our greedy planner | 87.5% | 3.21 min | 5.26 min | Sector 55: 66.5% |
| Fastest by road, MEXCLP standby | 92.6% | 3.00 min | 4.72 min | Sector 48: 70.8% |

Greedy planner vs MEXCLP: -5.16 pts [-5.48, -4.85].

| Demand pattern (PCR) | Today | MEXCLP | Gain [95% CI] |
|---|---|---|---|
| busy roads (our default) | 66.0% | 92.6% | +26.7 [+26.2, +27.1] |
| even over all streets (built-up area) | 63.4% | 91.1% | +27.7 [+27.3, +28.2] |
| crash-like, with black spots | 68.4% | 92.7% | +24.3 [+23.8, +24.7] |
| hotspot-heavy (black spots x20) | 71.3% | 90.1% | +18.8 [+18.3, +19.1] |
| night shift (20 vans) | 48.7% | 78.3% | +29.6 [+29.1, +30.1] |

Still not modelled: joint assignment of simultaneous calls, ambulance hospital choice and handover delay, breakdowns and re-dispatch, mutual aid with Mohali and Panchkula. The biggest caveat is unchanged: today's real van waiting positions are not published.
