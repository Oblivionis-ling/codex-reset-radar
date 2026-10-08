import type { ActionLevel, PredictionLine, PredictionProjection } from "./api";

export function tone(level: ActionLevel): string {
  return level.toLowerCase();
}

export function actionCopy(level: ActionLevel): string {
  const copy: Record<ActionLevel, string> = {
    GREEN: "正常使用",
    YELLOW: "开始关注，可以适当增加使用",
    ORANGE: "Reset 已比较临近，积极使用 Codex",
    RED: "强烈近期 Reset 信号，尽量消耗额度",
    UNKNOWN: "数据不足 / 当前无法判断"
  };
  return copy[level];
}

export function formatTime(value: string | null): string {
  if (!value) return "等待可信历史";
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toLocaleString("zh-CN", { hour12: false }) : "未知";
}

export function compactBasis(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  const firstSentence = normalized.match(/^.*?[。！？]/)?.[0]?.trim() ?? normalized;
  return firstSentence.length > 180 ? `${firstSentence.slice(0, 177)}…` : firstSentence;
}

export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function predictionMethodLabel(method: string | null, basis: string | null): string {
  if (method === "official_time_extraction") return "官方明确时间提取";
  if (method === "model_inference") return "模型推断";
  if (basis === "user_full_plus_7d") return "用户参考规则（非官方）";
  return method ?? "未说明";
}

export function predictionTimeSummary(line: PredictionLine): string {
  const form = line.form.toLowerCase();
  const expression = line.expression ?? line.relative_expression;
  const boundary = (value: string): string => formatTime(value);
  if (form === "proxy") {
    const start = line.predicted_start ? boundary(line.predicted_start) : null;
    const end = line.predicted_end ? boundary(line.predicted_end) : null;
    const proxyValue = expression ?? (start && end ? `${start} — ${end}` : start ?? end);
    return proxyValue
      ? `旧记录发帖时间代理：${proxyValue}（非实际开始时刻，未核实为准确执行点）`
      : "旧记录仅有发帖时间代理；实际开始时刻未核实";
  }
  const datePrecision = [form, line.precision?.toLowerCase() ?? ""]
    .some((value) => ["date", "day", "date_only", "calendar_day"].includes(value));
  const unresolved = Boolean(line.unresolved_reason) || (!line.predicted_start && !line.predicted_end);
  if (datePrecision) {
    const dateText = expression ?? [line.predicted_start, line.predicted_end].filter(Boolean).join(" — ");
    return dateText
      ? `${dateText}（日期粒度／仅整日包络，非午夜执行承诺）`
      : "未提供可信日期（日期粒度／仅整日包络，非午夜执行承诺）";
  }
  if (form === "relative") {
    if (unresolved) return `相对表达式未解析：${expression ?? "未提供原始表达"}`;
    const resolved = line.predicted_start && line.predicted_end
      ? `${boundary(line.predicted_start)} — ${boundary(line.predicted_end)}`
      : line.predicted_start ? `已知起点 ${boundary(line.predicted_start)}（终点未提供）`
        : line.predicted_end ? `已知终点 ${boundary(line.predicted_end)}（起点未提供）` : "未解析";
    return `${expression ? `相对表达式“${expression}” · ` : "相对时间 · "}${resolved}`;
  }
  if (unresolved && expression) {
    return `保留表达式但未解析：${expression}`;
  }
  const start = line.predicted_start ? boundary(line.predicted_start) : null;
  const end = line.predicted_end ? boundary(line.predicted_end) : null;
  if (form === "point" && start && end) {
    return start === end ? start : `点值端点不一致：${start} / ${end}`;
  }
  if (form === "point" && (start || end)) return `点值：${start ?? end}`;
  if (start && end) return `${start} — ${end}`;
  if (start) return `已知起点：${start}；终点未提供`;
  if (end) return `已知终点：${end}；起点未提供`;
  return line.relative_expression ? `相对时间未解析：${line.relative_expression}` : "未提供可信时间";
}

export function outputAvailabilityLabel(value: string | null): string {
  return value
    ? `至迟于 ${formatTime(value)} 已可读取（观测上界，不代表首次可用）`
    : "输出可用时间未记录";
}

export function predictionIsNotCurrent(line: PredictionLine): boolean {
  const blocked = new Set(["unknown", "not_implemented", "stale", "data_stale", "expired", "invalid", "failed", "rejected", "partial", "pending", "accepted", "error"]);
  return line.current_advice_eligible !== true || [line.state, line.validity_state, line.health_state]
    .some((value) => blocked.has(value.toLowerCase()));
}

export function downgradePredictionOnRefreshFailure(prediction: PredictionProjection | null): PredictionProjection | null {
  if (!prediction) return null;
  const reason = "Backend 刷新失败，仅显示最后一次成功结果；不作为当前建议。";
  const lines = Object.fromEntries(Object.entries(prediction.lines).map(([target, line]) => [target, {
    ...line,
    state: ["ready", "current", "available", "baseline"].includes(line.state.toLowerCase()) ? "stale" : line.state,
    validity_state: ["valid", "ready", "current"].includes(line.validity_state.toLowerCase()) ? "stale" : line.validity_state,
    health_state: "stale",
    current_advice_eligible: false,
    eligibility_reason: reason,
    health_reason: reason
  }])) as PredictionProjection["lines"];
  return {
    ...prediction,
    health: {
      ...prediction.health,
      current_data_health: "STALE",
      judgement_usable: false,
      refresh_failed: true,
      refresh_failure_reason: reason
    },
    lines
  };
}

export function predictionStateLabel(state: string): string {
  const labels: Record<string, string> = {
    ready: "可用",
    current: "当前版本",
    historical: "账本历史输出（非当前状态）",
    baseline: "参考",
    partial: "部分目标有效（各目标分别判断）",
    unknown: "未知 / 当前无法判断",
    not_implemented: "旧数据未实现此目标",
    stale: "已陈旧，不作为当前建议",
    data_stale: "输入数据陈旧",
    invalid: "无效 / 校验未通过",
    rejected: "结果已拒收 / 校验未通过",
    failed: "生成或处理失败",
    error: "读取失败",
    expired: "已过有效期",
    not_backfilled: "参考可计算但版本未回填",
    pending: "等待处理",
    accepted: "目标输出已通过校验",
    valid: "有效",
    waiting_for_verified_history: "等待可信历史",
    waiting: "等待数据"
  };
  return labels[state.toLowerCase()] ?? state;
}

export function predictionHealthLabel(state: string | null): string {
  if (!state) return "未知";
  const labels: Record<string, string> = {
    healthy: "健康",
    ready: "健康",
    current: "当前",
    stale: "过期 / 陈旧",
    data_stale: "输入数据陈旧",
    unknown: "未知",
    failed: "失败",
    rejected: "已拒收",
    partial: "部分可用",
    not_applicable: "不适用"
  };
  return labels[state.toLowerCase()] ?? state;
}

export function predictionReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    VALID: "校验通过",
    EXPIRED: "结果已过有效期",
    INPUT_CHANGED: "输入或父帖上下文已变化",
    CYCLE_CHANGED: "完整重置周期已变化",
    CONTENT_RESTRICTED: "引用内容受限",
    NO_BUSINESS_FULL_ANCHOR: "没有可信的完整重置锚点",
    ANCHOR_TIME_UNRESOLVED: "锚点时间无法解析",
    MISSING_TARGET: "缺少此预测目标的输出",
    ALL_PREDICTION_TARGETS_REJECTED: "所有目标输出均被拒收",
    RELATIVE_EXPRESSION_UNRESOLVED: "相对时间表达尚未解析",
    TIMEZONE_NOT_STATED: "未确认时区",
    NORMAL_VERSION_NOT_RECORDED: "Normal 参考版本未回填",
    NOT_BACKFILLED: "参考尚未写入有版本账本",
    PREDICTION_NOT_RECORDED: "账本尚无此目标预测记录",
    OUTPUT_AVAILABILITY_PENDING: "等待记录输出可用观测时间",
    MODEL_REQUEST_FAILED: "模型请求失败",
    CLOCK_ANOMALY: "时钟顺序异常",
    PLAN_CANCELLED: "计划已取消",
    PLAN_COMPLETED: "计划已完成"
  };
  if (labels[reason]) return `${reason} · ${labels[reason]}`;
  return /^[A-Z][A-Z0-9_]+$/.test(reason) ? `${reason}（具体校验或健康原因码）` : reason;
}

export function anchorLimitationLabel(value: string): string {
  if (/proxy|posted|legacy|unverified|not_verified/i.test(value)) {
    return `旧锚点仅为发帖时间代理，实际执行开始未核实（${value}）`;
  }
  return value;
}

/** Keeps ledger order; no sorting or selection by forecast accuracy. */
export function historyMilestones<T>(items: T[]): T[] {
  if (items.length <= 2) return [...items];
  const middle = Math.floor((items.length - 1) / 2);
  return [items[0], items[middle], items[items.length - 1]]
    .filter((item, index, selected) => selected.indexOf(item) === index);
}

/** A retry can keep the question revision while producing a distinct target output. */
export function historyRevisionLabel(line: Pick<PredictionLine,
  "revision" | "question_revision" | "output_revision" | "question_version">): string {
  const questionRevision = line.question_revision ?? line.revision;
  const question = questionRevision === null
    ? line.question_version ? `问题版本 ${line.question_version}` : "问题修订未记录"
    : `问题修订 ${questionRevision}`;
  const output = line.output_revision === null ? "输出修订未记录" : `输出修订 ${line.output_revision}`;
  return `${question} / ${output}`;
}
