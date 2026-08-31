import "./style.css";
import { DATA_BASE_URL } from "./config";
import {
  ageLabel,
  deriveDisplayHealth,
  deriveMirrorState,
  highValueTweets,
  loadDashboardData,
  mergeDashboardData,
  sortByTweetTime,
  type DashboardData,
  type DisplayHealth,
  type PublicHealthComponent,
  type PublicResetEvent,
  type PublicTweet
} from "./data";

type Language = "zh" | "en";
const LANGUAGE_STORAGE_KEY = "codex-reset-radar-language";
const REFRESH_INTERVAL_MS = 60_000;
const app = document.querySelector<HTMLElement>("#app");
let language: Language = readLanguage();
let lastSuccessfulData: DashboardData | null = null;
let lastRefreshFailed = false;
let refreshInFlight = false;

interface Copy {
  languageButton: string; languageAria: string; eyebrow: string; dataUpdated: string;
  tweets: string; dataUnavailable: string; refreshFailed: string; showingLastSuccess: string;
  dataStale: string; staleDescription: string; currentRadar: string; lastKnownRadar: string;
  confidence: string; urgency: string; lastUpdated: string; noRadarState: string;
  latestSignal: string; latestSignalHeading: string; monitorHealth: string; collectionStatus: string;
  dataMirror: string; lastSync: string; lastHeartbeat: string; lastKnownStatus: string;
  noHeartbeat: string; emptyTweet: string; unclassified: string; openOnX: string;
  translation: string; translationUnavailable: string; original: string; reply: string;
  overview: string; recentTweets: string; resetHistory: string; viewTweets: string; viewResets: string;
  lastReset: string; nextReset: string; noReset: string; baselineNote: string; forecastSource: string;
  forecastSources: Record<string, string>; signalWindow: Record<string, string>;
  advice: string; adviceReasons: Record<string, string>; adviceTitles: Record<string, string>;
  states: Record<string, string>; categories: Record<string, string>; urgencyValues: Record<string, string>;
  healthStates: Record<string, string>; monitorLabels: Record<string, string>;
  recentHighValue: string; noSignals: string; noSignalsDetail: string; tweetsPageTitle: string;
  tweetsPageDetail: string; resetPageTitle: string; resetPageDetail: string; sampleCount: string;
  beijingTime: string; source: string; interval: string; noHistory: string; timeDistribution: string;
  calendar: string; calendarDetail: string; unknown: string; snapshotGenerated: string;
}

const COPY: Record<Language, Copy> = {
  zh: {
    languageButton: "English", languageAria: "切换到英文", eyebrow: "公开 Radar · @thsottiaux",
    dataUpdated: "数据更新时间", tweets: "条 Tweet", dataUnavailable: "数据不可用", refreshFailed: "刷新失败",
    showingLastSuccess: "正在显示最后一次成功数据。", dataStale: "数据镜像过期",
    staleDescription: "公开数据镜像已超过 15 分钟未更新。", currentRadar: "当前 Radar",
    lastKnownRadar: "最后已知状态", confidence: "置信度", urgency: "紧急度", lastUpdated: "最后更新",
    noRadarState: "当前没有可用的 Radar 状态。", latestSignal: "最新高价值信号",
    latestSignalHeading: "最近的 Reset 相关动态", monitorHealth: "监控健康度", collectionStatus: "采集状态",
    dataMirror: "GitHub 数据镜像", lastSync: "最后同步", lastHeartbeat: "最后心跳",
    lastKnownStatus: "最后已知状态", noHeartbeat: "暂无心跳", emptyTweet: "（Tweet 文本为空）",
    unclassified: "未分类", openOnX: "在 X 上打开 ↗", translation: "中文翻译", translationUnavailable: "翻译暂不可用",
    original: "英文原文", reply: "回复", overview: "概览", recentTweets: "最近推文", resetHistory: "重置历史",
    viewTweets: "查看最近 Tweet →", viewResets: "查看重置历史 →", lastReset: "最近一次重置", nextReset: "预计下一次重置",
    noReset: "暂无已确认的 Reset", baselineNote: "按最近一次确认重置 + 7 天估算",
    forecastSource: "预测依据", forecastSources: { weekly_baseline: "周期推算", reset_hint: "Tibo 暗示", reset_announcement: "Tibo 明确预告", no_confirmed_reset: "暂无确认事件" },
    signalWindow: { within_24h: "未来 24 小时", explicit_time: "明确时间", unknown: "未知" },
    advice: "额度使用建议", adviceReasons: {
      confirmed: "Reset 已确认，可检查额度是否刷新。", radar_urgent: "Radar 显示 Reset 已接近，不妨优先使用剩余额度。",
      signal_within_24h: "存在高价值 Reset 信号，窗口可能在未来 24 小时内。",
      watch_or_baseline_near: "Radar 需要关注，或已接近基础周期估算时间。", no_immediate_signal: "目前没有需要立即行动的明显 Reset 信号。"
    },
    adviceTitles: { reset_confirmed: "重置已确认，可检查额度是否刷新", use_soon: "建议尽快使用额度", prioritize_usage: "建议优先使用剩余额度", speed_up_gently: "可以适当加快使用", normal_usage: "正常使用" },
    states: { QUIET: "平静", WATCH: "关注", LIKELY: "较可能重置", IMMINENT: "即将重置", ANNOUNCED: "已预告", CONFIRMED: "已确认重置", UNKNOWN: "未知" },
    categories: { reset_hint: "重置暗示", reset_announcement: "重置预告", reset_in_progress: "正在重置", reset_confirmed: "重置已确认", reset_denial: "重置否认", quota_information: "额度信息", codex_related: "Codex 相关", unrelated: "无关" },
    urgencyValues: { now: "现在", within_6h: "6 小时内", within_24h: "24 小时内", "within 24h": "24 小时内", within_3d: "3 天内", "within 3d": "3 天内", unknown: "未知" },
    healthStates: { healthy: "正常", warning: "警告", offline: "离线", stale: "数据过期", unknown: "未知", fresh: "最新" },
    monitorLabels: { backend: "Backend", profile_monitor: "Profile", replies_monitor: "Replies", search_backfill: "Search Backfill" },
    recentHighValue: "最新 Tibo 信号", noSignals: "当前没有可展示的高价值信号。", noSignalsDetail: "下一条 Reset 相关 Tweet 会显示在这里。",
    tweetsPageTitle: "最近 Tweet", tweetsPageDetail: "按发布时间倒序展示最近 20 条 Tweet。", resetPageTitle: "Reset 历史与统计",
    resetPageDetail: "只统计已确认发生的 Reset；暗示和预告不会计入历史。", sampleCount: "样本数",
    beijingTime: "北京时间", source: "来源", interval: "距上一次重置", noHistory: "暂无已确认的 Reset 历史。",
    timeDistribution: "Reset 时间分布", calendar: "Reset 日历", calendarDetail: "点击日期查看当天的 Reset 记录。",
    unknown: "未知", snapshotGenerated: "快照生成于"
  },
  en: {
    languageButton: "中文", languageAria: "切换到中文", eyebrow: "PUBLIC RADAR · @thsottiaux",
    dataUpdated: "Data updated", tweets: "Tweets", dataUnavailable: "Data unavailable", refreshFailed: "Refresh failed",
    showingLastSuccess: "Showing the last successful data.", dataStale: "Data mirror is stale",
    staleDescription: "The public mirror is older than 15 minutes.", currentRadar: "CURRENT RADAR",
    lastKnownRadar: "Last known state", confidence: "Confidence", urgency: "Urgency", lastUpdated: "Last updated",
    noRadarState: "No Radar state is available.", latestSignal: "LATEST HIGH-VALUE SIGNAL",
    latestSignalHeading: "Recent Reset-related activity", monitorHealth: "MONITOR HEALTH", collectionStatus: "Collection status",
    dataMirror: "GitHub Data Mirror", lastSync: "Last sync", lastHeartbeat: "Last heartbeat",
    lastKnownStatus: "Last known state", noHeartbeat: "No heartbeat", emptyTweet: "(empty Tweet text)",
    unclassified: "Unclassified", openOnX: "Open on X ↗", translation: "Chinese translation", translationUnavailable: "Translation unavailable",
    original: "English original", reply: "Reply", overview: "Overview", recentTweets: "Recent Tweets", resetHistory: "Reset history",
    viewTweets: "View recent Tweets →", viewResets: "View Reset history →", lastReset: "Last confirmed Reset", nextReset: "Estimated next Reset",
    noReset: "No confirmed Reset", baselineNote: "Estimated as last confirmed Reset + 7 days",
    forecastSource: "Forecast basis", forecastSources: { weekly_baseline: "Weekly baseline", reset_hint: "Tibo hint", reset_announcement: "Explicit Tibo announcement", no_confirmed_reset: "No confirmed event" },
    signalWindow: { within_24h: "Within 24 hours", explicit_time: "Explicit time", unknown: "Unknown" },
    advice: "Quota usage advice", adviceReasons: {
      confirmed: "Reset confirmed; you can check whether your quota has refreshed.", radar_urgent: "Radar indicates a nearby Reset; consider using remaining quota first.",
      signal_within_24h: "A high-value Reset signal points to a possible window within 24 hours.",
      watch_or_baseline_near: "Radar needs attention, or the weekly baseline is getting close.", no_immediate_signal: "There is no clear Reset signal requiring immediate action."
    },
    adviceTitles: { reset_confirmed: "Reset confirmed — check quota refresh", use_soon: "Consider using quota soon", prioritize_usage: "Prioritize remaining quota", speed_up_gently: "You can use quota a little faster", normal_usage: "Normal usage" },
    states: { QUIET: "Quiet", WATCH: "Watch", LIKELY: "Likely", IMMINENT: "Imminent", ANNOUNCED: "Announced", CONFIRMED: "Confirmed", UNKNOWN: "Unknown" },
    categories: { reset_hint: "Reset hint", reset_announcement: "Reset announcement", reset_in_progress: "Reset in progress", reset_confirmed: "Reset confirmed", reset_denial: "Reset denial", quota_information: "Quota information", codex_related: "Codex related", unrelated: "Unrelated" },
    urgencyValues: { now: "now", within_6h: "within 6h", within_24h: "within 24h", "within 24h": "within 24h", within_3d: "within 3d", "within 3d": "within 3d", unknown: "unknown" },
    healthStates: { healthy: "healthy", warning: "warning", offline: "offline", stale: "stale", unknown: "unknown", fresh: "fresh" },
    monitorLabels: { backend: "Backend", profile_monitor: "Profile", replies_monitor: "Replies", search_backfill: "Search Backfill" },
    recentHighValue: "LATEST TIBO SIGNAL", noSignals: "No high-value signal is available.", noSignalsDetail: "The next Reset-related Tweet will appear here.",
    tweetsPageTitle: "Recent Tweets", tweetsPageDetail: "The latest 20 Tweets, sorted by publication time.", resetPageTitle: "Reset history and statistics",
    resetPageDetail: "Only confirmed Resets are counted; hints and announcements are not history.", sampleCount: "Sample size",
    beijingTime: "Beijing time", source: "Source", interval: "Since previous Reset", noHistory: "No confirmed Reset history.",
    timeDistribution: "Reset time distribution", calendar: "Reset calendar", calendarDetail: "Select a date to see that day's Reset records.",
    unknown: "unknown", snapshotGenerated: "Snapshot generated"
  }
};

function readLanguage(): Language {
  try { return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "zh"; } catch { return "zh"; }
}
function saveLanguage(next: Language): void {
  try { window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next); } catch { /* view-only fallback */ }
}
function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] ?? character);
}
function confidence(value: number | undefined): string { return typeof value === "number" ? Math.round(value * 100) + "%" : "—"; }
function formatDate(value: string | null | undefined, currentLanguage: Language, withTime = true): string {
  if (!value) return COPY[currentLanguage].unknown;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return COPY[currentLanguage].unknown;
  return date.toLocaleString(currentLanguage === "zh" ? "zh-CN" : "en-US", { dateStyle: withTime ? "medium" : "long", ...(withTime ? { timeStyle: "short" } : {}), timeZone: "Asia/Shanghai" });
}
function categoryLabel(category: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  return category ? copy.categories[category] ?? category.replaceAll("_", " ") : copy.unclassified;
}
function stateLabel(state: string, currentLanguage: Language): string { return COPY[currentLanguage].states[state] ?? state; }
function urgencyLabel(urgency: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  return urgency ? copy.urgencyValues[urgency] ?? urgency.replaceAll("_", " ") : copy.unknown;
}
function tweetTime(tweet: PublicTweet): string { return tweet.created_at ?? tweet.discovered_at ?? ""; }
function snapshotTimestamp(data: DashboardData): string | undefined {
  return data.meta?.mirror_synced_at ?? data.meta?.generated_at ?? data.index?.generated_at ?? data.health?.generated_at;
}
function route(): string {
  const hash = window.location.hash.replace(/^#/, "");
  return hash === "/tweets" || hash === "/resets" ? hash : "/";
}
function reportedHealthLabel(state: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  return state ? copy.healthStates[state.toLowerCase()] ?? state : copy.unknown;
}
function sourceLabel(source: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  if (!source) return copy.unknown;
  const labels: Record<string, string> = currentLanguage === "zh"
    ? { reset_confirmed_tweet: "已确认 Tweet 派生", reset_event: "Reset 事件记录", manual: "人工记录" }
    : { reset_confirmed_tweet: "Derived from confirmed Tweet", reset_event: "Recorded Reset event", manual: "Manual record" };
  return labels[source] ?? source.replaceAll("_", " ");
}

function tweetCard(tweet: PublicTweet, currentLanguage: Language, compact = false): string {
  const copy = COPY[currentLanguage];
  const classification = tweet.classification;
  const category = classification?.category ?? "unclassified";
  const link = tweet.url && /^https:\/\/x\.com\//.test(tweet.url) ? tweet.url : "";
  const translated = tweet.translation_zh
    ? "<div class='tweet-translation'><span class='field-label'>" + escapeHtml(copy.translation) + "</span><p>" + escapeHtml(tweet.translation_zh) + "</p></div>"
    : "<div class='tweet-translation unavailable'><span class='field-label'>" + escapeHtml(copy.translation) + "</span><p>" + escapeHtml(copy.translationUnavailable) + "</p></div>";
  return "<article class='tweet-card " + (compact ? "tweet-card-compact" : "") + "'>" +
    "<div class='signal-meta'><span class='category-tag category-" + escapeHtml(category) + "'>" + escapeHtml(categoryLabel(classification?.category, currentLanguage)) + "</span>" +
    "<span>" + escapeHtml(formatDate(tweetTime(tweet), currentLanguage)) + "</span>" +
    (tweet.is_reply ? "<span class='reply-tag'>" + escapeHtml(copy.reply) + "</span>" : "") +
    (classification?.urgency ? "<span>" + escapeHtml(urgencyLabel(classification.urgency, currentLanguage)) + "</span>" : "") + "</div>" +
    translated +
    "<div class='original-block'><span class='field-label'>" + escapeHtml(copy.original) + "</span><p class='tweet-original'>" + escapeHtml(tweet.text || copy.emptyTweet) + "</p></div>" +
    (classification?.reason ? "<p class='classification-reason'>" + escapeHtml(classification.reason) + "</p>" : "") +
    "<div class='signal-footer'><span>" + escapeHtml(copy.confidence) + " " + escapeHtml(confidence(classification?.confidence)) + "</span>" +
    (link ? "<a href='" + escapeHtml(link) + "' target='_blank' rel='noreferrer'>" + escapeHtml(copy.openOnX) + "</a>" : "") + "</div></article>";
}

function monitorRow(component: PublicHealthComponent | undefined, snapshotAt: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const name = component?.component ?? "unknown";
  const state: DisplayHealth = deriveDisplayHealth(component, snapshotAt);
  const label = copy.monitorLabels[name] ?? (name === "unknown" ? copy.unknown : name.replaceAll("_", " "));
  const timestamp = component?.last_heartbeat;
  const status = copy.healthStates[state];
  const lastKnown = state === "stale" && component?.state
    ? "<span class='muted'>" + escapeHtml(copy.lastKnownStatus) + "：" + escapeHtml(reportedHealthLabel(component.state, currentLanguage)) + "</span>" : "";
  return "<div class='monitor-row'><div><strong>" + escapeHtml(label) + "</strong><span class='muted'>" +
    escapeHtml(timestamp ? copy.lastHeartbeat + "：" + formatDate(timestamp, currentLanguage) : copy.noHeartbeat) + "</span>" + lastKnown + "</div>" +
    "<span class='status-dot status-" + state + "' aria-label='" + escapeHtml(status) + "'>" + escapeHtml(status) + "</span>" +
    "<span class='age'>" + escapeHtml(ageLabel(timestamp, Date.now(), currentLanguage)) + "</span></div>";
}
function mirrorRow(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const syncedAt = data.meta?.mirror_synced_at ?? data.meta?.generated_at ?? snapshotTimestamp(data);
  const state = deriveMirrorState(syncedAt);
  const status = copy.healthStates[state];
  return "<div class='monitor-row'><div><strong>" + escapeHtml(copy.dataMirror) + "</strong><span class='muted'>" +
    escapeHtml(syncedAt ? copy.lastSync + "：" + formatDate(syncedAt, currentLanguage) : copy.noHeartbeat) + "</span></div>" +
    "<span class='status-dot status-" + state + "'>" + escapeHtml(status) + "</span><span class='age'>" +
    escapeHtml(ageLabel(syncedAt, Date.now(), currentLanguage)) + "</span></div>";
}
function advicePanel(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const advice = data.radar?.usage_advice;
  const level = advice?.level?.toUpperCase() ?? "GREEN";
  const title = copy.adviceTitles[advice?.title_code ?? "normal_usage"] ?? copy.adviceTitles.normal_usage;
  const reason = copy.adviceReasons[advice?.reason_code ?? "no_immediate_signal"] ?? copy.adviceReasons.no_immediate_signal;
  return "<section class='advice-panel advice-" + level + "'><div class='advice-lamp' aria-hidden='true'></div><div><p class='eyebrow'>" +
    escapeHtml(copy.advice) + "</p><h2>" + escapeHtml(title) + "</h2><p>" + escapeHtml(reason) + "</p></div></section>";
}
function resetFacts(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const forecast = data.radar?.forecast;
  const last = forecast?.last_reset_at ? formatDate(forecast.last_reset_at, currentLanguage) : copy.noReset;
  let next = copy.unknown;
  if (forecast?.signal_window) next = copy.signalWindow[forecast.signal_window] ?? forecast.signal_window;
  else if (forecast?.estimated_next_reset_at) next = formatDate(forecast.estimated_next_reset_at, currentLanguage);
  const source = copy.forecastSources[forecast?.forecast_source ?? ""] ?? copy.unknown;
  return "<section class='reset-facts'><div class='fact-card'><p class='eyebrow'>" + escapeHtml(copy.lastReset) +
    "</p><strong>" + escapeHtml(last) + "</strong><span>" + escapeHtml(sourceLabel(forecast?.last_reset_source ?? undefined, currentLanguage)) + "</span></div>" +
    "<div class='fact-card'><p class='eyebrow'>" + escapeHtml(copy.nextReset) + "</p><strong>" + escapeHtml(next) +
    "</strong><span>" + escapeHtml(copy.forecastSource + "：" + source) + "</span></div></section>";
}
function commonHeader(currentRoute: string, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  return "<header class='topbar'><div><p class='eyebrow'>" + escapeHtml(copy.eyebrow) + "</p><h1>Codex Reset Radar</h1></div>" +
    "<div class='topbar-actions'><nav class='nav' aria-label='Navigation'><a class='" + (currentRoute === "/" ? "active" : "") + "' href='#/'>" + escapeHtml(copy.overview) +
    "</a><a class='" + (currentRoute === "/tweets" ? "active" : "") + "' href='#/tweets'>" + escapeHtml(copy.recentTweets) +
    "</a><a class='" + (currentRoute === "/resets" ? "active" : "") + "' href='#/resets'>" + escapeHtml(copy.resetHistory) + "</a></nav>" +
    "<button class='language-toggle' type='button' data-language-toggle aria-label='" + escapeHtml(copy.languageAria) + "'>" + escapeHtml(copy.languageButton) + "</button></div></header>";
}
function notices(data: DashboardData, currentLanguage: Language, refreshFailed: boolean): string {
  const copy = COPY[currentLanguage];
  const snapshotAt = snapshotTimestamp(data);
  const stale = snapshotAt ? Date.now() - Date.parse(snapshotAt) > 15 * 60 * 1000 : false;
  const failure = data.errors.length ? "<div class='notice notice-error'><strong>" + escapeHtml(refreshFailed ? copy.refreshFailed : copy.dataUnavailable) +
    "</strong><span>" + escapeHtml(refreshFailed ? copy.showingLastSuccess : data.errors.join(" · ")) + "</span></div>" : "";
  const staleNotice = stale ? "<div class='notice notice-stale'><strong>" + escapeHtml(copy.dataStale) + "</strong><span>" + escapeHtml(copy.staleDescription) + "</span></div>" : "";
  return failure + staleNotice;
}
function homePage(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const snapshotAt = snapshotTimestamp(data);
  const stale = snapshotAt ? Date.now() - Date.parse(snapshotAt) > 15 * 60 * 1000 : false;
  const state = data.radar?.state ?? "UNKNOWN";
  const highValue = highValueTweets(data.tweets).slice(0, 3);
  const health = ["backend", "profile_monitor", "replies_monitor", "search_backfill"]
    .map((name) => monitorRow((data.health?.components ?? []).find((component) => component.component === name), snapshotAt, currentLanguage)).join("");
  return "<section class='radar-card state-" + escapeHtml(state) + "'><div class='radar-card-heading'><div><p class='eyebrow'>" +
    escapeHtml(copy.currentRadar) + "</p><h2>" + escapeHtml(stateLabel(state, currentLanguage)) + "</h2></div><div class='radar-card-badges'>" +
    (stale ? "<span class='stale-badge'>⚠️ " + escapeHtml(copy.lastKnownRadar) + "</span>" : "") + "</div></div>" +
    "<div class='radar-facts'><div><span>" + escapeHtml(copy.confidence) + "</span><strong>" + escapeHtml(confidence(data.radar?.confidence)) +
    "</strong></div><div><span>" + escapeHtml(copy.urgency) + "</span><strong>" + escapeHtml(urgencyLabel(data.radar?.urgency, currentLanguage)) +
    "</strong></div><div><span>" + escapeHtml(copy.lastUpdated) + "</span><strong>" + escapeHtml(formatDate(data.radar?.updated_at, currentLanguage)) + "</strong></div></div>" +
    "<p class='radar-reason'>" + escapeHtml(data.radar?.reason ?? copy.noRadarState) + "</p></section>" +
    advicePanel(data, currentLanguage) + resetFacts(data, currentLanguage) +
    "<div class='dashboard-grid'><section class='panel latest-panel'><div class='panel-heading'><div><p class='eyebrow'>" + escapeHtml(copy.latestSignal) +
    "</p><h2>" + escapeHtml(copy.latestSignalHeading) + "</h2></div></div>" +
    (highValue.length ? highValue.map((tweet) => tweetCard(tweet, currentLanguage, true)).join("") : "<div class='empty-state'>" + escapeHtml(copy.noSignals) + "</div>") +
    "<div class='panel-link'><a href='#/tweets'>" + escapeHtml(copy.viewTweets) + "</a></div></section>" +
    "<section class='panel health-panel'><div class='panel-heading'><div><p class='eyebrow'>" + escapeHtml(copy.monitorHealth) + "</p><h2>" +
    escapeHtml(copy.collectionStatus) + "</h2></div></div><div class='monitor-list'>" + mirrorRow(data, currentLanguage) + health + "</div></section></div>" +
    "<div class='home-links'><a class='link-card' href='#/resets'><strong>" + escapeHtml(copy.resetHistory) + "</strong><span>" + escapeHtml(copy.viewResets) + "</span></a></div>";
}
function tweetsPage(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const tweets = sortByTweetTime(data.tweets).slice(0, 20);
  return "<section class='page-heading'><p class='eyebrow'>" + escapeHtml(copy.recentTweets) + "</p><h2>" + escapeHtml(copy.tweetsPageTitle) +
    "</h2><p>" + escapeHtml(copy.tweetsPageDetail) + "</p></section><section class='tweet-feed'>" +
    (tweets.length ? tweets.map((tweet) => tweetCard(tweet, currentLanguage)).join("") : "<div class='empty-state'>" + escapeHtml(copy.noSignals) + "</div>") + "</section>";
}
function eventDetails(events: PublicResetEvent[], currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  if (!events.length) return "<p class='muted'>" + escapeHtml(copy.noHistory) + "</p>";
  return events.map((event) => "<div class='calendar-detail-row'><strong>" + escapeHtml(event.beijing_time ?? copy.unknown) +
    "</strong><span>" + escapeHtml(sourceLabel(event.source, currentLanguage)) + "</span>" +
    (event.evidence_tweet_id ? "<a href='https://x.com/thsottiaux/status/" + encodeURIComponent(event.evidence_tweet_id) + "' target='_blank' rel='noreferrer'>" + escapeHtml(copy.openOnX) + "</a>" : "") + "</div>").join("");
}
function calendar(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const events = data.resets?.events ?? [];
  const dateKey = events[0]?.beijing_date ?? new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai" }).format(new Date());
  const [year, month] = dateKey.split("-").map(Number);
  const first = new Date(Date.UTC(year, month - 1, 1));
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const start = first.getUTCDay();
  const weekdays = currentLanguage === "zh" ? ["日", "一", "二", "三", "四", "五", "六"] : ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
  const cells: string[] = weekdays.map((day) => "<span class='calendar-weekday'>" + day + "</span>");
  for (let i = 0; i < start; i += 1) cells.push("<span class='calendar-empty'></span>");
  for (let day = 1; day <= days; day += 1) {
    const key = year + "-" + String(month).padStart(2, "0") + "-" + String(day).padStart(2, "0");
    const dayEvents = events.filter((event) => event.beijing_date === key);
    cells.push("<button type='button' class='calendar-day " + (dayEvents.length ? "has-reset" : "") + "' data-calendar-date='" + key + "'>" + day +
      (dayEvents.length ? "<i aria-label='" + escapeHtml(String(dayEvents.length)) + "'>●</i>" : "") + "</button>");
  }
  return "<section class='panel calendar-panel'><div class='panel-heading'><div><p class='eyebrow'>" + escapeHtml(copy.calendar) + "</p><h2>" +
    new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString(currentLanguage === "zh" ? "zh-CN" : "en-US", { year: "numeric", month: "long", timeZone: "Asia/Shanghai" }) +
    "</h2></div></div><div class='calendar-grid'>" + cells.join("") + "</div><p class='calendar-help'>" + escapeHtml(copy.calendarDetail) +
    "</p><div class='calendar-detail' data-calendar-detail>" + eventDetails(events.filter((event) => event.beijing_date === dateKey), currentLanguage) + "</div></section>";
}
function resetsPage(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const resets = data.resets;
  const events = resets?.events ?? [];
  const distribution = resets?.time_distribution ?? {};
  const rows = events.map((event) => "<tr><td>" + escapeHtml(event.beijing_date ?? copy.unknown) + "</td><td>" +
    escapeHtml(event.beijing_time ?? copy.unknown) + "</td><td>" + escapeHtml(event.interval_label ?? "—") + "</td><td>" +
    escapeHtml(sourceLabel(event.source, currentLanguage)) + "</td><td>" + (event.evidence_tweet_id ? "<a href='https://x.com/thsottiaux/status/" +
    encodeURIComponent(event.evidence_tweet_id) + "' target='_blank' rel='noreferrer'>" + escapeHtml(copy.openOnX) + "</a>" : "—") + "</td></tr>").join("");
  const dist = ["00–06", "06–12", "12–18", "18–24"].map((bucket) => "<div class='distribution-row'><span>" + bucket + "</span><strong>" +
    String(distribution[bucket] ?? 0) + "</strong></div>").join("");
  return "<section class='page-heading'><p class='eyebrow'>" + escapeHtml(copy.resetHistory) + "</p><h2>" + escapeHtml(copy.resetPageTitle) +
    "</h2><p>" + escapeHtml(copy.resetPageDetail) + "</p></section><div class='stats-grid'><div class='stat-card'><span>" +
    escapeHtml(copy.sampleCount) + "</span><strong>" + String(resets?.sample_count ?? events.length) + "</strong></div><div class='stat-card'><span>" +
    escapeHtml(copy.timeDistribution) + "</span><strong>" + escapeHtml(resets?.timezone === "Asia/Shanghai" ? copy.beijingTime : (resets?.timezone ?? copy.unknown)) +
    "</strong></div></div><div class='resets-layout'>" + calendar(data, currentLanguage) + "<section class='panel distribution-panel'><div class='panel-heading'><h2>" +
    escapeHtml(copy.timeDistribution) + "</h2></div><div class='distribution-list'>" + dist + "</div></section></div>" +
    "<section class='panel table-panel'><div class='panel-heading'><h2>" + escapeHtml(copy.resetHistory) + "</h2></div>" +
    (rows ? "<div class='table-scroll'><table><thead><tr><th>" + escapeHtml(currentLanguage === "zh" ? "日期" : "Date") + "</th><th>" +
    escapeHtml(copy.beijingTime) + "</th><th>" + escapeHtml(copy.interval) + "</th><th>" + escapeHtml(copy.source) + "</th><th>X</th></tr></thead><tbody>" +
    rows + "</tbody></table></div>" : "<div class='empty-state'>" + escapeHtml(copy.noHistory) + "</div>") + "</section>";
}
function footer(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  return "<footer class='footer'><span>" + escapeHtml(copy.dataUpdated) + "：" + escapeHtml(formatDate(snapshotTimestamp(data), currentLanguage)) +
    " · " + escapeHtml(ageLabel(snapshotTimestamp(data), Date.now(), currentLanguage)) + "</span><span>" + escapeHtml(copy.snapshotGenerated) +
    " " + escapeHtml(formatDate(data.index?.generated_at, currentLanguage)) + "</span></footer>";
}
function render(data: DashboardData, refreshFailed = lastRefreshFailed): void {
  if (!app) return;
  const currentRoute = route();
  const copy = COPY[language];
  const content = currentRoute === "/tweets" ? tweetsPage(data, language) : currentRoute === "/resets" ? resetsPage(data, language) : homePage(data, language);
  const tweetCount = data.index?.tweet_count ?? data.tweets.length;
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  app.innerHTML = commonHeader(currentRoute, language) + notices(data, language, refreshFailed) +
    "<div class='topbar-meta'>" + tweetCount + " " + escapeHtml(copy.tweets) + "</div><main class='page-content'>" + content + "</main>" + footer(data, language);
  app.querySelector<HTMLButtonElement>("[data-language-toggle]")?.addEventListener("click", () => {
    language = language === "zh" ? "en" : "zh"; saveLanguage(language); render(data, refreshFailed);
  });
  app.querySelectorAll<HTMLButtonElement>("[data-calendar-date]").forEach((button) => button.addEventListener("click", () => {
    const selected = button.dataset.calendarDate;
    const events = data.resets?.events.filter((event) => event.beijing_date === selected) ?? [];
    const detail = app.querySelector<HTMLElement>("[data-calendar-detail]");
    if (detail) detail.innerHTML = eventDetails(events, language);
  }));
}
async function refreshDashboard(): Promise<void> {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const next = await loadDashboardData(fetch, DATA_BASE_URL);
    const hadPreviousData = Boolean(lastSuccessfulData);
    const merged = lastSuccessfulData ? mergeDashboardData(lastSuccessfulData, next) : next;
    lastSuccessfulData = merged; lastRefreshFailed = hadPreviousData && next.errors.length > 0; render(merged);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Data unavailable";
    if (lastSuccessfulData) { lastRefreshFailed = true; render({ ...lastSuccessfulData, errors: [message] }, true); }
    else render({ index: null, tweets: [], radar: null, health: null, meta: null, resets: null, errors: [message] });
  } finally { refreshInFlight = false; }
}

if (app) {
  void refreshDashboard();
  window.setInterval(() => void refreshDashboard(), REFRESH_INTERVAL_MS);
  window.addEventListener("hashchange", () => { if (lastSuccessfulData) render(lastSuccessfulData); });
}
