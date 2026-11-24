#!/usr/bin/env python3
"""
dither.py — turn any image into a dithered / halftoned bitmap.

Error diffusion (Floyd–Steinberg, Atkinson, Jarvis–Judice–Ninke, Stucki,
Burkes, Sierra, Sierra Lite), ordered (Bayer 2/4/8/16), random, threshold
and AM halftone dots. Grayscale or color, any palette, PNG or SVG output.

Requirements: Python 3.9+, Pillow, NumPy.

Examples
  python3 dither.py photo.jpg -o out.png --method atkinson --width 480 --scale 4
  python3 dither.py photo.jpg -o out.png --method bayer4 --palette "#1F2BD1,#F3F2EE"
  python3 dither.py photo.jpg -o out.png --method floyd-steinberg --color --palette riso
  python3 dither.py photo.jpg -o out.png --method halftone --cell 10 --angle 45 --width 1800
  python3 dither.py photo.jpg -o out.svg --method atkinson --width 200
  python3 dither.py photo.jpg --compare -o sheet.png --width 320
  python3 dither.py --list
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# --------------------------------------------------------------------------
# Kernels: list of (dx, dy, weight), divisor
# --------------------------------------------------------------------------
DIFFUSION = {
    "floyd-steinberg": ([(1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)], 16),
    "atkinson": ([(1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1)], 8),
    "jjn": ([(1, 0, 7), (2, 0, 5),
             (-2, 1, 3), (-1, 1, 5), (0, 1, 7), (1, 1, 5), (2, 1, 3),
             (-2, 2, 1), (-1, 2, 3), (0, 2, 5), (1, 2, 3), (2, 2, 1)], 48),
    "stucki": ([(1, 0, 8), (2, 0, 4),
                (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2),
                (-2, 2, 1), (-1, 2, 2), (0, 2, 4), (1, 2, 2), (2, 2, 1)], 42),
    "burkes": ([(1, 0, 8), (2, 0, 4),
                (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2)], 32),
    "sierra": ([(1, 0, 5), (2, 0, 3),
                (-2, 1, 2), (-1, 1, 4), (0, 1, 5), (1, 1, 4), (2, 1, 2),
                (-1, 2, 2), (0, 2, 3), (1, 2, 2)], 32),
    "sierra-lite": ([(1, 0, 2), (-1, 1, 1), (0, 1, 1)], 4),
}
ORDERED = {"bayer2": 2, "bayer4": 4, "bayer8": 8, "bayer16": 16}
OTHER = ["threshold", "random", "halftone"]
METHODS = list(DIFFUSION) + list(ORDERED) + OTHER

DESCRIPTIONS = {
    "floyd-steinberg": "classic error diffusion, smooth and organic",
    "atkinson": "classic Mac look: crisp, contrasty, loses some shadow/highlight detail",
    "jjn": "Jarvis-Judice-Ninke: wide kernel, very smooth, slower",
    "stucki": "wide kernel, smooth and sharp",
    "burkes": "faster cousin of Stucki",
    "sierra": "smooth, close to JJN",
    "sierra-lite": "tiny kernel, fast, a bit noisy",
    "bayer2": "ordered 2x2: coarse cross-hatch",
    "bayer4": "ordered 4x4: the retro grid / pixel-art pattern",
    "bayer8": "ordered 8x8: finer ordered pattern",
    "bayer16": "ordered 16x16: finest ordered pattern",
    "threshold": "hard cut, no dithering (posterize)",
    "random": "white-noise dithering, grainy",
    "halftone": "AM halftone dots (print / risograph / screen-print look)",
}

PRESETS = {
    "bw": ["#000000", "#ffffff"],
    "gray4": ["#000000", "#555555", "#aaaaaa", "#ffffff"],
    "gray8": ["#000000", "#242424", "#494949", "#6d6d6d", "#929292", "#b6b6b6", "#dbdbdb", "#ffffff"],
    "rgb8": ["#000000", "#ff0000", "#00ff00", "#0000ff", "#00ffff", "#ff00ff", "#ffff00", "#ffffff"],
    # Approximations of common risograph inks on white paper.
    "riso": ["#ffffff", "#000000", "#ff48b0", "#0078bf", "#ffe800"],
    "newsprint": ["#1a1a1a", "#efe9dc"],
    "blueprint": ["#1f3a93", "#e8eef7"],
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def parse_hex(h: str) -> tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"invalid hex color: #{h}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def parse_palette(spec: str | None, levels: int) -> list[tuple[int, int, int]]:
    if not spec:
        if levels < 2:
            raise ValueError("--levels must be >= 2")
        return [(round(255 * i / (levels - 1)),) * 3 for i in range(levels)]
    if spec in PRESETS:
        return [parse_hex(c) for c in PRESETS[spec]]
    cols = [parse_hex(c) for c in spec.replace(";", ",").split(",") if c.strip()]
    if len(cols) < 2:
        raise ValueError("a palette needs at least 2 colors")
    return cols


def luma(rgb) -> float:
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def load_image(path: str) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    return im.convert("RGB")


def resize(im: Image.Image, width: int | None) -> Image.Image:
    if not width or width == im.width:
        return im
    h = max(1, round(im.height * width / im.width))
    return im.resize((width, h), Image.LANCZOS)


def crop_aspect(im: Image.Image, spec: str) -> Image.Image:
    aw, ah = (float(x) for x in spec.replace("/", ":").split(":"))
    target = aw / ah
    w, h = im.size
    if w / h > target:
        nw = round(h * target)
        x0 = (w - nw) // 2
        return im.crop((x0, 0, x0 + nw, h))
    nh = round(w / target)
    y0 = (h - nh) // 2
    return im.crop((0, y0, w, y0 + nh))


def adjust(arr: np.ndarray, brightness: float, contrast: float, gamma: float, invert: bool) -> np.ndarray:
    """arr: float array in [0,1]."""
    if gamma != 1.0:
        arr = np.power(np.clip(arr, 0, 1), 1.0 / gamma)
    if brightness:
        arr = arr + brightness
    if contrast != 1.0:
        arr = (arr - 0.5) * contrast + 0.5
    if invert:
        arr = 1.0 - arr
    return np.clip(arr, 0.0, 1.0)


def bayer_matrix(n: int) -> np.ndarray:
    m = np.array([[0, 2], [3, 1]], dtype=float)
    while m.shape[0] < n:
        k = m.shape[0]
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return m[:n, :n]


# --------------------------------------------------------------------------
# Grayscale dithering -> index map into `levels_sorted`
# --------------------------------------------------------------------------
def gray_dither(g: np.ndarray, targets: list[float], method: str, serpentine: bool, seed: int | None) -> np.ndarray:
    """g: HxW float [0,1]. targets: sorted luminances of palette entries.
    Returns HxW int array of indices into targets."""
    h, w = g.shape
    t = np.array(targets)

    def nearest(vals: np.ndarray) -> np.ndarray:
        return np.abs(vals[..., None] - t).argmin(-1)

    if method == "threshold":
        return nearest(g)

    if method == "random":
        rng = np.random.default_rng(seed)
        spread = 1.0 / max(1, len(t) - 1)
        return nearest(np.clip(g + (rng.random(g.shape) - 0.5) * spread, 0, 1))

    if method in ORDERED:
        n = ORDERED[method]
        m = (bayer_matrix(n) + 0.5) / (n * n) - 0.5
        tile = np.tile(m, (h // n + 1, w // n + 1))[:h, :w]
        # map between neighbouring levels: offset scaled by local level gap
        spread = 1.0 / max(1, len(t) - 1)
        return nearest(np.clip(g + tile * spread, 0, 1))

    kernel, div = DIFFUSION[method]
    kernel = [(dx, dy, wt / div) for dx, dy, wt in kernel]
    buf = [list(map(float, row)) for row in g]
    out = np.zeros((h, w), dtype=np.int32)
    tl = list(t)
    for y in range(h):
        row = buf[y]
        rev = serpentine and (y % 2 == 1)
        xs = range(w - 1, -1, -1) if rev else range(w)
        for x in xs:
            old = row[x]
            # nearest target
            best, bi = 9.0, 0
            for i, tv in enumerate(tl):
                d = abs(old - tv)
                if d < best:
                    best, bi = d, i
            out[y, x] = bi
            err = old - tl[bi]
            if err == 0.0:
                continue
            for dx, dy, wt in kernel:
                xx = x - dx if rev else x + dx
                yy = y + dy
                if 0 <= xx < w and yy < h:
                    buf[yy][xx] += err * wt
    return out


# --------------------------------------------------------------------------
# Color dithering -> index map into palette
# --------------------------------------------------------------------------
def color_dither(rgb: np.ndarray, pal: list[tuple[int, int, int]], method: str, serpentine: bool, seed: int | None) -> np.ndarray:
    h, w, _ = rgb.shape
    P = np.array(pal, dtype=float) / 255.0

    def nearest(img: np.ndarray) -> np.ndarray:
        d = ((img[..., None, :] - P[None, None, :, :]) ** 2).sum(-1)
        return d.argmin(-1)

    if method == "threshold":
        return nearest(rgb)
    if method == "random":
        rng = np.random.default_rng(seed)
        return nearest(np.clip(rgb + (rng.random(rgb.shape[:2])[..., None] - 0.5) * 0.5, 0, 1))
    if method in ORDERED:
        n = ORDERED[method]
        m = (bayer_matrix(n) + 0.5) / (n * n) - 0.5
        tile = np.tile(m, (h // n + 1, w // n + 1))[:h, :w]
        spread = 1.0 / max(1, round(len(pal) ** (1 / 3)))
        return nearest(np.clip(rgb + tile[..., None] * spread, 0, 1))

    kernel, div = DIFFUSION[method]
    kernel = [(dx, dy, wt / div) for dx, dy, wt in kernel]
    buf = rgb.astype(float).copy()
    out = np.zeros((h, w), dtype=np.int32)
    pl = [tuple(c) for c in P]
    for y in range(h):
        rev = serpentine and (y % 2 == 1)
        xs = range(w - 1, -1, -1) if rev else range(w)
        row = buf[y]
        for x in xs:
            r, g, b = row[x]
            best, bi = 99.0, 0
            for i, (pr, pg, pb) in enumerate(pl):
                d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if d < best:
                    best, bi = d, i
            out[y, x] = bi
            pr, pg, pb = pl[bi]
            er, eg, eb = r - pr, g - pg, b - pb
            for dx, dy, wt in kernel:
                xx = x - dx if rev else x + dx
                yy = y + dy
                if 0 <= xx < w and yy < h:
                    buf[yy, xx, 0] += er * wt
                    buf[yy, xx, 1] += eg * wt
                    buf[yy, xx, 2] += eb * wt
    return out


# --------------------------------------------------------------------------
# AM halftone (grayscale, two colors: ink + paper)
# --------------------------------------------------------------------------
def halftone(g: np.ndarray, cell: float, angle_deg: float, shape: str) -> np.ndarray:
    """g: HxW float [0,1] (1 = white). Returns HxW bool, True = ink."""
    h, w = g.shape
    dark = 1.0 - g
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    u = xx * ca + yy * sa
    v = -xx * sa + yy * ca
    cu = (np.floor(u / cell) + 0.5) * cell
    cv = (np.floor(v / cell) + 0.5) * cell
    # sample darkness at the cell centre (back to image space)
    sx = np.clip(np.rint(cu * ca - cv * sa), 0, w - 1).astype(int)
    sy = np.clip(np.rint(cu * sa + cv * ca), 0, h - 1).astype(int)
    d = dark[sy, sx]
    du, dv = u - cu, v - cv
    if shape == "line":
        # line screen: band thickness proportional to darkness
        return np.abs(dv) <= d * cell / 2.0
    if shape == "square":
        r = cell * np.sqrt(d) / 2.0
        return np.maximum(np.abs(du), np.abs(dv)) <= r
    # round dot; area = d * cell^2
    r = cell * np.sqrt(d / math.pi)
    return du * du + dv * dv <= r * r


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def to_image(idx: np.ndarray, pal: list[tuple[int, int, int]], scale: int) -> Image.Image:
    lut = np.array(pal, dtype=np.uint8)
    im = Image.fromarray(lut[idx], "RGB")
    if scale > 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    return im


def to_svg(idx: np.ndarray, pal: list[tuple[int, int, int]], scale: int) -> str:
    h, w = idx.shape
    counts = np.bincount(idx.ravel(), minlength=len(pal))
    bg = int(counts.argmax())
    hexes = ["#%02x%02x%02x" % c for c in pal]
    groups: dict[int, list[str]] = {}
    n_rects = 0
    for y in range(h):
        row = idx[y]
        x = 0
        while x < w:
            c = int(row[x])
            x0 = x
            while x < w and row[x] == c:
                x += 1
            if c != bg:
                groups.setdefault(c, []).append(f'<rect x="{x0}" y="{y}" width="{x - x0}" height="1"/>')
                n_rects += 1
    if n_rects > 250_000:
        print(f"warning: SVG has {n_rects} rectangles; consider a smaller --width", file=sys.stderr)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w * scale}" height="{h * scale}" shape-rendering="crispEdges">',
        f'<rect width="{w}" height="{h}" fill="{hexes[bg]}"/>',
    ]
    for c, rects in groups.items():
        parts.append(f'<g fill="{hexes[c]}">' + "".join(rects) + "</g>")
    parts.append("</svg>")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------
def run(im: Image.Image, method: str, pal, *, color: bool, scale: int, brightness: float, contrast: float,
        gamma: float, invert: bool, serpentine: bool, seed, cell: float, angle: float, dot: str):
    arr = np.asarray(im, dtype=float) / 255.0
    arr = adjust(arr, brightness, contrast, gamma, invert)

    if method == "halftone":
        # halftone works at output resolution: upscale first, then screen
        if scale > 1:
            big = Image.fromarray((arr * 255).astype(np.uint8)).resize(
                (im.width * scale, im.height * scale), Image.BICUBIC)
            arr = np.asarray(big, dtype=float) / 255.0
        g = arr @ np.array([0.2126, 0.7152, 0.0722])
        order = sorted(range(len(pal)), key=lambda i: luma(pal[i]))
        ink, paper = order[0], order[-1]
        mask = halftone(g, cell, angle, dot)
        idx = np.where(mask, ink, paper)
        return idx, 1

    if color:
        idx = color_dither(arr, pal, method, serpentine, seed)
    else:
        g = arr @ np.array([0.2126, 0.7152, 0.0722])
        order = sorted(range(len(pal)), key=lambda i: luma(pal[i]))
        targets = [luma(pal[i]) for i in order]
        # stretch so the darkest/lightest palette colors map to full black/white input
        lo, hi = targets[0], targets[-1]
        if hi - lo > 1e-6:
            targets_n = [(t - lo) / (hi - lo) for t in targets]
        else:
            targets_n = targets
        sub = gray_dither(g, targets_n, method, serpentine, seed)
        idx = np.array(order)[sub]
    return idx, scale


def contact_sheet(im: Image.Image, pal, args, out: str):
    tiles = []
    for m in METHODS:
        idx, sc = run(im, m, pal, color=args.color, scale=1, brightness=args.brightness, contrast=args.contrast,
                      gamma=args.gamma, invert=args.invert, serpentine=args.serpentine, seed=args.seed,
                      cell=max(4.0, im.width / 60), angle=args.angle, dot=args.dot)
        tiles.append((m, to_image(idx, pal, 1)))
        print(f"  {m:16s} done", file=sys.stderr)
    cols = 4
    tw, th = tiles[0][1].size
    s = max(1, args.scale)
    pad, label_h = 16, 28
    rows = math.ceil(len(tiles) / cols)
    W = cols * (tw * s) + (cols + 1) * pad
    H = rows * (th * s + label_h) + (rows + 1) * pad
    sheet = Image.new("RGB", (W, H), (246, 246, 244))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    for i, (name, t) in enumerate(tiles):
        r, c = divmod(i, cols)
        x = pad + c * (tw * s + pad)
        y = pad + r * (th * s + label_h + pad)
        sheet.paste(t.resize((tw * s, th * s), Image.NEAREST), (x, y))
        draw.text((x, y + th * s + 6), name, fill=(17, 17, 17), font=font)
    sheet.save(out)


def main(argv=None):
    p = argparse.ArgumentParser(description="Dither / halftone an image.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("input", nargs="?", help="input image (jpg, png, webp, tiff...)")
    p.add_argument("-o", "--output", help="output .png or .svg (default: <input>_<method>.png)")
    p.add_argument("-m", "--method", default="floyd-steinberg", choices=METHODS)
    p.add_argument("-w", "--width", type=int, help="working width in dots (the image is resized first)")
    p.add_argument("--aspect", help="center-crop to an aspect ratio first, e.g. 3:4, 1:1, 16:9")
    p.add_argument("-s", "--scale", type=int, default=1, help="nearest-neighbour upscale of the result (crisp big pixels)")
    p.add_argument("-p", "--palette", help=f"preset ({', '.join(PRESETS)}) or comma-separated hex colors")
    p.add_argument("-l", "--levels", type=int, default=2, help="gray levels when no palette is given (default 2)")
    p.add_argument("--color", action="store_true", help="dither in color against the palette (needs --palette)")
    p.add_argument("--brightness", type=float, default=0.0, help="-1..1, added before dithering")
    p.add_argument("--contrast", type=float, default=1.0, help="multiplier around mid-gray (1 = unchanged)")
    p.add_argument("--gamma", type=float, default=1.0, help=">1 lightens midtones, <1 darkens")
    p.add_argument("--invert", action="store_true")
    p.add_argument("--serpentine", action="store_true", help="alternate scan direction (fewer directional artifacts)")
    p.add_argument("--sharpen", action="store_true", help="unsharp mask before dithering (keeps edges readable)")
    p.add_argument("--seed", type=int, default=None, help="seed for the random method")
    p.add_argument("--cell", type=float, default=8.0, help="halftone cell size in output pixels")
    p.add_argument("--angle", type=float, default=45.0, help="halftone screen angle in degrees")
    p.add_argument("--dot", choices=["round", "square", "line"], default="round", help="halftone dot shape")
    p.add_argument("--compare", action="store_true", help="render every method into one contact sheet")
    p.add_argument("--list", action="store_true", help="list methods and palette presets")
    args = p.parse_args(argv)

    if args.list:
        print("Methods:")
        for m in METHODS:
            print(f"  {m:16s} {DESCRIPTIONS[m]}")
        print("\nPalette presets:")
        for k, v in PRESETS.items():
            print(f"  {k:10s} {' '.join(v)}")
        return 0
    if not args.input:
        p.error("an input image is required")
    if args.color and not args.palette:
        p.error("--color needs a --palette with at least 2 colors")

    pal = parse_palette(args.palette, args.levels)
    im = load_image(args.input)
    if args.aspect:
        im = crop_aspect(im, args.aspect)
    im = resize(im, args.width)
    if args.sharpen:
        im = im.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=2))

    base = os.path.splitext(os.path.basename(args.input))[0]
    if args.compare:
        out = args.output or f"{base}_compare.png"
        contact_sheet(im, pal, args, out)
        print(out)
        return 0

    out = args.output or f"{base}_{args.method}.png"
    idx, sc = run(im, args.method, pal, color=args.color, scale=args.scale, brightness=args.brightness,
                  contrast=args.contrast, gamma=args.gamma, invert=args.invert, serpentine=args.serpentine,
                  seed=args.seed, cell=args.cell, angle=args.angle, dot=args.dot)
    if out.lower().endswith(".svg"):
        with open(out, "w") as f:
            f.write(to_svg(idx, pal, sc if args.method != "halftone" else 1))
    else:
        to_image(idx, pal, sc).save(out)
    h, w = idx.shape
    used = len(np.unique(idx))
    print(f"{out}  ({w}x{h} dots, x{sc} -> {w * sc}x{h * sc}px, {used} colors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
