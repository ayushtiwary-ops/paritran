"""Auth tests (SPEC 5, 9.1, 16): login, refresh, RBAC matrix, rate limits.

Uses the session-scoped ``db`` fixture (skips without a database). The
app's repo pool is initialized against the fixture DSN by pointing
DATABASE_URL at it before the TestClient lifespan runs.
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

# Not a real credential: test-process-only signing key.
TEST_JWT_SECRET = "test-only-jwt-secret-64-chars-not-a-real-credential-0000000000"

USERS = {
    "officer": ("officer1", "OFFICER1_PASSWORD"),
    "supervisor": ("supervisor1", "SUPERVISOR1_PASSWORD"),
    "auditor": ("auditor1", "AUDITOR1_PASSWORD"),
}

# Public by design (SPEC 9.1); everything else must 401 without a token.
PUBLIC_PATHS = {"/health", "/ready", "/metrics", "/api/auth/login", "/api/auth/refresh"}


@pytest.fixture
def api(db, monkeypatch):
    """TestClient over the app with the fixture database wired in."""
    monkeypatch.setenv("DATABASE_URL", db.app_dsn)
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    seed_users(get_settings())  # idempotent insert-only (db/seed.py)
    # Keep API tests on the honest degraded mapping path: no InLegalBERT
    # load in unit tests (mapping_degraded is asserted where relevant).
    monkeypatch.setattr(runstore, "_MAPPER_CACHE", [None])
    deps.limiter.reset()  # each test gets a fresh rate-limit budget
    with TestClient(main.app) as client:
        yield client
    get_settings.cache_clear()


def _password(role: str) -> str:
    return os.environ[USERS[role][1]]


def login(client, role: str) -> dict:
    username, _ = USERS[role]
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": _password(role)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_login_ok_returns_token_pair(api):
    body = login(api, "officer")
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["access_expires_in"] == get_settings().JWT_ACCESS_TTL_SECONDS
    assert body["refresh_expires_in"] == get_settings().JWT_REFRESH_TTL_SECONDS
    # The access token actually authenticates.
    ok = api.get("/api/audit/verify", headers=bearer(body["access_token"]))
    assert ok.status_code == 200


def test_login_bad_password_and_unknown_user_401(api):
    bad = api.post(
        "/api/auth/login",
        json={"username": "officer1", "password": "definitely-wrong"},
    )
    assert bad.status_code == 401
    unknown = api.post(
        "/api/auth/login",
        json={"username": "nobody-here", "password": "irrelevant"},
    )
    assert unknown.status_code == 401
    # One generic detail for both: no username enumeration.
    assert bad.json()["detail"] == unknown.json()["detail"]


def test_refresh_flow_issues_new_pair_and_rejects_access_tokens(api):
    pair = login(api, "supervisor")
    refreshed = api.post(
        "/api/auth/refresh", json={"refresh_token": pair["refresh_token"]}
    )
    assert refreshed.status_code == 200, refreshed.text
    new_pair = refreshed.json()
    assert new_pair["access_token"] and new_pair["refresh_token"]
    ok = api.get("/api/audit/verify", headers=bearer(new_pair["access_token"]))
    assert ok.status_code == 200

    # An ACCESS token presented as a refresh token is rejected (typ check).
    wrong_typ = api.post(
        "/api/auth/refresh", json={"refresh_token": pair["access_token"]}
    )
    assert wrong_typ.status_code == 401

    # A refresh token never authenticates a protected route.
    not_access = api.get(
        "/api/audit/verify", headers=bearer(pair["refresh_token"])
    )
    assert not_access.status_code == 401


def test_garbage_token_401(api):
    response = api.get("/api/audit/verify", headers=bearer("not.a.jwt"))
    assert response.status_code == 401


def test_role_matrix_403s(api):
    """SPEC 5 matrix: officer runs/decides, supervisor adds evaluation
    controls, auditor is read-only plus chain and tamper test."""
    officer = login(api, "officer")["access_token"]
    supervisor = login(api, "supervisor")["access_token"]
    auditor = login(api, "auditor")["access_token"]

    # Auditor is read-only: no runs, no artefacts, no decisions.
    assert (
        api.post("/api/intake/run", json={}, headers=bearer(auditor)).status_code
        == 403
    )
    decision = {
        "run_id": "x",
        "kind": "link",
        "ref": {"a": 1, "b": 2},
        "decision": "reject",
    }
    assert (
        api.post("/api/decisions", json=decision, headers=bearer(auditor)).status_code
        == 403
    )
    assert (
        api.get("/api/runs/nope", headers=bearer(auditor)).status_code == 403
    )

    # Tamper test is auditor ONLY (officer and supervisor rejected).
    for token in (officer, supervisor):
        assert (
            api.post("/api/audit/tamper-test", headers=bearer(token)).status_code
            == 403
        )

    # Reproduce is supervisor ONLY (officer and auditor rejected).
    for token in (officer, auditor):
        assert (
            api.post("/api/evaluation/reproduce", headers=bearer(token)).status_code
            == 403
        )

    # Supervisor passes every officer gate (officer implies supervisor).
    appended = api.post("/api/decisions", json=decision, headers=bearer(supervisor))
    assert appended.status_code == 200, appended.text

    # Every role reads the chain and the evaluation history.
    for token in (officer, supervisor, auditor):
        assert api.get("/api/audit/chain", headers=bearer(token)).status_code == 200
        assert (
            api.get("/api/evaluation/metrics", headers=bearer(token)).status_code
            == 200
        )


def test_every_api_route_requires_a_token(api):
    """No route is reachable without a valid token except the public set
    (SPEC 9.1: /health, /ready, /metrics, /api/auth/*)."""
    spec = main.app.openapi()
    checked = []
    for path, operations in sorted(spec["paths"].items()):
        if path in PUBLIC_PATHS:
            continue
        concrete = path.replace("{run_id}", "does-not-exist").replace("{idx}", "0")
        for method in operations:
            response = api.request(method.upper(), concrete)
            assert response.status_code == 401, (
                f"{method.upper()} {path} returned {response.status_code}"
                " without a token; expected 401"
            )
            checked.append(f"{method.upper()} {path}")
    # The sweep must actually cover the API surface.
    assert len(checked) >= 12, checked


def test_rate_limit_429_on_anonymous_burst(api):
    """Anonymous budget is 20/min (SPEC 5); the 21st login attempt in a
    burst is rejected with 429."""
    deps.limiter.reset()
    statuses = []
    for _ in range(21):
        response = api.post(
            "/api/auth/login",
            json={"username": "nobody-here", "password": "wrong"},
        )
        statuses.append(response.status_code)
    assert statuses[:20] == [401] * 20
    assert statuses[20] == 429
    deps.limiter.reset()  # do not starve later tests in this minute
