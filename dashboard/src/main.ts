import "./style.css";
import {
  ageLabel,
  healthState,
  isDataStale,
  loadDashboardData,
  resetSignalTweets,
  signalTweets,
  type DashboardData,
  type PublicHealthComponent,
  type PublicTweet
} from "./data";

const app = document.querySelector<HTMLElement>("#app");
const MONITOR_LABELS: Record<string, string> = {
  backend: "Backend",
  profile_monitor: "Profile",
  replies_monitor: "Replies",
  search_backfill: "Search Backfill"
};
const SIGNAL_LABELS: Record<string, string> = {
  reset_hint: "Reset hint",
  reset_announcement: "Reset announcement",
  reset_in_progress: "Reset in progress",
  reset_confirmed: "Reset confirmed",
  reset_denial: "Reset denial",
  quota_information: "Quota information"
};
const STATE_LABELS: Record<string, string> = {
  QUIET: "Quiet",
  WATCH: "Watch",
  LIKELY: "Likely",
  IMMINENT: "Imminent",
  ANNOUNCED: "Announced",
  CONFIRMED: "Confirmed"
};

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

function formatDate(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function categoryLabel(category: string | undefined): string {
  return category ? SIGNAL_LABELS[category] ?? category.replaceAll("_", " ") : "Unclassified";
}

function tweetTime(tweet: PublicTweet): string {
  return tweet.created_at ?? tweet.discovered_at ?? "";
}

function tweetCard(tweet: PublicTweet, compact = false): string {
  const classification = tweet.classification;
  const category = classification?.category ?? "unclassified";
  const link = tweet.url && /^https:\/\/x\.com\//.test(tweet.url) ? tweet.url : "";
  return `<article class="signal-item ${compact ? "signal-item-compact" : ""}">
    <div class="signal-meta">
      <span class="category-tag category-${escapeHtml(category)}">${escapeHtml(categoryLabel(classification?.category))}</span>
      <span>${escapeHtml(formatDate(tweetTime(tweet)))}</span>
      ${classification?.urgency ? `<span>${escapeHtml(classification.urgency.replaceAll("_", " "))}</span>` : ""}
    </div>
    <p class="tweet-text">${escapeHtml(tweet.text || "(empty Tweet text)")}</p>
    <div class="signal-footer">
      <span>confidence ${escapeHtml(confidence(classification?.confidence))}</span>
      ${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">Open on X ↗</a>` : ""}
    </div>
  </article>`;
}

function monitorRow(component: PublicHealthComponent | undefined): string {
  const name = component?.component ?? "unknown";
  const state = healthState(component);
  const label = MONITOR_LABELS[name] ?? name.replaceAll("_", " ");
  const timestamp = component?.last_heartbeat;
  return `<div class="monitor-row">
    <div><strong>${escapeHtml(label)}</strong><span class="muted">${escapeHtml(timestamp ? formatDate(timestamp) : "No heartbeat" )}</span></div>
    <span class="status-dot status-${state}" aria-label="${state}">${state}</span>
    <span class="age">${escapeHtml(ageLabel(timestamp))}</span>
  </div>`;
}

function render(data: DashboardData): void {
  if (!app) return;
  const radar = data.radar;
  const signals = signalTweets(data.tweets);
  const recent = signals.slice(0, 20);
  const timeline = resetSignalTweets(data.tweets).slice(0, 8);
  const healthComponents = data.health?.components ?? [];
  const healthByName = new Map(healthComponents.map((component) => [component.component, component]));
  const monitorRows = ["backend", "profile_monitor", "replies_monitor", "search_backfill"]
    .map((name) => monitorRow(healthByName.get(name)))
    .join("");
  const stale = isDataStale(data.index?.generated_at);
  const state = radar?.state ?? "UNKNOWN";
  const latest = signals[0];
  const failureNotice = data.errors.length > 0
    ? `<div class="notice notice-error"><strong>Data unavailable</strong><span>${escapeHtml(data.errors.join(" · "))}</span></div>`
    : "";
  const staleNotice = stale
    ? `<div class="notice notice-stale"><strong>Data may be stale</strong><span>The public mirror is older than 30 minutes.</span></div>`
    : "";

  app.innerHTML = `<header class="topbar">
    <div><p class="eyebrow">PUBLIC RADAR · @thsottiaux</p><h1>Codex Reset Radar</h1></div>
    <div class="topbar-meta"><span>${data.index?.tweet_count ?? data.tweets.length} Tweets</span><span>Updated ${escapeHtml(formatDate(data.index?.generated_at))}</span></div>
  </header>
  ${failureNotice}${staleNotice}
  <section class="radar-card state-${escapeHtml(state)}" aria-labelledby="radar-title">
    <div class="radar-card-heading"><div><p class="eyebrow">CURRENT RADAR</p><h2 id="radar-title">${escapeHtml(STATE_LABELS[state] ?? state)}</h2></div><span class="state-pill">${escapeHtml(state)}</span></div>
    <div class="radar-facts"><div><span>Confidence</span><strong>${escapeHtml(confidence(radar?.confidence))}</strong></div><div><span>Urgency</span><strong>${escapeHtml(radar?.urgency?.replaceAll("_", " ") ?? "unknown")}</strong></div><div><span>Last updated</span><strong>${escapeHtml(formatDate(radar?.updated_at))}</strong></div></div>
    <p class="radar-reason">${escapeHtml(radar?.reason ?? "No Radar state is available.")}</p>
  </section>
  <div class="dashboard-grid">
    <section class="panel latest-panel"><div class="panel-heading"><div><p class="eyebrow">LATEST SIGNAL</p><h2>Most recent relevant signal</h2></div></div>${latest ? tweetCard(latest) : `<div class="empty-state">No reset or quota signal is available in the current snapshot.</div>`}</section>
    <section class="panel health-panel"><div class="panel-heading"><div><p class="eyebrow">MONITOR HEALTH</p><h2>Collection status</h2></div></div><div class="monitor-list">${monitorRows}</div></section>
    <section class="panel recent-panel"><div class="panel-heading"><div><p class="eyebrow">RECENT SIGNALS</p><h2>Latest 20 relevant Tweets</h2></div><span class="panel-count">${recent.length}</span></div>${recent.length ? `<div class="signal-list">${recent.map((tweet) => tweetCard(tweet, true)).join("")}</div>` : `<div class="empty-state">No signals yet. The next classified reset or quota Tweet will appear here.</div>`}</section>
    <section class="panel timeline-panel"><div class="panel-heading"><div><p class="eyebrow">BASIC TIMELINE</p><h2>Reset signal history</h2></div></div>${timeline.length ? `<div class="timeline">${timeline.map((tweet) => `<div class="timeline-entry"><div class="timeline-marker"></div><div><div class="signal-meta"><span class="category-tag category-${escapeHtml(tweet.classification?.category ?? "unknown")}">${escapeHtml(categoryLabel(tweet.classification?.category))}</span><span>${escapeHtml(formatDate(tweetTime(tweet)))}</span></div><p>${escapeHtml(tweet.text || "(empty Tweet text)")}</p></div></div>`).join("")}</div>` : `<div class="empty-state">No reset-specific signals are available.</div>`}</section>
  </div>
  <footer class="footer"><span>Data source: repository <code>public-data/*.json</code></span><span>Snapshot generated ${escapeHtml(formatDate(data.index?.generated_at))}</span></footer>`;
}

if (app) {
  void loadDashboardData().then(render).catch((error) => render({ index: null, tweets: [], radar: null, health: null, errors: [error instanceof Error ? error.message : "Data unavailable"] }));
}
