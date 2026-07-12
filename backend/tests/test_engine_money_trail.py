"""Engine money-trail tests (SPEC 6.4, 6.1). Plain python, no db.

pct_traced is compared against the committed results.json oracle, and
recomputed inside the test with the prototype's own reachability loop to
prove the per-network extras never perturb the metric. Seed 22 has a
deliberately incomplete ledger (missing L1->L2 edges and one L2->cash
edge), which exercises breaks and untraced value.
"""

import json
from pathlib import Path

import networkx as nx

from paritran.engine import money_trail, synthetic

SEED = 42
BREAK_SEED = 22  # ledger has missing edges at this seed
from _paths import ORACLE_RESULTS as RESULTS_JSON


def test_seed42_pct_traced_matches_results_json_exactly():
    oracle = json.loads(RESULTS_JSON.read_text())
    result = money_trail.trace(synthetic.generate(SEED))
    assert result.pct_traced == oracle["pct_value_traced_to_cashout"] == 90.8


def test_metric_equals_prototype_reachability_loop():
    """Recompute pct_traced with the prototype's exact loop; the extra
    per-network outputs must not change it (SPEC 6.4)."""
    for seed in (SEED, BREAK_SEED):
        bundle = synthetic.generate(seed, narratives=False)
        total_val = traced_val = 0
        for c in bundle.complaints:
            if c.synd < 0:
                total_val += c.amt
                continue
            total_val += c.amt
            syn = bundle.syndicates[c.synd]
            reachable = (bundle.money.has_node(c.mule)
                         and bundle.money.has_node(syn.cash)
                         and nx.has_path(bundle.money, c.mule, syn.cash))
            if reachable:
                traced_val += c.amt
        result = money_trail.trace(bundle)
        assert result.pct_traced == round(100 * traced_val / total_val, 1)
        assert result.traced_amt == traced_val
        assert result.total_amt == total_val


def test_per_network_traced_sums_to_traced_total():
    for seed in (SEED, BREAK_SEED):
        bundle = synthetic.generate(seed, narratives=False)
        result = money_trail.trace(bundle)
        assert sum(n.traced_amt for n in result.per_network) \
            == result.traced_amt
        noise_total = sum(c.amt for c in bundle.complaints if c.synd < 0)
        assert sum(n.total_amt for n in result.per_network) + noise_total \
            == result.total_amt
        for n in result.per_network:
            assert 0 <= n.traced_amt <= n.total_amt


def test_hops_conserve_value():
    """Victim-side hops carry the full network value; the cash-out hop
    carries exactly the traced value."""
    for seed in (SEED, BREAK_SEED):
        bundle = synthetic.generate(seed, narratives=False)
        result = money_trail.trace(bundle)
        for n in result.per_network:
            truth = bundle.syndicates[n.syndicate]
            victim_hops = [h for h in n.hops
                           if h.src == money_trail.VICTIM_SOURCE]
            assert sum(h.amount for h in victim_hops) == n.total_amt
            l1_hops = [h for h in n.hops if h.dst == truth.l2]
            cash_hops = [h for h in n.hops if h.dst == truth.cash]
            if cash_hops:
                assert len(cash_hops) == 1
                assert cash_hops[0].amount \
                    == sum(h.amount for h in l1_hops) == n.traced_amt
            else:
                assert n.traced_amt == 0
            assert all(h.amount > 0 for h in n.hops)


def test_breaks_are_missing_ledger_edges_with_stranded_value():
    bundle = synthetic.generate(BREAK_SEED, narratives=False)
    result = money_trail.trace(bundle)
    all_breaks = [(n, b) for n in result.per_network for b in n.breaks]
    assert all_breaks, "seed 22 must exercise ledger breaks"
    for n, (src, dst) in all_breaks:
        truth = bundle.syndicates[n.syndicate]
        # The flagged edge really is absent from the ledger.
        assert not bundle.money.has_edge(src, dst)
        # And value really is stranded behind it: the network cannot be
        # fully traced.
        assert n.traced_amt < n.total_amt
        assert (src in truth.l1 and dst == truth.l2) \
            or (src == truth.l2 and dst == truth.cash)
    # Seed 22 includes an L2 -> cash break; that network traces nothing.
    cash_broken = [n for n in result.per_network
                   if any(b[1] == bundle.syndicates[n.syndicate].cash
                          for b in n.breaks)]
    assert cash_broken
    assert all(n.traced_amt == 0 for n in cash_broken)


def test_no_breaks_when_ledger_complete_seed42():
    """At seed 42 every ledger edge was drawn (that is WHY every network
    fully traces and the untraced 9.2 percent is exactly the noise)."""
    bundle = synthetic.generate(SEED, narratives=False)
    result = money_trail.trace(bundle)
    assert all(not n.breaks for n in result.per_network)
    assert all(n.traced_amt == n.total_amt for n in result.per_network)
    noise_total = sum(c.amt for c in bundle.complaints if c.synd < 0)
    assert result.total_amt - result.traced_amt == noise_total


def test_pct_independent_of_narratives():
    with_text = money_trail.trace(synthetic.generate(SEED, narratives=True))
    without_text = money_trail.trace(
        synthetic.generate(SEED, narratives=False))
    assert with_text.pct_traced == without_text.pct_traced
    assert with_text.traced_amt == without_text.traced_amt
    assert with_text.total_amt == without_text.total_amt
