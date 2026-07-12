"""Run lifecycle over the API (SPEC 9.1, 6.1, 16).

Starts a real seed-42 stub pipeline run through POST /api/intake/run,
polls GET /api/runs/{run_id} to completion, and asserts the results
contain every deterministic oracle key with the exact committed values
(loaded from results.json, never re-typed here). Also covers networks,
the case packet, F9 claims, evaluation metrics, and reproduce.

The completed run is cached at module level: the runstore is process
wide, so one pipeline execution serves every test in this file.
"""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

import paritran.api.main as main
import paritran.api.runstore as runstore
from paritran import pipeline
from paritran.api import deps
from paritran.config import get_settings
from paritran.db.seed import seed_users

from _paths import ORACLE_RESULTS

pytestmark = pytest.mark.db

TEST_JWT_SECRET = "test-only-jwt-secret-64-chars-not-a-real-credential-0000000000"
RUN_DEADLINE_SECONDS = 240

# Module-level cache: {"run_id": ...} once a seed-42 stub run completed.
_COMPLETED = {}

# Oracle keys that are exact at seed 42 (SPEC 6.1); time_to_packet_sec is
# live wall clock and money/section method strings are compared too.
LIVE_ONLY_KEYS = {"time_to_packet_sec"}


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db.app_dsn)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    seed_users(get_settings())
    monkeypatch.setattr(runstore, "_MAPPER_CACHE", [None])
    deps.limiter.reset()
    with TestClient(main.app) as client:
        yield client
    get_settings.cache_clear()


def _token(client, username: str, password_var: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": os.environ[password_var]},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def officer(client) -> dict:
    return {"Authorization": f"Bearer {_token(client, 'officer1', 'OFFICER1_PASSWORD')}"}


def supervisor(client) -> dict:
    return {
        "Authorization": f"Bearer {_token(client, 'supervisor1', 'SUPERVISOR1_PASSWORD')}"
    }


def _wait_for_completion(client, run_id: str, headers: dict) -> dict:
    deadline = time.monotonic() + RUN_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] == "failed":
            pytest.fail(f"run failed: {body['error']}")
        if body["status"] == "completed":
            return body
        time.sleep(0.5)
    pytest.fail(f"run {run_id} did not complete within {RUN_DEADLINE_SECONDS}s")


def completed_run(client, headers: dict) -> dict:
    """Start (or reuse) one completed seed-42 stub run; return its status."""
    run_id = _COMPLETED.get("run_id")
    if run_id and runstore.get(run_id) and runstore.get(run_id).status == "completed":
        response = client.get(f"/api/runs/{run_id}", headers=headers)
        assert response.status_code == 200
        return response.json()
    started = client.post(
        "/api/intake/run",
        json={"seed": 42, "generator": "stub"},
        headers=headers,
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    body = _wait_for_completion(client, run_id, headers)
    _COMPLETED["run_id"] = run_id
    return body


def test_stub_run_completes_with_exact_oracle_values(api, db):
    headers = officer(api)
    body = completed_run(api, headers)
    results = body["results"]
    oracle = json.loads(ORACLE_RESULTS.read_text(encoding="utf-8"))

    # Every deterministic oracle key equals the committed value exactly
    # (SPEC 6.1); nothing here is asserted against a re-typed literal.
    for key, value in oracle.items():
        assert key in results, f"oracle key {key!r} missing from run results"
        if key in LIVE_ONLY_KEYS:
            assert isinstance(results[key], (int, float))
        else:
            assert results[key] == value, (
                f"{key}: run produced {results[key]!r}, oracle says {value!r}"
            )

    # Honest degradation labels for the unit-test environment (the mapper
    # cache is pinned to None, so mapping must say it degraded).
    assert results["mapping_degraded"] is True
    assert results["semantic_unavailable"] is True
    assert results["f9_degraded"] is False

    # Persistence landed: a runs row and an eval_runs row, ids reported.
    assert body["persist_error"] is None
    assert body["db_run_id"] is not None
    assert body["eval_run_id"] is not None
    with db.admin() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT seed, status, metrics->>'n_complaints' FROM runs WHERE id = %s",
                (body["db_run_id"],),
            )
            seed, status, n_complaints = cur.fetchone()
            assert (seed, status) == (42, "completed")
            assert int(n_complaints) == oracle["n_complaints"]
            cur.execute(
                "SELECT generator, metrics->>'networks_found' FROM eval_runs"
                " WHERE id = %s",
                (body["eval_run_id"],),
            )
            generator, networks_found = cur.fetchone()
            assert generator == "stub"
            assert int(networks_found) == oracle["networks_found"]


def test_unknown_run_404(api):
    response = api.get("/api/runs/no-such-run", headers=officer(api))
    assert response.status_code == 404


def test_networks_listing_is_deterministic_and_complete(api):
    headers = officer(api)
    run = completed_run(api, headers)
    run_id = run["run_id"]

    first = api.get("/api/networks", params={"run_id": run_id}, headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()

    assert body["run_id"] == run_id
    assert len(body["networks"]) == run["results"]["networks_found"]
    assert body["graph"]["nodes"] == sorted(body["graph"]["nodes"])
    assert body["graph"]["edges"], "linkage graph has edges at seed 42"

    for network in body["networks"]:
        assert network["size"] >= 5  # SPEC 6.3 community floor
        assert network["members"] == sorted(network["members"])
        assert network["size"] == len(network["members"])
        triage = network["triage"]
        assert triage is not None
        # All four formula inputs displayed next to the score (SPEC 6.5).
        assert len(triage["inputs"]) == 4
        trail = network["trail"]
        assert trail is not None
        assert trail["hops"], "every seed-42 network has money-trail hops"
        assert trail["breaks"] == []  # seed-42 ledger is complete
        assert trail["traced_amt"] <= trail["total_amt"]

    # Byte-identical on a second read (deterministic ordering).
    second = api.get("/api/networks", params={"run_id": run_id}, headers=headers)
    assert second.json() == body

    # Single-network view matches the listing entry.
    one = api.get(
        "/api/networks/0", params={"run_id": run_id}, headers=headers
    )
    assert one.status_code == 200
    assert one.json() == body["networks"][0]

    out_of_range = api.get(
        f"/api/networks/{len(body['networks'])}",
        params={"run_id": run_id},
        headers=headers,
    )
    assert out_of_range.status_code == 404


def test_case_packet_and_stub_claims(api):
    headers = officer(api)
    run = completed_run(api, headers)
    run_id = run["run_id"]

    packet = api.get(f"/api/cases/{run_id}/packet", headers=headers)
    assert packet.status_code == 200, packet.text
    body = packet.json()
    assert len(body["chain_head"]) == 64
    assert body["case"]["case_id"].startswith("SEED42-NET")
    assert body["complaints"], "packet lists the network's complaints"
    assert all(len(c["intake_hash"]) == 64 for c in body["complaints"])

    claims = api.post(
        f"/api/cases/{run_id}/claims",
        json={"generator": "stub"},
        headers=headers,
    )
    assert claims.status_code == 200, claims.text
    f9 = claims.json()
    results = run["results"]
    assert f9["generator_name"] == results["generator_name"]
    assert f9["is_stub"] is True
    assert f9["degraded"] is False
    assert f9["corpus_version"] == "v1"
    # Same frozen baseline the run itself produced (SPEC 6.1).
    assert (f9["claims"], f9["passed"], f9["withheld"], f9["leaked"]) == (
        results["f9_claims"],
        results["f9_passed"],
        results["f9_withheld"],
        results["f9_leaked"],
    )
    assert len(f9["verdicts"]) == f9["claims"]
    withheld = [v for v in f9["verdicts"] if v["verdict"] == "WITHHELD"]
    assert len(withheld) == f9["withheld"]
    assert {v["sub_class"] for v in withheld} == {
        "invented_section",
        "unverifiable_quote",
    }


def test_reproduce_returns_baseline_and_matches(api):
    headers = supervisor(api)
    started = api.post("/api/evaluation/reproduce", headers=headers)
    assert started.status_code == 202, started.text
    body = started.json()
    oracle = json.loads(ORACLE_RESULTS.read_text(encoding="utf-8"))
    assert body["baseline"] == oracle
    assert body["seed"] == 42
    assert body["generator"] == "stub"

    finished = _wait_for_completion(api, body["run_id"], headers)
    results = finished["results"]
    for key, value in oracle.items():
        if key in LIVE_ONLY_KEYS:
            continue
        assert results[key] == value

    # The reproduce run landed in evaluation history, latest first.
    history = api.get(
        "/api/evaluation/metrics", params={"limit": 5}, headers=headers
    )
    assert history.status_code == 200
    rows = history.json()["rows"]
    assert rows, "eval_runs history is non-empty after a persisted run"
    assert rows[0]["id"] == max(r["id"] for r in rows)  # latest first
    assert rows[0]["metrics"]["n_complaints"] == oracle["n_complaints"]
    assert rows[0]["sample_sizes"]["complaints"] == oracle["n_complaints"]
    assert set(rows[0]["latencies"]) == set(pipeline.STAGES)
