import { useEffect, useState } from "react";
import { api } from "./api";
import { FloodRisk } from "./Monsoon";

/* Horizontal bars: one measure (share of calls reached in time), one hue; the recommended option in
   ultramarine, references in concrete grey. Values are printed, and every bar has a hover tip. */
function Bars({ rows, max = 100, unit = "%" }: { rows: { label: string; value: number; tip: string; strong?: boolean }[]; max?: number; unit?: string }) {
  return (
    <div className="bars" role="table">
      {rows.map((r) => (
        <div className="bar" key={r.label} role="row">
          <span className="lbl" role="cell">{r.label}</span>
          <span className="track" role="cell"><span className={`fill ${r.strong ? "" : "muted"}`} style={{ width: `${(100 * r.value) / max}%`, display: "block" }} /></span>
          <span className="val num" role="cell">{r.value.toFixed(1)}{unit}</span>
          <span className="tip">{r.tip}</span>
        </div>
      ))}
    </div>
  );
}

const ROW_LABEL: Record<string, string> = {
  "nearest_distance@current": "Today: nearest on the map, vans at stations",
  "nearest_eta@current": "Fastest by road, vans at stations",
  "coverage@current": "Coverage-aware rule, vans at stations",
  "nearest_eta@rebalanced": "Fastest by road, vans shared by demand",
  "nearest_eta@spread": "Fastest by road, vans spread evenly",
  "nearest_eta@mexclp": "Fastest by road, MEXCLP standby points (recommended)",
  "nearest_eta@optimised": "Fastest by road, our first greedy planner",
};

function WorstTable({ rows, keyName }: { rows: Record<string, any>; keyName: string }) {
  const order = ["nearest_distance@current", "nearest_eta@current", "nearest_eta@rebalanced", "nearest_eta@optimised", "nearest_eta@mexclp"];
  return (
    <table className="t">
      <thead><tr><th>Arrangement</th><th className="n">In target</th><th className="n">Median</th><th className="n">90% within</th><th className="n">Worst-served sector</th></tr></thead>
      <tbody>{order.filter((k) => rows[k]).map((k) => { const r = rows[k], w = r.worst_sector || {}; return (
        <tr key={k} className={k.endsWith("mexclp") ? "strong" : ""}><td>{ROW_LABEL[k] ?? k}</td><td className="n">{r[keyName].toFixed(1)}%</td>
          <td className="n">{r.p50_min.toFixed(2)} min</td><td className="n">{r.p90_min.toFixed(2)} min</td>
          <td className="n">{w.sector ? `Sector ${w.sector}: ${w.within_pct}%` : "–"}</td></tr>); })}</tbody>
    </table>
  );
}

export default function Evidence() {
  const [ev, setEv] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.evidence().then(setEv).catch((e) => setErr(e.message)); }, []);
  if (err) return <div className="evidence"><p className="err">Could not load results: {err}</p></div>;
  if (!ev) return <div className="evidence"><p className="hint">Loading results…</p></div>;
  const b = ev.benchmark, pcr = b?.scenarios?.pcr, fire = ev.fire_siting, amb = b?.scenarios?.ambulance;
  const tg = ev.triage_gemini?.summary, tb = ev.triage_baseline?.summary, tl = ev.triage_local?.summary;
  const ig = ev.india_gemini?.summary, ib = ev.india_baseline?.summary, il = ev.india_local?.summary;

  const rowsFor = (s: any, key: string) => Object.entries(s.rows as Record<string, any>).map(([k, v]) => ({
    label: ROW_LABEL[k] ?? k, value: v[key], strong: k.endsWith("@mexclp"),
    tip: s.vs_today[k] ? `${s.vs_today[k].within_pct_points >= 0 ? "+" : ""}${s.vs_today[k].within_pct_points.toFixed(1)} points vs today (95% CI ${s.vs_today[k].within_ci95[0].toFixed(1)} to ${s.vs_today[k].within_ci95[1].toFixed(1)}), mean ${v.mean_min.toFixed(2)} min` : `mean ${v.mean_min.toFixed(2)} min, 90% of calls within ${v.p90_min.toFixed(2)} min`,
  }));

  return (
    <div className="evidence">
      <div className="ev-inner">
        <h1>What the simulation shows</h1>
        <p className="lede">Every number here comes from replaying simulated calls on Chandigarh's real road network and its real police and fire stations, calibrated so today's rule reproduces the published 4 min 32 s police response. The calls themselves are synthetic, because incident-level data is not public.</p>

        {pcr && (
          <section className="panel">
            <h2>Police (PCR): share of calls reached within 5 minutes</h2>
            <p>{pcr.units} vans on duty, {pcr.calls_per_day} calls a day, {pcr.incidents.toLocaleString()} simulated calls per row. Same calls for every row.</p>
            <Bars rows={rowsFor(pcr, "within_5min_pct")} />
            <p style={{ marginTop: 12 }}>Sending the vehicle that is fastest by road adds about 2 points. Where idle vans wait adds far more: <b>+{pcr.vs_today["nearest_eta@mexclp"].within_pct_points.toFixed(1)} points</b> with standby points from MEXCLP, the textbook ambulance-location model (Daskin, 1983).</p>
            <p>Our own first planner (greedy coverage) reached {pcr.rows["nearest_eta@optimised"].within_5min_pct.toFixed(1)}%. MEXCLP beat it by {(-pcr.optimised_vs_mexclp.within_pct_points).toFixed(1)} points because it plans for vans being busy, so we switched to MEXCLP. The standby layer on the live map uses it.</p>
            <h3>Not just the average: the hardest-to-reach sector</h3>
            <WorstTable rows={pcr.rows} keyName="within_5min_pct" />
            <p>Not shown: today's real van positions are not published. If vans already wait at well-chosen points, the gain shrinks.</p>
          </section>
        )}

        {b?.demand_sweep && (
          <section className="panel">
            <h2>Does it depend on where we assumed calls happen?</h2>
            <p>Where calls happen is our weakest assumption, so we re-ran the police comparison under four different demand patterns and a night shift with fewer vans. Each time the planner only learned from that pattern's past calls.</p>
            <table className="t">
              <thead><tr><th>Demand pattern</th><th className="n">Today</th><th className="n">MEXCLP standby</th><th className="n">Gain [95% CI]</th><th className="n">Worst sector today → with standby</th></tr></thead>
              <tbody>{Object.entries(b.demand_sweep as Record<string, any>).map(([label, s]) => { const d = s.vs_today["nearest_eta@mexclp"]; const a = s.rows["nearest_distance@current"], m = s.rows["nearest_eta@mexclp"]; return (
                <tr key={label}><td>{label}</td><td className="n">{a.within_5min_pct.toFixed(1)}%</td><td className="n">{m.within_5min_pct.toFixed(1)}%</td>
                  <td className="n">+{d.within_pct_points.toFixed(1)} [{d.within_ci95[0].toFixed(1)}, {d.within_ci95[1].toFixed(1)}]</td>
                  <td className="n">{a.worst_sector?.within_pct ?? "–"}% → {m.worst_sector?.within_pct ?? "–"}%</td></tr>); })}</tbody>
            </table>
            <p style={{ marginTop: 10 }}>The gain stays between about +19 and +30 points in every pattern. It comes from where vans wait, not from predicting crime. Each row is {b.seeds} independent runs of {b.days} days on the same calls for every arrangement; intervals come from resampling whole days.</p>
          </section>
        )}

        {fire && (
          <section className="panel">
            <h2>Fire: where the next stations should go</h2>
            <p>Share of fire calls reached within 5 minutes, 7 stations today. Fire tenders need stations, so this compares new sites rather than moving tenders.</p>
            <Bars rows={Object.entries(fire.options as Record<string, any>).map(([k, v]) => ({
              label: k.replace("today: 7 stations", "Today, 7 stations").replace("+MC 2017 plan (IT Park only; Sector 53 pin missing)", "+ IT Park (2017 plan)").replace("+1 best new site", "+ 1 best new site").replace("+2 best new sites", "+ 2 best new sites"),
              value: v.within_5min_pct, strong: k.includes("best"),
              tip: v.vs_today ? `${v.vs_today.within_pct_points >= 0 ? "+" : ""}${v.vs_today.within_pct_points.toFixed(1)} points vs today; ${v.risk_within_5min_pct}% of fire risk within 5 min` : `${v.risk_within_5min_pct}% of fire risk within 5 min`,
            }))} />
            <p style={{ marginTop: 12 }}>The planned IT Park site sits close to Manimajra, so it adds little. The best two sites are at {fire.best_sites.map((s: number[]) => `${s[0].toFixed(4)}, ${s[1].toFixed(4)}`).join(" and ")}.</p>
          </section>
        )}

        {amb && (
          <section className="panel">
            <h2>Ambulance: a range, not a finding</h2>
            <p>The real 108 fleet and call volume are not published. With 6 vehicles at the five 108 hospitals and an assumed {amb.calls_per_day} calls a day:</p>
            <Bars rows={rowsFor(amb, "within_8min_pct")} />
            <p style={{ marginTop: 12 }}>At 80 calls a day, six vehicles are overloaded whatever the placement: that would be a fleet-size problem.</p>
          </section>
        )}

        <section className="panel">
          <h2>Call triage: Gemini, Gemma on this computer, and a keyword baseline</h2>
          <p>52 test calls we wrote in Hindi, Punjabi, English and mixed language, including pranks, fragments and trapped people. A sanity check, not real 112 data.
            The same rules turn each engine's facts into a priority, so the columns differ only in how well the call was read.</p>
          <TriageTable cols={[["Keyword baseline", tb], ["Gemini (cloud)", tg], [`Gemma, local${ev.triage_local?.model ? ` (${ev.triage_local.model})` : ""}`, tl]]} />
          {!tg && <p className="hint">Gemini column: run <code>python3 scripts/eval_triage.py --live</code>.</p>}
          {!tl && <p className="hint">Local Gemma column (sovereign mode): install Ollama, <code>ollama pull gemma3:4b</code>, then <code>python3 scripts/eval_triage.py --local</code>.</p>}
        </section>

        <section className="panel">
          <h2>Beyond Hindi and Punjabi: calls in other Indian languages</h2>
          <p>{ev.india_baseline?.summary?.calls ?? "32"} more test calls in Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati and Odia: the same kinds of emergency, written by us.
            112 is national, so the reader must work for every state's languages. The keyword reader only knows Hindi, Punjabi and English, which is why it fails here.</p>
          <TriageTable cols={[["Keyword baseline", ib], ["Gemini (cloud)", ig], ["Gemma, local", il]]} />
          {(ig || il) && <LangTable runs={[["Gemini", ig], ["Gemma, local", il]]} />}
          {!ig && <p className="hint">Run <code>python3 scripts/eval_triage.py --live --set india</code> (and <code>--local --set india</code> for Gemma).</p>}
        </section>

        <FloodRisk />
        <section className="panel">
          <h2>What this does not show</h2>
          <ul className="caveats">
            <li>Calls are simulated; incident locations follow road class, population and the four official black spots.</li>
            <li>Fire and ambulance call volumes and fleets are assumptions, so their results are ranges.</li>
            <li>Travel times come from OpenStreetMap road classes with a time-of-day factor, not live traffic.</li>
            <li>The traffic-police alert is a proposal: we found no live emergency signal priority in Chandigarh. Junction replies are simulated.</li>
            <li>Not modelled: assigning several calls together, hospital choice and handover delay for ambulances, units breaking down, and mutual aid with Mohali and Panchkula.</li>
          </ul>
        </section>

        <section className="panel credits">
          <h2>Data and licences</h2>
          <ul className="caveats">
            <li>Road network and map data © OpenStreetMap contributors, available under the Open Database Licence (ODbL). Basemap tiles: OpenFreeMap.</li>
            <li>Call reading uses Google Gemini through the Gemini API, under Google's terms. Gemma (backup in the cloud, and the local model in sovereign mode) is an open-weight model under the Gemma Terms of Use, separate from this project's MIT licence; local models run through Ollama.</li>
            <li>Personal data (phone, Aadhaar, PAN, e-mail, vehicle numbers, stated names) is removed from a call before it is sent to any model, in line with India's DPDP Act, 2023.</li>
            <li>Station, hospital and landmark points: Google Maps lookups checked by the team; points marked approximate are not yet verified.</li>
          </ul>
        </section>
      </div>
    </div>
  );
}

const TRIAGE_ROWS: [string, string, string][] = [["Critical calls rated P1", "p1_recall_pct", "higher is better"], ["Calls rated less urgent than they are", "under_triage_pct", "lower is better"],
  ["Calls missing a needed unit", "missed_units_pct", "lower is better"], ["Incident type correct", "incident_type_ok_pct", "higher is better"],
  ["Priority correct", "priority_ok_pct", "higher is better"], ["Sector read correctly", "sector_ok_pct", "higher is better"],
  ["Location mapped without asking", "location_resolved_pct", "higher is better"], ["Seconds per call (mean)", "latency_mean_s", "lower is better"]];

function TriageTable({ cols }: { cols: [string, any][] }) {
  return (
    <table className="t">
      <thead><tr><th>Measure</th>{cols.map(([n]) => <th key={n} className="n">{n}</th>)}</tr></thead>
      <tbody>{TRIAGE_ROWS.map(([l, k, h]) => (
        <tr key={k}><td>{l} <span className="hint">({h})</span></td>
          {cols.map(([n, s]) => <td key={n} className="n">{s?.[k] != null ? (k === "latency_mean_s" ? `${s[k]}` : `${s[k]}%`) : "–"}</td>)}</tr>))}</tbody>
    </table>
  );
}

const LANG_NAME: Record<string, string> = { ta: "Tamil", te: "Telugu", kn: "Kannada", ml: "Malayalam", bn: "Bengali", mr: "Marathi", gu: "Gujarati", or: "Odia" };
function LangTable({ runs }: { runs: [string, any][] }) {
  const langs = Object.keys(LANG_NAME).filter((l) => runs.some(([, s]) => s?.by_language?.[l]));
  return (
    <table className="t small" style={{ marginTop: 10 }}>
      <thead><tr><th>Language</th><th className="n">Calls</th>{runs.map(([n]) => <th key={n} className="n">{n}: type correct</th>)}{runs.map(([n]) => <th key={n + "u"} className="n">{n}: under-triaged</th>)}</tr></thead>
      <tbody>{langs.map((l) => {
        const any = runs.find(([, s]) => s?.by_language?.[l])?.[1].by_language[l];
        return (<tr key={l}><td>{LANG_NAME[l]}</td><td className="n">{any?.n}</td>
          {runs.map(([n, s]) => <td key={n} className="n">{s?.by_language?.[l] ? `${s.by_language[l].type_ok}%` : "–"}</td>)}
          {runs.map(([n, s]) => <td key={n + "u"} className="n">{s?.by_language?.[l] ? `${s.by_language[l].under}%` : "–"}</td>)}</tr>);
      })}</tbody>
    </table>
  );
}
