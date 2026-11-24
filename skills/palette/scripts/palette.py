#!/usr/bin/env python3
"""
palette.py — build, check and export color palettes.

Subcommands
  extract   pull a palette out of an image (k-means in OKLab), with roles
  contrast  WCAG 2 contrast matrix for a set of colors
  scale     tints and shades of one color (50 … 950), perceptually even (OKLCH)
  harmony   complementary / analogous / triadic / split / tetradic from one color
  export    write a palette to css, scss, tailwind, tokens (json), ase, gpl, svg, png

A palette is either a JSON file written by this script
  {"name": "...", "colors": [{"name": "ink", "hex": "#111111"}, ...]}
or a comma-separated list of hex colors ("#111,#f2efe9,#ff4f12").

Requirements: Python 3.9+, NumPy, Pillow.

Examples
  python3 palette.py extract photo.jpg -n 6 -o palette.json --sheet palette.png
  python3 palette.py contrast palette.json
  python3 palette.py scale "#2D4CB4" --name cobalt -o cobalt.json
  python3 palette.py harmony "#FF4F12" --type triadic
  python3 palette.py export palette.json --to ase -o palette.ase
  python3 palette.py export "#111,#f2efe9,#ff4f12" --to tailwind
"""
from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import struct
import sys

import numpy as np

# --------------------------------------------------------------------------
# Color math: sRGB <-> linear <-> OKLab / OKLCH (Björn Ottosson)
# --------------------------------------------------------------------------

def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 8:  # drop alpha
        h = h[:6]
    if len(h) != 6:
        raise ValueError(f"invalid hex color: #{h}")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def _lin(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _delin(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(np.clip(c, 0, None), 1 / 2.4) - 0.055)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])
_M2i = np.array([[1.0, 0.3963377774, 0.2158037573],
                 [1.0, -0.1055613458, -0.0638541728],
                 [1.0, -0.0894841775, -1.2914855480]])
_M1i = np.array([[4.0767416621, -3.3077115913, 0.2309699292],
                 [-1.2684380046, 2.6097574011, -0.3413193965],
                 [-0.0041960863, -0.7034186147, 1.7076147010]])


def srgb_to_oklab(rgb):
    lms = _lin(rgb) @ _M1.T
    return np.cbrt(lms) @ _M2.T


def oklab_to_srgb(lab):
    lms = (np.asarray(lab, dtype=float) @ _M2i.T) ** 3
    return _delin(lms @ _M1i.T)


def to_oklch(rgb):
    L, a, b = srgb_to_oklab(np.array(rgb))
    return float(L), float(math.hypot(a, b)), float(math.degrees(math.atan2(b, a)) % 360)


def from_oklch(L, C, H, fit=True):
    """OKLCH -> sRGB tuple; if fit, reduce chroma until in gamut."""
    def conv(c):
        a, b = c * math.cos(math.radians(H)), c * math.sin(math.radians(H))
        return oklab_to_srgb(np.array([L, a, b]))
    rgb = conv(C)
    if fit:
        lo, hi = 0.0, C
        if np.any(rgb < -1e-4) or np.any(rgb > 1 + 1e-4):
            for _ in range(24):
                mid = (lo + hi) / 2
                r = conv(mid)
                if np.any(r < -1e-4) or np.any(r > 1 + 1e-4):
                    hi = mid
                else:
                    lo = mid
            rgb = conv(lo)
    return tuple(float(x) for x in np.clip(rgb, 0, 1))


def rel_luminance(rgb) -> float:
    r, g, b = _lin(rgb)
    return float(0.2126 * r + 0.7152 * g + 0.0722 * b)


def contrast_ratio(a, b) -> float:
    la, lb = rel_luminance(a), rel_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def wcag_level(r: float) -> str:
    if r >= 7:
        return "AAA"
    if r >= 4.5:
        return "AA"
    if r >= 3:
        return "AA large"
    return "fail"


def hue_name(rgb) -> str:
    L, C, H = to_oklch(rgb)
    if C < 0.03:
        if L > 0.93:
            return "white"
        if L < 0.22:
            return "black"
        return "gray"
    # brown = dark/desaturated orange-yellow
    if 30 <= H < 100 and L < 0.6 and C < 0.15:
        return "brown"
    bands = [(20, "pink"), (45, "red"), (70, "orange"), (110, "yellow"), (150, "lime"), (175, "green"),
             (215, "teal"), (240, "cyan"), (275, "blue"), (310, "violet"), (345, "purple"), (360, "pink")]
    for limit, name in bands:
        if H < limit:
            base = name
            break
    if L > 0.85:
        return f"pale-{base}"
    if L < 0.4:
        return f"dark-{base}"
    return base


# --------------------------------------------------------------------------
# Palette I/O
# --------------------------------------------------------------------------

def load_palette(spec: str) -> dict:
    if os.path.isfile(spec):
        with open(spec) as f:
            data = json.load(f)
        if isinstance(data, list):
            data = {"name": os.path.splitext(os.path.basename(spec))[0], "colors": data}
        cols = []
        for i, c in enumerate(data["colors"]):
            if isinstance(c, str):
                c = {"hex": c}
            cols.append({"name": c.get("name") or f"color-{i + 1}", "hex": rgb_to_hex(hex_to_rgb(c["hex"])), **{k: v for k, v in c.items() if k not in ("name", "hex")}})
        return {"name": data.get("name", "palette"), "colors": cols}
    hexes = [h for h in spec.replace(";", ",").replace(" ", ",").split(",") if h.strip()]
    cols = []
    seen = {}
    for h in hexes:
        rgb = hex_to_rgb(h)
        n = hue_name(rgb)
        seen[n] = seen.get(n, 0) + 1
        cols.append({"name": n if seen[n] == 1 else f"{n}-{seen[n]}", "hex": rgb_to_hex(rgb)})
    return {"name": "palette", "colors": cols}


def slug(s: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "color"


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------

def kmeans(X: np.ndarray, k: int, iters: int = 40, seed: int = 0):
    rng = np.random.default_rng(seed)
    # k-means++ init
    centers = [X[rng.integers(len(X))]]
    for _ in range(1, k):
        d = np.min(((X[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        p = d / d.sum() if d.sum() > 0 else None
        centers.append(X[rng.choice(len(X), p=p)])
    C = np.array(centers)
    for _ in range(iters):
        lab = ((X[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)
        newC = np.array([X[lab == i].mean(0) if np.any(lab == i) else C[i] for i in range(k)])
        if np.allclose(newC, C, atol=1e-5):
            break
        C = newC
    lab = ((X[:, None, :] - C[None]) ** 2).sum(-1).argmin(1)
    return C, lab


def cmd_extract(a):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(a.image)).convert("RGB")
    im.thumbnail((180, 180), Image.LANCZOS)
    px = np.asarray(im, dtype=float).reshape(-1, 3) / 255.0
    X = srgb_to_oklab(px)
    # over-cluster, then merge clusters that are perceptually too close
    C, lab = kmeans(X, min(len(X), a.n + 4), seed=a.seed)
    shares = np.bincount(lab, minlength=len(C)) / len(lab)
    clusters = [[C[i], shares[i]] for i in range(len(C)) if shares[i] > 0]
    merged = True
    while merged and len(clusters) > a.n:
        merged = False
        best = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = np.linalg.norm(clusters[i][0] - clusters[j][0])
                if best is None or d < best[0]:
                    best = (d, i, j)
        d, i, j = best
        wi, wj = clusters[i][1], clusters[j][1]
        clusters[i] = [(clusters[i][0] * wi + clusters[j][0] * wj) / (wi + wj), wi + wj]
        clusters.pop(j)
        merged = True
    clusters.sort(key=lambda c: -c[1])
    colors = []
    for c, share in clusters:
        rgb = tuple(float(x) for x in np.clip(oklab_to_srgb(c), 0, 1))
        colors.append({"hex": rgb_to_hex(rgb), "share": round(float(share), 4), "rgb": rgb})

    # roles: background = largest share; ink = best contrast vs bg; accent = most chromatic of the rest
    if a.roles and len(colors) >= 3:
        bg = colors[0]
        rest = colors[1:]
        ink = max(rest, key=lambda c: contrast_ratio(bg["rgb"], c["rgb"]))
        others = [c for c in rest if c is not ink]
        accent = max(others, key=lambda c: to_oklch(c["rgb"])[1])
        bg["role"], ink["role"], accent["role"] = "background", "ink", "accent"
    used = {}
    for c in colors:
        base = c.get("role") or hue_name(c["rgb"])
        used[base] = used.get(base, 0) + 1
        c["name"] = base if used[base] == 1 else f"{base}-{used[base]}"
    pal = {"name": a.name or slug(os.path.splitext(os.path.basename(a.image))[0]),
           "source": os.path.basename(a.image),
           "colors": [{k: v for k, v in c.items() if k != "rgb"} for c in colors]}
    _emit_json(pal, a.output)
    print_table(pal)
    if a.roles and len(colors) >= 3:
        bgc = next(c for c in colors if c.get("role") == "background")
        inkc = next(c for c in colors if c.get("role") == "ink")
        r = contrast_ratio(bgc["rgb"], inkc["rgb"])
        print(f"\nink on background: {r:.2f}:1 ({wcag_level(r)})", file=sys.stderr)
    if a.sheet:
        render_sheet(pal, a.sheet)
        print(f"sheet: {a.sheet}", file=sys.stderr)


def _emit_json(pal, out):
    txt = json.dumps(pal, indent=2, ensure_ascii=False)
    if out:
        with open(out, "w") as f:
            f.write(txt + "\n")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(txt)


def print_table(pal):
    print(f"\n{pal['name']}", file=sys.stderr)
    for c in pal["colors"]:
        L, C, H = to_oklch(hex_to_rgb(c["hex"]))
        share = f"{c['share'] * 100:5.1f}%" if "share" in c else ""
        print(f"  {c['hex']}  {c['name']:<16} L {L:.2f}  C {C:.3f}  H {H:5.1f}  {share}", file=sys.stderr)


# --------------------------------------------------------------------------
# contrast
# --------------------------------------------------------------------------

def cmd_contrast(a):
    pal = load_palette(a.palette)
    cols = pal["colors"]
    names = [c["name"] for c in cols]
    rgbs = [hex_to_rgb(c["hex"]) for c in cols]
    if a.json:
        out = []
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                r = contrast_ratio(rgbs[i], rgbs[j])
                out.append({"a": names[i], "b": names[j], "ratio": round(r, 2), "level": wcag_level(r)})
        print(json.dumps(out, indent=2))
        return
    w = max(len(n) for n in names) + 2
    print("WCAG 2 contrast (text on background). AAA ≥ 7, AA ≥ 4.5, AA large ≥ 3 (18pt+ or 14pt bold).\n")
    print(" " * w + "".join(f"{n[:10]:>12}" for n in names))
    for i, n in enumerate(names):
        row = f"{n:<{w}}"
        for j in range(len(names)):
            if i == j:
                row += f"{'—':>12}"
            else:
                r = contrast_ratio(rgbs[i], rgbs[j])
                tag = {"AAA": "AAA", "AA": "AA", "AA large": "AA+", "fail": "✗"}[wcag_level(r)]
                row += f"{r:>7.2f} {tag:<4}"
        print(row)
    pairs = sorted(((contrast_ratio(rgbs[i], rgbs[j]), names[i], names[j])
                    for i in range(len(cols)) for j in range(i + 1, len(cols))), reverse=True)
    good = [p for p in pairs if p[0] >= 4.5]
    print("\nPairs safe for body text: " + (", ".join(f"{x} / {y} ({r:.1f})" for r, x, y in good) if good else "none"))


# --------------------------------------------------------------------------
# scale
# --------------------------------------------------------------------------

STEPS = {50: 0.975, 100: 0.94, 200: 0.885, 300: 0.81, 400: 0.72, 500: 0.635,
         600: 0.555, 700: 0.475, 800: 0.395, 900: 0.32, 950: 0.245}


def cmd_scale(a):
    rgb = hex_to_rgb(a.color)
    L0, C0, H0 = to_oklch(rgb)
    name = a.name or hue_name(rgb)
    colors = []
    nearest = min(STEPS, key=lambda s: abs(STEPS[s] - L0))
    for step, L in STEPS.items():
        if step == nearest and a.keep:
            hexv = rgb_to_hex(rgb)
        else:
            # chroma tapers toward the extremes so tints don't go neon and shades don't go muddy
            taper = 1 - (abs(L - L0) / max(L0, 1 - L0)) ** 2 * 0.55
            out = from_oklch(L, C0 * max(0.15, taper), H0)
            hexv = rgb_to_hex(out)
        colors.append({"name": f"{name}-{step}", "hex": hexv, "step": step})
    pal = {"name": name, "base": rgb_to_hex(rgb), "base_step": nearest, "colors": colors}
    _emit_json(pal, a.output)
    print_table(pal)
    print(f"\nbase {rgb_to_hex(rgb)} sits at step {nearest}" + (" (kept exact)" if a.keep else ""), file=sys.stderr)
    if a.sheet:
        render_sheet(pal, a.sheet)


# --------------------------------------------------------------------------
# harmony
# --------------------------------------------------------------------------

HARMONIES = {
    "complementary": [0, 180],
    "analogous": [-30, 0, 30],
    "triadic": [0, 120, 240],
    "split": [0, 150, 210],
    "tetradic": [0, 90, 180, 270],
}


def cmd_harmony(a):
    rgb = hex_to_rgb(a.color)
    L, C, H = to_oklch(rgb)
    cols = []
    for off in HARMONIES[a.type]:
        out = rgb if off == 0 else from_oklch(L, C, (H + off) % 360)
        cols.append({"name": f"{hue_name(out)}", "hex": rgb_to_hex(out), "hue_offset": off})
    seen = {}
    for c in cols:
        seen[c["name"]] = seen.get(c["name"], 0) + 1
        if seen[c["name"]] > 1:
            c["name"] += f"-{seen[c['name']]}"
    pal = {"name": f"{a.type}-{rgb_to_hex(rgb)[1:].lower()}", "colors": cols}
    _emit_json(pal, a.output)
    print_table(pal)
    if a.sheet:
        render_sheet(pal, a.sheet)


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def to_css(pal, prefix=""):
    lines = [":root {"] + [f"  --{prefix}{slug(c['name'])}: {c['hex']};" for c in pal["colors"]] + ["}"]
    return "\n".join(lines) + "\n"


def to_scss(pal, prefix=""):
    return "\n".join(f"${prefix}{slug(c['name'])}: {c['hex']};" for c in pal["colors"]) + "\n"


def to_tailwind(pal, prefix=""):
    # Tailwind CSS v4 theme variables
    lines = ["@theme {"] + [f"  --color-{prefix}{slug(c['name'])}: {c['hex']};" for c in pal["colors"]] + ["}"]
    return "\n".join(lines) + "\n"


def to_tokens(pal, prefix=""):
    # W3C Design Tokens Community Group format (hex string values)
    group = {}
    for c in pal["colors"]:
        group[f"{prefix}{slug(c['name'])}"] = {"$type": "color", "$value": c["hex"].lower()}
    return json.dumps({slug(pal["name"]): group}, indent=2) + "\n"


def to_gpl(pal, prefix=""):
    lines = ["GIMP Palette", f"Name: {pal['name']}", "Columns: 0", "#"]
    for c in pal["colors"]:
        r, g, b = (round(x * 255) for x in hex_to_rgb(c["hex"]))
        lines.append(f"{r:3d} {g:3d} {b:3d}\t{prefix}{c['name']}")
    return "\n".join(lines) + "\n"


def _ase_str(s: str) -> bytes:
    data = (s + "\0").encode("utf-16-be")
    return struct.pack(">H", len(data) // 2) + data


def to_ase(pal, prefix="") -> bytes:
    """Adobe Swatch Exchange (Illustrator, InDesign, Photoshop, Affinity...)."""
    blocks = []
    gname = _ase_str(pal["name"])
    blocks.append(struct.pack(">HI", 0xC001, len(gname)) + gname)          # group start
    for c in pal["colors"]:
        r, g, b = hex_to_rgb(c["hex"])
        body = _ase_str(prefix + c["name"]) + b"RGB " + struct.pack(">fff", r, g, b) + struct.pack(">H", 0)  # 0 = global
        blocks.append(struct.pack(">HI", 0x0001, len(body)) + body)
    blocks.append(struct.pack(">HI", 0xC002, 0))                              # group end
    return b"ASEF" + struct.pack(">HHI", 1, 0, len(blocks)) + b"".join(blocks)


def to_svg(pal, prefix=""):
    cols = pal["colors"]
    sw, sh, gap = 160, 200, 0
    W = len(cols) * sw
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {sh}" width="{W}" height="{sh}" font-family="ui-monospace, Menlo, monospace" font-size="12">']
    for i, c in enumerate(cols):
        rgb = hex_to_rgb(c["hex"])
        fg = "#111111" if rel_luminance(rgb) > 0.4 else "#FFFFFF"
        x = i * (sw + gap)
        parts.append(f'<rect x="{x}" y="0" width="{sw}" height="{sh}" fill="{c["hex"]}"/>')
        parts.append(f'<text x="{x + 12}" y="{sh - 30}" fill="{fg}">{c["name"]}</text>')
        parts.append(f'<text x="{x + 12}" y="{sh - 14}" fill="{fg}">{c["hex"]}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_sheet(pal, out):
    from PIL import Image, ImageDraw, ImageFont
    cols = pal["colors"]
    has_share = all("share" in c for c in cols)
    W, H = 1600, 900
    im = Image.new("RGB", (W, H), "#F4F3F0")
    d = ImageDraw.Draw(im)

    def font(sz):
        for f in ("DejaVuSansMono.ttf", "Menlo.ttc", "Courier New.ttf"):
            try:
                return ImageFont.truetype(f, sz)
            except OSError:
                continue
        return ImageFont.load_default()
    f_s = font(20)
    x = 0
    total = sum(c.get("share", 1) for c in cols) if has_share else len(cols)
    for c in cols:
        w = round(W * (c.get("share", 1) / total)) if has_share else W // len(cols)
        if c is cols[-1]:
            w = W - x
        rgb = hex_to_rgb(c["hex"])
        d.rectangle([x, 0, x + w, H], fill=c["hex"])
        fg = "#111111" if rel_luminance(rgb) > 0.4 else "#FFFFFF"
        if w > 90:
            d.text((x + 18, H - 92), c["name"], fill=fg, font=f_s)
            d.text((x + 18, H - 64), c["hex"], fill=fg, font=f_s)
            if has_share:
                d.text((x + 18, H - 36), f"{c['share'] * 100:.0f}%", fill=fg, font=f_s)
        x += w
    im.save(out)


EXPORTERS = {"css": (to_css, ".css"), "scss": (to_scss, ".scss"), "tailwind": (to_tailwind, ".css"),
             "tokens": (to_tokens, ".tokens.json"), "json": (None, ".json"), "gpl": (to_gpl, ".gpl"),
             "ase": (to_ase, ".ase"), "svg": (to_svg, ".svg"), "png": (None, ".png")}


def cmd_export(a):
    pal = load_palette(a.palette)
    fmt = a.to
    fn, ext = EXPORTERS[fmt]
    out = a.output
    if fmt == "png":
        render_sheet(pal, out or slug(pal["name"]) + ext)
        print(out or slug(pal["name"]) + ext)
        return
    if fmt == "json":
        _emit_json(pal, out)
        return
    data = fn(pal, a.prefix)
    if isinstance(data, bytes):
        out = out or slug(pal["name"]) + ext
        with open(out, "wb") as f:
            f.write(data)
        print(out)
    elif out:
        with open(out, "w") as f:
            f.write(data)
        print(out)
    else:
        sys.stdout.write(data)


def main(argv=None):
    p = argparse.ArgumentParser(description="Build, check and export color palettes.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("extract", help="extract a palette from an image")
    e.add_argument("image")
    e.add_argument("-n", type=int, default=6, help="number of colors (default 6)")
    e.add_argument("-o", "--output", help="palette JSON to write (default: stdout)")
    e.add_argument("--sheet", help="also render a swatch sheet PNG (widths = share of image)")
    e.add_argument("--name")
    e.add_argument("--no-roles", dest="roles", action="store_false", help="don't guess background/ink/accent")
    e.add_argument("--seed", type=int, default=0)
    e.set_defaults(func=cmd_extract)

    c = sub.add_parser("contrast", help="WCAG contrast matrix")
    c.add_argument("palette", help="palette JSON or comma-separated hex list")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_contrast)

    s = sub.add_parser("scale", help="tints/shades 50..950 of one color")
    s.add_argument("color")
    s.add_argument("--name")
    s.add_argument("--keep", action="store_true", help="keep the exact input color at its nearest step")
    s.add_argument("-o", "--output")
    s.add_argument("--sheet")
    s.set_defaults(func=cmd_scale)

    h = sub.add_parser("harmony", help="color harmonies in OKLCH")
    h.add_argument("color")
    h.add_argument("--type", choices=list(HARMONIES), default="complementary")
    h.add_argument("-o", "--output")
    h.add_argument("--sheet")
    h.set_defaults(func=cmd_harmony)

    x = sub.add_parser("export", help="export to design-tool formats")
    x.add_argument("palette", help="palette JSON or comma-separated hex list")
    x.add_argument("--to", required=True, choices=list(EXPORTERS))
    x.add_argument("-o", "--output")
    x.add_argument("--prefix", default="", help="prefix for variable / swatch names")
    x.set_defaults(func=cmd_export)

    a = p.parse_args(argv)
    a.func(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
