"""SemanticIndex tests (SPEC 6.7): local InLegalBERT, mean pooling, cosine.

These tests skip cleanly when torch/transformers are not installed or the
local InLegalBERT weights are absent; they never touch the network.
"""

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from paritran.engine.legal.semantic import (  # noqa: E402
    MAX_LENGTH,
    SemanticIndex,
    resolve_model_dir,
)

MODEL_DIR = resolve_model_dir()

pytestmark = pytest.mark.skipif(
    MODEL_DIR is None,
    reason=(
        "InLegalBERT weights not found locally (set INLEGALBERT_LOCAL_DIR or "
        "INLEGALBERT_PATH, or populate the HF hub cache)"
    ),
)

SMALL_CORPUS = {
    "CHEAT": (
        "Deceiving a person to make them hand over money or property "
        "through fraudulent inducement is the offence of cheating."
    ),
    "HACK": (
        "Gaining access to a computer system without the permission of its "
        "owner and damaging or copying the data stored in it."
    ),
    "EXTORT": (
        "Putting a person in fear of injury and thereby forcing them to "
        "deliver money or valuable items against their will."
    ),
}


@pytest.fixture(scope="module")
def index():
    return SemanticIndex(SMALL_CORPUS, model_dir=MODEL_DIR)


def test_resolver_accepts_hub_cache_layout():
    assert (MODEL_DIR / "config.json").is_file()


def test_doc_matrix_shape_and_unit_norms(index):
    matrix = index._doc_matrix
    assert matrix.shape[0] == len(SMALL_CORPUS)
    assert matrix.shape[1] > 0
    norms = matrix.norm(dim=1)
    assert torch.allclose(norms, torch.ones_like(norms), atol=1e-5)


def test_cosines_cover_corpus_and_are_bounded(index):
    cos = index.cosines("a complaint about a fraudulent bank transaction")
    assert set(cos) == set(SMALL_CORPUS)
    for value in cos.values():
        assert -1.0001 <= value <= 1.0001


def test_identical_text_ranks_its_own_document_first(index):
    for doc_id, text in SMALL_CORPUS.items():
        ranked = index.rank(text)
        top_score, top_id = ranked[0]
        assert top_id == doc_id
        assert top_score == pytest.approx(1.0, abs=1e-4)


def test_ranking_is_deterministic_across_calls(index):
    query = "someone broke into the office server and deleted the files"
    assert index.rank(query) == index.rank(query)


def test_long_input_truncates_at_256_without_error(index):
    long_text = "computer fraud investigation report " * 200
    encoded = index.tokenizer(
        [long_text], truncation=True, max_length=MAX_LENGTH, return_tensors="pt"
    )
    assert encoded["input_ids"].shape[1] <= MAX_LENGTH
    cos = index.cosines(long_text)
    assert set(cos) == set(SMALL_CORPUS)
