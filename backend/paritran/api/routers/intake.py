"""Intake endpoints (SPEC 9.1): start a pipeline run, ingest an artefact.

- ``POST /api/intake/run`` (officer+): registers a run in the in-process
  runstore and executes the nine-stage pipeline in a worker thread.
  Events stream over ``GET /api/stream/run/{run_id}``. The InLegalBERT
  mapper is built once at first use (module-level cache in runstore);
  when unavailable the run degrades honestly to BM25 + rules and its
  results carry ``mapping_degraded: true``.
- ``POST /api/intake/artefact`` (officer+): multipart PDF/image ingest.
  pdfplumber text extraction with Tesseract OCR fallback (engine
  ``ingest_ocr``), SHA-256 intake hash over the artefact bytes,
  rule-augmented NER over the extracted text, and an ``artefact.ingested``
  append to the audit chain (SPEC 8.1).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from typing import Literal

from paritran.api import runstore
from paritran.api.deps import limiter, require_role, role_rate_limit
from paritran.db import repo
from paritran.engine import ner
from paritran.engine.ingest_ocr import (
    SUPPORTED_SUFFIXES,
    UnsupportedArtefactError,
    extract_text,
)

__all__ = ["router"]

router = APIRouter(prefix="/api/intake", tags=["intake"])

# First 500 characters of extracted text returned to the caller.
EXCERPT_CHARS = 500


class RunRequest(BaseModel):
    seed: int = Field(default=42, description="Deterministic RNG seed (SPEC 6.2)")
    generator: Literal["stub", "ollama"] = Field(
        default="stub",
        description=(
            "F9 claim generator: 'stub' is the labelled deterministic"
            " fabricating stub (frozen v1 baseline); 'ollama' prompts the"
            " local model and degrades to the stub with an explicit flag"
            " when the model is unreachable (SPEC 6.8)"
        ),
    )


class RunStarted(BaseModel):
    run_id: str
    seed: int
    generator: str
    status: str
    stream_url: str


class IdentifierOut(BaseModel):
    identifier: str
    kind: str


class ArtefactResult(BaseModel):
    intake_hash: str = Field(description="SHA-256 over the raw artefact bytes")
    method: Literal["pdf-text", "ocr"]
    pages: int
    identifiers: list[IdentifierOut]
    text_excerpt: str = Field(
        description=f"First {EXCERPT_CHARS} characters of the extracted text"
    )
    audit_seq: int = Field(description="Audit chain seq of the artefact.ingested row")


@router.post(
    "/run",
    response_model=RunStarted,
    status_code=202,
    summary="Start a pipeline run",
    description=(
        "Officer or supervisor. Runs the nine deterministic stages (SPEC"
        " 6.11) in the background; follow progress on"
        " /api/stream/run/{run_id}. Any seed is honoured: a judge-named"
        " seed rerun is simply this endpoint with that seed, and every"
        " metric moves consistently with it (SPEC 17 step 7b)."
    ),
)
@limiter.limit(role_rate_limit)
async def start_run(
    request: Request,
    body: RunRequest = Body(default=RunRequest()),
    identity: dict = Depends(require_role("officer")),
) -> RunStarted:
    entry = await runstore.start_run(seed=body.seed, generator=body.generator)
    return RunStarted(
        run_id=entry.run_id,
        seed=entry.seed,
        generator=entry.generator,
        status=entry.status,
        stream_url=f"/api/stream/run/{entry.run_id}",
    )


@router.post(
    "/artefact",
    response_model=ArtefactResult,
    summary="Ingest a PDF or image artefact",
    description=(
        "Officer or supervisor. Multipart upload; pdfplumber text layer"
        " first, Tesseract OCR fallback for scans (method reported"
        " honestly). SHA-256 intake hash over the artefact bytes,"
        " rule-augmented NER over the extracted text, and an"
        " artefact.ingested append to the audit chain."
    ),
    responses={
        401: {"description": "missing or invalid token"},
        403: {"description": "role not permitted"},
        415: {"description": "unsupported artefact type"},
        422: {"description": "missing or empty upload"},
    },
)
@limiter.limit(role_rate_limit)
async def ingest_artefact(
    request: Request,
    file: UploadFile = File(...),
    identity: dict = Depends(require_role("officer")),
) -> ArtefactResult:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty upload")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=415, detail=str(UnsupportedArtefactError(suffix))
        )

    intake_hash = hashlib.sha256(data).hexdigest()

    # The extraction engine works on paths (pdfplumber/PIL), so the upload
    # lands in a temp file that is always removed afterwards.
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
        tmp.close()
        extraction = await asyncio.to_thread(extract_text, tmp.name)
        identifiers = await asyncio.to_thread(ner.extract, extraction["text"])
    finally:
        tmp.close()
        os.unlink(tmp.name)

    audit_row = await repo.append_audit(
        actor=identity["sub"],
        action="artefact.ingested",
        payload={
            "filename": file.filename,
            "intake_hash": intake_hash,
            "method": extraction["method"],
            "pages": extraction["pages"],
            "n_identifiers": len(identifiers),
            "role": identity["role"],
        },
    )

    return ArtefactResult(
        intake_hash=intake_hash,
        method=extraction["method"],
        pages=extraction["pages"],
        identifiers=[
            IdentifierOut(identifier=ident, kind=kind) for ident, kind in identifiers
        ],
        text_excerpt=extraction["text"][:EXCERPT_CHARS],
        audit_seq=audit_row["seq"],
    )
