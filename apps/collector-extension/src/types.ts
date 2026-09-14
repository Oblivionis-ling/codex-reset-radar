export type TweetSource = "profile_dom" | "with_replies" | "search" | "manual";

export interface NormalizedTweet {
  tweet_id: string;
  author: string;
  text: string;
  created_at: string | null;
  url: string;
  is_reply: boolean;
  reply_to: string | null;
  discovered_at: string;
  source: TweetSource;
}

export interface IngestMessage {
  type: "INGEST_TWEETS";
  tweets: NormalizedTweet[];
  trace_id?: string;
}

export interface HeartbeatMessage {
  type: "HEARTBEAT";
  component: string;
  instance_id?: string;
  sequence?: number;
  trace_id?: string;
  request_id?: string;
  observed_at?: string;
  state?: "healthy" | "warning" | "offline";
  last_tweet_seen?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown>;
}

export type DiagnosticEventType =
  | "CONTENT_SCRIPT_INIT"
  | "CONTENT_SCRIPT_HEARTBEAT_SENT"
  | "CONTENT_SCRIPT_HEARTBEAT_FAILED"
  | "CONTENT_SCRIPT_HEARTBEAT_TIMER_TICK"
  | "CONTENT_SCRIPT_LIFECYCLE_TICK"
  | "FALLBACK_TIMER_TICK"
  | "FALLBACK_SCAN_STARTED"
  | "FALLBACK_SCAN_COMPLETED"
  | "FALLBACK_SCAN_FAILED"
  | "MUTATION_OBSERVER_ATTACHED"
  | "MUTATION_OBSERVER_TRIGGERED"
  | "MUTATION_OBSERVER_DISCONNECTED"
  | "DOM_ROOT_CHANGED"
  | "LOCATION_CHANGED"
  | "PAGE_VISIBILITY_CHANGED"
  | "DOCUMENT_READY_STATE_CHANGED"
  | "SERVICE_WORKER_MESSAGE_SENT"
  | "SERVICE_WORKER_MESSAGE_FAILED"
  | "TAB_STATE_SNAPSHOT"
  | "HEARTBEAT_CREATED"
  | "HEARTBEAT_SW_RECEIVED"
  | "HEARTBEAT_HTTP_STARTED"
  | "HEARTBEAT_HTTP_SUCCESS"
  | "HEARTBEAT_HTTP_FAILED"
  | "HEARTBEAT_SKIPPED_NO_ACTIVE_SOURCE"
  | "DIAGNOSTIC_BACKFILL_STARTED"
  | "DIAGNOSTIC_BACKFILL_COMPLETED"
  | "DIAGNOSTIC_BACKFILL_FAILED";

export interface DiagnosticMessage {
  type: "DIAGNOSTIC";
  component: string;
  event: DiagnosticEventType;
  instance_id?: string;
  sequence?: number;
  trace_id?: string;
  request_id?: string;
  observed_at?: string;
  details?: Record<string, unknown>;
}

export interface RuntimeMessageResponse {
  ok: boolean;
  error?: string;
}
