"""Shared fixtures for the Paritran backend test suite (SPEC section 16).

Milestone 2 wiring:

- RUN_MIGRATIONS_ON_STARTUP is forced to "false" before any test module
  imports paritran code, so unit tests never reach a live database through
  the api lifespan, and the get_settings cache is cleared so the override
  is actually observed.
- The session-scoped ``db`` fixture probes ADMIN_DATABASE_URL with a two
  second budget. When the admin DSN does not connect, every db-marked test
  is skipped with reason "database unreachable". When it does connect, the
  fixture runs paritran.db.migrate.run_migrations once and yields a
  connection factory covering both the admin role and the app role.

Environment inputs (CI sets all of them; local runs without a database fall
back to inert defaults that simply fail the reachability probe):

- ADMIN_DATABASE_URL: paritran_admin DSN, used for migrations and assertions.
- DATABASE_URL: paritran_app DSN. Derived from the admin DSN when absent.
- APP_DB_PASSWORD: password the migration runner sets on paritran_app.
- OFFICER1_PASSWORD / SUPERVISOR1_PASSWORD / AUDITOR1_PASSWORD: seed users.

No secrets live in this file. The fallback values below are test-only
placeholders for throwaway scratch databases.
"""

import os

# Must run before any test module imports paritran.api or paritran.config,
# and conftest import precedes test module collection, so this is the spot.
os.environ["RUN_MIGRATIONS_ON_STARTUP"] = "false"
os.environ.setdefault("APP_DB_PASSWORD", "test-only-app-password")
os.environ.setdefault("OFFICER1_PASSWORD", "test-only-officer1-password")
os.environ.setdefault("SUPERVISOR1_PASSWORD", "test-only-supervisor1-password")
os.environ.setdefault("AUDITOR1_PASSWORD", "test-only-auditor1-password")

from dataclasses import dataclass, field  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg import conninfo  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

try:
    from paritran.config import get_settings

    get_settings.cache_clear()
except ImportError:  # pragma: no cover - partial checkouts during parallel work
    pass

CONNECT_PROBE_SECONDS = 2

# Inert placeholder, not a secret: with no server listening the probe fails
# fast and the db-marked tests skip.
_DEFAULT_ADMIN_DSN = "postgresql://paritran_admin:CHANGE_ME@localhost:5432/paritran"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "db: test needs a live Postgres reachable via ADMIN_DATABASE_URL",
    )


def _derive_app_dsn(admin_dsn: str, app_password: str) -> str:
    """Rebuild the admin DSN as a paritran_app DSN (same host, port, dbname)."""
    params = conninfo.conninfo_to_dict(admin_dsn)
    params["user"] = "paritran_app"
    params["password"] = app_password
    return conninfo.make_conninfo(**params)


@dataclass
class DbHandle:
    """Connection factory yielded by the ``db`` fixture."""

    admin_dsn: str
    app_dsn: str
    app_password: str
    first_run_applied: list[str] = field(default_factory=list)

    def admin(self, **kwargs) -> psycopg.Connection:
        """New connection as paritran_admin (schema owner)."""
        return psycopg.connect(self.admin_dsn, connect_timeout=10, **kwargs)

    def app(self, **kwargs) -> psycopg.Connection:
        """New connection as paritran_app (least-privilege role)."""
        return psycopg.connect(self.app_dsn, connect_timeout=10, **kwargs)

    @staticmethod
    def append_audit(conn: psycopg.Connection, actor: str, action: str, payload: dict):
        """Append one audit row on ``conn`` and commit it.

        Returns (seq, prev_hash, hash) as stored by the BEFORE INSERT trigger.
        """
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (actor, action, payload)"
                " VALUES (%s, %s, %s) RETURNING seq, prev_hash, hash",
                (actor, action, Jsonb(payload)),
            )
            row = cur.fetchone()
        conn.commit()
        return row


@pytest.fixture(autouse=True)
def _no_startup_migrations():
    """Keep startup migrations off and the settings cache fresh for every test."""
    os.environ["RUN_MIGRATIONS_ON_STARTUP"] = "false"
    try:
        from paritran.config import get_settings as cached_settings

        cached_settings.cache_clear()
    except ImportError:  # pragma: no cover - partial checkouts
        pass
    yield


TEST_DB_NAME = "paritran_test"


def _with_dbname(dsn: str, dbname: str) -> str:
    """Rebuild a DSN pointing at a different database on the same server."""
    params = conninfo.conninfo_to_dict(dsn)
    params["dbname"] = dbname
    return conninfo.make_conninfo(**params)


@pytest.fixture(scope="session")
def db():
    """Migrated handle on a DISPOSABLE database, or a skip when unreachable.

    The suite never touches the live application database: the fixture
    creates (drop-if-exists, then create) a dedicated ``paritran_test``
    database on the same server, migrates it, and points every DSN at it.
    Without this, the concurrency hammer would leave a hundred-plus test
    rows in the production audit ledger. The env DATABASE_URL is
    deliberately ignored here for the same reason. The test database is
    dropped again at session end, best effort.

    The reachability probe budget is CONNECT_PROBE_SECONDS. Because the
    fixture is session scoped, the probe runs once and its skip outcome is
    reused for every db-marked test in the session.
    """
    admin_dsn = os.environ.get("ADMIN_DATABASE_URL", _DEFAULT_ADMIN_DSN)
    app_password = os.environ["APP_DB_PASSWORD"]

    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=CONNECT_PROBE_SECONDS)
        probe.close()
    except psycopg.OperationalError:
        pytest.skip("database unreachable")

    with psycopg.connect(admin_dsn, autocommit=True) as bootstrap:
        bootstrap.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
        bootstrap.execute(f"CREATE DATABASE {TEST_DB_NAME}")

    test_admin_dsn = _with_dbname(admin_dsn, TEST_DB_NAME)

    # Imported lazily so pytest --collect-only works even before the
    # milestone 2 db package lands (it is written in parallel).
    from paritran.db.migrate import run_migrations

    applied = run_migrations(test_admin_dsn, app_password)

    yield DbHandle(
        admin_dsn=test_admin_dsn,
        app_dsn=_derive_app_dsn(test_admin_dsn, app_password),
        app_password=app_password,
        first_run_applied=list(applied),
    )

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as cleanup:
            cleanup.execute(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)")
    except psycopg.OperationalError:  # pragma: no cover - teardown best effort
        pass
