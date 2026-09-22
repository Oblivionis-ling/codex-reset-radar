import { API_BASE_URL } from "./config";

export const ACTION_LEVELS = ["GREEN", "YELLOW", "ORANGE", "RED", "UNKNOWN"] as const;
export type ActionLevel = (typeof ACTION_LEVELS)[number];

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
  decision?: Record<string, unknown>;
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
    decision: record(item.decision),
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
    last_known_result: item.last_known_result ? record(item.last_known_result) : null
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
