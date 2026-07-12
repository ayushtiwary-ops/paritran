"""Officer decisions (SPEC 9.1, 8.1): ``POST /api/decisions``.

Every accept/reject of a link or claim appends one row to the
DB-enforced audit chain via ``repo.append_audit`` (the BEFORE INSERT
trigger owns seq, ts, prev_hash, and hash; SPEC 7.2). The response
returns exactly what the database assigned, so the caller can render
the chain growing live.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from paritran.api.deps import limiter, require_role, role_rate_limit
from paritran.db import repo

__all__ = ["router"]

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


class DecisionRequest(BaseModel):
    run_id: str = Field(description="Run the decision applies to")
    kind: Literal["link", "claim"]
    ref: dict = Field(
        description=(
            "What is being decided, e.g. {'a': 12, 'b': 41} for a link or"
            " {'section': 'BNS 318', 'quote': '...'} for a claim"
        )
    )
    decision: Literal["accept", "reject"]


class DecisionAppended(BaseModel):
    seq: int
    hash: str
    prev_hash: str
    action: str


@router.post(
    "",
    response_model=DecisionAppended,
    summary="Record an officer decision on the audit chain",
    description=(
        "Officer or supervisor. Appends action"
        " decision.<kind>.<decision> (e.g. decision.link.reject) to the"
        " append-only audit chain; seq, hash, and prev_hash are assigned"
        " by the database trigger, never by this API (SPEC 7.2)."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted"},
    },
)
@limiter.limit(role_rate_limit)
async def post_decision(
    request: Request,
    body: DecisionRequest,
    identity: dict = Depends(require_role("officer")),
) -> DecisionAppended:
    action = f"decision.{body.kind}.{body.decision}"
    row = await repo.append_audit(
        actor=identity["sub"],
        action=action,
        payload={
            "run_id": body.run_id,
            "kind": body.kind,
            "ref": body.ref,
            "decision": body.decision,
            "role": identity["role"],
        },
    )
    return DecisionAppended(
        seq=row["seq"], hash=row["hash"], prev_hash=row["prev_hash"], action=action
    )
