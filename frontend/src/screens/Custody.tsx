/**
 * Custody Ledger, hero screen 3 (SPEC 10.3, SPEC 8).
 *
 * - GET /api/audit/chain paginated, rendered as a linked chain: mono
 *   hashes, prev-hash linkage drawn as an SVG connector whose color
 *   states whether this row's prev_hash equals the previous row's hash.
 * - GET /api/audit/verify banner: forest when clean, oxblood with
 *   first_bad_seq otherwise.
 * - POST /api/audit/tamper-test (auditor only, honest gate text for
 *   everyone else): the scratch copy breaks at break_seq (row flash,
 *   assertive announcement) while the response's real_chain_ok confirms
 *   the real chain was untouched and re-verified.
 * - SPEC 8.4 threat-model sentence, verbatim honesty about what a hash
 *   chain can and cannot detect.
 */

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useReducedMotion } from "motion/react";
import { useState, useSyncExternalStore } from "react";
import Skeleton, { SkeletonTheme } from "react-loading-skeleton";
import "react-loading-skeleton/dist/skeleton.css";
import { ApiError, getUser, subscribeAuth } from "../lib/api";
import { fmtTimestamp, shortHash } from "../lib/format";
import {
  getChain,
  getVerify,
  postTamperTest,
  type AuditRow,
  type TamperTestResult,
} from "../components/custody/auditApi";

const PAGE_SIZE = 50;
const GENESIS_PREV = "0".repeat(64);

function payloadSummary(payload: Record<string, unknown>): string {
  const text = JSON.stringify(payload);
  return text.length > 96 ? `${text.slice(0, 96)}…` : text;
}

function Connector({ ok, broken }: { ok: boolean; broken: boolean }) {
  return (
    <svg
      className={`chain-connector ${broken ? "broken" : ok ? "ok" : "bad"}`}
      viewBox="0 0 24 30"
      width={24}
      height={30}
      aria-hidden="true"
    >
      {broken ? (
        <g>
          <line x1="12" y1="0" x2="12" y2="10" />
          <line x1="6" y1="13" x2="18" y2="17" />
          <line x1="12" y1="20" x2="12" y2="30" />
        </g>
      ) : (
        <g>
          <line x1="12" y1="0" x2="12" y2="26" />
          <path d="M7 20 L12 27 L17 20" fill="none" />
        </g>
      )}
    </svg>
  );
}

function ChainRowCard({
  row,
  tamper,
}: {
  row: AuditRow;
  tamper: TamperTestResult | null;
}) {
  const corrupted = tamper !== null && row.seq === tamper.corrupted_seq;
  const downstream = tamper !== null && row.seq > tamper.break_seq;
  return (
    <div
      className={`chain-row ${corrupted ? "corrupted" : ""} ${downstream ? "downstream" : ""}`}
    >
      <div className="chain-row-head">
        <span className="mono chain-seq">seq {row.seq}</span>
        <span>
          <strong>{row.action}</strong>
          <span className="muted small"> by {row.actor}</span>
        </span>
        <span className="muted small mono">{fmtTimestamp(row.ts)}</span>
        {corrupted && (
          <span className="conf-chip low">
            corrupted in scratch copy . chain breaks here
          </span>
        )}
      </div>
      <p className="mono small chain-hashes">
        <span className="muted">prev </span>
        <span title={row.prev_hash}>
          {row.prev_hash === GENESIS_PREV ? "genesis (64 zeros)" : shortHash(row.prev_hash)}
        </span>
        <span className="muted"> hash </span>
        <span title={row.hash}>{shortHash(row.hash)}</span>
      </p>
      <p className="muted small mono chain-payload" title={JSON.stringify(row.payload)}>
        {payloadSummary(row.payload)}
      </p>
    </div>
  );
}

export function Custody() {
  const reduceMotion = useReducedMotion() ?? false;
  const user = useSyncExternalStore(subscribeAuth, getUser);
  const isAuditor = user?.role === "auditor";
  const queryClient = useQueryClient();

  const [offset, setOffset] = useState(0);
  const [tamper, setTamper] = useState<TamperTestResult | null>(null);
  const [tamperRunning, setTamperRunning] = useState(false);
  const [tamperError, setTamperError] = useState<string | null>(null);

  const chainQuery = useQuery({
    queryKey: ["audit-chain", offset],
    queryFn: () => getChain(PAGE_SIZE, offset),
    placeholderData: keepPreviousData,
  });
  const verifyQuery = useQuery({
    queryKey: ["audit-verify"],
    queryFn: getVerify,
  });

  const runTamperTest = async () => {
    if (tamperRunning) return;
    setTamperRunning(true);
    setTamperError(null);
    try {
      const result = await postTamperTest();
      setTamper(result);
      // Jump the page to the corrupted record so the break is on screen
      // (seq is 1-based; offset counts rows).
      setOffset(
        Math.max(0, result.corrupted_seq - 1 - Math.floor(PAGE_SIZE / 2)),
      );
      // The test appended tamper_test.run to the real chain; refresh.
      void queryClient.invalidateQueries({ queryKey: ["audit-chain"] });
      void queryClient.invalidateQueries({ queryKey: ["audit-verify"] });
    } catch (error) {
      setTamperError(
        error instanceof ApiError ? error.detail : String(error),
      );
    } finally {
      setTamperRunning(false);
    }
  };

  const exitTamperView = () => {
    setTamper(null);
    void queryClient.invalidateQueries({ queryKey: ["audit-chain"] });
    void queryClient.invalidateQueries({ queryKey: ["audit-verify"] });
  };

  const page = chainQuery.data;
  const total = page?.total ?? 0;
  const lastOnPage = page ? page.offset + page.rows.length : 0;

  return (
    <SkeletonTheme baseColor="#1E3A6B" highlightColor="#2E4E86">
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {/* Verify banner */}
        {verifyQuery.isPending && <Skeleton height={44} />}
        {verifyQuery.isError && (
          <div className="error-box" role="alert">
            Could not verify the chain:{" "}
            {verifyQuery.error instanceof ApiError
              ? verifyQuery.error.detail
              : String(verifyQuery.error)}
          </div>
        )}
        {verifyQuery.data !== undefined && (
          <div
            className={`verify-banner ${verifyQuery.data.ok ? "ok" : "bad"}`}
            role="status"
          >
            {verifyQuery.data.ok
              ? "Chain verified: recomputed from genesis in the database, every hash and prev-hash link intact."
              : `Chain verification FAILED: first bad seq ${verifyQuery.data.first_bad_seq ?? "unknown"}.`}
          </div>
        )}

        {/* Tamper test */}
        <div className="card">
          <h3>Tamper test (scratch copy)</h3>
          {isAuditor ? (
            <div className="f9-controls">
              <button
                type="button"
                className="btn btn-danger"
                onClick={() => void runTamperTest()}
                disabled={tamperRunning}
              >
                {tamperRunning ? "Running" : "Run tamper test"}
              </button>
              {tamper !== null && (
                <button type="button" className="btn" onClick={exitTamperView}>
                  Exit tamper view
                </button>
              )}
              <span className="muted small">
                Snapshots the chain into an unprotected scratch table,
                corrupts one mid-chain record there, and re-verifies. The
                real chain is never modified; the test itself is appended
                to it.
              </span>
            </div>
          ) : (
            <p className="notice-box small" style={{ margin: 0 }}>
              The tamper test needs the auditor role; you are signed in as{" "}
              {user?.username ?? "unknown"} ({user?.role ?? "unknown"}).
              This is deliberate: corrupting even a scratch copy of the
              ledger is an audit action, and running it lands on the real
              chain. Sign in as an auditor to run it.
            </p>
          )}
          {tamperError !== null && (
            <p className="error-box small" role="alert" style={{ marginBottom: 0 }}>
              Tamper test failed: {tamperError}
            </p>
          )}
          <div aria-live="assertive">
            {tamper !== null && (
              <div style={{ marginTop: "0.75rem" }}>
                <p className="error-box small" style={{ margin: 0 }}>
                  Scratch chain verification broke at seq {tamper.break_seq}:
                  the payload of seq {tamper.corrupted_seq} was corrupted in
                  the {tamper.scratch_rows}-row scratch snapshot and its hash
                  no longer recomputes.
                </p>
                <p
                  className="verify-banner ok small"
                  style={{ marginTop: "0.5rem" }}
                >
                  Real chain untouched:{" "}
                  {tamper.real_chain_ok
                    ? "re-verified clean after the test"
                    : "re-verification FAILED (unexpected; investigate)"}
                  . The test itself was appended as tamper_test.run at seq{" "}
                  {tamper.audit_seq}.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Chain */}
        <div className="card">
          <h3>
            {tamper !== null
              ? "Scratch copy (corruption exists only in the temp table; rows below mirror the snapshot)"
              : "Audit chain"}
          </h3>
          {chainQuery.isError && (
            <p className="error-box small" role="alert" style={{ margin: 0 }}>
              Could not load the chain:{" "}
              {chainQuery.error instanceof ApiError
                ? chainQuery.error.detail
                : String(chainQuery.error)}
            </p>
          )}
          {chainQuery.isPending && (
            <div aria-label="Loading audit chain">
              <Skeleton height={78} count={5} style={{ marginBottom: 8 }} />
            </div>
          )}
          {page !== undefined && page.rows.length === 0 && (
            <p className="muted small" style={{ margin: 0 }}>
              The audit chain is empty. Every intake, stage completion,
              decision, and packet assembly appends here; start a run to
              see it grow.
            </p>
          )}
          {page !== undefined && page.rows.length > 0 && (
            <div>
              <ol className="chain-list" style={{ opacity: reduceMotion ? 1 : undefined }}>
                {page.rows.map((row, index) => {
                  const prevRow =
                    index > 0 ? (page.rows[index - 1] ?? null) : null;
                  const linked =
                    prevRow !== null && row.prev_hash === prevRow.hash;
                  const brokenLink =
                    tamper !== null &&
                    prevRow !== null &&
                    row.seq > tamper.break_seq &&
                    prevRow.seq >= tamper.break_seq;
                  return (
                    <li key={row.seq}>
                      {prevRow !== null && (
                        <Connector ok={linked} broken={brokenLink} />
                      )}
                      <ChainRowCard row={row} tamper={tamper} />
                    </li>
                  );
                })}
              </ol>
              <div className="chain-pager">
                <button
                  type="button"
                  className="btn"
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                >
                  Earlier rows
                </button>
                <span className="mono small muted">
                  rows {page.offset + 1} to {lastOnPage} of {total}
                </span>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={lastOnPage >= total}
                >
                  Later rows
                </button>
              </div>
            </div>
          )}
        </div>

        {/* SPEC 8.4 threat model, one honest sentence */}
        <p className="counter-sub" style={{ margin: 0 }}>
          Threat model (SPEC 8.4): a hash chain is tamper-evident, not
          immutable; an attacker privileged enough to rewrite a record and
          recompute every downstream hash defeats internal verification,
          so the chain head is anchored out of band on every exported
          packet, in the structured log, and as a Prometheus metric.
        </p>
      </div>
    </SkeletonTheme>
  );
}
