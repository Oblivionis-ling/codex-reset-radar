import { describe, expect, it } from "vitest";
import { actionLevel, parsePredictionHistory, parseRadar, PREDICTION_API_VERSION } from "./api";

function predictionFixture(lines: Record<string, unknown>) {
  return {
    version: PREDICTION_API_VERSION,
    state: "partial",
    capabilities: { normal_weekly: true, extra_full: true, banked: true, history: true },
    health: {
      validation_valid: true,
      validation_reason: "VALID",
      current_data_health: "HEALTHY",
      generation_data_health: "HEALTHY",
      judgement_usable: true
    },
    lines
  };
}

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

  it("preserves supported not-attempted and pending states when dates are absent", () => {
    const result = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: {
          state: "waiting_for_verified_history",
          reason: "暂无可计算的周额度参考",
          unresolved_reason: "NO_BUSINESS_FULL_ANCHOR"
        },
        EXTRA_FULL: { state: "not_attempted" },
        BANKED: { state: "pending" }
      })
    });

    expect(result.prediction?.capabilities.extra_full).toBe(true);
    expect(result.prediction?.lines.EXTRA_FULL.state).toBe("not_attempted");
    expect(result.prediction?.lines.EXTRA_FULL.predicted_start).toBeNull();
    expect(result.prediction?.lines.BANKED.state).toBe("pending");
    expect(result.prediction?.lines.NORMAL_WEEKLY.reason).toBe("暂无可计算的周额度参考");
    expect(result.prediction?.lines.NORMAL_WEEKLY.unresolved_reason).toBe("NO_BUSINESS_FULL_ANCHOR");
  });

  it("keeps a rejected Full target separate from a valid UNKNOWN Banked target", () => {
    const result = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "waiting_for_verified_history", reason: "NO_BUSINESS_FULL_ANCHOR" },
        EXTRA_FULL: { state: "rejected", reason: "OFFICIAL_PLAN_NOT_VERIFIED" },
        BANKED: { state: "unknown_valid", reason: "UNKNOWN_VALID" }
      })
    });

    expect(result.prediction?.state).toBe("partial");
    expect(result.prediction?.lines.EXTRA_FULL.state).toBe("rejected");
    expect(result.prediction?.lines.EXTRA_FULL.predicted_start).toBeNull();
    expect(result.prediction?.lines.BANKED.state).toBe("unknown_valid");
    expect(result.prediction?.lines.BANKED.reason).toBe("UNKNOWN_VALID");
  });

  it("does not collapse a modern timeout into a genuine legacy capability gap", () => {
    const timeout = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "waiting_for_verified_history", reason: "NO_BUSINESS_FULL_ANCHOR" },
        EXTRA_FULL: { state: "timeout", reason: "MODEL_REQUEST_FAILED" },
        BANKED: { state: "timeout", reason: "MODEL_REQUEST_FAILED" }
      })
    });
    const legacy = parseRadar({
      action_level: "UNKNOWN",
      prediction: {
        ...predictionFixture({
          NORMAL_WEEKLY: { state: "waiting_for_verified_history", reason: "NO_BUSINESS_FULL_ANCHOR" },
          EXTRA_FULL: { state: "not_implemented", reason: "LEGACY_TARGET_NOT_IMPLEMENTED" },
          BANKED: { state: "not_implemented", reason: "LEGACY_TARGET_NOT_IMPLEMENTED" }
        }),
        capabilities: { normal_weekly: true, extra_full: false, banked: false, history: true }
      }
    });

    expect(timeout.prediction?.lines.EXTRA_FULL.state).toBe("timeout");
    expect(timeout.prediction?.lines.BANKED.state).toBe("timeout");
    expect(legacy.prediction?.lines.EXTRA_FULL.state).toBe("not_implemented");
    expect(legacy.prediction?.lines.EXTRA_FULL.reason).toBe("LEGACY_TARGET_NOT_IMPLEMENTED");
  });

  it("keeps last-known validity and expiry fields distinct", () => {
    const result = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "baseline", validity_state: "valid", predicted_start: "2026-10-16T10:00:00Z" },
        EXTRA_FULL: { state: "stale", validity_state: "valid", valid_until: "2026-10-12T00:00:00Z", predicted_start: "2026-10-11T10:00:00Z" },
        BANKED: { state: "expired", validity_state: "expired", valid_until: "2026-10-08T00:00:00Z", predicted_start: "2026-10-07T10:00:00Z" }
      })
    });

    expect(result.prediction?.lines.EXTRA_FULL.state).toBe("stale");
    expect(result.prediction?.lines.EXTRA_FULL.validity_state).toBe("valid");
    expect(result.prediction?.lines.EXTRA_FULL.valid_until).toBe("2026-10-12T00:00:00Z");
    expect(result.prediction?.lines.BANKED.state).toBe("expired");
    expect(result.prediction?.lines.BANKED.validity_state).toBe("expired");
    expect(result.prediction?.lines.BANKED.valid_until).toBe("2026-10-08T00:00:00Z");
  });

  it("normalizes the optional shared run/result projection on API and history lines", () => {
    const status_projection = {
      capability: { implementation: "supported", source: "ledger_v2" },
      run: { state: "timeout", run_id: "run-18", attempt_id: "attempt-18", finished_at: "2026-10-09T10:00:00Z", reason_code: "MODEL_REQUEST_FAILED" },
      result: { state: "not_returned", reason_code: "MODEL_REQUEST_FAILED", summary: "本次 Judge 超时，未返回目标结果。" },
      last_known: {
        state: "valid",
        forecast_id: "forecast-record-7",
        series_id: "series-full-4",
        revision: 4,
        origin_judgement_id: 7,
        valid_until: "2026-10-12T00:00:00Z",
        cycle_id: 3,
        reason_code: "VALID",
        forecast: {
          prediction_form: "start_only",
          predicted_start: "2026-10-11T10:00:00Z",
          predicted_end: null,
          time_basis: "official_planned",
          precision: "second",
          reason: "not projected to Web",
          reasoning_content: "not projected to Web",
          raw_response: "not projected to Web"
        }
      },
      history_status: "backfilled"
    };
    const current = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: {
          state: "waiting_for_verified_history",
          unresolved_reason: "NO_BUSINESS_FULL_ANCHOR",
          status_projection: {
            capability: { implementation: "supported", source: "ledger_v2" },
            run: { state: "not_started", run_id: null, attempt_id: null, finished_at: null, reason_code: null },
            result: { state: "unavailable", reason_code: "NO_BUSINESS_FULL_ANCHOR", summary: "缺少 Full 锚点" },
            last_known: null,
            normal: { helper_status: "waiting_for_verified_history", calculation_status: "no_business_full_anchor" },
            history_status: "not_backfilled"
          }
        },
        EXTRA_FULL: { state: "not_implemented", status_projection },
        BANKED: { state: "not_implemented", status_projection: { ...status_projection, run: { ...status_projection.run } } }
      })
    });
    const history = parsePredictionHistory({
      version: PREDICTION_API_VERSION,
      state: "ready",
      attempt_count_basis: "target_projection_not_http_count",
      items: [{ state: "not_implemented", status_projection }]
    }, "EXTRA_FULL", "series-full-4");

    expect(current.prediction?.lines.EXTRA_FULL.status_projection?.run).toEqual({
      state: "timeout", run_id: "run-18", attempt_id: "attempt-18",
      finished_at: "2026-10-09T10:00:00Z", reason_code: "MODEL_REQUEST_FAILED"
    });
    expect(current.prediction?.lines.BANKED.status_projection?.run?.attempt_id)
      .toBe(current.prediction?.lines.EXTRA_FULL.status_projection?.run?.attempt_id);
    expect(current.prediction?.lines.EXTRA_FULL.status_projection?.last_known).toMatchObject({
      state: "valid",
      forecast_id: "forecast-record-7",
      revision: 4,
      cycle_id: 3,
      valid_until: "2026-10-12T00:00:00Z",
      forecast: {
        predicted_start: "2026-10-11T10:00:00Z",
        predicted_end: null,
        prediction_form: "start_only"
      }
    });
    expect(current.prediction?.lines.EXTRA_FULL.status_projection?.last_known?.forecast)
      .not.toHaveProperty("reasoning_content");
    expect(current.prediction?.lines.EXTRA_FULL.status_projection?.last_known?.forecast)
      .not.toHaveProperty("raw_response");
    expect(current.prediction?.lines.NORMAL_WEEKLY.status_projection?.normal?.calculation_status).toBe("no_business_full_anchor");
    expect(current.prediction?.lines.NORMAL_WEEKLY.status_projection?.normal?.helper_status).toBe("waiting_for_verified_history");
    expect(current.prediction?.lines.NORMAL_WEEKLY.status_projection?.history_status).toBe("not_backfilled");
    expect(history.items[0].status_projection?.run?.attempt_id).toBe("attempt-18");
    expect(history.attempt_count_basis).toBe("target_projection_not_http_count");
  });

  it("retains only valid last-known target dates and drops expired or cycle-changed dates", () => {
    const result = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "unknown" },
        EXTRA_FULL: {
          state: "timeout",
          status_projection: {
            capability: { implementation: "supported", source: "ledger_v2" },
            run: { state: "timeout", run_id: "run-18", attempt_id: "attempt-18", finished_at: null, reason_code: "MODEL_REQUEST_FAILED" },
            result: { state: "not_returned", reason_code: "MODEL_REQUEST_FAILED", summary: null },
            last_known: {
              state: "valid", forecast_id: "forecast-valid", series_id: "series-x", revision: 5,
              origin_judgement_id: 9, valid_until: "2026-10-12T00:00:00Z", cycle_id: 3, reason_code: "VALID",
              forecast: { prediction_form: "point", predicted_start: "2026-10-11T10:00:00Z", predicted_end: null }
            },
            history_status: "backfilled"
          }
        },
        BANKED: {
          state: "failed",
          status_projection: {
            capability: { implementation: "supported", source: "ledger_v2" },
            run: { state: "failed", run_id: "run-18", attempt_id: "attempt-18", finished_at: null, reason_code: "MODEL_REQUEST_FAILED" },
            result: { state: "not_returned", reason_code: "MODEL_REQUEST_FAILED", summary: null },
            last_known: {
              state: "expired", forecast_id: "forecast-old", series_id: "series-y", revision: 2,
              origin_judgement_id: 4, valid_until: "2026-10-08T00:00:00Z", cycle_id: 2, reason_code: "EXPIRED",
              forecast: { prediction_form: "point", predicted_start: "2026-10-07T10:00:00Z", predicted_end: null }
            },
            history_status: "backfilled"
          }
        }
      })
    });

    expect(result.prediction?.lines.EXTRA_FULL.status_projection?.last_known?.forecast?.predicted_start)
      .toBe("2026-10-11T10:00:00Z");
    expect(result.prediction?.lines.BANKED.status_projection?.last_known?.state).toBe("expired");
    expect(result.prediction?.lines.BANKED.status_projection?.last_known?.forecast).toBeNull();
  });

  it("bounds identifiers and summaries and fails closed for a malformed present projection", () => {
    const result = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "unknown" },
        EXTRA_FULL: {
          state: "current",
          current_advice_eligible: true,
          predicted_start: "2026-10-11T10:00:00Z",
          status_projection: {
            capability: { implementation: "supported", source: "ledger_v2" },
            run: { state: "succeeded", run_id: "<img src=x>", attempt_id: "a".repeat(129), finished_at: null, reason_code: null },
            result: { state: "accepted", reason_code: "VALID", summary: "x".repeat(300) },
            last_known: null,
            history_status: "backfilled"
          }
        },
        BANKED: { state: "unknown" }
      })
    });
    const projection = result.prediction?.lines.EXTRA_FULL.status_projection;

    expect(projection?.capability?.implementation).toBe("supported");
    expect(projection?.run?.state).toBe("succeeded");
    expect(projection?.run?.run_id).toBeNull();
    expect(projection?.run?.attempt_id).toBeNull();
    expect(projection?.result?.reason_code).toBe("VALID");
    expect(projection?.result?.summary).toHaveLength(240);

    const malformed = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "unknown" },
        EXTRA_FULL: {
          state: "current", current_advice_eligible: true, predicted_start: "2026-10-11T10:00:00Z",
          status_projection: { capability: { implementation: "supported", source: "ledger_v2" }, run: { state: "pending" } }
        },
        BANKED: { state: "unknown" }
      })
    });
    expect(malformed.prediction?.lines.EXTRA_FULL.status_projection?.result?.state).toBe("unavailable");
    expect(malformed.prediction?.lines.EXTRA_FULL.status_projection?.result?.reason_code)
      .toBe("PREDICTION_STATUS_CONTRACT_ERROR");
  });

  it("fails closed for obvious model status conflicts but accepts Normal helper output without a model run", () => {
    const conflictingModel = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "unknown" },
        EXTRA_FULL: {
          state: "current", current_advice_eligible: true, predicted_start: "2026-10-11T10:00:00Z",
          status_projection: {
            capability: { implementation: "supported", source: "ledger_v2" },
            run: { state: "timeout", run_id: "run-1", attempt_id: "attempt-1", finished_at: null, reason_code: "MODEL_REQUEST_FAILED" },
            result: { state: "accepted", reason_code: "VALID", summary: null },
            last_known: null,
            history_status: "backfilled"
          }
        },
        BANKED: { state: "unknown" }
      })
    });
    const contractErrorClaimingSuccess = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "unknown" },
        EXTRA_FULL: { state: "unknown" },
        BANKED: {
          state: "current", current_advice_eligible: true, predicted_start: "2026-10-11T10:00:00Z",
          status_projection: {
            capability: { implementation: "unknown", source: "contract_error" },
            run: { state: "unknown_terminal", run_id: null, attempt_id: null, finished_at: null, reason_code: "PREDICTION_STATUS_CONTRACT_ERROR" },
            result: { state: "accepted", reason_code: "VALID", summary: null },
            last_known: null,
            history_status: "unknown"
          }
        }
      })
    });
    const normalHelper = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: {
          state: "baseline", current_advice_eligible: true, predicted_start: "2026-10-16T10:00:00Z",
          status_projection: {
            capability: { implementation: "supported", source: "ledger_v2" },
            run: { state: "not_started", run_id: null, attempt_id: null, finished_at: null, reason_code: null },
            result: { state: "accepted", reason_code: "VALID", summary: null },
            last_known: null,
            normal: { helper_status: "calculated", calculation_status: "calculated" },
            history_status: "not_backfilled"
          }
        },
        EXTRA_FULL: { state: "unknown" },
        BANKED: { state: "unknown" }
      })
    });
    const legacyValueInImplementation = parseRadar({
      action_level: "UNKNOWN",
      prediction: predictionFixture({
        NORMAL_WEEKLY: { state: "unknown" },
        EXTRA_FULL: { state: "unknown" },
        BANKED: {
          state: "not_implemented",
          status_projection: {
            capability: { implementation: "legacy_undeclared", source: "legacy_undeclared" },
            run: { state: "not_started", run_id: null, attempt_id: null, finished_at: null, reason_code: null },
            result: { state: "legacy_missing", reason_code: "TARGET_NOT_IMPLEMENTED", summary: null },
            last_known: null,
            history_status: "unknown"
          }
        }
      })
    });

    expect(conflictingModel.prediction?.lines.EXTRA_FULL.status_projection?.result?.state).toBe("unavailable");
    expect(conflictingModel.prediction?.lines.EXTRA_FULL.status_projection?.result?.reason_code)
      .toBe("PREDICTION_STATUS_CONTRACT_ERROR");
    expect(contractErrorClaimingSuccess.prediction?.lines.BANKED.status_projection?.result?.state).toBe("unavailable");
    expect(normalHelper.prediction?.lines.NORMAL_WEEKLY.status_projection?.run?.state).toBe("not_started");
    expect(normalHelper.prediction?.lines.NORMAL_WEEKLY.status_projection?.result?.state).toBe("accepted");
    expect(normalHelper.prediction?.lines.NORMAL_WEEKLY.status_projection?.normal?.calculation_status).toBe("calculated");
    expect(legacyValueInImplementation.prediction?.lines.BANKED.status_projection?.result?.state).toBe("unavailable");
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
