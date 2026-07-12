"""SSE end-to-end tests (SPEC 9.2, 9.3, 16).

A real uvicorn server is started on an ephemeral localhost port inside
the test's event loop, and httpx.AsyncClient streams over actual HTTP:
frames arrive live while the pipeline thread runs, which is exactly the
production transport (an in-process ASGI transport would buffer the
whole body and prove nothing about streaming).

The repo pool is initialized against the fixture DSN explicitly because
the server runs with lifespan off (the conftest forces
RUN_MIGRATIONS_ON_STARTUP=false either way).
"""

import asyncio
import json
import os

import httpx
import pytest
import uvicorn

import paritran.api.main as main
import paritran.api.runstore as runstore
from paritran import pipeline
from paritran.api import deps
from paritran.config import get_settings
from paritran.db import repo
from paritran.db.seed import seed_users

pytestmark = pytest.mark.db

TEST_JWT_SECRET = "test-only-jwt-secret-64-chars-not-a-real-credential-0000000000"
RUN_DEADLINE_SECONDS = 240


class _Server:
    """uvicorn on 127.0.0.1:<ephemeral>, on the current event loop."""

    def __init__(self):
        config = uvicorn.Config(
            main.app, host="127.0.0.1", port=0, log_level="warning", lifespan="off"
        )
        self.server = uvicorn.Server(config)
        self.task: asyncio.Task | None = None

    async def __aenter__(self) -> str:
        self.task = asyncio.create_task(self.server.serve())
        while not self.server.started:
            if self.task.done():  # startup failure surfaces, not a hang
                self.task.result()
            await asyncio.sleep(0.02)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    async def __aexit__(self, *exc):
        self.server.should_exit = True
        await asyncio.wait_for(self.task, timeout=10)


async def _setup(db, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", db.app_dsn)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    await asyncio.to_thread(seed_users, get_settings())
    monkeypatch.setattr(runstore, "_MAPPER_CACHE", [None])
    deps.limiter.reset()
    # Init the repo pool against the fixture DSN explicitly (lifespan off).
    await repo.close_pool()
    await repo.init_pool(db.app_dsn)


async def _teardown() -> None:
    await repo.close_pool()
    get_settings.cache_clear()


async def _login(client: httpx.AsyncClient, username: str, password_var: str) -> str:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": os.environ[password_var]},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _collect_run_events(client, run_id: str, token: str) -> list[tuple[str, dict]]:
    """Stream /api/stream/run/{run_id} (query-param token, the EventSource
    transport) until the server closes it after run.completed."""
    events: list[tuple[str, dict]] = []
    current = None
    async with client.stream(
        "GET", f"/api/stream/run/{run_id}", params={"token": token}
    ) as response:
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                current = line[len("event: ") :]
            elif line.startswith("data: ") and current is not None:
                events.append((current, json.loads(line[len("data: ") :])))
                current = None
    return events


@pytest.mark.asyncio
async def test_sse_run_stream_end_to_end(db, monkeypatch):
    await _setup(db, monkeypatch)
    try:
        async with _Server() as base_url:
            async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
                token = await _login(client, "officer1", "OFFICER1_PASSWORD")
                headers = {"Authorization": f"Bearer {token}"}

                started = await client.post(
                    "/api/intake/run",
                    json={"seed": 42, "generator": "stub"},
                    headers=headers,
                )
                assert started.status_code == 202, started.text
                run_id = started.json()["run_id"]

                events = await asyncio.wait_for(
                    _collect_run_events(client, run_id, token),
                    timeout=RUN_DEADLINE_SECONDS,
                )

                names = [name for name, _ in events]
                assert names[0] == "run.started"
                # The stream ends by itself right after run.completed.
                assert names[-1] == "run.completed"
                assert names.count("run.completed") == 1

                # stage.started for all nine stages, in execution order
                # (f9_audit before packet, SPEC 6.10 / pipeline docstring).
                started_stages = [
                    data["stage"] for name, data in events if name == "stage.started"
                ]
                assert started_stages == list(pipeline.EXECUTION_ORDER)
                assert set(started_stages) == set(pipeline.STAGES)
                completed_stages = [
                    data["stage"] for name, data in events if name == "stage.completed"
                ]
                assert set(completed_stages) == set(pipeline.STAGES)

                # Envelope shape (SPEC 9.3) and honest payloads.
                for name, data in events:
                    assert {"ts", "run_id", "stage", "payload"} <= set(data)
                    assert data["run_id"] == run_id
                final = events[-1][1]["payload"]
                assert final["seed"] == 42
                assert final["n_complaints"] == 297

                # Replay: a second subscriber AFTER completion gets the
                # identical event sequence and the stream still terminates.
                replay = await asyncio.wait_for(
                    _collect_run_events(client, run_id, token), timeout=30
                )
                assert [n for n, _ in replay] == names
    finally:
        await _teardown()


@pytest.mark.asyncio
async def test_sse_status_ticks_and_auth(db, monkeypatch):
    await _setup(db, monkeypatch)
    try:
        async with _Server() as base_url:
            async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
                token = await _login(client, "auditor1", "AUDITOR1_PASSWORD")
                headers = {"Authorization": f"Bearer {token}"}

                # No token: both channels are closed (401).
                denied = await client.get("/api/stream/status")
                assert denied.status_code == 401
                denied = await client.get("/api/stream/run/whatever")
                assert denied.status_code == 401

                # Unknown run with a valid token: 404.
                missing = await client.get(
                    "/api/stream/run/no-such-run", headers=headers
                )
                assert missing.status_code == 404

                # Header-auth status stream: read the first tick, then close.
                tick = None
                async with client.stream(
                    "GET", "/api/stream/status", headers=headers
                ) as response:
                    assert response.status_code == 200
                    current = None
                    async for line in response.aiter_lines():
                        if line.startswith("event: "):
                            current = line[len("event: ") :]
                        elif line.startswith("data: ") and current == "status.tick":
                            tick = json.loads(line[len("data: ") :])
                            break
                assert tick is not None
                payload = tick["payload"]
                assert set(payload["components"]) == {"db", "ollama", "model_files"}
                # The fixture database is really reachable.
                assert payload["components"]["db"]["status"] == "ok"
                latency = payload["latency"]
                assert {"count", "p50_ms", "p95_ms"} <= set(latency)
                # Requests above were recorded by the ring buffer.
                assert latency["count"] >= 1
                assert latency["p50_ms"] is not None
                assert latency["p95_ms"] >= latency["p50_ms"]
    finally:
        await _teardown()
