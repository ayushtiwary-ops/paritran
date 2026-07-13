# Paritran Demo-Day Runbook

On-prem, offline, deterministic. This is the exact sequence for the finale.

## Machine
This Mac (arm64). Docker via OrbStack. Ollama native on the host with `gemma3:4b`. InLegalBERT cached in the HF hub cache, mounted read-only.

## T-30 min: preflight
```bash
cd ~/Desktop/CYBER_HACKATHON_AHMEDABAD/paritran_repo
ollama list                 # gemma3:4b present
make preflight              # ports 8090/8081/3001 free, ollama reachable, compose config valid
docker compose down -v      # only if upgrading across the M1->M2 volume boundary (role split)
./scripts/bootstrap_env.sh  # generates .env if absent; adds any missing keys; prints role creds ONCE
docker compose up -d --build --wait   # ~13s to all-healthy on a warm cache
curl -sf localhost:8090/health | jq   # every component "ok"
```

## T-10 min: warm the models
Open the app (`http://localhost:8081`), log in as `supervisor1`, start one seed-42 stub run so the semantic index and mapper are built and cached. The first Ollama call is slow (cold model load, up to ~120s, `OLLAMA_TIMEOUT_SECONDS` covers it); trigger one F9 Ollama run now so the model is resident for the live demo.

## Go-live: Wi-Fi OFF
Turn off Wi-Fi. This is the honest zero-egress proof: the Security Posture panel's live egress self-test flips from "open" to "blocked" in front of the judges. Ollama is host-local, so the model still runs.

## The 90-second story (Demo screen, supervisor1)
One "Start" button drives the real seed-42 pipeline through five beats:
1. Intake: counters climb (297 complaints, rupees at risk).
2. Collapse: force graph streams in, 297 complaints become 6 mule networks; officer rejects one link (writes to the audit chain, hash shown).
3. Money trail: value flows victim to cash-out, traced % climbs to 90.8.
4. Packet + F9: Section 63 packet assembles with verbatim BNS/IT-Act quotes; "Plant a fabrication" button injects a known-bad claim and the F9 gate blocks it live (oxblood).
5. Custody: hash chain renders; tamper test breaks the scratch chain at the corrupted record, real chain stays verified.

Controls if a judge asks:
- "Is any number canned?" -> Evaluation screen -> Judge's seed -> type any seed -> every number moves. No canned value survives.
- "Reproduce your baseline" -> Evaluation -> Reproduce -> seed-42 rerun, diff all green.
- "Show the live model, not a stub" -> Case File -> F9 panel -> generator "ollama (live model)" -> gemma3:4b cites real sections (pass) and one paraphrase is withheld. The gate works on real output.

## Fallbacks
- Captioned demo video queued (never depends on the venue network).
- Docker daemon unresponsive (`docker version` hangs): `orbctl stop && orbctl start`, then `docker compose up -d --wait`. Known OrbStack wedge.
- Ollama down: F9 degrades to the labelled deterministic stub with a visible banner; the gate still runs.
- InLegalBERT fails to load: mapping degrades to BM25 + rules with a "rerank unavailable" label; every number stays live.

## Reproduce, standalone (any judge laptop)
```bash
pip install networkx==3.4.2
python3 src/paritran_prototype.py   # prints and writes results.json, seed 42
```
