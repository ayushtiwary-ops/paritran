"""Fenced language layer: claim generators behind one protocol (SPEC 6.8).

Two generators, one protocol, honest labels everywhere:

- :class:`~paritran.llm.stub.StubGenerator` (STUB, labelled): the
  prototype's deterministic fabricating mock, the frozen 50/40/10/0
  baseline and the offline fallback.
- :class:`~paritran.llm.ollama_client.OllamaGenerator` (REAL): local
  Ollama, settings-driven, leniently parsed, raises
  :class:`~paritran.llm.client.ModelUnavailable` so callers degrade to
  the stub with an explicit label.

Every claim from either generator goes through the F9 gate
(:mod:`paritran.engine.f9`); the UI always shows which generator
produced the on-screen numbers.
"""

from paritran.llm.client import Claim, ClaimGenerator, ModelUnavailable
from paritran.llm.ollama_client import OllamaGenerator, ParsedClaims, parse_claims
from paritran.llm.stub import StubGenerator

__all__ = [
    "Claim",
    "ClaimGenerator",
    "ModelUnavailable",
    "OllamaGenerator",
    "ParsedClaims",
    "parse_claims",
    "StubGenerator",
]
