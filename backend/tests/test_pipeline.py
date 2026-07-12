"""Pipeline orchestration tests (SPEC 6.11, 9.3): event stream, timing,
degradation, and the no-fake-breaks rule at seed 42."""

from _paths import ORACLE_RESULTS
import json
from pathlib import Path

import pytest

from paritran.engine.money_trail import trace
from paritran.engine.synthetic import generate
from paritran.engine.types import StageEvent
from paritran.llm.client import ModelUnavailable
from paritran.pipeline import EXECUTION_ORDER, STAGES, run_pipeline

ORACLE = json.loads(
    ORACLE_RESULTS.read_text(
        encoding="utf-8"
    )
)

# Headline numbers: every numeric/boolean oracle key must be announced
# through metric.updated as it becomes real (SPEC 9.3 truth rule).
HEADLINE_METRIC_KEYS = {
    key
    for key, value in ORACLE.items()
    if isinstance(value, (int, float, bool)) and key != "seed"
}


@pytest.fixture(scope="module")
def run():
    events: list[StageEvent] = []
    results = run_pipeline(seed=42, generator="stub", sink=events.append)
    return events, results


def test_run_completed_is_last_and_carries_full_results(run):
    events, results = run
    assert events[-1].event == "run.completed"
    assert events[-1].payload == results
    assert sum(1 for e in events if e.event == "run.completed") == 1


def test_every_stage_has_one_started_completed_pair_in_order(run):
    events, _ = run
    assert set(STAGES) == set(EXECUTION_ORDER)
    started = [e.stage for e in events if e.event == "stage.started"]
    completed = [e.stage for e in events if e.event == "stage.completed"]
    assert started == list(EXECUTION_ORDER)
    assert completed == list(EXECUTION_ORDER)
    for stage in EXECUTION_ORDER:
        i_started = next(
            i for i, e in enumerate(events)
            if e.event == "stage.started" and e.stage == stage
        )
        i_completed = next(
            i for i, e in enumerate(events)
            if e.event == "stage.completed" and e.stage == stage
        )
        assert i_started < i_completed


def test_stage_completed_carries_duration_ms(run):
    events, _ = run
    for e in events:
        if e.event == "stage.completed":
            assert isinstance(e.payload["duration_ms"], float)
            assert e.payload["duration_ms"] >= 0


def test_metric_updated_covers_every_headline_number(run):
    events, results = run
    emitted = {
        e.payload["key"]: e.payload["value"]
        for e in events
        if e.event == "metric.updated"
    }
    missing = HEADLINE_METRIC_KEYS - set(emitted)
    assert not missing, f"headline metrics never emitted: {missing}"
    for key in HEADLINE_METRIC_KEYS:
        assert emitted[key] == results[key], key


def test_stream_detail_events_present_and_deterministic(run):
    events, results = run
    node_ids = [e.payload["id"] for e in events if e.event == "graph.node.added"]
    assert len(node_ids) == results["n_complaints"]
    assert node_ids == sorted(node_ids)
    edges = [e for e in events if e.event == "graph.edge.added"]
    assert edges and all(e.payload["w"] >= 1 for e in edges)
    networks = [e for e in events if e.event == "network.discovered"]
    assert len(networks) == results["networks_found"]
    assert len([e for e in events if e.event == "trail.hop"]) > 0
    progress = [e.payload["pct"] for e in events if e.event == "trail.progress"]
    assert progress == sorted(progress)  # pct climbing (SPEC 9.3)
    assert len([e for e in events if e.event == "mapping.section"]) == results[
        "n_complaints"
    ]
    assert len([e for e in events if e.event == "f9.claim"]) == results["f9_claims"]
    assert len([e for e in events if e.event == "custody.appended"]) == results[
        "chain_len"
    ]


def test_stage_latencies_cover_all_nine_stages(run):
    _, results = run
    latencies = results["stage_latencies_ms"]
    assert set(latencies) == set(STAGES)
    for stage, ms in latencies.items():
        assert isinstance(ms, float) and ms >= 0, stage


def test_no_sink_operation(run):
    _, evented = run
    results = run_pipeline(seed=42, generator="stub")
    assert results["n_complaints"] == 297
    for key in ORACLE:
        if key == "time_to_packet_sec":
            continue
        assert results[key] == evented[key], key


def test_seed42_trail_breaks_are_empty_and_never_fabricated(run):
    events, _ = run
    # Engine truth at seed 42: the ledger is complete, so no breaks exist.
    trail = trace(generate(42))
    assert all(t.breaks == [] for t in trail.per_network)
    # The pipeline reports exactly that: zero breaks, no break-ish events.
    money_stage = next(
        e for e in events
        if e.event == "stage.completed" and e.stage == "money_trail"
    )
    assert money_stage.payload["metrics"]["n_breaks"] == 0
    assert not [e for e in events if "break" in e.event]


def test_degraded_mapping_is_labelled(run):
    _, results = run
    # This module runs the pipeline without a semantic index on purpose.
    assert results["mapping_degraded"] is True
    assert results["mapping"]["degraded"] is True
    assert results["mapping"]["v2_full_stack"] is None
    assert results["mapping"]["run_high"] + results["mapping"]["run_low"] == 297
    # The frozen floor row is measured live and equals the oracle.
    assert results["mapping"]["v1_floor"]["accuracy"] == ORACLE[
        "section_accuracy_bm25"
    ]


def test_ollama_unavailable_degrades_to_stub_with_honest_label(run, monkeypatch):
    _, stub_results = run

    class _DownGenerator:
        name = "ollama:test"
        is_stub = False

        def __init__(self):
            pass

        def generate_claims(self, context):
            raise ModelUnavailable("test: model offline")

    monkeypatch.setattr("paritran.pipeline.OllamaGenerator", _DownGenerator)
    results = run_pipeline(seed=42, generator="ollama")
    assert results["f9_degraded"] is True
    assert results["generator_name"] == "deterministic-stub"
    assert results["f9_is_stub"] is True
    assert results["f9_corpus_version"] == "v1"
    # Degraded run lands on the frozen stub baseline, honestly labelled.
    for key in ("f9_claims", "f9_passed", "f9_withheld_stub_fabrications",
                "f9_leaked"):
        assert results[key] == stub_results[key], key


def test_unknown_generator_rejected():
    with pytest.raises(ValueError):
        run_pipeline(seed=42, generator="gpt")
