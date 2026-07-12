"""Case endpoints (SPEC 9.1): packet retrieval and F9 claims.

- ``GET /api/cases/{run_id}/packet`` (officer+): the Section 63 packet
  the pipeline assembled for the run's largest network (SPEC 6.10),
  including ``chain_head`` (the custody anchor) and the pre-filled,
  BLANK-signature certificate. Served exactly as assembled; nothing is
  recomputed or embellished here.
- ``POST /api/cases/{run_id}/claims`` (officer+): runs a claim generator
  plus the F9 verbatim gate over the case (SPEC 6.8) and returns the
  F9Result-shaped verdict list. Generator "ollama" prompts the local
  model against corpus v2; if the model is unreachable the endpoint
  degrades to the deterministic stub (corpus v1, the frozen baseline
  path) and says so via ``degraded: true``. Never a silent swap.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from paritran.api import runstore
from paritran.api.deps import limiter, require_role, role_rate_limit
from paritran.engine.f9.gate import Gate
from paritran.engine.legal import FullMapper, corpus_v2_texts, load_corpus_v1
from paritran.llm.client import ModelUnavailable
from paritran.llm.ollama_client import OllamaGenerator
from paritran.llm.stub import StubGenerator

__all__ = ["router"]

router = APIRouter(prefix="/api/cases", tags=["cases"])


class ClaimsRequest(BaseModel):
    generator: Literal["stub", "ollama"] = Field(
        default="stub",
        description="Claim generator; the F9 gate runs over every claim either way",
    )


class VerdictOut(BaseModel):
    section: str
    quote: str
    is_fabricated: bool | None = Field(
        description="Ground-truth label when the generator knows (stub only)"
    )
    verdict: Literal["PASSED", "WITHHELD"]
    sub_class: Literal["invented_section", "unverifiable_quote"] | None


class F9Response(BaseModel):
    generator_name: str = Field(
        description="Shown next to every F9 number (SPEC 6.8)"
    )
    is_stub: bool
    corpus_version: str
    claims: int
    passed: int
    withheld: int
    leaked: int
    degraded: bool = Field(
        description="True when 'ollama' was requested but the model was"
        " unreachable and the deterministic stub ran instead"
    )
    verdicts: list[VerdictOut]


def _completed_entry(run_id: str) -> runstore.RunEntry:
    entry = runstore.get(run_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id {run_id!r}")
    if entry.status != "completed" or entry.artifacts is None:
        raise HTTPException(
            status_code=409,
            detail=f"run {run_id!r} is {entry.status}; the case is available"
            " once the run completes",
        )
    return entry


def _offence_corpus_v2() -> dict[str, str]:
    """Corpus v2 minus non-offence sections (same policy as the pipeline)."""
    return {
        k: v
        for k, v in corpus_v2_texts().items()
        if k not in FullMapper.NON_OFFENCE_SECTIONS
    }


def _case_facts(entry: runstore.RunEntry) -> str:
    """The same case-facts summary shape the pipeline feeds the gate."""
    results = entry.results or {}
    communities = entry.artifacts.linkage_result.communities
    largest = max(communities, key=len) if communities else set()
    return (
        f"Seed {entry.seed} synthetic run: {results.get('n_complaints')} complaints,"
        f" {results.get('networks_found')} mule networks found; the largest network"
        f" links {len(largest)} complaints;"
        f" {results.get('pct_value_traced_to_cashout')} percent"
        f" of complaint value traced to cash-out."
    )


def _run_claims(generator: str, case_facts: str):
    """Generator + gate, with the SPEC 6.8 degrade path. Blocking; call
    via to_thread (the Ollama path performs local HTTP I/O)."""
    degraded = False
    if generator == "stub":
        result = Gate(load_corpus_v1(), "v1").run(
            StubGenerator(), {"case_facts": case_facts}
        )
    else:
        offence = _offence_corpus_v2()
        try:
            result = Gate(offence, "v2").run(
                OllamaGenerator(), {"case_facts": case_facts, "corpus": offence}
            )
        except ModelUnavailable:
            degraded = True
            result = Gate(load_corpus_v1(), "v1").run(
                StubGenerator(), {"case_facts": case_facts}
            )
    return result, degraded


@router.get(
    "/{run_id}/packet",
    summary="The assembled Section 63 case packet (largest network)",
    description=(
        "Officer or supervisor. Exactly the packet the pipeline assembled"
        " (SPEC 6.10): complaint intake hashes, network reference, money"
        " trail with break points, verbatim corpus v2 quotes, the F9 audit"
        " result per claim, the custody extract, chain_head, and the BSA"
        " Section 63 certificate drafted with BLANK signature blocks."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted"},
        404: {"description": "unknown run_id"},
        409: {"description": "run not completed yet"},
    },
    response_model=dict,
)
@limiter.limit(role_rate_limit)
async def get_packet(
    request: Request,
    run_id: str,
    identity: dict = Depends(require_role("officer")),
) -> dict:
    entry = _completed_entry(run_id)
    return entry.artifacts.packet


@router.post(
    "/{run_id}/claims",
    response_model=F9Response,
    summary="Run a claim generator + the F9 gate over this case",
    description=(
        "Officer or supervisor. Every claim passes iff its section exists"
        " in the target corpus AND its quote is a whitespace-normalized"
        " case-insensitive verbatim substring (SPEC 6.8). 'ollama' gates"
        " against corpus v2; if the model is unreachable the deterministic"
        " stub runs against corpus v1 and degraded=true is returned."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted"},
        404: {"description": "unknown run_id"},
        409: {"description": "run not completed yet"},
    },
)
@limiter.limit(role_rate_limit)
async def run_claims(
    request: Request,
    run_id: str,
    body: ClaimsRequest = Body(default=ClaimsRequest()),
    identity: dict = Depends(require_role("officer")),
) -> F9Response:
    entry = _completed_entry(run_id)
    facts = _case_facts(entry)
    result, degraded = await asyncio.to_thread(_run_claims, body.generator, facts)
    return F9Response(
        generator_name=result.generator_name,
        is_stub=result.is_stub,
        corpus_version=result.corpus_version,
        claims=result.claims,
        passed=result.passed,
        withheld=result.withheld,
        leaked=result.leaked,
        degraded=degraded,
        verdicts=[
            VerdictOut(
                section=v.claim.section,
                quote=v.claim.quote,
                is_fabricated=v.claim.is_fabricated,
                verdict=v.verdict,
                sub_class=v.sub_class,
            )
            for v in result.verdicts
        ],
    )
