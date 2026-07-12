"""Full-stack section mapping: BM25 + InLegalBERT + rules (SPEC 6.7).

Ranking: ``ALPHA * bm25_norm + (1 - ALPHA) * cosine`` with ALPHA frozen at
0.5 BEFORE any golden-v1 scoring (no tune-on-test on n=21; any tuning
happens only on a disjoint dev split of golden v2 with the protocol
recorded in eval_runs). bm25_norm is per-query max-normalization:
score / max(score), and 0 for every document when the max is 0.

Confidence: HIGH iff the rule layer's proposals intersect the retrieval
top-2, else LOW and the case routes to the officer review queue
(routed_to_human=True).

measure helpers return honestly computed accuracies so the harness can
report the three-row decomposition: BM25-only over corpus v1 (52.4 frozen
floor), BM25-only over corpus v2 (the corpus effect), full stack over
corpus v2 (the rerank effect), plus the human-routing rate.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from paritran.engine.types import SectionMapping

from .bm25 import BM25Index, measure_accuracy, tok

# FROZEN at 0.5 before any golden-v1 scoring (SPEC 6.7). Do not tune here;
# tuning happens only on a disjoint golden-v2 dev split, recorded in eval_runs.
ALPHA = 0.5

TOP_K = 2


def _normalize_case(case) -> tuple[str, set[str]]:
    if isinstance(case, dict):
        return case["text"], set(case["gold"])
    text, gold = case
    return text, set(gold)


class FullMapper:
    """Three-path mapper over corpus v2: BM25, semantic, rules.

    ``semantic_index`` must expose ``cosines(text) -> dict[str, float]``
    (SemanticIndex does); ``rules`` must expose ``propose(text) ->
    tuple[str, ...]`` (RuleLayer does).
    """

    # Evidence provisions are not offences: they belong in the packet's
    # certificate display, never in the offence-candidate ranking, where
    # their generic computer vocabulary pollutes retrieval (integrator
    # protocol decision, NOTES.md, measured before/after in eval_runs).
    NON_OFFENCE_SECTIONS: frozenset[str] = frozenset({"BSA 63"})

    def __init__(self, corpus_v2: Mapping[str, str], semantic_index, rules):
        if not corpus_v2:
            raise ValueError("FullMapper needs a non-empty corpus")
        self.corpus: dict[str, str] = {
            k: v for k, v in corpus_v2.items() if k not in self.NON_OFFENCE_SECTIONS
        }
        if not self.corpus:
            raise ValueError("FullMapper needs at least one offence section")
        self.bm25 = BM25Index(self.corpus)
        self.semantic = semantic_index
        self.rules = rules

    def _combined(self, text: str) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
        """Return (bm25_raw, cosines, combined) score maps for ``text``."""
        query = tok(text)
        raw = {k: self.bm25.score(query, k) for k in self.corpus}
        max_raw = max(raw.values())
        bm25_norm = {
            k: (v / max_raw if max_raw > 0 else 0.0) for k, v in raw.items()
        }
        cos = self.semantic.cosines(text)
        combined = {
            k: ALPHA * bm25_norm[k] + (1 - ALPHA) * cos.get(k, 0.0)
            for k in self.corpus
        }
        return raw, cos, combined

    @staticmethod
    def _top(scores: Mapping[str, float], k: int = TOP_K) -> tuple[str, ...]:
        """Top-k ids by (score, id) descending, prototype tie order."""
        ranked = sorted(((sc, key) for key, sc in scores.items()), reverse=True)
        return tuple(key for _, key in ranked[:k])

    def map(self, text: str, complaint_id: int = -1) -> SectionMapping:
        """Map one complaint text to its top-2 sections with confidence."""
        raw, cos, combined = self._combined(text)
        top2 = self._top(combined)
        rule_secs = tuple(self.rules.propose(text))
        agree = bool(set(rule_secs) & set(top2))
        return SectionMapping(
            complaint_id=complaint_id,
            sections=top2,
            confidence="HIGH" if agree else "LOW",
            paths=(
                ("bm25", self._top(raw)),
                ("semantic", self._top(cos)),
                ("rules", rule_secs),
            ),
            routed_to_human=not agree,
        )

    def measure(self, golden_cases: Iterable) -> dict:
        """Full-stack accuracy and routing rate over a golden set.

        Hit iff the top-2 combined selection intersects the gold set (the
        same hit rule as the frozen v1 metric). Every number is computed by
        the real stack right here; nothing is canned.
        """
        cases = list(golden_cases)
        if not cases:
            raise ValueError("measure needs at least one golden case")
        hits = 0
        routed = 0
        high_n = 0
        high_hits = 0
        for case in cases:
            text, gold = _normalize_case(case)
            mapping = self.map(text)
            hit = bool(set(mapping.sections) & gold)
            if hit:
                hits += 1
            if mapping.routed_to_human:
                routed += 1
            else:
                high_n += 1
                if hit:
                    high_hits += 1
        n = len(cases)
        return {
            "n": n,
            "accuracy": round(100 * hits / n, 1),
            "routing_rate": round(100 * routed / n, 1),
            # The officer-safety headline: accuracy on the cases the three-path
            # agreement gate auto-decides (HIGH confidence). Everything else
            # routes to a human, so this is what an officer actually sees.
            "high_confidence_n": high_n,
            "high_confidence_accuracy": round(100 * high_hits / high_n, 1) if high_n else None,
            "method": (
                "alpha*bm25_norm + (1-alpha)*InLegalBERT cosine, alpha=0.5 frozen, "
                "top-2, hit iff prediction intersects gold"
            ),
        }


def measure_bm25(corpus: Mapping[str, str], golden_cases: Iterable) -> float:
    """BM25-only accuracy (prototype math). Re-exported from bm25.py.

    Over corpus v1 and golden v1 this is the frozen 52.4 floor; over corpus
    v2 and golden v1 it is the corpus-effect ablation row.
    """
    return measure_accuracy(corpus, golden_cases)
