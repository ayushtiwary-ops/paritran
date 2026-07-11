"""Async application-side data access over DATABASE_URL (SPEC 7, 8).

A single module-level psycopg_pool.AsyncConnectionPool, created closed
by init_pool and opened lazily on first use, so constructing the app
(and unit tests with RUN_MIGRATIONS_ON_STARTUP=false) never dials the
database.

append_audit inserts only (actor, action, payload). The BEFORE INSERT
trigger of SPEC 7.2 owns prev_hash and hash; Python never computes or
supplies either value. verify_chain delegates to the SQL function
verify_audit_chain() for the same reason: one canonical encoding, in
one place, in the database.
"""

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


async def init_pool(dsn: str) -> AsyncConnectionPool:
    """Create the process-wide pool (closed); idempotent."""
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(dsn, min_size=1, max_size=10, open=False)
    return _pool


async def close_pool() -> None:
    """Close and drop the pool; safe to call when never initialized."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def _acquire_pool() -> AsyncConnectionPool:
    """Return the pool, opening it on first use (lazy open)."""
    if _pool is None:
        raise RuntimeError("db pool not initialized; call init_pool(dsn) first")
    if _pool.closed:
        await _pool.open()
    return _pool


async def append_audit(actor: str, action: str, payload: dict) -> dict:
    """Append one audit row; return {seq, hash, prev_hash} from the DB.

    prev_hash and hash are intentionally absent from the INSERT column
    list: the SPEC 7.2 trigger sets both and never trusts client values.
    """
    pool = await _acquire_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "INSERT INTO audit_log (actor, action, payload) "
            "VALUES (%s, %s, %s) RETURNING seq, hash, prev_hash",
            (actor, action, Jsonb(payload)),
        )
        row = await cursor.fetchone()
    return {"seq": row[0], "hash": row[1], "prev_hash": row[2]}


async def verify_chain() -> int | None:
    """Run verify_audit_chain(); None when clean, else first bad seq."""
    pool = await _acquire_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT verify_audit_chain()")
        row = await cursor.fetchone()
    return row[0]
