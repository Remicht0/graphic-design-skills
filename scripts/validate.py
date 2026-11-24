#!/usr/bin/env python3
"""
validate.py — check every skill in skills/ against the Agent Skills format
and this repo's conventions. Run before opening a pull request; CI runs it too.

Checks
  • skills/<name>/SKILL.md exists, starts with YAML frontmatter
  • name: 1–64 chars, lowercase letters, digits and single hyphens, equals the folder name
  • description: 20–1024 chars, says when to use the skill
  • optional fields are known (license, compatibility ≤ 500 chars, metadata, allowed-tools)
  • body is not empty and under ~500 lines (move long references to separate files)
  • relative links / script paths mentioned in SKILL.md exist
  • scripts compile (Python) and are not huge binaries
  • every skill is listed in .claude-plugin/marketplace.json and in README.md

Usage: python3 scripts/validate.py [--fix-marketplace]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
KNOWN = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
MAX_FILE_MB = 2


def parse_frontmatter(text: str):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:]
    data, key = {}, None
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith(" "):
            key, val = m.group(1), m.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
                val = val[1:-1]
            data[key] = val
        elif key:  # continuation / nested map
            data[key] = (data[key] + " " + line.strip()).strip()
    return data, body


def check_skill(path: str, errors: list, warnings: list):
    name = os.path.basename(path)
    md = os.path.join(path, "SKILL.md")
    tag = f"skills/{name}"
    if not os.path.isfile(md):
        errors.append(f"{tag}: missing SKILL.md")
        return None
    text = open(md, encoding="utf-8").read()
    fm, body = parse_frontmatter(text)
    if fm is None:
        errors.append(f"{tag}: SKILL.md must start with YAML frontmatter between --- lines")
        return None
    n = fm.get("name", "")
    if not n:
        errors.append(f"{tag}: frontmatter needs a name")
    elif len(n) > 64 or not NAME_RE.match(n):
        errors.append(f"{tag}: name '{n}' must be 1–64 chars of lowercase letters, digits and single hyphens")
    elif n != name:
        errors.append(f"{tag}: name '{n}' must match the folder name '{name}'")
    d = fm.get("description", "")
    if not d:
        errors.append(f"{tag}: frontmatter needs a description")
    elif len(d) > 1024:
        errors.append(f"{tag}: description is {len(d)} chars (max 1024)")
    elif len(d) < 20:
        errors.append(f"{tag}: description is too short to tell an agent when to use the skill")
    elif not re.search(r"\b(use|when)\b", d, re.I):
        warnings.append(f"{tag}: description should say when to use the skill (\"Use when…\")")
    if "compatibility" in fm and len(fm["compatibility"]) > 500:
        errors.append(f"{tag}: compatibility is over 500 chars")
    for k in fm:
        if k not in KNOWN:
            warnings.append(f"{tag}: unknown frontmatter field '{k}'")
    if "license" not in fm:
        warnings.append(f"{tag}: add 'license: MIT' to the frontmatter")
    lines = body.strip().splitlines()
    if len(lines) < 5:
        errors.append(f"{tag}: SKILL.md body is (almost) empty")
    elif len(lines) > 500:
        warnings.append(f"{tag}: SKILL.md body is {len(lines)} lines; move details into reference files")

    # referenced local files
    for ref in set(re.findall(r"(?<![\w./-])((?:scripts|assets|templates|references)/[\w./-]+\.\w+)", body)):
        if not os.path.exists(os.path.join(path, ref)):
            errors.append(f"{tag}: SKILL.md mentions {ref}, which doesn't exist")
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            rel = os.path.relpath(fp, ROOT)
            if os.path.getsize(fp) > MAX_FILE_MB * 1024 * 1024:
                errors.append(f"{rel}: larger than {MAX_FILE_MB} MB")
            if f.endswith(".py"):
                try:
                    compile(open(fp, encoding="utf-8").read(), fp, "exec")
                except SyntaxError as e:
                    errors.append(f"{rel}: does not compile: line {e.lineno}: {e.msg}")
            if f in (".DS_Store", "Thumbs.db") or f.endswith((".pyc",)):
                errors.append(f"{rel}: junk file, remove it")
    return n or name


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix-marketplace", action="store_true", help="rewrite the skills list in marketplace.json")
    a = ap.parse_args(argv)

    errors, warnings, names = [], [], []
    for entry in sorted(os.listdir(SKILLS)):
        p = os.path.join(SKILLS, entry)
        if os.path.isdir(p) and not entry.startswith((".", "_")):
            n = check_skill(p, errors, warnings)
            if n:
                names.append(entry)

    # marketplace
    mp_path = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
    try:
        mp = json.load(open(mp_path))
        plugin = mp["plugins"][0]
        listed = [s.rstrip("/").split("/")[-1] for s in plugin.get("skills", [])]
        missing = [n for n in names if n not in listed]
        extra = [n for n in listed if n not in names]
        if a.fix_marketplace and (missing or extra):
            plugin["skills"] = [f"./skills/{n}" for n in names]
            json.dump(mp, open(mp_path, "w"), indent=2, ensure_ascii=False)
            open(mp_path, "a").write("\n")
            print(f"updated {os.path.relpath(mp_path, ROOT)}")
        else:
            for n in missing:
                errors.append(f"marketplace.json: skill '{n}' is not listed (run with --fix-marketplace)")
            for n in extra:
                errors.append(f"marketplace.json: lists '{n}', which doesn't exist")
    except FileNotFoundError:
        errors.append(".claude-plugin/marketplace.json is missing")
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        errors.append(f"marketplace.json is malformed: {e}")

    # README catalog
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for n in names:
        if f"skills/{n}" not in readme:
            errors.append(f"README.md: add skills/{n} to the skills table")

    for w in warnings:
        print(f"⚠️  {w}")
    for e in errors:
        print(f"❌ {e}")
    print(f"\n{len(names)} skill(s) checked: {', '.join(names)}")
    if errors:
        print(f"{len(errors)} error(s)")
        return 1
    print("✅ all good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
