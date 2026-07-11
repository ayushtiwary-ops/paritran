"""Legal retrieval stack (SPEC 6.7): corpora, BM25, semantic, rules, mapper.

Data files living next to this module:

- ``corpus_v1.json``: the prototype's 7 condensed section descriptions,
  byte-identical strings, frozen forever. Drives the 52.4 baseline only.
- ``corpus_v2.json``: verbatim statutory text fetched from India Code
  (indiacode.nic.in). Every entry's ``text_verbatim`` is a verbatim
  substring of its committed authoritative file under ``authoritative/``;
  ``tests/test_corpus_provenance.py`` enforces both containment and the
  SHA256SUMS checksums. The packet quotes only from v2.
"""

from __future__ import annotations

import json
from pathlib import Path

from .bm25 import BM25Index, measure_accuracy, tok  # noqa: F401
from .mapper import ALPHA, FullMapper, measure_bm25  # noqa: F401
from .rules import RuleLayer  # noqa: F401
from .semantic import SemanticIndex, resolve_model_dir  # noqa: F401

_HERE = Path(__file__).resolve().parent

CORPUS_V1_PATH = _HERE / "corpus_v1.json"
CORPUS_V2_PATH = _HERE / "corpus_v2.json"
AUTHORITATIVE_DIR = _HERE / "authoritative"


def load_corpus_v1() -> dict[str, str]:
    """The frozen v1 ``{section_id: condensed description}`` mapping."""
    doc = json.loads(CORPUS_V1_PATH.read_text(encoding="utf-8"))
    return dict(doc["entries"])


def load_corpus_v2() -> dict:
    """The full v2 document: version plus provenance-carrying entries."""
    return json.loads(CORPUS_V2_PATH.read_text(encoding="utf-8"))


def corpus_v2_texts() -> dict[str, str]:
    """The v2 retrieval corpus: ``{section_id: text_verbatim}``."""
    doc = load_corpus_v2()
    return {entry["id"]: entry["text_verbatim"] for entry in doc["entries"]}
