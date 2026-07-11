"""Okapi BM25 retrieval, the prototype's exact math (SPEC 6.7).

This module is the promoted form of the BM25 block in
``src/paritran_prototype.py`` (tokenizer regex, idf formula, k1=1.5, b=0.75,
map_sections with topn=2 and thresh=0.8), parameterized over any
``{section_id: text}`` corpus. Over corpus v1 and golden v1 it must reproduce
the frozen 52.4 baseline of results.json exactly; ``tests/test_legal_bm25.py``
locks that.

Numeric truth rule: every number returned here is computed by this real
retrieval method. Nothing is stubbed or canned.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Mapping

# Frozen prototype constants. Do not tune (SPEC 6.7: no tune-on-test).
K1 = 1.5
B = 0.75
TOPN = 2
THRESH = 0.8

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tok(text: str) -> list[str]:
    """The prototype's tokenizer: lowercase latin alphanumeric runs."""
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """Okapi BM25 over a ``{doc_id: text}`` corpus, prototype math exactly.

    Iteration order of ``corpus`` is preserved everywhere (dict insertion
    order), so tie-breaking in ranking matches the prototype byte-for-byte
    when given the same corpus in the same order.
    """

    def __init__(self, corpus: Mapping[str, str], k1: float = K1, b: float = B):
        if not corpus:
            raise ValueError("BM25Index needs a non-empty corpus")
        self.corpus: dict[str, str] = dict(corpus)
        self.k1 = k1
        self.b = b
        self.docs: dict[str, list[str]] = {k: tok(v) for k, v in self.corpus.items()}
        self.n = len(self.docs)
        self.avgdl = sum(len(d) for d in self.docs.values()) / self.n
        self.df: dict[str, int] = {}
        for d in self.docs.values():
            for w in set(d):
                self.df[w] = self.df.get(w, 0) + 1

    def idf(self, word: str) -> float:
        """Prototype idf: log(1 + (N - df + 0.5) / (df + 0.5))."""
        df = self.df.get(word, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def score(self, query_tokens: Iterable[str], doc_key: str) -> float:
        """Prototype bm25(q, dk) for one document."""
        d = self.docs[doc_key]
        length = len(d)
        sc = 0.0
        for w in query_tokens:
            if w in d:
                f = d.count(w)
                sc += self.idf(w) * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * length / self.avgdl)
                )
        return sc

    def scores(self, text: str) -> dict[str, float]:
        """Raw BM25 score for every document, corpus order preserved."""
        q = tok(text)
        return {k: self.score(q, k) for k in self.docs}

    def rank(self, text: str) -> list[tuple[float, str]]:
        """Prototype ranking: sorted (score, key) tuples, descending.

        Ties break on the key string descending, exactly like the
        prototype's ``sorted(..., reverse=True)`` over (score, key) pairs.
        """
        q = tok(text)
        return sorted(((self.score(q, k), k) for k in self.docs), reverse=True)

    def map_sections(self, text: str, topn: int = TOPN, thresh: float = THRESH) -> list[str]:
        """Prototype map_sections: top-n above threshold, else the top-1."""
        ranked = self.rank(text)
        return [k for sc, k in ranked[:topn] if sc >= thresh] or [ranked[0][1]]


def _normalize_case(case) -> tuple[str, set[str]]:
    """Accept {'text','gold'} dicts or (text, gold) pairs."""
    if isinstance(case, dict):
        return case["text"], set(case["gold"])
    text, gold = case
    return text, set(gold)


def measure_accuracy(
    corpus: Mapping[str, str],
    golden_cases: Iterable,
    topn: int = TOPN,
    thresh: float = THRESH,
) -> float:
    """Hit-rate of map_sections against gold section sets, prototype metric.

    A case counts as a hit iff the predicted set intersects the gold set;
    the result is round(100 * hits / n, 1), identical to the prototype's
    section_accuracy computation. Over corpus v1 and golden v1 this must
    return exactly 52.4 (the frozen floor).
    """
    cases = list(golden_cases)
    if not cases:
        raise ValueError("measure_accuracy needs at least one golden case")
    index = BM25Index(corpus)
    hits = 0
    for case in cases:
        text, gold = _normalize_case(case)
        if set(index.map_sections(text, topn=topn, thresh=thresh)) & gold:
            hits += 1
    return round(100 * hits / len(cases), 1)
