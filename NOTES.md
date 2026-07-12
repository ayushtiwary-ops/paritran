# NOTES.md | Architectural decision log

Short entries, newest last. This file plus SPEC.md is the durable context across sessions. Every entry: decision, why, what it displaces or risks.

## 2026-07-11 (SPEC phase)

1. **Demo machine locked: this Mac (arm64).** Founder-confirmed. Ollama runs natively on the host (Docker on Apple Silicon has no GPU passthrough; containerized inference would be visibly slower on stage). API reaches it at `host.docker.internal:11434`.
2. **Generative model: `gemma3:4b`** (already pulled locally), env-configurable via `OLLAMA_MODEL`. Supersedes the deck's stale `gemma:2b` reference. Zero new downloads, better model.
3. **InLegalBERT pulled and cached** at `~/.cache/huggingface/hub/models--law-ai--InLegalBERT/snapshots/b5ecfed8ed6cf9d25a3cb8225a8c52f161f7401a`. Ships in the offline bundle mounted read-only at `/models/InLegalBERT`. The section-mapping lift over the 52.4 BM25 floor will be measured, not claimed.
4. **Brand: "Paritran" alone.** Founder-confirmed. "CrimeGPT" is retired; it invites the GPT-wrapper kill-shot the red team dossier warns about.
5. **Corpus split v1/v2 (honesty fix found during spec).** The prototype corpus holds condensed section descriptions, not verbatim statute text. Displaying them under "quoted word for word from the bare act" would be the exact seam a code-reading judge exploits. v1 stays frozen for the 52.4 baseline; v2 carries verbatim bare-act text and is the only source the Section 63 packet quotes. F9 stub gates against v1 (preserves 40/10/0), live Ollama path gates against v2.
6. **RNG isolation for narratives.** New complaint text draws from `random.Random(f"text/{seed}/{id}")` so the prototype's structural draw order (and therefore every baseline metric) is untouched. Locked by a draw-order unit test.
7. **Tamper test runs on a scratch copy.** The real DB chain is append-only and stays intact; the test corrupts a clone and shows verification catching it. Stronger claim, zero self-harm. Running the test is itself audited.
8. **SSE only, no WebSockets.** One-way feeds cover every requirement; multi-investigator collab is a non-goal.
9. **Plain SQL migrations over Alembic.** Fewer moving parts, fully auditable by a police IT reviewer; applied idempotently at API startup.
10. **Host ports scanned live on the demo Mac (Milestone 1):** 8090 api, 8081 web, 3001 grafana are the only published ports. db and prometheus stay on the internal core network with nothing published (see item 24). 8000 is held by OrbStack itself and 8080/8001 by a local python service, so the originally drafted 8000/8080 were replaced before any code depended on them.
11. **Fonts self-hosted via @fontsource.** No CDN at runtime; offline bundle stays truly offline.
12. **Prototype is read-only.** `src/paritran_prototype.py` is the judge-verifiable appendix artifact; the app engine is a promoted copy under `backend/paritran/engine/` with the RNG contract test guaranteeing equivalence.
13. **Security scans run offline at the venue** from pre-fetched DBs (Trivy/Grype); posture panel shows real artifacts and honest last-scan timestamps. TLS/at-rest posture stated honestly (localhost demo, documented pilot path), no overclaims on the panel.

## 2026-07-11 (post adversarial review of SPEC.md, 16 findings, all accepted)

14. **Audit chain made concurrency-safe.** Original trigger design forked under parallel appends (stage events + officer decisions insert simultaneously during the demo). Now: advisory xact lock, trigger computes prev_hash itself, canonical jsonb preimage with epoch timestamps (immune to TimeZone/DateStyle GUCs and field-boundary collisions), unique index on prev_hash, concurrency + GUC-flip tests.
15. **Zero egress is measured, not asserted.** The original compose topology (`internal: true` everywhere) was unbuildable (blocks published ports and host.docker.internal). Now: core internal network for db, edge network for published ports and host Ollama, plus a live egress self-test and outbound-endpoint config audit on the posture panel. Demo runs Wi-Fi off so the self-test shows blocked, live.
16. **Post-submission correction owned publicly.** `docs/CHANGELOG_POST_SUBMISSION.md` states that the submitted Appendix A placeholders were replaced with real methods and re-measured (87.3 random -> 90.8 reachability, 90.5 keyword -> 52.4 BM25 floor, tautological F9 -> gated generative step). Hiding this reads as history rewriting; owning it disarms the kill-shot.
17. **One-time prototype wording revision (Milestone 1), then frozen.** results.json currently overclaims ("bare-act corpus", "real hallucinations") and computes f9_leaked vacuously. Strings and that one computation get fixed once, numerics stay byte-identical, then the file freezes.
18. **InLegalBERT lift de-confounded.** Added a BM25-only-over-corpus-v2 ablation row so the corpus effect and the rerank effect are separately visible. Alpha frozen at 0.5 before any golden-v1 scoring (no tune-on-test on n=21).
19. **Corpus v2 provenance enforced.** Official India Code text committed with checksums; unit test asserts every displayed quote is contained in the authoritative text. F9's quote-in-corpus check is only as honest as corpus-in-statute.
20. **"Judge's seed" control added.** Rerun with any seed a judge names; the strongest possible answer to "is any number canned". The frontend grep is downgraded to a spot-check and made exit-code effective in CI.
21. **Hash-chain threat model scoped honestly.** A privileged attacker who re-chains defeats internal verification; we say so, and anchor the chain head out of band (on every exported packet, in logs, as a Prometheus metric).
22. **OCR ingest specified, not dropped.** `POST /api/intake/artefact` (pdfplumber + Tesseract) with bundled synthetic samples, test, and milestone evidence; master prompt mandated the stack.

## 2026-07-11 (Milestone 1 integration)

23. **api image builds from context ./backend** with dockerfile ../infra/docker/Dockerfile.api; web builds from repo root (it needs frontend/ plus infra/docker/nginx.conf). Root .dockerignore and backend/.dockerignore keep node_modules, .git, and .env out of build contexts.
24. **db and prometheus publish no host ports.** core is internal: true, so publishing there is impossible anyway; judges see Grafana (3001), psql goes through docker compose exec. SPEC table updated to match.
25. **Vite 7.3.6, not 5.x** (frontend agent's call, ratified): vite <= 6.4.2 pulls an esbuild with GHSA-67mh-4wv8-2f99 and fails the npm audit gate; with 7.3.6 npm audit reports 0 vulnerabilities.
26. **OrbStack daemon wedged mid-milestone** (docker version timing out) after parallel builds plus a read-only-mount nginx test container; orbctl stop/start recovered it. Demo-day runbook gets a "docker daemon unresponsive" remediation line.
27. **Bootstrap credentials** print once and were stashed to the session scratchpad, not the repo. .env is chmod 600 and gitignored.

## 2026-07-11 (Milestone 2 integration)

28. **Audit trigger reassigns seq inside the advisory lock.** Postgres assigns identity values before BEFORE triggers run, so under load seq order diverged from lock (chain) order and forked the chain; the tests agent's 128-append hammer proved it after a lighter 2-session check had passed. `NEW.seq := nextval(...)` after the lock makes seq order equal chain order by construction.
29. **Chain trigger is SECURITY DEFINER with pinned search_path.** The explicit nextval runs with owner rights, so paritran_app keeps exactly SELECT and INSERT on audit_log and zero sequence grants.
30. **Seeder is insert-only.** No ON CONFLICT DO UPDATE, no xmax heuristic (it double-audited in practice), no password rotation at startup; rotating a seeded user is an explicit admin action, not a boot side effect.
31. **Migration SQL ships as setuptools package data.** In-container pytest imports the site-packages wheel; without package data the .sql files exist only in /app and the suite dies on FileNotFoundError while uvicorn (which adds cwd to sys.path) masks the gap.
32. **The test suite runs on a disposable paritran_test database** created and dropped per session on the same server. Before this, the concurrency hammer left 141 test rows in the live audit ledger, exactly the artefact a judge must never see.

## 2026-07-11 (post adversarial review of Milestone 2, 13 findings, all accepted)

33. **Trigger owns ts too.** A client-writable timestamp meant a backdated INSERT would be hash-certified; the trigger now sets `clock_timestamp()` server-side, mirroring seq and prev_hash. Test added.
34. **Gapless seq redesign.** Identity column dropped for a trigger-assigned dedicated sequence (one draw per row, inside the lock); the earlier fix burned two sequence values per insert and a judge would see seq 2, 4, 6 in an append-only ledger.
35. **TRUNCATE closed.** Statement-level BEFORE TRUNCATE trigger added; row triggers do not fire on TRUNCATE, so the owner could previously empty the ledger silently.
36. **Role bootstrap is create-only.** run_migrations never ALTERs an existing role's password (a pytest run could rotate the live credential mid-demo); CREATE ROLE runs under SET LOCAL log_statement = 'none'. Conftest requires an explicit APP_DB_PASSWORD and uses a per-pid test database name.
37. **Degenerate-secret guard.** Startup refuses CHANGE_ME or empty seed secrets (insert-only seeding would persist a guessable hash forever); bootstrap_env.sh now appends missing keys to an existing .env. init_pool moved out of the migration flag. SPEC 7.2 amended for seq/ts/SECURITY DEFINER/TRUNCATE so contract and code agree. ARCHITECTURE.md "immutable"/"encrypted" overclaims corrected. Stale M1-era pgdata volumes documented as a known startup-failure cause (fix: docker compose down -v).

## Mistake ledger (this repo)

- 2026-07-11: SPEC.md first draft contained a stray CJK character ("替") from an editing slip; caught on self-review, fixed. Class: output-hygiene. One instance.
- 2026-07-11: SPEC.md first draft specified a non-concurrency-safe audit-chain trigger (chain fork under parallel appends) and an unbuildable Docker network topology (internal: true with published ports). Caught by adversarial review before any code was written. Class: designed-without-refuting. Two instances; one more of this class means a codified pre-commit rule (every stateful design gets a written concurrency/failure walk before entering SPEC).
- 2026-07-11: SPEC.md first draft carried forward two overclaims from upstream docs ("real hallucinations" from the stub, "verbatim bare act" for condensed text) instead of catching them. Class: inherited-claim-not-verified.
- 2026-07-11: The rule-7 wording revision corrected the results keys and section comments but missed the module docstring ("real adversary", "every stage a REAL computation"); caught by the M1 adversarial review, fixed in a same-day addendum. Class: inherited-claim-not-verified, second instance. One more instance of this class means a codified rule: every wording-correction pass ends with a grep for the banned claim vocabulary over the whole touched file, not the edited hunks.
- 2026-07-11: M1 build wave produced three cross-agent inconsistencies (INLEGALBERT_PATH sha in .env.example vs SPEC, api env_file over-sharing secrets, ports claimed in NOTES/Makefile that nothing binds); all caught by the M1 adversarial review before the milestone closed. Class: parallel-agents-need-a-contract-linter.

## 2026-07-12 (Milestone 3 closed)

38. M3 done, 164 tests green in-container. Seed-42 reproduction exact through the full pipeline+harness. Mapping rows (golden v1): v1 floor 52.4, v2 bm25 ablation 38.1, v2 full stack 38.1, routing 61.9; extended v2: 35.0, routing 75.0. The honest headline: high-confidence (three-path agreement) accuracy is 100.0 on both sets (8/8, 15/15); everything else routes to a human. BSA 63 excluded from offence candidates (lifted extended v2 from 25.0 to 35.0).
39. F9 gate is whitespace-normalized verbatim (statute text wraps; token-exact still enforced; stub baseline unchanged). Live gemma3:4b run: 6 claims, 0 passed, 6 withheld (real paraphrases caught live), 0 leaked. OLLAMA_TIMEOUT_SECONDS raised to 120 (cold model load exceeded 30s; degrade-to-stub path proved itself honestly, labelled + flagged).
40. NER live-measured: precision 0.74, recall 1.0 at seed 42. Oracle/results.json and dataset/samples reach the container via ro mounts + PARITRAN_* env (single source of truth).
41. Founder speed directive (2026-07-12): per-milestone two-agent adversarial reviews consolidated into one final fresh-context review at M10 (DoD line 9); integrator self-review continues per milestone. Trade-off: later defect discovery, accepted for velocity.

## M3 mistake ledger additions
- Wave agents wrote repo-root path walks that break in-container (results.json at /); fixed with tests/_paths.py + mounts. Class: host-container path assumption, second instance (first: INLEGALBERT sha path). Rule adopted: any test referencing repo artifacts outside backend/ goes through _paths.py.
