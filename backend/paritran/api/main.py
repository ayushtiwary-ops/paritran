"""Paritran API application.

Milestone 4 surface:

- GET /health: 200 when the database is reachable, else 503. Ollama or
  model-file failures are reported per component but do not fail health,
  because the engine has labelled degrade paths for both: the
  deterministic fabricating stub behind the identical generator
  interface (SPEC 6.8) and the BM25 plus rules mapping path with a
  mandatory review flag (SPEC section 20).
- GET /ready: 200 only when db, ollama, and model files are all ok.
- GET /metrics: Prometheus scrape endpoint via
  prometheus-fastapi-instrumentator (SPEC section 12).
- The SPEC 9.1 REST routers (auth, intake, runs, networks, cases,
  decisions, audit, evaluation, security) and the SPEC 9.2 SSE
  channels, plus the SPEC 14 /api/demo/* controls and beat stream (M9).
- slowapi rate limiting keyed by JWT sub with role budgets (SPEC 5):
  officer/supervisor 120/min, auditor 60/min, anonymous 20/min. The
  public health/ready/metrics probes are not part of the API budget.
- A request-latency ring buffer (middleware below) feeding the honest
  p50/p95 numbers on the /api/stream/status ticks; empty means null,
  never an invented number.

Every component check is capped at 2 seconds (SPEC 9.1 and 12).

Milestone 8 observability (SPEC 12, 8.4):

- OpenTelemetry FastAPIInstrumentor wiring, import-guarded: when the
  opentelemetry packages are absent the app runs identically, and when
  present but no tracer provider/exporter is configured the OTel API
  hands out no-op spans, so the wiring adds no exporter, no background
  thread, and no egress (SPEC section 2).
- prometheus-fastapi-instrumentator now also exposes the
  http_requests_inprogress gauge (labelled by method and handler).
- Custom paritran_* metrics: paritran_runs_total and
  paritran_f9_verdicts_total live in runstore next to the state they
  count; paritran_audit_chain_head_info (the SPEC 8.4 out-of-band
  anchor) is defined here, primed from the last audit row at startup,
  and refreshed on every append via the repo append hook.
"""

import asyncio
import logging
import math
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import Info
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from paritran.api import auth, sse
from paritran.api.deps import limiter
from paritran.api.routers import ALL_ROUTERS
from paritran.config import get_settings
from paritran.db import repo
from paritran.db.migrate import run_migrations
from paritran.db.seed import seed_users

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0

# Ring buffer of recent request latencies (ms). Sized for the demo's
# request volume; the status stream reads percentiles from it.
LATENCY_RING_SIZE = 1024
REQUEST_LATENCIES_MS: deque = deque(maxlen=LATENCY_RING_SIZE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: migrations + seeding over ADMIN_DATABASE_URL (SPEC 7.1).

    When RUN_MIGRATIONS_ON_STARTUP is true (the compose default), the
    migration runner and user seeding execute before the app serves
    traffic, failing fast with a clear error when the database is
    unreachable. Unit tests set RUN_MIGRATIONS_ON_STARTUP=false and
    skip all of it. Both helpers are sync by design and run in a
    worker thread so the event loop is never blocked.
    """
    settings = get_settings()
    if settings.RUN_MIGRATIONS_ON_STARTUP:
        _reject_degenerate_secrets(settings)
        try:
            applied = await asyncio.to_thread(
                run_migrations, settings.ADMIN_DATABASE_URL, settings.APP_DB_PASSWORD
            )
            ensured = await asyncio.to_thread(seed_users, settings)
        except psycopg.OperationalError as exc:
            raise RuntimeError(
                "startup aborted: database unreachable or authentication failed "
                f"while running migrations/seed over ADMIN_DATABASE_URL ({type(exc).__name__}: {exc}). "
                "Check that the db service is up and the DSN host/port are correct. "
                "If the error names paritran_admin authentication, a pgdata volume "
                "initialized before the Milestone 2 role split is a known cause: "
                "recreate it with 'docker compose down -v'."
            ) from exc
        logger.info(
            "startup migrations applied=%s seeded_users=%s", applied, ensured
        )
    # The pool exists regardless of the migration flag: it is created closed
    # and opens lazily, so environments without a database are unaffected,
    # while deployments that migrate externally still get working routers.
    await repo.init_pool(settings.DATABASE_URL)
    if settings.RUN_MIGRATIONS_ON_STARTUP:
        # Prime the SPEC 8.4 chain-head anchor metric from the last audit
        # row, so the anchor is exposed from the first scrape and not only
        # after the first in-process append fires the repo hook. Gated on
        # the migration flag because it implies a reachable database;
        # unit-test environments skip it. Failure is logged, never fatal.
        try:
            head = await asyncio.wait_for(
                repo.get_chain_head(), timeout=CHECK_TIMEOUT_SECONDS
            )
        except Exception as exc:  # noqa: BLE001 - observability must not gate boot
            logger.warning("audit chain head metric not primed: %s", exc)
        else:
            if head is not None:
                _refresh_chain_head_metric(head)
    yield
    await repo.close_pool()


def _reject_degenerate_secrets(settings) -> None:
    """Fail startup before a placeholder secret can become a real credential.

    Seeding is insert-only, so an argon2 hash of "CHANGE_ME" or an empty
    string (compose interpolates missing .env keys to "") would persist as a
    permanently guessable login. Refusing to boot is the honest failure.
    """
    required = {
        "APP_DB_PASSWORD": settings.APP_DB_PASSWORD,
        "OFFICER1_PASSWORD": settings.OFFICER1_PASSWORD,
        "SUPERVISOR1_PASSWORD": settings.SUPERVISOR1_PASSWORD,
        "AUDITOR1_PASSWORD": settings.AUDITOR1_PASSWORD,
    }
    bad = sorted(name for name, value in required.items() if value in ("", "CHANGE_ME"))
    if bad:
        raise RuntimeError(
            "startup aborted: placeholder or empty secrets for "
            f"{', '.join(bad)}. Run scripts/bootstrap_env.sh (it generates "
            "real values and adds any keys missing from an existing .env)."
        )


app = FastAPI(
    title="Paritran API",
    version="0.1.0",
    description="From complaint to conviction. On-premise court-admissibility engine.",
    lifespan=lifespan,
)

# Rate limiting (SPEC 5): every API route is decorated with
# limiter.limit(role_rate_limit); this wires storage and the 429 handler.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def _record_request_latency(request: Request, call_next):
    """Feed the latency ring buffer (SPEC 12, status.tick p50/p95).

    For streaming responses this measures time to response start, which
    is the honest per-request number for an SSE endpoint.
    """
    t0 = time.perf_counter()
    response = await call_next(request)
    REQUEST_LATENCIES_MS.append(round((time.perf_counter() - t0) * 1000, 3))
    return response


def latency_percentiles() -> dict:
    """p50/p95 over the ring buffer; nulls when nothing was recorded."""
    data = sorted(REQUEST_LATENCIES_MS)
    if not data:
        return {"count": 0, "p50_ms": None, "p95_ms": None}

    def pct(p: float) -> float:
        idx = min(len(data) - 1, max(0, math.ceil(p / 100 * len(data)) - 1))
        return data[idx]

    return {"count": len(data), "p50_ms": pct(50), "p95_ms": pct(95)}


Instrumentator(
    # SPEC 12 dashboard needs the in-progress gauge; labels give the
    # per-handler breakdown (metric: http_requests_inprogress).
    should_instrument_requests_inprogress=True,
    inprogress_labels=True,
).instrument(app).expose(app)


def _wire_opentelemetry(target: FastAPI) -> bool:
    """OpenTelemetry FastAPIInstrumentor wiring (SPEC 12, Milestone 8).

    Import-guarded: without the opentelemetry packages installed the app
    runs identically and this returns False. When wired, span creation
    goes through the OTel API's global tracer provider; until a
    deployment configures an SDK provider with an exporter, that is the
    no-op/proxy provider, so no spans are recorded, no thread is
    started, and nothing leaves the process (SPEC section 2 zero
    egress). Never raises: observability wiring must not take the API
    down.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError as exc:
        logger.info("OpenTelemetry not installed; tracing not wired (%s)", exc)
        return False
    try:
        FastAPIInstrumentor.instrument_app(target)
    except Exception as exc:  # noqa: BLE001 - never let tracing wiring kill boot
        logger.warning("OpenTelemetry wiring failed; continuing without: %s", exc)
        return False
    logger.info("OpenTelemetry FastAPIInstrumentor wired")
    return True


OTEL_WIRED = _wire_opentelemetry(app)

# SPEC 8.4 out-of-band anchor: the current audit chain head, exposed as
# paritran_audit_chain_head_info{head_hash=..., seq=...} 1. An Info metric
# replaces its label set on every refresh, so exactly one head is ever
# exposed. Refreshed on every audit append (repo hook below) and primed
# from the last audit row in lifespan.
AUDIT_CHAIN_HEAD = Info(
    "paritran_audit_chain_head",
    "Current audit_log chain head observed by this API process "
    "(SPEC 8.4 out-of-band anchor): head_hash and seq of the latest row.",
)


def _refresh_chain_head_metric(row: dict) -> None:
    """Repo append hook: expose the freshly appended row as the chain head."""
    AUDIT_CHAIN_HEAD.info({"head_hash": str(row["hash"]), "seq": str(row["seq"])})


repo.register_append_hook(_refresh_chain_head_metric)

# SPEC 9.1 REST surface + SPEC 9.2 SSE channels (Milestone 4).
app.include_router(auth.router)
for _router in ALL_ROUTERS:
    app.include_router(_router)
app.include_router(sse.router)


async def check_db() -> dict[str, str]:
    """Round-trip SELECT 1 against DATABASE_URL with psycopg async."""
    settings = get_settings()
    conn = await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, connect_timeout=int(CHECK_TIMEOUT_SECONDS)
    )
    try:
        cursor = await conn.execute("SELECT 1")
        await cursor.fetchone()
    finally:
        await conn.close()
    return {"status": "ok", "detail": "SELECT 1 round-trip succeeded"}


async def check_ollama() -> dict[str, str]:
    """GET {OLLAMA_BASE_URL}/api/tags to confirm the model host is up."""
    settings = get_settings()
    url = settings.OLLAMA_BASE_URL.rstrip("/") + "/api/tags"
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
        response.raise_for_status()
    return {"status": "ok", "detail": f"GET {url} returned {response.status_code}"}


def resolve_model_dir(base: Path) -> Path | None:
    """Resolve the InLegalBERT weights directory under INLEGALBERT_PATH.

    Accepts either a flat model directory (config.json at the root) or a
    HuggingFace hub-cache layout (refs/main naming a snapshots/<sha> dir),
    so the mounted path is machine-independent (no snapshot sha in .env).
    """
    if (base / "config.json").is_file():
        return base
    ref = base / "refs" / "main"
    if ref.is_file():
        snapshot = base / "snapshots" / ref.read_text().strip()
        if (snapshot / "config.json").is_file():
            return snapshot
    snapshots = sorted((base / "snapshots").glob("*/config.json")) if (base / "snapshots").is_dir() else []
    return snapshots[0].parent if snapshots else None


async def check_model_files() -> dict[str, str]:
    """Verify InLegalBERT weights are present under INLEGALBERT_PATH."""
    settings = get_settings()

    def probe() -> dict[str, str]:
        base = Path(settings.INLEGALBERT_PATH)
        if not base.is_dir():
            return {"status": "down", "detail": f"{base} is not a directory"}
        resolved = resolve_model_dir(base)
        if resolved is None:
            return {"status": "down", "detail": f"no config.json found under {base}"}
        return {"status": "ok", "detail": f"InLegalBERT weights present at {resolved}"}

    return await asyncio.to_thread(probe)


async def _run_check(name: str, check) -> dict[str, str]:
    """Run one component check with the 2 second cap, never raising."""
    try:
        return await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, TimeoutError):
        return {
            "status": "down",
            "detail": f"{name} check exceeded {CHECK_TIMEOUT_SECONDS}s timeout",
        }
    except Exception as exc:
        return {"status": "down", "detail": f"{type(exc).__name__}: {exc}"}


async def _component_report() -> dict[str, dict[str, str]]:
    """Run all three component checks concurrently.

    Checks are resolved through module globals at call time so tests can
    monkeypatch check_db, check_ollama, and check_model_files.
    """
    db, ollama, model_files = await asyncio.gather(
        _run_check("db", check_db),
        _run_check("ollama", check_ollama),
        _run_check("model_files", check_model_files),
    )
    return {"db": db, "ollama": ollama, "model_files": model_files}


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness: 200 iff the database is ok (SPEC 9.1).

    Ollama or model_files being down degrades but does not fail health,
    because labelled fallbacks exist (SPEC 6.8 and section 20).
    """
    components = await _component_report()
    db_ok = components["db"]["status"] == "ok"
    all_ok = all(c["status"] == "ok" for c in components.values())
    status = "ok" if all_ok else ("degraded" if db_ok else "down")
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={"status": status, "components": components},
    )


@app.get("/ready")
async def ready() -> JSONResponse:
    """Readiness: 200 only when db, ollama, and model files are all ok."""
    components = await _component_report()
    all_ok = all(c["status"] == "ok" for c in components.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ok" if all_ok else "down", "components": components},
    )
