export const TYPE_LABEL: Record<string, string> = {
  road_accident: "Road accident", fire: "Fire", medical: "Medical", crime_violent: "Violence or threat",
  crime_property: "Theft or property crime", crowd: "Crowd", waterlogging: "Waterlogging", other_emergency: "Other emergency",
  non_emergency: "Not an emergency",
};
export const KIND_NAME: Record<string, string> = { police: "PCR", ambulance: "Ambulance", fire: "Fire tender" };
export const LANG: Record<string, string> = { en: "English", hi: "Hindi", "hi-latn": "Hinglish", pa: "Punjabi", "pa-latn": "Punjabi (Roman)", mixed: "Mixed",
  ta: "Tamil", te: "Telugu", kn: "Kannada", ml: "Malayalam", bn: "Bengali", mr: "Marathi", gu: "Gujarati", or: "Odia" };
export function mmss(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return "–";
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}
