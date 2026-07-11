"""Identifier extraction for complaint text (SPEC 6.6).

HONEST LABEL: this is rule-augmented NER, not a learned model. The pipeline
is spaCy ``blank("en")`` whose only component is an ``EntityRuler`` loaded
with regex token patterns. Every extraction is a deterministic pattern
match; there is no statistical inference anywhere in this module, and any
UI surface showing these results must say so (SPEC 6.6).

Extracted identifier kinds:

===============  ====================================================
kind             shape
===============  ====================================================
phone            Indian mobile: ``+91`` prefixed or bare 10 digits
                 starting 6-9 (canonicalized to the bare 10 digits)
upi              UPI VPA, ``handle@bank`` (bank part letters only,
                 which keeps e-mail addresses out)
ipv4             dotted-quad IPv4 with octet range checking
account          bank account number, 9-18 digits (a bare 10-digit
                 number starting 6-9 is classified phone, not
                 account; that precedence is deliberate and encoded
                 in the pattern itself)
ifsc             IFSC code, 4 letters + ``0`` + 6 alphanumerics
syn_phone        prototype corpus ``PH<d><d>``
syn_device       prototype corpus ``DV<d><d>``
syn_ip           prototype corpus ``IP<d><d>``
syn_mule_l1      prototype corpus ``MULE<d>_L1_<d>``
syn_mule_l2      prototype corpus ``MULE<d>_L2``
syn_cash         prototype corpus ``CASH<d>``
syn_solo         prototype corpus ``SOLO<d+>``
===============  ====================================================

Hindi and Gujarati text passes through IndicNLP script normalization
before matching (SPEC 6.6). Identifiers are Latin-script even inside
Devanagari or Gujarati narrative, and the normalizer leaves Latin text
untouched, so extraction is script-mix safe.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

import spacy
from indicnlp.normalize.indic_normalize import IndicNormalizerFactory

__all__ = ["KINDS", "extract", "normalize_indic", "score_extraction"]

# Kind names, lowercase, exactly as returned by extract().
KINDS: frozenset[str] = frozenset(
    {
        "phone",
        "upi",
        "ipv4",
        "account",
        "ifsc",
        "syn_phone",
        "syn_device",
        "syn_ip",
        "syn_mule_l1",
        "syn_mule_l2",
        "syn_cash",
        "syn_solo",
    }
)

_IPV4_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"

# EntityRuler token patterns. Labels are the uppercase kind names.
# Ambiguity between a bare 10-digit mobile (starts 6-9) and a 9-18 digit
# account number is resolved in the ACCOUNT regex itself (negative
# lookahead), so no two same-length patterns ever compete for one span.
_PATTERNS: list[dict] = [
    # -- Indian mobile numbers -------------------------------------------
    {"label": "PHONE", "pattern": [{"TEXT": {"REGEX": r"^\+91[6-9]\d{9}$"}}]},
    {
        "label": "PHONE",
        "pattern": [{"TEXT": "+91"}, {"TEXT": {"REGEX": r"^[6-9]\d{9}$"}}],
    },
    {
        "label": "PHONE",
        "pattern": [
            {"TEXT": "+91"},
            {"TEXT": "-"},
            {"TEXT": {"REGEX": r"^[6-9]\d{4}$"}},
            {"TEXT": "-"},
            {"TEXT": {"REGEX": r"^\d{5}$"}},
        ],
    },
    {
        "label": "PHONE",
        "pattern": [
            {"TEXT": "+91"},
            {"TEXT": {"REGEX": r"^[6-9]\d{4}$"}},
            {"TEXT": {"REGEX": r"^\d{5}$"}},
        ],
    },
    {"label": "PHONE", "pattern": [{"TEXT": {"REGEX": r"^[6-9]\d{9}$"}}]},
    # -- UPI virtual payment address --------------------------------------
    {
        "label": "UPI",
        "pattern": [
            {"TEXT": {"REGEX": r"^[A-Za-z0-9][A-Za-z0-9._-]{1,255}@[A-Za-z]{2,64}$"}}
        ],
    },
    # -- IPv4 --------------------------------------------------------------
    {
        "label": "IPV4",
        "pattern": [{"TEXT": {"REGEX": rf"^(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}$"}}],
    },
    # -- Bank account number (phone shape excluded by lookahead) -----------
    {
        "label": "ACCOUNT",
        "pattern": [{"TEXT": {"REGEX": r"^(?![6-9]\d{9}$)\d{9,18}$"}}],
    },
    # -- IFSC ---------------------------------------------------------------
    {"label": "IFSC", "pattern": [{"TEXT": {"REGEX": r"^[A-Z]{4}0[A-Z0-9]{6}$"}}]},
    # -- Synthetic corpus identifier shapes (prototype, SPEC 6.2) ----------
    {"label": "SYN_PHONE", "pattern": [{"TEXT": {"REGEX": r"^PH\d{2}$"}}]},
    {"label": "SYN_DEVICE", "pattern": [{"TEXT": {"REGEX": r"^DV\d{2}$"}}]},
    {"label": "SYN_IP", "pattern": [{"TEXT": {"REGEX": r"^IP\d{2}$"}}]},
    {"label": "SYN_MULE_L1", "pattern": [{"TEXT": {"REGEX": r"^MULE\d_L1_\d$"}}]},
    {"label": "SYN_MULE_L2", "pattern": [{"TEXT": {"REGEX": r"^MULE\d_L2$"}}]},
    {"label": "SYN_CASH", "pattern": [{"TEXT": {"REGEX": r"^CASH\d$"}}]},
    {"label": "SYN_SOLO", "pattern": [{"TEXT": {"REGEX": r"^SOLO\d+$"}}]},
]

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_GUJARATI = re.compile(r"[઀-૿]")


@lru_cache(maxsize=1)
def _pipeline():
    """Build the spaCy blank("en") + EntityRuler pipeline once per process."""
    nlp = spacy.blank("en")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(_PATTERNS)
    return nlp


@lru_cache(maxsize=4)
def _indic_normalizer(lang: str):
    return IndicNormalizerFactory().get_normalizer(lang)


def normalize_indic(text: str) -> str:
    """IndicNLP script normalization for Devanagari and Gujarati runs.

    Applied before pattern matching (SPEC 6.6). Latin-script content,
    which is where the identifiers live, passes through unchanged.
    """
    if _DEVANAGARI.search(text):
        text = _indic_normalizer("hi").normalize(text)
    if _GUJARATI.search(text):
        text = _indic_normalizer("gu").normalize(text)
    return text


def _canonical(kind: str, surface: str) -> str:
    """Canonical identifier string for one matched span.

    Phones collapse to the bare 10-digit form so that ``+91 9876543210``,
    ``+91-98765-43210`` and ``9876543210`` deduplicate to one identifier.
    Every other kind is returned verbatim.
    """
    if kind == "phone":
        digits = re.sub(r"\D", "", surface)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        return digits
    return surface


def extract(text: str) -> list[tuple[str, str]]:
    """Extract identifiers from complaint text.

    Returns a list of ``(identifier, kind)`` tuples, deduplicated, in a
    stable order: first occurrence in the (Indic-normalized) text wins.
    Deterministic for a given input string.
    """
    doc = _pipeline()(normalize_indic(text))
    seen: dict[tuple[str, str], None] = {}
    for ent in doc.ents:
        kind = ent.label_.lower()
        seen.setdefault((_canonical(kind, ent.text), kind), None)
    return list(seen)


def score_extraction(
    fixtures: Iterable[tuple[str, set[tuple[str, str]]]],
) -> dict:
    """Micro-averaged precision/recall of extract() over labelled texts.

    ``fixtures`` is an iterable of ``(text, expected)`` where ``expected``
    is the exact set of (identifier, kind) tuples planted in ``text``.
    Every number returned here is computed by really running extract();
    nothing is stubbed (truth rule, SPEC section 1).
    """
    tp = fp = fn = 0
    n_texts = 0
    for text, expected in fixtures:
        n_texts += 1
        got = set(extract(text))
        tp += len(got & expected)
        fp += len(got - expected)
        fn += len(expected - got)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "n_texts": n_texts,
        "method": "rule-augmented NER (spaCy EntityRuler regex patterns)",
    }
