import type {
  DiagnosticMessage,
  HeartbeatMessage,
  IngestMessage,
  NormalizedTweet,
  RuntimeMessageResponse
} from "./types";
import { buildSearchUrls } from "./search";

const BACKEND = "http://127.0.0.1:8787";
const SEARCH_ALARM = "search-backfill-5m";
const DEEP_SEARCH_ALARM = "search-backfill-6h";
const RETRY_ALARM = "backend-retry-1m";
const SEARCH_TIMEOUT_MS = 45_000;
const TARGET_TAB_PATTERNS = [
  "https://x.com/thsottiaux",
  "https://x.com/thsottiaux/*",
  "https://twitter.com/thsottiaux",
  "https://twitter.com/thsottiaux/*"
];
let searchRunning = false;

function log(message: string, details?: unknown): void {
  console.info(`[Codex Reset Radar] ${message}`, details ?? "");
}

function diagnosticLog(event: string, details?: unknown): void {
  console.info(`[Codex Reset Radar][${event}]`, details ?? "");
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function postJson(path: string, body: unknown): Promise<void> {
  const response = await fetch(`${BACKEND}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(`backend HTTP ${response.status}`);
}

async function enqueueTweets(tweets: NormalizedTweet[]): Promise<void> {
  const stored = await chrome.storage.local.get("pending_tweets");
  const pending = Array.isArray(stored.pending_tweets) ? stored.pending_tweets as NormalizedTweet[] : [];
  const merged = [...pending, ...tweets];
  await chrome.storage.local.set({ pending_tweets: merged.slice(-1000) });
}

async function flushTweets(): Promise<void> {
  const stored = await chrome.storage.local.get("pending_tweets");
  const pending = Array.isArray(stored.pending_tweets) ? stored.pending_tweets as NormalizedTweet[] : [];
  if (pending.length === 0) return;
  try {
    await postJson("/api/ingest/tweets", { tweets: pending.slice(0, 100) });
    await chrome.storage.local.set({ pending_tweets: pending.slice(100) });
    log("Tweet ingestion delivered", { count: Math.min(100, pending.length) });
  } catch (error) {
    log("Tweet ingestion retry queued", error instanceof Error ? error.message : error);
  }
}

async function ingest(tweets: NormalizedTweet[]): Promise<void> {
  if (tweets.length === 0) return;
  try {
    await postJson("/api/ingest/tweets", { tweets });
    log("Tweet batch sent", { count: tweets.length });
  } catch (error) {
    await enqueueTweets(tweets);
    log("Backend unavailable; Tweet batch queued", error instanceof Error ? error.message : error);
  }
}

function tabSnapshot(tab: chrome.tabs.Tab): Record<string, unknown> {
  const details: Record<string, unknown> = {};
  const extendedTab = tab as chrome.tabs.Tab & { frozen?: boolean };
  if (typeof tab.id === "number") details.tab_id = tab.id;
  if (typeof tab.url === "string") details.tab_url = tab.url;
  if (typeof tab.active === "boolean") details.tab_active = tab.active;
  if (typeof tab.status === "string") details.tab_status = tab.status;
  if (typeof tab.discarded === "boolean") details.tab_discarded = tab.discarded;
  if (typeof extendedTab.frozen === "boolean") details.tab_frozen = extendedTab.frozen;
  if (typeof tab.autoDiscardable === "boolean") details.tab_auto_discardable = tab.autoDiscardable;
  if (typeof tab.pinned === "boolean") details.tab_pinned = tab.pinned;
  if (typeof tab.windowId === "number") details.tab_window_id = tab.windowId;
  return details;
}

async function readTabSnapshot(tabId: number | undefined): Promise<Record<string, unknown>> {
  if (typeof tabId !== "number") return {};
  try {
    const tab = await chrome.tabs.get(tabId);
    return tabSnapshot(tab);
  } catch (error) {
    diagnosticLog("SERVICE_WORKER_MESSAGE_FAILED", {
      operation: "tabs.get",
      tab_id: tabId,
      error: errorText(error)
    });
    return { tab_id: tabId, tab_lookup_failed: true, tab_lookup_error: errorText(error) };
  }
}

async function heartbeat(message: HeartbeatMessage, sender?: chrome.runtime.MessageSender): Promise<void> {
  const metadata = {
    ...(message.metadata ?? {}),
    ...(await readTabSnapshot(sender?.tab?.id))
  };
  await postJson("/api/heartbeat", {
    component: message.component,
    observed_at: message.observed_at ?? null,
    state: message.state ?? "healthy",
    last_tweet_seen: message.last_tweet_seen ?? null,
    error: message.error ?? null,
    metadata
  });
  diagnosticLog("SERVICE_WORKER_MESSAGE_SENT", {
    message_type: message.type,
    component: message.component,
    observed_at: message.observed_at ?? null,
    actual_heartbeat_elapsed_ms: metadata.actual_heartbeat_elapsed_ms ?? null,
    ...(sender?.tab ? tabSnapshot(sender.tab) : {})
  });
}

async function diagnostic(message: DiagnosticMessage, sender?: chrome.runtime.MessageSender): Promise<void> {
  const details = {
    ...(message.details ?? {}),
    ...(await readTabSnapshot(sender?.tab?.id))
  };
  await postJson("/api/diagnostics", {
    component: message.component,
    event: message.event,
    observed_at: message.observed_at ?? null,
    details
  });
  diagnosticLog(message.event, { component: message.component, ...details });
}

function componentForTab(tab: chrome.tabs.Tab): string {
  const url = tab.url ?? "";
  if (/x\.com\/thsottiaux\/with_replies|twitter\.com\/thsottiaux\/with_replies/i.test(url)) {
    return "replies_monitor";
  }
  if (/x\.com\/thsottiaux|twitter\.com\/thsottiaux/i.test(url)) return "profile_monitor";
  return "extension_service_worker";
}

async function snapshotMatchingTabs(): Promise<void> {
  try {
    const tabs = await chrome.tabs.query({ url: TARGET_TAB_PATTERNS });
    const observedAt = new Date().toISOString();
    diagnosticLog("TAB_STATE_SNAPSHOT", {
      observed_at: observedAt,
      matching_tab_count: tabs.length,
      tabs: tabs.map(tabSnapshot)
    });
    const requests = tabs.map((tab) => postJson("/api/diagnostics", {
      component: componentForTab(tab),
      event: "TAB_STATE_SNAPSHOT",
      observed_at: observedAt,
      details: tabSnapshot(tab)
    }));
    if (tabs.length === 0) {
      requests.push(postJson("/api/diagnostics", {
        component: "extension_service_worker",
        event: "TAB_STATE_SNAPSHOT",
        observed_at: observedAt,
        details: { matching_tab_count: 0 }
      }));
    }
    await Promise.allSettled(requests);
  } catch (error) {
    diagnosticLog("SERVICE_WORKER_MESSAGE_FAILED", {
      operation: "tabs.query",
      error: errorText(error)
    });
  }
}

async function waitForTabComplete(tabId: number, initialStatus?: chrome.tabs.Tab["status"]): Promise<void> {
  if (initialStatus === "complete") return;
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    };
    const listener = (updatedTabId: number, info: { status?: string }) => {
      if (updatedTabId === tabId && info.status === "complete") finish();
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(finish, SEARCH_TIMEOUT_MS);
  });
}

async function scrollSearchTab(tabId: number): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: () => window.scrollBy(0, Math.max(500, window.innerHeight * 0.8))
    }).catch(() => undefined);
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
}

async function runSearchBackfill(hours: number): Promise<void> {
  if (searchRunning) return;
  searchRunning = true;
  const urls = buildSearchUrls(new Date(), hours);
  try {
    for (const url of urls) {
      let tab: chrome.tabs.Tab | undefined;
      try {
        tab = await chrome.tabs.create({ url, active: false });
        if (!tab.id) continue;
        await waitForTabComplete(tab.id, tab.status);
        await scrollSearchTab(tab.id);
        await new Promise((resolve) => setTimeout(resolve, 1_000));
      } catch (error) {
        log("Search window failed", error instanceof Error ? error.message : error);
      } finally {
        if (tab?.id) await chrome.tabs.remove(tab.id).catch(() => undefined);
      }
    }
    await heartbeat({ type: "HEARTBEAT", component: "search_backfill", state: "healthy", metadata: { hours: String(hours) } });
  } finally {
    searchRunning = false;
  }
}

let alarmSetupPromise: Promise<void> | undefined;

async function ensureAlarm(name: string, periodInMinutes: number): Promise<void> {
  const existing = await chrome.alarms.get(name);
  if (existing) return;
  await chrome.alarms.create(name, { periodInMinutes });
  log("Alarm created", { name, periodInMinutes });
}

function setupAlarms(): Promise<void> {
  // Service workers can be started repeatedly. Do not recreate an existing
  // alarm, because chrome.alarms.create replaces the same-name alarm and
  // restarts its countdown.
  if (!alarmSetupPromise) {
    alarmSetupPromise = Promise.all([
      ensureAlarm(SEARCH_ALARM, 5),
      ensureAlarm(DEEP_SEARCH_ALARM, 360),
      ensureAlarm(RETRY_ALARM, 1)
    ]).then(() => undefined);
  }
  return alarmSetupPromise;
}

chrome.runtime.onInstalled.addListener(() => void setupAlarms());
chrome.runtime.onStartup.addListener(() => void setupAlarms());
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === SEARCH_ALARM) void runSearchBackfill(72);
  if (alarm.name === DEEP_SEARCH_ALARM) void runSearchBackfill(24 * 7);
  if (alarm.name === RETRY_ALARM) {
    void flushTweets();
    void snapshotMatchingTabs();
  }
});

chrome.runtime.onMessage.addListener((message: IngestMessage | HeartbeatMessage | DiagnosticMessage, sender, sendResponse) => {
  if (message.type === "INGEST_TWEETS") {
    void ingest(message.tweets);
    return false;
  }
  if (message.type === "HEARTBEAT") {
    void heartbeat(message, sender)
      .then(() => sendResponse({ ok: true } satisfies RuntimeMessageResponse))
      .catch((error) => {
        diagnosticLog("SERVICE_WORKER_MESSAGE_FAILED", {
          message_type: message.type,
          component: message.component,
          error: errorText(error)
        });
        sendResponse({ ok: false, error: errorText(error) } satisfies RuntimeMessageResponse);
      });
    return true;
  }
  if (message.type === "DIAGNOSTIC") {
    void diagnostic(message, sender)
      .then(() => sendResponse({ ok: true } satisfies RuntimeMessageResponse))
      .catch((error) => {
        diagnosticLog("SERVICE_WORKER_MESSAGE_FAILED", {
          message_type: message.type,
          event: message.event,
          component: message.component,
          error: errorText(error)
        });
        sendResponse({ ok: false, error: errorText(error) } satisfies RuntimeMessageResponse);
      });
    return true;
  }
  return false;
});

diagnosticLog("SERVICE_WORKER_INIT", { observed_at: new Date().toISOString() });
void setupAlarms();
