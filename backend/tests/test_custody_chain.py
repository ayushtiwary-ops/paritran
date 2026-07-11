"""Custody chain tests (SPEC 6.9): byte-exact prototype semantics + tamper.

The reference implementation below is the prototype's build_chain/verify
(src/paritran_prototype.py) re-stated inline so hash-for-hash equality is
asserted, not assumed. Plain-python tests, no database; the DB-enforced
audit_log chain is covered by the milestone 2 db-marked tests.
"""

import hashlib
import json

import pytest

from paritran.engine.custody import GENESIS, build_chain, find_break, tamper, verify
from paritran.engine.types import ChainRecord


def prototype_build_chain(records):
    """Inline copy of the prototype's build_chain, byte-exact."""
    chain, prev = [], "0" * 64
    for r in records:
        h = hashlib.sha256((prev + json.dumps(r, sort_keys=True)).encode()).hexdigest()
        chain.append({"rec": r, "prev": prev, "hash": h})
        prev = h
    return chain


def prototype_records():
    """The reproduce run's 12 records, exactly as the prototype builds them."""
    return [
        {
            "artefact": f"evidence_{i}",
            "sha256": hashlib.sha256(str(i).encode()).hexdigest()[:16],
        }
        for i in range(12)
    ]


def test_chain_hashes_byte_exact_vs_prototype():
    records = prototype_records()
    ours = build_chain(records)
    reference = prototype_build_chain(records)
    assert len(ours) == 12
    assert [c.hash for c in ours] == [c["hash"] for c in reference]
    assert [c.prev for c in ours] == [c["prev"] for c in reference]
    assert ours[0].prev == GENESIS


def test_twelve_record_chain_verifies():
    chain = build_chain(prototype_records())
    assert len(chain) == 12
    assert verify(chain) is True
    assert find_break(chain) is None


def test_tamper_at_index_5_is_detected():
    chain = build_chain(prototype_records())
    tampered = tamper(chain, 5)
    assert verify(tampered) is False
    assert find_break(tampered) == 5
    # Prototype corruption semantics: rec swapped, stored prev/hash kept.
    assert tampered[5].rec == {"artefact": "swapped", "sha256": "deadbeef"}
    assert tampered[5].hash == chain[5].hash
    assert tampered[5].prev == chain[5].prev


def test_tamper_returns_a_copy_and_never_touches_the_original():
    chain = build_chain(prototype_records())
    original_snapshot = list(chain)
    tampered = tamper(chain, 5)
    assert tampered is not chain
    assert chain == original_snapshot
    assert verify(chain) is True  # the real chain is never corrupted (SPEC 8.3)


def test_tamper_index_out_of_range():
    chain = build_chain(prototype_records())
    with pytest.raises(IndexError):
        tamper(chain, 12)
    with pytest.raises(IndexError):
        tamper(chain, -1)


def test_verify_accepts_plain_dict_scratch_copies():
    """The auditor tamper test verifies scratch rows, not ChainRecords."""
    records = prototype_records()
    scratch = prototype_build_chain(records)  # plain dicts
    assert verify(scratch) is True
    scratch[5] = dict(scratch[5])
    scratch[5]["rec"] = {"artefact": "swapped", "sha256": "deadbeef"}
    assert verify(scratch) is False
    assert find_break(scratch) == 5


def test_downstream_break_localizes_at_first_bad_link():
    chain = build_chain(prototype_records())
    # Corrupt the LAST record: everything before it still verifies.
    tampered = tamper(chain, 11)
    assert find_break(tampered) == 11
    assert verify(tampered[:11]) is True


def test_records_kept_verbatim_in_chain():
    records = prototype_records()
    chain = build_chain(records)
    assert all(isinstance(c, ChainRecord) for c in chain)
    assert [c.rec for c in chain] == records
