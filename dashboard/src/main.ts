import "./style.css";
import { DATA_BASE_URL } from "./config";
import {
  ageLabel,
  deriveDisplayHealth,
  deriveMirrorState,
  isDataStale,
  loadDashboardData,
  mergeDashboardData,
  resetSignalTweets,
  signalTweets,
  type DashboardData,
  type DisplayHealth,
  type PublicHealthComponent,
  type PublicTweet
} from "./data";

type Language = "zh" | "en";

interface Copy {
  languageButton: string;
  languageAria: string;
  eyebrow: string;
  updated: string;
  dataUpdated: string;
  tweets: string;
  dataUnavailable: string;
  refreshFailed: string;
  showingLastSuccess: string;
  dataStale: string;
  staleDescription: string;
  currentRadar: string;
  lastKnownRadar: string;
  confidence: string;
  urgency: string;
  lastUpdated: string;
  noRadarState: string;
  latestSignal: string;
  lastKnownSignal: string;
  latestSignalHeading: string;
  monitorHealth: string;
  collectionStatus: string;
  recentSignals: string;
  recentSignalsHeading: string;
  noSignals: string;
  noSignalsDetail: string;
  basicTimeline: string;
  resetHistory: string;
  noResetSignals: string;
  dataSource: string;
  snapshotGenerated: string;
  dataMirror: string;
  lastSync: string;
  lastHeartbeat: string;
  lastKnownStatus: string;
  noHeartbeat: string;
  emptyTweet: string;
  unclassified: string;
  openOnX: string;
  unknown: string;
  states: Record<string, string>;
  categories: Record<string, string>;
  urgencyValues: Record<string, string>;
  healthStates: Record<string, string>;
  monitorLabels: Record<string, string>;
}

const COPY: Record<Language, Copy> = {
  zh: {
    languageButton: "English",
    languageAria: "切换到英文",
    eyebrow: "公开 Radar · @thsottiaux",
    updated: "更新于",
    dataUpdated: "数据更新时间",
    tweets: "条 Tweets",
    dataUnavailable: "数据不可用",
    refreshFailed: "刷新失败",
    showingLastSuccess: "正在显示最后一次成功数据。",
    dataStale: "数据镜像过期",
    staleDescription: "公开数据镜像已超过 15 分钟未更新。",
    currentRadar: "当前 Radar",
    lastKnownRadar: "最后已知状态",
    confidence: "置信度",
    urgency: "紧急度",
    lastUpdated: "最后更新",
    noRadarState: "当前没有可用的 Radar 状态。",
    latestSignal: "最新信号",
    lastKnownSignal: "最后已知信号",
    latestSignalHeading: "最近的相关信号",
    monitorHealth: "监控健康度",
    collectionStatus: "采集状态",
    recentSignals: "近期信号",
    recentSignalsHeading: "最近 20 条相关 Tweet",
    noSignals: "当前快照中没有 reset 或 quota 信号。",
    noSignalsDetail: "下一条归类为 reset 或 quota 的 Tweet 会显示在这里。",
    basicTimeline: "基础时间线",
    resetHistory: "Reset 信号历史",
    noResetSignals: "当前没有 reset 专属信号。",
    dataSource: "数据源：GitHub data 分支",
    snapshotGenerated: "快照生成于",
    dataMirror: "GitHub Data Mirror",
    lastSync: "最后同步",
    lastHeartbeat: "最后心跳",
    lastKnownStatus: "最后已知状态",
    noHeartbeat: "暂无心跳",
    emptyTweet: "（Tweet 文本为空）",
    unclassified: "未分类",
    openOnX: "在 X 上打开 ↗",
    unknown: "未知",
    states: {
      QUIET: "安静",
      WATCH: "观察",
      LIKELY: "可能发生",
      IMMINENT: "即将发生",
      ANNOUNCED: "已宣布",
      CONFIRMED: "已确认",
      UNKNOWN: "未知"
    },
    categories: {
      reset_hint: "Reset 提示",
      reset_announcement: "Reset 公告",
      reset_in_progress: "Reset 进行中",
      reset_confirmed: "Reset 已确认",
      reset_denial: "Reset 否认",
      quota_information: "Quota 信息"
    },
    urgencyValues: {
      now: "现在",
      within_6h: "6 小时内",
      within_24h: "24 小时内",
      "within 24h": "24 小时内",
      within_3d: "3 天内",
      "within 3d": "3 天内",
      unknown: "未知"
    },
    healthStates: {
      healthy: "正常",
      offline: "离线",
      stale: "数据过期",
      unknown: "未知",
      fresh: "最新"
    },
    monitorLabels: {
      backend: "Backend",
      profile_monitor: "Profile",
      replies_monitor: "Replies",
      search_backfill: "Search Backfill"
    }
  },
  en: {
    languageButton: "中文",
    languageAria: "切换到中文",
    eyebrow: "PUBLIC RADAR · @thsottiaux",
    updated: "Updated",
    dataUpdated: "Data updated",
    tweets: "Tweets",
    dataUnavailable: "Data unavailable",
    refreshFailed: "Refresh failed",
    showingLastSuccess: "Showing the last successful data.",
    dataStale: "Data mirror is stale",
    staleDescription: "The public mirror is older than 15 minutes.",
    currentRadar: "CURRENT RADAR",
    lastKnownRadar: "Last known state",
    confidence: "Confidence",
    urgency: "Urgency",
    lastUpdated: "Last updated",
    noRadarState: "No Radar state is available.",
    latestSignal: "LATEST SIGNAL",
    lastKnownSignal: "LAST KNOWN SIGNAL",
    latestSignalHeading: "Most recent relevant signal",
    monitorHealth: "MONITOR HEALTH",
    collectionStatus: "Collection status",
    recentSignals: "RECENT SIGNALS",
    recentSignalsHeading: "Latest 20 relevant Tweets",
    noSignals: "No reset or quota signal is available in the current snapshot.",
    noSignalsDetail: "The next classified reset or quota Tweet will appear here.",
    basicTimeline: "BASIC TIMELINE",
    resetHistory: "Reset signal history",
    noResetSignals: "No reset-specific signals are available.",
    dataSource: "Data source: GitHub data branch",
    snapshotGenerated: "Snapshot generated",
    dataMirror: "GitHub Data Mirror",
    lastSync: "Last sync",
    lastHeartbeat: "Last heartbeat",
    lastKnownStatus: "Last known state",
    noHeartbeat: "No heartbeat",
    emptyTweet: "(empty Tweet text)",
    unclassified: "Unclassified",
    openOnX: "Open on X ↗",
    unknown: "unknown",
    states: {
      QUIET: "Quiet",
      WATCH: "Watch",
      LIKELY: "Likely",
      IMMINENT: "Imminent",
      ANNOUNCED: "Announced",
      CONFIRMED: "Confirmed",
      UNKNOWN: "Unknown"
    },
    categories: {
      reset_hint: "Reset hint",
      reset_announcement: "Reset announcement",
      reset_in_progress: "Reset in progress",
      reset_confirmed: "Reset confirmed",
      reset_denial: "Reset denial",
      quota_information: "Quota information"
    },
    urgencyValues: {
      now: "now",
      within_6h: "within 6h",
      within_24h: "within 24h",
      "within 24h": "within 24h",
      within_3d: "within 3d",
      "within 3d": "within 3d",
      unknown: "unknown"
    },
    healthStates: {
      healthy: "healthy",
      offline: "offline",
      stale: "stale",
      unknown: "unknown",
      fresh: "fresh"
    },
    monitorLabels: {
      backend: "Backend",
      profile_monitor: "Profile",
      replies_monitor: "Replies",
      search_backfill: "Search Backfill"
    }
  }
};

const LANGUAGE_STORAGE_KEY = "codex-reset-radar-language";
const REFRESH_INTERVAL_MS = 60_000;
const app = document.querySelector<HTMLElement>("#app");
let language = readLanguage();
let lastSuccessfulData: DashboardData | null = null;
let lastRefreshFailed = false;
let refreshInFlight = false;

function readLanguage(): Language {
  try {
    return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "zh";
  } catch {
    return "zh";
  }
}

function saveLanguage(next: Language): void {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
  } catch {
    // A blocked localStorage should not prevent language switching for this view.
  }
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;"
  })[character] ?? character);
}

function confidence(value: number | undefined): string {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
}

function formatDate(value: string | null | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  if (!value) return copy.unknown;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? copy.unknown : date.toLocaleString(currentLanguage === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function categoryLabel(category: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  return category ? copy.categories[category] ?? category.replaceAll("_", " ") : copy.unclassified;
}

function stateLabel(state: string, currentLanguage: Language): string {
  return COPY[currentLanguage].states[state] ?? state;
}

function urgencyLabel(urgency: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  if (!urgency) return copy.unknown;
  return copy.urgencyValues[urgency] ?? urgency.replaceAll("_", " ");
}

function tweetTime(tweet: PublicTweet): string {
  return tweet.created_at ?? tweet.discovered_at ?? "";
}

function snapshotTimestamp(data: DashboardData): string | undefined {
  return data.meta?.mirror_synced_at
    ?? data.meta?.generated_at
    ?? data.index?.generated_at
    ?? data.health?.generated_at;
}

function reportedHealthLabel(state: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  return state ? copy.healthStates[state.toLowerCase()] ?? state : copy.unknown;
}

function tweetCard(tweet: PublicTweet, currentLanguage: Language, compact = false): string {
  const copy = COPY[currentLanguage];
  const classification = tweet.classification;
  const category = classification?.category ?? "unclassified";
  const link = tweet.url && /^https:\/\/x\.com\//.test(tweet.url) ? tweet.url : "";
  return `<article class="signal-item ${compact ? "signal-item-compact" : ""}">
    <div class="signal-meta">
      <span class="category-tag category-${escapeHtml(category)}">${escapeHtml(categoryLabel(classification?.category, currentLanguage))}</span>
      <span>${escapeHtml(formatDate(tweetTime(tweet), currentLanguage))}</span>
      ${classification?.urgency ? `<span>${escapeHtml(urgencyLabel(classification.urgency, currentLanguage))}</span>` : ""}
    </div>
    <p class="tweet-text">${escapeHtml(tweet.text || copy.emptyTweet)}</p>
    <div class="signal-footer">
      <span>${escapeHtml(copy.confidence)} ${escapeHtml(confidence(classification?.confidence))}</span>
      ${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${escapeHtml(copy.openOnX)}</a>` : ""}
    </div>
  </article>`;
}

function monitorRow(component: PublicHealthComponent | undefined, snapshotAt: string | undefined, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const name = component?.component ?? "unknown";
  const state: DisplayHealth = deriveDisplayHealth(component, snapshotAt);
  const label = copy.monitorLabels[name] ?? (name === "unknown" ? copy.unknown : name.replaceAll("_", " "));
  const timestamp = component?.last_heartbeat;
  const status = copy.healthStates[state];
  const lastKnown = state === "stale" && component?.state
    ? `<span class="muted">${escapeHtml(copy.lastKnownStatus)}：${escapeHtml(reportedHealthLabel(component.state, currentLanguage))}</span>`
    : "";
  return `<div class="monitor-row">
    <div><strong>${escapeHtml(label)}</strong><span class="muted">${escapeHtml(timestamp ? `${copy.lastHeartbeat}：${formatDate(timestamp, currentLanguage)}` : copy.noHeartbeat)}</span>${lastKnown}</div>
    <span class="status-dot status-${state}" aria-label="${escapeHtml(status)}">${escapeHtml(status)}</span>
    <span class="age">${escapeHtml(ageLabel(timestamp, Date.now(), currentLanguage))}</span>
  </div>`;
}

function mirrorRow(data: DashboardData, currentLanguage: Language): string {
  const copy = COPY[currentLanguage];
  const syncedAt = data.meta?.mirror_synced_at ?? data.meta?.generated_at ?? snapshotTimestamp(data);
  const state = deriveMirrorState(syncedAt);
  const status = copy.healthStates[state];
  return `<div class="mirror-row">
    <div><strong>${escapeHtml(copy.dataMirror)}</strong><span class="muted">${escapeHtml(syncedAt ? `${copy.lastSync}：${formatDate(syncedAt, currentLanguage)}` : copy.noHeartbeat)}</span></div>
    <span class="status-dot status-${state}" aria-label="${escapeHtml(status)}">${escapeHtml(status)}</span>
    <span class="age">${escapeHtml(ageLabel(syncedAt, Date.now(), currentLanguage))}</span>
  </div>`;
}

function render(data: DashboardData, refreshFailed = lastRefreshFailed): void {
  if (!app) return;
  const copy = COPY[language];
  const snapshotAt = snapshotTimestamp(data);
  const stale = isDataStale(snapshotAt);
  const radar = data.radar;
  const signals = signalTweets(data.tweets);
  const recent = signals.slice(0, 20);
  const timeline = resetSignalTweets(data.tweets).slice(0, 8);
  const healthComponents = data.health?.components ?? [];
  const healthByName = new Map(healthComponents.map((component) => [component.component, component]));
  const monitorRows = ["backend", "profile_monitor", "replies_monitor", "search_backfill"]
    .map((name) => monitorRow(healthByName.get(name), snapshotAt, language))
    .join("");
  const state = radar?.state ?? "UNKNOWN";
  const latest = signals[0];
  const tweetCount = data.index?.tweet_count ?? data.tweets.length;
  const tweetCountLabel = `${tweetCount} ${copy.tweets}`;
  const failureNotice = data.errors.length > 0
    ? `<div class="notice notice-error"><strong>${escapeHtml(refreshFailed ? copy.refreshFailed : copy.dataUnavailable)}</strong><span>${escapeHtml(refreshFailed ? copy.showingLastSuccess : data.errors.join(" · "))}</span></div>`
    : "";
  const staleNotice = stale
    ? `<div class="notice notice-stale"><strong>${escapeHtml(copy.dataStale)}</strong><span>${escapeHtml(copy.staleDescription)}</span></div>`
    : "";
  const radarFreshness = stale
    ? `<span class="stale-badge">⚠️ ${escapeHtml(copy.lastKnownRadar)}</span>`
    : "";
  const latestLabel = stale ? copy.lastKnownSignal : copy.latestSignal;

  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  app.innerHTML = `<header class="topbar">
    <div><p class="eyebrow">${escapeHtml(copy.eyebrow)}</p><h1>Codex Reset Radar</h1></div>
    <div class="topbar-actions"><div class="topbar-meta"><span>${escapeHtml(tweetCountLabel)}</span><span>${escapeHtml(copy.dataUpdated)}：${escapeHtml(formatDate(snapshotAt, language))} · ${escapeHtml(ageLabel(snapshotAt, Date.now(), language))}</span></div><button class="language-toggle" type="button" data-language-toggle aria-label="${escapeHtml(copy.languageAria)}">${escapeHtml(copy.languageButton)}</button></div>
  </header>
  ${failureNotice}${staleNotice}
  <section class="radar-card state-${escapeHtml(state)}" aria-labelledby="radar-title">
    <div class="radar-card-heading"><div><p class="eyebrow">${escapeHtml(copy.currentRadar)}</p><h2 id="radar-title">${escapeHtml(stateLabel(state, language))}</h2></div><div class="radar-card-badges">${radarFreshness}<span class="state-pill">${escapeHtml(state)}</span></div></div>
    <div class="radar-facts"><div><span>${escapeHtml(copy.confidence)}</span><strong>${escapeHtml(confidence(radar?.confidence))}</strong></div><div><span>${escapeHtml(copy.urgency)}</span><strong>${escapeHtml(urgencyLabel(radar?.urgency, language))}</strong></div><div><span>${escapeHtml(copy.lastUpdated)}</span><strong>${escapeHtml(formatDate(radar?.updated_at, language))}</strong></div></div>
    <p class="radar-reason">${escapeHtml(radar?.reason ?? copy.noRadarState)}</p>
  </section>
  <div class="dashboard-grid">
    <section class="panel latest-panel"><div class="panel-heading"><div><p class="eyebrow">${escapeHtml(latestLabel)}</p><h2>${escapeHtml(copy.latestSignalHeading)}</h2></div></div>${latest ? tweetCard(latest, language) : `<div class="empty-state">${escapeHtml(copy.noSignals)}</div>`}</section>
    <section class="panel health-panel"><div class="panel-heading"><div><p class="eyebrow">${escapeHtml(copy.monitorHealth)}</p><h2>${escapeHtml(copy.collectionStatus)}</h2></div></div><div class="monitor-list">${mirrorRow(data, language)}${monitorRows}</div></section>
    <section class="panel recent-panel"><div class="panel-heading"><div><p class="eyebrow">${escapeHtml(copy.recentSignals)}</p><h2>${escapeHtml(copy.recentSignalsHeading)}</h2></div><span class="panel-count">${recent.length}</span></div>${recent.length ? `<div class="signal-list">${recent.map((tweet) => tweetCard(tweet, language, true)).join("")}</div>` : `<div class="empty-state"><strong>${escapeHtml(copy.noSignals)}</strong><span>${escapeHtml(copy.noSignalsDetail)}</span></div>`}</section>
    <section class="panel timeline-panel"><div class="panel-heading"><div><p class="eyebrow">${escapeHtml(copy.basicTimeline)}</p><h2>${escapeHtml(copy.resetHistory)}</h2></div></div>${timeline.length ? `<div class="timeline">${timeline.map((tweet) => `<div class="timeline-entry"><div class="timeline-marker"></div><div><div class="signal-meta"><span class="category-tag category-${escapeHtml(tweet.classification?.category ?? "unknown")}">${escapeHtml(categoryLabel(tweet.classification?.category, language))}</span><span>${escapeHtml(formatDate(tweetTime(tweet), language))}</span></div><p>${escapeHtml(tweet.text || copy.emptyTweet)}</p></div></div>`).join("")}</div>` : `<div class="empty-state">${escapeHtml(copy.noResetSignals)}</div>`}</section>
  </div>
  <footer class="footer"><span>${escapeHtml(copy.dataSource)} <code>data/*.json</code></span><span>${escapeHtml(copy.snapshotGenerated)} ${escapeHtml(formatDate(data.index?.generated_at, language))}</span></footer>`;

  app.querySelector<HTMLButtonElement>("[data-language-toggle]")?.addEventListener("click", () => {
    language = language === "zh" ? "en" : "zh";
    saveLanguage(language);
    render(data);
  });
}

async function refreshDashboard(): Promise<void> {
  if (refreshInFlight) return;
  refreshInFlight = true;
  try {
    const next = await loadDashboardData(fetch, DATA_BASE_URL);
    const hadPreviousData = Boolean(lastSuccessfulData);
    const merged = lastSuccessfulData ? mergeDashboardData(lastSuccessfulData, next) : next;
    lastSuccessfulData = merged;
    lastRefreshFailed = hadPreviousData && next.errors.length > 0;
    render(merged, lastRefreshFailed);
  } catch (error) {
    if (lastSuccessfulData) {
      lastRefreshFailed = true;
      render({ ...lastSuccessfulData, errors: [error instanceof Error ? error.message : "Data unavailable"] }, true);
    } else {
      lastRefreshFailed = false;
      render({ index: null, tweets: [], radar: null, health: null, meta: null, errors: [error instanceof Error ? error.message : "Data unavailable"] }, false);
    }
  } finally {
    refreshInFlight = false;
  }
}

if (app) {
  void refreshDashboard();
  window.setInterval(() => void refreshDashboard(), REFRESH_INTERVAL_MS);
}
