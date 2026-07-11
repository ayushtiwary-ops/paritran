"""Entity linkage and mule-network detection (SPEC 6.3). REAL.

Prototype algorithm exactly:

1. One graph node per complaint id.
2. For every identifier shared by two complaints, an edge whose weight
   ``w`` counts the number of shared identifiers.
3. ``networkx.algorithms.community.greedy_modularity_communities`` with
   ``weight="w"`` (deterministic, no RNG; networkx pinned 3.4.2).
4. Predicted networks are the communities of size >= 5.
5. Pairwise precision / recall / F1 against ground-truth syndicates,
   rounded to 3 decimals (the only rounding, applied exactly where the
   prototype applies it).

At seed 42 the metrics must equal results.json exactly:
n_complaints 297, networks_found 6, P/R/F1 0.957/0.966/0.962.
"""

import itertools

import networkx as nx

from paritran.engine.types import LinkageMetrics, LinkageResult, SyntheticBundle

MIN_COMMUNITY_SIZE = 5


def link(bundle: SyntheticBundle) -> LinkageResult:
    """Run entity resolution + community detection over the bundle."""
    # Entity resolution + linkage graph (prototype section 2).
    graph = nx.Graph()
    for c in bundle.complaints:
        graph.add_node(c.id)
    id_index: dict[str, list[int]] = {}
    for c in bundle.complaints:
        for x in c.ids:
            id_index.setdefault(x, []).append(c.id)
    for members in id_index.values():
        for a, b in itertools.combinations(members, 2):
            if graph.has_edge(a, b):
                graph[a][b]["w"] += 1
            else:
                graph.add_edge(a, b, w=1)

    # Community detection (prototype section 3).
    comms = list(nx.algorithms.community.greedy_modularity_communities(
        graph, weight="w"))
    pred: dict[int, int] = {}
    for k, com in enumerate(comms):
        for n in com:
            pred[n] = k
    nextk = len(comms)
    for c in bundle.complaints:  # prototype fallback for uncovered nodes
        pred.setdefault(c.id, nextk)
        nextk += 1
    networks = [set(com) for com in comms if len(com) >= MIN_COMMUNITY_SIZE]

    # Pairwise precision / recall vs ground truth (prototype section 3).
    truth = {c.id: c.synd for c in bundle.complaints}
    tp = fp = fn = 0
    for a, b in itertools.combinations([c.id for c in bundle.complaints], 2):
        same_pred = pred[a] == pred[b]
        same_truth = truth[a] == truth[b]
        if same_pred and same_truth:
            tp += 1
        elif same_pred and not same_truth:
            fp += 1
        elif same_truth:
            fn += 1
    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0)

    metrics = LinkageMetrics(
        n_complaints=len(bundle.complaints),
        networks_found=len(networks),
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
    )
    return LinkageResult(metrics=metrics, graph=graph,
                         communities=networks, pred=pred)
