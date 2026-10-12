# Trevskills Scrum: Spec

A small scrum team you can see working. One Claude Code skill (`/trevskills-scrum`) turns a feature request into a merged pull request using subagents that hand off through markdown files. One HTML dashboard shows it happening. It is installed once and used in every repo under `~/Developer`.

## The loop

```
feature → spec-writer (opus) → builder (opus) → CHECK GATE (test/typecheck/lint/build)
                                   ▲                 │ fail: builder fixes, up to 3 tries
                                   │                 ▼ pass
                                   │   security (opus) · ux · ui · code (sonnet), all in parallel
                                   │                 │ WAIT FOR ALL 4
                                   └─ any CHANGES and round < limit (2): resume the same builder
                                                     │ all PASS, or the round limit is reached
                                                     ▼
                                               approver (opus)
                         APPROVE → push, PR, wait for CI, squash-merge, done
                         REWORK  → one extra round (at most once per job)
                         ESCALATE → needs-human (hard stops only) ◄── /trevskills-scrum approve | /trevskills-scrum rework
```

## Decisions (from Trevor, 2026-10-12)

1. **Where it lives:** its own repo at `~/Developer/repos/trevskills-scrum`. `install.sh` symlinks `skills/trevskills-scrum` and `agents/*.md` into `~/.claude`. Each project gets a gitignored `scrum/` folder holding `board.json`, `jobs/`, `backlog.md`, `project.md`, and a symlink to `dashboard.html`.
2. **UI:** one plain HTML file, no framework and no build step. It uses marked@12.0.2 from cdnjs to render markdown and falls back to `<pre>` if the CDN is unreachable.
3. **Merging:** the scrum may push its own `scrum/*` branch, open a PR, and `gh pr merge --squash` once checks pass. This is the single exception to "nobody merges" in `~/.claude/CLAUDE.md`. There is no local `git merge`, no push to main, and no auto-merge. `reset`, `rebase` and force-push stay blocked.
   - **Conflicts:** if the PR conflicts with the default branch, the orchestrator merges `origin/<default>` into its own `scrum/*` branch, the builder resolves the conflict, and a fresh check and review round runs. After 2 attempts it escalates. This is part of the same CLAUDE.md exception.
4. **Hard stops**, the only reasons to ESCALATE:
   - the diff touches the DB schema or migrations
   - the diff touches money, auth, or secrets
   - the builder is BLOCKED
   - infrastructure the scrum cannot fix itself: `gh` is missing, or conflicts or CI still failing after 2 fix attempts

   The approver decides everything else, including unresolved security findings and new dependencies.
5. **Isolation:** one worktree per job at `.claude/worktrees/scrum-<id>`, on branch `scrum/<id>`.
6. **Check gate before review:** the orchestrator runs the commands detected in `project.md`. When a check fails, the builder fixes it and no human is asked.
7. **Findings:** a reviewer may only answer CHANGES for a `[blocking]` finding with confidence of 80 or more. Matters of taste go under Notes.
8. **Approver at the round limit:** it rules on every open finding. It can fix the finding now through one REWORK, defer it to `backlog.md`, or override it with a reason.
9. **Resuming the builder:** use SendMessage to the recorded builder. If that agent is gone, start a fresh builder from the files.
10. **Repo profile:** the first run writes `scrum/project.md` (language, commands, conventions). Every agent reads it.
11. **Reviewers with no UI work:** if the spec says `UI surface: no`, the ux and ui reviewers PASS immediately.
12. **Lessons kept from /trevskills-commitpush:**
    - resolve the base branch instead of assuming `main`
    - the secret check
    - the build gate
    - commit message format: imperative title plus high-level bullets
    - reuse an open PR
    - write the PR body to a file
    - `gh pr checks --watch --fail-fast` with 3 retries on "no checks reported"

## Rules

- Agents get their context from files, not the conversation, and each agent writes only its own file. The builder also writes code inside its worktree.
- First lines are fixed:
  - each review starts `VERDICT: PASS|CHANGES`
  - `build.md` starts `STATUS: READY|BLOCKED`
  - `check.md` starts `CHECK: PASS|FAIL`
  - `decision.md` starts `APPROVE|REWORK|ESCALATE`
- WAIT FOR ALL: a round is complete only when all 4 review files exist. Never resume the builder mid-round.
- The orchestrator is the only process that writes `board.json`, and it does so only through `board.py`, which uses a file lock and an atomic replace.
- No agent ever runs `prisma migrate`, `prisma db push`, `reset`, `rebase`, or force-push. The only `git merge` anywhere is the orchestrator's conflict step: `origin/<default>` into its own `scrum/*` branch.

## Commands

- `/trevskills-scrum <feature>`: run a new job
- `/trevskills-scrum next`: run the first unchecked item in `scrum/backlog.md`
- `/trevskills-scrum approve <id>`: merge a needs-human job
- `/trevskills-scrum rework <id> <feedback>`: send a job back to the builder
- `/trevskills-scrum`: show the board and the command that serves the dashboard
