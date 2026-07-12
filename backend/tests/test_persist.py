"""Persistence tests (SPEC 7.1, 13): persist_run writes coherent rows and
run_eval(persist=True) lands an eval_runs row. Needs the db fixture."""

import pytest

from paritran.db.persist import persist_run
from paritran.eval import harness
from paritran.pipeline import execute

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def artifacts():
    return execute(seed=42, generator="stub")


def _one(conn, query, *params):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def test_persist_run_writes_coherent_rows(db, artifacts):
    run_id = persist_run(
        artifacts.results,
        artifacts.bundle,
        artifacts.linkage_result,
        artifacts.trail_result,
        artifacts.triage_scores,
        artifacts.mappings,
        artifacts.f9_result,
        dsn=db.app_dsn,
    )
    bundle = artifacts.bundle
    graph = artifacts.linkage_result.graph
    communities = artifacts.linkage_result.communities

    with db.admin() as conn:
        status, metrics, latencies = _one(
            conn,
            "SELECT status, metrics, stage_latencies FROM runs WHERE id = %s",
            run_id,
        )
        assert status == "completed"
        assert metrics["n_complaints"] == 297
        assert metrics["seed"] == 42
        assert set(latencies) == set(artifacts.results["stage_latencies_ms"])

        (n_complaints,) = _one(
            conn, "SELECT count(*) FROM complaints WHERE run_id = %s", run_id
        )
        assert n_complaints == 297
        (n_hashed,) = _one(
            conn,
            "SELECT count(*) FROM complaints"
            " WHERE run_id = %s AND length(intake_hash) = 64",
            run_id,
        )
        assert n_hashed == 297

        (n_entities,) = _one(
            conn, "SELECT count(*) FROM entities WHERE run_id = %s", run_id
        )
        assert n_entities == len({i for c in bundle.complaints for i in c.ids})
        (n_mentions,) = _one(
            conn,
            "SELECT count(*) FROM entity_mentions em"
            " JOIN complaints c ON c.id = em.complaint_id"
            " WHERE c.run_id = %s",
            run_id,
        )
        assert n_mentions == sum(len(c.ids) for c in bundle.complaints)

        (n_links,) = _one(
            conn, "SELECT count(*) FROM links WHERE run_id = %s", run_id
        )
        assert n_links == graph.number_of_edges()

        (n_networks,) = _one(
            conn, "SELECT count(*) FROM networks WHERE run_id = %s", run_id
        )
        assert n_networks == 6 == len(communities)
        (n_members,) = _one(
            conn,
            "SELECT count(*) FROM network_members nm"
            " JOIN networks n ON n.id = nm.network_id"
            " WHERE n.run_id = %s",
            run_id,
        )
        assert n_members == sum(len(c) for c in communities)

        (n_trails,) = _one(
            conn,
            "SELECT count(*) FROM trails t"
            " JOIN networks n ON n.id = t.network_id"
            " WHERE n.run_id = %s",
            run_id,
        )
        assert n_trails == 6
        traced, total = _one(
            conn,
            "SELECT sum(t.traced_amt), sum(t.total_amt) FROM trails t"
            " JOIN networks n ON n.id = t.network_id WHERE n.run_id = %s",
            run_id,
        )
        assert traced == artifacts.trail_result.traced_amt
        noise = sum(c.amt for c in bundle.complaints if c.synd < 0)
        assert total + noise == artifacts.trail_result.total_amt

        (n_money,) = _one(
            conn, "SELECT count(*) FROM money_edges WHERE run_id = %s", run_id
        )
        assert n_money == bundle.money.number_of_edges()

        # Seed-42 fact: the ledger is complete, so no persisted breaks.
        (n_with_breaks,) = _one(
            conn,
            "SELECT count(*) FROM trails t"
            " JOIN networks n ON n.id = t.network_id"
            " WHERE n.run_id = %s AND jsonb_array_length(t.breaks) > 0",
            run_id,
        )
        assert n_with_breaks == 0


def test_run_eval_persist_lands_eval_runs_row(db, monkeypatch):
    # Deterministic in CI: force the degraded (no-semantic) path so this
    # db test never depends on local model weights. The semantic path is
    # exercised by run_eval outside db-marked tests.
    monkeypatch.setattr(harness, "_build_semantic_index", lambda corpus: None)
    monkeypatch.delenv("GIT_SHA", raising=False)

    results = harness.run_eval(
        persist=True, seed=42, generator="stub", dsn=db.app_dsn
    )
    assert results["semantic_unavailable"] is True
    assert results["mapping_degraded"] is True
    eval_run_id = results["eval_run_id"]

    with db.admin() as conn:
        row = _one(
            conn,
            "SELECT git_sha, dataset_version, corpus_version, generator,"
            " model_tag, metrics, latencies, sample_sizes"
            " FROM eval_runs WHERE id = %s",
            eval_run_id,
        )
        git_sha, dataset_version, corpus_version, generator, model_tag, \
            metrics, latencies, sample_sizes = row
        assert git_sha == "unknown"
        assert dataset_version == "v1+v2"
        assert corpus_version == "v1+v2"
        assert generator == "stub"
        assert model_tag == "deterministic-stub"
        assert metrics["n_complaints"] == 297
        assert metrics["semantic_unavailable"] is True
        assert set(latencies) == set(results["stage_latencies_ms"])
        assert sample_sizes == {
            "golden_v1": 21,
            "extended_v2": 60,
            "complaints": 297,
        }
