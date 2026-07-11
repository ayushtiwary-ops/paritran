"""Health, readiness, and metrics endpoint tests (SPEC 9.1, 12, 16).

The three component check functions are monkeypatched so the suite
needs no live Postgres, Ollama, or InLegalBERT snapshot.
"""

from fastapi.testclient import TestClient

import paritran.api.main as main


def _passing(name: str):
    async def check() -> dict[str, str]:
        return {"status": "ok", "detail": f"{name} reachable (test double)"}

    return check


def _failing(name: str):
    async def check() -> dict[str, str]:
        return {"status": "down", "detail": f"{name} unreachable (test double)"}

    return check


def _patch_checks(monkeypatch, db, ollama, model_files) -> None:
    monkeypatch.setattr(main, "check_db", db)
    monkeypatch.setattr(main, "check_ollama", ollama)
    monkeypatch.setattr(main, "check_model_files", model_files)


def test_health_and_ready_all_ok(monkeypatch):
    _patch_checks(
        monkeypatch, _passing("db"), _passing("ollama"), _passing("model_files")
    )
    with TestClient(main.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok"
        assert set(body["components"]) == {"db", "ollama", "model_files"}
        for component in body["components"].values():
            assert component["status"] == "ok"
            assert component["detail"]

        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ok"


def test_health_db_down_returns_503(monkeypatch):
    _patch_checks(
        monkeypatch, _failing("db"), _passing("ollama"), _passing("model_files")
    )
    with TestClient(main.app) as client:
        health = client.get("/health")
        assert health.status_code == 503
        body = health.json()
        assert body["status"] == "down"
        assert body["components"]["db"]["status"] == "down"

        ready = client.get("/ready")
        assert ready.status_code == 503


def test_ollama_down_health_degraded_ready_503(monkeypatch):
    _patch_checks(
        monkeypatch, _passing("db"), _failing("ollama"), _passing("model_files")
    )
    with TestClient(main.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "degraded"
        assert body["components"]["ollama"]["status"] == "down"
        assert body["components"]["db"]["status"] == "ok"

        ready = client.get("/ready")
        assert ready.status_code == 503
        assert ready.json()["components"]["ollama"]["status"] == "down"


def test_metrics_endpoint_exposed():
    with TestClient(main.app) as client:
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "http_request" in metrics.text or "python_info" in metrics.text
