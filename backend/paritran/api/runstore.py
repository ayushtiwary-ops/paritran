"""In-process pipeline run registry (SPEC 9.1, 9.2, 6.11).

One module-level dict maps ``run_id`` to a :class:`RunEntry` holding the
run's status, every emitted event (for SSE replay), the set of live
subscriber queues (for SSE fan-out), and, once the run completes, the
results dict plus the full :class:`~paritran.pipeline.PipelineArtifacts`
that the networks/cases routers read from.

Execution model: the deterministic pipeline is synchronous by design
(SPEC 6.11), so :func:`start_run` runs it in a worker thread via
``asyncio.to_thread``. The pipeline's ``EventSink`` callback fires on
that worker thread; it hands every :class:`StageEvent` back to the event
loop with ``loop.call_soon_threadsafe``, so the events list and the
subscriber queues are only ever touched from the loop thread. No locks
are needed on the registry itself for the same reason.

On completion the run is persisted over the application DSN
(``db.persist.persist_run`` writes the domain tables, the eval harness
writer lands the ``eval_runs`` row, SPEC 7.1 and 13). A persistence
failure never falsifies the run: the computed results stay available and
``persist_error`` reports the failure honestly instead of pretending the
rows landed.

Mapper cache: the InLegalBERT semantic index and the FullMapper are
built once per process on first use (module-level cache) because the
model load is expensive. When the semantic stack is unavailable the
cache holds ``None`` and every run degrades honestly to BM25 + rules
with ``mapping_degraded: true`` (SPEC 6.7); nothing is silently
substituted.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
import time
import uuid

from prometheus_client import Counter

from paritran import pipeline
from paritran.config import get_settings
from paritran.db.persist import persist_run
from paritran.engine.legal import FullMapper, RuleLayer, corpus_v2_texts
from paritran.engine.types import StageEvent

# The harness owns honest semantic-index degradation and the eval_runs
# row format; reusing its helpers keeps one implementation of each.
from paritran.eval.harness import _build_semantic_index, _write_eval_run

__all__ = [
    "RunEntry",
    "TERMINAL_EVENTS",
    "get",
    "get_mapper",
    "list_runs",
    "reset",
    "start_run",
    "subscribe",
    "unsubscribe",
]

log = logging.getLogger(__name__)

# SSE streams close after forwarding one of these (SPEC 9.3).
TERMINAL_EVENTS = ("run.completed", "run.failed")

# Milestone 8 custom metrics (SPEC 12). Registered on the prometheus_client
# default registry, which prometheus-fastapi-instrumentator already exposes
# at /metrics; module-level so they register exactly once per process.
RUNS_TOTAL = Counter(
    "paritran_runs",
    "Pipeline runs started via POST /api/intake/run, by requested generator.",
    ["generator"],
)
F9_VERDICTS_TOTAL = Counter(
    "paritran_f9_verdicts",
    "F9 gate claim verdicts from completed pipeline runs, by verdict "
    "(PASSED/WITHHELD) and by the generator the result was actually "
    "produced with (F9Result.generator_name, so an ollama request that "
    "degraded to the stub is honestly counted under the stub's name).",
    ["verdict", "generator"],
)


@dataclasses.dataclass
class RunEntry:
    """Everything the API layer knows about one pipeline run."""

    run_id: str
    seed: int
    generator: str
    status: str = "running"  # running | completed | failed
    events: list[dict] = dataclasses.field(default_factory=list)
    queues: set[asyncio.Queue] = dataclasses.field(default_factory=set)
    results: dict | None = None
    artifacts: pipeline.PipelineArtifacts | None = None
    db_run_id: int | None = None
    eval_run_id: int | None = None
    error: str | None = None
    persist_error: str | None = None
    task: asyncio.Task | None = None


_runs: dict[str, RunEntry] = {}

# One-slot cache: empty until first build, then [mapper_or_None].
_MAPPER_CACHE: list = []
_MAPPER_LOCK = threading.Lock()


def _build_mapper():
    """FullMapper over corpus v2 with the semantic rerank, or None.

    None means the semantic stack is unavailable (missing weights or
    torch/transformers); the pipeline then runs BM25 + rules with
    ``mapping_degraded: true``. Same policy as the eval harness.
    """
    texts = corpus_v2_texts()
    offence = {
        k: v for k, v in texts.items() if k not in FullMapper.NON_OFFENCE_SECTIONS
    }
    index = _build_semantic_index(offence)
    if index is None:
        return None
    return FullMapper(texts, index, RuleLayer(allowed_sections=offence))


def get_mapper():
    """The cached mapper (built once per process), or None (degraded)."""
    with _MAPPER_LOCK:
        if not _MAPPER_CACHE:
            _MAPPER_CACHE.append(_build_mapper())
        return _MAPPER_CACHE[0]


def get(run_id: str) -> RunEntry | None:
    """Look up one run; None when unknown."""
    return _runs.get(run_id)


def list_runs() -> list[RunEntry]:
    """All registered runs, insertion (start) order."""
    return list(_runs.values())


def reset() -> None:
    """Drop every registered run and the mapper cache (test hook)."""
    _runs.clear()
    with _MAPPER_LOCK:
        _MAPPER_CACHE.clear()


def _append(entry: RunEntry, event: str, stage: str | None, payload: dict) -> None:
    """Record one event and fan it out to every subscriber queue.

    Loop-thread only (worker threads reach here via
    ``call_soon_threadsafe``), so list/set mutation is race-free.
    """
    evt = {
        "event": event,
        "ts": time.time(),
        "run_id": entry.run_id,
        "stage": stage,
        "payload": payload,
    }
    entry.events.append(evt)
    for queue in list(entry.queues):
        queue.put_nowait(evt)


def subscribe(entry: RunEntry) -> tuple[list[dict], asyncio.Queue]:
    """Snapshot the stored events and register a live queue, atomically.

    Called from the loop thread with no await between snapshot and
    registration, so no event can fall between replay and live tail.
    """
    queue: asyncio.Queue = asyncio.Queue()
    snapshot = list(entry.events)
    entry.queues.add(queue)
    return snapshot, queue


def unsubscribe(entry: RunEntry, queue: asyncio.Queue) -> None:
    """Remove one subscriber queue; safe if already removed."""
    entry.queues.discard(queue)


def _execute_and_persist(entry: RunEntry, sink) -> None:
    """Worker-thread body: run the pipeline, then persist (SPEC 7.1, 13)."""
    mapper = get_mapper()
    artifacts = pipeline.execute(
        seed=entry.seed, generator=entry.generator, sink=sink, mapper=mapper
    )
    results = artifacts.results
    # Same honest flag the eval harness sets (SPEC 6.7 degradation).
    results["semantic_unavailable"] = mapper is None
    entry.artifacts = artifacts
    entry.results = results

    # F9 verdict counters (SPEC 12): incremented exactly where the F9
    # result lands in the runstore, one per gated claim. prometheus_client
    # counters are thread-safe, so incrementing on this worker thread is
    # fine.
    f9 = artifacts.f9_result
    for verdict in f9.verdicts:
        F9_VERDICTS_TOTAL.labels(
            verdict=verdict.verdict, generator=f9.generator_name
        ).inc()

    dsn = get_settings().DATABASE_URL
    try:
        entry.db_run_id = persist_run(
            results,
            artifacts.bundle,
            artifacts.linkage_result,
            artifacts.trail_result,
            artifacts.triage_scores,
            artifacts.mappings,
            artifacts.f9_result,
            dsn=dsn,
        )
        entry.eval_run_id = _write_eval_run(results, entry.generator, dsn)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed silently
        # The run's numbers are real and stay served from memory; only
        # the database write failed, and the entry says so.
        entry.persist_error = f"{type(exc).__name__}: {exc}"
        log.warning(
            "run %s completed but persistence failed: %s",
            entry.run_id,
            entry.persist_error,
        )


async def start_run(seed: int, generator: str) -> RunEntry:
    """Register a run and launch it in a worker thread; returns at once.

    Events stream into the entry as the pipeline emits them; the SSE
    endpoint replays ``entry.events`` and then tails the live queue.
    """
    entry = RunEntry(run_id=uuid.uuid4().hex, seed=seed, generator=generator)
    _runs[entry.run_id] = entry
    RUNS_TOTAL.labels(generator=generator).inc()
    _append(entry, "run.started", None, {"seed": seed, "generator": generator})

    loop = asyncio.get_running_loop()

    def sink(stage_event: StageEvent) -> None:
        # Worker thread -> loop thread handoff; the loop owns all state.
        loop.call_soon_threadsafe(
            _append, entry, stage_event.event, stage_event.stage, stage_event.payload
        )

    async def drive() -> None:
        try:
            await asyncio.to_thread(_execute_and_persist, entry, sink)
        except Exception as exc:  # noqa: BLE001 - surfaced as run.failed
            entry.status = "failed"
            entry.error = f"{type(exc).__name__}: {exc}"
            log.exception("run %s failed", entry.run_id)
            _append(entry, "run.failed", None, {"error": entry.error})
        else:
            # All sink callbacks scheduled before the thread finished have
            # already run on the loop by the time we resume here, so the
            # events list is complete when status flips.
            entry.status = "completed"

    entry.task = asyncio.create_task(drive())
    return entry
