"""Recoverability triage per network (SPEC 6.5). Accounts, never people.

One plain exposed formula per network:

    score = 0.4 * trail_completeness
          + 0.3 * (1 - cashout_reached_fraction)
          + 0.2 * recency_proxy
          + 0.1 * amount_band

All four terms are deterministic functions of the synthetic bundle and
the money-trail result, all account or network level (no person-level
feature exists anywhere in this module or its inputs), and every term is
exposed in ``TriageScore.inputs`` next to the score:

- trail_completeness: fraction of the network's expected ledger edges
  that exist in the money graph, (present L1->L2 edges + L2->cash if
  present) / (len(l1) + 1). How much of the trail we can actually see.
- cashout_reached_fraction: the network's traced_amt / total_amt, the
  fraction of complaint value that already reached the cash-out node.
  The formula rewards its complement: value NOT yet at cash-out is the
  freezable, recoverable part.
- recency_proxy: complaint ids are the intake sequence of the synthetic
  bundle (id k is the k-th complaint taken in), so the proxy is the mean
  complaint id of the network's complaints divided by the maximum
  complaint id in the bundle. In [0, 1]; higher means the network's
  complaints are on average fresher intakes. Deterministic by
  construction, no clock involved.
- amount_band: min(1, syndicate_total / 5_000_000) with syndicate_total
  the network's total complaint value in rupees.

Display stability: each term is rounded to 4 decimals, the score is the
weighted sum of the ROUNDED terms, itself rounded to 4, so the on-screen
formula recombines to the on-screen score exactly.

``linkage_result`` is accepted per the pipeline contract (stage 5
consumes stages 3 and 4). The SPEC 6.5 formula is defined over the
money-trail networks; no linkage-derived feature enters the score.

The returned list is the triage queue: sorted by score descending,
ties broken by ascending syndicate id.
"""

from paritran.engine.types import (LinkageResult, SyntheticBundle,
                                   TrailResult, TriageScore)

W_TRAIL = 0.4
W_CASHOUT = 0.3
W_RECENCY = 0.2
W_AMOUNT = 0.1
AMOUNT_BAND_CAP = 5_000_000  # rupees


def score(bundle: SyntheticBundle, linkage_result: LinkageResult,
          trail_result: TrailResult) -> list[TriageScore]:
    """Score every network for the triage queue (SPEC 6.5)."""
    del linkage_result  # pipeline contract; no linkage feature is scored

    max_cid = max(c.id for c in bundle.complaints)
    ids_by_synd: dict[int, list[int]] = {s: [] for s in bundle.syndicates}
    for c in bundle.complaints:
        if c.synd >= 0:
            ids_by_synd[c.synd].append(c.id)

    scores: list[TriageScore] = []
    for trail in trail_result.per_network:
        s = trail.syndicate
        truth = bundle.syndicates[s]

        expected_edges = len(truth.l1) + 1
        present_edges = sum(
            1 for m in truth.l1 if bundle.money.has_edge(m, truth.l2))
        present_edges += 1 if bundle.money.has_edge(truth.l2,
                                                    truth.cash) else 0
        trail_completeness = round(present_edges / expected_edges, 4)

        cashout_reached_fraction = round(
            trail.traced_amt / trail.total_amt if trail.total_amt else 0.0, 4)

        cids = ids_by_synd[s]
        recency_proxy = round(
            (sum(cids) / len(cids)) / max_cid if cids else 0.0, 4)

        amount_band = round(min(1.0, trail.total_amt / AMOUNT_BAND_CAP), 4)

        value = round(
            W_TRAIL * trail_completeness
            + W_CASHOUT * (1 - cashout_reached_fraction)
            + W_RECENCY * recency_proxy
            + W_AMOUNT * amount_band, 4)

        scores.append(TriageScore(
            syndicate=s,
            score=value,
            inputs=(
                ("trail_completeness", trail_completeness),
                ("cashout_reached_fraction", cashout_reached_fraction),
                ("recency_proxy", recency_proxy),
                ("amount_band", amount_band),
            ),
        ))

    scores.sort(key=lambda t: (-t.score, t.syndicate))
    return scores
