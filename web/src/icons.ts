/* Map symbols, drawn as inline SVG so they need no image files.
   Incidents use the Indian road warning sign: white triangle, red border, black pictogram (IRC:67).
   Moving units are top-down vehicles that turn with the road; the light bar flashes while they drive. */
import type { Kind } from "./types";

const PICTO: Record<string, string> = {
  road_accident: `
    <g transform="rotate(-24 24 40)"><rect x="14" y="35" width="15" height="8" rx="2.5"/><rect x="16" y="32" width="9" height="5" rx="1.5"/></g>
    <g transform="rotate(24 40 40)"><rect x="35" y="35" width="15" height="8" rx="2.5"/><rect x="39" y="32" width="9" height="5" rx="1.5"/></g>
    <path d="M32 22 l1.6 4.4 4.4-1.6-1.6 4.4 4.4 1.6-4.4 1.6" fill="none" stroke="#0b0c0c" stroke-width="2" stroke-linejoin="round"/>`,
  fire: `<path d="M32 20c5 7 9 11 8.6 19.5C40.3 45.6 36.5 49 32 49s-8.6-3.3-8.6-8.4c0-4.6 3-7.3 4.3-11 1.6 2.5 3 3.4 4.3 3.6-1-4.2-.6-8.6 0-13.2z"/>
         <path d="M32 36c2.3 2.8 3.6 4.6 3.4 7.4-.2 2.4-1.6 3.8-3.4 3.8s-3.4-1.3-3.4-3.4c0-2.2 1.6-3.8 3.4-7.8z" fill="#fff"/>`,
  medical: `<rect x="28" y="25" width="8" height="23" rx="1"/><rect x="20.5" y="32.5" width="23" height="8" rx="1"/>`,
  crowd: `<circle cx="22" cy="31" r="3.6"/><circle cx="32" cy="28" r="4"/><circle cx="42" cy="31" r="3.6"/>
          <path d="M16 48c0-6 2.8-11 6-11s6 5 6 11zM25.5 48c0-7 3-13 6.5-13s6.5 6 6.5 13zM36 48c0-6 2.8-11 6-11s6 5 6 11z"/>`,
  waterlogging: `<path d="M17 33q3.75-4 7.5 0t7.5 0 7.5 0 7.5 0M17 40q3.75-4 7.5 0t7.5 0 7.5 0 7.5 0M17 47q3.75-4 7.5 0t7.5 0 7.5 0 7.5 0" fill="none" stroke="#0b0c0c" stroke-width="3" stroke-linecap="round"/>`,
  non_emergency: `<circle cx="32" cy="27" r="3"/><rect x="29.5" y="33" width="5" height="15" rx="1"/>`,
  alert: `<rect x="29" y="22" width="6" height="17" rx="2"/><circle cx="32" cy="45" r="3.4"/>`,
};

export function signSvg(type: string): string {
  const p = PICTO[type] ?? PICTO.alert;
  return `<svg viewBox="0 0 64 58" width="46" height="42" aria-hidden="true">
    <path d="M32 5 L60 53 H4 Z" fill="#fff" stroke="#d4351c" stroke-width="6.5" stroke-linejoin="round"/>
    <g fill="#0b0c0c">${p}</g></svg>`;
}

export const doneSvg = `<svg viewBox="0 0 40 40" width="34" height="34" aria-hidden="true">
  <circle cx="20" cy="20" r="17" fill="#00703c" stroke="#fff" stroke-width="3"/>
  <path d="M12 20.5l5.5 5.5L28.5 14" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/></svg>`;

/* Top-down vehicles, nose pointing up (heading 0 = north). Body colours follow the unit key. */
export function vehicleSvg(kind: Kind): string {
  if (kind === "fire") return `<svg viewBox="0 0 26 50" width="20" height="38" aria-hidden="true">
    <rect x="2" y="1.5" width="22" height="47" rx="4" fill="#d4351c" stroke="#fff" stroke-width="2"/>
    <rect x="4.5" y="4" width="17" height="7" rx="2" fill="#5c1a10"/>
    <rect x="5" y="13" width="7" height="3.6" rx="1" class="lb-a"/><rect x="14" y="13" width="7" height="3.6" rx="1" class="lb-b"/>
    <path d="M8 21v24M18 21v24M8 26h10M8 32h10M8 38h10" stroke="#fff" stroke-width="1.6" opacity=".85"/></svg>`;
  if (kind === "ambulance") return `<svg viewBox="0 0 26 44" width="20" height="34" aria-hidden="true">
    <rect x="2" y="1.5" width="22" height="41" rx="5" fill="#fff" stroke="#00703c" stroke-width="2.4"/>
    <rect x="4.5" y="4" width="17" height="7" rx="2.5" fill="#1b3b2c"/>
    <rect x="5" y="13" width="7" height="3.6" rx="1" class="lb-a"/><rect x="14" y="13" width="7" height="3.6" rx="1" class="lb-b"/>
    <rect x="10.6" y="21" width="4.8" height="15" rx=".8" fill="#d4351c"/><rect x="5.5" y="26.1" width="15" height="4.8" rx=".8" fill="#d4351c"/></svg>`;
  return `<svg viewBox="0 0 26 42" width="20" height="32" aria-hidden="true">
    <rect x="2" y="1.5" width="22" height="39" rx="6" fill="#1d70b8" stroke="#fff" stroke-width="2"/>
    <rect x="4.5" y="5" width="17" height="7.5" rx="2.5" fill="#0c2d4a"/>
    <rect x="4" y="15.5" width="8.5" height="4" rx="1.2" class="lb-a"/><rect x="13.5" y="15.5" width="8.5" height="4" rx="1.2" class="lb-b"/>
    <rect x="5.5" y="23" width="15" height="11" rx="2" fill="#fff" opacity=".9"/>
    <rect x="4.5" y="33.5" width="17" height="4.5" rx="1.6" fill="#0c2d4a"/></svg>`;
}
export const KIND_LETTER: Record<Kind, string> = { police: "P", ambulance: "A", fire: "F" };
