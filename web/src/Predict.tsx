/* Predict and monitor: the next hours (forecast), and live alerts when today doesn't match it. */
import { useState } from "react";
import { api } from "./api";
import type { Outlook, Watch, WatchAlert } from "./types";

const KIND_TAG: Record<WatchAlert["kind"], string> = {
  cluster: "Unusual cluster", surge: "Surge", coverage: "Cover gap", fleet: "Fleet low", rain: "Rain", prepare: "Get ready",
};

/* ---------- left rail: the outlook ---------- */
export function OutlookPanel({ o }: { o: Outlook | null }) {
  if (!o) return <div className="section"><h2>Next 6 hours</h2><p className="hint"><span className="spin" />Working out the forecast…</p></div>;
  const s = o.skill;
  return (
    <>
      <div className="section">
        <h2>Next 6 hours</h2>
        <p className="hint">Expected 112 calls that need a PCR van, by hour, with the range we'd expect 8 days in 10.
          Peak: <b>{o.peak_hour}</b>.{o.conditions.length > 0 && <> Adjusted for {o.conditions.join(" and ")}.</>}</p>
        <CallsChart o={o} />
        <table className="t small fc">
          <thead><tr><th>Hour</th><th className="n">Ambulance calls</th><th className="n">No ambulance free</th><th className="n">Fire calls</th></tr></thead>
          <tbody>{o.rows.map((r) => (
            <tr key={r.hour}><td className="num">{r.hour}</td><td className="n">{r.services.ambulance.expected.toFixed(1)}</td>
              <td className={`n ${r.services.ambulance.p_none_free >= 5 ? "warnc" : ""}`}>{r.services.ambulance.p_none_free.toFixed(1)}%</td>
              <td className="n">{r.services.fire.expected.toFixed(1)}</td></tr>))}</tbody>
        </table>
        <p className="hint">"No ambulance free": the chance that a new call finds all {o.rows[0].services.ambulance.units} ambulances busy (Erlang B, from calls per hour and minutes busy per call).</p>
      </div>
      <div className="section">
        <h2>Where, in the next hour</h2>
        <ol className="zones">{o.zones.map((z, i) => (
          <li key={z.sector}><span className="zn">{i + 1}</span><span><b>Sector {z.sector}</b> · {z.share}% of calls<br /><small className="muted">{z.why.join("; ")}</small></span></li>))}</ol>
        <p className="hint">Numbered on the map. Same model that places the standby points.</p>
      </div>
      <div className="section">
        <h2>Does the hotspot forecast work?</h2>
        <div className="kpis">
          <div><b className="num">{s.hit_pct}%</b><span>of next month's crashes in the top {s.area_pct}% of the map</span></div>
          <div><b className="num">{s.of_best_pct}%</b><span>of the best any forecast could do ({s.best_hit_pct}%)</span></div>
        </div>
        <p className="hint">Learned from {s.train_days} days ({s.train_n.toLocaleString()} crashes), tested on the next {s.test_days} days ({s.test_n} crashes) it never saw.
          Predictive Accuracy Index {s.pai} (random = 1). {s.note}</p>
      </div>
      <div className="section"><h2>What the forecast is built on</h2><ul className="plain hint">{o.notes.map((n) => <li key={n}>{n}</li>)}</ul></div>
    </>
  );
}

function CallsChart({ o }: { o: Outlook }) {
  const [hover, setHover] = useState<number | null>(null);
  const R = o.rows.map((r) => r.services.police);
  const W = 300, H = 150, L = 26, B = 22, T = 10;
  const max = Math.max(4, ...R.map((x) => x.high)) * 1.08;
  const step = (W - L) / R.length, bw = Math.min(26, step * 0.55);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const ticks = [0, Math.round(max / 2), Math.floor(max)].filter((v, i, a) => a.indexOf(v) === i);
  return (
    <figure className="rainchart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Expected PCR calls per hour from ${o.rows[0].hour}: ${R.map((x) => x.expected).join(", ")}`}>
        {ticks.map((v) => <g key={v}><line x1={L} x2={W - 2} y1={y(v)} y2={y(v)} className="grid" /><text x={L - 4} y={y(v) + 4} className="ax" textAnchor="end">{v}</text></g>)}
        {R.map((r, i) => {
          const cx = L + step * i + step / 2;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={L + step * i} y={T} width={step} height={H - T - B} fill="transparent" />
              <path d={`M${cx - bw / 2},${y(0)} V${y(r.expected) + 4} q0,-4 4,-4 H${cx + bw / 2 - 4} q4,0 4,4 V${y(0)} Z`} className={`bar ${hover === i ? "hot" : ""}`} />
              <line x1={cx} x2={cx} y1={y(r.high)} y2={y(r.low)} className="whisk" />
              <line x1={cx - 5} x2={cx + 5} y1={y(r.high)} y2={y(r.high)} className="whisk" />
              <line x1={cx - 5} x2={cx + 5} y1={y(r.low)} y2={y(r.low)} className="whisk" />
              <text x={cx} y={H - 6} className="ax" textAnchor="middle">{o.rows[i].hour.slice(0, 2)}</text>
            </g>
          );
        })}
      </svg>
      {hover !== null && <div className="tip" style={{ left: `${((L + step * hover + step / 2) / W) * 100}%` }}>
        <b>{R[hover].expected} calls</b> from {o.rows[hover].hour} (range {R[hover].low}-{R[hover].high}); about {R[hover].busy} of {R[hover].units} vans busy</div>}
      <figcaption className="hint">Bars: expected calls. Lines: 80% range (Poisson).</figcaption>
    </figure>
  );
}

/* ---------- right rail: live watch ---------- */
const TEST_CALLS = [
  "Sector 29 light point pe do bike takra gayi, ek ladka ghayal pada hai",
  "ITI Sector 29 ke paas jhagda ho raha hai, log dande se maar rahe hai",
  "Tribune Chowk ke paas ek gaadi mein aag lag gayi hai, dhuan nikal raha hai",
];

export function WatchPanel({ w, onDone, onError }: { w: Watch | null; onDone: (title: string, body?: string) => void; onError: (m: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (a: WatchAlert) => {
    if (!a.action) return;
    setBusy(a.id);
    try {
      const moves = a.action.kind === "spread" ? a.action.moves! : [{ unit: a.action.unit!, lat: a.action.lat!, lng: a.action.lng! }];
      for (const m of moves) await api.reposition(m.unit, m.lat, m.lng);
      onDone(`${moves.length === 1 ? moves[0].unit + " is" : moves.length + " vans are"} moving to standby`, "The map shows them driving there. Cover updates as they arrive.");
    } catch (e) { onError((e as Error).message); }
    setBusy(null);
  };
  const test = async () => {
    setBusy("test");
    try {
      for (const t of TEST_CALLS) { const fd = new FormData(); fd.append("transcript", t); await api.call(fd); await new Promise((r) => setTimeout(r, 400)); }
      onDone("3 test calls sent", "An accident, a fight and a car fire within a few hundred metres of each other.");
    } catch (e) { onError((e as Error).message); }
    setBusy(null);
  };
  const c = w?.coverage;
  return (
    <>
      <div className="section planhead">
        <h2>Live watch</h2>
        <p className="hint">Checks the live incidents against the forecast every few seconds{w ? ` (last ${w.window_min_demo} min on the demo clock, about ${w.window_min_wall} real minutes)` : ""}.</p>
      </div>
      {c && (
        <div className="section">
          <div className="summary-list">
            <div><span>Calls a PCR van can reach in 5 min, right now</span><b className="num">{c.now.toFixed(0)}%</b></div>
            <div><span>Free PCR vans</span><b className="num">{c.free} of {c.on_duty}</b></div>
          </div>
        </div>
      )}
      <div className="section">
        {!w ? <p className="hint"><span className="spin" />Starting…</p> : w.alerts.length === 0 ? <p className="hint">Nothing unusual. Alerts appear here when the live incidents don't match the forecast.</p> : (
          <ul className="walerts">{w.alerts.map((a) => (
            <li key={a.id} className={`wa wa-${a.level}`}>
              <div className="wa-h"><span className={`wtag ${a.kind}`}>{KIND_TAG[a.kind]}</span><b>{a.title}</b></div>
              <p>{a.text}</p>
              <p className="todo"><b>Do:</b> {a.todo}</p>
              <div className="row">
                {a.action && <button className="btn" disabled={busy !== null} onClick={() => act(a)}>{busy === a.id ? <><span className="spin" />Moving</> : a.action.label}</button>}
                <button className="btn secondary" onClick={() => api.dismiss(a.id).catch(() => {})}>Dismiss</button>
              </div>
            </li>))}</ul>
        )}
      </div>
      <div className="section">
        <h2>Try it</h2>
        <p className="hint">Sends three calls about different incidents close together (Sector 29 and Tribune Chowk). The watch should flag them as an unusual cluster.</p>
        <button className="btn secondary" disabled={busy !== null} onClick={test}>{busy === "test" ? <><span className="spin" />Sending</> : "Send 3 test calls"}</button>
      </div>
    </>
  );
}
