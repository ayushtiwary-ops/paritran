"""Concurrent audit appends must serialize into one unforked chain (SPEC 7.2).

32 threads, each holding its own sync psycopg connection as paritran_app,
each appending 4 rows in separate transactions. The advisory xact lock plus
the unique index on prev_hash must yield: verify_audit_chain() clean, exactly
128 new rows, and globally count(*) == count(DISTINCT prev_hash).
"""

import threading

import pytest

pytestmark = pytest.mark.db

THREADS = 32
ROWS_PER_THREAD = 4
JOIN_TIMEOUT_SECONDS = 120


def test_parallel_appends_keep_chain_intact(db):
    with db.admin() as conn:
        baseline = conn.execute("SELECT count(*) FROM audit_log").fetchone()[0]

    barrier = threading.Barrier(THREADS)
    errors: list[Exception] = []
    errors_lock = threading.Lock()

    def worker(worker_id: int) -> None:
        try:
            with db.app() as conn:
                barrier.wait(timeout=60)
                for row_idx in range(ROWS_PER_THREAD):
                    db.append_audit(
                        conn,
                        f"pytest-worker-{worker_id}",
                        "test.concurrency.append",
                        {"worker": worker_id, "row": row_idx},
                    )
        except Exception as exc:  # surfaced below, never swallowed
            with errors_lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(i,), name=f"audit-worker-{i}")
        for i in range(THREADS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=JOIN_TIMEOUT_SECONDS)

    stuck = [t.name for t in threads if t.is_alive()]
    assert not stuck, f"workers did not finish in time: {stuck}"
    assert not errors, f"worker appends failed: {errors[:3]}"

    with db.admin() as conn:
        total, distinct_prev = conn.execute(
            "SELECT count(*), count(DISTINCT prev_hash) FROM audit_log"
        ).fetchone()
        broken_at = conn.execute("SELECT verify_audit_chain()").fetchone()[0]

    assert broken_at is None, f"chain verification broke at seq {broken_at}"
    assert total == baseline + THREADS * ROWS_PER_THREAD
    assert total == distinct_prev, "prev_hash values are not globally unique"
