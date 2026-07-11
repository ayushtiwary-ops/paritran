"""Paritran API application.

This milestone (Milestone 1, repo skeleton) exposes:

- GET /health: 200 when the database is reachable, else 503. Ollama or
  model-file failures are reported per component but do not fail health,
  because the engine has labelled degrade paths for both: the
  deterministic fabricating stub behind the identical generator
  interface (SPEC 6.8) and the BM25 plus rules mapping path with a
  mandatory review flag (SPEC section 20).
- GET /ready: 200 only when db, ollama, and model files are all ok.
- GET /metrics: Prometheus scrape endpoint via
  prometheus-fastapi-instrumentator (SPEC section 12).

Every component check is capped at 2 seconds (SPEC 9.1 and 12).
The routers of SPEC section 9.1 and the SSE channels of 9.2 are
deferred to Milestone 4. OpenTelemetry FastAPIInstrumentor wiring is
deferred to Milestone 8 (observability).
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from paritran.config import get_settings
from paritran.db import repo
from paritran.db.migrate import run_migrations
from paritran.db.seed import seed_users

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0


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
        try:
            applied = await asyncio.to_thread(
                run_migrations, settings.ADMIN_DATABASE_URL, settings.APP_DB_PASSWORD
            )
            ensured = await asyncio.to_thread(seed_users, settings)
        except psycopg.OperationalError as exc:
            raise RuntimeError(
                "startup aborted: database unreachable while running "
                f"migrations/seed over ADMIN_DATABASE_URL ({type(exc).__name__}). "
                "Check that the db service is up and the DSN host/port are correct."
            ) from exc
        logger.info(
            "startup migrations applied=%s seeded_users=%s", applied, ensured
        )
        await repo.init_pool(settings.DATABASE_URL)
    yield
    await repo.close_pool()


app = FastAPI(
    title="Paritran API",
    version="0.1.0",
    description="From complaint to conviction. On-premise court-admissibility engine.",
    lifespan=lifespan,
)

Instrumentator().instrument(app).expose(app)


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
