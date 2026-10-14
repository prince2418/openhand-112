/* Open platform: OpenHand as digital public infrastructure. What plugs in, what goes out, in which standard,
   and a live log of every message the system would exchange with other agencies. */
import { Fragment, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { AIEngines, Iface, OutMsg } from "./types";

const PRINCIPLES = [
  ["Open source", "MIT licence. Any city or state can run, check or change it; no vendor lock-in."],
  ["Data sovereignty", "Sovereign mode runs Gemma, an open-weight model, on the state's own hardware: no call data leaves it, and it keeps working offline."],
  ["Open standards", "CAP 1.2 for public alerts (the format NDMA's SACHET uses), GeoJSON and CSV for open data, JSON over HTTPS for everything else, an OpenAPI description of every endpoint."],
  ["Builds on what exists", "Sits behind ERSS-112 and the ICCC: it doesn't replace the control room, the CCTV system or the dispatch radios; it adds a decision layer they can all call."],
  ["Privacy by design", "Names and numbers are removed before the AI reads a call. CCTV frames are not stored. Open data has no caller words, places rounded to ~550 m, times to the hour."],
  ["Human in charge", "The AI reads and suggests; fixed rules set priority; the dispatcher sends. Every message below is logged with what was sent and why."],
];

function EnginePanel({ onEngine }: { onEngine?: () => void }) {
  const [e, setE] = useState<AIEngines | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => api.engines().then(setE).catch(() => {});
  useEffect(() => { load(); const h = setInterval(load, 5000); return () => clearInterval(h); }, []);
  const use = async (k: "gemini" | "local") => {
    setBusy(k); setErr(null);
    try { setE(await api.setEngine(k)); onEngine?.(); } catch (x) { setErr((x as Error).message); }
    setBusy(null);
  };
  if (!e) return null;
  return (
    <section className="panel">
      <h2>Who reads the calls: cloud or sovereign</h2>
      <p>The same triage, rules and audit trail run on either engine. A state that can't send emergency calls to a cloud service runs
        <b> Gemma</b>, Google's open-weight model, on its own computer: the call text, photos and camera frames never leave the building.</p>
      <div className="engines">
        <div className={`engine ${e.active === "gemini" ? "on" : ""}`}>
          <h3>Google Gemini <small>cloud</small></h3>
          <p className="muted">{e.gemini.where}</p>
          {e.gemini.available ? <p>Model <code>{e.gemini.model}</code>{e.gemini.fallbacks.length > 0 && <> · backups {e.gemini.fallbacks.join(", ")}</>}</p>
            : <p className="warnc">No Gemini key in <code>.env</code>.</p>}
          <ul className="plain hint"><li>Reads text, photos, camera frames and voice clips</li><li>Personal details removed before sending (DPDP Act)</li></ul>
          {e.active === "gemini" ? <span className="badge">In use</span>
            : <button className="btn secondary" disabled={!e.gemini.available || busy !== null} onClick={() => use("gemini")}>{busy === "gemini" ? "Switching…" : "Use Gemini"}</button>}
        </div>
        <div className={`engine ${e.active === "local" ? "on" : ""}`}>
          <h3>Gemma on this computer <small>sovereign mode</small></h3>
          <p className="muted">{e.local.where} · open weights</p>
          <p>Model <code>{e.local.model}</code> {e.local.ok ? <span className="okc">ready</span> : <span className="warnc">not ready</span>}</p>
          {!e.local.ok && <p className="hint">{e.local.reason}</p>}
          <ul className="plain hint"><li>No call data leaves this computer; works without internet</li><li>Reads text, photos and camera frames; voice clips still need Gemini</li></ul>
          {e.active === "local" ? <span className="badge">In use</span>
            : <button className="btn" disabled={!e.local.ok || busy !== null} onClick={() => use("local")}>{busy === "local" ? "Switching…" : "Use Gemma on this computer"}</button>}
        </div>
      </div>
      {err && <p className="err">{err}</p>}
      <p className="hint">Accuracy of both engines on the same test calls: Evidence tab. Setup: install Ollama, then <code>ollama pull {e.local.model}</code>.</p>
    </section>
  );
}

export default function Platform({ onEngine }: { onEngine?: () => void }) {
  const [cat, setCat] = useState<Iface[]>([]);
  const [msgs, setMsgs] = useState<OutMsg[]>([]);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [capNote, setCapNote] = useState<string | null>(null);
  const last = useRef(0);
  useEffect(() => { api.catalogue().then((c) => setCat(c.interfaces)).catch(() => {}); }, []);
  useEffect(() => {
    let live = true;
    const tick = () => api.outbox(0).then((r) => { if (!live) return; setMsgs(r.messages); setTotal(r.total); last.current = r.total; }).catch(() => {});
    tick(); const h = setInterval(tick, 2000);
    return () => { live = false; clearInterval(h); };
  }, []);
  const ins = cat.filter((c) => c.dir === "in"), outs = cat.filter((c) => c.dir === "out");
  return (
    <div className="evidence platform">
      <section className="panel">
        <h2>OpenHand 112 as digital public infrastructure</h2>
        <p>A shared building block for Chandigarh's emergency services, not another standalone app. Existing systems send it calls and camera frames; it sends back
          decisions, dispatch orders, green-corridor windows, hospital pre-alerts and public alerts, each in an open format any agency can read.</p>
        <div className="arch" aria-label="How systems connect">
          <div className="col"><h3>Comes in</h3>{ins.map((c) => <div key={c.system} className="box in"><b>{c.system}</b><small>{c.owner}</small></div>)}</div>
          <div className="col core"><div className="box core"><b>OpenHand 112</b><small>Gemini (cloud) or Gemma (on-premise) reads calls and frames · rules set priority · routing, forecast and watch · open API</small></div></div>
          <div className="col"><h3>Goes out</h3>{outs.map((c) => <div key={c.system} className="box out"><b>{c.system}</b><small>{c.owner}</small></div>)}</div>
        </div>
      </section>

      <EnginePanel onEngine={onEngine} />

      <section className="panel">
        <h2>Message log <span className="count num">{total}</span></h2>
        <p className="hint">Every message the system exchanges with another agency, with the standard and the exact payload. In this prototype nothing leaves your computer:
          each one is <b>simulated</b>. Triage a call, dispatch, alert traffic or check a camera on the Live tab and it appears here.</p>
        <div className="row">
          <button className="btn secondary" onClick={() => api.capSend().then((m) => { setCapNote(null); setOpen(m.id); }).catch((e) => setCapNote((e as Error).message))}>
            Send waterlogging alert to SACHET (CAP, exercise)</button>
          <a className="btn secondary" href="/api/dpi/cap/flood.xml" target="_blank" rel="noreferrer">View CAP XML</a>
        </div>
        {capNote && <p className="err">{capNote}</p>}
        {msgs.length === 0 ? <p className="hint">No messages yet.</p> : (
          <table className="t small msgs">
            <thead><tr><th>Time</th><th></th><th>With</th><th>Message</th><th>Standard</th></tr></thead>
            <tbody>{msgs.map((m) => (
              <Fragment key={m.id}>
                <tr className={open === m.id ? "on" : ""} onClick={() => setOpen(open === m.id ? null : m.id)} style={{ cursor: "pointer" }}>
                  <td className="num">{m.at.slice(11, 19)}</td><td><span className={`dir ${m.direction}`}>{m.direction === "in" ? "IN" : "OUT"}</span></td>
                  <td>{m.party}</td><td><b>{m.what}</b><br /><small className="muted">{m.summary}</small></td><td><small>{m.standard}</small></td>
                </tr>
                {open === m.id && <tr className="payload"><td colSpan={5}><pre>{m.format === "xml" ? String(m.payload) : JSON.stringify(m.payload, null, 2)}</pre></td></tr>}
              </Fragment>))}</tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>Interfaces</h2>
        <table className="t small">
          <thead><tr><th></th><th>System</th><th>Other side</th><th>Format</th><th>Endpoint</th><th>Today</th><th>To go live</th></tr></thead>
          <tbody>{cat.map((c) => (
            <tr key={c.system}><td><span className={`dir ${c.dir}`}>{c.dir === "in" ? "IN" : "OUT"}</span></td><td><b>{c.system}</b></td><td>{c.owner}</td><td>{c.format}</td>
              <td><code>{c.endpoint}</code></td><td>{c.status}</td><td><small>{c.live}</small></td></tr>))}</tbody>
        </table>
        <div className="row" style={{ marginTop: 10 }}>
          <a className="btn" href="/docs" target="_blank" rel="noreferrer">API reference (OpenAPI)</a>
          <a className="btn secondary" href="/api/open/incidents.geojson" target="_blank" rel="noreferrer">Open data: GeoJSON</a>
          <a className="btn secondary" href="/api/open/incidents.csv">Open data: CSV</a>
        </div>
      </section>

      <section className="panel">
        <h2>Design principles</h2>
        <dl className="principles">{PRINCIPLES.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
      </section>
    </div>
  );
}
