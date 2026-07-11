"""BM25 exactness tests (SPEC 6.7, 6.1): the 52.4 floor and prototype math.

Plain-python tests: no database, no model weights, no network.
"""

import ast
import math
from pathlib import Path

import pytest

from paritran.engine.legal import load_corpus_v1, corpus_v2_texts
from paritran.engine.legal.bm25 import BM25Index, measure_accuracy, tok
from paritran.eval import load_golden_v1

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = REPO_ROOT / "src" / "paritran_prototype.py"


def _prototype_assignment(name):
    """Extract a top-level literal assignment from the prototype source."""
    tree = ast.parse(PROTOTYPE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in prototype")


def test_v1_floor_is_exactly_52_4():
    """SPEC 6.1: section_accuracy_bm25 over corpus v1 / golden v1 == 52.4."""
    accuracy = measure_accuracy(load_corpus_v1(), load_golden_v1())
    assert accuracy == 52.4


def test_corpus_v1_byte_identical_to_prototype():
    """corpus_v1.json carries the prototype CORPUS strings byte-for-byte."""
    if not PROTOTYPE.is_file():
        pytest.skip("prototype source not present in this checkout")
    proto_corpus = _prototype_assignment("CORPUS")
    loaded = load_corpus_v1()
    assert loaded == proto_corpus
    # Same insertion order too: ranking tie-breaks depend on it.
    assert list(loaded) == list(proto_corpus)


def test_golden_v1_byte_identical_to_prototype():
    """golden v1 carries the prototype's 21 LABELLED pairs byte-for-byte."""
    if not PROTOTYPE.is_file():
        pytest.skip("prototype source not present in this checkout")
    proto_labelled = _prototype_assignment("LABELLED")
    cases = load_golden_v1()
    assert len(cases) == len(proto_labelled) == 21
    for case, (text, gold) in zip(cases, proto_labelled):
        assert case["text"] == text
        assert set(case["gold"]) == set(gold)


def test_tokenizer_matches_prototype_regex():
    assert tok("A caller, claiming 2 be from-the BANK!") == [
        "a", "caller", "claiming", "2", "be", "from", "the", "bank",
    ]
    # Devanagari and Gujarati fall outside [a-z0-9]: same as the prototype.
    assert tok("ओटीपी ઓટીપી") == []


def test_score_matches_hand_computed_okapi_value():
    index = BM25Index({"A": "alpha beta beta", "B": "gamma delta"})
    # N=2, avgdl=2.5, df(beta)=1, f=2, L=3, k1=1.5, b=0.75
    idf = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    denom = 2 + 1.5 * (1 - 0.75 + 0.75 * 3 / 2.5)
    expected = idf * (2 * (1.5 + 1)) / denom
    assert index.score(["beta"], "A") == pytest.approx(expected, abs=1e-12)
    assert index.score(["beta"], "B") == 0.0


def test_map_sections_fallback_and_tie_order():
    """No score above threshold: prototype falls back to ranked[0][1].

    With all-zero scores the (score, key) reverse sort puts the highest
    key string first, exactly like the prototype.
    """
    index = BM25Index({"A": "alpha", "B": "gamma"})
    assert index.map_sections("zzz unrelated") == ["B"]


def test_map_sections_threshold_excludes_weak_second_hit():
    corpus = {
        "DOC1": "otp code bank account fraud",
        "DOC2": "completely different words entirely",
    }
    index = BM25Index(corpus)
    picked = index.map_sections("otp bank fraud")
    assert picked == ["DOC1"]


def test_bm25_parameterizes_over_corpus_v2():
    """The same implementation must run over the verbatim v2 corpus."""
    corpus = corpus_v2_texts()
    assert len(corpus) == 13
    index = BM25Index(corpus)
    picked = index.map_sections(
        "he was deceived into delivering property after a fraudulent inducement"
    )
    assert 1 <= len(picked) <= 2
    assert all(section in corpus for section in picked)


def test_measure_accuracy_rejects_empty_golden():
    with pytest.raises(ValueError):
        measure_accuracy({"A": "text"}, [])
