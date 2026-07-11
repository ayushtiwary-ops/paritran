"""audit_log protections as seen by paritran_app (SPEC 7.2, 8, 16).

Covers: INSERT allowed; UPDATE and DELETE rejected at the database level;
the privilege matrix itself (has_table_privilege); verify_audit_chain()
clean; and the trigger overwriting any client-supplied prev_hash.
"""

import psycopg
import pytest
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.db

# UPDATE/DELETE may die on the REVOKE (42501 InsufficientPrivilege) or, in a
# defense-in-depth world where a grant slipped back in, on the append-only
# trigger (P0001 RaiseException). Either way the write must not land.
_REJECTED = (psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)

_ZERO_HASH = "0" * 64


def test_app_can_insert_audit_row(db):
    with db.app() as conn:
        seq, prev_hash, row_hash = db.append_audit(
            conn, "pytest-rls", "test.rls.insert", {"probe": "insert"}
        )
    assert seq >= 1
    assert len(prev_hash) == 64
    assert len(row_hash) == 64
    assert row_hash != _ZERO_HASH


def test_app_update_rejected(db):
    with db.app() as conn:
        db.append_audit(conn, "pytest-rls", "test.rls.update_target", {"n": 1})
        with pytest.raises(_REJECTED):
            conn.execute(
                "UPDATE audit_log SET actor = 'tampered'"
                " WHERE action = 'test.rls.update_target'"
            )
        conn.rollback()


def test_app_delete_rejected(db):
    with db.app() as conn:
        db.append_audit(conn, "pytest-rls", "test.rls.delete_target", {"n": 1})
        with pytest.raises(_REJECTED):
            conn.execute(
                "DELETE FROM audit_log WHERE action = 'test.rls.delete_target'"
            )
        conn.rollback()


def test_owner_update_hits_append_only_trigger(db):
    """Even the table owner path is stopped by the BEFORE UPDATE trigger."""
    with db.app() as conn:
        seq, _, _ = db.append_audit(
            conn, "pytest-rls", "test.rls.owner_target", {"n": 1}
        )
    with db.admin() as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(
                "UPDATE audit_log SET actor = 'tampered' WHERE seq = %s", (seq,)
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("DELETE FROM audit_log WHERE seq = %s", (seq,))
        conn.rollback()


def test_privilege_matrix_for_app_role(db):
    with db.app() as conn:
        row = conn.execute(
            "SELECT has_table_privilege('paritran_app', 'audit_log', 'SELECT'),"
            "       has_table_privilege('paritran_app', 'audit_log', 'INSERT'),"
            "       has_table_privilege('paritran_app', 'audit_log', 'UPDATE'),"
            "       has_table_privilege('paritran_app', 'audit_log', 'DELETE')"
        ).fetchone()
    can_select, can_insert, can_update, can_delete = row
    assert can_select is True
    assert can_insert is True
    assert can_update is False, "paritran_app must not hold UPDATE on audit_log"
    assert can_delete is False, "paritran_app must not hold DELETE on audit_log"


def test_verify_chain_clean(db):
    with db.app() as conn:
        db.append_audit(conn, "pytest-rls", "test.rls.verify", {"probe": "verify"})
        assert conn.execute("SELECT verify_audit_chain()").fetchone()[0] is None


def test_client_supplied_prev_hash_is_overwritten(db):
    """The trigger never trusts a client prev_hash; the chain stays intact."""
    bogus = "f" * 64
    with db.app() as conn:
        head = conn.execute(
            "SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        expected_prev = head[0] if head else _ZERO_HASH

        stored_prev, stored_hash = conn.execute(
            "INSERT INTO audit_log (actor, action, payload, prev_hash, hash)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING prev_hash, hash",
            ("pytest-rls", "test.rls.bogus_prev", Jsonb({"bogus": True}), bogus, bogus),
        ).fetchone()
        conn.commit()

        assert stored_prev != bogus, "trigger trusted a client-supplied prev_hash"
        assert stored_prev == expected_prev
        assert stored_hash != bogus
        assert conn.execute("SELECT verify_audit_chain()").fetchone()[0] is None
