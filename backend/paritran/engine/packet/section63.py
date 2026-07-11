"""Section 63 case packet assembly (SPEC 6.10, REAL assembly, honest labels).

Pure function: :func:`assemble` performs no I/O, reads no clock, and does
not mutate its input. Everything in the packet comes from ``case_ctx``;
callers (the pipeline) supply real computed values, and anything drafted
rather than certified is labelled as such.

Honesty rules enforced here, not asserted:

- statutory quotes come ONLY from the corpus v2 entries passed in
  ``case_ctx["corpus_v2"]``; an unknown section id or a non-verbatim
  requested quote raises ``ValueError`` instead of emitting a packet,
- the BSA Section 63 certificate ships pre-filled with case facts and
  BLANK signature blocks under the label
  ``"drafted by Paritran, signed by the named custodian and independent
  expert"``. Paritran never certifies.

Required ``case_ctx`` keys (documented input contract):

- ``case``: dict of case summary metadata (``case_id`` recommended),
- ``complaints``: iterable of :class:`~paritran.engine.types.Complaint`
  or dicts carrying ``id`` and ``intake_hash``,
- ``network``: the network graph reference for this case (opaque, copied),
- ``trail``: :class:`~paritran.engine.types.NetworkTrail` or an
  equivalent dict (hops, breaks, traced_amt, total_amt),
- ``sections``: iterable of section ids or ``{"id", "quote"?}`` dicts,
- ``corpus_v2``: mapping section id to the v2 entry dict
  (``{id, act, section, title, text_verbatim, source_note}``),
- ``f9``: :class:`~paritran.engine.types.F9Result` (or equivalent dict),
- ``custody_extract``: iterable of
  :class:`~paritran.engine.types.ChainRecord` or plain dicts,
- ``chain_head``: current chain head hash (anchored on every export,
  SPEC 8.4),
- ``certificate`` (optional): prefill facts, e.g. ``custodian_name``,
  ``custodian_designation``, ``custodian_organisation``,
  ``system_description``, ``expert_name``, ``expert_designation``,
  ``expert_qualification``. Missing facts prefill as empty strings,
  never invented.
"""

import copy

__all__ = ["assemble", "CERTIFICATE_LABEL", "REQUIRED_KEYS"]

# Exact UI label (SPEC 6.10). Paritran drafts; the named humans sign.
CERTIFICATE_LABEL = (
    "drafted by Paritran, signed by the named custodian and independent expert"
)

REQUIRED_KEYS = (
    "case",
    "complaints",
    "network",
    "trail",
    "sections",
    "corpus_v2",
    "f9",
    "custody_extract",
    "chain_head",
)


def _get(obj, name: str, default=None):
    """Field access over dataclasses and dicts alike."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _complaint_entry(complaint) -> dict:
    return {
        "id": _get(complaint, "id"),
        "intake_hash": _get(complaint, "intake_hash", ""),
    }


def _trail_entry(trail) -> dict:
    hops = [
        {
            "src": _get(h, "src"),
            "dst": _get(h, "dst"),
            "amount": _get(h, "amount"),
        }
        for h in (_get(trail, "hops") or [])
    ]
    # Break points are freeze opportunities; JSON-friendly list pairs.
    breaks = [list(b) for b in (_get(trail, "breaks") or [])]
    return {
        "syndicate": _get(trail, "syndicate"),
        "hops": hops,
        "breaks": breaks,
        "traced_amt": _get(trail, "traced_amt"),
        "total_amt": _get(trail, "total_amt"),
    }


def _section_entry(request, corpus_v2: dict) -> dict:
    """One packet section, quoting ONLY the provided corpus v2 entry."""
    if isinstance(request, str):
        section_id, requested_quote = request, None
    else:
        section_id = _get(request, "id")
        requested_quote = _get(request, "quote")
    entry = corpus_v2.get(section_id)
    if entry is None:
        raise ValueError(
            f"section {section_id!r} is not in the provided corpus v2;"
            " the packet quotes only corpus v2 entries (SPEC 6.10)"
        )
    text_verbatim = _get(entry, "text_verbatim", "")
    if requested_quote is None:
        quote = text_verbatim
    else:
        if requested_quote not in text_verbatim:
            raise ValueError(
                f"requested quote for section {section_id!r} is not a verbatim"
                " substring of the corpus v2 text; refusing to emit a"
                " non-verbatim statutory quote"
            )
        quote = requested_quote
    return {
        "id": section_id,
        "title": _get(entry, "title", ""),
        "quote_verbatim": quote,
        "source_note": _get(entry, "source_note", ""),
    }


def _f9_entry(f9) -> dict:
    """F9 summary including the generator name, plus per-claim verdicts.

    SPEC 6.10 requires the F9 audit result for every claim in the packet;
    SPEC 6.8 requires the generator label on every F9 number.
    """
    verdicts = _get(f9, "verdicts") or []
    verdict_rows = []
    sub_class_counts = {"invented_section": 0, "unverifiable_quote": 0}
    for v in verdicts:
        claim = _get(v, "claim")
        sub_class = _get(v, "sub_class")
        if sub_class in sub_class_counts:
            sub_class_counts[sub_class] += 1
        verdict_rows.append(
            {
                "section": _get(claim, "section"),
                "quote": _get(claim, "quote"),
                "is_fabricated": _get(claim, "is_fabricated"),
                "verdict": _get(v, "verdict"),
                "sub_class": sub_class,
            }
        )
    return {
        "generator_name": _get(f9, "generator_name"),
        "is_stub": _get(f9, "is_stub"),
        "corpus_version": _get(f9, "corpus_version"),
        "claims": _get(f9, "claims"),
        "passed": _get(f9, "passed"),
        "withheld": _get(f9, "withheld"),
        "leaked": _get(f9, "leaked"),
        "withheld_sub_classes": sub_class_counts,
        "verdicts": verdict_rows,
    }


def _custody_entry(record) -> dict:
    return {
        "rec": copy.deepcopy(_get(record, "rec")),
        "prev": _get(record, "prev"),
        "hash": _get(record, "hash"),
    }


def _certificate(case: dict, prefill: dict, chain_head: str) -> dict:
    """BSA Section 63 certificate, Parts A and B, drafted not certified.

    Pre-filled with the case facts handed in; every signature block is
    blank. Statements are explicit drafts for the named signatory to
    review, correct, and sign.
    """
    case_ref = str(case.get("case_id") or case.get("id") or "")
    part_a = {
        "heading": (
            "BSA Section 63(4) Certificate, Part A:"
            " person in charge of the computer or communication device"
        ),
        "name": str(prefill.get("custodian_name", "")),
        "designation": str(prefill.get("custodian_designation", "")),
        "organisation": str(prefill.get("custodian_organisation", "")),
        "device_or_system": str(prefill.get("system_description", "")),
        "case_reference": case_ref,
        "draft_statement": (
            f"[DRAFT for review by the named custodian] The electronic records"
            f" listed in this packet for case {case_ref or '<case reference>'}"
            " were produced by the computer or communication device described"
            " above in the ordinary course of its regular use, and to the best"
            " of my knowledge and belief the device was operating properly"
            " during the relevant period."
        ),
        "signature_block": {"signature": "", "place": "", "date": ""},
    }
    part_b = {
        "heading": "BSA Section 63(4) Certificate, Part B: expert",
        "name": str(prefill.get("expert_name", "")),
        "designation": str(prefill.get("expert_designation", "")),
        "qualification": str(prefill.get("expert_qualification", "")),
        "case_reference": case_ref,
        "draft_statement": (
            f"[DRAFT for review by the named expert] I have examined the"
            f" electronic records and the SHA-256 custody extract in this"
            f" packet for case {case_ref or '<case reference>'} (chain head"
            f" {chain_head or '<chain head>'}) and set out my opinion on the"
            " matters stated therein."
        ),
        "signature_block": {"signature": "", "place": "", "date": ""},
    }
    return {"part_a": part_a, "part_b": part_b, "label": CERTIFICATE_LABEL}


def assemble(case_ctx: dict) -> dict:
    """Assemble the Section 63 case packet content. Pure, deterministic.

    Returns a plain-dict packet with keys: ``case``, ``complaints``,
    ``network``, ``trail``, ``sections``, ``f9``, ``custody_extract``,
    ``certificate``, ``chain_head``. Raises ``ValueError`` on missing
    inputs or on any attempt to quote outside the provided corpus v2.
    """
    missing = [k for k in REQUIRED_KEYS if k not in case_ctx]
    if missing:
        raise ValueError(f"case_ctx missing required keys: {missing}")

    case = copy.deepcopy(dict(case_ctx["case"]))
    corpus_v2 = case_ctx["corpus_v2"]
    chain_head = case_ctx["chain_head"]
    prefill = dict(case_ctx.get("certificate") or {})

    return {
        "case": case,
        "complaints": [_complaint_entry(c) for c in case_ctx["complaints"]],
        "network": copy.deepcopy(case_ctx["network"]),
        "trail": _trail_entry(case_ctx["trail"]),
        "sections": [_section_entry(s, corpus_v2) for s in case_ctx["sections"]],
        "f9": _f9_entry(case_ctx["f9"]),
        "custody_extract": [_custody_entry(r) for r in case_ctx["custody_extract"]],
        "certificate": _certificate(case, prefill, chain_head),
        "chain_head": chain_head,
    }
