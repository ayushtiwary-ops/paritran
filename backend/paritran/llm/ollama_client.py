"""Live claim generator over a local Ollama instance (SPEC 6.8, REAL).

Settings-driven (OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS via
:func:`paritran.config.get_settings`). Prompts the local model with the case
facts plus the corpus sections supplied in ``context["corpus"]``, instructs
strict JSON output ``[{"section": ..., "quote": ...}]``, and parses the reply
leniently. Every parsed claim then goes through the F9 gate; nothing from the
model is trusted before gating.

Parse-error contract (documented design decision): ``generate_claims`` and
:func:`parse_claims` return a :class:`ParsedClaims`, a ``list[Claim]``
subclass carrying an integer ``parse_errors`` attribute. It counts dropped
malformed items inside the extracted array, plus exactly 1 when no JSON
array could be extracted at all. Callers report it honestly next to the F9
numbers (a model that emits garbage is a measured fact, not a silent drop).

Failure contract: connection errors, timeouts, HTTP errors, and non-Ollama
response shapes raise :class:`~paritran.llm.client.ModelUnavailable`.
Callers degrade to the deterministic stub with an explicit honest label and
a mandatory human review flag (SPEC 6.8); this module never does that
substitution itself.
"""

import json

import httpx

from paritran.config import get_settings
from paritran.engine.types import Claim
from paritran.llm.client import ModelUnavailable

__all__ = ["OllamaGenerator", "ParsedClaims", "parse_claims", "build_prompt"]


class ParsedClaims(list):
    """``list[Claim]`` plus ``parse_errors``: malformed items dropped.

    ``parse_errors`` is 0 for a fully well-formed reply. When the reply
    contains no extractable JSON array, the list is empty and
    ``parse_errors`` is 1 (the whole payload counts as one malformed item).
    """

    parse_errors: int = 0


def _first_json_array(text: str):
    """Return the first JSON array decodable from ``text``, else None.

    Lenient by construction: scanning for ``[`` and attempting a
    ``raw_decode`` at each candidate position skips chatty preambles and
    fenced code blocks (the fence characters are simply non-array text).
    """
    decoder = json.JSONDecoder()
    idx = text.find("[")
    while idx != -1:
        try:
            value, _end = decoder.raw_decode(text, idx)
        except ValueError:
            value = None
        if isinstance(value, list):
            return value
        idx = text.find("[", idx + 1)
    return None


def parse_claims(text: str) -> ParsedClaims:
    """Leniently parse model output into claims.

    Extracts the first JSON array found anywhere in ``text`` (tolerating
    fenced code blocks and prose around it). Each well-formed item, a dict
    with non-empty string ``section`` and ``quote``, becomes a
    :class:`~paritran.engine.types.Claim` with ``is_fabricated=None``
    (a live model carries no ground-truth label). Malformed items are
    dropped and counted in ``parse_errors``.
    """
    result = ParsedClaims()
    array = _first_json_array(text)
    if array is None:
        result.parse_errors = 1
        return result
    errors = 0
    for item in array:
        if not isinstance(item, dict):
            errors += 1
            continue
        section = item.get("section")
        quote = item.get("quote")
        if not isinstance(section, str) or not isinstance(quote, str):
            errors += 1
            continue
        section, quote = section.strip(), quote.strip()
        if not section or not quote:
            errors += 1
            continue
        result.append(Claim(section=section, quote=quote, is_fabricated=None))
    result.parse_errors = errors
    return result


def _corpus_text(entry) -> str:
    """Corpus values may be plain text or full v2 entry dicts."""
    if isinstance(entry, dict):
        return str(entry.get("text_verbatim", entry.get("text", "")))
    return str(entry)


def build_prompt(context: dict) -> str:
    """Build the citation prompt from case facts + provided corpus sections."""
    facts = context.get("case_facts", "")
    if not isinstance(facts, str):
        facts = json.dumps(facts, sort_keys=True, default=str)
    corpus = context.get("corpus", {}) or {}
    lines = [
        "You are drafting statutory citations for a cybercrime case packet.",
        "",
        "Case facts summary:",
        facts,
        "",
        "Statutory corpus (the ONLY permitted quote sources):",
    ]
    for sec_id, entry in corpus.items():
        lines.append(f"[{sec_id}] {_corpus_text(entry)}")
    lines += [
        "",
        "Task: cite the sections that apply to these case facts.",
        "Respond with ONLY a JSON array, no prose and no code fences, shaped:",
        '[{"section": "<section id exactly as shown in brackets>",'
        ' "quote": "<short quote copied verbatim from that section>"}]',
        "Every quote MUST be copied character-for-character from the corpus"
        " text above. Do not paraphrase. Do not cite sections that are not"
        " in the corpus.",
    ]
    return "\n".join(lines)


class OllamaGenerator:
    """REAL generator: local Ollama, zero egress, leniently parsed.

    ``transport`` exists for unit tests (httpx.MockTransport); production
    callers omit it. No unit test in this repo performs live network I/O.
    """

    is_stub: bool = False

    def __init__(self, transport: httpx.BaseTransport | None = None):
        settings = get_settings()
        self._base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self._model = settings.OLLAMA_MODEL
        self._timeout = settings.OLLAMA_TIMEOUT_SECONDS
        self._transport = transport
        # Shown in the UI next to every F9 number (SPEC 6.8).
        self.name = f"ollama:{self._model}"

    def generate_claims(self, context: dict) -> ParsedClaims:
        """Prompt the model and return leniently parsed claims.

        Raises :class:`ModelUnavailable` on any transport, timeout, HTTP,
        or response-shape failure. Returned claims carry
        ``is_fabricated=None`` (no ground truth for a live model) and the
        list exposes ``parse_errors`` (see module docstring).
        """
        prompt = build_prompt(context)
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        try:
            with httpx.Client(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = client.post(f"{self._base_url}/api/generate", json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise ModelUnavailable(
                f"Ollama at {self._base_url} unavailable ({type(exc).__name__}): {exc}"
            ) from exc
        raw = body.get("response") if isinstance(body, dict) else None
        if not isinstance(raw, str):
            raise ModelUnavailable(
                f"Ollama at {self._base_url} returned a non-Ollama response shape"
                " (missing string 'response' field)"
            )
        return parse_claims(raw)
