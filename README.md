# Paritran

### From complaint to conviction.

An admissible-evidence engine for the Cyber Crime Branch. Paritran runs inside the branch, links related complaints into mule networks, reconstructs the money trail with a tamper-evident chain of custody, drafts the Section 63 certificate, and maps each offence to the right law with the statute quoted word for word. Every output passes a groundedness gate that refuses anything it cannot trace to a source. The officer reviews and signs. The engine never decides on its own. That describes the target system, specified in `SPEC.md` and built milestone by milestone; the measured slice below implements linkage, the money trail, the BM25 mapping floor, the F9 gate, and custody today, with certificate drafting and verbatim statute quoting (corpus v2) landing per the SPEC milestones.

**Status:** working prototype slice, measured on synthetic data. **Data:** synthetic only, ground truth known, zero real PII. **Deployment posture:** on-premise; zero egress is an operator-verified run condition, not an invariant of every host configuration. **Seed:** 42, fully reproducible.

`KANAD S.H.I.E.L.D. 2026` · `PS-69EEFE4F8CD1C` · `Team Paritran`

---

## Why this exists

Detection and freezing are only the beginning of a cyber-fraud investigation. The courtroom packet is the part where an investigating officer turns linked complaints, a money trail, cited law, and custody records into a reviewable case file. Paritran builds that packet while keeping the officer accountable for every decision.

---

## Reproducible results (seed 42, synthetic data)

Run `python3 src/paritran_prototype.py`. Every number below is written to `results.json`. Nothing here is a placeholder; each metric is produced by the method named.

| Metric | Result | Method |
|---|---|---|
| Mule networks recovered | 6 of 6 seeded, from 297 complaints | greedy modularity community detection |
| Linkage precision / recall / F1 | 0.957 / 0.966 / 0.962 | pairwise agreement vs ground truth |
| Value traced to cash-out | 90.8 percent | directed-graph reachability (real trace) |
| Section mapping accuracy | 52.4 percent | Okapi BM25 over the condensed section-description corpus (v1), untuned set |
| Groundedness gate (F9) | 40 passed, 10 stub fabrications withheld, 0 leaked | verbatim-citation gate over a fabricating generative step (deterministic stub) |
| Chain of custody | verified and tamper-evident | SHA-256 hash chain |

**On the 52.4 percent, and the honest decomposition.** 52.4 percent is the BM25 lexical floor over the condensed v1 corpus. The result that matters is precision via abstention: when rules, BM25, and InLegalBERT agree, measured accuracy is 100 percent (8/8 on golden v1 and 15/15 on the extended set); every disagreement routes to a human officer. These are frozen benchmark results, not a claim that every future dependency version is equivalent without re-measurement.

---

## Post-submission corrections

The submitted PDF's Appendix A contained three placeholder computations; they have since been replaced with the real methods and re-measured, and `docs/CHANGELOG_POST_SUBMISSION.md` states the old and new numbers side by side.

---

## Quickstart

```bash
# Reproducible core (only dependency is networkx)
pip install networkx==3.4.2
python3 src/paritran_prototype.py      # prints and writes results.json

# or, hermetic, via Docker
docker compose up --build prototype
```

---

## Architecture, in one breath

One deterministic core, a fenced language layer. Linkage, money trail, scoring and custody are graph and rule based, so the same input gives the same output every time. The language model is used only to summarise cited evidence and draft documents, and every draft passes the groundedness gate before any officer sees it. A SHA-256 chain of custody runs under every stage. Full detail in `docs/ARCHITECTURE.md`.

```
ingest (hashed) -> entity resolution -> linkage graph -> money trail
      -> predictive triage -> grounded mapping -> Section 63 packet
      -> groundedness audit (F9) -> officer sign-off
```

---

## Repository layout

```
paritran_repo/
  SPEC.md                     the build contract; NOTES.md, the decision log
  src/paritran_prototype.py   the measured pipeline (the appendix code, corrected)
  results.json                regenerated on every run, seed 42
  backend/                    FastAPI application and engine (built per SPEC milestones)
  frontend/                   React + TypeScript officer interface
  infra/, scripts/            Docker, nginx, Prometheus, Grafana, CI, bootstrap
  dataset/DATASHEET.md        dataset documentation (synthetic generator)
  docs/ARCHITECTURE.md        system design; docs/CHANGELOG_POST_SUBMISSION.md
  Dockerfile, docker-compose.yml, run.sh   on-prem, zero-egress bundle
  requirements.txt            core plus the full-stack dependencies
  LICENSE                     evaluation license
  CITATION.cff
```

---

## Ethics, security, accountability

Synthetic data only, no real complainant, victim or accused data. Privacy by design: on-premise, role-based access, encryption, full audit, even where the law would exempt a law-enforcement tool. The human stays accountable: every machine output is a suggestion an officer accepts or rejects, and every decision is logged. Predictions score money and infrastructure, never people, which avoids the profiling failure that has dogged person-level prediction.

---

## Legal basis

Aligned to the laws in force since 1 July 2024: Bharatiya Nyaya Sanhita (BNS), Bharatiya Nagarik Suraksha Sanhita (BNSS), and Bharatiya Sakshya Adhiniyam (BSA). Section 63 of the BSA governs the admissibility of electronic records and requires dual certification; Paritran drafts and pre-fills the certificate and binds the integrity hash, and the named custodian and independent expert review and sign. Paritran does not certify.

---

## Team

Ayush Tiwary, architecture, the grounding and audit core, legal mapping, on-premise build. Aditya Arora, graph analytics and money trail, synthetic data, dashboard and front end.

## License and citation

Evaluation license, see `LICENSE`. Dual-licensing for law-enforcement deployment on request. Cite via `CITATION.cff`.
