"""SSE channels (SPEC 9.2, 9.3): pipeline run events and status ticks.

Hand-rolled ``text/event-stream`` over Starlette's StreamingResponse;
no extra dependency. Envelope per SPEC 9.3: every ``data:`` line is
JSON ``{ts, run_id?, stage?, payload}`` and the SSE ``event:`` field
carries the catalog event name.

Auth: any authenticated role. The browser EventSource API cannot set
request headers, so the JWT may arrive either as ``Authorization:
Bearer`` or as a ``?token=`` query parameter; verification is identical
(:func:`paritran.api.deps.sse_identity`).

- ``GET /api/stream/run/{run_id}``: replays every stored event for the
  run, then tails the live queue; a ``: keepalive`` comment goes out
  every 15 s of silence; the stream ends after ``run.completed`` (or
  ``run.failed``).
- ``GET /api/stream/status``: one ``status.tick`` every 2 s with the
  live component checks (same functions health/ready use) and p50/p95
  of recent request latencies from the main-module ring buffer. When no
  requests have been recorded the percentiles are null, honestly, never
  a made-up number.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from paritran.api import runstore
from paritran.api.deps import limiter, role_rate_limit, sse_identity

__all__ = ["router", "KEEPALIVE_SECONDS", "STATUS_TICK_SECONDS"]

router = APIRouter(prefix="/api/stream", tags=["stream"])

KEEPALIVE_SECONDS = 15.0
STATUS_TICK_SECONDS = 2.0

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def format_event(evt: dict) -> str:
    """One SSE frame: ``event:`` name plus the SPEC 9.3 JSON envelope."""
    data = {
        "ts": evt.get("ts"),
        "run_id": evt.get("run_id"),
        "stage": evt.get("stage"),
        "payload": evt.get("payload", {}),
    }
    return f"event: {evt['event']}\ndata: {json.dumps(data, default=str)}\n\n"


@router.get(
    "/run/{run_id}",
    summary="Stream one run's pipeline events (SSE)",
    description=(
        "Replays every event recorded so far for the run, then streams live"
        " events until run.completed (or run.failed). Token via"
        " Authorization: Bearer header or ?token= query parameter"
        " (EventSource cannot set headers). Keepalive comment every 15 s."
    ),
    responses={
        200: {"content": {"text/event-stream": {}}},
        401: {"description": "missing or invalid token"},
        404: {"description": "unknown run_id"},
    },
)
@limiter.limit(role_rate_limit)
async def stream_run(
    request: Request,
    run_id: str,
    identity: dict = Depends(sse_identity),
) -> StreamingResponse:
    entry = runstore.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id {run_id!r}")

    async def gen():
        snapshot, queue = runstore.subscribe(entry)
        try:
            terminal = False
            for evt in snapshot:
                yield format_event(evt)
                if evt["event"] in runstore.TERMINAL_EVENTS:
                    terminal = True
            while not terminal:
                try:
                    evt = await asyncio.wait_for(
                        queue.get(), timeout=KEEPALIVE_SECONDS
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    yield ": keepalive\n\n"
                    continue
                yield format_event(evt)
                if evt["event"] in runstore.TERMINAL_EVENTS:
                    terminal = True
        finally:
            runstore.unsubscribe(entry, queue)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@router.get(
    "/status",
    summary="Stream system status ticks (SSE)",
    description=(
        "One status.tick every 2 s: component checks (db, ollama, model"
        " files, the same functions /health uses) and p50/p95 of recent"
        " request latencies from the in-process ring buffer. Percentiles"
        " are null until requests have been recorded. Token via header or"
        " ?token= query parameter."
    ),
    responses={
        200: {"content": {"text/event-stream": {}}},
        401: {"description": "missing or invalid token"},
    },
)
@limiter.limit(role_rate_limit)
async def stream_status(
    request: Request,
    identity: dict = Depends(sse_identity),
) -> StreamingResponse:
    # Imported lazily: main imports this router at module load, so a
    # top-level import back into main would be circular.
    from paritran.api import main as api_main

    async def gen():
        while True:
            components = await api_main._component_report()
            evt = {
                "event": "status.tick",
                "ts": time.time(),
                "run_id": None,
                "stage": None,
                "payload": {
                    "components": components,
                    "latency": api_main.latency_percentiles(),
                    "runs": {
                        "total": len(runstore.list_runs()),
                        "running": sum(
                            1
                            for r in runstore.list_runs()
                            if r.status == "running"
                        ),
                    },
                },
            }
            yield format_event(evt)
            await asyncio.sleep(STATUS_TICK_SECONDS)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
