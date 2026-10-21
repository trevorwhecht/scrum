---
name: trevskills-scrum
description: Run the scrum team. "/trevskills-scrum <feature>" builds a feature end to end (spec → build → check → up to 4 parallel reviews → approver → squash-merged PR). Also "/trevskills-scrum next", "/trevskills-scrum approve <id>", "/trevskills-scrum rework <id> <feedback>", "/trevskills-scrum discuss <id> [note]", "/trevskills-scrum resume <id>" (restart a job the watchdog flagged as stalled, one Trevor paused, or one stopped for another resumable reason; the dashboard's Resume and Play), "/trevskills-scrum askme [1-3] <feature>" (answer questions first, then build), "/trevskills-scrum bigboy <feature>" (plan a big request into 2-5 chained child jobs), "/trevskills-scrum digest" (learn from done jobs; also runs itself after every 10), "/trevskills-scrum run-all" (triage the backlog, then schedule every open item in parallel where files don't overlap), "/trevskills-scrum run-all askme <1-3>" (the same, but first answer questions for every item the triage left open), "/trevskills-scrum lilguy <feature>" (cheap mode: no subagents; this session makes the change in the main checkout, runs the checks, then lands it with commitpush), "/trevskills-scrum cloud [N]" (run up to N backlog items in claude.ai/code cloud sessions), "/trevskills-scrum cloud-sync" (pull their results onto the board), "/trevskills-scrum cloud-home <id>" (bring one synced cloud job's artifacts, follow-ups, migrate or rules merge home; serve.py starts it), and bare "/trevskills-scrum" for status.
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

The session running this skill **is the orchestrator**. It spawns every agent, moves files between steps, and is the only caller of `board.py`. It never writes code (except in the **Lilguy lane**), and it never reads diffs or reviews beyond their first lines, which keeps its context small. Agents get their context from files, never from this conversation.

**Headless sessions block.** In a `claude -p` session (a dashboard or nohup run), ending the turn exits the process and kills everything it spawned: background agents, pending SendMessage replies, ScheduleWakeup/cron/loop timers. So the orchestrator never ends its turn while an agent or subprocess it spawned is still running; it waits for every one to return or exit, a "background" spawn included. It never relies on a later notification, a SendMessage reply or a `ScheduleWakeup`/cron/loop timer to continue, because those die with the process.

This skill is a sanctioned exception to the global git rules: it may push its own `scrum/*` branch, `gh pr create`, and `gh pr merge --squash` that PR once checks pass. Nothing else:
- never `git reset`, `git rebase`, or `--force`, and never `git merge` except the conflict step in **Merge**
- never `git pull` except the one guarded fast-forward (`--ff-only`) of the main checkout in **Merge** step 7 (Clean up), which runs after every merge; never stash, merge, reset or switch branches in the main checkout
- never push `main`/`master`, except through commitpush invoked with the Skill tool in the **Lilguy lane**
- never `--auto` or `--admin`
- when `scrum/project.md` sets `Base branch:`, never open a PR into, merge into, or push the remote default branch; every job targets that base branch instead. Promoting it to `main` is Trevor's own merge commit, never squash, and no scrum command does it
- never `prisma migrate` or `prisma db push` directly. The one way to migrate is invoking `/trevskills-migrate` (Skill tool), and only from the **Migrate** step (run by **Merge**'s schema guard and by **Lilguy lane** step 4). Trevor chose this: schema changes migrate and merge unattended once the pipeline passes. Sub-agents never migrate

Jev never removes a reviewer and never approves a merge.

## Setup (start of every invocation)

Run from the repo's **main checkout**, not a worktree:

```bash
test "$(git rev-parse --git-dir)" = "$(git rev-parse --git-common-dir)" || echo "NOT MAIN CHECKOUT"
REPO="$(git rev-parse --show-toplevel)"; F="$REPO/scrum"
B() { python3 "$HOME/.claude/skills/trevskills-scrum/board.py" --dir "$F" "$@"; }
```

Shell variables and functions don't survive between Bash calls, so re-derive `REPO`, `F` and the board function `B` (and the job's `WT`, `BASE`, `DEFAULT` from `board.json`) at the start of each call. `B` is a function, not a string variable, so it works in both bash and zsh.

**Agent-written text in a shell command** (a reason, title, verify string or prompt): never put it inside double quotes or backticks. Strip single quotes from it and wrap it in single quotes, or write it to a file and pass the file.

**Abort:** Trevor can abort a job from the dashboard at any moment. From then on every `B set` or `sync` for it fails with `was aborted`. When you see that, stop immediately: spawn nothing more, push nothing, merge nothing. Report that the job was aborted. Leave its branch, worktree and PR exactly as they are.

**Pause:** Trevor can pause a job in progress from the dashboard. Its session is killed at once and the job becomes `needs-human` with reason `stalled in <stage>: paused by Trevor`. If a session survives, every `B set` or `sync` for it fails with `was paused by Trevor`. When you see that, stop quietly as for abort: spawn nothing more, push nothing, merge nothing. Play restarts it with `/trevskills-scrum resume <id>`. Only `B set --unpause` (which `resume` and `rework` use) clears a pause; a plain `B set <id> ... reason=` is refused like any other write.

**Untrusted reason text:** a reason that copies text from an agent-written file (assessment.md, decision.md, a track or review file) or from command output (stderr, file names, branch names) can contain `$(...)` or a backtick. Remove every `'` from that text, then pass the reason in single quotes, `reason='...'`, never in double quotes, so the shell expands nothing in it. Every reason template below with a `<placeholder>` is written this way; reasons whose only variables are `$ID` or `$DEFAULT` keep double quotes so those expand.

If this isn't the main checkout, stop and say so. Run `B register "$REPO"` every time (it's idempotent): that's what puts this repo on the one all-projects dashboard.

**Prerequisites (every command that runs a job: new job, `next`, `start`, `run-all`, `approve`, `rework`, `resume`, `lilguy`, `cloud`, `cloud-job`, `cloud-home`; not bare `/trevskills-scrum`).** Before spawning any agent, check:
- `git remote` prints something. If not, stop and tell the user to run `git remote add origin <url>`.
- `command -v gh && gh auth status` succeeds. If not, stop and tell the user to run `brew install gh && gh auth login`.

**Roadmap resume (the commands in the Prerequisites list, plus `roadmap`; never bare `/trevskills-scrum`).** Run `B roadmap-show`. If it prints a roadmap with a `running` step whose `job` is `done` on `$F/board.json` (its hook was missed), run `B roadmap-next <that job>` first and, when it prints a step, do **Roadmap lane** **Starting a step** with it, before the requested command.

If `$F/project.md` is missing, do the **first-run setup** below. Otherwise go to the command.

**Record your terminal** (New job, `start`, `approve`, `rework`, `discuss`, `resume`, `lilguy`; once you know the job id `$ID`). This is what the dashboard's Open terminal button brings to the front. Each field is skipped, never an error, when it isn't usable:

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

   `- Base branch: <branch>` is an optional line Trevor adds by hand to make every job target `<branch>` instead of `origin/HEAD` (see **New job** step 2). First-run setup never writes it.

   `- Orchestrator model: <model>` is an optional, hand-added line: the `--model` for headless orchestrator sessions, meaning only the headless `start` and `resume` sessions (BigBoy children started by **BigBoy lane** step 3, and the dashboard's Run now, reopen, Resume and Play). It defaults to `sonnet`. `inherit` (any case) passes no `--model`, so the session keeps its default model. A blank or malformed value (not `^[A-Za-z0-9._-]+$`) also gives `sonnet`. Interactive sessions, approve, rework, digest, research and agent `model:` pins ignore it. First-run setup never writes it.

   `- E2E: <command>` is another optional line Trevor adds by hand: an end-to-end test command the **Check gate** runs when the diff touches `UI globs`, and the BigBoy reviewer runs on main. First-run setup never writes it either.

   `- Cloud environment: <id>` is a third optional, hand-added line: the claude.ai/code environment the **Cloud lane** starts sessions in.

5. Tell the user this repo is now on the dashboard: open the **Trevskills Scrum** app, or run `python3 ~/.claude/skills/trevskills-scrum/serve.py` from anywhere, then go to http://localhost:8765. One dashboard shows every project.

## Commands

For `approve` and `rework`, load the job from `$F/board.json`: `WT` is its `worktree`, `BASE` is its `base`, and `DEFAULT` is `BASE` with the `origin/` prefix removed. `N` is its `round`.

- **`/trevskills-scrum`** (no args): first run **Cloud lane** **Sync** when a job is in stage `cloud`. Then print each job's `id stage round reason pr` from `$F/board.json`, and the dashboard command.
- **`/trevskills-scrum next`**: first run `B watchdog`. It flags every job stuck 30+ minutes in `spec`, `build`, `check`, `review` or `approve` with no live session as `needs-human` (reason `stalled in <stage>: ...`) and prints `{"flagged"}`; a stuck `spec` job with no `feature.md` (a claim whose session died first) is aborted instead and its backlog line reopened in place, never flagged; for each flagged id that has a `parent`, run **BigBoy lane** step 6 with `ID=<that id>`. Then run `B next`. It claims the first `- [ ]` line in `$F/backlog.md` that waits on nothing, under the board lock, creates the job, and prints `{"id", "feature"}`; two sessions never get the same item. If `id` is null, say the backlog is empty (or every open item waits on a prerequisite) and stop. Otherwise run **New job** from step 1b with `ID=<id>` and that feature text (step 2 records your terminal).
- Backlog lines look like `- [ ] [5] Text {#k3f9} {needs #a1b2} <!-- estimate reason -->`; the `[5]` is Fibonacci difficulty points. The optional ` {#k3f9}` is the item's id (4 chars `[a-z0-9]`) and ` {needs #a1b2 …}` lists the ids of items it waits on; both sit after the text and before any ` → <job>`, and the item's text excludes them. A prerequisite still blocks while its line is open, or while the job that claimed it is not `done` or `aborted`; an unknown id never blocks. `next` and `runall-start` skip an item that waits: `next` takes the first open item that waits on nothing (`next --index` on a waiting item fails with `waits on #<id>`), and `runall-start` leaves an item open when it waits on a job claimed outside the run. The optional ` {setup: <step>; <step>}` marker, after ` {needs …}` and before any ` → <job>`, is a Human setup checklist that only Trevor can do (added with `B backlog-add --setup`): `next` skips the item (`next --index` on it fails with `waits on Human setup`), `runall-start` leaves it open, and an item that needs it stays open too. The dashboard Backlog dialog's Setup done button on that item removes the marker (backlog op `setup-done`), and the item is then claimable like any other. Only ever change `backlog.md` through `B` (`next`, `backlog-add`, `triage-apply`), never by hand-editing it. Checks only a human can do live in `manual-checks.md` instead (`- [ ] Text`, added with `B manual-add`); no job ever runs them.
- **`/trevskills-scrum <feature text>`**: run **New job**.
- **`/trevskills-scrum askme [1-3] <feature text>`**: run **New job** with the **Askme** step (1c) at that level. With no level, or a level that is not 1, 2 or 3, use level 2 and treat the whole rest as the feature text.
- **`/trevskills-scrum bigboy <feature text>`**: run **New job** steps 1-2, then `B set $ID lane=bigboy` and go straight to the **BigBoy lane**. No spec writer runs for the parent.
- **`/trevskills-scrum lilguy <feature text>`**: run the **Lilguy lane**. No agent is spawned.
- **`/trevskills-scrum roadmap <brief>`**: draft `$F/roadmap.md` from the brief and, on Trevor's yes, start P1 S1 (**Roadmap lane**).
- **`/trevskills-scrum roadmap`** (no brief): print the roadmap status block (**Roadmap lane**). It starts nothing.
- **`/trevskills-scrum start <id>`**: the dashboard's Run now button already claimed a backlog item as job `<id>` and wrote its `feature.md`. Load the job and run **New job** from step 2. For a BigBoy child (the job has a `parent`; started as `/trevskills-scrum start <child>` by **BigBoy lane** step 3 or by the dashboard's Setup done), run **BigBoy lane** step 4 (Spec refresh) after step 2: it skips step 3 when `spec.md` exists and no refresh is needed.
- **`/trevskills-scrum start <id> askme <1-3>`**: the same, but the dashboard's Run now had Askme set, so it opened this session in a new Terminal window. Load the job and run **New job** from step 1c (Askme) at that level; a missing or bad level means level 2.
- **`/trevskills-scrum approve <id>`**: the job must be `needs-human`. **refuse** (and suggest `/trevskills-scrum rework <id> "<feedback>"` instead) if the job has no `worktree`, has no commits beyond `BASE` (`git -C "$WT" log --oneline "$BASE"..HEAD` is empty), or its reason starts `blocked`, `spec writer`, `obsolete` or `stalled`; there is nothing approved to merge (for `stalled`, suggest `/trevskills-scrum resume <id>` instead). Also run Merge step 1's **main checkout guard**; while it fails, **refuse** with the same message it would write as the reason (`Uncommitted change in <repo name>: <first files>. Fix: commit + push it (or undo it), then click Approve & merge.` or `<repo name> main checkout is on <branch>, not <default>. Fix: switch it back to <default>, then click Approve & merge.`) and don't write `human-approval.md`. Once it passes, continue. When the prompt says `Trevor confirms /trevskills-migrate has already been run` (sent by the dashboard when he ticks that box), write `git -C "$WT" rev-parse HEAD:prisma` to `$F/jobs/<id>/migrated.md` so **Merge**'s schema guard skips **Migrate**. Then **record your terminal** with `ID=<id>`, write `$F/jobs/<id>/human-approval.md` containing `Approved by Trevor <ISO date>` and run **Merge**.
- **`/trevskills-scrum rework <id> <feedback>`**: append `## <ISO date>\n<feedback>` to `$F/jobs/<id>/rework.md`. **Off-track BigBoy parent** (the job has `children` and its reason starts `bigboy off track`): Trevor's note is his decision on the plan, so no builder runs. **Record your terminal** with `ID=<id>`, run `B set --unpause <id> stage=running reason=`, then `B chain-lock <id> <id>` (same tries and stop as **BigBoy lane** step 5). Spawn `scrum-tracker` with the **BigBoy lane** step 5 prompt (`P=<id>`) plus the line `Trevor's decision is in PARENT_DIR/rework.md: read it first and follow it.` Handle its `track-N.md` exactly as step 5 sub-step 1 does (ADJUST re-runs step 2 for the rewritten children; OFF TRACK sets the off-track reason again, unlocks and stops), then run step 5 sub-steps 2-3 (with `B chain-unlock <id> <id>`) and stop. Every other job: run `B set --unpause <id> stage=build reason= limit=<round+2>`, then **record your terminal** with `ID=<id>`. If the worktree is gone, recreate it from the branch with `git worktree add "$REPO/.claude/worktrees/scrum-<id>" scrum/<id>`. If the job's `lane` is `debug` and `$F/jobs/<id>/assessment.md` is missing or its first line is not `ASSESSMENT: READY`, no builder ever ran, so re-diagnose instead: move `assessment.md` (if present) to `assessment-prev.md`, run **Debug lane** from step 1 with the debugger prompt extended by `Read JOB_DIR/rework.md first.` and the re-spawn line, and continue as Debug lane does. Otherwise resume the builder (see **Resuming the builder**) pointing it at `rework.md`, then continue at **Check gate**.
- **`/trevskills-scrum discuss <id> [<note>]`**: an interactive talk-through before anything goes back to the builder. The dashboard's Discuss first button opens it in a new terminal, with whatever Trevor typed as the note. The job must be `needs-human`. **Record your terminal** with `ID=<id>`. Read only the board `reason`, the first lines and `## Rulings` of `decision.md`, `rework.md`, and `migrate-stop.md` if it exists. Then tell Trevor in plain words:
  1. What is stopping the job.
  2. Whether a rework can clear it. A `Hard stop:` never clears through rework: the builder can fix code, but the approver stops again on the same hard stop. Only `approve` clears it (for `migrate stopped`, approve runs `/trevskills-migrate` again through **Merge**).
  3. What his note would actually do: change code (rework), give the go-ahead (approve), or neither.

  Discuss until you agree. Spawn nothing, edit nothing and run no command until Trevor picks one. Then carry it out in this session exactly as that command: `approve <id>`, or `rework <id> "<the agreed feedback, written so the builder can act on it>"`. If he picks neither, stop.
- **`/trevskills-scrum resume <id>`**: the dashboard's Resume button starts it headless for a job `B watchdog` flagged or one stopped for another resumable reason, and its Play button for a job Trevor paused. The job must be `needs-human` with a reason starting with one of `board.py`'s `RESUMABLE` prefixes: `stalled in <stage>`, `bigboy off track`, `bigboy review: main not updated`, `bigboy blocked` or `Base branch `; otherwise **refuse** and stop. **Record your terminal** with `ID=<id>` right after the first `B set` below (a paused job refuses every write before `B set --unpause`), or first when the branch has none. Then re-enter by reason. **`bigboy off track`**: run `B set <id> stage=running reason=`, then **BigBoy lane** step 5 sub-steps 2-3 with `P=<id>` (`B chain-lock <id> <id>`, `B ready`, `B chain-unlock <id> <id>`, then **start** each ready child, or step 7 when `all_merged`), skipping the tracker. **`bigboy review: main not updated`**: re-check that the main checkout fast-forwards to `origin/$DEFAULT`: `git -C "$REPO" fetch` (`DEFAULT` from the job's `base`), then `git -C "$REPO" merge-base --is-ancestor HEAD origin/$DEFAULT`, plus **Merge** step 7's **Fast-forward main** (its guard and fast-forward). If any of it fails, set the same reason again and stop. Otherwise run **BigBoy lane** step 7 with `P=<id>`, without its `main not updated` check. **`bigboy blocked`**: read the parent's children from the board and run `B abort <c> --reason 'skipped: depends on aborted <ids>'` for only the `waiting` children that depend (directly or through another `waiting` child) on an aborted sibling (`<ids>` are the aborted children it depends on). If none do, set the same reason again and stop. Otherwise run `B set <id> stage=running reason=`, then **BigBoy lane** step 5 sub-steps 2-3 with `P=<id>` (step 7 when `all_merged`). **`Base branch `**: run `B set <id> stage=spec reason=`, then **New job** from step 2. Step 2 re-reads project.md and stops again with the same reason if the line is still bad. **`stalled in <stage>`**: load it like `approve` (`WT`, `BASE`, `DEFAULT`, `N`), run `B set --unpause <id> stage=<stage> reason=` (first: a paused job refuses every other write), and re-enter the pipeline at that stage: `spec`: **New job** from step 3; `plan`: delete `$F/jobs/<id>/plan.md` if present and run **BigBoy lane** from step 1; `merging`: **Merge** from step 1; `build`: resume the builder (see **Resuming the builder**) with `Your session was interrupted: finish the work, commit, update build.md.`, then **Check gate**; `check`: **Check gate** from step 2 (step 1 already set the round); `review`: run `B sync <id>`, spawn (as **Review** step 3) only the reviewers named in its `missing` (the skip and carried-forward files of **Review** step 2 are written before any spawn, so `missing` never names them; a resumed session can't tell how the round started, so it writes no new carried-forward file and spawns them on the full diff), then continue at **Review** step 4 (a `lane=fast` job spawns only `scrum-review-code`, when `review-code.md` is missing, and continues as **Fast lane** step 2 does after its spawn); `approve`: **Approve** step 1. From there the job runs to the end as a `start` session would, including **BigBoy lane** chaining for a child.
- **`/trevskills-scrum digest`**: run **Digest**. The dashboard's Digest now button starts it headless.
- **`/trevskills-scrum cloud [N]`**, **`/trevskills-scrum cloud-sync`**, **`/trevskills-scrum cloud-home <id>`** and **`/trevskills-scrum cloud-job <id> <feature text>`**: run the **Cloud lane**.
- **`/trevskills-scrum run-all`**: run **Run all**: triage, then schedule every open item in parallel where files don't overlap. The dashboard's Run all button opens it in a new Terminal window when Trevor picks Askme Off.
- **`/trevskills-scrum run-all askme <1-3>`**: the same, with the **Askme** step of **Run all** at that level, so this session asks Trevor about every item before any child starts. The dashboard's Run all button opens it when Trevor picks level 1, 2 or 3. A missing or bad level means level 2.

## New job

Every needs-human reason is `<what is wrong>. Fix: <exact fix>`, with no double quotes or backticks. A job goes needs-human only when its card offers Approve, Resume or Send back; a stop whose only fix is Abort is handled by the agents instead.

**Auto-abort instead of needs-human.** Some stops below run `B abort $ID --requeue --reason 'requeue: <error>'` (the job lands in Done as aborted and its feature goes back on the backlog), or `B abort $ID --reason 'looks already fixed: ...'`, and stop. The `<error>` part is quoted under the **Untrusted reason text** rule. For a job with a `parent` (a BigBoy child), the requeue abort runs without `--requeue` (its text is a planner ticket, not a backlog item), and after any of these aborts the run then does **BigBoy lane** step 6. The **Roadmap lane** stop rule (`B roadmap-stop`) applies to these aborts as it does to needs-human. Inside a cloud-job session, they are reported to GitHub as **Cloud lane** **Needs-human** says. The final report says the job was auto-aborted (requeued, or auto-closed as looks already fixed) and why.

For a BigBoy child (the job has a `parent`), every time this run sets the child `stage=needs-human`, also run **BigBoy lane** step 6, so independent children still start. Every time this run sets a job `stage=needs-human`, also apply the **Roadmap lane** stop rule (`B roadmap-stop` only when that job, or its `parent`, is a roadmap step's `job`).

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
2. **Base:** first **record your terminal** (Setup). Then run `git fetch origin`. Read the optional base branch: `BB=$(sed -n 's/^- Base branch: *//p' "$F/project.md" | head -1 | sed 's/[[:space:]]*$//')`.
   - **`BB` empty (line missing or blank):** `DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's#^origin/##')`. If `symbolic-ref` fails (no `origin/HEAD`), run `git remote set-head origin -a` and try `symbolic-ref` again.
   - **`BB` set:** if it does not match `^[A-Za-z0-9._/-]+$`, run `B set $ID stage=needs-human reason="Base branch line in scrum/project.md is malformed. Fix: correct or remove it, then click Resume."` and stop before the spec writer. If `git rev-parse --verify -q "origin/$BB"` fails, run `B set $ID stage=needs-human reason='Base branch <BB> not found on origin. Fix: push <BB> to origin or remove the Base branch line from scrum/project.md, then click Resume.'` and stop before the spec writer. Otherwise `DEFAULT=$BB`.

   Then `BASE=origin/$DEFAULT`. Run `B set $ID base=$BASE`.
3. **Spec:** if `$F/jobs/$ID/spec.md` already exists (pre-written from the backlog), skip the spec-writer spawn and the respawn below and go straight to 3b and 3c; this skip never applies when step 3 runs with the `Refresh spec.md:` line from **BigBoy lane** step 4, which still spawns over the existing spec.md. Otherwise spawn `scrum-spec-writer` (see **Routing**) and wait for it. Prompt:
   ```
   JOB_DIR=$F/jobs/$ID
   WORKTREE=none
   BASE=$BASE
   ROUND=0
   PROJECT=$F/project.md
   Write spec.md for this job.
   ```
   **Model:** only when `$F/jobs/$ID/feature.md` exists, outside a `lilguy` or `cloud` lane session, pick the model once per job: reuse `jev.log`'s `model` decision, else run `python3 ~/.claude/skills/trevskills-scrum/jev-gate.py model $F/jobs/$ID` with Bash timeout 90000 and take its one-word output. When it is `sonnet` or `opus`, pass Agent override `model: "<word>"` to every cloud `scrum-spec-writer` spawn of this step (first spawn, respawn, cloud retry, `Refresh spec.md:`) and the `scrum-builder` spawn in step 5. Otherwise pass no override (Opus).
   If `spec.md` is missing afterwards, spawn it once more. If it's still missing, run `B abort $ID --requeue --reason 'requeue: spec writer produced nothing'` and stop (see **Auto-abort instead of needs-human**). After each spawn, record it: `B set $ID specwriter=<id>` for a cloud spawn (the returned agent id), or `B set $ID specwriter=local` when **Routing** ran it locally. When the cloud retry replaces a local run, record the cloud agent's id instead.
   3b. **Obsolete:** if the first line of `spec.md` starts with `OBSOLETE:` (`head -1 "$F/jobs/$ID/spec.md" | grep -q '^OBSOLETE:'`), the request needs no change, so abort the job yourself. Strip any single quotes from the rest of that line, then run `B abort $ID --reason 'obsolete: <rest of that line>'` and stop: create no worktree and spawn no builder. The final report says the job was auto-aborted as obsolete and why.
   3c. **Lane:** read the `Lane:` line from `spec.md` and run `B set $ID lane=<fast|standard|debug|bigboy>`. Set `lane=debug` when it says exactly `Lane: debug`, whatever the `Hard stops:` and `UI surface:` lines say. Set `lane=bigboy` when it says exactly `Lane: bigboy`, whatever the other header lines say; the job then goes to the **BigBoy lane** and gets no worktree (skip steps 4-6). A BigBoy child (the job has a `parent`) never gets `bigboy`: for it, `Lane: bigboy` counts as `standard`. Set `fast` only when it says exactly `Lane: fast`, the `Hard stops:` line is `none`, and the `UI surface:` line is `no`. Set `standard` in every other case: the line is missing or malformed, or it says `fast` but `Hard stops:` is anything but `none` or `UI surface:` is `yes`.
      **Human setup:** then, when the job has no `parent` or its parent's `lane` is `runall` (a **Run all** child; so this skips a BigBoy child, whose planner ticket carries its own `Human setup:`), its lane is not `bigboy`, this is not a **Cloud lane** job session, `spec.md`'s `Human setup:` line is present and not `none`, and its `## Waiting on setup` section has a non-empty line, park the deferred part in the backlog: remove every `'` from the `Human setup:` value and from that line, run the **Dupe check** below on it, then `B backlog-add --setup='<Human setup value>' -- '<that line> (from $ID)'`. Then continue the job: the spec already covers only the part that works without the setup. A missing or `none` line, or a missing or empty `## Waiting on setup` section, adds nothing, and so does a re-run of this step (a resume at `spec`) when `backlog.md` already has a line containing both `(from $ID)` and `{setup:`. A failing `backlog-add` adds nothing and never stops the job; name it in the final report as `Human setup not parked: <its error>`.
      **Dupe check** (before every `B backlog-add`): when `$F/backlog.md` has an open `- [ ]` line, pipe each new item, every `'` removed, to `python3 ~/.claude/skills/trevskills-scrum/jev-gate.py dupe $F/jobs/$ID` (one call per item, Bash timeout 90000; a BigBoy parent uses `$F/jobs/$P`). On output `dupe <item>`, append ` (possible dupe of <item>)`, every `'` removed, to the text passed to `backlog-add`. The item is always added, whatever the output.
4. **Worktree:**
   ```bash
   WT="$REPO/.claude/worktrees/scrum-$ID"
   git worktree add "$WT" -b "scrum/$ID" "$BASE"
   find "$REPO" -maxdepth 1 -name '.env*' | while read -r e; do git -C "$REPO" ls-files --error-unmatch -- "$(basename "$e")" >/dev/null 2>&1 || ln -sfn "$e" "$WT/$(basename "$e")"; done
   ```
   A tracked `.env*` file (e.g. `.env.example`) is never symlinked: the worktree already has it, and a symlink over it is a typechange every reviewer flags.
   Then `B set $ID worktree=$WT stage=build`.
5. **Build:** spawn `scrum-builder` (see **Routing**) with step 3's **Model:** override and wait for it. Name it `builder-$ID` if the Agent tool accepts a name. Prompt: the 5 lines with `WORKTREE=$WT` and `ROUND=0`, plus `Implement spec.md. Write build.md.` Record the returned agent id/name with `B set $ID builder=<id>`. If `build.md` starts `STATUS: BLOCKED`, run `B set $ID stage=needs-human reason='blocked: <first reason line>. Fix: type what the builder needs and click Send back to builder.'` and stop. If the job's `lane` is `debug`, see **Debug lane** instead of this step.
6. Continue at **Check gate**.

## Run all

Cleans the backlog, then runs every open item as a child job of one Run-all parent, in parallel where files don't overlap, with nobody watching. Setup and Prerequisites apply. Trevor stops it by interrupting or closing its Terminal window.

1. Run `B triage-start`. Under the board lock it claims `$F/triage/<id>/` and prints `{"id", "open"}`. If `id` is null, say the backlog is empty and stop.
2. Spawn `scrum-triager` with the Agent tool override `model: "sonnet"` (first spawn and the respawn below) and wait for it. Prompt:
   ```
   TRIAGE_DIR=$F/triage/<id>
   BACKLOG=$F/backlog.md
   PROJECT=$F/project.md
   Write plan.json for this triage.
   ```
   If `$F/triage/<id>/plan.json` is missing afterwards, spawn it once more.
3. Run `B triage-apply <id>`. It merges, retires, moves manual-only items to `$F/manual-checks.md`, estimates and adds dependencies (the plan's `depends` entries become `{needs …}` markers) under the board lock, skips stale entries, and writes `$F/triage/<id>/report.md` and `$F/triage/latest.md`. If it exits non-zero (including when plan.json is still missing), write `Triage <id> failed: <message>` to `$F/triage/latest.md`, with its error line as the message, and continue. A failed triage never blocks the run.
4. Run `B watchdog`; for each flagged id that has a `parent`, run **BigBoy lane** step 6 with `ID=<that id>`. Then run `B runall-start`. Under the board lock it makes a `lane=runall` parent with every open backlog item as a `waiting` child and prints `{"id", "children"}`. A child whose item needs another item claimed in the same run `depends_on` that sibling, so `B ready` holds it until the sibling is `done`; an item waiting on a job outside the run stays open and gets no child. If `id` is null, say the backlog is empty (or every open item waits) and stop. Otherwise `P` is that id.
5. **Askme** (only for `run-all askme <n>`; otherwise skip to step 6). Record no terminal here; Run all never does. For each child in `runall-start`'s `children`, in that order, run a question round with Trevor in this same session, exactly as New job step 1c does for one job: read `$F/jobs/<child>/feature.md` (and `$F/jobs/<child>/spec.md` when the item came with one), ask at that level's semantics from step 1c (level 1 only what blocks the build, level 2 a moderate number, level 3 thorough; a bad or missing level means level 2), with follow-ups when an answer is unclear. Say which item each round is about. Spawn no agent and edit no file except the children's `feature.md` and `spec.md` while asking. After each child's round, append its pairs to `$F/jobs/<child>/feature.md`, one pair per question asked, follow-ups included:
   ```
   ## Q&A
   - Q: <question>
     A: <Trevor's answer>
   ```
   A child with no questions gets no `## Q&A` section. When a child already had a pre-written `spec.md` and got at least one Q&A pair, delete that `spec.md`: the answers are Trevor's decisions, so its spec is rewritten from them in step 6 or in its own `start`. A child with no pairs keeps its `spec.md`. If Trevor says to skip or stop, write the pairs answered so far for the current child (and delete its `spec.md` if it got any), ask nothing for the remaining children, and carry on. This is the only place Run all asks questions; no child `start` session ever asks.
6. Run **BigBoy lane** step 2 for P's children.
7. Run **BigBoy lane** step 3 for `P`, then give the final report. Never ask questions here outside step 5.

The final report lists the Run-all parent id, the children it created, which children started in this session, then what the triage merged, retired, moved to manual checks, estimated and added dependencies for (counts from `triage-apply`, `depends` included, or the failure line).

## Fast lane

Applies only while the job's `lane` on the board is `fast`. A job with no `lane`, or `lane=standard`, never reads this section. Same builder, same Check gate; then one diff-only code review and straight to Merge, with no approver.

1. **Promotion (deterministic).** Promoting means running `B set $ID lane=standard` and appending `Promoted to standard: <trigger>` to `$F/jobs/$ID/promoted.md`; the job then continues on the standard path from where it is. A standard job is never set back to fast. You never judge the conditions yourself: run `B route-check $ID` (add `--clean-start` only when this session knows the round was not started by the Merge **Conflicts** step) and promote with trigger = its `promote` field whenever that is non-null; a `null` `promote` means the job stays fast.
   - **2nd check failure:** when `check.md` says `CHECK: FAIL` for the 2nd time in a round, run `B route-check $ID --check-fails 2` (`check.md` is overwritten per attempt, so you pass the count). Its `promote` is then `check failed twice`. The fix attempts in **Check gate** step 4 then carry on as standard.
   - **After `CHECK: PASS`, before Review**, run `B route-check $ID`. This runs again on every round, including after the Merge **Conflicts** step sends the job back to the Check gate. It checks, in order, against `git -C "$WT" diff --numstat`/`--name-only "$BASE"...HEAD`: a binary file; more than 100 added+deleted lines; more than 3 files (exactly 100 lines or exactly 3 files stays fast); the Merge schema guard regex or `(^|/)\.env`; `UI globs` from `project.md`; then the sensitive-path regex, case-insensitively: `grep -iE '(^|/)(middleware|proxy)\.[cm]?[jt]sx?$|auth|session|login|signin|signup|password|permission|payment|billing|checkout|stripe|webhook|secret|credential'` (trigger `sensitive path <first matching file>`; **Review** step 2's Security skip uses this same regex). A diff it can't read promotes (`diff unreadable`).
2. **Review.** Run `B set $ID stage=review`. Write `round-$N/review-security.md`, `round-$N/review-ux.md` and `round-$N/review-ui.md` yourself, each containing exactly:
   ```
   VERDICT: PASS
   Skipped by orchestrator: fast lane.
   ```
   Spawn only `scrum-review-code`, with the 5 lines (`ROUND=$N`), the line `LANE=fast`, and `Review this round. Write only your own review file.` Wait for it, then handle `B sync $ID` exactly as **Review** step 4. That includes the `review-pass`/`review-changes` line for a local build.
3. **Route:**
   - `verdict` is `PASS`: go straight to **Merge**. Spawn no approver; there is no decision.md. The PR uses the no-Merge-summary fallback in Merge step 3 (job title, spec acceptance criteria as bullets), and the body line `Approved by the scrum approver. Spec, reviews and decision: scrum/jobs/$ID/` is replaced by `Fast lane: check gate + code review. Spec and review: scrum/jobs/$ID/`. The schema guard still runs unchanged. With no decision.md, the `Restart:` line counts as `none`.
   - `verdict` is `CHANGES` and `round < limit`: resume the builder as in **Review** step 5, run `B set $ID stage=build`, and go to **Check gate**. The job stays fast.
   - `verdict` is `CHANGES` and `round >= limit`: go to **Approve**, as standard does.

## Debug lane

Applies only while the job's `lane` on the board is `debug`. A job with any other `lane` never reads this section. It replaces New job step 5; Check gate, Review and Approve then run as standard, with the debug additions in **Check gate**.

1. **Diagnose.** Spawn `scrum-debugger` and wait for it. Prompt: the 5 lines with `WORKTREE=$WT` and `ROUND=0`, plus `Reproduce and diagnose. Write assessment.md.` Whenever the debugger is spawned again for the same job (step 2's re-spawn, or `rework`), its prompt also gets the **re-spawn line**: `An earlier attempt may have committed a repro test: reuse it if it still fails for the reported reason, otherwise remove it with git rm and commit that removal.`
2. **Validate `$F/jobs/$ID/assessment.md`.** It is invalid when it is missing, its first line is not one of `ASSESSMENT: READY`, `ASSESSMENT: NO_REPRO` or `ASSESSMENT: BLOCKED`, or a READY one lacks a `Repro:` line, a `Repro test:` line or at least one `- ` line under `## Allowed files`, or has a `## Compliance` line containing `conflict`. A READY one is also invalid unless its `Repro:` value (trimmed) starts with project.md's `Test:` command (trimmed), followed by a space or the end of the line. When `Test:` is `none`, a READY one is valid only when the trimmed `Repro:` value's first space-separated word is one of `python3`, `python`, `node`, `bash`, `sh`, `ruby` or `perl`, and its second word equals the trimmed `Repro test:` path exactly; more arguments may follow after a space. Anything else is invalid: a bare path, the path in a later position, or a different first word. It is also invalid when the `Repro:` value contains any of `;` `&` `|` `` ` `` `$` `<` `>` or a newline. If invalid, delete it and re-spawn the debugger once, with the re-spawn line. If it is still missing or invalid, run `B abort $ID --requeue --reason 'requeue: debugger output unreadable'` and stop (see **Auto-abort instead of needs-human**).
3. **No repro or blocked.** `<line 2>` is line 2 of assessment.md after removing every `` ` ``, `$`, `"` and `'` from it. For `ASSESSMENT: NO_REPRO`, run `B abort $ID --reason 'looks already fixed: no repro — <line 2>'` and stop; the final report says the job was auto-closed as looks already fixed and why (see **Auto-abort instead of needs-human**). For `ASSESSMENT: BLOCKED`, run `B set $ID stage=needs-human reason='debug: blocked — <line 2>. Fix: click Discuss first.'` and stop.
4. **Repro must fail.** Run the `Repro:` command in `$WT`. Write `$F/jobs/$ID/repro-before.md`: first line `REPRO: FAIL` (non-zero exit) or `REPRO: PASS` (exit 0), then `Commit: <git -C "$WT" rev-parse HEAD>`, the exit code, and the last 40 lines of output in a fenced block. If the exit code is 0, run `B abort $ID --reason 'looks already fixed: repro passes on <short HEAD> — see repro-before.md'` (`<short HEAD>` is `git -C "$WT" rev-parse --short HEAD`) and stop; the final report says the job was auto-closed as looks already fixed and why.
5. **Build.** Spawn the builder as New job step 5 does (same name, same `B set $ID builder=`, same BLOCKED handling), but the last prompt line is `Implement the fix in JOB_DIR/assessment.md. Change only the files under ## Allowed files. Write build.md.` Then continue at **Check gate**.

## BigBoy lane

Applies only to a job whose `lane` on the board is `bigboy` or `runall` (the **parent**), and to its **children**. A request too big for one job is split by `scrum-planner` into 2-5 tickets; each ticket runs as its own child job (spec → build → check → review → approve → its own PR, in its own lane and its own session) and merges on its own. The parent gets no worktree, branch or PR, and never goes through Check gate, Review, Approve or Merge. `B next` never claims a child. A `runall` parent comes from **Run all**: steps 1 and 7 never run for it, and it has no plan.md. In steps 1-3, `$ID` is the parent; in steps 4-7, `P` is the child's `parent` from the board.

1. **Plan.** Run `B set $ID stage=plan`. Spawn `scrum-planner` and wait for it. Prompt:
   ```
   JOB_DIR=$F/jobs/$ID
   PROJECT=$F/project.md
   Read JOB_DIR/spec.md first when it exists; do not re-audit its ## Findings.
   Write plan.md for this job.
   ```
   Then run `B plan-apply $ID`. Under the board lock it checks plan.md (first line `PLAN: READY`, 2-5 tickets, every `Depends on:` names a known ticket other than itself with no cycle, exactly one `Exposure: yes` ticket and it depends on every other), creates one `waiting` child job per ticket with its `feature.md`, sets the parent's `children`, moves the parent to `running`, and prints `{"children": [...]}`. A refused plan creates nothing. If it exits non-zero, delete `$F/jobs/$ID/plan.md`, spawn the planner once more, and run `B plan-apply $ID` again. If that fails too, take its error line, strip quotes (`'` and `"`) and backticks, run `B abort $ID --requeue --reason 'requeue: planner output unreadable: <error line>'` and stop (see **Auto-abort instead of needs-human**).
2. **Child specs, startable children only.** Spawn one `scrum-spec-writer` per child whose `depends_on` is empty, **in ONE message**, in the background, and wait for all of them (see **Routing**: each child is routed on its own, and local ones run as background subprocesses alongside the cloud ones). Each prompt is the New job step 3 prompt with `JOB_DIR=$F/jobs/<child>`. Every other child gets its spec in its own `start` session (step 4 runs New job step 3 when `spec.md` is missing); until then a child with no spec.md runs alone, which is the accepted cost. Then, for each child spawned for here:
   - **Obsolete:** if its `spec.md` starts with `OBSOLETE:`, run `B abort <child> --reason 'obsolete: <rest of that line, single quotes stripped>'`. Its dependents never become ready.
   - **Lane:** otherwise run New job step 3c with `ID=<child>` (`Lane: bigboy` counts as `standard`). A child without a `spec.md` is fine: its own `start` writes it.
3. **Start.** Run `B ready $ID` and **start** each id in `ready`. To start a child (here, in step 5 and in step 6), run detached from the main checkout, logging to `scrum/runs/`:
   ```bash
   mkdir -p "$F/runs"; LOG="$(date +%Y%m%d-%H%M%S)-start-<child>.log"
   OM=$(sed -n 's/^- Orchestrator model: *//p' "$F/project.md" | head -1 | sed 's/[[:space:]]*$//')
   case "$OM" in [Ii][Nn][Hh][Ee][Rr][Ii][Tt]) OM= ;; ""|*[!A-Za-z0-9._-]*) OM=sonnet ;; esac
   MODEL=(); [ -n "$OM" ] && MODEL=(--model "$OM")
   (cd "$REPO" && CLAUDE_NOTIFIER_DISABLE=1 nohup claude -p "/trevskills-scrum start <child>" "${MODEL[@]}" --permission-mode acceptEdits > "$F/runs/$LOG" 2>&1 < /dev/null &)
   B set <child> runlog=runs/$LOG
   ```
   `OM` is the `- Orchestrator model:` line (see Setup): blank, missing or malformed gives `sonnet`, and `inherit` drops `--model`. `MODEL` is an array on purpose: zsh never word-splits `${OM:+--model "$OM"}`, so that form passes one word and `claude` dies with `unknown option`.
   This session is then done with the parent: each child chains the next from its own Merge step 7. Give the final report.
4. **Spec refresh** (in the child's own `start` session, after New job step 2). For each id in the child's `depends_on`, list the files its PR changed: `gh pr diff <that job's pr> --name-only`. Compare them, as exact paths, with the backtick-quoted paths under `## Likely files` in the child's `spec.md`. If `spec.md` is missing, run New job step 3 as usual. If any path overlaps, run New job step 3 with the extra prompt line `Refresh spec.md: dependencies <ids> merged and changed <files>.`, then step 3b and 3c. Otherwise skip step 3 (3b and 3c ran in step 2). Then continue at New job step 4.
5. **Chaining** (Merge step 7, after `stage=done`, for a job with a `parent`). Sub-steps 1-2 run under P's chain lock, so two children that merge close together never write the same `track-N.md`, rewrite the same waiting child, or claim a child mid-rewrite:
   - **Lock.** Run `B chain-lock $P $ID` with Bash timeout 600000. It waits up to 540 s while another session holds the lock, then prints `{"acquired", "holder"}`. While it prints `"acquired": false`, run it again, up to 4 tries in all. If it still has not acquired the lock, run `B set $P stage=needs-human reason='bigboy chain lock held by <holder>. Fix: if no session for <holder> is running, delete scrum/jobs/<P>/.chain.lock, then click Run now on a waiting child.'` (`<holder>` from its output, `'` removed; `<P>` is the parent id) and stop.
   - **Unlock.** Run `B chain-unlock $P $ID` right after sub-step 2's `B ready $P`, and before every earlier stop: OFF TRACK, or a tracker or spec writer failure that ends this session.
   1. **Tracker.** Skip it when P's `lane` is `runall`. Unless every child of `P` in `$F/board.json` is now `done`, spawn `scrum-tracker` with the Agent tool override `model: "sonnet"` and wait for it. `N` is how many children of `P` are `done`. Prompt:
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
      - `TRACK: OFF TRACK`: run `B set $P stage=needs-human reason='bigboy off track: <line 2 of track-N.md>. Fix: read the latest track file, then click Resume to carry on with the plan or Send back with your decision to replan.'`, start no child, run `B chain-unlock $P $ID`, and stop.
      - `TRACK: ON TRACK`, or a missing or unreadable file: carry on.
   2. Run `B ready $P`. Under the lock it claims (moves to `spec`) every `waiting` child whose `depends_on` are all `done`, whose `setup` is not `pending`, and that can run beside the siblings in progress (a `parallel=no` child, or a `parallel=yes` child whose `spec.md` is missing or has no backtick-quoted path under `## Likely files`, runs alone: only when none is, and none starts beside it; any other child never beside one whose `## Likely files` overlap its own), up to an in-progress cap paced by `~/.claude/usage.json` (written by the `board.py statusline` status line: a Run-all parent's cap of 3 rises to 5 when well under pace and drops to 2 or 1 when over; a BigBoy parent is only ever throttled to 2 or 1; at least 1 child always starts, and running children are never touched), so a second call never returns it again. An aborted child counts as finished, so `all_merged` is true once every child is `done` or `aborted`. When nothing is ready or in progress and not every child is finished, the parent stays `running` with reason `waiting on you in: <ids>` while any `needs-human` or setup-pending child exists (no sound; their actions are on the children); otherwise, when some `waiting` child of a BigBoy depends (directly or through another waiting child) on an aborted one, it sets the parent `needs-human` with reason `bigboy blocked: <aborted ids>. Fix: click Resume to skip the children that depend on them and run the final review.` A later claim, or a child in progress, sets it back to `running` with no reason; a legacy `bigboy blocked` / `run-all blocked` parent is re-evaluated the same way. It prints `{"ready", "merged", "total", "in_progress", "all_merged"}`. Then run `B chain-unlock $P $ID`.
   3. If `all_merged` is true, go to step 7; when P's `lane` is `runall`, run `B set $P stage=done reason=` instead. Otherwise **start** each id in `ready` (step 3; its own `start` runs the step 4 refresh).
6. **After a child stops.** When a child's run sets it `needs-human` or auto-aborts it (**New job** **Auto-abort instead of needs-human**), run `B chain-lock $P $ID` (same tries and stop as step 5), then `B ready $P`, then `B chain-unlock $P $ID`. If `all_merged` is true, go to step 7; when P's `lane` is `runall`, run `B set $P stage=done reason=` instead. Otherwise **start** each id in `ready`, so tickets that don't depend on it keep going. A failed child blocks only its dependents.
7. **Final BigBoy review.** Run `B set $P stage=review`. If Merge step 7 reported `main not updated`, run `B set $P stage=needs-human reason="bigboy review: main not updated. Fix: make the main checkout fast-forward, then click Resume to re-run the review."` and stop. Otherwise spawn `scrum-bigboy-reviewer` and wait for it. Prompt:
   ```
   PARENT_DIR=$F/jobs/$P
   JOBS_DIR=$F/jobs
   BOARD_JSON=$F/board.json
   REPO=$REPO
   PROJECT=$F/project.md
   Review the whole BigBoy on main. Write bigboy-review.md.
   ```
   If the first line of `bigboy-review.md` is neither `BIGBOY: PASS` nor `BIGBOY: GAPS`, delete it and spawn the reviewer once more; if it is still unreadable, treat it as GAPS with no fix ticket.
   - `BIGBOY: PASS`: run `B set $P stage=done reason=`. If plan.md has a `## Phase 2` section and `B roadmap-show` lists `$P` as a step's `job`, run `B roadmap-insert <that p> <that s> bigboy '<its line, every ' removed>'` instead of `backlog-add`; otherwise, with a `## Phase 2` section, run the **Dupe check** (3c, `jev-gate.py dupe`) on it, then `B backlog-add "<its line> (Phase 2 of $P)"`. Either way, then run `B roadmap-next $P` and, when it prints a step, do **Roadmap lane** **Starting a step** with it.
   - `BIGBOY: GAPS` the first time: run `B plan-apply $P --fix`. It adds one child, ticket `FIX`, from the `## Fix ticket` text, with no dependencies, and moves the parent back to `running`. Run step 2 for it, then `B ready $P` and **start** it. When it merges, step 5 brings the parent back here and the reviewer runs once more.
   - `BIGBOY: GAPS` again, or `plan-apply --fix` exits non-zero (no `## Fix ticket`, or the FIX child already exists): the parent goes done and every gap is filed; there is no needs-human. Run `B set $P stage=done reason='merged + gaps: <line 2 of bigboy-review.md>'`. The items are every `## Done when` line marked `— gap —`, plus one item when `## Tests` shows a non-zero exit, each with every `'` removed. When `B roadmap-show` lists `$P` as a step's `job`, run `B roadmap-insert <p> <s> standard '<item>'` for each (`<p> <s>` from that step); otherwise run the **Dupe check** (3c, `jev-gate.py dupe`) on each, then `B backlog-add "<item> (gap of $P)" ...`, one argument per item. Then run `B roadmap-next $P` and, when it prints a step, do **Roadmap lane** **Starting a step** with it, as PASS does.

## Roadmap lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/roadmap.md` when this lane runs.

## Lilguy lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/lilguy.md` when this lane runs.

## Cloud lane

Read `$HOME/.claude/skills/trevskills-scrum/lanes/cloud.md` when this lane runs.

## Check gate

If the job's `lane` is `fast`, see **Fast lane** (promotion on the 2nd failure, and before Review). If the job's `lane` is `debug`, step 2 adds the debug checks and step 4 ends differently.

1. `N = round + 1` (round as stored on the board). Run `mkdir -p $F/jobs/$ID/round-$N`, then `B set $ID round=$N stage=check`.
2. In `$WT`, run each of Test / Typecheck / Lint / Build from `project.md` that isn't `none`. When `project.md` has an `E2E:` line that isn't `none` and any file in `git -C "$WT" diff --name-only "$BASE"...HEAD` matches `UI globs`, also run that E2E command in `$WT`; it is reported like the others, and a non-zero exit is `CHECK: FAIL`. Also run `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)\.env'`; any output is a failure ("committed .env file").
   For `lane=debug`, also run these; each failure makes `CHECK: FAIL` and gets its own entry in check.md:
   - **Repro:** the `Repro:` command from `assessment.md`, in `$WT`. It must exit 0.
   - **Allowed files:** every path in `git -C "$WT" diff --name-only "$BASE"...HEAD` must be listed under `## Allowed files` or be the `Repro test:` path. Otherwise it fails with `outside allowed files: <path>`.
   - **Repro test untouched:** `git -C "$WT" diff --name-only <Commit from repro-before.md> HEAD -- <Repro test path>` must print nothing. Otherwise it fails with `repro test changed`.
3. Write `round-$N/check.md`: first line `CHECK: PASS` or `CHECK: FAIL`, then for each command its exit code and the last 40 lines of output in a fenced block.
4. If it says FAIL, resume the builder (see **Sonnet promotion**) with `Checks failed: read JOB_DIR/round-N/check.md, fix, commit, update build.md.` **E2E triage:** when the E2E command from step 2 ran and exited non-zero, first spawn `scrum-review-e2e` with the 5 lines (`ROUND=$N`) plus `Triage the failing E2E run. Write only your own review file.`, and wait for it; then the resume message is `Checks failed: read JOB_DIR/round-N/check.md and JOB_DIR/round-N/review-e2e.md, fix, commit, update build.md.` instead. Then re-run steps 2–3, overwriting `check.md`. Allow up to **3** fix attempts. While the board says `builder=local`, attempts 1 and 2 re-run the local builder and attempt 3 is its cloud retry (see **Routing**). If it still fails, skip the review and go to **Approve**; the approver rules on the failing check. Exception: a `lane=debug` job that still fails after the 3rd fix attempt never goes to **Approve**: run `B set $ID stage=needs-human reason="debug: 3 failed fixes — question the design. Fix: click Discuss first."` and stop.
5. If it says PASS, go to **Review**.

## Review (WAIT FOR ALL)

If the job's `lane` is `fast`, see **Fast lane** instead of this section.

1. Run `B set $ID stage=review`. Write `git -C "$WT" rev-parse HEAD` to `round-$N/head.txt` (the HEAD this round reviews).
2. **Which reviewers run.** Run `B review-plan $ID`, adding `--incremental` only on a round `N >= 2` that this session started through step 5's `CHANGES` route (never after the Approve `REWORK` route, the Merge **Conflicts** step, or in a resumed session that can't tell how the round started). It decides incremental re-review or full review, writes the carried-forward and skip files into `round-$N/` before any spawn, and prints `{"spawn": [...], "since": ...}`. `since` is the SINCE sha on an incremental round and `null` on a full one; on a full round a reviewer missing from `spawn` was skipped (security: no sensitive files in diff; ui and ux: no `UI globs` file in diff, decided from the diff, never from the spec's `UI surface:` line).
   - **Jev gate (additive only).** Only when `since` is `null` and at least one of `security`, `ui`, `ux` is missing from `spawn`, ask `reviewer-security` (security missing) and/or `reviewer-ui` (ui and ux missing). Run each with Bash timeout 90000:
     ```bash
     { git -C "$WT" diff --stat "$BASE"...HEAD | tail -1; git -C "$WT" diff --name-only "$BASE"...HEAD; } | tr '\n' ' ' | python3 ~/.claude/skills/trevskills-scrum/jev-gate.py <reviewer-security|reviewer-ui> $F/jobs/$ID
     ```
     Output `add` means the gate's 0.7 cutoff was met: delete that skip file and add the reviewer back to `spawn` (security; or both ui and ux). Output `skip`, anything else, an error or a timeout leaves the skips. Jev never removes a reviewer, and is never consulted in the fast lane or for carried-forward reviewers.
   - **Shared dev server (once per round, after the skips and the Jev gate above).** Start it only when all of these hold: at least one of `ui` / `ux` is in step 2's `spawn` after the Jev gate; at least one file in `git -C "$WT" diff --name-only "$BASE"...HEAD` matches `UI globs`; and `project.md`'s `Dev command:` is present and not `none`. When any of these fails, start nothing, write no `dev-url.txt` and pass no `DEV_URL`. Otherwise:
     - Pick a free port that is never 3001 (e.g. `python3 -c 'import socket; s=socket.socket(); s.bind(("",0)); print(s.getsockname()[1])'`, picked again if it prints 3001). Start the server exactly once this round, in the background, from `$WT`: `(cd "$WT" && exec env PORT=<port> nohup <Dev command> >> "$F/jobs/$ID/round-$N/dev.log" 2>&1 < /dev/null) & echo $!`, and record that PID and the port. The subshell `exec`s the server, so `$!` is the server's own PID, not a wrapper's.
     - **Probe**, polling every 2 s. It counts as reachable only when both succeed within 60 seconds of the start: (a) `curl -s -o /dev/null -w '%{http_code}' http://localhost:<port>/` returns `200`; (b) one GET to a data API path returns a 2xx status. The API path is the first `/api/...` path the diff references (`git -C "$WT" diff "$BASE"...HEAD | grep -oE '/api/[A-Za-z0-9_./-]*' | head -1`), otherwise the first `/api/...` path the served root page references (the same `grep` over `curl -s http://localhost:<port>/`). When neither has an `/api/` path, skip (b) and record `no API path to probe` in `round-$N/dev.log`.
     - On success write `round-$N/dev-url.txt` containing exactly `http://localhost:<port>`. On failure write `round-$N/dev-url.txt` as `unreachable: <why>` (for example `unreachable: / returned 500`, `unreachable: /api/orders returned 404` or `unreachable: no response within 60s`), stop the server as in step 4's last bullet, and pass no `DEV_URL`; the ui/ux reviewers then start their own servers.
3. Spawn **in ONE message**, in the background, exactly the reviewers in step 2's `spawn`, each as `scrum-review-<role>` (`scrum-review-security`, `scrum-review-ux`, `scrum-review-ui`, `scrum-review-code`). In the same message, also spawn `scrum-review-e2e` when `project.md` has an `E2E:` line that isn't `none` and any file in `git -C "$WT" diff --name-only "$BASE"...HEAD` matches `UI globs`; it writes `round-$N/review-e2e.md`, overwriting any file the **Check gate** E2E triage left. It is never carried forward and never skipped on an incremental round when those conditions hold. The orchestrator never spawns `scrum-review-e2e` when `project.md` has no `E2E:` line or the line is `none`. Each gets the 5 lines with `ROUND=$N` plus `Review this round. Write only your own review file.` When `since` is non-null, each `spawn` reviewer also gets `SINCE=<since>` and `Re-review: verify each blocking finding in JOB_DIR/round-<N-1>/review-<role>.md against git diff SINCE..HEAD.` When `round-$N/dev-url.txt` holds a URL (not `unreachable: ...`), the `scrum-review-ui` and `scrum-review-ux` spawns, and any step 4 re-spawn of them, also get the extra prompt line `DEV_URL=<url>`; no other reviewer gets it. No `model:` override is passed to any reviewer.
   - **Move-only refactor.** On a full-review round (never an incremental re-review), after step 2, run `B move-ratio $ID`. When it exits 0 and its `ratio` is `>= 0.9` (nearly every added line is one git marks as moved), add the line `MOVE_ONLY=yes` to the prompts of `scrum-review-code`, `scrum-review-ui` and `scrum-review-ux`, for whichever of them are spawned; never `scrum-review-security`. A non-zero exit or unparseable output means no MOVE_ONLY line. A reviewer missing from step 2's `spawn` stays skipped. Re-run it every full-review round.
4. **WAIT FOR ALL.** Do nothing else until every spawned reviewer has completed. Then run `B sync $ID`. If the board says `builder=local`, log `review-pass` or `review-changes` (see **Routing** step 5).
   - `complete` must be `true`. If it isn't, `missing` lists the absent files (e.g. `review-ui.md`): re-spawn only the reviewers named in `missing`, once. If a file is still missing after the re-spawn, write that file yourself as `VERDICT: CHANGES` plus `Reviewer produced no output.`, then run `B sync $ID` again.
   - `review-e2e.md` is optional to `B sync`, so it never appears in `missing`. When you spawned `scrum-review-e2e` this round and `round-$N/review-e2e.md` is absent, re-spawn it once; if it is still missing, write it yourself as `VERDICT: CHANGES` plus `Reviewer produced no output.` (the same rule as above), then run `B sync $ID` again. `invalid` may name `e2e`, handled like the others.
   - If `invalid` is non-empty, delete those files and re-spawn those reviewers, once. If they come back invalid again, treat them as CHANGES.
   - **Never resume the builder mid-round.**
   - **Stop the shared server.** Once this WAIT FOR ALL is finished, re-spawns included, and before step 5 routes, stop the server that step 2's **Shared dev server** bullet started: `kill <recorded PID>`, then `lsof -ti tcp:<port> -sTCP:LISTEN | xargs kill` for any child still listening on the port. Do this on every route out of step 4, including a stop or a needs-human, and skip it only when no server was started this round.
5. Route:
   - `verdict` is `PASS` on a **clean round**: go straight to **Merge**. Spawn no approver; there is no decision.md. Run `B route-check $ID`, adding `--clean-start` only when this session knows the round was not started by the Merge **Conflicts** step; it is a clean round only when its `clean_round` is `true` (it checks the lane, `N` = 1, `round-1/check.md` and all four reviews passing with skip files counted, no `round-1/review-*.md` line starting `Rendered: blocked`, so an environment-blocked render always goes to **Approve**, no schema guard, `.env` or sensitive-path file in the diff, and the spec's `Hard stops:` line being exactly `none`).

     The PR uses the no-Merge-summary fallback in Merge step 3 (job title, spec acceptance criteria as bullets), and the body line `Approved by the scrum approver. Spec, reviews and decision: scrum/jobs/$ID/` is replaced by `Clean round: check gate + reviews. Spec and reviews: scrum/jobs/$ID/`. The schema guard still runs unchanged. With no decision.md, the `Restart:` line counts as `none`.
   - `verdict` is `PASS` otherwise (`clean_round` is `false`, or `route-check` exits non-zero): go to **Approve**.
   - `verdict` is `CHANGES` and `round < limit`: resume the builder (see **Sonnet promotion**) with `Review round N has CHANGES: read every review-*.md in JOB_DIR/round-N/, fix blocking findings, commit, update build.md.` (`review-*.md` includes `review-e2e.md` when it exists; its `VERDICT: CHANGES` alone makes the verdict `CHANGES`.) Run `B set $ID stage=build`, then go to **Check gate**.
   - `verdict` is `CHANGES` and `round >= limit`: go to **Approve**.

## Approve

1. Run `B set $ID stage=approve`. Spawn `scrum-approver` and wait for it. Prompt: the 5 lines plus `Decide this job. Write decision.md.`
   - **Model:** run `B route-check $ID`, adding `--clean-start` only when this session knows the round was not started by the Merge **Conflicts** step. Pass Agent override `model: "sonnet"` to `scrum-approver` when its `approver_sonnet` is `true`. Otherwise, when the Merge schema guard regex `(^|/)prisma/(schema\.prisma|migrations/)|\.sql$` matches no file in `git -C "$WT" diff --name-only "$BASE"...HEAD`, pipe **Review** step 2's Jev gate diff line plus `grep -m1 '^# ' "$F/jobs/$ID/spec.md"` to `python3 ~/.claude/skills/trevskills-scrum/jev-gate.py approver $F/jobs/$ID` (Bash timeout 90000). Output `sonnet` passes `model: "sonnet"`. When the schema guard matches, make no Jev call. In every other case (including when you can't tell, e.g. after a session restart, so no `--clean-start`) omit the override so the agent's default, Opus, runs.
2. Copy `decision.md` into `round-$N/decision.md`; that's how the approver later sees whether REWORK has already been used. Run `B sync $ID` and read `decision`.
3. **Manual checks and follow-ups.** First, when `decision.md` has a non-empty `## Manual checks` section that is not just `- none`, run `B manual-add "<item> (from $ID)" ...`, one argument per bullet. It appends them to `$F/manual-checks.md`, the checklist Trevor ticks off in the dashboard's Backlog dialog, never to the backlog. Do this whether or not `## Follow-ups` is empty; if `manual-add` exits non-zero, name it in the final report only.
   Then, when `decision.md` has no `## Follow-ups` section, or it is empty, or its only bullet is `- none`, spawn nothing, run neither `backlog-spec` nor `backlog-add`, and go to step 4. Otherwise pre-write a spec per follow-up:
   - If the board's `specwriter` is a recorded agent id, use SendMessage to it, the same way **Resuming the builder** does. Spawn a fresh `scrum-spec-writer` (see **Routing**) instead when `specwriter` is `local`, missing or empty, or when SendMessage fails because the agent no longer exists. The message or prompt is:
     ```
     JOB_DIR=$F/jobs/$ID
     BACKLOG=$F/backlog.md
     PROJECT=$F/project.md
     Run follow-up mode: pre-write a spec for each Follow-ups bullet in decision.md.
     ```
   - Wait for it, then run `B backlog-spec $ID`. If it reports `skipped` files, name them in the final report only.
   - **Fallback:** if the spec writer fails, leaves no `$F/jobs/$ID/followups/*.md`, or `B backlog-spec $ID` exits non-zero, run the **Dupe check** (3c, `jev-gate.py dupe`) on each, then append the bullets with `B backlog-add "<item> (from $ID)" ...`, one argument per bullet. The lock keeps parallel sessions from clobbering each other.

   Approve never blocks or sets needs-human because of this step; go on to step 4.
4. Route:
   - `APPROVE`: go to **Merge**.
   - `REWORK` and sync's `"reworks"` is greater than 1: the approver broke the once-only rule. Run `B set $ID stage=needs-human reason="approver requested second rework. Fix: read decision.md, then click Approve & merge or Send back to builder."` and stop.
   - `REWORK` (first time): run `B set $ID limit=$((N+1)) stage=build`. Resume the builder with `The approver requested rework: read JOB_DIR/decision.md (Rulings marked fix-now), fix, commit, update build.md.` Then go to **Check gate**.
   - `ESCALATE` or `INVALID`: the reason is the second line of `decision.md` plus the fix for its hard-stop kind. If it starts `Hard stop: blocked`, run `B set $ID stage=needs-human reason='<second line of decision.md>. Fix: type what the builder needs and click Send back to builder.'`. For any other second line, run `B set $ID stage=needs-human reason='<second line of decision.md>. Fix: click Discuss first.'`. For INVALID, run `B set $ID stage=needs-human reason="approver output unreadable. Fix: click Discuss first."`. Report and stop.

## Migrate (Merge's schema guard; Lilguy lane step 4)

Trevor chose to let schema changes migrate and merge with nobody watching. This stops only when `/trevskills-migrate` itself stops.

1. `cd "$WT"` and invoke `/trevskills-migrate` (Skill tool) there with args `base=$BASE`, following it exactly. Every question it would put to Trevor (a duplicate column, a good-practices fix, drift) is a stop: never answer one yourself.
2. If it stops or any check fails, `cd "$REPO"` and run `B set $ID stage=needs-human reason='migrate stopped: we should <what to change> because <one line why>. Fix: fix that cause, then click Approve & merge to run it again.'` and stop; never work around it.
3. On success, commit what it generated (`git -C "$WT" add prisma && git -C "$WT" commit -m "Add migration"`, skipped when nothing changed), write `git -C "$WT" rev-parse HEAD:prisma` to `$F/jobs/$ID/migrated.md`, and `cd "$REPO"`. In the Lilguy lane skip both: commitpush lands the migration with the change.

## Merge (APPROVE, or /trevskills-scrum approve)

The steps below reuse the lessons from `/trevskills-commitpush`.

1. **Preconditions:**
   - `command -v gh && gh auth status` must succeed. If not, run `stage=needs-human reason="GitHub CLI is not installed or not signed in; branch scrum/$ID is local only. Fix: run brew install gh, then gh auth login in Terminal, then click Approve & merge."` and stop.
   - `git -C "$WT" status --porcelain` must be empty. If it isn't, resume the builder once with `Commit or remove uncommitted changes.` If it is still dirty, run `B set $ID stage=needs-human reason='Uncommitted files in the job worktree: <first files>. Fix: click Send back to builder and ask it to commit or remove them.'` and stop.
   - **Schema guard (deterministic; doesn't rely on any model):** if `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)prisma/(schema\.prisma|migrations/)|\.sql$'` prints anything and `$F/jobs/$ID/migrated.md` doesn't hold `git -C "$WT" rev-parse HEAD:prisma`, run **Migrate**. In the **Cloud lane**, which never migrates, run `B set $ID stage=needs-human reason='Hard stop: schema — <first matching file>. Fix: click Approve & merge; it runs /trevskills-migrate first.'` and stop instead. Run this guard again right before step 6, because CI-fix commits skip the approver.
   - **Agent rules guard (deterministic; doesn't rely on any model):** if `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)agents/scrum-[^/]*\.md$|(^|/)SKILL\.md$|(^|/)trevskills-scrum/lanes/[^/]*\.md$'` prints anything, `$F/jobs/$ID/human-approval.md` doesn't exist, and `B digest-verify $ID --worktree "$WT" --base "$BASE"` exits non-zero, run `B set $ID stage=needs-human reason='Hard stop: agent rules — <first matching file>. Fix: review the diff, then click Approve & merge.'` and stop. A job that edits the pipeline's own rules never merges without a human, whichever way it reached Merge (fast lane PASS, clean round, approver APPROVE, or a cloud job), unless `B digest-verify $ID` proves its rules-file diff is exactly the digest proposals Trevor already approved (status `queued`) that its `feature.md` cites, and nothing else. Run this guard again right before step 6, next to the schema guard.
   - **Main checkout guard (before any push or merge):** the main checkout must be able to fast-forward after the merge, or the change never goes live. It passes only if `git -C "$REPO" symbolic-ref --short HEAD` equals `$DEFAULT` and `git -C "$REPO" status --porcelain --untracked-files=no` is empty (untracked files don't count). If it has uncommitted changes, run `B set $ID stage=needs-human reason='Uncommitted change in <repo name>: <first files>. Fix: commit + push it (or undo it), then click Approve & merge.'` and stop. If it is on the wrong branch, run `B set $ID stage=needs-human reason='<repo name> main checkout is on <branch>, not <default>. Fix: switch it back to <default>, then click Approve & merge.'` and stop. `<repo name>` is `basename "$REPO"`. Never stash, clean or switch branches in the main checkout to make it pass; Trevor fixes it by hand, then runs `/trevskills-scrum approve <id>`.
2. Run `B set $ID stage=merging`. Then `git -C "$WT" push -u origin "scrum/$ID"`. That pushes the scrum branch only.
3. **PR.** Run `gh pr view "scrum/$ID" --json number,url,state`:
   - `OPEN`: reuse it.
   - `MERGED`: skip steps 4–6 and go to step 7 (Clean up), so the fast-forward and the live check still run.
   - `CLOSED`: run `stage=needs-human reason="The pull request was closed on GitHub. Fix: reopen it on GitHub, then click Approve & merge."` and stop.
   - No PR, or reusing one: the title is the decision.md `Merge summary` title. If there is no Merge summary (a human-approved ESCALATE), use the job title and the spec's acceptance criteria as bullets. Either way write the body to `BODY=$F/jobs/$ID/pr-body.txt`, which is also used in step 6. Write the body to that file and pass it with `--body-file`. The body is the Merge summary bullets, then `Approved by the scrum approver. Spec, reviews and decision: scrum/jobs/$ID/` (for a fast-lane job, the line in **Fast lane** step 3 instead; for a Clean round, the `Clean round:` line in **Review** step 5 instead), then a line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Create it with `gh pr create --base "$DEFAULT" --head "scrum/$ID" --title "<Merge summary title>" --body-file "$BODY"`.

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
6. **Merge:** re-run the schema guard and the agent rules guard from step 1. If the job's `lane` is `debug` and step 4 made any CI fix commit, next to it re-run the three **Check gate** debug checks (Repro, Allowed files, Repro test untouched) in `$WT` on HEAD; if any fails, run `B set $ID stage=needs-human reason='debug: checks fail after CI fix — <first failing check>. Fix: click Send back to builder with what to change.'` and stop without merging. Then run `B sync $ID` right before merging; if it says the job was aborted, stop. Then `gh pr merge "scrum/$ID" --squash --subject "<title> (#<number>)" --body-file "$BODY"`. Never use `--auto`, `--admin` or `--delete-branch`. If the merge fails (branch protection, a required review, anything else), run `B set $ID stage=needs-human reason='merge refused: <first line of stderr>. Fix: clear that on GitHub, then click Approve & merge.'` and stop.
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
     3. **Verify:** run only `curl -sfL localhost:<port>/<path>`, alone or piped to `grep -F -- <string>`. If the `Restart:` line's `verify:` has any other shape, do not run it (an older `curl -sf` line without `-L` counts as another shape); build this form from the port and the changed path (`/` when none is more specific). Retry in the background for a few seconds while it starts.
        - With a verify string: a 200 is not enough; the served content must contain this job's change. A string from the safe set may go in single quotes (`grep -F -- '<verify string>'`). Otherwise load it through a quoted heredoc and match the variable:
          ```bash
          VERIFY=$(cat <<'EOF'
          <verify string>
          EOF
          )
          curl -sfL localhost:<port>/<path> | grep -F -- "$VERIFY"
          ```
          No match is `verify failed`.
        - With no verify string (behavioural): it passes only when the PID from `lsof -ti tcp:<port> -sTCP:LISTEN` after the start differs from the one recorded before the kill, and `curl -sfL localhost:<port>/<path>` exits 0. Either failing is `verify failed`; passing is reported as `restarted + verified (behavioural)`.
   - **Mark done, only now.** If the guard, the fast-forward, the restart or the verify failed, run `B set $ID stage=done reason='merged, not live: <why>'`, where `<why>` is `not on <default>`, `uncommitted changes`, `fast-forward failed`, `restart failed`, `restart command not allowed` or `verify failed`. Otherwise (including `Restart: none` after a successful fast-forward) run `B set $ID stage=done reason=`. The dashboard card shows the `merged, not live` reason as a warning; Trevor clears it with `B set <id> reason=` once he has made the change live.
   - If `B set ... stage=done` refuses, run `B set $ID stage=needs-human reason='<its error, quotes stripped>. Fix: merge the PR on GitHub, then click Approve & merge.'` and stop.
   - **Roadmap chaining.** If the job has no `parent`, after `stage=done` run `B roadmap-next $ID`. When it prints a step, do **Roadmap lane** **Starting a step** with it after the Digest check. When it prints `null`, do **Roadmap lane** step 6 (**Roadmap done**) after the Digest check.
   - **BigBoy chaining.** If the job has a `parent`, after `stage=done` run **BigBoy lane** step 5 (tracker, `B ready`, start the next children or the final review).
   - **Digest check.** After `stage=done`, run `B digest-due`. If it prints `"due": true`, run **Digest** in this same session before the final report.

## Routing

Only `scrum-spec-writer`, `scrum-builder` and `scrum-digest-reader` are routed, and only in the steps that point here. Every other spawn uses the Agent tool as written.

1. **Ask.** Take `START=$(date +%s)` just before the step. Run `python3 "$HOME/.claude/skills/trevskills-scrum/../../local/route.py" <role> --job $F/jobs/$ID` (for a BigBoy child, `$ID` is that child's id), or `python3 "$HOME/.claude/skills/trevskills-scrum/../../local/route.py" scrum-digest-reader --scrum $F` for the digest reader. The step runs `local` only when that exits 0 and prints a JSON object whose `runner` is `local`; `<model>` is its `model`. Every other result means `cloud`: `cloud`, `skip`, a non-zero exit, unparseable output, or route.py missing. `cloud` means: spawn with the Agent tool exactly as the step says.
2. **Local runner.** One subprocess that does the agent's work and writes the same artifact. Run it from `$REPO` (the main checkout) with the Bash tool's `run_in_background` and Bash timeout 3600000, and wait for it to finish as you would for a spawned agent. `<role>` is the agent name. The prompt is the agent definition body (everything after the second `---` line of its file), a blank line, then the same prompt lines the Agent tool would have received, extra lines included (e.g. the spec refresh line); write those lines with their values filled in:
   ```bash
   AGENT="$HOME/.claude/agents/<role>.md"; TOOLS=$(sed -n 's/^tools: //p' "$AGENT" | head -1)
   PROMPT="$(awk 'n>=2; /^---$/{n++}' "$AGENT")

   $(cat <<'EOF'
   <the prompt lines>
   EOF
   )"
   SCRUM_LOCAL_MODEL=<model> SCRUM_LOCAL_CONTEXT=32768 python3 "$HOME/.claude/skills/trevskills-scrum/../../local/run.py" claude -p "$PROMPT" --allowedTools "$TOOLS"
   ```
   **The builder is the exception:** its local runner is one Ollama call with no agent loop (a small model in Claude Code fills 32K with tool output and never finishes). Run, from `$REPO`, `python3 "$HOME/.claude/skills/trevskills-scrum/../../local/build.py" "$F/jobs/$ID" "$WT" <model>` for the first build, adding the resume text as one more quoted argument on every resume (**Routing** step 4). It edits only the spec's `## Likely files`, commits on the branch and writes `build.md`; a non-zero exit is an invalid run.
   A local build runs `B set $ID builder=local` instead of recording an agent id. A local follow-up-mode spec writer records no `specwriter`.
3. **One cloud retry, never loop.** A local run is invalid when: **spec writer**, `spec.md` is missing; **follow-up-mode spec writer** (**Approve** step 3), `$F/jobs/$ID/followups/` has no `*.md`; **digest reader**, `notes.md` is missing or its first line is not `DIGEST NOTES`; **builder**, `build.md` is missing. A subprocess that exits non-zero is invalid too, even when an older artifact from an earlier attempt is still there (a refused run.py preflight is one such case); its last stderr line is the reason. Retry an invalid run once on cloud with the Agent tool and the same prompt plus one extra line `Local run failed: <reason>.` That retry replaces the step's own "spawn it once more", so the step still makes at most 2 attempts before its existing needs-human or `error.md` stop. A step gets one cloud retry at most and never goes back to local.
4. **Builder while the board says `builder=local`.** Every fix attempt and every review, approver, rework, CI or merge resume re-runs `local/build.py` with the resume text as its last argument (it reads the check, review or decision files that text names). A local build has no Agent id, so there is no SendMessage.
   - **Check gate:** fix attempts 1 and 2 run local. If the check still fails after them, fix attempt 3 is the cloud retry: a fresh `scrum-builder` with the 5 lines, the resume text and `Local run failed: check still failing after 2 local fix attempts.` The 3-attempt cap is unchanged.
   - **Fast lane:** promotion on the 2nd check failure moves the next fix attempt to cloud (`Local run failed: check failed twice.`), and that move is the step's one cloud retry.
   - Whenever a build moves to cloud, run `B set $ID builder=<cloud agent id>` and stop routing the builder for this job. From then on, resumes use SendMessage as in **Resuming the builder**.
5. **Log every routed attempt.** Run `python3 "$HOME/.claude/skills/trevskills-scrum/../../local/route.py" record <dir> <role> <runner> <model> $(( $(date +%s) - START )) <outcome>`, taking a fresh `START` before each attempt. `<dir>` is `$F/jobs/$ID`, or `$F` for the digest reader. `<runner>` is `local` or `cloud`. `<model>` is the router's `model`, or `-` for cloud. `<outcome>`:
   - a local spec writer or digest reader: `ok` or `invalid-artifact`;
   - a local build: `ok` or `invalid-artifact`, plus one more line, `check-pass` or `check-fail`, when that build reaches the Check gate, and one more, `review-pass` or `review-changes`, after **Review** step 4 or **Fast lane** step 2 syncs a round the board still records as `builder=local` (`review-pass` when the synced `verdict` is `PASS`). That last line is the paid reviewers' judgement of the local build, the evidence the digest uses for the builder's trust;
   - a first-try cloud run: `ok`;
   - the cloud retry: its own line, runner `cloud`, outcome `fallback`.

   Ignore a failed `record` call. Logging never blocks the pipeline.

## Resuming the builder

If the board's `builder` is `local`, re-run the local builder subprocess instead of SendMessage (see **Routing** step 4). Otherwise use SendMessage to the recorded `builder` (the name `builder-$ID`, or the stored agent id) with a message naming the exact file(s) to read. If SendMessage fails because the agent no longer exists (for example after a session restart):
1. Spawn a fresh `scrum-builder` with the 5 lines plus `You are resuming this job. Read spec.md, build.md, and <the file(s) above>, then continue.`
2. Run `B set $ID builder=<new id>`.

In a headless (`claude -p`) session, skip SendMessage: its reply would arrive after the turn ends, and the process exits with it (see **Headless sessions block.**). Resume through step 1 instead (spawn a fresh `scrum-builder` in the foreground and wait for it to return), then step 2.

**Sonnet promotion.** A cloud builder runs as Sonnet while `$F/jobs/$ID/jev.log`'s `model` line decided `sonnet` and it has no `promote` line. On its first `CHECK: FAIL` (**Check gate** step 4) or `VERDICT: CHANGES` round (**Review** step 5), instead of SendMessage:
1. Run `printf '%s\n' '<check-fail round N|changes round N>' | python3 ~/.claude/skills/trevskills-scrum/jev-gate.py promote $F/jobs/$ID` with Bash timeout 90000.
2. Spawn a fresh `scrum-builder` with Agent override `model: "opus"`: step 1's prompt above plus the resume text.
3. Run `B set $ID builder=<new id>`.

A builder already promoted, or with `builder=local`, is never promoted again.

Outside the **Lilguy lane**, the orchestrator never edits code or review files itself, except for these sanctioned review files: the UI/UX skip, security skip and `Carried forward from round` files that `B review-plan` writes in **Review** step 2, the `Reviewer produced no output.` fallback, and the fast lane skip files in **Fast lane** step 2.

## Digest

Learns from finished jobs. It runs from the main checkout (Setup applies, but not the Prerequisites: it needs no remote and no `gh`), and it never pushes, merges or opens a PR. It never edits an agent, skill, rule or memory file itself. Step 4 handles the edit proposals the digester marked obvious: serve.py applies each one whose old text occurs exactly once and whose repo's contract tests still pass, and commits them locally under one `lilguy` board job; any it can't apply becomes a repo backlog item. Trevor approves or rejects every other proposal from its needs-human card on the board or in the dashboard's **Digest** dialog. The last decision trims the digested job folders.

1. Run `B digest-start`. Under the board lock it claims every `done` job that's in no earlier digest and prints `{"id", "jobs"}`. If `id` is null, say there is nothing to digest and stop. Otherwise `D=$F/digests/<id>`.
2. Spawn `scrum-digest-reader` (see **Routing**) and wait for it. Prompt:
   ```
   DIGEST_DIR=$D
   JOBS_DIR=$F/jobs
   Write notes.md for this digest.
   ```
   If `$D/notes.md` is missing or its first line isn't exactly `DIGEST NOTES` (`head -1 "$D/notes.md"`), spawn it once more. If it still fails, write `$D/error.md` containing the one line `digest reader produced no notes` and stop.
3. Set `R=$(cd "$(realpath ~/.claude/skills/trevskills-scrum)/../.." && pwd)`, then spawn `scrum-digester` and wait for it. Prompt:
   ```
   DIGEST_DIR=$D
   PROJECT=$F/project.md
   ROUTING=$R/local/routing.json
   Write proposals.json for this digest.
   ```
   If `python3 -m json.tool "$D/proposals.json"` fails, or the file has no `proposals` list (`python3 -c 'import json,sys; sys.exit(not isinstance(json.load(open(sys.argv[1])).get("proposals"), list))' "$D/proposals.json"` exits non-zero), spawn it once more. If it still fails, write `$D/error.md` containing the one line `digester produced no valid proposals` and stop.
4. If the `proposals` list is empty, run `B digest-trim <id>`. Otherwise run `python3 ~/.claude/skills/trevskills-scrum/serve.py --digest-auto <id> --dir $F`. It prints `{"applied": [{"id", "target", "obvious_reason"}], "queued": [{"id", "target", "obvious_reason", "reason"}], "human": [{"id", "reason"}], "job"}`. `applied` proposals are already edited and committed (not pushed) under board job `job`; `queued` ones became backlog items. Report each applied proposal as `<pid> → <target>: <obvious_reason>` and the commit's job id, then each queued proposal as `<pid> → <target> queued: <reason>`, then the number of `human` proposals left for Trevor on the board.

## Final report

End with the job id, the final stage, for a BigBoy parent or child the children this run started (or `none`) and the parent's stage, the PR URL, rounds used, any follow-ups added to the backlog, for merged jobs whether main was fast-forwarded (`main updated`, or `main not updated: <reason>`) the restart outcome (`restarted + verified`, `restarted + verified (behavioural)`, `restart failed`, `restart command not allowed`, `verify failed`, `Restart pending: <process> — <reason>`, or `none`), and whether the change is live (`live`, or `merged, not live: <why>` as written to the board), and, for needs-human, the exact reason and the next command (`/trevskills-scrum approve <id>`, `/trevskills-scrum rework <id> "<feedback>"`, or `/trevskills-scrum discuss <id>` when it's unclear which).
