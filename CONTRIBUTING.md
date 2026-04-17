# Contributing to Integrated AI

This document defines how we work in this repo. Follow these rules on every piece of work — no exceptions.

---

## Golden Rule: Never Push Directly to `main`

`main` is protected. Every change goes through a Pull Request, no matter how small.

---

## Branching Strategy

We use **feature branches**. Every piece of work lives on its own short-lived branch.

### Branch naming

| Type | Pattern | Example |
|---|---|---|
| New feature | `feature/<short-description>` | `feature/analysis2-competitor-scoring` |
| Bug fix | `fix/<short-description>` | `fix/collect-timeout-handling` |
| Client work | `client/<client-slug>` | `client/credimax-query-expansion` |
| Chores / config | `chore/<short-description>` | `chore/update-gitignore` |

Keep names lowercase, hyphen-separated, concise (3–5 words max).

### Workflow

```
1. Start from an up-to-date main
   git checkout main
   git pull origin main

2. Create your branch
   git checkout -b feature/my-thing

3. Do your work — commit often (see commit format below)

4. Push your branch
   git push origin feature/my-thing

5. Open a Pull Request on GitHub (main ← your branch)

6. CI runs automatically — fix anything that fails

7. Review your own PR description, then merge

8. Delete the branch after merge
```

---

## Commit Message Format

Use the **Conventional Commits** format:

```
<type>: <short summary>

[optional body — what and why, not how]
```

### Types

| Type | Use for |
|---|---|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `chore` | Tooling, config, dependency updates |
| `docs` | Documentation only |
| `refactor` | Code restructure, no behavior change |
| `test` | Adding or fixing tests |
| `client` | Client folder data / bank updates |

### Examples

```
feat: add --limit flag to collect1.2

fix: handle consecutive empty responses in collect

chore: harden .gitignore for aisodata CSVs

client: expand credimax query_template_bank

docs: add setup instructions to README
```

---

## Pull Request Checklist

Before merging, confirm:

- [ ] Branch is up to date with `main` (`git pull origin main` before pushing)
- [ ] CI is green (syntax check passes)
- [ ] No secrets or API keys in the diff
- [ ] Large data CSVs are NOT included (add to Google Drive instead)
- [ ] PR description explains *what* and *why* (not just "updated files")

---

## What Lives in Git vs. Google Drive

| Artifact | Where |
|---|---|
| Source code (`.py`, `.html`, `.css`, etc.) | ✅ Git |
| Config/schema files (`config.json`, `datafile.json`, `*.csv` bank files) | ✅ Git |
| Query/value bank CSVs (`query_template_bank.csv`, `value_bank.csv`) | ✅ Git |
| Generated pipeline output (`*_aisodata*.csv`) | 📁 Google Drive |
| Large benchmark datasets (`benchmark_data_*.csv`) | 📁 Google Drive |
| `.env` files with real keys | ❌ Never committed |

---

## Working with AI Agents (Cursor / Claude Code)

- AI agents (Claude, Cursor) work on feature branches only — never directly on `main`
- Agent commits must follow the same commit format above
- Treat agent-generated code like any other PR: read the diff before merging
