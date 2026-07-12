"""Pipeline orchestrator (SPEC 6.11): the nine stages, timed and evented.

Stage names are the frozen contract enumeration (types.StageEvent):
ingest, entity_resolution, linkage, money_trail, triage, legal_mapping,
packet, f9_audit, signoff. Execution runs f9_audit BEFORE packet because
SPEC 6.10 requires the packet to embed the F9 audit result and the
custody chain head, and ``engine.packet.section63.assemble`` hard-fails
without both. All nine stages are emitted and timed either way.

Numeric truth rule (SPEC section 1): every number in the returned
results dict is computed by the real engine module that owns it, in this
run. At seed 42 with the stub generator the deterministic keys equal the
committed results.json exactly; ``tests/test_reproduction.py`` is the
gate. ``time_to_packet_sec`` is live wall clock, display only.

Honest degradation:

- no semantic index and no mapper: legal mapping runs BM25 + rules only
  and the results carry ``mapping_degraded: true`` (never a silently
  swapped full-stack number),
- generator "ollama" with the model unreachable: the run degrades to the
  deterministic stub, gated against corpus v1 (the frozen baseline
  path), and the results carry ``f9_degraded: true``.

Facts honored by construction: at seed 42 the synthetic money ledger is
complete, so every ``NetworkTrail.breaks`` list is empty and the
untraced 9.2 percent is noise-complaint value. Nothing here fabricates a
break; breaks come only from ``engine.money_trail.trace``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from collections import Counter

from paritran.engine import linkage, money_trail, ner, synthetic, triage
from paritran.engine.custody import chain as custody
from paritran.engine.f9.gate import Gate
from paritran.engine.legal import (
    BM25Index,
    FullMapper,
    RuleLayer,
    corpus_v2_texts,
    load_corpus_v1,
    load_corpus_v2,
    measure_accuracy,
)
from paritran.engine.packet import section63
from paritran.engine.types import EventSink, SectionMapping, StageEvent
from paritran.eval import load_golden_v1, load_golden_v2
from paritran.llm.client import ModelUnavailable
from paritran.llm.ollama_client import OllamaGenerator
from paritran.llm.stub import StubGenerator

__all__ = ["run_pipeline", "execute", "PipelineArtifacts", "STAGES", "EXECUTION_ORDER"]

# Frozen contract enumeration (paritran.engine.types.StageEvent.stage).
STAGES = (
    "ingest",
    "entity_resolution",
    "linkage",
    "money_trail",
    "triage",
    "legal_mapping",
    "packet",
    "f9_audit",
    "signoff",
)

# Actual execution order: packet consumes the F9 result and the custody
# chain head (SPEC 6.10), so f9_audit runs first. See module docstring.
EXECUTION_ORDER = (
    "ingest",
    "entity_resolution",
    "linkage",
    "money_trail",
    "triage",
    "legal_mapping",
    "f9_audit",
    "packet",
    "signoff",
)

# Prototype custody demo shape: 12 artefact records, tamper at index 5.
N_CUSTODY_RECORDS = 12
TAMPER_INDEX = 5

MONEY_TRAIL_METHOD = "directed-graph reachability"
SECTION_METHOD = "Okapi BM25 over condensed section-description corpus (v1)"
DATA_LABEL = "synthetic, ground-truth known, zero real PII"


@dataclasses.dataclass
class PipelineArtifacts:
    """Everything one run produced: the results dict plus the engine
    objects the persistence layer (db/persist.py) writes to Postgres."""

    results: dict
    bundle: synthetic.SyntheticBundle
    linkage_result: linkage.LinkageResult
    trail_result: money_trail.TrailResult
    triage_scores: list
    mappings: list[SectionMapping]
    f9_result: object
    chain: list
    packet: dict


class _Emitter:
    """StageEvent emission plus per-stage wall-clock timing (ms)."""

    def __init__(self, sink: EventSink | None):
        self._sink = sink
        self.latencies_ms: dict[str, float] = {}
        self._t0: dict[str, float] = {}

    def emit(self, stage: str, event: str, payload: dict) -> None:
        if self._sink is not None:
            self._sink(StageEvent(stage=stage, event=event, payload=payload))

    def metric(self, stage: str, key: str, value) -> None:
        self.emit(stage, "metric.updated", {"key": key, "value": value})

    def start(self, stage: str) -> None:
        self._t0[stage] = time.perf_counter()
        self.emit(stage, "stage.started", {})

    def complete(self, stage: str, metrics: dict) -> float:
        duration_ms = round((time.perf_counter() - self._t0[stage]) * 1000, 3)
        self.latencies_ms[stage] = duration_ms
        self.emit(
            stage,
            "stage.completed",
            {"duration_ms": duration_ms, "metrics": metrics},
        )
        return duration_ms


class _Bm25RulesMapper:
    """Degraded mapping path: BM25 + rules only, no semantic rerank.

    Used only when no semantic index is available; every run that used
    it carries ``mapping_degraded: true`` in its results (honest label,
    SPEC 6.7). Same offence-candidate policy as FullMapper: evidence
    provisions (BSA 63) are excluded from ranking.
    """

    def __init__(self, corpus_v2: dict[str, str], rules: RuleLayer):
        self.corpus = {
            k: v
            for k, v in corpus_v2.items()
            if k not in FullMapper.NON_OFFENCE_SECTIONS
        }
        self.bm25 = BM25Index(self.corpus)
        self.rules = rules

    def map(self, text: str, complaint_id: int = -1) -> SectionMapping:
        raw = self.bm25.scores(text)
        ranked = sorted(((sc, key) for key, sc in raw.items()), reverse=True)
        top2 = tuple(key for _, key in ranked[:2])
        rule_secs = tuple(self.rules.propose(text))
        agree = bool(set(rule_secs) & set(top2))
        return SectionMapping(
            complaint_id=complaint_id,
            sections=top2,
            confidence="HIGH" if agree else "LOW",
            paths=(("bm25", top2), ("rules", rule_secs)),
            routed_to_human=not agree,
        )


def _offence_corpus_v2() -> dict[str, str]:
    """Corpus v2 texts minus non-offence sections (integrator decision:
    BSA 63 belongs in the certificate display, never in offence ranking)."""
    return {
        k: v
        for k, v in corpus_v2_texts().items()
        if k not in FullMapper.NON_OFFENCE_SECTIONS
    }


def _majority_syndicate(members, truth: dict[int, int]) -> int | None:
    """Ground-truth majority syndicate of a community (noise excluded)."""
    counts = Counter(truth[cid] for cid in members if truth[cid] >= 0)
    if not counts:
        return None
    # Deterministic tie-break: highest count, then lowest syndicate id.
    return min(counts, key=lambda s: (-counts[s], s))


def execute(
    seed: int = 42,
    generator: str = "stub",
    sink: EventSink | None = None,
    semantic_index=None,
    mapper=None,
) -> PipelineArtifacts:
    """Run all nine stages and return results plus engine artifacts."""
    if generator not in ("stub", "ollama"):
        raise ValueError(f"unknown generator {generator!r}; use 'stub' or 'ollama'")

    em = _Emitter(sink)
    t0 = time.time()

    # ---- stage 1: ingest -------------------------------------------------
    em.start("ingest")
    bundle = synthetic.generate(seed)
    ner_tp = ner_fp = ner_fn = 0
    ingested = []
    for c in bundle.complaints:
        intake_hash = hashlib.sha256(c.narrative.encode("utf-8")).hexdigest()
        c = dataclasses.replace(c, intake_hash=intake_hash)
        ingested.append(c)
        # Live NER measurement against the identifiers the generator
        # actually embedded (SPEC 6.6). Never asserted, always computed.
        got = {ident for ident, _kind in ner.extract(c.narrative)}
        expected = set(c.ids)
        ner_tp += len(got & expected)
        ner_fp += len(got - expected)
        ner_fn += len(expected - got)
    bundle.complaints = ingested
    n_complaints = len(bundle.complaints)
    n_syndicates_seeded = len(bundle.syndicates)
    ner_precision = round(ner_tp / (ner_tp + ner_fp), 3) if ner_tp + ner_fp else 0.0
    ner_recall = round(ner_tp / (ner_tp + ner_fn), 3) if ner_tp + ner_fn else 0.0
    em.metric("ingest", "n_complaints", n_complaints)
    em.metric("ingest", "n_syndicates_seeded", n_syndicates_seeded)
    em.metric("ingest", "ner_precision", ner_precision)
    em.metric("ingest", "ner_recall", ner_recall)
    em.complete(
        "ingest",
        {
            "n_complaints": n_complaints,
            "n_syndicates_seeded": n_syndicates_seeded,
            "ner_precision": ner_precision,
            "ner_recall": ner_recall,
        },
    )

    # ---- stage 2: entity_resolution -------------------------------------
    em.start("entity_resolution")
    id_index: dict[str, list[int]] = {}
    for c in bundle.complaints:
        for ident in sorted(c.ids):
            id_index.setdefault(ident, []).append(c.id)
    n_identifiers = len(id_index)
    n_shared = sum(1 for members in id_index.values() if len(members) >= 2)
    n_mentions = sum(len(members) for members in id_index.values())
    em.complete(
        "entity_resolution",
        {
            "n_identifiers": n_identifiers,
            "n_shared_identifiers": n_shared,
            "n_mentions": n_mentions,
        },
    )

    # ---- stage 3: linkage ------------------------------------------------
    em.start("linkage")
    linkage_result = linkage.link(bundle)
    for cid in sorted(linkage_result.graph.nodes):
        em.emit("linkage", "graph.node.added", {"id": cid})
    # Deterministic edge order regardless of per-process set ordering.
    for a, b in sorted(tuple(sorted(edge)) for edge in linkage_result.graph.edges):
        em.emit(
            "linkage",
            "graph.edge.added",
            {"a": a, "b": b, "w": linkage_result.graph[a][b]["w"]},
        )
    for idx, community in enumerate(linkage_result.communities):
        em.emit(
            "linkage",
            "network.discovered",
            {"index": idx, "size": len(community), "members": sorted(community)},
        )
    metrics = linkage_result.metrics
    em.metric("linkage", "networks_found", metrics.networks_found)
    em.metric("linkage", "linkage_precision", metrics.precision)
    em.metric("linkage", "linkage_recall", metrics.recall)
    em.metric("linkage", "linkage_f1", metrics.f1)
    em.complete(
        "linkage",
        {
            "networks_found": metrics.networks_found,
            "precision": metrics.precision,
            "recall": metrics.recall,
            "f1": metrics.f1,
            "n_edges": linkage_result.graph.number_of_edges(),
        },
    )

    # ---- stage 4: money_trail --------------------------------------------
    em.start("money_trail")
    trail_result = money_trail.trace(bundle)
    cumulative_traced = 0
    n_breaks = 0
    for trail in trail_result.per_network:
        for hop in trail.hops:
            em.emit(
                "money_trail",
                "trail.hop",
                {
                    "syndicate": trail.syndicate,
                    "src": hop.src,
                    "dst": hop.dst,
                    "amount": hop.amount,
                },
            )
        n_breaks += len(trail.breaks)
        cumulative_traced += trail.traced_amt
        pct_so_far = round(
            100 * cumulative_traced / trail_result.total_amt, 1
        ) if trail_result.total_amt else 0.0
        em.emit(
            "money_trail",
            "trail.progress",
            {"syndicate": trail.syndicate, "pct": pct_so_far},
        )
    em.metric(
        "money_trail", "pct_value_traced_to_cashout", trail_result.pct_traced
    )
    em.complete(
        "money_trail",
        {
            "pct_traced": trail_result.pct_traced,
            "traced_amt": trail_result.traced_amt,
            "total_amt": trail_result.total_amt,
            "n_breaks": n_breaks,
        },
    )

    # ---- stage 5: triage ---------------------------------------------------
    em.start("triage")
    triage_scores = triage.score(bundle, linkage_result, trail_result)
    em.complete(
        "triage",
        {"queue": [(t.syndicate, t.score) for t in triage_scores]},
    )

    # ---- stage 6: legal_mapping -------------------------------------------
    em.start("legal_mapping")
    corpus_v1 = load_corpus_v1()
    golden_v1 = load_golden_v1()
    golden_v2 = load_golden_v2()
    offence_v2 = _offence_corpus_v2()

    # Frozen floor, measured live every run (never asserted): BM25 over
    # corpus v1 against golden v1. Must equal 52.4 at any seed (the
    # golden set does not move with the seed).
    section_accuracy_bm25 = measure_accuracy(corpus_v1, golden_v1)
    # Corpus-effect ablation: same BM25 math over corpus v2 offence text.
    v2_bm25_ablation = measure_accuracy(offence_v2, golden_v1)

    mapping_degraded = False
    if mapper is None and semantic_index is not None:
        mapper = FullMapper(
            corpus_v2_texts(),
            semantic_index,
            RuleLayer(allowed_sections=offence_v2),
        )
    if mapper is None:
        mapping_degraded = True
        mapper = _Bm25RulesMapper(
            corpus_v2_texts(), RuleLayer(allowed_sections=offence_v2)
        )

    mappings: list[SectionMapping] = []
    high = low = 0
    for c in bundle.complaints:
        mapping = mapper.map(c.narrative, complaint_id=c.id)
        mappings.append(mapping)
        if mapping.confidence == "HIGH":
            high += 1
        else:
            low += 1
        em.emit(
            "legal_mapping",
            "mapping.section",
            {
                "complaint_id": mapping.complaint_id,
                "sections": list(mapping.sections),
                "confidence": mapping.confidence,
                "paths": [[name, list(secs)] for name, secs in mapping.paths],
                "routed_to_human": mapping.routed_to_human,
            },
        )
    run_routing_rate = round(100 * low / n_complaints, 1) if n_complaints else 0.0

    if mapping_degraded:
        v2_full_stack = None
        extended_v2_full_stack = None
        routing_rate = run_routing_rate
    else:
        v2_full_stack = mapper.measure(golden_v1)
        extended_v2_full_stack = mapper.measure(golden_v2)
        routing_rate = v2_full_stack["routing_rate"]

    mapping_rows = {
        "v1_floor": {"n": len(golden_v1), "accuracy": section_accuracy_bm25},
        "v2_bm25_ablation": {"n": len(golden_v1), "accuracy": v2_bm25_ablation},
        "v2_full_stack": v2_full_stack,
        "extended_v2_full_stack": extended_v2_full_stack,
        "routing_rate": routing_rate,
        "run_high": high,
        "run_low": low,
        "run_routing_rate": run_routing_rate,
        "degraded": mapping_degraded,
    }
    em.metric("legal_mapping", "section_accuracy_bm25", section_accuracy_bm25)
    em.complete(
        "legal_mapping",
        {
            "section_accuracy_bm25": section_accuracy_bm25,
            "v2_bm25_ablation": v2_bm25_ablation,
            "high": high,
            "low": low,
            "routing_rate": routing_rate,
            "degraded": mapping_degraded,
        },
    )

    # ---- stage 7 (execution): f9_audit + custody chain ---------------------
    em.start("f9_audit")
    truth = {c.id: c.synd for c in bundle.complaints}
    largest = max(
        linkage_result.communities, key=len, default=set()
    ) if linkage_result.communities else set()
    case_facts = (
        f"Seed {seed} synthetic run: {n_complaints} complaints,"
        f" {metrics.networks_found} mule networks found; the largest network"
        f" links {len(largest)} complaints; {trail_result.pct_traced} percent"
        f" of complaint value traced to cash-out."
    )
    f9_degraded = False
    if generator == "stub":
        gen = StubGenerator()
        gate = Gate(corpus_v1, "v1")
        f9_result = gate.run(gen, {"case_facts": case_facts})
    else:  # "ollama"
        try:
            gen = OllamaGenerator()
            gate = Gate(offence_v2, "v2")
            f9_result = gate.run(
                gen, {"case_facts": case_facts, "corpus": offence_v2}
            )
        except ModelUnavailable:
            # SPEC 6.8 degradation: deterministic stub, frozen v1 path,
            # explicit label. Never a silent substitution.
            f9_degraded = True
            gen = StubGenerator()
            gate = Gate(corpus_v1, "v1")
            f9_result = gate.run(gen, {"case_facts": case_facts})
    for verdict in f9_result.verdicts:
        em.emit(
            "f9_audit",
            "f9.claim",
            {
                "section": verdict.claim.section,
                "quote": verdict.claim.quote,
                "is_fabricated": verdict.claim.is_fabricated,
                "verdict": verdict.verdict,
                "sub_class": verdict.sub_class,
            },
        )
    em.metric("f9_audit", "f9_claims", f9_result.claims)
    em.metric("f9_audit", "f9_passed", f9_result.passed)
    em.metric("f9_audit", "f9_withheld_stub_fabrications", f9_result.withheld)
    em.metric("f9_audit", "f9_leaked", f9_result.leaked)

    # Custody: the prototype's 12-record in-memory chain, byte-exact recs,
    # verified, then tamper detection over a disposable copy (SPEC 6.9).
    records = [
        {
            "artefact": f"evidence_{i}",
            "sha256": hashlib.sha256(str(i).encode()).hexdigest()[:16],
        }
        for i in range(N_CUSTODY_RECORDS)
    ]
    chain = custody.build_chain(records)
    chain_verified = custody.verify(chain)
    tampered = custody.tamper(chain, TAMPER_INDEX)
    tamper_detected = not custody.verify(tampered)
    for link in chain:
        em.emit(
            "f9_audit",
            "custody.appended",
            {"rec": link.rec, "prev": link.prev, "hash": link.hash},
        )
    em.metric("f9_audit", "chain_len", len(chain))
    em.metric("f9_audit", "chain_verified", chain_verified)
    em.metric("f9_audit", "tamper_detected", tamper_detected)
    em.complete(
        "f9_audit",
        {
            "generator_name": f9_result.generator_name,
            "is_stub": f9_result.is_stub,
            "corpus_version": f9_result.corpus_version,
            "claims": f9_result.claims,
            "passed": f9_result.passed,
            "withheld": f9_result.withheld,
            "leaked": f9_result.leaked,
            "degraded": f9_degraded,
            "chain_len": len(chain),
            "chain_verified": chain_verified,
            "tamper_detected": tamper_detected,
        },
    )

    # ---- stage 8 (execution): packet ----------------------------------------
    em.start("packet")
    if not largest:
        raise RuntimeError("no network found; cannot assemble a packet")
    packet_synd = _majority_syndicate(largest, truth)
    if packet_synd is None:
        raise RuntimeError("largest network has no ground-truth syndicate")
    trail_by_synd = {t.syndicate: t for t in trail_result.per_network}
    packet_trail = trail_by_synd[packet_synd]
    member_ids = sorted(largest)
    member_set = set(member_ids)
    packet_complaints = [c for c in bundle.complaints if c.id in member_set]
    section_counts: Counter[str] = Counter()
    for mapping in mappings:
        if mapping.complaint_id in member_set:
            section_counts.update(mapping.sections)
    packet_sections = sorted(
        section_counts, key=lambda sec: (-section_counts[sec], sec)
    )
    corpus_v2_entries = {
        entry["id"]: entry for entry in load_corpus_v2()["entries"]
    }
    chain_head = chain[-1].hash
    packet = section63.assemble(
        {
            "case": {
                "case_id": f"SEED{seed}-NET{packet_synd}",
                "seed": seed,
                "syndicate": packet_synd,
                "n_complaints": len(packet_complaints),
            },
            "complaints": packet_complaints,
            "network": {
                "syndicate": packet_synd,
                "size": len(member_ids),
                "members": member_ids,
            },
            "trail": packet_trail,
            "sections": packet_sections,
            "corpus_v2": corpus_v2_entries,
            "f9": f9_result,
            "custody_extract": chain,
            "chain_head": chain_head,
        }
    )
    time_to_packet_sec = round(time.time() - t0, 3)
    em.metric("packet", "time_to_packet_sec", time_to_packet_sec)
    em.complete(
        "packet",
        {
            "case_id": packet["case"]["case_id"],
            "n_sections": len(packet_sections),
            "chain_head": chain_head,
            "time_to_packet_sec": time_to_packet_sec,
        },
    )

    # ---- stage 9: signoff -----------------------------------------------------
    em.start("signoff")
    results = {
        # results.json contract (SPEC 6.1), every value from this run.
        "n_complaints": n_complaints,
        "n_syndicates_seeded": n_syndicates_seeded,
        "networks_found": metrics.networks_found,
        "linkage_precision": metrics.precision,
        "linkage_recall": metrics.recall,
        "linkage_f1": metrics.f1,
        "pct_value_traced_to_cashout": trail_result.pct_traced,
        "money_trail_method": MONEY_TRAIL_METHOD,
        "section_accuracy_bm25": section_accuracy_bm25,
        "section_method": SECTION_METHOD,
        "f9_claims": f9_result.claims,
        "f9_passed": f9_result.passed,
        # Honest key naming: the oracle key describes stub fabrications and
        # only applies to the stub path; live-model withhelds are just
        # "withheld". Both paths also expose the generic key.
        ("f9_withheld_stub_fabrications" if f9_result.is_stub else "f9_withheld"): f9_result.withheld,
        "f9_withheld": f9_result.withheld,
        "f9_leaked": f9_result.leaked,
        "chain_len": len(chain),
        "chain_verified": chain_verified,
        "tamper_detected": tamper_detected,
        "time_to_packet_sec": time_to_packet_sec,
        "data": DATA_LABEL,
        "seed": seed,
        # Live-measured extras (SPEC 6.1 live rows), distinct keys.
        "ner_precision": ner_precision,
        "ner_recall": ner_recall,
        "mapping": mapping_rows,
        "mapping_degraded": mapping_degraded,
        "stage_latencies_ms": em.latencies_ms,
        "generator_name": f9_result.generator_name,
        "f9_is_stub": f9_result.is_stub,
        "f9_corpus_version": f9_result.corpus_version,
        "f9_degraded": f9_degraded,
    }
    em.complete("signoff", {"keys": sorted(results)})
    em.emit("signoff", "run.completed", results)

    return PipelineArtifacts(
        results=results,
        bundle=bundle,
        linkage_result=linkage_result,
        trail_result=trail_result,
        triage_scores=triage_scores,
        mappings=mappings,
        f9_result=f9_result,
        chain=chain,
        packet=packet,
    )


def run_pipeline(
    seed: int = 42,
    generator: str = "stub",
    sink: EventSink | None = None,
    semantic_index=None,
    mapper=None,
) -> dict:
    """Run the nine-stage pipeline; return the results dict (SPEC 6.11).

    At (seed=42, generator="stub") the deterministic keys equal the
    committed results.json exactly. ``execute`` returns the same results
    plus the engine artifacts for persistence.
    """
    return execute(
        seed=seed,
        generator=generator,
        sink=sink,
        semantic_index=semantic_index,
        mapper=mapper,
    ).results
