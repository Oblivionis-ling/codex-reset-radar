import { describe, expect, it } from "vitest";
import {
  actionCopy,
  anchorLimitationLabel,
  compactBasis,
  downgradePredictionOnRefreshFailure,
  formatTime,
  historyMilestones,
  historyRevisionLabel,
  outputAvailabilityLabel,
  predictionHealthLabel,
  predictionIsNotCurrent,
  predictionReasonLabel,
  predictionStateLabel,
  predictionStatusProjectionNotes,
  predictionTimeSummary,
  tone
} from "./radar-ui";
import type { PredictionLine, PredictionProjection, PredictionStatusProjection } from "./api";

function statusProjection(overrides: Partial<PredictionStatusProjection> = {}): PredictionStatusProjection {
  return {
    capability: { implementation: "supported", source: "ledger_v2" },
    run: { state: "succeeded", run_id: "run-1", attempt_id: "attempt-1", finished_at: null, reason_code: null },
    result: { state: "accepted", reason_code: "VALID", summary: null },
    last_known: null,
    normal: null,
    history_status: "backfilled",
    ...overrides
  };
}

function predictionLine(overrides: Partial<PredictionLine> = {}): PredictionLine {
  return {
    target: "EXTRA_FULL",
    record_id: null,
    ledger_seq: null,
    is_synthetic: null,
    record_kind: "prediction",
    state: "unknown",
    form: "unknown",
    predicted_start: null,
    predicted_end: null,
    expression: null,
    date_boundaries: null,
    relative_expression: null,
    relative_anchor: null,
    unresolved_reason: null,
    source_timezone: null,
    precision: null,
    time_basis: null,
    scope: null,
    anchor_limitation: null,
    anchor_time_basis: null,
    method: null,
    basis: null,
    reason: null,
    updated_at: null,
    updated_at_source: null,
    validity_state: "unknown",
    valid_until: null,
    health_state: "unknown",
    health_reason: null,
    series_id: null,
    forecast_id: null,
    revision: null,
    question_revision: null,
    question_version: null,
    forecast_revision: null,
    forecast_version: null,
    output_revision: null,
    target_output_id: null,
    previous_id: null,
    output_available_at: null,
    output_availability_kind: null,
    current_advice_eligible: false,
    eligibility_reason: null,
    ...overrides
  };
}

describe("V2 product tones", () => {
  it("renders UNKNOWN as white rather than green", () => {
    expect(tone("UNKNOWN")).toBe("unknown");
    expect(actionCopy("UNKNOWN")).toContain("无法判断");
  });

  it("keeps the four action levels distinct", () => {
    expect(["GREEN", "YELLOW", "ORANGE", "RED"].map((value) => tone(value as never))).toEqual([
      "green", "yellow", "orange", "red"
    ]);
  });

  it("uses the Full-anchor reason for Normal's empty state, while keeping backfill separate", () => {
    const noAnchor = predictionLine({
      target: "NORMAL_WEEKLY",
      state: "waiting_for_verified_history",
      reason: "Normal 参考暂不可计算",
      unresolved_reason: "NO_BUSINESS_FULL_ANCHOR"
    });
    const noAnchorReasonCodeFallback = predictionLine({
      target: "NORMAL_WEEKLY",
      state: "waiting_for_verified_history",
      reason: "NO_BUSINESS_FULL_ANCHOR"
    });
    const oneSidedWithAnchorReason = predictionLine({
      target: "NORMAL_WEEKLY",
      state: "baseline",
      unresolved_reason: "NO_BUSINESS_FULL_ANCHOR",
      predicted_start: "2026-10-16T10:00:00Z"
    });
    const computedButNotBackfilled = predictionLine({
      target: "NORMAL_WEEKLY",
      state: "not_backfilled",
      reason: "NORMAL_VERSION_NOT_RECORDED",
      form: "point",
      expression: "2026-10-16T10:00:00Z",
      predicted_start: "2026-10-16T10:00:00Z"
    });
    const projectedNoAnchor = predictionLine({
      target: "NORMAL_WEEKLY",
      state: "waiting_for_verified_history",
      unresolved_reason: "NO_BUSINESS_FULL_ANCHOR",
      status_projection: statusProjection({
        run: { state: "not_started", run_id: null, attempt_id: null, finished_at: null, reason_code: null },
        result: { state: "unavailable", reason_code: "NO_BUSINESS_FULL_ANCHOR", summary: null },
        normal: { helper_status: "waiting_for_verified_history", calculation_status: "no_business_full_anchor" },
        history_status: "not_backfilled"
      })
    });
    const canonicalOnlyNoAnchor = predictionLine({
      target: "NORMAL_WEEKLY",
      state: "waiting_for_verified_history",
      status_projection: statusProjection({
        result: { state: "unavailable", reason_code: null, summary: "缺少锚点" },
        normal: { helper_status: "waiting_for_verified_history", calculation_status: "no_business_full_anchor" }
      })
    });
    const canonicalReasonNoAnchor = predictionLine({
      target: "NORMAL_WEEKLY",
      state: "waiting_for_verified_history",
      status_projection: statusProjection({
        result: { state: "unavailable", reason_code: "NO_BUSINESS_FULL_ANCHOR", summary: null },
        normal: { helper_status: "waiting_for_verified_history", calculation_status: "unresolved" }
      })
    });
    const oneSidedCanonicalNoAnchor = predictionLine({
      target: "NORMAL_WEEKLY",
      state: "baseline",
      predicted_start: "2026-10-16T10:00:00Z",
      status_projection: statusProjection({
        result: { state: "unavailable", reason_code: "NO_BUSINESS_FULL_ANCHOR", summary: null },
        normal: { helper_status: "waiting_for_verified_history", calculation_status: "no_business_full_anchor" }
      })
    });

    expect(predictionTimeSummary(noAnchor)).toBe("暂无可计算的周额度参考：缺少可用的Full锚点。");
    expect(noAnchor.predicted_start).toBeNull();
    expect(noAnchor.predicted_end).toBeNull();
    expect(predictionTimeSummary(noAnchorReasonCodeFallback)).toBe("暂无可计算的周额度参考：缺少可用的Full锚点。");
    expect(predictionTimeSummary(oneSidedWithAnchorReason)).not.toContain("暂无可计算的周额度参考");
    expect(predictionTimeSummary(oneSidedWithAnchorReason)).toContain("已知起点");
    expect(predictionTimeSummary(computedButNotBackfilled)).not.toContain("暂无可计算的周额度参考");
    expect(predictionTimeSummary(computedButNotBackfilled)).toContain("2026");
    expect(predictionStateLabel("not_backfilled")).toBe("历史版本未回填");
    const normalNotes = predictionStatusProjectionNotes(projectedNoAnchor).join(" · ");
    expect(normalNotes).toContain("Normal helper：等待可信历史");
    expect(normalNotes).toContain("Normal 计算：缺少可用的 Full 锚点");
    expect(normalNotes).toContain("Normal 历史：历史版本未回填");
    expect(predictionTimeSummary(canonicalOnlyNoAnchor)).toBe("暂无可计算的周额度参考：缺少可用的Full锚点。");
    expect(predictionTimeSummary(canonicalReasonNoAnchor)).toBe("暂无可计算的周额度参考：缺少可用的Full锚点。");
    expect(predictionTimeSummary(oneSidedCanonicalNoAnchor)).not.toContain("暂无可计算的周额度参考");
    expect(predictionTimeSummary(oneSidedCanonicalNoAnchor)).toContain("已知起点");
  });

  it("labels attempt, timeout, UNKNOWN, and legacy states without inferring from missing dates", () => {
    const expected: [string, string][] = [
      ["not_attempted", "尚未尝试"],
      ["pending", "正在生成"],
      ["timeout", "本次请求超时"],
      ["failed", "本次生成或处理失败"],
      ["cancelled", "本次请求已取消"],
      ["unknown_valid", "合法 UNKNOWN"],
      ["not_implemented", "当前记录未提供此目标"]
    ];

    for (const [state, label] of expected) {
      const line = predictionLine({ state, current_advice_eligible: true });
      expect(predictionStateLabel(state)).toBe(label);
      expect(predictionIsNotCurrent(line)).toBe(true);
    }
    expect(predictionReasonLabel("UNKNOWN_VALID")).toContain("通过校验");
    expect(predictionReasonLabel("LEGACY_TARGET_NOT_IMPLEMENTED")).toContain("旧记录");
    expect(predictionTimeSummary(predictionLine({ state: "timeout" }))).toContain("未返回可用日期");
    expect(predictionTimeSummary(predictionLine({ state: "not_attempted" }))).toContain("尚未生成");
  });

  it("keeps current-run failure dates empty and labels valid last-known dates as old", () => {
    const line = predictionLine({
      state: "timeout",
      predicted_start: "2026-10-07T10:00:00Z",
      current_advice_eligible: true,
      status_projection: statusProjection({
        run: { state: "timeout", run_id: "run-18", attempt_id: "attempt-18", finished_at: null, reason_code: "MODEL_REQUEST_FAILED" },
        result: { state: "not_returned", reason_code: "MODEL_REQUEST_FAILED", summary: "本次 Judge 超时，未返回目标结果。" },
        last_known: {
          state: "valid",
          forecast_id: "forecast-old",
          series_id: "series-x",
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
            precision: "second"
          }
        }
      })
    });
    const notes = predictionStatusProjectionNotes(line).join(" · ");

    expect(predictionTimeSummary(line)).toBe("本次请求超时，未返回可用日期");
    expect(predictionIsNotCurrent(line)).toBe(true);
    expect(notes).toContain("本目标结果：本次未返回目标结果");
    expect(notes).toContain("最后已知结果（不是本次结果）");
    expect(notes).toContain("原日期 已知起点");
    expect(notes).toContain(formatTime("2026-10-11T10:00:00Z"));
    expect(notes).not.toContain(formatTime("2026-10-07T10:00:00Z"));
  });

  it("does not show old target dates after last-known expiry or cycle change", () => {
    const line = predictionLine({
      state: "failed",
      status_projection: statusProjection({
        run: { state: "failed", run_id: "run-19", attempt_id: "attempt-19", finished_at: null, reason_code: "MODEL_REQUEST_FAILED" },
        result: { state: "not_returned", reason_code: "MODEL_REQUEST_FAILED", summary: null },
        last_known: {
          state: "cycle_changed",
          forecast_id: "forecast-old",
          series_id: "series-x",
          revision: 3,
          origin_judgement_id: 5,
          valid_until: "2026-10-08T00:00:00Z",
          cycle_id: 2,
          reason_code: "CYCLE_CHANGED",
          forecast: null
        }
      })
    });
    const notes = predictionStatusProjectionNotes(line).join(" · ");

    expect(notes).toContain("完整重置周期已变化");
    expect(notes).not.toContain(formatTime("2026-10-07T10:00:00Z"));
    expect(predictionTimeSummary(line)).toBe("本次请求失败，未返回可用日期");
  });

  it("keeps conservative line-state gates while allowing a current line with accepted target result", () => {
    const current = predictionLine({
      state: "current",
      current_advice_eligible: true,
      validity_state: "valid",
      health_state: "healthy",
      status_projection: statusProjection()
    });
    expect(predictionIsNotCurrent(current)).toBe(false);

    for (const state of ["accepted", "stale", "expired", "rejected"]) {
      expect(predictionIsNotCurrent({ ...current, state })).toBe(true);
    }
    expect(predictionIsNotCurrent({
      ...current,
      status_projection: statusProjection({
        result: { state: "rejected", reason_code: "OFFICIAL_PLAN_NOT_VERIFIED", summary: null }
      })
    })).toBe(true);
    expect(predictionIsNotCurrent({
      ...current,
      status_projection: statusProjection({
        run: { state: "pending", run_id: "run-2", attempt_id: "attempt-2", finished_at: null, reason_code: null }
      })
    })).toBe(true);
    const contradictoryRun = {
      ...current,
      predicted_start: "2026-10-11T10:00:00Z",
      status_projection: statusProjection({
        run: { state: "timeout", run_id: "run-3", attempt_id: "attempt-3", finished_at: null, reason_code: "MODEL_REQUEST_FAILED" }
      })
    };
    expect(predictionTimeSummary(contradictoryRun)).toBe("本次请求超时，未返回可用日期");
  });

  it("keeps a last-known valid line distinct from an expired line", () => {
    const lastKnown = predictionLine({
      state: "stale",
      validity_state: "valid",
      current_advice_eligible: false,
      valid_until: "2026-10-12T00:00:00Z",
      predicted_start: "2026-10-11T10:00:00Z"
    });
    const expired = predictionLine({
      state: "expired",
      validity_state: "expired",
      current_advice_eligible: false,
      valid_until: "2026-10-08T00:00:00Z",
      predicted_start: "2026-10-07T10:00:00Z"
    });

    expect(predictionStateLabel(lastKnown.state)).toContain("不作为当前建议");
    expect(predictionStateLabel(lastKnown.validity_state)).toBe("有效");
    expect(predictionIsNotCurrent(lastKnown)).toBe(true);
    expect(predictionStateLabel(expired.state)).toBe("已过有效期");
    expect(predictionStateLabel(expired.validity_state)).toBe("已过有效期");
    expect(predictionIsNotCurrent(expired)).toBe(true);
  });

  it("keeps a long signal basis available without expanding the first screen", () => {
    const long = `第一句是当前窗口的摘要。${"后续完整依据".repeat(60)}`;
    expect(compactBasis(long)).toBe("第一句是当前窗口的摘要。");
  });

  it("shows a date as an all-day envelope, never as a midnight execution promise", () => {
    const summary = predictionTimeSummary(predictionLine({
      form: "date",
      precision: "day",
      expression: "2026-10-10",
      date_boundaries: "closed_conservative_local_day_envelope_not_execution_instants",
      predicted_start: "2026-10-10T00:00:00Z",
      predicted_end: "2026-10-11T00:00:00Z"
    }));

    expect(summary).toContain("2026-10-10");
    expect(summary).toContain("日期粒度／仅整日包络，非午夜执行承诺");
    expect(summary).not.toContain("2026-10-11");
  });

  it("keeps legacy post-time proxies visibly unverified instead of presenting them as point predictions", () => {
    const summary = predictionTimeSummary(predictionLine({
      target: "NORMAL_WEEKLY",
      state: "baseline",
      form: "proxy",
      precision: "unknown",
      predicted_start: "2026-10-09T08:00:00Z",
      predicted_end: "2026-10-09T08:00:00Z",
      anchor_limitation: "POST_TIME_PROXY_NOT_ACTUAL_START"
    }));

    expect(summary).toContain("发帖时间代理");
    expect(summary).toContain("非实际开始时刻");
    expect(summary).toContain("未核实为准确执行点");
    expect(summary).not.toMatch(/^点值/);
    expect(anchorLimitationLabel("POST_TIME_PROXY_NOT_ACTUAL_START")).toContain("实际执行开始未核实");
  });

  it("retains unresolved relative expression, and labels a one-sided value as a boundary", () => {
    const relative = predictionTimeSummary(predictionLine({
      form: "relative",
      expression: "今晚",
      relative_expression: "今晚",
      relative_anchor: "2026-10-09T08:00:00Z",
      unresolved_reason: "TIMEZONE_NOT_STATED"
    }));
    const oneSided = predictionTimeSummary(predictionLine({
      form: "start_only",
      predicted_start: "2026-10-10T10:00:00Z"
    }));

    expect(relative).toContain("今晚");
    expect(relative).toContain("未解析");
    expect(oneSided).toContain("已知起点");
    expect(oneSided).not.toContain("点值");
  });

  it("describes observed output availability as an upper bound, not an exact first-seen time", () => {
    expect(outputAvailabilityLabel("2026-10-09T08:15:00Z")).toContain("至迟于");
    expect(outputAvailabilityLabel("2026-10-09T08:15:00Z")).toContain("不代表首次可用");
  });

  it("blocks failed, rejected, partial and invalid states from current advice", () => {
    for (const state of ["failed", "rejected", "partial", "invalid"]) {
      expect(predictionIsNotCurrent(predictionLine({ state, current_advice_eligible: true }))).toBe(true);
    }
    expect(predictionStateLabel("rejected")).toContain("拒收");
    expect(predictionStateLabel("unknown")).toContain("未知");
    expect(predictionHealthLabel("STALE")).toContain("陈旧");
  });

  it("selects chronology milestones in returned ledger order, not by quality", () => {
    expect(historyMilestones(["v1", "v2", "v3", "v4", "v5"])).toEqual(["v1", "v3", "v5"]);
    expect(historyMilestones(["v1", "v2", "v3", "v4"])).toEqual(["v1", "v2", "v4"]);
  });

  it("labels the question and target-output revisions independently across retries", () => {
    const firstAttempt = predictionLine({
      revision: 4,
      question_revision: 4,
      question_version: "question-4",
      output_revision: 1,
      target_output_id: "judgement-10:EXTRA_FULL"
    });
    const retry = predictionLine({
      revision: 4,
      question_revision: 4,
      question_version: "question-4",
      output_revision: 2,
      target_output_id: "judgement-11:EXTRA_FULL"
    });

    expect(historyRevisionLabel(firstAttempt)).toBe("问题修订 4 / 输出修订 1");
    expect(historyRevisionLabel(retry)).toBe("问题修订 4 / 输出修订 2");
  });

  it("uses the shared refresh-failure downgrade for every prediction line", () => {
    const line = (target: PredictionLine["target"], state: string): PredictionLine => predictionLine({
      target,
      state,
      current_advice_eligible: true,
      validity_state: "valid",
      health_state: "healthy"
    });
    const prediction: PredictionProjection = {
      version: "prediction-three-lines-v1",
      algorithm_version: null,
      state: "partial",
      capabilities: {
        normal_weekly: true,
        extra_full: true,
        banked: true,
        history: false,
        normal_history: false,
        ledger_history_readable: true,
        model_targets: ["EXTRA_FULL", "BANKED"]
      },
      health: {
        validation_valid: true,
        validation_reason: "VALID",
        current_data_health: "HEALTHY",
        generation_data_health: "HEALTHY",
        generation_health_reason: null,
        judgement_usable: true,
        current_collector_health: {},
        refresh_failed: false,
        refresh_failure_reason: null,
        ledger: {}
      },
      lines: {
        NORMAL_WEEKLY: line("NORMAL_WEEKLY", "baseline"),
        EXTRA_FULL: {
          ...line("EXTRA_FULL", "current"),
          predicted_start: "2026-10-11T10:00:00Z",
          valid_until: "2026-10-12T00:00:00Z",
          status_projection: statusProjection()
        },
        BANKED: { ...line("BANKED", "rejected"), validity_state: "expired", valid_until: "2026-10-08T00:00:00Z" }
      }
    };

    const downgraded = downgradePredictionOnRefreshFailure(prediction);

    expect(downgraded?.health.refresh_failed).toBe(true);
    expect(downgraded?.lines.NORMAL_WEEKLY.state).toBe("stale");
    expect(downgraded?.lines.EXTRA_FULL.current_advice_eligible).toBe(false);
    expect(downgraded?.lines.EXTRA_FULL.status_projection?.result?.state).toBe("accepted");
    expect(downgraded ? predictionIsNotCurrent(downgraded.lines.EXTRA_FULL) : false).toBe(true);
    expect(downgraded?.lines.EXTRA_FULL.predicted_start).toBe("2026-10-11T10:00:00Z");
    expect(downgraded?.lines.EXTRA_FULL.valid_until).toBe("2026-10-12T00:00:00Z");
    expect(downgraded?.lines.BANKED.state).toBe("rejected");
    expect(downgraded?.lines.BANKED.validity_state).toBe("expired");
    expect(downgraded?.lines.BANKED.valid_until).toBe("2026-10-08T00:00:00Z");
    expect(downgraded?.lines.BANKED.health_state).toBe("stale");
  });
});
