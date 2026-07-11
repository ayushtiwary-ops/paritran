# Post-Submission Changelog

This file exists because silence about corrections reads as history rewriting. The submitted PDF (Appendix A) is what the judges received. The repository is what we actually run. Where they differ, this changelog says exactly what changed, when, and why. Old and new numbers sit side by side.

---

## Entry 1, post-submission and pre-finale (recorded 2026-07-11)

### Three placeholder computations in the submitted Appendix A were replaced with real methods and re-measured

The submitted Appendix A contained an honest, reproducible harness in which three slots were filled with placeholder logic under time pressure. The repo slice (`src/paritran_prototype.py`) now computes all three with the real methods. Every number below regenerates from `python3 src/paritran_prototype.py` at seed 42.

| Metric | Submitted Appendix A (old) | Repo slice (new) | What changed |
|---|---|---|---|
| Money trail, value traced to cash-out | 87.3 percent, produced by `random.random() < 0.90` (a random draw per complaint, no trace) | 90.8 percent | Directed-graph reachability: a seeded, deliberately incomplete money ledger is built (victim mule to L1 to L2 to cash-out) and each complaint's value is walked along the real edges; only value that actually reaches the cash-out node counts as traced. |
| Section mapping accuracy | 90.5 percent, a keyword `if`-ladder scored on 21 sentences whose keywords were chosen to match the ladder | 52.4 percent | Okapi BM25 retrieval over the condensed section-description corpus (v1), scored on an untuned natural-language labelled set that does not reuse corpus wording. This is the honest lexical floor. The full retrieval stack (BM25 plus InLegalBERT rerank plus rule-layer agreement, over the verbatim corpus v2) is measured live in the application, reported as separate rows so the corpus effect and the rerank effect are each visible. |
| F9 groundedness gate | 0 ungrounded of 50, a tautology: every emitted claim was copied from the corpus and then compared with the corpus, so 0 was guaranteed; the planted fabrication was "BNS 999", trivially absent | 50 claims, 40 passed, 10 withheld, 0 leaked | Verbatim-citation gate over a generative step that fabricates on purpose: the deterministic stub emits 1-in-5 ground-truth-labelled fabrications (an invented "BNS 420" section and non-verbatim paraphrases), so the gate is exercised against an adversary rather than a self-comparison. Leaked counts ground-truth fabrications that pass the gate. |
| Linkage precision / recall / F1 | 0.929 / 0.944 / 0.936 | 0.957 / 0.966 / 0.962 | Same method (pairwise agreement against seeded ground truth, greedy modularity communities). Re-measured on the corrected harness, whose generator draw order changed when the placeholder computations were removed, so the seed-42 synthetic dataset differs from the submitted run. |

### Why we publish this

Because the honest answer to "your appendix says `random.random()`" is: correct, and here is when and how we fixed it. The submitted document said the numbers were real; three of them were placeholders. We replaced the placeholders with the methods the architecture describes, re-measured, and printed both columns above. Anyone can diff the submitted appendix against `src/paritran_prototype.py` and reconcile every line against this table.

---

## Entry 2, 2026-07-11

### Truth-rule-7 wording revision of the prototype, then freeze

One revision to `src/paritran_prototype.py` and `results.json`, fixing dishonest labels. Strings, one key rename, and one recomputation; no RNG-affecting change; every numeric value byte-identical to the pre-revision file (verified by key-by-key diff; `time_to_packet_sec` is wall clock, measured live, never baseline-compared).

- `section_method` value corrected to "Okapi BM25 over condensed section-description corpus (v1)". The v1 corpus contains condensed section descriptions, not verbatim bare-act text, and may not be labelled otherwise.
- Results key renamed: `f9_withheld_real_hallucinations` is now `f9_withheld_stub_fabrications`. The withheld claims are stub-generated fabrications, deterministic and ground-truth labelled, not real model hallucinations. Value unchanged at 10.
- `f9_leaked` recomputed non-tautologically. It previously tested `gate(c)` on claims already selected by `not gate(c)`, which is 0 by construction. It now counts ground-truth-labelled fabrications that PASS the gate, which is the meaningful leak definition. Value unchanged at 0, now earned rather than guaranteed.
- Comments and docstrings corrected to match: the corpus is condensed section descriptions, the stub fabricates (it does not "hallucinate"), and the honest framing stays that the stub fabricates on purpose so the gate is exercised non-tautologically.
- From this revision forward, `src/paritran_prototype.py` and the deterministic values in `results.json` are frozen. The production engine reproduces them exactly (SPEC section 6.1).
