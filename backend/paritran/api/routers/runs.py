"""Run status endpoint (SPEC 9.1): ``GET /api/runs/{run_id}``.

Reads the in-process runstore. The results dict is exactly what the
pipeline computed for this run (numeric truth rule, SPEC section 1);
``db_run_id`` and ``eval_run_id`` are set once persistence lands, and
``persist_error`` reports a persistence failure honestly instead of
hiding it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from paritran.api import runstore
from paritran.api.deps import limiter, require_role, role_rate_limit

__all__ = ["router"]

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunStatus(BaseModel):
    run_id: str
    seed: int
    generator: str
    status: str = Field(description="running | completed | failed")
    n_events: int
    results: dict | None = Field(
        default=None, description="Pipeline results dict once completed (SPEC 6.11)"
    )
    db_run_id: int | None = None
    eval_run_id: int | None = None
    error: str | None = None
    persist_error: str | None = None


@router.get(
    "/{run_id}",
    response_model=RunStatus,
    summary="Run status and results",
    description=(
        "Officer or supervisor. Status plus, once completed, the full"
        " results dict (every value computed by this run's engine stages)."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted"},
        404: {"description": "unknown run_id"},
    },
)
@limiter.limit(role_rate_limit)
async def get_run(
    request: Request,
    run_id: str,
    identity: dict = Depends(require_role("officer")),
) -> RunStatus:
    entry = runstore.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id {run_id!r}")
    return RunStatus(
        run_id=entry.run_id,
        seed=entry.seed,
        generator=entry.generator,
        status=entry.status,
        n_events=len(entry.events),
        results=entry.results,
        db_run_id=entry.db_run_id,
        eval_run_id=entry.eval_run_id,
        error=entry.error,
        persist_error=entry.persist_error,
    )
