#!/usr/bin/env python3
"""
render.py — render an editorial HTML document to a print-ready PDF,
with PNG previews and automatic layout checks.

  • one <section class="page"> per page (see assets/print.css)
  • --format sets the page size, --bleed adds bleed and writes TrimBox/BleedBox
  • [data-fit="0.9"] on a title: font size is fitted so the line fills 90 %
    of its block's width (great for giant display words)
  • checks: text overflowing its block or crossing the trim, missing fonts
    (silent fallbacks), low-resolution images, empty pages
  • --png writes one preview per page, --sheet a contact sheet of all pages,
    --grid draws the 12-column grid on the previews

Requirements: pip install playwright (+ `python -m playwright install chromium`
or an installed Chrome). Optional: pikepdf (TrimBox/BleedBox), Pillow (sheet).

Examples
  python3 render.py doc.html -o doc.pdf --png previews --sheet sheet.png
  python3 render.py doc.html -o doc.pdf --format A3 --bleed 3
  python3 render.py doc.html --png previews --grid          # previews only
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile

FORMATS = {  # width x height in mm
    "A5": (148, 210), "A4": (210, 297), "A3": (297, 420), "A2": (420, 594),
    "letter": (215.9, 279.4), "tabloid": (279.4, 431.8),
    "16:9": (338.67, 190.5), "square": (210, 210), "instagram": (285.75, 285.75),
    "instagram-portrait": (285.75, 357.19), "story": (190.5, 338.67), "business-card": (85, 55),
}

FIT_JS = r"""
() => {
  const out = [];
  for (const el of document.querySelectorAll('[data-fit]')) {
    const ratio = parseFloat(el.dataset.fit || '1');
    const box = el.parentElement;
    const target = (el.dataset.fitWidth ? parseFloat(el.dataset.fitWidth) : box.clientWidth) * ratio;
    el.style.whiteSpace = 'nowrap';
    el.style.display = 'inline-block';
    let lo = 4, hi = 2000;
    for (let i = 0; i < 30; i++) {
      const mid = (lo + hi) / 2;
      el.style.fontSize = mid + 'px';
      if (el.scrollWidth > target) hi = mid; else lo = mid;
    }
    el.style.fontSize = lo + 'px';
    out.push({text: el.textContent.trim().slice(0, 30), px: Math.round(lo)});
  }
  return out;
}
"""

CHECK_JS = r"""
() => {
  const issues = [];
  const pxPerMm = 96 / 25.4;
  const pages = [...document.querySelectorAll('.page')];
  const bleedMm = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bleed')) || 0;
  pages.forEach((page, i) => {
    const n = i + 1;
    const pr = page.getBoundingClientRect();
    const b = bleedMm * pxPerMm;
    const trim = {l: pr.left + b, t: pr.top + b, r: pr.right - b, b: pr.bottom - b};
    if (!page.innerText.trim() && !page.querySelector('img, svg, canvas')) issues.push({page: n, level: 'WARN', msg: 'empty page'});
    // text blocks: overflow of their own box, or crossing the trim
    const textEls = page.querySelectorAll('.text, .lead, .micro, p, li, figcaption, h1, h2, h3, h4, .display');
    textEls.forEach((el) => {
      if (!el.innerText || !el.innerText.trim()) return;
      const label = el.className ? '.' + String(el.className).split(' ')[0] : el.tagName.toLowerCase();
      const sample = el.innerText.trim().replace(/\s+/g, ' ').slice(0, 40);
      const isDisplay = el.classList.contains('display') || el.closest('.display');
      // measure the inked text, not the (often full-width) element box
      const rg = document.createRange();
      rg.selectNodeContents(el);
      const rr = [...rg.getClientRects()].filter((q) => q.width > 0 && q.height > 0);
      if (!rr.length) return;
      const r = {left: Math.min(...rr.map((q) => q.left)), top: Math.min(...rr.map((q) => q.top)),
                 right: Math.max(...rr.map((q) => q.right)), bottom: Math.max(...rr.map((q) => q.bottom))};
      // text crossing the trim (display type is allowed to bleed on purpose)
      if (!isDisplay && (r.left < trim.l - 0.5 || r.right > trim.r + 0.5 || r.top < trim.t - 0.5 || r.bottom > trim.b + 0.5)) {
        issues.push({page: n, level: 'FAIL', msg: `text crosses the page edge: ${label} "${sample}"`});
        return;
      }
      // text too close to the cut (< 3 mm) — will look cramped or get trimmed
      const safe = 3 * pxPerMm;
      if (!isDisplay && (r.left < trim.l + safe || r.right > trim.r - safe || r.top < trim.t + safe || r.bottom > trim.b - safe)) {
        issues.push({page: n, level: 'WARN', msg: `text within 3 mm of the cut: ${label} "${sample}"`});
      }
      // overflowing its grid cell
      const cell = el.closest('.page > *') || el;
      if (cell !== page) {
        const cr = cell.getBoundingClientRect();
        if (!isDisplay && (cell.scrollHeight > cell.clientHeight + 2 || r.bottom > cr.bottom + 2)) {
          issues.push({page: n, level: 'WARN', msg: `text overflows its block: ${label} "${sample}"`});
        }
      }
      const fs = parseFloat(getComputedStyle(el).fontSize) / pxPerMm * 72 / 25.4;
      if (fs < 6) issues.push({page: n, level: 'WARN', msg: `text under 6 pt (${fs.toFixed(1)} pt): ${label} "${sample}"`});
    });
    // overlapping text: compare the inked area (text ranges) of top-level blocks
    const blocks = [...page.children].filter((c) => c.innerText && c.innerText.trim());
    // text line boxes: a glyph's content box is taller than its line when line-height is tight
    // (display type at .8), so each rect is trimmed to the line-height of its own element.
    const lineRects = (blk) => {
      const out = [];
      const walker = document.createTreeWalker(blk, NodeFilter.SHOW_TEXT);
      for (let t = walker.nextNode(); t; t = walker.nextNode()) {
        if (!t.textContent.trim()) continue;
        const cs = getComputedStyle(t.parentElement);
        const fs = parseFloat(cs.fontSize);
        const lh = cs.lineHeight === 'normal' ? fs * 1.2 : parseFloat(cs.lineHeight);
        const rg = document.createRange();
        rg.selectNodeContents(t);
        for (const r of rg.getClientRects()) {
          if (r.width <= 0 || r.height <= 0) continue;
          const trim = Math.max(0, (r.height - lh) / 2);
          out.push({left: r.left, right: r.right, top: r.top + trim, bottom: r.bottom - trim});
        }
      }
      return out;
    };
    const inked = blocks.map((blk) => {
      const rects = lineRects(blk);
      if (!rects.length) return null;
      return {rects, s: blk.innerText.trim().replace(/\s+/g, ' ').slice(0, 28)};
    });
    // compare line boxes one by one (a union box would flag blocks whose text merely surrounds another)
    const hits = (A, B) => A.rects.some((p) => B.rects.some((q) =>
      Math.min(p.right, q.right) - Math.max(p.left, q.left) > 2 && Math.min(p.bottom, q.bottom) - Math.max(p.top, q.top) > 2));
    for (let a = 0; a < inked.length; a++) for (let c = a + 1; c < inked.length; c++) {
      const A = inked[a], B = inked[c];
      if (A && B && hits(A, B)) issues.push({page: n, level: 'WARN', msg: `text blocks overlap: "${A.s}" / "${B.s}"`});
    }
    // images: effective resolution at printed size
    page.querySelectorAll('img').forEach((img) => {
      if (!img.complete || !img.naturalWidth) {
        issues.push({page: n, level: 'FAIL', msg: `image not loaded: ${img.getAttribute('src')}`});
        return;
      }
      const r = img.getBoundingClientRect();
      // object-fit: cover crops: the shown part of the image is what matters
      const fit = getComputedStyle(img).objectFit;
      const scale = fit === 'cover' ? Math.max(r.width / img.naturalWidth, r.height / img.naturalHeight)
                                    : Math.min(r.width / img.naturalWidth, r.height / img.naturalHeight);
      const ppi = 96 / scale;
      const name = (img.getAttribute('src') || '').split('/').pop();
      const pixelated = img.closest('.pixel');
      if (pixelated && ppi < 150) issues.push({page: n, level: 'WARN', msg: `${name}: pixel/dithered image at ${Math.round(ppi)} ppi — PDF viewers and printers may smooth it. Upscale it with nearest-neighbour first (dither.py --scale ${Math.ceil(300 / ppi)})`});
      else if (!pixelated && ppi < 150) issues.push({page: n, level: 'WARN', msg: `${name}: ${Math.round(ppi)} ppi at printed size (blurry; aim for 300)`});
      else if (!pixelated && ppi < 250) issues.push({page: n, level: 'INFO', msg: `${name}: ${Math.round(ppi)} ppi at printed size (OK for screen/digital print, soft for offset)`});
    });
  });
  // fonts: detect silent fallbacks by measuring
  const probe = document.createElement('span');
  probe.textContent = 'Hamburgefontsiv 0123456789 AaBbQqRrWw';
  probe.style.cssText = 'position:absolute;visibility:hidden;font-size:72px;white-space:nowrap';
  document.body.appendChild(probe);
  const width = (fam) => { probe.style.fontFamily = fam; return probe.getBoundingClientRect().width; };
  const used = new Set();
  document.querySelectorAll('.page, .page *').forEach((el) => {
    if (el.childNodes && [...el.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim())) {
      used.add(getComputedStyle(el).fontFamily);
    }
  });
  const fonts = [];
  for (const stack of used) {
    const fams = stack.split(',').map((s) => s.trim().replace(/^["']|["']$/g, ''));
    let resolved = null;
    for (const f of fams) {
      if (['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-monospace'].includes(f)) { resolved = resolved || f + ' (generic)'; break; }
      const q = `"${f}"`;
      if (width(q + ', monospace') !== width('monospace') || width(q + ', serif') !== width('serif')) { resolved = f; break; }
    }
    fonts.push({stack, resolved, first: fams[0]});
    if (resolved !== fams[0]) issues.push({page: 0, level: 'WARN', msg: `font "${fams[0]}" not available — rendered with ${resolved}`});
  }
  probe.remove();
  return {pages: pages.length, issues, fonts};
}
"""


def launch(p, chrome):
    if chrome:
        return p.chromium.launch(executable_path=chrome)
    try:
        return p.chromium.launch()
    except Exception:
        pass
    try:
        return p.chromium.launch(channel="chrome")
    except Exception:
        pass
    for exe in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        path = shutil.which(exe) or (exe if os.path.exists(exe) else None)
        if path:
            return p.chromium.launch(executable_path=path)
    raise SystemExit("No Chromium found. Run: python -m playwright install chromium (or pass --chrome PATH)")


def parse_format(fmt: str | None):
    if not fmt:
        return None
    f = fmt.strip()
    land = f.endswith("-landscape") or f.endswith("-l")
    key = f if f in FORMATS else re.sub(r"-(landscape|l|portrait|p)$", "", f)
    if key in FORMATS:
        w, h = FORMATS[key]
    else:
        m = re.match(r"^([\d.]+)x([\d.]+)(mm)?$", key)
        if not m:
            raise SystemExit(f"unknown format {fmt}: use {', '.join(FORMATS)} (+ -landscape) or WxHmm")
        w, h = float(m.group(1)), float(m.group(2))
    if land and h > w:
        w, h = h, w
    return w, h


def set_boxes(pdf_path, bleed_mm, trim_wh=None):
    try:
        import pikepdf
    except ImportError:
        print("  (pikepdf not installed: TrimBox/BleedBox not written)", file=sys.stderr)
        return False
    b = bleed_mm * 72 / 25.4
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
        for page in pdf.pages:
            x0, y0, x1, y1 = [float(v) for v in page.MediaBox]
            page.obj["/BleedBox"] = pikepdf.Array([x0, y0, x1, y1])
            page.obj["/TrimBox"] = pikepdf.Array([x0 + b, y0 + b, x1 - b, y1 - b])
        pdf.save(pdf_path)
    return True


def contact_sheet(paths, out, cols=4):
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in paths]
    tw = 520
    tiles = [im.resize((tw, round(im.height * tw / im.width)), Image.LANCZOS) for im in ims]
    th = max(t.height for t in tiles)
    cols = min(cols, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    pad = 24
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * pad, rows * th + (rows + 1) * pad), (130, 130, 128))
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet.paste(t, (pad + c * (tw + pad), pad + r * (th + pad)))
    sheet.save(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html")
    ap.add_argument("-o", "--output", help="PDF to write (omit for previews/checks only)")
    ap.add_argument("--format", help=f"page size: {', '.join(FORMATS)} (+ -landscape) or WxHmm. "
                                     "Default: whatever the document's CSS says (A4 landscape in print.css)")
    ap.add_argument("--bleed", type=float, default=0, help="bleed in mm (writes TrimBox/BleedBox)")
    ap.add_argument("--png", help="folder for one PNG preview per page")
    ap.add_argument("--scale", type=float, default=1.5, help="preview pixel density (1 = 96 dpi)")
    ap.add_argument("--sheet", help="contact sheet PNG of all pages")
    ap.add_argument("--grid", action="store_true", help="draw the grid and trim on previews")
    ap.add_argument("--json", help="write the check results as JSON")
    ap.add_argument("--chrome", help="path to Chrome/Chromium")
    a = ap.parse_args(argv)

    from playwright.sync_api import sync_playwright

    src = os.path.abspath(a.html)
    fmt = parse_format(a.format)
    css = []
    if fmt:
        w, h = fmt
        css.append(f":root{{--pw:{w}mm;--ph:{h}mm}}")
    if a.bleed:
        css.append(f":root{{--bleed:{a.bleed}mm}}")

    with sync_playwright() as p:
        browser = launch(p, a.chrome)
        page = browser.new_page(device_scale_factor=a.scale)
        try:
            page.goto("file://" + src, wait_until="networkidle", timeout=30000)
        except Exception:
            page.goto("file://" + src, wait_until="load", timeout=60000)
        if css:
            page.add_style_tag(content="\n".join(css))
        # page size: read the real page box (handles documents with their own @page)
        size = page.evaluate("""() => { const p = document.querySelector('.page');
            if (!p) return null; const r = p.getBoundingClientRect();
            return [r.width * 25.4 / 96, r.height * 25.4 / 96]; }""")
        if not size:
            raise SystemExit("no <section class=\"page\"> found in the document")
        page.add_style_tag(content=f"@page{{size:{size[0]:.3f}mm {size[1]:.3f}mm;margin:0}} body{{background:none}} "
                                   "@media screen{.page{margin:0 !important;box-shadow:none !important}}")
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        fitted = page.evaluate(FIT_JS)
        page.evaluate("document.fonts.ready")
        report = page.evaluate(CHECK_JS)
        report["fitted"] = fitted
        report["size_mm"] = [round(size[0], 2), round(size[1], 2)]

        if a.output:
            page.emulate_media(media="print")
            page.pdf(path=a.output, prefer_css_page_size=True, print_background=True)
            page.emulate_media(media="screen")
            if a.bleed:
                set_boxes(a.output, a.bleed)

        pngs = []
        if a.png or a.sheet:
            folder = a.png or tempfile.mkdtemp(prefix="previews-")
            os.makedirs(folder, exist_ok=True)
            if a.grid:
                page.evaluate("document.body.classList.add('show-grid','show-trim')")
            # gap between pages + integer clip so no row of the next page leaks into a preview
            page.add_style_tag(content="@media screen{.page{margin:0 0 40px 0 !important}}")
            for i, el in enumerate(page.query_selector_all(".page"), 1):
                path = os.path.join(folder, f"page-{i:02d}.png")
                bb = el.bounding_box()
                page.screenshot(path=path, full_page=True,
                                clip={"x": bb["x"], "y": bb["y"], "width": int(bb["width"]), "height": int(bb["height"])})
                pngs.append(path)
        browser.close()

    if a.sheet and pngs:
        contact_sheet(pngs, a.sheet)

    # ---- report
    issues = report["issues"]
    order = {"FAIL": 0, "WARN": 1, "INFO": 2}
    issues.sort(key=lambda x: (order[x["level"]], x["page"]))
    w, h = report["size_mm"]
    trim = f"{w - 2 * a.bleed:.0f}×{h - 2 * a.bleed:.0f} mm" + (f" + {a.bleed:g} mm bleed" if a.bleed else "")
    print(f"{report['pages']} page(s), {trim}" + (f" → {a.output}" if a.output else ""))
    for f in fitted:
        print(f"  fitted \"{f['text']}\" → {f['px'] * 0.75:.0f} pt")
    icon = {"FAIL": "❌", "WARN": "⚠️ ", "INFO": "ℹ️ "}
    seen = set()
    for it in issues:
        key = (it["level"], it["page"], it["msg"])
        if key in seen:
            continue
        seen.add(key)
        where = f"p.{it['page']}" if it["page"] else "doc"
        print(f"  {icon[it['level']]} {where:5s} {it['msg']}")
    if not issues:
        print("  ✅ no layout issues found")
    if pngs and a.png:
        print(f"  previews: {a.png}/" + (f" · sheet: {a.sheet}" if a.sheet else ""))
    elif a.sheet:
        print(f"  sheet: {a.sheet}")
        shutil.rmtree(os.path.dirname(pngs[0]), ignore_errors=True)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    return 1 if any(i["level"] == "FAIL" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
