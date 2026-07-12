"""Evaluation harness (SPEC section 13).

``run_eval`` builds the InLegalBERT semantic index when the local model
resolves (env INLEGALBERT_LOCAL_DIR / INLEGALBERT_PATH or the HF hub
cache default, see engine/legal/semantic.py), constructs the FullMapper,
runs the full pipeline, and, when ``persist`` is true, writes one
``eval_runs`` row over the application DSN.

Honest degradation: when torch/transformers are missing, the weights are
absent, or the model fails to load, the harness sets
``semantic_unavailable: true`` in its output and the pipeline runs the
BM25 + rules mapping path with ``mapping_degraded: true``. No full-stack
number is ever reported from a run that did not actually run the full
stack.
"""

from __future__ import annotations

import logging
import os

import psycopg
from psycopg.types.json import Jsonb

from paritran.config import get_settings
from paritran.engine.legal import FullMapper, RuleLayer, corpus_v2_texts
from paritran.eval import load_golden_v1, load_golden_v2
from paritran.pipeline import run_pipeline

__all__ = ["run_eval"]

log = logging.getLogger(__name__)

DATASET_VERSION = "v1+v2"
CORPUS_VERSION = "v1+v2"


def _build_semantic_index(corpus: dict[str, str]):
    """SemanticIndex over ``corpus``, or None when it cannot load.

    Every failure mode degrades cleanly (SPEC 6.7 / build fact d):
    missing torch/transformers, unresolved weights directory, or a load
    error all return None; the caller flags ``semantic_unavailable``.
    """
    try:
        from paritran.engine.legal.semantic import SemanticIndex, resolve_model_dir
    except ImportError as exc:
        log.warning("semantic stack unavailable (import): %s", exc)
        return None
    if resolve_model_dir() is None:
        log.warning(
            "InLegalBERT weights not found (INLEGALBERT_LOCAL_DIR, "
            "INLEGALBERT_PATH, HF hub cache); mapping degrades to BM25+rules"
        )
        return None
    try:
        return SemanticIndex(corpus)
    except (OSError, ValueError, RuntimeError) as exc:
        log.warning("InLegalBERT failed to load, degrading: %s", exc)
        return None


def _write_eval_run(results: dict, generator: str, dsn: str) -> int:
    """Insert one eval_runs row (SPEC 13); return its id."""
    settings = get_settings()
    if generator == "ollama":
        model_tag = settings.OLLAMA_MODEL
    else:
        # Honest label: a stub (or stub-degraded) run is never tagged with
        # the Ollama model name.
        model_tag = str(results.get("generator_name", "deterministic-stub"))
    sample_sizes = {
        "golden_v1": len(load_golden_v1()),
        "extended_v2": len(load_golden_v2()),
        "complaints": results["n_complaints"],
    }
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "INSERT INTO eval_runs"
            " (git_sha, dataset_version, corpus_version, generator,"
            "  model_tag, metrics, latencies, sample_sizes)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING id",
            (
                os.environ.get("GIT_SHA", "unknown"),
                DATASET_VERSION,
                CORPUS_VERSION,
                generator,
                model_tag,
                Jsonb(results),
                Jsonb(results["stage_latencies_ms"]),
                Jsonb(sample_sizes),
            ),
        ).fetchone()
    return row[0]


def run_eval(
    persist: bool = False,
    seed: int = 42,
    generator: str = "stub",
    dsn: str | None = None,
) -> dict:
    """Run the pipeline with the strongest available mapping stack.

    Returns the pipeline results plus ``semantic_unavailable`` (and
    ``eval_run_id`` when persisted). ``dsn`` defaults to the application
    DATABASE_URL from settings; tests point it at a fixture database.
    """
    texts = corpus_v2_texts()
    offence = {
        k: v for k, v in texts.items() if k not in FullMapper.NON_OFFENCE_SECTIONS
    }
    semantic_index = _build_semantic_index(offence)
    mapper = None
    if semantic_index is not None:
        mapper = FullMapper(
            texts, semantic_index, RuleLayer(allowed_sections=offence)
        )

    results = run_pipeline(seed=seed, generator=generator, mapper=mapper)
    results["semantic_unavailable"] = semantic_index is None

    if persist:
        target_dsn = dsn if dsn is not None else get_settings().DATABASE_URL
        results["eval_run_id"] = _write_eval_run(results, generator, target_dsn)
    return results
