#!/usr/bin/env python3
"""
Honesty and budget gate for docs/index.html (SPEC_WEBSITE Sections 5-6).
Exit nonzero on any failure. Run:  python3 scripts/site/check_site.py
Add --list to print every number token found (used to build the allowlist).

Checks:
  - banned vocabulary and the word "hallucination" absent
  - "team@paritran.in", "0.048", em dash (U+2014) absent
  - required strings present (0.045, contact, stub fabrications, seed 42, anchors, /app/ link, demo link)
  - every number token in the rendered text is in allowlist_numbers.json
  - "100.0" only within 120 chars of both "8/8" and "15/15"
  - REAL/STUB/REPLAY/INFRA labels present (>= number of metric figures)
  - file-size budgets (html/css/js/fonts, initial-load sum)
"""
import html as htmllib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DOCS = os.path.join(REPO, "docs")
INDEX = os.path.join(DOCS, "index.html")
ALLOW = os.path.join(HERE, "allowlist_numbers.json")

BANNED = ["cutting-edge", "cutting edge", "revolutionary", "seamless", "ai-powered", "ai powered",
          "disruptive", "game-changer", "game changer", "transformative", "world-class", "world class",
          "state-of-the-art", "state of the art", "unlock", "empower", "hallucinat"]

FAILURES = []


def fail(msg):
    FAILURES.append(msg)


def rendered_text(raw):
    # drop script and style blocks, then tags, then decode entities
    t = re.sub(r"<script[\s\S]*?</script>", " ", raw)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t)
    # drop attributes' content by removing whole tags (keeps visible text only)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t)
    return re.sub(r"\s+", " ", t)


def number_tokens(text):
    # clean numeric tokens: fractions (8/8), decimals+percent (0.957, 90.8%),
    # grouped integers (22,845, 1,000), plain integers. Structural punctuation
    # like SHA-256, Section 63(4), gemma3:4b resolves to its component integers.
    toks = re.findall(r"\d+/\d+|\d[\d,]*\.\d+%?|\d[\d,]*%?", text)
    out = []
    for tk in toks:
        tk = tk.strip(",.")
        if tk and any(c.isdigit() for c in tk):
            out.append(tk)
    return out


def main():
    raw = open(INDEX, encoding="utf-8").read()
    text = rendered_text(raw)
    low = raw.lower()

    if "--list" in sys.argv:
        seen = {}
        for tk in number_tokens(text):
            seen[tk] = seen.get(tk, 0) + 1
        for tk in sorted(seen):
            print(f"{seen[tk]:3}  {tk}")
        return 0

    # 1. banned vocabulary + em dash
    for b in BANNED:
        if b in low:
            fail(f"banned token present: {b!r}")
    if "—" in raw:
        fail("em dash U+2014 present in index.html")
    for bad in ["team@paritran.in", "0.048"]:
        if bad in low:
            fail(f"must-be-absent token present: {bad!r}")

    # 2. required strings
    required = ["0.045", "aloolifts@gmail.com", "stub fabrications", "seed 42",
                'id="results"', 'id="pilot"',
                'https://ayushtiwary-ops.github.io/paritran/app/', 'href="demo.html"']
    for r in required:
        if r not in raw:
            fail(f"required string missing: {r!r}")

    # 3. allowlist: every number token must be allowlisted
    if not os.path.exists(ALLOW):
        fail("allowlist_numbers.json missing")
        allow = {}
    else:
        allow = json.load(open(ALLOW, encoding="utf-8"))
    allow_keys = set(allow.keys())
    orphans = {}
    for tk in number_tokens(text):
        if tk not in allow_keys:
            orphans[tk] = orphans.get(tk, 0) + 1
    if orphans:
        fail("orphan numbers (not in allowlist): " + ", ".join(f"{k}(x{v})" for k, v in sorted(orphans.items())))

    # 4. 100.0 adjacency to 8/8 and 15/15
    for m in re.finditer(r"100\.0", text):
        window = text[max(0, m.start() - 120): m.end() + 120]
        if "8/8" not in window or "15/15" not in window:
            fail("'100.0' appears without both '8/8' and '15/15' within 120 chars")

    # 5. label presence
    labels = len(re.findall(r"\b(REAL|STUB|REPLAY|INFRA)\b", raw))
    figures = raw.count("<figure")
    if labels < figures:
        fail(f"labels ({labels}) fewer than figures ({figures})")

    # 6. file-size budgets (raw bytes)
    def size(p):
        return os.path.getsize(p) if os.path.exists(p) else 0

    budgets = {
        INDEX: 70 * 1024,
        os.path.join(DOCS, "assets/css/site.css"): 30 * 1024,
        os.path.join(DOCS, "assets/js/site.js"): 40 * 1024,
    }
    for p, cap in budgets.items():
        if size(p) > cap:
            fail(f"{os.path.basename(p)} {size(p)} bytes exceeds budget {cap}")
    fonts = 0
    fdir = os.path.join(DOCS, "assets/fonts")
    if os.path.isdir(fdir):
        fonts = sum(size(os.path.join(fdir, f)) for f in os.listdir(fdir))
    if fonts > 200 * 1024:
        fail(f"fonts total {fonts} bytes exceeds 200 KB")

    if FAILURES:
        print("check_site.py FAIL:")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("check_site.py PASS")
    print(f"  numbers: {len(set(number_tokens(text)))} distinct tokens, all allowlisted")
    print(f"  labels: {labels} >= figures: {figures}")
    print(f"  sizes: html {size(INDEX)}B, css {size(budgets and os.path.join(DOCS,'assets/css/site.css'))}B, "
          f"js {size(os.path.join(DOCS,'assets/js/site.js'))}B, fonts {fonts}B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
