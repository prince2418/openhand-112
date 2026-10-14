/* Across India: the same engine run on other cities with scripts/add_city.py (OpenStreetMap only). */
import { useEffect, useRef, useState } from "react";
import maplibregl, { GeoJSONSource, Map as MLMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { api } from "./api";

const VECTOR_STYLE = "https://tiles.openfreemap.org/styles/positron";
const RASTER: maplibregl.StyleSpecification = {
  version: 8, sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap contributors" } },
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#f3f2f1" } }, { id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.85, "raster-opacity": 0.85 } }],
};
const KIND_COLOR: Record<string, string> = { police: "#1d70b8", fire: "#d4351c", hospital: "#00703c", ambulance_base: "#00703c", ambulance_station: "#00703c" };

type CityRow = {
  slug: string; name: string; state: string | null; source: string; junctions: number; road_km: number; police_stations: number; fire_stations: number;
  hospitals: number; vans: number; seconds: { total: number };
  pcr: { today_pct: number; standby_pct: number; gain_pts: number }; fire: { today_pct: number; with_2_new_pct: number } | null; hospital: { pct: number } | null;
};

export default function Cities() {
  const [rows, setRows] = useState<CityRow[] | null>(null);
  const [how, setHow] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [city, setCity] = useState<any>(null);
  const [view, setView] = useState<"today" | "plan">("today");
  useEffect(() => { api.cities().then((r) => { setRows(r.cities); setHow(r.how); if (r.cities.length) setSel(r.cities.find((c: CityRow) => c.slug !== "chandigarh")?.slug ?? r.cities[0].slug); }).catch(() => setRows([])); }, []);
  useEffect(() => { if (sel) api.city(sel).then(setCity).catch(() => setCity(null)); }, [sel]);
  const others = rows?.filter((r) => r.slug !== "chandigarh").length ?? 0;

  return (
    <div className="evidence cities">
      <section className="panel">
        <h2>The same engine, any Indian city</h2>
        <p>112 is one national number, run on one national platform (ERSS). OpenHand is built so a state can switch it on without starting over:</p>
        <div className="portable">
          <div><b>Roads and stations</b><span>From OpenStreetMap with one command: road network, police, fire and hospitals, standby points. No city data needed to start.</span></div>
          <div><b>Calls in 11 languages</b><span>Hindi, Punjabi, English, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, Odia. Scores in the Evidence tab.</span></div>
          <div><b>Sovereign mode</b><span>Gemma on the state's own computer: no call data leaves the state. Switch in the Open platform tab.</span></div>
          <div><b>Open standards</b><span>CAP 1.2 alerts for NDMA's SACHET, GeoJSON open data, an OpenAPI for every endpoint. MIT licence.</span></div>
        </div>
      </section>

      <section className="panel">
        <h2>Cities run so far <span className="count num">{rows?.length ?? 0}</span></h2>
        <p className="hint">Each row is the same code as the Chandigarh app, run on that city's OpenStreetMap data. "Today" assumes PCR vans wait at police stations
          ({rows?.[0] ? "2 per station unless the fleet is known" : ""}); "standby" moves the same vans to MEXCLP standby points. All vans free; model, not measured.</p>
        {rows === null ? <p className="hint"><span className="spin" />Loading…</p> : rows.length === 0 ? <p className="hint">No cities yet. Run <code>{how}</code>.</p> : (
          <table className="t citytable">
            <thead><tr><th>City</th><th className="n">Road junctions</th><th className="n">Police stations</th><th className="n">PCR vans</th>
              <th className="n">Calls reached in 5 min: today → standby</th><th className="n">Fire in 5 min: today → +2 stations</th><th className="n">Hospital ≤10 min</th><th className="n">Built in</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.slug} className={sel === r.slug ? "on" : ""} onClick={() => setSel(r.slug)} style={{ cursor: "pointer" }}>
                <td><b>{r.name}</b>{r.state && r.state !== r.name ? <small className="muted">, {r.state}</small> : null}</td>
                <td className="n">{r.junctions.toLocaleString()}</td><td className="n">{r.police_stations}</td><td className="n">{r.vans}</td>
                <td className="n">{r.pcr.today_pct}% → <b>{r.pcr.standby_pct}%</b> <span className="gain">+{r.pcr.gain_pts}</span></td>
                <td className="n">{r.fire ? <>{r.fire.today_pct}% → {r.fire.with_2_new_pct}%</> : "–"}</td>
                <td className="n">{r.hospital ? `${r.hospital.pct}%` : "–"}</td>
                <td className="n">{r.seconds.total < 90 ? `${r.seconds.total} s` : `${Math.round(r.seconds.total / 60)} min`}</td>
              </tr>))}</tbody>
          </table>
        )}
        {others === 0 && rows !== null && <p className="hint">Only Chandigarh so far. Add another city: <code>{how}</code></p>}
      </section>

      {city && (
        <section className="panel">
          <div className="cityhead">
            <h2>{city.name}: where a PCR van can reach in 5 minutes</h2>
            <div className="seg" role="group" aria-label="Arrangement">
              <button className={view === "today" ? "on" : ""} onClick={() => setView("today")}>Vans at police stations ({city.pcr.today_pct}%)</button>
              <button className={view === "plan" ? "on" : ""} onClick={() => setView("plan")}>Vans at standby points ({city.pcr.standby_pct}%)</button>
            </div>
          </div>
          <CityMap city={city} view={view} />
          <div className="fkey"><span><i style={{ background: "#d4351c", opacity: .55 }} />not reached in 5 min</span><span><i style={{ background: "#f47738", opacity: .55 }} />partly</span>
            <span><i style={{ background: "#00703c", opacity: .35 }} />reached</span><span><i className="dotk" style={{ background: "#1d70b8" }} />police station</span>
            <span><i className="dotk" style={{ background: "#d4351c" }} />fire</span><span><i className="dotk" style={{ background: "#00703c" }} />hospital</span>
            {view === "plan" && <span><i className="dotk" style={{ background: "#fff", border: "3px solid #0b0c0c" }} />standby point</span>}</div>
          <p className="hint">Source: {city.source}. Assumptions: {city.assumptions.join("; ")}.</p>
        </section>
      )}

      <section className="panel">
        <h2>Add a city</h2>
        <p>On any computer with internet (takes 1–10 minutes depending on city size):</p>
        <pre className="cmd">{how}{"\n"}python3 scripts/add_city.py "Bhubaneswar, Odisha, India" --vans 40</pre>
        <p className="hint">To go live in a new city, a state adds what OpenStreetMap doesn't have: the real van count and waiting points, local landmarks for call locations,
          and (optionally) its waterlogging spots. The triage, rules, dispatch, forecast, watch and open-platform layers need no change.</p>
      </section>
    </div>
  );
}

function CityMap({ city, view }: { city: any; view: "today" | "plan" }) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const ready = useRef(false);
  const draw = () => {
    const m = map.current;
    if (!m || !ready.current) return;
    const half = (c: any) => c.size / 2;
    const cells = { type: "FeatureCollection", features: city.cells.map((c: any) => ({
      type: "Feature", properties: { v: view === "today" ? c.today : c.plan },
      geometry: { type: "Polygon", coordinates: [[[c.lng - half(c), c.lat - half(c)], [c.lng + half(c), c.lat - half(c)], [c.lng + half(c), c.lat + half(c)], [c.lng - half(c), c.lat + half(c)], [c.lng - half(c), c.lat - half(c)]]] } })) };
    const st = { type: "FeatureCollection", features: city.stations.map((s: any) => ({ type: "Feature", properties: { kind: s.kind, name: s.name ?? s.kind }, geometry: { type: "Point", coordinates: [s.lng, s.lat] } })) };
    const sb = { type: "FeatureCollection", features: (view === "plan" ? city.pcr.standby_points : []).map((p: any) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [p.lng, p.lat] } })) };
    for (const [id, data] of [["cells", cells], ["st", st], ["sb", sb]] as const) {
      const src = m.getSource(id) as GeoJSONSource | undefined;
      if (src) src.setData(data as any); else m.addSource(id, { type: "geojson", data: data as any });
    }
    if (!m.getLayer("cells")) {
      m.addLayer({ id: "cells", type: "fill", source: "cells", paint: { "fill-color": ["step", ["get", "v"], "#d4351c", 0.5, "#f47738", 0.9, "#00703c"], "fill-opacity": ["step", ["get", "v"], 0.55, 0.9, 0.3] } });
      m.addLayer({ id: "st", type: "circle", source: "st", paint: { "circle-radius": 4.5, "circle-color": ["match", ["get", "kind"], "police", KIND_COLOR.police, "fire", KIND_COLOR.fire, KIND_COLOR.hospital], "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
      m.addLayer({ id: "sb", type: "circle", source: "sb", paint: { "circle-radius": 5, "circle-color": "#fff", "circle-stroke-color": "#0b0c0c", "circle-stroke-width": 3 } });
    }
  };
  useEffect(() => {
    if (!box.current) return;
    const m = new maplibregl.Map({ container: box.current, style: VECTOR_STYLE, center: city.center, zoom: 11, attributionControl: { compact: true } });
    map.current = m;
    m.on("load", () => { ready.current = true; m.fitBounds(city.bounds, { padding: 20, duration: 0 }); draw(); });
    let fellBack = false;
    m.on("error", () => {   // vector tiles blocked: plain OSM raster tiles instead (the layers draw either way)
      if (!fellBack && !ready.current) { fellBack = true; m.setStyle(RASTER); m.once("style.load", () => { ready.current = true; m.fitBounds(city.bounds, { padding: 20, duration: 0 }); draw(); }); }
    });
    return () => { ready.current = false; m.remove(); map.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [city.slug]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(draw, [view, city]);
  return <div ref={box} className="citymap" aria-label={`Map of ${city.name}`} />;
}
