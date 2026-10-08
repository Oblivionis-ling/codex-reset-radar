import { describe, expect, it } from "vitest";
import { actionLevel, parsePredictionHistory, parseRadar, PREDICTION_API_VERSION } from "./api";

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
    expect(result.prediction).toBeNull();
  });

  it("parses the versioned three-target projection without collapsing partial/rejected states", () => {
    const result = parseRadar({
      action_level: "UNKNOWN",
      prediction: {
        version: PREDICTION_API_VERSION,
        algorithm_version: "three-lines-time-v1",
        state: "partial",
        capabilities: { normal_weekly: true, extra_full: true, banked: true, history: true },
        health: {
          validation_valid: true,
          validation_reason: "VALID",
          current_data_health: "HEALTHY",
          generation_data_health: "HEALTHY",
          judgement_usable: true,
          current_collector_health: { profile_monitor: { state: "healthy", reason: "FRESH" } }
        },
        lines: {
          NORMAL_WEEKLY: { state: "baseline", form: "date", expression: "2026-10-10",
            date_boundaries: "closed_conservative_local_day_envelope_not_execution_instants" },
          EXTRA_FULL: { state: "ready", form: "relative", expression: "今晚", relative_anchor_at: "2026-10-09T08:00:00Z",
            unresolved_reason: "TIMEZONE_NOT_STATED", output_available_at: "2026-10-09T08:15:00Z", current_advice_eligible: true },
          BANKED: { state: "rejected", reason: "MISSING_TARGET", current_advice_eligible: false }
        }
      }
    });

    expect(result.prediction?.version).toBe(PREDICTION_API_VERSION);
    expect(result.prediction?.state).toBe("partial");
    expect(result.prediction?.lines.NORMAL_WEEKLY.date_boundaries).toContain("not_execution_instants");
    expect(result.prediction?.lines.EXTRA_FULL.relative_anchor).toBe("2026-10-09T08:00:00Z");
    expect(result.prediction?.lines.EXTRA_FULL.unresolved_reason).toBe("TIMEZONE_NOT_STATED");
    expect(result.prediction?.lines.BANKED.state).toBe("rejected");
    expect(result.prediction?.health.current_collector_health.profile_monitor).toEqual({ state: "healthy", reason: "FRESH" });
  });

  it("preserves history chronology and the server truncation signal", () => {
    const items = [
      { record_id: "record-10", ledger_seq: 10, is_synthetic: true,
        question_version: "question-4", question_revision: 4, output_revision: 1,
        target_output_id: "judgement-10:EXTRA_FULL", resolved_prediction_form: "point",
        predicted_start: "2026-10-11T10:00:00Z", method: "model_inference" },
      { record_id: "record-20", ledger_seq: 20, is_synthetic: true,
        question_version: "question-4", question_revision: 4, output_revision: 2,
        target_output_id: "judgement-11:EXTRA_FULL", resolved_prediction_form: "range",
        predicted_start: "2026-10-12T10:00:00Z", predicted_end: "2026-10-12T12:00:00Z",
        method: "official_time_extraction" }
    ];
    const history = parsePredictionHistory({
      version: PREDICTION_API_VERSION,
      state: "ready",
      items,
      first_items: [items[0]],
      last_items: [items[1]],
      total_count: 11,
      truncated: true
    }, "EXTRA_FULL", "series-x");

    expect(history.items.map((line) => [line.question_revision, line.output_revision])).toEqual([[4, 1], [4, 2]]);
    expect(history.items.map((line) => line.target_output_id)).toEqual([
      "judgement-10:EXTRA_FULL", "judgement-11:EXTRA_FULL"
    ]);
    expect(history.items.map((line) => [line.form, line.predicted_start, line.method])).toEqual([
      ["point", "2026-10-11T10:00:00Z", "model_inference"],
      ["range", "2026-10-12T10:00:00Z", "official_time_extraction"]
    ]);
    expect(history.first_items.map((line) => line.ledger_seq)).toEqual([10]);
    expect(history.last_items.map((line) => line.output_revision)).toEqual([2]);
    expect(history.first_items[0].is_synthetic).toBe(true);
    expect(history.total_count).toBe(11);
    expect(history.truncated).toBe(true);
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
