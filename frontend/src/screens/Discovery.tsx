/**
 * Discovery & Triage, the hero screen (SPEC 10.3 item 1).
 *
 * Start run -> POST /api/intake/run -> subscribe SSE
 * /api/stream/run/{id}. graph.node.added / graph.edge.added events
 * stream into a canvas force graph so complaints visibly collapse into
 * networks; network.discovered colors communities; noise stays muted.
 * Counters animate on metric.updated values only. The triage queue
 * ranks networks by recoverability with every formula input exposed
 * (GET /api/networks). Rejecting a link posts an officer decision
 * (optimistic, rolled back on error) and surfaces the audit hash.
 *
 * Truth rule 1: every number on this screen arrives in an SSE or REST
 * payload. Event pacing (the visible collapse) delays WHEN real events
 * paint, never WHAT they say.
 */

import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type FormEvent,
} from "react";
import CountUp from "react-countup";
import ForceGraph2D, {
  type ForceGraphMethods,
  type LinkObject,
  type NodeObject,
} from "react-force-graph-2d";
import Skeleton, { SkeletonTheme } from "react-loading-skeleton";
import "react-loading-skeleton/dist/skeleton.css";
import { useSearchParams } from "react-router";
import { pushToast } from "../app/toasts";
import {
  ApiError,
  getNetworks,
  postDecision,
  startRun,
  type NetworkSummary,
} from "../lib/api";
import { inr, num, pct, shortHash } from "../lib/format";
import { recordRecentRun } from "../lib/recentRuns";
import {
  openRunStream,
  type RunEventMap,
  type SseEnvelope,
  type StreamHandle,
} from "../lib/sse";

// ---------------------------------------------------------------------------
// Run state reducer (non-graph events)

const STAGES = [
  "ingest",
  "entity_resolution",
  "linkage",
  "money_trail",
  "triage",
  "legal_mapping",
  "f9_audit",
  "packet",
  "signoff",
] as const;

type StageName = (typeof STAGES)[number];
type StageStatus = "pending" | "running" | "done";

interface RunState {
  runStatus: "idle" | "running" | "completed" | "failed";
  seed: number | null;
  generator: string | null;
  stages: Record<string, StageStatus>;
  /** metric.updated key -> value, verbatim from payloads. */
  metrics: Record<string, number | string | boolean>;
  /** linkage stage.completed metrics (precision/recall/f1/n_edges). */
  linkage: Record<string, unknown> | null;
  /** money_trail stage.completed metrics (traced_amt/total_amt/...). */
  money: Record<string, unknown> | null;
  networksDiscovered: number;
  trailPct: number | null;
  error: string | null;
  streamLost: boolean;
}

const initialRunState: RunState = {
  runStatus: "idle",
  seed: null,
  generator: null,
  stages: {},
  metrics: {},
  linkage: null,
  money: null,
  networksDiscovered: 0,
  trailPct: null,
  error: null,
  streamLost: false,
};

type RunAction =
  | { type: "reset" }
  | { type: "run.started"; seed: number; generator: string }
  | { type: "stage.started"; stage: string }
  | { type: "stage.completed"; stage: string; metrics: Record<string, unknown> }
  | { type: "metric.updated"; key: string; value: number | string | boolean }
  | { type: "network.discovered" }
  | { type: "trail.progress"; pctValue: number }
  | { type: "run.completed" }
  | { type: "run.failed"; error: string }
  | { type: "stream.lost" };

function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "reset":
      return { ...initialRunState, runStatus: "running" };
    case "run.started":
      return {
        ...state,
        runStatus: "running",
        seed: action.seed,
        generator: action.generator,
      };
    case "stage.started":
      return {
        ...state,
        stages: { ...state.stages, [action.stage]: "running" },
      };
    case "stage.completed": {
      const next: RunState = {
        ...state,
        stages: { ...state.stages, [action.stage]: "done" },
      };
      if (action.stage === "linkage") next.linkage = action.metrics;
      if (action.stage === "money_trail") next.money = action.metrics;
      return next;
    }
    case "metric.updated":
      return {
        ...state,
        metrics: { ...state.metrics, [action.key]: action.value },
      };
    case "network.discovered":
      return { ...state, networksDiscovered: state.networksDiscovered + 1 };
    case "trail.progress":
      return { ...state, trailPct: action.pctValue };
    case "run.completed":
      return { ...state, runStatus: "completed" };
    case "run.failed":
      return { ...state, runStatus: "failed", error: action.error };
    case "stream.lost":
      return { ...state, streamLost: true };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Graph data (paced application of graph.* events)

interface NodeDatum {
  id: number;
  community: number | null;
}

interface LinkDatum {
  w: number;
}

type GNode = NodeObject<NodeDatum>;
type GLink = LinkObject<NodeDatum, LinkDatum>;

type GraphEvent =
  | { kind: "node"; id: number }
  | { kind: "edge"; a: number; b: number; w: number }
  | { kind: "network"; index: number; members: number[] };

/** Distinct community hues that sit on the navy canvas; noise is muted. */
const COMMUNITY_COLORS = [
  "#3E9E9F",
  "#C98D3D",
  "#4C9A72",
  "#6FA8DC",
  "#C06C6C",
  "#9B7FC7",
  "#D4B26A",
  "#5BBFA5",
];
const NOISE_COLOR = "#87847A";
const UNASSIGNED_COLOR = "#FBFAF6";

function communityColor(community: number | null): string {
  if (community === null) return UNASSIGNED_COLOR;
  return COMMUNITY_COLORS[community % COMMUNITY_COLORS.length] ?? NOISE_COLOR;
}

function endpointId(end: GLink["source"]): number | null {
  if (typeof end === "number") return end;
  if (typeof end === "object" && end !== null && typeof end.id === "number") {
    return end.id;
  }
  return null;
}

interface SelectedLink {
  a: number;
  b: number;
  w: number;
}

// ---------------------------------------------------------------------------

export function Discovery() {
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const reduceMotion = useReducedMotion() ?? false;

  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const [seedInput, setSeedInput] = useState("42");
  const [generatorInput, setGeneratorInput] = useState<"stub" | "ollama">(
    "stub",
  );
  const [starting, setStarting] = useState(false);
  const [selectedLink, setSelectedLink] = useState<SelectedLink | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [hoverNode, setHoverNode] = useState<GNode | null>(null);

  // Graph data lives in refs (mutated by the paced drainer); a state
  // object identity change triggers the canvas re-join.
  const nodesRef = useRef<GNode[]>([]);
  const linksRef = useRef<GLink[]>([]);
  const nodeIndexRef = useRef<Map<number, GNode>>(new Map());
  const adjacencyRef = useRef<Map<number, Set<number>>>(new Map());
  const queueRef = useRef<GraphEvent[]>([]);
  const [graphData, setGraphData] = useState<{ nodes: GNode[]; links: GLink[] }>(
    { nodes: [], links: [] },
  );
  const graphRef = useRef<ForceGraphMethods<GNode, GLink> | undefined>(
    undefined,
  );

  const graphContainerRef = useRef<HTMLDivElement | null>(null);
  const [graphSize, setGraphSize] = useState({ width: 640, height: 480 });

  useEffect(() => {
    const el = graphContainerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setGraphSize({
        width: Math.max(entry.contentRect.width, 200),
        height: Math.max(entry.contentRect.height, 320),
      });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const resetGraph = useCallback(() => {
    nodesRef.current = [];
    linksRef.current = [];
    nodeIndexRef.current = new Map();
    adjacencyRef.current = new Map();
    queueRef.current = [];
    setGraphData({ nodes: [], links: [] });
    setSelectedLink(null);
    setHoverNode(null);
  }, []);

  const applyGraphEvent = useCallback((event: GraphEvent) => {
    if (event.kind === "node") {
      if (nodeIndexRef.current.has(event.id)) return;
      const node: GNode = { id: event.id, community: null };
      nodeIndexRef.current.set(event.id, node);
      nodesRef.current.push(node);
    } else if (event.kind === "edge") {
      linksRef.current.push({ source: event.a, target: event.b, w: event.w });
      const adj = adjacencyRef.current;
      if (!adj.has(event.a)) adj.set(event.a, new Set());
      if (!adj.has(event.b)) adj.set(event.b, new Set());
      adj.get(event.a)?.add(event.b);
      adj.get(event.b)?.add(event.a);
    } else {
      for (const member of event.members) {
        const node = nodeIndexRef.current.get(member);
        if (node) node.community = event.index;
      }
    }
  }, []);

  // Paced drainer: applies queued graph events at a bounded rate so the
  // collapse is visible (pacing changes WHEN real events paint, never
  // WHAT they say). The batch grows with the backlog so long edge tails
  // still finish in seconds. Reduced motion applies everything at once.
  useEffect(() => {
    const interval = setInterval(() => {
      const queue = queueRef.current;
      if (queue.length === 0) return;
      const BATCH = reduceMotion
        ? Number.POSITIVE_INFINITY
        : Math.max(12, Math.ceil(queue.length / 15));
      let applied = 0;
      let discovered = 0;
      while (queue.length > 0 && applied < BATCH) {
        const event = queue.shift();
        if (!event) break;
        applyGraphEvent(event);
        if (event.kind === "network") discovered += 1;
        applied += 1;
      }
      for (let i = 0; i < discovered; i++) {
        dispatch({ type: "network.discovered" });
      }
      setGraphData({
        nodes: [...nodesRef.current],
        links: [...linksRef.current],
      });
    }, 25);
    return () => clearInterval(interval);
  }, [applyGraphEvent, reduceMotion]);

  // SSE subscription for the run named in ?run=.
  useEffect(() => {
    if (runId === null) return;
    dispatch({ type: "reset" });
    resetGraph();

    const on = <K extends keyof RunEventMap>(
      handler: (e: SseEnvelope<RunEventMap[K]>) => void,
    ) => handler;

    const handle: StreamHandle = openRunStream(
      runId,
      {
        "run.started": on<"run.started">((e) =>
          dispatch({
            type: "run.started",
            seed: e.payload.seed,
            generator: e.payload.generator,
          }),
        ),
        "stage.started": on<"stage.started">((e) => {
          if (e.stage) dispatch({ type: "stage.started", stage: e.stage });
        }),
        "stage.completed": on<"stage.completed">((e) => {
          if (e.stage) {
            dispatch({
              type: "stage.completed",
              stage: e.stage,
              metrics: e.payload.metrics,
            });
          }
        }),
        "metric.updated": on<"metric.updated">((e) =>
          dispatch({
            type: "metric.updated",
            key: e.payload.key,
            value: e.payload.value,
          }),
        ),
        "graph.node.added": on<"graph.node.added">((e) => {
          queueRef.current.push({ kind: "node", id: e.payload.id });
        }),
        "graph.edge.added": on<"graph.edge.added">((e) => {
          queueRef.current.push({
            kind: "edge",
            a: e.payload.a,
            b: e.payload.b,
            w: e.payload.w,
          });
        }),
        "network.discovered": on<"network.discovered">((e) => {
          queueRef.current.push({
            kind: "network",
            index: e.payload.index,
            members: e.payload.members,
          });
        }),
        "trail.progress": on<"trail.progress">((e) =>
          dispatch({ type: "trail.progress", pctValue: e.payload.pct }),
        ),
        "run.completed": on<"run.completed">(() =>
          dispatch({ type: "run.completed" }),
        ),
        "run.failed": on<"run.failed">((e) =>
          dispatch({ type: "run.failed", error: e.payload.error }),
        ),
      },
      {
        onError: () => dispatch({ type: "stream.lost" }),
      },
    );
    return () => handle.close();
  }, [runId, resetGraph]);

  // Triage queue: per-network scores + all formula inputs, once complete.
  // The backend answers 409 for a few hundred ms between the run.completed
  // SSE event and the run registry flipping to completed; retry through it.
  const networksQuery = useQuery({
    queryKey: ["networks", runId],
    queryFn: () => getNetworks(runId ?? ""),
    enabled: runId !== null && state.runStatus === "completed",
    staleTime: Number.POSITIVE_INFINITY,
    retry: (failureCount, error) =>
      error instanceof ApiError && error.status === 409 && failureCount < 30,
    retryDelay: 700,
  });

  const onStartRun = async (event: FormEvent) => {
    event.preventDefault();
    if (starting) return;
    const seed = Number.parseInt(seedInput.trim(), 10);
    if (!Number.isSafeInteger(seed)) {
      pushToast({
        title: "Seed must be an integer",
        tone: "danger",
        assertive: true,
      });
      return;
    }
    setStarting(true);
    try {
      const started = await startRun(seed, generatorInput);
      // Case File's run picker reads this back from sessionStorage.
      recordRecentRun({
        run_id: started.run_id,
        seed: started.seed,
        generator: started.generator,
        started_at: new Date().toISOString(),
      });
      setSearchParams({ run: started.run_id });
      pushToast({
        title: `Run started (seed ${started.seed}, ${started.generator})`,
        detail: started.run_id,
        tone: "info",
      });
    } catch (error) {
      pushToast({
        title: "Run failed to start",
        detail: error instanceof ApiError ? error.detail : String(error),
        tone: "danger",
        assertive: true,
      });
    } finally {
      setStarting(false);
    }
  };

  const neighborSet = useMemo(() => {
    if (hoverNode === null || typeof hoverNode.id !== "number") return null;
    const set = new Set<number>(adjacencyRef.current.get(hoverNode.id) ?? []);
    set.add(hoverNode.id);
    return set;
  }, [hoverNode]);

  const nodeColor = useCallback(
    (node: GNode): string => {
      const base = communityColor(node.community ?? null);
      if (neighborSet !== null && typeof node.id === "number") {
        if (!neighborSet.has(node.id)) return "rgba(135, 132, 122, 0.15)";
      }
      return base;
    },
    [neighborSet],
  );

  const linkColor = useCallback(
    (link: GLink): string => {
      const a = endpointId(link.source);
      const b = endpointId(link.target);
      if (neighborSet !== null) {
        if (a === null || b === null || !neighborSet.has(a) || !neighborSet.has(b)) {
          return "rgba(135, 132, 122, 0.06)";
        }
        return "rgba(251, 250, 246, 0.65)";
      }
      return "rgba(251, 250, 246, 0.22)";
    },
    [neighborSet],
  );

  const onLinkClick = useCallback((link: GLink) => {
    const a = endpointId(link.source);
    const b = endpointId(link.target);
    if (a === null || b === null) return;
    setSelectedLink({ a, b, w: link.w });
  }, []);

  const rejectLink = async () => {
    if (selectedLink === null || runId === null || rejecting) return;
    const { a, b, w } = selectedLink;
    setRejecting(true);

    // Optimistic removal; the exact link objects are restored on error.
    const removed = linksRef.current.filter((l) => {
      const la = endpointId(l.source);
      const lb = endpointId(l.target);
      return (la === a && lb === b) || (la === b && lb === a);
    });
    linksRef.current = linksRef.current.filter((l) => !removed.includes(l));
    adjacencyRef.current.get(a)?.delete(b);
    adjacencyRef.current.get(b)?.delete(a);
    setGraphData({ nodes: [...nodesRef.current], links: [...linksRef.current] });
    setSelectedLink(null);

    try {
      const appended = await postDecision({
        run_id: runId,
        kind: "link",
        ref: { a, b, w },
        decision: "reject",
      });
      pushToast({
        title: `Link ${a} to ${b} rejected, audit seq ${appended.seq}`,
        detail: `${appended.action} ${shortHash(appended.hash)}`,
        tone: "success",
        assertive: true,
      });
    } catch (error) {
      // Rollback: the decision did not land on the audit chain.
      linksRef.current = [...linksRef.current, ...removed];
      adjacencyRef.current.get(a)?.add(b);
      adjacencyRef.current.get(b)?.add(a);
      setGraphData({
        nodes: [...nodesRef.current],
        links: [...linksRef.current],
      });
      setSelectedLink({ a, b, w });
      pushToast({
        title: "Reject failed, link restored",
        detail: error instanceof ApiError ? error.detail : String(error),
        tone: "danger",
        assertive: true,
      });
    } finally {
      setRejecting(false);
    }
  };

  const complaintsIngested = state.metrics["n_complaints"];
  const rupeesAtRisk = state.money?.["total_amt"];
  const tracedAmt = state.money?.["traced_amt"];
  const pctTraced = state.metrics["pct_value_traced_to_cashout"];
  const linkageMetrics = state.linkage;

  const running = state.runStatus === "running";
  const countUpDuration = reduceMotion ? 0 : 1.2;

  // Keyboard-accessible link selection (SPEC 10.4): the heaviest streamed
  // links, straight from graph.edge.added payloads, selectable as buttons.
  const strongestLinks = useMemo(() => {
    const rows: SelectedLink[] = [];
    for (const link of graphData.links) {
      const a = endpointId(link.source);
      const b = endpointId(link.target);
      if (a === null || b === null) continue;
      rows.push({ a, b, w: link.w });
    }
    rows.sort((x, y) => y.w - x.w || x.a - y.a || x.b - y.b);
    return rows.slice(0, 5);
  }, [graphData.links]);

  const rankedNetworks: NetworkSummary[] = useMemo(() => {
    const rows = networksQuery.data?.networks ?? [];
    return [...rows].sort(
      (x, y) => (y.triage?.score ?? -1) - (x.triage?.score ?? -1),
    );
  }, [networksQuery.data]);

  return (
    <SkeletonTheme baseColor="#1E3A6B" highlightColor="#2E4E86">
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {/* Run controls */}
        <form
          onSubmit={(e) => void onStartRun(e)}
          className="card"
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: "0.9rem",
            flexWrap: "wrap",
          }}
        >
          <div>
            <label className="field-label" htmlFor="seed-input">
              Seed
            </label>
            <input
              id="seed-input"
              className="input"
              style={{ width: "7rem" }}
              inputMode="numeric"
              value={seedInput}
              onChange={(e) => setSeedInput(e.target.value)}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="generator-select">
              Generator
            </label>
            <select
              id="generator-select"
              className="select"
              value={generatorInput}
              onChange={(e) =>
                setGeneratorInput(e.target.value === "ollama" ? "ollama" : "stub")
              }
            >
              <option value="stub">stub (deterministic, labelled)</option>
              <option value="ollama">ollama (live model)</option>
            </select>
          </div>
          <button type="submit" className="btn btn-primary" disabled={starting}>
            {starting ? "Starting" : "Start run"}
          </button>
          {state.seed !== null && (
            <span className="mono small muted">
              run seed {state.seed} . generator {state.generator} . status{" "}
              {state.runStatus}
            </span>
          )}
          {state.streamLost && state.runStatus === "running" && (
            <span className="error-box small">
              Event stream disconnected. Reload to replay (the server
              replays every stored event).
            </span>
          )}
        </form>

        {state.runStatus === "failed" && state.error !== null && (
          <div className="error-box" role="alert">
            Run failed: {state.error}
          </div>
        )}

        {/* Stage rail */}
        {runId !== null && (
          <div className="stage-rail" aria-label="Pipeline stages">
            {STAGES.map((stage: StageName) => {
              const status = state.stages[stage] ?? "pending";
              return (
                <span
                  key={stage}
                  className={`stage-pill ${status === "done" ? "done" : status === "running" ? "running" : ""}`}
                >
                  {stage}
                </span>
              );
            })}
          </div>
        )}

        {/* Counters (every value from metric.updated / stage.completed) */}
        <div className="counter-row" aria-live="polite">
          <motion.div
            className="card"
            initial={reduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <p className="counter-label">Complaints ingested</p>
            <p className="counter-value">
              {typeof complaintsIngested === "number" ? (
                <CountUp
                  end={complaintsIngested}
                  duration={countUpDuration}
                  separator=","
                  preserveValue
                />
              ) : (
                <span className="muted">{running ? "…" : "no run yet"}</span>
              )}
            </p>
            <p className="counter-sub">metric: n_complaints</p>
          </motion.div>

          <motion.div
            className="card"
            initial={reduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <p className="counter-label">Networks found</p>
            <p className="counter-value">
              {runId !== null ? (
                <CountUp
                  end={state.networksDiscovered}
                  duration={reduceMotion ? 0 : 0.5}
                  preserveValue
                />
              ) : (
                <span className="muted">no run yet</span>
              )}
            </p>
            <p className="counter-sub">network.discovered events</p>
          </motion.div>

          <motion.div
            className="card"
            initial={reduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <p className="counter-label">Rupees at risk</p>
            <p className="counter-value">
              {typeof rupeesAtRisk === "number" ? (
                <CountUp
                  end={rupeesAtRisk}
                  duration={countUpDuration}
                  preserveValue
                  formattingFn={inr}
                />
              ) : (
                <span className="muted">
                  {running ? "awaiting money trail" : "no run yet"}
                </span>
              )}
            </p>
            <p className="counter-sub">
              {typeof tracedAmt === "number" && typeof pctTraced === "number"
                ? `${inr(tracedAmt)} traced to cash-out (${pct(pctTraced)})`
                : state.trailPct !== null
                  ? `tracing ${pct(state.trailPct)}`
                  : "money_trail stage totals"}
            </p>
          </motion.div>

          <motion.div
            className="card"
            initial={reduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <p className="counter-label">Linkage quality</p>
            {linkageMetrics !== null ? (
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                {(["precision", "recall", "f1"] as const).map((key) => {
                  const value = linkageMetrics[key];
                  return typeof value === "number" ? (
                    <span key={key} className="metric-chip">
                      {key === "f1" ? "F1" : key.slice(0, 1).toUpperCase()}
                      <strong>{num(value)}</strong>
                    </span>
                  ) : null;
                })}
              </div>
            ) : (
              <p className="counter-value">
                <span className="muted">
                  {running ? "awaiting linkage" : "no run yet"}
                </span>
              </p>
            )}
            <p className="counter-sub">appears when the linkage stage completes</p>
          </motion.div>
        </div>

        {/* Graph + side column */}
        <div className="discovery-grid">
          <div
            className="card graph-panel"
            ref={graphContainerRef}
            style={{ height: "520px" }}
          >
            <div className="graph-overlay">
              {graphData.nodes.length > 0 && (
                <span>
                  {graphData.nodes.length} nodes . {graphData.links.length}{" "}
                  links
                  {queueRef.current.length > 0 ? " . streaming" : ""}
                </span>
              )}
            </div>
            {graphData.nodes.length === 0 && (
              <div className="graph-empty">
                {runId === null
                  ? "No run yet. Start a run to stream the linkage graph in, complaint by complaint."
                  : "Waiting for graph events on the run stream."}
              </div>
            )}
            <ForceGraph2D<NodeDatum, LinkDatum>
              ref={graphRef}
              width={graphSize.width}
              height={graphSize.height}
              graphData={graphData}
              backgroundColor="rgba(0,0,0,0)"
              nodeColor={nodeColor}
              nodeRelSize={3.2}
              nodeLabel={(node) =>
                `complaint ${String(node.id)}${
                  typeof node.community === "number"
                    ? ` . network ${node.community}`
                    : " . unassigned"
                }`
              }
              linkColor={linkColor}
              linkWidth={(link) => Math.min(1 + link.w * 0.4, 3)}
              linkLabel={(link) => `shared identifiers: ${link.w}`}
              onNodeHover={(node) => setHoverNode(node)}
              onLinkClick={onLinkClick}
              cooldownTicks={reduceMotion ? 0 : undefined}
              d3VelocityDecay={0.35}
            />
          </div>

          <div className="side-panel">
            {/* Link inspector */}
            <div className="card">
              <h3>Link inspector</h3>
              {selectedLink === null ? (
                <div>
                  <p className="muted small" style={{ margin: 0 }}>
                    Click a link in the graph (or pick one below) to
                    inspect it and, if it is wrong, reject it. Every
                    rejection lands on the audit chain.
                  </p>
                  {strongestLinks.length > 0 && (
                    <ul className="strong-links" aria-label="Strongest links">
                      {strongestLinks.map((link) => (
                        <li key={`${link.a}-${link.b}`}>
                          <button
                            type="button"
                            className="btn small"
                            onClick={() =>
                              setSelectedLink({
                                a: link.a,
                                b: link.b,
                                w: link.w,
                              })
                            }
                          >
                            {link.a} to {link.b}
                            <span className="muted"> . w {link.w}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : (
                <motion.div
                  initial={reduceMotion ? false : { opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                >
                  <dl className="link-facts">
                    <dt>complaint A</dt>
                    <dd>{selectedLink.a}</dd>
                    <dt>complaint B</dt>
                    <dd>{selectedLink.b}</dd>
                    <dt>shared identifiers</dt>
                    <dd>{selectedLink.w}</dd>
                  </dl>
                  <div
                    style={{ display: "flex", gap: "0.5rem", marginTop: "0.8rem" }}
                  >
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => void rejectLink()}
                      disabled={rejecting}
                    >
                      {rejecting ? "Rejecting" : "Reject link"}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setSelectedLink(null)}
                    >
                      Close
                    </button>
                  </div>
                </motion.div>
              )}
            </div>

            {/* Triage queue */}
            <div className="card">
              <h3>Triage queue (recoverability)</h3>
              {runId === null && (
                <p className="muted small" style={{ margin: 0 }}>
                  Ranks discovered networks once a run completes. All
                  formula inputs are shown next to each score.
                </p>
              )}
              {runId !== null && state.runStatus === "running" && (
                <div aria-label="Loading triage queue">
                  <Skeleton height={72} count={3} style={{ marginBottom: 8 }} />
                </div>
              )}
              {runId !== null && state.runStatus === "failed" && (
                <p className="muted small" style={{ margin: 0 }}>
                  Run failed; no triage queue for this run.
                </p>
              )}
              {state.runStatus === "completed" && networksQuery.isPending && (
                <Skeleton height={72} count={3} style={{ marginBottom: 8 }} />
              )}
              {state.runStatus === "completed" && networksQuery.isError && (
                <p className="error-box small" style={{ margin: 0 }}>
                  Could not load networks:{" "}
                  {networksQuery.error instanceof ApiError
                    ? networksQuery.error.detail
                    : String(networksQuery.error)}
                </p>
              )}
              {networksQuery.data && (
                <ol className="triage-list">
                  {rankedNetworks.map((network) => (
                    <li key={network.index} className="triage-item">
                      <div className="triage-head">
                        <span>
                          <span
                            className="dot"
                            style={{
                              background: communityColor(network.index),
                              marginRight: "0.45rem",
                            }}
                            aria-hidden="true"
                          />
                          network {network.index}
                          <span className="muted small">
                            {" "}
                            . {network.size} complaints
                          </span>
                        </span>
                        <span className="triage-score">
                          {network.triage !== null
                            ? num(network.triage.score)
                            : "no score"}
                        </span>
                      </div>
                      {network.triage !== null ? (
                        <dl className="triage-inputs">
                          {Object.entries(network.triage.inputs).map(
                            ([key, value]) => (
                              <div
                                key={key}
                                style={{ display: "contents" }}
                              >
                                <dt>{key}</dt>
                                <dd>{num(value)}</dd>
                              </div>
                            ),
                          )}
                        </dl>
                      ) : (
                        <p className="muted small" style={{ margin: "0.35rem 0 0" }}>
                          No ground-truth syndicate for this community; no
                          triage inputs to show.
                        </p>
                      )}
                      {network.trail !== null && (
                        <p className="counter-sub">
                          trail {inr(network.trail.traced_amt)} of{" "}
                          {inr(network.trail.total_amt)} traced .{" "}
                          {network.trail.breaks.length} break
                          {network.trail.breaks.length === 1 ? "" : "s"}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
        </div>
      </div>
    </SkeletonTheme>
  );
}
