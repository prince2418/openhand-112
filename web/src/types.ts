export type Kind = "police" | "ambulance" | "fire";
export type Priority = "P1" | "P2" | "P3" | "P4";

export interface Station { kind: string; name: string; lat: number; lng: number }
export interface Hotspot { name: string; type: string; lat: number; lng: number; accuracy: string; basis: string }
export interface Meta { stations: Station[]; hotspots: Hotspot[]; unit_labels: Record<Kind, string>; bounds: [[number, number], [number, number]]; center: [number, number];
  sectors: Record<string, [number, number]>; roads: Record<string, [number, number][]>;
  alert_words: { direct: string[]; female: string[]; threat: string[] }; cameras: Camera[]; flood_spots: FloodSpotMeta[] }
export interface Camera { id: string; lat: number; lng: number; road: string; m?: number }
export interface CCTVCheck { shows_incident: "yes" | "no" | "unclear"; seen_type: string; what_is_seen: string; people_visible: number | null;
  injured_visible: boolean; fire_or_smoke: boolean; weapon_visible: boolean; violence_visible: boolean; crowd_building: boolean;
  vehicles_involved: number | null; road_blocked: boolean; hazards: string[]; looks_stale_or_unrelated: boolean; confidence: number }

export interface Unit { id: string; kind: Kind; base: string; status: "available" | "en_route" | "on_scene" | "returning"; incident: string | null; lat: number; lng: number; eta_wall_s: number | null; scene_left_wall_s: number | null; home_wall_s: number | null;
  tele: Tele | null; path: { c: [number, number][]; t: number[]; m: number[] } | null }
export interface Tele { left_km: number; route_km: number; speed_kmh: number; left_s: number; heading: number; rolling: boolean }

export interface Extract {
  incident_type: string; secondary_types: string[]; location_text: string | null; sector: number | null; landmark: string | null;
  people_injured: number | null; unconscious_or_not_breathing: boolean; immediate_life_threat: boolean; people_trapped: boolean;
  violence_ongoing: boolean; fire_or_smoke: boolean; hazards: string[]; vulnerable: string[]; caller_language: string;
  summary_en: string; missing_info: string[]; confidence: number;
}
export interface Decision { priority: Priority; units: Kind[]; reasons: string[]; needs_human_review: boolean; review_reasons: string[] }
export interface Option { unit: string; base: string; eta_s: number; km: number }
export interface Rec { available: number; best: Option | null; options?: Option[]; nearest_by_distance?: Option; saved_s?: number; note?: string }
export interface Junction { lat: number; lng: number; road: string; at_s: number; at_wall: number }
export interface CorridorRoute { unit: string; kind: Kind; eta_s: number; route: [number, number][]; junctions: Junction[]; km: number | null; avg_kmh: number | null }

export interface Incident {
  id: string; t: number; age_s: number; status: "new" | "dispatched" | "resolved"; lat: number | null; lng: number | null;
  calls: number; more_calls: string[]; units: string[]; transcript: string | null;
  triage: { extract: Extract; decision: Decision; location: { lat: number | null; lng: number | null; method: string; label: string; resolved: boolean; road?: string | null }; meta: { model: string; latency_s: number; redacted?: string[]; engine?: string }; note: string | null };
  recommendation: Record<string, Rec> | null; corridor: { routes: CorridorRoute[] } | null;
  events: TimelineEvent[]; outcome: Outcome | null;
  gemini: { state: "trying" | "done" | "gave_up"; attempt: number; error: string | null } | null;
  fast: string | null; extra: Record<string, Rec> | null; traffic: Post[];
  cameras: Camera[]; cctv: { camera: string; t: number; check: CCTVCheck; model: string; latency_s: number; notes: string[] }[];
}
export interface TimelineEvent { t: number; at_s: number; kind: "call" | "triage" | "location" | "dispatch" | "traffic" | "arrive" | "clear" | "resolved" | "note"; text: string }
export interface Outcome {
  first_on_scene_s: number | null; per_unit_s: Record<string, number>; targets_met: Record<string, boolean>; all_targets_met: boolean;
  target_s: number | null; saved_vs_nearest_s: number; junctions_alerted: number; duration_s: number; closed_by: "units" | "dispatcher"; calls: number;
}
export interface Alert { id: string; incident: string; junctions: number; message: string }
export interface Conditions { fog: boolean; night: boolean; pcr_on_duty: number; fog_slowdown: number; closures: { id: number; lat: number; lng: number; segments: [number, number][][] }[];
  flood: { label: string; at: string; closed: number; diverted: number; seg_closed: [number, number][][]; seg_divert: [number, number][][] } | null }
export interface Post { i: number; unit: string; road: string; lat: number; lng: number; status: "scheduled" | "sent" | "cleared" | "done" | "no_reply"; opens_in_s: number; unit_in_s: number; ack_after_s: number | null }
export interface State { now: number; demo_speed: number; units: Unit[]; incidents: Incident[]; free: Record<Kind, number>; alerts: Alert[]; conditions: Conditions }
export interface Health { triage: string; model: string | null; ai_name?: string; fallbacks: string[]; demo_speed: number; speed_scale: number }
export interface AIEngines {
  active: "gemini" | "local" | "none"; ai_name: string;
  gemini: { available: boolean; model: string | null; fallbacks: string[]; where: string };
  local: { ok: boolean; model: string; host: string; reason?: string; installed?: string[]; where: string; audio: boolean };
}
export interface Sample { id: string; lang: string; transcript: string }

export type FLevel = "clear" | "watch" | "divert" | "close";
export interface FloodSpotMeta { id: string; name: string; kind: string; lat: number; lng: number; radius_m: number; sources: string[]; accuracy: string; region: string }
export interface FloodSpot { id: string; name: string; kind: string; lat: number; lng: number; depth: number; level: FLevel; trend: "rising" | "falling" | "steady";
  peak: number; peak_at: string; team_from: string | null; accuracy: string; sources: string[]; forecast: FLevel; close_at: string | null }
export interface FloodAction { kind: "close" | "preclose" | "divert" | "pumps" | "ems" | "rescue" | "reopen"; spot?: string; title: string; text: string;
  barricades?: { lat: number; lng: number; road: string }[]; diversion?: { text: string; path: [number, number][] } | null }
export interface FloodTeam { team: number; spot: string; name: string; at: string; state: "working" | "due" | "later"; peak: number; peak_no_pump: number; saved_h: number }
export interface FloodPlan {
  active: true; scenario: { id: string; label: string; note: string; start: string; now_step: number }; step: number; now: string; labels: string[];
  rain_hourly: number[]; rain_now: number; step_h: number; counts: Record<FLevel, number>; spots: FloodSpot[]; actions: FloodAction[]; teams: FloodTeam[]; teams_total: number;
  ems: { amb_cover_before: number; amb_cover_after: number; pcr_cover_before: number; pcr_cover_after: number; cut_off: number; sectors_lost: number[];
    hospitals: { name: string; before_min: number; after_min: number }[]; move?: { lat: number; lng: number; gain: number; text: string } };
  totals: { closed_hours: number; closed_hours_no_pump: number; peak_closed: number }; pumps: boolean;
  design_mm_h: { north: number; south: number }; thresholds: { watch: number; divert: number; close: number }; depth: number[][];
}
export interface FloodScenario { id: string; label: string; note: string; total_mm: number | null }
export interface Advisory { advisory: { english: string; hindi: string; punjabi: string; sms: string }; by: string; note?: string; latency_s?: number }

// ---------- predict and monitor ----------
export interface SvcHour { expected: number; low: number; high: number; busy: number; units: number; p_none_free: number }
export interface Zone { sector: number; lat: number; lng: number; expected: number; share: number; crash: number; why: string[] }
export interface Skill { area_pct: number; hit_pct: number; pai: number; prior_hit_pct: number; prior_pai: number; best_hit_pct: number; of_best_pct: number;
  train_days: number; test_days: number; train_n: number; test_n: number; cell_m: number; note: string }
export interface Outlook { from: string; rows: { hour: string; services: Record<Kind, SvcHour> }[]; zones: Zone[]; conditions: string[];
  city_next_hour: number; peak_hour: string; skill: Skill; notes: string[] }
export interface Move { unit: string; base: string; lat: number; lng: number; from_lat: number; from_lng: number; place: string; gain: number }
export interface WatchAlert { id: string; kind: "cluster" | "surge" | "coverage" | "fleet" | "rain" | "prepare"; level: "high" | "medium"; title: string; text: string; todo: string;
  lat?: number; lng?: number; radius_m?: number; incidents?: string[]; from_lat?: number; from_lng?: number; moves?: Move[];
  action?: { kind: "reposition" | "spread"; unit?: string; lat?: number; lng?: number; moves?: { unit: string; lat: number; lng: number }[]; label: string } }
export interface Watch { alerts: WatchAlert[]; coverage: { now: number; all_free: number; free: number; on_duty: number; sectors_lost: number[]; move: Move | null };
  conditions: string[]; window_min_demo: number; window_min_wall: number }

// ---------- open platform ----------
export interface Iface { dir: "in" | "out"; system: string; owner: string; format: string; endpoint: string; status: string; live: string }
export interface OutMsg { id: string; at: string; direction: "in" | "out"; party: string; what: string; standard: string; summary: string; format: "json" | "xml"; simulated: boolean; payload: unknown }
