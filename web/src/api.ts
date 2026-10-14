async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not json */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}
const json = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** Name of the AI engine reading calls right now ("Gemini" or "local Gemma"); App sets it from /api/health. */
export const ai = { name: "Gemini", local: false };

export const api = {
  cities: () => req<any>("/api/cities"),
  city: (slug: string) => req<any>(`/api/cities/${slug}`),
  engines: () => req<import("./types").AIEngines>("/api/ai"),
  setEngine: (engine: "gemini" | "local") => req<import("./types").AIEngines>("/api/ai", json({ engine })),
  health: () => req<import("./types").Health>("/api/health"),
  meta: () => req<import("./types").Meta>("/api/meta"),
  state: () => req<import("./types").State>("/api/state"),
  samples: () => req<import("./types").Sample[]>("/api/samples"),
  risk: (kind: string) => req<{ hour: number; cells: { lat: number; lng: number; level: number }[] }>(`/api/risk?kind=${kind}`),
  standby: () => req<{ points: { lat: number; lng: number }[] }>("/api/standby"),
  evidence: () => req<any>("/api/evidence"),
  call: (fd: FormData) => req<{ incident: import("./types").Incident; merged: boolean }>("/api/calls", { method: "POST", body: fd }),
  setLocation: (id: string, lat: number, lng: number, label?: string) => req<import("./types").Incident>(`/api/incidents/${id}/location`, json({ lat, lng, label })),
  dispatch: (id: string, units?: string[]) => req<import("./types").Incident>(`/api/incidents/${id}/dispatch`, json({ units })),
  notify: (id: string) => req<import("./types").Alert>(`/api/incidents/${id}/notify-traffic`, json({})),
  close: (id: string) => req<import("./types").Incident>(`/api/incidents/${id}/close`, json({})),
  conditions: (c: { fog?: boolean; night?: boolean }) => req<import("./types").Conditions>("/api/conditions", json(c)),
  closeRoad: (lat: number, lng: number) => req<import("./types").Conditions>("/api/closures", json({ lat, lng })),
  reopenRoads: () => req<import("./types").Conditions>("/api/closures", { method: "DELETE" }),
  cctvCheck: (id: string, fd: FormData) => req<import("./types").Incident>(`/api/incidents/${id}/cctv`, { method: "POST", body: fd }),
  cctvAlert: (fd: FormData) => req<{ incident: import("./types").Incident | null; message: string | null }>("/api/cctv/alert", { method: "POST", body: fd }),
  floodScenarios: () => req<import("./types").FloodScenario[]>("/api/flood/scenarios"),
  floodStart: (scenario: string, mm_h?: number, hours?: number) => req<import("./types").FloodPlan>("/api/flood/start", json({ scenario, mm_h, hours })),
  floodApply: (step?: number, pumps?: boolean) => req<import("./types").FloodPlan>("/api/flood/apply", json({ step, pumps })),
  floodPlan: () => req<import("./types").FloodPlan | { active: false }>("/api/flood/plan"),
  floodClear: () => req<{ active: false }>("/api/flood", { method: "DELETE" }),
  floodRisk: () => req<any>("/api/flood/risk"),
  floodAdvisory: () => req<import("./types").Advisory>("/api/flood/advisory", json({})),
  outlook: () => req<import("./types").Outlook>("/api/predict/outlook"),
  watch: () => req<import("./types").Watch>("/api/watch"),
  dismiss: (id: string) => req<{ ok: boolean }>(`/api/watch/${encodeURIComponent(id)}/dismiss`, json({})),
  reposition: (unit: string, lat: number, lng: number) => req<{ unit: string; to: string; eta_s: number }>(`/api/units/${unit}/reposition`, json({ lat, lng })),
  catalogue: () => req<{ interfaces: import("./types").Iface[]; api_docs: string; openapi: string; licence: string }>("/api/dpi/catalogue"),
  outbox: (since = 0) => req<{ messages: import("./types").OutMsg[]; total: number }>(`/api/dpi/outbox?since=${since}`),
  capSend: () => req<import("./types").OutMsg>("/api/dpi/cap/flood/send", json({})),
  reset: () => req<{ ok: boolean }>("/api/reset", { method: "POST" }),
};
