"""Judge's-seed property tests (SPEC 14): any seed produces internally
consistent, honestly measured results that move with the seed."""

from _paths import ORACLE_RESULTS
import json
from pathlib import Path

import pytest

from paritran.engine.money_trail import trace
from paritran.engine.synthetic import generate
from paritran.pipeline import STAGES, run_pipeline

ORACLE = json.loads(
    ORACLE_RESULTS.read_text(
        encoding="utf-8"
    )
)

SEED = 22


@pytest.fixture(scope="module")
def results() -> dict:
    return run_pipeline(seed=SEED, generator="stub")


def test_seed_is_carried_and_data_moves_with_it(results):
    assert results["seed"] == SEED
    bundle = generate(SEED)
    assert results["n_complaints"] == len(bundle.complaints)
    # The numbers must move with the seed: a canned copy of the seed-42
    # oracle would be caught here.
    moving_keys = (
        "n_complaints",
        "linkage_precision",
        "linkage_recall",
        "linkage_f1",
        "pct_value_traced_to_cashout",
    )
    assert any(results[k] != ORACLE[k] for k in moving_keys), (
        "seed 22 produced the identical headline numbers as seed 42 on every "
        "moving key; the run is not actually seed-driven"
    )


def test_internal_consistency(results):
    p, r, f1 = (
        results["linkage_precision"],
        results["linkage_recall"],
        results["linkage_f1"],
    )
    assert 0 <= p <= 1 and 0 <= r <= 1 and 0 <= f1 <= 1
    if p + r:
        # f1 is rounded from the unrounded p and r, so recombination of
        # the rounded values matches only within rounding slack.
        assert abs(f1 - (2 * p * r / (p + r))) < 2e-3
    assert 0 <= results["pct_value_traced_to_cashout"] <= 100
    assert results["networks_found"] >= 1
    assert results["n_syndicates_seeded"] == 6
    # Stub F9 path is seed-independent by design (frozen baseline).
    assert results["f9_claims"] == results["f9_passed"] + results[
        "f9_withheld_stub_fabrications"
    ]
    assert results["f9_leaked"] == 0
    assert results["chain_len"] == 12
    assert results["chain_verified"] is True
    assert results["tamper_detected"] is True
    # The frozen v1 floor does not move with the seed (fixed golden set).
    assert results["section_accuracy_bm25"] == ORACLE["section_accuracy_bm25"]
    assert set(results["stage_latencies_ms"]) == set(STAGES)


def test_per_network_trail_sums_hold_at_seed_22():
    bundle = generate(SEED)
    trail = trace(bundle)
    assert sum(t.traced_amt for t in trail.per_network) == trail.traced_amt
    noise_value = sum(c.amt for c in bundle.complaints if c.synd < 0)
    assert (
        sum(t.total_amt for t in trail.per_network) + noise_value
        == trail.total_amt
    )
    # Breaks are only ever missing ledger edges, never invented.
    for t in trail.per_network:
        for src, dst in t.breaks:
            assert not bundle.money.has_edge(src, dst)
        assert t.traced_amt <= t.total_amt


def test_pipeline_pct_matches_engine_at_seed_22(results):
    assert results["pct_value_traced_to_cashout"] == trace(generate(SEED)).pct_traced
