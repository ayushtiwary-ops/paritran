"""Tests for paritran.engine.ner (SPEC 6.6): rule-augmented NER.

Plain-python tests, no db marker. Each fixture text plants a known exact
set of (identifier, kind) pairs; the suite asserts precision and recall
1.0 over the fixtures, computed for real by score_extraction (no stubbed
numbers, truth rule SPEC section 1).
"""

from paritran.engine.ner import KINDS, extract, normalize_indic, score_extraction

# ---------------------------------------------------------------------------
# Fixtures: (text, exact set of planted (identifier, kind) pairs)
# ---------------------------------------------------------------------------

EN_TEXT = (
    "The victim received a call from +91 9876543210 and later from 9123456780. "
    "Money went to the UPI handle fraudster@upi from account 123456789012 "
    "(IFSC HDFC0000123). The fraudulent session came from IP 203.0.113.7. "
    "Case notes also reference corpus identifiers PH00, DV12 and IP21, mule "
    "accounts MULE3_L1_1 and MULE3_L2, cash-out CASH3 and singleton SOLO123."
)
EN_EXPECTED = {
    ("9876543210", "phone"),
    ("9123456780", "phone"),
    ("fraudster@upi", "upi"),
    ("123456789012", "account"),
    ("HDFC0000123", "ifsc"),
    ("203.0.113.7", "ipv4"),
    ("PH00", "syn_phone"),
    ("DV12", "syn_device"),
    ("IP21", "syn_ip"),
    ("MULE3_L1_1", "syn_mule_l1"),
    ("MULE3_L2", "syn_mule_l2"),
    ("CASH3", "syn_cash"),
    ("SOLO123", "syn_solo"),
}

# Hindi narrative, Latin-script identifiers embedded in Devanagari text.
HI_TEXT = (
    "शिकायतकर्ता को मोबाइल नंबर 9876543210 से कॉल आया और खाते 123456789012 से "
    "पैसा UPI हैंडल fraudster@upi पर भेजा गया। धोखेबाज़ का IP पता 203.0.113.7 था "
    "और IFSC कोड HDFC0000123 दर्ज है।"
)
HI_EXPECTED = {
    ("9876543210", "phone"),
    ("123456789012", "account"),
    ("fraudster@upi", "upi"),
    ("203.0.113.7", "ipv4"),
    ("HDFC0000123", "ifsc"),
}

# Gujarati narrative, Latin-script identifiers embedded in Gujarati text.
GU_TEXT = (
    "ફરિયાદીને મોબાઈલ નંબર 9876543210 પરથી કૉલ આવ્યો અને ખાતા 123456789012 "
    "માંથી રકમ UPI હેન્ડલ fraudster@upi પર મોકલાઈ. છેતરપિંડીનું IP સરનામું "
    "203.0.113.7 હતું અને ઓળખ MULE3_L1_1 નોંધાઈ છે."
)
GU_EXPECTED = {
    ("9876543210", "phone"),
    ("123456789012", "account"),
    ("fraudster@upi", "upi"),
    ("203.0.113.7", "ipv4"),
    ("MULE3_L1_1", "syn_mule_l1"),
}

# Narrative shaped like the synthetic generator output (SPEC 6.2 shapes).
PROTO_TEXT = (
    "Complaint 41 mentions phone PH31, device DV20, address IP50, mule "
    "MULE5_L1_2 feeding MULE5_L2, cash-out CASH5, and noise account SOLO260."
)
PROTO_EXPECTED = {
    ("PH31", "syn_phone"),
    ("DV20", "syn_device"),
    ("IP50", "syn_ip"),
    ("MULE5_L1_2", "syn_mule_l1"),
    ("MULE5_L2", "syn_mule_l2"),
    ("CASH5", "syn_cash"),
    ("SOLO260", "syn_solo"),
}

FIXTURES = [
    (EN_TEXT, EN_EXPECTED),
    (HI_TEXT, HI_EXPECTED),
    (GU_TEXT, GU_EXPECTED),
    (PROTO_TEXT, PROTO_EXPECTED),
]


# ---------------------------------------------------------------------------
# Per-fixture exactness
# ---------------------------------------------------------------------------


def test_english_fixture_exact():
    assert set(extract(EN_TEXT)) == EN_EXPECTED


def test_hindi_mixed_script_exact():
    # The narrative really is Devanagari, so the indicnlp path is exercised.
    assert any("ऀ" <= ch <= "ॿ" for ch in HI_TEXT)
    assert set(extract(HI_TEXT)) == HI_EXPECTED


def test_gujarati_mixed_script_exact():
    assert any("઀" <= ch <= "૿" for ch in GU_TEXT)
    assert set(extract(GU_TEXT)) == GU_EXPECTED


def test_prototype_corpus_shapes_exact():
    assert set(extract(PROTO_TEXT)) == PROTO_EXPECTED


def test_fixture_precision_recall_is_one():
    """P/R 1.0 on the fixtures, computed by really running the extractor."""
    scores = score_extraction(FIXTURES)
    print(f"\nNER fixture scores: {scores}")
    assert scores["n_texts"] == 4
    assert scores["fp"] == 0
    assert scores["fn"] == 0
    assert scores["precision"] == 1.0
    assert scores["recall"] == 1.0


# ---------------------------------------------------------------------------
# Behavioural contracts
# ---------------------------------------------------------------------------


def test_phone_format_canonicalization():
    """Every supported Indian mobile format collapses to the bare 10 digits."""
    for form in (
        "+919876543210",
        "+91 9876543210",
        "+91-98765-43210",
        "+91 98765 43210",
        "9876543210",
    ):
        assert extract(f"call from {form} today") == [("9876543210", "phone")], form


def test_phone_wins_over_account_for_10_digit_mobile_shape():
    # A bare 10-digit number starting 6-9 is a phone, never an account.
    assert extract("number 9876543210 noted") == [("9876543210", "phone")]
    # A 10-digit number NOT starting 6-9 falls to the account pattern.
    assert extract("account 1234567890 noted") == [("1234567890", "account")]


def test_dedup_and_stable_first_occurrence_order():
    text = (
        "First 9876543210, then account 123456789012, then again 9876543210 "
        "and +919876543210, and the account 123456789012 once more."
    )
    result = extract(text)
    assert result == [
        ("9876543210", "phone"),
        ("123456789012", "account"),
    ]
    # Deterministic: identical output on a second run.
    assert extract(text) == result


def test_no_false_positives_on_benign_text():
    text = (
        "Meet at 5 pm on 3 June 2026. Email admin@example.com about invoice "
        "12345678, PIN code 380001, and reference note 42."
    )
    # E-mail addresses (dotted domain), short numbers and years must not match.
    assert extract(text) == []


def test_kinds_are_from_the_published_set():
    for _, kind in extract(EN_TEXT):
        assert kind in KINDS


def test_normalize_indic_passthrough_for_latin():
    latin = "acct 123456789012 +91 9876543210 fraudster@upi HDFC0000123"
    assert normalize_indic(latin) == latin
