"""Session GUCs must not affect the audit hash preimage (SPEC 7.2, 16).

The trigger feeds ts into the hash as an epoch string precisely because
timestamptz::text varies with TimeZone and DateStyle. So appending and
verifying under shifted GUCs must still yield a clean chain.
"""

import pytest

pytestmark = pytest.mark.db


def test_chain_verifies_under_shifted_session_gucs(db):
    # Rows appended under default session GUCs.
    with db.app() as conn:
        for i in range(3):
            db.append_audit(conn, "pytest-guc", "test.guc.append_default", {"i": i})

    # New session with shifted rendering GUCs: verification must not care.
    with db.app() as conn:
        conn.execute("SET TimeZone TO 'Asia/Kolkata'")
        conn.execute("SET DateStyle TO 'German, DMY'")
        assert conn.execute("SELECT verify_audit_chain()").fetchone()[0] is None

        # Appending under the shifted GUCs must hash identically too.
        db.append_audit(conn, "pytest-guc", "test.guc.append_shifted", {"i": 99})
        assert conn.execute("SELECT verify_audit_chain()").fetchone()[0] is None

    # And a fresh default session agrees the chain is still clean.
    with db.app() as conn:
        assert conn.execute("SELECT verify_audit_chain()").fetchone()[0] is None
