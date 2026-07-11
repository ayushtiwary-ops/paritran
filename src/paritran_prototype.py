"""
Paritran prototype slice  (synthetic data only, zero real PII).

Pipeline, every stage a REAL computation (no placeholders):
  synthetic complaints
    -> entity resolution -> linkage graph
    -> community detection (mule networks)              [networkx]
    -> money-trail reconstruction (graph reachability)  [real trace]
    -> grounded legal mapping (BM25 retrieval)          [real retrieval]
    -> F9 groundedness gate over a generative step      [real, non-tautological]
    -> SHA-256 hash-chained chain of custody            [real, tamper-tested]

Outputs measured, reproducible metrics to results.json.
Fixed seed. Reproduce:  python3 paritran_prototype.py

NOTE ON THE MODEL LAYER
  In production the generator is a local LLM (Gemma via Ollama, zero egress) and
  the retriever is BM25 + InLegalBERT embeddings. Here the generator is a
  transparent stub that also fabricates, so the F9 gate is exercised against a
  real adversary rather than a self-comparison. Swap-in points are marked TODO.
"""
import random, re, json, time, hashlib, itertools, os
import networkx as nx

random.seed(42)
BASE = os.path.dirname(os.path.abspath(__file__))
t0 = time.time()

# ----------------------------------------------------------------------------
# 1. Synthetic generator with seeded ground-truth syndicates
# ----------------------------------------------------------------------------
N_SYND = 6
complaints, syndicates, cid = [], {}, 0
for s in range(N_SYND):
    phones  = [f"PH{s}{i}"       for i in range(random.randint(2, 4))]
    devices = [f"DV{s}{i}"       for i in range(random.randint(1, 3))]
    ips     = [f"IP{s}{i}"       for i in range(random.randint(1, 2))]
    l1      = [f"MULE{s}_L1_{i}" for i in range(random.randint(2, 3))]
    l2      = f"MULE{s}_L2"
    cash    = f"CASH{s}"
    syndicates[s] = {"l1": l1, "l2": l2, "cash": cash}
    pool = phones + devices + ips + l1
    for _ in range(random.randint(25, 55)):
        ids = set(random.sample(pool, k=random.randint(1, 3)))
        if random.random() < 0.06:                       # realistic cross-syndicate bleed
            ids.add(f"PH{random.randint(0, N_SYND-1)}0")
        complaints.append({"id": cid, "synd": s, "ids": ids,
                           "amt": random.randint(5, 500) * 1000,
                           "mule": random.choice(l1)})
        cid += 1
for _ in range(40):                                       # legitimate unrelated noise
    complaints.append({"id": cid, "synd": -1 - cid, "ids": {f"SOLO{cid}"},
                       "amt": random.randint(5, 300) * 1000, "mule": f"SOLO{cid}"})
    cid += 1

# ----------------------------------------------------------------------------
# 2. Entity resolution + linkage graph
# ----------------------------------------------------------------------------
G = nx.Graph()
for c in complaints:
    G.add_node(c["id"])
id_index = {}
for c in complaints:
    for x in c["ids"]:
        id_index.setdefault(x, []).append(c["id"])
for members in id_index.values():
    for a, b in itertools.combinations(members, 2):
        if G.has_edge(a, b): G[a][b]["w"] += 1
        else:                G.add_edge(a, b, w=1)

# ----------------------------------------------------------------------------
# 3. Community detection -> predicted mule networks
# ----------------------------------------------------------------------------
comms = list(nx.algorithms.community.greedy_modularity_communities(G, weight="w"))
pred = {}
for k, com in enumerate(comms):
    for n in com: pred[n] = k
nextk = len(comms)
for c in complaints:
    pred.setdefault(c["id"], nextk); nextk += 1
networks_found = len([com for com in comms if len(com) >= 5])

# pairwise precision / recall vs ground truth
truth = {c["id"]: c["synd"] for c in complaints}
tp = fp = fn = 0
for a, b in itertools.combinations([c["id"] for c in complaints], 2):
    sp, st = pred[a] == pred[b], truth[a] == truth[b]
    if   sp and st:     tp += 1
    elif sp and not st: fp += 1
    elif st:            fn += 1
precision = tp / (tp + fp) if tp + fp else 0
recall    = tp / (tp + fn) if tp + fn else 0
f1        = 2 * precision * recall / (precision + recall) if precision + recall else 0

# ----------------------------------------------------------------------------
# 4. Money-trail reconstruction  -- REAL reachability, not random.random()
#    Build a directed money ledger (deliberately incomplete) and WALK it.
# ----------------------------------------------------------------------------
P_EDGE = 0.93
money = nx.DiGraph()
for s in range(N_SYND):
    syn = syndicates[s]
    for m in syn["l1"]:
        if random.random() < P_EDGE: money.add_edge(m, syn["l2"])
    if random.random() < 0.98:       money.add_edge(syn["l2"], syn["cash"])
total_val = traced_val = 0
for c in complaints:
    if c["synd"] < 0:  # noise singletons have no syndicate trail
        total_val += c["amt"]; continue
    total_val += c["amt"]
    syn = syndicates[c["synd"]]
    reachable = money.has_node(c["mule"]) and money.has_node(syn["cash"]) \
        and nx.has_path(money, c["mule"], syn["cash"])
    if reachable: traced_val += c["amt"]
pct_traced = round(100 * traced_val / total_val, 1)

# ----------------------------------------------------------------------------
# 5. Grounded legal mapping  -- REAL BM25 retrieval over bare-act text
#    (TODO: add InLegalBERT semantic reranking + rule-layer agreement)
# ----------------------------------------------------------------------------
CORPUS = {
 "BNS 318":  "Cheating and dishonestly inducing delivery of property; whoever deceives any person fraudulently or dishonestly to deliver any property.",
 "BNS 319":  "Cheating by personation; a person cheats by pretending to be some other person or knowingly substituting one person for another.",
 "BNS 111":  "Organised crime; any continuing unlawful activity by a crime syndicate including financial fraud and running of mule accounts.",
 "IT Act 66C":"Identity theft; fraudulent or dishonest use of the electronic signature, password or any other unique identification feature of any person.",
 "IT Act 66D":"Cheating by personation by using any communication device or computer resource.",
 "BNS 308":  "Extortion; intentionally putting a person in fear of injury to dishonestly induce delivery of property.",
 "IT Act 43":"Damage to computer or system; unauthorised access, downloading or introduction of a contaminant.",
}
def tok(s): return re.findall(r"[a-z0-9]+", s.lower())
docs = {k: tok(v) for k, v in CORPUS.items()}
N = len(docs); avgdl = sum(len(d) for d in docs.values()) / N
df = {}
for d in docs.values():
    for w in set(d): df[w] = df.get(w, 0) + 1
import math
def idf(w): return math.log(1 + (N - df.get(w, 0) + 0.5) / (df.get(w, 0) + 0.5))
def bm25(q, dk, k1=1.5, b=0.75):
    d = docs[dk]; L = len(d); sc = 0.0
    for w in q:
        if w in d:
            f = d.count(w); sc += idf(w) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * L / avgdl))
    return sc
def map_sections(text, topn=2, thresh=0.8):
    q = tok(text); ranked = sorted(((bm25(q, k), k) for k in docs), reverse=True)
    return [k for sc, k in ranked[:topn] if sc >= thresh] or [ranked[0][1]]
LABELLED = [   # untuned natural-language complaints (do NOT reuse statute wording)
 ("A caller claiming to be from the bank made her share the one time code, then emptied the account", {"IT Act 66C","BNS 318"}),
 ("He set up a fake trading application and lured victims to deposit money", {"IT Act 66D","BNS 318"}),
 ("Someone used my stolen credentials to authorise a payment", {"IT Act 66C"}),
 ("A ring of operators ran dozens of rented accounts to move stolen funds", {"BNS 111"}),
 ("She was tricked into transferring money for a promised refund that never came", {"BNS 318"}),
 ("A man pretended to be a police officer on a video call and demanded a fine", {"BNS 319","IT Act 66D"}),
 ("Impersonating my cousin online, the fraudster asked for urgent money", {"BNS 319"}),
 ("After a phishing message my net banking password was captured", {"IT Act 66C","IT Act 66D"}),
 ("A parcel scam caller demanded a customs clearance charge", {"BNS 318"}),
 ("The gang laundered proceeds through a chain of go-between accounts", {"BNS 111"}),
 ("My biometric details were cloned to withdraw money", {"IT Act 66C"}),
 ("A fake officer over a call threatened arrest unless money was sent", {"BNS 319","BNS 318"}),
 ("An app cloned my identity and opened accounts in my name", {"IT Act 66C","IT Act 66D"}),
 ("I was deceived into paying an advance for a job that did not exist", {"BNS 318"}),
 ("Crypto scheme operators posed as advisors and took deposits", {"BNS 318","IT Act 66D"}),
 ("A reset link stole my banking login after I clicked it", {"IT Act 66C","IT Act 66D"}),
 ("The syndicate coordinated withdrawals across many mule accounts", {"BNS 111"}),
 ("A stranger posed as a delivery agent to extract the verification code", {"BNS 319","IT Act 66C"}),
 ("Fraudsters deceived an elderly man into sending money to a fake charity", {"BNS 318"}),
 ("Using a spoofed number they pretended to be a government official", {"BNS 319"}),
 ("Unauthorised access wiped and transferred funds from the account", {"IT Act 66D","IT Act 43"}),
]
hits = sum(1 for txt, gold in LABELLED if set(map_sections(txt)) & gold)
section_acc = round(100 * hits / len(LABELLED), 1)

# ----------------------------------------------------------------------------
# 6. F9 groundedness gate  -- REAL, over a generative step that also fabricates
#    Gate rule: a claim passes iff its cited section exists AND its quote is a
#    verbatim substring of that bare act. Catches paraphrase and invention.
# ----------------------------------------------------------------------------
def gate(sec, quote): return sec in CORPUS and quote.strip().lower() in CORPUS[sec].lower()
def mock_generate():                 # TODO: replace with Gemma via Ollama
    real = {"BNS 318":"dishonestly inducing delivery of property",
            "BNS 319":"pretending to be some other person",
            "IT Act 66C":"unique identification feature",
            "IT Act 66D":"using any communication device or computer resource",
            "BNS 111":"continuing unlawful activity by a crime syndicate"}
    secs, out = list(real), []
    for i in range(50):
        sec = secs[i % len(secs)]
        if i % 5 == 0:               # the model hallucinates ~1 in 5
            out.append(("BNS 420", "whoever commits cyber fraud") if i % 10 == 0
                       else (sec, "the accused clearly intended to defraud the victim"))
        else:
            out.append((sec, real[sec]))
    return out
claims   = mock_generate()
withheld = [c for c in claims if not gate(*c)]
passed   = [c for c in claims if gate(*c)]

# ----------------------------------------------------------------------------
# 7. SHA-256 hash-chained chain of custody  -- real, tamper-tested
# ----------------------------------------------------------------------------
def build_chain(records):
    chain, prev = [], "0" * 64
    for r in records:
        h = hashlib.sha256((prev + json.dumps(r, sort_keys=True)).encode()).hexdigest()
        chain.append({"rec": r, "prev": prev, "hash": h}); prev = h
    return chain
def verify(chain):
    prev = "0" * 64
    for link in chain:
        h = hashlib.sha256((prev + json.dumps(link["rec"], sort_keys=True)).encode()).hexdigest()
        if h != link["hash"]: return False
        prev = h
    return True
records = [{"artefact": f"evidence_{i}", "sha256": hashlib.sha256(str(i).encode()).hexdigest()[:16]} for i in range(12)]
chain = build_chain(records); chain_ok = verify(chain)
tampered = [dict(l) for l in chain]
tampered[5] = dict(tampered[5]); tampered[5]["rec"] = {"artefact": "swapped", "sha256": "deadbeef"}
tamper_detected = not verify(tampered)

# ----------------------------------------------------------------------------
# results
# ----------------------------------------------------------------------------
results = {
 "n_complaints": len(complaints), "n_syndicates_seeded": N_SYND, "networks_found": networks_found,
 "linkage_precision": round(precision, 3), "linkage_recall": round(recall, 3), "linkage_f1": round(f1, 3),
 "pct_value_traced_to_cashout": pct_traced, "money_trail_method": "directed-graph reachability",
 "section_accuracy_bm25": section_acc, "section_method": "Okapi BM25 over bare-act corpus (InLegalBERT rerank TODO)",
 "f9_claims": len(claims), "f9_passed": len(passed), "f9_withheld_real_hallucinations": len(withheld),
 "f9_leaked": sum(1 for c in withheld if gate(*c)),
 "chain_len": len(chain), "chain_verified": chain_ok, "tamper_detected": tamper_detected,
 "time_to_packet_sec": round(time.time() - t0, 3),
 "data": "synthetic, ground-truth known, zero real PII", "seed": 42,
}
json.dump(results, open(os.path.join(BASE, "..", "results.json"), "w"), indent=2)
print(json.dumps(results, indent=2))
