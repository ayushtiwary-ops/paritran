"""Paritran data layer (SPEC section 7).

Modules:

- migrate: sync migration runner over ADMIN_DATABASE_URL. Creates the
  non-owner ``paritran_app`` LOGIN role before any migration applies,
  then applies plain numbered SQL files in lexical order with sha256
  bookkeeping in ``schema_migrations``.
- repo: async application-side access over DATABASE_URL via a lazily
  opened psycopg_pool.AsyncConnectionPool. Owns audit appends and chain
  verification calls; never computes hashes in Python (the DB trigger
  of SPEC 7.2 owns the chain).
- seed: idempotent seeding of the three SPEC section 5 users with
  argon2id password hashes.

Submodules are imported explicitly by callers (``from paritran.db
import migrate``) rather than re-exported here, so importing
``paritran.db`` stays free of psycopg and argon2 import costs.
"""
