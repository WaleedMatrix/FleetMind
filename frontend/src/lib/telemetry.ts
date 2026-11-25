import { announceSessionExpiry, fleetMindRequest } from "./api";
import type { AlertFilter, Prediction } from "./predictions";

export type StorageState = "ready" | "migration_required" | "unavailable";
export type Availability = "available" | "unavailable" | "stale" | "unknown" | "stopped";
export type Connection = "connecting" | "live" | "reconnecting" | "paused" | "unavailable";

export type AssessmentEvent = {
  cursor: string;
  event_id: string;
  observed_at: string;
  ingested_at: string;
  assessed_at: string;
  prediction: Prediction;
};
export type Snapshot = { state: StorageState; cursor: string | null; items: AssessmentEvent[] };
export type Counters = {
  received: number; processed: number; duplicates: number; invalid: number;
  retried_events: number; retry_attempts: number; dead_lettered: number; committed: number;
};
export type MetricPoint = {
  started_at: string; received_per_s: number | null; committed_per_s: number | null;
  max_worker_lag: number | null; inference_ms: number | null; database_ms: number | null;
  observation_to_commit_ms: number | null;
};
export type Metrics = {
  state: StorageState; as_of: string; window_seconds: number; bucket_seconds: number;
  stale_after_seconds: number; worker: Availability; broker: Availability;
  active_workers: number | null; last_report_at: string | null; last_broker_probe_at: string | null;
  last_assessed_at: string | null; durable_assessments: number | null; reported_totals: Counters | null;
  max_worker_lag: number | null; truncated: boolean; points: MetricPoint[];
};
export type DeadLetter = {
  category: "invalid_payload" | "unsupported_version" | "partition_key_mismatch" |
    "missing_asset" | "machine_type_mismatch" | "event_id_conflict";
  rejected_at: string; event_id: string | null; original_topic: string;
  original_partition: number; original_offset: number;
};
export type DeadLetters = { state: StorageState; last_report_at: string | null; items: DeadLetter[] };

export const FEED_LIMIT = 60;

export function telemetryQuery(asset: string, filter: AlertFilter) {
  const params = new URLSearchParams();
  if (asset) params.set("asset_id", asset);
  if (filter !== "all") params.set("alert_level", filter);
  return params.toString();
}

function cursorValue(cursor: unknown): cursor is string {
  return typeof cursor === "string" && /^(0|[1-9][0-9]{0,18})$/.test(cursor);
}

function newer(a: string, b: string) {
  return a.length > b.length || (a.length === b.length && a > b);
}

export function mergeAssessments(current: AssessmentEvent[], incoming: AssessmentEvent[]) {
  const unique = new Map(current.map((item) => [item.event_id, item]));
  for (const item of incoming) unique.set(item.event_id, item);
  return [...unique.values()].sort((a, b) => a.cursor === b.cursor ? 0 : newer(a.cursor, b.cursor) ? -1 : 1)
    .slice(0, FEED_LIMIT);
}

type FeedHandlers = {
  cursor?: string;
  query?: string;
  onBatch: (items: AssessmentEvent[], cursor: string) => void;
  onStatus?: (status: Connection, detail?: string) => void;
  onReset?: () => void;
  onReady?: () => void;
};

export function followTelemetry(handlers: FeedHandlers) {
  let last = handlers.cursor;
  let source: EventSource | null = null;
  let pending: AssessmentEvent[] = [];
  let batchTimer = 0;
  let retryTimer = 0;
  let watchdog = 0;
  let retries = 0;
  let disposed = false;

  function flush() {
    window.clearTimeout(batchTimer);
    batchTimer = 0;
    if (last !== undefined) handlers.onBatch(pending, last);
    pending = [];
  }

  function touch() {
    window.clearTimeout(watchdog);
    watchdog = window.setTimeout(() => retry("The live stream stopped responding."), 25_000);
  }

  function retry(detail?: string) {
    if (disposed) return;
    source?.close();
    source = null;
    window.clearTimeout(watchdog);
    window.clearTimeout(retryTimer);
    if (batchTimer) flush();
    handlers.onStatus?.(detail ? "unavailable" : "reconnecting", detail);
    retryTimer = window.setTimeout(open, Math.min(2_000 * 2 ** retries++, 30_000));
  }

  function open() {
    if (disposed) return;
    const params = new URLSearchParams(handlers.query);
    if (last !== undefined) params.set("cursor", last);
    const stream = new EventSource(`/api/fleetmind/telemetry/stream?${params}`);
    source = stream;
    touch();
    const listen = (name: string, handle: (event: MessageEvent<string>) => void) => {
      stream.addEventListener(name, (event) => {
        if (disposed || source !== stream) return;
        touch();
        handle(event as MessageEvent<string>);
      });
    };
    listen("ready", (event) => {
      if (!cursorValue(event.lastEventId)) return;
      last ??= event.lastEventId;
      retries = 0;
      handlers.onStatus?.("live");
      handlers.onReady?.();
    });
    listen("session_expired", () => {
      stream.close();
      source = null;
      window.clearTimeout(watchdog);
      announceSessionExpiry();
    });
    listen("heartbeat", () => undefined);
    listen("cursor", (event) => {
      if (cursorValue(event.lastEventId) && (last === undefined || newer(event.lastEventId, last))) {
        last = event.lastEventId;
        if (!batchTimer) batchTimer = window.setTimeout(flush, 150);
      }
    });
    listen("assessment", (event) => {
      if (!cursorValue(event.lastEventId) || (last !== undefined && !newer(event.lastEventId, last))) return;
      try {
        const item = JSON.parse(event.data) as AssessmentEvent;
        if (item.cursor !== event.lastEventId || !item.event_id || !item.prediction) throw new Error();
        last = item.cursor;
        pending.push(item);
        if (pending.length > FEED_LIMIT) pending.shift();
        if (!batchTimer) batchTimer = window.setTimeout(flush, 150);
      } catch {
        retry("The live stream sent an invalid assessment.");
      }
    });
    listen("reset", () => {
      if (handlers.onReset) {
        stream.close();
        source = null;
        window.clearTimeout(watchdog);
        handlers.onReset();
      } else {
        last = undefined;
        retry();
      }
    });
    listen("unavailable", (event) => {
      let detail = "Live telemetry is unavailable.";
      try { detail = (JSON.parse(event.data) as { detail?: string }).detail || detail; } catch {}
      retry(detail);
    });
    stream.onerror = () => {
      if (source !== stream) return;
      retry();
      void fleetMindRequest("auth/me").catch(() => undefined);
    };
  }

  handlers.onStatus?.("connecting");
  open();
  return () => {
    disposed = true;
    source?.close();
    window.clearTimeout(watchdog);
    window.clearTimeout(retryTimer);
    window.clearTimeout(batchTimer);
  };
}
