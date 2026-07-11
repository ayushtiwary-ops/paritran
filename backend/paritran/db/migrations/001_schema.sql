-- 001_schema.sql: Paritran data layer (SPEC.md sections 4, 5, 7, 8).
-- Applied by the migration runner over ADMIN_DATABASE_URL inside one transaction.
-- Assumes the non-owner LOGIN role paritran_app already exists (runner creates it first).
-- Plain SQL only, no psql meta-commands.

-- SPEC 7.2: pgcrypto provides digest() for the audit hash chain.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Domain tables (SPEC 7.1)
-- ---------------------------------------------------------------------------

CREATE TABLE users (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('officer', 'supervisor', 'auditor')),
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE runs (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  seed            INT NOT NULL,
  git_sha         TEXT,
  dataset_version TEXT,
  generator       TEXT,
  model_tag       TEXT,
  status          TEXT NOT NULL DEFAULT 'running',
  metrics         JSONB,
  stage_latencies JSONB,
  started_at      TIMESTAMPTZ DEFAULT now(),
  finished_at     TIMESTAMPTZ
);

CREATE TABLE complaints (
  id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id      BIGINT REFERENCES runs(id),
  ext_id      INT NOT NULL,
  synd        INT NOT NULL,
  amt         BIGINT NOT NULL,
  mule        TEXT NOT NULL,
  narrative   TEXT,
  lang        TEXT,
  intake_hash CHAR(64),
  UNIQUE (run_id, ext_id)
);

CREATE TABLE entities (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id     BIGINT REFERENCES runs(id),
  identifier TEXT NOT NULL,
  kind       TEXT,
  UNIQUE (run_id, identifier)
);

CREATE TABLE entity_mentions (
  complaint_id BIGINT REFERENCES complaints(id),
  entity_id    BIGINT REFERENCES entities(id),
  PRIMARY KEY (complaint_id, entity_id)
);

CREATE TABLE links (
  id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id BIGINT REFERENCES runs(id),
  a      BIGINT REFERENCES complaints(id),
  b      BIGINT REFERENCES complaints(id),
  weight INT NOT NULL,
  status TEXT NOT NULL DEFAULT 'suggested'
);

CREATE TABLE networks (
  id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id BIGINT REFERENCES runs(id),
  idx    INT NOT NULL,
  size   INT NOT NULL,
  triage JSONB,
  UNIQUE (run_id, idx)
);

CREATE TABLE network_members (
  network_id   BIGINT REFERENCES networks(id),
  complaint_id BIGINT REFERENCES complaints(id),
  PRIMARY KEY (network_id, complaint_id)
);

CREATE TABLE money_edges (
  id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id BIGINT REFERENCES runs(id),
  src    TEXT NOT NULL,
  dst    TEXT NOT NULL
);

CREATE TABLE trails (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  network_id BIGINT REFERENCES networks(id),
  hops       JSONB,
  traced_amt BIGINT,
  total_amt  BIGINT,
  breaks     JSONB
);

CREATE TABLE cases (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id     BIGINT REFERENCES runs(id),
  network_id BIGINT REFERENCES networks(id),
  status     TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE section_mappings (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  case_id      BIGINT REFERENCES cases(id),
  complaint_id BIGINT REFERENCES complaints(id),
  sections     JSONB,
  confidence   TEXT,
  paths        JSONB
);

CREATE TABLE claims (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  case_id    BIGINT REFERENCES cases(id),
  generator  TEXT NOT NULL,
  section    TEXT,
  quote      TEXT,
  verdict    TEXT,
  reason     TEXT,
  sub_class  TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE packets (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  case_id    BIGINT REFERENCES cases(id),
  content    JSONB,
  chain_head CHAR(64),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE officer_decisions (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  case_id    BIGINT REFERENCES cases(id),
  actor      TEXT NOT NULL,
  decision   TEXT NOT NULL,
  target     JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE eval_runs (
  id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  git_sha         TEXT,
  dataset_version TEXT,
  corpus_version  TEXT,
  generator       TEXT,
  model_tag       TEXT,
  metrics         JSONB,
  latencies       JSONB,
  sample_sizes    JSONB,
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- audit_log: DB-enforced hash chain, append-only (SPEC 7.2, SPEC 8)
-- ---------------------------------------------------------------------------

-- seq is assigned exclusively by the hash-chain trigger from this dedicated
-- sequence, inside the advisory lock: one draw per row, so the ledger shows a
-- dense sequence (gaps only from aborted transactions), and seq order equals
-- chain order by construction. An identity column would be assigned BEFORE
-- the trigger runs and fork the chain under concurrency.
CREATE TABLE audit_log (
  seq       BIGINT PRIMARY KEY,
  ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor     TEXT NOT NULL,
  action    TEXT NOT NULL,
  payload   JSONB NOT NULL,
  prev_hash CHAR(64) NOT NULL,
  hash      CHAR(64) NOT NULL
);
CREATE SEQUENCE audit_log_seq OWNED BY audit_log.seq;

-- SPEC 7.2: a forked chain cannot even commit, independent of the advisory lock.
CREATE UNIQUE INDEX audit_log_prev_hash_key ON audit_log (prev_hash);

-- SPEC 7.2: BEFORE INSERT trigger; serializes appends, sets prev_hash from the
-- committed head (never trusts a client value), hashes a canonical GUC-immune
-- preimage (ts enters as epoch text, jsonb text output is deterministic).
-- SECURITY DEFINER: the trigger's nextval() and head lookup run with the
-- owner's rights, so paritran_app needs no sequence grant at all (its
-- audit_log privileges stay exactly SELECT and INSERT). search_path is
-- pinned, standard definer-function hygiene.
CREATE FUNCTION audit_log_hash_chain() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  last_hash CHAR(64);
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('audit_log'));
  -- The trigger owns every integrity-bearing column. seq comes from the
  -- dedicated sequence inside the lock (seq order equals chain order); ts is
  -- server-assigned so a client cannot backdate or future-date a custody
  -- entry and have the hash certify the lie; prev_hash never trusts a client.
  NEW.seq := nextval('audit_log_seq');
  NEW.ts  := clock_timestamp();
  SELECT hash INTO last_hash FROM audit_log ORDER BY seq DESC LIMIT 1;
  IF last_hash IS NULL THEN
    last_hash := repeat('0', 64);
  END IF;
  NEW.prev_hash := last_hash;
  NEW.hash := encode(digest(jsonb_build_object(
      'prev', NEW.prev_hash,
      'actor', NEW.actor,
      'action', NEW.action,
      'payload', NEW.payload,
      'ts_epoch', extract(epoch FROM NEW.ts)::text
    )::text, 'sha256'), 'hex');
  RETURN NEW;
END;
$$;

CREATE TRIGGER audit_log_hash_chain
  BEFORE INSERT ON audit_log
  FOR EACH ROW
  EXECUTE FUNCTION audit_log_hash_chain();

-- SPEC 7.2: append-only enforcement. UPDATE, DELETE, and TRUNCATE all hit the
-- trigger, including the table-owner path. Residual (SPEC 8.4 threat model):
-- a superuser can still disable triggers; the out-of-band chain-head anchor
-- is the answer to that class, not this trigger.
CREATE FUNCTION audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END;
$$;

CREATE TRIGGER audit_log_append_only
  BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW
  EXECUTE FUNCTION audit_log_append_only();

CREATE TRIGGER audit_log_no_truncate
  BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT
  EXECUTE FUNCTION audit_log_append_only();

-- SPEC 7.2: verify_audit_chain() walks the chain recomputing hashes with the
-- identical canonical encoding; returns the first bad seq, NULL when clean.
CREATE FUNCTION verify_audit_chain() RETURNS BIGINT
LANGUAGE plpgsql STABLE
AS $$
DECLARE
  expected   TEXT := repeat('0', 64);
  recomputed TEXT;
  r          RECORD;
BEGIN
  FOR r IN
    SELECT seq, ts, actor, action, payload, prev_hash, hash
    FROM audit_log
    ORDER BY seq
  LOOP
    IF r.prev_hash <> expected THEN
      RETURN r.seq;
    END IF;
    recomputed := encode(digest(jsonb_build_object(
        'prev', r.prev_hash,
        'actor', r.actor,
        'action', r.action,
        'payload', r.payload,
        'ts_epoch', extract(epoch FROM r.ts)::text
      )::text, 'sha256'), 'hex');
    IF recomputed <> r.hash THEN
      RETURN r.seq;
    END IF;
    expected := r.hash;
  END LOOP;
  RETURN NULL;
END;
$$;

-- SPEC 7.2: RLS enabled with SELECT and INSERT policies only for paritran_app.
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_log_app_select ON audit_log
  FOR SELECT TO paritran_app USING (true);

CREATE POLICY audit_log_app_insert ON audit_log
  FOR INSERT TO paritran_app WITH CHECK (true);

-- ---------------------------------------------------------------------------
-- Grants: least privilege for paritran_app (SPEC section 4 role split)
-- ---------------------------------------------------------------------------

GRANT SELECT, INSERT, UPDATE, DELETE ON
  users,
  runs,
  complaints,
  entities,
  entity_mentions,
  links,
  networks,
  network_members,
  money_edges,
  trails,
  cases,
  section_mappings,
  claims,
  packets,
  officer_decisions,
  eval_runs
TO paritran_app;

-- USAGE on every domain identity sequence so paritran_app can insert.
DO $$
DECLARE
  t       TEXT;
  seqname TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'users', 'runs', 'complaints', 'entities', 'links', 'networks',
    'money_edges', 'trails', 'cases', 'section_mappings', 'claims',
    'packets', 'officer_decisions', 'eval_runs'
  ] LOOP
    seqname := pg_get_serial_sequence(t, 'id');
    IF seqname IS NOT NULL THEN
      EXECUTE format('GRANT USAGE ON SEQUENCE %s TO paritran_app', seqname);
    END IF;
  END LOOP;
END;
$$;

-- SPEC 7.2: audit_log gets exactly SELECT and INSERT, and the explicit REVOKE.
GRANT SELECT, INSERT ON audit_log TO paritran_app;
REVOKE UPDATE, DELETE ON audit_log FROM paritran_app;
