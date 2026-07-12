"""Demo-mode endpoints (SPEC 9.1, 14).

- ``POST /api/demo/start`` (supervisor): launches the real seed-42 stub
  pipeline through the run registry and a paced five-beat narrator over
  it (``paritran.demo``). Returns the run id plus both stream urls: the
  pipeline's own events on ``/api/stream/run/{run_id}`` and the beats on
  ``/api/stream/demo/{demo_id}``.
- ``POST /api/demo/plant-fabrication`` (supervisor): pushes one known-bad,
  labelled claim through the SAME F9 gate path against corpus v2 and
  returns the live verdict, proving the gate blocks it (SPEC 6.8, 14).
- ``GET /api/stream/demo/{demo_id}`` (any authed): replays the demo's
  beats so far, then tails live ones until ``demo.completed`` (or
  ``demo.failed``); a keepalive comment every 15 s.

No demo number is canned: every beat and every verdict is produced by the
real engine on this run (SPEC section 1). The narrator only paces WHEN a
real fact is revealed.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from paritran import demo
from paritran.api import sse
from paritran.api.deps import (
    limiter,
    require_role,
    role_rate_limit,
    sse_identity,
)

__all__ = ["router"]

router = APIRouter(tags=["demo"])


class DemoStarted(BaseModel):
    demo_id: str
    run_id: str
    seed: int
    generator: str
    demo_stream_url: str = Field(
        description="SSE of the paced beats; open until demo.completed"
    )
    run_stream_url: str = Field(
        description="SSE of the pipeline's own events (SPEC 9.3), closes on"
        " run.completed"
    )


class PlantedVerdict(BaseModel):
    label: str = Field(description="Always marks the claim as planted")
    section: str
    quote: str
    is_fabricated: bool | None
    verdict: str = Field(description="PASSED or WITHHELD, the live gate result")
    sub_class: str | None
    corpus_version: str
    generator_name: str
    blocked: bool = Field(description="True when the gate WITHHELD the claim")
    gate_rule: str


@router.post(
    "/api/demo/start",
    response_model=DemoStarted,
    status_code=202,
    summary="Start the paced demo narrative over a real seed-42 run",
    description=(
        "Supervisor only. Launches the deterministic seed-42 stub pipeline"
        " (SPEC 6.11) and a five-beat narrator (SPEC 14) over it. Every beat"
        " quotes the real run; the planted fabrication is blocked by the"
        " real F9 gate and the tamper test is the engine's own (SPEC 6.9)."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted (supervisor only)"},
    },
)
@limiter.limit(role_rate_limit)
async def start_demo(
    request: Request,
    identity: dict = Depends(require_role("supervisor")),
) -> DemoStarted:
    entry = await demo.start_demo(actor=identity["sub"])
    return DemoStarted(
        demo_id=entry.demo_id,
        run_id=entry.run_id,
        seed=42,
        generator="stub",
        demo_stream_url=f"/api/stream/demo/{entry.demo_id}",
        run_stream_url=f"/api/stream/run/{entry.run_id}",
    )


@router.post(
    "/api/demo/plant-fabrication",
    response_model=PlantedVerdict,
    summary="Push one planted fabrication through the F9 gate (corpus v2)",
    description=(
        "Supervisor only. Injects one known-bad, labelled claim (a real"
        " section id with a fabricated quote) through the SAME verbatim F9"
        " gate the pipeline uses, against corpus v2 bare-act text. The"
        " gate withholds it live; the response carries the verdict."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted (supervisor only)"},
    },
)
@limiter.limit(role_rate_limit)
async def plant_fabrication(
    request: Request,
    identity: dict = Depends(require_role("supervisor")),
) -> PlantedVerdict:
    result = await asyncio.to_thread(demo.plant_fabrication)
    return PlantedVerdict(**result)


@router.get(
    "/api/stream/demo/{demo_id}",
    summary="Stream one demo's paced beats (SSE)",
    description=(
        "Any authenticated role. Replays every beat recorded so far, then"
        " streams live beats until demo.completed (or demo.failed). Token"
        " via Authorization: Bearer header or ?token= query parameter"
        " (EventSource cannot set headers). Keepalive comment every 15 s."
    ),
    responses={
        200: {"content": {"text/event-stream": {}}},
        401: {"description": "missing or invalid token"},
        404: {"description": "unknown demo_id"},
    },
)
@limiter.limit(role_rate_limit)
async def stream_demo(
    request: Request,
    demo_id: str,
    identity: dict = Depends(sse_identity),
) -> StreamingResponse:
    entry = demo.get(demo_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown demo_id {demo_id!r}")

    async def gen():
        snapshot, queue = demo.subscribe(entry)
        try:
            terminal = False
            for evt in snapshot:
                yield sse.format_event(evt)
                if evt["event"] in demo.TERMINAL_EVENTS:
                    terminal = True
            while not terminal:
                try:
                    evt = await asyncio.wait_for(
                        queue.get(), timeout=sse.KEEPALIVE_SECONDS
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    yield ": keepalive\n\n"
                    continue
                yield sse.format_event(evt)
                if evt["event"] in demo.TERMINAL_EVENTS:
                    terminal = True
        finally:
            demo.unsubscribe(entry, queue)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=sse._SSE_HEADERS
    )
