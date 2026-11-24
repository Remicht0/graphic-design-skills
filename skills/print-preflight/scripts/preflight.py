#!/usr/bin/env python3
"""
preflight.py — check a PDF before sending it to print.

Checks
  pages        trim size (named format), bleed per side, mixed page sizes
  images       effective resolution (ppi) at placed size, color space
  fonts        embedded or not, Type 3, subset
  color        RGB vs CMYK vs spot (Pantone…) in vectors and images,
               total ink coverage (TAC) of CMYK vectors and CMYK images,
               output intent (PDF/X)
  strokes      hairlines thinner than 0.25 pt
  other        transparency, annotations / form fields, encryption, layers

Exit code 1 when at least one check FAILS (useful in scripts / CI).

Requirements: Python 3.9+, pikepdf (pip install pikepdf). Pillow + NumPy
optional, for ink coverage of CMYK images.

Examples
  python3 preflight.py flyer.pdf
  python3 preflight.py flyer.pdf --bleed 5 --min-ppi 300 -o report.md --json report.json
  python3 preflight.py slides.pdf --target digital
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field

import pikepdf
from pikepdf import Name, Operator

PT_PER_MM = 72 / 25.4

FORMATS = {  # width x height in mm (portrait)
    "A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420), "A4": (210, 297),
    "A5": (148, 210), "A6": (105, 148), "A7": (74, 105), "B5": (176, 250), "B4": (250, 353),
    "SRA3": (320, 450), "DL": (99, 210), "Letter": (215.9, 279.4), "Legal": (215.9, 355.6),
    "Tabloid": (279.4, 431.8), "Business card EU": (55, 85), "Business card US": (50.8, 88.9),
    "Business card": (50, 90), "Square 210": (210, 210), "Square 148": (148, 148),
    "Instagram 1080 (screen)": (381, 381), "16:9 slide": (254, 142.875), "40x60 poster": (400, 600),
    "50x70 poster": (500, 700), "60x80 poster": (600, 800), "70x100 poster": (700, 1000),
}


@dataclass
class Finding:
    level: str  # PASS / WARN / FAIL / INFO
    check: str
    message: str
    pages: list = field(default_factory=list)


class Report:
    def __init__(self):
        self.items: list[Finding] = []

    def add(self, level, check, message, pages=None):
        self.items.append(Finding(level, check, message, sorted(set(pages or []))))

    def counts(self):
        c = {"FAIL": 0, "WARN": 0, "PASS": 0, "INFO": 0}
        for i in self.items:
            c[i.level] += 1
        return c


def fmt_pages(pages, total):
    if not pages:
        return ""
    if len(pages) == total and total > 1:
        return " (all pages)"
    # compress ranges
    out, start, prev = [], pages[0], pages[0]
    for p in pages[1:] + [None]:
        if p is not None and p == prev + 1:
            prev = p
            continue
        out.append(f"{start}" if start == prev else f"{start}–{prev}")
        if p is not None:
            start = prev = p
    return f" (p. {', '.join(out)})" if len(out) <= 8 else f" ({len(pages)} pages)"


def box(page, name):
    b = page.obj.get(name)
    if b is None:
        return None
    return [float(x) for x in b]


def mm(v):
    return v / PT_PER_MM


def name_format(w_mm, h_mm, tol=1.5):
    a, b = sorted((w_mm, h_mm))
    for name, (fw, fh) in FORMATS.items():
        x, y = sorted((fw, fh))
        if abs(a - x) <= tol and abs(b - y) <= tol:
            orient = "" if abs(w_mm - h_mm) < tol else (" portrait" if h_mm > w_mm else " landscape")
            return name + orient
    return None


# --------------------------------------------------------------------------
# Content stream walker
# --------------------------------------------------------------------------

def mat(a, b, c, d, e, f):
    return [[a, b, 0.0], [c, d, 0.0], [e, f, 1.0]]


def mul(m, n):
    return [[sum(m[i][k] * n[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


IDENT = mat(1, 0, 0, 1, 0, 0)


def cs_kind(cs, resources):
    """Classify a color space object -> ('rgb'|'cmyk'|'gray'|'spot'|'lab'|'indexed:<base>'|'pattern'|'other', spot names)."""
    try:
        if isinstance(cs, Name):
            n = str(cs)
            if n in ("/DeviceRGB", "/CalRGB", "/RGB"):
                return "rgb", []
            if n in ("/DeviceCMYK", "/CMYK"):
                return "cmyk", []
            if n in ("/DeviceGray", "/CalGray", "/G"):
                return "gray", []
            if n == "/Pattern":
                return "pattern", []
            # named resource
            if resources is not None and "/ColorSpace" in resources and n in resources.ColorSpace:
                return cs_kind(resources.ColorSpace[n], resources)
            return "other", []
        if isinstance(cs, pikepdf.Array) and len(cs) > 0:
            fam = str(cs[0])
            if fam == "/ICCBased":
                n = int(cs[1].get("/N", 3))
                return {1: "gray", 3: "rgb", 4: "cmyk"}.get(n, "other"), []
            if fam in ("/CalRGB",):
                return "rgb", []
            if fam in ("/CalGray",):
                return "gray", []
            if fam == "/Lab":
                return "lab", []
            if fam == "/Separation":
                nm = str(cs[1]).lstrip("/")
                if nm in ("All", "None"):
                    return "registration" if nm == "All" else "other", []
                if nm in ("Cyan", "Magenta", "Yellow", "Black"):
                    return "cmyk", []
                return "spot", [nm]
            if fam == "/DeviceN":
                names = [str(x).lstrip("/") for x in cs[1]]
                spots = [x for x in names if x not in ("Cyan", "Magenta", "Yellow", "Black", "None")]
                return ("spot" if spots else "cmyk"), spots
            if fam in ("/Indexed", "/I"):
                base, spots = cs_kind(cs[1], resources)
                return base, spots
            if fam == "/Pattern":
                return "pattern", []
    except Exception:
        pass
    return "other", []


class Walker:
    def __init__(self, pdf, opts):
        self.pdf = pdf
        self.opts = opts
        self.images = {}        # objgen -> dict
        self.color_use = {}     # kind -> set(pages), vector art and text only
        self.image_color = {}   # kind -> set(pages), raster images
        self.spots = {}         # name -> set(pages)
        self.hairlines = {}     # page -> count
        self.tac_vec = []       # (tac, page)
        self.transparency = set()
        self.fonts = {}         # key -> dict
        self.visited_forms = set()

    def note_color(self, kind, page, spots=(), image=False):
        (self.image_color if image else self.color_use).setdefault(kind, set()).add(page)
        for s in spots:
            self.spots.setdefault(s, set()).add(page)

    def use_font(self, resources, fname, page):
        """Record a font that actually draws text (fonts merely listed in resources are ignored)."""
        if resources is None or fname is None or "/Font" not in resources or fname not in resources.Font:
            return
        font = resources.Font[fname]
        if True:
            try:
                key = font.objgen if font.is_indirect else (page, str(fname))
                sub = str(font.get("/Subtype", ""))
                base = str(font.get("/BaseFont", fname)).lstrip("/")
                desc_font = font
                if sub == "/Type0" and "/DescendantFonts" in font:
                    desc_font = font.DescendantFonts[0]
                fd = desc_font.get("/FontDescriptor")
                if sub == "/Type3":
                    embedded = True
                else:
                    embedded = fd is not None and any(k in fd for k in ("/FontFile", "/FontFile2", "/FontFile3"))
                entry = self.fonts.setdefault(key, {"name": base.split("+", 1)[-1], "subset": "+" in base[:7],
                                                    "type": sub.lstrip("/"), "embedded": embedded, "pages": set()})
                entry["pages"].add(page)
            except Exception:
                pass

    def walk(self, stream_owner, resources, page, ctm):
        try:
            instrs = pikepdf.parse_content_stream(stream_owner)
        except Exception:
            return
        stack = []
        font = None
        lw = 1.0
        fill_cs = stroke_cs = "gray"
        fill_spots = stroke_spots = []
        for operands, op in instrs:
            o = str(op)
            try:
                if o == "q":
                    stack.append((ctm, lw, fill_cs, stroke_cs, fill_spots, stroke_spots, font))
                elif o == "Q":
                    if stack:
                        ctm, lw, fill_cs, stroke_cs, fill_spots, stroke_spots, font = stack.pop()
                elif o == "cm":
                    ctm = mul(mat(*[float(x) for x in operands]), ctm)
                elif o == "w":
                    lw = float(operands[0])
                elif o in ("S", "s", "B", "B*", "b", "b*"):
                    sx = math.hypot(ctm[0][0], ctm[0][1])
                    sy = math.hypot(ctm[1][0], ctm[1][1])
                    eff = lw * (sx + sy) / 2
                    if eff < self.opts.hairline:
                        self.hairlines[page] = self.hairlines.get(page, 0) + 1
                    self.note_color(stroke_cs, page, stroke_spots)
                    if o in ("B", "B*", "b", "b*"):
                        self.note_color(fill_cs, page, fill_spots)
                elif o in ("f", "F", "f*"):
                    self.note_color(fill_cs, page, fill_spots)
                elif o == "Tf":
                    font = operands[0]
                elif o in ("Tj", "TJ", "'", '"'):
                    self.use_font(resources, font, page)
                    self.note_color(fill_cs, page, fill_spots)
                elif o == "rg":
                    fill_cs, fill_spots = "rgb", []
                elif o == "RG":
                    stroke_cs, stroke_spots = "rgb", []
                elif o in ("g",):
                    fill_cs, fill_spots = "gray", []
                elif o in ("G",):
                    stroke_cs, stroke_spots = "gray", []
                elif o in ("k", "K"):
                    vals = [float(x) for x in operands]
                    tac = sum(vals) * 100
                    self.tac_vec.append((tac, page))
                    if o == "k":
                        fill_cs, fill_spots = "cmyk", []
                    else:
                        stroke_cs, stroke_spots = "cmyk", []
                elif o in ("cs", "CS"):
                    kind, spots = cs_kind(operands[0], resources)
                    if o == "cs":
                        fill_cs, fill_spots = kind, spots
                    else:
                        stroke_cs, stroke_spots = kind, spots
                elif o in ("sc", "scn", "SC", "SCN"):
                    cs_now = fill_cs if o in ("sc", "scn") else stroke_cs
                    nums = []
                    for x in operands:
                        if isinstance(x, Name):
                            continue
                        try:
                            nums.append(float(x))
                        except (TypeError, ValueError):
                            pass
                    if cs_now == "cmyk" and len(nums) == 4:
                        self.tac_vec.append((sum(nums) * 100, page))
                elif o == "gs":
                    gs = resources.ExtGState[operands[0]]
                    if "/LW" in gs:
                        lw = float(gs.LW)
                    if float(gs.get("/ca", 1)) < 1 or float(gs.get("/CA", 1)) < 1:
                        self.transparency.add(page)
                    sm = gs.get("/SMask")
                    if sm is not None and str(sm) != "/None":
                        self.transparency.add(page)
                    bm = gs.get("/BM")
                    if bm is not None and str(bm) not in ("/Normal", "/Compatible"):
                        self.transparency.add(page)
                elif o == "Do":
                    xo = resources.XObject[operands[0]]
                    st = str(xo.get("/Subtype"))
                    if st == "/Image":
                        self.place_image(xo, ctm, page, resources)
                    elif st == "/Form":
                        m = xo.get("/Matrix")
                        fctm = mul(mat(*[float(x) for x in m]), ctm) if m is not None else ctm
                        fres = xo.get("/Resources") or resources
                        if "/Group" in xo and str(xo.Group.get("/S", "")) == "/Transparency":
                            self.transparency.add(page)
                        key = (xo.objgen, page, tuple(map(tuple, fctm)))
                        if key not in self.visited_forms:
                            self.visited_forms.add(key)
                            self.walk(xo, fres, page, fctm)
                elif o == "INLINE IMAGE":
                    iim = operands[0]
                    try:
                        pimg = iim
                        w = int(pimg.width)
                        h = int(pimg.height)
                        self.record_image(("inline", page, len(self.images)), w, h, ctm, page, "inline image",
                                          self.inline_cs(pimg), [], None)
                    except Exception:
                        pass
            except Exception:
                continue

    def inline_cs(self, pimg):
        try:
            cs = pimg.colorspace
            return {"/DeviceRGB": "rgb", "/DeviceCMYK": "cmyk", "/DeviceGray": "gray"}.get(str(cs), "other")
        except Exception:
            return "other"

    def place_image(self, xo, ctm, page, resources):
        w, h = int(xo.get("/Width", 0)), int(xo.get("/Height", 0))
        if xo.get("/ImageMask", False):
            kind, spots = "mask", []
        else:
            kind, spots = cs_kind(xo.get("/ColorSpace", Name.DeviceGray), resources)
        if "/SMask" in xo:
            self.transparency.add(page)
        self.record_image(xo.objgen, w, h, ctm, page, str(xo.get("/Filter", "")), kind, spots, xo)

    def record_image(self, key, w, h, ctm, page, filt, kind, spots, xo):
        pw = math.hypot(ctm[0][0], ctm[0][1])   # placed width in pt
        ph = math.hypot(ctm[1][0], ctm[1][1])
        if pw < 0.5 or ph < 0.5 or w == 0 or h == 0:
            return
        ppi = min(w / (pw / 72), h / (ph / 72))
        e = self.images.get(key)
        if e is None:
            e = self.images[key] = {"px": (w, h), "min_ppi": ppi, "placed_mm": (mm(pw), mm(ph)),
                                    "kind": kind, "spots": spots, "pages": set(), "xo": xo, "filter": filt}
        if ppi < e["min_ppi"]:
            e["min_ppi"], e["placed_mm"] = ppi, (mm(pw), mm(ph))
        e["pages"].add(page)
        if kind != "mask":
            self.note_color(kind, page, spots, image=True)


def image_tac(xo, sample=200):
    """99th-percentile total ink of a CMYK image, or None."""
    try:
        import numpy as np
        from PIL import Image
        im = pikepdf.PdfImage(xo).as_pil_image()
        if im.mode != "CMYK":
            return None
        im.thumbnail((sample, sample))
        a = np.asarray(im, dtype=float)
        # Adobe CMYK JPEGs are often stored inverted (Decode [1 0 1 0 ...])
        # Pillow already undoes the Adobe APP14 inversion of CMYK JPEGs (the PDF
        # /Decode [1 0 ...] array exists for that same inversion): only apply
        # /Decode ourselves when Pillow didn't.
        dec = xo.get("/Decode")
        if dec is not None and float(dec[0]) == 1 and "adobe" not in im.info:
            a = 255 - a
        tac = a.sum(-1) / 255 * 100
        return float(np.percentile(tac, 99))
    except Exception:
        return None


# --------------------------------------------------------------------------
# Main checks
# --------------------------------------------------------------------------

def preflight(path, opts):
    rep = Report()
    try:
        pdf = pikepdf.open(path)
    except pikepdf.PasswordError:
        rep.add("FAIL", "file", "PDF is password-protected: the printer can't open it. Export without a password.")
        return rep, {"pages": 0}
    n = len(pdf.pages)
    meta = {"file": path, "pages": n, "pdf_version": pdf.pdf_version}
    if pdf.is_encrypted:
        rep.add("WARN", "file", "PDF has security restrictions. Some print workflows refuse restricted files; export without security.")
    print_mode = opts.target == "print"

    # ---- pages / bleed ----
    sizes = {}
    bleed_bad, bleed_short, bleed_ok = [], [], []
    for i, page in enumerate(pdf.pages, 1):
        media = box(page, "/MediaBox") or [0, 0, 595, 842]
        crop = box(page, "/CropBox") or media
        trim = box(page, "/TrimBox") or crop
        bleedb = box(page, "/BleedBox") or crop
        rot = int(page.obj.get("/Rotate", 0)) % 180
        tw, th = mm(trim[2] - trim[0]), mm(trim[3] - trim[1])
        if rot:
            tw, th = th, tw
        key = (round(tw, 1), round(th, 1))
        sizes.setdefault(key, []).append(i)
        if print_mode:
            sides = [trim[0] - bleedb[0], trim[1] - bleedb[1], bleedb[2] - trim[2], bleedb[3] - trim[3]]
            b = min(mm(s) for s in sides)
            if "/TrimBox" not in page.obj and b <= 0.01:
                bleed_bad.append(i)
            elif b + 0.05 < opts.bleed:
                bleed_short.append((i, b))
            else:
                bleed_ok.append((i, b))
    for (w, h), pages in sizes.items():
        nm = name_format(w, h)
        rep.add("INFO", "pages", f"Trim size {w:g} × {h:g} mm" + (f" — {nm}" if nm else ""), pages)
    if len(sizes) > 1:
        rep.add("WARN", "pages", f"Mixed page sizes ({len(sizes)} different). Fine for a booklet with a cover spread, otherwise check.")
    if print_mode:
        if bleed_bad:
            rep.add("WARN", "bleed",
                    f"No bleed: the page is exactly the finished size. Anything that touches the edge (photo, color "
                    f"background) will show a white sliver after cutting. Re-export with {opts.bleed:g} mm bleed and crop marks, "
                    f"unless the design has white margins all around.", bleed_bad)
        if bleed_short:
            worst = min(b for _, b in bleed_short)
            rep.add("FAIL", "bleed", f"Bleed too small: {worst:.1f} mm, {opts.bleed:g} mm required.", [p for p, _ in bleed_short])
        if bleed_ok and not bleed_bad and not bleed_short:
            b = min(x for _, x in bleed_ok)
            rep.add("PASS", "bleed", f"Bleed {b:.1f} mm on every side (≥ {opts.bleed:g} mm).")

    # ---- walk content ----
    wk = Walker(pdf, opts)
    for i, page in enumerate(pdf.pages, 1):
        res = page.obj.get("/Resources")
        if "/Group" in page.obj and str(page.obj.Group.get("/S", "")) == "/Transparency":
            wk.transparency.add(i)
        wk.walk(page, res, i, IDENT)
        annots = page.obj.get("/Annots")
        if annots is not None:
            kinds = set()
            for a in annots:
                st = str(a.get("/Subtype", "")).lstrip("/")
                if st not in ("Link", "PrinterMark", "TrapNet"):
                    kinds.add(st)
            if kinds:
                rep.add("WARN", "annotations",
                        f"Annotations / form fields ({', '.join(sorted(kinds))}): comments and fields often don't print. "
                        "Flatten or remove them.", [i])

    # ---- images ----
    imgs = [e for e in wk.images.values() if e["kind"] != "mask"]
    if not imgs:
        rep.add("INFO", "images", "No raster images.")
    else:
        # 3 % tolerance: 291 ppi is a 300 ppi image placed a hair larger, not a problem
        target = opts.min_ppi * 0.97
        low_fail = [e for e in imgs if e["min_ppi"] < opts.low_ppi]
        low_warn = [e for e in imgs if opts.low_ppi <= e["min_ppi"] < target]
        where = "in print" if print_mode else "on screen when zoomed"
        for e in sorted(low_fail, key=lambda e: e["min_ppi"]):
            rep.add("FAIL" if print_mode else "WARN", "images",
                    f"Image {e['px'][0]}×{e['px'][1]} px placed at {e['placed_mm'][0]:.0f}×{e['placed_mm'][1]:.0f} mm "
                    f"= {e['min_ppi']:.0f} ppi (pixelated {where}; needs {opts.min_ppi} ppi, i.e. "
                    f"{math.ceil(e['placed_mm'][0] / 25.4 * opts.min_ppi)} px wide).", sorted(e["pages"]))
        for e in sorted(low_warn, key=lambda e: e["min_ppi"]):
            rep.add("WARN", "images",
                    f"Image {e['px'][0]}×{e['px'][1]} px at {e['placed_mm'][0]:.0f}×{e['placed_mm'][1]:.0f} mm "
                    f"= {e['min_ppi']:.0f} ppi (below {opts.min_ppi}; may look soft up close).", sorted(e["pages"]))
        ok = [e for e in imgs if e["min_ppi"] >= target]
        if ok and not low_fail and not low_warn:
            rep.add("PASS", "images", f"All {len(imgs)} images ≥ {opts.min_ppi} ppi at placed size "
                                      f"(lowest {min(e['min_ppi'] for e in imgs):.0f} ppi).")
        elif ok:
            rep.add("PASS", "images", f"{len(ok)} other image(s) ≥ {opts.min_ppi} ppi.")
        if print_mode:
            rgb_imgs = [e for e in imgs if e["kind"] == "rgb"]
            if rgb_imgs:
                pages = sorted(set().union(*[e["pages"] for e in rgb_imgs]))
                rep.add("WARN", "color",
                        f"{len(rgb_imgs)} RGB image(s). The printer will convert them to CMYK: bright blues, greens and "
                        f"oranges may dull. Fine for most digital printers; for offset, convert with the printer's profile.",
                        pages)
            for e in imgs:
                if e["kind"] == "cmyk" and e["xo"] is not None:
                    t = image_tac(e["xo"])
                    if t is not None and t > opts.max_ink:
                        rep.add("WARN", "ink", f"CMYK image with ~{t:.0f}% total ink in its darkest areas "
                                               f"(limit {opts.max_ink}%): risk of smearing / set-off.", sorted(e["pages"]))

    # ---- fonts ----
    if not wk.fonts:
        rep.add("INFO", "fonts", "No fonts (text outlined or no text).")
    else:
        not_emb = [f for f in wk.fonts.values() if not f["embedded"]]
        t3 = [f for f in wk.fonts.values() if f["type"] == "Type3"]
        for f in not_emb:
            who = "The printer" if print_mode else "Other computers"
            rep.add("FAIL", "fonts", f"Font not embedded: {f['name']}. {who} will substitute another font. "
                                     "Re-export with fonts embedded (or outline the text).", sorted(f["pages"]))
        if t3:
            rep.add("WARN", "fonts", f"Type 3 font(s): {', '.join(sorted({f['name'] for f in t3}))} — usually bitmap "
                                     "fonts from some exporters; can print blurry.", sorted(set().union(*[f['pages'] for f in t3])))
        if not not_emb:
            names = sorted({f["name"] for f in wk.fonts.values()})
            rep.add("PASS", "fonts", f"All {len(names)} font(s) embedded: {', '.join(names[:8])}" + (" …" if len(names) > 8 else ""))

    # ---- color ----
    cu = wk.color_use
    ic = wk.image_color
    def used(d):
        return [k for k in ("cmyk", "rgb", "gray", "spot", "lab") if k in d]
    rep.add("INFO", "color", "Color spaces — vectors & text: " + (", ".join(used(cu)) or "none")
            + " · images: " + (", ".join(used(ic)) or "none"))
    if print_mode and "rgb" in cu:
        rep.add("WARN", "color", "RGB colors in vector art or text. OK for digital print; for offset or exact brand "
                                 "colors, convert to CMYK (or define spot colors).", sorted(cu["rgb"]))
    if wk.spots:
        for s, pages in sorted(wk.spots.items()):
            rep.add("WARN" if print_mode else "INFO", "color",
                    f"Spot color \"{s}\". Only right if you pay for a special ink; otherwise convert it to CMYK.", sorted(pages))
    if "registration" in cu:
        rep.add("FAIL", "color", "Registration color (100% of every ink) used on page content: it prints as a muddy "
                                 "rich black and can smear. Use black (0/0/0/100) or a rich black instead.", sorted(cu["registration"]))
    if print_mode and wk.tac_vec:
        over = [(t, p) for t, p in wk.tac_vec if t > opts.max_ink + 0.5]
        if over:
            worst = max(t for t, _ in over)
            rep.add("WARN", "ink", f"CMYK colors up to {worst:.0f}% total ink (limit {opts.max_ink}%): smearing / long drying. "
                                   "For rich black use about 60/40/40/100.", [p for _, p in over])
        else:
            rep.add("PASS", "ink", f"CMYK vector colors under {opts.max_ink}% total ink.")
    oi = pdf.Root.get("/OutputIntents")
    if oi is not None and len(oi):
        ident = str(oi[0].get("/OutputConditionIdentifier", "")) or str(oi[0].get("/Info", ""))
        sub = str(oi[0].get("/S", "")).lstrip("/")
        rep.add("INFO", "color", f"Output intent {sub}: {ident}")
    elif print_mode:
        rep.add("INFO", "color", "No output intent (not a PDF/X file). Ask the printer whether they need PDF/X-1a or PDF/X-4.")

    # ---- hairlines ----
    if wk.hairlines:
        total = sum(wk.hairlines.values())
        rep.add("WARN" if print_mode else "INFO", "strokes",
                f"{total} stroke(s) thinner than {opts.hairline} pt: hairlines may disappear or break up in print.",
                sorted(wk.hairlines))
    elif print_mode:
        rep.add("PASS", "strokes", f"No strokes thinner than {opts.hairline} pt.")

    # ---- transparency / layers ----
    if wk.transparency:
        rep.add("INFO", "transparency", "Transparency (opacity, blend modes or soft masks). Fine for PDF/X-4 and modern "
                                         "printers; flatten if the printer asks for PDF/X-1a.", sorted(wk.transparency))
    if "/OCProperties" in pdf.Root:
        rep.add("WARN", "layers", "PDF has layers (optional content). Hidden layers may print or vanish depending on the RIP; "
                                  "merge layers before export.")

    meta["fonts"] = [{k: (sorted(v) if isinstance(v, set) else v) for k, v in f.items()} for f in wk.fonts.values()]
    meta["images"] = [{"px": e["px"], "min_ppi": round(e["min_ppi"], 1), "placed_mm": [round(x, 1) for x in e["placed_mm"]],
                       "colorspace": e["kind"], "pages": sorted(e["pages"])} for e in wk.images.values()]
    meta["spot_colors"] = sorted(wk.spots)
    return rep, meta


ICON = {"FAIL": "❌", "WARN": "⚠️", "PASS": "✅", "INFO": "ℹ️"}
ORDER = {"FAIL": 0, "WARN": 1, "PASS": 2, "INFO": 3}


def to_markdown(rep, meta, opts):
    c = rep.counts()
    verdict = "Not ready to print" if c["FAIL"] else ("Printable, with warnings" if c["WARN"] else "Ready to print")
    if opts.target == "digital":
        verdict = verdict.replace("print", "share")
    lines = [f"# Preflight — {meta.get('file', '')}", "",
             f"**{verdict}** · {c['FAIL']} fail · {c['WARN']} warning · {c['PASS']} pass · "
             f"{meta.get('pages', 0)} page(s) · PDF {meta.get('pdf_version', '?')} · target: {opts.target}", ""]
    for it in sorted(rep.items, key=lambda i: ORDER[i.level]):
        lines.append(f"- {ICON[it.level]} **{it.check}** — {it.message}{fmt_pages(it.pages, meta.get('pages', 0))}")
    lines += ["", f"_Settings: bleed {opts.bleed:g} mm · min {opts.min_ppi} ppi (fail < {opts.low_ppi}) · "
                  f"max ink {opts.max_ink}% · hairline {opts.hairline} pt._"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description="Preflight a PDF for print.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("pdf")
    p.add_argument("--target", choices=["print", "digital"], default="print",
                   help="'digital' skips bleed/CMYK/ink checks (screen PDFs, slides)")
    p.add_argument("--bleed", type=float, default=3.0, help="required bleed in mm (default 3)")
    p.add_argument("--min-ppi", type=int, default=300, help="target image resolution (default 300)")
    p.add_argument("--low-ppi", type=int, default=150, help="below this an image FAILS (default 150)")
    p.add_argument("--max-ink", type=int, default=300, help="total area coverage limit in %% (default 300)")
    p.add_argument("--hairline", type=float, default=0.25, help="thinnest acceptable stroke in pt (default 0.25)")
    p.add_argument("-o", "--output", help="write the Markdown report here (default: stdout)")
    p.add_argument("--json", help="also write machine-readable results")
    p.add_argument("--no-exit-code", action="store_true", help="always exit 0")
    opts = p.parse_args(argv)
    if opts.target == "digital":
        opts.min_ppi = min(opts.min_ppi, 150)
        opts.low_ppi = min(opts.low_ppi, 72)

    rep, meta = preflight(opts.pdf, opts)
    md = to_markdown(rep, meta, opts)
    if opts.output:
        with open(opts.output, "w") as f:
            f.write(md)
        print(opts.output)
    else:
        sys.stdout.write(md)
    if opts.json:
        with open(opts.json, "w") as f:
            json.dump({"summary": rep.counts(), "meta": meta,
                       "findings": [i.__dict__ for i in sorted(rep.items, key=lambda i: ORDER[i.level])]},
                      f, indent=2, ensure_ascii=False, default=str)
    return 1 if (rep.counts()["FAIL"] and not opts.no_exit_code) else 0


if __name__ == "__main__":
    sys.exit(main())
