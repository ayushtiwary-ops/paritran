"""StubGenerator byte-exactness against the prototype (SPEC 6.8).

The reference sequence below is the prototype's ``mock_generate``
(src/paritran_prototype.py) re-stated inline, tuple for tuple, so the
test fails if either side drifts. Plain-python tests, no database.
"""

from paritran.engine.types import Claim
from paritran.llm.stub import REAL_PHRASES, StubGenerator


def prototype_mock_generate():
    """Inline copy of the prototype's mock_generate, byte-exact."""
    real = {
        "BNS 318": "dishonestly inducing delivery of property",
        "BNS 319": "pretending to be some other person",
        "IT Act 66C": "unique identification feature",
        "IT Act 66D": "using any communication device or computer resource",
        "BNS 111": "continuing unlawful activity by a crime syndicate",
    }
    secs, out = list(real), []
    for i in range(50):
        sec = secs[i % len(secs)]
        if i % 5 == 0:
            out.append(
                ("BNS 420", "whoever commits cyber fraud", True)
                if i % 10 == 0
                else (sec, "the accused clearly intended to defraud the victim", True)
            )
        else:
            out.append((sec, real[sec], False))
    return out


def test_stub_sequence_is_byte_exact_prototype():
    claims = StubGenerator().generate_claims({})
    expected = prototype_mock_generate()
    assert len(claims) == 50
    assert [(c.section, c.quote, c.is_fabricated) for c in claims] == expected


def test_stub_real_phrases_match_prototype_dict():
    assert REAL_PHRASES == {
        "BNS 318": "dishonestly inducing delivery of property",
        "BNS 319": "pretending to be some other person",
        "IT Act 66C": "unique identification feature",
        "IT Act 66D": "using any communication device or computer resource",
        "BNS 111": "continuing unlawful activity by a crime syndicate",
    }
    # Insertion order drives the claim cycle; lock it.
    assert list(REAL_PHRASES) == [
        "BNS 318",
        "BNS 319",
        "IT Act 66C",
        "IT Act 66D",
        "BNS 111",
    ]


def test_stub_ground_truth_labels():
    claims = StubGenerator().generate_claims({})
    for i, claim in enumerate(claims):
        assert isinstance(claim, Claim)
        assert claim.is_fabricated is (i % 5 == 0), f"label wrong at i={i}"
    assert sum(1 for c in claims if c.is_fabricated) == 10
    assert sum(1 for c in claims if c.section == "BNS 420") == 5
    paraphrases = [
        c
        for c in claims
        if c.quote == "the accused clearly intended to defraud the victim"
    ]
    assert len(paraphrases) == 5
    assert all(c.is_fabricated for c in paraphrases)


def test_stub_is_honestly_labelled():
    stub = StubGenerator()
    assert stub.name == "deterministic-stub"
    assert stub.is_stub is True


def test_stub_ignores_context_and_is_deterministic():
    a = StubGenerator().generate_claims({})
    b = StubGenerator().generate_claims({"case_facts": "anything", "corpus": {"X": "y"}})
    assert a == b
