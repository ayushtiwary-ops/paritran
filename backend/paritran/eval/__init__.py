"""Evaluation data package (SPEC 7.3): golden section-mapping sets.

- ``golden/section_mapping_v1.json``: the prototype's 21 labelled cases,
  byte-identical, frozen forever (the 52.4 floor is measured on these).
- ``golden/extended_v2.json``: 60 new labelled cases (English, Hindi,
  Gujarati mix, with hard negatives), reported as a separate row with its
  own sample size. v2 never replaces the v1 numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

SECTION_MAPPING_V1_PATH = GOLDEN_DIR / "section_mapping_v1.json"
EXTENDED_V2_PATH = GOLDEN_DIR / "extended_v2.json"


def load_golden_v1() -> list[dict]:
    """The 21 frozen prototype cases as ``{"text", "gold"}`` dicts."""
    doc = json.loads(SECTION_MAPPING_V1_PATH.read_text(encoding="utf-8"))
    return list(doc["cases"])


def load_golden_v2() -> list[dict]:
    """The 60 extended cases as ``{"text", "gold", "lang"}`` dicts."""
    doc = json.loads(EXTENDED_V2_PATH.read_text(encoding="utf-8"))
    return list(doc["cases"])
