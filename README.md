# Paritran

### From complaint to conviction.

An admissible-evidence engine for the Cyber Crime Branch. Paritran runs inside the branch, links related complaints into mule networks, reconstructs the money trail with a tamper-evident chain of custody, drafts the Section 63 certificate, and maps each offence to the right law with the statute quoted word for word. Every output passes a groundedness gate that refuses anything it cannot trace to a source. The officer reviews and signs. The engine never decides on its own. That describes the target system, specified in `SPEC.md` and built milestone by milestone; the measured slice below implements linkage, the money trail, the BM25 mapping floor, the F9 gate, and custody today, with certificate drafting and verbatim statute quoting (corpus v2) landing per the SPEC milestones.

**Status:** working prototype slice, measured on synthetic data. **Data:** synthetic only, ground truth known, zero real PII. **Deployment:** on-premise, zero egress. **Seed:** 42, fully reproducible.

`KANAD S.H.I.E.L.D. 2026` · `PS-69EEFE4F8CD1C` · `Team Paritran`

---

## Why this exists

India catches cyber fraud and then loses it in court. People lost about ₹22,845 crore to cyber criminals in 2024. Yet only 2.43 percent of NCRP complaints became FIRs, about 18 percent of cybercrime cases reach a chargesheet, and only about 1.6 percent end in a conviction. Detection is crowded (I4C Samanvaya, the 1930 helpline, RBI MuleHunter). The courtroom packet, the part where one investigating officer turns a stack of small complaints into a case that holds up, is empty. Paritran builds that packet.

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
| Chain of custody | 12 records verified, tamper detected | SHA-256 hash chain |
| Time to packet | ~0.05 s for 297 complaints | end to end, wall clock: measured live each run, never baseline-compared |

**On the 52.4 percent, and the honest decomposition.** 52.4 is BM25 lexical retrieval alone, over the condensed v1 corpus, on a deliberately untuned, natural-language test set. It is the honest floor. Adding the verbatim v2 corpus and InLegalBERT reranking scores 38.1 percent on this set, below that floor, and we show that rather than hide it. The result that matters is not a single-label accuracy at all: when the three independent paths (rules, BM25, InLegalBERT) agree, measured accuracy is 100.0 percent (8/8 on golden v1, 15/15 on the extended set), and everything else is routed to a human officer, with human-routed accuracy 61.9 and 75.0 on the two sets. We report the full decomposition, including the rows where the fuller stack did not beat the baseline, not a keyword score tuned to pass.

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
