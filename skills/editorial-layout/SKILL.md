---
name: editorial-layout
description: Design editorial, magazine-style PDF layouts in HTML/CSS — briefs, reports, portfolios, zines, presentations, posters, Instagram carousels — on a 12-column print grid with extreme type scale, one accent color, bleeding images and varied compositions, then render to a print-ready PDF (with bleed) plus PNG previews and automatic layout checks. Use whenever the user wants a document, PDF, deck, booklet or boards that look designed rather than templated, or asks for a magazine, editorial or Swiss-style layout.
license: MIT
compatibility: Needs Python 3.9+ and Playwright with Chromium (pip install playwright, then python -m playwright install chromium) or an installed Chrome. Optional - pikepdf (bleed boxes), Pillow (contact sheet), Node.js/npm (offline fonts).
---

# Editorial layout

You write the document as HTML on top of `assets/print.css`, then `scripts/render.py` turns it into a PDF, renders previews and checks the layout. The CSS gives you a page system; the design comes from the rules below. The difference between "designed" and "generated" is almost entirely in those rules, so follow them.

## Setup

```bash
mkdir -p doc/img && cp assets/print.css doc/ && cp templates/example.html doc/index.html
# in doc/index.html, change the stylesheet link to href="print.css"
```

Fonts: the template loads Google Fonts. If the network blocks them (common in sandboxes), download the same families locally; the template already links `fonts/fonts.css`:
```bash
python3 scripts/fonts.py "Anton" "Inter" "Instrument Serif" "JetBrains Mono" --weights 200,400,600 --italic -o doc/fonts
```
`render.py` warns when a font silently fell back to another one. Never deliver with a fallback font.

## The page system (print.css)

- `<section class="page">` = one page. Default A4 landscape; `render.py --format A4|A3|A5|letter|16:9|square|instagram|instagram-portrait|story` (+`-landscape`) or `WxHmm`.
- Each page is a **12 × 8 grid** inside 9 mm margins, 4 mm gutters. Place blocks with `x1–x12` (first column), `w1–w12` (columns spanned), `y1–y8` (first row), `h1–h8` (rows spanned). Align inside a cell with `top / mid / bottom / left / right`, stack with `stack`.
- **Bleed**: `bleed-l / -r / -t / -b / bleed` pull a block from the margin to the cut edge (plus bleed when rendered with `--bleed`).
- **Type**: `.display` (big, uppercase by default; `.low` lowercase, `.thin` light grotesk, `.serif`, `.wrap`, `.outline`), `.lead` (13 pt), `.text` (8.6 pt, max 78 mm wide), `.micro` (6.6 pt mono caps), `.it` (serif italic for one word), `.num` (tabular figures), `.unit` (small unit next to a big number), `.hl` (highlight), `.accent-c` (accent color), `.vertical`.
- **Fit**: `data-fit="1"` on a one-line title makes it exactly fill its block's width (`0.9` = 90 %).
- **Images**: wrap in `<div class="img …">`. `.bw` grayscale, `.duo` duotone on the accent, `.contain`, `.round`, `.pixel` (crisp pixels for dithered images). A PDF keeps an image at its own pixel size, and viewers or printers may smooth small pixel art: upscale dithered images with nearest-neighbour to about 300 ppi at their printed size first (`dither.py --scale`).
- **Pages**: `.page.alt` (inverted ink/paper), `.page.accent` (accent background).
- **Theme**: override `--paper`, `--ink`, `--accent`, `--font-display`, `--font-text`, `--font-serif`, `--font-mono` in a `:root {}` block.

## Design rules

**Scale and type**
- Three levels only: display, text, micro (plus a lead paragraph on text-heavy pages). Display at least 5× the text size. Nothing in between: medium sizes everywhere is the #1 sign of a templated document.
- Break display lines by hand with `<br>`; never leave one word alone on the last line.
- One italic serif word inside a display title, on the word that carries the meaning, at most once or twice per document. Repeated, it becomes a tic.

**Composition**
- One dominant element per page (a giant word, a number, or an image), a little text, and at least 40 % empty space.
- Asymmetry: nothing centered except a cover or a quote. Tension comes from edges: what bleeds off the page, what sits tight against a margin.
- Only display type and images may leave the page. Text never does (`render.py` checks this).
- Keep a recurring marker in the same place on every page, like a micro index `(01) Approach` top-left. It replaces headers and footers.

**Things that make a document look generated — avoid them**
- Generic headers and footers ("Project name · Page 3/12"), navigation bars repeating the table of contents, a "Sources" page nobody asked for.
- Rules and lines separating text blocks, boxes, rounded cards, drop shadows, icons, gradients.
- The same composition repeated with different text. Never use the same layout twice in a row; on a short document (≤ 8 pages), never twice at all.
- A giant decorative number on every page, an italic serif phrase as every section opener, an identical metadata grid on every page.
- Long paragraphs. One short sentence per idea (about 20 words). If in doubt, cut rather than summarize.
- Expected examples. When the content needs references or brands, pick less obvious, verified ones.

**Color**
- One paper, one ink, one accent. Roughly 60 % paper, 30 % ink, 10 % accent, used for one or two things per page. An `alt` page every 3–4 pages gives rhythm.
- All images in a document share one treatment: all black and white, all duotone, all dithered, or all color.

## Compositions to draw from

Mix these; each page should feel different from the previous one.

| Composition | Recipe |
|---|---|
| Giant word off the bottom | `.display` with `data-fit="1"` in an `x1 w12 y6 h3 bottom bleed-b` block |
| Image corner + lead | `.img x1 w7 y1 h5 bleed-l bleed-t`, `.lead` at `x9 w4 y2` |
| Statement | 2–3 display lines at 120–160 pt from `y2`, one `.text` block bottom-right `x9 w3 y7 h2 bottom` |
| Split | image `x1 w6 y1 h8 bleed-l bleed-t bleed-b`, text bottom of `x8 w4` |
| Giant thin number | `.display.thin.num` at 350–500 pt sliding off the right edge, a `.text` caption bottom-left |
| Quote on dark | `.page.alt`, serif display quote `x6 w6`, small round image left |
| Image strip | 3–4 `.img` blocks side by side bleeding off the top, `.micro` captions under each |
| Color / data blocks | blocks bleeding off the bottom, values in `.micro` inside each |
| Vertical label | `.micro.vertical` along a margin, big image on the rest |
| Full-bleed image + word | `.img bleed` filling the page, a display word in paper color on a calm area of the image |

## Workflow

1. **Plan**: document type, audience, page count (brief 6–10, report 10–16, poster 1), format. Write the outline as one line per page with its composition, so no two neighbors match.
2. **Content first**: final, short texts and the images, treated consistently (use the `dither` or `palette` skills if relevant). Look at every image before placing it; file names lie.
3. **Write the HTML**: start from `templates/example.html`, set the theme variables, build each page from the grid classes.
4. **Render and check**:
   ```bash
   python3 scripts/render.py doc/index.html -o doc/doc.pdf --png doc/previews --sheet doc/sheet.png
   ```
   Fix every ❌ and ⚠️ (text overlapping or crossing the edge, missing fonts, blurry images). Then **look at the contact sheet** yourself: rhythm, variety, empty space, alignment. `--grid` overlays the grid on previews to check alignment.
5. **Print**: add `--bleed 3` for anything going to a printer, so edge images extend past the cut and the PDF gets TrimBox/BleedBox, then run the `print-preflight` skill on the PDF. Chrome writes RGB PDFs: fine for digital printing; for offset, the printer or Acrobat converts to CMYK.
6. **Deliver** the PDF with one line naming the direction taken (fonts, palette, compositions), so the next document can reuse or change it.

## Other formats

- **Slides**: `--format 16:9`; same rules, even less text.
- **Instagram carousel**: `--format instagram-portrait` (4:5), render with `--png slides --scale 1`: the social formats are sized so that scale 1 gives exactly 1080 × 1350 px (`instagram` 1080 × 1080, `story` at `--scale 1.5` gives 1080 × 1920). One idea per slide; the first slide carries a giant word.
- **Poster**: one page, `--format A2` or `--format 500x700mm`, `--bleed 3`.
