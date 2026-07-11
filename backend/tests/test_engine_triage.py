"""Engine triage tests (SPEC 6.5). Plain python, no db.

Every term of the exposed formula is recomputed independently in the
tests from the bundle and the trail result. All features are account or
network level; nothing person-level exists.
"""

from paritran.engine import linkage, money_trail, synthetic, triage

SEED = 42
BREAK_SEED = 22

EXPECTED_INPUT_NAMES = (
    "trail_completeness",
    "cashout_reached_fraction",
    "recency_proxy",
    "amount_band",
)


def _pipeline(seed):
    bundle = synthetic.generate(seed, narratives=False)
    lk = linkage.link(bundle)
    tr = money_trail.trace(bundle)
    return bundle, lk, tr, triage.score(bundle, lk, tr)


def test_one_score_per_network_and_deterministic():
    bundle, lk, tr, scores = _pipeline(SEED)
    assert sorted(t.syndicate for t in scores) == sorted(bundle.syndicates)
    again = triage.score(bundle, lk, tr)
    assert scores == again


def test_score_recombines_from_exposed_inputs():
    """score = 0.4*tc + 0.3*(1-cr) + 0.2*rp + 0.1*ab, from the very
    numbers shown in inputs (SPEC 6.5: all terms displayed)."""
    for seed in (SEED, BREAK_SEED):
        _, _, _, scores = _pipeline(seed)
        for t in scores:
            terms = dict(t.inputs)
            assert tuple(terms) == EXPECTED_INPUT_NAMES
            recombined = round(
                0.4 * terms["trail_completeness"]
                + 0.3 * (1 - terms["cashout_reached_fraction"])
                + 0.2 * terms["recency_proxy"]
                + 0.1 * terms["amount_band"], 4)
            assert t.score == recombined


def test_inputs_in_unit_range():
    for seed in (SEED, BREAK_SEED):
        _, _, _, scores = _pipeline(seed)
        for t in scores:
            for name, value in t.inputs:
                assert 0.0 <= value <= 1.0, (t.syndicate, name, value)
            assert 0.0 <= t.score <= 1.0


def test_queue_sorted_descending():
    for seed in (SEED, BREAK_SEED):
        _, _, _, scores = _pipeline(seed)
        values = [t.score for t in scores]
        assert values == sorted(values, reverse=True)


def test_terms_recomputed_from_bundle_and_trail():
    for seed in (SEED, BREAK_SEED):
        bundle, _, tr, scores = _pipeline(seed)
        trails = {n.syndicate: n for n in tr.per_network}
        max_cid = max(c.id for c in bundle.complaints)
        for t in scores:
            truth = bundle.syndicates[t.syndicate]
            trail = trails[t.syndicate]
            terms = dict(t.inputs)

            present = sum(1 for m in truth.l1
                          if bundle.money.has_edge(m, truth.l2))
            present += 1 if bundle.money.has_edge(truth.l2,
                                                  truth.cash) else 0
            assert terms["trail_completeness"] \
                == round(present / (len(truth.l1) + 1), 4)

            assert terms["cashout_reached_fraction"] \
                == round(trail.traced_amt / trail.total_amt, 4)

            cids = [c.id for c in bundle.complaints
                    if c.synd == t.syndicate]
            assert terms["recency_proxy"] \
                == round((sum(cids) / len(cids)) / max_cid, 4)

            assert terms["amount_band"] \
                == round(min(1.0, trail.total_amt / 5_000_000), 4)


def test_break_seed_moves_trail_terms():
    """Seed 22's incomplete ledger must show up in the terms: at least
    one network with trail_completeness < 1 and cashout fraction < 1."""
    _, _, _, scores = _pipeline(BREAK_SEED)
    terms = [dict(t.inputs) for t in scores]
    assert any(x["trail_completeness"] < 1.0 for x in terms)
    assert any(x["cashout_reached_fraction"] < 1.0 for x in terms)


def test_no_person_level_features():
    """The exposed inputs are exactly the four account/network level
    terms of SPEC 6.5, nothing else."""
    _, _, _, scores = _pipeline(SEED)
    for t in scores:
        assert tuple(name for name, _ in t.inputs) == EXPECTED_INPUT_NAMES
