# Project Instructions for Claude Code

## Role
You are an autonomous coding agent working in parallel with a human developer using Cursor IDE.

## Workflow
- The human handles: quick edits, inline completions, UI tweaks, small fixes via Cursor
- You handle: multi-file refactors, complex features, migrations, tests, CI/CD tasks

## Rules
- Always read existing code before making changes
- Run tests after any significant change
- Use git to commit logical units of work with clear messages
- Ask for clarification before making irreversible changes (e.g. deleting files, dropping DB tables)
- Never overwrite files the human is actively editing — check git status first

## Stack
- Python: SBACO (webish, aio_benchmark), playground scripts
- Web: HTML/CSS (Santa_Barbara_Common_Ground site), Firebase
- Tooling: Node/npm, git
