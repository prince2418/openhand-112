import { useEffect, useRef, useState } from "react";
import { ai, api } from "./api";
import type { Alert, Incident, Meta, Sample, State, Unit } from "./types";
import { KIND_NAME, LANG, TYPE_LABEL, mmss } from "./format";
import { LANGS, VoiceSession, alertHit, speechSupported, startVoice } from "./voice";

/* ---------------- new call ---------------- */
export function CallPanel({ samples, onCreated, triageMode, meta }: { samples: Sample[]; onCreated: (i: Incident, merged: boolean) => void; triageMode: string; meta: Meta | null }) {
  const [text, setText] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [audio, setAudio] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [secs, setSecs] = useState(0);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [lang, setLang] = useState(() => { try { return localStorage.getItem("oh-lang") || "hi-IN"; } catch { return "hi-IN"; } });
  const [alertMsg, setAlertMsg] = useState<string | null>(null);
  const [converting, setConverting] = useState(false);
  const session = useRef<VoiceSession | null>(null);
  const textRef = useRef("");
  const interimRef = useRef("");
  const fired = useRef(false);
  useEffect(() => { if (!busy) return; setSecs(0); const t0 = Date.now(); const h = setInterval(() => setSecs(Math.floor((Date.now() - t0) / 1000)), 250); return () => clearInterval(h); }, [busy]);
  const imgRef = useRef<HTMLInputElement>(null), audRef = useRef<HTMLInputElement>(null);
  const gemini = triageMode === "gemini" || triageMode === "local";
  const cloud = triageMode === "gemini";   // voice clips: cloud Gemini only (local Gemma reads text and photos)
  const live = speechSupported();

  async function send(t: string, aud: File | null) {
    setBusy(true); setErr(null);
    const fd = new FormData();
    fd.append("transcript", t);
    if (image) fd.append("image", image);
    if (aud) fd.append("audio", aud);
    try {
      const r = await api.call(fd);
      onCreated(r.incident, r.merged);
      setText(""); textRef.current = ""; setImage(null); setAudio(null); setInterim("");
      if (imgRef.current) imgRef.current.value = ""; if (audRef.current) audRef.current.value = "";
    } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  }
  function submit(e: React.FormEvent) { e.preventDefault(); void send(text, audio); }

  async function stopAndSend() {
    const s = session.current; session.current = null; setListening(false);
    const t = (textRef.current + " " + interimRef.current).trim();
    interimRef.current = ""; setInterim("");
    // We have the words: send them straight away (fast, nothing heavy in the browser).
    // No words (browser can't transcribe): send the recording, which only Gemini can read.
    if (t) { s?.stop(false); void send(t, null); return; }
    if (!cloud) { s?.stop(false); setErr("No words were picked up, and recordings need cloud Gemini. Type what the caller said, or try Chrome."); return; }
    setConverting(true);
    const file = s ? await s.stop(true) : null;
    setConverting(false);
    if (file) void send("", file); else setErr("The recording was empty. Try again, closer to the microphone.");
  }

  async function startListening() {
    setErr(null); setAlertMsg(null); fired.current = false;
    setText(""); textRef.current = ""; setInterim("");
    try {
      session.current = await startVoice(lang, (fin, inter) => {
        textRef.current = fin; interimRef.current = inter; setText(fin); setInterim(inter);
        const hit = alertHit(`${fin} ${inter}`, meta?.alert_words);
        if (hit && !fired.current) {   // sexual violence words: don't wait for the caller to finish
          fired.current = true;
          setAlertMsg(`"${hit}" heard: call sent at once so police can go now.`);
          textRef.current = `${fin} ${inter}`.trim(); interimRef.current = "";
          void stopAndSend();
        }
      });
      setListening(true);
    } catch (x) {
      setErr(`Microphone not available: ${(x as Error).message}. Allow microphone access for this page and try again.`);
    }
  }

  return (
    <form className="section" onSubmit={submit} aria-labelledby="newcall">
      <h2 id="newcall">New 112 call</h2>
      <div className={`voice ${listening ? "on" : ""}`}>
        <button type="button" className="mic" onClick={() => (listening ? stopAndSend() : startListening())} disabled={busy}
                aria-pressed={listening} title={listening ? "Stop and send the call" : "Speak the call into the microphone"}>
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
            {listening ? <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />
              : <><rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" /></>}
          </svg>
        </button>
        <div className="voice-txt">
          <b>{listening ? "Listening… press again to send" : converting ? "Preparing the recording…" : "Speak the call"}</b>
          <span>{listening ? (live ? "Words appear below as they are said" : "Recording (this browser can't show words live; Gemini will listen)")
            : live ? "Microphone, with live words" : "Microphone (recording only in this browser)"}</span>
        </div>
        <select aria-label="Language the caller speaks" value={lang} disabled={listening}
                onChange={(e) => { setLang(e.target.value); try { localStorage.setItem("oh-lang", e.target.value); } catch { /* ignore */ } }}>
          {LANGS.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
        </select>
        {listening && <span className="wave" aria-hidden="true"><i /><i /><i /><i /><i /></span>}
      </div>
      {alertMsg && <p className="alertline" role="alert">{alertMsg}</p>}
      <label className="hint" htmlFor="sample" style={{ display: "block", marginTop: 12 }}>Or load a sample call</label>
      <select id="sample" value="" onChange={(e) => { const s = samples.find((x) => x.id === e.target.value); if (s) setText(s.transcript); }}>
        <option value="">Choose one of {samples.length} test calls (11 languages)…</option>
        {samples.map((s) => <option key={s.id} value={s.id}>{LANG[s.lang] ?? s.lang}: {s.transcript.slice(0, 60)}</option>)}
      </select>
      <label className="hint" htmlFor="tx" style={{ display: "block", marginTop: 10 }}>What the caller said (any language)</label>
      <textarea id="tx" value={listening && interim ? `${text} ${interim}`.trim() : text} readOnly={listening}
                onChange={(e) => { setText(e.target.value); textRef.current = e.target.value; }} placeholder="e.g. Tribune Chowk pe accident, ek aadmi behosh hai" />
      <div className="row">
        <label className={`file ${image ? "has" : ""}`} title={gemini ? "" : "Needs a Gemini key"}>
          <input ref={imgRef} type="file" accept="image/*" disabled={!gemini} onChange={(e) => setImage(e.target.files?.[0] ?? null)} />
          {image ? `Photo: ${image.name.slice(0, 18)}` : "Add photo"}
        </label>
        <label className={`file ${audio ? "has" : ""}`} title={cloud ? "" : "Voice clips need cloud Gemini"}>
          <input ref={audRef} type="file" accept="audio/*" disabled={!cloud} onChange={(e) => setAudio(e.target.files?.[0] ?? null)} />
          {audio ? `Audio: ${audio.name.slice(0, 18)}` : "Add audio file"}
        </label>
      </div>
      <div className="row"><button className="btn wide" disabled={busy || listening || (!text.trim() && !image && !audio)}>{busy ? <><span className="spin" aria-hidden="true" />Reading the call… {secs}s</> : "Triage call"}</button></div>
      {err && <p className="err" role="alert">{err}</p>}
      {!gemini && <p className="hint">No Gemini key found, so calls are read by the keyword fallback. Photos and audio need Gemini.</p>}
    </form>
  );
}

/* ---------------- camera alert (ICCC) ---------------- */
export function CameraAlert({ meta, gemini, onCreated, onInfo }: { meta: Meta | null; gemini: boolean; onCreated: (i: Incident, merged: boolean) => void; onInfo: (t: string) => void }) {
  const [cam, setCam] = useState("");
  const [img, setImg] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement>(null);
  async function send() {
    if (!cam || !img) return;
    setBusy(true); setErr(null);
    const fd = new FormData(); fd.append("camera_id", cam); fd.append("image", img);
    try {
      const r = await api.cctvAlert(fd);
      if (r.incident) { onCreated(r.incident, false); if (r.message) onInfo(r.message); } else onInfo(r.message ?? "Nothing found");
      setImg(null); if (ref.current) ref.current.value = "";
    } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  }
  return (
    <details className="section camalert">
      <summary><b>Camera alert</b> <span className="hint">a CCTV frame opens an incident, no caller needed</span></summary>
      {!gemini && <p className="hint">Needs a Gemini key: Gemini reads the frame.</p>}
      <select aria-label="Camera" value={cam} onChange={(e) => setCam(e.target.value)} style={{ marginTop: 8 }}>
        <option value="">Choose a camera…</option>
        {(meta?.cameras ?? []).map((c) => <option key={c.id} value={c.id}>{c.id}: {c.road}</option>)}
      </select>
      <div className="row">
        <label className={`file ${img ? "has" : ""}`}><input ref={ref} type="file" accept="image/*" disabled={!gemini} onChange={(e) => setImg(e.target.files?.[0] ?? null)} />{img ? `Frame: ${img.name.slice(0, 20)}` : "Add camera frame"}</label>
        <button type="button" className="btn" disabled={!gemini || busy || !cam || !img} onClick={send}>{busy ? "Reading frame…" : "Send alert"}</button>
      </div>
      {err && <p className="err" role="alert">{err}</p>}
      <p className="hint">Positions are simulated: Chandigarh's ICCC watches about 285 locations, but the list is not public. Frames are not stored; only what the AI saw is kept.</p>
    </details>
  );
}

/* ---------------- CCTV on an incident ---------------- */
const VERDICT: Record<string, [string, string]> = { yes: ["Confirms the call", "v-ok"], no: ["Does not show it", "v-bad"], unclear: ["Unclear", "v-meh"] };
function CCTVSection({ inc, gemini, onChanged, onError }: { inc: Incident; gemini: boolean; onChanged: (i: Incident) => void; onError: (m: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!inc.cameras?.length && !inc.cctv?.length) return null;
  async function check(cam: string, f: File) {
    setBusy(cam);
    const fd = new FormData(); fd.append("camera_id", cam); fd.append("image", f);
    try { onChanged(await api.cctvCheck(inc.id, fd)); } catch (e) { onError((e as Error).message); } finally { setBusy(null); }
  }
  return (
    <div className="section">
      <h2>CCTV</h2>
      {inc.cameras?.length > 0 && <>
        <p className="hint" style={{ marginTop: 0 }}>Nearest cameras (simulated positions). Pull a frame from the ICCC feed and {ai.name} checks it against the call.</p>
        <ul className="cams">{inc.cameras.map((c) => (
          <li key={c.id}>
            <span><b>{c.id}</b> {c.road}, {c.m} m away</span>
            <label className={`file small ${!gemini || busy ? "off" : ""}`} title={gemini ? "Upload the camera frame" : "Needs a Gemini key"}>
              <input type="file" accept="image/*" disabled={!gemini || !!busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) void check(c.id, f); e.target.value = ""; }} />
              {busy === c.id ? "Checking…" : "Check frame"}
            </label>
          </li>))}</ul>
      </>}
      {inc.cctv?.map((r, k) => { const [label, cls] = VERDICT[r.check.shows_incident]; const c = r.check;
        const flags = [c.injured_visible && "injured person", c.fire_or_smoke && "fire or smoke", c.weapon_visible && "weapon", c.violence_visible && "violence",
          c.crowd_building && "crowd building", c.road_blocked && "road blocked", c.looks_stale_or_unrelated && "looks old or unrelated",
          c.people_visible != null && `${c.people_visible} people`, c.vehicles_involved != null && `${c.vehicles_involved} vehicles`].filter(Boolean) as string[];
        return (
          <div key={k} className={`cctv ${cls}`}>
            <div className="cctv-h"><b>{r.camera}</b> <span className={`tag ${cls === "v-ok" ? "tag-green" : cls === "v-bad" ? "tag-red" : "tag-orange"}`}>{label}</span></div>
            <p>{c.what_is_seen}</p>
            {flags.length > 0 && <div className="facts">{flags.map((f) => <span key={f} className={`fact ${/injured|fire|weapon|violence|crowd/.test(f) ? "hot" : ""}`}>{f}</span>)}</div>}
            {r.notes.length > 0 && <ul className="plain">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
            <p className="note">Read by {r.model} in {r.latency_s}s, confidence {Math.round(c.confidence * 100)}%. CCTV can raise urgency, never lower it.</p>
          </div>);
      })}
    </div>
  );
}

/* ---------------- queue ---------------- */
export function Queue({ state, selectedId, onSelect }: { state: State | null; selectedId: string | null; onSelect: (id: string) => void }) {
  const incs = state?.incidents ?? [];
  const order = { P1: 0, P2: 1, P3: 2, P4: 3 } as const;
  const sorted = [...incs].sort((a, b) => (a.status === "resolved" ? 1 : 0) - (b.status === "resolved" ? 1 : 0)
    || order[a.triage.decision.priority] - order[b.triage.decision.priority] || b.t - a.t);
  return (
    <div>
      <div className="section" style={{ borderBottom: 0, paddingBottom: 4 }}><h2>Incidents</h2></div>
      {sorted.length === 0 ? <p className="empty">No calls yet. Triage a call to start.</p> : (
        <ul className="queue">
          {sorted.map((i) => {
            const d = i.triage.decision;
            return (
              <li key={i.id} className={`qi ${i.status}`} aria-current={i.id === selectedId} onClick={() => onSelect(i.id)}
                  onKeyDown={(e) => e.key === "Enter" && onSelect(i.id)} tabIndex={0}>
                <div className={`pchip ${d.priority}`}>{d.priority}</div>
                <div>
                  <div className="t">{TYPE_LABEL[i.triage.extract.incident_type]}{i.calls > 1 ? ` (${i.calls} calls)` : ""}</div>
                  <div className="s">{i.triage.extract.summary_en}</div>
                </div>
                <div className="m num"><StatusTag inc={i} units={state?.units} /><br />{mmss(i.age_s)} ago</div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* ---------------- status ---------------- */
function phase(inc: Incident, units?: Unit[]): { label: string; cls: string } {
  if (inc.status === "resolved") return { label: "Closed", cls: "tag-green" };
  if (inc.status === "new") return inc.triage.decision.needs_human_review ? { label: "Check", cls: "tag-orange" } : { label: "Waiting", cls: "tag-red" };
  const mine = (units ?? []).filter((u) => inc.units.includes(u.id) && u.incident === inc.id);
  if (mine.some((u) => u.status === "on_scene")) return { label: "On scene", cls: "tag-purple" };
  return { label: "On the way", cls: "tag-blue" };
}
export function StatusTag({ inc, units }: { inc: Incident; units?: Unit[] }) {
  const p = phase(inc, units);
  return <strong className={`tag ${p.cls}`}>{p.label}</strong>;
}

/* ---------------- outcome + timeline ---------------- */
function OutcomePanel({ inc }: { inc: Incident }) {
  const o = inc.outcome;
  if (!o) return null;
  return (
    <div className="panel-done" role="status">
      <h2>Incident closed</h2>
      {o.first_on_scene_s != null ? (
        <div className="big num">{mmss(o.first_on_scene_s)}<span>first unit on scene (call handling + drive)</span></div>
      ) : <div className="big-sub">No unit needed: caller referred to the right service.</div>}
      {o.target_s != null && o.first_on_scene_s != null && (
        <div className="big-sub">{o.all_targets_met ? "Every unit arrived within its target" : "Not every unit met its target"} (target {mmss(o.target_s)})</div>
      )}
    </div>
  );
}
function OutcomeList({ inc, units }: { inc: Incident; units: Map<string, Unit> }) {
  const o = inc.outcome;
  if (!o) return null;
  const rows: [string, React.ReactNode][] = [];
  Object.entries(o.per_unit_s).forEach(([uid, s]) => rows.push([`${uid} (${KIND_NAME[units.get(uid)?.kind ?? ""] ?? "unit"})`,
    <span className="num">{mmss(s)} {o.targets_met[uid] ? <span className="ok">within target</span> : <span className="late">over target</span>}</span>]));
  if (o.saved_vs_nearest_s > 0) rows.push(["Saved vs nearest on the map", <span className="num ok">{mmss(o.saved_vs_nearest_s)} faster</span>]);
  if (o.junctions_alerted > 0) rows.push(["Junctions cleared by traffic police", <span className="num">{o.junctions_alerted}</span>]);
  if (o.calls > 1) rows.push(["Calls about this incident", <span className="num">{o.calls}</span>]);
  rows.push(["Call to close (simulated time)", <span className="num">{mmss(o.duration_s)}</span>]);
  rows.push(["Closed by", o.closed_by === "dispatcher" ? "Dispatcher" : "Units cleared the scene"]);
  return <dl className="summary-list">{rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}
function Timeline({ inc }: { inc: Incident }) {
  if (!inc.events?.length) return null;
  return (
    <div className="section">
      <h2>Timeline</h2>
      <ol className="timeline">
        {inc.events.map((e, k) => (
          <li key={k} className={`ev ev-${e.kind}`}>
            <span className="ev-t num">+{mmss(e.at_s)}</span>
            <span className="ev-x">{e.text}</span>
          </li>
        ))}
      </ol>
      <p className="hint">Times count from the call, on the simulated clock.</p>
    </div>
  );
}

/* ---------------- incident card ---------------- */
export function IncidentCard({ inc, state, meta, onChanged, onPick, picking, onError, gemini }: {
  inc: Incident | null; state: State | null; meta: Meta | null; onChanged: (i: Incident) => void; onPick: () => void; picking: boolean; onError: (m: string) => void; gemini?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [alert, setAlert] = useState<Alert | null>(null);
  const top = useRef<HTMLDivElement>(null);
  // when an incident closes (or another is selected), bring the top of the card into view
  useEffect(() => { top.current?.closest(".rail")?.scrollTo({ top: 0, behavior: "smooth" }); }, [inc?.id, inc?.status]);
  if (!inc) return (
    <div className="section">
      <h2>No incident selected</h2>
      <p className="hint">Triage a call on the left, or pick one from the list. The card shows what the call says, why it got its priority, which unit gets there first, and the route to clear.</p>
    </div>
  );
  const x = inc.triage.extract, d = inc.triage.decision, loc = inc.triage.location;
  const facts: [string, boolean][] = [];
  if (x.people_injured != null) facts.push([`${x.people_injured} injured`, x.people_injured > 0]);
  if (x.unconscious_or_not_breathing) facts.push(["unconscious or not breathing", true]);
  if (x.immediate_life_threat) facts.push(["life-threatening", true]);
  if (x.people_trapped) facts.push(["people trapped", true]);
  if (x.violence_ongoing) facts.push(["violence now", true]);
  if (x.fire_or_smoke) facts.push(["fire or smoke", true]);
  x.hazards.forEach((h) => facts.push([`hazard: ${h.replace("_", " ")}`, true]));
  x.vulnerable.forEach((v) => facts.push([v, false]));
  if (x.sector) facts.push([`Sector ${x.sector}`, false]);
  if (x.landmark) facts.push([x.landmark, false]);

  const act = async (f: () => Promise<Incident>) => { setBusy(true); setErr(null); try { onChanged(await f()); } catch (e) { setErr((e as Error).message); onError((e as Error).message); } finally { setBusy(false); } };
  const unitsById = new Map(state?.units.map((u) => [u.id, u]) ?? []);
  const mine = inc.units.map((id) => unitsById.get(id)).filter(Boolean) as Unit[];
  const anyDriving = mine.some((u) => u.status === "en_route" && u.incident === inc.id);
  const demo = state?.demo_speed ?? 10;
  const routeOf = (uid: string) => inc.corridor?.routes.find((r) => r.unit === uid);

  return (
    <div ref={top}>
      {inc.status === "resolved" && <div className="section"><OutcomePanel inc={inc} /><OutcomeList inc={inc} units={unitsById} /></div>}
      <div className="section">
        <div className="card-head">
          <div className={`pblock ${d.priority}`} aria-label={`Priority ${d.priority}`}>{d.priority}</div>
          <div>
            <div className="ctype">{TYPE_LABEL[x.incident_type]}</div>
            <div className="cmeta num"><StatusTag inc={inc} units={state?.units} /> {inc.id}, {mmss(inc.age_s)} ago{inc.calls > 1 ? `, ${inc.calls} calls about this` : ""}</div>
            <div className="cmeta">{loc.resolved ? `Location: ${loc.label}` : "Location not known yet"}</div>
          </div>
        </div>
        <p className="summary">{x.summary_en}</p>
        {inc.transcript && <p className="callq">“{inc.transcript}”</p>}
        {facts.length > 0 && <div className="facts">{facts.map(([f, hot]) => <span key={f} className={`fact ${hot ? "hot" : ""}`}>{f}</span>)}</div>}
        <h3>Why {d.priority}</h3>
        <ul className="plain">{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        {d.needs_human_review && inc.status === "new" && <div className="review"><b>Check before sending:</b> {d.review_reasons.join("; ")}.</div>}
        {x.missing_info.length > 0 && <><h3>Ask the caller</h3><ul className="plain">{x.missing_info.map((q) => <li key={q}>{q}</li>)}</ul></>}
        {inc.fast && <div className="fastbar" role="status"><b>Fast path:</b> sexual violence or harassment words heard (“{inc.fast}”). The nearest PCR was sent at once, without waiting for the AI.</div>}
        {inc.gemini?.state === "trying" && (
          <div className="gem trying" role="status"><span className="spin dark" aria-hidden="true" />
            <div><b>{ai.name} is still reading this call</b> (attempt {inc.gemini.attempt}{inc.gemini.error ? `; last try: ${inc.gemini.error}` : ""}).
              The keyword reading below is provisional and is replaced when {ai.name} answers.</div></div>
        )}
        {inc.gemini?.state === "gave_up" && (
          <div className="gem gave" role="status"><div><b>{ai.name} could not read this call</b> ({inc.gemini.error}). The keyword reading stands: check it with the caller.</div></div>
        )}
        {inc.gemini?.state === "done" && <div className="gem done" role="status"><div><b>Updated by {ai.name}</b> after {inc.gemini.attempt} attempt{inc.gemini.attempt > 1 ? "s" : ""}.</div></div>}
        {inc.triage.note && inc.gemini?.state !== "done" && !inc.fast && <p className="note">{inc.triage.note}</p>}
        {!inc.triage.note && <p className="note">Read by {inc.triage.meta.model} in {inc.triage.meta.latency_s}s. Priority and units come from fixed rules, not the model.{inc.triage.meta.engine === "local" && " Read on this computer: the call never left it."}</p>}
        {!!inc.triage.meta.redacted?.length && <p className="note">Removed before the call went to the model (DPDP Act): {inc.triage.meta.redacted.join(", ")}. The dispatcher still sees the full call.</p>}
      </div>

      {inc.status !== "resolved" && <div className="section">
        <h2>{inc.status === "new" ? "Send" : "Units"}</h2>
        {inc.status === "new" && (
          <div className={`placebox ${loc.resolved ? "" : "need"}`}>
            {!loc.resolved ? (
              <p style={{ margin: 0 }}><b>Where is it?</b> {loc.road ? <>The caller said <b>{loc.road}</b> but not where on it. It's highlighted on the map: confirm the spot with the caller and click it.</>
                : <>The call didn't give a place we can map. Confirm it with the caller, then click it on the map or choose the sector.</>}</p>
            ) : <p style={{ margin: 0 }}><b>Place:</b> {loc.label}. Wrong? Click the right spot on the map or choose the sector.</p>}
            <div className="row">
              <select aria-label="Choose sector" value="" onChange={(e) => {
                const ll = meta?.sectors[e.target.value]; if (ll) act(() => api.setLocation(inc.id, ll[0], ll[1], `Sector ${e.target.value} (centre, chosen by dispatcher)`));
              }}>
                <option value="">Choose sector…</option>
                {meta && Object.keys(meta.sectors).map((k) => <option key={k} value={k}>Sector {k}</option>)}
              </select>
              {loc.resolved && <button className="btn secondary" onClick={onPick} disabled={picking}>{picking ? "Click the map…" : "Move on map"}</button>}
            </div>
          </div>
        )}
        {d.units.length === 0 && <>
          <p className="hint" style={{ marginTop: 0 }}>Not an emergency: no unit needed. Refer the caller to the right service.</p>
          <div className="row"><button className="btn secondary wide" disabled={busy} onClick={() => act(() => api.close(inc.id))}>Close: caller referred</button></div>
        </>}
        {inc.status === "new" && inc.recommendation && Object.entries(inc.recommendation).map(([kind, r]) => (
          <div className="rec" key={kind}>
            <div className="k"><span>{KIND_NAME[kind]}</span><span className="hint">{r.available} free</span></div>
            {r.best ? (
              <>
                <div><span className="eta num">{mmss(r.best.eta_s)}</span> <span>{r.best.unit} from {r.best.base}</span></div>
                {r.nearest_by_distance && r.nearest_by_distance.unit !== r.best.unit ? (
                  <div className="vs">Nearest on the map is {r.nearest_by_distance.unit} ({r.nearest_by_distance.km} km), but by road it takes {mmss(r.nearest_by_distance.eta_s)}. <span className="saved">{mmss(r.saved_s)} faster</span> this way.</div>
                ) : <div className="vs">Also the nearest unit on the map.</div>}
                {r.options && r.options.length > 1 && <div className="opts num">Next: {r.options.slice(1).map((o) => `${o.unit} ${mmss(o.eta_s)}`).join(", ")}</div>}
              </>
            ) : <div className="vs">{r.note}</div>}
          </div>
        ))}
        {inc.status === "new" && inc.recommendation && (
          <div className="row"><button className="btn wide" disabled={busy} onClick={() => act(() => api.dispatch(inc.id))}>Dispatch {Object.values(inc.recommendation).filter((r) => r.best).map((r) => r.best!.unit).join(" + ")}</button></div>
        )}
        {inc.status === "dispatched" && inc.extra && Object.entries(inc.extra).map(([kind, r]) => (
          <div className="rec extra" key={kind}>
            <div className="k"><span>Suggested next: {KIND_NAME[kind]}</span><span className="hint">{r.available} free</span></div>
            {r.best ? <>
              <div><span className="eta num">{mmss(r.best.eta_s)}</span> <span>{r.best.unit} from {r.best.base}</span></div>
              <div className="row"><button className="btn wide" disabled={busy} onClick={() => act(() => api.dispatch(inc.id, [r.best!.unit]))}>Send {KIND_NAME[kind].toLowerCase()} {r.best.unit}</button></div>
            </> : <div className="vs">{r.note}</div>}
          </div>
        ))}
        {inc.status === "dispatched" && mine.map((u) => {
          const r = routeOf(u.id);
          const here = u.incident === inc.id;
          const total = r ? (r.eta_s + 60) / demo : 1;
          const pct = u.status === "en_route" && here ? Math.max(4, Math.min(100, 100 * (1 - (u.eta_wall_s ?? 0) / total))) : 100;
          const what = !here || u.status === "returning" || u.status === "available" ? `cleared, returning to base`
            : u.status === "en_route" ? `on the way (${u.eta_wall_s} s on the demo clock)`
            : `on scene${u.scene_left_wall_s != null ? ` (clears in ${u.scene_left_wall_s} s on the demo clock)` : ""}`;
          const tl = here ? u.tele : null;
          return (
            <div className={`unitrow ${u.kind} ${here ? u.status : "done"}`} key={u.id}>
              <div className="ur-top"><b>{u.id}</b> <span>{KIND_NAME[u.kind]} from {u.base}{r?.km ? `, ${r.km} km route` : ""}</span></div>
              <div className="ur-what num">{what}</div>
              {tl && u.status === "en_route" && (
                <dl className="stats">
                  <div><dt>Distance left</dt><dd>{tl.left_km.toFixed(1)}<small>km</small></dd></div>
                  <div><dt>Speed now</dt><dd>{tl.rolling ? tl.speed_kmh : 0}<small>km/h</small></dd></div>
                  <div><dt>Real drive left</dt><dd>{mmss(tl.left_s)}</dd></div>
                </dl>
              )}
              <div className="track" aria-hidden="true"><span style={{ width: `${pct}%` }} /></div>
            </div>
          );
        })}
        {inc.status === "dispatched" && (
          <div className="row"><button className="btn secondary wide" disabled={busy || anyDriving} onClick={() => act(() => api.close(inc.id))}
            title={anyDriving ? "Wait until every unit has arrived" : "Units clear the scene now"}>{anyDriving ? "Close incident (after arrival)" : "Close incident now"}</button></div>
        )}
        {err && <p className="err" role="alert">{err}</p>}
      </div>}

      {inc.corridor && inc.status === "dispatched" && anyDriving && (
        <div className="section">
          <h2>Clear the way</h2>
          <p className="hint" style={{ marginTop: 0 }}>Junctions on main roads along the route, with when the unit reaches each. Traffic police can hold them green or clear them.</p>
          {inc.traffic?.length > 0 ? (
            <>
              <p className="hint" style={{ marginTop: 0 }}>Each junction gets its own alert, sent 2 minutes (simulated) before the unit reaches it. Replies are simulated.</p>
              <ul className="posts">{inc.traffic.map((p) => (
                <li key={p.i} className={`post ${p.status}`}>
                  <span className="pdot" aria-hidden="true" />
                  <span className="pwhere">{p.unit}: junction on {p.road} road</span>
                  <span className="pstat num">{p.status === "scheduled" ? `alert in ${p.opens_in_s}s` : p.status === "sent" ? `sent, unit in ${p.unit_in_s}s`
                    : p.status === "cleared" ? `cleared (replied in ${p.ack_after_s}s)` : p.status === "done" ? "unit passed" : "no reply"}</span>
                </li>))}</ul>
              <p className="hint">{inc.traffic.filter((p) => p.status === "cleared" || p.status === "done").length} of {inc.traffic.length} posts confirmed; {inc.traffic.filter((p) => p.status === "no_reply").length} did not reply.</p>
            </>
          ) : inc.corridor.routes.map((r) => (
            <div key={r.unit}>
              <h3>{r.unit} ({KIND_NAME[r.kind]}): {r.km ?? "?"} km, {mmss(r.eta_s)} drive{r.avg_kmh ? ` at ${r.avg_kmh} km/h average` : ""}, {r.junctions.length} junctions</h3>
              <ul className="junctions">{r.junctions.slice(0, 8).map((j, k) => <li key={k} className="num"><span>Junction on {j.road} road</span><span>+{mmss(j.at_s)}</span></li>)}</ul>
              {r.junctions.length > 8 && <p className="hint">and {r.junctions.length - 8} more</p>}
            </div>
          ))}
          {!inc.traffic?.length && <div className="row"><button className="btn secondary wide" disabled={busy || alert?.incident === inc.id} onClick={async () => { try { setAlert(await api.notify(inc.id)); } catch (e) { setErr((e as Error).message); } }}>{alert?.incident === inc.id ? "Traffic police alerted" : "Alert traffic police"}</button></div>}
          {alert && alert.incident === inc.id && <div className="alert" role="status">Sent {alert.id}: {alert.message}. (Simulated: Chandigarh has no live signal priority link today.)</div>}
        </div>
      )}
      <CCTVSection inc={inc} gemini={!!gemini} onChanged={onChanged} onError={onError} />
      <Timeline inc={inc} />
    </div>
  );
}
