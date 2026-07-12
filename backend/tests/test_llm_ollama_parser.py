"""Ollama client tests (SPEC 6.8): lenient parser + failure contract.

No live network calls: the parser is tested against inline fixture
strings, and the transport paths use httpx.MockTransport. Exactly one
optional live test exists at the bottom, skipped unless
PARITRAN_LIVE_OLLAMA=1. Plain-python tests, no database.
"""

import json
import os

import httpx
import pytest

from paritran.llm.client import ModelUnavailable
from paritran.llm.ollama_client import (
    OllamaGenerator,
    ParsedClaims,
    build_prompt,
    parse_claims,
)

WELL_FORMED = (
    '[{"section": "BNS 318", "quote": "dishonestly inducing delivery of property"},'
    ' {"section": "IT Act 66C", "quote": "unique identification feature"}]'
)

FENCED = (
    "```json\n"
    '[{"section": "BNS 319", "quote": "pretending to be some other person"}]\n'
    "```"
)

CHATTY_PREAMBLE = (
    "Sure! Based on the case facts, the applicable sections are as follows.\n\n"
    "```json\n"
    '[{"section": "BNS 111", "quote": "continuing unlawful activity"},\n'
    ' {"section": "IT Act 66D", "quote": "using any communication device"}]\n'
    "```\n"
    "Let me know if you need anything else!"
)

MALFORMED_ITEMS = (
    '[{"section": "BNS 318", "quote": "whoever deceives any person"},'
    ' {"section": 420},'
    ' "not an object",'
    ' {"quote": "quote without a section"},'
    ' {"section": "  ", "quote": "blank section"},'
    ' {"section": "BNS 319", "quote": ""}]'
)

NO_ARRAY = "I cannot cite any sections for this case."

BROKEN_JSON_THEN_NOTHING = "Here you go: [{'section': 'BNS 318' quote:}]"


def test_parser_well_formed():
    claims = parse_claims(WELL_FORMED)
    assert isinstance(claims, ParsedClaims)
    assert claims.parse_errors == 0
    assert [(c.section, c.quote) for c in claims] == [
        ("BNS 318", "dishonestly inducing delivery of property"),
        ("IT Act 66C", "unique identification feature"),
    ]
    assert all(c.is_fabricated is None for c in claims)


def test_parser_tolerates_fenced_code_block():
    claims = parse_claims(FENCED)
    assert claims.parse_errors == 0
    assert [(c.section, c.quote) for c in claims] == [
        ("BNS 319", "pretending to be some other person")
    ]


def test_parser_tolerates_chatty_preamble_and_postamble():
    claims = parse_claims(CHATTY_PREAMBLE)
    assert claims.parse_errors == 0
    assert [c.section for c in claims] == ["BNS 111", "IT Act 66D"]


def test_parser_drops_and_counts_malformed_items():
    claims = parse_claims(MALFORMED_ITEMS)
    assert [(c.section, c.quote) for c in claims] == [
        ("BNS 318", "whoever deceives any person")
    ]
    assert claims.parse_errors == 5


def test_parser_no_array_at_all():
    claims = parse_claims(NO_ARRAY)
    assert list(claims) == []
    assert claims.parse_errors == 1


def test_parser_unparseable_bracket_counts_as_no_array():
    claims = parse_claims(BROKEN_JSON_THEN_NOTHING)
    assert list(claims) == []
    assert claims.parse_errors == 1


def test_parser_strips_whitespace_on_fields():
    claims = parse_claims('[{"section": " BNS 318 ", "quote": " some words "}]')
    assert claims[0].section == "BNS 318"
    assert claims[0].quote == "some words"


def test_prompt_contains_facts_and_corpus_and_json_instruction():
    prompt = build_prompt(
        {
            "case_facts": "Victim was induced to share an OTP.",
            "corpus": {
                "BNS 318": "whoever deceives any person fraudulently",
                "IT Act 66C": {"text_verbatim": "unique identification feature"},
            },
        }
    )
    assert "Victim was induced to share an OTP." in prompt
    assert "[BNS 318] whoever deceives any person fraudulently" in prompt
    assert "[IT Act 66C] unique identification feature" in prompt
    assert "JSON array" in prompt
    assert "verbatim" in prompt


def _ollama_ok_transport(model_response_text: str, seen: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"response": model_response_text})

    return httpx.MockTransport(handler)


def test_generator_success_path_parses_model_output():
    seen: dict = {}
    generator = OllamaGenerator(transport=_ollama_ok_transport(CHATTY_PREAMBLE, seen))
    claims = generator.generate_claims(
        {"case_facts": "facts", "corpus": {"BNS 111": "text"}}
    )
    assert [c.section for c in claims] == ["BNS 111", "IT Act 66D"]
    assert claims.parse_errors == 0
    assert seen["url"].endswith("/api/generate")
    assert seen["body"]["stream"] is False
    assert seen["body"]["model"] == generator.name.removeprefix("ollama:")
    assert "[BNS 111] text" in seen["body"]["prompt"]


def test_generator_labels_are_settings_driven_and_not_stub():
    generator = OllamaGenerator(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"response": "[]"}))
    )
    assert generator.is_stub is False
    assert generator.name.startswith("ollama:")


def test_connection_error_raises_model_unavailable():
    def refuse(request: httpx.Request):
        raise httpx.ConnectError("connection refused", request=request)

    generator = OllamaGenerator(transport=httpx.MockTransport(refuse))
    with pytest.raises(ModelUnavailable):
        generator.generate_claims({"case_facts": "", "corpus": {}})


def test_timeout_raises_model_unavailable():
    def too_slow(request: httpx.Request):
        raise httpx.ReadTimeout("timed out", request=request)

    generator = OllamaGenerator(transport=httpx.MockTransport(too_slow))
    with pytest.raises(ModelUnavailable):
        generator.generate_claims({"case_facts": "", "corpus": {}})


def test_http_error_status_raises_model_unavailable():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(500, json={"error": "boom"})
    )
    generator = OllamaGenerator(transport=transport)
    with pytest.raises(ModelUnavailable):
        generator.generate_claims({"case_facts": "", "corpus": {}})


def test_non_ollama_response_shape_raises_model_unavailable():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"unexpected": "shape"})
    )
    generator = OllamaGenerator(transport=transport)
    with pytest.raises(ModelUnavailable):
        generator.generate_claims({"case_facts": "", "corpus": {}})


@pytest.mark.skipif(
    os.environ.get("PARITRAN_LIVE_OLLAMA") != "1",
    reason="live Ollama test runs only with PARITRAN_LIVE_OLLAMA=1",
)
def test_live_ollama_generates_parseable_claims():
    """Optional live smoke test. Model output varies run to run, so this
    asserts structure only (honest: no exact values claimed for a live LLM)."""
    generator = OllamaGenerator()
    claims = generator.generate_claims(
        {
            "case_facts": "A caller posing as a bank officer obtained the"
            " victim's one-time password and drained the account.",
            "corpus": {
                "BNS 318": "Cheating and dishonestly inducing delivery of"
                " property; whoever deceives any person fraudulently or"
                " dishonestly to deliver any property.",
                "IT Act 66C": "Identity theft; fraudulent or dishonest use of"
                " the electronic signature, password or any other unique"
                " identification feature of any person.",
            },
        }
    )
    assert isinstance(claims, ParsedClaims)
    assert claims.parse_errors >= 0
    for claim in claims:
        assert claim.section
        assert claim.quote
        assert claim.is_fabricated is None


def test_parse_strips_bracketed_section_id():
    """Models echo the prompt's [BNS 111] bracket form; parser must strip it
    so the id matches the corpus key (else valid citations gate as invented)."""
    from paritran.llm.ollama_client import parse_claims
    out = parse_claims('[{"section": "[BNS 111]", "quote": "organised crime"}]')
    assert len(out) == 1
    assert out[0].section == "BNS 111"
