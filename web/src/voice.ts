/* Voice intake: record the caller from the microphone and, where the browser supports it, show the words live
   (Web Speech API: Chrome and Safari). The recording is converted to 16 kHz WAV so Gemini can read it too. */

export const LANGS = [
  { code: "hi-IN", label: "Hindi / Hinglish" },
  { code: "en-IN", label: "English (India)" },
  { code: "pa-IN", label: "Punjabi" },
  { code: "ta-IN", label: "Tamil" }, { code: "te-IN", label: "Telugu" }, { code: "kn-IN", label: "Kannada" },
  { code: "ml-IN", label: "Malayalam" }, { code: "bn-IN", label: "Bengali" }, { code: "mr-IN", label: "Marathi" },
  { code: "gu-IN", label: "Gujarati" }, { code: "or-IN", label: "Odia" },
];

export function speechSupported(): boolean {
  return !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
}

export interface VoiceSession { stop: (wantAudio: boolean) => Promise<File | null>; cancel: () => void }

export async function startVoice(lang: string, onText: (finalText: string, interim: string) => void): Promise<VoiceSession> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const chunks: Blob[] = [];
  const rec = new MediaRecorder(stream);
  rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  rec.start(250);

  let finalText = "";
  let recog: any = null;
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (SR) {
    recog = new SR();
    recog.lang = lang; recog.continuous = true; recog.interimResults = true;
    recog.onresult = (ev: any) => {
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) finalText += (finalText ? " " : "") + r[0].transcript.trim();
        else interim += r[0].transcript;
      }
      onText(finalText, interim);
    };
    recog.onend = () => { if (recog && recog._keep) { try { recog.start(); } catch { /* already running */ } } };
    recog._keep = true;
    try { recog.start(); } catch { recog = null; }
  }

  const finish = () => {
    if (recog) { recog._keep = false; try { recog.stop(); } catch { /* ignore */ } }
    stream.getTracks().forEach((t) => t.stop());
  };
  return {
    cancel: () => { try { rec.stop(); } catch { /* ignore */ } finish(); },
    // wantAudio=false (we already have the words): stop at once, no conversion, nothing heavy on the page
    stop: (wantAudio: boolean) => new Promise((resolve) => {
      if (!wantAudio) { try { rec.stop(); } catch { /* ignore */ } finish(); resolve(null); return; }
      rec.onstop = async () => {
        finish();
        try {
          const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
          resolve(blob.size ? new File([await toWav(blob)], "voice-call.wav", { type: "audio/wav" }) : null);
        } catch { resolve(null); }
      };
      try { rec.stop(); } catch { finish(); resolve(null); }
    }),
  };
}

async function toWav(blob: Blob): Promise<Blob> {
  const AC = window.AudioContext || (window as any).webkitAudioContext;
  const ctx = new AC();
  const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
  void ctx.close();
  const rate = 16000, len = Math.ceil(buf.duration * rate);
  const off = new OfflineAudioContext(1, len, rate);
  const src = off.createBufferSource(); src.buffer = buf; src.connect(off.destination); src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const w = (o: number, s: string) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true); out.setUint32(24, rate, true);
  out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true); w(36, "data"); out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
  return new Blob([out], { type: "audio/wav" });
}

/* same rule and spelling normalisation as the server's fast path (word lists come from /api/meta) */
export function norm(text: string): string {
  let t = text.toLowerCase().normalize("NFC").replace(/\u093c|\u0a3c/g, "");
  t = t.replace(/ee/g, "i").replace(/oo/g, "u").replace(/ou/g, "au").replace(/ph/g, "f").replace(/w/g, "v").replace(/z/g, "j").replace(/q/g, "k");
  t = t.replace(/([a-z])\1+/g, "$1");
  return t.replace(/[^\p{L}\p{M}\p{N}\s-]/gu, " ").replace(/\s+/g, " ").trim();
}
export function alertHit(text: string, words?: { direct: string[]; female: string[]; threat: string[] }): string | null {
  if (!words || !text) return null;
  const t = norm(text);
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const has = (w0: string) => { const w = norm(w0); if (!w) return false;
    return /^[\x00-\x7f]+$/.test(w) ? new RegExp(`(?<![a-z])${esc(w)}`).test(t) : t.includes(w); };
  const d = words.direct.find(has); if (d) return d;
  let f = words.female.find((w) => has(w) && norm(w).length > 3);
  const th = words.threat.find(has);
  if (th && !f) f = ["she", "her"].find((w) => new RegExp(`\\b${w}\\b`).test(t));
  return f && th ? `${f} + ${th}` : null;
}
