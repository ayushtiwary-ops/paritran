"""Deterministic keyword/pattern rule layer (SPEC 6.7).

One of the three mapping paths (BM25, semantic, rules). Honest positioning:
this layer only PROPOSES sections; it is never a headline metric. Its sole
quantified role is the confidence gate in mapper.py (HIGH iff a rule
proposal intersects the retrieval top-2).

Patterns are plain regexes over the lowercased complaint text, evaluated in
a fixed order, so the proposal list is deterministic for a given text.
Hindi and Gujarati keywords are included because golden v2 contains both
languages (SPEC 7.3).
"""

from __future__ import annotations

import re
from typing import Iterable

# (pattern, proposed section ids). Evaluated top to bottom; proposals are
# deduplicated preserving first-match order. Section ids reference
# corpus_v2.json.
_RULE_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Identity theft: OTP / password / PIN / card or biometric credentials.
    (
        r"\botp\b|one[\s-]?time\s+(?:password|code)|verification\s+code"
        r"|passwords?\b|pass\s?code|\bpins?\b|credentials?"
        r"|net\s?banking|internet\s+banking|upi\b|card\s+details|cvv"
        r"|biometric|fingerprint|thumb\s+impression|aadhaar|e-?sign"
        r"|ओटीपी|पासवर्ड|पिन\b"
        r"|ઓટીપી|પાસવર્ડ|પિન\b",
        ("IT Act 66C",),
    ),
    # Personation: pretending to be someone else.
    (
        r"pretend|imperson|posing\s+as|posed\s+as|claiming\s+to\s+be"
        r"|disguis|fake\s+(?:officer|official|police|agent|inspector)"
        r"|in\s+(?:a\s+)?uniform|spoofed"
        r"|बनकर|बनके"
        r"|બનીને|બન્યો|ઢોંગ",
        ("BNS 319",),
    ),
    # Personation through a device / computer resource.
    (
        r"video\s+call|voice\s+call|caller|phone\s+call|whatsapp|telegram"
        r"|fake\s+(?:app|application|website|portal|profile|page|group)"
        r"|online\s+(?:seller|profile|group)|spoofed\s+number|e-?mail|email"
        r"|वीडियो\s?कॉल|कॉल|फर्जी\s?(?:ऐप|वेबसाइट)"
        r"|વીડિયો\s?કોલ|કોલ\b|બનાવટી\s?(?:એપ|વેબસાઇટ)",
        ("IT Act 66D",),
    ),
    # Cheating: deception inducing delivery of property.
    (
        r"deceiv|trick|lure[a-z]*|cheat|defraud|\bscam|fraudulent|dupe"
        r"|fake\s+(?:refund|prize|lottery|charity|job|offer|scheme|trading|invest)"
        r"|promis|advance\s+(?:fee|payment|money)|never\s+(?:came|existed|arrived|delivered)"
        r"|ठगी|धोखा|लालच"
        r"|છેતરપિંડી|છેતર|લાલચ",
        ("BNS 318",),
    ),
    # Organised crime: syndicates, gangs, mule account rings.
    (
        r"syndicate|\bgang\b|\bring\b|ring\s+of|racket|cartel|organi[sz]ed"
        r"|mule\s+accounts?|rented\s+accounts?|launder|layer\s+after\s+layer"
        r"|network\s+of\s+accounts|operators\s+r(?:an|unning)"
        r"|गिरोह|गैंग"
        r"|ટોળકી|મંડળી",
        ("BNS 111",),
    ),
    # Extortion: fear-induced delivery.
    (
        r"threat|blackmail|extort|ransom|protection\s+money|will\s+be\s+harmed"
        r"|fear\s+of|unless\s+(?:i|you|he|she|we|money)"
        r"|धमकी|फिरौती"
        r"|ધમકી|ખંડણી",
        ("BNS 308",),
    ),
    # Theft: dishonest taking of movable property.
    (
        r"snatch|pickpocket|\bstole\b|\bstolen\b|\btheft\b|\blifted\b|shoplif"
        r"|चोरी|चुरा"
        r"|ચોરી|ચોરા",
        ("BNS 303",),
    ),
    # Criminal breach of trust: entrusted property misappropriated.
    (
        r"entrust|misappropriat|embezzl|गबन"
        r"|(?:treasurer|cashier|accountant|agent|custodian|खजानची|मुनीम|ખજાનચી)"
        r"|collections?\s+(?:kept|used|diverted)|instead\s+of\s+depositing"
        r"|સોંપેલ",
        ("BNS 316",),
    ),
    # Forgery of valuable security (cheque, note, bond, share certificate).
    (
        r"(?:forg|fake|counterfeit|bogus)[a-z]*\s+(?:cheque|check|promissory|bond|share\s+certificate|security|will\b)"
        r"|withdrawal\s+slip|जाली\s?चेक|બનાવટી\s?ચેક",
        ("BNS 338", "BNS 336"),
    ),
    # Forgery generally: false documents or electronic records.
    (
        r"forg(?:e|ed|ery|ing)|counterfeit|fabricated\s+(?:document|record|letter|agreement)"
        r"|fake\s+(?:document|letter|agreement|stamp|certificate|signature)"
        r"|signature\s+(?:that\s+was\s+not|was\s+not\s+mine|forged|copied)"
        r"|जाली|फर्जी\s?दस्तावेज"
        r"|બનાવટી\s?દસ્તાવેજ",
        ("BNS 336",),
    ),
    # Computer damage / unauthorised access (and its dishonest form).
    (
        r"unauthori[sz]ed\s+access|without\s+(?:permission|authori[sz]ation)"
        r"|hack|malware|ransomware|\bvirus\b|contaminant|tamper"
        r"|deleted\s+(?:all\s+)?(?:my\s+|the\s+)?(?:data|files|records)"
        r"|wiped|crash(?:ed|ing)|denial\s+of\s+(?:access|service)"
        r"|logged\s+in(?:to)?\s+.{0,40}without"
        r"|हैक|હેક",
        ("IT Act 43", "IT Act 66"),
    ),
    # Electronic-record evidence language (certificate display path).
    (
        r"electronic\s+record|computer\s+output|section\s*63\s+certificate",
        ("BSA 63",),
    ),
)

_COMPILED: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = tuple(
    (re.compile(pattern), sections) for pattern, sections in _RULE_TABLE
)


class RuleLayer:
    """Deterministic keyword layer proposing candidate sections.

    ``allowed_sections`` restricts proposals to a corpus's ids so the layer
    can never propose a section the retrieval corpus does not contain.
    """

    name = "rules"

    def __init__(self, allowed_sections: Iterable[str] | None = None):
        self.allowed = set(allowed_sections) if allowed_sections is not None else None

    def propose(self, text: str) -> tuple[str, ...]:
        """Ordered, deduplicated section proposals for ``text``."""
        lowered = text.lower()
        out: list[str] = []
        for pattern, sections in _COMPILED:
            if pattern.search(lowered):
                for sec in sections:
                    if sec not in out and (self.allowed is None or sec in self.allowed):
                        out.append(sec)
        return tuple(out)
