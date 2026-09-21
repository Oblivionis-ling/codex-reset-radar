import { describe, expect, it } from "vitest";
import { actionLevel, parseRadar } from "./api";

describe("V2 Radar API contract", () => {
  it('keeps stale health, model unknown, validation and previews distinct',()=>{
    const result=parseRadar({action_level:'UNKNOWN',data_health:'STALE',current_data_health:'HEALTHY',
      judgement_data_health:'STALE',display_mode:'last_known',validation:{valid:true,reason:'VALID'},
      last_known_result:{action_level:'ORANGE'},special_announcements:[
        {candidate_id:3,tweet_id:'100',summary:'Synthetic banked preview',scope:'unknown',scheduled_at:null},
        {candidate_id:4,tweet_id:'javascript:alert(1)'}]});
    expect(result.display_mode).toBe('last_known');
    expect(result.judgement_data_health).toBe('STALE');
    expect(result.current_data_health).toBe('HEALTHY');
    expect(result.validation.valid).toBe(true);
    expect(result.special_announcements).toHaveLength(1);
    expect(result.special_announcements[0].scheduled_at).toBeNull();
    expect(result.special_resets).toEqual([]);
  });
  it("accepts the four action levels plus UNKNOWN", () => {
    expect(["GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"].map(actionLevel)).toEqual([
      "GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"
    ]);
    expect(actionLevel("CONFIRMED")).toBe("UNKNOWN");
  });

  it("does not expose a confidence field", () => {
    const result = parseRadar({
      version: "2.0.0-alpha.1",
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
