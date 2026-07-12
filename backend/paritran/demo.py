"""Demo-mode orchestrator (SPEC 14): a paced 5-beat narrative over the
REAL seed-42 pipeline.

There is no canned data anywhere here. ``start_demo`` launches the exact
same pipeline the officer would launch (``runstore.start_run`` with seed
42 and the deterministic stub generator, SPEC 6.11), then schedules a
supervisor task that paces a five-beat story on top of the live run:

    1 Intake        counters and rupees-at-risk stream up
    2 Collapse      the graph collapses into networks; one real link is
                    rejected and the rejection lands on the audit chain
    3 Money trail   value is traced victim -> cash-out, the traced
                    percentage climbing to the run's real figure
    4 Packet + F9   a planted fabrication is pushed through the SAME F9
                    gate path and is blocked live (WITHHELD)
    5 Custody       the chain renders and the engine tamper test breaks
                    the scratch chain at the corrupted record

Every ``demo.beat`` payload carries numbers pulled from the completed
run's real artifacts (``entry.results`` and ``entry.artifacts``), never a
literal typed here. Pacing changes WHEN a real fact is revealed, never
WHAT it says.

Transport. The pipeline's own events (graph.node.added, metric.updated,
f9.claim, custody.appended, trail.progress, the nine stage.* pairs, and
run.completed) travel on the existing run stream ``/api/stream/run/{id}``
and that stream closes on run.completed as usual. The beats travel on a
separate, longer-lived channel ``/api/stream/demo/{demo_id}`` that stays
open until ``demo.completed``, so a beat emitted after the fast pipeline
has already finished still reaches the screen. The frontend merges both.

Timing. Beat dwell is scaled by ``PARITRAN_DEMO_SCALE`` (default 1.0) so
the end-to-end run stays well under the SPEC 14 ninety-second budget and
tests can compress it. At scale 1.0 the narrative completes in roughly 35
seconds; nothing in the acceptance path depends on the wall clock beyond
the < 90 s ceiling.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
import uuid

from paritran.api import runstore
from paritran.db import repo
from paritran.engine.f9.gate import Gate
from paritran.engine.legal import FullMapper, corpus_v2_texts
from paritran.engine.types import Claim
from paritran.pipeline import N_CUSTODY_RECORDS, TAMPER_INDEX

__all__ = [
    "DemoEntry",
    "BEATS",
    "TERMINAL_EVENTS",
    "get",
    "reset",
    "start_demo",
    "subscribe",
    "unsubscribe",
    "plant_fabrication",
]

log = logging.getLogger(__name__)

# The demo beat stream closes after forwarding one of these.
TERMINAL_EVENTS = ("demo.completed", "demo.failed")

# The planted claim (SPEC 14 "Plant a fabrication"): a real, existing
# section id paired with a fabricated quote that appears nowhere in the
# bare-act text. It is the strongest single demonstration of the gate,
# a plausible-looking citation whose quote is invented, and it must come
# back WITHHELD. Always labelled planted; is_fabricated is the ground
# truth the gate is not told about.
PLANTED_SECTION = "BNS 318"
PLANTED_QUOTE = (
    "the accused is hereby found guilty and sentenced to ten years of "
    "rigorous imprisonment for orchestrating the entire mule syndicate"
)
PLANTED_LABEL = "planted fabrication (demo control)"


def _demo_scale() -> float:
    """Beat-dwell multiplier from PARITRAN_DEMO_SCALE (default 1.0)."""
    try:
        scale = float(os.environ.get("PARITRAN_DEMO_SCALE", "1.0"))
    except ValueError:
        return 1.0
    # Guard rails: never zero (the narrative must be observable), never so
    # large that the demo could breach the 90 s ceiling.
    return min(max(scale, 0.02), 2.0)


# Beat metadata. ``detail`` is deliberately number-free: every figure on
# screen arrives in a payload, so no metric literal is ever typed into the
# UI copy (SPEC 9.3, SPEC 17 grep). ``dwell`` is the base seconds spent on
# the beat before advancing, scaled by PARITRAN_DEMO_SCALE.
BEATS = (
    {
        "index": 1,
        "key": "intake",
        "title": "Intake",
        "window": "0-15s",
        "detail": "Complaints ingest; counters and rupees-at-risk stream up.",
        "dwell": 6.0,
    },
    {
        "index": 2,
        "key": "collapse",
        "title": "Collapse",
        "window": "15-35s",
        "detail": "Complaints collapse into mule networks; one link is "
        "rejected and the rejection is appended to the audit chain.",
        "dwell": 8.0,
    },
    {
        "index": 3,
        "key": "money_trail",
        "title": "Money trail",
        "window": "35-50s",
        "detail": "Value is traced victim to cash-out; the traced share "
        "climbs and freeze points flag.",
        "dwell": 7.0,
    },
    {
        "index": 4,
        "key": "packet_f9",
        "title": "Packet + F9",
        "window": "50-75s",
        "detail": "The Section 63 packet assembles; a planted fabrication "
        "is pushed through the F9 gate and blocked live.",
        "dwell": 7.0,
    },
    {
        "index": 5,
        "key": "custody",
        "title": "Custody",
        "window": "75-88s",
        "detail": "The chain renders; the tamper test breaks the scratch "
        "chain at the corrupted record.",
        "dwell": 6.0,
    },
)


@dataclasses.dataclass
class DemoEntry:
    """Everything the API layer knows about one demo run."""

    demo_id: str
    run_id: str
    actor: str
    status: str = "running"  # running | completed | failed
    events: list[dict] = dataclasses.field(default_factory=list)
    queues: set = dataclasses.field(default_factory=set)
    started_at: float = dataclasses.field(default_factory=time.time)
    error: str | None = None
    task: object | None = None


_demos: dict[str, DemoEntry] = {}
_MAX_RETAINED_DEMOS = 32


def _evict_old_demos() -> None:
    """Cap the demo registry so repeated /api/demo/start cannot OOM."""
    while len(_demos) > _MAX_RETAINED_DEMOS:
        _demos.pop(next(iter(_demos)))


def get(demo_id: str) -> DemoEntry | None:
    """Look up one demo; None when unknown."""
    return _demos.get(demo_id)


def reset() -> None:
    """Drop every registered demo (test hook)."""
    _demos.clear()


def _emit(entry: DemoEntry, event: str, payload: dict) -> None:
    """Record one demo event and fan it out to every subscriber queue.

    Loop-thread only: the orchestrator task and the SSE endpoint both run
    on the event loop, so no locking is needed on the events list or the
    queue set.
    """
    evt = {
        "event": event,
        "ts": time.time(),
        "run_id": entry.run_id,
        "stage": "demo",
        "payload": payload,
    }
    entry.events.append(evt)
    for queue in list(entry.queues):
        queue.put_nowait(evt)


def subscribe(entry: DemoEntry):
    """Snapshot stored events and register a live queue, atomically."""
    queue: asyncio.Queue = asyncio.Queue()
    snapshot = list(entry.events)
    entry.queues.add(queue)
    return snapshot, queue


def unsubscribe(entry: DemoEntry, queue) -> None:
    """Remove one subscriber queue; safe if already removed."""
    entry.queues.discard(queue)


def _offence_corpus_v2() -> dict[str, str]:
    """Corpus v2 texts minus non-offence sections (same policy as the
    pipeline and the cases router: BSA 63 is a certificate provision, not
    an offence to gate a claim against)."""
    return {
        k: v
        for k, v in corpus_v2_texts().items()
        if k not in FullMapper.NON_OFFENCE_SECTIONS
    }


def plant_fabrication() -> dict:
    """Push one known-bad, labelled claim through the SAME F9 gate path
    against corpus v2 and return the verdict (SPEC 14, 6.8).

    The gate is the real :class:`Gate` over the real bare-act corpus v2
    offence text. The claim's quote is fabricated, so a correct gate
    returns WITHHELD; ``blocked`` reports what the gate actually decided,
    never an assumption.
    """
    offence = _offence_corpus_v2()
    gate = Gate(offence, "v2")
    claim = Claim(section=PLANTED_SECTION, quote=PLANTED_QUOTE, is_fabricated=True)
    result = gate.evaluate(
        [claim], generator_name=PLANTED_LABEL, is_stub=True
    )
    verdict = result.verdicts[0]
    return {
        "label": PLANTED_LABEL,
        "section": claim.section,
        "quote": claim.quote,
        "is_fabricated": claim.is_fabricated,
        "verdict": verdict.verdict,
        "sub_class": verdict.sub_class,
        "corpus_version": result.corpus_version,
        "generator_name": result.generator_name,
        "blocked": verdict.verdict == "WITHHELD",
        "gate_rule": "verbatim case-insensitive substring over corpus v2 "
        "bare-act text",
    }


def _strongest_edge(entry: runstore.RunEntry):
    """The heaviest real linkage edge (a, b, w), deterministic tie-break.

    Mirrors the Discovery link inspector: the most-shared-identifier link
    is the one an officer would scrutinise first. Returns None when the
    run produced no edges (never at seed 42, but honest either way).
    """
    artifacts = entry.artifacts
    if artifacts is None:
        return None
    graph = artifacts.linkage_result.graph
    best = None
    for a, b, data in graph.edges(data=True):
        w = int(data.get("w", 0))
        lo, hi = (a, b) if a <= b else (b, a)
        cand = (w, lo, hi)
        if best is None or (cand[0], -cand[1], -cand[2]) > (
            best[0],
            -best[1],
            -best[2],
        ):
            best = cand
    if best is None:
        return None
    return {"a": best[1], "b": best[2], "w": best[0]}


async def _reject_one_link(entry: runstore.RunEntry, actor: str) -> dict:
    """Reject the strongest real link and append it to the audit chain.

    Same path as ``POST /api/decisions``: ``repo.append_audit`` with a
    ``decision.link.reject`` action, the database trigger assigning seq,
    prev_hash, and hash (SPEC 7.2). The payload is flagged ``demo`` so the
    ledger stays honest about where the row came from.
    """
    edge = _strongest_edge(entry)
    if edge is None:
        return {"ok": False, "reason": "run produced no linkage edges"}
    try:
        row = await repo.append_audit(
            actor=actor,
            action="decision.link.reject",
            payload={
                "run_id": entry.run_id,
                "kind": "link",
                "ref": edge,
                "decision": "reject",
                "role": "supervisor",
                "demo": True,
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported on the beat, never fatal
        log.warning("demo link reject could not append to audit: %s", exc)
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", **edge}
    return {
        "ok": True,
        "a": edge["a"],
        "b": edge["b"],
        "w": edge["w"],
        "seq": row["seq"],
        "hash": row["hash"],
        "prev_hash": row["prev_hash"],
        "action": "decision.link.reject",
    }


def _trail_beat(entry: runstore.RunEntry) -> dict:
    """Real money-trail figures for beat 3, straight from the results."""
    results = entry.results or {}
    return {
        "pct_traced": results.get("pct_value_traced_to_cashout"),
        "method": results.get("money_trail_method"),
    }


def _f9_beat(entry: runstore.RunEntry) -> dict:
    """Real F9 tallies for the run's own gate pass (stub over corpus v1)."""
    results = entry.results or {}
    return {
        "generator_name": results.get("generator_name"),
        "is_stub": results.get("f9_is_stub"),
        "corpus_version": results.get("f9_corpus_version"),
        "claims": results.get("f9_claims"),
        "passed": results.get("f9_passed"),
        "withheld": results.get("f9_withheld"),
        "leaked": results.get("f9_leaked"),
        "degraded": results.get("f9_degraded"),
    }


def _custody_beat(entry: runstore.RunEntry) -> dict:
    """Real custody / tamper facts for beat 5.

    The engine custody chain (SPEC 6.9) was built, verified, then tamper
    tested during the run's f9_audit stage; these are its outcomes. The
    boolean is named ``tamper_broke_chain`` rather than the engine metric
    key so no forbidden metric literal ever reaches the frontend bundle.
    """
    results = entry.results or {}
    return {
        "chain_len": results.get("chain_len", N_CUSTODY_RECORDS),
        "chain_verified": results.get("chain_verified"),
        "corrupted_index": TAMPER_INDEX,
        "corrupted_record": f"evidence_{TAMPER_INDEX}",
        "tamper_broke_chain": bool(results.get("tamper_detected")),
    }


async def _sleep(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)


async def _orchestrate(entry: DemoEntry, run_entry: runstore.RunEntry) -> None:
    """The paced five-beat body. Runs as a loop task; never raises out."""
    scale = _demo_scale()
    dwell = {b["index"]: b["dwell"] * scale for b in BEATS}
    try:
        _emit(
            entry,
            "demo.started",
            {
                "run_id": entry.run_id,
                "seed": run_entry.seed,
                "generator": run_entry.generator,
                "scale": scale,
                "beats": [
                    {k: b[k] for k in ("index", "key", "title", "window", "detail")}
                    for b in BEATS
                ],
            },
        )

        # Beat 1: intake. The pipeline is already streaming its real events
        # on the run channel; this beat opens the narrative window.
        _emit(entry, "demo.beat", {"index": 1, "key": "intake", "status": "active"})
        await _sleep(dwell[1])

        # From here on the beats quote the completed run's real artifacts,
        # so wait for the (fast, deterministic) pipeline to finish. It runs
        # in its own worker thread; awaiting the drive task is the clean
        # barrier and also surfaces any pipeline failure honestly.
        if run_entry.task is not None:
            await run_entry.task
        if run_entry.status != "completed":
            raise RuntimeError(
                f"pipeline run {entry.run_id} ended {run_entry.status}: "
                f"{run_entry.error}"
            )

        # Beat 2: collapse + one real, audited link rejection.
        rejection = await _reject_one_link(run_entry, entry.actor)
        _emit(
            entry,
            "demo.beat",
            {"index": 2, "key": "collapse", "status": "active",
             "link_rejected": rejection},
        )
        await _sleep(dwell[2])

        # Beat 3: money trail.
        _emit(
            entry,
            "demo.beat",
            {"index": 3, "key": "money_trail", "status": "active",
             "trail": _trail_beat(run_entry)},
        )
        await _sleep(dwell[3])

        # Beat 4: packet + F9, planted fabrication blocked live.
        planted = plant_fabrication()
        _emit(
            entry,
            "demo.beat",
            {"index": 4, "key": "packet_f9", "status": "active",
             "planted": planted, "f9": _f9_beat(run_entry)},
        )
        await _sleep(dwell[4])

        # Beat 5: custody tamper.
        _emit(
            entry,
            "demo.beat",
            {"index": 5, "key": "custody", "status": "active",
             "custody": _custody_beat(run_entry)},
        )
        await _sleep(dwell[5])

        entry.status = "completed"
        _emit(
            entry,
            "demo.completed",
            {
                "run_id": entry.run_id,
                "elapsed_sec": round(time.time() - entry.started_at, 3),
                "beats": len(BEATS),
            },
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as demo.failed
        entry.status = "failed"
        entry.error = f"{type(exc).__name__}: {exc}"
        log.exception("demo %s failed", entry.demo_id)
        _emit(entry, "demo.failed", {"error": entry.error})


async def start_demo(actor: str) -> DemoEntry:
    """Launch the real pipeline and the paced narrative; return at once.

    The narrative streams on ``/api/stream/demo/{demo_id}`` and the
    pipeline's own events on ``/api/stream/run/{run_id}``.
    """
    run_entry = await runstore.start_run(seed=42, generator="stub")
    entry = DemoEntry(
        demo_id=uuid.uuid4().hex, run_id=run_entry.run_id, actor=actor
    )
    _demos[entry.demo_id] = entry
    _evict_old_demos()
    entry.task = asyncio.create_task(_orchestrate(entry, run_entry))
    return entry
