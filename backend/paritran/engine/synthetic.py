"""Synthetic complaint generator (SPEC 6.2). Zero real PII, ever.

RNG contract (critical, SPEC 6.2):

Structural stream. One ``random.Random(seed)`` instance reproduces the
prototype's global ``random.seed(seed)`` draw order EXACTLY:

1. Per syndicate s in 0..5: ``randint`` phones(2,4), devices(1,3),
   ips(1,2), l1(2,3); complaint count ``randint(25,55)``; per complaint:
   ``randint(1,3)`` evaluated as the k argument of ``sample`` (which then
   consumes its own draws), one ``random() < 0.06`` bleed check plus
   ``randint(0,5)`` only when it fires, ``randint(5,500)`` amount,
   ``choice(l1)`` mule.
2. 40 noise complaints: ``randint(5,300)`` each.
3. Money ledger, after all complaints: per syndicate, per L1 mule
   ``random() < 0.93``, then ``random() < 0.98`` for L2 to cash.

Text stream. Narratives NEVER touch the structural stream. Each
complaint's text (and its language pick and template pick) comes from its
own ``random.Random(f"text/{seed}/{complaint_id}")`` instance. String
seeding is sha512 based and platform stable. ``generate(seed,
narratives=False)`` skips text rendering entirely and the structural
fields are byte-identical either way; the unit tests lock this.

Narratives. Deterministic templates per fraud archetype (OTP vishing,
fake trading app, impersonation, mule ring, phishing, parcel scam), one
archetype per seeded syndicate. Every identifier in ``complaint.ids``
appears verbatim in the text (sorted order, so the sentence is stable
across processes regardless of PYTHONHASHSEED), the rupee amount in the
text equals ``amt``, and the first-layer mule account is named. A
deterministic subset of complaints is rendered in Hindi and Gujarati
(the per-complaint text RNG's first ``random()`` draw: < 0.10 Hindi,
< 0.20 Gujarati, else English, so each targets roughly 10 percent).
Noise complaints get benign non-fraud narratives (service follow-ups).

``intake_hash`` is deliberately left at its default: SPEC says it is set
at ingest, not by the generator.
"""

import random

import networkx as nx

from paritran.engine.types import Complaint, SyndicateTruth, SyntheticBundle

N_SYND = 6
N_NOISE = 40
P_EDGE = 0.93          # L1 mule -> L2 ledger edge probability (prototype P_EDGE)
P_CASH_EDGE = 0.98     # L2 -> cash-out ledger edge probability
P_BLEED = 0.06         # cross-syndicate identifier bleed probability

HI_FRACTION = 0.10     # target fraction of Hindi narratives
GU_FRACTION = 0.10     # target fraction of Gujarati narratives

# One archetype per seeded syndicate (deterministic assignment).
ARCHETYPES = (
    "otp_vishing",
    "fake_trading_app",
    "impersonation",
    "mule_ring",
    "phishing",
    "parcel_scam",
)

# ---------------------------------------------------------------------------
# Narrative templates. {amt} is the plain rupee integer equal to
# Complaint.amt, {mule} the first-layer mule account, {ref} the reference
# identifier for benign noise complaints. Identifier coverage of
# complaint.ids is guaranteed mechanically by the appended identifier
# sentence, never by the lead template.
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "otp_vishing": {
        "en": (
            "A caller posing as a bank officer convinced the complainant to"
            " share the one time password, and Rs {amt} was debited from the"
            " account soon after. The funds were transferred to account"
            " {mule}.",
            "The complainant received a vishing call warning that the debit"
            " card would be blocked, shared the OTP under pressure, and lost"
            " Rs {amt}. The amount moved to account {mule}.",
        ),
        "hi": (
            "बैंक अधिकारी बनकर एक व्यक्ति ने फोन किया और डेबिट कार्ड बंद होने का डर"
            " दिखाकर ओटीपी पूछ लिया। खाते से Rs {amt} निकल गए। रकम खाता {mule}"
            " में गई।",
        ),
        "gu": (
            "બેંક અધિકારી હોવાનો ઢોંગ કરીને એક વ્યક્તિએ ફોન કરી ઓટીપી માંગ્યો અને"
            " ખાતામાંથી Rs {amt} ઉપડી ગયા. રકમ ખાતા {mule} માં ગઈ.",
        ),
    },
    "fake_trading_app": {
        "en": (
            "The complainant was lured into a fake trading application that"
            " showed fabricated profits and deposited Rs {amt}, which could"
            " never be withdrawn. The deposit landed in account {mule}.",
            "An online tipster pushed the complainant onto a bogus trading"
            " platform; a deposit of Rs {amt} was made and the platform then"
            " blocked every withdrawal. The money went to account {mule}.",
        ),
        "hi": (
            "एक नकली ट्रेडिंग ऐप में झूठा मुनाफा दिखाकर शिकायतकर्ता से Rs {amt}"
            " जमा करवाए गए, निकासी कभी नहीं हुई। रकम खाता {mule} में गई।",
        ),
        "gu": (
            "નકલી ટ્રેડિંગ એપમાં ખોટો નફો બતાવી ફરિયાદી પાસે Rs {amt} જમા"
            " કરાવ્યા, ઉપાડ ક્યારેય ન થયો. રકમ ખાતા {mule} માં ગઈ.",
        ),
    },
    "impersonation": {
        "en": (
            "A person impersonating a senior police officer on a video call"
            " threatened arrest and made the complainant transfer Rs {amt}."
            " The transfer went to account {mule}.",
            "Pretending to be a relative stranded abroad, the fraudster"
            " begged for urgent help and collected Rs {amt}. The amount was"
            " credited to account {mule}.",
        ),
        "hi": (
            "पुलिस अधिकारी बनकर वीडियो कॉल पर गिरफ्तारी की धमकी दी गई और Rs"
            " {amt} ट्रांसफर करवा लिए गए। रकम खाता {mule} में गई।",
        ),
        "gu": (
            "પોલીસ અધિકારી હોવાનો ઢોંગ કરી વિડિયો કૉલ પર ધરપકડની ધમકી આપી Rs"
            " {amt} ટ્રાન્સફર કરાવ્યા. રકમ ખાતા {mule} માં ગઈ.",
        ),
    },
    "mule_ring": {
        "en": (
            "Operators running a ring of rented bank accounts induced the"
            " complainant to transfer Rs {amt} as a processing deposit for a"
            " work-from-home task scheme. The funds moved into account"
            " {mule}.",
            "The complainant was drawn into a task scheme run through a ring"
            " of rented accounts and lost Rs {amt} of personal funds. The"
            " first credit went to account {mule}.",
        ),
        "hi": (
            "किराये के खातों के एक गिरोह ने टास्क स्कीम के बहाने शिकायतकर्ता से Rs"
            " {amt} ट्रांसफर करवा लिए। पहली रकम खाता {mule} में गई।",
        ),
        "gu": (
            "ભાડાના ખાતાઓની ટોળકીએ ટાસ્ક સ્કીમના બહાને ફરિયાદી પાસે Rs {amt}"
            " ટ્રાન્સફર કરાવ્યા. પહેલી રકમ ખાતા {mule} માં ગઈ.",
        ),
    },
    "phishing": {
        "en": (
            "After clicking a phishing link that copied the bank's login"
            " page, the complainant's net banking credentials were captured"
            " and Rs {amt} was transferred out. The money was routed to"
            " account {mule}.",
            "A phishing SMS about a KYC update captured the complainant's"
            " credentials, after which Rs {amt} left the account. The amount"
            " reached account {mule}.",
        ),
        "hi": (
            "केवाईसी अपडेट के नाम पर भेजे गए फ़िशिंग लिंक से नेट बैंकिंग विवरण चुरा"
            " लिए गए और Rs {amt} खाते से निकल गए। रकम खाता {mule} में गई।",
        ),
        "gu": (
            "કેવાયસી અપડેટના નામે મોકલેલી ફિશિંગ લિંકથી નેટ બેંકિંગ વિગતો ચોરાઈ"
            " અને Rs {amt} ખાતામાંથી ઉપડી ગયા. રકમ ખાતા {mule} માં ગઈ.",
        ),
    },
    "parcel_scam": {
        "en": (
            "A caller claiming a parcel was held at customs demanded a"
            " clearance charge, and the complainant paid Rs {amt}. The"
            " payment went to account {mule}.",
            "Posing as a courier company, the fraudster said an"
            " international parcel contained contraband and extracted Rs"
            " {amt} as a release fee. The funds landed in account {mule}.",
        ),
        "hi": (
            "कस्टम में पार्सल रुकने का झांसा देकर क्लीयरेंस शुल्क के नाम पर Rs {amt}"
            " ले लिए गए। भुगतान खाता {mule} में गया।",
        ),
        "gu": (
            "કસ્ટમમાં પાર્સલ અટક્યાનું બહાનું કરી ક્લિયરન્સ ચાર્જ પેટે Rs {amt}"
            " પડાવી લીધા. ચુકવણી ખાતા {mule} માં ગઈ.",
        ),
    },
    # Benign, explicitly non-fraud narratives for the 40 noise complaints.
    "noise": {
        "en": (
            "Request for status of a pending refund of Rs {amt} for a"
            " cancelled booking, reference {ref}. No fraud is suspected;"
            " this is a service follow-up.",
            "A duplicate charge of Rs {amt} appeared on last month's"
            " statement, reference {ref}. The complainant requests a"
            " reversal by the service provider; no fraud is alleged.",
        ),
        "hi": (
            "रद्द बुकिंग के Rs {amt} के लंबित रिफंड की स्थिति जाननी है, संदर्भ"
            " {ref}। किसी धोखाधड़ी की आशंका नहीं है, यह केवल सेवा संबंधी अनुरोध"
            " है।",
        ),
        "gu": (
            "રદ થયેલા બુકિંગના Rs {amt} ના બાકી રિફંડની સ્થિતિ જાણવી છે, સંદર્ભ"
            " {ref}. કોઈ છેતરપિંડીની શંકા નથી, આ માત્ર સેવા સંબંધિત વિનંતી છે.",
        ),
    },
}

# Identifier type labels for the appended identifier sentence.
_ID_LABELS = {
    "en": {"PH": "phone", "DV": "device", "IP": "IP address",
           "MULE": "beneficiary account", "SOLO": "reference",
           "OTHER": "identifier"},
    "hi": {"PH": "फोन", "DV": "डिवाइस", "IP": "आईपी",
           "MULE": "लाभार्थी खाता", "SOLO": "संदर्भ", "OTHER": "पहचानकर्ता"},
    "gu": {"PH": "ફોન", "DV": "ડિવાઇસ", "IP": "આઈપી",
           "MULE": "લાભાર્થી ખાતું", "SOLO": "સંદર્ભ", "OTHER": "ઓળખકર્તા"},
}

_ID_SENTENCE_LEAD = {
    "en": "Identifiers on record:",
    "hi": "दर्ज पहचानकर्ता:",
    "gu": "નોંધાયેલા ઓળખકર્તા:",
}


def _id_kind(identifier: str) -> str:
    for prefix in ("MULE", "SOLO", "PH", "DV", "IP"):
        if identifier.startswith(prefix):
            return prefix
    return "OTHER"


def _id_sentence(ids_sorted: list[str], lang: str) -> str:
    labels = _ID_LABELS[lang]
    parts = [f"{labels[_id_kind(x)]} {x}" for x in ids_sorted]
    stop = "।" if lang == "hi" else "."  # danda for Hindi
    return f"{_ID_SENTENCE_LEAD[lang]} {', '.join(parts)}{stop}"


def _render_narrative(seed: int, complaint_id: int, synd: int,
                      ids: frozenset[str], amt: int, mule: str) -> tuple[str, str]:
    """Deterministic narrative + language from the isolated text RNG.

    Draw protocol on ``random.Random(f"text/{seed}/{complaint_id}")``:
    draw 1 ``random()`` picks the language, draw 2 ``randrange`` picks the
    template variant. Nothing here reads the structural stream.
    """
    rng = random.Random(f"text/{seed}/{complaint_id}")
    u = rng.random()
    if u < HI_FRACTION:
        lang = "hi"
    elif u < HI_FRACTION + GU_FRACTION:
        lang = "gu"
    else:
        lang = "en"
    key = "noise" if synd < 0 else ARCHETYPES[synd % len(ARCHETYPES)]
    variants = _TEMPLATES[key][lang]
    lead = variants[rng.randrange(len(variants))]
    body = lead.format(amt=amt, mule=mule, ref=mule)
    # Sorted so the sentence is byte-stable across processes (frozenset
    # iteration order depends on the per-process string hash seed).
    return f"{body} {_id_sentence(sorted(ids), lang)}", lang


def generate(seed: int = 42, narratives: bool = True) -> SyntheticBundle:
    """Generate the synthetic bundle. Prototype structural stream, exact.

    ``narratives=False`` leaves ``narrative``/``lang`` at their defaults
    without consuming any RNG anywhere; structural fields are identical.
    """
    rng = random.Random(seed)

    raw: list[dict] = []
    syndicates: dict[int, SyndicateTruth] = {}
    cid = 0
    for s in range(N_SYND):
        phones = [f"PH{s}{i}" for i in range(rng.randint(2, 4))]
        devices = [f"DV{s}{i}" for i in range(rng.randint(1, 3))]
        ips = [f"IP{s}{i}" for i in range(rng.randint(1, 2))]
        l1 = [f"MULE{s}_L1_{i}" for i in range(rng.randint(2, 3))]
        l2 = f"MULE{s}_L2"
        cash = f"CASH{s}"
        syndicates[s] = SyndicateTruth(l1=tuple(l1), l2=l2, cash=cash)
        pool = phones + devices + ips + l1
        for _ in range(rng.randint(25, 55)):
            ids = set(rng.sample(pool, k=rng.randint(1, 3)))
            if rng.random() < P_BLEED:  # realistic cross-syndicate bleed
                ids.add(f"PH{rng.randint(0, N_SYND - 1)}0")
            amt = rng.randint(5, 500) * 1000
            mule = rng.choice(l1)
            raw.append({"id": cid, "synd": s, "ids": ids, "amt": amt,
                        "mule": mule})
            cid += 1
    for _ in range(N_NOISE):  # legitimate unrelated noise
        raw.append({"id": cid, "synd": -1 - cid, "ids": {f"SOLO{cid}"},
                    "amt": rng.randint(5, 300) * 1000, "mule": f"SOLO{cid}"})
        cid += 1

    # Money ledger, after all complaints (deliberately incomplete).
    money = nx.DiGraph()
    for s in range(N_SYND):
        syn = syndicates[s]
        for m in syn.l1:
            if rng.random() < P_EDGE:
                money.add_edge(m, syn.l2)
        if rng.random() < P_CASH_EDGE:
            money.add_edge(syn.l2, syn.cash)

    complaints: list[Complaint] = []
    for r in raw:
        frozen_ids = frozenset(r["ids"])
        if narratives:
            narrative, lang = _render_narrative(
                seed, r["id"], r["synd"], frozen_ids, r["amt"], r["mule"])
            complaints.append(Complaint(
                id=r["id"], synd=r["synd"], ids=frozen_ids, amt=r["amt"],
                mule=r["mule"], narrative=narrative, lang=lang))
        else:
            complaints.append(Complaint(
                id=r["id"], synd=r["synd"], ids=frozen_ids, amt=r["amt"],
                mule=r["mule"]))

    return SyntheticBundle(seed=seed, complaints=complaints,
                           syndicates=syndicates, money=money)
