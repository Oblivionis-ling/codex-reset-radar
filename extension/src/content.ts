import { extractTweets, sourceForLocation } from "./parser";
import type {
  DiagnosticEventType,
  DiagnosticMessage,
  HeartbeatMessage,
  IngestMessage,
  NormalizedTweet,
  RuntimeMessageResponse
} from "./types";

const BACKEND_COMPONENTS: Record<string, string> = {
  profile_dom: "profile_monitor",
  with_replies: "replies_monitor",
  search: "search_backfill"
};
const HEARTBEAT_INTERVAL_MS = 60_000;
const OBSERVATION_INTERVAL_MS = 2_000;
const LIFECYCLE_DIAGNOSTIC_INTERVAL_MS = 30_000;
const MUTATION_DIAGNOSTIC_THROTTLE_MS = 30_000;
const LOCAL_SEEN_LIMIT = 500;

let activeSource = sourceForLocation(window.location.pathname);
let lastTweetSeen: string | null = null;
let scanTimer: number | undefined;
let scanRunning = false;
let scanRequested = false;
let lastScanAt: string | null = null;
let lastScanSuccess: boolean | null = null;
let lastHeartbeatAttemptAtMs: Record<"scan" | "interval", number | undefined> = {
  scan: undefined,
  interval: undefined
};
let lastLocation = window.location.href;
let lastVisibility = document.visibilityState;
let lastReadyState = document.readyState;
let observer: MutationObserver | null = null;
let observerRoot: HTMLElement | null = null;
let lastReportedDomRoot: HTMLElement | null = null;
let observerAttached = false;
let mutationCount = 0;
let lastMutationDiagnosticAt = 0;

function componentForSource(source: typeof activeSource = activeSource): string | null {
  return source ? BACKEND_COMPONENTS[source] ?? null : null;
}

function monitorForSource(source: typeof activeSource = activeSource): string | null {
  if (source === "profile_dom") return "profile";
  if (source === "with_replies") return "replies";
  if (source === "search") return "search";
  return null;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function localDiagnostic(event: string, details: Record<string, unknown> = {}): void {
  console.info(`[Codex Reset Radar][${event}]`, details);
}

async function sendRuntimeMessage(
  message: IngestMessage | HeartbeatMessage | DiagnosticMessage,
  label: string
): Promise<RuntimeMessageResponse | undefined> {
  try {
    const response = await chrome.runtime.sendMessage(message) as RuntimeMessageResponse | undefined;
    if (response && response.ok === false) {
      throw new Error(response.error || `${label} rejected by service worker`);
    }
    localDiagnostic("SERVICE_WORKER_MESSAGE_SENT", { label, message_type: message.type });
    return response;
  } catch (error) {
    localDiagnostic("SERVICE_WORKER_MESSAGE_FAILED", {
      label,
      message_type: message.type,
      error: errorText(error)
    });
    throw error;
  }
}

function emitDiagnostic(
  event: DiagnosticEventType,
  details: Record<string, unknown> = {},
  source: typeof activeSource = activeSource
): void {
  const observedAt = new Date().toISOString();
  const component = componentForSource(source);
  const payloadDetails = {
    monitor: monitorForSource(source),
    url: window.location.href,
    document_visibility: document.visibilityState,
    document_ready_state: document.readyState,
    ...details
  };
  localDiagnostic(event, payloadDetails);
  if (!component) return;
  const message: DiagnosticMessage = {
    type: "DIAGNOSTIC",
    component,
    event,
    observed_at: observedAt,
    details: payloadDetails
  };
  void sendRuntimeMessage(message, `diagnostic:${event}`).catch(() => undefined);
}

function currentTargetDom(): boolean {
  return Boolean(document.querySelector('[data-testid="tweet"], article'));
}

function observerStatus(): Record<string, unknown> {
  return {
    observer_attached: observerAttached,
    observer_root_is_document_body: observerRoot === document.body,
    observer_root_connected: observerRoot ? document.contains(observerRoot) : false,
    observer_root_tag: observerRoot?.tagName ?? null
  };
}

function heartbeatMetadata(timerSource: "scan" | "interval"): Record<string, unknown> {
  const now = performance.now();
  const previousAttemptAtMs = lastHeartbeatAttemptAtMs[timerSource];
  const actualElapsed = previousAttemptAtMs === undefined ? null : Math.round(now - previousAttemptAtMs);
  lastHeartbeatAttemptAtMs[timerSource] = now;
  return {
    monitor: monitorForSource(),
    timestamp: new Date().toISOString(),
    url: window.location.href,
    document_visibility: document.visibilityState,
    document_ready_state: document.readyState,
    has_target_dom: currentTargetDom(),
    ...observerStatus(),
    last_scan_at: lastScanAt,
    last_scan_success: lastScanSuccess,
    expected_heartbeat_interval_ms: HEARTBEAT_INTERVAL_MS,
    actual_heartbeat_elapsed_ms: actualElapsed,
    heartbeat_timer_source: timerSource,
    scan_running: scanRunning,
    mutation_count: mutationCount
  };
}

function scheduleScan(reason: string): void {
  scanRequested = true;
  if (scanTimer !== undefined) return;
  scanTimer = window.setTimeout(() => {
    scanTimer = undefined;
    if (!scanRequested) return;
    scanRequested = false;
    void scan(reason);
  }, 150);
}

async function readSeenIds(): Promise<string[]> {
  const stored = await chrome.storage.local.get("seen_tweet_ids");
  return Array.isArray(stored.seen_tweet_ids) ? stored.seen_tweet_ids : [];
}

async function remember(ids: string[]): Promise<void> {
  const existing = await readSeenIds();
  const merged = [...new Set([...ids, ...existing])].slice(0, LOCAL_SEEN_LIMIT);
  await chrome.storage.local.set({ seen_tweet_ids: merged });
}

async function sendHeartbeat(
  state: HeartbeatMessage["state"] = "healthy",
  error: string | null = null,
  timerSource: "scan" | "interval" = "interval"
): Promise<void> {
  if (!activeSource) return;
  const observedAt = new Date().toISOString();
  const message: HeartbeatMessage = {
    type: "HEARTBEAT",
    component: BACKEND_COMPONENTS[activeSource],
    observed_at: observedAt,
    state,
    last_tweet_seen: lastTweetSeen,
    error,
    metadata: heartbeatMetadata(timerSource)
  };
  try {
    await sendRuntimeMessage(message, `heartbeat:${message.component}`);
    emitDiagnostic("CONTENT_SCRIPT_HEARTBEAT_SENT", {
      component: message.component,
      heartbeat_observed_at: observedAt,
      timer_source: timerSource,
      state,
      expected_heartbeat_interval_ms: message.metadata?.expected_heartbeat_interval_ms ?? null,
      actual_heartbeat_elapsed_ms: message.metadata?.actual_heartbeat_elapsed_ms ?? null
    });
  } catch (sendError) {
    emitDiagnostic("CONTENT_SCRIPT_HEARTBEAT_FAILED", {
      component: message.component,
      heartbeat_observed_at: observedAt,
      timer_source: timerSource,
      state,
      error: errorText(sendError)
    });
  }
}

function pageWarning(tweetCount: number): string | null {
  if (tweetCount > 0) return null;
  const bodyText = document.body?.innerText?.toLowerCase() ?? "";
  if (activeSource === "search" && /log in|sign up|登录|注册/.test(bodyText)) {
    return "X search is behind a login wall";
  }
  if (activeSource === "with_replies" && /error|出错了|reload|重试/.test(bodyText)) {
    return "X replies page reported a reload error";
  }
  return null;
}

async function scan(reason: string): Promise<void> {
  if (!activeSource || scanRunning) return;
  const isFallback = reason === "fallback";
  if (isFallback) {
    emitDiagnostic("FALLBACK_SCAN_STARTED", { source: activeSource });
  }
  scanRunning = true;
  lastScanAt = new Date().toISOString();
  try {
    const existing = new Set(await readSeenIds());
    const tweets = extractTweets(document, activeSource);
    const fresh = tweets.filter((tweet) => !existing.has(tweet.tweet_id));
    // Always send a fresh discovery to the backend. SQLite source sightings
    // make repeated scans useful for reliability measurement.
    const batch: NormalizedTweet[] = fresh.length > 0 ? fresh : tweets.slice(0, 50);
    if (batch.length > 0) {
      lastTweetSeen = batch[0].discovered_at;
      await remember(tweets.map((tweet) => tweet.tweet_id));
      const message: IngestMessage = { type: "INGEST_TWEETS", tweets: batch };
      await sendRuntimeMessage(message, `ingest:${activeSource}`);
    }
    const warning = pageWarning(tweets.length);
    lastScanSuccess = true;
    void sendHeartbeat(warning ? "warning" : "healthy", warning, "scan");
    if (isFallback) {
      emitDiagnostic("FALLBACK_SCAN_COMPLETED", {
        source: activeSource,
        tweet_count: tweets.length,
        fresh_count: fresh.length,
        warning
      });
    }
    localDiagnostic("SCAN_COMPLETED", { reason, cards: tweets.length, fresh: fresh.length });
  } catch (error) {
    lastScanSuccess = false;
    if (isFallback) {
      emitDiagnostic("FALLBACK_SCAN_FAILED", { source: activeSource, error: errorText(error) });
    }
    void sendHeartbeat("warning", errorText(error), "scan");
    localDiagnostic("SCAN_FAILED", { reason, error: errorText(error) });
  } finally {
    scanRunning = false;
  }
}

function noteMutation(): void {
  mutationCount += 1;
  const now = Date.now();
  localDiagnostic("MUTATION_OBSERVER_TRIGGERED", { mutation_count: mutationCount });
  if (now - lastMutationDiagnosticAt >= MUTATION_DIAGNOSTIC_THROTTLE_MS) {
    lastMutationDiagnosticAt = now;
    emitDiagnostic("MUTATION_OBSERVER_TRIGGERED", { mutation_count: mutationCount });
  }
  scheduleScan("mutation");
}

function attachObserver(): void {
  observer = new MutationObserver(noteMutation);
  observerRoot = document.body;
  lastReportedDomRoot = observerRoot;
  if (!observerRoot) {
    observerAttached = false;
    emitDiagnostic("MUTATION_OBSERVER_ATTACHED", { attached: false, reason: "document.body unavailable" });
    return;
  }
  observer.observe(observerRoot, { childList: true, subtree: true });
  observerAttached = true;
  emitDiagnostic("MUTATION_OBSERVER_ATTACHED", { attached: true, ...observerStatus() });
}

function inspectDomRoot(): void {
  if (observerRoot === document.body) return;
  if (lastReportedDomRoot === document.body) return;
  lastReportedDomRoot = document.body;
  emitDiagnostic("DOM_ROOT_CHANGED", {
    previous_root_tag: observerRoot?.tagName ?? null,
    current_root_tag: document.body?.tagName ?? null,
    ...observerStatus()
  });
}

function inspectLocation(): void {
  const nextLocation = window.location.href;
  if (nextLocation === lastLocation) {
    inspectDomRoot();
    return;
  }
  const previousLocation = lastLocation;
  const previousSource = activeSource;
  lastLocation = nextLocation;
  activeSource = sourceForLocation(window.location.pathname, previousSource);
  lastTweetSeen = null;
  emitDiagnostic("LOCATION_CHANGED", {
    previous_url: previousLocation,
    next_url: nextLocation,
    previous_source: previousSource,
    next_source: activeSource
  }, previousSource);
  if (activeSource) scheduleScan("route-change");
  inspectDomRoot();
}

function onVisibilityChange(): void {
  if (document.visibilityState === lastVisibility) return;
  const previous = lastVisibility;
  lastVisibility = document.visibilityState;
  emitDiagnostic("PAGE_VISIBILITY_CHANGED", { previous_visibility: previous, visibility: lastVisibility });
}

function onReadyStateChange(): void {
  if (document.readyState === lastReadyState) return;
  const previous = lastReadyState;
  lastReadyState = document.readyState;
  emitDiagnostic("DOCUMENT_READY_STATE_CHANGED", { previous_ready_state: previous, ready_state: lastReadyState });
}

function onPageHide(): void {
  if (!observerAttached) return;
  observerAttached = false;
  observer?.disconnect();
  emitDiagnostic("MUTATION_OBSERVER_DISCONNECTED", { reason: "pagehide", ...observerStatus() });
}

document.addEventListener("visibilitychange", onVisibilityChange);
document.addEventListener("readystatechange", onReadyStateChange);
window.addEventListener("pagehide", onPageHide);

emitDiagnostic("CONTENT_SCRIPT_INIT", {
  initial_source: activeSource,
  initial_url: window.location.href,
  ...observerStatus()
});
emitDiagnostic("PAGE_VISIBILITY_CHANGED", { reason: "init", visibility: document.visibilityState });
emitDiagnostic("DOCUMENT_READY_STATE_CHANGED", { reason: "init", ready_state: document.readyState });
attachObserver();
scheduleScan("initial");

// X changes profile tabs through client-side routing. Re-evaluate the route
// so Profile -> Replies does not require a full page reload to be monitored.
window.setInterval(inspectLocation, OBSERVATION_INTERVAL_MS);
window.setInterval(() => {
  emitDiagnostic("FALLBACK_TIMER_TICK", { expected_interval_ms: HEARTBEAT_INTERVAL_MS });
  scheduleScan("fallback");
}, HEARTBEAT_INTERVAL_MS);
window.setInterval(() => {
  emitDiagnostic("CONTENT_SCRIPT_HEARTBEAT_TIMER_TICK", {
    expected_interval_ms: HEARTBEAT_INTERVAL_MS,
    timer_source: "interval"
  });
  void sendHeartbeat("healthy", null, "interval");
}, HEARTBEAT_INTERVAL_MS);
window.setInterval(() => {
  emitDiagnostic("CONTENT_SCRIPT_LIFECYCLE_TICK", {
    expected_interval_ms: LIFECYCLE_DIAGNOSTIC_INTERVAL_MS,
    observer_status: observerStatus(),
    has_target_dom: currentTargetDom(),
    scan_running: scanRunning
  });
}, LIFECYCLE_DIAGNOSTIC_INTERVAL_MS);
