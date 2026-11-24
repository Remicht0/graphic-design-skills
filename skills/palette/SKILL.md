---
name: palette
description: Build, check and export color palettes — extract one from a photo or moodboard, generate tints and shades (50–950) or harmonies in OKLCH, check WCAG contrast, and export to CSS variables, Tailwind, design tokens, Adobe ASE (Illustrator/InDesign/Photoshop), GIMP/Krita GPL or a swatch sheet. Use whenever the user wants a color palette, a color scale, "colors that go with" something, a contrast or accessibility check, or swatches for a design tool.
license: MIT
compatibility: Needs Python 3.9+ with NumPy and Pillow (pip install numpy pillow).
---

# Palette

`scripts/palette.py` does the color math (OKLab/OKLCH, WCAG contrast, k-means extraction) and writes files for design tools. Your job is the design judgement on top: which colors deserve a role, whether the palette actually works for text, and explaining the choices in plain words.

## Commands

```bash
# 1. From an image: dominant colors with their share of the image + a swatch sheet
python3 scripts/palette.py extract photo.jpg -n 6 -o palette.json --sheet palette.png

# 2. Accessibility: which pairs can carry text
python3 scripts/palette.py contrast palette.json
python3 scripts/palette.py contrast "#111111,#F2EFE9,#FF4F12"

# 3. A full scale from one brand color (50 … 950), perceptually even
python3 scripts/palette.py scale "#2D4CB4" --name cobalt --keep -o cobalt.json

# 4. Harmonies: complementary | analogous | triadic | split | tetradic
python3 scripts/palette.py harmony "#FF4F12" --type split

# 5. Export: css | scss | tailwind | tokens | json | ase | gpl | svg | png
python3 scripts/palette.py export palette.json --to ase -o palette.ase
python3 scripts/palette.py export palette.json --to tailwind
```

A palette is a JSON file written by the script, or simply a comma-separated hex list. You can hand-edit the JSON (rename colors, drop one) and feed it back to `contrast` or `export`.

## How to work

1. **Start from the source the user has**: a photo, a moodboard, a logo, an existing brand color, or just a mood in words. For words, propose 4–6 hex values yourself, then run `contrast` on them: never present a palette you haven't checked.
2. **Give every color a job.** A usable palette is not six equal colors. Name roles: background (paper), ink (text), accent (one or two uses per page), plus supporting neutrals. Roughly 60 % background, 30 % ink and neutrals, 10 % accent. `extract` guesses background / ink / accent automatically; correct it when it's wrong (it often picks a large photo area as "background").
3. **Check contrast before delivering.** Body text needs **4.5:1** (WCAG AA); large text (≥ 24 px, or ≥ 18.5 px bold) needs **3:1**; logos and pure decoration are exempt. If ink on background fails, darken the ink or lighten the paper rather than dropping the pairing. Say plainly which pairs are safe for text.
4. **Scales** (`scale`) are for UI and brand systems that need tints. `--keep` keeps the exact brand color at its nearest step and reports which step that is ("your blue is cobalt-700"). Chroma is tapered toward the light and dark ends so tints don't look neon and shades don't look muddy.
5. **Export in the format the user's tool reads**:
   | Tool | Format |
   |---|---|
   | Illustrator, InDesign, Photoshop, Affinity, Procreate (import) | `ase` |
   | Figma | `tokens` (via the Tokens Studio plugin) or paste hex |
   | Web | `css`, `scss`, `tailwind` (v4 `@theme`) |
   | GIMP, Krita, Inkscape | `gpl` |
   | A visual to share | `png` (swatch sheet) or `svg` |

## Notes on judgement

- Photos rarely give a good palette as-is: the k-means result reflects area, not importance. A small red object can matter more than a big grey wall. Look at the image yourself and swap in the color that carries the image's identity.
- Off-whites and off-blacks (#F2EFE9, #151515) feel more designed than pure #FFF and #000, and keep the same contrast ratios almost intact.
- Two saturated colors of the same lightness vibrate when they touch. Check OKLCH lightness (`L` in the table output): if two accents have nearly the same L, separate them or change one.
- For print, these are RGB values. Tell the user to convert to CMYK or Pantone in their layout software with their printer's profile; screen-to-print shifts are normal, especially for bright greens, blues and oranges.
