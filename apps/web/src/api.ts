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
  next_reset: {
    status: "waiting_for_verified_history" | "baseline";
    estimated_at: string | null;
    basis: string;
  };
  last_full_reset: ResetEvent | null;
  special_resets: ResetEvent[];
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  commit: string;
  database: { status: string; counts: Record<string, number> };
  collector: Record<string, { state: string; last_seen_at: string; sequence?: number | null }>;
  runtime: { github_mirror_enabled: boolean; pages_dependency: boolean; log_retention_days: number };
}

export interface TiboPost {
  id: number;
  tweet_id: string;
  posted_at: string | null;
  text: string;
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
    display_tone: item.event_type === "SPECIAL_RESET" ? "PURPLE" : "EVENT"
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
    next_reset: {
      status: next.status === "baseline" ? "baseline" : "waiting_for_verified_history",
      estimated_at: typeof next.estimated_at === "string" ? next.estimated_at : null,
      basis: text(next.basis)
    },
    last_full_reset: lastFull,
    special_resets: special
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
