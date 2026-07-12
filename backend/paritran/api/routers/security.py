"""Security posture endpoint (SPEC 9.1, 11, and the SPEC 2 egress test).

GET /api/security/posture (auditor or supervisor) returns:

- Scanner summaries read from ``infra/scans/out/summary.json`` as
  produced by ``infra/scans/run_all.sh``. Location resolution, in
  order: ``PARITRAN_SCANS_DIR`` env var, then the compose mount default
  ``/oracle/scans``, then the repo-root ``infra/scans/out`` fallback so
  host-side runs work before (and without) the compose mount. A missing
  summary is reported as exactly that: ``summary_available: false``,
  never an invented clean bill.
- The outbound-endpoint config audit: the complete list of configured
  outbound endpoints, which is exactly one HTTP endpoint (host-local
  Ollama, ``settings.OLLAMA_BASE_URL``) plus the database DSN host on
  the internal compose network. Nothing else is configured anywhere.
- A live egress self-test (SPEC 2: zero egress is measured, not
  asserted): one TCP connect attempt from inside this process to a
  routable address (1.1.1.1:443) with a 2 s timeout. ``open`` means
  this process can reach the internet right now; ``blocked`` means the
  attempt failed (at the venue: Wi-Fi off, so blocked at the OS level,
  live). The result is whatever actually happened, timestamped.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from paritran.api.deps import limiter, require_role, role_rate_limit
from paritran.config import get_settings

__all__ = ["router"]

router = APIRouter(prefix="/api/security", tags=["security"])

EGRESS_TARGET_HOST = "1.1.1.1"
EGRESS_TARGET_PORT = 443
EGRESS_TIMEOUT_SECONDS = 2.0

# Compose mounts the host's infra/scans/out here (read-only).
DEFAULT_SCANS_DIR = "/oracle/scans"


class ScannerSummary(BaseModel):
    """One tool's row from summary.json, relayed verbatim (truth rule 1)."""

    status: str = Field(description="ok | findings | not_installed | error")
    critical: int | None = None
    high: int | None = None
    medium: int | None = None
    low: int | None = None
    unknown: int | None = None
    findings_total: int | None = None
    ran_at: str | None = None
    note: str | None = None
    error_detail: str | None = None


class OutboundEndpoint(BaseModel):
    name: str
    endpoint: str
    purpose: str


class EgressSelfTest(BaseModel):
    attempted: bool
    result: str = Field(description="open | blocked | not_attempted")
    target: str
    timeout_seconds: float
    checked_at: str
    detail: str


class SecurityPosture(BaseModel):
    summary_available: bool
    summary_generated_at: str | None
    last_scan_at: str | None = Field(
        description="Latest ran_at across scanners that actually ran"
    )
    scans: dict[str, ScannerSummary]
    scans_dir: str
    scans_source: str = Field(
        description="How scans_dir was resolved: env, compose mount, or repo fallback"
    )
    outbound_endpoints: list[OutboundEndpoint]
    egress: EgressSelfTest


def _scans_dir() -> tuple[Path, str]:
    """Resolve the scan-artifact directory and say how it was resolved."""
    env = os.environ.get("PARITRAN_SCANS_DIR")
    if env:
        return Path(env), "env:PARITRAN_SCANS_DIR"
    default = Path(DEFAULT_SCANS_DIR)
    if default.is_dir():
        return default, f"compose mount {DEFAULT_SCANS_DIR}"
    # Host-side runs: backend/paritran/api/routers/ is four levels below
    # the repo root, where run_all.sh writes infra/scans/out.
    repo_out = Path(__file__).resolve().parents[4] / "infra" / "scans" / "out"
    return repo_out, "repo fallback infra/scans/out"


def _load_summary(scans_dir: Path) -> tuple[bool, str | None, dict[str, ScannerSummary]]:
    path = scans_dir / "summary.json"
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False, None, {}
    scans = {
        tool: ScannerSummary(**entry)
        for tool, entry in doc.get("summary", {}).items()
    }
    return True, doc.get("generated_at"), scans


def _outbound_endpoints() -> list[OutboundEndpoint]:
    """The complete configured-outbound-endpoint list (SPEC 2 config audit)."""
    settings = get_settings()
    db = urlsplit(settings.DATABASE_URL)
    db_host = db.hostname or "unknown"
    db_port = f":{db.port}" if db.port else ""
    return [
        OutboundEndpoint(
            name="ollama",
            endpoint=settings.OLLAMA_BASE_URL,
            purpose=(
                "generative step for the F9-gated language layer; host-local"
                f" model {settings.OLLAMA_MODEL}, the only configured HTTP egress"
            ),
        ),
        OutboundEndpoint(
            name="database",
            endpoint=f"postgresql://{db_host}{db_port}",
            purpose=(
                "Postgres DSN host (credentials omitted); on the internal"
                " compose network in the container deployment"
            ),
        ),
    ]


async def _egress_self_test() -> EgressSelfTest:
    """One real TCP connect attempt; the result is measured, not asserted."""
    target = f"{EGRESS_TARGET_HOST}:{EGRESS_TARGET_PORT}"
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(EGRESS_TARGET_HOST, EGRESS_TARGET_PORT),
            timeout=EGRESS_TIMEOUT_SECONDS,
        )
    except (TimeoutError, asyncio.TimeoutError, OSError) as exc:
        return EgressSelfTest(
            attempted=True,
            result="blocked",
            target=target,
            timeout_seconds=EGRESS_TIMEOUT_SECONDS,
            checked_at=checked_at,
            detail=(
                "TCP connect failed"
                f" ({type(exc).__name__}); outbound traffic from this process"
                " is blocked right now"
            ),
        )
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return EgressSelfTest(
        attempted=True,
        result="open",
        target=target,
        timeout_seconds=EGRESS_TIMEOUT_SECONDS,
        checked_at=checked_at,
        detail=(
            "TCP connect succeeded; this process CAN reach the internet"
            " right now. At the venue the demo runs with Wi-Fi off, which"
            " this same test then shows as blocked, live."
        ),
    )


@router.get(
    "/posture",
    response_model=SecurityPosture,
    summary="Scan artifact summaries, outbound config audit, live egress self-test",
    description=(
        "Auditor or supervisor. Relays infra/scans/out/summary.json"
        " (produced by infra/scans/run_all.sh) without modification,"
        " lists every configured outbound endpoint, and performs one"
        " live TCP egress attempt (SPEC 2: measured, not asserted)."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted (auditor or supervisor)"},
    },
)
@limiter.limit(role_rate_limit)
async def get_posture(
    request: Request,
    identity: dict = Depends(require_role("auditor", "supervisor")),
) -> SecurityPosture:
    scans_dir, source = _scans_dir()
    available, generated_at, scans = _load_summary(scans_dir)
    ran_ats = [s.ran_at for s in scans.values() if s.ran_at]
    egress = await _egress_self_test()
    return SecurityPosture(
        summary_available=available,
        summary_generated_at=generated_at,
        last_scan_at=max(ran_ats) if ran_ats else None,
        scans=scans,
        scans_dir=str(scans_dir),
        scans_source=source,
        outbound_endpoints=_outbound_endpoints(),
        egress=egress,
    )
