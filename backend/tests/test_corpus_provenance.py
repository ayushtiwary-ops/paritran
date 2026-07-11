"""Corpus provenance tests (SPEC 6.7): corpus-in-statute, enforced.

The F9 gate certifying quote-in-corpus is only as honest as
corpus-in-statute, so this file enforces the second containment:

- every corpus_v2 ``text_verbatim`` is a verbatim substring of its
  committed authoritative file (the India Code digital text),
- every committed authoritative file matches its SHA256SUMS entry,
- corpus_v1 and golden v1 are byte-identical to the prototype source.

Plain-python tests: no database, no model, no network.
"""

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

from paritran.engine.legal import (
    AUTHORITATIVE_DIR,
    load_corpus_v1,
    load_corpus_v2,
)
from paritran.eval import load_golden_v1

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = REPO_ROOT / "src" / "paritran_prototype.py"

EXPECTED_V2_IDS = [
    "BNS 111", "BNS 303", "BNS 308", "BNS 316", "BNS 318", "BNS 319",
    "BNS 336", "BNS 338",
    "IT Act 43", "IT Act 66", "IT Act 66C", "IT Act 66D",
    "BSA 63",
]


def _entries():
    return load_corpus_v2()["entries"]


def _authoritative_path(entry_id: str) -> Path:
    return AUTHORITATIVE_DIR / (entry_id.replace(" ", "_") + ".txt")


def test_corpus_v2_covers_the_spec_section_list():
    ids = [entry["id"] for entry in _entries()]
    assert ids == EXPECTED_V2_IDS


def test_every_entry_has_the_contract_fields():
    for entry in _entries():
        for key in ("id", "act", "section", "title", "text_verbatim", "source_note"):
            assert key in entry, f"{entry.get('id')}: missing {key}"
        note = entry["source_note"]
        for key in ("url", "accessed", "edition"):
            assert note.get(key), f"{entry['id']}: source_note missing {key}"
        assert "indiacode.nic.in" in note["url"]


def test_text_verbatim_contained_in_authoritative_file():
    """The core containment: corpus text is a byte-verbatim subset of the
    committed authoritative statute text."""
    for entry in _entries():
        path = _authoritative_path(entry["id"])
        assert path.is_file(), f"missing authoritative file for {entry['id']}"
        authoritative = path.read_text(encoding="utf-8")
        assert entry["text_verbatim"] in authoritative, (
            f"{entry['id']}: text_verbatim is not a verbatim substring of "
            f"{path.name}"
        )


def test_text_verbatim_is_clean_plain_text():
    for entry in _entries():
        text = entry["text_verbatim"]
        assert text.strip(), f"{entry['id']}: empty text_verbatim"
        assert not re.search(r"<[a-zA-Z/]", text), f"{entry['id']}: HTML residue"


def test_sha256sums_match_every_authoritative_file():
    sums_path = AUTHORITATIVE_DIR / "SHA256SUMS"
    assert sums_path.is_file()
    listed = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        listed[name.strip()] = digest
    on_disk = {
        p.name for p in AUTHORITATIVE_DIR.iterdir() if p.name != "SHA256SUMS"
    }
    assert set(listed) == on_disk, "SHA256SUMS out of sync with directory"
    for name, digest in listed.items():
        actual = hashlib.sha256((AUTHORITATIVE_DIR / name).read_bytes()).hexdigest()
        assert actual == digest, f"checksum mismatch for {name}"


def test_raw_endpoint_bytes_committed_for_every_section():
    """Each .txt is a documented mechanical rendering of the raw JSON the
    India Code endpoint returned; the raw bytes are committed alongside."""
    for entry in _entries():
        raw_path = AUTHORITATIVE_DIR / (entry["id"].replace(" ", "_") + ".raw.json")
        assert raw_path.is_file(), f"missing raw endpoint bytes for {entry['id']}"
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        assert payload.get("content", "").strip(), f"{entry['id']}: empty raw content"


def _prototype_assignment(name):
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


def test_corpus_v1_is_frozen_prototype_bytes():
    if not PROTOTYPE.is_file():
        pytest.skip("prototype source not present in this checkout")
    assert load_corpus_v1() == _prototype_assignment("CORPUS")


def test_golden_v1_is_frozen_prototype_bytes():
    if not PROTOTYPE.is_file():
        pytest.skip("prototype source not present in this checkout")
    labelled = _prototype_assignment("LABELLED")
    cases = load_golden_v1()
    assert [case["text"] for case in cases] == [text for text, _ in labelled]
    assert [set(case["gold"]) for case in cases] == [set(g) for _, g in labelled]


def test_corpus_versions_are_labelled():
    assert json.loads(
        (AUTHORITATIVE_DIR.parent / "corpus_v1.json").read_text(encoding="utf-8")
    )["version"] == "v1"
    assert load_corpus_v2()["version"] == "v2"
