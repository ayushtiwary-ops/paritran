"""Audit API tests (SPEC 9.1, 7.2, 8.3, 16).

Decisions append to the DB-enforced chain, the chain lists and
verifies, and the auditor tamper test breaks a scratch copy at the
corrupted record while the real chain stays intact and gains a
tamper_test.run row.
"""

import os

import pytest
from fastapi.testclient import TestClient

import paritran.api.main as main
import paritran.api.runstore as runstore
from paritran.api import deps
from paritran.config import get_settings
from paritran.db.seed import seed_users

pytestmark = pytest.mark.db

TEST_JWT_SECRET = "test-only-jwt-secret-64-chars-not-a-real-credential-0000000000"


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


def _token(client, username: str, password_var: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": os.environ[password_var]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_decision_appends_and_chain_lists_and_verifies(api):
    officer = _token(api, "officer1", "OFFICER1_PASSWORD")

    decision = {
        "run_id": "run-under-review",
        "kind": "link",
        "ref": {"a": 12, "b": 41},
        "decision": "reject",
    }
    appended = api.post("/api/decisions", json=decision, headers=officer)
    assert appended.status_code == 200, appended.text
    row = appended.json()
    assert row["action"] == "decision.link.reject"
    assert len(row["hash"]) == 64 and len(row["prev_hash"]) == 64
    assert row["hash"] != row["prev_hash"]

    # A second decision chains onto the first.
    second = api.post(
        "/api/decisions",
        json={**decision, "kind": "claim", "decision": "accept"},
        headers=officer,
    )
    assert second.status_code == 200
    assert second.json()["action"] == "decision.claim.accept"
    assert second.json()["seq"] > row["seq"]

    # The ledger lists the appended rows with their payloads.
    chain = api.get(
        "/api/audit/chain", params={"limit": 1000}, headers=officer
    )
    assert chain.status_code == 200
    body = chain.json()
    seqs = [r["seq"] for r in body["rows"]]
    assert seqs == sorted(seqs)
    by_seq = {r["seq"]: r for r in body["rows"]}
    assert by_seq[row["seq"]]["action"] == "decision.link.reject"
    assert by_seq[row["seq"]]["actor"] == "officer1"
    assert by_seq[row["seq"]]["payload"]["ref"] == {"a": 12, "b": 41}

    # And the whole chain verifies clean in the database.
    verify = api.get("/api/audit/verify", headers=officer)
    assert verify.status_code == 200
    assert verify.json() == {"ok": True, "first_bad_seq": None}


def test_tamper_test_breaks_scratch_only_and_is_itself_audited(api):
    officer = _token(api, "officer1", "OFFICER1_PASSWORD")
    auditor = _token(api, "auditor1", "AUDITOR1_PASSWORD")

    # Guarantee a mid-chain (>= 3 rows) by appending real decisions.
    for i in range(3):
        response = api.post(
            "/api/decisions",
            json={
                "run_id": "tamper-setup",
                "kind": "link",
                "ref": {"a": i, "b": i + 1},
                "decision": "accept",
            },
            headers=officer,
        )
        assert response.status_code == 200

    # Officer may not run it (auditor only).
    assert api.post("/api/audit/tamper-test", headers=officer).status_code == 403

    result = api.post("/api/audit/tamper-test", headers=auditor)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["scratch_rows"] >= 3
    # Verification over the corrupted scratch copy breaks exactly at the
    # corrupted record, which is mid-chain (never first, never last).
    assert body["break_seq"] == body["corrupted_seq"]
    assert body["real_chain_ok"] is True

    # The REAL chain still verifies clean afterwards.
    verify = api.get("/api/audit/verify", headers=auditor)
    assert verify.json() == {"ok": True, "first_bad_seq": None}

    # And the demo itself was appended to the real chain.
    chain = api.get(
        "/api/audit/chain", params={"limit": 1000}, headers=auditor
    ).json()
    by_seq = {r["seq"]: r for r in chain["rows"]}
    audit_row = by_seq[body["audit_seq"]]
    assert audit_row["action"] == "tamper_test.run"
    assert audit_row["actor"] == "auditor1"
    assert audit_row["payload"]["break_seq"] == body["break_seq"]
    # Mid-chain: strictly between the first and last pre-existing rows.
    pre_existing = [s for s in by_seq if s < body["audit_seq"]]
    assert min(pre_existing) < body["corrupted_seq"] <= max(pre_existing)

    # The scratch table did not leak into the real schema.
    verify_again = api.get("/api/audit/verify", headers=auditor)
    assert verify_again.json()["ok"] is True


def test_chain_pagination(api):
    officer = _token(api, "officer1", "OFFICER1_PASSWORD")
    full = api.get("/api/audit/chain", params={"limit": 1000}, headers=officer).json()
    assert full["total"] >= 2
    page = api.get(
        "/api/audit/chain", params={"limit": 1, "offset": 1}, headers=officer
    ).json()
    assert len(page["rows"]) == 1
    assert page["rows"][0]["seq"] == full["rows"][1]["seq"]
