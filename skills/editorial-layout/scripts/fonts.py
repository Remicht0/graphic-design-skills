#!/usr/bin/env python3
"""
fonts.py — download open-source fonts locally (from Fontsource via npm) and
write a fonts.css with the @font-face rules, so documents render with the
right typefaces even offline or where Google Fonts is blocked.

Every Google Font (and many others) is on Fontsource. Licenses (mostly SIL
OFL) are copied next to the files.

Requirements: Node.js / npm on the PATH.

Examples
  python3 fonts.py "Instrument Serif" "Anton" -o fonts
  python3 fonts.py "Inter" --weights 300,400,600,800 --italic -o fonts
  python3 fonts.py "Space Grotesk" "JetBrains Mono" -o fonts --subsets latin,latin-ext,cyrillic
Then in the HTML:  <link rel="stylesheet" href="fonts/fonts.css">
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


def slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")


def fetch(pkg: str, tmp: str) -> str:
    r = subprocess.run(["npm", "pack", pkg, "--silent"], cwd=tmp, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"npm pack {pkg} failed")
    tgz = os.path.join(tmp, r.stdout.strip().splitlines()[-1])
    dest = os.path.join(tmp, slug(pkg))
    with tarfile.open(tgz) as t:
        try:
            t.extractall(dest, filter="data")  # safe extraction (Python 3.12+ / recent 3.8–3.11)
        except TypeError:
            t.extractall(dest)
    return os.path.join(dest, "package")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("families", nargs="+", help='font family names, e.g. "Instrument Serif"')
    ap.add_argument("-o", "--out", default="fonts", help="output folder (default ./fonts)")
    ap.add_argument("--weights", default="400,700", help="comma-separated weights (default 400,700; unavailable ones are skipped)")
    ap.add_argument("--italic", action="store_true", help="also fetch italics")
    ap.add_argument("--subsets", default="latin,latin-ext", help="unicode subsets (default latin,latin-ext)")
    a = ap.parse_args(argv)

    if not shutil.which("npm"):
        raise SystemExit("npm not found: install Node.js, or download the fonts manually (fonts.google.com)")
    os.makedirs(a.out, exist_ok=True)
    weights = [w.strip() for w in a.weights.split(",") if w.strip()]
    subsets = [s.strip() for s in a.subsets.split(",") if s.strip()]
    styles = [""] + (["-italic"] if a.italic else [])
    css_out = []
    css_path = os.path.join(a.out, "fonts.css")
    if os.path.exists(css_path):  # append to an existing set, replacing families we re-fetch
        wanted = {f.lower() for f in a.families}
        for block in re.split(r"(?=/\* )", open(css_path).read()):
            m = re.search(r"font-family:\s*'([^']+)'", block)
            if block.strip() and not (m and m.group(1).lower() in wanted):
                css_out.append(block.strip())

    with tempfile.TemporaryDirectory() as tmp:
        for fam in a.families:
            s = slug(fam)
            try:
                pkg = fetch(f"@fontsource/{s}", tmp)
            except RuntimeError as e:
                print(f"✗ {fam}: not found on Fontsource ({e.__class__.__name__}). Check the exact name on fontsource.org.", file=sys.stderr)
                continue
            meta = {}
            if os.path.exists(os.path.join(pkg, "metadata.json")):
                meta = json.load(open(os.path.join(pkg, "metadata.json")))
            avail_w = [str(w) for w in meta.get("weights", [])]
            variable = bool(meta.get("variable"))
            got = []
            for w in weights:
                if avail_w and w not in avail_w:
                    continue
                for st in styles:
                    for sub in subsets:
                        f = os.path.join(pkg, f"{sub}-{w}{st}.css")
                        if not os.path.exists(f):
                            continue
                        css = open(f).read()
                        for woff2 in re.findall(r"url\(\./files/([^)]+\.woff2)\)", css):
                            shutil.copy(os.path.join(pkg, "files", woff2), os.path.join(a.out, woff2))
                        # keep woff2 only, point to the local copy
                        css = re.sub(r"src:\s*url\(\./files/([^)]+\.woff2)\)\s*format\('woff2'\)[^;]*;",
                                     r"src: url(\1) format('woff2');", css)
                        css_out.append(css.strip())
                        got.append(f"{w}{st}")
            lic = os.path.join(pkg, "LICENSE")
            if os.path.exists(lic):
                shutil.copy(lic, os.path.join(a.out, f"{s}-LICENSE.txt"))
            if got:
                uniq = sorted(set(got), key=got.index)
                print(f"✓ {fam}: {', '.join(uniq)}" + (f"  (available weights: {', '.join(avail_w)})" if avail_w else ""))
            else:
                print(f"✗ {fam}: none of the weights {weights} exist (available: {', '.join(avail_w) or '?'})"
                      + ("; it is a variable font, try its listed weights" if variable else ""), file=sys.stderr)

    with open(css_path, "w") as f:
        f.write("\n\n".join(css_out) + "\n")
    print(f"→ {css_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
