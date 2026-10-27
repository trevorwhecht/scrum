---
name: trevskills-scrum
description: Run the scrum team. "/trevskills-scrum <feature>" builds a feature end to end (spec → build → check → up to 4 parallel reviews → approver → squash-merged PR). Also "/trevskills-scrum now"/"next"/"later <feature>" (start it, queue it first, or add it to the backlog), "/trevskills-scrum next", "/trevskills-scrum approve <id>", "/trevskills-scrum rework <id> <feedback>", "/trevskills-scrum discuss <id> [note]", "/trevskills-scrum resume <id>" (restart a job the watchdog flagged as stalled, one Trevor paused, or one stopped for another resumable reason; the dashboard's Resume and Play), "/trevskills-scrum askme [1-3] <feature>" (answer questions first, then build), "/trevskills-scrum bigboy <feature>" (plan a big request into 2-5 chained child jobs), "/trevskills-scrum digest" (learn from done jobs; also runs itself after every 10), "/trevskills-scrum run-all" (triage the backlog, then schedule every open item in parallel where files don't overlap), "/trevskills-scrum run-all askme <1-3>" (the same, but first answer questions for every item the triage left open), "/trevskills-scrum lilguy <feature>" (cheap mode: no subagents; this session makes the change in the job's own worktree, runs the checks, then lands it through a squash-merged PR), "/trevskills-scrum cloud [N]" (run up to N backlog items in claude.ai/code cloud sessions), "/trevskills-scrum cloud-sync" (pull their results onto the board), "/trevskills-scrum cloud-home <id>" (bring one synced cloud job's artifacts, follow-ups, migrate or rules merge home; serve.py starts it), and bare "/trevskills-scrum" for status.
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

The session running this skill **is the orchestrator**. It spawns every agent, moves files between steps, and is the only caller of `board.py`. It never writes code (except in the **Lilguy lane**), and it never reads diffs or reviews beyond their first lines. Agents get their context from files, never from this conversation.

**Headless sessions block.** In a `claude -p` session (a dashboard or nohup run), ending the turn exits the process and kills everything it spawned: background agents, pending SendMessage replies, ScheduleWakeup/cron/loop timers. So the orchestrator never ends its turn while an agent or subprocess it spawned is still running; it waits for every one to return or exit, a "background" spawn included. It never relies on a later notification, a SendMessage reply or a `ScheduleWakeup`/cron/loop timer to continue, because those die with the process.

This skill is a sanctioned exception to the global git rules: it may push its own `scrum/*` branch, `gh pr create`, and `gh pr merge --squash` that PR once checks pass. Nothing else:
- never `git reset`, `git rebase`, or `--force`, and never `git merge` except the conflict step in **Merge**, the pre-build sync in **New job** and the retry sync in **approve**
- never `git pull` except the one guarded fast-forward (`--ff-only`) of the main checkout in **Merge** step 7 (Clean up), which runs after every merge; never stash, merge, reset or switch branches in the main checkout
- never push `main`/`master`
- never `--auto` or `--admin`
- when `scrum/project.md` sets `Base branch:`, never open a PR into, merge into, or push the remote default branch; every job targets that base branch instead. Promoting it to `main` is Trevor's own merge commit, never squash, and no scrum command does it
- never `prisma migrate` or `prisma db push` directly. The one way to migrate is invoking `/trevskills-migrate` (Skill tool), and only from the **Migrate** step (run by **Merge**'s schema guard). Trevor chose this: schema changes migrate and merge unattended once the pipeline passes. Sub-agents never migrate

Jev never removes a reviewer and never approves a merge.

## Setup (start of every invocation)

Run from the repo's **main checkout**, not a worktree:

```bash
test "$(git rev-parse --git-dir)" = "$(git rev-parse --git-common-dir)" || echo "NOT MAIN CHECKOUT"
REPO="$(git rev-parse --show-toplevel)"; F="$REPO/scrum"
B() { python3 "$HOME/.claude/skills/trevskills-scrum/board.py" --dir "$F" "$@"; }
```

Shell variables and functions don't survive between Bash calls, so re-derive `REPO`, `F` and the board function `B` (and the job's `WT`, `BASE`, `DEFAULT` from `board.json`) at the start of each call.

**Agent-written text in a shell command** (a reason, title, verify string or prompt): never put it inside double quotes or backticks. Strip single quotes from it and wrap it in single quotes, or write it to a file and pass the file.

**Abort:** Trevor can abort a job from the dashboard at any moment. From then on every `B set` or `sync` for it fails with `was aborted`. When you see that, stop immediately: spawn nothing more, push nothing, merge nothing. Report that the job was aborted. Leave its branch, worktree and PR exactly as they are.

**Pause:** Trevor can pause a job in progress from the dashboard. Its session is killed at once and the job stays in its stage with board `paused` true and reason `stalled in <stage>: paused by Trevor`. If a session survives, every `B set` or `sync` for it fails with `was paused by Trevor`. When you see that, stop quietly as for abort: spawn nothing more, push nothing, merge nothing. Play restarts it with `/trevskills-scrum resume <id>`. Only `B set --unpause` with a `stage=` (which `resume` and `rework` use) clears a pause; a plain `B set <id> ... reason=` is refused like any other write.

**Untrusted reason text:** a reason that copies text from an agent-written file (assessment.md, decision.md, a track or review file) or from command output (stderr, file names, branch names) can contain `$(...)` or a backtick. Remove every `'` from that text, then pass the reason in single quotes, `reason='...'`, never in double quotes, so the shell expands nothing in it. Every reason template below with a `<placeholder>` is written this way; reasons whose only variables are `$ID` or `$DEFAULT` keep double quotes so those expand.

If this isn't the main checkout, stop and say so. Run `B register "$REPO"` every time (it's idempotent): that's what puts this repo on the one all-projects dashboard.

**Prerequisites (every command that runs a job: new job, `next`, `start`, `run-all`, `approve`, `rework`, `resume`, `lilguy`, `cloud`, `cloud-job`, `cloud-home`; not bare `/trevskills-scrum`).** Before spawning any agent, check:
- `git remote` prints something. If not, stop and tell the user to run `git remote add origin <url>`.
- `command -v gh && gh auth status` succeeds. If not, stop and tell the user to run `brew install gh && gh auth login`.

**Roadmap resume (the commands in the Prerequisites list, plus `roadmap`; never bare `/trevskills-scrum`).** Run `B roadmap-show`. If it prints a roadmap with a `running` step whose `job` is `done` on `$F/board.json` (its hook was missed), run `B roadmap-next <that job>` first and, when it prints a step, do **Roadmap lane** **Starting a step** with it, before the requested command.

If `$F/project.md` is missing, do the **first-run setup** below. Otherwise go to the command.

**Record your terminal** (New job, `start`, `approve`, `rework`, `discuss`, `resume`, `lilguy`; once you know the job id `$ID`). It is skipped, never an error, when it isn't usable:

```bash
T=$(ps -o tty= -p $PPID | tr -d ' '); case "$T" in ttys[0-9]*) B set $ID tty=$T ;; esac
```
A tty of `??` or empty sets nothing. The recorded tty is also what the frontmatter hooks (`board.py hook`) match on to mark the job `waiting` while this session waits on Trevor.

### First-run setup (once per repo)

Read `$HOME/.claude/skills/trevskills-scrum/lanes/setup.md` when this section runs.

## Commands

Read `$HOME/.claude/skills/trevskills-scrum/lanes/commands.md` when this section runs.

## New job

**Every stop is a closed question.** A job goes needs-human only through `B ask`: in plain words, what happened and why it needs Trevor, then 2 or 3 options `--a`, `--b`, `--c`, each `<Label>=<command>`, the command one of `approve <id>`, `rework <id> "<fix text>"`, `abort <id> [--requeue|--cascade]`, `resume <id>` or `shell: <cmd>`, then `--recommend <key> '<why>'`. Read `$HOME/.claude/skills/trevskills-scrum/lanes/stops.md` for the Issue / Options / Recommended shape every question takes. `B set` refuses the needs-human stage. The question has no double quotes or backticks, is quoted under **Untrusted reason text**, and becomes the reason, so it keeps the old reason's prefix (`Hard stop: schema`, `Hard stop: render`, `blocked:`, `bigboy off track`, `bigboy review: main not updated`, `Base branch `). An option with a `<placeholder>` is single-quoted, `<id>` written out; one with only `$ID` or `$P` is double-quoted. A stop whose only fix is Abort is still handled by the agents instead. A stalled job is not a stop: it keeps its stage with board `stalled` true and serve.py resumes it. A run that cannot carry on, a resume or approve included, ends with a fresh `B ask` naming the blocker it actually hit, which replaces the old question; a question only in chat leaves the old one on the board and does not count.

**Auto-abort instead of needs-human.** Some stops below run `B abort $ID --requeue --reason 'requeue: <error>'` (the job lands in Done as aborted and its feature goes back on the backlog), or `B abort $ID --reason 'looks already fixed: ...'`, and stop. The `<error>` part is quoted under the **Untrusted reason text** rule. For a job with a `parent` (a BigBoy child), the requeue abort runs without `--requeue` (its text is a planner ticket, not a backlog item), and after any of these aborts the run then does **BigBoy lane** step 6. The **Roadmap lane** stop rule (`B roadmap-stop`) applies to these aborts as it does to needs-human. Inside a cloud-job session, they are reported to GitHub as **Cloud lane** **Needs-human** says. The final report says the job was auto-aborted (requeued, or auto-closed as looks already fixed) and why.

For a BigBoy child (the job has a `parent`), every time this run runs `B ask` for the child, also run **BigBoy lane** step 6, so independent children still start. Every time this run runs `B ask` for a job, also apply the **Roadmap lane** stop rule (`B roadmap-stop` only when that job, or its `parent`, is a roadmap step's `job`).

**Unblock.** When a `B ask` run with `--kind` prints `"unblock": true`, the job was not parked, so don't stop: read `$HOME/.claude/skills/trevskills-scrum/lanes/unblock.md` and follow it (it spawns `scrum-unblocker`); the two side steps above then wait until an ask actually parks.

Read `$HOME/.claude/skills/trevskills-scrum/lanes/newjob.md` when this section runs.

## Run all

Read `$HOME/.claude/skills/trevskills-scrum/lanes/runall.md` when this lane runs.

## Fast lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/newjob.md` when this section runs.

## Debug lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/debug.md` when this lane runs.

## BigBoy lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/bigboy.md` when this lane runs.

## Roadmap lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/roadmap.md` when this lane runs.

## Lilguy lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/lilguy.md` when this lane runs.

## Cloud lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/cloud.md` when this lane runs.

## Check gate

Read `$HOME/.claude/skills/trevskills-scrum/lanes/newjob.md` when this section runs.

## Review (WAIT FOR ALL)

Read `$HOME/.claude/skills/trevskills-scrum/lanes/review.md` when this section runs.

## Approve

Read `$HOME/.claude/skills/trevskills-scrum/lanes/review.md` when this section runs.

## Migrate (Merge's schema guard)

Schema changes migrate and merge unattended (Trevor's call); this stops only when `/trevskills-migrate` stops.

1. `cd "$WT"` and invoke `/trevskills-migrate` (Skill tool) there with args `base=$BASE`, plus `prod-approved=<content>` if `$F/jobs/$ID/prod-approval.md` exists, following it exactly. Every question it would put to Trevor is a stop: never answer one yourself.
2. On a stop, `cd "$REPO"`. If its only stop is Step 8.2 (`prod-approval-sha: <sha>`), write `<sha>` to `$F/jobs/$ID/prod-approval-pending.md` and run `B ask $ID 'migrate needs your OK: the database update would <what the flagged SQL does> because <why>.' --a "Merge anyway=approve $ID" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop. If the stop names a migration folder this branch lacks, find the one board job (not done or aborted) whose `git -C "$REPO" ls-tree -r --name-only "scrum/<id>"` lists a path containing `/<folder>/`, run `B wait-on $ID <that id> --then "approve $ID"`, and stop on exit 0, keeping the worktree; with no such job or a non-zero exit, fall through. If the stop is `/trevskills-migrate` Step 1's duplicate-column finding naming a concrete alternative (drop, reuse or read through a relation), the job is not in the **Lilguy lane**, and `$F/jobs/$ID/rework.md` has no line starting `Auto-rework: duplicate column`, follow **`/trevskills-scrum rework`** with `$ID` and the note `Auto-rework: duplicate column — <the alternative>` and stop, with no `B ask`: on this path never migrate anyway and never touch dev or prod data; otherwise fall through. On any other stop, run `B ask $ID 'migrate stopped: the database update stopped; we should <what to change> because <why>.' --a "Try again=approve $ID" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop; never work around it.
3. On success, commit what it generated (`git -C "$WT" add prisma && git -C "$WT" commit -m "Add migration"`, skipped when nothing changed), write `git -C "$WT" rev-parse HEAD:prisma` to `$F/jobs/$ID/migrated.md`, and `cd "$REPO"`.

## Merge (APPROVE, or /trevskills-scrum approve)

1. **Preconditions:**
   - `command -v gh && gh auth status` must succeed. If not, run `B ask $ID "GitHub CLI is not installed or not signed in, so this job cannot push its branch or open a pull request. Run brew install gh, then gh auth login, then press Try again." --a "Try again=approve $ID" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop.
   - `git -C "$WT" status --porcelain` must be empty. If it isn't, resume the builder once with `Commit or remove uncommitted changes.` If it is still dirty, write those files to `$F/jobs/$ID/stop.md`, run `B ask $ID 'Uncommitted files in the job worktree: the separate copy of the repo this job works in has changes the builder never committed, so it cannot merge. The file list is in the stop.md tab of this job.' --a "Send back with a note=rework $ID \"commit or remove every uncommitted file in the worktree\"" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop.
   - **Schema guard (deterministic):** if `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)prisma/(schema\.prisma|migrations/)|\.sql$'` prints anything and `$F/jobs/$ID/migrated.md` doesn't hold `git -C "$WT" rev-parse HEAD:prisma`, run **Migrate**. In the **Cloud lane**, which never migrates, write the matching files to `$F/jobs/$ID/stop.md`, run `B ask $ID 'Hard stop: schema — this job changes the database structure, and a cloud session cannot update the database. Migrate and merge runs the database update on this Mac, then merges. The changed files are in the stop.md tab of this job.' --a "Migrate and merge=approve $ID" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop instead. Run this guard again right before step 6, because CI-fix commits skip the approver.
   - **Main checkout guard (before any push or merge):** it passes only if `git -C "$REPO" symbolic-ref --short HEAD` equals `$DEFAULT` and `git -C "$REPO" status --porcelain --untracked-files=no` is empty. `<repo name>` is `basename "$REPO"`; `<the files>` are the paths that status prints, each quoted under the **Untrusted reason text** rule.
     - **Uncommitted changes (self-heal):** run project.md's Test command (its `- Test:` line; `none` or missing counts as a fail) in `$REPO`. If it passes, invoke `/trevskills-commitpush` via the Skill tool in `$REPO`, following it exactly, then re-check this guard and continue the merge. If the test fails, commitpush stops, or the guard still fails, write those files to `$F/jobs/$ID/stop.md`, run `B ask $ID 'Uncommitted change in <repo name>: the main copy has edits nobody committed and its tests fail, so this job cannot go live. The file list is in the stop.md tab of this job. Stash them, or commit and push them, yourself in the chat in <repo name> (git stash, or git commit then git push), then pick Keep my changes and carry on, the recommended option. Remove this job throws away this job, its unmerged work and the jobs waiting on it.' --a "Keep my changes and carry on=resume $ID" --b 'Throw away the changes=shell: git checkout -- <the files>' --c "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop.
     - **Wrong branch:** run `B ask $ID '<repo name> main checkout is on <branch>, not <default>, so this job cannot go live. Run git checkout <default> yourself in the chat in <repo name>, then pick Carry on, the recommended option. Remove this job throws away this job, its unmerged work and the jobs waiting on it.' --a "Carry on=resume $ID" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop.
     - **Unpushed commits:** after the branch and clean checks pass, and only when `git -C "$REPO" fetch origin "$DEFAULT"` succeeds (a failed fetch skips this check): if `git -C "$REPO" rev-list --count "origin/$DEFAULT..$DEFAULT"` prints more than 0, run `B ask $ID 'Unpushed commits in <repo name>: the main copy has commits that are not on GitHub, so after this job merges the main copy could not update and the change would not go live. Push them yourself in the chat in <repo name> (git pull, then git push), then pick Carry on, the recommended option. Remove this job throws away this job, its unmerged work and the jobs waiting on it.' --a "Carry on=resume $ID" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop. Local main that is only behind origin passes.
     - All three asks recommend key `a`. Never stash, clean or switch branches in the main checkout on your own to make it pass. Only the Throw away the changes option Trevor picks throws anything away.
2. Run `B set $ID stage=merging`. Then `git -C "$WT" push -u origin "scrum/$ID"`.

Read `$HOME/.claude/skills/trevskills-scrum/lanes/merge.md` when this section runs.

## Routing

`scrum-spec-writer`, `scrum-builder` and `scrum-digest-reader` always spawn on cloud with the Agent tool exactly as the step says. Take `START=$(date +%s)` just before each spawn, and after it log the spawn with `python3 "$HOME/.claude/skills/trevskills-scrum/../../local/route.py" record <dir> <role> cloud - $(( $(date +%s) - START )) ok`. `<dir>` is `$F/jobs/$ID` (for a BigBoy child, `$ID` is that child's id), or `$F` for the digest reader. `<role>` is the agent name.

Ignore a failed `record` call. Logging never blocks the pipeline.

## Resuming the builder

Read `$HOME/.claude/skills/trevskills-scrum/lanes/merge.md` when this section runs.

## Digest

Read `$HOME/.claude/skills/trevskills-scrum/lanes/digest.md` when this lane runs.

## Final report

End with the job id, the final stage, for a BigBoy parent or child the children this run started (or `none`) and the parent's stage, the PR URL, rounds used, any follow-ups added to the backlog, for merged jobs whether main was fast-forwarded (`main updated`, or `main not updated: <reason>`) the restart outcome (`restarted + verified`, `restarted + verified (behavioural)`, `restart failed`, `restart command not allowed`, `verify failed`, `Restart pending: <process> — <reason>`, or `none`), and whether the change is live (`live`, or `merged, not live: <why>` as written to the board), and, for needs-human, the exact reason and the next command (`/trevskills-scrum approve <id>`, `/trevskills-scrum rework <id> "<feedback>"`, or `/trevskills-scrum discuss <id>` when it's unclear which).
