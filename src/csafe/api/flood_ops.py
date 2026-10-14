"""Waterlogging in the live app: run a rain scenario, apply the flooded roads to routing, and write the plan.

What the plan says at any moment (all deterministic; Gemini only rewrites the public advisory):
  close    : spots at >= 30 cm: barricade points on the main roads into them, and the diversion around
  pre-close: spots forecast to reach closure in the next 2 h: barricades ready, close at the time shown
  divert   : spots at 15-30 cm: public traffic diverted, emergency vehicles may pass slowly
  pumps    : which MC flood team goes where, and by when (18 teams, MC 2025)
  rescue   : low-lying colonies at >= divert: fire and rescue on standby
  ems      : how the closures change ambulance and PCR reach, and where one free ambulance should wait
  reopen   : spots that were closed and are now below 15 cm and falling
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
from scipy.sparse.csgraph import dijkstra

from .. import flood as F
from ..demand import scenario_weights

LOOKAHEAD_H = 2.0
AMB_DRIVE_S = 480 - 60       # 8-min ambulance target minus 60 s call handling
PCR_DRIVE_S = 300 - 60       # 5-min PCR target minus call handling
MAJOR_HOSPITALS = ("PGIMER", "GMCH-32", "GMSH-16")


class FloodOps:
    def __init__(self, world):
        self.w = world
        net = world.net
        self.spots = F.load_spots(net)
        self.fit = F.calibrate(self.spots)
        self.run: dict | None = None
        self.meta: dict | None = None
        self.step: int | None = None
        self.node_level: dict[int, int] = {}
        self._risk: dict | None = None
        self._demand = scenario_weights(net, "pcr")
        self._demand = self._demand / self._demand.sum()
        roads = json.loads((F.ROOT / "data/roads.json").read_text())
        pts, names = [], []
        for name, r in roads.items():
            for lat, lng in r["points"]:
                pts.append((lat, lng)); names.append(name)
        from scipy.spatial import cKDTree
        self._road_xy = cKDTree(net._xy([p[0] for p in pts], [p[1] for p in pts]))
        self._road_names = names
        from ..triage.location import SECTOR_POINTS
        secs = sorted(SECTOR_POINTS)
        self._sec = np.array(secs)
        self._sec_xy = net._xy([SECTOR_POINTS[s][1][0] for s in secs], [SECTOR_POINTS[s][1][1] for s in secs])
        xy = net._xy(net.lat, net.lon)
        d = np.sqrt(((xy[:, None, :] - self._sec_xy[None, :, :]) ** 2).sum(axis=2))
        j = d.argmin(axis=1)
        self.sector_of_node = np.where(d[np.arange(len(j)), j] <= 900, self._sec[j], 0)
        import pandas as pd
        hosp = pd.read_csv(F.ROOT / "data/hospitals_google.csv")
        hosp = hosp[hosp["name"].str.startswith(MAJOR_HOSPITALS)]
        self.hospitals = [(r.name, int(net.snap(r.lat, r.lng)[0])) for r in hosp.itertuples()]
        self.pumps = True

    # ---------- names for places ----------
    def road_name(self, node: int) -> str:
        net = self.w.net
        d, k = self._road_xy.query(net._xy([net.lat[node]], [net.lon[node]])[0])
        if d <= 45:
            return self._road_names[int(k)]
        return f"sector road near Sector {self.sector_label(node)}"

    def _where(self, node: int) -> str:
        nm = self.road_name(node)
        return f"near Sector {self.sector_label(node)}" if nm.startswith("sector road") else f"on {nm} near Sector {self.sector_label(node)}"

    def sector_label(self, node: int) -> str:
        net = self.w.net
        d = np.linalg.norm(self._sec_xy - net._xy([net.lat[node]], [net.lon[node]])[0], axis=1)
        return str(int(self._sec[int(d.argmin())]))

    # ---------- scenario ----------
    def scenarios(self) -> list[dict]:
        out = [dict(id=k, label=v["label"], note=v["note"], total_mm=round(sum(v["hourly"]), 1)) for k, v in F.SCENARIOS.items()]
        out.append(dict(id="live", label="Live: Open-Meteo, last 24 h and next 12 h", note="Real rain for central Chandigarh, refreshed when you load it.", total_mm=None))
        return out

    def start(self, key: str, custom: dict | None = None, live: dict | None = None) -> dict:
        if key == "custom":
            mm, hrs = float(custom["mm_h"]), int(custom["hours"])
            hourly = F._pad([mm] * hrs, hrs + 8)
            meta = dict(id="custom", label=f"Custom: {mm:g} mm/h for {hrs} h", note="Your numbers.", start="12:00", now_step=0)
        elif key == "live":
            hourly = F._pad(live["hourly"], len(live["hourly"]) + 6)
            meta = dict(id="live", label=f"Live rain (Open-Meteo, fetched {live['fetched']})",
                        note=f"Last 24 h: {live['past24_mm']} mm. Next 12 h forecast: {live['next12_mm']} mm.",
                        start=live["start"], now_step=int(live["now_index"] / F.STEP_H))
        else:
            sc = F.SCENARIOS[key]
            hourly, meta = sc["hourly"], dict(id=key, label=sc["label"], note=sc["note"], start=sc["start"], now_step=0)
        weight = self._importance()
        run = F.run(hourly, self.spots, meta["start"], now_step=meta["now_step"], weight=weight)
        if isinstance(meta["start"], datetime):
            meta["start"] = meta["start"].strftime("%H:%M")
        self.run, self.meta = run, meta
        return self.apply(meta["now_step"] if key == "live" else self._first_interesting())

    def _first_interesting(self) -> int:
        """Open a replay at the worst moment so the plan has something to show."""
        L = np.array([s["level_no_pump"] for s in self.run["spots"]])   # (S, T)
        return int((L ** 2).sum(axis=0).argmax())

    def _importance(self) -> np.ndarray:
        """Pump priority weight: arterial roads and hospital approaches first, colonies (homes) close behind."""
        w = []
        for s in self.spots:
            k = 1.0
            if s.kind in ("chowk", "underpass"):
                k = 1.3
            if s.kind == "colony":
                k = 1.2
            if any(np.hypot((s.lat - self.w.net.lat[n]) * 111e3, (s.lng - self.w.net.lon[n]) * 96e3) < 1200 for _, n in self.hospitals):
                k += 0.3
            w.append(k)
        return np.array(w)

    def clear(self) -> dict:
        self.run = self.meta = self.step = None
        self.node_level = {}
        with self.w.lock:
            self.w._apply_closures()
            self.w._refresh_recommendations()
        return {"active": False}

    # ---------- apply a moment of the run to live routing ----------
    def set_pumps(self, on: bool) -> dict:
        self.pumps = bool(on)
        return self.apply(self.step or 0)

    def _lv(self, r: dict) -> list[int]:
        return r["level"] if self.pumps else r["level_no_pump"]

    def _d(self, r: dict) -> list[float]:
        return r["depth"] if self.pumps else r["depth_no_pump"]

    def apply(self, step: int) -> dict:
        if self.run is None:
            raise ValueError("start a rain scenario first")
        T = len(self.run["labels"])
        step = int(np.clip(step, 0, T - 1))
        self.step = step
        lv = {}
        for s, r in zip(self.spots, self.run["spots"]):
            L = self._lv(r)[step]
            if L >= 2:
                for n in s.nodes:
                    lv[n] = max(lv.get(n, 0), L)
        self.node_level = lv
        with self.w.lock:
            self.w._apply_closures()
            self.w._refresh_recommendations()
            return self.plan()

    # ---------- the plan ----------
    def plan(self) -> dict:
        run, t = self.run, self.step
        labels = run["labels"]
        ahead = int(LOOKAHEAD_H / F.STEP_H)
        now_lab = labels[t]
        spots_now, actions = [], []
        for s, r in zip(self.spots, run["spots"]):
            d, L = self._d(r), self._lv(r)
            nxt = L[t:t + ahead + 1]
            trend = "rising" if t + 1 < len(d) and d[min(len(d) - 1, t + 2)] > d[t] + 0.2 else "falling" if t > 0 and d[min(len(d) - 1, t + 2)] < d[t] - 0.2 else "steady"
            close_at = next((labels[t + i] for i, x in enumerate(nxt) if x == 3), None) if L[t] < 3 else None
            entry = dict(id=s.id, name=s.name, kind=s.kind, lat=s.lat, lng=s.lng, depth=d[t], level=F.LEVELS[L[t]], trend=trend,
                         peak=round(max(d), 1), peak_at=labels[int(np.argmax(d))], team_from=r["team_from"] if self.pumps else None, accuracy=s.accuracy, sources=s.sources,
                         forecast=F.LEVELS[max(nxt)], close_at=close_at)
            spots_now.append(entry)
            was_closed = any(x == 3 for x in L[max(0, t - 8):t])
            if L[t] == 3:
                actions.append(dict(kind="close", spot=s.id, rank=0, title=f"Close {s.name}",
                                    text=f"Water about {d[t]:.0f} cm and {trend}. Closed to all traffic, including ambulances and PCR vans.",
                                    **self._diversion(s)))
            elif close_at:
                actions.append(dict(kind="preclose", spot=s.id, rank=1, title=f"Get ready to close {s.name} at {close_at}",
                                    text=f"Now {d[t]:.0f} cm, forecast to pass 30 cm by {close_at}. Put barricades and a traffic post in place now.",
                                    **self._diversion(s, planned=True)))
            elif L[t] == 2:
                actions.append(dict(kind="divert", spot=s.id, rank=2, title=f"Divert traffic at {s.name}",
                                    text=f"Water about {d[t]:.0f} cm ({trend}). Two-wheelers and cars diverted; emergency vehicles may pass at walking pace."))
            elif was_closed and L[t] < 2 and trend != "rising":
                actions.append(dict(kind="reopen", spot=s.id, rank=4, title=f"Reopen {s.name}",
                                    text=f"Down to {d[t]:.0f} cm and {trend}. Reopen after an MC check of the road surface and manholes."))
            if s.kind == "colony" and L[t] >= 2:
                actions.append(dict(kind="rescue", spot=s.id, rank=3, title=f"Rescue standby: {s.name}",
                                    text="Low-lying homes. Fire and rescue team with a pump and rope on standby; check on ground-floor and elderly residents."))
        # pump teams due in the next 2 hours (or already working)
        teams = [(r["team_step"], s, r) for s, r in zip(self.spots, run["spots"]) if r["team_step"] is not None and self.pumps]
        teams.sort(key=lambda x: x[0])
        team_rows = []
        for i, (ts, s, r) in enumerate(teams, 1):
            state = "working" if ts <= t else "due" if ts <= t + ahead else "later"
            team_rows.append(dict(team=i, spot=s.id, name=s.name, at=labels[ts], state=state, peak=r["peak_cm"], peak_no_pump=r["peak_no_pump_cm"],
                                  saved_h=round(r["hours_closed_no_pump"] - r["hours_closed"], 2)))
        due = [x for x in team_rows if x["state"] == "due"]
        if due:
            actions.append(dict(kind="pumps", rank=1.5, title=f"Send {len(due)} MC flood team{'s' if len(due) > 1 else ''}",
                                text="; ".join(f"Team {x['team']} to {x['name']} by {x['at']}" for x in due[:6]) + ("…" if len(due) > 6 else "")))
        ems = self._ems()
        if ems["amb_cover_after"] < ems["amb_cover_before"] - 0.5 or ems["cut_off"] or ems.get("move"):
            actions.append(dict(kind="ems", rank=2.5, title="Ambulance reach",
                                text=f"Share of calls an ambulance can reach in 8 min: {ems['amb_cover_before']:.1f}% → {ems['amb_cover_after']:.1f}%."
                                     + (f" {ems['cut_off']} road points have no way in until the water drops." if ems["cut_off"] else "")
                                     + (f" {ems['move']['text']}" if ems.get("move") else "")))
        actions.sort(key=lambda a: a["rank"])
        n = {k: sum(1 for x in spots_now if x["level"] == k) for k in F.LEVELS}
        rain_now = run["rain_hourly"][int(t * F.STEP_H)] if int(t * F.STEP_H) < len(run["rain_hourly"]) else 0.0
        return dict(active=True, scenario=self.meta, step=t, now=now_lab, labels=labels, rain_hourly=run["rain_hourly"], rain_now=rain_now,
                    step_h=F.STEP_H, counts=n, spots=spots_now, actions=actions, teams=team_rows, teams_total=F.MC_TEAMS, ems=ems,
                    totals=dict(closed_hours=run["closed_hours"], closed_hours_no_pump=run["closed_hours_no_pump"], peak_closed=run["peak_closed"]), pumps=self.pumps,
                    design_mm_h=F.DESIGN_MM_H, thresholds=dict(watch=F.WATCH_CM, divert=F.DIVERT_CM, close=F.CLOSE_CM),
                    depth=[self._d(r) for r in run["spots"]])

    def _boundary(self, inside: set[int]) -> list[int]:
        """Road nodes just outside a flooded area, on its biggest roads: where barricades and traffic posts go."""
        net, A0, AT = self.w.net, self.w._A0, self._A0T()
        out = set()
        for n in inside:
            out |= {int(m) for m in A0.indices[A0.indptr[n]:A0.indptr[n + 1]]}
            out |= {int(m) for m in AT.indices[AT.indptr[n]:AT.indptr[n + 1]]}
        out -= inside
        order = ["trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "living_street"]
        rank = lambda m: order.index(net.node_class[m]) if net.node_class[m] in order else 9  # noqa: E731
        ranked = sorted(out, key=rank)
        if not ranked:
            return []
        return [m for m in ranked if rank(m) <= max(rank(ranked[0]), 2)][:8]

    def _A0T(self):
        if not hasattr(self, "_a0t"):
            self._a0t = self.w._A0.T.tocsr()
        return self._a0t

    def _diversion(self, s: F.Spot, planned: bool = False) -> dict:
        """Barricade points, and the way round between two of them at least 250 m apart."""
        net = self.w.net
        inside = set(s.nodes)
        b = self._boundary(inside)
        bars = [dict(lat=float(net.lat[m]), lng=float(net.lon[m]), road=self.road_name(m)) for m in b[:6]]
        # small spots (an underpass): look a little further out for the ends of the detour
        for extra in (150, 300):
            xy = net._xy(net.lat[b], net.lon[b]) if b else np.zeros((0, 2))
            if len(b) >= 2 and np.linalg.norm(xy[:, None] - xy[None], axis=2).max() >= 250:
                break
            ctr = net._xy([s.lat], [s.lng])[0]
            b = self._boundary(set(net._tree.query_ball_point(ctr, s.radius_m + extra)) | inside)
        if len(b) < 2:
            return dict(barricades=bars, diversion=None)
        A = self.w.net.A
        if planned or not any(self.node_level.get(n, 0) >= 3 for n in s.nodes):
            A = A.tocoo(copy=True)
            idx = np.array(s.nodes)
            m = np.isin(A.row, idx) | np.isin(A.col, idx)
            A.data[m] = 1e7
            A = A.tocsr()
        xy = net._xy(net.lat[b], net.lon[b])
        D = np.linalg.norm(xy[:, None] - xy[None], axis=2)
        pairs = sorted(((D[i, j], i, j) for i in range(len(b)) for j in range(len(b)) if i != j and D[i, j] >= 250), reverse=True)
        dist = dijkstra(A, directed=True, indices=b)
        base = dijkstra(self.w._A0, directed=True, indices=b)
        pick = next(((i, j) for _, i, j in pairs if dist[i, b[j]] < 1e6), None)
        if pick is None:
            return dict(barricades=bars, diversion=dict(text="No way round on mapped roads: hold traffic at the barricades or turn it back.", path=[]))
        i, j = pick
        a, c = b[i], b[j]
        _, pred = dijkstra(A, directed=True, indices=a, return_predecessors=True)
        path, v = [c], c
        while v != a:
            v = int(pred[v]); path.append(v)
        path = path[::-1]
        coords = [[round(float(net.lon[p]), 5), round(float(net.lat[p]), 5)] for p in path]
        names = []
        for p in path[::2]:
            nm = self.road_name(p)
            if not nm.startswith("sector road") and nm not in names:
                names.append(nm)
        km = sum(np.hypot((coords[k + 1][1] - coords[k][1]) * 111.32, (coords[k + 1][0] - coords[k][0]) * 95.7) for k in range(len(coords) - 1))
        extra_min = max(0.0, (dist[i, c] - base[i, c]) * self.w.travel_scale() / 60)
        via = ", ".join(names[:3]) if names else f"the sector roads round Sector {self.sector_label(path[len(path) // 2])}"
        return dict(barricades=bars, diversion=dict(text=f"Divert via {via}: {km:.1f} km, about {max(1, round(extra_min))} min longer than the direct road.", path=coords))

    def _ems(self) -> dict:
        """Ambulance and PCR reach before vs after the flooding, and one standby suggestion."""
        w = self.w
        scale = w.travel_scale()
        amb = sorted({u.home for u in w.units.values() if u.kind == "ambulance" and not u.off_duty})
        pcr = sorted({u.home for u in w.units.values() if u.kind == "police" and not u.off_duty})

        def reach(A, homes):
            return dijkstra(A, directed=True, indices=homes, min_only=True) * scale

        a0, a1 = reach(w._A0, amb), reach(w.net.A, amb)
        p0, p1 = reach(w._A0, pcr), reach(w.net.A, pcr)
        dem = self._demand
        cov = lambda t, lim: float(dem[t <= lim].sum() * 100)  # noqa: E731
        out = dict(amb_cover_before=cov(a0, AMB_DRIVE_S), amb_cover_after=cov(a1, AMB_DRIVE_S),
                   pcr_cover_before=cov(p0, PCR_DRIVE_S), pcr_cover_after=cov(p1, PCR_DRIVE_S),
                   cut_off=int(sum(1 for n in np.flatnonzero((a1 > 1e6) & (a0 < 1e6)) if n not in self.node_level)))
        # sectors that lost ambulance reach
        lost = (a0 <= AMB_DRIVE_S) & (a1 > AMB_DRIVE_S)
        secs = {}
        for n in np.flatnonzero(lost):
            sc = int(self.sector_of_node[n])
            if sc:
                secs[sc] = secs.get(sc, 0.0) + float(dem[n])
        out["sectors_lost"] = [int(s) for s, _ in sorted(secs.items(), key=lambda x: -x[1])[:6]]
        # hospital access
        hrows = []
        for name, hn in self.hospitals:
            t0 = dijkstra(w._A0.T.tocsr(), directed=True, indices=hn) * scale
            t1 = dijkstra(w.net.A.T.tocsr(), directed=True, indices=hn) * scale
            ok = (t0 < 1e6) & (t1 < 1e6)
            hrows.append(dict(name=name, before_min=round(float((t0[ok] * dem[ok]).sum() / dem[ok].sum() / 60), 1),
                              after_min=round(float((t1[ok] * dem[ok]).sum() / dem[ok].sum() / 60), 1)))
        out["hospitals"] = hrows
        # where one free ambulance should wait to win back the most lost reach
        if lost.any():
            unc = dem * lost
            xy = w.net._xy(w.net.lat, w.net.lon)
            from scipy.spatial import cKDTree
            tree = cKDTree(xy)
            dens = np.array([unc[tree.query_ball_point(xy[n], 1500)].sum() for n in np.flatnonzero(lost)])
            cand = np.flatnonzero(lost)[np.argsort(-dens)[:25]]
            cand = np.unique(np.concatenate([cand, w.net.snap(w.net.lat[cand], w.net.lon[cand])]))
            T = dijkstra(w.net.A, directed=True, indices=cand) * scale
            gain = ((T <= AMB_DRIVE_S) * unc[None, :]).sum(axis=1)
            k = int(gain.argmax())
            if gain[k] * 100 >= 0.5:
                n = int(cand[k])
                out["move"] = dict(lat=float(w.net.lat[n]), lng=float(w.net.lon[n]), gain=round(float(gain[k] * 100), 1),
                                   text=f"Move one free ambulance to wait {self._where(n)}: wins back {gain[k] * 100:.1f}% of calls.")
        for k in ("amb_cover_before", "amb_cover_after", "pcr_cover_before", "pcr_cover_after"):
            out[k] = round(out[k], 1)
        return out

    # ---------- history ----------
    def risk(self) -> dict:
        if self._risk is None:
            seasons, info = F.history()
            self._risk = F.risk_table(self.spots, seasons, info) | {"fit": self.fit}
        return self._risk

    # ---------- public advisory ----------
    def advisory_facts(self) -> dict:
        p = self.plan()
        return dict(time=p["now"], rain_now_mm_h=p["rain_now"],
                    closed=[dict(place=a["title"].replace("Close ", ""), diversion=(a.get("diversion") or {}).get("text")) for a in p["actions"] if a["kind"] == "close"],
                    closing_soon=[a["title"] for a in p["actions"] if a["kind"] == "preclose"],
                    diverted=[a["title"].replace("Divert traffic at ", "") for a in p["actions"] if a["kind"] == "divert"],
                    reopened=[a["title"].replace("Reopen ", "") for a in p["actions"] if a["kind"] == "reopen"])

    @staticmethod
    def template(f: dict) -> dict:
        def lst(x, none="none"):
            return ", ".join(x) if x else none
        en = (f"Chandigarh Traffic Police advisory ({f['time']}): heavy rain. Closed due to waterlogging: "
              f"{lst([c['place'] for c in f['closed']])}. Avoid: {lst(f['diverted'])}. "
              + " ".join(c["diversion"] for c in f["closed"] if c["diversion"])
              + " Do not drive through water above the wheel hub. Emergency: dial 112.")
        hi = (f"चंडीगढ़ ट्रैफिक पुलिस सूचना ({f['time']}): भारी बारिश। जलभराव के कारण बंद: {lst([c['place'] for c in f['closed']], 'कोई नहीं')}। "
              f"इनसे बचें: {lst(f['diverted'], 'कोई नहीं')}। पानी भरी सड़क पर गाड़ी न चलाएँ। आपात स्थिति में 112 डायल करें।")
        pa = (f"ਚੰਡੀਗੜ੍ਹ ਟ੍ਰੈਫਿਕ ਪੁਲਿਸ ਸੂਚਨਾ ({f['time']}): ਭਾਰੀ ਮੀਂਹ। ਪਾਣੀ ਭਰਨ ਕਾਰਨ ਬੰਦ: {lst([c['place'] for c in f['closed']], 'ਕੋਈ ਨਹੀਂ')}। "
              f"ਇਨ੍ਹਾਂ ਤੋਂ ਬਚੋ: {lst(f['diverted'], 'ਕੋਈ ਨਹੀਂ')}। ਪਾਣੀ ਵਾਲੀ ਸੜਕ 'ਤੇ ਗੱਡੀ ਨਾ ਚਲਾਓ। ਐਮਰਜੈਂਸੀ ਲਈ 112।")
        sms = f"CHD Traffic: rain. Closed: {lst([c['place'].split(' (')[0] for c in f['closed']])}. Avoid waterlogged roads. Emergency 112"
        return dict(english=en, hindi=hi, punjabi=pa, sms=sms[:160])


def label_time(start: str, step: int) -> str:
    t0 = datetime.strptime(start, "%H:%M")
    return (t0 + timedelta(hours=step * F.STEP_H)).strftime("%H:%M")
