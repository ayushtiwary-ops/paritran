/**
 * Security Posture, screen 5 (SPEC 10.3, 11, and the SPEC 2 egress test).
 *
 * - Scanner cards straight from GET /api/security/posture, which relays
 *   infra/scans/out/summary.json unmodified: per-tool severity counts,
 *   last-scan timestamp, and not_installed / error states shown exactly
 *   as recorded (muted, never hidden).
 * - Egress panel: the configured-outbound-endpoint audit plus the live
 *   TCP self-test result, timestamped. Measured, not asserted (SPEC 2).
 * - OWASP Top 10:2025 coverage checklist mapping each category to the
 *   concrete control in this repo (details in docs/SECURITY.md).
 * - Auth / RBAC / rate-limit summary: static description of the
 *   mechanisms with their code paths. No invented numbers anywhere;
 *   every count on this screen comes from the posture payload.
 */

import { useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import Skeleton, { SkeletonTheme } from "react-loading-skeleton";
import "react-loading-skeleton/dist/skeleton.css";
import { ApiError, getUser, subscribeAuth } from "../lib/api";
import { fmtTimestamp } from "../lib/format";
import {
  getPosture,
  type ScannerSummary,
  type SecurityPosture,
} from "../components/security/postureApi";

/** Display order for scanner cards (every key the harness can emit). */
const SCANNER_ORDER = [
  "pip-audit",
  "npm-audit",
  "bandit",
  "semgrep",
  "gitleaks",
  "trivy-fs",
  "trivy-image",
  "grype",
];

interface OwaspItem {
  id: string;
  title: string;
  status: "covered" | "partial";
  control: string;
  path: string;
}

/**
 * OWASP Top 10:2025 mapped to this repo's concrete controls. Statuses
 * are honest: "partial" names the gap. Full table in docs/SECURITY.md.
 */
const OWASP_2025: OwaspItem[] = [
  {
    id: "A01:2025",
    title: "Broken Access Control",
    status: "covered",
    control:
      "JWT role gates on every route (officer/supervisor/auditor), RBAC" +
      " matrix under test, and DB least privilege: the app role holds only" +
      " SELECT and INSERT on the audit ledger.",
    path: "backend/paritran/api/deps.py . backend/tests/test_auth.py",
  },
  {
    id: "A02:2025",
    title: "Security Misconfiguration",
    status: "covered",
    control:
      "db and prometheus publish no host ports (internal network); nginx" +
      " sends CSP, X-Frame-Options DENY, nosniff, and no-referrer; startup" +
      " refuses placeholder secrets.",
    path: "docker-compose.yml . infra/docker/nginx.conf",
  },
  {
    id: "A03:2025",
    title: "Software Supply Chain Failures",
    status: "partial",
    control:
      "All dependencies pinned (requirements + lockfile); pip-audit, npm" +
      " audit, trivy, and grype run via run_all.sh and CI. Gap: no" +
      " standalone SBOM artifact is published yet.",
    path: "infra/scans/run_all.sh . .github/workflows/ci.yml",
  },
  {
    id: "A04:2025",
    title: "Cryptographic Failures",
    status: "partial",
    control:
      "Argon2id password hashing, random 64-hex JWT secret, SHA-256 audit" +
      " chain. Gap stated honestly: demo transport is localhost-only" +
      " without TLS; the pilot TLS path is documented, not deployed.",
    path: "backend/paritran/api/auth.py . docs/SECURITY.md",
  },
  {
    id: "A05:2025",
    title: "Injection",
    status: "covered",
    control:
      "Every query is parameterized psycopg (no SQL built from user" +
      " input), pydantic validates all request bodies, React escapes all" +
      " rendered output.",
    path: "backend/paritran/db/repo.py",
  },
  {
    id: "A06:2025",
    title: "Insecure Design",
    status: "covered",
    control:
      "Threat model written down (including what the hash chain cannot" +
      " detect), generative output fenced behind the F9 gate, human" +
      " sign-off on every packet.",
    path: "docs/SECURITY.md . backend/paritran/engine/f9/gate.py",
  },
  {
    id: "A07:2025",
    title: "Authentication Failures",
    status: "covered",
    control:
      "Argon2id hashes, 15-minute access tokens with 8-hour refresh," +
      " typ-checked JWTs, per-identity rate limits, and a startup guard" +
      " that refuses degenerate seed passwords.",
    path: "backend/paritran/api/auth.py . backend/paritran/api/main.py",
  },
  {
    id: "A08:2025",
    title: "Software or Data Integrity Failures",
    status: "covered",
    control:
      "DB-enforced append-only hash chain over every decision and" +
      " artefact event (UPDATE/DELETE/TRUNCATE rejected by trigger)," +
      " seed-42 reproduction contract, gitleaks secret scan.",
    path: "backend/paritran/db/migrations . backend/tests/test_rls_audit.py",
  },
  {
    id: "A09:2025",
    title: "Logging & Alerting Failures",
    status: "partial",
    control:
      "Every officer decision and artefact event lands on the audit" +
      " chain; Prometheus + Grafana dashboards; critical alerts surface" +
      " in-app over SSE. Gap: no out-of-app paging, demo scope only.",
    path: "backend/paritran/db/repo.py . infra/grafana",
  },
  {
    id: "A10:2025",
    title: "Mishandling of Exceptional Conditions",
    status: "covered",
    control:
      "Labelled degrade paths (stub generator, BM25+rules with mandatory" +
      " review flag), fail-fast startup, health checks that report per" +
      " component with 2 s timeouts and honest 503s.",
    path: "backend/paritran/api/main.py . backend/paritran/llm",
  },
];

function sevCount(value: number | null): string {
  return value === null ? "-" : String(value);
}

function ScannerCard({ tool, scan }: { tool: string; scan: ScannerSummary }) {
  const inactive = scan.status === "not_installed" || scan.status === "error";
  const critical = scan.critical ?? 0;
  const high = scan.high ?? 0;
  return (
    <div className="card" style={inactive ? { opacity: 0.55 } : undefined}>
      <h3>{tool}</h3>
      {scan.status === "not_installed" && (
        <p className="muted small" style={{ margin: 0 }}>
          Not installed when run_all.sh last ran; recorded honestly, not
          skipped silently.
        </p>
      )}
      {scan.status === "error" && (
        <p className="muted small" style={{ margin: 0 }}>
          Scanner failed to run: {scan.error_detail ?? "see scan logs"}.
        </p>
      )}
      {(scan.status === "ok" || scan.status === "findings") && (
        <div>
          <p style={{ margin: "0 0 0.4rem" }}>
            <span
              className={`conf-chip ${critical + high > 0 ? "low" : "high"}`}
            >
              {sevCount(scan.critical)} critical . {sevCount(scan.high)} high
            </span>
          </p>
          <p className="mono small" style={{ margin: 0 }}>
            medium {sevCount(scan.medium)} . low {sevCount(scan.low)} .
            unknown {sevCount(scan.unknown)} . total{" "}
            {sevCount(scan.findings_total)}
          </p>
          {scan.ran_at !== null && (
            <p className="counter-sub">ran {fmtTimestamp(scan.ran_at)}</p>
          )}
          {scan.note !== null && scan.note !== undefined && (
            <p className="muted small" style={{ margin: "0.3rem 0 0" }}>
              {scan.note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function EgressPanel({ posture }: { posture: SecurityPosture }) {
  const { egress, outbound_endpoints } = posture;
  const blocked = egress.result === "blocked";
  return (
    <div className="card">
      <h3>Egress: measured, not asserted</h3>
      <div
        className={`verify-banner ${blocked ? "ok" : "bad"}`}
        role="status"
        style={{ marginBottom: "0.75rem" }}
      >
        Live self-test: outbound TCP to {egress.target} is{" "}
        <strong>{egress.result}</strong> (checked{" "}
        {fmtTimestamp(egress.checked_at)}, {egress.timeout_seconds}s timeout).
      </div>
      <p className="muted small" style={{ margin: "0 0 0.75rem" }}>
        {egress.detail} Docker cannot both publish ports and block WAN on
        the same network, so zero egress is proven by this live attempt
        from inside the api process, not asserted from config.
      </p>
      <p className="counter-label" style={{ marginBottom: "0.35rem" }}>
        Configured outbound endpoints (the complete list)
      </p>
      {outbound_endpoints.map((endpoint) => (
        <p key={endpoint.name} className="small" style={{ margin: "0 0 0.4rem" }}>
          <span className="mono">{endpoint.endpoint}</span>
          <span className="muted"> . {endpoint.purpose}</span>
        </p>
      ))}
    </div>
  );
}

export function Security() {
  const user = useSyncExternalStore(subscribeAuth, getUser);
  const postureQuery = useQuery({
    queryKey: ["security-posture"],
    queryFn: getPosture,
    refetchOnWindowFocus: false,
  });

  const posture = postureQuery.data;
  const forbidden =
    postureQuery.error instanceof ApiError && postureQuery.error.status === 403;

  return (
    <SkeletonTheme baseColor="#1E3A6B" highlightColor="#2E4E86">
      <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        {postureQuery.isPending && (
          <div aria-label="Loading security posture">
            <Skeleton height={120} count={2} style={{ marginBottom: 8 }} />
          </div>
        )}
        {postureQuery.isError && forbidden && (
          <p className="notice-box small" style={{ margin: 0 }}>
            The posture endpoint needs the auditor or supervisor role; you
            are signed in as {user?.username ?? "unknown"} (
            {user?.role ?? "unknown"}). This mirrors SPEC 9.1: security
            posture is an oversight view, not an investigation tool.
          </p>
        )}
        {postureQuery.isError && !forbidden && (
          <div className="error-box" role="alert">
            Could not load the security posture:{" "}
            {postureQuery.error instanceof ApiError
              ? postureQuery.error.detail
              : String(postureQuery.error)}
          </div>
        )}

        {posture !== undefined && (
          <>
            {/* Scan artifact summaries */}
            <div className="card">
              <h3>Scanner artifacts (infra/scans/run_all.sh)</h3>
              {posture.summary_available ? (
                <p className="muted small" style={{ margin: 0 }}>
                  Relayed unmodified from summary.json (
                  <span className="mono">{posture.scans_source}</span>
                  ), generated{" "}
                  {posture.summary_generated_at !== null
                    ? fmtTimestamp(posture.summary_generated_at)
                    : "unknown"}
                  {posture.last_scan_at !== null && (
                    <> . last scan {fmtTimestamp(posture.last_scan_at)}</>
                  )}
                  .
                </p>
              ) : (
                <p className="notice-box small" style={{ margin: 0 }}>
                  No scan artifacts found at{" "}
                  <span className="mono">{posture.scans_dir}</span>. Run
                  ./infra/scans/run_all.sh; this panel reports absence, it
                  never invents a clean bill.
                </p>
              )}
            </div>
            {posture.summary_available && (
              <div className="counter-row">
                {SCANNER_ORDER.filter((tool) => tool in posture.scans).map(
                  (tool) => (
                    <ScannerCard
                      key={tool}
                      tool={tool}
                      scan={posture.scans[tool] as ScannerSummary}
                    />
                  ),
                )}
              </div>
            )}

            <EgressPanel posture={posture} />
          </>
        )}

        {/* OWASP Top 10:2025 checklist (static mapping, statuses honest) */}
        <div className="card">
          <h3>OWASP Top 10:2025 coverage</h3>
          <p className="muted small" style={{ margin: "0 0 0.75rem" }}>
            Each category mapped to the concrete control in this repo;
            "partial" names the gap instead of hiding it. Full table with
            the ASVS 5.0 alignment and accepted risks: docs/SECURITY.md.
          </p>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {OWASP_2025.map((item) => (
              <li
                key={item.id}
                style={{
                  padding: "0.5rem 0",
                  borderTop: "1px solid var(--line)",
                }}
              >
                <p style={{ margin: "0 0 0.2rem" }}>
                  <span className="mono small">{item.id}</span>{" "}
                  <strong>{item.title}</strong>{" "}
                  <span
                    className={`conf-chip ${item.status === "covered" ? "high" : "low"}`}
                  >
                    {item.status}
                  </span>
                </p>
                <p className="muted small" style={{ margin: "0 0 0.2rem" }}>
                  {item.control}
                </p>
                <p className="counter-sub" style={{ margin: 0 }}>
                  {item.path}
                </p>
              </li>
            ))}
          </ul>
        </div>

        {/* Auth / RBAC / rate limiting: mechanisms, not numbers */}
        <div className="card">
          <h3>Auth, RBAC, rate limiting</h3>
          <p className="small" style={{ margin: "0 0 0.5rem" }}>
            JWT access tokens (15 min) plus refresh tokens (8 h), Argon2id
            password hashing, roles officer / supervisor / auditor with
            supervisor inheriting officer rights and nothing else implied
            (backend/paritran/api/deps.py, backend/paritran/api/auth.py).
          </p>
          <p className="small" style={{ margin: "0 0 0.5rem" }}>
            slowapi rate limiting keyed by the JWT sub claim: officer and
            supervisor 120/min, auditor 60/min, unauthenticated 20/min by
            client IP. Configured budgets from SPEC 5, verified by
            backend/tests/test_auth.py; not measured traffic numbers.
          </p>
          <p className="small" style={{ margin: 0 }}>
            Transport honesty: the demo serves plain HTTP on localhost
            only, behind nginx security headers (CSP, X-Frame-Options
            DENY, nosniff). TLS termination is a documented pilot step
            (docs/SECURITY.md), deliberately not claimed here.
          </p>
        </div>

        {/* SPEC 8.4 threat-model sentence, same honesty as Custody */}
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
