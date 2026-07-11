"""FullMapper tests (SPEC 6.7): frozen alpha blend, confidence, routing.

Plain-python tests: the semantic path is a fake with preset cosines so the
mapper logic is tested without torch or model weights. Real-model numbers
are produced by the measure helpers on machines that have the weights (see
test_legal_semantic.py for the model itself).
"""

import pytest

from paritran.engine.legal import corpus_v2_texts, load_corpus_v1
from paritran.engine.legal.bm25 import BM25Index, tok
from paritran.engine.legal.mapper import ALPHA, FullMapper, measure_bm25
from paritran.engine.legal.rules import RuleLayer
from paritran.engine.types import SectionMapping
from paritran.eval import load_golden_v1, load_golden_v2


class FakeSemantic:
    """Preset cosine map; stands in for SemanticIndex in plain tests."""

    def __init__(self, cosine_map):
        self.cosine_map = dict(cosine_map)

    def cosines(self, text):
        return dict(self.cosine_map)


class FakeRules:
    def __init__(self, proposals):
        self.proposals = tuple(proposals)

    def propose(self, text):
        return self.proposals


CORPUS = {
    "S1": "otp code shared with bank caller",
    "S2": "gang syndicate rented mule accounts",
    "S3": "threat fear demand of money",
}


def test_alpha_is_frozen_at_half():
    assert ALPHA == 0.5


def test_zero_bm25_ranking_is_pure_cosine():
    """Query with no lexical overlap: bm25_norm is all 0 (max=0 rule)."""
    semantic = FakeSemantic({"S1": 0.10, "S2": 0.90, "S3": 0.50})
    mapper = FullMapper(CORPUS, semantic, FakeRules(("S2",)))
    query = "zzz qqq xxx"
    assert all(mapper.bm25.score(tok(query), k) == 0.0 for k in CORPUS)
    mapping = mapper.map(query)
    assert mapping.sections == ("S2", "S3")
    assert mapping.confidence == "HIGH"
    assert mapping.routed_to_human is False


def test_combined_score_matches_formula_by_hand():
    semantic = FakeSemantic({"S1": 0.0, "S2": 0.0, "S3": 0.8})
    mapper = FullMapper(CORPUS, semantic, FakeRules(()))
    query = "otp shared with the bank caller"
    raw = {k: mapper.bm25.score(tok(query), k) for k in CORPUS}
    max_raw = max(raw.values())
    assert max_raw > 0
    combined = {
        k: ALPHA * (raw[k] / max_raw) + (1 - ALPHA) * semantic.cosine_map[k]
        for k in CORPUS
    }
    expected = tuple(
        k for _, k in sorted(((v, k) for k, v in combined.items()), reverse=True)[:2]
    )
    mapping = mapper.map(query)
    assert mapping.sections == expected
    # S1 is the lexical winner (bm25_norm 1.0 -> 0.5 combined); S3 rides
    # the preset cosine (0.4 combined). Both beat S2.
    assert mapping.sections == ("S1", "S3")


def test_low_confidence_routes_to_human():
    semantic = FakeSemantic({"S1": 0.9, "S2": 0.1, "S3": 0.0})
    mapper = FullMapper(CORPUS, semantic, FakeRules(("S3",)))
    mapping = mapper.map("zzz")
    assert mapping.confidence == "LOW"
    assert mapping.routed_to_human is True


def test_empty_rule_proposals_are_low_confidence():
    semantic = FakeSemantic({"S1": 0.9, "S2": 0.1, "S3": 0.0})
    mapper = FullMapper(CORPUS, semantic, FakeRules(()))
    mapping = mapper.map("zzz")
    assert mapping.confidence == "LOW"
    assert mapping.routed_to_human is True


def test_mapping_is_the_frozen_contract_type():
    semantic = FakeSemantic({"S1": 0.2, "S2": 0.1, "S3": 0.0})
    mapper = FullMapper(CORPUS, semantic, FakeRules(("S1",)))
    mapping = mapper.map("otp shared", complaint_id=7)
    assert isinstance(mapping, SectionMapping)
    assert mapping.complaint_id == 7
    assert len(mapping.sections) == 2
    names = [name for name, _ in mapping.paths]
    assert names == ["bm25", "semantic", "rules"]
    for _, sections in mapping.paths:
        assert isinstance(sections, tuple)


def test_measure_counts_hits_and_routing_by_hand():
    semantic = FakeSemantic({"S1": 0.0, "S2": 0.0, "S3": 0.0})
    mapper = FullMapper(CORPUS, semantic, RuleLayer(CORPUS))
    golden = [
        # bm25 top-2 will contain S1; RuleLayer sees "otp" -> proposes 66C
        # which is outside this corpus, so proposals filter to () -> LOW.
        {"text": "otp code shared with a caller", "gold": ["S1"]},
        # No lexical overlap and zero cosines: prediction cannot hit S9.
        {"text": "totally unrelated words", "gold": ["S9"]},
    ]
    report = mapper.measure(golden)
    assert report["n"] == 2
    assert report["accuracy"] == 50.0
    assert report["routing_rate"] == 100.0


def test_v1_floor_via_measure_bm25_is_52_4():
    assert measure_bm25(load_corpus_v1(), load_golden_v1()) == 52.4


def test_full_mapper_runs_over_corpus_v2_and_golden_sets():
    """Plumbing check over the real v2 corpus with a neutral fake semantic
    path (all cosines 0.0, so ranking reduces to bm25_norm). Real-model
    accuracies are measured live by the harness, never asserted here."""
    corpus = corpus_v2_texts()
    semantic = FakeSemantic({k: 0.0 for k in corpus})
    mapper = FullMapper(corpus, semantic, RuleLayer(corpus))
    for case in load_golden_v1() + load_golden_v2():
        mapping = mapper.map(case["text"])
        assert len(mapping.sections) == 2
        assert set(mapping.sections) <= set(corpus)
        assert mapping.confidence in ("HIGH", "LOW")
        assert mapping.routed_to_human == (mapping.confidence == "LOW")


def test_golden_v2_composition():
    cases = load_golden_v2()
    assert len(cases) == 60
    corpus = corpus_v2_texts()
    langs = [case["lang"] for case in cases]
    assert langs.count("hi") >= 6
    assert langs.count("gu") >= 6
    for case in cases:
        assert case["text"].strip()
        assert case["gold"], "every case needs at least one gold section"
        assert set(case["gold"]) <= set(corpus)
        assert case["lang"] in ("en", "hi", "gu")
