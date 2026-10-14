/* Rain and waterlogging: pick the rain, scrub through the storm, and read the plan for that moment.
   Everything the plan says comes from the server's water model; Gemini only rewrites the public advisory. */
import { useEffect, useRef, useState } from "react";
import { ai, api } from "./api";
import type { Advisory, FLevel, FloodAction, FloodPlan, FloodScenario } from "./types";

export const LEVEL_LABEL: Record<FLevel, string> = { clear: "Clear", watch: "Watch", divert: "Divert", close: "Closed" };
const ACTION_GROUP: { kind: FloodAction["kind"]; title: string }[] = [
  { kind: "close", title: "Close now" }, { kind: "preclose", title: "Close soon" }, { kind: "pumps", title: "Pump teams" },
  { kind: "divert", title: "Divert traffic" }, { kind: "ems", title: "Ambulance and police reach" },
  { kind: "rescue", title: "Rescue standby" }, { kind: "reopen", title: "Reopen" },
];

/* ---------- left rail: rain input, chart and time scrubber ---------- */
export function RainPanel({ plan, setPlan, onError }: { plan: FloodPlan | null; setPlan: (p: FloodPlan | null) => void; onError: (m: string) => void }) {
  const [scen, setScen] = useState<FloodScenario[]>([]);
  const [pick, setPick] = useState("aug2024");
  const [mm, setMm] = useState(40);
  const [hrs, setHrs] = useState(2);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [step, setStep] = useState(0);
  const pending = useRef<number | null>(null);
  const stepRef = useRef(0);
  stepRef.current = step;

  useEffect(() => { api.floodScenarios().then(setScen).catch(() => {}); }, []);
  useEffect(() => { if (plan) setStep(plan.step); }, [plan?.step, plan?.scenario.label]);

  async function load() {
    setBusy(true); setPlaying(false);
    try { setPlan(await api.floodStart(pick, pick === "custom" ? mm : undefined, pick === "custom" ? hrs : undefined)); }
    catch (e) { onError((e as Error).message); } finally { setBusy(false); }
  }
  // scrubbing: show the new time at once, apply it to routing when the slider settles
  function goto(s: number) {
    setStep(s);
    if (pending.current) window.clearTimeout(pending.current);
    pending.current = window.setTimeout(() => api.floodApply(s).then(setPlan).catch((e) => onError(e.message)), 250);
  }
  useEffect(() => {
    if (!playing || !plan) return;
    const len = plan.labels.length;
    const h = window.setInterval(() => {
      const n = stepRef.current + 1;
      if (n >= len) { setPlaying(false); return; }
      stepRef.current = n; setStep(n);
      api.floodApply(n).then(setPlan).catch(() => {});
    }, 700);
    return () => window.clearInterval(h);
  }, [playing, plan?.scenario.label]);

  const last = plan ? plan.labels.length - 1 : 0;
  return (
    <>
      <form className="section" onSubmit={(e) => { e.preventDefault(); void load(); }} aria-labelledby="rainh">
        <h2 id="rainh">Rain</h2>
        <fieldset className="radios">
          <legend className="hint">Which rain</legend>
          {scen.map((s) => (
            <label key={s.id}><input type="radio" name="scen" value={s.id} checked={pick === s.id} onChange={() => setPick(s.id)} />
              <span>{s.label}<small>{s.note}</small></span></label>
          ))}
          <label><input type="radio" name="scen" value="custom" checked={pick === "custom"} onChange={() => setPick("custom")} /><span>Your own numbers</span></label>
        </fieldset>
        {pick === "custom" && (
          <div className="row">
            <label className="mini">mm per hour<input type="number" min={1} max={200} value={mm} onChange={(e) => setMm(+e.target.value)} /></label>
            <label className="mini">for hours<input type="number" min={1} max={24} value={hrs} onChange={(e) => setHrs(+e.target.value)} /></label>
          </div>
        )}
        <div className="row"><button className="btn" disabled={busy}>{busy ? <><span className="spin" />Working out the water</> : plan ? "Load this rain" : "Start rain plan"}</button>
          {plan && <button type="button" className="btn secondary" onClick={() => api.floodClear().then(() => setPlan(null))}>Stop rain plan</button>}</div>
      </form>
      {plan && (
        <div className="section">
          <h2>{plan.scenario.label}</h2>
          <RainChart plan={plan} step={step} onPick={goto} />
          <div className="scrub">
            <button type="button" className="btn secondary" onClick={() => setPlaying(!playing)} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button>
            <input type="range" min={0} max={last} value={step} onChange={(e) => goto(+e.target.value)} aria-label="Time in the storm" />
            <b className="num">{plan.labels[step]}</b>
          </div>
          <p className="hint">Drag through the storm. Roads closed at this moment are closed for live dispatch too: ambulance and PCR routes go around them.</p>
          <label className="check"><input type="checkbox" checked={plan.pumps} onChange={(e) => api.floodApply(undefined, e.target.checked).then(setPlan).catch((x) => onError(x.message))} />
            MC pump teams go out as planned ({plan.teams_total} teams)</label>
          <div className="kpis">
            <div><b className="num">{plan.counts.close}</b><span>closed</span></div>
            <div><b className="num">{plan.counts.divert}</b><span>diverted</span></div>
            <div><b className="num">{plan.counts.watch}</b><span>on watch</span></div>
          </div>
          <p className="hint">Whole storm: <b>{plan.totals.closed_hours_no_pump} road-hours closed</b> with no pumps; <b>{plan.totals.closed_hours}</b> with the pump plan.</p>
        </div>
      )}
      {plan && <SpotList plan={plan} />}
    </>
  );
}

/* Hourly rain as bars, with the drains' design capacity as two reference lines. Single series: no legend. */
function RainChart({ plan, step, onPick }: { plan: FloodPlan; step: number; onPick: (s: number) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  const R = plan.rain_hourly, n = R.length;
  const W = 310, H = 130, L = 30, B = 20, T = 8;
  const max = Math.max(25, ...R) * 1.1;
  const x = (i: number) => L + (i / n) * (W - L - 4), y = (v: number) => T + (1 - v / max) * (H - T - B);
  const bw = Math.max(2, (W - L - 4) / n - 2);
  const perHour = Math.round(1 / plan.step_h);
  const nowH = step / perHour;
  const ticks = [0, Math.round(max / 2 / 10) * 10, Math.floor(max / 10) * 10].filter((v, i, a) => a.indexOf(v) === i);
  const hourLabel = (h: number) => plan.labels[Math.min(plan.labels.length - 1, h * perHour)] ?? "";
  return (
    <figure className="rainchart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Hourly rain, peak ${Math.max(...R)} mm in an hour`} onMouseLeave={() => setHover(null)}>
        {ticks.map((v) => <g key={v}><line x1={L} x2={W - 2} y1={y(v)} y2={y(v)} className="grid" /><text x={L - 4} y={y(v) + 4} className="ax" textAnchor="end">{v}</text></g>)}
        {R.map((v, i) => (
          <g key={i} onMouseEnter={() => setHover(i)} onClick={() => onPick(i * perHour)} style={{ cursor: "pointer" }}>
            <rect x={x(i)} y={T} width={(W - L - 4) / n} height={H - T - B} fill="transparent" />
            {v > 0 && <rect x={x(i) + 1} y={y(v)} width={bw} height={Math.max(1, y(0) - y(v))} rx={Math.min(2, bw / 2)} className={i < nowH - 0.001 ? "bar past" : "bar"} />}
          </g>
        ))}
        {(["north", "south"] as const).map((k) => (
          <g key={k}><line x1={L} x2={W - 2} y1={y(plan.design_mm_h[k])} y2={y(plan.design_mm_h[k])} className={`ref ${k}`} />
            <text x={W - 4} y={y(plan.design_mm_h[k]) - 3} textAnchor="end" className="reflab">drains {k === "north" ? "N" : "S"} {plan.design_mm_h[k]}</text></g>
        ))}
        <line x1={x(nowH)} x2={x(nowH)} y1={T} y2={H - B} className="nowline" />
        <text x={L} y={H - 5} className="ax">{hourLabel(0)}</text>
        <text x={W - 2} y={H - 5} className="ax" textAnchor="end">{hourLabel(n - 1)}</text>
      </svg>
      {hover !== null && <div className="tip" style={{ left: `${(x(hover) / W) * 100}%` }}><b>{R[hover]} mm</b> in the hour from {hourLabel(hover)}</div>}
      <figcaption className="hint">mm of rain per hour. Lines: what the drains were designed for (15 mm/h northern sectors, 20 southern; MC). Click a bar to jump there.</figcaption>
    </figure>
  );
}

function SpotList({ plan }: { plan: FloodPlan }) {
  const order: FLevel[] = ["close", "divert", "watch", "clear"];
  const spots = [...plan.spots].sort((a, b) => order.indexOf(a.level) - order.indexOf(b.level) || b.depth - a.depth);
  return (
    <div className="section">
      <h2>Known flood spots ({plan.spots.length})</h2>
      <ul className="spots">
        {spots.map((s) => (
          <li key={s.id} className={`lv-${s.level}`}>
            <span className={`lvtag ${s.level}`}>{LEVEL_LABEL[s.level]}</span>
            <span className="sname">{s.name}{s.accuracy !== "good" && <small title="Position worked out from the sector grid or an unverified list"> · position {s.accuracy}</small>}</span>
            <span className="num depth">{s.depth.toFixed(0)} cm {s.trend === "rising" ? "↑" : s.trend === "falling" ? "↓" : ""}</span>
          </li>
        ))}
      </ul>
      <p className="hint">Watch 5 cm, divert 15 cm, close 30 cm. Spots from the traffic police list (9 Jul 2023), MC's flood-prone list (Sep 2025) and news reports of 11 Aug 2024 and 19 Aug 2025.</p>
    </div>
  );
}

/* ---------- right rail: the plan for this moment ---------- */
export function PlanPanel({ plan, gemini }: { plan: FloodPlan | null; gemini: boolean }) {
  const [adv, setAdv] = useState<Advisory | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"english" | "hindi" | "punjabi" | "sms">("english");
  useEffect(() => setAdv(null), [plan?.scenario.label, plan?.step]);
  if (!plan) return (
    <div className="section">
      <h2>No rain plan running</h2>
      <p className="hint">Pick some rain on the left. The model works out how deep the water gets at each of Chandigarh's known flood spots, every 15 minutes, and turns that into a plan: which roads to close and when, where the barricades and diversions go, where the 18 MC flood teams go, and how ambulance reach changes.</p>
      <p className="hint">Replays of 11 Aug 2024 and 8-9 Jul 2023 use the real rain totals; the live option uses Open-Meteo's rain for the last 24 hours and the next 12.</p>
    </div>
  );
  return (
    <>
      <div className="section planhead">
        <h2>Plan at {plan.now}</h2>
        <p className="hint">Rain this hour: <b>{plan.rain_now} mm</b>. {plan.actions.length === 0 ? "Nothing to do: the drains are coping." : ""}</p>
      </div>
      {ACTION_GROUP.map(({ kind, title }) => {
        const acts = plan.actions.filter((a) => a.kind === kind);
        if (!acts.length) return null;
        return (
          <div key={kind} className={`section act act-${kind}`}>
            <h2>{title}{acts.length > 1 && <span className="count num">{acts.length}</span>}</h2>
            {kind === "divert" ? (
              <ul className="plain">{acts.map((a) => <li key={a.title}><b>{a.title.replace("Divert traffic at ", "")}</b>: {a.text.split(".")[0]}.</li>)}</ul>
            ) : acts.map((a) => (
              <div key={a.title} className="actrow">
                {kind !== "pumps" && kind !== "ems" && <h3>{a.title}</h3>}
                <p>{a.text}</p>
                {a.diversion && <p className="div"><b>{a.diversion.text}</b></p>}
                {a.barricades && a.barricades.length > 0 && <p className="hint">Barricades and traffic posts: {a.barricades.length} points ({[...new Set(a.barricades.map((b) => b.road))].slice(0, 3).join(", ")}).</p>}
              </div>
            ))}
          </div>
        );
      })}
      <div className="section">
        <h2>Pump teams</h2>
        {plan.teams.length === 0 ? <p className="hint">{plan.pumps ? "No spot needs a team." : "Pump teams switched off: this is what happens if nobody goes out."}</p> : (
          <table className="t small">
            <thead><tr><th>Team</th><th>Where</th><th>By</th><th>Peak cm</th></tr></thead>
            <tbody>{plan.teams.map((t) => (
              <tr key={t.team} className={`ts-${t.state}`}><td className="n">{t.team}</td><td>{t.name}</td><td className="n">{t.at}{t.state === "working" ? " ✓" : ""}</td>
                <td className="n" title={`without a pump: ${t.peak_no_pump} cm`}>{t.peak.toFixed(0)} <small>(no pump {t.peak_no_pump.toFixed(0)})</small></td></tr>))}</tbody>
          </table>
        )}
      </div>
      <div className="section">
        <h2>Emergency reach</h2>
        <div className="summary-list">
          <div><span>Calls an ambulance reaches in 8 min</span><b className="num">{plan.ems.amb_cover_before}% → {plan.ems.amb_cover_after}%</b></div>
          <div><span>Calls a PCR reaches in 5 min</span><b className="num">{plan.ems.pcr_cover_before}% → {plan.ems.pcr_cover_after}%</b></div>
          {plan.ems.hospitals.map((h) => <div key={h.name}><span>Average drive to {h.name}</span><b className="num">{h.before_min} → {h.after_min} min</b></div>)}
        </div>
        {plan.ems.sectors_lost.length > 0 && plan.ems.amb_cover_after < plan.ems.amb_cover_before - 0.5 && <p className="hint">Sectors losing 8-minute ambulance reach: {plan.ems.sectors_lost.join(", ")}.</p>}
        <p className="hint">Same fleet and response targets as the benchmark; demand weighted by road use (model).</p>
      </div>
      <div className="section">
        <h2>Public advisory</h2>
        <button className="btn" disabled={busy} onClick={async () => { setBusy(true); try { setAdv(await api.floodAdvisory()); } finally { setBusy(false); } }}>
          {busy ? <><span className="spin" />Writing</> : gemini ? `Write it with ${ai.name} (English, Hindi, Punjabi)` : "Write it (template)"}</button>
        {adv && (
          <div className="adv">
            <div className="advtabs" role="tablist">{(["english", "hindi", "punjabi", "sms"] as const).map((k) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{k === "sms" ? "SMS" : k[0].toUpperCase() + k.slice(1)}</button>))}</div>
            <p className="advtext" lang={tab === "hindi" ? "hi" : tab === "punjabi" ? "pa" : "en"}>{adv.advisory[tab]}</p>
            <div className="row"><button className="btn secondary" onClick={() => navigator.clipboard?.writeText(adv.advisory[tab])}>Copy</button>
              <span className="hint">{adv.by === "template" ? adv.note : `Written by ${adv.by} from the plan's facts only${adv.latency_s ? ` in ${adv.latency_s} s` : ""}. Check before sending.`}</span></div>
          </div>
        )}
      </div>
    </>
  );
}

/* ---------- Evidence tab: how often each spot floods, from past monsoons ---------- */
export function FloodRisk() {
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.floodRisk().then(setR).catch((e) => setErr(e.message)); }, []);
  if (err) return <section className="panel"><h2>Waterlogging</h2><p className="err">{err}</p></section>;
  if (!r) return <section className="panel"><h2>Waterlogging: how often each spot floods</h2><p className="hint">Running the water model over past monsoons…</p></section>;
  const c = r.check;
  return (
    <section className="panel">
      <h2>Waterlogging: how often each spot floods</h2>
      <p>Rain: <b>{r.info.source}</b> ({r.info.seasons} monsoons, June to September). {r.info.caveat}</p>
      <p className="hint">Generated monsoons average {r.rain.season_mm_mean} mm (IMD normal 844.9 mm). The wettest day of a season is {r.rain.max_day_mm_median} mm in a typical year
        ({r.rain.max_day_mm_p90} mm in 1 year in 10); the city recorded 129.7 mm on 11 Aug 2024 and 322.2 mm on 8-9 Jul 2023.</p>
      <h3>Check against what happened</h3>
      <ul className="plain">
        <li>Fitted on the {r.fit.fitted_on.length} places reported waterlogged on 11 Aug 2024: one city-wide ponding scale ({r.fit.gain_scale}) and nothing else.</li>
        <li>Held out: of the <b>{c.t23_listed}</b> roads the traffic police told people to avoid on 9 Jul 2023, the 2023 replay floods <b>{c.t23_diverted_or_closed}</b> to divert depth or more ({c.t23_closed} to closure).</li>
        <li>No false alarms in ordinary rain: a 12 mm shower closes {c.shower_closed} and diverts {c.shower_diverted}; 25 mm/h for 2 hours closes {c.heavy_closed} and diverts {c.heavy_diverted} of {c.spots} spots.</li>
      </ul>
      <table className="t">
        <thead><tr><th>Spot</th><th>Drains (mm/h)</th><th>Closures per monsoon</th><th>Chance of at least one</th><th>Hours closed per monsoon</th><th>1-hour burst that closes it</th></tr></thead>
        <tbody>{r.rows.map((x: any) => (
          <tr key={x.id}><td>{x.name}<br /><small className="muted">{x.sources.join(", ")}{x.accuracy !== "good" ? ` · position ${x.accuracy}` : ""}</small></td>
            <td className="n">{x.capacity_mm_h}</td><td className="n">{x.closures_per_season}</td><td className="n">{Math.round(x.p_closure * 100)}%</td>
            <td className="n">{x.hours_closed_per_season}</td><td className="n">{x.burst_to_close_mm_h} mm</td></tr>))}</tbody>
      </table>
      <p className="hint">Without pump teams. Drain design: {r.design_mm_h.north} mm/h in the northern sectors and {r.design_mm_h.south} mm/h in the southern ones (MC via Tribune, Aug 2024); a spot named in 2 reports is taken to drain 10% worse, 3 or more 20%.
        How much water ponds per mm over capacity, how fast it drains, the depth thresholds and the pump rate ({r.pump_cm_h} cm/h) are assumptions, labelled in <code>src/csafe/flood.py</code>.
        Sources: T23 Tribune 9 Jul 2023 (traffic police list), T24 Tribune 12 Aug 2024, MC25 Tribune 4 Sep 2025 (MC's flood-prone list), W25 PTI 20 Aug 2025.</p>
    </section>
  );
}
