# AISO Branching Policy

This repository uses short-lived branches named for the AISO work being done.
Branch names must describe the product area, behavior, or operational change,
not the person, tool, editor, or AI agent that created the branch.

## Branch Lifecycle

One branch is strictly for one pull request only.

Rules:

- Every distinct task starts on a new branch.
- Every branch should map to exactly one PR.
- Once that PR is merged, delete the branch.
- Do not keep committing follow-up tasks to a branch whose PR has already been merged.
- Do not reuse old branch names for consequent work.
- If a task naturally grows into a second task, finish the current PR, merge it, delete the branch, then create a new branch for the next task.

This keeps review history clean and makes each PR easy to reason about.

## Core Rule

Branch names must not contain agent, assistant, tool, editor, or vendor names.

Do not use names such as:

- `codex/...`
- `claude/...`
- `cursor/...`
- `copilot/...`
- `agent/...`
- `assistant/...`
- `ai/...` when it refers to the worker rather than the AISO product domain

Good branch names answer: "What AISO capability or risk is changing?"

## Format

Use:

```text
<type>/<aiso-area>-<short-outcome>
```

Rules:

- Lowercase only.
- Use hyphens between words.
- Keep names concise, usually 3-6 words after the slash.
- Use AISO product language: scans, BYOK, metrics, dashboard, pipeline, auth, security, deployment, clients.
- Avoid personal names, agent names, machine names, editor names, or implementation trivia.

## Allowed Types

| Type | Use For | Example |
|---|---|---|
| `feature` | New user-facing capability | `feature/dashboard-real-metrics` |
| `fix` | Bug fix or behavior correction | `fix/byok-provider-filtering` |
| `security` | Auth, secrets, access control, hardening | `security/proxy-session-validation` |
| `refactor` | Code structure change without intended behavior change | `refactor/scan-metrics-service` |
| `test` | Test coverage or test infrastructure | `test/pipeline-metrics-coverage` |
| `docs` | Documentation only | `docs/branching-policy` |
| `chore` | Tooling, dependency, config, maintenance | `chore/update-python-deps` |
| `infra` | Deployment, CI/CD, hosting, environment setup | `infra/render-api-deploy` |
| `client` | Client-specific query banks or profile work | `client/pemspa-query-bank` |
| `data` | Data schemas, seed data, benchmarks, generated indexes | `data/scan-result-seed-fixtures` |
| `release` | Release preparation | `release/launch-readiness` |
| `hotfix` | Urgent production fix | `hotfix/scan-start-failure` |

Prefer `feature` over `feat` for branch names. Commit messages may still use
Conventional Commit types such as `feat:`, `fix:`, and `docs:`.

## Examples

Good:

```text
feature/metrics-dashboard
feature/onboarding-client-profile
fix/scan-history-fetch-path
security/byok-zero-persistence
refactor/pipeline-result-persistence
test/metrics-endpoint-authorization
infra/vercel-frontend-deploy
docs/runbook-local-development
client/pemspa-scan-config
```

Bad:

```text
codex/metrics-dashboard
claude/fix-dashboard
cursor/onboarding-ui
agent/security-hardening
assistant/pipeline-work
chandrakiran/new-stuff
feature/codex-fixes
fix/claude-bug
```

## Workflow

1. For every new task, start from an up-to-date `main`.

   ```bash
   git switch main
   git pull --ff-only origin main
   ```

2. Create a fresh branch for this task and this PR only.

   ```bash
   git switch -c feature/dashboard-real-metrics
   ```

3. Keep the branch scoped to one logical change and one PR.

4. Commit in small, reviewable units using Conventional Commits.

   ```bash
   git commit -m "feat: wire dashboard to scan metrics"
   ```

5. Run the relevant checks before pushing.

6. Push the branch and open a pull request into `main`.

   ```bash
   git push -u origin feature/dashboard-real-metrics
   ```

7. After the PR is merged, delete the branch locally and remotely.

   ```bash
   git switch main
   git pull --ff-only origin main
   git branch -d feature/dashboard-real-metrics
   git push origin --delete feature/dashboard-real-metrics
   ```

8. Start the next task from a new branch.

## Branch Ownership

Multiple people and tools may contribute to the same branch, but the branch
name remains about the AISO workstream. Ownership should be documented in the
pull request, not encoded in the branch name.

## Emergency Fixes

Use `hotfix/<aiso-area>-<failure>` for urgent production fixes.

Examples:

```text
hotfix/auth-login-redirect
hotfix/scan-runner-timeout
hotfix/metrics-endpoint-500
```

After a hotfix merge, backport or reconcile the fix into any active feature
branches that touch the same area.
