/**
 * Global System Status widget (SPEC 10.3 item 6), bottom of the nav.
 *
 * Consumes GET /api/stream/status over SSE: colored component dots
 * (forest ok, oxblood down, muted unknown) and a p50/p95 latency
 * sparkline drawn as inline SVG from the last 30 ticks. When the
 * backend reports null percentiles (no requests recorded yet) the
 * widget says so instead of inventing a number.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  openStatusStream,
  type StatusTickPayload,
  type StreamHandle,
} from "../lib/sse";

const MAX_TICKS = 30;

interface LatencyPoint {
  p50: number | null;
  p95: number | null;
}

interface WidgetState {
  connected: boolean;
  components: Record<string, { status: string; detail: string }> | null;
  latencies: LatencyPoint[];
  runsRunning: number | null;
}

function dotColor(status: string | undefined): string {
  if (status === undefined) return "var(--color-muted)";
  return status.trim().toLowerCase() === "ok"
    ? "var(--color-forest)"
    : "var(--color-oxblood)";
}

function Sparkline({ points }: { points: LatencyPoint[] }) {
  const width = 180;
  const height = 34;

  const drawn = useMemo(() => {
    const p95Values = points
      .map((p) => p.p95)
      .filter((v): v is number => v !== null);
    if (p95Values.length < 2) return null;
    const max = Math.max(
      ...p95Values,
      ...points.map((p) => p.p50 ?? 0),
      1,
    );
    const toPath = (pick: (p: LatencyPoint) => number | null): string =>
      points
        .map((p, i) => {
          const v = pick(p);
          if (v === null) return null;
          const x = (i / Math.max(points.length - 1, 1)) * width;
          const y = height - (v / max) * (height - 4) - 2;
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .filter((s): s is string => s !== null)
        .join(" ");
    return { p50: toPath((p) => p.p50), p95: toPath((p) => p.p95), max };
  }, [points]);

  if (drawn === null) {
    return (
      <p className="sparkline-caption">latency: no request data yet</p>
    );
  }

  return (
    <div>
      <p className="sparkline-caption">
        p50 / p95 request latency, last {points.length} ticks (max{" "}
        {drawn.max.toFixed(0)} ms)
      </p>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="p50 and p95 latency sparkline"
      >
        <polyline
          points={drawn.p50}
          fill="none"
          stroke="var(--color-teal)"
          strokeWidth="1.5"
        />
        <polyline
          points={drawn.p95}
          fill="none"
          stroke="var(--color-gold)"
          strokeWidth="1.5"
        />
      </svg>
    </div>
  );
}

export function StatusWidget() {
  const [state, setState] = useState<WidgetState>({
    connected: false,
    components: null,
    latencies: [],
    runsRunning: null,
  });
  const handleRef = useRef<StreamHandle | null>(null);

  useEffect(() => {
    const onTick = (envelope: { payload: StatusTickPayload }) => {
      const { components, latency, runs } = envelope.payload;
      setState((prev) => ({
        connected: true,
        components,
        latencies: [
          ...prev.latencies,
          { p50: latency.p50_ms, p95: latency.p95_ms },
        ].slice(-MAX_TICKS),
        runsRunning: runs.running,
      }));
    };
    handleRef.current = openStatusStream(onTick, {
      autoReconnect: true,
      reconnectDelayMs: 4000,
    });
    return () => handleRef.current?.close();
  }, []);

  const componentNames = state.components
    ? Object.keys(state.components)
    : ["db", "ollama", "model_files"];

  return (
    <aside className="status-widget" aria-live="polite" aria-label="System status">
      <p className="status-title">System status</p>
      <ul>
        {componentNames.map((name) => {
          const check = state.components?.[name];
          return (
            <li key={name}>
              <span
                className="dot"
                style={{ background: dotColor(check?.status) }}
                aria-hidden="true"
              />
              <span>{name}</span>
              <span className="muted">{check?.status ?? "unknown"}</span>
            </li>
          );
        })}
      </ul>
      <Sparkline points={state.latencies} />
      {state.runsRunning !== null && state.runsRunning > 0 && (
        <p className="sparkline-caption">
          {state.runsRunning} run{state.runsRunning === 1 ? "" : "s"} in
          progress
        </p>
      )}
      {!state.connected && (
        <p className="sparkline-caption">waiting for status stream</p>
      )}
    </aside>
  );
}
