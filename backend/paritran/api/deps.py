"""API dependencies: JWT decoding, role gates, rate limiting (SPEC 5, 9).

Role model (SPEC section 5): ``officer`` runs the pipeline and makes
link/claim decisions; ``supervisor`` holds every officer right plus the
evaluation controls; ``auditor`` is read-only plus the custody chain and
the tamper test. :func:`require_role` encodes exactly that: requiring
``officer`` automatically admits ``supervisor``, and nothing else is ever
implied.

Rate limiting (SPEC section 5): slowapi keyed by the JWT ``sub`` claim,
falling back to the client IP for anonymous requests. Limits by role:
officer and supervisor 120/min, auditor 60/min, anonymous 20/min. The
key embeds the role (``role:sub``) so slowapi's dynamic limit provider
can pick the right limit; keys are scoped per route by slowapi, so a
burst against one endpoint never starves another.

Token transport: ``Authorization: Bearer <jwt>`` everywhere. The SSE
endpoints additionally accept ``?token=<jwt>`` because the browser
EventSource API cannot set request headers (SPEC 9.2); the token is
verified identically either way.
"""

from __future__ import annotations

import jwt
from fastapi import HTTPException, Request
from psycopg_pool import AsyncConnectionPool
from slowapi import Limiter
from slowapi.util import get_remote_address

from paritran.config import get_settings
from paritran.db import repo

__all__ = [
    "ROLES",
    "db_pool",
    "decode_token",
    "limiter",
    "require_authenticated",
    "require_role",
    "role_rate_limit",
    "sse_identity",
]

ROLES = ("officer", "supervisor", "auditor")

_ALGORITHM = "HS256"


async def db_pool() -> AsyncConnectionPool:
    """The process-wide repo pool, opened lazily (public repo API only)."""
    pool = await repo.init_pool(get_settings().DATABASE_URL)
    if pool.closed:
        await pool.open()
    return pool


def _bearer_token(request: Request) -> str | None:
    """Extract the Bearer token from the Authorization header, else None."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def decode_token(token: str | None, expected_typ: str = "access") -> dict:
    """Decode and validate one JWT; raise HTTPException(401) on any failure.

    Enforces signature, expiry, ``typ`` (an access token is never accepted
    where a refresh token is expected and vice versa), and the presence of
    ``sub`` and a known ``role``.
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = jwt.decode(
            token, get_settings().JWT_SECRET, algorithms=[_ALGORITHM]
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"invalid token: {type(exc).__name__}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if (
        claims.get("typ") != expected_typ
        or not claims.get("sub")
        or claims.get("role") not in ROLES
    ):
        raise HTTPException(
            status_code=401,
            detail=f"invalid token: expected a {expected_typ} token with sub and role",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


def require_role(*roles: str):
    """Dependency factory: authenticate and authorize by role.

    ``require_role("officer")`` admits officer AND supervisor (SPEC 5:
    supervisor holds all officer rights). ``require_role("auditor")`` or
    ``require_role("supervisor")`` admit exactly that role. Returns
    ``{"sub", "role"}`` for the audit trail.
    """
    allowed = set(roles)
    if "officer" in allowed:
        allowed.add("supervisor")

    async def dependency(request: Request) -> dict:
        claims = decode_token(_bearer_token(request))
        if claims["role"] not in allowed:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"role {claims['role']!r} is not permitted here; "
                    f"requires one of {sorted(allowed)}"
                ),
            )
        return {"sub": claims["sub"], "role": claims["role"]}

    return dependency


# Any authenticated user (officer, supervisor, or auditor).
require_authenticated = require_role("officer", "auditor")


async def sse_identity(request: Request) -> dict:
    """Authenticate an SSE request: Bearer header OR ``?token=`` query.

    EventSource cannot set headers (SPEC 9.2), so the token may arrive as
    a query parameter; verification is identical for both transports.
    """
    token = _bearer_token(request) or request.query_params.get("token")
    claims = decode_token(token)
    return {"sub": claims["sub"], "role": claims["role"]}


# ---------------------------------------------------------------------------
# Rate limiting (SPEC section 5)
# ---------------------------------------------------------------------------


def _rate_key(request: Request) -> str:
    """slowapi key: ``role:sub`` from a valid JWT, else ``anon:<ip>``.

    A syntactically present but invalid token counts as anonymous: the
    caller has not proven an identity, so it gets the anonymous budget.
    """
    token = _bearer_token(request) or request.query_params.get("token")
    if token:
        try:
            claims = jwt.decode(
                token, get_settings().JWT_SECRET, algorithms=[_ALGORITHM]
            )
        except jwt.InvalidTokenError:
            claims = {}
        role = claims.get("role")
        sub = claims.get("sub")
        if claims.get("typ") == "access" and sub and role in ROLES:
            return f"{role}:{sub}"
    return f"anon:{get_remote_address(request)}"


def role_rate_limit(key: str) -> str:
    """Dynamic limit provider (slowapi calls it with the rate key).

    The parameter MUST be named ``key``: slowapi inspects the signature
    and only then passes the key_func result.
    """
    role = key.split(":", 1)[0]
    if role in ("officer", "supervisor"):
        return "120/minute"
    if role == "auditor":
        return "60/minute"
    return "20/minute"


limiter = Limiter(key_func=_rate_key)
