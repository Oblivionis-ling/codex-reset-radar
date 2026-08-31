export const RADAR_STATES = ["QUIET", "WATCH", "LIKELY", "IMMINENT", "ANNOUNCED", "CONFIRMED", "UNKNOWN"] as const;
export const ADVICE_LEVELS = ["GREEN", "YELLOW", "ORANGE", "RED"] as const;

export function radarStateToken(value: string): string {
  const token = value.toUpperCase();
  return RADAR_STATES.includes(token as (typeof RADAR_STATES)[number]) ? token.toLowerCase() : "unknown";
}

export function adviceTone(value: string): string {
  const token = value.toUpperCase();
  return ADVICE_LEVELS.includes(token as (typeof ADVICE_LEVELS)[number]) ? token.toLowerCase() : "green";
}
