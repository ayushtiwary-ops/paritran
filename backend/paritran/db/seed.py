"""Seed the SPEC section 5 users: officer1, supervisor1, auditor1.

Sync on purpose: it runs once at api startup right after migrations
(the lifespan wraps it in ``asyncio.to_thread``). Connects over
DATABASE_URL as ``paritran_app``, which is exactly the privilege the
seeding needs (INSERT on users, INSERT on audit_log).

Insert-only by design: an existing user is never touched, so reruns
mutate nothing (no re-hash, no audit row). Rotating a seeded user's
password is an explicit admin action, not a startup side effect. The
ON CONFLICT DO NOTHING + RETURNING form reports exactly the rows this
statement inserted, with no reliance on the fragile xmax heuristic.

Passwords are argon2id-hashed with argon2-cffi defaults. Plaintext
passwords never enter SQL text (bind parameters only, and only the
hash is stored), are never printed, and never appear in any log line
or audit payload raised from this module.
"""

import psycopg
from argon2 import PasswordHasher
from psycopg.types.json import Jsonb

_INSERT_IF_ABSENT = """
INSERT INTO users (username, password_hash, role)
VALUES (%s, %s, %s)
ON CONFLICT (username) DO NOTHING
RETURNING username
"""

_AUDIT_INSERT = """
INSERT INTO audit_log (actor, action, payload)
VALUES (%s, %s, %s)
"""


def seed_users(settings) -> list[str]:
    """Ensure the three seeded users exist; return their usernames.

    Idempotent: insert-only, so a rerun changes no row and appends no
    audit entry. One audit row (action 'user.seeded') per NEWLY
    created user only.
    """
    hasher = PasswordHasher()  # argon2-cffi defaults: argon2id
    wanted = [
        ("officer1", settings.OFFICER1_PASSWORD, "officer"),
        ("supervisor1", settings.SUPERVISOR1_PASSWORD, "supervisor"),
        ("auditor1", settings.AUDITOR1_PASSWORD, "auditor"),
    ]

    ensured: list[str] = []
    with psycopg.connect(settings.DATABASE_URL) as conn:
        for username, password, role in wanted:
            row = conn.execute(
                _INSERT_IF_ABSENT, (username, hasher.hash(password), role)
            ).fetchone()
            newly_created = row is not None
            if newly_created:
                conn.execute(
                    _AUDIT_INSERT,
                    (
                        "system",
                        "user.seeded",
                        Jsonb({"username": username, "role": role}),
                    ),
                )
            ensured.append(username)
        conn.commit()
    return ensured
