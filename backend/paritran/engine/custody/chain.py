"""In-memory SHA-256 hash chain of custody (SPEC 6.9, REAL).

Byte-exact semantics of the prototype's ``build_chain``/``verify``:
each link hash is ``sha256(prev + json.dumps(rec, sort_keys=True))``
with the genesis ``prev`` of 64 zeros. Used by the reproduce run
(12 records, verified, tamper detected). The production chain is the
DB-enforced ``audit_log`` table (SPEC 7.2); the tamper test never
corrupts a real chain, it corrupts the disposable copy produced by
:func:`tamper`.
"""

import hashlib
import json
from typing import Iterable, Sequence

from paritran.engine.types import ChainRecord

__all__ = ["GENESIS", "build_chain", "verify", "find_break", "tamper"]

GENESIS = "0" * 64


def _link_hash(prev: str, rec: dict) -> str:
    """The prototype's preimage, byte-exact: prev + canonical JSON."""
    return hashlib.sha256((prev + json.dumps(rec, sort_keys=True)).encode()).hexdigest()


def _field(link, name: str):
    """Read a link field from a ChainRecord or a plain dict.

    Plain dicts appear in scratch copies (e.g. rows snapshotted out of the
    database for the auditor tamper test), so verification accepts both.
    """
    if isinstance(link, dict):
        return link[name]
    return getattr(link, name)


def build_chain(records: Iterable[dict]) -> list[ChainRecord]:
    """Chain ``records`` in order, returning immutable ChainRecords."""
    chain: list[ChainRecord] = []
    prev = GENESIS
    for rec in records:
        h = _link_hash(prev, rec)
        chain.append(ChainRecord(rec=rec, prev=prev, hash=h))
        prev = h
    return chain


def verify(chain: Sequence) -> bool:
    """Recompute every hash from genesis; True iff the whole chain holds.

    Prototype-exact semantics: walk from the 64-zero genesis, recompute
    ``sha256(prev + canonical json)`` per link, compare to the stored
    hash, and carry the recomputed hash forward. Accepts ChainRecords or
    plain ``{"rec", "prev", "hash"}`` dicts (scratch copies).
    """
    prev = GENESIS
    for link in chain:
        h = _link_hash(prev, _field(link, "rec"))
        if h != _field(link, "hash"):
            return False
        prev = h
    return True


def find_break(chain: Sequence) -> int | None:
    """Index of the first link whose hash fails recomputation, else None.

    Same walk as :func:`verify`; exposed separately so the auditor tamper
    test can report WHERE the scratch chain breaks (SPEC 8.3).
    """
    prev = GENESIS
    for i, link in enumerate(chain):
        h = _link_hash(prev, _field(link, "rec"))
        if h != _field(link, "hash"):
            return i
        prev = h
    return None


def tamper(chain: Sequence[ChainRecord], index: int) -> list[ChainRecord]:
    """Return a corrupted COPY of ``chain`` for the scratch tamper test.

    Exactly the prototype's corruption: the record payload at ``index``
    is swapped for a marker artefact while the stored prev/hash are kept,
    so recomputation fails at ``index``. ("deadbeef" is the prototype's
    hex marker value, not a secret.) The input chain is never modified;
    the real chain is never the input to a tamper demo (SPEC 8.3).
    """
    if not 0 <= index < len(chain):
        raise IndexError(f"tamper index {index} outside chain of length {len(chain)}")
    tampered = list(chain)
    victim = tampered[index]
    tampered[index] = ChainRecord(
        rec={"artefact": "swapped", "sha256": "deadbeef"},
        prev=victim.prev,
        hash=victim.hash,
    )
    return tampered
