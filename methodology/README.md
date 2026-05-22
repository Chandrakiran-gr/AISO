# AISO Methodology Specifications — Steps 1-3 Subset

This is the focused subset for building the upstream pipeline (onboarding, question generation, scoring, selection).

## Files in this folder

| File | Purpose |
|---|---|
| `pipeline-1.0.md` | THE primary spec for Steps 1-3. Read this first. |
| `versioning-1.0.md` | Bitemporal storage + audit log. Needed for hash-chaining prompts. |
| `execution-1.0.md` | Only Part B (hexagonal seam) is relevant right now. The rest is for the scan engine, which is a later phase. |

## What's NOT here (and why)

The full methodology has 7 other spec files (AVS-1.0, N-sampling-1.0, classifier-1.0, question-bank-1.0, pricing-1.0). Those are for the scan execution and measurement layer — a LATER phase. They are deliberately excluded right now to keep the agent focused.

You will add them back when you start Phases 0-11 (the scan engine).

## Versioning

Each file follows SemVer 2.0. When bumping a version, create a new file (e.g., `pipeline-1.1.md`) rather than overwriting. The old file remains forever for historical reproducibility.

## Cross-references

`pipeline-1.0.md` references the other two:
- versioning-1.0.md — for hash-chaining the generation prompt, scorer prompt, realism filter
- execution-1.0.md (Part B only) — for the hexagonal seam pattern used in adapters
