"""THE reproduction gate (SPEC 6.1): seed-42 stub run equals results.json.

Iterates every key of the committed oracle. Every key except
``time_to_packet_sec`` (live wall clock, display only) must be present in
the pipeline results with an EXACTLY equal value. The comparison table is
printed so a human (or the CI log) can read the per-key verdicts.
"""

import json
from pathlib import Path

import pytest

from paritran.pipeline import run_pipeline

from _paths import ORACLE_RESULTS as ORACLE_PATH
ORACLE = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))

LIVE_KEYS = {"time_to_packet_sec"}


@pytest.fixture(scope="module")
def results() -> dict:
    return run_pipeline(seed=42, generator="stub")


def _exactly_equal(expected, actual) -> bool:
    """Value equality that never lets bool/int coercion hide a drift."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(actual, bool) and actual is expected
    return type(actual) is type(expected) and actual == expected


def test_seed42_stub_reproduces_results_json_exactly(results):
    rows = []
    failures = []
    for key, expected in ORACLE.items():
        if key not in results:
            rows.append((key, expected, "<MISSING>", "FAIL"))
            failures.append(key)
            continue
        actual = results[key]
        if key in LIVE_KEYS:
            ok = isinstance(actual, (int, float)) and actual >= 0
            rows.append(
                (key, "live wall clock", actual, "PASS" if ok else "FAIL")
            )
        else:
            ok = _exactly_equal(expected, actual)
            rows.append((key, expected, actual, "PASS" if ok else "FAIL"))
        if not ok:
            failures.append(key)

    width = max(len(k) for k in ORACLE)
    print("\nReproduction comparison (oracle: results.json, seed 42, stub):")
    for key, expected, actual, verdict in rows:
        print(f"  {key:<{width}}  expected={expected!r}  actual={actual!r}  {verdict}")
    assert not failures, f"oracle keys not reproduced exactly: {failures}"


def test_oracle_covers_the_spec_61_contract():
    """Guard the oracle file itself: the frozen key set must be intact."""
    assert ORACLE["seed"] == 42
    assert ORACLE["n_complaints"] == 297
    assert ORACLE["f9_withheld_stub_fabrications"] == 10
    assert ORACLE["f9_leaked"] == 0


def test_rerun_is_deterministic(results):
    """A second run reproduces every deterministic key of the first."""
    second = run_pipeline(seed=42, generator="stub")
    for key in ORACLE:
        if key in LIVE_KEYS:
            continue
        assert second[key] == results[key], key
