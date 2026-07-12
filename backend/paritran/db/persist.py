"""Persist one pipeline run to Postgres (SPEC 7.1: engine outputs per run).

Synchronous psycopg on purpose: callers (the API lifecycle in M4, tests
here) run it in a worker thread. One connection, one transaction; either
every row of the run lands or none does. Batched ``executemany`` for the
bulk tables (complaints, entities, mentions, links, members, money
edges).

Written tables: runs, complaints, entities, entity_mentions, links,
networks, network_members, money_edges, trails. ``mappings`` and
``f9_result`` are accepted per the persistence contract but not written
here: section_mappings and claims hang off ``cases``, which are created
by the officer case workflow (SPEC 9.1), not by run persistence.

Returns the new ``runs.id``.
"""

from __future__ import annotations

import os
from collections import Counter

import psycopg
from psycopg.types.json import Jsonb

__all__ = ["persist_run"]

DATASET_VERSION = "v1+v2"

# Synthetic identifier prefixes -> entity kind labels (matches the
# rule-augmented NER kind names in engine/ner.py).
_KIND_PREFIXES = (
    ("MULE", None),  # resolved to l1/l2 below
    ("CASH", "syn_cash"),
    ("SOLO", "syn_solo"),
    ("PH", "syn_phone"),
    ("DV", "syn_device"),
    ("IP", "syn_ip"),
)


def _identifier_kind(identifier: str) -> str:
    if identifier.startswith("MULE"):
        return "syn_mule_l1" if "_L1_" in identifier else "syn_mule_l2"
    for prefix, kind in _KIND_PREFIXES[1:]:
        if identifier.startswith(prefix):
            return kind
    return "other"


def _majority_syndicate(members, truth: dict[int, int]) -> int | None:
    counts = Counter(truth[cid] for cid in members if truth[cid] >= 0)
    if not counts:
        return None
    return min(counts, key=lambda s: (-counts[s], s))


def persist_run(
    results: dict,
    bundle,
    linkage_result,
    trail_result,
    triage_scores,
    mappings,
    f9_result,
    dsn: str,
) -> int:
    """Write the whole run in one transaction; return runs.id."""
    del mappings, f9_result  # contract inputs; written via cases (M4)

    complaints = bundle.complaints
    truth = {c.id: c.synd for c in complaints}
    triage_by_synd = {t.syndicate: t for t in triage_scores}
    trail_by_synd = {t.syndicate: t for t in trail_result.per_network}

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # -- runs ------------------------------------------------------
            cur.execute(
                "INSERT INTO runs"
                " (seed, git_sha, dataset_version, generator, model_tag,"
                "  status, metrics, stage_latencies, finished_at)"
                " VALUES (%s, %s, %s, %s, %s, 'completed', %s, %s, now())"
                " RETURNING id",
                (
                    results["seed"],
                    os.environ.get("GIT_SHA", "unknown"),
                    DATASET_VERSION,
                    results.get("generator_name"),
                    results.get("generator_name"),
                    Jsonb(results),
                    Jsonb(results.get("stage_latencies_ms", {})),
                ),
            )
            run_id = cur.fetchone()[0]

            # -- complaints --------------------------------------------------
            cur.executemany(
                "INSERT INTO complaints"
                " (run_id, ext_id, synd, amt, mule, narrative, lang,"
                "  intake_hash)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        run_id,
                        c.id,
                        c.synd,
                        c.amt,
                        c.mule,
                        c.narrative,
                        c.lang,
                        c.intake_hash or None,
                    )
                    for c in complaints
                ],
            )
            cur.execute(
                "SELECT ext_id, id FROM complaints WHERE run_id = %s", (run_id,)
            )
            complaint_db_id = dict(cur.fetchall())

            # -- entities + entity_mentions (from complaint.ids) -------------
            identifiers = sorted({ident for c in complaints for ident in c.ids})
            cur.executemany(
                "INSERT INTO entities (run_id, identifier, kind)"
                " VALUES (%s, %s, %s)",
                [
                    (run_id, ident, _identifier_kind(ident))
                    for ident in identifiers
                ],
            )
            cur.execute(
                "SELECT identifier, id FROM entities WHERE run_id = %s",
                (run_id,),
            )
            entity_db_id = dict(cur.fetchall())
            cur.executemany(
                "INSERT INTO entity_mentions (complaint_id, entity_id)"
                " VALUES (%s, %s)",
                [
                    (complaint_db_id[c.id], entity_db_id[ident])
                    for c in complaints
                    for ident in sorted(c.ids)
                ],
            )

            # -- links (linkage graph edges with weight) ---------------------
            edges = sorted(
                (min(a, b), max(a, b), w)
                for a, b, w in linkage_result.graph.edges(data="w")
            )
            cur.executemany(
                "INSERT INTO links (run_id, a, b, weight)"
                " VALUES (%s, %s, %s, %s)",
                [
                    (run_id, complaint_db_id[a], complaint_db_id[b], w)
                    for a, b, w in edges
                ],
            )

            # -- networks + members + trails ---------------------------------
            for idx, community in enumerate(linkage_result.communities):
                synd = _majority_syndicate(community, truth)
                triage_row = triage_by_synd.get(synd) if synd is not None else None
                triage_json = (
                    {
                        "syndicate": triage_row.syndicate,
                        "score": triage_row.score,
                        "inputs": dict(triage_row.inputs),
                    }
                    if triage_row is not None
                    else None
                )
                cur.execute(
                    "INSERT INTO networks (run_id, idx, size, triage)"
                    " VALUES (%s, %s, %s, %s) RETURNING id",
                    (
                        run_id,
                        idx,
                        len(community),
                        Jsonb(triage_json) if triage_json is not None else None,
                    ),
                )
                network_id = cur.fetchone()[0]
                cur.executemany(
                    "INSERT INTO network_members (network_id, complaint_id)"
                    " VALUES (%s, %s)",
                    [
                        (network_id, complaint_db_id[cid])
                        for cid in sorted(community)
                    ],
                )
                trail = trail_by_synd.get(synd) if synd is not None else None
                if trail is not None:
                    cur.execute(
                        "INSERT INTO trails"
                        " (network_id, hops, traced_amt, total_amt, breaks)"
                        " VALUES (%s, %s, %s, %s, %s)",
                        (
                            network_id,
                            Jsonb(
                                [
                                    {
                                        "src": h.src,
                                        "dst": h.dst,
                                        "amount": h.amount,
                                    }
                                    for h in trail.hops
                                ]
                            ),
                            trail.traced_amt,
                            trail.total_amt,
                            Jsonb([list(b) for b in trail.breaks]),
                        ),
                    )

            # -- money_edges --------------------------------------------------
            cur.executemany(
                "INSERT INTO money_edges (run_id, src, dst)"
                " VALUES (%s, %s, %s)",
                [
                    (run_id, src, dst)
                    for src, dst in sorted(bundle.money.edges)
                ],
            )
        conn.commit()
    return run_id
