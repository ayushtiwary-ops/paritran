# Paritran Architecture

## Design principle
One deterministic core, a fenced language layer. Anything that affects a legal or evidentiary outcome is graph or rule based and reproducible. The language model is fenced to two jobs, summarising cited evidence and drafting documents, and cannot emit a claim that has not passed the groundedness gate.

## Layers
1. **Sovereign ingest.** Text and voice, multilingual (Gujarati, Hindi, English). Every artefact SHA-256 hashed on intake. No egress.
2. **Entity resolution.** spaCy NER pulls identifiers (phones, devices, IPs, accounts) from complaint text; identifiers resolve to entities.
3. **Linkage graph.** Complaints joined by shared identifiers; greedy modularity community detection surfaces mule networks. Optional graph neural network for link prediction as data grows.
4. **Money trail.** Directed ledger from victim to L1 to L2 to cash-out; value traced by real graph reachability, with freeze points flagged.
5. **Predictive triage.** Recoverability scoring and network-growth signals, computed on money and infrastructure, never on persons. Every score is a plain function with its inputs exposed.
6. **Grounded mapping.** Rule layer, BM25 plus InLegalBERT retrieval over the bare acts, and a grounded model each propose a section; the result comes from agreement, not one model's confidence. Disagreement routes to a human.
7. **Section 63 packet.** Certificate Part A and Part B pre-filled, integrity hash computed and bound, artefact packaged with its custody trail.
8. **Groundedness audit (F9).** Every claim, section and citation is checked against source text. Unsupported tokens fail and are withheld. No clause without a source, no source without a clickable citation.
9. **Officer sign-off.** Assist, not decide. Every acceptance or rejection is written to the immutable log.

## Data flow and PII containment
Raw complaint text enters ingest and is hashed immediately. PII lives only inside the branch boundary, encrypted at rest and in transit. The language model runs locally (Ollama, Gemma) with no network egress, so no personal data leaves the premises. The audit log and custody chain are append-only and database-enforced.

## Non-functionals
- **Offline first.** Runs air-gapped inside a police station; no internet dependency at inference time.
- **Deterministic core.** Same input, same output, every run (seed-fixed, rule and graph based).
- **Reproducibility.** The measured slice regenerates all metrics from a fixed seed.
- **Integrity.** SHA-256 hash-chained custody; any silent edit breaks the chain and is flagged.
- **Failure handling.** Model unavailable degrades to retrieval-plus-rules with mandatory human review; low agreement escalates to an officer; long inputs are chunked.

## Integration seam
API-first, designed to integrate with CCTNS, ICJS and CFCFRMS as those interfaces open, while running fully standalone in the branch on day one under the one-data-once-entry principle.
