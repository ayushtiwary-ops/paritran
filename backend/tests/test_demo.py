"""Demo-mode endpoint tests (SPEC 9.1, 14, 16).

Covered:

- ``POST /api/demo/plant-fabrication`` blocks a planted claim live (the
  gate WITHHELDs it against corpus v2) and is supervisor-gated.
- ``POST /api/demo/start`` is supervisor-gated and returns both stream
  urls.
- The full paced narrative: the demo beat stream carries demo.started, one
  beat per SPEC 14 beat (the planted fabrication blocked in beat 4, the
  tamper test breaking the chain in beat 5), and demo.completed; the run
  stream carries the nine pipeline stages and run.completed; and the beat
  2 link rejection landed a real decision.link.reject row on the audit
  chain.

All tests are db-marked and run against the disposable scratch database
the conftest ``db`` fixture provisions. The demo dwell is compressed with
PARITRAN_DEMO_SCALE so the narrative completes in a couple of seconds
while every beat and every number stays real.
"""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

import paritran.api.main as main
import paritran.api.runstore as runstore
import paritran.demo as demo
from paritran.api import deps
from paritran.config import get_settings
from paritran.db.seed import seed_users

pytestmark = pytest.mark.db

TEST_JWT_SECRET = "test-only-jwt-secret-64-chars-not-a-real-credential-0000000000"


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db.app_dsn)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    # Compress the paced narrative so the beats fire fast; every figure is
    # still the real run's, only the dwell shrinks.
    monkeypatch.setenv("PARITRAN_DEMO_SCALE", "0.02")
    get_settings.cache_clear()
    seed_users(get_settings())
    # Force the honest degraded mapping path (no InLegalBERT load in CI),
    # exactly as the audit tests do.
    monkeypatch.setattr(runstore, "_MAPPER_CACHE", [None])
    runstore.reset()
    demo.reset()
    deps.limiter.reset()
    with TestClient(main.app) as client:
        yield client
    get_settings.cache_clear()


def _token(client, username: str, password_var: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": os.environ[password_var]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _consume_sse(client, url: str, headers: dict, terminal: set[str], cap: int = 8000):
    """Read an SSE stream into a list of (event, data) until a terminal
    event or the cap. The demo/run streams close on their terminal event,
    so this returns promptly once the narrative finishes."""
    events: list[tuple[str, dict]] = []
    with client.stream("GET", url, headers=headers) as response:
        assert response.status_code == 200, response.text
        event_name = None
        for raw in response.iter_lines():
            line = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event_name is not None:
                payload = json.loads(line.split(":", 1)[1].strip())
                events.append((event_name, payload))
                if event_name in terminal:
                    break
                if len(events) >= cap:
                    break
                event_name = None
    return events


def test_plant_fabrication_blocks_live(api):
    supervisor = _token(api, "supervisor1", "SUPERVISOR1_PASSWORD")
    response = api.post("/api/demo/plant-fabrication", headers=supervisor)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "WITHHELD"
    assert body["blocked"] is True
    assert body["corpus_version"] == "v2"
    assert body["is_fabricated"] is True
    # Labelled as planted, next to its gate rule.
    assert "planted" in body["label"].lower()
    assert body["sub_class"] in ("invented_section", "unverifiable_quote")


def test_plant_fabrication_requires_supervisor(api):
    officer = _token(api, "officer1", "OFFICER1_PASSWORD")
    response = api.post("/api/demo/plant-fabrication", headers=officer)
    assert response.status_code == 403, response.text


def test_demo_start_requires_supervisor(api):
    officer = _token(api, "officer1", "OFFICER1_PASSWORD")
    response = api.post("/api/demo/start", headers=officer)
    assert response.status_code == 403, response.text


def test_demo_full_narrative(api):
    supervisor = _token(api, "supervisor1", "SUPERVISOR1_PASSWORD")

    started = api.post("/api/demo/start", headers=supervisor)
    assert started.status_code == 202, started.text
    body = started.json()
    demo_id = body["demo_id"]
    run_id = body["run_id"]
    assert body["seed"] == 42
    assert body["generator"] == "stub"
    assert body["demo_stream_url"] == f"/api/stream/demo/{demo_id}"
    assert body["run_stream_url"] == f"/api/stream/run/{run_id}"

    # --- the paced beat stream ---------------------------------------------
    beat_events = _consume_sse(
        api,
        body["demo_stream_url"],
        supervisor,
        terminal={"demo.completed", "demo.failed"},
    )
    names = [name for name, _ in beat_events]
    assert "demo.started" in names
    assert "demo.completed" in names, names
    assert "demo.failed" not in names, beat_events

    started_evt = next(p for n, p in beat_events if n == "demo.started")
    assert len(started_evt["payload"]["beats"]) == 5

    beats = {
        p["payload"]["index"]: p["payload"]
        for n, p in beat_events
        if n == "demo.beat"
    }
    assert set(beats) == {1, 2, 3, 4, 5}, sorted(beats)

    # Beat 2 rejected a real link and reported the audit seq.
    assert beats[2]["link_rejected"]["ok"] is True
    assert beats[2]["link_rejected"]["action"] == "decision.link.reject"
    assert beats[2]["link_rejected"]["seq"] > 0

    # Beat 3 carries the real traced percentage.
    assert isinstance(beats[3]["trail"]["pct_traced"], (int, float))

    # Beat 4 blocked the planted fabrication live.
    assert beats[4]["planted"]["blocked"] is True
    assert beats[4]["planted"]["verdict"] == "WITHHELD"
    assert beats[4]["planted"]["corpus_version"] == "v2"
    # The run's own F9 gate tallies are present and labelled.
    assert beats[4]["f9"]["generator_name"]

    # Beat 5 broke the scratch chain at the corrupted record.
    assert beats[5]["custody"]["tamper_broke_chain"] is True
    assert beats[5]["custody"]["chain_verified"] is True

    completed = next(p for n, p in beat_events if n == "demo.completed")
    assert completed["payload"]["beats"] == 5
    assert completed["payload"]["elapsed_sec"] < 90

    # --- the pipeline's own stream carried nine stages ----------------------
    run_events = _consume_sse(
        api,
        body["run_stream_url"],
        supervisor,
        terminal={"run.completed", "run.failed"},
    )
    stage_started = [
        p["stage"] for n, p in run_events if n == "stage.started"
    ]
    assert len(stage_started) == 9, stage_started
    assert set(stage_started) == {
        "ingest",
        "entity_resolution",
        "linkage",
        "money_trail",
        "triage",
        "legal_mapping",
        "f9_audit",
        "packet",
        "signoff",
    }
    assert any(n == "run.completed" for n, _ in run_events)

    # --- the link rejection is on the real audit chain ----------------------
    chain = api.get("/api/audit/chain?limit=1000", headers=supervisor)
    assert chain.status_code == 200, chain.text
    actions = [row["action"] for row in chain.json()["rows"]]
    assert "decision.link.reject" in actions


def test_demo_status_entry_completes(api):
    """The in-process demo entry flips to completed (belt and braces on the
    orchestrator, independent of the SSE transport)."""
    supervisor = _token(api, "supervisor1", "SUPERVISOR1_PASSWORD")
    body = api.post("/api/demo/start", headers=supervisor).json()
    demo_id = body["demo_id"]

    deadline = time.time() + 60
    entry = demo.get(demo_id)
    assert entry is not None
    while time.time() < deadline and entry.status == "running":
        time.sleep(0.2)
    assert entry.status == "completed", entry.error
