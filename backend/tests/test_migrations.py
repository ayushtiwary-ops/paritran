"""Migration runner behavior (SPEC 7.1): apply, rerun no-op, checksum drift.

The ``db`` session fixture already ran run_migrations once, so this module
asserts the recorded outcome, then exercises rerun idempotency and the
hard-error path for a mutated already-applied file using a throwaway
migrations directory (the runner's ``migrations_dir`` parameter exists for
exactly this kind of isolation).
"""

import hashlib
import re
from importlib import import_module
from pathlib import Path

import pytest

pytestmark = pytest.mark.db

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")

_CANARY_NAME = "990_checksum_canary.sql"
_CANARY_SQL_V1 = "CREATE TABLE IF NOT EXISTS pytest_checksum_canary (id INT);\n"
_CANARY_SQL_V2 = (
    "CREATE TABLE IF NOT EXISTS pytest_checksum_canary (id INT, mutated INT);\n"
)

_EXPECTED_TABLES = {
    "users",
    "runs",
    "complaints",
    "entities",
    "entity_mentions",
    "links",
    "networks",
    "network_members",
    "money_edges",
    "trails",
    "cases",
    "section_mappings",
    "claims",
    "packets",
    "officer_decisions",
    "eval_runs",
    "audit_log",
    "schema_migrations",
}


def _package_migrations_dir() -> Path:
    db_pkg = import_module("paritran.db")
    return Path(db_pkg.__file__).parent / "migrations"


def _cleanup_canary(db) -> None:
    with db.admin() as conn:
        conn.execute(
            "DELETE FROM schema_migrations WHERE filename = %s", (_CANARY_NAME,)
        )
        conn.execute("DROP TABLE IF EXISTS pytest_checksum_canary")
        conn.commit()


def test_001_schema_applied_and_recorded(db):
    """001 applies: bookkeeping row present, checksum real, tables exist."""
    with db.admin() as conn:
        rows = conn.execute(
            "SELECT filename, sha256 FROM schema_migrations ORDER BY filename"
        ).fetchall()
        present_tables = {
            r[0]
            for r in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }

    recorded = {filename: sha for filename, sha in rows}
    assert "001_schema.sql" in recorded
    for filename, sha in recorded.items():
        assert _SHA256_HEX.match(sha), f"{filename} sha256 is not 64 lowercase hex"

    missing = _EXPECTED_TABLES - present_tables
    assert not missing, f"schema tables missing after 001: {sorted(missing)}"

    # Recorded checksums match the shipped files byte for byte.
    migrations_dir = _package_migrations_dir()
    for filename, sha in recorded.items():
        path = migrations_dir / filename
        if path.exists():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == sha

    # Whatever the session fixture applied, it applied in lexical order.
    assert db.first_run_applied == sorted(db.first_run_applied)


def test_rerun_applies_nothing(db):
    from paritran.db.migrate import run_migrations

    assert run_migrations(db.admin_dsn, db.app_password) == []


def test_mutated_applied_file_is_hard_error(db, tmp_path):
    """A previously applied file whose sha256 changed must raise, not re-run."""
    from paritran.db.migrate import run_migrations

    canary = tmp_path / _CANARY_NAME
    canary.write_text(_CANARY_SQL_V1, encoding="utf-8")

    _cleanup_canary(db)  # defensive: prior sessions on a persistent database
    try:
        applied = run_migrations(
            db.admin_dsn, db.app_password, migrations_dir=tmp_path
        )
        assert _CANARY_NAME in applied

        # Unchanged rerun stays a no-op.
        assert (
            run_migrations(db.admin_dsn, db.app_password, migrations_dir=tmp_path)
            == []
        )

        # Mutate the applied file: HARD ERROR, and the mutation never executes.
        canary.write_text(_CANARY_SQL_V2, encoding="utf-8")
        with pytest.raises(Exception):
            run_migrations(db.admin_dsn, db.app_password, migrations_dir=tmp_path)

        with db.admin() as conn:
            cols = {
                r[0]
                for r in conn.execute(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'pytest_checksum_canary'"
                ).fetchall()
            }
        assert "mutated" not in cols, "mutated migration was silently re-run"
    finally:
        _cleanup_canary(db)
