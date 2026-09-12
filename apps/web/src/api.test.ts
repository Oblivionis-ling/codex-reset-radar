import { describe, expect, it } from "vitest";
import { actionLevel, parseRadar } from "./api";

describe("V2 Radar API contract", () => {
  it("accepts the four action levels plus UNKNOWN", () => {
    expect(["GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"].map(actionLevel)).toEqual([
      "GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"
    ]);
    expect(actionLevel("CONFIRMED")).toBe("UNKNOWN");
  });

  it("does not expose a confidence field", () => {
    const result = parseRadar({
      version: "0.1.0-alpha.1",
      action_level: "UNKNOWN",
      horizon_24h: "UNKNOWN",
      horizon_48h: "UNKNOWN",
      horizon_72h: "UNKNOWN",
      confidence: 0.99,
      next_reset: { status: "waiting_for_verified_history" }
    });
    expect(result.action_level).toBe("UNKNOWN");
    expect("confidence" in result).toBe(false);
  });

  it("normalizes every special reset to PURPLE", () => {
    const result = parseRadar({
      action_level: "GREEN",
      horizon_24h: "GREEN",
      horizon_48h: "YELLOW",
      horizon_72h: "ORANGE",
      special_resets: [{
        id: 1,
        event_type: "SPECIAL_RESET",
        special_type: "BANKED",
        occurred_at: "2026-09-01T00:00:00Z",
        title: "Synthetic fixture",
        summary: "Not real history",
        display_tone: "RED"
      }]
    });
    expect(result.special_resets[0].display_tone).toBe("PURPLE");
  });
});
