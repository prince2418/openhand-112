/* Sound cues, synthesised with the Web Audio API (no audio files, nothing to download).
   Short and distinct, like a dispatch console: the dispatcher should know what happened without looking.
   Browsers only allow audio after a user gesture, so the context is created on the first click. */

type Cue = "call" | "callP1" | "dispatch" | "traffic" | "arrive" | "resolved" | "error";

let ctx: AudioContext | null = null;
let enabled = true;
try { enabled = localStorage.getItem("oh-sound") !== "off"; } catch { /* storage blocked: default on */ }

export function unlockAudio() {
  if (ctx) { if (ctx.state === "suspended") void ctx.resume(); return; }
  const AC = window.AudioContext || (window as any).webkitAudioContext;
  if (AC) ctx = new AC();
}
export const soundOn = () => enabled;
export function setSound(on: boolean) {
  enabled = on;
  try { localStorage.setItem("oh-sound", on ? "on" : "off"); } catch { /* ignore */ }
  if (on) { unlockAudio(); play("dispatch"); }
}

function tone(freq: number, start: number, dur: number, opts: { type?: OscillatorType; gain?: number; to?: number } = {}) {
  if (!ctx) return;
  const t0 = ctx.currentTime + start;
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.type = opts.type ?? "sine";
  o.frequency.setValueAtTime(freq, t0);
  if (opts.to) o.frequency.exponentialRampToValueAtTime(opts.to, t0 + dur);
  const peak = opts.gain ?? 0.18;
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(peak, t0 + 0.012);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g).connect(ctx.destination);
  o.start(t0); o.stop(t0 + dur + 0.02);
}

export function play(cue: Cue) {
  if (!enabled || !ctx) return;
  if (ctx.state === "suspended") void ctx.resume();
  switch (cue) {
    case "callP1":    // urgent two-tone, twice
      [0, 0.36].forEach((s) => { tone(988, s, 0.16, { type: "triangle", gain: 0.2 }); tone(740, s + 0.17, 0.16, { type: "triangle", gain: 0.2 }); });
      break;
    case "call":      // soft double chime
      tone(784, 0, 0.22, { gain: 0.14 }); tone(1047, 0.13, 0.3, { gain: 0.12 });
      break;
    case "dispatch":  // rising confirm
      [523, 659, 784].forEach((f, i) => tone(f, i * 0.08, 0.18, { type: "triangle", gain: 0.13 }));
      break;
    case "traffic":   // radio chirp
      tone(1400, 0, 0.09, { type: "square", gain: 0.05, to: 2200 }); tone(2200, 0.11, 0.07, { type: "square", gain: 0.04, to: 1400 });
      break;
    case "arrive":    // bell
      tone(1319, 0, 0.9, { gain: 0.16 }); tone(2637, 0, 0.5, { gain: 0.05 });
      break;
    case "resolved":  // gentle major arpeggio
      [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.1, 0.5, { gain: 0.11 }));
      break;
    case "error":
      tone(220, 0, 0.25, { type: "sawtooth", gain: 0.06 });
      break;
  }
}
