"""Migration runner (SPEC 7.1, section 4 role split).

Runs synchronously over ADMIN_DATABASE_URL: it executes once at api
startup (the lifespan wraps it in ``asyncio.to_thread``) and DDL over a
pool buys nothing. Sequence per run:

1. Ensure the ``paritran_app`` LOGIN role exists and set its password.
   This happens BEFORE any migration applies because 001_schema.sql
   GRANTs to that role. All role SQL is built with ``psycopg.sql``
   composition; the password is never interpolated via string
   formatting and never logged.
2. Ensure the ``schema_migrations`` bookkeeping table.
3. Apply pending ``*.sql`` files in lexical order, each inside its own
   transaction together with its bookkeeping row.

A previously applied file whose sha256 no longer matches the recorded
checksum is a hard error, never a silent re-run (SPEC 7.1).
"""

import hashlib
from pathlib import Path

import psycopg
from psycopg import sql

APP_ROLE = "paritran_app"

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_BOOKKEEPING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    sha256     CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT now()
)
"""


class MigrationChecksumError(RuntimeError):
    """An already-applied migration file changed on disk (SPEC 7.1)."""


def _ensure_app_role(conn: psycopg.Connection, password: str) -> None:
    """Create paritran_app if absent, then set its password every run.

    Uses psycopg.sql composition (sql.Literal) because CREATE/ALTER ROLE
    cannot take server-side bind parameters. The password value never
    passes through str.format, f-strings, or logging.
    """
    row = conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)
    ).fetchone()
    if row is None:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(APP_ROLE), sql.Literal(password)
            )
        )
    conn.execute(
        sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
            sql.Identifier(APP_ROLE), sql.Literal(password)
        )
    )


def run_migrations(
    admin_dsn: str,
    app_role_password: str,
    migrations_dir: str | Path | None = None,
) -> list[str]:
    """Apply pending migrations; return the filenames applied this run.

    Idempotent: applied files are recorded in ``schema_migrations`` with
    their sha256 and skipped on later runs. A recorded file whose
    on-disk checksum differs raises MigrationChecksumError.
    """
    directory = Path(migrations_dir) if migrations_dir is not None else DEFAULT_MIGRATIONS_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {directory}")

    applied: list[str] = []
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        # Serialize concurrent runners (e.g. api restart races) so role
        # bootstrap and file application never interleave.
        conn.execute("SELECT pg_advisory_lock(hashtext('schema_migrations'))")
        try:
            with conn.transaction():
                _ensure_app_role(conn, app_role_password)
            with conn.transaction():
                conn.execute(_BOOKKEEPING_DDL)

            recorded: dict[str, str] = {
                filename: sha256.strip()
                for filename, sha256 in conn.execute(
                    "SELECT filename, sha256 FROM schema_migrations"
                ).fetchall()
            }

            for path in sorted(directory.glob("*.sql")):
                body = path.read_bytes()
                digest = hashlib.sha256(body).hexdigest()
                if path.name in recorded:
                    if recorded[path.name] != digest:
                        raise MigrationChecksumError(
                            f"migration {path.name} was already applied with "
                            f"sha256 {recorded[path.name]} but the file on disk "
                            f"now hashes to {digest}; refusing to continue "
                            "(SPEC 7.1: changed applied migrations are a hard error)"
                        )
                    continue
                with conn.transaction():
                    conn.execute(body.decode("utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations (filename, sha256) VALUES (%s, %s)",
                        (path.name, digest),
                    )
                applied.append(path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext('schema_migrations'))")

    return applied
