"""Claim generator protocol and shared model-layer errors (SPEC 6.8).

The protocol itself lives in the frozen type contract
(:mod:`paritran.engine.types`); this module only re-exports it so every
generator implementation and every caller imports from one place, and
defines the error that signals "live model unreachable".
"""

from paritran.engine.types import Claim, ClaimGenerator

__all__ = ["Claim", "ClaimGenerator", "ModelUnavailable"]


class ModelUnavailable(RuntimeError):
    """The live model endpoint cannot be reached or did not behave.

    Raised by :class:`paritran.llm.ollama_client.OllamaGenerator` on
    connection failures, timeouts, HTTP errors, and non-Ollama response
    shapes. Callers must degrade to the deterministic stub with an
    explicit honest label ("model offline, deterministic stub active")
    and a mandatory human review flag, per SPEC 6.8. Nothing in this
    codebase silently substitutes stub output for model output.
    """
