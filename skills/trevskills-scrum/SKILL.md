---
name: trevskills-scrum
description: Run the scrum team. "/trevskills-scrum <feature>" builds a feature end to end (spec → build → check → up to 4 parallel reviews → approver → squash-merged PR). Also "/trevskills-scrum next", "/trevskills-scrum approve <id>", "/trevskills-scrum rework <id> <feedback>", "/trevskills-scrum discuss <id> [note]", "/trevskills-scrum askme [1-3] <feature>" (answer questions first, then build), "/trevskills-scrum bigboy <feature>" (plan a big request into 2-5 chained child jobs), "/trevskills-scrum digest" (learn from done jobs; also runs itself after every 10), "/trevskills-scrum run-all" (triage the backlog, then run every open item), and bare "/trevskills-scrum" for status.
hooks:
  PermissionRequest:
    - hooks:
        - type: command
          command: 'python3 "$HOME/.claude/skills/trevskills-scrum/board.py" hook'
          timeout: 5
  PreToolUse:
    - matcher: AskUserQuestion
      hooks:
        - type: command
          command: 'python3 "$HOME/.claude/skills/trevskills-scrum/board.py" hook'
          timeout: 5
  Stop:
    - hooks:
        - type: command
          command: 'python3 "$HOME/.claude/skills/trevskills-scrum/board.py" hook'
          timeout: 5
  UserPromptSubmit:
    - hooks:
        - type: command
          command: 'python3 "$HOME/.claude/skills/trevskills-scrum/board.py" hook'
          timeout: 5
  PostToolUse:
    - hooks:
        - type: command
          command: 'python3 "$HOME/.claude/skills/trevskills-scrum/board.py" hook'
          timeout: 5
---

# Trevskills Scrum: orchestrator

The session running this skill **is the orchestrator**. It spawns every agent, moves files between steps, and is the only caller of `board.py`. It never writes code, and it never reads diffs or reviews beyond their first lines, which keeps its context small. Agents get their context from files, never from this conversation.

This skill is a sanctioned exception to the global git rules: it may push its own `scrum/*` branch, `gh pr create`, and `gh pr merge --squash` that PR once checks pass. Nothing else:
- never `git reset`, `git rebase`, or `--force`, and never `git merge` except the conflict step in **Merge**
- never `git pull` except the one guarded fast-forward (`--ff-only`) of the main checkout in **Merge** step 7 (Clean up), which runs after every merge; never stash, merge, reset or switch branches in the main checkout
- never push `main`/`master`
- never `--auto` or `--admin`
- never `prisma migrate` or `prisma db push` directly. The one way to migrate is invoking `/trevskills-migrate` (Skill tool), and only from **approve** on a `Hard stop: schema` job. Sub-agents never migrate

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

**Prerequisites (every command that runs a job: new job, `next`, `start`, `run-all`, `approve`, `rework`; not bare `/trevskills-scrum`).** Before spawning any agent, check:
- `git remote` prints something. If not, stop and tell the user to run `git remote add origin <url>`.
- `command -v gh && gh auth status` succeeds. If not, stop and tell the user to run `brew install gh && gh auth login`.

If `$F/project.md` is missing, do the **first-run setup** below. Otherwise go to the command.

**Record your terminal** (New job, `start`, `approve`, `rework`, `discuss`; once you know the job id `$ID`). This is what the dashboard's Open terminal button brings to the front. Each field is skipped, never an error, when it isn't usable:

```bash
T=$(ps -o tty= -p $PPID | tr -d ' '); case "$T" in ttys[0-9]*) B set $ID tty=$T ;; esac
case "$TERM_PROGRAM" in Apple_Terminal|iTerm.app|ghostty) B set $ID term=$TERM_PROGRAM ;; esac
```
A tty of `??` or empty, or a `$TERM_PROGRAM` outside that list, sets nothing. The recorded tty is also what the frontmatter hooks (`board.py hook`) match on to mark the job `waiting` while this session waits on Trevor.

### First-run setup (once per repo)

1. Run `mkdir -p "$F/jobs"`.
2. Add `scrum/` and `.claude/worktrees/` to `$(git rev-parse --git-common-dir)/info/exclude` unless they're already there. This keeps your tracked `.gitignore` untouched.
3. If `$F/backlog.md` is missing, create it containing `# Backlog` plus one blank line.
4. Detect the project and write `$F/project.md`:
   - Read the repo `CLAUDE.md`/`AGENTS.md`, every `CLAUDE.md` in parent folders up to `$HOME`, and `.claude/rules/*.md` at each of those levels.
   - Then read `package.json` scripts and the lockfile, or `pyproject.toml`/`Makefile`/`go.mod`/`Cargo.toml`.
   - Prefer commands written explicitly in CLAUDE.md. Otherwise use package scripts (`test`, `lint`, `typecheck`, `build`). For TypeScript with no typecheck script, use `npx tsc --noEmit`. `Dev command:` is the command that starts the local dev server: an explicit one in CLAUDE.md first, then the `dev` package script, otherwise `none`. Write `none` when a command doesn't exist. Never invent a test runner.
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
- Dev command: <command|none>
- Has UI: <yes|no>
- UI globs: <space-separated globs|none>
- Conventions to read: <absolute paths of every CLAUDE.md / AGENTS.md / rules file found>
- Notes: <anything an agent must know, e.g. "tests need .env">
```

5. Tell the user this repo is now on the dashboard: open the **Trevskills Scrum** app, or run `python3 ~/.claude/skills/trevskills-scrum/serve.py` from anywhere, then go to http://localhost:8765. One dashboard shows every project.

## Commands

For `approve` and `rework`, load the job from `$F/board.json`: `WT` is its `worktree`, `BASE` is its `base`, and `DEFAULT` is `BASE` with the `origin/` prefix removed. `N` is its `round`.

- **`/trevskills-scrum`** (no args): print each job's `id stage round reason pr` from `$F/board.json`, and the dashboard command.
- **`/trevskills-scrum next`**: run `B next`. It claims the first `- [ ]` line in `$F/backlog.md` under the board lock, creates the job, and prints `{"id", "feature"}`; two sessions never get the same item. If `id` is null, say the backlog is empty and stop. Otherwise run **New job** from step 1b with `ID=<id>` and that feature text (step 2 records your terminal).
- Backlog lines look like `- [ ] [5] Text <!-- estimate reason -->`; the `[5]` is Fibonacci difficulty points. Only ever change `backlog.md` through `B` (`next`, `backlog-add`, `triage-apply`), never by hand-editing it.
- **`/trevskills-scrum <feature text>`**: run **New job**.
- **`/trevskills-scrum askme [1-3] <feature text>`**: run **New job** with the **Askme** step (1c) at that level. With no level, or a level that is not 1, 2 or 3, use level 2 and treat the whole rest as the feature text.
- **`/trevskills-scrum bigboy <feature text>`**: run **New job** steps 1-2, then `B set $ID lane=bigboy` and go straight to the **BigBoy lane**. No spec writer runs for the parent.
- **`/trevskills-scrum start <id>`**: the dashboard's Run now button already claimed a backlog item as job `<id>` and wrote its `feature.md`. Load the job and run **New job** from step 2. For a BigBoy child (the job has a `parent`; started as `/trevskills-scrum start <child>` by **BigBoy lane** step 3 or by the dashboard's Setup done), run **BigBoy lane** step 4 (Spec refresh) after step 2: it skips step 3 when `spec.md` exists and no refresh is needed.
- **`/trevskills-scrum start <id> askme <1-3>`**: the same, but the dashboard's Run now had Askme set, so it opened this session in a new Terminal window. Load the job and run **New job** from step 1c (Askme) at that level; a missing or bad level means level 2.
- **`/trevskills-scrum approve <id>`**: the job must be `needs-human`. **refuse** (and suggest `/trevskills-scrum rework <id> "<feedback>"` instead) if the job has no `worktree`, has no commits beyond `BASE` (`git -C "$WT" log --oneline "$BASE"..HEAD` is empty), or its reason starts `blocked`, `spec writer` or `obsolete`; there is nothing approved to merge. Also run Merge step 1's **main checkout guard**; while it fails, **refuse** with the same message it would write as the reason (`Uncommitted change in <repo name>: <first files>. Fix: commit + push it (or undo it), then click Approve & merge.` or `<repo name> main checkout is on <branch>, not <default>. Fix: switch it back to <default>, then click Approve & merge.`) and don't write `human-approval.md`. Once it passes, continue. If the reason contains `Hard stop: schema`, Trevor's approve is the go-ahead to migrate: `cd "$WT"` and invoke `/trevskills-migrate` there with args `base=$BASE`, following it exactly. If it stops or any check fails, run `B set <id> stage=needs-human reason="migrate stopped: <one line why>. Fix: fix that cause, then click Approve & merge to run it again."` and stop; never work around it. On success, commit what it generated (`git -C "$WT" add prisma/migrations && git -C "$WT" commit -m "Add migration"`) and `cd "$REPO"`. Skip the migrate step when the prompt says `Trevor confirms /trevskills-migrate has already been run` (sent by the dashboard when he ticks that box). Then **record your terminal** with `ID=<id>`, write `$F/jobs/<id>/human-approval.md` containing `Approved by Trevor <ISO date>` and run **Merge**.
- **`/trevskills-scrum rework <id> <feedback>`**: append `## <ISO date>\n<feedback>` to `$F/jobs/<id>/rework.md`. Run `B set <id> stage=build reason= limit=<round+2>`, then **record your terminal** with `ID=<id>`. If the worktree is gone, recreate it from the branch with `git worktree add "$REPO/.claude/worktrees/scrum-<id>" scrum/<id>`. Resume the builder (see **Resuming the builder**) pointing it at `rework.md`, then continue at **Check gate**.
- **`/trevskills-scrum discuss <id> [<note>]`**: an interactive talk-through before anything goes back to the builder. The dashboard's Discuss first button opens it in a new terminal, with whatever Trevor typed as the note. The job must be `needs-human`. **Record your terminal** with `ID=<id>`. Read only the board `reason`, the first lines and `## Rulings` of `decision.md`, `rework.md`, and `migrate-stop.md` if it exists. Then tell Trevor in plain words:
  1. What is stopping the job.
  2. Whether a rework can clear it. A `Hard stop:` never clears through rework: the builder can fix code, but the approver stops again on the same hard stop. Only `approve` clears it (for `Hard stop: schema`, approve runs `/trevskills-migrate`).
  3. What his note would actually do: change code (rework), give the go-ahead (approve), or neither.

  Discuss until you agree. Spawn nothing, edit nothing and run no command until Trevor picks one. Then carry it out in this session exactly as that command: `approve <id>`, or `rework <id> "<the agreed feedback, written so the builder can act on it>"`. If he picks neither, stop.
- **`/trevskills-scrum digest`**: run **Digest**. The dashboard's Digest now button starts it headless.
- **`/trevskills-scrum run-all`**: run **Run all**. The dashboard's Run all button opens it in a new Terminal window.

## New job

Every needs-human reason is `<what is wrong>. Fix: <exact fix>`, with no double quotes or backticks. For a BigBoy child (the job has a `parent`), every time this run sets the child `stage=needs-human`, also run **BigBoy lane** step 6, so independent children still start.

1. `ID=$(B new "<title>")`. The title is the feature's first line, at most 60 characters.
   1b. Write the full feature text to `$F/jobs/$ID/feature.md`.
   1c. **Askme** (only for `askme` or `start <id> askme`; otherwise skip to step 2). An interactive question round with Trevor, run like **discuss**. **Record your terminal** first. Read `feature.md`, `$F/project.md` and just enough of the repo to know what is unclear. The level sets how many questions; you pick the number within it:
      - level 1 asks only what blocks the build;
      - level 2 asks a moderate number;
      - level 3 is thorough.

      Ask in rounds, in plain words. When an answer is unclear, or contradicts another answer, ask follow-up or different questions before going on. Until the questions are done, spawn no agent, create no worktree and edit no file except `feature.md`. Then append to `$F/jobs/$ID/feature.md`, with one pair per question asked, follow-ups included:
      ```
      ## Q&A
      - Q: <question>
        A: <Trevor's answer>
      ```
      If Trevor says to skip or stop, write the pairs answered so far (nothing at all if there are none) and carry on. The same session then runs the rest of the job (step 2 onward).
2. **Base:** first **record your terminal** (Setup). Then run `git fetch origin`. `DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's#^origin/##')`. If `symbolic-ref` fails (no `origin/HEAD`), run `git remote set-head origin -a` and try `symbolic-ref` again. Then `BASE=origin/$DEFAULT`. Run `B set $ID base=$BASE`.
3. **Spec:** spawn `scrum-spec-writer` and wait for it. Prompt:
   ```
   JOB_DIR=$F/jobs/$ID
   WORKTREE=none
   BASE=$BASE
   ROUND=0
   PROJECT=$F/project.md
   Write spec.md for this job.
   ```
   If `spec.md` is missing afterwards, spawn it once more. If it's still missing, set `stage=needs-human reason="spec writer produced nothing. Fix: click Abort job with Put back in backlog ticked, then run it again."` and stop.
   3b. **Obsolete:** if the first line of `spec.md` starts with `OBSOLETE:` (`head -1 "$F/jobs/$ID/spec.md" | grep -q '^OBSOLETE:'`), the request needs no change, so abort the job yourself. Strip any single quotes from the rest of that line, then run `B abort $ID --reason 'obsolete: <rest of that line>'` and stop: create no worktree and spawn no builder. The final report says the job was auto-aborted as obsolete and why.
   3c. **Lane:** read the `Lane:` line from `spec.md` and run `B set $ID lane=<fast|standard|debug|bigboy>`. Set `lane=debug` when it says exactly `Lane: debug`, whatever the `Hard stops:` and `UI surface:` lines say. Set `lane=bigboy` when it says exactly `Lane: bigboy`, whatever the other header lines say; the job then goes to the **BigBoy lane** and gets no worktree (skip steps 4-6). A BigBoy child (the job has a `parent`) never gets `bigboy`: for it, `Lane: bigboy` counts as `standard`. Set `fast` only when it says exactly `Lane: fast`, the `Hard stops:` line is `none`, and the `UI surface:` line is `no`. Set `standard` in every other case: the line is missing or malformed, or it says `fast` but `Hard stops:` is anything but `none` or `UI surface:` is `yes`.
4. **Worktree:**
   ```bash
   WT="$REPO/.claude/worktrees/scrum-$ID"
   git worktree add "$WT" -b "scrum/$ID" "$BASE"
   find "$REPO" -maxdepth 1 -name '.env*' | while read -r e; do ln -sfn "$e" "$WT/$(basename "$e")"; done
   ```
   Then `B set $ID worktree=$WT stage=build`.
5. **Build:** spawn `scrum-builder` and wait for it. Name it `builder-$ID` if the Agent tool accepts a name. Prompt: the 5 lines with `WORKTREE=$WT` and `ROUND=0`, plus `Implement spec.md. Write build.md.` Record the returned agent id/name with `B set $ID builder=<id>`. If `build.md` starts `STATUS: BLOCKED`, run `B set $ID stage=needs-human reason="blocked: <first reason line>. Fix: type what the builder needs and click Send back to builder."` and stop. If the job's `lane` is `debug`, see **Debug lane** instead of this step.
6. Continue at **Check gate**.

## Run all

Cleans the backlog, then works through every open item as jobs, one after another, with nobody watching. Setup and Prerequisites apply. Trevor stops it by interrupting or closing its Terminal window.

1. Run `B triage-start`. Under the board lock it claims `$F/triage/<id>/` and prints `{"id", "open"}`. If `id` is null, say the backlog is empty and stop.
2. Spawn `scrum-triager` and wait for it. Prompt:
   ```
   TRIAGE_DIR=$F/triage/<id>
   BACKLOG=$F/backlog.md
   PROJECT=$F/project.md
   Write plan.json for this triage.
   ```
   If `$F/triage/<id>/plan.json` is missing afterwards, spawn it once more.
3. Run `B triage-apply <id>`. It merges, retires and estimates under the board lock, skips stale entries, and writes `$F/triage/<id>/report.md` and `$F/triage/latest.md`. If it exits non-zero (including when plan.json is still missing), write `Triage <id> failed: <message>` to `$F/triage/latest.md`, with its error line as the message, and continue. A failed triage never blocks the run.
4. **Loop.** Run `B next`. If `id` is null, stop and give the final report. Otherwise run **New job** from step 1b with `ID=<id>` and that feature text. Whatever the job ends in (done, needs-human, aborted from the dashboard, auto-aborted as obsolete), go back to `B next`. A needs-human job does not stop the loop: Trevor clears it later with approve, rework or discuss. Never ask questions here; there is no Askme step.

The final report lists every job id this run started with its final stage (and for needs-human, its reason), then what the triage merged, retired and estimated (counts from `triage-apply`, or the failure line).

## Fast lane

Applies only while the job's `lane` on the board is `fast`. A job with no `lane`, or `lane=standard`, never reads this section. Same builder, same Check gate; then one diff-only code review and straight to Merge, with no approver.

1. **Promotion (deterministic).** Promoting means running `B set $ID lane=standard` and appending `Promoted to standard: <trigger>` to `$F/jobs/$ID/promoted.md`; the job then continues on the standard path from where it is. A standard job is never set back to fast.
   - **2nd check failure:** a fast job whose `check.md` says `CHECK: FAIL` for the 2nd time in a round is promoted (trigger `check failed twice`). The fix attempts in **Check gate** step 4 then carry on as standard.
   - **After `CHECK: PASS`, before Review**, promote if any of these hold (trigger names the first one hit). This runs again on every round, including after the Merge **Conflicts** step sends the job back to the Check gate:
     - `git -C "$WT" diff --numstat "$BASE"...HEAD` sums to more than 100 added+deleted lines, or any line shows `-` (a binary file);
     - more than 3 files changed (exactly 100 lines or exactly 3 files stays fast);
     - any changed file (`git -C "$WT" diff --name-only "$BASE"...HEAD`) matches the Merge schema guard regex `(^|/)prisma/(schema\.prisma|migrations/)|\.sql$` or `(^|/)\.env`;
     - any changed file matches `UI globs` from `project.md` (matching rules are in First-run setup).
2. **Review.** Run `B set $ID stage=review`. Write `round-$N/review-security.md`, `round-$N/review-ux.md` and `round-$N/review-ui.md` yourself, each containing exactly:
   ```
   VERDICT: PASS
   Skipped by orchestrator: fast lane.
   ```
   Spawn only `scrum-review-code`, with the 5 lines (`ROUND=$N`), the line `LANE=fast`, and `Review this round. Write only your own review file.` Wait for it, then handle `B sync $ID` exactly as **Review** step 4.
3. **Route:**
   - `verdict` is `PASS`: go straight to **Merge**. Spawn no approver; there is no decision.md. The PR uses the no-Merge-summary fallback in Merge step 3 (job title, spec acceptance criteria as bullets), and the body line `Approved by the scrum approver. Spec, reviews and decision: scrum/jobs/$ID/` is replaced by `Fast lane: check gate + code review. Spec and review: scrum/jobs/$ID/`. The schema guard still runs unchanged. With no decision.md, the `Restart:` line counts as `none`.
   - `verdict` is `CHANGES` and `round < limit`: resume the builder as in **Review** step 5, run `B set $ID stage=build`, and go to **Check gate**. The job stays fast.
   - `verdict` is `CHANGES` and `round >= limit`: go to **Approve**, as standard does.

## Debug lane

Applies only while the job's `lane` on the board is `debug`. A job with any other `lane` never reads this section. It replaces New job step 5; Check gate, Review and Approve then run as standard, with the debug additions in **Check gate**.

1. **Diagnose.** Spawn `scrum-debugger` and wait for it. Prompt: the 5 lines with `WORKTREE=$WT` and `ROUND=0`, plus `Reproduce and diagnose. Write assessment.md.`
2. **Validate `$F/jobs/$ID/assessment.md`.** It is invalid when it is missing, its first line is not one of `ASSESSMENT: READY`, `ASSESSMENT: NO_REPRO` or `ASSESSMENT: BLOCKED`, or a READY one lacks a `Repro:` line, a `Repro test:` line or at least one `- ` line under `## Allowed files`, or has a `## Compliance` line containing `conflict`. If invalid, delete it and re-spawn the debugger once. If it is still missing or invalid, run `B set $ID stage=needs-human reason="debugger output unreadable. Fix: click Abort job with Put back in backlog ticked, then run it again."` and stop.
3. **No repro or blocked.** For `ASSESSMENT: NO_REPRO`, run `B set $ID stage=needs-human reason="debug: no repro — <line 2>. Fix: click Abort job; if the bug is real, re-add it to the backlog with exact steps to reproduce it."` and stop. For `ASSESSMENT: BLOCKED`, run `B set $ID stage=needs-human reason="debug: blocked — <line 2>. Fix: click Discuss first."` and stop.
4. **Repro must fail.** Run the `Repro:` command in `$WT`. Write `$F/jobs/$ID/repro-before.md`: first line `REPRO: FAIL` (non-zero exit) or `REPRO: PASS` (exit 0), then `Commit: <git -C "$WT" rev-parse HEAD>`, the exit code, and the last 40 lines of output in a fenced block. If the exit code is 0, run `B set $ID stage=needs-human reason="debug: repro does not fail. Fix: click Abort job; the bug looks already fixed."` and stop.
5. **Build.** Spawn the builder as New job step 5 does (same name, same `B set $ID builder=`, same BLOCKED handling), but the last prompt line is `Implement the fix in JOB_DIR/assessment.md. Change only the files under ## Allowed files. Write build.md.` Then continue at **Check gate**.

## BigBoy lane

Applies only to a job whose `lane` on the board is `bigboy` (the **parent**), and to its **children**. A request too big for one job is split by `scrum-planner` into 2-5 tickets; each ticket runs as its own child job (spec → build → check → review → approve → its own PR, in its own lane and its own session) and merges on its own. The parent gets no worktree, branch or PR, and never goes through Check gate, Review, Approve or Merge. Children never get a backlog line, so `B next` and Run all never claim them. In steps 1-3, `$ID` is the parent; in steps 4-7, `P` is the child's `parent` from the board.

1. **Plan.** Run `B set $ID stage=plan`. Spawn `scrum-planner` and wait for it. Prompt:
   ```
   JOB_DIR=$F/jobs/$ID
   PROJECT=$F/project.md
   Write plan.md for this job.
   ```
   Then run `B plan-apply $ID`. Under the board lock it checks plan.md (first line `PLAN: READY`, 2-5 tickets, every `Depends on:` names a known ticket other than itself with no cycle, exactly one `Exposure: yes` ticket and it depends on every other), creates one `waiting` child job per ticket with its `feature.md`, sets the parent's `children`, moves the parent to `running`, and prints `{"children": [...]}`. A refused plan creates nothing. If it exits non-zero, delete `$F/jobs/$ID/plan.md`, spawn the planner once more, and run `B plan-apply $ID` again. If that fails too, take its error line, strip double quotes and backticks, run `B set $ID stage=needs-human reason="planner output unreadable: <error line>. Fix: click Abort job with Put back in backlog ticked, then run it again."` and stop.
2. **Child specs, all up front.** Spawn one `scrum-spec-writer` per child **in ONE message**, in the background, and wait for all of them. Each prompt is the New job step 3 prompt with `JOB_DIR=$F/jobs/<child>`. Then, for each child:
   - **Obsolete:** if its `spec.md` starts with `OBSOLETE:`, run `B abort <child> --reason 'obsolete: <rest of that line, single quotes stripped>'`. Its dependents never become ready.
   - **Lane:** otherwise run New job step 3c with `ID=<child>` (`Lane: bigboy` counts as `standard`). A child without a `spec.md` is fine: its own `start` writes it.
3. **Start.** Run `B ready $ID` and **start** each id in `ready`. To start a child (here, in step 5 and in step 6), run detached from the main checkout, logging to `scrum/runs/`:
   ```bash
   mkdir -p "$F/runs"; LOG="$(date +%Y%m%d-%H%M%S)-start-<child>.log"
   (cd "$REPO" && nohup claude -p "/trevskills-scrum start <child>" --permission-mode acceptEdits > "$F/runs/$LOG" 2>&1 < /dev/null &)
   B set <child> runlog=runs/$LOG
   ```
   This session is then done with the parent: each child chains the next from its own Merge step 7. Give the final report.
4. **Spec refresh** (in the child's own `start` session, after New job step 2). For each id in the child's `depends_on`, list the files its PR changed: `gh pr diff <that job's pr> --name-only`. Compare them, as exact paths, with the backtick-quoted paths under `## Likely files` in the child's `spec.md`. If `spec.md` is missing, run New job step 3 as usual. If any path overlaps, run New job step 3 with the extra prompt line `Refresh spec.md: dependencies <ids> merged and changed <files>.`, then step 3b and 3c. Otherwise skip step 3 (3b and 3c ran in step 2). Then continue at New job step 4.
5. **Chaining** (Merge step 7, after `stage=done`, for a job with a `parent`):
   1. **Tracker.** Unless every child of `P` in `$F/board.json` is now `done`, spawn `scrum-tracker` with the Agent tool override `model: "sonnet"` and wait for it. `N` is how many children of `P` are `done`. Prompt:
      ```
      PARENT_DIR=$F/jobs/$P
      JOBS_DIR=$F/jobs
      BOARD_JSON=$F/board.json
      PROJECT=$F/project.md
      N=<merged count>
      Check the BigBoy goal. Write track-N.md.
      ```
      Read the first line of `$F/jobs/$P/track-N.md`:
      - `TRACK: ADJUST`: it may have rewritten the `feature.md` of children still `waiting` (listed under `## Rewritten`), and logged each change under `## Diverged` in the parent's plan.md. Re-run step 2 for exactly those children.
      - `TRACK: OFF TRACK`: run `B set $P stage=needs-human reason="bigboy off track: <line 2 of track-N.md>. Fix: read the latest track file, then click Abort job and re-add the request with your decision."`, start no child, and stop.
      - `TRACK: ON TRACK`, or a missing or unreadable file: carry on.
   2. Run `B ready $P`. Under the lock it claims (moves to `spec`) every `waiting` child whose `depends_on` are all `done`, whose `setup` is not `pending`, and that can run beside the siblings in progress (a `parallel=no` child only when none is; a `parallel=yes` child never beside a `parallel=no` one or one whose `## Likely files` overlap its own), so a second call never returns it again. When nothing is ready or in progress and not every child is done, it sets the parent `needs-human` with reason `bigboy blocked: <ids>`; a later claim sets it back to `running`. It prints `{"ready", "merged", "total", "in_progress", "all_merged"}`.
   3. If `all_merged` is true, go to step 7. Otherwise **start** each id in `ready` (step 3; its own `start` runs the step 4 refresh).
6. **After a child stops.** When a child's run sets it `needs-human`, run `B ready $P` and **start** each id in `ready`, so tickets that don't depend on it keep going. A failed child blocks only its dependents.
7. **Final BigBoy review.** Run `B set $P stage=review`. If Merge step 7 reported `main not updated`, run `B set $P stage=needs-human reason="bigboy review: main not updated. Fix: make the main checkout fast-forward, then click Abort job and re-add the request if anything is missing."` and stop. Otherwise spawn `scrum-bigboy-reviewer` and wait for it. Prompt:
   ```
   PARENT_DIR=$F/jobs/$P
   JOBS_DIR=$F/jobs
   BOARD_JSON=$F/board.json
   REPO=$REPO
   PROJECT=$F/project.md
   Review the whole BigBoy on main. Write bigboy-review.md.
   ```
   If the first line of `bigboy-review.md` is neither `BIGBOY: PASS` nor `BIGBOY: GAPS`, delete it and spawn the reviewer once more; if it is still unreadable, treat it as GAPS with no fix ticket.
   - `BIGBOY: PASS`: run `B set $P stage=done reason=`. If plan.md has a `## Phase 2` section, run `B backlog-add "<its line> (Phase 2 of $P)"`.
   - `BIGBOY: GAPS` the first time: run `B plan-apply $P --fix`. It adds one child, ticket `FIX`, from the `## Fix ticket` text, with no dependencies, and moves the parent back to `running`. Run step 2 for it, then `B ready $P` and **start** it. When it merges, step 5 brings the parent back here and the reviewer runs once more.
   - `BIGBOY: GAPS` again, or `plan-apply --fix` exits non-zero (no `## Fix ticket`, or the FIX child already exists): run `B set $P stage=needs-human reason="bigboy review: gaps remain — <line 2 of bigboy-review.md>. Fix: read bigboy-review.md, add a backlog item for each gap, then click Abort job."` and stop.

## Check gate

If the job's `lane` is `fast`, see **Fast lane** (promotion on the 2nd failure, and before Review). If the job's `lane` is `debug`, step 2 adds the debug checks and step 4 ends differently.

1. `N = round + 1` (round as stored on the board). Run `mkdir -p $F/jobs/$ID/round-$N`, then `B set $ID round=$N stage=check`.
2. In `$WT`, run each of Test / Typecheck / Lint / Build from `project.md` that isn't `none`. Also run `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)\.env'`; any output is a failure ("committed .env file").
   For `lane=debug`, also run these; each failure makes `CHECK: FAIL` and gets its own entry in check.md:
   - **Repro:** the `Repro:` command from `assessment.md`, in `$WT`. It must exit 0.
   - **Allowed files:** every path in `git -C "$WT" diff --name-only "$BASE"...HEAD` must be listed under `## Allowed files` or be the `Repro test:` path. Otherwise it fails with `outside allowed files: <path>`.
   - **Repro test untouched:** `git -C "$WT" diff --name-only <Commit from repro-before.md> HEAD -- <Repro test path>` must print nothing. Otherwise it fails with `repro test changed`.
3. Write `round-$N/check.md`: first line `CHECK: PASS` or `CHECK: FAIL`, then for each command its exit code and the last 40 lines of output in a fenced block.
4. If it says FAIL, resume the builder with `Checks failed: read JOB_DIR/round-N/check.md, fix, commit, update build.md.` Then re-run steps 2–3, overwriting `check.md`. Allow up to **3** fix attempts. If it still fails, skip the review and go to **Approve**; the approver rules on the failing check. Exception: a `lane=debug` job that still fails after the 3rd fix attempt never goes to **Approve**: run `B set $ID stage=needs-human reason="debug: 3 failed fixes — question the design. Fix: click Discuss first."` and stop.
5. If it says PASS, go to **Review**.

## Review (WAIT FOR ALL)

If the job's `lane` is `fast`, see **Fast lane** instead of this section.

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
   - `REWORK` and sync's `"reworks"` is greater than 1: the approver broke the once-only rule. Run `B set $ID stage=needs-human reason="approver requested second rework. Fix: read decision.md, then click Approve & merge or Send back to builder."` and stop.
   - `REWORK` (first time): run `B set $ID limit=$((N+1)) stage=build`. Resume the builder with `The approver requested rework: read JOB_DIR/decision.md (Rulings marked fix-now), fix, commit, update build.md.` Then go to **Check gate**.
   - `ESCALATE` or `INVALID`: the reason is the second line of `decision.md` plus the fix for its hard-stop kind. If it starts `Hard stop: schema`, run `B set $ID stage=needs-human reason="<second line of decision.md>. Fix: click Approve & merge; it runs /trevskills-migrate first."`. If it starts `Hard stop: money`, `Hard stop: auth` or `Hard stop: secrets`, run `B set $ID stage=needs-human reason="<second line of decision.md>. Fix: review the diff, then click Approve & merge."`. If it starts `Hard stop: blocked`, run `B set $ID stage=needs-human reason="<second line of decision.md>. Fix: type what the builder needs and click Send back to builder."`. For any other second line, run `B set $ID stage=needs-human reason="<second line of decision.md>. Fix: click Discuss first."`. For INVALID, run `B set $ID stage=needs-human reason="approver output unreadable. Fix: click Discuss first."`. Report and stop.

## Merge (APPROVE, or /trevskills-scrum approve)

The steps below reuse the lessons from `/trevskills-commitpush`.

1. **Preconditions:**
   - `command -v gh && gh auth status` must succeed. If not, run `stage=needs-human reason="GitHub CLI is not installed or not signed in; branch scrum/$ID is local only. Fix: run gh auth login in Terminal, then click Approve & merge."` and stop.
   - `git -C "$WT" status --porcelain` must be empty. If it isn't, resume the builder once with `Commit or remove uncommitted changes.` If it is still dirty, run `B set $ID stage=needs-human reason="Uncommitted files in the job worktree: <first files>. Fix: click Send back to builder and ask it to commit or remove them."` and stop.
   - **Schema guard (deterministic; doesn't rely on any model):** if `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)prisma/(schema\.prisma|migrations/)|\.sql$'` prints anything and `$F/jobs/$ID/human-approval.md` doesn't exist, run `B set $ID stage=needs-human reason="Hard stop: schema — <first matching file>. Fix: click Approve & merge; it runs /trevskills-migrate first."` and stop. Run this guard again right before step 6, because CI-fix commits skip the approver.
   - **Main checkout guard (before any push or merge):** the main checkout must be able to fast-forward after the merge, or the change never goes live. It passes only if `git -C "$REPO" symbolic-ref --short HEAD` equals `$DEFAULT` and `git -C "$REPO" status --porcelain --untracked-files=no` is empty (untracked files don't count). If it has uncommitted changes, run `B set $ID stage=needs-human reason="Uncommitted change in <repo name>: <first files>. Fix: commit + push it (or undo it), then click Approve & merge."` and stop. If it is on the wrong branch, run `B set $ID stage=needs-human reason="<repo name> main checkout is on <branch>, not <default>. Fix: switch it back to <default>, then click Approve & merge."` and stop. `<repo name>` is `basename "$REPO"`. Never stash, clean or switch branches in the main checkout to make it pass; Trevor fixes it by hand, then runs `/trevskills-scrum approve <id>`.
2. Run `B set $ID stage=merging`. Then `git -C "$WT" push -u origin "scrum/$ID"`. That pushes the scrum branch only.
3. **PR.** Run `gh pr view "scrum/$ID" --json number,url,state`:
   - `OPEN`: reuse it.
   - `MERGED`: skip steps 4–6 and go to step 7 (Clean up), so the fast-forward and the live check still run.
   - `CLOSED`: run `stage=needs-human reason="The pull request was closed on GitHub. Fix: reopen it on GitHub, then click Approve & merge."` and stop.
   - No PR, or reusing one: the title is the decision.md `Merge summary` title. If there is no Merge summary (a human-approved ESCALATE), use the job title and the spec's acceptance criteria as bullets. Either way write the body to `BODY=$F/jobs/$ID/pr-body.txt`, which is also used in step 6. Write the body to that file and pass it with `--body-file`. The body is the Merge summary bullets, then `Approved by the scrum approver. Spec, reviews and decision: scrum/jobs/$ID/` (for a fast-lane job, the line in **Fast lane** step 3 instead), then a line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Create it with `gh pr create --base "$DEFAULT" --head "scrum/$ID" --title "<Merge summary title>" --body-file "$BODY"`.

   Then `B set $ID pr=<url>`.
4. **Checks.** Run this in the **background**, because foreground `sleep` is blocked:
   ```bash
   for i in 1 2 3 4; do out=$(gh pr checks "scrum/$ID" --watch --fail-fast --interval 15 2>&1); code=$?
     echo "$out" | grep -q "no checks reported" || break; sleep 20; done; echo "exit=$code"; echo "$out" | tail -40
   ```
   - `exit=0`: continue to step 5.
   - Still "no checks reported": the repo has no CI. Continue, and note "no CI ran" in the final report.
   - Any other failure: write the failing output to `$F/jobs/$ID/ci.md`, resume the builder with `CI failed: read JOB_DIR/ci.md, fix, commit.`, push again, and re-check. Allow at most **2** CI fix attempts. After that, run `stage=needs-human reason="CI still fails after 2 fix attempts. Fix: read ci.md, then click Send back to builder with what to change."` and stop.
5. **Conflicts.** Run `gh pr view "scrum/$ID" --json mergeable --jq .mergeable`. If it returns `UNKNOWN`, GitHub is still computing; re-run it in the background every 10 seconds, up to 6 times. If it returns `CONFLICTING`, resolve it. This is the one sanctioned `git merge`, and it only ever goes into this job's own branch. Allow at most **2** attempts; after that, run `stage=needs-human reason="merge conflicts with $DEFAULT after 2 tries. Fix: click Send back to builder and ask it to merge $DEFAULT and resolve them."` and stop. Each attempt:
   1. `git -C "$WT" fetch origin`, then `git -C "$WT" merge "origin/$DEFAULT" --no-edit`.
   2. If that merge itself conflicts, resume the builder with `The default branch was merged into your branch and has conflicts: resolve them, commit, update build.md.`
   3. Run `B set $ID limit=$((N+1))` and go to **Check gate**. That gives a fresh check and full review round, then the approver, then Merge again, reusing the open PR.
6. **Merge:** re-run the schema guard from step 1, and run `B sync $ID` right before merging; if it says the job was aborted, stop. Then `gh pr merge "scrum/$ID" --squash --subject "<title> (#<number>)" --body-file "$BODY"`. Never use `--auto`, `--admin` or `--delete-branch`. If the merge fails (branch protection, a required review, anything else), run `B set $ID stage=needs-human reason="merge refused: <first line of stderr>. Fix: clear that on GitHub, then click Approve & merge."` and stop.
7. **Clean up:**
   - **Pick the verify string** (only when the decision.md `Restart:` line is not `Restart: none`), before removing the worktree: a distinctive piece of one line this job's diff added to a served file (a new CSS class, copy string or JSON key), from `git -C "$WT" diff "$BASE"...HEAD`. Prefer a substring of at least 8 characters that contains none of `'` `"` `` ` `` `$` `\` `!` or a newline. If no such substring exists, use the line as is; it is passed through a quoted heredoc in Verify, never pasted into the command. If the diff adds no line to a served file, there is no verify string and Verify uses the behavioural check.
   - Run `git worktree remove "$WT"`. If git refuses because of local changes, leave the worktree in place and mention it. This never affects whether the job is live.
   - Run `git fetch origin`.
   - **Fast-forward main (always, whatever the `Restart:` line says).** The dashboard and this skill are served from the main checkout, so it must not stay behind origin:
     1. **Guard (same test as step 1):** `git -C "$REPO" symbolic-ref --short HEAD` must equal `$DEFAULT`, and `git -C "$REPO" status --porcelain --untracked-files=no` must be empty.
     2. If both pass, run `git -C "$REPO" pull --ff-only`.
     3. If a guard check or the fast-forward fails, report `main not updated: <reason>`, where reason is `not on <default>`, `uncommitted changes` or `fast-forward failed`. Never merge, reset, rebase or stash to make it work.
   - **Restart.** Read the `Restart:` line from `$F/jobs/$ID/decision.md` (no line, e.g. a human-approved ESCALATE without one, counts as `none`). If it is not `Restart: none`, in order:
     1. **Skip if main wasn't updated:** if the fast-forward above did not succeed, do not restart. Report `Restart pending: <process> — <reason>`, with the same reason as `main not updated`.
     2. **Restart:** `<port>` is the number in the `Restart:` line's `on port <N>`; when the line names serve.py and gives no port, use 8765. A non-serve.py line with no port is not restarted: report `Restart pending: <process> — no port in Restart line` and treat it as `restart failed`. Start only an allowed command, and never one taken from the `Restart:` line:
        - serve.py: `mkdir -p ~/.claude/trevskills-scrum && nohup python3 ~/.claude/skills/trevskills-scrum/serve.py >> ~/.claude/trevskills-scrum/serve.log 2>&1 &` (as in `app/make-app.sh`);
        - anything else: the exact `Dev command:` value from `$F/project.md`, run as `nohup <Dev command> >> "$F/dev.log" 2>&1 &` from `$REPO`.

        If the line names any other start command, or `Dev command:` is `none` or missing for a non-serve.py process, run nothing: report `Restart pending: <process> — restart command not allowed` and treat it as `restart command not allowed`. Otherwise record the old PID with `lsof -ti tcp:<port> -sTCP:LISTEN`, stop it with `lsof -ti tcp:<port> -sTCP:LISTEN | xargs kill`, and start the allowed command.
     3. **Verify:** run only `curl -sf localhost:<port>/<path>`, alone or piped to `grep -F -- <string>`. If the `Restart:` line's `verify:` has any other shape, do not run it; build this form from the port and the changed path (`/` when none is more specific). Retry in the background for a few seconds while it starts.
        - With a verify string: a 200 is not enough; the served content must contain this job's change. A string from the safe set may go in single quotes (`grep -F -- '<verify string>'`). Otherwise load it through a quoted heredoc and match the variable:
          ```bash
          VERIFY=$(cat <<'EOF'
          <verify string>
          EOF
          )
          curl -sf localhost:<port>/<path> | grep -F -- "$VERIFY"
          ```
          No match is `verify failed`.
        - With no verify string (behavioural): it passes only when the PID from `lsof -ti tcp:<port> -sTCP:LISTEN` after the start differs from the one recorded before the kill, and `curl -sf localhost:<port>/<path>` exits 0. Either failing is `verify failed`; passing is reported as `restarted + verified (behavioural)`.
   - **Mark done, only now.** If the guard, the fast-forward, the restart or the verify failed, run `B set $ID stage=done reason="merged, not live: <why>"`, where `<why>` is `not on <default>`, `uncommitted changes`, `fast-forward failed`, `restart failed`, `restart command not allowed` or `verify failed`. Otherwise (including `Restart: none` after a successful fast-forward) run `B set $ID stage=done reason=`. The dashboard card shows the `merged, not live` reason as a warning; Trevor clears it with `B set <id> reason=` once he has made the change live.
   - **BigBoy chaining.** If the job has a `parent`, after `stage=done` run **BigBoy lane** step 5 (tracker, `B ready`, start the next children or the final review).
   - **Digest check.** After `stage=done`, run `B digest-due`. If it prints `"due": true`, run **Digest** in this same session before the final report.

## Resuming the builder

Use SendMessage to the recorded `builder` (the name `builder-$ID`, or the stored agent id) with a message naming the exact file(s) to read. If SendMessage fails because the agent no longer exists (for example after a session restart):
1. Spawn a fresh `scrum-builder` with the 5 lines plus `You are resuming this job. Read spec.md, build.md, and <the file(s) above>, then continue.`
2. Run `B set $ID builder=<new id>`.

The orchestrator never edits code or review files itself, except for three sanctioned review files: the UI/UX skip files in **Review** step 2, the `Reviewer produced no output.` fallback, and the fast lane skip files in **Fast lane** step 2.

## Digest

Learns from finished jobs. It runs from the main checkout (Setup applies, but not the Prerequisites: it needs no remote and no `gh`), and it never pushes, merges or opens a PR. It never edits an agent, skill, rule or memory file itself: Trevor approves or rejects each proposal in the dashboard's **Digest** dialog, and the dashboard trims the digested job folders once the last one is decided.

1. Run `B digest-start`. Under the board lock it claims every `done` job that's in no earlier digest and prints `{"id", "jobs"}`. If `id` is null, say there is nothing to digest and stop. Otherwise `D=$F/digests/<id>`.
2. Spawn `scrum-digest-reader` and wait for it. Prompt:
   ```
   DIGEST_DIR=$D
   JOBS_DIR=$F/jobs
   Write notes.md for this digest.
   ```
   If `$D/notes.md` is missing or its first line isn't exactly `DIGEST NOTES` (`head -1 "$D/notes.md"`), spawn it once more. If it still fails, write `$D/error.md` containing the one line `digest reader produced no notes` and stop.
3. Spawn `scrum-digester` and wait for it. Prompt:
   ```
   DIGEST_DIR=$D
   PROJECT=$F/project.md
   Write proposals.json for this digest.
   ```
   If `python3 -m json.tool "$D/proposals.json"` fails, or the file has no `proposals` list (`python3 -c 'import json,sys; sys.exit(not isinstance(json.load(open(sys.argv[1])).get("proposals"), list))' "$D/proposals.json"` exits non-zero), spawn it once more. If it still fails, write `$D/error.md` containing the one line `digester produced no valid proposals` and stop.
4. If the `proposals` list is empty, run `B digest-trim <id>`. Otherwise report how many proposals wait in the dashboard's **Digest** dialog.

## Final report

End with the job id, the final stage, for a BigBoy parent or child the children this run started (or `none`) and the parent's stage, the PR URL, rounds used, any follow-ups added to the backlog, for merged jobs whether main was fast-forwarded (`main updated`, or `main not updated: <reason>`) the restart outcome (`restarted + verified`, `restarted + verified (behavioural)`, `restart failed`, `restart command not allowed`, `verify failed`, `Restart pending: <process> — <reason>`, or `none`), and whether the change is live (`live`, or `merged, not live: <why>` as written to the board), and, for needs-human, the exact reason and the next command (`/trevskills-scrum approve <id>`, `/trevskills-scrum rework <id> "<feedback>"`, or `/trevskills-scrum discuss <id>` when it's unclear which).
