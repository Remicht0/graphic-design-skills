"""
Smoke tests for the skills' scripts. Run with:  python -m pytest -q
Each test runs a script the way an agent would (as a subprocess) on small
generated inputs, and checks the outputs. The layout test is skipped when no
Chromium is available.
"""
import json
import os
import shutil
import struct
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(ROOT, "skills")


def run(*args, ok=(0,)):
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    assert r.returncode in ok, r.stdout + r.stderr
    return r


@pytest.fixture
def photo(tmp_path):
    """A small synthetic 'photo': gradient + circle + noise."""
    h, w = 120, 180
    y, x = np.mgrid[0:h, 0:w]
    r = (x / w * 255)
    g = (y / h * 255)
    b = 255 - (x + y) / (w + h) * 255
    img = np.stack([r, g, b], -1)
    img[((x - 90) ** 2 + (y - 60) ** 2) < 900] = [20, 20, 20]
    img += np.random.default_rng(0).normal(0, 8, img.shape)
    p = tmp_path / "photo.png"
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(p)
    return p


# ---------------------------------------------------------------- dither
DITHER = os.path.join(S, "dither", "scripts", "dither.py")


@pytest.mark.parametrize("method", ["floyd-steinberg", "atkinson", "jjn", "stucki", "burkes", "sierra",
                                    "sierra-lite", "bayer2", "bayer4", "bayer8", "bayer16", "threshold",
                                    "random", "halftone"])
def test_dither_methods(photo, tmp_path, method):
    out = tmp_path / f"{method}.png"
    run(DITHER, str(photo), "-o", str(out), "-m", method, "--width", "90", "--scale", "2")
    im = Image.open(out)
    assert im.size == (180, 120)
    assert len(im.getcolors(256)) <= 2


def test_dither_palette_color_svg(photo, tmp_path):
    out = tmp_path / "riso.png"
    run(DITHER, str(photo), "-o", str(out), "--color", "--palette", "riso", "--width", "60")
    assert len(Image.open(out).getcolors(256)) <= 5
    svg = tmp_path / "out.svg"
    run(DITHER, str(photo), "-o", str(svg), "-m", "bayer4", "--width", "40")
    assert svg.read_text().startswith("<svg")
    duo = tmp_path / "duo.png"
    run(DITHER, str(photo), "-o", str(duo), "--palette", "#1F2BD1,#F3F2EE", "--aspect", "1:1", "--width", "50")
    im = Image.open(duo).convert("RGB")
    assert im.size == (50, 50)
    assert {c for _, c in im.getcolors(256)} <= {(0x1F, 0x2B, 0xD1), (0xF3, 0xF2, 0xEE)}


def test_dither_compare(photo, tmp_path):
    out = tmp_path / "cmp.png"
    run(DITHER, str(photo), "--compare", "-o", str(out), "--width", "60")
    assert Image.open(out).width > 200


# ---------------------------------------------------------------- palette
PALETTE = os.path.join(S, "palette", "scripts", "palette.py")


def test_palette_extract_and_exports(photo, tmp_path):
    pj = tmp_path / "p.json"
    run(PALETTE, "extract", str(photo), "-n", "5", "-o", str(pj), "--sheet", str(tmp_path / "sheet.png"))
    data = json.loads(pj.read_text())
    assert 3 <= len(data["colors"]) <= 5
    assert abs(sum(c["share"] for c in data["colors"]) - 1) < 0.01
    for fmt in ["css", "scss", "tailwind", "tokens", "gpl", "svg", "png", "json"]:
        out = tmp_path / f"out.{fmt}"
        run(PALETTE, "export", str(pj), "--to", fmt, "-o", str(out))
        assert out.stat().st_size > 0
    ase = tmp_path / "p.ase"
    run(PALETTE, "export", str(pj), "--to", "ase", "-o", str(ase))
    raw = ase.read_bytes()
    assert raw[:4] == b"ASEF" and struct.unpack(">HH", raw[4:8]) == (1, 0)
    assert struct.unpack(">I", raw[8:12])[0] == len(data["colors"]) + 2  # colors + group start/end


def test_palette_contrast_values(tmp_path):
    r = run(PALETTE, "contrast", "#777777,#FFFFFF,#000000", "--json")
    pairs = {(p["a"], p["b"]): p for p in json.loads(r.stdout)}
    gray_white = next(p for k, p in pairs.items() if "gray" in k and "white" in k)
    assert gray_white["ratio"] == pytest.approx(4.48, abs=0.01)   # known WCAG value
    black_white = next(p for k, p in pairs.items() if "black" in k and "white" in k)
    assert black_white["ratio"] == 21.0


def test_palette_scale_and_harmony(tmp_path):
    out = tmp_path / "s.json"
    run(PALETTE, "scale", "#2D4CB4", "--keep", "-o", str(out))
    cols = json.loads(out.read_text())["colors"]
    assert len(cols) == 11 and "#2D4CB4" in [c["hex"] for c in cols]
    r = run(PALETTE, "harmony", "#FF4F12", "--type", "triadic")
    assert len(json.loads(r.stdout)["colors"]) == 3


# ---------------------------------------------------------------- preflight
PREFLIGHT = os.path.join(S, "print-preflight", "scripts", "preflight.py")


def test_preflight_catches_problems(photo, tmp_path):
    rl = pytest.importorskip("reportlab")
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "bad.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(210 * mm, 297 * mm))
    c.drawImage(str(photo), 0, 150 * mm, width=210 * mm, height=140 * mm)  # ~22 ppi
    c.setFont("Helvetica", 20)
    c.drawString(20 * mm, 100 * mm, "not embedded")
    c.setLineWidth(0.1)
    c.line(20 * mm, 90 * mm, 190 * mm, 90 * mm)
    c.setFillColorCMYK(1, 1, 1, 1)
    c.rect(20 * mm, 20 * mm, 50 * mm, 30 * mm, fill=1, stroke=0)
    c.showPage()
    c.save()
    js = tmp_path / "r.json"
    run(PREFLIGHT, str(pdf), "--json", str(js), ok=(1,))
    res = json.loads(js.read_text())
    checks = {(f["level"], f["check"]) for f in res["findings"]}
    assert ("FAIL", "images") in checks
    assert ("FAIL", "fonts") in checks
    assert ("WARN", "bleed") in checks
    assert ("WARN", "ink") in checks
    assert ("WARN", "strokes") in checks


def test_preflight_clean_file(tmp_path):
    pytest.importorskip("reportlab")
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "ok.pdf"
    b = 3 * mm
    c = canvas.Canvas(str(pdf), pagesize=(148 * mm + 2 * b, 210 * mm + 2 * b))
    c.setTrimBox((b, b, 148 * mm + b, 210 * mm + b))
    c.setBleedBox((0, 0, 148 * mm + 2 * b, 210 * mm + 2 * b))
    c.setFillColorCMYK(0, 0.6, 1, 0)
    c.rect(0, 0, 148 * mm + 2 * b, 50 * mm, fill=1, stroke=0)
    c.showPage()
    c.save()
    r = run(PREFLIGHT, str(pdf))
    assert "Ready to print" in r.stdout
    assert "A5" in r.stdout


# ---------------------------------------------------------------- art direction (static mode)
STATIC = os.path.join(S, "art-direction-analyzer", "scripts", "extract_static.py")


def test_static_extractor(tmp_path):
    (tmp_path / "s.css").write_text(":root{--ink:#151515;--accent:#ff4f12}"
                                    "h1{font-family:'Anton',sans-serif;font-size:120px;transition:color .3s ease}"
                                    "@keyframes slide{to{transform:translateX(-50%)}}@media (max-width:768px){h1{font-size:60px}}")
    (tmp_path / "i.html").write_text('<html><head><title>T</title><link rel="stylesheet" href="s.css">'
                                     '<script src="https://cdn.example.com/gsap.min.js"></script></head>'
                                     '<body style="color:rgb(21,21,21)"><h1>Hi</h1></body></html>')
    r = run(STATIC, str(tmp_path / "i.html"))
    d = json.loads(r.stdout)
    assert d["fonts"]["declared"][0]["value"] == "Anton"
    assert "--accent" in d["cssVariables"]
    assert "slide" in d["motion"]["keyframes"]
    assert "GSAP" in d["libraries"]
    assert any(c["value"] == "#151515" for c in d["colors"])


# ---------------------------------------------------------------- editorial layout (needs a browser)
def _chrome():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    for exe in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(exe):
            return shutil.which(exe)
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return "playwright"
    except Exception:
        return None


@pytest.mark.skipif(_chrome() is None, reason="no Chromium available")
def test_editorial_render(tmp_path):
    render = os.path.join(S, "editorial-layout", "scripts", "render.py")
    html = os.path.join(S, "editorial-layout", "templates", "example.html")
    pdf = tmp_path / "ex.pdf"
    args = [render, html, "-o", str(pdf), "--png", str(tmp_path / "prev"), "--bleed", "3"]
    chrome = _chrome()
    if chrome != "playwright":
        args += ["--chrome", chrome]
    r = run(*args)
    assert "6 page(s)" in r.stdout
    assert len(os.listdir(tmp_path / "prev")) == 6
    import pikepdf
    with pikepdf.open(pdf) as p:
        assert len(p.pages) == 6
        assert "/TrimBox" in p.pages[0].obj
