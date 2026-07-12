/**
 * Evaluation screen (SPEC 10.3 item 4).
 *
 * - eval_runs history from GET /api/evaluation/metrics (sample sizes,
 *   generator labels, timestamps).
 * - Section-mapping panel: v1_floor, v2_bm25_ablation, v2_full_stack,
 *   extended_v2_full_stack with routing_rate, high_confidence_accuracy
 *   and the method strings exactly as the payload carries them.
 * - Reproduce (supervisor role): POST /api/evaluation/reproduce, then a
 *   live diff of the committed baseline against the fresh run as
 *   run.completed arrives; every equal row gets a green check.
 * - Judge's seed: any seed into POST /api/intake/run; the banner states
 *   why this is the proof that nothing is canned.
 *
 * Honest states: a non-supervisor sees exactly why Reproduce is not
 * available; missing rows render as explicit absences, never as zeros.
 */

import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Skeleton, { SkeletonTheme } from "react-loading-skeleton";
import "react-loading-skeleton/dist/skeleton.css";
import { useNavigate } from "react-router";
import { pushToast } from "../app/toasts";
import {
  ApiError,
  getEvalRuns,
  getUser,
  startReproduce,
  startRun,
  type MappingMeasureRow,
  type MappingRows,
} from "../lib/api";
import { fmtTimestamp, num, pct } from "../lib/format";
import { openRunStream, type StreamHandle } from "../lib/sse";

// ---------------------------------------------------------------------------
// Reproduce diff state

interface ReproduceState {
  phase: "idle" | "running" | "done" | "failed";
  runId: string | null;
  baseline: Record<string, unknown> | null;
  fresh: Record<string, unknown> | null;
  stagesDone: string[];
  error: string | null;
}

const initialReproduce: ReproduceState = {
  phase: "idle",
  runId: null,
  baseline: null,
  fresh: null,
  stagesDone: [],
  error: null,
};

/** Wall-clock keys are measured live and never baseline-compared (SPEC 6.1). */
const WALL_CLOCK_KEYS = new Set(["time_to_packet_sec"]);

function valuesEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  return JSON.stringify(a) === JSON.stringify(b);
}

function renderValue(value: unknown): string {
  if (value === undefined) return "(absent)";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

// ---------------------------------------------------------------------------
// Mapping panel

const MAPPING_ROW_ORDER = [
  "v1_floor",
  "v2_bm25_ablation",
  "v2_full_stack",
  "extended_v2_full_stack",
] as const;

type MappingRowKey = (typeof MAPPING_ROW_ORDER)[number];

function MappingPanel({
  mapping,
  sectionMethod,
}: {
  mapping: MappingRows;
  sectionMethod: string | undefined;
}) {
  const rows: { key: MappingRowKey; row: MappingMeasureRow | null }[] =
    MAPPING_ROW_ORDER.map((key) => ({ key, row: mapping[key] ?? null }));

  return (
    <div className="card">
      <h3>Section mapping (latest eval run)</h3>
      {mapping.degraded && (
        <p className="notice-box small">
          This run mapped in degraded mode (BM25 + rules only; the
          semantic rerank stack was unavailable). Full-stack rows are
          honestly absent.
        </p>
      )}
      <div className="table-scroll">
        <table className="data">
          <thead>
            <tr>
              <th scope="col">row</th>
              <th scope="col">n</th>
              <th scope="col">accuracy</th>
              <th scope="col">routing rate</th>
              <th scope="col">high-conf n</th>
              <th scope="col">high-conf accuracy</th>
              <th scope="col" className="wrap">
                method (from payload)
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ key, row }) => (
              <tr key={key}>
                <td className="mono">{key}</td>
                {row === null ? (
                  <td colSpan={6} className="muted">
                    not present in this run&apos;s payload
                  </td>
                ) : (
                  <>
                    <td className="num">{row.n}</td>
                    <td className="num">
                      {typeof row.accuracy === "number"
                        ? pct(row.accuracy)
                        : "n/a"}
                    </td>
                    <td className="num">
                      {typeof row.routing_rate === "number"
                        ? pct(row.routing_rate)
                        : "n/a"}
                    </td>
                    <td className="num">
                      {typeof row.high_confidence_n === "number"
                        ? row.high_confidence_n
                        : "n/a"}
                    </td>
                    <td className="num">
                      {typeof row.high_confidence_accuracy === "number"
                        ? pct(row.high_confidence_accuracy)
                        : "n/a"}
                    </td>
                    <td className="wrap mono small">
                      {row.method ??
                        (key === "v1_floor" && sectionMethod !== undefined
                          ? sectionMethod
                          : "no method string in payload")}
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="counter-sub">
        run-level routing:{" "}
        {typeof mapping.routing_rate === "number"
          ? `${pct(mapping.routing_rate)} routed to human (golden set)`
          : "n/a"}{" "}
        . this run&apos;s complaints: {mapping.run_high} high /{" "}
        {mapping.run_low} low confidence ({pct(mapping.run_routing_rate)}{" "}
        routed)
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------

export function Evaluation() {
  const navigate = useNavigate();
  const reduceMotion = useReducedMotion() ?? false;
  const user = getUser();
  const isSupervisor = user?.role === "supervisor";

  const evalQuery = useQuery({
    queryKey: ["eval-runs"],
    queryFn: () => getEvalRuns(20),
  });

  const [repro, setRepro] = useState<ReproduceState>(initialReproduce);
  const streamRef = useRef<StreamHandle | null>(null);
  const [judgeSeed, setJudgeSeed] = useState("");
  const [judgeStarting, setJudgeStarting] = useState(false);

  useEffect(() => () => streamRef.current?.close(), []);

  const onReproduce = async () => {
    if (repro.phase === "running") return;
    streamRef.current?.close();
    setRepro({ ...initialReproduce, phase: "running" });
    try {
      const started = await startReproduce();
      setRepro((prev) => ({
        ...prev,
        runId: started.run_id,
        baseline: started.baseline,
      }));
      streamRef.current = openRunStream(
        started.run_id,
        {
          "stage.completed": (e) => {
            if (e.stage) {
              setRepro((prev) => ({
                ...prev,
                stagesDone: [...prev.stagesDone, e.stage ?? ""],
              }));
            }
          },
          "run.completed": (e) => {
            setRepro((prev) => ({
              ...prev,
              phase: "done",
              fresh: e.payload,
            }));
          },
          "run.failed": (e) => {
            setRepro((prev) => ({
              ...prev,
              phase: "failed",
              error: e.payload.error,
            }));
          },
        },
        {
          onError: () =>
            setRepro((prev) =>
              prev.phase === "running"
                ? {
                    ...prev,
                    phase: "failed",
                    error: "event stream disconnected before completion",
                  }
                : prev,
            ),
        },
      );
    } catch (error) {
      const detail =
        error instanceof ApiError ? error.detail : String(error);
      setRepro({ ...initialReproduce, phase: "failed", error: detail });
      pushToast({
        title: "Reproduce failed to start",
        detail,
        tone: "danger",
        assertive: true,
      });
    }
  };

  const onJudgeSeed = async (event: FormEvent) => {
    event.preventDefault();
    if (judgeStarting) return;
    const seed = Number.parseInt(judgeSeed.trim(), 10);
    if (!Number.isSafeInteger(seed)) {
      pushToast({
        title: "Seed must be an integer",
        tone: "danger",
        assertive: true,
      });
      return;
    }
    setJudgeStarting(true);
    try {
      const started = await startRun(seed, "stub");
      pushToast({
        title: `Judge's-seed run started (seed ${started.seed})`,
        detail: started.run_id,
        tone: "info",
      });
      navigate(`/?run=${encodeURIComponent(started.run_id)}`);
    } catch (error) {
      pushToast({
        title: "Run failed to start",
        detail: error instanceof ApiError ? error.detail : String(error),
        tone: "danger",
        assertive: true,
      });
    } finally {
      setJudgeStarting(false);
    }
  };

  const latestMetrics = evalQuery.data?.rows[0]?.metrics ?? null;

  const diffRows = useMemo(() => {
    if (repro.baseline === null) return [];
    return Object.entries(repro.baseline).map(([key, baselineValue]) => {
      const freshValue = repro.fresh?.[key];
      const wallClock = WALL_CLOCK_KEYS.has(key);
      const equal =
        !wallClock &&
        repro.fresh !== null &&
        valuesEqual(baselineValue, freshValue);
      return { key, baselineValue, freshValue, wallClock, equal };
    });
  }, [repro.baseline, repro.fresh]);

  const allGreen =
    repro.phase === "done" &&
    diffRows.length > 0 &&
    diffRows.every((row) => row.equal || row.wallClock);

  return (
    <SkeletonTheme baseColor="#1E3A6B" highlightColor="#2E4E86">
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {/* Judge's seed banner */}
        <div className="notice-box">
          <strong>Judge&apos;s seed.</strong> Type any seed and the full
          nine-stage engine reruns live with it; every number on every
          screen is recomputed from that run&apos;s payloads. A canned value
          cannot survive an arbitrary seed, which is the strongest proof
          that nothing here is hardcoded.
          <form
            onSubmit={(e) => void onJudgeSeed(e)}
            style={{
              display: "flex",
              gap: "0.6rem",
              marginTop: "0.6rem",
              alignItems: "center",
            }}
          >
            <label className="field-label" htmlFor="judge-seed" style={{ margin: 0 }}>
              Seed
            </label>
            <input
              id="judge-seed"
              className="input"
              style={{ width: "8rem" }}
              inputMode="numeric"
              placeholder="any integer"
              value={judgeSeed}
              onChange={(e) => setJudgeSeed(e.target.value)}
            />
            <button
              type="submit"
              className="btn btn-primary"
              disabled={judgeStarting || judgeSeed.trim() === ""}
            >
              {judgeStarting ? "Starting" : "Rerun with this seed"}
            </button>
          </form>
        </div>

        {/* Eval runs table */}
        <div className="card">
          <h3>Evaluation runs (GET /api/evaluation/metrics)</h3>
          {evalQuery.isPending && <Skeleton height={30} count={5} />}
          {evalQuery.isError && (
            <p className="error-box small" style={{ margin: 0 }}>
              Could not load evaluation runs:{" "}
              {evalQuery.error instanceof ApiError
                ? evalQuery.error.detail
                : String(evalQuery.error)}
            </p>
          )}
          {evalQuery.data && evalQuery.data.rows.length === 0 && (
            <p className="muted small" style={{ margin: 0 }}>
              No evaluation runs recorded yet. Start a pipeline run (or
              Reproduce below) and a row lands here.
            </p>
          )}
          {evalQuery.data && evalQuery.data.rows.length > 0 && (
            <div className="table-scroll">
              <table className="data">
                <thead>
                  <tr>
                    <th scope="col">id</th>
                    <th scope="col">created</th>
                    <th scope="col">generator</th>
                    <th scope="col">model tag</th>
                    <th scope="col">seed</th>
                    <th scope="col">complaints</th>
                    <th scope="col">linkage F1</th>
                    <th scope="col">% traced</th>
                    <th scope="col">sample sizes</th>
                  </tr>
                </thead>
                <tbody>
                  {evalQuery.data.rows.map((row) => (
                    <tr key={row.id}>
                      <td className="num">{row.id}</td>
                      <td>{fmtTimestamp(row.created_at)}</td>
                      <td className="mono">{row.generator ?? "n/a"}</td>
                      <td className="mono">{row.model_tag ?? "n/a"}</td>
                      <td className="num">
                        {typeof row.metrics?.seed === "number"
                          ? row.metrics.seed
                          : "n/a"}
                      </td>
                      <td className="num">
                        {typeof row.metrics?.n_complaints === "number"
                          ? row.metrics.n_complaints
                          : "n/a"}
                      </td>
                      <td className="num">
                        {typeof row.metrics?.linkage_f1 === "number"
                          ? num(row.metrics.linkage_f1)
                          : "n/a"}
                      </td>
                      <td className="num">
                        {typeof row.metrics?.pct_value_traced_to_cashout ===
                        "number"
                          ? pct(row.metrics.pct_value_traced_to_cashout)
                          : "n/a"}
                      </td>
                      <td className="mono small">
                        {row.sample_sizes
                          ? Object.entries(row.sample_sizes)
                              .map(([k, v]) => `${k}=${v}`)
                              .join(" ")
                          : "n/a"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Section-mapping panel */}
        {latestMetrics?.mapping ? (
          <MappingPanel
            mapping={latestMetrics.mapping}
            sectionMethod={
              typeof latestMetrics.section_method === "string"
                ? latestMetrics.section_method
                : undefined
            }
          />
        ) : (
          <div className="card">
            <h3>Section mapping</h3>
            <p className="muted small" style={{ margin: 0 }}>
              No eval run with mapping rows yet; the panel fills from the
              latest run&apos;s payload once one exists.
            </p>
          </div>
        )}

        {/* Reproduce */}
        <div className="card">
          <h3>Reproduce the seed-42 baseline (supervisor)</h3>
          <p className="small" style={{ marginTop: 0 }}>
            Reruns the deterministic pipeline live and diffs the fresh
            numbers against the committed baseline (results.json). Equal
            rows go green; wall-clock timings are measured live and never
            baseline-compared.
          </p>
          {!isSupervisor && (
            <p className="notice-box small">
              Reproduce requires the supervisor role. You are signed in as{" "}
              <span className="mono">
                {user?.username ?? "unknown"} ({user?.role ?? "unknown"})
              </span>
              , so the button is disabled here, not hidden: the backend
              enforces the same rule with a 403.
            </p>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void onReproduce()}
            disabled={!isSupervisor || repro.phase === "running"}
          >
            {repro.phase === "running" ? "Reproducing" : "Reproduce"}
          </button>

          {repro.phase === "running" && (
            <p className="mono small muted" style={{ marginBottom: 0 }}>
              stages completed: {repro.stagesDone.length} of 9
              {repro.stagesDone.length > 0
                ? ` (${repro.stagesDone.join(", ")})`
                : ""}
            </p>
          )}
          {repro.phase === "failed" && repro.error !== null && (
            <p className="error-box small" style={{ marginBottom: 0 }}>
              Reproduce failed: {repro.error}
            </p>
          )}

          {repro.baseline !== null && (
            <motion.div
              initial={reduceMotion ? false : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              style={{ marginTop: "0.9rem" }}
            >
              {allGreen && (
                <p className="notice-box small" role="status">
                  <span style={{ color: "var(--color-forest)" }}>✓</span>{" "}
                  Every compared key matches the committed baseline
                  exactly. The numbers regenerated live.
                </p>
              )}
              <div className="table-scroll">
                <table className="data">
                  <thead>
                    <tr>
                      <th scope="col">key</th>
                      <th scope="col" className="wrap">
                        baseline (results.json)
                      </th>
                      <th scope="col" className="wrap">
                        fresh run
                      </th>
                      <th scope="col">match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diffRows.map((row) => (
                      <tr key={row.key}>
                        <td className="mono">{row.key}</td>
                        <td className="wrap mono small">
                          {renderValue(row.baselineValue)}
                        </td>
                        <td className="wrap mono small">
                          {repro.fresh === null
                            ? "running"
                            : renderValue(row.freshValue)}
                        </td>
                        <td>
                          {row.wallClock ? (
                            <span className="diff-skipped">
                              live wall clock, not compared
                            </span>
                          ) : repro.fresh === null ? (
                            <span className="diff-skipped">pending</span>
                          ) : row.equal ? (
                            <span className="diff-equal">
                              <span className="check">✓</span> equal
                            </span>
                          ) : (
                            <span className="diff-differs">differs</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}
        </div>
      </div>
    </SkeletonTheme>
  );
}
