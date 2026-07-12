/**
 * Typed fetch wrapper for the Paritran REST surface (SPEC 9.1).
 *
 * - JWT pair lives in sessionStorage (cleared when the tab closes).
 * - Every authed call attaches Authorization: Bearer; a 401 triggers ONE
 *   refresh attempt (single-flight across concurrent callers) and one
 *   retry. A second 401, or a failed refresh, clears the session so the
 *   route guard sends the user back to /login.
 * - No number is invented here: every exported type mirrors a backend
 *   response model field for field (truth rule 1, SPEC section 1).
 */

const ACCESS_KEY = "paritran.access";
const REFRESH_KEY = "paritran.refresh";
const USER_KEY = "paritran.user";

// ---------------------------------------------------------------------------
// Errors

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`HTTP ${status}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// ---------------------------------------------------------------------------
// Session store (sessionStorage + subscribers for useSyncExternalStore)

export interface SessionUser {
  username: string;
  role: string;
}

type Listener = () => void;
const listeners = new Set<Listener>();

function notify(): void {
  for (const fn of listeners) fn();
}

export function subscribeAuth(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_KEY);
}

function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_KEY);
}

/** Cached JSON snapshot so useSyncExternalStore gets a stable reference. */
let userSnapshotRaw: string | null = null;
let userSnapshot: SessionUser | null = null;

export function getUser(): SessionUser | null {
  const raw = sessionStorage.getItem(USER_KEY);
  if (raw === userSnapshotRaw) return userSnapshot;
  userSnapshotRaw = raw;
  if (raw === null) {
    userSnapshot = null;
    return null;
  }
  try {
    userSnapshot = JSON.parse(raw) as SessionUser;
  } catch {
    userSnapshot = null;
  }
  return userSnapshot;
}

export function isAuthenticated(): boolean {
  return getAccessToken() !== null;
}

interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  access_expires_in: number;
  refresh_expires_in: number;
}

/** Decode the JWT payload (base64url JSON) without verifying: the server
 *  verifies; the client only reads sub/role for display and gating. */
function decodeClaims(token: string): { sub?: string; role?: string } {
  const part = token.split(".")[1];
  if (!part) return {};
  try {
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(b64)) as { sub?: string; role?: string };
  } catch {
    return {};
  }
}

function storePair(pair: TokenPair): SessionUser {
  sessionStorage.setItem(ACCESS_KEY, pair.access_token);
  sessionStorage.setItem(REFRESH_KEY, pair.refresh_token);
  const claims = decodeClaims(pair.access_token);
  const user: SessionUser = {
    username: claims.sub ?? "unknown",
    role: claims.role ?? "unknown",
  };
  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  notify();
  return user;
}

export function clearSession(): void {
  sessionStorage.removeItem(ACCESS_KEY);
  sessionStorage.removeItem(REFRESH_KEY);
  sessionStorage.removeItem(USER_KEY);
  notify();
}

// ---------------------------------------------------------------------------
// Login / refresh / logout

async function readDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const detail = (body as Record<string, unknown>).detail;
      if (typeof detail === "string") return detail;
      return JSON.stringify(detail ?? body);
    }
    return String(body);
  } catch {
    return response.statusText || "request failed";
  }
}

export async function login(
  username: string,
  password: string,
): Promise<SessionUser> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  const pair = (await response.json()) as TokenPair;
  return storePair(pair);
}

export function logout(): void {
  clearSession();
}

/** Single-flight refresh: concurrent 401s share one refresh round-trip. */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshOnce(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken === null) return false;
    try {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) return false;
      storePair((await response.json()) as TokenPair);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

/**
 * Refresh the session tokens (single-flight). Exposed for the SSE layer:
 * EventSource cannot send an Authorization header mid-stream, so on a
 * stream error the wrapper refreshes here and reconnects with the fresh
 * ?token=. Returns false when no valid refresh token exists.
 */
export function refreshSession(): Promise<boolean> {
  return refreshOnce();
}

// ---------------------------------------------------------------------------
// Core fetch wrapper

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const attempt = async (): Promise<Response> => {
    const headers = new Headers(init?.headers);
    const token = getAccessToken();
    if (token !== null) headers.set("Authorization", `Bearer ${token}`);
    if (init?.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(path, { ...init, headers });
  };

  let response = await attempt();
  if (response.status === 401) {
    const refreshed = await refreshOnce();
    if (!refreshed) {
      clearSession();
      throw new ApiError(401, "session expired; sign in again");
    }
    response = await attempt();
    if (response.status === 401) {
      clearSession();
      throw new ApiError(401, "session expired; sign in again");
    }
  }
  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// Response types (mirror backend pydantic models field for field)

export interface RunStarted {
  run_id: string;
  seed: number;
  generator: string;
  status: string;
  stream_url: string;
}

/** One measured mapping row (engine FullMapper.measure / pipeline rows). */
export interface MappingMeasureRow {
  n: number;
  accuracy: number | null;
  routing_rate?: number;
  high_confidence_n?: number;
  high_confidence_accuracy?: number | null;
  method?: string;
}

export interface MappingRows {
  v1_floor: MappingMeasureRow | null;
  v2_bm25_ablation: MappingMeasureRow | null;
  v2_full_stack: MappingMeasureRow | null;
  extended_v2_full_stack: MappingMeasureRow | null;
  routing_rate: number | null;
  run_high: number;
  run_low: number;
  run_routing_rate: number;
  degraded: boolean;
}

/**
 * Pipeline results dict (SPEC 6.11). Keys are open-ended (the diff view
 * iterates whatever the payload carries); the fields below are the ones
 * screens read by name.
 */
export interface RunResults {
  n_complaints?: number;
  n_syndicates_seeded?: number;
  networks_found?: number;
  linkage_precision?: number;
  linkage_recall?: number;
  linkage_f1?: number;
  pct_value_traced_to_cashout?: number;
  money_trail_method?: string;
  section_accuracy_bm25?: number;
  section_method?: string;
  f9_claims?: number;
  f9_passed?: number;
  f9_withheld?: number;
  f9_leaked?: number;
  chain_len?: number;
  chain_verified?: boolean;
  time_to_packet_sec?: number;
  data?: string;
  seed?: number;
  ner_precision?: number;
  ner_recall?: number;
  mapping?: MappingRows;
  mapping_degraded?: boolean;
  stage_latencies_ms?: Record<string, number>;
  generator_name?: string;
  f9_is_stub?: boolean;
  f9_corpus_version?: string;
  f9_degraded?: boolean;
  semantic_unavailable?: boolean;
  [key: string]: unknown;
}

export interface RunStatus {
  run_id: string;
  seed: number;
  generator: string;
  status: string;
  n_events: number;
  results: RunResults | null;
  db_run_id: number | null;
  eval_run_id: number | null;
  error: string | null;
  persist_error: string | null;
}

export interface GraphEdge {
  a: number;
  b: number;
  w: number;
}

export interface NetworkTriage {
  syndicate: number;
  score: number;
  /** All four formula terms, straight from the engine (SPEC 6.5). */
  inputs: Record<string, number>;
}

export interface TrailHop {
  src: string;
  dst: string;
  amount: number;
}

export interface NetworkTrail {
  syndicate: number;
  hops: TrailHop[];
  breaks: string[][];
  traced_amt: number;
  total_amt: number;
}

export interface NetworkSummary {
  index: number;
  size: number;
  members: number[];
  syndicate: number | null;
  triage: NetworkTriage | null;
  trail: NetworkTrail | null;
}

export interface NetworksResponse {
  run_id: string;
  graph: { nodes: number[]; edges: GraphEdge[] };
  networks: NetworkSummary[];
}

export interface EvalRunRow {
  id: number;
  created_at: string;
  git_sha: string | null;
  dataset_version: string | null;
  corpus_version: string | null;
  generator: string | null;
  model_tag: string | null;
  metrics: RunResults | null;
  latencies: Record<string, number> | null;
  sample_sizes: Record<string, number> | null;
}

export interface EvalRunsPage {
  rows: EvalRunRow[];
}

export interface ReproduceStarted {
  run_id: string;
  seed: number;
  generator: string;
  stream_url: string;
  baseline: Record<string, unknown>;
}

export interface DecisionRequest {
  run_id: string;
  kind: "link" | "claim";
  ref: Record<string, unknown>;
  decision: "accept" | "reject";
}

export interface DecisionAppended {
  seq: number;
  hash: string;
  prev_hash: string;
  action: string;
}

// ---------------------------------------------------------------------------
// Endpoint helpers

export function startRun(seed: number, generator: "stub" | "ollama"): Promise<RunStarted> {
  return apiFetch<RunStarted>("/api/intake/run", {
    method: "POST",
    body: JSON.stringify({ seed, generator }),
  });
}

export function getRun(runId: string): Promise<RunStatus> {
  return apiFetch<RunStatus>(`/api/runs/${encodeURIComponent(runId)}`);
}

export function getNetworks(runId: string): Promise<NetworksResponse> {
  return apiFetch<NetworksResponse>(
    `/api/networks?run_id=${encodeURIComponent(runId)}`,
  );
}

export function getEvalRuns(limit = 20): Promise<EvalRunsPage> {
  return apiFetch<EvalRunsPage>(`/api/evaluation/metrics?limit=${limit}`);
}

export function startReproduce(): Promise<ReproduceStarted> {
  return apiFetch<ReproduceStarted>("/api/evaluation/reproduce", {
    method: "POST",
  });
}

export function postDecision(body: DecisionRequest): Promise<DecisionAppended> {
  return apiFetch<DecisionAppended>("/api/decisions", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
