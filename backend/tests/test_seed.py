"""Seeded users (SPEC section 5): creation, argon2id hashes, idempotency.

seed_users(settings) must ensure officer1/supervisor1/auditor1 with the
right roles, hash the env-provided passwords with argon2id, and append one
'user.seeded' audit row per NEWLY created user only, so a rerun changes
nothing and appends nothing.
"""

import os

import pytest

pytestmark = pytest.mark.db

_SEEDED_ROLES = {
    "officer1": "officer",
    "supervisor1": "supervisor",
    "auditor1": "auditor",
}

_PASSWORD_ENV = {
    "officer1": "OFFICER1_PASSWORD",
    "supervisor1": "SUPERVISOR1_PASSWORD",
    "auditor1": "AUDITOR1_PASSWORD",
}


def _make_settings(db):
    """Settings instance pointed at the test database, env passwords intact.

    Explicit kwargs keep the test independent of any .env file on disk.
    """
    from paritran.config import Settings

    return Settings(
        ADMIN_DATABASE_URL=db.admin_dsn,
        DATABASE_URL=db.app_dsn,
        APP_DB_PASSWORD=db.app_password,
        OFFICER1_PASSWORD=os.environ["OFFICER1_PASSWORD"],
        SUPERVISOR1_PASSWORD=os.environ["SUPERVISOR1_PASSWORD"],
        AUDITOR1_PASSWORD=os.environ["AUDITOR1_PASSWORD"],
        RUN_MIGRATIONS_ON_STARTUP=False,
    )


def _seeded_audit_count(db) -> int:
    with db.admin() as conn:
        return conn.execute(
            "SELECT count(*) FROM audit_log WHERE action = 'user.seeded'"
        ).fetchone()[0]


def _fetch_seeded_users(db) -> dict[str, tuple[str, str]]:
    """username -> (role, password_hash) for the three seeded usernames."""
    with db.admin() as conn:
        rows = conn.execute(
            "SELECT username, role, password_hash FROM users"
            " WHERE username = ANY(%s)",
            (list(_SEEDED_ROLES),),
        ).fetchall()
    return {username: (role, password_hash) for username, role, password_hash in rows}


def test_seed_users_creates_roles_and_argon2id_hashes(db):
    from argon2 import PasswordHasher

    from paritran.db.seed import seed_users

    # Isolation on persistent databases: observe actual creation this session.
    with db.admin() as conn:
        conn.execute(
            "DELETE FROM users WHERE username = ANY(%s)", (list(_SEEDED_ROLES),)
        )
        conn.commit()

    audit_before = _seeded_audit_count(db)
    ensured = seed_users(_make_settings(db))
    assert set(_SEEDED_ROLES) <= set(ensured)

    users = _fetch_seeded_users(db)
    assert set(users) == set(_SEEDED_ROLES)

    hasher = PasswordHasher()
    for username, (role, password_hash) in users.items():
        assert role == _SEEDED_ROLES[username]
        assert password_hash.startswith("$argon2id$"), (
            f"{username} hash is not argon2id"
        )
        assert hasher.verify(password_hash, os.environ[_PASSWORD_ENV[username]])

    assert _seeded_audit_count(db) - audit_before == len(_SEEDED_ROLES), (
        "expected exactly one user.seeded audit row per newly created user"
    )


def test_seed_users_rerun_is_idempotent(db):
    from paritran.db.seed import seed_users

    settings = _make_settings(db)
    seed_users(settings)  # ensure the three exist regardless of test order

    users_before = _fetch_seeded_users(db)
    audit_before = _seeded_audit_count(db)

    ensured = seed_users(settings)
    assert set(_SEEDED_ROLES) <= set(ensured)

    users_after = _fetch_seeded_users(db)
    assert users_after == users_before, "rerun mutated seeded users"
    assert _seeded_audit_count(db) == audit_before, (
        "rerun appended duplicate user.seeded audit rows"
    )

    with db.admin() as conn:
        count = conn.execute(
            "SELECT count(*) FROM users WHERE username = ANY(%s)",
            (list(_SEEDED_ROLES),),
        ).fetchone()[0]
    assert count == len(_SEEDED_ROLES), "rerun duplicated seeded users"
