import { API_BASE_URL } from "./config";

/** Mirrors apps/backend/app/prediction_contract.py::PREDICTION_API_VERSION. */
export const PREDICTION_API_VERSION = "prediction-three-lines-v1";
/** API view includes the independent Normal reference in addition to model targets. */
export const PREDICTION_TARGETS = ["NORMAL_WEEKLY", "EXTRA_FULL", "BANKED"] as const;
export type PredictionTarget = (typeof PREDICTION_TARGETS)[number];
export const ACTION_LEVELS = ["GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"] as const;
export type ActionLevel = (typeof ACTION_LEVELS)[number];

export interface PredictionLine {
  target: PredictionTarget;
  record_id: string | null;
  ledger_seq: number | null;
  is_synthetic: boolean | null;
  record_kind: string | null;
  state: string;
  form: string;
  predicted_start: string | null;
  predicted_end: string | null;
  expression: string | null;
  date_boundaries: string | null;
  relative_expression: string | null;
  relative_anchor: string | null;
  unresolved_reason: string | null;
  source_timezone: string | null;
  precision: string | null;
  time_basis: string | null;
  scope: string | null;
  anchor_limitation: string | null;
  anchor_time_basis: string | null;
  method: string | null;
  basis: string | null;
  reason: string | null;
  updated_at: string | null;
  updated_at_source: string | null;
  validity_state: string;
  valid_until: string | null;
  health_state: string;
  health_reason: string | null;
  series_id: string | null;
  forecast_id: string | null;
  revision: number | null;
  question_revision: number | null;
  question_version: string | null;
  forecast_revision: number | null;
  forecast_version: string | null;
  output_revision: number | null;
  target_output_id: string | null;
  previous_id: string | null;
  output_available_at: string | null;
  output_availability_kind: string | null;
  current_advice_eligible: boolean;
  eligibility_reason: string | null;
}

export interface PredictionProjection {
  version: string;
  algorithm_version: string | null;
  state: string;
  capabilities: {
    normal_weekly: boolean;
    extra_full: boolean;
    banked: boolean;
    history: boolean;
    normal_history: boolean;
    ledger_history_readable: boolean;
    model_targets: PredictionTarget[];
  };
  health: {
    validation_valid: boolean;
    validation_reason: string;
    current_data_health: string;
    generation_data_health: string | null;
    generation_health_reason: string | null;
    judgement_usable: boolean;
    current_collector_health: Record<string, unknown>;
    refresh_failed: boolean;
    refresh_failure_reason: string | null;
    ledger: Record<string, unknown>;
  };
  lines: Record<PredictionTarget, PredictionLine>;
}

export interface PredictionHistoryAttempt {
  target: PredictionTarget;
  attempt_number: number | null;
  attempted_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  state: string;
  reason_code: string | null;
  reason: string | null;
  output_status: string | null;
}

export interface PredictionHistoryResponse {
  version: string;
  state: string;
  target: PredictionTarget;
  series_id: string;
  items: PredictionLine[];
  first_items: PredictionLine[];
  last_items: PredictionLine[];
  attempts: PredictionHistoryAttempt[];
  attempts_available: boolean;
  attempts_truncated: boolean;
  reason: string | null;
  total_count: number;
  total_count_known: boolean;
  truncated: boolean;
  order_basis: string | null;
}

export interface ResetEvent {
  id: number;
  event_type: "FULL_RESET" | "SPECIAL_RESET";
  special_type: "PARTIAL" | "BANKED" | "RESET_CARD" | "STAGED" | "EXTRA_CREDIT" | "OTHER" | null;
  occurred_at: string;
  title: string;
  summary: string;
  display_tone: "PURPLE" | "EVENT";
  occurred_at_end?: string | null;
  time_basis?: string;
  scope?: string;
  execution_stage?: string;
  evidence_post_ids?: string[];
}

export interface RadarResponse {
  version: string;
  action_level: ActionLevel;
  horizon_24h: ActionLevel;
  horizon_48h: ActionLevel;
  horizon_72h: ActionLevel;
  data_health: string;
  reason_summary: string;
  judged_at: string | null;
  valid_until: string | null;
  judgement_id: number | null;
  judgement_state: string;
  estimated_start: string | null;
  estimated_end: string | null;
  estimate_basis: string;
  evidence_post_ids: string[];
  judge_runtime: Record<string, unknown>;
  pipeline: Record<string, unknown>;
  next_reset: {
    status: "waiting_for_verified_history" | "baseline" | "expired";
    estimated_at: string | null;
    basis: string;
  };
  last_full_reset: ResetEvent | null;
  special_resets: ResetEvent[];
  special_announcements: { candidate_id: number; tweet_id: string; posted_at: string; summary: string; scope: string; scheduled_at: string | null }[];
  current_data_health: string;
  judgement_data_health: string;
  display_mode: string;
  validation: { valid: boolean; reason: string };
  last_known_result: Record<string, unknown> | null;
  prediction: PredictionProjection | null;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  commit: string;
  database: { status: string; counts: Record<string, number> };
  collector: Record<string, { state: string; last_seen_at: string; sequence?: number | null; reported_state?: string; age_seconds?: number | null; reason?: string }>;
  runtime: { github_mirror_enabled: boolean; pages_dependency: boolean; log_retention_days: number };
  intelligence?: {
    pipeline: Record<string, unknown>;
    judge: Record<string, unknown>;
    pending_jobs: number;
  };
}

export interface TiboPost {
  id: number;
  tweet_id: string;
  posted_at: string | null;
  text: string;
  original_text: string;
  original_language: string;
  translated_text: string | null;
  analysis_status: string;
  translation_status: string;
  processing_error: string | null;
  reply_context?: { state: string; missing: string[]; direct_parent_id?: string | null;
    nodes: { tweet_id: string; author: string; posted_at: string; text: string; url: string; depth: number }[] };
  context_acquisition?: { status: string; reason: string | null };
  analysis: {
    category?: string;
    summary?: string;
    evidence_quote?: string;
    _analysed_at?: string;
    context_sufficient?: boolean;
  } | null;
  url: string;
  is_reply: boolean;
  source: string;
}

export interface PostsResponse {
  items: TiboPost[];
  count: number;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function nullableText(...values: unknown[]): string | null {
  return values.find((value): value is string => typeof value === "string") ?? null;
}

function optionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function readableValue(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value && typeof value === "object") return JSON.stringify(value).slice(0, 1000);
  return null;
}

function scopeText(value: unknown): string | null {
  if (typeof value === "string") return value;
  const item = record(value);
  const rawValue = nullableText(item.value);
  if (!rawValue) return readableValue(value);
  const labels: Record<string, string> = {
    unknown: "范围未知",
    all_paid: "全部付费用户",
    work_and_codex: "Work 与 Codex",
    plus_pro: "Plus Pro",
    partial_users: "部分用户",
    banked_only: "仅 Banked"
  };
  const certainty = nullableText(item.certainty);
  const certaintyLabel = certainty === "not_established_by_ledger" ? "账本未确认" : certainty;
  return `${labels[rawValue] ?? rawValue}${certaintyLabel ? `（${certaintyLabel}）` : ""}`;
}

function parsePredictionLine(value: unknown, target: PredictionTarget): PredictionLine {
  const item = record(value);
  const time = record(item.time);
  const validity = record(item.validity);
  const health = record(item.health);
  const healthValue = item.health;
  const validityValue = item.validity;
  return {
    target,
    record_id: nullableText(item.record_id),
    ledger_seq: optionalNumber(item.ledger_seq),
    is_synthetic: typeof item.is_synthetic === "boolean" ? item.is_synthetic : null,
    record_kind: nullableText(item.record_kind),
    state: text(item.state ?? item.status, "invalid"),
    form: text(item.resolved_prediction_form ?? item.form ?? item.prediction_form ?? time.form, "unknown"),
    predicted_start: nullableText(item.predicted_start, item.start, time.start),
    predicted_end: nullableText(item.predicted_end, item.end, time.end),
    expression: nullableText(item.expression, time.expression),
    date_boundaries: nullableText(item.date_boundaries, time.date_boundaries),
    relative_expression: nullableText(item.relative_expression, item.expression, time.relative_expression, time.expression),
    relative_anchor: readableValue(item.relative_anchor ?? item.relative_anchor_at ?? item.posted_anchor
      ?? item.anchor ?? time.relative_anchor ?? time.relative_anchor_at ?? time.posted_anchor ?? time.anchor),
    unresolved_reason: nullableText(item.unresolved_reason, time.unresolved_reason),
    source_timezone: nullableText(item.source_timezone, time.source_timezone),
    precision: nullableText(item.precision, time.precision),
    time_basis: nullableText(item.time_basis, time.time_basis),
    scope: scopeText(item.scope),
    anchor_limitation: nullableText(item.anchor_limitation),
    anchor_time_basis: nullableText(item.anchor_time_basis),
    method: nullableText(item.method, item.source_method),
    basis: nullableText(item.basis),
    reason: nullableText(item.reason, item.reason_summary),
    updated_at: nullableText(item.updated_at, item.recorded_at, item.judged_at),
    updated_at_source: nullableText(item.updated_at_source),
    validity_state: typeof validityValue === "string"
      ? validityValue
      : text(validity.state ?? item.validity_state, "unknown"),
    valid_until: nullableText(validity.valid_until, item.valid_until),
    health_state: typeof healthValue === "string"
      ? healthValue
      : text(health.state ?? item.health_state ?? item.data_health, "unknown"),
    health_reason: nullableText(health.reason, item.health_reason),
    series_id: nullableText(item.series_id),
    forecast_id: nullableText(item.forecast_id),
    revision: optionalNumber(item.revision),
    question_revision: optionalNumber(item.question_revision ?? item.forecast_revision ?? item.revision),
    question_version: readableValue(item.question_version ?? item.forecast_version),
    forecast_revision: optionalNumber(item.forecast_revision),
    forecast_version: readableValue(item.forecast_version),
    output_revision: optionalNumber(item.output_revision),
    target_output_id: nullableText(item.target_output_id),
    previous_id: nullableText(item.previous_id),
    output_available_at: nullableText(item.output_available_at),
    output_availability_kind: nullableText(item.output_availability_kind, item.availability_kind),
    current_advice_eligible: item.current_advice_eligible === true,
    eligibility_reason: nullableText(item.eligibility_reason)
  };
}

function parsePrediction(value: unknown): PredictionProjection | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = record(value);
  const rawCapabilities = record(item.capabilities);
  const rawLines = record(item.lines);
  const rawHealth = record(item.health);
  const targets = PREDICTION_TARGETS;
  const capabilities = {
    normal_weekly: rawCapabilities.normal_weekly === true || rawCapabilities.NORMAL_WEEKLY === true,
    extra_full: rawCapabilities.extra_full === true || rawCapabilities.EXTRA_FULL === true,
    banked: rawCapabilities.banked === true || rawCapabilities.BANKED === true,
    history: rawCapabilities.history === true
  };
  const modelTargets = Array.isArray(rawCapabilities.model_targets)
    ? rawCapabilities.model_targets.filter((target): target is PredictionTarget => PREDICTION_TARGETS.includes(target as PredictionTarget))
    : [];
  const lines = Object.fromEntries(targets.map((target) => {
    const source = rawLines[target];
    if (source && typeof source === "object" && !Array.isArray(source)) {
      return [target, parsePredictionLine(source, target)];
    }
    const supported = target === "NORMAL_WEEKLY" ? capabilities.normal_weekly
      : target === "EXTRA_FULL" ? capabilities.extra_full : capabilities.banked;
    return [target, parsePredictionLine({
      state: supported ? "invalid" : "not_implemented",
      reason: supported ? "Capability was advertised without a line DTO." : "This target is not available in the current API response."
    }, target)];
  })) as Record<PredictionTarget, PredictionLine>;
  return {
    version: text(item.version, "unknown"),
    algorithm_version: nullableText(item.algorithm_version),
    state: text(item.state ?? item.status, "unknown"),
    capabilities: {
      ...capabilities,
      normal_history: rawCapabilities.normal_history === true,
      ledger_history_readable: rawCapabilities.ledger_history_readable === true,
      model_targets: modelTargets
    },
    health: {
      validation_valid: rawHealth.validation_valid === true,
      validation_reason: text(rawHealth.validation_reason, "UNKNOWN"),
      current_data_health: text(rawHealth.current_data_health, "UNKNOWN"),
      generation_data_health: nullableText(rawHealth.generation_data_health),
      generation_health_reason: nullableText(rawHealth.generation_health_reason),
      judgement_usable: rawHealth.judgement_usable === true,
      current_collector_health: record(rawHealth.current_collector_health),
      refresh_failed: rawHealth.refresh_failed === true,
      refresh_failure_reason: nullableText(rawHealth.refresh_failure_reason),
      ledger: record(rawHealth.ledger)
    },
    lines
  };
}

export function parsePredictionHistory(
  value: unknown,
  requestedTarget: PredictionTarget,
  requestedSeriesId: string
): PredictionHistoryResponse {
  const item = record(value);
  const rows = Array.isArray(item.items) ? item.items : [];
  const firstRows = Array.isArray(item.first_items) ? item.first_items
    : item.first_item && typeof item.first_item === "object" ? [item.first_item] : [];
  const lastRows = Array.isArray(item.last_items) ? item.last_items
    : item.last_item && typeof item.last_item === "object" ? [item.last_item] : [];
  const attempts = Array.isArray(item.attempts) ? item.attempts : [];
  const reportedTotal = optionalNumber(item.total_count ?? item.total);
  return {
    version: text(item.version, "unknown"),
    state: text(item.state, "unknown"),
    target: requestedTarget,
    series_id: text(item.series_id, requestedSeriesId),
    items: rows.map((row) => parsePredictionLine(row, requestedTarget)),
    first_items: firstRows.map((row) => parsePredictionLine(row, requestedTarget)),
    last_items: lastRows.map((row) => parsePredictionLine(row, requestedTarget)),
    attempts: attempts.map((row): PredictionHistoryAttempt | null => {
      const attempt = record(row);
      if (attempt.target !== requestedTarget) return null;
      return {
        target: requestedTarget,
        attempt_number: optionalNumber(attempt.attempt_number),
        attempted_at: nullableText(attempt.attempted_at),
        started_at: nullableText(attempt.started_at),
        finished_at: nullableText(attempt.finished_at),
        state: text(attempt.state ?? attempt.status, "unknown"),
        reason_code: nullableText(attempt.reason_code),
        reason: nullableText(attempt.reason),
        output_status: nullableText(attempt.output_status)
      };
    }).filter((attempt): attempt is PredictionHistoryAttempt => attempt !== null),
    attempts_available: item.attempts_available === true,
    attempts_truncated: item.attempts_truncated === true,
    reason: nullableText(item.reason, item.message),
    total_count: reportedTotal ?? rows.length,
    total_count_known: item.total_count_known === false ? false : reportedTotal !== null,
    truncated: item.truncated === true || item.has_more === true
      || (reportedTotal ?? rows.length) > rows.length,
    order_basis: nullableText(item.order_basis)
  };
}

export function actionLevel(value: unknown): ActionLevel {
  return ACTION_LEVELS.includes(value as ActionLevel) ? value as ActionLevel : "UNKNOWN";
}

function resetEvent(value: unknown): ResetEvent | null {
  const item = record(value);
  if (typeof item.id !== "number" || (item.event_type !== "FULL_RESET" && item.event_type !== "SPECIAL_RESET")) return null;
  return {
    id: item.id,
    event_type: item.event_type,
    special_type: typeof item.special_type === "string" ? item.special_type as ResetEvent["special_type"] : null,
    occurred_at: text(item.occurred_at),
    title: text(item.title, "Untitled reset event"),
    summary: text(item.summary),
    display_tone: item.event_type === "SPECIAL_RESET" ? "PURPLE" : "EVENT",
    occurred_at_end: typeof item.occurred_at_end === "string" ? item.occurred_at_end : null,
    time_basis: text(item.time_basis, "unknown"),
    scope: text(item.scope, "unknown"),
    execution_stage: text(item.execution_stage, "unknown"),
    evidence_post_ids: Array.isArray(item.evidence_post_ids) ? item.evidence_post_ids.map(String) : []
  };
}

export function parseRadar(value: unknown): RadarResponse {
  const item = record(value);
  const next = record(item.next_reset);
  const lastFull = resetEvent(item.last_full_reset);
  const special = Array.isArray(item.special_resets) ? item.special_resets.map(resetEvent).filter((event): event is ResetEvent => Boolean(event)) : [];
  return {
    version: text(item.version, "unknown"),
    action_level: actionLevel(item.action_level),
    horizon_24h: actionLevel(item.horizon_24h),
    horizon_48h: actionLevel(item.horizon_48h),
    horizon_72h: actionLevel(item.horizon_72h),
    data_health: text(item.data_health, "UNKNOWN"),
    reason_summary: text(item.reason_summary, "当前没有可靠判断。"),
    judged_at: typeof item.judged_at === "string" ? item.judged_at : null,
    valid_until: typeof item.valid_until === "string" ? item.valid_until : null,
    judgement_id: typeof item.judgement_id === "number" ? item.judgement_id : null,
    judgement_state: text(item.judgement_state, "waiting"),
    estimated_start: typeof item.estimated_start === "string" ? item.estimated_start : null,
    estimated_end: typeof item.estimated_end === "string" ? item.estimated_end : null,
    estimate_basis: text(item.estimate_basis, "当前没有可靠的信号时间范围。"),
    evidence_post_ids: Array.isArray(item.evidence_post_ids) ? item.evidence_post_ids.map(String) : [],
    judge_runtime: record(item.judge_runtime),
    pipeline: record(item.pipeline),
    next_reset: {
      status: next.status === "baseline" || next.status === "expired" ? next.status : "waiting_for_verified_history",
      estimated_at: typeof next.estimated_at === "string" ? next.estimated_at : null,
      basis: text(next.basis)
    },
    last_full_reset: lastFull,
    special_resets: special,
    special_announcements: (Array.isArray(item.special_announcements) ? item.special_announcements : []).map(record)
      .filter(a=>typeof a.candidate_id==='number' && /^\d+$/.test(text(a.tweet_id)))
      .map(a=>({candidate_id:a.candidate_id as number,tweet_id:text(a.tweet_id),posted_at:text(a.posted_at),
        summary:text(a.summary),scope:text(a.scope,'unknown'),scheduled_at:typeof a.scheduled_at==='string'?a.scheduled_at:null})),
    current_data_health: text(item.current_data_health, 'UNKNOWN'),
    judgement_data_health: text(item.judgement_data_health, 'UNKNOWN'),
    display_mode: text(item.display_mode, 'unavailable'),
    validation: {valid:record(item.validation).valid===true,reason:text(record(item.validation).reason,'UNKNOWN')},
    last_known_result: item.last_known_result ? record(item.last_known_result) : null,
    prediction: parsePrediction(item.prediction)
  };
}

async function getJson(path: string): Promise<unknown> {
  const response = await fetch(`${API_BASE_URL}${path}`, { headers: { Accept: "application/json" }, cache: "no-store" });
  if (!response.ok) throw new Error(`Backend ${response.status}`);
  return response.json();
}

export async function loadV2Dashboard(): Promise<{ radar: RadarResponse; health: HealthResponse; posts: PostsResponse }> {
  const [radar, health, posts] = await Promise.all([
    getJson("/radar"),
    getJson("/health"),
    getJson("/posts?limit=12")
  ]);
  return {
    radar: parseRadar(radar),
    health: health as HealthResponse,
    posts: posts as PostsResponse
  };
}

export async function loadPredictionHistory(
  target: PredictionTarget,
  seriesId: string,
  limit = 100
): Promise<PredictionHistoryResponse> {
  const boundedLimit = Math.max(1, Math.min(200, Math.trunc(limit)));
  const query = new URLSearchParams({ target, series_id: seriesId, limit: String(boundedLimit) });
  const value = await getJson(`/predictions/history?${query.toString()}`);
  return parsePredictionHistory(value, target, seriesId);
}
