---
name: art-direction-analyzer
description: Break down the art direction of a live website — typography, color palette, grid and spacing, motion and interactions, imagery — by inspecting the rendered page (computed styles, screenshots, hover states), and save a structured reference file with screenshots for a design inspiration library. Use whenever the user wants to study, deconstruct, scrape or reverse-engineer a site's design, visual identity, UI or motion, save a site as a reference or moodboard entry, or asks "how did they do this" about a website — even without the word "analysis".
license: MIT
compatibility: Best with a browser tool (navigate, screenshot, run JavaScript) or Python Playwright (pip install playwright). Falls back to HTML/CSS source only, which cannot see computed styles or motion.
---

# Art direction analyzer

Reading a page's text tells you nothing about its art direction. You need the **rendered** page: resolved fonts, real colors after CSS variables, actual transition timings, how the composition reads on screen. This skill captures that and turns it into a reference a designer will actually reuse.

## 1. Get the URL(s)

Ask for one if none was given. Several sites → one report per site, never blended: references are compared side by side.

## 2. Capture the live page — pick the best available route

**A. Interactive browser tool** (best: you can see and interact):
1. Navigate, wait until fonts and entrance animations have settled (take a screenshot, check it looks finished).
2. Screenshot the first screen, then scroll 2–3 screens and screenshot each: composition and rhythm change down the page, and scroll animations trigger.
3. Hover a nav link, a primary button and a card; screenshot mid-hover. Motion personality usually lives here.
4. Run `scripts/extract-da.js`: paste the whole file into the JavaScript tool. It returns JSON: typography by role, loaded fonts, type scale, colors ranked by use, CSS variables, spacing, radii, shadows, grid usage, transitions, animations, filters, blend modes, largest images, and detected libraries / site builders (GSAP, Lenis, Webflow, Framer, Three.js…).
5. If an inner page reads very differently (product, about, case study), repeat there. Two or three pages maximum: a representative read, not a crawl.

**B. No interactive browser, but Python Playwright** (headless, also good for batches):
```bash
python3 scripts/capture.py https://site.com -o design-references/site_2026-01-31 --sections 3 --mobile
```
It saves the screenshots (first screen, scrolled screens, hovers, mobile) and `extract.json`, clicking away common cookie banners. **Open and look at every screenshot** before writing: the JSON alone gives numbers, not a design read.

**C. No browser at all** (lowest fidelity):
```bash
python3 scripts/extract_static.py https://site.com -o extract.json
```
Fonts declared, CSS variables, colors, breakpoints, keyframes, libraries from script URLs. No screenshots, no computed styles, no observed motion. State this limitation at the top of the report.

## 3. Write the report

Translate data into a designer's vocabulary. Don't paste raw JSON. Identify typefaces by name when you can (the loaded font list helps; "Neue Haas Grotesk Display" ≠ "Helvetica"), describe the palette as a system (dominant / accent / neutrals and how each is used), and place the site in a wider design language (Swiss editorial, web brutalism, Y2K maximalism, Japanese minimal, neo-corporate, scrapbook, 90s software…). That last step is the real value; the extracted values are evidence.

Write the report in the user's language. Use this structure:

```markdown
# [Site name] — Art direction
**URL**: … · **Captured**: [date] · **Method**: browser / headless / static

## Overview
![First screen](screenshots/01-home.png)
[other screenshots, each with a one-line caption saying what to look at]

## Typography
- Typefaces by role (display / text / UI), with names and likely foundry when known
- Scale: sizes from biggest to smallest, ratio between display and text, weights, line height, tracking
- Distinctive treatments (all caps, extreme sizes, tight leading, italics, variable axes, mixing serif and grotesk…)

## Color
- Dominant / accent / neutrals with hex values
- Logic of use (accent only on CTAs, background changes per section, inverted sections…)

## Layout & composition
- Grid (columns, margins, max width), section rhythm
- Recurring spacing values, density, use of empty space
- Alignment habits, hierarchy, what breaks the grid on purpose

## Motion & interaction
- Libraries / site builder detected
- Transition durations and easings
- Notable effects: hover, scroll, page load, page transitions, cursor

## Imagery & graphic language
- Photo / illustration / 3D / type-only; treatment (grain, duotone, cut-outs, crops)
- Icons, shapes, recurring graphic devices

## In one line
[2–4 sentences placing the site in a design language, and what makes it memorable]

## Ideas to take
[2–4 concrete, transferable moves for the user's own work — not a summary of the above]
```

Keep "In one line" and "Ideas to take" closer to a design-school critique than marketing copy: specific, a little opinionated.

## 4. Save it as a reference, not a chat message

```
design-references/<site-slug>_<YYYY-MM-DD>/
├── report.md
├── extract.json
└── screenshots/
    ├── 01-home.png
    └── …
```

Deliver the folder (or report + screenshots) as files, and suggest the user moves it into wherever they keep references (a folder, Are.na, Notion, Figma).

## Notes

- Capture everything in one pass (type, color, layout, motion, imagery). Don't ask which aspects to analyze: a partial reference is much weaker.
- Login walls, bot protection or heavy cookie walls: say plainly what blocked you and report what you could get. Never guess values you couldn't observe.
- Font names in `extract.json` can be aliases (sites rename files, e.g. "Font1"). Cross-check with the screenshot and the `@font-face` sources before naming a typeface.
- This is for study and inspiration. If the user wants to reuse fonts, photos or code from a site, remind them those usually need a license.
