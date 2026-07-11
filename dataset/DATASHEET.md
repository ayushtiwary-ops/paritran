# Dataset Datasheet: Paritran Synthetic Mule-Network Corpus

Following the "Datasheets for Datasets" framework (Gebru et al., 2021). This documents the synthetic dataset used to measure every result in `results.json`. There is no real personal data anywhere in this dataset.

## Motivation
- **Purpose.** To measure Paritran's linkage, money-trail, legal-mapping, groundedness and custody components against a known ground truth, without touching real complainant or victim data.
- **Why synthetic.** Real cybercrime complaints contain sensitive PII. Under the DPDP Act 2023 and data-sovereignty norms, and as an ethical baseline, we generate synthetic complaints with seeded ground-truth syndicates so that precision and recall are meaningful and no real person is exposed.

## Composition
- **Instances.** About 297 synthetic complaints per run (seed 42), each with a complaint id, a true syndicate label, a set of identifiers (phones, devices, IPs, mule accounts), a victim amount, and an associated first-layer mule.
- **Seeded structure.** 6 ground-truth syndicates, each with layer-1 and layer-2 mule accounts and a cash-out node, plus about 40 legitimate unrelated noise complaints.
- **Realism controls.** About 6 percent cross-syndicate identifier bleed to create genuine false-merge pressure; a deliberately incomplete money ledger (about 93 percent edge completeness) so the money-trail trace has to cope with gaps.
- **Labels.** Ground-truth syndicate membership per complaint; a 21-case labelled set for section mapping with natural-language complaints that do not reuse the corpus wording.

## Collection process
- **Generator.** `src/paritran_prototype.py`, Section 1, using Python `random` with `seed=42`. Fully deterministic and reproducible.
- **No third parties, no scraping, no real records.** Every field is generated.

## Preprocessing, cleaning, labelling
- Identifiers are generated already normalised. Ground-truth labels are assigned at generation time, so evaluation is exact. The section-mapping test set is hand-written to be semantically realistic and lexically distinct from the corpus text (condensed section descriptions, corpus v1), to avoid inflating retrieval accuracy.

## Uses
- **Intended.** Benchmarking the Paritran pipeline components and demonstrating reproducibility to evaluators.
- **Not intended.** Training a production model for deployment, or drawing conclusions about real-world base rates. Synthetic distributions approximate, but do not equal, real fraud patterns. For the branch pilot we will seek an anonymised, consented real sample under appropriate authority.

## Distribution and maintenance
- **Distribution.** Ships as the generator, not as a frozen file, so any reviewer regenerates the identical dataset from seed 42.
- **Maintainers.** Team Paritran (Ayush Tiwary, Aditya Arora).
- **Provenance.** Every produced artefact is SHA-256 hashed inside the pipeline, so a given run's data and results are verifiable.

## Ethical and legal
- Zero real PII. No complainant, victim or accused data. Safe to share with the jury and to run on any machine. This datasheet and the fixed-seed generator together let a judge reproduce every number in `results.json` (the corrected Appendix A) in under a minute. The submitted PDF's three placeholder-derived numbers differ from these; `docs/CHANGELOG_POST_SUBMISSION.md` states both sets side by side.
