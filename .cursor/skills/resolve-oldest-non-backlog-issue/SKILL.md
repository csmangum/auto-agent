---
name: resolve-oldest-non-backlog-issue
description: >-
  Finds the oldest open GitHub issue in the repo that does not have the backlog label,
  implements the fix or agreed scope, runs tests, and closes the loop with a PR or
  issue comment. Use when the user wants to pick off the next triaged issue, resolve
  the oldest non-backlog GitHub issue, or work the issue queue excluding backlog.
---

# Resolve oldest non-backlog GitHub issue

## When this applies

Use this workflow when the user (or task) asks to work the **oldest** open issue **excluding** items labeled **`backlog`** (or `BACKLOG_LABEL` from the helper script).

## 1. Select the issue

From the repository root, run:

```bash
./scripts/gh-oldest-open-issue-not-backlog.sh
```

- Prints one JSON object: `number`, `title`, `createdAt`, `url`, `labels`.
- Exits **1** if no matching issue exists.
- URL only: `./scripts/gh-oldest-open-issue-not-backlog.sh --url`
- Exclude a different label: `BACKLOG_LABEL=triage ./scripts/gh-oldest-open-issue-not-backlog.sh`

If the script is missing, equivalent:

```bash
gh issue list --state open --limit 500 --json number,title,createdAt,url,labels \
  | jq '[.[] | select([.labels[]?.name] | all(. != "backlog"))] | sort_by(.createdAt) | .[0]'
```

Requires `gh` authenticated for the repo; respects the current directory’s GitHub remote.

## 2. Understand the issue

```bash
gh issue view <number>
```

Read the full body, acceptance criteria, linked issues/PRs, and comments. Skim related code paths before coding.

## 3. Triage before coding

| Situation | Action |
|-----------|--------|
| Duplicate / already fixed on `main` | Comment with evidence; close or ask to close |
| Wrong repo or external-only work | Comment; do not change this codebase |
| Epic larger than one PR | Implement one vertical slice that matches the issue’s scope; note follow-ups in the PR body |
| Unclear requirements | Ask the user 1–2 concrete questions |

## 4. Implement and verify

- Follow [AGENTS.md](/AGENTS.md): focused diff, project test commands, Ruff/mypy if the repo uses them.
- Prefer closing the issue in GitHub via PR: body or title references `Fixes #N` / `Closes #N` when appropriate.
- Run the relevant tests for the touched area; do not merge without a green run for the scope you changed.

## 5. Close the loop

- Open a PR (`gh pr create`) or push the branch per team practice.
- If the issue is only partially addressed, comment on the issue with what shipped and what remains.
- Do not label issues `backlog` as part of this workflow unless the user asked to triage.

## Notes

- **Oldest** = minimum `createdAt` among open issues after filtering.
- Label match is **exact** (`backlog` ≠ `Backlog` unless GitHub stores that casing—use `BACKLOG_LABEL` to match the repo).
- Issues with **no** labels are included (they are not backlog).
