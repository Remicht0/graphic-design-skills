---
name: print-preflight
description: Check a PDF before it goes to the printer — bleed, trim size, image resolution at placed size, embedded fonts, RGB vs CMYK vs spot colors, total ink coverage, hairlines, transparency, layers and annotations — and explain each problem with the fix for InDesign, Illustrator, Affinity, Canva or Figma. Use whenever the user is about to print something (flyer, poster, business card, book, zine, packaging) or asks "is my file OK for print", "why did the printer reject my file", or wants a PDF checked.
license: MIT
compatibility: Needs Python 3.9+ with pikepdf (pip install pikepdf). Pillow and NumPy optional, for ink coverage of CMYK images.
---

# Print preflight

`scripts/preflight.py` inspects the PDF structure and reports FAIL / WARN / PASS findings in plain language. Your job is to run it with the right settings for the job, then turn the report into a short, prioritized list of fixes the user can actually do in their software.

## Workflow

1. **Ask (or infer) the job** if it isn't clear: what is printed, by whom, and how. It changes the settings:
   | Job | Settings |
   |---|---|
   | Flyer, poster, card at a print shop (default) | `--bleed 3` |
   | Large format (posters > A2, banners) | `--bleed 5 --min-ppi 150 --low-ppi 100` (seen from a distance) |
   | Offset / professional printer | defaults, and treat every RGB warning as a real problem |
   | Home or office printer | `--bleed 0` (they can't print to the edge anyway) |
   | Screen PDF, portfolio, slides | `--target digital` |
   If the printer gave specs (bleed, PDF/X, ink limit), use them: they override everything here.
2. **Run it:**
   ```bash
   python3 scripts/preflight.py file.pdf -o report.md --json report.json [settings]
   ```
3. **Answer with the verdict first**, then only the problems, most serious first, each with its fix. Don't paste the whole report unless asked; send `report.md` as a file if the user wants it.
4. If something can only be judged by eye (does the background really touch the edge? is that image meant to be pixelated?), look at the page: render it to PNG if a tool is available, or ask the user.

## Fixes, by problem

**No bleed / bleed too small.** Backgrounds and images that touch the edge must extend past it by the bleed (usually 3 mm).
- InDesign: Document Setup → Bleed 3 mm, pull edge elements to the red bleed line, then Export PDF → Marks and Bleeds → "Use Document Bleed Settings" + Crop Marks.
- Illustrator: Document Setup → Bleed 3 mm; Save as PDF → Marks and Bleeds.
- Affinity (Publisher/Designer): Document Setup → Bleed; Export PDF → More → "Include bleed".
- Canva: File → View settings → Show print bleed; Download → PDF Print → tick "Crop marks and bleed".
- Figma: no bleed setting. Make the frame 6 mm larger in both directions (e.g. A4 = 216 × 303 mm), keep important content 3 mm inside the trim, and tell the printer the trim size.

**Low image resolution.** The report gives the pixel width needed. Fix by using the original file (not a screenshot or a social-media download), placing the image smaller, or, as a last resort, AI upscaling and checking the result at 100 %. Pixel-art or dithered images are fine if they were made big enough with nearest-neighbour scaling.

**Font not embedded.** Re-export as "PDF (print)" / "High quality print". InDesign and Affinity embed by default unless the font's license forbids it; then convert the text to outlines. Canva and Figma always embed.

**RGB.** Digital print shops convert RGB automatically and it's usually fine. For offset printing or exact brand colors: convert images in Photoshop (Edit → Convert to Profile, the printer's profile, often FOGRA39 / FOGRA51 in Europe, GRACoL / SWOP in the US) and set swatches to CMYK. Warn that very bright RGB blues, greens and oranges cannot be reproduced in CMYK.

**Spot color.** Only correct if the job is printed with that special ink (and paid for). Otherwise: InDesign Swatches → Swatch Options → Color Type "Process", or Ink Manager → "All Spots to Process".

**Total ink over limit.** Dark areas with too much ink smear and dry slowly. Use a standard rich black (60/40/40/100) instead of 100/100/100/100, and convert images with the printer's profile, which caps the total ink.

**Registration color used for content.** It prints with every ink at 100 %. Replace it with black.

**Hairlines.** Lines under 0.25 pt may vanish or break. Set strokes to at least 0.25 pt (0.5 pt for light colors or reversed-out lines).

**Annotations / form fields / layers.** Comments and fields often don't print; layers may print differently. Re-export without comments, flatten form fields, and merge or hide layers deliberately.

**Transparency.** Fine for PDF/X-4 and modern printers. Only if the printer asks for PDF/X-1a, export with that preset (it flattens transparency) and check the result for white lines or color shifts.

## Limits (say so when relevant)

The script reads the PDF's structure; it doesn't render pages. It cannot tell whether content actually reaches the page edge, measure ink coverage of RGB artwork, spot text that is too small or too close to the trim, check overprint settings, or validate full PDF/X conformance. For a critical or expensive job, recommend the printer's own preflight or Acrobat Pro's Preflight as a final check.
