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
import { adviceTone, radarStateToken } from "./ui";

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
  refreshData: string; skipToContent: string;
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
  navLabel: string; records: string; why: string; id: string; autoRefresh: string;
  dataSource: string; status: string; reset: string; forecastBasis: string; latest: string;
  viewDetails: string; timezone: string; confirmedReset: string; opsMatrix: string;
}

const COPY: Record<Language, Copy> = {
  zh: {
    languageButton: "EN", languageAria: "切换到英文", eyebrow: "公开情报控制台 · @thsottiaux",
    dataUpdated: "数据更新时间", refreshData: "刷新数据", skipToContent: "跳转到主要内容", tweets: "条 Tweet", dataUnavailable: "数据不可用", refreshFailed: "刷新失败",
    showingLastSuccess: "正在显示最后一次成功数据。", dataStale: "数据镜像过期",
    staleDescription: "公开快照超过 15 分钟未更新；监控显示为最后已知状态。", currentRadar: "当前 Radar",
    lastKnownRadar: "最后已知状态", confidence: "置信度", urgency: "紧迫程度", lastUpdated: "最后更新",
    noRadarState: "当前没有可用的 Radar 状态。", latestSignal: "最新信号",
    latestSignalHeading: "Tibo 的高价值 Reset 动态", monitorHealth: "监控状态", collectionStatus: "采集状态",
    dataMirror: "数据镜像", lastSync: "最后同步", lastHeartbeat: "最后心跳", lastKnownStatus: "最后已知状态",
    noHeartbeat: "暂无心跳", emptyTweet: "（Tweet 文本为空）", unclassified: "未分类", openOnX: "在 X 上打开 ↗",
    translation: "中文翻译", translationUnavailable: "翻译暂不可用", original: "英文原文", reply: "回复",
    overview: "概览", recentTweets: "最近推文", resetHistory: "重置历史", viewTweets: "查看最近 Tweet →",
    viewResets: "查看重置历史 →", lastReset: "最近一次确认重置", nextReset: "预计下一次重置",
    noReset: "暂无已确认的 Reset", baselineNote: "按最近一次确认重置 + 7 天估算", forecastSource: "预测依据",
    forecastSources: { weekly_baseline: "周期推算", reset_hint: "Tibo 重置暗示", reset_announcement: "Tibo 明确预告", no_confirmed_reset: "暂无确认事件" },
    signalWindow: { within_24h: "未来 24 小时", explicit_time: "明确时间", unknown: "未知" },
    advice: "额度使用建议", adviceReasons: {
      confirmed: "Reset 已确认，可检查额度是否刷新。", radar_urgent: "Radar 显示 Reset 已接近，可以优先使用剩余额度。",
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
    tweetsPageTitle: "最近推文", tweetsPageDetail: "按发布时间倒序展示最近 20 条 Tweet。", resetPageTitle: "Reset 历史与统计",
    resetPageDetail: "只统计已确认发生的 Reset；暗示和预告不会计入历史。", sampleCount: "样本数", beijingTime: "北京时间",
    source: "来源", interval: "距上一次重置", noHistory: "暂无已确认的 Reset 历史。", timeDistribution: "时间分布",
    calendar: "Reset 日历", calendarDetail: "点击日期查看当天的 Reset 记录。", unknown: "未知", snapshotGenerated: "快照生成于",
    navLabel: "主导航", records: "条记录", why: "判断原因", id: "技术 ID", autoRefresh: "每 60 秒自动刷新",
    dataSource: "数据来源", status: "状态", reset: "RESET", forecastBasis: "依据", latest: "最新", viewDetails: "查看详情",
    timezone: "时区", confirmedReset: "确认事件", opsMatrix: "运维矩阵"
  },
  en: {
    languageButton: "中文", languageAria: "切换到中文", eyebrow: "PUBLIC INTELLIGENCE CONSOLE · @thsottiaux",
    dataUpdated: "Data updated", refreshData: "REFRESH DATA", skipToContent: "Skip to main content", tweets: "Tweets", dataUnavailable: "Data unavailable", refreshFailed: "Refresh failed",
    showingLastSuccess: "Showing the last successful data.", dataStale: "Data mirror is stale",
    staleDescription: "The public snapshot is older than 15 minutes; monitor states are last known.", currentRadar: "CURRENT RADAR",
    lastKnownRadar: "LAST KNOWN STATE", confidence: "CONFIDENCE", urgency: "URGENCY", lastUpdated: "LAST UPDATED",
    noRadarState: "No Radar state is available.", latestSignal: "LATEST SIGNAL",
    latestSignalHeading: "High-value Reset activity from Tibo", monitorHealth: "MONITOR STATUS", collectionStatus: "COLLECTION STATUS",
    dataMirror: "DATA MIRROR", lastSync: "LAST SYNC", lastHeartbeat: "LAST HEARTBEAT", lastKnownStatus: "LAST KNOWN STATE",
    noHeartbeat: "No heartbeat", emptyTweet: "(empty Tweet text)", unclassified: "Unclassified", openOnX: "Open on X ↗",
    translation: "CHINESE TRANSLATION", translationUnavailable: "Translation unavailable", original: "ENGLISH ORIGINAL", reply: "REPLY",
    overview: "Overview", recentTweets: "Recent Tweets", resetHistory: "Reset History", viewTweets: "View recent Tweets →",
    viewResets: "View Reset History →", lastReset: "LAST CONFIRMED RESET", nextReset: "ESTIMATED NEXT RESET",
    noReset: "No confirmed Reset", baselineNote: "Estimated as last confirmed Reset + 7 days", forecastSource: "FORECAST BASIS",
    forecastSources: { weekly_baseline: "Weekly baseline", reset_hint: "Tibo Reset hint", reset_announcement: "Explicit Tibo announcement", no_confirmed_reset: "No confirmed event" },
    signalWindow: { within_24h: "Within 24 hours", explicit_time: "Explicit time", unknown: "Unknown" },
    advice: "QUOTA USAGE ADVICE", adviceReasons: {
      confirmed: "Reset confirmed; check whether your quota has refreshed.", radar_urgent: "Radar indicates a nearby Reset; consider using remaining quota first.",
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
    tweetsPageTitle: "Recent Tweets", tweetsPageDetail: "The latest 20 Tweets, sorted by publication time.", resetPageTitle: "Reset History & Statistics",
    resetPageDetail: "Only confirmed Resets are counted; hints and announcements are not history.", sampleCount: "SAMPLE SIZE", beijingTime: "BEIJING TIME",
    source: "SOURCE", interval: "SINCE PREVIOUS RESET", noHistory: "No confirmed Reset history.", timeDistribution: "TIME DISTRIBUTION",
    calendar: "RESET CALENDAR", calendarDetail: "Select a date to see that day's Reset records.", unknown: "unknown", snapshotGenerated: "Snapshot generated",
    navLabel: "Primary navigation", records: "records", why: "WHY THIS STATE", id: "TECHNICAL ID", autoRefresh: "Auto-refresh every 60 seconds",
    dataSource: "DATA SOURCE", status: "STATUS", reset: "RESET", forecastBasis: "BASIS", latest: "LATEST", viewDetails: "VIEW DETAILS",
    timezone: "TIMEZONE", confirmedReset: "CONFIRMED EVENT", opsMatrix: "OPS MATRIX"
  }
};

function readLanguage(): Language {
  try { return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "zh"; } catch { return "zh"; }
}
function saveLanguage(next: Language): void {
  try { window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next); } catch { /* view-only fallback */ }
}
function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] ?? character);
}
function safeToken(value: string | undefined, fallback = "unknown"): string {
  const token = (value ?? "").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
  return token || fallback;
}
function confidence(value: number | undefined): string { return typeof value === "number" ? Math.round(value * 100) + "%" : "—"; }
function formatDate(value: string | null | undefined, currentLanguage: Language, withTime = true): string {
  if (!value) return COPY[currentLanguage].unknown;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return COPY[currentLanguage].unknown;
  return date.toLocaleString(currentLanguage === "zh" ? "zh-CN" : "en-US", { dateStyle: withTime ? "medium" : "long", ...(withTime ? { timeStyle: "short" } : {}), timeZone: "Asia/Shanghai" });
}
function formatStamp(value: string | null | undefined, currentLanguage: Language): { day: string; time: string; full: string } {
  if (!value) return { day: COPY[currentLanguage].unknown, time: "—", full: COPY[currentLanguage].unknown };
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { day: COPY[currentLanguage].unknown, time: "—", full: COPY[currentLanguage].unknown };
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date).map((part) => [part.type, part.value]));
  return { day: `${parts.month}.${parts.day}`, time: `${parts.hour}:${parts.minute}`, full: formatDate(value, currentLanguage) };
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
function intervalDisplay(event: PublicResetEvent, currentLanguage: Language): string {
  if (currentLanguage === "zh") return event.interval_label ?? "—";
  if (typeof event.interval_seconds !== "number" || !Number.isFinite(event.interval_seconds)) return "—";
  const hours = Math.max(0, Math.floor(event.interval_seconds / 3600));
  const days = Math.floor(hours / 24);
  const remaining = hours % 24;
  if (!days) return `${remaining}h`;
  return `${days}d ${remaining}h`;
}
function snapshotIsStale(data: DashboardData): boolean { return deriveMirrorState(snapshotTimestamp(data)) === "stale"; }

function translationBlock(tweet: PublicTweet, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  if (tweet.translation_zh) {
    return `<div class="translation-block"><span class="field-label">${escapeHtml(copy.translation)}</span><p>${escapeHtml(tweet.translation_zh)}</p></div>`;
  }
  return `<div class="translation-block translation-missing"><span class="field-label">${escapeHtml(copy.translation)}</span><p>${escapeHtml(copy.translationUnavailable)}</p></div>`;
}

function tweetRow(tweet: PublicTweet, currentLanguage: Language, compact = false): string {
  const copy = COPY[currentLanguage];
  const classification = tweet.classification;
  const category = classification?.category ?? "unclassified";
  const link = tweet.url && /^https:\/\/x\.com\//.test(tweet.url) ? tweet.url : "";
  const time = tweetTime(tweet);
  return `<article class="signal-row${compact ? " signal-row-compact" : ""}">
    <div class="signal-row-rail">
      <span class="record-index">${escapeHtml(tweet.is_reply ? copy.reply : currentLanguage === "zh" ? "推文" : "TWEET")}</span>
      <time datetime="${escapeHtml(time)}">${escapeHtml(formatDate(time, currentLanguage))}</time>
      <span class="rail-id">${escapeHtml(tweet.tweet_id ? `#${tweet.tweet_id}` : "#—")}</span>
    </div>
    <div class="signal-row-content">
      <div class="row-meta">
        <span class="category-tag category-${safeToken(category)}">${escapeHtml(categoryLabel(category, currentLanguage))}</span>
        ${classification?.urgency ? `<span class="meta-text">${escapeHtml(urgencyLabel(classification.urgency, currentLanguage))}</span>` : ""}
        <span class="meta-text">${escapeHtml(copy.confidence)} ${escapeHtml(confidence(classification?.confidence))}</span>
      </div>
      ${translationBlock(tweet, currentLanguage)}
      <div class="original-block"><span class="field-label">${escapeHtml(copy.original)}</span><p>${escapeHtml(tweet.text || copy.emptyTweet)}</p></div>
      ${classification?.reason ? `<div class="reason-block"><span class="field-label">${escapeHtml(copy.why)}</span><p>${escapeHtml(classification.reason)}</p></div>` : ""}
      <div class="signal-footer">
        <span class="source-id">${escapeHtml(copy.id)} <code>${escapeHtml(tweet.tweet_id ?? "—")}</code></span>
        ${link ? `<a class="text-link" href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${escapeHtml(copy.openOnX)}</a>` : ""}
      </div>
    </div>
  </article>`;
}

function statusMark(state: string, label: string): string {
  return `<span class="status-mark status-${safeToken(state)}"><span class="status-square" aria-hidden="true"></span>${escapeHtml(label)}</span>`;
}
function monitorRow(component: PublicHealthComponent | undefined, snapshotAt: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const name = component?.component ?? "unknown";
  const state: DisplayHealth = deriveDisplayHealth(component, snapshotAt);
  const label = copy.monitorLabels[name] ?? (name === "unknown" ? copy.unknown : name.replaceAll("_", " "));
  const timestamp = component?.last_heartbeat;
  const status = copy.healthStates[state] ?? copy.unknown;
  const lastKnown = state === "stale" && component?.state ? `<span class="last-known">${escapeHtml(copy.lastKnownStatus)}：${escapeHtml(reportedHealthLabel(component.state, currentLanguage))}</span>` : "";
  return `<div class="ops-row">
    <div class="ops-name"><strong>${escapeHtml(label)}</strong><span class="muted">${escapeHtml(timestamp ? formatDate(timestamp, currentLanguage) : copy.noHeartbeat)}</span>${lastKnown}</div>
    <div>${statusMark(state, status)}</div>
    <div class="ops-age">${escapeHtml(ageLabel(timestamp, Date.now(), currentLanguage))}</div>
  </div>`;
}
function mirrorRow(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const syncedAt = data.meta?.mirror_synced_at ?? data.meta?.generated_at ?? snapshotTimestamp(data);
  const state = deriveMirrorState(syncedAt);
  const status = copy.healthStates[state] ?? copy.unknown;
  return `<div class="mirror-strip">
    <div class="mirror-title"><span class="field-label">${escapeHtml(copy.dataMirror)}</span><strong>${escapeHtml(copy.dataSource)} / ${escapeHtml(data.meta?.data_branch ?? "data")}</strong></div>
    <div class="mirror-status">${statusMark(state, status)}</div>
    <div class="mirror-time"><span>${escapeHtml(copy.lastSync)}</span><strong>${escapeHtml(ageLabel(syncedAt, Date.now(), currentLanguage))}</strong><small>${escapeHtml(syncedAt ? formatDate(syncedAt, currentLanguage) : copy.unknown)}</small></div>
  </div>`;
}

function advicePanel(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const advice = data.radar?.usage_advice;
  const level = advice?.level?.toUpperCase() ?? "GREEN";
  const title = copy.adviceTitles[advice?.title_code ?? "normal_usage"] ?? copy.adviceTitles.normal_usage;
  const reason = copy.adviceReasons[advice?.reason_code ?? "no_immediate_signal"] ?? copy.adviceReasons.no_immediate_signal;
  return `<section class="advice-module advice-${adviceTone(level)}">
    <div class="advice-code"><span class="field-label">${escapeHtml(copy.advice)}</span><strong>${escapeHtml(level)}</strong></div>
    <div class="advice-copy"><h2>${escapeHtml(title)}</h2><p>${escapeHtml(reason)}</p></div>
  </section>`;
}

function resetMetric(value: string | null | undefined, title: string, subline: string, age: string, currentLanguage: Language): string {
  const stamp = formatStamp(value, currentLanguage);
  return `<article class="metric-cell reset-metric"><span class="field-label">${escapeHtml(title)}</span><strong>${escapeHtml(stamp.day)}</strong><b>${escapeHtml(stamp.time)}</b><span class="metric-subline">${escapeHtml(subline)}</span><small class="metric-age">${escapeHtml(age)}</small></article>`;
}
function overviewBoard(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const radar = data.radar;
  const rawState = (radar?.state ?? "UNKNOWN").toUpperCase();
  const state = radarStateToken(rawState);
  const forecast = radar?.forecast;
  const stale = snapshotIsStale(data);
  const lastReset = forecast?.last_reset_at;
  const nextReset = forecast?.estimated_next_reset_at;
  const forecastSource = copy.forecastSources[forecast?.forecast_source ?? ""] ?? copy.unknown;
  const nextSubline = forecast?.signal_window ? `${copy.forecastSource}：${copy.signalWindow[forecast.signal_window] ?? forecast.signal_window}` : `${copy.forecastBasis}：${forecastSource}`;
  const lastSubline = `${copy.beijingTime} · ${sourceLabel(forecast?.last_reset_source ?? undefined, currentLanguage)}`;
  return `<section class="overview-board">
    <article class="radar-state-board state-${escapeHtml(state)}">
      <div class="board-topline"><span class="field-label">${escapeHtml(copy.currentRadar)}</span><span class="state-code">${escapeHtml(rawState)}</span></div>
      <div class="radar-display">${escapeHtml(stateLabel(rawState, currentLanguage))}</div>
      <div class="radar-note"><span class="field-label">${escapeHtml(stale ? copy.lastKnownRadar : copy.status)}</span><p>${escapeHtml(radar?.reason ?? copy.noRadarState)}</p></div>
      <div class="radar-bottom"><span>${escapeHtml(copy.lastUpdated)}：${escapeHtml(formatDate(radar?.updated_at, currentLanguage))}</span><span>${escapeHtml(stale ? copy.dataStale : copy.autoRefresh)}</span></div>
    </article>
    <article class="metric-cell confidence-metric"><span class="field-label">${escapeHtml(copy.confidence)}</span><strong>${escapeHtml(confidence(radar?.confidence))}</strong><span class="metric-subline">${escapeHtml(copy.status)} / ${escapeHtml(rawState)}</span></article>
    <article class="metric-cell urgency-metric"><span class="field-label">${escapeHtml(copy.urgency)}</span><strong>${escapeHtml(urgencyLabel(radar?.urgency, currentLanguage))}</strong><span class="metric-subline">${escapeHtml(copy.latest)}</span></article>
    ${resetMetric(lastReset, copy.lastReset, lastSubline, lastReset ? ageLabel(lastReset, Date.now(), currentLanguage) : copy.unknown, currentLanguage)}
    ${resetMetric(nextReset, copy.nextReset, nextSubline, nextReset ? formatDate(nextReset, currentLanguage) : copy.unknown, currentLanguage)}
  </section>`;
}

function notices(data: DashboardData, currentLanguage: Language, refreshFailed: boolean): string {
  const copy = COPY[currentLanguage];
  const parts: string[] = [];
  if (data.errors.length || refreshFailed) parts.push(`<div class="notice notice-error"><strong>${escapeHtml(copy.dataUnavailable)} / ${escapeHtml(copy.refreshFailed)}</strong><span>${escapeHtml(copy.showingLastSuccess)}</span></div>`);
  if (snapshotIsStale(data)) parts.push(`<div class="notice notice-stale"><strong>${escapeHtml(copy.dataStale)}</strong><span>${escapeHtml(copy.staleDescription)}</span></div>`);
  return parts.join("");
}

function sidebar(currentRoute: string, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const nav = (href: string, index: string, label: string) => `<a class="side-link${currentRoute === href ? " active" : ""}" href="#${href}"><span class="nav-index">${index}</span><span>${escapeHtml(label)}</span></a>`;
  return `<aside class="sidebar"><div class="brand-lockup"><span class="brand-mark">CRR</span><div><strong>Codex Reset</strong><span>Radar / Grid Ops</span></div></div>
    <div class="sidebar-label">${escapeHtml(copy.navLabel)}</div><nav class="side-nav" aria-label="${escapeHtml(copy.navLabel)}">${nav("/", "01", copy.overview)}${nav("/tweets", "02", copy.recentTweets)}${nav("/resets", "03", copy.resetHistory)}</nav>
    <div class="sidebar-footer"><span class="field-label">${escapeHtml(copy.dataSource)}</span><strong>GitHub / data</strong><span>${escapeHtml(copy.autoRefresh)}</span></div></aside>`;
}
function header(currentRoute: string, currentLanguage: Language, data: DashboardData): string {
  const copy = COPY[currentLanguage];
  const tweetCount = data.index?.tweet_count ?? data.tweets.length;
  const link = (href: string, label: string) => `<a class="mobile-nav-link${currentRoute === href ? " active" : ""}" href="#${href}">${escapeHtml(label)}</a>`;
  return `<header class="topbar"><div class="mobile-brand"><span class="brand-mark">CRR</span><strong>Codex Reset Radar</strong></div><div class="topbar-context"><span class="field-label">${escapeHtml(copy.eyebrow)}</span><span class="topbar-title">${escapeHtml(currentRoute === "/" ? copy.overview : currentRoute === "/tweets" ? copy.recentTweets : copy.resetHistory)}</span></div><nav class="mobile-nav" aria-label="${escapeHtml(copy.navLabel)}">${link("/", copy.overview)}${link("/tweets", copy.recentTweets)}${link("/resets", copy.resetHistory)}</nav><div class="topbar-actions"><span class="record-count">${escapeHtml(tweetCount)} ${escapeHtml(copy.tweets)}</span><button class="refresh-button" type="button" data-refresh>${escapeHtml(copy.refreshData)} ↻</button><button class="language-toggle" type="button" data-language-toggle aria-label="${escapeHtml(copy.languageAria)}">${escapeHtml(copy.languageButton)}</button></div></header>`;
}

function homePage(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const signals = highValueTweets(data.tweets).slice(0, 3);
  const snapshotAt = snapshotTimestamp(data);
  const health = ["backend", "profile_monitor", "replies_monitor", "search_backfill"].map((name) => monitorRow((data.health?.components ?? []).find((component) => component.component === name), snapshotAt, currentLanguage)).join("");
  return `<section class="page-intro"><div><span class="section-number">01</span><span class="field-label">${escapeHtml(copy.overview)}</span><h1>Codex Reset Radar</h1></div><p>${escapeHtml(copy.latestSignalHeading)}</p></section>${overviewBoard(data, currentLanguage)}${advicePanel(data, currentLanguage)}<section class="split-grid"><section class="panel latest-panel"><div class="panel-header"><div><span class="section-number">02</span><span class="field-label">${escapeHtml(copy.latestSignal)}</span><h2>${escapeHtml(copy.latestSignalHeading)}</h2></div><span class="panel-count">${signals.length} / 3</span></div><div class="signal-list">${signals.length ? signals.map((tweet) => tweetRow(tweet, currentLanguage, true)).join("") : `<div class="empty-state"><strong>${escapeHtml(copy.noSignals)}</strong><p>${escapeHtml(copy.noSignalsDetail)}</p></div>`}</div><a class="panel-cta" href="#/tweets">${escapeHtml(copy.viewTweets)}</a></section><section class="panel ops-panel"><div class="panel-header"><div><span class="section-number">03</span><span class="field-label">${escapeHtml(copy.monitorHealth)}</span><h2>${escapeHtml(copy.opsMatrix)}</h2></div><span class="panel-count">4 / 4</span></div><div class="ops-matrix"><div class="ops-header"><span>${escapeHtml(copy.dataSource)}</span><span>${escapeHtml(copy.status)}</span><span>${escapeHtml(copy.lastHeartbeat)}</span></div>${health}</div>${mirrorRow(data, currentLanguage)}</section></section><div class="cta-grid"><a href="#/tweets"><span class="section-number">02</span><strong>${escapeHtml(copy.recentTweets)}</strong><span>${escapeHtml(copy.viewTweets)}</span></a><a href="#/resets"><span class="section-number">03</span><strong>${escapeHtml(copy.resetHistory)}</strong><span>${escapeHtml(copy.viewResets)}</span></a></div>`;
}

function pageHeading(number: string, title: string, detail: string): string {
  return `<section class="page-intro page-intro-inner"><div><span class="section-number">${escapeHtml(number)}</span><span class="field-label">${escapeHtml(title)}</span><h1>${escapeHtml(title)}</h1></div><p>${escapeHtml(detail)}</p></section>`;
}
function tweetsPage(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const tweets = sortByTweetTime(data.tweets).slice(0, 20);
  return `${pageHeading("02", copy.tweetsPageTitle, copy.tweetsPageDetail)}<section class="archive-panel"><div class="archive-toolbar"><div><span class="field-label">${escapeHtml(copy.recentTweets)}</span><strong>${tweets.length} / 20 ${escapeHtml(copy.records)}</strong></div><span>${escapeHtml(copy.dataUpdated)}：${escapeHtml(formatDate(snapshotTimestamp(data), currentLanguage))}</span></div><div class="archive-header"><span>${escapeHtml(copy.dataSource)}</span><span>${escapeHtml(copy.status)}</span><span>${escapeHtml(copy.original)}</span><span>${escapeHtml(copy.id)}</span></div>${tweets.length ? tweets.map((tweet) => tweetRow(tweet, currentLanguage)).join("") : `<div class="empty-state">${escapeHtml(copy.noSignals)}</div>`}</section>`;
}

function eventDetails(events: PublicResetEvent[], currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  if (!events.length) return `<p class="detail-empty">${escapeHtml(copy.noHistory)}</p>`;
  return events.map((event) => `<div class="calendar-event"><strong>${escapeHtml(event.beijing_time ?? copy.unknown)}</strong><span>${escapeHtml(sourceLabel(event.source, currentLanguage))}</span>${event.evidence_tweet_id ? `<a class="text-link" href="https://x.com/thsottiaux/status/${encodeURIComponent(event.evidence_tweet_id)}" target="_blank" rel="noreferrer">${escapeHtml(copy.openOnX)}</a>` : ""}</div>`).join("");
}
function calendar(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const events = data.resets?.events ?? [];
  const selected = events[0]?.beijing_date ?? "";
  const anchor = events.find((event) => event.beijing_date === selected)?.event_time ?? events[0]?.event_time;
  const anchorDate = anchor ? new Date(anchor) : new Date();
  const year = anchorDate.getUTCFullYear();
  const month = anchorDate.getUTCMonth() + 1;
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const start = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  const weekdays = currentLanguage === "zh" ? ["日", "一", "二", "三", "四", "五", "六"] : ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
  const cells: string[] = weekdays.map((day) => `<span class="calendar-weekday">${day}</span>`);
  for (let i = 0; i < start; i += 1) cells.push(`<span class="calendar-empty" aria-hidden="true"></span>`);
  for (let day = 1; day <= days; day += 1) {
    const key = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const dayEvents = events.filter((event) => event.beijing_date === key);
    cells.push(`<button type="button" class="calendar-day${dayEvents.length ? " has-reset" : ""}${key === selected ? " selected" : ""}" data-calendar-date="${escapeHtml(key)}" aria-pressed="${key === selected ? "true" : "false"}"><span>${day}</span>${dayEvents.length ? `<small aria-label="${escapeHtml(copy.reset)}">${escapeHtml(copy.reset)}</small>` : ""}</button>`);
  }
  return `<section class="panel calendar-panel"><div class="panel-header"><div><span class="section-number">01</span><span class="field-label">${escapeHtml(copy.calendar)}</span><h2>${escapeHtml(new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString(currentLanguage === "zh" ? "zh-CN" : "en-US", { year: "numeric", month: "long", timeZone: "Asia/Shanghai" }))}</h2></div><span class="panel-count">${events.length}</span></div><div class="calendar-grid">${cells.join("")}</div><p class="calendar-help">${escapeHtml(copy.calendarDetail)}</p><div class="calendar-detail" data-calendar-detail>${eventDetails(events.filter((event) => event.beijing_date === selected), currentLanguage)}</div></section>`;
}
function distribution(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const values = ["00–06", "06–12", "12–18", "18–24"].map((bucket) => ({ bucket, count: data.resets?.time_distribution?.[bucket] ?? 0 }));
  const max = Math.max(1, ...values.map((value) => value.count));
  return `<section class="panel distribution-panel"><div class="panel-header"><div><span class="section-number">02</span><span class="field-label">${escapeHtml(copy.timeDistribution)}</span><h2>${escapeHtml(copy.beijingTime)}</h2></div><span class="panel-count">${escapeHtml(String(data.resets?.sample_count ?? 0))}</span></div><div class="distribution-list">${values.map((value) => `<div class="distribution-row"><span>${escapeHtml(value.bucket)}</span><div class="distribution-bar"><i style="width:${Math.round(value.count / max * 100)}%"></i></div><strong>${value.count}</strong></div>`).join("")}</div></section>`;
}
function history(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const events = data.resets?.events ?? [];
  const dateLabel = currentLanguage === "zh" ? "日期" : "DATE";
  const timeLabel = currentLanguage === "zh" ? copy.beijingTime : "TIME";
  const intervalLabel = currentLanguage === "zh" ? copy.interval : "INTERVAL";
  const sourceLabelText = currentLanguage === "zh" ? copy.source : "SOURCE";
  const rows = events.map((event) => `<div class="history-row"><span data-label="${escapeHtml(dateLabel)}"><strong>${escapeHtml(event.beijing_date ?? copy.unknown)}</strong><small>${escapeHtml(copy.beijingTime)}</small></span><span data-label="${escapeHtml(timeLabel)}">${escapeHtml(event.beijing_time ?? copy.unknown)}</span><span data-label="${escapeHtml(intervalLabel)}">${escapeHtml(intervalDisplay(event, currentLanguage))}</span><span data-label="${escapeHtml(sourceLabelText)}">${escapeHtml(sourceLabel(event.source, currentLanguage))}</span><span data-label="X">${event.evidence_tweet_id ? `<a class="text-link" href="https://x.com/thsottiaux/status/${encodeURIComponent(event.evidence_tweet_id)}" target="_blank" rel="noreferrer">${escapeHtml(copy.openOnX)}</a>` : "—"}</span></div>`).join("");
  return `<section class="panel history-panel"><div class="panel-header"><div><span class="section-number">03</span><span class="field-label">${escapeHtml(copy.resetHistory)}</span><h2>${escapeHtml(copy.confirmedReset)}</h2></div><span class="panel-count">${events.length}</span></div><div class="history-list"><div class="history-row history-head"><span>${escapeHtml(currentLanguage === "zh" ? "日期" : "DATE")}</span><span>${escapeHtml(copy.beijingTime)}</span><span>${escapeHtml(copy.interval)}</span><span>${escapeHtml(copy.source)}</span><span>X</span></div>${rows || `<div class="empty-state">${escapeHtml(copy.noHistory)}</div>`}</div></section>`;
}
function resetsPage(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const count = data.resets?.sample_count ?? data.resets?.events.length ?? 0;
  return `${pageHeading("03", copy.resetPageTitle, copy.resetPageDetail)}<div class="reset-summary"><div><span class="field-label">${escapeHtml(copy.sampleCount)}</span><strong>${count}</strong></div><div><span class="field-label">${escapeHtml(copy.timezone)}</span><strong>${escapeHtml(data.resets?.timezone === "Asia/Shanghai" ? copy.beijingTime : data.resets?.timezone ?? copy.unknown)}</strong></div><div><span class="field-label">${escapeHtml(copy.dataUpdated)}</span><strong>${escapeHtml(formatDate(data.resets?.generated_at, currentLanguage))}</strong></div></div><div class="reset-workbench">${calendar(data, currentLanguage)}${distribution(data, currentLanguage)}</div>${history(data, currentLanguage)}`;
}
function footer(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  return `<footer class="footer"><span>${escapeHtml(copy.dataUpdated)}：${escapeHtml(formatDate(snapshotTimestamp(data), currentLanguage))} · ${escapeHtml(ageLabel(snapshotTimestamp(data), Date.now(), currentLanguage))}</span><span>${escapeHtml(copy.snapshotGenerated)} ${escapeHtml(formatDate(data.index?.generated_at, currentLanguage))}</span></footer>`;
}
function render(data: DashboardData, refreshFailed = lastRefreshFailed): void {
  if (!app) return;
  const currentRoute = route();
  const content = currentRoute === "/tweets" ? tweetsPage(data, language) : currentRoute === "/resets" ? resetsPage(data, language) : homePage(data, language);
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  app.innerHTML = `<a class="skip-link" href="#main-content">${escapeHtml(COPY[language].skipToContent)}</a><div class="app-shell">${sidebar(currentRoute, language)}<div class="workspace">${header(currentRoute, language, data)}<div class="content-wrap">${notices(data, language, refreshFailed)}<main id="main-content" class="page-content">${content}</main>${footer(data, language)}</div></div></div>`;
  app.querySelector<HTMLButtonElement>("[data-language-toggle]")?.addEventListener("click", () => { language = language === "zh" ? "en" : "zh"; saveLanguage(language); render(data, refreshFailed); });
  app.querySelector<HTMLButtonElement>("[data-refresh]")?.addEventListener("click", () => { void refreshDashboard(); });
  app.querySelectorAll<HTMLButtonElement>("[data-calendar-date]").forEach((button) => button.addEventListener("click", () => {
    const selected = button.dataset.calendarDate;
    const events = data.resets?.events.filter((event) => event.beijing_date === selected) ?? [];
    app.querySelectorAll<HTMLButtonElement>("[data-calendar-date]").forEach((day) => { day.classList.remove("selected"); day.setAttribute("aria-pressed", "false"); });
    button.classList.add("selected"); button.setAttribute("aria-pressed", "true");
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
