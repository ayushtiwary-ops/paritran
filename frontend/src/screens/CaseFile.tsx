/**
 * Case File, hero screen 2 (SPEC 10.3).
 *
 * Run selection: ?run= query param, or a picker over the recent runs
 * Discovery records in sessionStorage; with neither, an honest empty
 * state links back to Discovery. Sections:
 * (a) money trail: animated SVG victim -> mule layers -> cash-out from
 *     GET /api/networks/{idx} trail hops, breaks in oxblood as freeze
 *     points, run-wide traced percentage counting up;
 * (b) mapped sections: packet quotes + per-complaint mapping.section
 *     events replayed from the stored run stream;
 * (c) the Section 63 packet as an assembling document (print styles in
 *     app.css);
 * (d) the F9 audit panel over POST /api/cases/{run_id}/claims.
 *
 * Truth rule 1: every number on this screen arrives in a REST or SSE
 * payload; motion only changes when values paint, never what they say.
 */

import { useQuery } from "@tanstack/react-query";
import { useReducedMotion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import Skeleton, { SkeletonTheme } from "react-loading-skeleton";
import "react-loading-skeleton/dist/skeleton.css";
import { Link, useSearchParams } from "react-router";
import {
  ApiError,
  getNetworks,
  getRun,
  type NetworkSummary,
} from "../lib/api";
import { listRecentRuns } from "../lib/recentRuns";
import { openRunStream, type StreamHandle } from "../lib/sse";
import { getNetworkDetail, getPacket } from "../components/casefile/caseApi";
import { F9Panel } from "../components/casefile/F9Panel";
import {
  MappedSections,
  type MappingSectionEvent,
} from "../components/casefile/MappedSections";
import { MoneyTrail } from "../components/casefile/MoneyTrail";
import { PacketView } from "../components/casefile/PacketView";

/** Retry through the short 409 window between run.completed and the
 *  run registry flipping to completed (same pattern as Discovery). */
const retry409 = (failureCount: number, error: unknown) =>
  error instanceof ApiError && error.status === 409 && failureCount < 30;

export function CaseFile() {
  const [searchParams, setSearchParams] = useSearchParams();
  const runId = searchParams.get("run");
  const reduceMotion = useReducedMotion() ?? false;
  const recentRuns = useMemo(listRecentRuns, []);
  const [networkIdx, setNetworkIdx] = useState(0);

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId ?? ""),
    enabled: runId !== null,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 1500 : false,
  });
  const runStatus = runQuery.data?.status ?? null;
  const completed = runStatus === "completed";

  const networksQuery = useQuery({
    queryKey: ["networks", runId],
    queryFn: () => getNetworks(runId ?? ""),
    enabled: runId !== null && completed,
    staleTime: Number.POSITIVE_INFINITY,
    retry: retry409,
    retryDelay: 700,
  });

  const networkQuery = useQuery({
    queryKey: ["network", runId, networkIdx],
    queryFn: () => getNetworkDetail(runId ?? "", networkIdx),
    enabled: runId !== null && completed,
    staleTime: Number.POSITIVE_INFINITY,
    retry: retry409,
    retryDelay: 700,
  });

  const packetQuery = useQuery({
    queryKey: ["packet", runId],
    queryFn: () => getPacket(runId ?? ""),
    enabled: runId !== null && completed,
    staleTime: Number.POSITIVE_INFINITY,
    retry: retry409,
    retryDelay: 700,
  });

  // Per-complaint mapping rows: the stored run stream replays every
  // event for a completed run, so one subscription collects the
  // engine's mapping.section emissions and closes on run.completed.
  const [mappings, setMappings] = useState<MappingSectionEvent[] | null>(null);
  const [mappingStreamError, setMappingStreamError] = useState(false);
  const mappingBuffer = useRef<MappingSectionEvent[]>([]);

  useEffect(() => {
    if (runId === null || !completed) return;
    setMappings(null);
    setMappingStreamError(false);
    mappingBuffer.current = [];
    const handle: StreamHandle = openRunStream(
      runId,
      {
        "mapping.section": (envelope) => {
          mappingBuffer.current.push(envelope.payload);
        },
        "run.completed": () => {
          setMappings([...mappingBuffer.current]);
        },
      },
      { onError: () => setMappingStreamError(true) },
    );
    return () => handle.close();
  }, [runId, completed]);

  // ------------------------------------------------------------------ empty
  if (runId === null) {
    return (
      <div className="card" style={{ maxWidth: "40rem" }}>
        <h3>No run selected</h3>
        {recentRuns.length > 0 ? (
          <div>
            <p className="small" style={{ marginTop: 0 }}>
              Pick one of this tab's recent runs, or start a fresh one in{" "}
              <Link to="/">Discovery</Link>.
            </p>
            <ul className="strong-links">
              {recentRuns.map((run) => (
                <li key={run.run_id}>
                  <button
                    type="button"
                    className="btn small"
                    onClick={() => setSearchParams({ run: run.run_id })}
                  >
                    seed {run.seed} . {run.generator}
                    <span className="muted"> . {run.run_id}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="notice-box" style={{ marginBottom: 0 }}>
            The case file renders a completed run's live engine output
            and nothing else. Start a run in{" "}
            <Link to="/">Discovery</Link>, then come back (or open this
            screen with ?run=&lt;run id&gt;).
          </p>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------- states
  if (runQuery.isError) {
    return (
      <div className="error-box" role="alert">
        Could not load run {runId}:{" "}
        {runQuery.error instanceof ApiError
          ? runQuery.error.detail
          : String(runQuery.error)}
        {". "}
        <Link to="/">Start a run in Discovery</Link> (run ids live only as
        long as the API process).
      </div>
    );
  }

  if (runQuery.isPending) {
    return (
      <SkeletonTheme baseColor="#1E3A6B" highlightColor="#2E4E86">
        <div aria-label="Loading run">
          <Skeleton height={110} count={3} style={{ marginBottom: 12 }} />
        </div>
      </SkeletonTheme>
    );
  }

  if (runStatus === "failed") {
    return (
      <div className="error-box" role="alert">
        Run {runId} failed
        {runQuery.data.error !== null ? `: ${runQuery.data.error}` : ""}. No
        case file exists for a failed run.{" "}
        <Link to="/">Start a new run in Discovery.</Link>
      </div>
    );
  }

  if (!completed) {
    return (
      <div className="card" style={{ maxWidth: "40rem" }}>
        <h3>Run in progress</h3>
        <p className="small" style={{ marginTop: 0 }}>
          Run {runId} is {runStatus ?? "starting"}. The case file
          assembles once the pipeline completes; watch it live in{" "}
          <Link to={`/?run=${encodeURIComponent(runId)}`}>Discovery</Link>.
        </p>
        <SkeletonTheme baseColor="#1E3A6B" highlightColor="#2E4E86">
          <Skeleton height={56} count={2} style={{ marginBottom: 8 }} />
        </SkeletonTheme>
      </div>
    );
  }

  const results = runQuery.data.results;
  const pctTracedRun =
    typeof results?.pct_value_traced_to_cashout === "number"
      ? results.pct_value_traced_to_cashout
      : null;
  const networks: NetworkSummary[] = networksQuery.data?.networks ?? [];
  const network = networkQuery.data ?? null;

  return (
    <SkeletonTheme baseColor="#1E3A6B" highlightColor="#2E4E86">
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {/* Run + network selectors */}
        <div className="card casefile-controls">
          <div>
            <label className="field-label" htmlFor="casefile-run">
              Run
            </label>
            <select
              id="casefile-run"
              className="select"
              value={runId}
              onChange={(e) => {
                setNetworkIdx(0);
                setSearchParams({ run: e.target.value });
              }}
            >
              {!recentRuns.some((r) => r.run_id === runId) && (
                <option value={runId}>{runId}</option>
              )}
              {recentRuns.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  seed {run.seed} . {run.generator} . {run.run_id}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="field-label" htmlFor="casefile-network">
              Network
            </label>
            <select
              id="casefile-network"
              className="select"
              value={networkIdx}
              onChange={(e) => setNetworkIdx(Number(e.target.value))}
              disabled={networks.length === 0}
            >
              {networks.length === 0 && (
                <option value={networkIdx}>network {networkIdx}</option>
              )}
              {networks.map((n) => (
                <option key={n.index} value={n.index}>
                  network {n.index} . {n.size} complaints
                  {n.syndicate !== null ? ` . syndicate ${n.syndicate}` : ""}
                </option>
              ))}
            </select>
          </div>
          <span className="mono small muted">
            run {runId} . seed {runQuery.data.seed} . generator{" "}
            {runQuery.data.generator}
          </span>
        </div>

        {/* (a) Money trail */}
        <div className="card">
          <h3>Money trail (directed-graph reachability)</h3>
          {networkQuery.isPending && (
            <Skeleton height={220} style={{ marginBottom: 8 }} />
          )}
          {networkQuery.isError && (
            <p className="error-box small" style={{ margin: 0 }} role="alert">
              Could not load network {networkIdx}:{" "}
              {networkQuery.error instanceof ApiError
                ? networkQuery.error.detail
                : String(networkQuery.error)}
            </p>
          )}
          {network !== null && network.trail === null && (
            <p className="muted small" style={{ margin: 0 }}>
              No money trail for network {network.index}: it has no
              ground-truth syndicate, so the engine walked no ledger for
              it. Pick another network above.
            </p>
          )}
          {network !== null && network.trail !== null && (
            <MoneyTrail
              key={`${runId}-${network.index}`}
              trail={network.trail}
              pctTracedRun={pctTracedRun}
              reduceMotion={reduceMotion}
            />
          )}
        </div>

        <div className="casefile-grid">
          {/* (b) Mapped sections */}
          {packetQuery.isPending ? (
            <div className="card" aria-label="Loading mapped sections">
              <h3>Mapped sections (verbatim corpus v2)</h3>
              <Skeleton height={64} count={3} style={{ marginBottom: 8 }} />
            </div>
          ) : packetQuery.isError ? (
            <div className="card">
              <h3>Mapped sections (verbatim corpus v2)</h3>
              <p className="error-box small" style={{ margin: 0 }} role="alert">
                Could not load the packet:{" "}
                {packetQuery.error instanceof ApiError
                  ? packetQuery.error.detail
                  : String(packetQuery.error)}
              </p>
            </div>
          ) : (
            <MappedSections
              sections={packetQuery.data.sections}
              mappings={mappings}
              members={network?.members ?? []}
              streamError={mappingStreamError}
              reduceMotion={reduceMotion}
            />
          )}

          {/* (d) F9 audit */}
          <F9Panel runId={runId} reduceMotion={reduceMotion} />
        </div>

        {/* (c) Section 63 packet */}
        {packetQuery.isPending && (
          <div className="card" aria-label="Loading packet">
            <h3>Section 63 packet</h3>
            <Skeleton height={90} count={3} style={{ marginBottom: 8 }} />
          </div>
        )}
        {packetQuery.data !== undefined && (
          <PacketView packet={packetQuery.data} reduceMotion={reduceMotion} />
        )}
      </div>
    </SkeletonTheme>
  );
}
