"""Authentication endpoints: JWT issue and refresh (SPEC section 5, 9.1).

- ``POST /api/auth/login``: argon2id verification against the seeded
  ``users`` table (SPEC 5), then an access + refresh token pair. Both
  tokens are HS256 JWTs carrying ``sub``, ``role``, and ``typ``
  ("access" or "refresh"); TTLs come from JWT_ACCESS_TTL_SECONDS and
  JWT_REFRESH_TTL_SECONDS.
- ``POST /api/auth/refresh``: exchanges a valid refresh token for a new
  pair. An access token presented here is rejected (``typ`` check in
  :func:`paritran.api.deps.decode_token`), and vice versa.

Both endpoints are public and therefore rate limited on the anonymous
budget (20/min per client IP, SPEC section 5). Login failures return
one generic 401 for both unknown-user and wrong-password; a dummy
argon2 verification is burned on the unknown-user path so response
timing does not enumerate usernames.
"""

from __future__ import annotations

import asyncio
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from paritran.api.deps import db_pool, decode_token, limiter, role_rate_limit
from paritran.config import get_settings

__all__ = ["router"]

router = APIRouter(prefix="/api/auth", tags=["auth"])

_ALGORITHM = "HS256"
_HASHER = PasswordHasher()  # argon2id defaults, same as db/seed.py
# Timing-equalizer hash for unknown usernames (verified and discarded).
# The literal is not a credential; nothing accepts this password.
_DUMMY_HASH = _HASHER.hash("paritran-timing-equalizer")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, examples=["officer1"])
    password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_in: int
    refresh_expires_in: int


def _issue_pair(sub: str, role: str) -> TokenPair:
    """Sign a fresh access + refresh pair for one authenticated user."""
    settings = get_settings()
    now = int(time.time())

    def sign(typ: str, ttl: int) -> str:
        return jwt.encode(
            {"sub": sub, "role": role, "typ": typ, "iat": now, "exp": now + ttl},
            settings.JWT_SECRET,
            algorithm=_ALGORITHM,
        )

    return TokenPair(
        access_token=sign("access", settings.JWT_ACCESS_TTL_SECONDS),
        refresh_token=sign("refresh", settings.JWT_REFRESH_TTL_SECONDS),
        access_expires_in=settings.JWT_ACCESS_TTL_SECONDS,
        refresh_expires_in=settings.JWT_REFRESH_TTL_SECONDS,
    )


def _verify_password(password_hash: str, password: str) -> bool:
    """argon2 verification; False on mismatch or malformed hash."""
    try:
        _HASHER.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False
    return True


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Issue an access + refresh token pair",
    description=(
        "Verifies the username and password against the seeded users table"
        " (argon2id) and returns HS256 JWTs. Roles: officer, supervisor,"
        " auditor (SPEC section 5). Rate limited at 20/min per client IP."
    ),
    responses={401: {"description": "invalid username or password"}},
)
@limiter.limit(role_rate_limit)
async def login(request: Request, body: LoginRequest) -> TokenPair:
    pool = await db_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "SELECT password_hash, role FROM users WHERE username = %s",
            (body.username,),
        )
        row = await cursor.fetchone()

    if row is None:
        # Burn one verification so unknown-user and wrong-password take
        # comparable time (no username enumeration by latency).
        await asyncio.to_thread(_verify_password, _DUMMY_HASH, body.password)
        raise HTTPException(status_code=401, detail="invalid username or password")

    password_hash, role = row
    ok = await asyncio.to_thread(_verify_password, password_hash, body.password)
    if not ok:
        raise HTTPException(status_code=401, detail="invalid username or password")
    return _issue_pair(body.username, role)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Exchange a refresh token for a new token pair",
    description=(
        "Accepts ONLY a token with typ='refresh'; presenting an access"
        " token here is rejected with 401. Returns a brand new access +"
        " refresh pair for the same sub and role."
    ),
    responses={401: {"description": "invalid, expired, or non-refresh token"}},
)
@limiter.limit(role_rate_limit)
async def refresh(request: Request, body: RefreshRequest) -> TokenPair:
    claims = decode_token(body.refresh_token, expected_typ="refresh")
    return _issue_pair(claims["sub"], claims["role"])
