---
name: trevskills-scrum
description: Run the scrum team. "/trevskills-scrum <feature>" builds a feature end to end (spec → build → check → up to 4 parallel reviews → approver → squash-merged PR). Also "/trevskills-scrum next", "/trevskills-scrum approve <id>", "/trevskills-scrum rework <id> <feedback>", and bare "/trevskills-scrum" for status.
---

# Trevskills Scrum: orchestrator

The session running this skill **is the orchestrator**. It spawns every agent, moves files between steps, and is the only caller of `board.py`. It never writes code, and it never reads diffs or reviews beyond their first lines, which keeps its context small. Agents get their context from files, never from this conversation.

This skill is a sanctioned exception to the global git rules: it may push its own `scrum/*` branch, `gh pr create`, and `gh pr merge --squash` that PR once checks pass. Nothing else:
- never `git reset`, `git rebase`, or `--force`, and never `git merge` except the conflict step in **Merge**
- never `git pull` except the one guarded `git -C "$REPO" pull --ff-only` in **Merge** step 7 (Clean up); never stash, merge, reset or switch branches in the main checkout
- never push `main`/`master`
- never `--auto` or `--admin`
- never `prisma migrate` or `prisma db push`

## Setup (start of every invocation)

Run from the repo's **main checkout**, not a worktree:

```bash
test "$(git rev-parse --git-dir)" = "$(git rev-parse --git-common-dir)" || echo "NOT MAIN CHECKOUT"
REPO="$(git rev-parse --show-toplevel)"; F="$REPO/scrum"
B() { python3 "$HOME/.claude/skills/trevskills-scrum/board.py" --dir "$F" "$@"; }
```

Shell variables and functions don't survive between Bash calls, so re-derive `REPO`, `F` and the board function `B` (and the job's `WT`, `BASE`, `DEFAULT` from `board.json`) at the start of each call. `B` is a function, not a string variable, so it works in both bash and zsh.

**Abort:** Trevor can abort a job from the dashboard at any moment. From then on every `B set` or `sync` for it fails with `was aborted`. When you see that, stop immediately: spawn nothing more, push nothing, merge nothing. Report that the job was aborted. Leave its branch, worktree and PR exactly as they are.

If this isn't the main checkout, stop and say so. Run `B register "$REPO"` every time (it's idempotent): that's what puts this repo on the one all-projects dashboard.

**Prerequisites (every command that runs a job: new job, `next`, `start`, `approve`, `rework`; not bare `/trevskills-scrum`).** Before spawning any agent, check:
- `git remote` prints something. If not, stop and tell the user to run `git remote add origin <url>`.
- `command -v gh && gh auth status` succeeds. If not, stop and tell the user to run `brew install gh && gh auth login`.

If `$F/project.md` is missing, do the **first-run setup** below. Otherwise go to the command.

### First-run setup (once per repo)

1. Run `mkdir -p "$F/jobs"`.
2. Add `scrum/` and `.claude/worktrees/` to `$(git rev-parse --git-common-dir)/info/exclude` unless they're already there. This keeps your tracked `.gitignore` untouched.
3. If `$F/backlog.md` is missing, create it containing `# Backlog` plus one blank line.
4. Detect the project and write `$F/project.md`:
   - Read the repo `CLAUDE.md`/`AGENTS.md`, every `CLAUDE.md` in parent folders up to `$HOME`, and `.claude/rules/*.md` at each of those levels.
   - Then read `package.json` scripts and the lockfile, or `pyproject.toml`/`Makefile`/`go.mod`/`Cargo.toml`.
   - Prefer commands written explicitly in CLAUDE.md. Otherwise use package scripts (`test`, `lint`, `typecheck`, `build`). For TypeScript with no typecheck script, use `npx tsc --noEmit`. Write `none` when a command doesn't exist. Never invent a test runner.
   - `UI globs`: start from `*.tsx *.jsx *.css *.scss *.html *.vue *.svelte components/ app/`, keep only the entries the repo actually contains, and write `none` if the repo has no UI. Matching: `*.ext` matches any path ending in `.ext`, an entry ending in `/` matches any path containing that directory as a path component, and any other entry matches that exact path.

```markdown
# Project profile (written by /trevskills-scrum; edit freely)
- Stack: <language / framework>
- Package manager: <npm|pnpm|yarn|pip|...>
- Install: <command>
- Test: <command|none>
- Typecheck: <command|none>
- Lint: <command|none>
- Build: <command|none>
- Has UI: <yes|no>
- UI globs: <space-separated globs|none>
- Conventions to read: <absolute paths of every CLAUDE.md / AGENTS.md / rules file found>
- Notes: <anything an agent must know, e.g. "tests need .env">
```

5. Tell the user this repo is now on the dashboard: open the **Trevskills Scrum** app, or run `python3 ~/.claude/skills/trevskills-scrum/serve.py` from anywhere, then go to http://localhost:8765. One dashboard shows every project.

## Commands

For `approve` and `rework`, load the job from `$F/board.json`: `WT` is its `worktree`, `BASE` is its `base`, and `DEFAULT` is `BASE` with the `origin/` prefix removed. `N` is its `round`.

- **`/trevskills-scrum`** (no args): print each job's `id stage round reason pr` from `$F/board.json`, and the dashboard command.
- **`/trevskills-scrum next`**: run `B next`. It claims the first `- [ ]` line in `$F/backlog.md` under the board lock, creates the job, and prints `{"id", "feature"}`; two sessions never get the same item. If `id` is null, say the backlog is empty and stop. Otherwise run **New job** from step 1b with `ID=<id>` and that feature text.
- Backlog lines look like `- [ ] [5] Text <!-- estimate reason -->`; the `[5]` is Fibonacci difficulty points. Only ever change `backlog.md` through `B` (`next`, `backlog-add`), never by hand-editing it.
- **`/trevskills-scrum <feature text>`**: run **New job**.
- **`/trevskills-scrum start <id>`**: the dashboard's Run now button already claimed a backlog item as job `<id>` and wrote its `feature.md`. Load the job and run **New job** from step 2.
- **`/trevskills-scrum approve <id>`**: the job must be `needs-human`. **refuse** (and suggest `/trevskills-scrum rework <id> "<feedback>"` instead) if the job has no `worktree`, has no commits beyond `BASE` (`git -C "$WT" log --oneline "$BASE"..HEAD` is empty), or its reason starts `blocked` or `spec writer`; there is nothing approved to merge. If the reason contains `Hard stop: schema`, remind the user to run `/trevskills-migrate` in the worktree first, and stop until they confirm. A prompt that says `Trevor confirms /trevskills-migrate has already been run` (sent by the dashboard after he ticked that box) counts as that confirmation. Then write `$F/jobs/<id>/human-approval.md` containing `Approved by Trevor <ISO date>` and run **Merge**.
- **`/trevskills-scrum rework <id> <feedback>`**: append `## <ISO date>\n<feedback>` to `$F/jobs/<id>/rework.md`. Run `B set <id> stage=build reason= limit=<round+2>`. If the worktree is gone, recreate it from the branch with `git worktree add "$REPO/.claude/worktrees/scrum-<id>" scrum/<id>`. Resume the builder (see **Resuming the builder**) pointing it at `rework.md`, then continue at **Check gate**.

## New job

1. `ID=$(B new "<title>")`. The title is the feature's first line, at most 60 characters.
   1b. Write the full feature text to `$F/jobs/$ID/feature.md`.
2. **Base:** run `git fetch origin`. `DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's#^origin/##')`. If `symbolic-ref` fails (no `origin/HEAD`), run `git remote set-head origin -a` and try `symbolic-ref` again. Then `BASE=origin/$DEFAULT`. Run `B set $ID base=$BASE`.
3. **Spec:** spawn `scrum-spec-writer` and wait for it. Prompt:
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
   WT="$REPO/.claude/worktrees/scrum-$ID"
   git worktree add "$WT" -b "scrum/$ID" "$BASE"
   find "$REPO" -maxdepth 1 -name '.env*' | while read -r e; do ln -sfn "$e" "$WT/$(basename "$e")"; done
   ```
   Then `B set $ID worktree=$WT stage=build`.
5. **Build:** spawn `scrum-builder` and wait for it. Name it `builder-$ID` if the Agent tool accepts a name. Prompt: the 5 lines with `WORKTREE=$WT` and `ROUND=0`, plus `Implement spec.md. Write build.md.` Record the returned agent id/name with `B set $ID builder=<id>`. If `build.md` starts `STATUS: BLOCKED`, run `B set $ID stage=needs-human reason="blocked: <first reason line>"` and stop.
6. Continue at **Check gate**.

## Check gate

1. `N = round + 1` (round as stored on the board). Run `mkdir -p $F/jobs/$ID/round-$N`, then `B set $ID round=$N stage=check`.
2. In `$WT`, run each of Test / Typecheck / Lint / Build from `project.md` that isn't `none`. Also run `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)\.env'`; any output is a failure ("committed .env file").
3. Write `round-$N/check.md`: first line `CHECK: PASS` or `CHECK: FAIL`, then for each command its exit code and the last 40 lines of output in a fenced block.
4. If it says FAIL, resume the builder with `Checks failed: read JOB_DIR/round-N/check.md, fix, commit, update build.md.` Then re-run steps 2–3, overwriting `check.md`. Allow up to **3** fix attempts. If it still fails, skip the review and go to **Approve**; the approver rules on the failing check.
5. If it says PASS, go to **Review**.

## Review (WAIT FOR ALL)

1. Run `B set $ID stage=review`.
2. **UI/UX skip (decided from the diff, never from the spec's `UI surface:` line).** If `project.md` has `UI globs` set to something other than `none`, and no file from `git -C "$WT" diff --name-only "$BASE"...HEAD` matches any of them (matching rules are in First-run setup), write `round-$N/review-ui.md` and `round-$N/review-ux.md` yourself, each containing exactly:
   ```
   VERDICT: PASS
   Skipped by orchestrator: no UI files in diff.
   ```
   Then spawn only `scrum-review-security` and `scrum-review-code`. Otherwise (`UI globs` missing or `none`, or any file matches), spawn all four.
3. Spawn the reviewers **in ONE message**, in the background: `scrum-review-security`, `scrum-review-ux`, `scrum-review-ui`, `scrum-review-code` (minus the two skipped in step 2). Each gets the 5 lines with `ROUND=$N` plus `Review this round. Write only your own review file.`
4. **WAIT FOR ALL.** Do nothing else until every spawned reviewer has completed. Then run `B sync $ID`.
   - `complete` must be `true`. If a file is missing, re-spawn only that reviewer, once. If it is still missing after the re-spawn, write that file yourself as `VERDICT: CHANGES` plus `Reviewer produced no output.`, then run `B sync $ID` again.
   - If `invalid` is non-empty, delete those files and re-spawn those reviewers, once. If they come back invalid again, treat them as CHANGES.
   - **Never resume the builder mid-round.**
5. Route:
   - `verdict` is `PASS`: go to **Approve**.
   - `verdict` is `CHANGES` and `round < limit`: resume the builder with `Review round N has CHANGES: read every review-*.md in JOB_DIR/round-N/, fix blocking findings, commit, update build.md.` Run `B set $ID stage=build`, then go to **Check gate**.
   - `verdict` is `CHANGES` and `round >= limit`: go to **Approve**.

## Approve

1. Run `B set $ID stage=approve`. Spawn `scrum-approver` and wait for it. Prompt: the 5 lines plus `Decide this job. Write decision.md.`
   - **Model:** pass the Agent tool override `model: "sonnet"` to `scrum-approver` only when all of these hold: the latest `round-$N/check.md` is `CHECK: PASS`; all four `round-$N/review-*.md` start `VERDICT: PASS` (orchestrator-written skip files count); the Merge schema guard regex matches nothing in the diff; and you know this round was not started by the Merge **Conflicts** step. In every other case (including when you can't tell, e.g. after a session restart) omit the override so the agent's default, Opus, runs.
2. Copy `decision.md` into `round-$N/decision.md`; that's how the approver later sees whether REWORK has already been used. Run `B sync $ID` and read `decision`.
3. Append the `## Follow-ups` bullets in `decision.md` to the backlog with `B backlog-add "<item> (from $ID)" ...`, one argument per bullet. The lock keeps parallel sessions from clobbering each other.
4. Route:
   - `APPROVE`: go to **Merge**.
   - `REWORK` and sync's `"reworks"` is greater than 1: the approver broke the once-only rule. Run `B set $ID stage=needs-human reason="approver requested second rework"` and stop.
   - `REWORK` (first time): run `B set $ID limit=$((N+1)) stage=build`. Resume the builder with `The approver requested rework: read JOB_DIR/decision.md (Rulings marked fix-now), fix, commit, update build.md.` Then go to **Check gate**.
   - `ESCALATE` or `INVALID`: run `B set $ID stage=needs-human reason="<second line of decision.md>"`. Report and stop. For INVALID, use reason `approver output unreadable`.

## Merge (APPROVE, or /trevskills-scrum approve)

The steps below reuse the lessons from `/trevskills-commitpush`.

1. **Preconditions:**
   - `command -v gh && gh auth status` must succeed. If not, run `stage=needs-human reason="gh unavailable; branch scrum/$ID is local"` and stop.
   - `git -C "$WT" status --porcelain` must be empty. If it isn't, resume the builder once with `Commit or remove uncommitted changes.` If it is still dirty, run `B set $ID stage=needs-human reason="worktree dirty"` and stop.
   - **Schema guard (deterministic; doesn't rely on any model):** if `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)prisma/(schema\.prisma|migrations/)|\.sql$'` prints anything and `$F/jobs/$ID/human-approval.md` doesn't exist, run `B set $ID stage=needs-human reason="Hard stop: schema — <first matching file>"` and stop. Run this guard again right before step 6, because CI-fix commits skip the approver.
2. Run `B set $ID stage=merging`. Then `git -C "$WT" push -u origin "scrum/$ID"`. That pushes the scrum branch only.
3. **PR.** Run `gh pr view "scrum/$ID" --json number,url,state`:
   - `OPEN`: reuse it.
   - `MERGED`: run `stage=done` and stop.
   - `CLOSED`: run `stage=needs-human reason="PR was closed by someone"` and stop.
   - No PR, or reusing one: the title is the decision.md `Merge summary` title. If there is no Merge summary (a human-approved ESCALATE), use the job title and the spec's acceptance criteria as bullets. Either way write the body to `BODY=$F/jobs/$ID/pr-body.txt`, which is also used in step 6. Write the body to that file and pass it with `--body-file`. The body is the Merge summary bullets, then `Approved by the scrum approver. Spec, reviews and decision: scrum/jobs/$ID/`, then a line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Create it with `gh pr create --base "$DEFAULT" --head "scrum/$ID" --title "<Merge summary title>" --body-file "$BODY"`.

   Then `B set $ID pr=<url>`.
4. **Checks.** Run this in the **background**, because foreground `sleep` is blocked:
   ```bash
   for i in 1 2 3 4; do out=$(gh pr checks "scrum/$ID" --watch --fail-fast --interval 15 2>&1); code=$?
     echo "$out" | grep -q "no checks reported" || break; sleep 20; done; echo "exit=$code"; echo "$out" | tail -40
   ```
   - `exit=0`: continue to step 5.
   - Still "no checks reported": the repo has no CI. Continue, and note "no CI ran" in the final report.
   - Any other failure: write the failing output to `$F/jobs/$ID/ci.md`, resume the builder with `CI failed: read JOB_DIR/ci.md, fix, commit.`, push again, and re-check. Allow at most **2** CI fix attempts. After that, run `stage=needs-human reason="CI failing"` and stop.
5. **Conflicts.** Run `gh pr view "scrum/$ID" --json mergeable --jq .mergeable`. If it returns `UNKNOWN`, GitHub is still computing; re-run it in the background every 10 seconds, up to 6 times. If it returns `CONFLICTING`, resolve it. This is the one sanctioned `git merge`, and it only ever goes into this job's own branch. Allow at most **2** attempts; after that, run `stage=needs-human reason="conflicts with $DEFAULT"` and stop. Each attempt:
   1. `git -C "$WT" fetch origin`, then `git -C "$WT" merge "origin/$DEFAULT" --no-edit`.
   2. If that merge itself conflicts, resume the builder with `The default branch was merged into your branch and has conflicts: resolve them, commit, update build.md.`
   3. Run `B set $ID limit=$((N+1))` and go to **Check gate**. That gives a fresh check and full review round, then the approver, then Merge again, reusing the open PR.
6. **Merge:** re-run the schema guard from step 1, and run `B sync $ID` right before merging; if it says the job was aborted, stop. Then `gh pr merge "scrum/$ID" --squash --subject "<title> (#<number>)" --body-file "$BODY"`. Never use `--auto`, `--admin` or `--delete-branch`. If the merge fails (branch protection, a required review, anything else), run `B set $ID stage=needs-human reason="merge refused: <first line of stderr>"` and stop.
7. **Clean up:**
   - Run `git worktree remove "$WT"`. If git refuses because of local changes, leave the worktree in place and mention it.
   - Run `git fetch origin`.
   - Run `B set $ID stage=done reason=`.
   - **Restart.** Read the `Restart:` line from `$F/jobs/$ID/decision.md` (no line, e.g. a human-approved ESCALATE without one, counts as `none`). If it is not `Restart: none`, in order:
     1. **Guard:** `git -C "$REPO" symbolic-ref --short HEAD` must equal `$DEFAULT`, and `git -C "$REPO" status --porcelain` must be empty.
     2. **Fast-forward:** if both pass, run `git -C "$REPO" pull --ff-only`.
     3. **Skip on failure:** if a guard check or the fast-forward fails, do not restart. Report `Restart pending: <process> — <reason>`, where reason is `not on <default>`, `uncommitted changes` or `fast-forward failed`. Never merge, reset, rebase or stash to make it work.
     4. **Restart:** stop the old process, found by its port (`lsof -ti tcp:8765 -sTCP:LISTEN | xargs kill`). Start it again the way it was started. For serve.py that is `mkdir -p ~/.claude/trevskills-scrum && nohup python3 ~/.claude/skills/trevskills-scrum/serve.py >> ~/.claude/trevskills-scrum/serve.log 2>&1 &` (as in `app/make-app.sh`); for anything else, the start command named in the `Restart:` line, used as given.
     5. **Verify:** the process answers, e.g. `curl -sf` against the new or changed endpoint returns 200 (retry in the background for a few seconds while it starts).
     A failed restart or verify doesn't change `done`; it is only reported.

## Resuming the builder

Use SendMessage to the recorded `builder` (the name `builder-$ID`, or the stored agent id) with a message naming the exact file(s) to read. If SendMessage fails because the agent no longer exists (for example after a session restart):
1. Spawn a fresh `scrum-builder` with the 5 lines plus `You are resuming this job. Read spec.md, build.md, and <the file(s) above>, then continue.`
2. Run `B set $ID builder=<new id>`.

The orchestrator never edits code or review files itself, except for two sanctioned review files: the UI/UX skip files in **Review** step 2, and the `Reviewer produced no output.` fallback.

## Final report

End with the job id, the final stage, the PR URL, rounds used, any follow-ups added to the backlog, the restart outcome for merged jobs (`restarted + verified`, `restart failed`, `verify failed`, `Restart pending: <process> — <reason>`, or `none`), and, for needs-human, the exact reason and the next command (`/trevskills-scrum approve <id>` or `/trevskills-scrum rework <id> "<feedback>"`).
