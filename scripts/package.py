#!/usr/bin/env python3
"""
package.py — build one .zip per skill in dist/, ready to upload to Claude
(Customize → Skills → + → Upload a skill). Each zip contains the skill
folder at its top level, as Claude expects.

Usage: python3 scripts/package.py [skill-name ...]
"""
from __future__ import annotations

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"__pycache__", ".previews", "previews"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def package(name: str, out_dir: str) -> str:
    src = os.path.join(ROOT, "skills", name)
    if not os.path.isfile(os.path.join(src, "SKILL.md")):
        raise SystemExit(f"no skill named {name}")
    out = os.path.join(out_dir, f"{name}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for f in sorted(files):
                if f in SKIP_FILES or f.endswith(".pyc"):
                    continue
                full = os.path.join(root, f)
                z.write(full, os.path.join(name, os.path.relpath(full, src)))
    return out


def main(argv):
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    names = argv or sorted(d for d in os.listdir(os.path.join(ROOT, "skills"))
                           if os.path.isdir(os.path.join(ROOT, "skills", d)) and not d.startswith((".", "_")))
    for n in names:
        path = package(n, out_dir)
        print(f"{os.path.relpath(path, ROOT)}  ({os.path.getsize(path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
