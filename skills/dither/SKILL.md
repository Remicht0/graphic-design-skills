---
name: dither
description: Turn photos and images into dithered, halftoned or bitmap graphics (Floyd–Steinberg, Atkinson, Bayer, halftone dots, duotone, risograph-style color) as PNG or SVG, sized for screen or print. Use when the user wants a dithered, 1-bit, pixel, halftone, newspaper, risograph, screen-print or "old Mac" look, a bitmap/trame effect, or an image prepared for laser engraving or a plotter.
license: MIT
compatibility: Needs Python 3.9+ with Pillow and NumPy (pip install pillow numpy).
---

# Dither

Turns any image into a dithered or halftoned bitmap with `scripts/dither.py`. The script does the pixel work; your job is choosing the method, the dot size and the palette so the result reads well at its final size, and checking it visually before handing it over.

## Workflow

1. **Get the image and its destination.** Where will it live: Instagram post, poster, t-shirt print, laser engraving, a web hero? The destination decides the dot size and the format (see "Sizing").
2. **Make a contact sheet first** when the user has not named a method. It renders all 14 methods side by side in about a second:
   ```bash
   python3 scripts/dither.py input.jpg --compare -o compare.png --width 320 --scale 2
   ```
   Look at it and pick the 1–2 methods that suit the image and the intent. If the user is around, show them the sheet.
3. **Render the final** at the right size, then **look at the output** (open the PNG) before delivering. Check that faces, text and the subject's edges are still readable. If not, see "Fixing a weak result".
4. Deliver the file with one line on the settings used (method, width, palette), so the user can ask for variations.

## Choosing a method

| Look wanted | Method | Notes |
|---|---|---|
| Classic, organic grain | `floyd-steinberg` | Safe default. Add `--serpentine` to remove diagonal "worms". |
| Old Mac / editorial bitmap, punchy | `atkinson` | Drops some shadow and highlight detail, so contrast feels higher. Great on portraits of objects and bold shapes. |
| Smoothest gradients | `jjn`, `stucki`, `sierra` | Wide kernels, best for skies and skin-like gradients. |
| Retro grid, pixel art, games | `bayer4`, `bayer8` | Ordered patterns: regular cross-hatch, very graphic, tile well. Also the most stable in animation (no flicker between frames). |
| Newspaper, risograph, screen print | `halftone` | Real round, square or line dots at a screen angle (`--dot`, `--angle`, `--cell`). |
| Poster / stencil | `threshold` | No dithering; pair with `--contrast`. |
| Grainy, photocopy noise | `random` | Use `--seed` for reproducible output. |

## Palettes and color

- Default is pure black and white. `--levels 4` gives 4 grays.
- **Duotone:** pass two colors, ink first or last, it doesn't matter (they are sorted by lightness): `--palette "#1F2BD1,#F3F2EE"`. This is usually the most "designed" result: an ink color on an off-white paper.
- **Presets:** `bw`, `gray4`, `gray8`, `rgb8`, `riso`, `newsprint`, `blueprint`. `python3 scripts/dither.py --list` prints them.
- **Color dithering:** `--color --palette riso` (or any list of 3+ hex colors) dithers in color, mixing the palette dots optically. Works best with error diffusion methods and a palette that contains a dark, a light, and 2–3 saturated colors.

## Sizing (the part people get wrong)

`--width` is the number of dots across. Fewer dots = bigger, more visible pixels. `--scale` then enlarges each dot with nearest-neighbour so it stays perfectly crisp.

- **Screen:** final pixel width ÷ scale = width. A 1080 px Instagram post with chunky dots: `--width 270 --scale 4`. With fine grain: `--width 540 --scale 2`.
- **Print:** decide the visible dot size first. For a poster 50 cm wide printed at 300 dpi (5906 px) with dots of about 1 mm: `--width 500 --scale 12` (500 dots × 12 = 6000 px). Never upscale the PNG afterwards with smooth resampling: the dots would blur.
- **Halftone** works at output resolution: give the final pixel size with `--width` (and `--scale 1`), and set the dot pitch with `--cell` in pixels. At 300 dpi, `--cell 12` ≈ 25 lines per inch, a visible "pop art" screen; `--cell 6` ≈ 50 lpi, a newspaper look.
- **SVG** (`-o out.svg`) gives vector squares, perfect for laser engraving, vinyl cutting, plotters or infinite scaling. Keep `--width` small (under ~400) or the file gets heavy; the script warns above 250k rectangles.

## Fixing a weak result

- Subject lost in mush → reduce `--width` less aggressively, add `--sharpen`, or raise `--contrast 1.2`.
- Too dark overall (common with dithering) → `--gamma 1.3` or `--brightness 0.08`.
- Shadows blocked in Atkinson → switch to `floyd-steinberg` or lift with `--gamma`.
- Busy background competing with the subject → crop first, or remove the background before dithering.
- White subject on white paper disappears → add `--invert` or pick a darker paper color.

## Examples

```bash
# Instagram square, chunky Atkinson duotone
python3 scripts/dither.py photo.jpg -o post.png -m atkinson --width 270 --scale 4 --palette "#111111,#E9E7E1"

# A3 poster (297 mm @ 300 dpi ≈ 3508 px), round halftone dots at 45°
python3 scripts/dither.py photo.jpg -o poster.png -m halftone --width 3508 --cell 14 --angle 45

# Risograph-style color
python3 scripts/dither.py photo.jpg -o riso.png -m floyd-steinberg --color --palette riso --width 600 --scale 2 --serpentine

# Vector file for laser engraving
python3 scripts/dither.py logo.png -o engrave.svg -m bayer4 --width 240
```
