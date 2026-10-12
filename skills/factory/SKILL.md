---
name: factory
description: Run the software factory. "/factory <feature>" builds a feature end to end (spec → build → check → 4 parallel reviews → approver → squash-merged PR). Also "/factory next", "/factory approve <id>", "/factory rework <id> <feedback>", and bare "/factory" for status.
---

# Software Factory: orchestrator

The session running this skill **is the orchestrator**. It spawns every agent, moves files between steps, and is the only caller of `board.py`. It never writes code, and it never reads diffs or reviews beyond their first lines, which keeps its context small. Agents get their context from files, never from this conversation.

This skill is a sanctioned exception to the global git rules: it may push its own `factory/*` branch, `gh pr create`, and `gh pr merge --squash` that PR once checks pass. Nothing else:
- never `git reset`, `git rebase`, or `--force`, and never `git merge` except the conflict step in **Merge**
- never push `main`/`master`
- never `--auto` or `--admin`
- never `prisma migrate` or `prisma db push`

## Setup (start of every invocation)

Run from the repo's **main checkout**, not a worktree:

```bash
test "$(git rev-parse --git-dir)" = "$(git rev-parse --git-common-dir)" || echo "NOT MAIN CHECKOUT"
REPO="$(git rev-parse --show-toplevel)"; F="$REPO/factory"
BOARD="python3 $HOME/.claude/skills/factory/board.py --dir $F"
```

Shell variables don't survive between Bash calls, so re-derive `REPO`, `F` and `BOARD` (and the job's `WT`, `BASE`, `DEFAULT` from `board.json`) at the start of each call.

If this isn't the main checkout, stop and say so. If `$F/project.md` is missing, do the **first-run setup** below. Otherwise go to the command.

### First-run setup (once per repo)

1. Run `mkdir -p "$F/jobs"`, then `ln -sfn "$HOME/.claude/skills/factory/dashboard.html" "$F/dashboard.html"`.
2. Add `factory/` and `.claude/worktrees/` to `$(git rev-parse --git-common-dir)/info/exclude` unless they're already there. This keeps your tracked `.gitignore` untouched.
3. If `$F/backlog.md` is missing, create it containing `# Backlog` plus one blank line.
4. Detect the project and write `$F/project.md`:
   - Read the repo `CLAUDE.md`/`AGENTS.md`, every `CLAUDE.md` in parent folders up to `$HOME`, and `.claude/rules/*.md` at each of those levels.
   - Then read `package.json` scripts and the lockfile, or `pyproject.toml`/`Makefile`/`go.mod`/`Cargo.toml`.
   - Prefer commands written explicitly in CLAUDE.md. Otherwise use package scripts (`test`, `lint`, `typecheck`, `build`). For TypeScript with no typecheck script, use `npx tsc --noEmit`. Write `none` when a command doesn't exist. Never invent a test runner.

```markdown
# Project profile (written by /factory; edit freely)
- Stack: <language / framework>
- Package manager: <npm|pnpm|yarn|pip|...>
- Install: <command>
- Test: <command|none>
- Typecheck: <command|none>
- Lint: <command|none>
- Build: <command|none>
- Has UI: <yes|no>
- Conventions to read: <absolute paths of every CLAUDE.md / AGENTS.md / rules file found>
- Notes: <anything an agent must know, e.g. "tests need .env">
```

5. Tell the user: `Dashboard: cd factory && python3 -m http.server 8765` → http://localhost:8765/dashboard.html

## Commands

For `approve` and `rework`, load the job from `$F/board.json`: `WT` is its `worktree`, `BASE` is its `base`, and `DEFAULT` is `BASE` with the `origin/` prefix removed. `N` is its `round`.

- **`/factory`** (no args): print each job's `id stage round reason pr` from `$F/board.json`, and the dashboard command.
- **`/factory next`**: run `$BOARD next`. It claims the first `- [ ]` line in `$F/backlog.md` under the board lock, creates the job, and prints `{"id", "feature"}`; two sessions never get the same item. If `id` is null, say the backlog is empty and stop. Otherwise run **New job** from step 1b with `ID=<id>` and that feature text.
- **`/factory <feature text>`**: run **New job**.
- **`/factory approve <id>`**: the job must be `needs-human`. **refuse** (and suggest `/factory rework <id> "<feedback>"` instead) if the job has no `worktree`, has no commits beyond `BASE` (`git -C "$WT" log --oneline "$BASE"..HEAD` is empty), or its reason starts `blocked` or `spec writer`; there is nothing approved to merge. If the reason contains `Hard stop: schema`, remind the user to run `/trevskills-migrate` in the worktree first, and stop until they confirm. Then write `$F/jobs/<id>/human-approval.md` containing `Approved by Trevor <ISO date>` and run **Merge**.
- **`/factory rework <id> <feedback>`**: append `## <ISO date>\n<feedback>` to `$F/jobs/<id>/rework.md`. Run `$BOARD set <id> stage=build reason= limit=<round+2>`. If the worktree is gone, recreate it from the branch with `git worktree add "$REPO/.claude/worktrees/factory-<id>" factory/<id>`. Resume the builder (see **Resuming the builder**) pointing it at `rework.md`, then continue at **Check gate**.

## New job

1. `ID=$($BOARD new "<title>")`. The title is the feature's first line, at most 60 characters.
   1b. Write the full feature text to `$F/jobs/$ID/feature.md`.
2. **Base:** run `git fetch origin` (skip it if there is no remote). `DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's#^origin/##')`, then `BASE=origin/$DEFAULT`. With no remote, use the current branch, but only if it's `main` or `master`; otherwise stop. Run `$BOARD set $ID base=$BASE`.
3. **Spec:** spawn `factory-spec-writer` and wait for it. Prompt:
   ```
   JOB_DIR=$F/jobs/$ID
   WORKTREE=none
   BASE=$BASE
   ROUND=0
   PROJECT=$F/project.md
   Write spec.md for this job.
   ```
   If `spec.md` is missing afterwards, spawn it once more. If it's still missing, set `stage=needs-human reason="spec writer produced nothing"` and stop.
4. **Worktree:**
   ```bash
   WT="$REPO/.claude/worktrees/factory-$ID"
   git worktree add "$WT" -b "factory/$ID" "$BASE"
   for e in "$REPO"/.env*; do [ -e "$e" ] && ln -sfn "$e" "$WT/$(basename "$e")"; done
   ```
   Then `$BOARD set $ID worktree=$WT stage=build`.
5. **Build:** spawn `factory-builder` and wait for it. Name it `builder-$ID` if the Agent tool accepts a name. Prompt: the 5 lines with `WORKTREE=$WT` and `ROUND=0`, plus `Implement spec.md. Write build.md.` Record the returned agent id/name with `$BOARD set $ID builder=<id>`. If `build.md` starts `STATUS: BLOCKED`, run `$BOARD set $ID stage=needs-human reason="blocked: <first reason line>"` and stop.
6. Continue at **Check gate**.

## Check gate

1. `N = round + 1` (round as stored on the board). Run `mkdir -p $F/jobs/$ID/round-$N`, then `$BOARD set $ID round=$N stage=check`.
2. In `$WT`, run each of Test / Typecheck / Lint / Build from `project.md` that isn't `none`. Also run `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)\.env'`; any output is a failure ("committed .env file").
3. Write `round-$N/check.md`: first line `CHECK: PASS` or `CHECK: FAIL`, then for each command its exit code and the last 40 lines of output in a fenced block.
4. If it says FAIL, resume the builder with `Checks failed: read JOB_DIR/round-N/check.md, fix, commit, update build.md.` Then re-run steps 2–3, overwriting `check.md`. Allow up to **3** fix attempts. If it still fails, skip the review and go to **Approve**; the approver rules on the failing check.
5. If it says PASS, go to **Review**.

## Review (WAIT FOR ALL)

1. Run `$BOARD set $ID stage=review`.
2. Spawn **all four reviewers in ONE message**, in the background: `factory-review-security`, `factory-review-ux`, `factory-review-ui`, `factory-review-code`. Each gets the 5 lines with `ROUND=$N` plus `Review this round. Write only your own review file.`
3. **WAIT FOR ALL.** Do nothing else until all four have completed. Then run `$BOARD sync $ID`.
   - `complete` must be `true`. If a file is missing, re-spawn only that reviewer, once. If it is still missing after the re-spawn, write that file yourself as `VERDICT: CHANGES` plus `Reviewer produced no output.`, then run `$BOARD sync $ID` again.
   - If `invalid` is non-empty, delete those files and re-spawn those reviewers, once. If they come back invalid again, treat them as CHANGES.
   - **Never resume the builder mid-round.**
4. Route:
   - `verdict` is `PASS`: go to **Approve**.
   - `verdict` is `CHANGES` and `round < limit`: resume the builder with `Review round N has CHANGES: read every review-*.md in JOB_DIR/round-N/, fix blocking findings, commit, update build.md.` Run `$BOARD set $ID stage=build`, then go to **Check gate**.
   - `verdict` is `CHANGES` and `round >= limit`: go to **Approve**.

## Approve

1. Run `$BOARD set $ID stage=approve`. Spawn `factory-approver` and wait for it. Prompt: the 5 lines plus `Decide this job. Write decision.md.`
2. Copy `decision.md` into `round-$N/decision.md`; that's how the approver later sees whether REWORK has already been used. Run `$BOARD sync $ID` and read `decision`.
3. Append the `## Follow-ups` bullets in `decision.md` to the backlog with `$BOARD backlog-add "<item> (from $ID)" ...`, one argument per bullet. The lock keeps parallel sessions from clobbering each other.
4. Route:
   - `APPROVE`: go to **Merge**.
   - `REWORK` and sync's `"reworks"` is greater than 1: the approver broke the once-only rule. Run `$BOARD set $ID stage=needs-human reason="approver requested second rework"` and stop.
   - `REWORK` (first time): run `$BOARD set $ID limit=$((N+1)) stage=build`. Resume the builder with `The approver requested rework: read JOB_DIR/decision.md (Rulings marked fix-now), fix, commit, update build.md.` Then go to **Check gate**.
   - `ESCALATE` or `INVALID`: run `$BOARD set $ID stage=needs-human reason="<second line of decision.md>"`. Report and stop. For INVALID, use reason `approver output unreadable`.

## Merge (APPROVE, or /factory approve)

The steps below reuse the lessons from `/trevskills-commitpush`.

1. **Preconditions:**
   - `command -v gh && gh auth status` must succeed. If not, run `stage=needs-human reason="gh unavailable; branch factory/$ID is local"` and stop.
   - `git -C "$WT" status --porcelain` must be empty. If it isn't, resume the builder once with `Commit or remove uncommitted changes.` If it is still dirty, run `$BOARD set $ID stage=needs-human reason="worktree dirty"` and stop.
   - **Schema guard (deterministic; doesn't rely on any model):** if `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)prisma/(schema\.prisma|migrations/)|\.sql$'` prints anything and `$F/jobs/$ID/human-approval.md` doesn't exist, run `$BOARD set $ID stage=needs-human reason="Hard stop: schema — <first matching file>"` and stop. Run this guard again right before step 6, because CI-fix commits skip the approver.
2. Run `$BOARD set $ID stage=merging`. Then `git -C "$WT" push -u origin "factory/$ID"`. That pushes the factory branch only.
3. **PR.** Run `gh pr view "factory/$ID" --json number,url,state`:
   - `OPEN`: reuse it.
   - `MERGED`: run `stage=done` and stop.
   - `CLOSED`: run `stage=needs-human reason="PR was closed by someone"` and stop.
   - No PR, or reusing one: the title is the decision.md `Merge summary` title. If there is no Merge summary (a human-approved ESCALATE), use the job title and the spec's acceptance criteria as bullets. Either way write the body to `BODY=$F/jobs/$ID/pr-body.txt`, which is also used in step 6. Write the body to that file and pass it with `--body-file`. The body is the Merge summary bullets, then `Approved by the factory approver. Spec, reviews and decision: factory/jobs/$ID/`, then a line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Create it with `gh pr create --base "$DEFAULT" --head "factory/$ID" --title "<Merge summary title>" --body-file "$BODY"`.

   Then `$BOARD set $ID pr=<url>`.
4. **Checks.** Run this in the **background**, because foreground `sleep` is blocked:
   ```bash
   for i in 1 2 3 4; do out=$(gh pr checks "factory/$ID" --watch --fail-fast --interval 15 2>&1); code=$?
     echo "$out" | grep -q "no checks reported" || break; sleep 20; done; echo "exit=$code"; echo "$out" | tail -40
   ```
   - `exit=0`: continue to step 5.
   - Still "no checks reported": the repo has no CI. Continue, and note "no CI ran" in the final report.
   - Any other failure: write the failing output to `$F/jobs/$ID/ci.md`, resume the builder with `CI failed: read JOB_DIR/ci.md, fix, commit.`, push again, and re-check. Allow at most **2** CI fix attempts. After that, run `stage=needs-human reason="CI failing"` and stop.
5. **Conflicts.** Run `gh pr view "factory/$ID" --json mergeable --jq .mergeable`. If it returns `UNKNOWN`, GitHub is still computing; re-run it in the background every 10 seconds, up to 6 times. If it returns `CONFLICTING`, resolve it. This is the one sanctioned `git merge`, and it only ever goes into this job's own branch. Allow at most **2** attempts; after that, run `stage=needs-human reason="conflicts with $DEFAULT"` and stop. Each attempt:
   1. `git -C "$WT" fetch origin`, then `git -C "$WT" merge "origin/$DEFAULT" --no-edit`.
   2. If that merge itself conflicts, resume the builder with `The default branch was merged into your branch and has conflicts: resolve them, commit, update build.md.`
   3. Run `$BOARD set $ID limit=$((N+1))` and go to **Check gate**. That gives a fresh check and full review round, then the approver, then Merge again, reusing the open PR.
6. **Merge:** re-run the schema guard from step 1. Then `gh pr merge "factory/$ID" --squash --subject "<title> (#<number>)" --body-file "$BODY"`. Never use `--auto`, `--admin` or `--delete-branch`. If the merge fails (branch protection, a required review, anything else), run `$BOARD set $ID stage=needs-human reason="merge refused: <first line of stderr>"` and stop.
7. **Clean up:**
   - Run `git worktree remove "$WT"`. If git refuses because of local changes, leave the worktree in place and mention it.
   - Run `git fetch origin`.
   - Run `$BOARD set $ID stage=done reason=`.

## Resuming the builder

Use SendMessage to the recorded `builder` (the name `builder-$ID`, or the stored agent id) with a message naming the exact file(s) to read. If SendMessage fails because the agent no longer exists (for example after a session restart):
1. Spawn a fresh `factory-builder` with the 5 lines plus `You are resuming this job. Read spec.md, build.md, and <the file(s) above>, then continue.`
2. Run `$BOARD set $ID builder=<new id>`.

The orchestrator never edits code or review files itself.

## Final report

End with the job id, the final stage, the PR URL, rounds used, any follow-ups added to the backlog, and, for needs-human, the exact reason and the next command (`/factory approve <id>` or `/factory rework <id> "<feedback>"`).
