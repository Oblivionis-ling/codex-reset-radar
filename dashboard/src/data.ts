export const PUBLIC_DATA_FILES = ["index", "tweets", "radar", "health"] as const;
export const SIGNAL_CATEGORIES = new Set([
  "reset_hint",
  "reset_announcement",
  "reset_in_progress",
  "reset_confirmed",
  "reset_denial",
  "quota_information"
]);
export const RESET_CATEGORIES = new Set([
  "reset_hint",
  "reset_announcement",
  "reset_in_progress",
  "reset_confirmed",
  "reset_denial"
]);
export const DATA_STALE_MS = 30 * 60 * 1000;
export const HEALTH_WARNING_MS = 15 * 60 * 1000;
export const HEALTH_OFFLINE_MS = 30 * 60 * 1000;

export type JsonRecord = Record<string, unknown>;

export interface PublicIndex {
  generated_at?: string;
  tweet_count?: number;
  classified_tweet_count?: number;
  category_counts?: Record<string, number>;
}

export interface PublicClassification {
  category?: string;
  confidence?: number;
  urgency?: string;
  explicitness?: string;
  reason?: string;
  classified_at?: string;
}

export interface PublicTweet {
  tweet_id?: string;
  author?: string;
  text?: string;
  created_at?: string | null;
  discovered_at?: string | null;
  url?: string;
  is_reply?: boolean;
  classification?: PublicClassification | null;
}

export interface PublicRadar {
  state?: string;
  confidence?: number;
  urgency?: string;
  reason?: string;
  updated_at?: string | null;
  trigger_tweet_id?: string | null;
}

export interface PublicHealthComponent {
  component?: string;
  state?: string;
  last_heartbeat?: string | null;
}

export interface PublicHealth {
  generated_at?: string;
  components?: PublicHealthComponent[];
}

export interface DashboardData {
  index: PublicIndex | null;
  tweets: PublicTweet[];
  radar: PublicRadar | null;
  health: PublicHealth | null;
  errors: string[];
}

export type FetchJson = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

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
  return {
    generated_at: asString(value.generated_at),
    tweet_count: asNumber(value.tweet_count),
    classified_tweet_count: asNumber(value.classified_tweet_count),
    category_counts: counts
  };
}

function normalizeClassification(value: unknown): PublicClassification | null {
  if (!isRecord(value)) return null;
  return {
    category: asString(value.category),
    confidence: asNumber(value.confidence),
    urgency: asString(value.urgency),
    explicitness: asString(value.explicitness),
    reason: asString(value.reason),
    classified_at: asString(value.classified_at)
  };
}

function normalizeTweets(value: unknown): PublicTweet[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((tweet) => ({
    tweet_id: asString(tweet.tweet_id),
    author: asString(tweet.author),
    text: asString(tweet.text) ?? "",
    created_at: typeof tweet.created_at === "string" ? tweet.created_at : null,
    discovered_at: typeof tweet.discovered_at === "string" ? tweet.discovered_at : null,
    url: asString(tweet.url),
    is_reply: tweet.is_reply === true,
    classification: normalizeClassification(tweet.classification)
  }));
}

function normalizeRadar(value: unknown): PublicRadar | null {
  if (!isRecord(value)) return null;
  return {
    state: asString(value.state),
    confidence: asNumber(value.confidence),
    urgency: asString(value.urgency),
    reason: asString(value.reason),
    updated_at: typeof value.updated_at === "string" ? value.updated_at : null,
    trigger_tweet_id: typeof value.trigger_tweet_id === "string" ? value.trigger_tweet_id : null
  };
}

function normalizeHealth(value: unknown): PublicHealth | null {
  if (!isRecord(value)) return null;
  const components = Array.isArray(value.components)
    ? value.components.filter(isRecord).map((component) => ({
        component: asString(component.component),
        state: asString(component.state),
        last_heartbeat: typeof component.last_heartbeat === "string" ? component.last_heartbeat : null
      }))
    : [];
  return { generated_at: asString(value.generated_at), components };
}

export function sortByTweetTime(tweets: PublicTweet[]): PublicTweet[] {
  return [...tweets].sort((left, right) => {
    const leftTime = Date.parse(left.created_at ?? left.discovered_at ?? "") || 0;
    const rightTime = Date.parse(right.created_at ?? right.discovered_at ?? "") || 0;
    return rightTime - leftTime;
  });
}

export function signalTweets(tweets: PublicTweet[]): PublicTweet[] {
  return sortByTweetTime(tweets).filter((tweet) => SIGNAL_CATEGORIES.has(tweet.classification?.category ?? ""));
}

export function resetSignalTweets(tweets: PublicTweet[]): PublicTweet[] {
  return sortByTweetTime(tweets).filter((tweet) => RESET_CATEGORIES.has(tweet.classification?.category ?? ""));
}

export function isDataStale(generatedAt: string | undefined, now = Date.now(), thresholdMs = DATA_STALE_MS): boolean {
  if (!generatedAt) return true;
  const timestamp = Date.parse(generatedAt);
  return !Number.isFinite(timestamp) || now - timestamp > thresholdMs;
}

export function healthState(
  component: PublicHealthComponent | undefined,
  now = Date.now()
): "healthy" | "warning" | "offline" | "unknown" {
  if (!component) return "unknown";
  const reported = component.state?.toLowerCase();
  if (reported === "offline") return "offline";
  const timestamp = component.last_heartbeat ? Date.parse(component.last_heartbeat) : Number.NaN;
  if (!Number.isFinite(timestamp)) return reported === "healthy" ? "warning" : "unknown";
  const age = Math.max(0, now - timestamp);
  if (age > HEALTH_OFFLINE_MS) return "offline";
  if (age > HEALTH_WARNING_MS && reported === "healthy") return "warning";
  return reported === "healthy" || reported === "warning" ? reported : "unknown";
}

export function ageLabel(timestamp: string | null | undefined, now = Date.now(), language: "zh" | "en" = "en"): string {
  const unknown = language === "zh" ? "未知" : "unknown";
  if (!timestamp) return unknown;
  const parsed = Date.parse(timestamp);
  if (!Number.isFinite(parsed)) return unknown;
  const seconds = Math.max(0, Math.floor((now - parsed) / 1000));
  if (language === "zh") {
    if (seconds < 60) return `${seconds} 秒前`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} 分钟前`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} 小时前`;
    return `${Math.floor(hours / 24)} 天前`;
  }
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export async function loadDashboardData(
  fetcher: FetchJson = fetch,
  baseUrl = document.baseURI
): Promise<DashboardData> {
  const result: DashboardData = { index: null, tweets: [], radar: null, health: null, errors: [] };
  const values = await Promise.all(
    PUBLIC_DATA_FILES.map(async (file) => {
      try {
        const response = await fetcher(new URL(`public-data/${file}.json`, baseUrl));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return { file, value: await response.json() as unknown };
      } catch (error) {
        result.errors.push(`${file}: ${error instanceof Error ? error.message : "request failed"}`);
        return { file, value: null };
      }
    })
  );
  for (const item of values) {
    if (item.file === "index") result.index = normalizeIndex(item.value);
    if (item.file === "tweets") result.tweets = normalizeTweets(item.value);
    if (item.file === "radar") result.radar = normalizeRadar(item.value);
    if (item.file === "health") result.health = normalizeHealth(item.value);
  }
  return result;
}
