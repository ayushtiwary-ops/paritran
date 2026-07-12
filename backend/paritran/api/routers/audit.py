"""Audit chain endpoints (SPEC 9.1, 7.2, 8.3).

- ``GET /api/audit/chain`` (any authed): the ledger rows in seq order
  with per-row hash and prev-hash linkage.
- ``GET /api/audit/verify`` (any authed): runs the database's
  ``verify_audit_chain()`` (one canonical encoding, in one place, in
  the database) and reports the first bad seq, or a clean chain.
- ``POST /api/audit/tamper-test`` (auditor only): the SPEC 8.3
  demonstration. The chain is snapshotted into a TEMP scratch table
  with none of the real table's protections, ONE mid-chain payload is
  corrupted there, and verification runs over the scratch copy in SQL
  mirroring verify_audit_chain semantics (same canonical preimage, same
  prev-hash walk). The real audit_log is never modified; the act of
  running the tamper test is itself appended to the real chain.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from paritran.api.deps import (
    db_pool,
    limiter,
    require_authenticated,
    require_role,
    role_rate_limit,
)
from paritran.db import repo

__all__ = ["router"]

router = APIRouter(prefix="/api/audit", tags=["audit"])

# Minimum rows for a meaningful mid-chain corruption (a first or last
# row is not "mid-chain").
MIN_TAMPER_ROWS = 3

# Recompute the SPEC 7.2 canonical preimage over the scratch copy and
# walk prev-hash linkage exactly as verify_audit_chain() does; the first
# offending seq is the break. Window lag() gives each row its
# predecessor's stored hash (genesis 64 zeros for the first row).
_SCRATCH_VERIFY_SQL = """
SELECT seq FROM (
  SELECT
    seq,
    hash,
    prev_hash,
    encode(digest(jsonb_build_object(
        'prev', prev_hash,
        'actor', actor,
        'action', action,
        'payload', payload,
        'ts_epoch', extract(epoch FROM ts)::text
      )::text, 'sha256'), 'hex') AS recomputed,
    coalesce(lag(hash) OVER (ORDER BY seq), repeat('0', 64)) AS expected_prev
  FROM audit_scratch
) walk
WHERE prev_hash <> expected_prev OR recomputed <> hash
ORDER BY seq
LIMIT 1
"""


class AuditRow(BaseModel):
    seq: int
    ts: str
    actor: str
    action: str
    payload: dict
    prev_hash: str
    hash: str


class ChainPage(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[AuditRow]


class VerifyResult(BaseModel):
    ok: bool
    first_bad_seq: int | None = Field(
        description="Seq of the first row failing recomputation; null when clean"
    )


class TamperTestResult(BaseModel):
    break_seq: int = Field(
        description="Where verification over the corrupted scratch copy breaks"
    )
    corrupted_seq: int = Field(description="The scratch row whose payload was edited")
    scratch_rows: int
    real_chain_ok: bool = Field(
        description="verify_audit_chain() over the REAL chain, run afterwards"
    )
    audit_seq: int = Field(
        description="Seq of the tamper_test.run row appended to the real chain"
    )


@router.get(
    "/chain",
    response_model=ChainPage,
    summary="The audit ledger (hash chain rows)",
    description="Any authenticated role. Rows in seq order with hash linkage.",
    responses={401: {"description": "missing or invalid token"}},
)
@limiter.limit(role_rate_limit)
async def get_chain(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    identity: dict = Depends(require_authenticated),
) -> ChainPage:
    pool = await db_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT count(*) FROM audit_log")
        (total,) = await cursor.fetchone()
        cursor = await conn.execute(
            "SELECT seq, ts, actor, action, payload, prev_hash, hash"
            " FROM audit_log ORDER BY seq LIMIT %s OFFSET %s",
            (limit, offset),
        )
        rows = await cursor.fetchall()
    return ChainPage(
        total=total,
        limit=limit,
        offset=offset,
        rows=[
            AuditRow(
                seq=seq,
                ts=ts.isoformat(),
                actor=actor,
                action=action,
                payload=payload,
                prev_hash=prev_hash,
                hash=hash_,
            )
            for seq, ts, actor, action, payload, prev_hash, hash_ in rows
        ],
    )


@router.get(
    "/verify",
    response_model=VerifyResult,
    summary="Verify the real audit chain",
    description=(
        "Any authenticated role. Runs verify_audit_chain() in the database"
        " (SPEC 7.2): the whole chain is recomputed from genesis with the"
        " canonical preimage; returns the first bad seq or ok=true."
    ),
    responses={401: {"description": "missing or invalid token"}},
)
@limiter.limit(role_rate_limit)
async def verify(
    request: Request,
    identity: dict = Depends(require_authenticated),
) -> VerifyResult:
    first_bad = await repo.verify_chain()
    return VerifyResult(ok=first_bad is None, first_bad_seq=first_bad)


@router.post(
    "/tamper-test",
    response_model=TamperTestResult,
    summary="Scratch-copy tamper demonstration (SPEC 8.3)",
    description=(
        "Auditor only. Snapshots the chain into a TEMP scratch table (no"
        " triggers, no protections), corrupts one mid-chain payload THERE,"
        " and verifies the scratch copy in SQL mirroring"
        " verify_audit_chain semantics: the chain visibly breaks at the"
        " corrupted record. The real chain is never touched, is"
        " re-verified afterwards, and gains a tamper_test.run row."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted (auditor only)"},
        409: {"description": "chain too short for a mid-chain corruption"},
    },
)
@limiter.limit(role_rate_limit)
async def tamper_test(
    request: Request,
    identity: dict = Depends(require_role("auditor")),
) -> TamperTestResult:
    pool = await db_pool()
    async with pool.connection() as conn:
        # One transaction: the TEMP table lives exactly as long as the demo.
        await conn.execute(
            "CREATE TEMP TABLE audit_scratch ON COMMIT DROP AS"
            " SELECT seq, ts, actor, action, payload, prev_hash, hash"
            " FROM audit_log"
        )
        cursor = await conn.execute("SELECT count(*) FROM audit_scratch")
        (n_rows,) = await cursor.fetchone()
        if n_rows < MIN_TAMPER_ROWS:
            raise HTTPException(
                status_code=409,
                detail=f"audit chain has {n_rows} rows; the tamper test needs"
                f" at least {MIN_TAMPER_ROWS} for a mid-chain corruption",
            )

        # Pick the middle row: never the first, never the last.
        cursor = await conn.execute(
            "SELECT seq FROM audit_scratch ORDER BY seq OFFSET %s LIMIT 1",
            (n_rows // 2,),
        )
        (corrupt_seq,) = await cursor.fetchone()

        # The corruption the real table's triggers would reject outright.
        await conn.execute(
            "UPDATE audit_scratch SET payload ="
            " jsonb_set(payload, '{tampered}', 'true') WHERE seq = %s",
            (corrupt_seq,),
        )

        cursor = await conn.execute(_SCRATCH_VERIFY_SQL)
        row = await cursor.fetchone()
        break_seq = row[0] if row else None

    if break_seq is None:  # would mean the corruption was not detected
        raise HTTPException(
            status_code=500,
            detail="tamper test failed to break the scratch chain; this is a bug",
        )

    # The real chain must still verify, and the demo itself is chained.
    real_first_bad = await repo.verify_chain()
    audit_row = await repo.append_audit(
        actor=identity["sub"],
        action="tamper_test.run",
        payload={
            "break_seq": break_seq,
            "corrupted_seq": corrupt_seq,
            "scratch_rows": n_rows,
            "real_chain_ok": real_first_bad is None,
        },
    )
    return TamperTestResult(
        break_seq=break_seq,
        corrupted_seq=corrupt_seq,
        scratch_rows=n_rows,
        real_chain_ok=real_first_bad is None,
        audit_seq=audit_row["seq"],
    )
