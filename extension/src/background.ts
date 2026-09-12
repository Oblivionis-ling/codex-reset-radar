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
const DIAGNOSTIC_RING_KEY = "codex-reset-radar-extension-diagnostic-ring";
const DIAGNOSTIC_RING_LIMIT = 500;
const TARGET_TAB_PATTERNS = [
  "https://x.com/thsottiaux",
  "https://x.com/thsottiaux/*",
  "https://twitter.com/thsottiaux",
  "https://twitter.com/thsottiaux/*"
];
let searchRunning = false;
let searchHeartbeatSequence = 0;
let ringWrite = Promise.resolve();
const EXTENSION_INSTANCE_ID = `extension-sw-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;

function log(message: string, details?: unknown): void {
  console.info(`[Codex Reset Radar] ${message}`, details ?? "");
}

function diagnosticLog(event: string, details?: unknown): void {
  const normalized = details && typeof details === "object" ? details as Record<string, unknown> : { value: details ?? "" };
  const record = {
    timestamp: new Date().toISOString(),
    event,
    component: typeof normalized.component === "string" ? normalized.component : "extension_service_worker",
    instance_id: EXTENSION_INSTANCE_ID,
    trace_id: typeof normalized.trace_id === "string" ? normalized.trace_id : null,
    sequence: typeof normalized.sequence === "number" ? normalized.sequence : null,
    details: normalized
  };
  console.info(`[Codex Reset Radar][${event}]`, details ?? "");
  ringWrite = ringWrite.then(async () => {
    try {
      const stored = await chrome.storage.local.get(DIAGNOSTIC_RING_KEY);
      const existing = Array.isArray(stored[DIAGNOSTIC_RING_KEY]) ? stored[DIAGNOSTIC_RING_KEY] as unknown[] : [];
      await chrome.storage.local.set({ [DIAGNOSTIC_RING_KEY]: [...existing, record].slice(-DIAGNOSTIC_RING_LIMIT) });
    } catch {
      // The emergency ring is deliberately best effort.
    }
  }).catch(() => undefined);
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

class BackendHttpError extends Error {
  status: number | null;
  durationMs: number;
  requestId: string;
  constructor(message: string, requestId: string, durationMs: number, status: number | null = null) {
    super(message);
    this.status = status;
    this.durationMs = durationMs;
    this.requestId = requestId;
  }
}

async function postJson(path: string, body: unknown, context: { traceId?: string; requestId?: string } = {}): Promise<{ requestId: string; status: number; durationMs: number }> {
  const requestId = context.requestId ?? `req-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
  const started = performance.now();
  const response = await fetch(`${BACKEND}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": requestId,
      ...(context.traceId ? { "X-Trace-ID": context.traceId } : {}),
      "X-Extension-Instance-ID": EXTENSION_INSTANCE_ID
    },
    body: JSON.stringify(body)
  });
  const durationMs = Math.max(0, Math.round(performance.now() - started));
  if (!response.ok) throw new BackendHttpError(`backend HTTP ${response.status}`, requestId, durationMs, response.status);
  return { requestId, status: response.status, durationMs };
}

function postBackendDiagnostic(event: string, component: string, details: Record<string, unknown> = {}): void {
  const traceId = typeof details.trace_id === "string" ? details.trace_id : undefined;
  void postJson("/api/diagnostics", {
    component,
    event,
    instance_id: typeof details.instance_id === "string" ? details.instance_id : EXTENSION_INSTANCE_ID,
    sequence: typeof details.sequence === "number" ? details.sequence : null,
    trace_id: traceId,
    details
  }, { traceId }).catch(() => undefined);
}

async function readDiagnosticRing(): Promise<unknown[]> {
  const stored = await chrome.storage.local.get(DIAGNOSTIC_RING_KEY);
  return Array.isArray(stored[DIAGNOSTIC_RING_KEY]) ? stored[DIAGNOSTIC_RING_KEY] as unknown[] : [];
}

async function flushDiagnosticRing(): Promise<void> {
  const ring = await readDiagnosticRing();
  if (ring.length === 0) return;
  const batch = ring.slice(0, 50).filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"));
  if (batch.length === 0) return;
  diagnosticLog("DIAGNOSTIC_BACKFILL_STARTED", { count: batch.length, extension_instance_id: EXTENSION_INSTANCE_ID });
  try {
    await postJson("/api/diagnostics/batch", {
      events: batch.map((item) => ({
        component: typeof item.component === "string" ? item.component : "extension_service_worker",
        event: typeof item.event === "string" ? item.event : "UNKNOWN",
        instance_id: typeof item.instance_id === "string" ? item.instance_id : EXTENSION_INSTANCE_ID,
        trace_id: typeof item.trace_id === "string" ? item.trace_id : null,
        sequence: typeof item.sequence === "number" ? item.sequence : null,
        observed_at: typeof item.timestamp === "string" ? item.timestamp : null,
        details: item.details && typeof item.details === "object" ? item.details : {}
      }))
    });
    const current = await readDiagnosticRing();
    await chrome.storage.local.set({ [DIAGNOSTIC_RING_KEY]: current.slice(batch.length) });
    diagnosticLog("DIAGNOSTIC_BACKFILL_COMPLETED", { count: batch.length, extension_instance_id: EXTENSION_INSTANCE_ID });
  } catch (error) {
    diagnosticLog("DIAGNOSTIC_BACKFILL_FAILED", { count: batch.length, error: errorText(error), extension_instance_id: EXTENSION_INSTANCE_ID });
  }
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
    await postJson("/api/ingest/tweets", { tweets: pending.slice(0, 100) }, { traceId: `tweet-backfill-${EXTENSION_INSTANCE_ID}` });
    await chrome.storage.local.set({ pending_tweets: pending.slice(100) });
    log("Tweet ingestion delivered", { count: Math.min(100, pending.length) });
  } catch (error) {
    log("Tweet ingestion retry queued", error instanceof Error ? error.message : error);
  }
}

async function ingest(tweets: NormalizedTweet[]): Promise<void> {
  if (tweets.length === 0) return;
  try {
    const traceId = `tweet-${EXTENSION_INSTANCE_ID}-${Date.now().toString(36)}`;
    await postJson("/api/ingest/tweets", { tweets, trace_id: traceId }, { traceId });
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
  const sequence = message.sequence ?? ++searchHeartbeatSequence;
  const traceId = message.trace_id ?? `hb-${message.component}-${EXTENSION_INSTANCE_ID}-${sequence}`;
  const requestId = message.request_id ?? `req-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
  const metadata = {
    ...(message.metadata ?? {}),
    ...(await readTabSnapshot(sender?.tab?.id)),
    extension_instance_id: EXTENSION_INSTANCE_ID,
    service_worker_instance_id: EXTENSION_INSTANCE_ID,
    sequence,
    trace_id: traceId,
    request_id: requestId
  };
  const component = message.component;
  const flowDetails = {
    component,
    instance_id: message.instance_id ?? EXTENSION_INSTANCE_ID,
    service_worker_instance_id: EXTENSION_INSTANCE_ID,
    sequence,
    trace_id: traceId,
    request_id: requestId,
    observed_at: message.observed_at ?? null,
    ...(sender?.tab ? tabSnapshot(sender.tab) : {})
  };
  diagnosticLog("HEARTBEAT_SW_RECEIVED", flowDetails);
  postBackendDiagnostic("HEARTBEAT_SW_RECEIVED", component, flowDetails);
  diagnosticLog("HEARTBEAT_HTTP_STARTED", flowDetails);
  postBackendDiagnostic("HEARTBEAT_HTTP_STARTED", component, flowDetails);
  try {
    const response = await postJson("/api/heartbeat", {
    component: message.component,
    instance_id: message.instance_id ?? EXTENSION_INSTANCE_ID,
    sequence,
    trace_id: traceId,
    request_id: requestId,
    observed_at: message.observed_at ?? null,
    state: message.state ?? "healthy",
    last_tweet_seen: message.last_tweet_seen ?? null,
    error: message.error ?? null,
    metadata
    }, { traceId, requestId });
    const successDetails = { ...flowDetails, http_status: response.status, duration_ms: response.durationMs };
    diagnosticLog("HEARTBEAT_HTTP_SUCCESS", successDetails);
    postBackendDiagnostic("HEARTBEAT_HTTP_SUCCESS", component, successDetails);
    diagnosticLog("SERVICE_WORKER_MESSAGE_SENT", {
    message_type: message.type,
    component: message.component,
    instance_id: message.instance_id ?? EXTENSION_INSTANCE_ID,
    sequence,
    trace_id: traceId,
    request_id: requestId,
    observed_at: message.observed_at ?? null,
    actual_heartbeat_elapsed_ms: metadata.actual_heartbeat_elapsed_ms ?? null,
    ...(sender?.tab ? tabSnapshot(sender.tab) : {})
    });
  } catch (error) {
    const failureDetails = {
      ...flowDetails,
      http_status: error instanceof BackendHttpError ? error.status : null,
      duration_ms: error instanceof BackendHttpError ? error.durationMs : null,
      error: errorText(error)
    };
    diagnosticLog("HEARTBEAT_HTTP_FAILED", failureDetails);
    postBackendDiagnostic("HEARTBEAT_HTTP_FAILED", component, failureDetails);
    throw error;
  }
}

async function diagnostic(message: DiagnosticMessage, sender?: chrome.runtime.MessageSender): Promise<void> {
  const details = {
    ...(message.details ?? {}),
    ...(await readTabSnapshot(sender?.tab?.id))
  };
  await postJson("/api/diagnostics", {
    component: message.component,
    event: message.event,
    instance_id: message.instance_id ?? EXTENSION_INSTANCE_ID,
    sequence: message.sequence ?? null,
    trace_id: message.trace_id ?? null,
    observed_at: message.observed_at ?? null,
    details
  }, { traceId: message.trace_id });
  diagnosticLog(message.event, {
    component: message.component,
    instance_id: message.instance_id ?? EXTENSION_INSTANCE_ID,
    sequence: message.sequence ?? null,
    trace_id: message.trace_id ?? null,
    ...details
  });
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
    void flushDiagnosticRing();
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

diagnosticLog("SERVICE_WORKER_INIT", { observed_at: new Date().toISOString(), extension_instance_id: EXTENSION_INSTANCE_ID });
void setupAlarms();
