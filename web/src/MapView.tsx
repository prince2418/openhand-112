import { useEffect, useRef } from "react";
import maplibregl, { GeoJSONSource, Map as MLMap, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FloodPlan, Incident, Meta, State, Watch, Zone } from "./types";
import { KIND_NAME, TYPE_LABEL, mmss } from "./format";
import { KIND_LETTER, doneSvg, signSvg, vehicleSvg } from "./icons";

// Free basemap, no key: OpenFreeMap vector tiles; falls back to OSM raster tiles if that fails.
const VECTOR_STYLE = "https://tiles.openfreemap.org/styles/positron";
const RASTER_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" } },
  layers: [{ id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.85, "raster-opacity": 0.85 } }],
};
// GOV.UK colour palette: blue police, green ambulance, red fire; priorities red > orange > grey
const KIND_COLOR: Record<string, string> = { police: "#1d70b8", ambulance: "#00703c", fire: "#d4351c", ambulance_base: "#00703c" };
const POST_LABEL: Record<string, string> = { scheduled: "alert scheduled", sent: "alert sent, waiting for reply", cleared: "traffic post replied: clearing", done: "unit passed", no_reply: "no reply from the post" };
const P_COLOR: Record<string, string> = { P1: "#d4351c", P2: "#f47738", P3: "#505a5f", P4: "#b1b4b6" };

export interface Layers { stations: boolean; risk: boolean; standby: boolean; hotspots: boolean; cctv: boolean }
interface Props {
  meta: Meta | null; state: State | null; selected: Incident | null; layers: Layers;
  risk: { lat: number; lng: number; level: number }[]; standby: { lat: number; lng: number }[];
  picking: boolean; onPick: (lat: number, lng: number) => void; onSelect: (id: string) => void;
  flood?: FloodPlan | null;
  watch?: Watch | null; zones?: Zone[];
}
const LV_COLOR: Record<string, string> = { clear: "#5694ca", watch: "#ffdd00", divert: "#f47738", close: "#d4351c" };

const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features });
const pt = (lng: number, lat: number, props: Record<string, unknown> = {}): GeoJSON.Feature => ({ type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: props });

// a circle of radius r metres as a polygon (MapLibre circles are in pixels)
const ring = (lng: number, lat: number, r: number): GeoJSON.Feature => ({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [
  Array.from({ length: 65 }, (_, i) => { const a = (i / 64) * 2 * Math.PI; return [lng + (r * Math.sin(a)) / (111320 * Math.cos((lat * Math.PI) / 180)), lat + (r * Math.cos(a)) / 111320]; })] } });

export default function MapView({ meta, state, selected, layers, risk, standby, picking, onPick, onSelect, flood, watch, zones }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const ready = useRef(false);
  const unitMarkers = useRef(new Map<string, Marker>());
  const incMarkers = useRef(new Map<string, Marker>());
  const fitted = useRef(false);
  const pickRef = useRef({ picking, onPick });
  pickRef.current = { picking, onPick };

  // create the map once
  useEffect(() => {
    if (!box.current || map.current) return;
    const m = new maplibregl.Map({ container: box.current, style: VECTOR_STYLE, center: [76.779, 30.733], zoom: 12.6, attributionControl: { compact: true } });
    map.current = m;
    let fellBack = false;
    m.on("error", (e) => {
      if (!fellBack && !ready.current && String(e?.error?.message ?? "").match(/style|fetch|load/i)) { fellBack = true; m.setStyle(RASTER_STYLE); }
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("click", (e) => { if (pickRef.current.picking) pickRef.current.onPick(e.lngLat.lat, e.lngLat.lng); });
    m.on("style.load", () => {
      const src = (id: string) => { if (!m.getSource(id)) m.addSource(id, { type: "geojson", data: fc([]) }); };
      ["risk", "standby", "stations", "hotspots", "routes", "junctions", "hintroad", "closures", "closurepts", "cameras", "camhi",
       "fsegd", "fsegc", "fdiv", "fspots", "fbars", "fmove", "wring", "wmove", "wdest", "wzone"].forEach(src);
      // waterlogging: diverted links (dashed orange), closed links (red over dark blue), diversions (dashed blue)
      m.addLayer({ id: "fsegd", type: "line", source: "fsegd", layout: { "line-cap": "butt" }, paint: { "line-color": "#f47738", "line-width": 6, "line-dasharray": [1.2, 0.8] } });
      m.addLayer({ id: "fsegc-case", type: "line", source: "fsegc", layout: { "line-cap": "round" }, paint: { "line-color": "#003078", "line-width": 10 } });
      m.addLayer({ id: "fsegc", type: "line", source: "fsegc", layout: { "line-cap": "round" }, paint: { "line-color": "#d4351c", "line-width": 5 } });
      m.addLayer({ id: "fdiv", type: "line", source: "fdiv", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#1d70b8", "line-width": 4, "line-dasharray": [2, 1.5] } });
      m.addLayer({ id: "fspots", type: "circle", source: "fspots", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, ["+", 5, ["*", 0.25, ["get", "depth"]]], 15, ["+", 12, ["*", 0.6, ["get", "depth"]]]],
        "circle-color": ["get", "color"], "circle-opacity": ["case", ["==", ["get", "level"], "clear"], 0.12, 0.45],
        "circle-stroke-color": ["get", "color"], "circle-stroke-width": 2 } });
      m.addLayer({ id: "fspots-lab", type: "symbol", source: "fspots", filter: ["!=", ["get", "level"], "clear"],
        layout: { "text-field": ["concat", ["to-string", ["round", ["get", "depth"]]], " cm"], "text-size": 12, "text-offset": [0, 1.6], "text-allow-overlap": false, "text-font": ["Noto Sans Bold", "Open Sans Bold"] },
        paint: { "text-color": "#0b0c0c", "text-halo-color": "#ffffff", "text-halo-width": 2 } });
      m.addLayer({ id: "fbars", type: "circle", source: "fbars", paint: { "circle-radius": 5, "circle-color": "#ffffff", "circle-stroke-color": "#d4351c", "circle-stroke-width": 3 } });
      m.addLayer({ id: "wzone", type: "circle", source: "wzone", paint: { "circle-radius": 13, "circle-color": "rgba(244,119,56,0.18)", "circle-stroke-color": "#f47738", "circle-stroke-width": 2 } });
      m.addLayer({ id: "wzone-lab", type: "symbol", source: "wzone", layout: { "text-field": ["get", "n"], "text-size": 12, "text-allow-overlap": true, "text-font": ["Noto Sans Bold", "Open Sans Bold"] }, paint: { "text-color": "#6f2f05" } });
      m.addLayer({ id: "wring", type: "fill", source: "wring", paint: { "fill-color": "rgba(212,53,28,0.10)", "fill-outline-color": "#d4351c" } });
      m.addLayer({ id: "wring-line", type: "line", source: "wring", paint: { "line-color": "#d4351c", "line-width": 2.5, "line-dasharray": [2, 1.2] } });
      m.addLayer({ id: "wmove", type: "line", source: "wmove", layout: { "line-cap": "round" }, paint: { "line-color": "#00703c", "line-width": 3, "line-dasharray": [1.5, 1.2] } });
      m.addLayer({ id: "wdest", type: "circle", source: "wdest", paint: { "circle-radius": 7, "circle-color": "#ffffff", "circle-stroke-color": "#00703c", "circle-stroke-width": 3 } });
      m.addLayer({ id: "fmove", type: "circle", source: "fmove", paint: { "circle-radius": 9, "circle-color": "rgba(0,112,60,0.2)", "circle-stroke-color": "#00703c", "circle-stroke-width": 3 } });
      m.addLayer({ id: "camhi", type: "circle", source: "camhi", paint: { "circle-radius": 11, "circle-color": "rgba(29,112,184,0.15)", "circle-stroke-color": "#1d70b8", "circle-stroke-width": 2 } });
      m.addLayer({ id: "cameras", type: "circle", source: "cameras", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 2.5, 15, 5], "circle-color": "#0b0c0c", "circle-stroke-color": "#ffffff", "circle-stroke-width": 1 } });
      m.addLayer({ id: "closures", type: "line", source: "closures", layout: { "line-cap": "round" }, paint: { "line-color": "#d4351c", "line-width": 7, "line-opacity": 0.85 } });
      m.addLayer({ id: "closurepts", type: "symbol", source: "closurepts", layout: { "text-field": "✕", "text-size": 20, "text-allow-overlap": true, "text-font": ["Noto Sans Bold", "Open Sans Bold"] },
        paint: { "text-color": "#ffffff", "text-halo-color": "#d4351c", "text-halo-width": 6 } });
      m.addLayer({ id: "hintroad", type: "circle", source: "hintroad", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 3, 15, 7], "circle-color": "#ffdd00", "circle-stroke-color": "#0b0c0c", "circle-stroke-width": 1 } });
      m.addLayer({ id: "risk", type: "circle", source: "risk", paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 7, 14, 22],
        "circle-color": "#f47738", "circle-opacity": ["*", 0.55, ["get", "level"]], "circle-blur": 0.6 } });
      m.addLayer({ id: "standby", type: "circle", source: "standby", paint: {
        "circle-radius": 6, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#1d70b8", "circle-stroke-width": 2 } });
      m.addLayer({ id: "hotspots", type: "circle", source: "hotspots", paint: {
        "circle-radius": 9, "circle-color": "rgba(212,53,28,0.10)", "circle-stroke-color": "#d4351c", "circle-stroke-width": 1.5, "circle-stroke-opacity": 0.7 } });
      m.addLayer({ id: "stations", type: "circle", source: "stations", paint: {
        "circle-radius": 5, "circle-color": "#ffffff", "circle-stroke-color": ["get", "color"], "circle-stroke-width": 2.5 } });
      m.addLayer({ id: "routes-casing", type: "line", source: "routes", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#ffffff", "line-width": 9 } });
      m.addLayer({ id: "routes", type: "line", source: "routes", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": 5, "line-opacity": 0.35 } });
      m.addLayer({ id: "routes-dash", type: "line", source: "routes", layout: { "line-cap": "butt", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": 4, "line-dasharray": [0, 4, 3] } });
      m.addLayer({ id: "junctions", type: "circle", source: "junctions", paint: {
        "circle-radius": ["case", ["==", ["get", "st"], "sent"], 7, 5], "circle-color": ["match", ["get", "st"], "sent", "#ffdd00", "cleared", "#00703c", "done", "#85994b", "no_reply", "#d4351c", "scheduled", "#b1b4b6", "#ffdd00"],
        "circle-stroke-color": "#0b0c0c", "circle-stroke-width": 2 } });
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
      const hover = (layer: string, text: (p: any) => string) => {
        m.on("mouseenter", layer, (e) => { m.getCanvas().style.cursor = "default"; const f = e.features?.[0]; if (f) popup.setLngLat((f.geometry as any).coordinates).setText(text(f.properties)).addTo(m); });
        m.on("mouseleave", layer, () => popup.remove());
      };
      hover("stations", (p) => p.name);
      hover("cameras", (p) => `${p.id}: ${p.road} (simulated position)`);
      hover("hotspots", (p) => `${p.name} (${p.type === "fire" ? "fire risk site" : "crash black spot"})`);
      hover("junctions", (p) => `Junction on ${p.road} road: ${p.label}`);
      hover("standby", () => "Suggested standby point for a free PCR van");
      hover("fspots", (p) => `${p.name}: ${p.level === "clear" ? "clear" : `${Math.round(p.depth)} cm, ${p.label}`}`);
      hover("fbars", (p) => `Barricade and traffic post (${p.road})`);
      hover("wzone", (p) => `Sector ${p.sector}: ${p.text}`);
      hover("wdest", (p) => `${p.unit}: wait here (${p.place})`);
      hover("fmove", () => "Wait here: one free ambulance (wins back reach lost to flooding)");
      ready.current = true;
      m.fire("ohready");
    });
    return () => { m.remove(); map.current = null; ready.current = false; };
  }, []);

  useEffect(() => { if (map.current) map.current.getCanvas().style.cursor = picking ? "crosshair" : ""; }, [picking]);

  // open fitted to the city
  useEffect(() => {
    const m = map.current; if (!m || !meta?.bounds || fitted.current) return;
    fitted.current = true;
    m.fitBounds(meta.bounds as unknown as maplibregl.LngLatBoundsLike, { padding: { top: 30, bottom: 30, left: 30, right: 30 }, duration: 0 });
  }, [meta]);

  // static and slow layers
  useEffect(() => {
    const m = map.current; if (!m) return;
    const apply = () => {
      if (!ready.current) return;
      (m.getSource("stations") as GeoJSONSource)?.setData(fc(meta ? meta.stations.map((s) => pt(s.lng, s.lat, { name: s.name, color: KIND_COLOR[s.kind] ?? "#555" })) : []));
      (m.getSource("hotspots") as GeoJSONSource)?.setData(fc(meta ? meta.hotspots.map((h) => pt(h.lng, h.lat, { name: h.name, type: h.type })) : []));
      (m.getSource("risk") as GeoJSONSource)?.setData(fc(risk.map((c) => pt(c.lng, c.lat, { level: c.level }))));
      (m.getSource("standby") as GeoJSONSource)?.setData(fc(standby.map((c) => pt(c.lng, c.lat))));
      m.setLayoutProperty("stations", "visibility", layers.stations ? "visible" : "none");
      m.setLayoutProperty("hotspots", "visibility", layers.hotspots ? "visible" : "none");
      m.setLayoutProperty("risk", "visibility", layers.risk ? "visible" : "none");
      m.setLayoutProperty("standby", "visibility", layers.standby ? "visible" : "none");
      (m.getSource("cameras") as GeoJSONSource)?.setData(fc(meta?.cameras ? meta.cameras.map((c) => pt(c.lng, c.lat, { id: c.id, road: c.road })) : []));
      m.setLayoutProperty("cameras", "visibility", layers.cctv ? "visible" : "none");
    };
    apply(); m.on("ohready", apply);
    return () => { m.off("ohready", apply); };
  }, [meta, risk, standby, layers]);

  // the road the caller named, when we don't know where on it: yellow dots to click on
  useEffect(() => {
    const m = map.current; if (!m || !ready.current) return;
    const road = selected && selected.status === "new" && !selected.triage.location.resolved ? selected.triage.location.road : null;
    const pts = road && meta?.roads?.[road] ? meta.roads[road] : [];
    (m.getSource("hintroad") as GeoJSONSource)?.setData(fc(pts.map(([lng, lat]) => pt(lng, lat))));
    if (pts.length) {
      const b = pts.reduce((bb, [x, y]) => [[Math.min(bb[0][0], x), Math.min(bb[0][1], y)], [Math.max(bb[1][0], x), Math.max(bb[1][1], y)]], [[180, 90], [-180, -90]]);
      m.fitBounds(b as maplibregl.LngLatBoundsLike, { padding: 80, duration: 600, maxZoom: 15 });
    }
  }, [selected?.id, selected?.status, selected?.triage.location.resolved, meta]);

  // routes + junctions of the selected incident (or every active route when none is selected)
  useEffect(() => {
    const m = map.current; if (!m || !ready.current || !state) return;
    const active = state.incidents.filter((i) => i.status === "dispatched" && i.corridor && (!selected || i.id === selected.id));
    const routes: GeoJSON.Feature[] = [], js: GeoJSON.Feature[] = [];
    for (const inc of active) for (const r of inc.corridor!.routes) {
      const u = state.units.find((x) => x.id === r.unit);
      if (!u || u.status !== "en_route") continue;
      routes.push({ type: "Feature", geometry: { type: "LineString", coordinates: r.route }, properties: { color: KIND_COLOR[r.kind] } });
      if (selected && !inc.traffic?.length) r.junctions.forEach((j) => js.push(pt(j.lng, j.lat, { road: j.road, st: "plan", label: `unit passes about ${Math.floor(j.at_s / 60)}:${String(j.at_s % 60).padStart(2, "0")} after leaving` })));
    }
    if (selected?.traffic?.length) selected.traffic.forEach((p) => js.push(pt(p.lng, p.lat, { road: p.road, st: p.status, label: POST_LABEL[p.status] })));
    (m.getSource("routes") as GeoJSONSource)?.setData(fc(routes));
    (m.getSource("junctions") as GeoJSONSource)?.setData(fc(js));
  }, [state, selected]);

  // cameras near the selected incident
  useEffect(() => {
    const m = map.current; if (!m || !ready.current) return;
    (m.getSource("camhi") as GeoJSONSource)?.setData(fc((selected?.cameras ?? []).map((c) => pt(c.lng, c.lat))));
  }, [selected?.id, selected?.cameras?.length]);

  // closed roads (what-if)
  useEffect(() => {
    const m = map.current; if (!m || !ready.current) return;
    const cl = state?.conditions?.closures ?? [];
    (m.getSource("closures") as GeoJSONSource)?.setData(fc(cl.flatMap((c) => c.segments.map((s) => ({ type: "Feature", geometry: { type: "LineString", coordinates: s }, properties: {} } as GeoJSON.Feature)))));
    (m.getSource("closurepts") as GeoJSONSource)?.setData(fc(cl.map((c) => pt(c.lng, c.lat))));
  }, [state?.conditions?.closures]);

  // waterlogging: flooded links (from the live conditions, shown on every tab) and the plan's spots and actions
  useEffect(() => {
    const m = map.current; if (!m || !ready.current) return;
    const f = state?.conditions?.flood;
    const lines = (segs: [number, number][][] | undefined) => fc((segs ?? []).map((c) => ({ type: "Feature", geometry: { type: "LineString", coordinates: c }, properties: {} } as GeoJSON.Feature)));
    (m.getSource("fsegc") as GeoJSONSource)?.setData(lines(f?.seg_closed));
    (m.getSource("fsegd") as GeoJSONSource)?.setData(lines(f?.seg_divert));
  }, [state?.conditions?.flood]);
  useEffect(() => {
    const m = map.current; if (!m) return;
    const apply = () => {
      if (!ready.current) return;
      const LAB: Record<string, string> = { clear: "clear", watch: "watch", divert: "divert traffic", close: "closed" };
      (m.getSource("fspots") as GeoJSONSource)?.setData(fc((flood?.spots ?? []).map((s) => pt(s.lng, s.lat, { name: s.name, depth: s.depth, level: s.level, color: LV_COLOR[s.level], label: LAB[s.level] }))));
      const acts = flood?.actions ?? [];
      (m.getSource("fbars") as GeoJSONSource)?.setData(fc(acts.filter((a) => a.kind === "close" || a.kind === "preclose").flatMap((a) => (a.barricades ?? []).map((b) => pt(b.lng, b.lat, { road: b.road })))));
      (m.getSource("fdiv") as GeoJSONSource)?.setData(fc(acts.filter((a) => a.diversion?.path?.length).map((a) => ({ type: "Feature", geometry: { type: "LineString", coordinates: a.diversion!.path }, properties: {} } as GeoJSON.Feature))));
      const mv = flood?.ems.move;
      (m.getSource("fmove") as GeoJSONSource)?.setData(fc(mv ? [pt(mv.lng, mv.lat)] : []));
    };
    apply(); m.on("ohready", apply);
    return () => { m.off("ohready", apply); };
  }, [flood]);

  // predict and monitor: likely zones next hour, unusual clusters, suggested van moves
  useEffect(() => {
    const m = map.current; if (!m) return;
    const apply = () => {
      if (!ready.current) return;
      (m.getSource("wzone") as GeoJSONSource)?.setData(fc((zones ?? []).map((z, i) => pt(z.lng, z.lat, { n: String(i + 1), sector: z.sector, text: `${z.share}% of the next hour's calls; ${z.why.join("; ")}` }))));
      const al = watch?.alerts ?? [];
      (m.getSource("wring") as GeoJSONSource)?.setData(fc(al.filter((a) => a.kind === "cluster" && a.lat != null).map((a) => ring(a.lng!, a.lat!, a.radius_m ?? 700))));
      const mv = al.flatMap((a) => a.moves ?? (a.kind === "coverage" && a.from_lat != null ? [{ unit: a.action?.unit ?? "", place: "", lat: a.lat!, lng: a.lng!, from_lat: a.from_lat!, from_lng: a.from_lng! }] : []));
      (m.getSource("wmove") as GeoJSONSource)?.setData(fc(mv.map((x) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: [[x.from_lng, x.from_lat], [x.lng, x.lat]] } } as GeoJSON.Feature))));
      (m.getSource("wdest") as GeoJSONSource)?.setData(fc(mv.map((x) => pt(x.lng, x.lat, { unit: x.unit, place: x.place }))));
    };
    apply(); m.on("ohready", apply);
    return () => { m.off("ohready", apply); };
  }, [watch, zones]);

  // keep the latest state and when it arrived, for the animation loop
  const live = useRef<{ state: State | null; at: number }>({ state: null, at: 0 });
  useEffect(() => { live.current = { state, at: performance.now() }; }, [state]);

  // live markers: units and incidents
  useEffect(() => {
    const m = map.current; if (!m || !state) return;
    const seenU = new Set<string>();
    for (const u of state.units) {
      seenU.add(u.id);
      const moving = !!u.path && (u.status === "en_route" || u.status === "returning");
      const mode = moving ? "moving" : u.status === "on_scene" ? "scene" : "idle";
      let mk = unitMarkers.current.get(u.id);
      if (mk && (mk.getElement() as HTMLElement).dataset.mode !== mode) { mk.remove(); unitMarkers.current.delete(u.id); mk = undefined; }
      if (!mk) {
        const wrap = document.createElement("div");      // maplibre owns the wrapper's classes and position
        wrap.dataset.mode = mode;
        if (mode === "idle") {
          wrap.innerHTML = `<div class="u ${u.kind}" role="img">${KIND_LETTER[u.kind]}</div>`;
        } else {
          wrap.innerHTML = `<div class="veh ${u.kind} ${u.status}" role="img"><div class="rot">${vehicleSvg(u.kind)}</div>`
            + `<div class="vtag"><b>${u.id}</b><span class="v-km"></span><span class="v-sp"></span><span class="v-eta"></span></div></div>`;
        }
        mk = new maplibregl.Marker({ element: wrap }).setLngLat([u.lng, u.lat]).addTo(m);
        unitMarkers.current.set(u.id, mk);
      }
      const el = mk.getElement().firstElementChild as HTMLElement;
      el.className = mode === "idle" ? `u ${u.kind}` : `veh ${u.kind} ${u.status}`;
      const label = `${u.id} ${KIND_NAME[u.kind]}, ${u.status.replace("_", " ")} (base: ${u.base})`;
      el.title = label; el.setAttribute("aria-label", label);
      if (!moving) mk.setLngLat([u.lng, u.lat]);
    }
    const seenI = new Set<string>();
    for (const inc of state.incidents) {
      if (inc.lat == null || inc.lng == null || (inc.status === "resolved" && selected?.id !== inc.id)) continue;
      seenI.add(inc.id);
      const done = inc.status === "resolved";
      const p = inc.triage.decision.priority;
      const key = `${done}:${p}:${inc.triage.extract.incident_type}`;
      let mk = incMarkers.current.get(inc.id);
      if (mk && (mk.getElement() as HTMLElement).dataset.key !== key) { mk.remove(); incMarkers.current.delete(inc.id); mk = undefined; }
      if (!mk) {
        const wrap = document.createElement("div");
        wrap.dataset.key = key;
        const btn = document.createElement("button");
        btn.innerHTML = done ? doneSvg
          : `<span class="ring r1"></span><span class="ring r2"></span><span class="ring r3"></span>${signSvg(inc.triage.extract.incident_type)}`
            + `<span class="itag"><b class="${p}">${p}</b>${inc.id}</span>`;
        btn.addEventListener("click", (ev) => { ev.stopPropagation(); onSelect(inc.id); });
        wrap.appendChild(btn);
        mk = new maplibregl.Marker({ element: wrap }).setLngLat([inc.lng, inc.lat]).addTo(m);
        incMarkers.current.set(inc.id, mk);
      }
      const el = mk.getElement().firstElementChild as HTMLElement;
      el.className = `beacon ${p} ${inc.status} ${selected?.id === inc.id ? "sel" : ""}`;
      el.title = `${inc.id}: ${TYPE_LABEL[inc.triage.extract.incident_type]} (${p})`;
      el.setAttribute("aria-label", el.title);
      mk.setLngLat([inc.lng, inc.lat]);
    }
    for (const [id, mk] of incMarkers.current) if (!seenI.has(id)) { mk.remove(); incMarkers.current.delete(id); }
    for (const [id, mk] of unitMarkers.current) if (!seenU.has(id)) { mk.remove(); unitMarkers.current.delete(id); }
  }, [state, selected, onSelect]);

  // smooth motion: between server updates, move each driving unit along its timed route every frame,
  // turn it to face the road, and update its distance / speed / ETA tag
  useEffect(() => {
    let raf = 0, lastText = 0;
    const step = (now: number) => {
      const { state: st, at } = live.current;
      if (st) {
        const sim = st.now + ((now - at) / 1000) * st.demo_speed;
        const writeText = now - lastText > 250;
        for (const u of st.units) {
          const P = u.path; if (!P || P.t.length < 2) continue;
          const mk = unitMarkers.current.get(u.id); if (!mk) continue;
          const el = mk.getElement();
          if (el.dataset.mode !== "moving") continue;
          const T = P.t, n = T.length;
          let i: number, f: number;
          if (sim <= T[0]) { i = 0; f = 0; } else if (sim >= T[n - 1]) { i = n - 2; f = 1; }
          else { let lo = 0, hi = n - 1; while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (T[mid] <= sim) lo = mid; else hi = mid; } i = lo; f = (sim - T[i]) / Math.max(1e-6, T[i + 1] - T[i]); }
          const a = P.c[i], b = P.c[i + 1];
          mk.setLngLat([a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])]);
          const hd = (Math.atan2((b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180), b[1] - a[1]) * 180) / Math.PI;
          const rot = el.querySelector<HTMLElement>(".rot"); if (rot) rot.style.transform = `rotate(${hd}deg)`;
          if (writeText) {
            const done = P.m[i] + f * (P.m[i + 1] - P.m[i]);
            const j0 = Math.max(0, i - 3), j1 = Math.min(n - 1, i + 4), dt = T[j1] - T[j0];
            const rolling = sim > T[0] && sim < T[n - 1];
            const kmh = rolling && dt > 0 ? (3.6 * (P.m[j1] - P.m[j0])) / dt : 0;
            const left = Math.max(0, (P.m[n - 1] - done) / 1000), eta = Math.max(0, T[n - 1] - sim);
            const set = (c: string, t: string) => { const x = el.querySelector(c); if (x) x.textContent = t; };
            set(".v-km", `${left.toFixed(1)} km`);
            set(".v-sp", sim < T[0] ? "rolling out" : `${Math.round(kmh)} km/h`);
            set(".v-eta", u.status === "returning" ? `home ${mmss(eta)}` : `ETA ${mmss(eta)}`);
          }
        }
        if (writeText) lastText = now;
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, []);

  // marching dashes on active routes
  useEffect(() => {
    const seq = [[0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5], [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0], [0, 0.5, 3, 3.5], [0, 1, 3, 3], [0, 1.5, 3, 2.5], [0, 2, 3, 2], [0, 2.5, 3, 1.5], [0, 3, 3, 1], [0, 3.5, 3, 0.5]];
    let k = 0;
    const h = setInterval(() => {
      const m = map.current; if (!m || !ready.current || !m.getLayer("routes-dash")) return;
      k = (k + 1) % seq.length; m.setPaintProperty("routes-dash", "line-dasharray", seq[k]);
    }, 70);
    return () => clearInterval(h);
  }, []);

  // fly to a newly selected incident
  useEffect(() => {
    if (selected?.lat != null && selected?.lng != null && map.current) map.current.easeTo({ center: [selected.lng, selected.lat], zoom: Math.max(map.current.getZoom(), 13), duration: 600 });
  }, [selected?.id, selected?.lat]);

  return <div className="map" ref={box} aria-label="Map of Chandigarh with units and incidents" />;
}
