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

Milestone 8 (SPEC 8.4, 12): after every successful append the row's
{seq, hash, prev_hash} is handed to the registered append hooks so the
API layer can refresh the out-of-band chain-head anchor metric. Hooks
observe; they never gate. A hook failure is logged and swallowed so
observability can never break a custody write.
"""

import logging
from typing import Callable

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None

# Post-append observers (Milestone 8): each receives the appended row's
# {seq, hash, prev_hash}. Module-level so registration survives app
# factories; list order is registration order.
_APPEND_HOOKS: list[Callable[[dict], None]] = []


def register_append_hook(hook: Callable[[dict], None]) -> None:
    """Register a post-append observer; idempotent per function object."""
    if hook not in _APPEND_HOOKS:
        _APPEND_HOOKS.append(hook)


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
    result = {"seq": row[0], "hash": row[1], "prev_hash": row[2]}
    for hook in list(_APPEND_HOOKS):
        try:
            hook(result)
        except Exception:  # noqa: BLE001 - observers never break custody writes
            log.warning("audit append hook %r failed", hook, exc_info=True)
    return result


async def get_chain_head() -> dict | None:
    """Latest audit row as {seq, hash, prev_hash}; None when the chain is empty.

    Used at startup to prime the SPEC 8.4 chain-head anchor metric before
    the first in-process append fires the hooks.
    """
    pool = await _acquire_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT seq, hash, prev_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return {"seq": row[0], "hash": row[1], "prev_hash": row[2]}


async def verify_chain() -> int | None:
    """Run verify_audit_chain(); None when clean, else first bad seq."""
    pool = await _acquire_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute("SELECT verify_audit_chain()")
        row = await cursor.fetchone()
    return row[0]
