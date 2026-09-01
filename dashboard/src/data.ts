export const PUBLIC_DATA_FILES = ["index", "tweets", "radar", "health", "meta", "resets"] as const;
export const SIGNAL_CATEGORIES = new Set([
  "reset_hint", "reset_announcement", "reset_in_progress",
  "reset_confirmed", "reset_denial", "quota_information"
]);
export const RESET_CATEGORIES = new Set([
  "reset_hint", "reset_announcement", "reset_in_progress",
  "reset_confirmed", "reset_denial"
]);
export const HIGH_VALUE_CATEGORIES = new Set([
  "reset_hint", "reset_announcement", "reset_in_progress", "reset_confirmed"
]);
export const DATA_STALE_MS = 15 * 60 * 1000;

export type JsonRecord = Record<string, unknown>;
export interface PublicIndex { generated_at?: string; tweet_count?: number; classified_tweet_count?: number; category_counts?: Record<string, number>; }
export interface PublicClassification {
  category?: string; confidence?: number; urgency?: string; explicitness?: string;
  reason?: string; classified_at?: string;
}
export interface PublicTweet {
  tweet_id?: string; author?: string; text?: string;
  translation_zh?: string | null; translation_model?: string | null;
  translation_version?: string | null; translated_at?: string | null;
  created_at?: string | null; discovered_at?: string | null; url?: string;
  is_reply?: boolean; reply_to?: string | null; sources?: string[];
  classification?: PublicClassification | null;
}
export interface PublicForecast {
  last_reset_at?: string | null; last_reset_source?: string | null;
  last_reset_evidence_tweet_id?: string | null; baseline_next_reset_at?: string | null;
  signal_window?: string | null; estimated_next_reset_at?: string | null;
  forecast_source?: string; forecast_reason?: string; active_signal_tweet_id?: string | null;
}
export interface PublicUsageAdvice { level?: string; title_code?: string; reason_code?: string; }
export interface PublicRadar {
  state?: string; confidence?: number; urgency?: string; reason?: string;
  updated_at?: string | null; trigger_tweet_id?: string | null;
  forecast?: PublicForecast | null; usage_advice?: PublicUsageAdvice | null;
}
export interface PublicHealthComponent { component?: string; state?: string; last_heartbeat?: string | null; }
export interface PublicHealth { generated_at?: string; components?: PublicHealthComponent[]; }
export interface PublicMeta {
  schema_version?: number; generated_at?: string; mirror_synced_at?: string;
  source?: string; data_branch?: string; last_sync_status?: string;
}
export interface PublicResetEvent {
  event_time?: string | null; source?: string; evidence_tweet_id?: string | null;
  notes?: string | null; beijing_date?: string; beijing_time?: string;
  interval_seconds?: number | null; interval_label?: string | null;
}
export interface PublicResets {
  generated_at?: string; timezone?: string; sample_count?: number;
  events: PublicResetEvent[]; time_distribution?: Record<string, number>;
}
export interface DashboardData {
  index: PublicIndex | null; tweets: PublicTweet[]; radar: PublicRadar | null;
  health: PublicHealth | null; meta: PublicMeta | null; resets: PublicResets | null;
  errors: string[];
}
export type FetchJson = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
export type PublicDataFile = typeof PUBLIC_DATA_FILES[number];
export interface DashboardFileLoadTrace {
  file: PublicDataFile;
  url: string;
  request_started_at: string;
  response_received_at: string | null;
  status: number | null;
  ok: boolean;
  error?: string;
}
export type DashboardFileTraceHandler = (trace: DashboardFileLoadTrace) => void;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}
function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
function normalizeIndex(value: unknown): PublicIndex | null {
  if (!isRecord(value)) return null;
  const counts = isRecord(value.category_counts)
    ? Object.fromEntries(Object.entries(value.category_counts).filter(([, count]) => typeof count === "number")) as Record<string, number>
    : undefined;
  return { generated_at: asString(value.generated_at), tweet_count: asNumber(value.tweet_count), classified_tweet_count: asNumber(value.classified_tweet_count), category_counts: counts };
}
function normalizeClassification(value: unknown): PublicClassification | null {
  if (!isRecord(value)) return null;
  return { category: asString(value.category), confidence: asNumber(value.confidence), urgency: asString(value.urgency), explicitness: asString(value.explicitness), reason: asString(value.reason), classified_at: asString(value.classified_at) };
}
function normalizeTweets(value: unknown): PublicTweet[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((tweet) => ({
    tweet_id: asString(tweet.tweet_id), author: asString(tweet.author), text: asString(tweet.text) ?? "",
    translation_zh: typeof tweet.translation_zh === "string" ? tweet.translation_zh : null,
    translation_model: asString(tweet.translation_model) ?? null,
    translation_version: asString(tweet.translation_version) ?? null,
    translated_at: typeof tweet.translated_at === "string" ? tweet.translated_at : null,
    created_at: typeof tweet.created_at === "string" ? tweet.created_at : null,
    discovered_at: typeof tweet.discovered_at === "string" ? tweet.discovered_at : null,
    url: asString(tweet.url), is_reply: tweet.is_reply === true,
    reply_to: typeof tweet.reply_to === "string" ? tweet.reply_to : null,
    sources: Array.isArray(tweet.sources) ? tweet.sources.filter((source): source is string => typeof source === "string") : [],
    classification: normalizeClassification(tweet.classification)
  }));
}
function normalizeForecast(value: unknown): PublicForecast | null {
  if (!isRecord(value)) return null;
  return {
    last_reset_at: typeof value.last_reset_at === "string" ? value.last_reset_at : null,
    last_reset_source: asString(value.last_reset_source) ?? null,
    last_reset_evidence_tweet_id: typeof value.last_reset_evidence_tweet_id === "string" ? value.last_reset_evidence_tweet_id : null,
    baseline_next_reset_at: typeof value.baseline_next_reset_at === "string" ? value.baseline_next_reset_at : null,
    signal_window: asString(value.signal_window) ?? null,
    estimated_next_reset_at: typeof value.estimated_next_reset_at === "string" ? value.estimated_next_reset_at : null,
    forecast_source: asString(value.forecast_source), forecast_reason: asString(value.forecast_reason),
    active_signal_tweet_id: typeof value.active_signal_tweet_id === "string" ? value.active_signal_tweet_id : null
  };
}
function normalizeRadar(value: unknown): PublicRadar | null {
  if (!isRecord(value)) return null;
  const advice = isRecord(value.usage_advice) ? value.usage_advice : null;
  return {
    state: asString(value.state), confidence: asNumber(value.confidence), urgency: asString(value.urgency),
    reason: asString(value.reason), updated_at: typeof value.updated_at === "string" ? value.updated_at : null,
    trigger_tweet_id: typeof value.trigger_tweet_id === "string" ? value.trigger_tweet_id : null,
    forecast: normalizeForecast(value.forecast),
    usage_advice: advice ? { level: asString(advice.level), title_code: asString(advice.title_code), reason_code: asString(advice.reason_code) } : null
  };
}
function normalizeHealth(value: unknown): PublicHealth | null {
  if (!isRecord(value)) return null;
  const components = Array.isArray(value.components) ? value.components.filter(isRecord).map((component) => ({
    component: asString(component.component), state: asString(component.state),
    last_heartbeat: typeof component.last_heartbeat === "string" ? component.last_heartbeat : null
  })) : [];
  return { generated_at: asString(value.generated_at), components };
}
function normalizeMeta(value: unknown): PublicMeta | null {
  if (!isRecord(value)) return null;
  return { schema_version: asNumber(value.schema_version), generated_at: asString(value.generated_at), mirror_synced_at: asString(value.mirror_synced_at), source: asString(value.source), data_branch: asString(value.data_branch), last_sync_status: asString(value.last_sync_status) };
}
function normalizeResets(value: unknown): PublicResets | null {
  if (!isRecord(value)) return null;
  const events = Array.isArray(value.events) ? value.events.filter(isRecord).map((event) => ({
    event_time: typeof event.event_time === "string" ? event.event_time : null,
    source: asString(event.source), evidence_tweet_id: typeof event.evidence_tweet_id === "string" ? event.evidence_tweet_id : null,
    notes: typeof event.notes === "string" ? event.notes : null, beijing_date: asString(event.beijing_date),
    beijing_time: asString(event.beijing_time), interval_seconds: asNumber(event.interval_seconds) ?? null,
    interval_label: typeof event.interval_label === "string" ? event.interval_label : null
  })) : [];
  const distribution = isRecord(value.time_distribution)
    ? Object.fromEntries(Object.entries(value.time_distribution).map(([key, count]) => [key, typeof count === "number" ? count : 0])) as Record<string, number>
    : undefined;
  return { generated_at: asString(value.generated_at), timezone: asString(value.timezone), sample_count: asNumber(value.sample_count), events, time_distribution: distribution };
}

export function sortByTweetTime(tweets: PublicTweet[]): PublicTweet[] {
  return [...tweets].sort((left, right) => (Date.parse(right.created_at ?? right.discovered_at ?? "") || 0) - (Date.parse(left.created_at ?? left.discovered_at ?? "") || 0));
}
export function signalTweets(tweets: PublicTweet[]): PublicTweet[] {
  return sortByTweetTime(tweets).filter((tweet) => SIGNAL_CATEGORIES.has(tweet.classification?.category ?? ""));
}
export function highValueTweets(tweets: PublicTweet[]): PublicTweet[] {
  return sortByTweetTime(tweets).filter((tweet) => HIGH_VALUE_CATEGORIES.has(tweet.classification?.category ?? ""));
}
export function resetSignalTweets(tweets: PublicTweet[]): PublicTweet[] {
  return sortByTweetTime(tweets).filter((tweet) => RESET_CATEGORIES.has(tweet.classification?.category ?? ""));
}
export function isDataStale(generatedAt: string | undefined, now = Date.now(), thresholdMs = DATA_STALE_MS): boolean {
  return deriveDataFreshness(generatedAt, now, thresholdMs) === "stale";
}
export type DisplayHealth = "healthy" | "offline" | "stale" | "unknown";
export type DataFreshness = "fresh" | "stale" | "unknown";
export function deriveDataFreshness(generatedAt: string | undefined, now = Date.now(), thresholdMs = DATA_STALE_MS): DataFreshness {
  if (!generatedAt) return "unknown";
  const timestamp = Date.parse(generatedAt);
  if (!Number.isFinite(timestamp)) return "unknown";
  return now - timestamp > thresholdMs ? "stale" : "fresh";
}
export function deriveDisplayHealth(component: PublicHealthComponent | undefined, snapshotGeneratedAt: string | undefined, now = Date.now()): DisplayHealth {
  if (!component) return "unknown";
  const freshness = deriveDataFreshness(snapshotGeneratedAt, now);
  if (freshness === "unknown") return "unknown";
  if (freshness === "stale") return "stale";
  const reported = component.state?.toLowerCase();
  if (reported === "healthy") return "healthy";
  if (reported === "offline") return "offline";
  return "unknown";
}
export function deriveMirrorState(syncedAt: string | undefined, now = Date.now()): DataFreshness {
  return deriveDataFreshness(syncedAt, now);
}
export function mergeDashboardData(previous: DashboardData, next: DashboardData): DashboardData {
  const failedFiles = new Set(next.errors.map((error) => error.split(":", 1)[0]));
  return {
    index: failedFiles.has("index") ? previous.index : next.index, tweets: failedFiles.has("tweets") ? previous.tweets : next.tweets,
    radar: failedFiles.has("radar") ? previous.radar : next.radar, health: failedFiles.has("health") ? previous.health : next.health,
    meta: failedFiles.has("meta") ? previous.meta : next.meta, resets: failedFiles.has("resets") ? previous.resets : next.resets,
    errors: next.errors
  };
}
export function ageLabel(timestamp: string | null | undefined, now = Date.now(), language: "zh" | "en" = "en"): string {
  const unknown = language === "zh" ? "未知" : "unknown";
  if (!timestamp) return unknown;
  const parsed = Date.parse(timestamp);
  if (!Number.isFinite(parsed)) return unknown;
  const seconds = Math.max(0, Math.floor((now - parsed) / 1000));
  if (language === "zh") {
    if (seconds < 60) return seconds + " 秒前";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + " 分钟前";
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + " 小时前";
    return Math.floor(hours / 24) + " 天前";
  }
  if (seconds < 60) return seconds + "s ago";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + "m ago";
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours + "h ago";
  return Math.floor(hours / 24) + "d ago";
}
export async function loadDashboardData(
  fetcher: FetchJson = fetch,
  baseUrl = document.baseURI,
  onFileTrace?: DashboardFileTraceHandler
): Promise<DashboardData> {
  const result: DashboardData = { index: null, tweets: [], radar: null, health: null, meta: null, resets: null, errors: [] };
  const resolvedBase = new URL(baseUrl, typeof document === "undefined" ? "https://data.invalid/" : document.baseURI);
  const values = await Promise.all(PUBLIC_DATA_FILES.map(async (file) => {
    const requestStartedAt = new Date().toISOString();
    const requestUrl = new URL(file + ".json", resolvedBase);
    let responseReceivedAt: string | null = null;
    let status: number | null = null;
    try {
      const response = await fetcher(requestUrl, { cache: "no-store" });
      responseReceivedAt = new Date().toISOString();
      status = response.status;
      if (!response.ok) throw new Error("HTTP " + response.status);
      const value = await response.json() as unknown;
      onFileTrace?.({
        file,
        url: requestUrl.toString(),
        request_started_at: requestStartedAt,
        response_received_at: responseReceivedAt,
        status,
        ok: true
      });
      return { file, value };
    } catch (error) {
      const message = error instanceof Error ? error.message : "request failed";
      result.errors.push(file + ": " + message);
      onFileTrace?.({
        file,
        url: requestUrl.toString(),
        request_started_at: requestStartedAt,
        response_received_at: responseReceivedAt,
        status,
        ok: false,
        error: message
      });
      return { file, value: null };
    }
  }));
  for (const item of values) {
    if (item.file === "index") result.index = normalizeIndex(item.value);
    if (item.file === "tweets") result.tweets = normalizeTweets(item.value);
    if (item.file === "radar") result.radar = normalizeRadar(item.value);
    if (item.file === "health") result.health = normalizeHealth(item.value);
    if (item.file === "meta") result.meta = normalizeMeta(item.value);
    if (item.file === "resets") result.resets = normalizeResets(item.value);
  }
  return result;
}
