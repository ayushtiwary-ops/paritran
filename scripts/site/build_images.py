#!/usr/bin/env python3
"""
Convert product screenshots to web-optimized images for the site.

Source: ../deck/shots/*.png (2560w, one level above the repo; the 5 existing
seed-42 captures plus any new packet.png / demo.png produced by the extended
capture spec). Output: docs/assets/img/<name>.{webp,jpg} at 1600w. Pillow only.
A missing source is reported and skipped (stack-gated captures), never faked.
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
SHOTS = os.path.abspath(os.path.join(REPO, "..", "deck", "shots"))
OUT = os.path.join(REPO, "docs", "assets", "img")
os.makedirs(OUT, exist_ok=True)

TARGET_W = 1600
NAMES = ["discovery", "casefile", "custody", "evaluation", "security", "packet", "demo"]

for name in NAMES:
    src = os.path.join(SHOTS, name + ".png")
    if not os.path.exists(src):
        print(f"skip {name}: no source at {src} (stack-gated capture pending)")
        continue
    im = Image.open(src).convert("RGB")
    if im.width > TARGET_W:
        h = round(im.height * TARGET_W / im.width)
        im = im.resize((TARGET_W, h), Image.LANCZOS)
    webp = os.path.join(OUT, name + ".webp")
    jpg = os.path.join(OUT, name + ".jpg")
    im.save(webp, "WEBP", quality=82, method=6)
    im.save(jpg, "JPEG", quality=80, optimize=True, progressive=True)
    print(f"{name}: {im.width}x{im.height} -> webp {os.path.getsize(webp)//1024}KB, jpg {os.path.getsize(jpg)//1024}KB")
print("done.")
