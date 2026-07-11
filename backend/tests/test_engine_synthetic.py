"""Engine synthetic generator tests (SPEC 6.2). Plain python, no db.

Locks the two RNG contracts:
1. The structural stream reproduces the prototype's exact draw order.
2. The text stream is fully isolated: narratives on or off, the
   structural fields are byte-equal.
"""

import random

from paritran.engine import synthetic

SEED = 42


def _structural_repr(bundle):
    """Byte-comparable projection of the structural fields only."""
    return repr([
        (c.id, c.synd, tuple(sorted(c.ids)), c.amt, c.mule)
        for c in bundle.complaints
    ] + [sorted(bundle.syndicates.items(), key=lambda kv: kv[0])] +
        [sorted(bundle.money.edges())])


def test_structural_counts_seed42():
    bundle = synthetic.generate(SEED)
    assert len(bundle.complaints) == 297
    assert len(bundle.syndicates) == 6
    assert sum(1 for c in bundle.complaints if c.synd < 0) == 40


def test_prototype_stream_equality():
    """Replicate the prototype's generation loop verbatim on the GLOBAL
    random module (exactly as src/paritran_prototype.py does) and require
    identical structure from generate()'s single Random(seed) instance."""
    random.seed(SEED)
    complaints, syndicates, cid = [], {}, 0
    for s in range(6):
        phones = [f"PH{s}{i}" for i in range(random.randint(2, 4))]
        devices = [f"DV{s}{i}" for i in range(random.randint(1, 3))]
        ips = [f"IP{s}{i}" for i in range(random.randint(1, 2))]
        l1 = [f"MULE{s}_L1_{i}" for i in range(random.randint(2, 3))]
        syndicates[s] = {"l1": l1, "l2": f"MULE{s}_L2", "cash": f"CASH{s}"}
        pool = phones + devices + ips + l1
        for _ in range(random.randint(25, 55)):
            ids = set(random.sample(pool, k=random.randint(1, 3)))
            if random.random() < 0.06:
                ids.add(f"PH{random.randint(0, 5)}0")
            complaints.append({"id": cid, "synd": s, "ids": ids,
                               "amt": random.randint(5, 500) * 1000,
                               "mule": random.choice(l1)})
            cid += 1
    for _ in range(40):
        complaints.append({"id": cid, "synd": -1 - cid,
                           "ids": {f"SOLO{cid}"},
                           "amt": random.randint(5, 300) * 1000,
                           "mule": f"SOLO{cid}"})
        cid += 1
    edges = []
    for s in range(6):
        syn = syndicates[s]
        for m in syn["l1"]:
            if random.random() < 0.93:
                edges.append((m, syn["l2"]))
        if random.random() < 0.98:
            edges.append((syn["l2"], syn["cash"]))

    bundle = synthetic.generate(SEED)
    assert len(bundle.complaints) == len(complaints)
    for got, want in zip(bundle.complaints, complaints):
        assert got.id == want["id"]
        assert got.synd == want["synd"]
        assert got.ids == frozenset(want["ids"])
        assert got.amt == want["amt"]
        assert got.mule == want["mule"]
    for s, want in syndicates.items():
        truth = bundle.syndicates[s]
        assert truth.l1 == tuple(want["l1"])
        assert truth.l2 == want["l2"]
        assert truth.cash == want["cash"]
    assert sorted(bundle.money.edges()) == sorted(edges)


def test_generate_twice_identical():
    b1 = synthetic.generate(SEED)
    b2 = synthetic.generate(SEED)
    assert b1.complaints == b2.complaints  # includes narrative and lang
    assert b1.syndicates == b2.syndicates
    assert sorted(b1.money.edges()) == sorted(b2.money.edges())
    assert sorted(b1.money.nodes()) == sorted(b2.money.nodes())


def test_text_rng_isolation_structural_byte_equality():
    """Structural fields byte-equal whether narratives render or not."""
    with_text = synthetic.generate(SEED, narratives=True)
    without_text = synthetic.generate(SEED, narratives=False)
    assert _structural_repr(with_text) == _structural_repr(without_text)
    # And the disabled path really is blank on the narrative layer.
    assert all(c.narrative == "" and c.lang == "en"
               for c in without_text.complaints)


def test_every_identifier_verbatim_in_narrative():
    bundle = synthetic.generate(SEED)
    for c in bundle.complaints:
        for identifier in c.ids:
            assert identifier in c.narrative, (c.id, identifier)


def test_rupee_amount_in_narrative_equals_amt():
    bundle = synthetic.generate(SEED)
    for c in bundle.complaints:
        assert f"Rs {c.amt}" in c.narrative, c.id


def test_language_mix_deterministic_subset():
    bundle = synthetic.generate(SEED)
    n = len(bundle.complaints)
    counts = {"en": 0, "hi": 0, "gu": 0}
    for c in bundle.complaints:
        counts[c.lang] += 1
    # Target roughly 10 percent each for hi and gu.
    assert 0.05 <= counts["hi"] / n <= 0.15
    assert 0.05 <= counts["gu"] / n <= 0.15
    assert counts["en"] > counts["hi"] + counts["gu"]
    # Real scripts: Devanagari for hi, Gujarati block for gu.
    for c in bundle.complaints:
        if c.lang == "hi":
            assert any("ऀ" <= ch <= "ॿ" for ch in c.narrative), c.id
        elif c.lang == "gu":
            assert any("઀" <= ch <= "૿" for ch in c.narrative), c.id


def test_noise_narratives_are_benign():
    bundle = synthetic.generate(SEED)
    markers = {
        "en": "no fraud is",
        "hi": "धोखाधड़ी की आशंका नहीं",
        "gu": "છેતરપિંડીની શંકા નથી",
    }
    noise = [c for c in bundle.complaints if c.synd < 0]
    assert noise
    for c in noise:
        text = c.narrative.lower() if c.lang == "en" else c.narrative
        assert markers[c.lang] in text, c.id


def test_seed_sensitivity_not_canned():
    other = synthetic.generate(43)
    baseline = synthetic.generate(SEED)
    assert len(other.complaints) != len(baseline.complaints)
    assert _structural_repr(other) != _structural_repr(baseline)
