/**
 * Demo mode, the guided single-screen run of the whole story (SPEC 14).
 *
 * A big Start button launches POST /api/demo/start, which runs the REAL
 * seed-42 stub pipeline and a paced five-beat narrator over it. This
 * screen subscribes to both channels:
 *
 *  - the run stream (/api/stream/run/{run_id}) carries the pipeline's own
 *    real events: the graph collapsing, metric.updated counters, the
 *    money trail, f9.claim verdicts, custody.appended records, and the
 *    nine stage.started / stage.completed pairs;
 *  - the demo stream (/api/stream/demo/{demo_id}) carries the beats, each
 *    quoting figures produced by that same run.
 *
 * Controls: "Plant a fabrication" pushes one labelled known-bad claim
 * through the live F9 gate (blocked, oxblood flash, assertive announce);
 * "Reproduce results" jumps to Evaluation; "Judge's seed" reruns the full
 * engine with any seed so every number on Discovery moves with it.
 *
 * Truth rule 1: every number here arrives in an SSE or REST payload.
 * Pacing changes WHEN a real fact paints, never WHAT it says.
 */

import { useReducedMotion } from "motion/react";
import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import CountUp from "react-countup";
import { useNavigate } from "react-router";
import { pushToast } from "../app/toasts";
import { ApiError, getUser, startRun, subscribeAuth } from "../lib/api";
import { inr, pct, shortHash } from "../lib/format";
import { recordRecentRun } from "../lib/recentRuns";
import {
  openDemoStream,
  openRunStream,
  type DemoCustodyBeat,
  type DemoF9Beat,
  type DemoLinkRejected,
  type DemoPlanted,
  type DemoTrailBeat,
  type RunEventMap,
  type SseEnvelope,
  type StreamHandle,
} from "../lib/sse";
import {
  DemoGraph,
  type DemoGLink,
  type DemoGNode,
} from "../components/demo/DemoGraph";
import { plantFabrication, startDemo } from "../components/demo/demoApi";

// ---------------------------------------------------------------------------
// Run-side state (counters, stages, honest labels)

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

interface CustodyRecord {
  artefact: string;
  hash: string;
}

interface RunState {
  metrics: Record<string, number | string | boolean>;
  stages: Record<string, StageStatus>;
  stagesStarted: number;
  linkage: Record<string, unknown> | null;
  money: Record<string, unknown> | null;
  networksDiscovered: number;
  custody: CustodyRecord[];
  results: Record<string, unknown> | null;
  runCompleted: boolean;
}

const initialRunState: RunState = {
  metrics: {},
  stages: {},
  stagesStarted: 0,
  linkage: null,
  money: null,
  networksDiscovered: 0,
  custody: [],
  results: null,
  runCompleted: false,
};

type RunAction =
  | { type: "reset" }
  | { type: "stage.started"; stage: string }
  | { type: "stage.completed"; stage: string; metrics: Record<string, unknown> }
  | { type: "metric.updated"; key: string; value: number | string | boolean }
  | { type: "network.discovered" }
  | { type: "custody.appended"; record: CustodyRecord }
  | { type: "run.completed"; results: Record<string, unknown> };

function runReducer(state: RunState, action: RunAction): RunState {
  switch (action.type) {
    case "reset":
      return { ...initialRunState };
    case "stage.started":
      return {
        ...state,
        stages: { ...state.stages, [action.stage]: "running" },
        stagesStarted: state.stagesStarted + 1,
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
    case "custody.appended":
      return { ...state, custody: [...state.custody, action.record] };
    case "run.completed":
      return { ...state, runCompleted: true, results: action.results };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Demo-beat state

interface BeatMeta {
  index: number;
  key: string;
  title: string;
  window: string;
  detail: string;
}
interface BeatData {
  active: boolean;
  linkRejected?: DemoLinkRejected;
  trail?: DemoTrailBeat;
  planted?: DemoPlanted;
  f9?: DemoF9Beat;
  custody?: DemoCustodyBeat;
}

type GraphEvent =
  | { kind: "node"; id: number }
  | { kind: "edge"; a: number; b: number; w: number }
  | { kind: "network"; index: number; members: number[] };

// ---------------------------------------------------------------------------

export function Demo() {
  const navigate = useNavigate();
  const reduceMotion = useReducedMotion() ?? false;
  const user = useSyncExternalStore(subscribeAuth, getUser);
  const isSupervisor = user?.role === "supervisor";

  const [runState, dispatch] = useReducer(runReducer, initialRunState);
  const [demoId, setDemoId] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [demoStatus, setDemoStatus] = useState<
    "idle" | "starting" | "running" | "completed" | "failed"
  >("idle");
  const [demoError, setDemoError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [beatsMeta, setBeatsMeta] = useState<BeatMeta[]>([]);
  const [beats, setBeats] = useState<Record<number, BeatData>>({});
  const [activeBeat, setActiveBeat] = useState(0);

  // Manual "Plant a fabrication" control result + a flash key to retrigger
  // the oxblood animation on each new block.
  const [manualPlanted, setManualPlanted] = useState<DemoPlanted | null>(null);
  const [planting, setPlanting] = useState(false);
  const [flashKey, setFlashKey] = useState(0);
  const [judgeSeed, setJudgeSeed] = useState("7");
  const [seedStarting, setSeedStarting] = useState(false);

  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine,
  );
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);

  // Graph data (paced drainer, same model as Discovery).
  const nodesRef = useRef<DemoGNode[]>([]);
  const linksRef = useRef<DemoGLink[]>([]);
  const nodeIndexRef = useRef<Map<number, DemoGNode>>(new Map());
  const queueRef = useRef<GraphEvent[]>([]);
  const [graphData, setGraphData] = useState<{
    nodes: DemoGNode[];
    links: DemoGLink[];
  }>({ nodes: [], links: [] });

  const resetGraph = useCallback(() => {
    nodesRef.current = [];
    linksRef.current = [];
    nodeIndexRef.current = new Map();
    queueRef.current = [];
    setGraphData({ nodes: [], links: [] });
  }, []);

  const applyGraphEvent = useCallback((event: GraphEvent) => {
    if (event.kind === "node") {
      if (nodeIndexRef.current.has(event.id)) return;
      const node: DemoGNode = { id: event.id, community: null };
      nodeIndexRef.current.set(event.id, node);
      nodesRef.current.push(node);
    } else if (event.kind === "edge") {
      linksRef.current.push({ source: event.a, target: event.b, w: event.w });
    } else {
      for (const member of event.members) {
        const node = nodeIndexRef.current.get(member);
        if (node) node.community = event.index;
      }
    }
  }, []);

  // Paced drainer: applies queued graph events at a bounded rate so the
  // collapse is visible; reduced motion applies everything at once.
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
      for (let i = 0; i < discovered; i++) dispatch({ type: "network.discovered" });
      setGraphData({ nodes: [...nodesRef.current], links: [...linksRef.current] });
    }, 25);
    return () => clearInterval(interval);
  }, [applyGraphEvent, reduceMotion]);

  // Run-stream subscription (real pipeline events).
  useEffect(() => {
    if (runId === null) return;
    const on = <K extends keyof RunEventMap>(
      handler: (e: SseEnvelope<RunEventMap[K]>) => void,
    ) => handler;

    const handle: StreamHandle = openRunStream(runId, {
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
      "custody.appended": on<"custody.appended">((e) => {
        const rec = e.payload.rec as unknown;
        let artefact = "record";
        if (typeof rec === "string") artefact = rec;
        else if (rec && typeof rec === "object" && "artefact" in rec) {
          artefact = String((rec as { artefact: unknown }).artefact);
        }
        dispatch({
          type: "custody.appended",
          record: { artefact, hash: e.payload.hash },
        });
      }),
      "run.completed": on<"run.completed">((e) =>
        dispatch({
          type: "run.completed",
          results: e.payload as Record<string, unknown>,
        }),
      ),
    });
    return () => handle.close();
  }, [runId]);

  // Demo-stream subscription (paced beats).
  useEffect(() => {
    if (demoId === null) return;
    const handle: StreamHandle = openDemoStream(
      demoId,
      {
        "demo.started": (e) => {
          setBeatsMeta(e.payload.beats);
        },
        "demo.beat": (e) => {
          const p = e.payload;
          setActiveBeat((n) => Math.max(n, p.index));
          setBeats((prev) => ({
            ...prev,
            [p.index]: {
              active: true,
              linkRejected: p.link_rejected,
              trail: p.trail,
              planted: p.planted,
              f9: p.f9,
              custody: p.custody,
            },
          }));
          if (p.key === "packet_f9" && p.planted?.blocked) {
            setFlashKey((k) => k + 1);
            pushToast({
              title: "F9 gate blocked the planted fabrication",
              detail: `${p.planted.section} . ${p.planted.verdict} . corpus ${p.planted.corpus_version}`,
              tone: "danger",
              assertive: true,
            });
          }
        },
        "demo.completed": (e) => {
          setDemoStatus("completed");
          setElapsed(e.payload.elapsed_sec);
        },
        "demo.failed": (e) => {
          setDemoStatus("failed");
          setDemoError(e.payload.error);
        },
      },
      {
        onError: () =>
          setDemoError((prev) => prev ?? "demo beat stream disconnected"),
      },
    );
    return () => handle.close();
  }, [demoId]);

  const onStart = async () => {
    if (demoStatus === "starting" || demoStatus === "running") return;
    setDemoStatus("starting");
    setDemoError(null);
    setElapsed(null);
    setBeats({});
    setBeatsMeta([]);
    setActiveBeat(0);
    setManualPlanted(null);
    dispatch({ type: "reset" });
    resetGraph();
    try {
      const started = await startDemo();
      setDemoId(started.demo_id);
      setRunId(started.run_id);
      setDemoStatus("running");
      recordRecentRun({
        run_id: started.run_id,
        seed: started.seed,
        generator: started.generator,
        started_at: new Date().toISOString(),
      });
    } catch (error) {
      setDemoStatus("failed");
      setDemoError(error instanceof ApiError ? error.detail : String(error));
      pushToast({
        title: "Demo failed to start",
        detail: error instanceof ApiError ? error.detail : String(error),
        tone: "danger",
        assertive: true,
      });
    }
  };

  const onPlant = async () => {
    if (planting) return;
    setPlanting(true);
    try {
      const verdict = await plantFabrication();
      setManualPlanted(verdict);
      setFlashKey((k) => k + 1);
      pushToast({
        title: verdict.blocked
          ? "Planted fabrication blocked by the F9 gate"
          : "Planted fabrication PASSED (investigate: gate did not withhold)",
        detail: `${verdict.section} . ${verdict.verdict} . ${verdict.generator_name}`,
        tone: verdict.blocked ? "success" : "danger",
        assertive: true,
      });
    } catch (error) {
      pushToast({
        title: "Plant a fabrication failed",
        detail: error instanceof ApiError ? error.detail : String(error),
        tone: "danger",
        assertive: true,
      });
    } finally {
      setPlanting(false);
    }
  };

  const onJudgeSeed = async () => {
    if (seedStarting) return;
    const seed = Number.parseInt(judgeSeed.trim(), 10);
    if (!Number.isSafeInteger(seed)) {
      pushToast({ title: "Seed must be an integer", tone: "danger", assertive: true });
      return;
    }
    setSeedStarting(true);
    try {
      const started = await startRun(seed, "stub");
      recordRecentRun({
        run_id: started.run_id,
        seed: started.seed,
        generator: started.generator,
        started_at: new Date().toISOString(),
      });
      pushToast({
        title: `Judge's seed ${started.seed}: full engine rerun started`,
        detail: "Opening Discovery; every number moves with the seed.",
        tone: "info",
      });
      navigate(`/?run=${encodeURIComponent(started.run_id)}`);
    } catch (error) {
      pushToast({
        title: "Judge's-seed run failed to start",
        detail: error instanceof ApiError ? error.detail : String(error),
        tone: "danger",
        assertive: true,
      });
    } finally {
      setSeedStarting(false);
    }
  };

  // Honest labels derived from the completed run's real results.
  const results = runState.results;
  const generatorName =
    (results?.["generator_name"] as string | undefined) ?? "deterministic-stub";
  const isStub = results?.["f9_is_stub"] as boolean | undefined;
  const semanticUnavailable = results?.["semantic_unavailable"] as
    | boolean
    | undefined;
  const mappingDegraded = results?.["mapping_degraded"] as boolean | undefined;

  const complaints = runState.metrics["n_complaints"];
  const rupees = runState.money?.["total_amt"];
  const traced = runState.money?.["traced_amt"];
  const pctTraced = runState.metrics["pct_value_traced_to_cashout"];
  const linkageF1 = runState.linkage?.["f1"];

  const beat4 = beats[4];
  const shownPlanted = manualPlanted ?? beat4?.planted ?? null;

  const running = demoStatus === "running" || demoStatus === "starting";
  const started = demoId !== null;

  return (
    <div className="demo-screen">
      {/* Header: what this is, honest posture, controls */}
      <div className="card demo-hero">
        <div className="demo-hero-copy">
          <h3 style={{ marginTop: 0 }}>Guided demo (SPEC 14)</h3>
          <p className="muted small" style={{ margin: "0 0 0.6rem" }}>
            One Start button runs the real seed-42 pipeline and paces the
            five-beat story over it: intake, the graph collapsing into
            networks, the money trail, the Section 63 packet with a planted
            fabrication blocked by F9, and the custody tamper test. Every
            number below arrives from the engine over SSE or REST; nothing
            on this screen is canned.
          </p>
          <div className="demo-badges" aria-label="Run posture">
            <span className="demo-badge on-prem">on-premise . zero-egress</span>
            <span className={`demo-badge ${online ? "wan" : "offline"}`}>
              {online ? "WAN reachable (not used)" : "offline"}
            </span>
            <span className="demo-badge">
              generator: <strong>{generatorName}</strong>
            </span>
            {isStub !== undefined && (
              <span className="demo-badge">
                {isStub ? "deterministic stub (labelled)" : "live model"}
              </span>
            )}
            {(semanticUnavailable || mappingDegraded) && (
              <span className="demo-badge degraded">
                InLegalBERT rerank unavailable . BM25 + rules (labelled)
              </span>
            )}
          </div>
        </div>
        <div className="demo-hero-actions">
          {isSupervisor ? (
            <button
              type="button"
              className="btn btn-primary demo-start"
              data-testid="demo-start"
              onClick={() => void onStart()}
              disabled={running}
            >
              {demoStatus === "starting"
                ? "Starting"
                : demoStatus === "running"
                  ? "Running"
                  : demoStatus === "completed"
                    ? "Run demo again"
                    : "Start demo"}
            </button>
          ) : (
            <p className="notice-box small" style={{ margin: 0 }}>
              Starting the demo needs the supervisor role; you are signed in
              as {user?.username ?? "unknown"} ({user?.role ?? "unknown"}).
            </p>
          )}
          <div
            className="demo-status mono small"
            data-testid="demo-status"
            data-status={demoStatus}
            aria-live="polite"
          >
            status {demoStatus}
            {elapsed !== null && ` . completed in ${elapsed.toFixed(1)} s`}
          </div>
          {demoError !== null && (
            <p className="error-box small" role="alert" style={{ margin: 0 }}>
              {demoError}
            </p>
          )}
        </div>
      </div>

      {/* Live counters (every value from a run payload) */}
      <div className="counter-row" aria-live="polite">
        <div className="card">
          <p className="counter-label">Complaints ingested</p>
          <p className="counter-value">
            {typeof complaints === "number" ? (
              <CountUp end={complaints} duration={reduceMotion ? 0 : 1.2} separator="," preserveValue />
            ) : (
              <span className="muted">{running ? "…" : "no run yet"}</span>
            )}
          </p>
          <p className="counter-sub">metric: n_complaints</p>
        </div>
        <div className="card">
          <p className="counter-label">Networks found</p>
          <p className="counter-value">
            {started ? (
              <CountUp end={runState.networksDiscovered} duration={reduceMotion ? 0 : 0.5} preserveValue />
            ) : (
              <span className="muted">no run yet</span>
            )}
          </p>
          <p className="counter-sub">network.discovered events</p>
        </div>
        <div className="card">
          <p className="counter-label">Rupees at risk</p>
          <p className="counter-value">
            {typeof rupees === "number" ? (
              <CountUp end={rupees} duration={reduceMotion ? 0 : 1.2} preserveValue formattingFn={inr} />
            ) : (
              <span className="muted">{running ? "awaiting money trail" : "no run yet"}</span>
            )}
          </p>
          <p className="counter-sub">
            {typeof traced === "number" && typeof pctTraced === "number"
              ? `${inr(traced)} traced (${pct(pctTraced)})`
              : "money_trail stage totals"}
          </p>
        </div>
        <div className="card">
          <p className="counter-label">Linkage F1</p>
          <p className="counter-value">
            {typeof linkageF1 === "number" ? (
              <CountUp end={linkageF1} decimals={3} duration={reduceMotion ? 0 : 1} preserveValue />
            ) : (
              <span className="muted">{running ? "awaiting linkage" : "no run yet"}</span>
            )}
          </p>
          <p className="counter-sub">linkage stage.completed</p>
        </div>
      </div>

      {/* Stage rail (nine stages) */}
      {started && (
        <div className="stage-rail" aria-label="Pipeline stages">
          {STAGES.map((stage: StageName) => {
            const status = runState.stages[stage] ?? "pending";
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

      <div className="demo-grid">
        {/* Graph + beat timeline */}
        <div className="demo-main">
          <DemoGraph
            nodes={graphData.nodes}
            links={graphData.links}
            reduceMotion={reduceMotion}
            streaming={queueRef.current.length > 0}
          />

          <ol className="demo-beats" aria-label="Demo beats">
            {beatsMeta.map((meta) => {
              const data = beats[meta.index];
              const isActive = activeBeat >= meta.index;
              const isCurrent = activeBeat === meta.index && demoStatus === "running";
              return (
                <li
                  key={meta.index}
                  data-testid={`beat-${meta.index}`}
                  data-active={isActive ? "true" : "false"}
                  className={`demo-beat card ${isActive ? "active" : "pending"} ${isCurrent ? "current" : ""}`}
                >
                  <div className="demo-beat-head">
                    <span className="demo-beat-index mono">{meta.index}</span>
                    <span>
                      <strong>{meta.title}</strong>
                      <span className="muted small"> . {meta.window}</span>
                    </span>
                    <span className={`stage-pill ${isActive ? "done" : ""}`}>
                      {isActive ? "reached" : "pending"}
                    </span>
                  </div>
                  <p className="muted small" style={{ margin: "0.3rem 0 0" }}>
                    {meta.detail}
                  </p>

                  {/* Beat 2: the real audited link rejection */}
                  {meta.key === "collapse" && data?.linkRejected && (
                    <div className="demo-beat-body">
                      {data.linkRejected.ok ? (
                        <p className="mono small">
                          rejected link {data.linkRejected.a} to{" "}
                          {data.linkRejected.b} (w {data.linkRejected.w}) .
                          appended {data.linkRejected.action} at seq{" "}
                          {data.linkRejected.seq} .{" "}
                          {data.linkRejected.hash
                            ? shortHash(data.linkRejected.hash)
                            : ""}
                        </p>
                      ) : (
                        <p className="muted small">
                          link rejection not appended: {data.linkRejected.reason}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Beat 3: money trail */}
                  {meta.key === "money_trail" && data?.trail && (
                    <div className="demo-beat-body">
                      <p className="mono small">
                        {typeof data.trail.pct_traced === "number"
                          ? `${pct(data.trail.pct_traced)} of value traced to cash-out`
                          : "trail measured"}
                        {data.trail.method ? ` . ${data.trail.method}` : ""}
                      </p>
                    </div>
                  )}

                  {/* Beat 4: packet + F9 planted fabrication */}
                  {meta.key === "packet_f9" && (
                    <PlantedBlock
                      f9={data?.f9}
                      planted={shownPlanted}
                      flashKey={flashKey}
                      reduceMotion={reduceMotion}
                    />
                  )}

                  {/* Beat 5: custody tamper */}
                  {meta.key === "custody" && data?.custody && (
                    <CustodyBlock
                      custody={data.custody}
                      records={runState.custody}
                    />
                  )}
                </li>
              );
            })}
            {beatsMeta.length === 0 && !started && (
              <li className="demo-beat card pending">
                <p className="muted small" style={{ margin: 0 }}>
                  Press Start to run the five-beat story. The beats appear
                  here as the narrator paces the real run.
                </p>
              </li>
            )}
          </ol>
        </div>

        {/* Controls */}
        <aside className="demo-controls">
          <div className="card">
            <h3>Controls</h3>
            <p className="muted small" style={{ marginTop: 0 }}>
              Re-run any part of the proof live.
            </p>
            <div className="demo-control-stack">
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => void onPlant()}
                disabled={!isSupervisor || planting}
              >
                {planting ? "Planting" : "Plant a fabrication"}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => navigate("/evaluation")}
              >
                Reproduce results
              </button>
              <div className="demo-seed">
                <label className="field-label" htmlFor="judge-seed">
                  Judge's seed
                </label>
                <div style={{ display: "flex", gap: "0.4rem" }}>
                  <input
                    id="judge-seed"
                    className="input"
                    style={{ width: "5.5rem" }}
                    inputMode="numeric"
                    value={judgeSeed}
                    onChange={(e) => setJudgeSeed(e.target.value)}
                  />
                  <button
                    type="button"
                    className="btn"
                    onClick={() => void onJudgeSeed()}
                    disabled={seedStarting}
                  >
                    {seedStarting ? "Starting" : "Rerun"}
                  </button>
                </div>
                <p className="counter-sub" style={{ marginBottom: 0 }}>
                  Reruns the full engine with any seed; opens Discovery so
                  every number moves with it. The strongest proof nothing is
                  canned.
                </p>
              </div>
            </div>
          </div>

          {/* Manual plant result, always with its gate label */}
          {manualPlanted && (
            <div className="card" aria-live="assertive">
              <h3>Manual plant verdict</h3>
              <PlantedVerdictCard planted={manualPlanted} flashKey={flashKey} reduceMotion={reduceMotion} />
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Beat 4 content: the F9 tallies plus the planted fabrication, blocked.

function PlantedBlock({
  f9,
  planted,
  flashKey,
  reduceMotion,
}: {
  f9: DemoF9Beat | undefined;
  planted: DemoPlanted | null;
  flashKey: number;
  reduceMotion: boolean;
}) {
  return (
    <div className="demo-beat-body">
      {f9 && (
        <p className="mono small f9-generator-line">
          run gate: generator <strong>{f9.generator_name}</strong> . corpus{" "}
          {f9.corpus_version} . claims {f9.claims} . passed {f9.passed} .{" "}
          <span className="f9-withheld">withheld {f9.withheld}</span> . leaked{" "}
          {f9.leaked}
        </p>
      )}
      {planted ? (
        <div aria-live="assertive">
          <PlantedVerdictCard planted={planted} flashKey={flashKey} reduceMotion={reduceMotion} />
        </div>
      ) : (
        <p className="muted small" style={{ margin: 0 }}>
          The planted fabrication is pushed through the same gate here.
        </p>
      )}
    </div>
  );
}

function PlantedVerdictCard({
  planted,
  flashKey,
  reduceMotion,
}: {
  planted: DemoPlanted;
  flashKey: number;
  reduceMotion: boolean;
}) {
  return (
    <div
      key={reduceMotion ? undefined : flashKey}
      data-testid={planted.blocked ? "planted-blocked" : "planted-leaked"}
      className={`planted-card ${planted.blocked ? "blocked" : "leaked"} ${reduceMotion ? "" : "flash"}`}
    >
      <div className="planted-head">
        <span className={`verdict-chip ${planted.blocked ? "withheld" : "passed"}`}>
          {planted.verdict}
        </span>
        <span className="mono small">{planted.section}</span>
        <span className="conf-chip low">{planted.label}</span>
        {planted.sub_class && (
          <span className="conf-chip low">{planted.sub_class}</span>
        )}
      </div>
      <p className="small verdict-quote" style={{ margin: "0.35rem 0" }}>
        "{planted.quote}"
      </p>
      <p className="mono small muted" style={{ margin: 0 }}>
        {planted.blocked
          ? `blocked live by the F9 gate (${planted.gate_rule})`
          : "PASSED the gate (unexpected; investigate)"}{" "}
        . corpus {planted.corpus_version} . generator {planted.generator_name}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Beat 5 content: the engine custody chain with the tamper break.

function CustodyBlock({
  custody,
  records,
}: {
  custody: DemoCustodyBeat;
  records: CustodyRecord[];
}) {
  return (
    <div className="demo-beat-body" aria-live="assertive">
      <p className="mono small" style={{ margin: "0 0 0.4rem" }}>
        chain length {custody.chain_len} .{" "}
        {custody.chain_verified ? "verified from genesis" : "verification failed"}
      </p>
      <div className="demo-chain">
        {records.map((rec, index) => {
          const corrupted = rec.artefact === custody.corrupted_record;
          return (
            <span
              key={`${rec.artefact}-${index}`}
              className={`demo-chain-node ${corrupted ? "corrupted" : ""}`}
              title={`${rec.artefact} . ${shortHash(rec.hash)}`}
            >
              {rec.artefact}
            </span>
          );
        })}
      </div>
      <p
        data-testid="tamper-result"
        data-broke={custody.tamper_broke_chain ? "true" : "false"}
        className={custody.tamper_broke_chain ? "error-box small" : "muted small"}
        style={{ margin: "0.5rem 0 0" }}
      >
        {custody.tamper_broke_chain
          ? `Tamper test broke the scratch chain at ${custody.corrupted_record} (record ${custody.corrupted_index}); its hash no longer recomputes. The real chain is untouched.`
          : "Tamper test did not break the chain (unexpected; investigate)."}
      </p>
    </div>
  );
}
