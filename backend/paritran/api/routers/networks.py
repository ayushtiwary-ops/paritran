"""Network endpoints (SPEC 9.1): graph, communities, triage, trails.

Built from the completed run's in-process artifacts (linkage graph,
communities, triage scores, money trails). Every list is deterministic:
nodes sorted, edges sorted as (a, b) pairs, members sorted, communities
in the engine's frozen order, so two reads of the same run are
byte-identical.

- ``GET /api/networks?run_id=``: the whole graph (nodes, weighted edges)
  plus one summary per discovered network.
- ``GET /api/networks/{idx}?run_id=``: one network in full, including
  its money trail hops, break points (freeze opportunities), and the
  triage score next to all four of its inputs (SPEC 6.5).
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from paritran.api import runstore
from paritran.api.deps import limiter, require_role, role_rate_limit

__all__ = ["router"]

router = APIRouter(prefix="/api/networks", tags=["networks"])


class EdgeOut(BaseModel):
    a: int
    b: int
    w: int


class GraphOut(BaseModel):
    nodes: list[int]
    edges: list[EdgeOut]


class TriageOut(BaseModel):
    syndicate: int
    score: float
    inputs: dict[str, float] = Field(
        description="All four formula terms shown next to the score (SPEC 6.5)"
    )


class HopOut(BaseModel):
    src: str
    dst: str
    amount: int


class TrailOut(BaseModel):
    syndicate: int
    hops: list[HopOut]
    breaks: list[list[str]] = Field(
        description="Missing ledger edges, flagged as freeze opportunities"
    )
    traced_amt: int
    total_amt: int


class NetworkOut(BaseModel):
    index: int
    size: int
    members: list[int]
    syndicate: int | None = Field(
        description="Ground-truth majority syndicate (synthetic data only)"
    )
    triage: TriageOut | None
    trail: TrailOut | None


class NetworksResponse(BaseModel):
    run_id: str
    graph: GraphOut
    networks: list[NetworkOut]


def _majority_syndicate(members, truth: dict[int, int]) -> int | None:
    """Ground-truth majority syndicate of a community (noise excluded)."""
    counts = Counter(truth[cid] for cid in members if truth[cid] >= 0)
    if not counts:
        return None
    return min(counts, key=lambda s: (-counts[s], s))


def _completed_entry(run_id: str) -> runstore.RunEntry:
    entry = runstore.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id {run_id!r}")
    if entry.status != "completed" or entry.artifacts is None:
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id!r} is {entry.status}; networks are available"
            " once the run completes",
        )
    return entry


def _network_out(entry: runstore.RunEntry, idx: int) -> NetworkOut:
    artifacts = entry.artifacts
    communities = artifacts.linkage_result.communities
    if not 0 <= idx < len(communities):
        raise HTTPException(
            status_code=404,
            detail=f"network index {idx} out of range (run has {len(communities)})",
        )
    community = communities[idx]
    truth = {c.id: c.synd for c in artifacts.bundle.complaints}
    synd = _majority_syndicate(community, truth)

    triage = None
    trail = None
    if synd is not None:
        triage_row = next(
            (t for t in artifacts.triage_scores if t.syndicate == synd), None
        )
        if triage_row is not None:
            triage = TriageOut(
                syndicate=triage_row.syndicate,
                score=triage_row.score,
                inputs=dict(triage_row.inputs),
            )
        trail_row = next(
            (t for t in artifacts.trail_result.per_network if t.syndicate == synd),
            None,
        )
        if trail_row is not None:
            trail = TrailOut(
                syndicate=trail_row.syndicate,
                hops=[
                    HopOut(src=h.src, dst=h.dst, amount=h.amount)
                    for h in trail_row.hops
                ],
                breaks=[list(b) for b in trail_row.breaks],
                traced_amt=trail_row.traced_amt,
                total_amt=trail_row.total_amt,
            )

    return NetworkOut(
        index=idx,
        size=len(community),
        members=sorted(community),
        syndicate=synd,
        triage=triage,
        trail=trail,
    )


@router.get(
    "",
    response_model=NetworksResponse,
    summary="Graph and all discovered networks for one run",
    description=(
        "Officer or supervisor. Nodes, weighted linkage edges, and one"
        " summary per community of size >= 5 (SPEC 6.3), with triage"
        " inputs + score and the money trail per network. Deterministic"
        " ordering throughout."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted"},
        404: {"description": "unknown run_id"},
        409: {"description": "run not completed yet"},
    },
)
@limiter.limit(role_rate_limit)
async def list_networks(
    request: Request,
    run_id: str = Query(description="Run id from POST /api/intake/run"),
    identity: dict = Depends(require_role("officer")),
) -> NetworksResponse:
    entry = _completed_entry(run_id)
    graph = entry.artifacts.linkage_result.graph
    edges = sorted(
        (min(a, b), max(a, b), w) for a, b, w in graph.edges(data="w")
    )
    return NetworksResponse(
        run_id=run_id,
        graph=GraphOut(
            nodes=sorted(graph.nodes),
            edges=[EdgeOut(a=a, b=b, w=w) for a, b, w in edges],
        ),
        networks=[
            _network_out(entry, idx)
            for idx in range(len(entry.artifacts.linkage_result.communities))
        ],
    )


@router.get(
    "/{idx}",
    response_model=NetworkOut,
    summary="One network in full (members, triage, money trail, breaks)",
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted"},
        404: {"description": "unknown run_id or network index"},
        409: {"description": "run not completed yet"},
    },
)
@limiter.limit(role_rate_limit)
async def get_network(
    request: Request,
    idx: int,
    run_id: str = Query(description="Run id from POST /api/intake/run"),
    identity: dict = Depends(require_role("officer")),
) -> NetworkOut:
    entry = _completed_entry(run_id)
    return _network_out(entry, idx)
