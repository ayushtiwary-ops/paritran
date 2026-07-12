"""F9 gate tests (SPEC 6.8): frozen stub baseline, sub-classes, leak math.

The corpus below is the prototype's CORPUS (corpus v1), byte-identical to
src/paritran_prototype.py. It is defined inline so these tests stand alone
while the legal package (engine/legal/corpus_v1.json, another workstream)
lands in parallel. Plain-python tests, no database.
"""

import json
from pathlib import Path

import pytest

from paritran.engine.f9 import Gate
from paritran.engine.types import Claim
from paritran.llm.stub import StubGenerator

# Byte-identical to the prototype CORPUS (corpus v1, condensed descriptions).
CORPUS_V1 = {
    "BNS 318": "Cheating and dishonestly inducing delivery of property; whoever deceives any person fraudulently or dishonestly to deliver any property.",
    "BNS 319": "Cheating by personation; a person cheats by pretending to be some other person or knowingly substituting one person for another.",
    "BNS 111": "Organised crime; any continuing unlawful activity by a crime syndicate including financial fraud and running of mule accounts.",
    "IT Act 66C": "Identity theft; fraudulent or dishonest use of the electronic signature, password or any other unique identification feature of any person.",
    "IT Act 66D": "Cheating by personation by using any communication device or computer resource.",
    "BNS 308": "Extortion; intentionally putting a person in fear of injury to dishonestly induce delivery of property.",
    "IT Act 43": "Damage to computer or system; unauthorised access, downloading or introduction of a contaminant.",
}

from _paths import ORACLE_RESULTS as RESULTS_JSON


@pytest.fixture()
def gate_v1() -> Gate:
    return Gate(CORPUS_V1, corpus_version="v1")


def test_stub_through_gate_matches_frozen_baseline(gate_v1):
    """SPEC 6.1 exact row: f9 claims/passed/withheld/leaked = 50/40/10/0."""
    result = gate_v1.run(StubGenerator(), {})
    assert result.claims == 50
    assert result.passed == 40
    assert result.withheld == 10
    assert result.leaked == 0
    assert result.corpus_version == "v1"
    assert result.generator_name == "deterministic-stub"
    assert result.is_stub is True
    assert len(result.verdicts) == 50
    assert result.passed + result.withheld == result.claims


def test_stub_baseline_equals_committed_results_json(gate_v1):
    """The committed results.json is the exactness oracle; compare to it."""
    committed = json.loads(RESULTS_JSON.read_text())
    result = gate_v1.run(StubGenerator(), {})
    assert result.claims == committed["f9_claims"]
    assert result.passed == committed["f9_passed"]
    assert result.withheld == committed["f9_withheld_stub_fabrications"]
    assert result.leaked == committed["f9_leaked"]


def test_withheld_sub_class_composition(gate_v1):
    """10 withheld = 5 invented_section (BNS 420) + 5 unverifiable_quote."""
    result = gate_v1.run(StubGenerator(), {})
    withheld = [v for v in result.verdicts if v.verdict == "WITHHELD"]
    invented = [v for v in withheld if v.sub_class == "invented_section"]
    unverifiable = [v for v in withheld if v.sub_class == "unverifiable_quote"]
    assert len(withheld) == 10
    assert len(invented) == 5
    assert len(unverifiable) == 5
    assert all(v.claim.section == "BNS 420" for v in invented)
    assert all(v.claim.section in CORPUS_V1 for v in unverifiable)
    # Every PASSED verdict has no sub-class.
    assert all(
        v.sub_class is None for v in result.verdicts if v.verdict == "PASSED"
    )


def test_leaked_zero_is_meaningful_not_hardcoded(gate_v1):
    """leaked is recomputed per rule 7: fabrications that PASS count.

    Plant a ground-truth fabrication whose quote IS verbatim in the corpus;
    the gate must pass it and leaked must become exactly 1. This proves the
    zero in the baseline is a measurement, not a constant.
    """
    plant = Claim(
        section="BNS 318",
        quote="dishonestly inducing delivery of property",
        is_fabricated=True,
    )
    claims = list(StubGenerator().generate_claims({})) + [plant]
    result = gate_v1.evaluate(
        claims, generator_name="stub+plant", is_stub=True
    )
    assert result.claims == 51
    assert result.passed == 41
    assert result.withheld == 10
    assert result.leaked == 1


def test_gate_rule_catches_invention_and_paraphrase(gate_v1):
    # Invented section: withheld as invented_section even with a real-looking quote.
    assert gate_v1.check("BNS 420", "whoever commits cyber fraud") is False
    # Paraphrase of a real section: withheld as unverifiable_quote.
    assert gate_v1.check("BNS 318", "inducing the delivery of property") is False
    verdicts = gate_v1.evaluate(
        [
            Claim(section="BNS 420", quote="whoever commits cyber fraud"),
            Claim(section="BNS 318", quote="inducing the delivery of property"),
        ]
    ).verdicts
    assert [v.verdict for v in verdicts] == ["WITHHELD", "WITHHELD"]
    assert [v.sub_class for v in verdicts] == [
        "invented_section",
        "unverifiable_quote",
    ]


def test_gate_rule_is_case_insensitive_verbatim_substring(gate_v1):
    assert gate_v1.check("BNS 318", "DISHONESTLY INDUCING DELIVERY OF PROPERTY")
    assert gate_v1.check("BNS 318", "  dishonestly inducing delivery of property  ")
    # Whitespace-normalized (SPEC 6.8): wrapped statute text folds, so runs
    # of spaces or newlines in the quote still match; tokens must be exact.
    assert gate_v1.check("BNS 318", "dishonestly  inducing delivery of property")
    assert gate_v1.check("BNS 318", "dishonestly inducing\ndelivery of property")
    assert not gate_v1.check("BNS 318", "dishonestly inducing delivery of assets")
    assert not gate_v1.check("BNS 318", "")


def test_unlabelled_evaluate_defaults_to_stub_label(gate_v1):
    """Honest default: an unlabelled evaluation never claims a live model."""
    result = gate_v1.evaluate([])
    assert result.is_stub is True
    assert result.generator_name == "unlabelled"
    assert result.claims == 0
    assert result.leaked == 0


def test_unlabelled_ground_truth_never_counts_as_leak(gate_v1):
    """is_fabricated=None (live model, no ground truth) cannot leak."""
    result = gate_v1.evaluate(
        [
            Claim(
                section="BNS 318",
                quote="dishonestly inducing delivery of property",
                is_fabricated=None,
            )
        ]
    )
    assert result.passed == 1
    assert result.leaked == 0
