---
name: your-skill-name
description: One or two sentences — what the skill does, then "Use when…" with the words people actually say when they need it (e.g. "halftone", "is my file OK for print", "make a moodboard").
license: MIT
compatibility: What it needs to run, e.g. Python 3.9+ with Pillow (pip install pillow).
---

# Skill title

One short paragraph: what the skill produces, and what the agent's job is on top of the script (the judgement part).

## Workflow

1. **Understand the job.** What does the user need, for which destination (screen, print, a specific tool)? Ask only if a wrong guess would be costly.
2. **Do the work.**
   ```bash
   python3 scripts/your_script.py input -o output
   ```
3. **Look at the result** before delivering (open the image / PDF). Check the things that usually go wrong: list them here.
4. **Deliver** the file with one line on the choices made, so the user can ask for variations.

## Choosing options

| If the user wants… | Do this |
|---|---|
| … | … |

## Fixing a weak result

- Symptom → fix.

## Limits

What this skill can't do or detect, and when to recommend a professional tool or a human expert instead.
