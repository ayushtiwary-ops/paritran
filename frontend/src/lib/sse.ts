/**
 * EventSource wrapper for the two SSE channels (SPEC 9.2, 9.3).
 *
 * The browser EventSource API cannot set request headers, so the JWT
 * travels as a ?token= query parameter; backend/paritran/api/sse.py
 * verifies it identically to the Authorization header path.
 *
 * Auto-reconnect is OFF by default (the native EventSource retry is
 * suppressed by closing on error); callers opt in per stream. The run
 * stream replays all stored events on connect, so a reconnect never
 * loses data, it re-delivers.
 */

import { getAccessToken, refreshSession } from "./api";

/** SPEC 9.3 envelope: every data: line is {ts, run_id?, stage?, payload}. */
export interface SseEnvelope<P> {
  ts: number | string | null;
  run_id: string | null;
  stage: string | null;
  payload: P;
}

// ---------------------------------------------------------------------------
// Event payload types (SPEC 9.3 catalog, shapes from pipeline.py emissions)

export interface StageCompletedPayload {
  duration_ms: number;
  metrics: Record<string, unknown>;
}

export interface RunEventMap {
  "run.started": { seed: number; generator: string };
  "stage.started": Record<string, never>;
  "stage.completed": StageCompletedPayload;
  "graph.node.added": { id: number };
  "graph.edge.added": { a: number; b: number; w: number };
  "network.discovered": { index: number; size: number; members: number[] };
  "trail.hop": { syndicate: number; src: string; dst: string; amount: number };
  "trail.progress": { syndicate: number; pct: number };
  "mapping.section": {
    complaint_id: number;
    sections: string[];
    confidence: string;
    paths: [string, string[]][];
    routed_to_human: boolean;
  };
  "f9.claim": {
    section: string;
    quote: string;
    is_fabricated: boolean;
    verdict: string;
    sub_class: string | null;
  };
  "custody.appended": { rec: string; prev: string; hash: string };
  "metric.updated": { key: string; value: number | string | boolean };
  "run.completed": Record<string, unknown>;
  "run.failed": { error: string };
  "eval.progress": Record<string, unknown>;
  "alert.critical": Record<string, unknown>;
}

export type RunEventHandlers = {
  [K in keyof RunEventMap]?: (envelope: SseEnvelope<RunEventMap[K]>) => void;
};

export interface ComponentCheck {
  status: string;
  detail: string;
}

export interface StatusTickPayload {
  components: Record<string, ComponentCheck>;
  latency: { count: number; p50_ms: number | null; p95_ms: number | null };
  runs: { total: number; running: number };
}

// ---------------------------------------------------------------------------

export interface StreamHandle {
  close: () => void;
}

export interface StreamOptions {
  /** Default false: on error the stream closes and onError fires once. */
  autoReconnect?: boolean;
  /** Reconnect delay in ms when autoReconnect is on (default 3000). */
  reconnectDelayMs?: number;
  onError?: (event: Event) => void;
}

const TERMINAL_EVENTS = ["run.completed", "run.failed"] as const;

function streamUrl(path: string): string {
  const token = getAccessToken() ?? "";
  return `${path}?token=${encodeURIComponent(token)}`;
}

/**
 * Subscribe to one run's pipeline events. The server replays every stored
 * event first, then tails live ones, and closes after run.completed or
 * run.failed; the wrapper closes its side on a terminal event so the
 * server hang-up is not misread as an error.
 */
export function openRunStream(
  runId: string,
  handlers: RunEventHandlers,
  options: StreamOptions = {},
): StreamHandle {
  const { autoReconnect = false, reconnectDelayMs = 3000, onError } = options;
  let source: EventSource | null = null;
  let closed = false;
  let terminal = false;
  let refreshRetried = false;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const connect = (): void => {
    source = new EventSource(
      streamUrl(`/api/stream/run/${encodeURIComponent(runId)}`),
    );
    for (const name of Object.keys(handlers) as (keyof RunEventMap)[]) {
      const handler = handlers[name];
      if (!handler) continue;
      source.addEventListener(name, (event: MessageEvent<string>) => {
        if (closed) return;
        refreshRetried = false; // data is flowing; allow a future refresh
        let envelope: SseEnvelope<never>;
        try {
          envelope = JSON.parse(event.data) as SseEnvelope<never>;
        } catch {
          return;
        }
        if ((TERMINAL_EVENTS as readonly string[]).includes(name)) {
          terminal = true;
        }
        (handler as (e: SseEnvelope<never>) => void)(envelope);
        if (terminal) {
          // Server ends the stream after a terminal event; close our side
          // so the EventSource does not auto-retry a finished run.
          close();
        }
      });
    }
    source.onerror = (event: Event) => {
      if (closed || terminal) {
        close();
        return;
      }
      source?.close();
      // The most common stream error is an expired access token (the
      // EventSource ?token= cannot rotate mid-stream): refresh once and
      // reconnect; the server replays every stored event, so nothing is
      // lost. Only after a failed refresh does the error surface.
      void (async () => {
        const refreshed = refreshRetried ? false : await refreshSession();
        if (closed) return;
        if (refreshed && !autoReconnect) {
          refreshRetried = true;
          connect();
        } else if (autoReconnect) {
          retryTimer = setTimeout(connect, reconnectDelayMs);
        } else {
          onError?.(event);
        }
      })();
    };
  };

  const close = (): void => {
    closed = true;
    if (retryTimer !== null) clearTimeout(retryTimer);
    source?.close();
  };

  connect();
  return { close };
}

/** Subscribe to the 2 s system status ticks. */
export function openStatusStream(
  onTick: (envelope: SseEnvelope<StatusTickPayload>) => void,
  options: StreamOptions = {},
): StreamHandle {
  const { autoReconnect = false, reconnectDelayMs = 3000, onError } = options;
  let source: EventSource | null = null;
  let closed = false;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  let gotTick = false;

  const connect = (): void => {
    source = new EventSource(streamUrl("/api/stream/status"));
    source.addEventListener("status.tick", (event: MessageEvent<string>) => {
      if (closed) return;
      gotTick = true;
      try {
        onTick(JSON.parse(event.data) as SseEnvelope<StatusTickPayload>);
      } catch {
        // Malformed frame: skip; the next tick arrives in 2 s.
      }
    });
    source.onerror = (event: Event) => {
      if (closed) return;
      source?.close();
      void (async () => {
        // Expired ?token= is the usual cause; refresh before retrying so
        // the reconnect does not hammer 401s with a dead token.
        const refreshed = await refreshSession();
        if (closed) return;
        if (autoReconnect && (refreshed || gotTick)) {
          gotTick = false;
          retryTimer = setTimeout(connect, reconnectDelayMs);
        } else {
          onError?.(event);
        }
      })();
    };
  };

  const close = (): void => {
    closed = true;
    if (retryTimer !== null) clearTimeout(retryTimer);
    source?.close();
  };

  connect();
  return { close };
}
