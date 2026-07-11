"""Money-trail reconstruction (SPEC 6.4). REAL graph reachability.

The headline metric is the prototype's, exactly: walk every complaint,
sum amounts, and count an amount as traced iff the ledger contains a
directed path from the complaint's first-layer mule to the syndicate's
cash-out node (``nx.has_path``). ``pct_traced`` is rounded to 1 decimal
and must equal results.json at seed 42 (90.8).

Additional REAL outputs for the UI, none of which perturb the metric
(the metric loop below is the prototype loop, unmodified; everything
else is bookkeeping on the side):

- per-network trail hops, ordered victim side -> cash-out: complaint
  amounts aggregated per victim-side L1 mule (src ``"victims"``), then
  L1 -> L2 flows over existing ledger edges, then the L2 -> cash flow;
- break points: ledger edges that are missing where aggregated complaint
  value would have flowed (freeze opportunities, the money is stranded
  at the src side of the missing edge);
- per-network traced / total value.

Invariant (unit-tested): the per-network ``traced_amt`` values sum to
the global traced total. Noise complaints (synd < 0) count toward the
global total but belong to no network and are never traced, exactly as
in the prototype.
"""

import networkx as nx

from paritran.engine.types import (NetworkTrail, SyntheticBundle, TrailHop,
                                   TrailResult)

# Pseudo-source label for the aggregated victim side of each network.
VICTIM_SOURCE = "victims"


def trace(bundle: SyntheticBundle) -> TrailResult:
    """Trace complaint value through the money ledger."""
    money = bundle.money

    # ---- Prototype metric loop, exact (prototype section 4). ----
    total_val = traced_val = 0
    total_by_synd = {s: 0 for s in bundle.syndicates}
    traced_by_synd = {s: 0 for s in bundle.syndicates}
    flow_by_mule = {s: {m: 0 for m in bundle.syndicates[s].l1}
                    for s in bundle.syndicates}
    for c in bundle.complaints:
        if c.synd < 0:  # noise singletons have no syndicate trail
            total_val += c.amt
            continue
        total_val += c.amt
        syn = bundle.syndicates[c.synd]
        reachable = (money.has_node(c.mule) and money.has_node(syn.cash)
                     and nx.has_path(money, c.mule, syn.cash))
        total_by_synd[c.synd] += c.amt
        flow_by_mule[c.synd][c.mule] += c.amt
        if reachable:
            traced_val += c.amt
            traced_by_synd[c.synd] += c.amt
    pct_traced = round(100 * traced_val / total_val, 1)

    # ---- Per-network trails (UI extras, computed on the side). ----
    per_network: list[NetworkTrail] = []
    for s in sorted(bundle.syndicates):
        truth = bundle.syndicates[s]
        flow = flow_by_mule[s]
        hops: list[TrailHop] = []
        breaks: list[tuple[str, str]] = []

        # Victim side: aggregate complaint amounts per L1 mule.
        for m in truth.l1:
            if flow[m] > 0:
                hops.append(TrailHop(src=VICTIM_SOURCE, dst=m,
                                     amount=flow[m]))
        # L1 -> L2 over existing ledger edges; missing edges with
        # stranded value are breaks (freeze points).
        reached_l2 = 0
        for m in truth.l1:
            if money.has_edge(m, truth.l2):
                if flow[m] > 0:
                    hops.append(TrailHop(src=m, dst=truth.l2,
                                         amount=flow[m]))
                reached_l2 += flow[m]
            elif flow[m] > 0:
                breaks.append((m, truth.l2))
        # L2 -> cash-out.
        if money.has_edge(truth.l2, truth.cash):
            if reached_l2 > 0:
                hops.append(TrailHop(src=truth.l2, dst=truth.cash,
                                     amount=reached_l2))
        elif reached_l2 > 0:
            breaks.append((truth.l2, truth.cash))

        per_network.append(NetworkTrail(
            syndicate=s, hops=hops, breaks=breaks,
            traced_amt=traced_by_synd[s], total_amt=total_by_synd[s]))

    return TrailResult(pct_traced=pct_traced, total_amt=total_val,
                       traced_amt=traced_val, per_network=per_network)
