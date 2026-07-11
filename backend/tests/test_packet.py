"""Section 63 packet assembly tests (SPEC 6.10). Plain-python, no database.

Covers: key completeness, the exact certificate label with blank
signature blocks, the quote-only-from-corpus-v2 rule (enforced, not
asserted), purity (no mutation, deterministic), and the F9 summary
carrying the generator name.
"""

import copy
import hashlib

import pytest

from paritran.engine.custody import build_chain
from paritran.engine.f9 import Gate
from paritran.engine.packet import CERTIFICATE_LABEL, assemble
from paritran.engine.types import Complaint, NetworkTrail, TrailHop
from paritran.llm.stub import StubGenerator

# Test-local corpus v1 (prototype CORPUS subset semantics live in
# test_f9_gate.py; here the gate only needs to produce a real F9Result).
CORPUS_V1 = {
    "BNS 318": "Cheating and dishonestly inducing delivery of property; whoever deceives any person fraudulently or dishonestly to deliver any property.",
    "BNS 319": "Cheating by personation; a person cheats by pretending to be some other person or knowingly substituting one person for another.",
    "BNS 111": "Organised crime; any continuing unlawful activity by a crime syndicate including financial fraud and running of mule accounts.",
    "IT Act 66C": "Identity theft; fraudulent or dishonest use of the electronic signature, password or any other unique identification feature of any person.",
    "IT Act 66D": "Cheating by personation by using any communication device or computer resource.",
}

# Test-shaped corpus v2 entries (the real corpus_v2.json is another
# workstream; assemble takes whatever entries the caller passes and must
# quote nothing outside them).
CORPUS_V2 = {
    "BNS 318": {
        "id": "BNS 318",
        "act": "Bharatiya Nyaya Sanhita, 2023",
        "section": "318",
        "title": "Cheating",
        "text_verbatim": "Whoever, by deceiving any person, fraudulently or dishonestly induces the person so deceived to deliver any property to any person.",
        "source_note": "India Code, BNS 2023, s. 318 (test fixture)",
    },
    "IT Act 66C": {
        "id": "IT Act 66C",
        "act": "Information Technology Act, 2000",
        "section": "66C",
        "title": "Punishment for identity theft",
        "text_verbatim": "Whoever, fraudulently or dishonestly make use of the electronic signature, password or any other unique identification feature of any other person.",
        "source_note": "India Code, IT Act 2000, s. 66C (test fixture)",
    },
}


def make_case_ctx() -> dict:
    complaints = [
        Complaint(
            id=1,
            synd=0,
            ids=frozenset({"PH00"}),
            amt=250000,
            mule="MULE0_L1_0",
            intake_hash=hashlib.sha256(b"narrative-1").hexdigest(),
        ),
        Complaint(
            id=2,
            synd=0,
            ids=frozenset({"PH01"}),
            amt=90000,
            mule="MULE0_L1_1",
            intake_hash=hashlib.sha256(b"narrative-2").hexdigest(),
        ),
    ]
    trail = NetworkTrail(
        syndicate=0,
        hops=[
            TrailHop(src="MULE0_L1_0", dst="MULE0_L2", amount=250000),
            TrailHop(src="MULE0_L2", dst="CASH0", amount=340000),
        ],
        breaks=[("MULE0_L1_1", "MULE0_L2")],
        traced_amt=250000,
        total_amt=340000,
    )
    f9 = Gate(CORPUS_V1, corpus_version="v1").run(StubGenerator(), {})
    chain = build_chain(
        [{"artefact": f"evidence_{i}", "sha256": str(i)} for i in range(3)]
    )
    return {
        "case": {"case_id": "CASE-2026-0007", "title": "OTP vishing ring"},
        "complaints": complaints,
        "network": {"network_id": 0, "members": [1, 2]},
        "trail": trail,
        "sections": [
            "BNS 318",
            {"id": "IT Act 66C", "quote": "unique identification feature"},
        ],
        "corpus_v2": CORPUS_V2,
        "f9": f9,
        "custody_extract": chain,
        "chain_head": chain[-1].hash,
        "certificate": {
            "custodian_name": "Insp. A. Sharma",
            "custodian_designation": "Inspector, Cyber Crime Branch",
            "custodian_organisation": "Cyber Crime Branch, Ahmedabad",
            "system_description": "Paritran case server, host paritran-01",
            "expert_name": "Dr. B. Patel",
            "expert_designation": "Independent Examiner of Electronic Evidence",
            "expert_qualification": "S. 79A IT Act notified examiner",
        },
    }


def test_packet_keys_complete():
    packet = assemble(make_case_ctx())
    assert set(packet.keys()) == {
        "case",
        "complaints",
        "network",
        "trail",
        "sections",
        "f9",
        "custody_extract",
        "certificate",
        "chain_head",
    }


def test_missing_required_key_is_an_error():
    ctx = make_case_ctx()
    del ctx["chain_head"]
    with pytest.raises(ValueError, match="chain_head"):
        assemble(ctx)


def test_complaints_carry_ids_and_intake_hashes():
    packet = assemble(make_case_ctx())
    assert packet["complaints"] == [
        {"id": 1, "intake_hash": hashlib.sha256(b"narrative-1").hexdigest()},
        {"id": 2, "intake_hash": hashlib.sha256(b"narrative-2").hexdigest()},
    ]


def test_trail_includes_hops_and_breaks():
    packet = assemble(make_case_ctx())
    trail = packet["trail"]
    assert trail["syndicate"] == 0
    assert trail["hops"][0] == {"src": "MULE0_L1_0", "dst": "MULE0_L2", "amount": 250000}
    assert trail["breaks"] == [["MULE0_L1_1", "MULE0_L2"]]
    assert trail["traced_amt"] == 250000
    assert trail["total_amt"] == 340000


def test_sections_quote_only_corpus_v2():
    packet = assemble(make_case_ctx())
    by_id = {s["id"]: s for s in packet["sections"]}
    # Full verbatim text when no narrower quote is requested.
    assert (
        by_id["BNS 318"]["quote_verbatim"] == CORPUS_V2["BNS 318"]["text_verbatim"]
    )
    assert by_id["BNS 318"]["title"] == "Cheating"
    assert by_id["BNS 318"]["source_note"].startswith("India Code")
    # Requested quote must be verbatim-contained, and is kept as requested.
    assert by_id["IT Act 66C"]["quote_verbatim"] == "unique identification feature"
    assert (
        by_id["IT Act 66C"]["quote_verbatim"]
        in CORPUS_V2["IT Act 66C"]["text_verbatim"]
    )
    for section in packet["sections"]:
        assert set(section.keys()) == {"id", "title", "quote_verbatim", "source_note"}


def test_section_outside_corpus_v2_refused():
    ctx = make_case_ctx()
    ctx["sections"] = ["BNS 420"]
    with pytest.raises(ValueError, match="corpus v2"):
        assemble(ctx)


def test_non_verbatim_quote_refused():
    ctx = make_case_ctx()
    ctx["sections"] = [{"id": "BNS 318", "quote": "whoever commits cyber fraud"}]
    with pytest.raises(ValueError, match="verbatim"):
        assemble(ctx)


def test_f9_summary_includes_generator_name_and_verdicts():
    packet = assemble(make_case_ctx())
    f9 = packet["f9"]
    assert f9["generator_name"] == "deterministic-stub"
    assert f9["is_stub"] is True
    assert f9["corpus_version"] == "v1"
    assert (f9["claims"], f9["passed"], f9["withheld"], f9["leaked"]) == (50, 40, 10, 0)
    assert f9["withheld_sub_classes"] == {
        "invented_section": 5,
        "unverifiable_quote": 5,
    }
    assert len(f9["verdicts"]) == 50  # F9 audit result for every claim (SPEC 6.10)
    assert {"section", "quote", "is_fabricated", "verdict", "sub_class"} == set(
        f9["verdicts"][0].keys()
    )


def test_custody_extract_and_chain_head():
    ctx = make_case_ctx()
    packet = assemble(ctx)
    assert len(packet["custody_extract"]) == 3
    assert packet["custody_extract"][-1]["hash"] == ctx["chain_head"]
    assert packet["chain_head"] == ctx["chain_head"]
    for row in packet["custody_extract"]:
        assert set(row.keys()) == {"rec", "prev", "hash"}


def test_certificate_label_and_blank_signature_blocks():
    packet = assemble(make_case_ctx())
    certificate = packet["certificate"]
    assert certificate["label"] == CERTIFICATE_LABEL
    assert (
        certificate["label"]
        == "drafted by Paritran, signed by the named custodian and independent expert"
    )
    part_a, part_b = certificate["part_a"], certificate["part_b"]
    # Prefilled with case facts.
    assert part_a["name"] == "Insp. A. Sharma"
    assert part_a["case_reference"] == "CASE-2026-0007"
    assert part_b["name"] == "Dr. B. Patel"
    assert part_b["case_reference"] == "CASE-2026-0007"
    assert "DRAFT" in part_a["draft_statement"]
    assert "DRAFT" in part_b["draft_statement"]
    # Blank signature blocks: Paritran never certifies.
    for part in (part_a, part_b):
        assert part["signature_block"] == {"signature": "", "place": "", "date": ""}


def test_missing_certificate_prefill_stays_blank_never_invented():
    ctx = make_case_ctx()
    del ctx["certificate"]
    packet = assemble(ctx)
    assert packet["certificate"]["part_a"]["name"] == ""
    assert packet["certificate"]["part_b"]["name"] == ""
    assert packet["certificate"]["label"] == CERTIFICATE_LABEL


def test_assembly_is_pure_and_deterministic():
    ctx = make_case_ctx()
    snapshot = copy.deepcopy(ctx)
    first = assemble(ctx)
    second = assemble(ctx)
    assert first == second  # deterministic given inputs, no clock, no I/O
    assert ctx == snapshot  # input not mutated
    # Output does not alias mutable input: mutating the packet leaves ctx intact.
    first["case"]["title"] = "mutated"
    first["network"]["members"].append(99)
    assert ctx["case"]["title"] == "OTP vishing ring"
    assert ctx["network"]["members"] == [1, 2]
