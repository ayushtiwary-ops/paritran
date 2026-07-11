# PARITRAN | Build Specification (SPEC.md)

**Product:** Paritran, "From complaint to conviction." An on-premise, zero-egress, court-admissibility engine for the Cyber Crime Branch.
**Event:** KANAD S.H.I.E.L.D. 2026 Grand Finale, 27 to 28 July 2026, iHub Gujarat. Team Paritran, PS-69EEFE4F8CD1C, Category 2.
**This document is the contract.** Every milestone diff is adversarially reviewed against it. If code and SPEC disagree, one of them is wrong and the build stops until they agree.
**Status legend used throughout:** REAL (computed live by the named method), STUB (deterministic stand-in behind the production interface, labelled in the UI), MOCKED (visual only, labelled in the UI). Nothing on screen may be silently MOCKED.

---

## 0. Locked decisions (founder-confirmed, 11 July 2026)

| Decision | Value | Consequence |
|---|---|---|
| Demo machine | This Mac (Apple Silicon, macOS) | Ollama runs natively on the host (`gemma3:4b`, already pulled). Docker runs Postgres, API, frontend, Prometheus, Grafana. Offline bundle targets arm64. |
| InLegalBERT | Pulled and cached (`law-ai/InLegalBERT`) | Semantic rerank is REAL. The lift over the 52.4 percent BM25 floor is measured on the Evaluation screen and decomposed against a BM25-only corpus-v2 ablation, so the rerank effect is isolated from the corpus effect. Model files ship inside the offline bundle. |
| Brand | "Paritran" alone, tagline "From complaint to conviction" | No "CrimeGPT" anywhere in UI or docs. Palette and type per Section 10. |
| Generative model | `gemma3:4b` via host Ollama (env-configurable) | The deck's `gemma:2b` reference is superseded. `OLLAMA_MODEL` env var controls the tag. |

---

## 1. Non-negotiable truth rules

1. **Every number shown anywhere in the UI is produced by the real method, live, from the engine.** No hardcoded metric values anywhere between engine and screen (frontend or API layer). Proof, in strength order: (a) the Judge's-seed control (Section 14) reruns the pipeline with an arbitrary seed and every number moves accordingly, which no canned value survives; (b) the Section 17 grep is a spot-check only, never claimed as the proof; (c) the frontend renders numbers only from SSE/REST payloads (Section 9.3).
2. The three fixes are first-class engine code: (a) money trail by directed-graph reachability, (b) legal mapping by BM25 plus InLegalBERT rerank plus rule-layer agreement, (c) F9 groundedness gate over a real generative step (Ollama Gemma live; deterministic fabricating stub behind the identical interface when the model is down, always labelled).
3. Synthetic data only. Zero real complainant, victim, or accused data. Anything mocked is labelled mocked.
4. **Baseline reproduction contract (Section 6.1):** the deterministic seed-42 metrics must equal `results.json` exactly. Wall-clock timings are measured live and never baseline-compared.
5. **Corpus honesty:** the prototype's 7-entry corpus contains condensed section descriptions, not verbatim statute text. The app may not display those lines under a "quoted word for word from the bare act" label. Section 7.3 splits the corpus into v1 (baseline, frozen) and v2 (verbatim bare-act text for the packet). This closes an honesty gap a code-reading judge would find.
6. **Own the post-submission correction publicly.** The submitted PDF's Appendix A contained the three placeholder computations the red team flagged (random-draw money trail 87.3, keyword mapper 90.5, tautological F9, linkage 0.929/0.944/0.936). The repo slice already computes the real methods with re-measured numbers. `docs/CHANGELOG_POST_SUBMISSION.md` (plus one line in README and one deck line) states this plainly, old vs new numbers side by side. Silence reads as history rewriting; owning it is the strongest answer to that kill-shot.
7. **One-time prototype wording revision, then freeze.** The current prototype and `results.json` self-describe the v1 corpus as "bare-act" text and the stub's withheld claims as "real hallucinations", and compute `f9_leaked` vacuously (testing `gate(c)` on items already filtered by `not gate(c)`, 0 by construction). One revision, in Milestone 1, fixes strings and that one computation only: `section_method` becomes "Okapi BM25 over condensed section-description corpus (v1)", key `f9_withheld_real_hallucinations` becomes `f9_withheld_stub_fabrications`, comments corrected, and `f9_leaked` recomputed meaningfully as ground-truth-labelled fabrications that PASS the gate (value stays 0, now non-tautologically). Every numeric value must remain identical; README/DATASHEET update to match; the change lands in the changelog. From that revision forward the file is frozen.

---

## 2. System overview

Nine-stage pipeline, one deterministic core, a fenced language layer:

```
1 ingest (SHA-256 hashed)  -> 2 entity resolution -> 3 linkage graph
-> 4 money trail (reachability) -> 5 predictive triage (accounts, not people)
-> 6 grounded legal mapping (rules + BM25 + InLegalBERT, agreement)
-> 7 Section 63 packet -> 8 groundedness audit (F9) -> 9 officer sign-off
```

Services (docker compose):

| Service | Image / build | Port (host) | Role |
|---|---|---|---|
| `db` | postgres:16 (alpine) | none (core network only; psql via `docker compose exec db`) | Data + DB-enforced hash-chained audit log |
| `api` | `backend/` (python:3.11-slim) | 8090 -> 8000 | FastAPI, engine, SSE, auth, eval harness |
| `web` | `frontend/` (nginx serving Vite build) | 8081 -> 80 | React app, fonts and assets vendored |
| `prometheus` | prom/prometheus | none (core network only; judges see Grafana) | Scrapes `api /metrics` |
| `grafana` | grafana/grafana | 3001 -> 3000 | Provisioned dashboard |
| (host) | Ollama, native macOS | 11434 | `gemma3:4b`, reached at `host.docker.internal:11434` |

Network topology (buildable as written): network `core` (`internal: true`) carries db and Prometheus scrape traffic; network `edge` (regular bridge) carries the published ports above and the api's route to host-local Ollama (`host.docker.internal` via `extra_hosts: host-gateway`). Docker cannot both publish ports and block WAN on the same network, so zero egress is **measured, not asserted**: the api exposes an egress self-test (outbound TCP attempt to a routable address, 2 s timeout) and a config audit (the complete list of configured outbound endpoints, which is exactly one: host-local Ollama). The Security Posture panel displays both, timestamped. The demo runs with the machine's Wi-Fi off, so the self-test shows outbound blocked at the OS level, live, in front of the judge.

---

## 3. Repository layout

```
paritran_repo/
  SPEC.md  NOTES.md  README.md  LICENSE  CITATION.cff
  src/paritran_prototype.py      # judge-verifiable slice; one wording-only revision (rule 7), then frozen
  results.json                   # regenerated by the slice; the baseline contract
  dataset/DATASHEET.md           # updated to describe v1 + v2 golden sets
  dataset/samples/               # one synthetic complaint PDF + one scan image for OCR ingest
  docs/ARCHITECTURE.md  docs/RUNBOOK_DEMO_DAY.md  docs/SECURITY.md  docs/CHANGELOG_POST_SUBMISSION.md
  backend/
    pyproject.toml  requirements.txt (fully pinned)
    paritran/
      config.py                  # pydantic-settings, all env vars
      pipeline.py                # 9-stage orchestrator, emits typed events
      engine/
        synthetic.py             # promoted generator, RNG contract in 6.2
        linkage.py  money_trail.py  triage.py  ner.py  ingest_ocr.py
        legal/ (corpus_v1.json, corpus_v2.json, authoritative/ (official India Code text + sha256),
                bm25.py, semantic.py, rules.py, mapper.py)
        f9/ (gate.py, claims.py)
        custody/chain.py
        packet/section63.py
      llm/ (client.py protocol, ollama_client.py, stub.py)
      db/ (schema.sql, migrations/NNN_*.sql, repo.py, seed.py)
      api/ (main.py, sse.py, auth.py, deps.py,
            routers/{intake,networks,cases,packets,audit,evaluation,security,health,demo}.py)
      eval/ (harness.py, golden/section_mapping_v1.json, golden/extended_v2.json)
    tests/                       # pytest; names in Section 16
  frontend/
    package.json  vite.config.ts  index.html
    src/ (design/tokens.css, lib/{api,sse,format}.ts, app routes,
          components/{graph,trail,packet,custody,evaluation,posture,status,palette}/...)
    tests/ (vitest)  e2e/ (playwright demo-mode smoke)
  infra/
    docker/ (Dockerfile.api, Dockerfile.web, nginx.conf)
    grafana/provisioning/ (datasource + dashboard JSON)
    prometheus/prometheus.yml
    scans/ (run_all.sh, out/*.json artifacts)
  scripts/ (bootstrap_env.sh, ci_local.sh, bundle_save.sh, bundle_load.sh, demo_preflight.sh)
  .github/workflows/ci.yml
  .env.example  docker-compose.yml  Makefile
```

`src/paritran_prototype.py` receives exactly one wording-only revision (truth rule 7), is then frozen for good, and supersedes the submitted Appendix A per `docs/CHANGELOG_POST_SUBMISSION.md`. It stays runnable standalone by a judge.

---

## 4. Environment variables (`.env.example`)

```
DATABASE_URL=postgresql://paritran_app:CHANGE_ME@db:5432/paritran
POSTGRES_PASSWORD=CHANGE_ME
JWT_SECRET=CHANGE_ME                  # bootstrap_env.sh generates 64 hex chars
JWT_ACCESS_TTL_SECONDS=900
JWT_REFRESH_TTL_SECONDS=28800
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=gemma3:4b
OLLAMA_TIMEOUT_SECONDS=30
INLEGALBERT_PATH=/models/InLegalBERT  # HF snapshot mounted read-only into api
SEED=42
DEMO_MODE=false
SOUND_DEFAULT=off
```

`scripts/bootstrap_env.sh` creates `.env` from `.env.example` with random secrets if `.env` is absent. No secrets in the repo, ever (gitleaks enforces).

---

## 5. Roles and auth

- JWT access tokens (15 min) + refresh tokens (8 h). Argon2id password hashing. Tokens carry `sub`, `role`.
- Roles: `officer` (run pipeline, accept/reject links, assemble packets), `supervisor` (officer rights + approve packet + evaluation controls), `auditor` (read-only + custody chain + tamper test + security posture).
- Seeded users `officer1`, `supervisor1`, `auditor1`; passwords generated into `.env` by bootstrap, printed once.
- slowapi rate limiting keyed by JWT `sub`: officer 120/min, supervisor 120/min, auditor 60/min, unauthenticated 20/min.
- Every officer decision and every artefact event writes to the audit chain (Section 8).

---

## 6. Engine package (the deterministic core)

### 6.1 Baseline reproduction contract

`POST /api/evaluation/reproduce` and `pytest tests/test_reproduction.py` re-run the seed-42 pipeline. These values must equal `results.json` **exactly**:

| Metric | Required value | Class |
|---|---|---|
| n_complaints | 297 | exact |
| networks_found | 6 (of 6 seeded) | exact |
| linkage precision / recall / F1 | 0.957 / 0.966 / 0.962 | exact |
| pct_value_traced_to_cashout | 90.8 | exact |
| section_accuracy_bm25 (corpus v1, golden v1) | 52.4 | exact |
| f9 stub path: claims / passed / withheld / leaked | 50 / 40 / 10 / 0 (leaked recomputed per rule 7: ground-truth fabrications that PASS) | exact |
| chain_len / chain_verified / tamper_detected | 12 / true / true | exact |
| time_to_packet_sec | measured live | live, display only |
| BM25-only over corpus v2, golden v1 (ablation) | measured; isolates the corpus effect from the rerank effect | live-measured, logged per run |
| full-stack section accuracy (BM25+InLegalBERT+rules, corpus v2) | measured, reported honestly | live-measured, logged per run |
| F9 over live Ollama output | measured, reported honestly | live-measured, logged per run |
| NER extraction P/R on synthetic text | measured | live-measured |
| p50/p95 latency per stage | measured | live-measured |

### 6.2 `engine/synthetic.py`, RNG contract (critical)

The promoted generator must reproduce the prototype's **exact draw order** on one `random.Random(seed)` instance (Mersenne Twister, identical to the prototype's global `random.seed(42)` sequence):

1. Per syndicate s in 0..5: `randint` phones(2,4), devices(1,3), ips(1,2), l1(2,3); then complaint count `randint(25,55)`; per complaint: `randint(1,3)` inside `sample`, `random() < 0.06` bleed check (plus `randint(0,5)` only when it fires), `randint(5,500)` amount, `choice(l1)` mule.
2. 40 noise complaints: `randint(5,300)` each.
3. Money ledger, after all complaints: per syndicate, per L1 mule `random() < 0.93`, then `random() < 0.98` for L2 to cash.

**Complaint narrative text (new, for NER/legal/UI) must not consume this stream.** Text is drawn from `random.Random(f"text/{seed}/{complaint_id}")` (string seeding is sha512-based and platform-stable). A unit test locks structural equality against the prototype's output.

Narratives: deterministic templates per fraud archetype (OTP/vishing, fake trading app, impersonation, mule ring, phishing, parcel scam), embedding the complaint's known identifiers so NER accuracy is measurable. Language mix: majority English, a deterministic subset Hindi and Gujarati (IndicNLP normalization at ingest). Amounts in the text match `amt`.

### 6.3 `engine/linkage.py` (REAL)

Same algorithm as the prototype: identifier-shared edges with weight, `networkx.algorithms.community.greedy_modularity_communities(weight="w")` (deterministic, no RNG), networks = communities of size >= 5, pairwise precision/recall/F1 vs ground truth. networkx pinned 3.4.2.

### 6.4 `engine/money_trail.py` (REAL)

Directed ledger walk exactly as the prototype (`nx.has_path` from complaint mule to syndicate cash-out). Additional REAL outputs for the UI, none of which perturb the metric:
- per-network trail paths (ordered hops victim -> L1 -> L2 -> cash) for the flow animation,
- break points (missing edges) flagged as freeze opportunities,
- per-network traced/untraced value totals.

### 6.5 `engine/triage.py` (REAL, accounts not people)

Recoverability score per network, a plain exposed function:
`score = 0.4*trail_completeness + 0.3*(1 - cashout_reached_fraction) + 0.2*recency_proxy + 0.1*amount_band`
All four inputs are displayed next to the score in the UI. Deterministic. Scores rank networks for the triage queue. No person-level features exist anywhere in the codebase.

### 6.6 `engine/ner.py` (REAL)

spaCy pipeline with an EntityRuler layered over regex patterns for Indian identifiers (phone formats, account numbers, IFSC-like codes, IPs, device IDs, UPI handles). Honest labelling: this is rule-augmented NER, and the UI says so. Measured against the identifiers embedded by the generator (P/R on the Evaluation screen). Gujarati/Hindi text passes through IndicNLP normalization (and transliteration where needed) before extraction.

### 6.7 `engine/legal/` (REAL, three paths + agreement)

- `corpus_v1.json`: the prototype's 7 entries, byte-identical. Drives the frozen 52.4 baseline only.
- `corpus_v2.json`: verbatim bare-act text for the app: BNS 111, 303, 308, 316, 318, 319, 336, 338; IT Act 43, 66, 66C, 66D; BSA 63 (for the certificate display). Each entry: `{id, act, section, title, text_verbatim, source_note}`. Provenance is enforced, not asserted: the official India Code digital text of each section is committed under `legal/authoritative/` with source URL, edition, and sha256, and a unit test asserts every `text_verbatim` is contained in its authoritative file. The F9 gate certifying quote-in-corpus is only as honest as corpus-in-statute, so both containments are tested. The packet quotes only from v2.
- `bm25.py`: the prototype's Okapi BM25 byte-for-byte (k1=1.5, b=0.75, topn=2, thresh=0.8) for the v1 baseline, plus the same implementation parameterized over v2 for the app path.
- `semantic.py`: InLegalBERT mean-pooled embeddings (`transformers`, local snapshot, truncation 256), cosine similarity, embeddings precomputed at startup and cached.
- `rules.py`: the deterministic keyword/pattern layer, honestly positioned as one of three paths (never a headline metric).
- `mapper.py`: full-stack mapping. Rank by `alpha*bm25_norm + (1-alpha)*cosine` with **alpha frozen at 0.5 before any golden-v1 scoring** (no tune-on-test on n=21; any tuning happens only on a disjoint dev split of golden v2, protocol recorded in eval_runs). Confidence: HIGH iff rule layer and retrieval agree on at least one section, else LOW and the case routes to the officer review queue. Reported on golden v1 (21 cases), three rows so the lift decomposes honestly: BM25-only over corpus v1 (52.4, frozen floor), BM25-only over corpus v2 (ablation, the corpus effect), full stack over corpus v2 (the InLegalBERT rerank effect is the delta vs the ablation). Human-routing rate reported alongside. Extended golden v2 (Section 7.3) reported separately, never replacing the v1 numbers.

### 6.8 `engine/f9/` (REAL gate over a real generative step)

Gate rule (unchanged): a claim `(section, quote)` passes iff the section exists in the target corpus AND the quote is a verbatim case-insensitive substring of that section's text. Catches paraphrase and invention.

Claim generators behind one protocol (`llm/client.py`):

```python
class ClaimGenerator(Protocol):
    name: str          # shown in the UI next to every F9 number
    is_stub: bool
    def generate_claims(self, case: CaseContext) -> list[Claim]  # Claim(section, quote)
```

- `ollama_client.py` (REAL): prompts `gemma3:4b` with case facts + the v2 corpus, instructs it to emit (section, quote) citations as JSON; parses leniently; every parsed claim goes through the gate. Timeout `OLLAMA_TIMEOUT_SECONDS`; on failure, degrade to the stub with an explicit UI banner ("model offline, deterministic stub active") and mandatory human review flag, per ARCHITECTURE.md failure handling.
- `stub.py` (STUB, labelled): the prototype's fabricating mock, byte-identical sequence (50 claims, 1-in-5 fabrication: 5 nonexistent "BNS 420", 5 plausible paraphrases). Gates against corpus v1. This is the frozen 40/10/0 baseline and the offline fallback. It fabricates, so the gate is exercised non-tautologically even without Ollama.
- Withheld claims are sub-classified: `invented_section` (cited section does not exist) vs `unverifiable_quote` (section exists, quote not verbatim; includes honest paraphrase). The UI metric is labelled "ungrounded (withheld) claim rate", never "hallucination rate": the verbatim gate is deliberately stricter than hallucination detection and withholds accurate paraphrase too. "Fabrication" is claimed only for the invented-section class and ground-truth-labelled plants.
- The UI always shows which generator produced the on-screen F9 numbers, and shows both the frozen stub baseline and the live Ollama run when available.

### 6.9 `engine/custody/chain.py` + DB enforcement (REAL)

In-memory chain: identical to the prototype (sha256(prev + canonical JSON)), used by the reproduce run (12 records, verified, tamper detected). Production chain: the `audit_log` table in Section 8, DB-enforced. The tamper test never corrupts the real chain (Section 8.3).

### 6.10 `engine/packet/section63.py` (REAL assembly, honest labels)

Assembles the case packet: case summary metadata, complaint list with intake hashes, network graph reference, money trail with break points, mapped sections with **verbatim v2 quotes** and clickable source references, F9 audit result for every claim, custody trail extract, and the BSA Section 63 certificate with Part A (person producing the record) and Part B (expert) **pre-filled with case facts and blank signature blocks**. The UI labels the certificate "drafted by Paritran, signed by the named custodian and independent expert". Paritran never certifies. Export: print-CSS rendered view (browser print to PDF).

### 6.11 `pipeline.py`

Orchestrates stages 1..9, timing each (p50/p95 aggregation in the eval store), emitting the SSE events of Section 9.3. Deterministic given (seed, corpus versions, generator choice).

---

## 7. Data layer

### 7.1 Schema (Postgres 16, plain SQL migrations applied at API startup)

Tables: `users`, `runs` (pipeline executions: seed, git_sha, dataset_version, model tags, metrics JSONB, stage latencies), `complaints`, `entities`, `entity_mentions`, `links`, `networks`, `network_members`, `money_edges`, `trails`, `cases`, `section_mappings`, `claims` (with f9 verdict + reason), `packets`, `officer_decisions`, `audit_log` (Section 8), `eval_runs`.

All engine outputs persist per run so the frontend reads only from the API/DB, never from bundled JSON.

### 7.2 `audit_log` (DB-enforced hash chain, append-only)

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE audit_log (
  seq        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor      TEXT NOT NULL,
  action     TEXT NOT NULL,          -- e.g. link.rejected, packet.assembled, artefact.ingested
  payload    JSONB NOT NULL,
  prev_hash  CHAR(64) NOT NULL,
  hash       CHAR(64) NOT NULL
);
```

- BEFORE INSERT trigger, concurrency-safe and canonical:
  1. `pg_advisory_xact_lock(hashtext('audit_log'))` first, so appends serialize. Stage completions and officer decisions insert concurrently during the demo; without the lock, two transactions read the same head under READ COMMITTED and fork the chain, making an untampered log fail verification.
  2. The trigger itself reads the last committed row's `hash` (or 64 zeros) and **sets** `NEW.prev_hash`; it never trusts a client-supplied value.
  3. The preimage is an unambiguous canonical encoding, immune to field-boundary collisions and to session GUCs (`timestamptz::text` varies with TimeZone/DateStyle, so `ts` enters as epoch): `NEW.hash = encode(digest(jsonb_build_object('prev', NEW.prev_hash, 'actor', NEW.actor, 'action', NEW.action, 'payload', NEW.payload, 'ts_epoch', extract(epoch from NEW.ts)::text)::text, 'sha256'), 'hex')`. (jsonb text output is deterministic for a given jsonb value.)
- `CREATE UNIQUE INDEX ON audit_log(prev_hash)`: a forked chain cannot even commit, independent of the lock.
- BEFORE UPDATE OR DELETE trigger: `RAISE EXCEPTION 'audit_log is append-only'`.
- `REVOKE UPDATE, DELETE ON audit_log FROM paritran_app;` plus RLS enabled with INSERT/SELECT policies only. Defense in depth: even the table owner path hits the trigger.
- `verify_audit_chain()` walks the chain recomputing hashes; exposed at `GET /api/audit/verify`.

### 7.3 Corpora and golden data versioning

- `corpus_v1.json` frozen forever (baseline). `corpus_v2.json` versioned; any edit bumps `dataset_version` recorded on every run.
- `golden/section_mapping_v1.json`: the prototype's 21 labelled cases, byte-identical.
- `golden/extended_v2.json`: 60 new labelled cases (English, Hindi, Gujarati mix; includes hard negatives) reported as a separate row with its own sample size. v2 never replaces v1 numbers.

---

## 8. Custody and the tamper test

1. Every artefact intake, engine stage completion, officer decision, packet assembly, and demo control action appends to `audit_log`.
2. The Custody Ledger screen renders the chain with per-row hash, prev-hash linkage, actor, action.
3. **Tamper test (auditor role):** the API snapshots the chain into a scratch table (no protections), corrupts one mid-chain record, runs verification over the scratch copy, and returns the break index. The UI renders the chain visibly breaking at that record. The real chain is never modified; the act of running a tamper test is itself appended to the real chain.
4. **Honest threat model, plus an anchor.** A hash chain detects any edit that does not re-chain. An attacker privileged enough to rewrite record N and recompute every downstream hash defeats internal verification, and we say so in one sentence on the Custody screen and in SECURITY.md. Mitigation: the current chain head hash is anchored out of band on every exported Section 63 packet, in the structured log on every append batch, and as a Prometheus metric, so verification also compares against the last external anchor.

---

## 9. API surface

### 9.1 REST (all typed, OpenAPI at `/docs`)

| Method + path | Role | Purpose |
|---|---|---|
| POST `/api/auth/login`, `/api/auth/refresh` | public | JWT issue/refresh |
| POST `/api/intake/run` | officer | Start a pipeline run (body: seed, generator: ollama|stub); returns `run_id` |
| POST `/api/intake/artefact` | officer | Multipart PDF/image ingest: pdfplumber text extraction, Tesseract OCR fallback for scans, SHA-256 intake hash, audit append, NER over extracted text. Demonstrated on the bundled synthetic samples |
| GET `/api/runs/{id}` | officer | Run status + metrics |
| GET `/api/networks?run_id=` / `/api/networks/{id}` | officer | Graph JSON (nodes, edges, communities, triage scores) |
| GET `/api/networks/{id}/trail` | officer | Money trail hops, break points, traced totals |
| GET `/api/cases/{id}` / POST `/api/cases/{id}/packet` | officer | Case file, assemble packet |
| POST `/api/cases/{id}/claims` | officer | Run generator + F9 over the case; returns claims with verdicts |
| POST `/api/decisions` | officer | Accept/reject a link or claim; appends to audit chain |
| GET `/api/audit/chain`, GET `/api/audit/verify` | any authed | Ledger + verification |
| POST `/api/audit/tamper-test` | auditor | Scratch-copy tamper demonstration (8.3) |
| GET `/api/evaluation/metrics` | any authed | Latest + historical eval runs |
| POST `/api/evaluation/reproduce` | supervisor | Seed-42 rerun; progress over SSE; asserts 6.1 |
| GET `/api/security/posture` | auditor/supervisor | Scan artifact summaries, last-scan ts, outbound-endpoint config audit, live egress self-test result (Section 2) |
| POST `/api/demo/start`, POST `/api/demo/plant-fabrication` | supervisor | Demo mode controls (Section 14) |
| GET `/health`, GET `/ready` | public | Async component checks (db, ollama, model files), 200/503, per-check timeout 2 s |
| GET `/metrics` | scrape | Prometheus |

### 9.2 SSE channels

`GET /api/stream/run/{run_id}` (pipeline events), `GET /api/stream/status` (system status ticks). SSE only; no WebSockets (non-goal).

### 9.3 SSE event catalog (envelope: `{ts, run_id?, stage?, payload}`)

`run.started`, `stage.started`, `stage.completed` (with duration_ms and stage metrics), `graph.node.added`, `graph.edge.added`, `network.discovered`, `trail.hop`, `trail.progress` (pct climbing), `mapping.section` (per case: sections, paths agreement, confidence), `f9.claim` (claim, verdict PASSED/WITHHELD, reason), `custody.appended`, `metric.updated` (key, value; drives every animated counter), `run.completed` (full results), `status.tick` (component states, p50, p95), `eval.progress`, `alert.critical`.

The frontend renders numbers **only** from `metric.updated`/`run.completed`/REST payloads. This is what makes truth rule 1 enforceable by grep.

---

## 10. Frontend

### 10.1 Design tokens (exact, in `design/tokens.css`)

Navy `#0A1F44`, Steel `#1E3A6B`, Teal `#2E7273`, Gold `#A87229`, Oxblood `#7A2E2E`, Forest `#2D6A4F`, Muted `#87847A`, Surface `#FBFAF6`. IBM Plex Sans (structure), IBM Plex Mono (labels, hashes), IBM Plex Serif (hero numbers), all self-hosted via `@fontsource/*` (no CDN, offline-safe). Color semantics: navy = deterministic core, teal = language layer, oxblood = audit gate/warnings, forest = human-in-the-loop/positive, gold = highlight.

### 10.2 Stack

React 18 + TypeScript strict + Vite. TanStack Query (+ SSE hooks feeding the cache). react-force-graph-2d (canvas) for the hero collapse; Cytoscape.js for the analysis graph; Nivo for judge-facing charts; visx where custom; Motion for transitions; react-countup for counters; cmdk palette (Cmd+K: jump to case, network, evidence, screen); react-loading-skeleton for loads over 500 ms.

### 10.3 Screens

1. **Discovery & Triage (hero).** Complaint counters stream up; force graph nodes stream in over SSE one by one; 297 complaints visibly collapse into 6 networks; hover dims unconnected nodes/edges; triage queue ranks networks by recoverability with inputs exposed; officer can reject a link (optimistic update + audit append).
2. **Case File.** Money trail animates value victim -> L1 -> L2 -> cash-out with the traced percentage climbing as the walk completes; break points flagged as freeze opportunities; mapped sections with verbatim v2 quotes and clickable sources; Section 63 certificate pre-filling; F9 panel ticking claims PASSED/WITHHELD with generator name shown, planted fabrication visibly blocked (oxblood flash, optional muted chime).
3. **Custody Ledger.** Hash-chained list, monospace hashes, prev-hash linkage drawn; "Run tamper test" (auditor) visibly breaks the scratch chain at the corrupted record.
4. **Evaluation.** All Section 6.1 metrics live from the harness with trend lines and sample sizes; the section-mapping panel shows all three rows (v1 floor, v2 BM25-only ablation, v2 full stack) so the corpus effect and the InLegalBERT rerank effect are separately visible; one-click **Reproduce** reruns seed-42 with SSE progress and shows the numbers regenerate identically (diff view: baseline vs fresh run, all green); a **Judge's seed** control reruns the pipeline with any seed a judge names, the strongest proof nothing is canned.
5. **Security Posture.** OWASP Top 10:2025 coverage checklist, CVE counts per scanner from the latest artifacts, last-scan timestamp, egress panel (outbound-endpoint config audit plus the live self-test result with timestamp, per Section 2), auth/RBAC/rate-limit status.
6. **Login** + global **System Status** widget (SSE): component dots (db, ollama, model), p50/p95 latency sparkline, model and DB pulse.

### 10.4 Experience bar

Skeletons > 500 ms, optimistic updates, graceful empty/error states, no dead ends. Full keyboard navigation; cmdk palette; `aria-live="polite"` for routine updates, `assertive` for F9 blocks and tamper detection; sound off by default, muteable, only on critical alerts; no layout shift (CLS 0 target); 60 fps graph interaction on the demo Mac (canvas renderers, capped node count, physics damping).

---

## 11. Security

- OWASP ASVS 5.0 alignment documented in `docs/SECURITY.md` with a per-control status table; design against OWASP Top 10:2025 including supply chain (pinned deps, lockfiles, SBOM).
- Scans, all runnable offline at the venue via `infra/scans/run_all.sh` (DBs pre-fetched into the bundle): pip-audit, npm audit, Bandit, Semgrep (vendored ruleset), gitleaks, Trivy (fs + image, offline DB), Grype (SBOM via syft). Output JSON artifacts in `infra/scans/out/`, summarized by `/api/security/posture`. Target zero criticals; any accepted risk is documented in `docs/SECURITY.md` with owner and rationale.
- CI (`.github/workflows/ci.yml`) runs tests + scans + the metric gate; `scripts/ci_local.sh` is the offline equivalent and the demo-day source of truth.
- AuthN/AuthZ per Section 5. Security headers (CSP, X-Frame-Options, etc.) on `web`. CORS locked to the web origin.
- Encryption in transit: TLS termination documented for pilot (nginx + certs); demo runs localhost-only and says so honestly in the posture panel. At rest: FileVault on the demo Mac + Postgres volume documented; pilot posture documented in SECURITY.md. No overclaims on the panel.

---

## 12. Observability

- OpenTelemetry `FastAPIInstrumentor` + `prometheus-fastapi-instrumentator` on the API.
- Prometheus scrapes; Grafana auto-provisions a dashboard (request rate, p50/p95, stage latencies, F9 verdict counts, SSE clients, DB health).
- `/health` and `/ready`: async checks with 2 s timeouts (db round-trip, Ollama tag list, InLegalBERT files present), 200/503 with per-component detail.
- In-app System Status widget consumes `status.tick` SSE, not Grafana, so it works even if Grafana is down.

---

## 13. Evaluation harness

- `eval/harness.py` runs the full pipeline against the golden sets, writing an `eval_runs` row: git SHA, dataset_version, corpus versions, generator name + model tag, every 6.1 metric, per-stage p50/p95, sample sizes.
- CI gate: deterministic metrics must equal 6.1 exactly; the build fails otherwise.
- Evaluation screen renders history with trend lines; Reproduce = live rerun in front of the judge.
- Groundedness scoring follows the RAGAS faithfulness pattern (claims decomposed, each verified against source) with our stricter verbatim gate. The displayed metric is the ungrounded (withheld) claim rate with its sub-classes (invented section vs unverifiable quote), each with sample size. "Fabrication" is claimed only for invented sections and ground-truth-labelled plants (Section 6.8).

---

## 14. Demo mode (offline, deterministic, < 90 s)

`DEMO_MODE=true` + supervisor `POST /api/demo/start` drives a scripted orchestrator over the real engine (no canned frontend data; the engine actually runs, seed 42):

| Beat | Time | What happens |
|---|---|---|
| 1 Intake | 0-15 s | Complaint counters and rupees-at-risk stream up |
| 2 Collapse | 15-35 s | Graph streams in; 297 complaints collapse into 6 networks; officer rejects one link (audit append shown) |
| 3 Money trail | 35-50 s | Value flows victim to cash-out; traced % climbs to 90.8; freeze points flash |
| 4 Packet + F9 | 50-75 s | Sections cited verbatim, certificate pre-fills, planted fabrication (control button) visibly blocked by F9 |
| 5 Custody | 75-88 s | Chain renders; tamper test breaks the scratch chain at the corrupted record |

Controls: "Plant a fabrication" (injects a known-bad claim through the same gate path, labelled as planted), "Reproduce results" (jumps to Evaluation and reruns), "Judge's seed" (rerun with any seed a judge names; every number on screen moves with it). Runs with WAN disabled; Ollama optional (stub fallback labelled). Playwright e2e drives the full narrative and asserts zero console errors and < 90 s.

---

## 15. Non-goals (explicit)

- No WebSockets / multi-investigator collaboration.
- No real CCTNS/ICJS/CFCFRMS integration (API-first seam documented only).
- No model training or fine-tuning; no real-data ingestion of any kind.
- No voice input (roadmap only). Document ingest (pdfplumber + Tesseract OCR) IS in scope via `POST /api/intake/artefact` on the bundled synthetic samples (Section 9.1); OCR accuracy tuning is out of scope.
- No Kubernetes, cloud deploy, LDAP/SSO, mobile app, email/notifications, backup/DR implementation (documented posture only).
- No UI chrome localization (Gujarati/Hindi demonstrated in complaint content and processing, not menus).
- No person-level prediction of any kind, anywhere.

---

## 16. Test plan (pytest + vitest + Playwright)

Backend: `test_reproduction.py` (6.1 exact equality), `test_synthetic_rng.py` (draw-order lock vs prototype), `test_linkage.py`, `test_money_trail.py` (hand-built ledgers incl. broken hops), `test_legal_mapping.py` (v1 floor exact; full-stack measured and logged; agreement routing), `test_f9.py` (stub 40/10/0 exact; gate catches paraphrase + invented section; Ollama parser on recorded fixtures), `test_custody.py` (chain, tamper), `test_rls_audit.py` (UPDATE/DELETE rejected at DB level; chain verify), `test_audit_concurrency.py` (N parallel appends; chain verifies; unique prev_hash holds), `test_audit_guc.py` (flip TimeZone/DateStyle between insert and verify; chain still verifies), `test_corpus_provenance.py` (every v2 `text_verbatim` contained in its authoritative file; checksums match), `test_ingest_ocr.py` (bundled samples extract text, get hashed, append to audit), `test_arbitrary_seed.py` (a non-42 seed yields different, internally consistent metrics), `test_auth.py` (RBAC matrix, rate limits), `test_api_contract.py` (OpenAPI schemas), `test_health.py`.
Frontend: vitest for lib + components (SSE reducer, counters bind only to event data); Playwright: demo-mode narrative (Section 14), login flow, keyboard navigation smoke.

---

## 17. End-to-end verification procedure (run before calling any milestone done)

```bash
# 1. Clean bring-up (no internet needed once bundle is loaded)
./scripts/bootstrap_env.sh && docker compose up -d --wait
# 2. Health
curl -sf localhost:8090/health | jq .   # every component "ok"
# 3. Backend tests + metric gate
docker compose exec api pytest -q       # all green, includes 6.1 exact equality
# 4. Frontend tests
cd frontend && npm test -- --run && npx playwright test
# 5. Truth-rule spot-check. The exit code carries the verdict; CI must fail on a match.
#    (The real proof is step 7b: no canned value survives an arbitrary seed.)
! grep -rInE "0\.957|0\.966|0\.962|90\.8|52\.4|\b297\b|40 ?/ ?10|tamper_detected" frontend/src
# 6. Security scans
./infra/scans/run_all.sh && jq .summary infra/scans/out/summary.json   # zero criticals
# 7. Reproduce in the UI: Evaluation -> Reproduce -> all rows green (baseline == fresh)
# 7b. Judge's seed: rerun with a non-42 seed; every displayed metric moves consistently
# 8. Demo mode: WAN off, DEMO_MODE=true, full narrative < 90 s, zero console errors (Playwright report)
# 9. Observability: Grafana localhost:3001 dashboard populated; /metrics live
# 10. Prototype still standalone: python3 src/paritran_prototype.py reproduces results.json
```

---

## 18. Milestones and acceptance checks

| # | Milestone | Acceptance (evidence required, not assertions) |
|---|---|---|
| 1 | Repo skeleton + compose | `docker compose up` brings up empty API (health 200), DB, web shell; git initialized; CI file present; truth-rule-7 prototype wording revision landed with `docs/CHANGELOG_POST_SUBMISSION.md`, all numeric values byte-identical (diff attached) |
| 2 | Data layer | Migrations apply; audit chain triggers reject UPDATE/DELETE (test output); concurrency and GUC-flip tests green; seed load; RLS proven in test |
| 3 | Engine package | `pytest` green; 6.1 deterministic metrics equal `results.json` exactly (test output attached) |
| 4 | API + SSE | OpenAPI complete; SSE catalog emitted end-to-end (curl transcript); auth + RBAC tests green |
| 5 | Frontend shell | Tokens, routing, palette, skeletons, status widget rendering live `/health` SSE (screenshot) |
| 6 | Four hero screens | Each screen driven by live engine events (screen recordings); truth-rule spot-check passes by exit code; artefact (PDF/OCR) ingest demonstrated on the bundled sample (evidence) |
| 7 | Security | Scans wired, zero criticals or documented acceptance; posture panel renders artifacts (screenshot) |
| 8 | Observability | Grafana dashboard populated (screenshot); /health component checks; status widget live |
| 9 | Demo mode | Playwright run: full narrative offline < 90 s, zero console errors (report attached) |
| 10 | Polish + final adversarial review | A11y pass (keyboard map, aria-live, contrast); perf pass (no layout shift, 60 fps interaction); fresh-context adversarial review vs the red-team dossier finds no correctness, security, or honesty gap |

Each milestone ends with an adversarial review subagent in a fresh context checking the diff against this SPEC and reporting only correctness, security, and honesty gaps. Fix before proceeding.

---

## 19. Definition of Done (verbatim, pass or fail)

- `docker compose up` brings the entire app up on a clean machine with no manual steps and no internet.
- `pytest` and frontend tests pass; engine metrics reproduce the seed-42 baselines exactly.
- Every UI number traces to a live engine value; grep the frontend for hardcoded metrics returns nothing.
- Security scans (pip-audit, npm audit, Trivy, Semgrep, Bandit, gitleaks) report zero criticals in CI; the posture panel renders their live output.
- OpenTelemetry traces and Prometheus metrics are live; Grafana loads a populated dashboard; `/health` returns component status.
- The evaluation screen renders live metrics and the Reproduce button regenerates identical numbers on screen.
- Demo mode runs the full narrative offline in under 90 seconds with zero errors, including the live fabrication block and the tamper test.
- Accessibility: keyboard-navigable, aria-live on dynamic regions, no contrast failures. Performance: no layout shift, smooth 60fps graph interaction on a mid laptop.
- A fresh-context adversarial subagent reviewing the final diff against `PARITRAN_RedTeam_Evaluation_v2_GROUNDED.md` finds no correctness, security, or honesty gap.

---

## 20. Risk register

| Risk | Mitigation |
|---|---|
| Ollama down or slow on stage | Stub fallback behind identical interface, labelled; demo rehearsed both ways; preflight script checks `ollama list` |
| InLegalBERT load failure | Model files verified by `/ready`; bundle carries the snapshot; BM25+rules degrade path with mandatory review flag |
| Docker cold-start at venue | `bundle_save.sh`/`bundle_load.sh` pre-load images; `demo_preflight.sh` boots and smoke-tests everything in one command |
| Port conflicts on demo Mac | Host ports chosen against a live scan of this machine (8090 api, 8081 web, 5433 db, 9090 prometheus, 3001 grafana; 8000/8080/8001 are occupied by OrbStack and a local python service); preflight re-checks |
| RNG drift breaking baselines | Draw-order lock test; networkx pinned; Python pinned 3.11 |
| Judge asks "is any number canned?" | Judge's-seed rerun (no canned value survives an arbitrary seed), Reproduce button, spot-check grep in CI by exit code, standalone runnable prototype |
| Judge diffs the app numbers against the submitted Appendix A | `docs/CHANGELOG_POST_SUBMISSION.md` owns the correction, old vs new side by side; one rehearsed sentence in the Q&A pack |
