"""Evaluation endpoints (SPEC 9.1, 13).

- ``GET /api/evaluation/metrics`` (any authed): eval_runs rows, latest
  first. Every row was written by a real pipeline run (SPEC 13).
- ``POST /api/evaluation/reproduce`` (supervisor): starts a fresh
  seed-42 stub run through the same runstore as /api/intake/run (its
  events stream on /api/stream/run/{run_id}) and returns the committed
  baseline (results.json) so the caller can diff fresh against frozen
  in front of the judge (SPEC 6.1). A judge's-seed rerun is NOT a
  separate endpoint: POST /api/intake/run with any seed reruns the full
  engine and every displayed metric moves with it (SPEC 17 step 7b).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from paritran.api import runstore
from paritran.api.deps import (
    db_pool,
    limiter,
    require_authenticated,
    require_role,
    role_rate_limit,
)

__all__ = ["router"]

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

BASELINE_SEED = 42


def _oracle_path() -> Path:
    """The committed baseline: PARITRAN_RESULTS_JSON or repo results.json.

    Same resolution the test suite uses (tests/_paths.py): the compose
    stack mounts the repo's results.json and points the env var at it;
    on a host checkout the file sits four levels above this module.
    """
    env = os.environ.get("PARITRAN_RESULTS_JSON")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "results.json"


class EvalRunRow(BaseModel):
    id: int
    created_at: str
    git_sha: str | None
    dataset_version: str | None
    corpus_version: str | None
    generator: str | None
    model_tag: str | None
    metrics: dict | None
    latencies: dict | None
    sample_sizes: dict | None


class EvalRunsPage(BaseModel):
    rows: list[EvalRunRow] = Field(description="Latest first")


class ReproduceStarted(BaseModel):
    run_id: str
    seed: int
    generator: str
    stream_url: str
    baseline: dict = Field(
        description="The committed seed-42 oracle (results.json); the fresh"
        " run's deterministic keys must equal these exactly (SPEC 6.1)"
    )


@router.get(
    "/metrics",
    response_model=EvalRunsPage,
    summary="Evaluation history (eval_runs rows, latest first)",
    description=(
        "Any authenticated role. Each row records git SHA, dataset and"
        " corpus versions, generator + model tag, every SPEC 6.1 metric,"
        " per-stage latencies, and sample sizes (SPEC 13)."
    ),
    responses={401: {"description": "missing or invalid token"}},
)
@limiter.limit(role_rate_limit)
async def metrics(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    identity: dict = Depends(require_authenticated),
) -> EvalRunsPage:
    pool = await db_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT id, created_at, git_sha, dataset_version, corpus_version,"
            " generator, model_tag, metrics, latencies, sample_sizes"
            " FROM eval_runs ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        rows = await cursor.fetchall()
    return EvalRunsPage(
        rows=[
            EvalRunRow(
                id=r[0],
                created_at=r[1].isoformat(),
                git_sha=r[2],
                dataset_version=r[3],
                corpus_version=r[4],
                generator=r[5],
                model_tag=r[6],
                metrics=r[7],
                latencies=r[8],
                sample_sizes=r[9],
            )
            for r in rows
        ]
    )


@router.post(
    "/reproduce",
    response_model=ReproduceStarted,
    status_code=202,
    summary="Reproduce the seed-42 baseline live",
    description=(
        "Supervisor only. Starts a seed-42 deterministic-stub run through"
        " the same run registry as /api/intake/run; progress streams on"
        " /api/stream/run/{run_id} and the response carries the committed"
        " baseline for on-screen comparison. For a judge's-seed rerun use"
        " POST /api/intake/run with any seed: no canned value survives an"
        " arbitrary seed (SPEC 17 step 7b)."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted (supervisor only)"},
        500: {"description": "committed baseline results.json not found"},
    },
)
@limiter.limit(role_rate_limit)
async def reproduce(
    request: Request,
    identity: dict = Depends(require_role("supervisor")),
) -> ReproduceStarted:
    oracle = _oracle_path()
    if not oracle.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"committed baseline not found at {oracle}; set"
            " PARITRAN_RESULTS_JSON or restore results.json",
        )
    baseline = json.loads(oracle.read_text(encoding="utf-8"))
    entry = await runstore.start_run(seed=BASELINE_SEED, generator="stub")
    return ReproduceStarted(
        run_id=entry.run_id,
        seed=entry.seed,
        generator=entry.generator,
        stream_url=f"/api/stream/run/{entry.run_id}",
        baseline=baseline,
    )
