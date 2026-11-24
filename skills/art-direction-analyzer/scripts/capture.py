#!/usr/bin/env python3
"""
capture.py — headless capture of a website's art direction.

Opens the page in Chromium (Playwright), waits for fonts and entrance
animations, then saves into OUT_DIR:
  01-home.png            first screen
  02-…png                one screenshot per scrolled screen (--sections)
  hover-*.png            a nav link and a button, mid-hover
  mobile.png             first screen at 390 px wide (--mobile)
  fullpage.png           whole page, capped in height (--fullpage)
  extract.json           computed design tokens (scripts/extract-da.js)

Use it when no interactive browser tool is available, or to batch several sites.

Requirements: pip install playwright && python -m playwright install chromium
(or an installed Chrome/Chromium: it is found automatically, or pass --chrome).

Examples
  python3 capture.py https://example.com -o refs/example
  python3 capture.py https://example.com -o refs/example --sections 5 --mobile --fullpage
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))

COOKIE_WORDS = ["accept all", "accept", "agree", "allow all", "got it", "ok", "tout accepter", "accepter",
                "j'accepte", "alle akzeptieren", "aceptar", "accetta"]


def launch(p, chrome: str | None):
    errors = []
    if chrome:
        return p.chromium.launch(executable_path=chrome)
    try:
        return p.chromium.launch()
    except Exception as e:  # browsers not downloaded
        errors.append(str(e).splitlines()[0])
    try:
        return p.chromium.launch(channel="chrome")
    except Exception as e:
        errors.append(str(e).splitlines()[0])
    for exe in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        path = shutil.which(exe) or (exe if os.path.exists(exe) else None)
        if path:
            return p.chromium.launch(executable_path=path)
    raise SystemExit("No Chromium found. Run: python -m playwright install chromium\n" + "\n".join(errors))


def dismiss_cookies(page):
    for word in COOKIE_WORDS:
        try:
            btn = page.get_by_role("button", name=word, exact=False).first
            if btn.is_visible(timeout=300):
                btn.click(timeout=1000)
                page.wait_for_timeout(500)
                return word
        except Exception:
            continue
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="https://… or a local .html file")
    ap.add_argument("-o", "--out", required=True, help="output folder")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--sections", type=int, default=3, help="extra scrolled screenshots (default 3)")
    ap.add_argument("--wait", type=int, default=2500, help="ms to wait after load for fonts/intro animations")
    ap.add_argument("--mobile", action="store_true", help="also capture a 390 px wide mobile screen")
    ap.add_argument("--fullpage", action="store_true", help="also save a full-page screenshot (max 12000 px tall)")
    ap.add_argument("--keep-cookie-banner", action="store_true", help="don't try to click 'accept' on cookie banners")
    ap.add_argument("--chrome", help="path to a Chrome/Chromium executable")
    a = ap.parse_args(argv)

    from playwright.sync_api import sync_playwright

    url = a.url
    if os.path.exists(url):
        url = "file://" + os.path.abspath(url)
    os.makedirs(a.out, exist_ok=True)
    js = open(os.path.join(HERE, "extract-da.js"), encoding="utf-8").read().strip().rstrip(";")
    shots = []

    with sync_playwright() as p:
        browser = launch(p, a.chrome)
        ctx = browser.new_context(viewport={"width": a.width, "height": a.height}, device_scale_factor=1,
                                  user_agent=None)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception:
            page.goto(url, wait_until="load", timeout=60000)
        try:
            page.evaluate("document.fonts && document.fonts.ready")
        except Exception:
            pass
        page.wait_for_timeout(a.wait)
        clicked = None if a.keep_cookie_banner else dismiss_cookies(page)

        def shot(name, **kw):
            path = os.path.join(a.out, name)
            page.screenshot(path=path, **kw)
            shots.append(name)

        shot("01-home.png")
        total = page.evaluate("document.documentElement.scrollHeight")
        for i in range(a.sections):
            y = (i + 1) * a.height
            if y >= total - 50:
                break
            page.evaluate(f"window.scrollTo(0, {y})")
            page.wait_for_timeout(900)  # let scroll-triggered animations play
            shot(f"{i + 2:02d}-scroll.png")

        # hover states
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
        for label, sel in (("nav", "nav a, header a"), ("button", "button, .btn, a.button, [role=button]")):
            try:
                el = page.locator(sel).filter(visible=True).first
                el.hover(timeout=2000)
                page.wait_for_timeout(400)
                bb = el.bounding_box()
                if bb:
                    pad = 80
                    clip = {"x": max(0, bb["x"] - pad), "y": max(0, bb["y"] - pad),
                            "width": min(a.width, bb["width"] + 2 * pad), "height": bb["height"] + 2 * pad}
                    shot(f"hover-{label}.png", clip=clip)
            except Exception:
                pass

        data = page.evaluate(js)
        data["_capture"] = {"date": time.strftime("%Y-%m-%d"), "viewport": [a.width, a.height],
                            "cookie_banner_clicked": clicked, "screenshots": shots}

        if a.fullpage:
            h = min(total, 12000)
            page.set_viewport_size({"width": a.width, "height": a.height})
            shot("fullpage.png", full_page=h < 12000, clip=None if h < 12000 else {"x": 0, "y": 0, "width": a.width, "height": h})

        if a.mobile:
            m = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                                    has_touch=True)
            mp = m.new_page()
            try:
                mp.goto(url, wait_until="networkidle", timeout=45000)
            except Exception:
                mp.goto(url, wait_until="load", timeout=60000)
            mp.wait_for_timeout(a.wait)
            if not a.keep_cookie_banner:
                dismiss_cookies(mp)
            mp.screenshot(path=os.path.join(a.out, "mobile.png"))
            shots.append("mobile.png")
            m.close()
        browser.close()

    with open(os.path.join(a.out, "extract.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"{a.out}: {len(shots)} screenshots + extract.json")
    fams = ", ".join(x["value"] for x in data["fonts"]["familiesByTextVolume"][:4])
    print(f"  fonts: {fams}")
    print(f"  libraries: {', '.join(data['libraries']) or 'none detected'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
