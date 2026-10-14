import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ai, api } from "./api";
import MapView, { Layers } from "./MapView";
import { CallPanel, CameraAlert, IncidentCard, Queue } from "./Live";
import Evidence from "./Evidence";
import { PlanPanel, RainPanel } from "./Monsoon";
import { OutlookPanel, WatchPanel } from "./Predict";
import Cities from "./Cities";
import Platform from "./Platform";
import { play, setSound, soundOn, unlockAudio } from "./sound";
import type { Conditions, FloodPlan, Health, Incident, Meta, Outlook, Sample, State, Watch } from "./types";

interface Note { id: number; kind: "info" | "success" | "warn"; title: string; body?: string; inc?: string }

// which sound and banner each timeline event gets (only events that happen while the app is open)
const CUE: Record<string, { cue: Parameters<typeof play>[0]; rank: number }> = {
  resolved: { cue: "resolved", rank: 5 }, arrive: { cue: "arrive", rank: 4 }, dispatch: { cue: "dispatch", rank: 3 },
  traffic: { cue: "traffic", rank: 2 }, call: { cue: "call", rank: 1 },
};

export default function App() {
  const [tab, setTab] = useState<"live" | "predict" | "rain" | "platform" | "india" | "evidence">("live");
  const [outlook, setOutlook] = useState<Outlook | null>(null);
  const [watch, setWatch] = useState<Watch | null>(null);
  const seenAlerts = useRef<Set<string> | null>(null);
  const [plan, setPlan] = useState<FloodPlan | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const aiOn = health?.triage === "gemini" || health?.triage === "local";
  ai.name = health?.ai_name ?? "Gemini"; ai.local = health?.triage === "local";
  const refreshHealth = () => api.health().then(setHealth).catch(() => {});
  const [meta, setMeta] = useState<Meta | null>(null);
  const [state, setState] = useState<State | null>(null);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [closing, setClosing] = useState(false);   // "close a road" click mode
  const [layers, setLayers] = useState<Layers>({ stations: true, risk: false, standby: false, hotspots: true, cctv: false });
  const [risk, setRisk] = useState<{ lat: number; lng: number; level: number }[]>([]);
  const [standby, setStandby] = useState<{ lat: number; lng: number }[]>([]);
  const [offline, setOffline] = useState(false);
  const [notes, setNotes] = useState<Note[]>([]);
  const [sound, setSoundState] = useState(soundOn());
  const seen = useRef<Set<string> | null>(null);
  const noteId = useRef(1);

  const notify = useCallback((n: Omit<Note, "id">) => {
    const id = noteId.current++;
    setNotes((xs) => [...xs.slice(-2), { ...n, id }]);
    setTimeout(() => setNotes((xs) => xs.filter((x) => x.id !== id)), 6000);
  }, []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setOffline(true));
    api.meta().then(setMeta).catch(() => setOffline(true));
    api.samples().then(setSamples).catch(() => {});
    api.floodPlan().then((p) => setPlan(p.active ? (p as FloodPlan) : null)).catch(() => {});
    const unlock = () => unlockAudio();
    window.addEventListener("pointerdown", unlock);
    window.addEventListener("keydown", unlock);
    return () => { window.removeEventListener("pointerdown", unlock); window.removeEventListener("keydown", unlock); };
  }, []);

  // Watch the incident timelines: every new event gets a sound and, for arrivals and closures, a banner.
  const ingest = useCallback((s: State) => {
    const keys = (i: Incident) => i.events.map((e, k) => `${i.id}:${k}:${e.kind}`);
    if (seen.current === null) { seen.current = new Set(s.incidents.flatMap(keys)); return; }
    let best: { cue: Parameters<typeof play>[0]; rank: number } | null = null;
    for (const inc of s.incidents) {
      inc.events.forEach((e, k) => {
        const key = `${inc.id}:${k}:${e.kind}`;
        if (seen.current!.has(key)) return;
        seen.current!.add(key);
        let c = CUE[e.kind];
        if (e.kind === "call" && k === 0 && inc.triage.decision.priority === "P1") c = { cue: "callP1", rank: 6 };
        if (c && (!best || c.rank > best.rank)) best = c;
        if (e.kind === "arrive") notify({ kind: "info", title: `On scene at ${inc.id}`, body: e.text, inc: inc.id });
        if (e.kind === "resolved") {
          const o = inc.outcome;
          notify({ kind: "success", title: `${inc.id} closed`, inc: inc.id,
            body: o?.first_on_scene_s != null ? `First unit on scene: response ${fmt(o.first_on_scene_s)}${o.all_targets_met ? ", every unit within target" : ""}.` : e.text });
        }
      });
    }
    if (best) play((best as { cue: Parameters<typeof play>[0] }).cue);
  }, [notify]);

  useEffect(() => {
    let live = true;
    const tick = () => api.state().then((s) => { if (live) { ingest(s); setState(s); setOffline(false); } }).catch(() => live && setOffline(true));
    tick(); const h = setInterval(tick, 1000);
    return () => { live = false; clearInterval(h); };
  }, [ingest]);
  useEffect(() => { if (layers.risk && risk.length === 0) api.risk("crash").then((r) => setRisk(r.cells)).catch(() => {}); }, [layers.risk]);
  useEffect(() => { if (layers.standby && standby.length === 0) api.standby().then((r) => setStandby(r.points)).catch(() => {}); }, [layers.standby]);

  // live watch: polled on every tab so a new alert shows up wherever the presenter is
  useEffect(() => {
    let live = true;
    const tick = () => api.watch().then((w) => {
      if (!live) return;
      setWatch(w);
      const ids = new Set(w.alerts.map((a) => a.id));
      if (seenAlerts.current === null) { seenAlerts.current = ids; return; }
      const fresh = w.alerts.filter((a) => !seenAlerts.current!.has(a.id) && a.kind !== "prepare");
      fresh.slice(0, 1).forEach((a) => { notify({ kind: "warn", title: `Watch: ${a.title}`, body: a.todo }); play("traffic"); });
      ids.forEach((i) => seenAlerts.current!.add(i));
    }).catch(() => {});
    tick(); const h = setInterval(tick, 3000);
    return () => { live = false; clearInterval(h); };
  }, [notify]);
  useEffect(() => {
    if (tab !== "predict") return;
    let live = true;
    const get = () => api.outlook().then((o) => live && setOutlook(o)).catch(() => {});
    get(); const h = setInterval(get, 30000);
    if (risk.length === 0) api.risk("crash").then((r) => setRisk(r.cells)).catch(() => {});
    if (standby.length === 0) api.standby().then((r) => setStandby(r.points)).catch(() => {});
    return () => { live = false; clearInterval(h); };
  }, [tab, state?.conditions?.fog, state?.conditions?.night, !!state?.conditions?.flood]);

  const selected = useMemo(() => state?.incidents.find((i) => i.id === sel) ?? null, [state, sel]);
  // a new incident with no place: the map is ready for a click straight away
  const needsPlace = !!selected && selected.status === "new" && !selected.triage.location.resolved;
  const pickOn = picking || needsPlace;
  const applyConditions = (c: Conditions) => setState((s) => (s ? { ...s, conditions: c } : s));
  const onChanged = useCallback((i: Incident) => {
    setState((s) => s ? { ...s, incidents: s.incidents.map((x) => (x.id === i.id ? i : x)) } : s);
  }, []);
  const onCreated = (i: Incident, merged: boolean) => {
    setSel(i.id);
    setState((s) => s ? { ...s, incidents: [i, ...s.incidents.filter((x) => x.id !== i.id)] } : s);
    if (merged) notify({ kind: "warn", title: `Another call about ${i.id}`, body: `Now ${i.calls} calls: priority ${i.triage.decision.priority}.`, inc: i.id });
  };
  const onPick = async (lat: number, lng: number) => {
    if (closing) {
      setClosing(false);
      try { applyConditions(await api.closeRoad(lat, lng)); notify({ kind: "warn", title: "Road closed", body: "Routes and arrival times now go around it." }); play("traffic"); }
      catch (e) { notify({ kind: "warn", title: (e as Error).message }); }
      return;
    }
    if (!sel) return; setPicking(false);
    try { onChanged(await api.setLocation(sel, lat, lng)); } catch (e) { notify({ kind: "warn", title: (e as Error).message }); play("error"); }
  };
  const free = state?.free;
  const active = state?.incidents.filter((i) => i.status !== "resolved").length ?? 0;

  return (
    <div className="app">
      <a className="skip" href="#main">Skip to main content</a>
      <header className="top">
        <div className="top-in">
          <div className="mark" aria-label="OpenHand 112"><span>OpenHand</span><b>112</b></div>
          <span className="sub">Emergency response, Chandigarh</span>
          <nav className="tabs" aria-label="Sections">
            <button className="tab" aria-current={tab === "live" ? "page" : undefined} onClick={() => setTab("live")}>Live dispatch</button>
            <button className="tab" aria-current={tab === "predict" ? "page" : undefined} onClick={() => setTab("predict")}>Predict and monitor</button>
            <button className="tab" aria-current={tab === "rain" ? "page" : undefined} onClick={() => setTab("rain")}>Rain and waterlogging</button>
            <button className="tab" aria-current={tab === "platform" ? "page" : undefined} onClick={() => setTab("platform")}>Open platform</button>
            <button className="tab" aria-current={tab === "india" ? "page" : undefined} onClick={() => setTab("india")}>Across India</button>
            <button className="tab" aria-current={tab === "evidence" ? "page" : undefined} onClick={() => setTab("evidence")}>Evidence</button>
          </nav>
          <button className="sound" aria-pressed={sound} onClick={() => { setSound(!sound); setSoundState(!sound); }} title="Sound cues for calls, dispatches, arrivals and closures">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z" fill="currentColor" />
              {sound ? <path d="M16 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />
                : <path d="M16 9l5 6M21 9l-5 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />}</svg>
            Sound {sound ? "on" : "off"}
          </button>
        </div>
      </header>
      <div className="phase">
        <strong className="tag tag-blue">Prototype</strong>
        <span>Hackathon prototype on test calls and simulated units. Not an official Chandigarh Administration service.</span>
      </div>
      <div className="statusbar" role="status">
        {offline ? <span className="off">Server not reachable. Is <code>run_app.py</code> running?</span> : (
          <>
            <span title={health?.model ?? ""}><i className="dot" style={{ background: aiOn ? "var(--green)" : "var(--orange)" }} />
              {health?.triage === "gemini" ? <>Calls read by <b>Gemini</b> ({health.model})</> : health?.triage === "local"
                ? <>Calls read by <b>Gemma on this computer</b> ({health.model}) · sovereign mode</> : "Calls read by keyword fallback"}</span>
            <span className="num"><b>{active}</b> open incident{active === 1 ? "" : "s"}</span>
            {free && <span className="free num">Free now: <b>{free.police}</b> PCR · <b>{free.ambulance}</b> ambulance · <b>{free.fire}</b> fire tender</span>}
            {watch && watch.alerts.length > 0 && <button className={`watchpill ${watch.alerts.some((a) => a.level === "high") ? "high" : ""}`} onClick={() => setTab("predict")}>
              Watch: <b className="num">{watch.alerts.length}</b> alert{watch.alerts.length === 1 ? "" : "s"}</button>}
            {state?.conditions?.flood && <button className="rainpill" onClick={() => setTab("rain")} title={state.conditions.flood.label}>
              Rain plan {state.conditions.flood.at}: <b className="num">{state.conditions.flood.closed}</b> closed · <b className="num">{state.conditions.flood.diverted}</b> diverted</button>}
            {state && <span className="num muted" title="The demo clock runs faster than real time so drives finish on stage">Demo clock ×{state.demo_speed}</span>}
          </>
        )}
      </div>

      {tab === "evidence" ? <main id="main" className="evwrap"><Evidence /></main> : tab === "platform" ? <main id="main" className="evwrap"><Platform onEngine={refreshHealth} /></main> : tab === "india" ? <main id="main" className="evwrap"><Cities /></main> : tab === "predict" ? (
        <main id="main" className="live predict">
          <aside className="rail left"><OutlookPanel o={outlook} /></aside>
          <section className="mapwrap" aria-label="Map of forecast and alerts">
            <MapView meta={meta} state={state} selected={null} layers={{ ...layers, risk: true, standby: true, cctv: false, hotspots: true }} risk={risk} standby={standby}
                     picking={false} onPick={() => {}} onSelect={(id) => { setSel(id); setTab("live"); }} watch={watch} zones={outlook?.zones} />
            <div className="notes" aria-live="polite">
              {notes.map((n) => (<div key={n.id} className={`banner ${n.kind}`}><div className="banner-title">{n.title}</div>{n.body && <div className="banner-body">{n.body}</div>}</div>))}
            </div>
            <div className="layers fkey" aria-label="Key">
              <strong>Predict and monitor</strong>
              <span><i className="lv zone" />Likely next hour (1 = most)</span><span><i className="lv risk" />Crash risk (model)</span>
              <span><i className="lv standby" />Standby point</span><span><i className="ln clus" />Unusual cluster</span><span><i className="ln mv" />Suggested move</span>
            </div>
          </section>
          <aside className="rail right"><WatchPanel w={watch} onDone={(t, b) => { notify({ kind: "success", title: t, body: b }); play("dispatch"); }}
                                                  onError={(m) => { notify({ kind: "warn", title: m }); play("error"); }} /></aside>
        </main>
      ) : tab === "rain" ? (
        <main id="main" className="live rain">
          <aside className="rail left"><RainPanel plan={plan} setPlan={setPlan} onError={(m) => { notify({ kind: "warn", title: m }); play("error"); }} /></aside>
          <section className="mapwrap" aria-label="Map of flood spots">
            <MapView meta={meta} state={state} selected={null} layers={{ ...layers, risk: false, standby: false, cctv: false, hotspots: false }} risk={[]} standby={[]}
                     picking={false} onPick={() => {}} onSelect={(id) => { setSel(id); setTab("live"); }} flood={plan} />
            <div className="notes" aria-live="polite">
              {notes.map((n) => (<div key={n.id} className={`banner ${n.kind}`}><div className="banner-title">{n.title}</div>{n.body && <div className="banner-body">{n.body}</div>}</div>))}
            </div>
            <div className="layers fkey" aria-label="Key">
              <strong>Water at flood spots</strong>
              <span><i className="lv watch" />Watch 5+ cm</span><span><i className="lv divert" />Divert 15+ cm</span><span><i className="lv close" />Closed 30+ cm</span>
              <span><i className="ln closed" />Closed road</span><span><i className="ln div" />Diversion</span><span><i className="lv bar" />Barricade post</span>
            </div>
          </section>
          <aside className="rail right"><PlanPanel plan={plan} gemini={aiOn} /></aside>
        </main>
      ) : (
        <main id="main" className="live">
          <aside className="rail left">
            <CallPanel samples={samples} onCreated={onCreated} triageMode={health?.triage ?? "keyword_baseline"} meta={meta} />
            <CameraAlert meta={meta} gemini={aiOn} onCreated={onCreated} onInfo={(t) => notify({ kind: "info", title: t })} />
            <Queue state={state} selectedId={sel} onSelect={setSel} />
          </aside>
          <section className="mapwrap" aria-label="Map">
            <MapView meta={meta} state={state} selected={selected} layers={layers} risk={risk} standby={standby}
                     picking={pickOn || closing} onPick={onPick} onSelect={setSel} />
            {closing && <div className="pickbar closebar" role="status">Click the road to close (flooded underpass, VIP movement, protest)<button onClick={() => setClosing(false)}>Cancel</button></div>}
            {!closing && pickOn && selected && <div className="pickbar" role="status">
              Click on the map where {selected.id} is{selected.triage.location.road ? ` (${selected.triage.location.road} is highlighted)` : ""}
              {picking && !needsPlace && <button onClick={() => setPicking(false)}>Cancel</button>}</div>}
            <div className="notes" aria-live="polite">
              {notes.map((n) => (
                <div key={n.id} className={`banner ${n.kind}`} onClick={() => n.inc && setSel(n.inc)} role={n.inc ? "button" : undefined}>
                  <div className="banner-title">{n.title}</div>
                  {n.body && <div className="banner-body">{n.body}</div>}
                </div>
              ))}
            </div>
            {state?.conditions && (
              <fieldset className="whatif">
                <legend>What if</legend>
                <label><input type="checkbox" checked={state.conditions.fog} onChange={(e) => api.conditions({ fog: e.target.checked }).then((c) => { applyConditions(c); notify({ kind: "warn", title: e.target.checked ? "Winter fog on" : "Fog cleared", body: e.target.checked ? `Every drive now takes ${state.conditions.fog_slowdown}× as long.` : undefined }); })} />Winter fog (drives {state.conditions.fog_slowdown}× slower)</label>
                <label><input type="checkbox" checked={state.conditions.night} onChange={(e) => api.conditions({ night: e.target.checked }).then((c) => { applyConditions(c); notify({ kind: "warn", title: e.target.checked ? "Night shift" : "Day shift", body: `${c.pcr_on_duty} PCR vans on duty.` }); })} />Night shift ({state.conditions.night ? state.conditions.pcr_on_duty : 20} PCR on duty)</label>
                <div className="row" style={{ marginTop: 4 }}>
                  <button type="button" className="btn secondary" onClick={() => setClosing(true)} disabled={closing}>Close a road</button>
                  {state.conditions.closures.length > 0 && <button type="button" className="btn secondary" onClick={() => api.reopenRoads().then((c) => { applyConditions(c); notify({ kind: "info", title: "All roads reopened" }); })}>Reopen {state.conditions.closures.length}</button>}
                </div>
              </fieldset>
            )}
            <fieldset className="layers">
              <legend>Map layers</legend>
              {([["stations", "Stations and hospitals"], ["hotspots", "Black spots and fire-risk sites"], ["risk", "Crash risk this hour (model)"], ["standby", "Suggested PCR standby points"], ["cctv", `CCTV cameras (${meta?.cameras?.length ?? 0}, simulated positions)`]] as const).map(([k, l]) => (
                <label key={k}><input type="checkbox" checked={layers[k]} onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })} />{l}</label>
              ))}
              <div className="key">
                <span><i className="u-key police" />PCR</span><span><i className="u-key ambulance" />Ambulance</span><span><i className="u-key fire" />Fire</span>
              </div>
            </fieldset>
          </section>
          <aside className="rail right">
            <IncidentCard inc={selected} state={state} meta={meta} gemini={aiOn} onChanged={onChanged} onPick={() => setPicking(true)} picking={pickOn}
                          onError={(m) => { notify({ kind: "warn", title: m }); play("error"); }} />
          </aside>
        </main>
      )}
    </div>
  );
}

function fmt(s: number) { return `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`; }
