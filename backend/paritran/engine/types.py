"""Frozen data contract for the Paritran engine (SPEC section 6).

Written by the integrator BEFORE the Milestone 3 build wave; every engine
module imports these types. Changing a field here is a contract change and
belongs in SPEC.md first.

Numeric truth rule: nothing in this module computes anything. Every value
carried here is produced by the real method in its owning module.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol


@dataclass(frozen=True)
class Complaint:
    """One synthetic complaint. Structural fields reproduce the prototype
    byte-for-byte at seed 42; narrative fields come from the isolated
    text RNG (SPEC 6.2) and never perturb the structural stream."""

    id: int
    synd: int                    # ground-truth syndicate, negative = noise
    ids: frozenset[str]          # identifiers mentioned (phones, devices, IPs, mules)
    amt: int                     # rupees
    mule: str                    # first-layer mule account
    narrative: str = ""          # natural-language complaint text
    lang: Literal["en", "hi", "gu"] = "en"
    intake_hash: str = ""        # sha256 of narrative, set at ingest


@dataclass(frozen=True)
class SyndicateTruth:
    l1: tuple[str, ...]
    l2: str
    cash: str


@dataclass
class SyntheticBundle:
    seed: int
    complaints: list[Complaint]
    syndicates: dict[int, SyndicateTruth]
    money: Any                   # networkx.DiGraph, edges L1->L2->cash


@dataclass(frozen=True)
class LinkageMetrics:
    n_complaints: int
    networks_found: int
    precision: float             # rounded 3, must equal results.json at seed 42
    recall: float
    f1: float


@dataclass
class LinkageResult:
    metrics: LinkageMetrics
    graph: Any                   # networkx.Graph over complaint ids
    communities: list[set[int]]  # size >= 5 communities, prototype order
    pred: dict[int, int]         # complaint id -> predicted community


@dataclass(frozen=True)
class TrailHop:
    src: str
    dst: str
    amount: int


@dataclass
class NetworkTrail:
    syndicate: int
    hops: list[TrailHop]                 # ordered victim-side -> cash-out flows
    breaks: list[tuple[str, str]]        # missing ledger edges (freeze points)
    traced_amt: int
    total_amt: int


@dataclass
class TrailResult:
    pct_traced: float            # rounded 1, must equal results.json at seed 42
    total_amt: int
    traced_amt: int
    per_network: list[NetworkTrail]


@dataclass(frozen=True)
class TriageScore:
    """Accounts, never people (SPEC 6.5). All inputs exposed with the score."""

    syndicate: int
    score: float
    inputs: tuple[tuple[str, float], ...]  # (name, value), the plain formula terms


@dataclass(frozen=True)
class SectionMapping:
    complaint_id: int
    sections: tuple[str, ...]
    confidence: Literal["HIGH", "LOW"]
    paths: tuple[tuple[str, tuple[str, ...]], ...]  # ("bm25"|"semantic"|"rules", sections)
    routed_to_human: bool


@dataclass(frozen=True)
class Claim:
    section: str
    quote: str
    is_fabricated: bool | None = None   # ground-truth label when the generator knows


@dataclass(frozen=True)
class ClaimVerdict:
    claim: Claim
    verdict: Literal["PASSED", "WITHHELD"]
    sub_class: Literal["invented_section", "unverifiable_quote"] | None


@dataclass
class F9Result:
    generator_name: str
    is_stub: bool
    corpus_version: str          # "v1" | "v2"
    claims: int
    passed: int
    withheld: int
    leaked: int                  # ground-truth fabrications that PASSED
    verdicts: list[ClaimVerdict]


class ClaimGenerator(Protocol):
    """SPEC 6.8. The UI shows `name` next to every F9 number."""

    name: str
    is_stub: bool

    def generate_claims(self, context: dict) -> list[Claim]: ...


@dataclass(frozen=True)
class ChainRecord:
    rec: dict
    prev: str
    hash: str


@dataclass(frozen=True)
class StageEvent:
    """Emitted by the pipeline; Milestone 4 forwards these over SSE."""

    stage: str                   # ingest|entity_resolution|linkage|money_trail|triage|legal_mapping|packet|f9_audit|signoff
    event: str                   # SPEC 9.3 event name
    payload: dict = field(default_factory=dict)


EventSink = Callable[[StageEvent], None]
