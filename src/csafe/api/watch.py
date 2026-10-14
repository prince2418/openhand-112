"""Predict and monitor: what the next hours should look like, and live alerts when today doesn't match.

Three parts, all deterministic and cheap enough to run on every poll:

  outlook : expected 112 calls per hour for the next 6 hours by service, with an 80% range (Poisson),
            how stretched each fleet will be (Erlang B: chance that no unit is free when a call comes),
            and the sectors where incidents are most likely in the next hour.
  watch   : live alerts from the incidents in the app
            - cluster: more incidents close together than the forecast allows (Poisson tail p < 0.01)
            - surge: more incidents of one kind city-wide than expected in the last hour
            - coverage: share of calls a PCR van can reach in 5 min right now, the sectors that lost it,
              and the one move that wins back the most (a free van to a standby point)
            - fleet: ambulances or fire tenders running low
            - rain: roads the waterlogging plan says will close soon
  skill   : how well a hotspot forecast learned from 90 days of incidents predicts the next 30 days
            (hit rate and the Predictive Accuracy Index, Chainey et al. 2008), on simulated incidents.

Every rate below is labelled. Calls per day: PCR >300/day (PUBLISHED); ambulance 40 and fire 5 (ASSUMPTIONS,
same as the benchmark). Weather multipliers are ASSUMPTIONS.
"""
from __future__ import annotations

import math
import time

import numpy as np
from scipy.sparse.csgraph import dijkstra
from scipy.stats import poisson

from ..demand import HOURLY_PROFILE, estimate_weights, generate, scenario_weights

SERVICE = {   # calls/day, minutes busy per call (drive + on scene + back), units on duty
    "police": dict(label="PCR", rate=300.0, busy_min=30.0, weights="pcr"),
    "ambulance": dict(label="Ambulance", rate=40.0, busy_min=53.0, weights="ambulance"),
    "fire": dict(label="Fire tender", rate=5.0, busy_min=70.0, weights="fire"),
}
CRASH_PER_DAY = 20.0          # road crashes reaching 112 per day (ASSUMPTION; part of the PCR volume)
FOG_MULT = {"police": 1.10, "ambulance": 1.10, "fire": 1.0}      # ASSUMPTION: more crashes in fog
RAIN_MULT = {"police": 1.15, "ambulance": 1.10, "fire": 1.0}     # ASSUMPTION: waterlogging, stalled cars, crashes
TYPE_SERVICE = {"road_accident": "crash", "fire": "fire", "medical": "ambulance"}
CLUSTER_R_M = 700.0
WINDOW_S = 3600.0             # look-back window, simulated seconds (6 real minutes on the x10 demo clock)
P_ALERT = 0.01
PCR_REACH_S = 300 - 60        # 5-min PCR target minus call handling


def erlang_b(load: float, c: int) -> float:
    """Chance that all c units are busy when a call arrives, for offered load `load` (Erlangs)."""
    if c <= 0:
        return 1.0
    b = 1.0
    for k in range(1, c + 1):
        b = load * b / (k + load * b)
    return b


class Watch:
    def __init__(self, world):
        self.w = world
        net = world.net
        hs = str(world.ROOT_HOTSPOTS)
        self.weights = {k: scenario_weights(net, v["weights"], hs) for k, v in SERVICE.items()}
        self.weights["crash"] = scenario_weights(net, "crash", hs)
        self.xy = net._xy(net.lat, net.lon)
        from scipy.spatial import cKDTree
        self.tree = cKDTree(self.xy)
        self._skill = None
        self._cand = None          # (closure version, standby node list, travel-time rows)
        self._cache = (0.0, None)
        self.dismissed: set[str] = set()

    # ---------- helpers ----------
    def _sector(self, node: int) -> int:
        return int(self.w.flood.sector_of_node[node])

    def _place(self, lat: float, lng: float) -> str:
        """A name people know for a point: nearest landmark or black spot within 600 m, else the sector."""
        best, bd = None, 600.0
        for h in self.w.hotspots:
            d = math.hypot((h["lat"] - lat) * 111_320, (h["lng"] - lng) * 95_700)
            if d < bd:
                best, bd = h["name"].split(" (")[0], d
        node = int(self.w.net.snap(lat, lng)[0])
        sec = int(self.w.flood.sector_label(node))
        if best:
            return f"{best} (Sector {sec})" if sec else best
        return f"Sector {sec}"

    def multipliers(self) -> tuple[dict, list[str]]:
        m = {k: 1.0 for k in SERVICE}
        why = []
        if self.w.fog:
            m = {k: m[k] * FOG_MULT[k] for k in m}
            why.append("winter fog (+10% PCR and ambulance calls, assumption)")
        fl = self.w._flood_state()
        if fl and (fl["closed"] or fl["diverted"]):
            m = {k: m[k] * RAIN_MULT[k] for k in m}
            why.append("waterlogging on the roads (+15% PCR, +10% ambulance calls, assumption)")
        return m, why

    def on_duty(self) -> dict:
        return {k: sum(1 for u in self.w.units.values() if u.kind == k and not u.off_duty) for k in SERVICE}

    # ---------- outlook ----------
    def outlook(self, hours: int = 6) -> dict:
        h0 = self.w.hour()
        mult, why = self.multipliers()
        duty = self.on_duty()
        rows = []
        for i in range(hours):
            h = (h0 + i) % 24
            r = {"hour": f"{h:02d}:00", "services": {}}
            for k, s in SERVICE.items():
                lam = s["rate"] * HOURLY_PROFILE[h] * mult[k]
                load = lam * s["busy_min"] / 60.0
                lam, load = float(lam), float(load)
                r["services"][k] = dict(expected=round(lam, 1), low=int(poisson.ppf(0.1, lam)), high=int(poisson.ppf(0.9, lam)),
                                        busy=round(load, 1), units=duty[k], p_none_free=round(erlang_b(load, duty[k]) * 100, 1))
            rows.append(r)
        # where, next hour: expected incidents per sector across services
        h = h0 % 24
        lam_node = sum(SERVICE[k]["rate"] * HOURLY_PROFILE[h] * mult[k] * self.weights[k] for k in SERVICE)
        crash_node = CRASH_PER_DAY * HOURLY_PROFILE[h] * mult["police"] * self.weights["crash"]
        sec = self.w.flood.sector_of_node
        zones = []
        for s in np.unique(sec[sec > 0]):
            m = sec == s
            exp, crash = float(lam_node[m].sum()), float(crash_node[m].sum())
            j = int(np.flatnonzero(m)[np.argmax(lam_node[m])])
            zones.append(dict(sector=int(s), expected=exp, crash=crash, lat=float(self.w.net.lat[m].mean()), lng=float(self.w.net.lon[m].mean()),
                              peak_lat=float(self.w.net.lat[j]), peak_lng=float(self.w.net.lon[j])))
        zones.sort(key=lambda z: -z["expected"])
        city = float(lam_node.sum())
        out_z = []
        flood_spots = {}
        if self.w.flood.run is not None:
            for sp in self.w.flood.plan()["spots"]:
                if sp["forecast"] in ("divert", "close"):
                    flood_spots.setdefault(self._sector(int(self.w.net.snap(sp["lat"], sp["lng"])[0])), []).append(sp["name"])
        for z in zones[:8]:
            reasons = []
            near = [hh["name"].split(" (")[0] for hh in self.w.hotspots
                    if hh.get("type") == "road_crash" and math.hypot((hh["lat"] - z["lat"]) * 111_320, (hh["lng"] - z["lng"]) * 95_700) < 900]
            if near:
                reasons.append(f"crash black spot: {near[0]}")
            if z["crash"] / max(z["expected"], 1e-9) > CRASH_PER_DAY / SERVICE["police"]["rate"] * 1.6:
                reasons.append("crash-prone main roads")
            if z["sector"] in flood_spots:
                reasons.append(f"waterlogging forecast: {flood_spots[z['sector']][0]}")
            if not reasons:
                reasons.append("busy roads and dense housing")
            out_z.append(dict(sector=z["sector"], lat=z["peak_lat"], lng=z["peak_lng"], expected=round(z["expected"], 2),
                              share=round(z["expected"] / city * 100, 1), crash=round(z["crash"], 2), why=reasons))
        peak = max(rows, key=lambda r: r["services"]["police"]["expected"])
        return {"from": f"{h0:02d}:00", "rows": rows, "zones": out_z, "conditions": why, "city_next_hour": round(city, 1),
                "peak_hour": peak["hour"], "skill": self.skill(),
                "notes": ["PCR >300 calls a day is published (Chandigarh Police). Ambulance 40 and fire 5 a day, minutes busy per call, "
                          "and the weather effects are assumptions, the same as in the benchmark.",
                          "Hour-of-day shape and where incidents happen come from the demand model (road class, official black spots). "
                          "Replace with ERSS call records to make it a learned forecast; the code path is the same."]}

    # ---------- forecast skill ----------
    def skill(self) -> dict:
        """Hotspot forecast learned from 90 days of (simulated) crashes, tested on the next 30 days it never saw."""
        if self._skill is None:
            net, cell = self.w.net, 450.0
            truth = self.weights["crash"]
            hist = generate(truth, CRASH_PER_DAY, 90, seed=901, mean_service_s=1).node
            test = generate(truth, CRASH_PER_DAY, 30, seed=902, mean_service_s=1).node
            prior = scenario_weights(net, "pcr")              # road class only: what you'd guess with no history
            fc = estimate_weights(net, hist, prior=prior, sigma_m=250)
            gx = np.floor(self.xy[:, 0] / cell).astype(np.int64)
            gy = np.floor(self.xy[:, 1] / cell).astype(np.int64)
            key = (gx - gx.min()) * 100_000 + (gy - gy.min())
            cells, inv = np.unique(key, return_inverse=True)
            ncell = len(cells)

            def capture(w: np.ndarray, top: float = 0.10) -> float:
                score = np.bincount(inv, weights=w, minlength=ncell)
                k = max(1, int(round(top * ncell)))
                hot = np.zeros(ncell, bool)
                hot[np.argsort(-score)[:k]] = True
                return float(hot[inv[test]].mean())

            hit_fc, hit_prior, hit_best = capture(fc), capture(prior), capture(truth)
            self._skill = dict(area_pct=10, hit_pct=round(hit_fc * 100, 1), pai=round(hit_fc / 0.10, 2),
                               prior_hit_pct=round(hit_prior * 100, 1), prior_pai=round(hit_prior / 0.10, 2),
                               best_hit_pct=round(hit_best * 100, 1), of_best_pct=round(hit_fc / hit_best * 100),
                               train_days=90, test_days=30, train_n=int(len(hist)), test_n=int(len(test)), cell_m=int(cell),
                               note="Simulated crashes (20 a day, placed by the demand model). The test month is drawn separately and never "
                                    "seen in training. Run the same code on ERSS crash records to get the real number.")
        return self._skill

    # ---------- live watch ----------
    def _recent(self) -> list:
        now = self.w.now()
        return [i for i in self.w.incidents.values() if i.lat is not None and now - i.t <= WINDOW_S]

    def _clusters(self, h: int, mult: dict) -> list[dict]:
        incs = self._recent()
        if len(incs) < 2:
            return []
        net = self.w.net
        pts = net._xy([i.lat for i in incs], [i.lng for i in incs])
        out, used = [], set()
        for a in range(len(incs)):
            d = np.hypot(*(pts - pts[a]).T)
            grp = [b for b in np.flatnonzero(d <= CLUSTER_R_M)]
            if len(grp) < 2:
                continue
            ids = frozenset(incs[b].id for b in grp)
            if ids in used or any(ids < u for u in used):
                continue
            used.add(ids)
            nodes = self.tree.query_ball_point(pts[a], CLUSTER_R_M)
            span = max(incs[b].t for b in grp) - min(incs[b].t for b in grp)
            win = max(span, 900.0)        # scan window: the cluster's own time span, at least 15 min (simulated)
            mu = sum(SERVICE[k]["rate"] * HOURLY_PROFILE[h] * mult[k] * float(self.weights[k][nodes].sum()) for k in SERVICE) * win / 3600
            n = len(grp)
            p = float(poisson.sf(n - 1, mu))
            if p >= P_ALERT:
                continue
            types = sorted({incs[b].triage["extract"]["incident_type"] for b in grp})
            c = incs[a]
            out.append(dict(id="cluster-" + "-".join(sorted(ids)), kind="cluster", level="high" if p < 0.001 else "medium",
                            title=f"{n} incidents within 700 m of {self._place(c.lat, c.lng)}",
                            text=f"In {max(1, round(span / 60))} min (demo clock). The forecast for this area over {round(win / 60)} min is {mu:.2f}, "
                                 f"so this is unusual (p {'< 0.001' if p < 0.001 else f'= {p:.3f}'}). Types: {', '.join(t.replace('_', ' ') for t in types)}.",
                            todo="Look for one cause (a pile-up, a fight spreading, a gas leak). Check the nearest cameras and send a supervisor; "
                                 "keep the next free PCR close.",
                            lat=c.lat, lng=c.lng, radius_m=CLUSTER_R_M, incidents=sorted(ids), expected=round(mu, 3), observed=n, p=p))
        return out

    def _surges(self, h: int, mult: dict) -> list[dict]:
        incs = self._recent()
        out = []
        rate = {"crash": CRASH_PER_DAY * mult["police"], "fire": SERVICE["fire"]["rate"] * mult["fire"],
                "ambulance": SERVICE["ambulance"]["rate"] * mult["ambulance"] * 0.5}
        names = {"crash": "road crashes", "fire": "fires", "ambulance": "medical emergencies"}
        for t, svc in TYPE_SERVICE.items():
            n = sum(1 for i in incs if i.triage["extract"]["incident_type"] == t)
            if n < 2:
                continue
            mu = rate[svc] * HOURLY_PROFILE[h] * WINDOW_S / 3600
            p = float(poisson.sf(n - 1, mu))
            if p < P_ALERT:
                out.append(dict(id=f"surge-{t}-{n}", kind="surge", level="medium",
                                title=f"{n} {names[svc]} city-wide in the last hour",
                                text=f"Expected about {mu:.1f} at this hour (p {'< 0.001' if p < 0.001 else f'= {p:.3f}'}).",
                                todo="Tell the shift supervisor; check for a common cause (weather, an event, a chemical leak) and hold one unit back.",
                                expected=round(mu, 2), observed=n, p=p))
        return out

    def _candidates(self):
        """Travel times from each standby point (the MEXCLP plan), recomputed only when roads open or close."""
        ver = (len(self.w.closures), tuple(sorted(self.w.flood.node_level.items()))[:50], self.w.fog)
        if self._cand is None or self._cand[0] != ver:
            pts = self.w.standby_plan()["points"]
            nodes = np.unique(self.w.net.snap(np.array([p["lat"] for p in pts]), np.array([p["lng"] for p in pts])))
            T = dijkstra(self.w.net.A, directed=True, indices=nodes)
            self._cand = (ver, nodes, T)
        return self._cand[1], self._cand[2]

    @staticmethod
    def _free(u) -> bool:
        """Free for cover: parked, or driving back/to a standby point with no incident (it covers from where it is going)."""
        return u.status == "available" or (u.status == "returning" and u.incident is None)

    def coverage(self) -> dict:
        w = self.w
        k = w.travel_scale()
        dem = self.weights["police"]
        duty = [u for u in w.units.values() if u.kind == "police" and not u.off_duty]
        free = [u for u in duty if self._free(u)]
        homes_all = sorted({u.home for u in duty})
        t_all = dijkstra(w.net.A, directed=True, indices=homes_all, min_only=True) * k if homes_all else np.full(w.net.n, np.inf)
        homes = sorted({u.home for u in free})
        t_now = dijkstra(w.net.A, directed=True, indices=homes, min_only=True) * k if homes else np.full(w.net.n, np.inf)
        cov_all = float(dem[t_all <= PCR_REACH_S].sum() * 100)
        cov_now = float(dem[t_now <= PCR_REACH_S].sum() * 100)
        lost = (t_all <= PCR_REACH_S) & (t_now > PCR_REACH_S)
        secs = {}
        for n in np.flatnonzero(lost):
            s = self._sector(n)
            if s:
                secs[s] = secs.get(s, 0.0) + float(dem[n])
        out = dict(now=round(cov_now, 1), all_free=round(cov_all, 1), free=len(free), on_duty=len(duty),
                   sectors_lost=[int(s) for s, _ in sorted(secs.items(), key=lambda x: -x[1])[:6]], move=None)
        if free and cov_all - cov_now >= 1.0:
            nodes, T = self._candidates()
            covered = t_now <= PCR_REACH_S
            gain = ((T * k <= PCR_REACH_S) & ~covered[None, :]).astype(float) @ dem
            # moving a van also uncovers what only it covered: pick the van whose base matters least now
            best = None
            for j in np.argsort(-gain)[:5]:
                if gain[j] * 100 < 1.0:
                    break
                for u in sorted(free, key=lambda u: float(np.hypot(*(self.xy[u.home] - self.xy[nodes[j]])))):
                    others = sorted({v.home for v in free if v.id != u.id} | {int(nodes[j])})
                    t2 = dijkstra(w.net.A, directed=True, indices=others, min_only=True) * k
                    net_gain = float(dem[t2 <= PCR_REACH_S].sum() * 100) - cov_now
                    if best is None or net_gain > best[0]:
                        best = (net_gain, u, int(nodes[j]))
                    break
            if best and best[0] >= 1.0:
                g, u, n = best
                out["move"] = dict(unit=u.id, base=u.base_name, lat=float(w.net.lat[n]), lng=float(w.net.lon[n]),
                                   from_lat=float(w.net.lat[u.home]), from_lng=float(w.net.lon[u.home]),
                                   gain=round(g, 1), place=self._place(float(w.net.lat[n]), float(w.net.lon[n])))
        return out

    def spread_plan(self, max_moves: int = 16) -> dict | None:
        """Vans parked two to a station cover the same streets. Send the extra ones to the standby points that add
        the most 5-minute cover (greedy over the MEXCLP points). Moving a second van off a station loses no cover."""
        w = self.w
        k = w.travel_scale()
        dem = self.weights["police"]
        free = [u for u in w.units.values() if u.kind == "police" and u.status == "available" and not u.off_duty]
        if len(free) < 2:
            return None
        homes = sorted({u.home for u in w.units.values() if u.kind == "police" and not u.off_duty and self._free(u)})
        t_now = dijkstra(w.net.A, directed=True, indices=homes, min_only=True) * k
        covered = t_now <= PCR_REACH_S
        before = float(dem[covered].sum() * 100)
        nodes, T = self._candidates()
        reach = (T * k) <= PCR_REACH_S
        count: dict[int, list] = {}
        for u in free:
            count.setdefault(u.home, []).append(u)
        taken = set(homes)
        moves, after = [], before
        for _ in range(max_moves):
            stacked = [u for us in count.values() if len(us) > 1 for u in us[1:]]
            if not stacked:
                break
            gain = (reach & ~covered[None, :]).astype(float) @ dem
            for j, n in enumerate(nodes):
                if int(n) in taken:
                    gain[j] = -1
            j = int(np.argmax(gain))
            if gain[j] * 100 < 0.5:
                break
            n = int(nodes[j])
            u = min(stacked, key=lambda v: float(np.hypot(*(self.xy[v.home] - self.xy[n]))))
            count[u.home].remove(u)
            taken.add(n)
            covered |= reach[j]
            after += float(gain[j] * 100)
            moves.append(dict(unit=u.id, base=u.base_name, lat=float(w.net.lat[n]), lng=float(w.net.lon[n]),
                              from_lat=float(w.net.lat[u.home]), from_lng=float(w.net.lon[u.home]),
                              place=self._place(float(w.net.lat[n]), float(w.net.lon[n])), gain=round(float(gain[j] * 100), 1)))
        if not moves or after - before < 3.0:
            return None
        return dict(before=round(before, 1), after=round(after, 1), moves=moves)

    def watch(self) -> dict:
        t_wall = time.time()
        if self._cache[1] is not None and t_wall - self._cache[0] < 2.0:
            return self._cache[1]
        with self.w.lock:
            self.w._advance()
            h = self.w.hour()
            mult, why = self.multipliers()
            alerts = self._clusters(h, mult) + self._surges(h, mult)
            cov = self.coverage()
            if cov["move"]:
                mv = cov["move"]
                alerts.append(dict(id=f"cover-{mv['unit']}-{round(mv['lat'], 4)}", kind="coverage", level="medium",
                                   title=f"5-minute PCR cover down to {cov['now']:.0f}% (normally {cov['all_free']:.0f}%)",
                                   text=f"{cov['on_duty'] - cov['free']} of {cov['on_duty']} vans are busy."
                                        + (f" Sectors that lost cover: {', '.join(map(str, cov['sectors_lost']))}." if cov["sectors_lost"] else ""),
                                   todo=f"Move {mv['unit']} from {mv['base']} to wait near {mv['place']}: wins back {mv['gain']:.1f}% of calls.",
                                   action=dict(kind="reposition", unit=mv["unit"], lat=mv["lat"], lng=mv["lng"], label=f"Move {mv['unit']}"),
                                   lat=mv["lat"], lng=mv["lng"], from_lat=mv["from_lat"], from_lng=mv["from_lng"]))
            sp = self.spread_plan()
            if sp:
                o = self.outlook_peak()
                alerts.append(dict(id=f"spread-{len(sp['moves'])}-{round(sp['after'])}", kind="prepare", level="medium",
                                   title=f"Spread the parked PCR vans: 5-minute cover {sp['before']:.0f}% → {sp['after']:.0f}%",
                                   text=f"{len(sp['moves'])} free vans are parked at a station with another van, covering the same streets. "
                                        f"Next PCR peak: {o['hour']} (about {o['expected']:.0f} calls an hour).",
                                   todo=f"Send {len(sp['moves'])} of them to wait at standby points (the placement plan from the benchmark).",
                                   action=dict(kind="spread", moves=[dict(unit=m["unit"], lat=m["lat"], lng=m["lng"]) for m in sp["moves"]],
                                               label=f"Move {len(sp['moves'])} vans"),
                                   moves=sp["moves"]))
            duty = self.on_duty()
            for kind, lab in (("ambulance", "ambulance"), ("fire", "fire tender")):
                fr = sum(1 for u in self.w.units.values() if u.kind == kind and u.status == "available" and not u.off_duty)
                if duty[kind] and fr <= max(1, duty[kind] // 5):
                    lam = SERVICE[kind]["rate"] * HOURLY_PROFILE[h] * mult[kind]
                    alerts.append(dict(id=f"fleet-{kind}-{fr}", kind="fleet", level="high" if fr == 0 else "medium",
                                       title=f"{fr} of {duty[kind]} {lab}s free",
                                       text=f"About {lam:.1f} {lab} calls are expected in the next hour.",
                                       todo="Ask the nearest neighbouring service (Mohali, Panchkula) to stand by for mutual aid."
                                            if fr == 0 else "Hold the free one for P1 calls; send lower-priority calls the next one that clears."))
            if self.w.flood.run is not None:
                p = self.w.flood.plan()
                soon = [a for a in p["actions"] if a["kind"] == "preclose"]
                if soon:
                    alerts.append(dict(id=f"rain-{p['now']}-{len(soon)}", kind="rain", level="medium",
                                       title=f"{len(soon)} road{'s' if len(soon) > 1 else ''} forecast to close within 2 hours",
                                       text="; ".join(a["title"].replace("Get ready to close ", "") for a in soon[:3]),
                                       todo="Put barricades and traffic posts in place before the water gets there (Rain tab has the plan)."))
            alerts = [a for a in alerts if a["id"] not in self.dismissed]
            alerts.sort(key=lambda a: (a["level"] != "high", ["cluster", "fleet", "coverage", "surge", "rain", "prepare"].index(a["kind"])))
            res = {"alerts": alerts, "coverage": cov, "conditions": why, "window_min_demo": round(WINDOW_S / 60),
                   "window_min_wall": round(WINDOW_S / 60 / self.w.demo_speed, 1)}
        self._cache = (t_wall, res)
        return res

    def outlook_peak(self) -> dict:
        h0 = self.w.hour()
        mult, _ = self.multipliers()
        hs = [(h0 + i) % 24 for i in range(12)]
        h = max(hs, key=lambda x: HOURLY_PROFILE[x])
        return dict(hour=f"{h:02d}:00", expected=float(SERVICE["police"]["rate"] * HOURLY_PROFILE[h] * mult["police"]))

    def dismiss(self, aid: str):
        self.dismissed.add(aid)
        self._cache = (0.0, None)

    def reposition(self, uid: str, lat: float, lng: float) -> dict:
        """Send a free unit to wait somewhere else: it drives there (shown moving) and that becomes its base."""
        w = self.w
        with w.lock:
            w._advance()
            u = w.units[uid]
            if u.status != "available" or u.off_duty:
                raise ValueError(f"{uid} is not free")
            dest = int(w.net.snap(lat, lng)[0])
            path = w.net.route(u.home, dest)
            coords, secs, mets = w.net.path_timed(path)
            k = w.travel_scale()
            t0 = w.now()
            u.route, u.route_t, u.route_m = coords, [t0 + x * k for x in secs], mets
            u.t_arrive = t0 + (secs[-1] * k if secs else 0.0)
            u.t_home = u.t_arrive
            u.status, u.incident = "returning", None
            u.home = dest
            place = self._place(lat, lng)
            u.base_name = f"standby near {place}"
            self._cache = (0.0, None)
            w.outbox.send("out", f"{uid} mobile data terminal", "Unit move order", "JSON over the CAD link",
                          f"{uid}: move to standby near {place}", dict(unit=uid, action="standby", lat=round(lat, 5), lng=round(lng, 5),
                                                                       reason="restore 5-minute cover"))
            return dict(unit=uid, to=place, eta_s=round(u.t_arrive - t0))
