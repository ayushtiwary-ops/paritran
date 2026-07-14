#!/usr/bin/env python3
"""
Generate REAL seed-42 replay data for the website's signature visuals, without
the docker stack and without touching the frozen results.json.

V3 (collapse graph): docs/assets/data/graph_replay.json
V4 (money trail):    docs/assets/data/money_trail.json

Method: the standalone judge-verifiable prototype (src/paritran_prototype.py)
computes the linkage graph, the 6 communities, and the money ledger with only
networkx. We execute it in an isolated namespace with its results.json write
neutralized, read the in-memory structures, and HARD FAIL unless the derived
metrics equal the frozen results.json. So the animation is a re-rendering of a
real run, never invented positions.
"""
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
PROTO = os.path.join(REPO, "src", "paritran_prototype.py")
RESULTS = os.path.join(REPO, "results.json")
OUTDIR = os.path.join(REPO, "docs", "assets", "data")
os.makedirs(OUTDIR, exist_ok=True)

# --- run the prototype in isolation, results.json write neutralized ----------
src = open(PROTO, encoding="utf-8").read()
WRITE_LINE = 'json.dump(results, open(os.path.join(BASE, "..", "results.json"), "w"), indent=2)'
assert src.count(WRITE_LINE) == 1, "prototype results.json write line drifted; refusing to run"
src = src.replace(WRITE_LINE, "pass  # results.json write neutralized by export_replay.py")
ns = {"__name__": "__export__", "__file__": PROTO}
exec(compile(src, PROTO, "exec"), ns)  # noqa: S102 (trusted first-party source)

complaints = ns["complaints"]
G = ns["G"]
comms = ns["comms"]
pred = ns["pred"]
money = ns["money"]
syndicates = ns["syndicates"]
results = ns["results"]

# --- parity gate: derived must equal frozen results.json ---------------------
frozen = json.load(open(RESULTS, encoding="utf-8"))
checks = {
    "n_complaints": 297,
    "networks_found": 6,
    "linkage_f1": 0.962,
    "pct_value_traced_to_cashout": 90.8,
    "linkage_precision": 0.957,
    "linkage_recall": 0.966,
}
for key, expected in checks.items():
    got, froz = results[key], frozen[key]
    assert got == froz == expected, f"PARITY FAIL {key}: derived {got}, frozen {froz}, expected {expected}"
print("parity OK:", {k: results[k] for k in checks})

# --- V3: collapse graph layout (deterministic) -------------------------------
rng = random.Random(42_000)  # layout-only seed, separate from the engine seed
W, H = 820, 520
CX, CY = W / 2, H / 2

networks = sorted((c for c in comms if len(c) >= 5), key=len, reverse=True)
assert len(networks) == 6, f"expected 6 detected networks, got {len(networks)}"
net_of = {}
for idx, com in enumerate(networks):
    for nid in com:
        net_of[nid] = idx

# 6 cluster centers on a circle
cluster_r = 165
centers = []
for i in range(6):
    a = 2 * math.pi * i / 6 - math.pi / 2
    centers.append((CX + cluster_r * math.cos(a), CY + cluster_r * 0.82 * math.sin(a)))

ids = [c["id"] for c in complaints]
reveal_order = ids[:]
rng.shuffle(reveal_order)
reveal_at = {nid: i for i, nid in enumerate(reveal_order)}

nodes = []
for c in complaints:
    nid = c["id"]
    net = net_of.get(nid, -1)
    # initial position: a wide streaming ring
    ta = rng.uniform(0, 2 * math.pi)
    x0 = CX + (250 + rng.uniform(-20, 20)) * math.cos(ta)
    y0 = CY + (250 + rng.uniform(-20, 20)) * 0.82 * math.sin(ta)
    if net >= 0:
        cxp, cyp = centers[net]
        rr = 46 * math.sqrt(rng.random())
        aa = rng.uniform(0, 2 * math.pi)
        x1 = cxp + rr * math.cos(aa)
        y1 = cyp + rr * math.sin(aa)
    else:
        # noise: outer ring, dim
        aa = rng.uniform(0, 2 * math.pi)
        x1 = CX + (238 + rng.uniform(-8, 8)) * math.cos(aa)
        y1 = CY + (238 + rng.uniform(-8, 8)) * 0.82 * math.sin(aa)
    nodes.append({
        "id": nid, "net": net, "revealAt": reveal_at[nid],
        "x0": round(x0, 1), "y0": round(y0, 1), "x1": round(x1, 1), "y1": round(y1, 1),
    })

# edges: keep intra-network edges (they do the clustering), cap for page weight
intra = [(a, b) for a, b in G.edges() if net_of.get(a, -1) != -1 and net_of.get(a, -1) == net_of.get(b, -1)]
intra.sort()
MAX_EDGES = 520
if len(intra) > MAX_EDGES:
    step = len(intra) / MAX_EDGES
    intra = [intra[int(i * step)] for i in range(MAX_EDGES)]
edges = [[a, b] for a, b in intra]

graph = {
    "meta": {"n_complaints": 297, "networks_found": 6, "linkage_f1": 0.962,
             "w": W, "h": H, "note": "REPLAY of real seed-42 linkage output; positions re-rendered"},
    "nodes": nodes,
    "edges": edges,
    "edges_subsampled": len(intra) >= MAX_EDGES,
}
json.dump(graph, open(os.path.join(OUTDIR, "graph_replay.json"), "w"), separators=(",", ":"))
print(f"wrote graph_replay.json: {len(nodes)} nodes, {len(edges)} edges (subsampled={graph['edges_subsampled']})")

# --- V4: money trail. Prefer a network with a real freeze point (broken hop) --
import networkx as nx  # noqa: E402 (already imported inside the prototype ns)
by_synd = {}
for c in complaints:
    if c["synd"] >= 0:
        by_synd.setdefault(c["synd"], []).append(c)


def analyse(s):
    syn = syndicates[s]
    vic = by_synd[s]
    l1_in = {}
    for c in vic:
        l1_in[c["mule"]] = l1_in.get(c["mule"], 0) + c["amt"]
    hops = []
    for m in syn["l1"]:
        amt = l1_in.get(m, 0)
        hops.append({"from": m, "to": syn["l2"], "amount": amt,
                     "broken": (amt > 0 and not money.has_edge(m, syn["l2"]))})
    l2_amt = sum(l1_in.get(m, 0) for m in syn["l1"] if money.has_edge(m, syn["l2"]))
    hops.append({"from": syn["l2"], "to": syn["cash"], "amount": l2_amt,
                 "broken": (l2_amt > 0 and not money.has_edge(syn["l2"], syn["cash"]))})
    total = sum(c["amt"] for c in vic)
    traced = sum(c["amt"] for c in vic
                 if money.has_node(c["mule"]) and money.has_node(syn["cash"])
                 and nx.has_path(money, c["mule"], syn["cash"]))
    broken = sum(1 for h in hops if h["broken"])
    return {"syn": syn, "vic": vic, "hops": hops, "total": total,
            "traced": traced, "broken": broken}


analyses = {s: analyse(s) for s in by_synd}
# choose: most freeze points, then most victims; a real broken hop makes the point
big = max(analyses, key=lambda s: (analyses[s]["broken"], len(analyses[s]["vic"])))
a = analyses[big]
syn, vic, hops, total_amt, traced_amt = a["syn"], a["vic"], a["hops"], a["total"], a["traced"]

money_out = {
    "headline_pct_traced": 90.8,
    "network": {
        "id": int(big),
        "victims": {"count": len(vic), "total": total_amt},
        "l1_count": len(syn["l1"]),
        "hops": hops,
        "traced_pct_this_network": round(100 * traced_amt / total_amt, 1) if total_amt else 0.0,
        "note": "REPLAY of real seed-42 money-ledger reachability; broken hops are freeze points",
    },
}
json.dump(money_out, open(os.path.join(OUTDIR, "money_trail.json"), "w"), separators=(",", ":"))
print(f"wrote money_trail.json: network {big}, {len(vic)} victims, {len(syn['l1'])} L1 mules, "
      f"{sum(1 for h in hops if h['broken'])} broken hop(s)")
print("frozen results.json untouched by this script.")
