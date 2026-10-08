import { describe, expect, it } from "vitest";
import {
  actionCopy,
  anchorLimitationLabel,
  compactBasis,
  downgradePredictionOnRefreshFailure,
  historyMilestones,
  historyRevisionLabel,
  outputAvailabilityLabel,
  predictionHealthLabel,
  predictionIsNotCurrent,
  predictionStateLabel,
  predictionTimeSummary,
  tone
} from "./radar-ui";
import type { PredictionLine, PredictionProjection } from "./api";

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
        EXTRA_FULL: line("EXTRA_FULL", "current"),
        BANKED: line("BANKED", "rejected")
      }
    };

    const downgraded = downgradePredictionOnRefreshFailure(prediction);

    expect(downgraded?.health.refresh_failed).toBe(true);
    expect(downgraded?.lines.NORMAL_WEEKLY.state).toBe("stale");
    expect(downgraded?.lines.EXTRA_FULL.current_advice_eligible).toBe(false);
    expect(downgraded?.lines.BANKED.state).toBe("rejected");
    expect(downgraded?.lines.BANKED.health_state).toBe("stale");
  });
});
