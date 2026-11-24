# Contributing

Thanks for helping! This repo collects agent skills for graphic design work. You don't need to be a developer: the most valuable part of a skill is the design knowledge in its `SKILL.md`. Issues and pull requests in French are welcome too.

## Ways to help

- **Add a skill** from the [wanted list](#skills-wed-love-to-have) or your own idea. Open an issue first ("Skill idea" template) so we can agree on the scope.
- **Improve a skill**: better instructions, a new option, a fix for a case it handles badly.
- **Report a bug**: attach the input file if you can (or a small one that reproduces it) and the exact command.
- **Show what you made** with the skills in Discussions. Real examples help everyone write better instructions.

## Anatomy of a skill

```
skills/<skill-name>/
├── SKILL.md          required: frontmatter + instructions
├── scripts/          optional: code the agent runs (Python preferred)
├── assets/           optional: files used in outputs (CSS, templates, profiles…)
└── templates/        optional: starting points
```

`SKILL.md` starts with YAML frontmatter ([Agent Skills format](https://agentskills.io)):

```yaml
---
name: skill-name            # = folder name; lowercase, digits, hyphens; max 64 chars
description: What it does, and when to use it. Name the words people actually say ("halftone", "is my file OK for print"). Max 1024 chars.
license: MIT
compatibility: What it needs to run (Python packages, a browser…).
---
```

The description is how an agent decides to load your skill, so it matters more than anything else: say what the skill does **and when to use it**, with the user's vocabulary.

Copy [`template/SKILL.md`](template/SKILL.md) to start.

## Writing a good SKILL.md

- **Write for a smart colleague who isn't a designer.** Explain the judgement calls (which method for which look, what to check before delivering), not what any model already knows.
- **Workflow first, reference after.** Numbered steps an agent can follow, then tables and recipes.
- **Always include a "look at the result" step.** Agents should open the image or PDF they made before handing it over.
- **Be honest about limits**: what the script can't detect, when to send the user to a professional tool.
- **Keep it under ~300 lines.** Move long references to a separate file in the skill folder and link to it.
- **Plain language, short sentences.** Many users are students or freelancers, often not native English speakers.

## Scripts

- Python 3.9+, standard library first; allowed dependencies: Pillow, NumPy, pikepdf, Playwright. Ask in the issue before adding another one.
- A command-line interface with `--help`, examples in the docstring, clear error messages.
- No network access unless that's the point of the script (and say so in `SKILL.md`). No telemetry, no API keys.
- Only assets you made yourself or that are CC0 / public domain / OFL, with credits in the README.
- Add a test to `tests/test_skills.py` that runs the script on a small generated input.

## Before opening a pull request

```bash
pip install pillow numpy pikepdf reportlab playwright pytest
python3 scripts/validate.py      # frontmatter, names, links, marketplace and README lists
python -m pytest -q              # script tests (the layout test needs Chromium)
```

New skill? Also add it to the table in `README.md` and run `python3 scripts/validate.py --fix-marketplace` to list it in `.claude-plugin/marketplace.json`.

## Skills we'd love to have

Good first contributions, from small to large:

- **type-pairing**: suggest font pairings (free fonts) for a brief, with a specimen page.
- **social-export**: one visual → every social format (feed, story, banner, thumbnail) with safe zones.
- **color-blindness**: simulate protanopia / deuteranopia / tritanopia on an image or palette and flag confusing pairs.
- **riso-separations**: split an image or design into spot-color layers for risograph or screen printing.
- **mockup**: place artwork onto a product photo (poster on a wall, tee, packaging) with perspective.
- **moodboard**: assemble a grid of reference images with captions and credits.
- **brand-guidelines**: turn a logo, palette and fonts into a short brand book PDF (could build on editorial-layout).
- **vectorize**: trace a bitmap into clean SVG paths.
- **zine-imposition**: reorder pages of a PDF for folding and booklet printing.

Improvements to existing skills:

- palette: APCA contrast, Procreate `.swatches` export, CMYK suggestions.
- dither: blue-noise, line / crosshatch and stochastic screens, CMYK halftone separations.
- print-preflight: small text check, overprint check, ink coverage of RGB artwork (needs rendering).
- editorial-layout: an A4 portrait report template, a 16:9 deck template, a poster template.

## Code of conduct

Be kind and constructive; critique the work, not the person. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
