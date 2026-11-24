#!/usr/bin/env python3
"""
extract_static.py — low-fidelity design-token extraction from HTML + CSS
source, for when no browser is available.

Reads a URL (and its linked stylesheets) or local .html / .css files, and
reports: font families (declared, @font-face, Google Fonts, Adobe Fonts),
CSS custom properties, colors ranked by frequency, font sizes, media-query
breakpoints, transitions / animations / @keyframes, and libraries guessed
from script URLs.

It does NOT see computed styles, JS-injected CSS, or what is actually used
on the page — say so in any report built from it.

Requirements: Python 3.9+ (standard library only).

Examples
  python3 extract_static.py https://example.com -o extract.json
  python3 extract_static.py page.html styles.css
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (art-direction-analyzer; +https://github.com/Remicht0/graphic-design-skills)"

LIBS = {
    "GSAP": r"gsap|greensock|TweenMax", "ScrollTrigger": r"ScrollTrigger", "Lenis": r"lenis",
    "Locomotive Scroll": r"locomotive", "Three.js": r"three(\.module)?(\.min)?\.js|/three@",
    "Swiper": r"swiper", "Barba": r"barba", "Swup": r"swup", "Lottie": r"lottie|bodymovin",
    "Spline": r"spline", "Rive": r"rive", "p5": r"p5(\.min)?\.js", "AOS": r"\baos\b",
    "Webflow": r"webflow", "Framer": r"framer(usercontent)?\.com|framer-motion", "Shopify": r"cdn\.shopify",
    "WordPress": r"wp-content|wp-includes", "Squarespace": r"squarespace", "Wix": r"wixstatic|parastorage",
    "Next.js": r"/_next/", "Nuxt": r"/_nuxt/", "Cargo": r"cargo\.site|cargocollective",
    "jQuery": r"jquery", "Splitting / SplitType": r"splitting|split-type",
}

COLOR_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b|rgba?\([^)]*\)|hsla?\([^)]*\)|oklch\([^)]*\)|oklab\([^)]*\)")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
        enc = r.headers.get_content_charset() or "utf-8"
    return raw.decode(enc, errors="replace")


def norm_hex(c: str) -> str:
    c = c.strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) in (3, 4):
            h = "".join(x * 2 for x in h)
        return "#" + h[:6].upper() + (f" @{round(int(h[6:8], 16) / 2.55)}%" if len(h) == 8 and h[6:8].lower() != "ff" else "")
    m = re.match(r"rgba?\(([^)]*)\)", c)
    if m:
        parts = [p for p in re.split(r"[ ,/]+", m.group(1)) if p]
        try:
            vals = [float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in parts[:3]]
            hexv = "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in vals)
            if len(parts) > 3:
                a = float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3])
                if a < 1:
                    return f"{hexv} @{round(a * 100)}%"
            return hexv
        except ValueError:
            return c
    return re.sub(r"\s+", " ", c)


def analyze(html_docs: list[tuple[str, str]], css_docs: list[tuple[str, str]]):
    css_all = "\n".join(t for _, t in css_docs)
    html_all = "\n".join(t for _, t in html_docs)
    # inline <style> and style="" attributes
    css_all += "\n" + "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html_all, re.S | re.I))
    inline = re.findall(r'style="([^"]*)"', html_all, re.I)
    css_all += "\n" + "\n".join("x{" + s + "}" for s in inline)
    css_nc = re.sub(r"/\*.*?\*/", "", css_all, flags=re.S)

    families = collections.Counter()
    for m in re.finditer(r"font-family\s*:\s*([^;}{]+)", css_nc, re.I):
        first = m.group(1).split(",")[0].strip().strip("'\"")
        if first and not first.startswith("var("):
            families[first] += 1
    for m in re.finditer(r"\bfont\s*:\s*([^;}{]+)", css_nc, re.I):
        tail = m.group(1)
        fm = re.search(r"\d(?:px|rem|em|%|pt)?(?:/[\d.]+\w*)?\s+(['\"]?[A-Za-z][^,;]*)", tail)
        if fm:
            families[fm.group(1).strip().strip("'\"")] += 1
    font_faces = sorted({f.strip().strip("'\"") for f in re.findall(r"@font-face\s*{[^}]*font-family\s*:\s*([^;}]+)", css_nc, re.I)})
    google = []
    for href in re.findall(r"fonts\.googleapis\.com/css2?\?([^\"'\s>]+)", html_all + css_all):
        q = urllib.parse.parse_qs(urllib.parse.unquote(href.replace("&amp;", "&")))
        for fam in q.get("family", []):
            google.append(fam.split(":")[0].replace("+", " "))
    adobe = bool(re.search(r"use\.typekit\.net|p\.typekit\.net", html_all + css_all))

    variables = {}
    for block in re.findall(r"(?::root|html)\s*{([^}]*)}", css_nc):
        for name, val in re.findall(r"(--[\w-]+)\s*:\s*([^;]+)", block):
            if len(variables) < 150:
                variables[name] = val.strip()

    colors = collections.Counter(norm_hex(c) for c in COLOR_RE.findall(css_nc))
    sizes = collections.Counter(re.findall(r"font-size\s*:\s*([^;}{]+)", css_nc, re.I))
    weights = collections.Counter(w.strip() for w in re.findall(r"font-weight\s*:\s*([^;}{]+)", css_nc, re.I))
    spacing = collections.Counter(re.findall(r"letter-spacing\s*:\s*([^;}{]+)", css_nc, re.I))
    medias = collections.Counter(m.strip() for m in re.findall(r"@media([^{]+){", css_nc))
    transitions = collections.Counter(t.strip() for t in re.findall(r"transition\s*:\s*([^;}{]+)", css_nc, re.I))
    animations = collections.Counter(t.strip() for t in re.findall(r"animation\s*:\s*([^;}{]+)", css_nc, re.I))
    easings = collections.Counter(re.findall(r"cubic-bezier\([^)]*\)", css_nc))
    keyframes = sorted(set(re.findall(r"@(?:-webkit-)?keyframes\s+([\w-]+)", css_nc)))
    radii = collections.Counter(r.strip() for r in re.findall(r"border-radius\s*:\s*([^;}{]+)", css_nc, re.I))

    script_srcs = re.findall(r"<script[^>]+src=[\"']([^\"']+)", html_all, re.I)
    blob = " ".join(script_srcs) + " " + html_all[:300000]
    libs = [name for name, pat in LIBS.items() if re.search(pat, blob, re.I)]

    title = re.search(r"<title[^>]*>(.*?)</title>", html_all, re.S | re.I)
    top = lambda c, n: [{"value": k, "count": v} for k, v in c.most_common(n)]
    return {
        "mode": "static (HTML/CSS source only — no computed styles, no motion observed)",
        "title": title.group(1).strip() if title else None,
        "sources": {"html": [u for u, _ in html_docs], "css": [u for u, _ in css_docs]},
        "fonts": {"declared": top(families, 12), "font_face": font_faces, "google_fonts": sorted(set(google)),
                  "adobe_fonts": adobe, "sizes": top(sizes, 14), "weights": top(weights, 8),
                  "letter_spacing": top(spacing, 8)},
        "colors": top(colors, 20),
        "cssVariables": variables,
        "radii": top(radii, 8),
        "breakpoints": top(medias, 10),
        "motion": {"transitions": top(transitions, 10), "animations": top(animations, 10),
                   "easings": top(easings, 6), "keyframes": keyframes[:40]},
        "libraries": libs,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="a URL, or local .html / .css files")
    ap.add_argument("-o", "--output", help="write JSON here (default: stdout)")
    ap.add_argument("--max-css", type=int, default=12, help="max linked stylesheets to fetch")
    a = ap.parse_args(argv)

    html_docs, css_docs = [], []
    for src in a.inputs:
        if re.match(r"https?://", src):
            html = fetch(src)
            html_docs.append((src, html))
            hrefs = re.findall(r"<link[^>]+rel=[\"']?stylesheet[\"']?[^>]*>", html, re.I)
            links = []
            for tag in hrefs:
                m = re.search(r"href=[\"']([^\"']+)", tag)
                if m:
                    links.append(urllib.parse.urljoin(src, m.group(1).replace("&amp;", "&")))
            for link in links[: a.max_css]:
                try:
                    css_docs.append((link, fetch(link)))
                except Exception as e:
                    print(f"skip {link}: {e}", file=sys.stderr)
        elif src.lower().endswith((".css", ".scss")):
            css_docs.append((src, open(src, encoding="utf-8", errors="replace").read()))
        else:
            html = open(src, encoding="utf-8", errors="replace").read()
            html_docs.append((src, html))
            base = os.path.dirname(os.path.abspath(src))
            for m in re.findall(r"<link[^>]+href=[\"']([^\"']+\.css)[\"']", html, re.I):
                p = os.path.join(base, m)
                if os.path.exists(p):
                    css_docs.append((p, open(p, encoding="utf-8", errors="replace").read()))

    data = analyze(html_docs, css_docs)
    txt = json.dumps(data, indent=2, ensure_ascii=False)
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(txt)
        print(a.output)
    else:
        print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
