---
name: trevskills-scrum
description: Run the scrum team. "/trevskills-scrum <feature>" builds a feature end to end (spec → build → check → up to 4 parallel reviews → approver → squash-merged PR). Also "/trevskills-scrum next", "/trevskills-scrum approve <id>", "/trevskills-scrum rework <id> <feedback>", "/trevskills-scrum discuss <id> [note]", "/trevskills-scrum resume <id>" (restart a job the watchdog flagged as stalled, or one Trevor paused; the dashboard's Play), "/trevskills-scrum askme [1-3] <feature>" (answer questions first, then build), "/trevskills-scrum bigboy <feature>" (plan a big request into 2-5 chained child jobs), "/trevskills-scrum digest" (learn from done jobs; also runs itself after every 10), "/trevskills-scrum run-all" (triage the backlog, then schedule every open item in parallel where files don't overlap), "/trevskills-scrum lilguy <feature>" (cheap mode: no subagents; this session makes the change in the main checkout, runs the checks, then lands it with commitpush), "/trevskills-scrum cloud [N]" (run up to N backlog items in claude.ai/code cloud sessions), "/trevskills-scrum cloud-sync" (pull their results onto the board), and bare "/trevskills-scrum" for status.
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

This skill is a sanctioned exception to the global git rules: it may push its own `scrum/*` branch, `gh pr create`, and `gh pr merge --squash` that PR once checks pass. Nothing else:
- never `git reset`, `git rebase`, or `--force`, and never `git merge` except the conflict step in **Merge**
- never `git pull` except the one guarded fast-forward (`--ff-only`) of the main checkout in **Merge** step 7 (Clean up), which runs after every merge; never stash, merge, reset or switch branches in the main checkout
- never push `main`/`master`, except through commitpush invoked with the Skill tool in the **Lilguy lane**
- never `--auto` or `--admin`
- when `scrum/project.md` sets `Base branch:`, never open a PR into, merge into, or push the remote default branch; every job targets that base branch instead. Promoting it to `main` is Trevor's own merge commit, never squash, and no scrum command does it
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

**Pause:** Trevor can pause a job in progress from the dashboard. Its session is killed at once and the job becomes `needs-human` with reason `stalled in <stage>: paused by Trevor`. If a session survives, every `B set` or `sync` for it fails with `was paused by Trevor`. When you see that, stop quietly as for abort: spawn nothing more, push nothing, merge nothing. Play restarts it with `/trevskills-scrum resume <id>`.

**Untrusted reason text:** a reason that copies text from an agent-written file (assessment.md, decision.md, a track or review file) or from command output (stderr, file names, branch names) can contain `$(...)` or a backtick. Remove every `'` from that text, then pass the reason in single quotes, `reason='...'`, never in double quotes, so the shell expands nothing in it. Every reason template below with a `<placeholder>` is written this way; reasons whose only variables are `$ID` or `$DEFAULT` keep double quotes so those expand.

If this isn't the main checkout, stop and say so. Run `B register "$REPO"` every time (it's idempotent): that's what puts this repo on the one all-projects dashboard.

**Prerequisites (every command that runs a job: new job, `next`, `start`, `run-all`, `approve`, `rework`, `resume`, `lilguy`, `cloud`, `cloud-job`; not bare `/trevskills-scrum`).** Before spawning any agent, check:
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

   `- E2E: <command>` is another optional line Trevor adds by hand: an end-to-end test command the **Check gate** runs when the diff touches `UI globs`, and the BigBoy reviewer runs on main. First-run setup never writes it either.

   `- Cloud environment: <id>` is a third optional, hand-added line: the claude.ai/code environment the **Cloud lane** starts sessions in.

5. Tell the user this repo is now on the dashboard: open the **Trevskills Scrum** app, or run `python3 ~/.claude/skills/trevskills-scrum/serve.py` from anywhere, then go to http://localhost:8765. One dashboard shows every project.

## Commands

For `approve` and `rework`, load the job from `$F/board.json`: `WT` is its `worktree`, `BASE` is its `base`, and `DEFAULT` is `BASE` with the `origin/` prefix removed. `N` is its `round`.

- **`/trevskills-scrum`** (no args): first run **Cloud lane** **Sync** when a job is in stage `cloud`. Then print each job's `id stage round reason pr` from `$F/board.json`, and the dashboard command.
- **`/trevskills-scrum next`**: first run `B watchdog`. It flags every job stuck 30+ minutes in `spec`, `build`, `check`, `review` or `approve` with no live session as `needs-human` (reason `stalled in <stage>: ...`) and prints `{"flagged"}`; for each flagged id that has a `parent`, run **BigBoy lane** step 6 with `ID=<that id>`. Then run `B next`. It claims the first `- [ ]` line in `$F/backlog.md` under the board lock, creates the job, and prints `{"id", "feature"}`; two sessions never get the same item. If `id` is null, say the backlog is empty and stop. Otherwise run **New job** from step 1b with `ID=<id>` and that feature text (step 2 records your terminal).
- Backlog lines look like `- [ ] [5] Text <!-- estimate reason -->`; the `[5]` is Fibonacci difficulty points. Only ever change `backlog.md` through `B` (`next`, `backlog-add`, `triage-apply`), never by hand-editing it.
- **`/trevskills-scrum <feature text>`**: run **New job**.
- **`/trevskills-scrum askme [1-3] <feature text>`**: run **New job** with the **Askme** step (1c) at that level. With no level, or a level that is not 1, 2 or 3, use level 2 and treat the whole rest as the feature text.
- **`/trevskills-scrum bigboy <feature text>`**: run **New job** steps 1-2, then `B set $ID lane=bigboy` and go straight to the **BigBoy lane**. No spec writer runs for the parent.
- **`/trevskills-scrum lilguy <feature text>`**: run the **Lilguy lane**. No agent is spawned.
- **`/trevskills-scrum roadmap <brief>`**: draft `$F/roadmap.md` from the brief and, on Trevor's yes, start P1 S1 (**Roadmap lane**).
- **`/trevskills-scrum roadmap`** (no brief): print the roadmap status block (**Roadmap lane**). It starts nothing.
- **`/trevskills-scrum start <id>`**: the dashboard's Run now button already claimed a backlog item as job `<id>` and wrote its `feature.md`. Load the job and run **New job** from step 2. For a BigBoy child (the job has a `parent`; started as `/trevskills-scrum start <child>` by **BigBoy lane** step 3 or by the dashboard's Setup done), run **BigBoy lane** step 4 (Spec refresh) after step 2: it skips step 3 when `spec.md` exists and no refresh is needed.
- **`/trevskills-scrum start <id> askme <1-3>`**: the same, but the dashboard's Run now had Askme set, so it opened this session in a new Terminal window. Load the job and run **New job** from step 1c (Askme) at that level; a missing or bad level means level 2.
- **`/trevskills-scrum approve <id>`**: the job must be `needs-human`. **refuse** (and suggest `/trevskills-scrum rework <id> "<feedback>"` instead) if the job has no `worktree`, has no commits beyond `BASE` (`git -C "$WT" log --oneline "$BASE"..HEAD` is empty), or its reason starts `blocked`, `spec writer`, `obsolete` or `stalled`; there is nothing approved to merge (for `stalled`, suggest `/trevskills-scrum resume <id>` instead). Also run Merge step 1's **main checkout guard**; while it fails, **refuse** with the same message it would write as the reason (`Uncommitted change in <repo name>: <first files>. Fix: commit + push it (or undo it), then click Approve & merge.` or `<repo name> main checkout is on <branch>, not <default>. Fix: switch it back to <default>, then click Approve & merge.`) and don't write `human-approval.md`. Once it passes, continue. If the reason contains `Hard stop: schema`, Trevor's approve is the go-ahead to migrate: `cd "$WT"` and invoke `/trevskills-migrate` there with args `base=$BASE`, following it exactly. If it stops or any check fails, run `B set <id> stage=needs-human reason='migrate stopped: <one line why>. Fix: fix that cause, then click Approve & merge to run it again.'` and stop; never work around it. On success, commit what it generated (`git -C "$WT" add prisma/migrations && git -C "$WT" commit -m "Add migration"`) and `cd "$REPO"`. Skip the migrate step when the prompt says `Trevor confirms /trevskills-migrate has already been run` (sent by the dashboard when he ticks that box). Then **record your terminal** with `ID=<id>`, write `$F/jobs/<id>/human-approval.md` containing `Approved by Trevor <ISO date>` and run **Merge**.
- **`/trevskills-scrum rework <id> <feedback>`**: append `## <ISO date>\n<feedback>` to `$F/jobs/<id>/rework.md`. Run `B set <id> stage=build reason= limit=<round+2>`, then **record your terminal** with `ID=<id>`. If the worktree is gone, recreate it from the branch with `git worktree add "$REPO/.claude/worktrees/scrum-<id>" scrum/<id>`. If the job's `lane` is `debug` and `$F/jobs/<id>/assessment.md` is missing or its first line is not `ASSESSMENT: READY`, no builder ever ran, so re-diagnose instead: move `assessment.md` (if present) to `assessment-prev.md`, run **Debug lane** from step 1 with the debugger prompt extended by `Read JOB_DIR/rework.md first.` and the re-spawn line, and continue as Debug lane does. Otherwise resume the builder (see **Resuming the builder**) pointing it at `rework.md`, then continue at **Check gate**.
- **`/trevskills-scrum discuss <id> [<note>]`**: an interactive talk-through before anything goes back to the builder. The dashboard's Discuss first button opens it in a new terminal, with whatever Trevor typed as the note. The job must be `needs-human`. **Record your terminal** with `ID=<id>`. Read only the board `reason`, the first lines and `## Rulings` of `decision.md`, `rework.md`, and `migrate-stop.md` if it exists. Then tell Trevor in plain words:
  1. What is stopping the job.
  2. Whether a rework can clear it. A `Hard stop:` never clears through rework: the builder can fix code, but the approver stops again on the same hard stop. Only `approve` clears it (for `Hard stop: schema`, approve runs `/trevskills-migrate`).
  3. What his note would actually do: change code (rework), give the go-ahead (approve), or neither.

  Discuss until you agree. Spawn nothing, edit nothing and run no command until Trevor picks one. Then carry it out in this session exactly as that command: `approve <id>`, or `rework <id> "<the agreed feedback, written so the builder can act on it>"`. If he picks neither, stop.
- **`/trevskills-scrum resume <id>`**: the dashboard's Resume button starts it headless for a job `B watchdog` flagged, and its Play button for a job Trevor paused. The job must be `needs-human` with a reason starting `stalled in <stage>`; otherwise **refuse** and stop. Load it like `approve` (`WT`, `BASE`, `DEFAULT`, `N`), run `B set <id> stage=<stage> reason=` (first: a paused job refuses every other write), **record your terminal** with `ID=<id>`, and re-enter the pipeline at that stage: `spec`: **New job** from step 3; `plan`: delete `$F/jobs/<id>/plan.md` if present and run **BigBoy lane** from step 1; `merging`: **Merge** from step 1; `build`: resume the builder (see **Resuming the builder**) with `Your session was interrupted: finish the work, commit, update build.md.`, then **Check gate**; `check`: **Check gate** from step 2 (step 1 already set the round); `review`: run `B sync <id>`, spawn (as **Review** step 3) only the reviewers named in its `missing` (the skip and carried-forward files of **Review** step 2 are written before any spawn, so `missing` never names them; a resumed session can't tell how the round started, so it writes no new carried-forward file and spawns them on the full diff), then continue at **Review** step 4 (a `lane=fast` job spawns only `scrum-review-code`, when `review-code.md` is missing, and continues as **Fast lane** step 2 does after its spawn); `approve`: **Approve** step 1. From there the job runs to the end as a `start` session would, including **BigBoy lane** chaining for a child.
- **`/trevskills-scrum digest`**: run **Digest**. The dashboard's Digest now button starts it headless.
- **`/trevskills-scrum cloud [N]`**, **`/trevskills-scrum cloud-sync`** and **`/trevskills-scrum cloud-job <id> <feature text>`**: run the **Cloud lane**.
- **`/trevskills-scrum run-all`**: run **Run all**: triage, then schedule every open item in parallel where files don't overlap. The dashboard's Run all button opens it in a new Terminal window.

## New job

Every needs-human reason is `<what is wrong>. Fix: <exact fix>`, with no double quotes or backticks. For a BigBoy child (the job has a `parent`), every time this run sets the child `stage=needs-human`, also run **BigBoy lane** step 6, so independent children still start. Every time this run sets a job `stage=needs-human`, also apply the **Roadmap lane** stop rule (`B roadmap-stop` only when that job, or its `parent`, is a roadmap step's `job`).

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
   - **`BB` set:** if it does not match `^[A-Za-z0-9._/-]+$`, run `B set $ID stage=needs-human reason="Base branch line in scrum/project.md is malformed. Fix: correct or remove it, then click Abort job with Put back in backlog ticked and run it again."` and stop before the spec writer. If `git rev-parse --verify -q "origin/$BB"` fails, run `B set $ID stage=needs-human reason='Base branch <BB> not found on origin. Fix: push <BB> to origin or remove the Base branch line from scrum/project.md, then click Abort job with Put back in backlog ticked and run it again.'` and stop before the spec writer. Otherwise `DEFAULT=$BB`.

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
   **Model:** pass the Agent tool override `model: "sonnet"` to every cloud `scrum-spec-writer` spawn of this step (first spawn, respawn, cloud retry and the `Refresh spec.md:` spawn) when `feature.md` already has either a `## Acceptance criteria` or `## Done when` heading followed, before the next `## ` heading, by at least one line starting `- `, or a `## Q&A` heading. Otherwise omit the override so the agent's default, Opus, runs.
   If `spec.md` is missing afterwards, spawn it once more. If it's still missing, set `stage=needs-human reason="spec writer produced nothing. Fix: click Abort job with Put back in backlog ticked, then run it again."` and stop. After each spawn, record it: `B set $ID specwriter=<id>` for a cloud spawn (the returned agent id), or `B set $ID specwriter=local` when **Routing** ran it locally. When the cloud retry replaces a local run, record the cloud agent's id instead.
   3b. **Obsolete:** if the first line of `spec.md` starts with `OBSOLETE:` (`head -1 "$F/jobs/$ID/spec.md" | grep -q '^OBSOLETE:'`), the request needs no change, so abort the job yourself. Strip any single quotes from the rest of that line, then run `B abort $ID --reason 'obsolete: <rest of that line>'` and stop: create no worktree and spawn no builder. The final report says the job was auto-aborted as obsolete and why.
   3c. **Lane:** read the `Lane:` line from `spec.md` and run `B set $ID lane=<fast|standard|debug|bigboy>`. Set `lane=debug` when it says exactly `Lane: debug`, whatever the `Hard stops:` and `UI surface:` lines say. Set `lane=bigboy` when it says exactly `Lane: bigboy`, whatever the other header lines say; the job then goes to the **BigBoy lane** and gets no worktree (skip steps 4-6). A BigBoy child (the job has a `parent`) never gets `bigboy`: for it, `Lane: bigboy` counts as `standard`. Set `fast` only when it says exactly `Lane: fast`, the `Hard stops:` line is `none`, and the `UI surface:` line is `no`. Set `standard` in every other case: the line is missing or malformed, or it says `fast` but `Hard stops:` is anything but `none` or `UI surface:` is `yes`.
4. **Worktree:**
   ```bash
   WT="$REPO/.claude/worktrees/scrum-$ID"
   git worktree add "$WT" -b "scrum/$ID" "$BASE"
   find "$REPO" -maxdepth 1 -name '.env*' | while read -r e; do ln -sfn "$e" "$WT/$(basename "$e")"; done
   ```
   Then `B set $ID worktree=$WT stage=build`.
5. **Build:** spawn `scrum-builder` (see **Routing**) and wait for it. Name it `builder-$ID` if the Agent tool accepts a name. Prompt: the 5 lines with `WORKTREE=$WT` and `ROUND=0`, plus `Implement spec.md. Write build.md.` Record the returned agent id/name with `B set $ID builder=<id>`. If `build.md` starts `STATUS: BLOCKED`, run `B set $ID stage=needs-human reason='blocked: <first reason line>. Fix: type what the builder needs and click Send back to builder.'` and stop. If the job's `lane` is `debug`, see **Debug lane** instead of this step.
6. Continue at **Check gate**.

## Run all

Cleans the backlog, then runs every open item as a child job of one Run-all parent, in parallel where files don't overlap, with nobody watching. Setup and Prerequisites apply. Trevor stops it by interrupting or closing its Terminal window.

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
4. Run `B watchdog`; for each flagged id that has a `parent`, run **BigBoy lane** step 6 with `ID=<that id>`. Then run `B runall-start`. Under the board lock it makes a `lane=runall` parent with every open backlog item as a `waiting` child and prints `{"id", "children"}`. If `id` is null, say the backlog is empty and stop. Otherwise `P` is that id.
5. Run **BigBoy lane** step 2 for P's children.
6. Run **BigBoy lane** step 3 for `P`, then give the final report. Never ask questions here; there is no Askme step.

The final report lists the Run-all parent id, the children it created, which children started in this session, then what the triage merged, retired and estimated (counts from `triage-apply`, or the failure line).

## Fast lane

Applies only while the job's `lane` on the board is `fast`. A job with no `lane`, or `lane=standard`, never reads this section. Same builder, same Check gate; then one diff-only code review and straight to Merge, with no approver.

1. **Promotion (deterministic).** Promoting means running `B set $ID lane=standard` and appending `Promoted to standard: <trigger>` to `$F/jobs/$ID/promoted.md`; the job then continues on the standard path from where it is. A standard job is never set back to fast.
   - **2nd check failure:** a fast job whose `check.md` says `CHECK: FAIL` for the 2nd time in a round is promoted (trigger `check failed twice`). The fix attempts in **Check gate** step 4 then carry on as standard.
   - **After `CHECK: PASS`, before Review**, promote if any of these hold (trigger names the first one hit). This runs again on every round, including after the Merge **Conflicts** step sends the job back to the Check gate:
     - `git -C "$WT" diff --numstat "$BASE"...HEAD` sums to more than 100 added+deleted lines, or any line shows `-` (a binary file);
     - more than 3 files changed (exactly 100 lines or exactly 3 files stays fast);
     - any changed file (`git -C "$WT" diff --name-only "$BASE"...HEAD`) matches the Merge schema guard regex `(^|/)prisma/(schema\.prisma|migrations/)|\.sql$` or `(^|/)\.env`;
     - any changed file matches `UI globs` from `project.md` (matching rules are in First-run setup);
     - any changed file matches the sensitive-path regex, case-insensitively: `grep -iE '(^|/)(middleware|proxy)\.[cm]?[jt]sx?$|auth|session|login|signin|signup|password|permission|payment|billing|checkout|stripe|webhook|secret|credential'` (trigger `sensitive path <first matching file>`).
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
2. **Validate `$F/jobs/$ID/assessment.md`.** It is invalid when it is missing, its first line is not one of `ASSESSMENT: READY`, `ASSESSMENT: NO_REPRO` or `ASSESSMENT: BLOCKED`, or a READY one lacks a `Repro:` line, a `Repro test:` line or at least one `- ` line under `## Allowed files`, or has a `## Compliance` line containing `conflict`. A READY one is also invalid unless its `Repro:` value (trimmed) starts with project.md's `Test:` command (trimmed), followed by a space or the end of the line; when `Test:` is `none`, the value must instead contain the `Repro test:` path. It is also invalid when the `Repro:` value contains any of `;` `&` `|` `` ` `` `$` `<` `>` or a newline. If invalid, delete it and re-spawn the debugger once, with the re-spawn line. If it is still missing or invalid, run `B set $ID stage=needs-human reason="debugger output unreadable. Fix: click Abort job with Put back in backlog ticked, then run it again."` and stop.
3. **No repro or blocked.** `<line 2>` is line 2 of assessment.md after removing every `` ` ``, `$`, `"` and `'` from it. For `ASSESSMENT: NO_REPRO`, run `B set $ID stage=needs-human reason='debug: no repro — <line 2>. Fix: click Abort job; if the bug is real, re-add it to the backlog with exact steps to reproduce it.'` and stop. For `ASSESSMENT: BLOCKED`, run `B set $ID stage=needs-human reason='debug: blocked — <line 2>. Fix: click Discuss first.'` and stop.
4. **Repro must fail.** Run the `Repro:` command in `$WT`. Write `$F/jobs/$ID/repro-before.md`: first line `REPRO: FAIL` (non-zero exit) or `REPRO: PASS` (exit 0), then `Commit: <git -C "$WT" rev-parse HEAD>`, the exit code, and the last 40 lines of output in a fenced block. If the exit code is 0, run `B set $ID stage=needs-human reason="debug: repro does not fail. Fix: click Abort job; the bug looks already fixed."` and stop.
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
   Then run `B plan-apply $ID`. Under the board lock it checks plan.md (first line `PLAN: READY`, 2-5 tickets, every `Depends on:` names a known ticket other than itself with no cycle, exactly one `Exposure: yes` ticket and it depends on every other), creates one `waiting` child job per ticket with its `feature.md`, sets the parent's `children`, moves the parent to `running`, and prints `{"children": [...]}`. A refused plan creates nothing. If it exits non-zero, delete `$F/jobs/$ID/plan.md`, spawn the planner once more, and run `B plan-apply $ID` again. If that fails too, take its error line, strip quotes (`'` and `"`) and backticks, run `B set $ID stage=needs-human reason='planner output unreadable: <error line>. Fix: click Abort job with Put back in backlog ticked, then run it again.'` and stop.
2. **Child specs, startable children only.** Spawn one `scrum-spec-writer` per child whose `depends_on` is empty, **in ONE message**, in the background, and wait for all of them (see **Routing**: each child is routed on its own, and local ones run as background subprocesses alongside the cloud ones). Each prompt is the New job step 3 prompt with `JOB_DIR=$F/jobs/<child>`. Every other child gets its spec in its own `start` session (step 4 runs New job step 3 when `spec.md` is missing); until then a child with no spec.md runs alone, which is the accepted cost. Then, for each child spawned for here:
   - **Obsolete:** if its `spec.md` starts with `OBSOLETE:`, run `B abort <child> --reason 'obsolete: <rest of that line, single quotes stripped>'`. Its dependents never become ready.
   - **Lane:** otherwise run New job step 3c with `ID=<child>` (`Lane: bigboy` counts as `standard`). A child without a `spec.md` is fine: its own `start` writes it.
3. **Start.** Run `B ready $ID` and **start** each id in `ready`. To start a child (here, in step 5 and in step 6), run detached from the main checkout, logging to `scrum/runs/`:
   ```bash
   mkdir -p "$F/runs"; LOG="$(date +%Y%m%d-%H%M%S)-start-<child>.log"
   (cd "$REPO" && CLAUDE_NOTIFIER_DISABLE=1 nohup claude -p "/trevskills-scrum start <child>" --permission-mode acceptEdits > "$F/runs/$LOG" 2>&1 < /dev/null &)
   B set <child> runlog=runs/$LOG
   ```
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
      - `TRACK: OFF TRACK`: run `B set $P stage=needs-human reason='bigboy off track: <line 2 of track-N.md>. Fix: read the latest track file, then click Abort job and re-add the request with your decision.'`, start no child, run `B chain-unlock $P $ID`, and stop.
      - `TRACK: ON TRACK`, or a missing or unreadable file: carry on.
   2. Run `B ready $P`. Under the lock it claims (moves to `spec`) every `waiting` child whose `depends_on` are all `done`, whose `setup` is not `pending`, and that can run beside the siblings in progress (a `parallel=no` child, or a `parallel=yes` child whose `spec.md` is missing or has no backtick-quoted path under `## Likely files`, runs alone: only when none is, and none starts beside it; any other child never beside one whose `## Likely files` overlap its own), up to an in-progress cap paced by `~/.claude/usage.json` (written by the `board.py statusline` status line: a Run-all parent's cap of 3 rises to 5 when well under pace and drops to 2 or 1 when over; a BigBoy parent is only ever throttled to 2 or 1; at least 1 child always starts, and running children are never touched), so a second call never returns it again. When nothing is ready or in progress and not every child is done, the parent stays `running` with reason `waiting on you in: <ids>` when only `needs-human` or setup-pending children block it (no sound; their actions are on the children); only when an aborted BigBoy child blocks does it set the parent `needs-human` with reason `bigboy blocked: <ids>`. A later claim, or a child in progress, sets it back to `running` with no reason; a legacy `bigboy blocked` / `run-all blocked` parent is re-evaluated the same way. It prints `{"ready", "merged", "total", "in_progress", "all_merged"}`. Then run `B chain-unlock $P $ID`.
   3. If `all_merged` is true, go to step 7; when P's `lane` is `runall`, run `B set $P stage=done reason=` instead. Otherwise **start** each id in `ready` (step 3; its own `start` runs the step 4 refresh).
6. **After a child stops.** When a child's run sets it `needs-human`, run `B chain-lock $P $ID` (same tries and stop as step 5), then `B ready $P`, then `B chain-unlock $P $ID`, and **start** each id in `ready`, so tickets that don't depend on it keep going. A failed child blocks only its dependents.
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
   - `BIGBOY: PASS`: run `B set $P stage=done reason=`. If plan.md has a `## Phase 2` section and `B roadmap-show` lists `$P` as a step's `job`, run `B roadmap-insert <that p> <that s> bigboy '<its line, every ' removed>'` instead of `backlog-add`; otherwise, with a `## Phase 2` section, run `B backlog-add "<its line> (Phase 2 of $P)"`. Either way, then run `B roadmap-next $P` and, when it prints a step, do **Roadmap lane** **Starting a step** with it.
   - `BIGBOY: GAPS` the first time: run `B plan-apply $P --fix`. It adds one child, ticket `FIX`, from the `## Fix ticket` text, with no dependencies, and moves the parent back to `running`. Run step 2 for it, then `B ready $P` and **start** it. When it merges, step 5 brings the parent back here and the reviewer runs once more.
   - `BIGBOY: GAPS` again, or `plan-apply --fix` exits non-zero (no `## Fix ticket`, or the FIX child already exists): run `B set $P stage=needs-human reason='bigboy review: gaps remain — <line 2 of bigboy-review.md>. Fix: read bigboy-review.md, add a backlog item for each gap, then click Abort job.'` and stop.

## Roadmap lane

A roadmap strings bigboy and standard jobs into ordered phases in `$F/roadmap.md`, and chains each step into the next with no prompt. `roadmap.md` is the single source of truth and the resume doc. Only ever change it through `B` (`roadmap-link`, `roadmap-next`, `roadmap-insert`, `roadmap-stop`), except when drafting it below. Each step stops only where its job or bigboy already stops.

1. **Draft** (`/trevskills-scrum roadmap <brief>`; Setup and Prerequisites apply). If `$F/roadmap.md` already exists, say so, change nothing and stop. Otherwise draft it from the brief in this exact format, which `board.py` parses:
   ```
   ROADMAP: <name>
   Goal: <one line>

   ## Constraints
   - <rule every step must keep>

   ## P1 <phase title>
   - [ ] S1 <bigboy|standard>: <request>
   - [ ] S2 <bigboy|standard>: <request>
   ## P2 <phase title>
   - [ ] S1 <bigboy|standard>: <request>

   ## Log
   ```
   Show the draft to Trevor once. On his yes, write it to `$F/roadmap.md`, run `B roadmap-show`, and do **Starting a step** with its `next` (P1 S1). On anything else, write nothing and stop.
2. **Status** (bare `/trevskills-scrum roadmap`). Run `B roadmap-show`. If it prints `null`, say there is no roadmap. Otherwise print:
   ```
   <name>
   P<p>/<phases> <phase title> · S<s>/<steps in that phase>
   next: S<n> <request>      (or: next: none)
   blocker: <job> <reason>   (or: blocker: none)
   ```
   `p` and `s` come from `current`. It starts nothing.
3. **Starting a step** `<P> <S> <kind> <request>`, run in this session. The feature text is the request, a blank line, then every `- ` line under `## Constraints` in `roadmap.md`, copied verbatim. A `bigboy` step runs exactly as `/trevskills-scrum bigboy <feature text>`; a `standard` step runs **New job** with that feature text. Right after `B new` gives `$ID`, run `B roadmap-link <P> <S> $ID`.
4. **Stop rule.** Whenever this session sets a job `stage=needs-human`, the step job is that job, or its `parent` for a BigBoy child. If `B roadmap-show` lists that id as a step's `job`, run `B roadmap-stop <that id> '<reason>'`, with the reason quoted under the **Untrusted reason text** rule. With no roadmap, or with the id in no step, skip the call: `board.py` exits non-zero for a job in no step.
5. **Resume.** Setup's **Roadmap resume** finishes a `running` step whose job is already `done` (`B roadmap-next`) and starts what it prints before the requested command.

## Lilguy lane

Applies only to `/trevskills-scrum lilguy <feature text>`, the cheap mode. This session makes the whole change itself in `$REPO` (the main checkout), on whatever branch is checked out, and spawns no agent: no spec writer, builder, reviewer or approver, no worktree, no `scrum/<id>` branch, no Digest check, no BigBoy chaining (a lilguy job never has a `parent`). Every needs-human reason here leaves the change uncommitted in the main checkout, so its Fix says to finish it by hand or discard it; Approve and rework do not apply.

1. **Refuse (before any `B new`).** After Setup and Prerequisites, give a plain message, create no job, and stop when:
   - `git -C "$REPO" status --porcelain -- . ':(exclude)scrum'` prints anything (tracked or untracked): `<repo name> has uncommitted changes: <first files>. Fix: commit or discard them, then run lilguy again.`
   - `git -C "$REPO" symbolic-ref -q --short HEAD` fails (detached HEAD): `<repo name> is on a detached HEAD. Fix: check out a branch, then run lilguy again.`
   - `$F/project.md` has a `Base branch:` line (read as in **New job** step 2) and `git -C "$REPO" symbolic-ref -q --short HEAD` is not that branch: `<repo name> is on <branch>, not <base branch>. Fix: switch to <base branch>, then run lilguy again.`

   While lilguy's change is uncommitted, pipeline jobs merging at the same time stop at the **Merge** main checkout guard until lilguy has committed.
2. **Job.** Run **New job** steps 1-1b, then `B set $ID lane=lilguy stage=build` and **record your terminal**. If any `B set` fails with `was aborted`, follow the Setup **Abort** rule: stop and leave the working tree untouched.
3. **Build.** Read `$F/project.md` and every convention file it lists, then make the change in `$REPO`.
4. **Check.** Run `B set $ID stage=check`. In `$REPO`, run the **Check gate** step 2 commands (each project.md Test / Typecheck / Lint / Build that isn't `none`). The changed files are `{ git -C "$REPO" diff --name-only HEAD; git -C "$REPO" ls-files --others --exclude-standard; }`; run the **Check gate** `.env` check (`(^|/)\.env`) over them, and the **Merge** schema guard regex over them. Write `$F/jobs/$ID/check.md` in the **Check gate** step 3 format (no `round-N/`; `round` and `limit` stay unset).
   - A schema match: run `B set $ID stage=needs-human reason='Hard stop: schema — <first matching file>. Fix: run /trevskills-migrate yourself in the main checkout, then /trevskills-commitpush, or discard the change.'` right away and stop, with no fix attempts. lilguy never runs /trevskills-migrate itself.
   - Any other failure: fix it yourself and re-run this step, up to **3** fix attempts. If it still fails, run `B set $ID stage=needs-human reason="lilguy: checks still fail after 3 fixes. Fix: read scrum/jobs/$ID/check.md, then fix and run /trevskills-commitpush in the main checkout, or discard the change."` and stop without landing.
5. **Land.** Run `B set $ID stage=merging`. `DEFAULT` is found with the same rule as **New job** step 2 (the `Base branch:` line, else `origin/HEAD`; without `B set base`). Invoke commitpush only through the Skill tool: `trevskills-commitpush-nextjs` when `python3 -c` finds `"next"` in `$REPO/package.json` under `dependencies` or `devDependencies` (a missing or unreadable package.json means not Next.js), `trevskills-commitpush` otherwise, and `trevskills-commitpush` too if the Skill tool says the nextjs one is not installed. It does the `git add -A`, commit and publish; this lane never runs those git or gh commands itself.
   - **Path A (on `$DEFAULT`):** done when `git -C "$REPO" status --porcelain -- . ':(exclude)scrum'` is empty and `git -C "$REPO" rev-list @{u}..HEAD` prints nothing (an error, e.g. no upstream, counts as unpushed).
   - **Path B (any other branch):** the same test, then `B set $ID pr=<url>` with the url from `gh pr view --json url`.
   - Both pass: `B set $ID stage=done reason=` (board.py plays the done sound). If commitpush stopped, the test fails, or Path B finds no PR, run `B set $ID stage=needs-human reason='lilguy: commitpush did not finish — <one line why>. Fix: finish /trevskills-commitpush by hand in the main checkout, or discard the change.'` and stop.
   - If `B set ... stage=done` refuses, run `B set $ID stage=needs-human reason='<its error, quotes stripped>. Fix: merge the PR on GitHub, then click Approve & merge.'` and stop.
6. End with the **Final report** (job id, stage, PR URL on Path B, and for needs-human the reason).

## Cloud lane

Runs backlog jobs in Claude Code cloud sessions (claude.ai/code), paid by Trevor's cloud-session credit instead of his weekly plan. The cloud environment's setup script is `cloud/setup.sh` from the scrum repo, so the session loads this same skill and agents. Only the differences are listed; every other step runs as written.

1. **Dispatch** (`/trevskills-scrum cloud [N]`, N defaults to 4; from the main checkout; Setup and Prerequisites apply). First run **Sync** (step 3). Then refuse with a plain message and start nothing when:
   - `$F/project.md` has a `Base branch:` line: `Cloud lane does not support Base branch yet. Fix: run these jobs locally.`
   - `git -C "$REPO" status --porcelain -- . ':(exclude)scrum'` prints anything, `git -C "$REPO" symbolic-ref -q --short HEAD` is not `$DEFAULT` (found as in **New job** step 2), or after `git fetch origin` `git -C "$REPO" rev-list "origin/$DEFAULT..HEAD"` prints anything: `<repo name> must be clean, on <default> and pushed. Fix: commit and push or discard, then run cloud again.`
   - **Credit check (before every batch).** The credit balance has no API. When the Claude in Chrome tools are available (`mcp__claude-in-chrome__*`; read the chrome-browser skill first), open https://claude.ai/settings/usage in a new tab and read `Cloud session credits ... $X of $250 left`. If X is under $25: `Cloud credit is $X, under $25. Fix: top up, then run cloud again.` If the tools are missing or X can't be read, ask Trevor once with AskUserQuestion whether at least $25 is left; anything but a yes refuses with `Cloud credit unreadable and unconfirmed.`

   Then up to N times: run `B next`; stop when `id` is null. Write the feature text to `$F/jobs/$ID/feature.md` (**New job** step 1b) and start the session (macOS `script` gives `claude --cloud` the TTY it needs; the feature text stays inside a variable so the shell expands nothing in it):
   ```bash
   CE=$(sed -n 's/^- Cloud environment: *//p' "$F/project.md" | head -1 | sed 's/[[:space:]]*$//'); E=()
   printf '%s' "$CE" | grep -qE '^[A-Za-z0-9_-]+$' && E=(--environment "$CE")
   FEAT=$(cat "$F/jobs/$ID/feature.md")
   OUT=$(script -q /dev/null claude --cloud "${E[@]}" "/trevskills-scrum cloud-job $ID $FEAT" < /dev/null 2>&1)
   URL=$(printf '%s' "$OUT" | grep -oE 'https://claude\.ai/code/session_[A-Za-z0-9_-]+' | head -1)
   ```
   With a `URL`, run `B set $ID stage=cloud cloud=$URL`. Without one, run `B set $ID stage=needs-human reason='claude --cloud did not start: <last line of OUT>. Fix: click Abort job with Put back in backlog ticked, then run cloud again.'`. Stage `cloud` is never flagged by `B watchdog`. The final report lists each id with its session URL.
2. **Cloud job** (`/trevskills-scrum cloud-job <id> <feature text>`, inside the cloud session). The job runs **New job** end to end (spec → build → Check gate → Review → Approve → Merge) with these deltas:
   - **Setup:** the cloned repo is the main checkout, and its `scrum/` is a throwaway board: first-run setup as usual, minus step 5. Prerequisites check `gh api user` instead of `gh auth status` (cloud `gh` is signed in through a proxy that `gh auth status` rejects). Skip Roadmap resume and **Record your terminal**: no dashboard, tty or terminal recording here.
   - **Job:** New job step 1 is `B new "<title>" --id <id>`, so the job keeps the id it was given; then step 1b, then step 2 on. A spec that says `Lane: bigboy` counts as `standard`, as for a BigBoy child.
   - **Routing** is always cloud: never call route.py; every routed step spawns with the Agent tool as written.
   - **GitHub:** cloud blocks GitHub GraphQL, so each `gh pr` call in **Merge** becomes its REST twin, with `R='repos/{owner}/{repo}'` (`gh` fills it in from origin). These are the same sanctioned PR create and squash-merge.
     - step 3 lookup: `gh api "$R/pulls?head={owner}:scrum/$ID&state=all" --jq '.[0] | {number, html_url, state, merged_at}'` (`merged_at` set is MERGED);
     - step 3 create: the title starts `[scrum <id>] ` (that is how **Sync** finds it): `gh api "$R/pulls" -f title="[scrum $ID] <title>" -f head="scrum/$ID" -f base="$DEFAULT" -F body=@"$BODY" --jq .html_url`;
     - step 4 checks, in the background: `SHA=$(git -C "$WT" rev-parse HEAD)`, then every 15 s `gh api "$R/commits/$SHA/check-runs" --jq '[.check_runs[] | .conclusion // "pending"] | unique | join(" ")'` until it has no `pending`; still empty after 90 s is "no CI ran"; anything but `success`, `skipped` and `neutral` is a failure, and `ci.md` gets each failing run's name, conclusion, `html_url` and `output.summary`;
     - step 5: `gh api "$R/pulls/<number>" --jq .mergeable`, where `null` is `UNKNOWN` and `false` is `CONFLICTING`; the **Conflicts** steps then run unchanged, which is also how parallel cloud jobs settle conflicts;
     - step 6: `gh api -X PUT "$R/pulls/<number>/merge" -f merge_method=squash -f commit_title="<title> (#<number>)" -F commit_message=@"$BODY"`.
   - **Merge** auto-merges under exactly the local rules: every hard stop (schema, money, auth, secrets, blocked) still stops. Skip step 1's main checkout guard. Step 7 is only `B set $ID stage=done reason=`: no worktree removal, fast-forward, restart, verify, chaining or Digest (local **Sync** fast-forwards Trevor's checkout).
   - **Never migrate in cloud:** never run `/trevskills-migrate`, `prisma migrate` or `prisma db push`; `approve` and its migrate step only ever run locally. A `Hard stop: schema` (from the approver or the Merge schema guard) is reported as **Needs-human** below, so its comment's first line starts `Hard stop: schema`, and **Sync** migrates it locally.
   - **Needs-human:** every time this job would set `stage=needs-human` (or abort itself as obsolete, with its `obsolete: ...` reason), it also reports to GitHub, then stops: push `scrum/$ID` (with no commits beyond `$BASE`, push `$(git commit-tree "$BASE^{tree}" -p "$BASE" -m "[scrum $ID] needs-human")` to `refs/heads/scrum/$ID` so a PR can exist), open the PR as above or keep the open one, add the label with `gh api "$R/issues/<number>/labels" -f "labels[]=scrum:needs-human"`, and post a comment whose first line is the reason and whose second line is `<!-- scrum needs-human -->`, with `gh api "$R/issues/<number>/comments" -F body=@<file holding it>`.
3. **Sync** (`/trevskills-scrum cloud-sync`; also the start of `cloud` and of bare `/trevskills-scrum`; skip it when `gh` is not signed in). For each job in stage `cloud`, find its PR: `gh pr list --state all --search "\"[scrum $ID]\" in:title" --json number,url,state,labels,title,baseRefName --jq "[.[] | select(.title | startswith(\"[scrum $ID]\"))][0]"`.
   - No PR: still running; leave it.
   - PR `MERGED`: `B set $ID stage=done pr=<url> reason=`.
   - PR `OPEN` with label `scrum:needs-human`: the reason is the first line of the newest comment holding `<!-- scrum needs-human -->` (`gh pr view <number> --json comments --jq '[.comments[].body | select(contains("<!-- scrum needs-human -->"))] | last | split("\n")[0]'`), quoted under the **Untrusted reason text** rule. Run `git fetch origin` and, as `rework` does, `git worktree add "$REPO/.claude/worktrees/scrum-$ID" "scrum/$ID"`, then `B set $ID stage=needs-human pr=<url> base=origin/<baseRefName> worktree=$REPO/.claude/worktrees/scrum-$ID reason='<reason>'` (leave out `worktree=` when the add failed), so `approve`, `rework` and `discuss` work as for a local job.
   - **Schema auto-migrate.** When that reason starts `Hard stop: schema` and the worktree add succeeded, do not leave it for Trevor: start a detached local approve, as **BigBoy lane** step 3 starts a child. Trevor chose this unattended path on purpose, so migrations run locally on a cheap model with nobody watching:
     ```bash
     mkdir -p "$F/runs"; LOG="$(date +%Y%m%d-%H%M%S)-approve-$ID.log"
     (cd "$REPO" && CLAUDE_NOTIFIER_DISABLE=1 nohup claude -p "/trevskills-scrum approve $ID" --model sonnet --permission-mode acceptEdits > "$F/runs/$LOG" 2>&1 < /dev/null &)
     B set $ID runlog=runs/$LOG
     ```
     `approve` then runs `/trevskills-migrate` and **Merge** exactly as it already does: its main checkout guard and every refusal still apply, and a refusal or a stopped migrate leaves the job `needs-human`. `--model sonnet` on that session is the only model override; never edit any agent's `model:` line.
   - PR `CLOSED`: `B set $ID stage=needs-human pr=<url> reason="cloud PR closed without merging. Fix: click Abort job with Put back in backlog ticked to run it again."`.

   When any job went `done`, run **Merge** step 7's **Fast-forward main** once; if it fails, run `B set <each such id> reason='merged, not live: <why>'`.

## Check gate

If the job's `lane` is `fast`, see **Fast lane** (promotion on the 2nd failure, and before Review). If the job's `lane` is `debug`, step 2 adds the debug checks and step 4 ends differently.

1. `N = round + 1` (round as stored on the board). Run `mkdir -p $F/jobs/$ID/round-$N`, then `B set $ID round=$N stage=check`.
2. In `$WT`, run each of Test / Typecheck / Lint / Build from `project.md` that isn't `none`. When `project.md` has an `E2E:` line that isn't `none` and any file in `git -C "$WT" diff --name-only "$BASE"...HEAD` matches `UI globs`, also run that E2E command in `$WT`; it is reported like the others, and a non-zero exit is `CHECK: FAIL`. Also run `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)\.env'`; any output is a failure ("committed .env file").
   For `lane=debug`, also run these; each failure makes `CHECK: FAIL` and gets its own entry in check.md:
   - **Repro:** the `Repro:` command from `assessment.md`, in `$WT`. It must exit 0.
   - **Allowed files:** every path in `git -C "$WT" diff --name-only "$BASE"...HEAD` must be listed under `## Allowed files` or be the `Repro test:` path. Otherwise it fails with `outside allowed files: <path>`.
   - **Repro test untouched:** `git -C "$WT" diff --name-only <Commit from repro-before.md> HEAD -- <Repro test path>` must print nothing. Otherwise it fails with `repro test changed`.
3. Write `round-$N/check.md`: first line `CHECK: PASS` or `CHECK: FAIL`, then for each command its exit code and the last 40 lines of output in a fenced block.
4. If it says FAIL, resume the builder with `Checks failed: read JOB_DIR/round-N/check.md, fix, commit, update build.md.` Then re-run steps 2–3, overwriting `check.md`. Allow up to **3** fix attempts. While the board says `builder=local`, attempts 1 and 2 re-run the local builder and attempt 3 is its cloud retry (see **Routing**). If it still fails, skip the review and go to **Approve**; the approver rules on the failing check. Exception: a `lane=debug` job that still fails after the 3rd fix attempt never goes to **Approve**: run `B set $ID stage=needs-human reason="debug: 3 failed fixes — question the design. Fix: click Discuss first."` and stop.
5. If it says PASS, go to **Review**.

## Review (WAIT FOR ALL)

If the job's `lane` is `fast`, see **Fast lane** instead of this section.

1. Run `B set $ID stage=review`. Write `git -C "$WT" rev-parse HEAD` to `round-$N/head.txt` (the HEAD this round reviews).
2. **Which reviewers run.** First decide incremental or full review, then apply the skips. Every file written here is written before any spawn.
   - **Incremental re-review** (only on a round `N >= 2` that this session started through step 5's `CHANGES` route). `SINCE` is the content of `round-(N-1)/head.txt`. For each of `security`, `ux`, `ui`, `code`: when `round-(N-1)/review-<role>.md` starts `VERDICT: PASS`, spawn nothing for it and write `round-$N/review-<role>.md` yourself, containing exactly:
     ```
     VERDICT: PASS
     Carried forward from round <N-1>: no blocking findings.
     ```
     When it starts `VERDICT: CHANGES`, that reviewer is spawned in step 3 with two extra prompt lines: `SINCE=<SINCE>` and `Re-review: verify each blocking finding in JOB_DIR/round-<N-1>/review-<role>.md against git diff SINCE..HEAD.` The skips and the Jev gate below are not applied on an incremental round.
   - **Full review fallback.** Skip the incremental rule, and run every reviewer on the full diff with the normal skips below, when any of these holds: `round-(N-1)/head.txt` is missing or unreadable; any path in `git -C "$WT" diff --name-only <SINCE> HEAD` is not in `git -C "$WT" diff --name-only "$BASE"...<SINCE>` (the fix touched a file the earlier reviews never saw); or the round was started by the Approve `REWORK` route, by the Merge **Conflicts** step, or by a resumed session that can't tell how it started.
   - **UI/UX skip (decided from the diff, never from the spec's `UI surface:` line).** If `project.md` has `UI globs` set to something other than `none`, and no file from `git -C "$WT" diff --name-only "$BASE"...HEAD` matches any of them (matching rules are in First-run setup), write `round-$N/review-ui.md` and `round-$N/review-ux.md` yourself, each containing exactly:
     ```
     VERDICT: PASS
     Skipped by orchestrator: no UI files in diff.
     ```
     Otherwise (`UI globs` missing or `none`, or any file matches), ui and ux run.
   - **Security skip.** When the diff can be read and no file in `git -C "$WT" diff --name-only "$BASE"...HEAD` matches the **Fast lane** sensitive-path regex, the **Merge** schema guard regex, `(^|/)\.env`, or the manifest regex `(^|/)(package\.json|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|requirements[^/]*\.txt|pyproject\.toml|go\.mod|Cargo\.toml)$`, write `round-$N/review-security.md` yourself, containing exactly:
     ```
     VERDICT: PASS
     Skipped by orchestrator: no sensitive files in diff.
     ```
     Otherwise (a match, or the diff can't be read) security runs. Re-check every round.
   - **Jev gate (additive only).** On a full-review round, only when at least one of the two skips above was taken and `~/.claude/scripts/jev-rank.py` exists, ask it about each skipped kind. The questions are `This diff needs a security review` and `This diff needs a UI review`. Run each with Bash timeout 90000:
     ```bash
     { git -C "$WT" diff --stat "$BASE"...HEAD | tail -1; git -C "$WT" diff --name-only "$BASE"...HEAD; } | tr '\n' ' ' | python3 ~/.claude/scripts/jev-rank.py "<question>" --top 1
     ```
     The score is the first tab-separated field of its output. A score `>= 0.7` deletes that skip file and the reviewer runs: security for the security question, both ui and ux for the UI question. A non-zero exit, a timeout, empty output or an unparseable score leaves the skips as they are. Jev never removes a reviewer, and is never consulted in the fast lane or for carried-forward reviewers.
3. Spawn the reviewers **in ONE message**, in the background: `scrum-review-security`, `scrum-review-ux`, `scrum-review-ui`, `scrum-review-code`, minus every one whose `round-$N/review-*.md` step 2 wrote. Each gets the 5 lines with `ROUND=$N` plus `Review this round. Write only your own review file.`, and the two re-review lines from step 2 on an incremental round. No `model:` override is passed to any reviewer.
4. **WAIT FOR ALL.** Do nothing else until every spawned reviewer has completed. Then run `B sync $ID`. If the board says `builder=local`, log `review-pass` or `review-changes` (see **Routing** step 5).
   - `complete` must be `true`. If it isn't, `missing` lists the absent files (e.g. `review-ui.md`): re-spawn only the reviewers named in `missing`, once. If a file is still missing after the re-spawn, write that file yourself as `VERDICT: CHANGES` plus `Reviewer produced no output.`, then run `B sync $ID` again.
   - If `invalid` is non-empty, delete those files and re-spawn those reviewers, once. If they come back invalid again, treat them as CHANGES.
   - **Never resume the builder mid-round.**
5. Route:
   - `verdict` is `PASS` on a **clean round**: go straight to **Merge**. Spawn no approver; there is no decision.md. A clean round is one where every one of these holds:
     - the job's `lane` is `standard`;
     - `N` is 1;
     - `round-1/check.md` is `CHECK: PASS`;
     - all four `round-1/review-*.md` start `VERDICT: PASS` (orchestrator-written skip files count);
     - no file in `git -C "$WT" diff --name-only "$BASE"...HEAD` matches the **Merge** schema guard regex, the **Fast lane** sensitive-path regex, or `(^|/)\.env`;
     - the spec's `Hard stops:` line is exactly `none`;
     - this session knows the round was not started by the Merge **Conflicts** step.

     The PR uses the no-Merge-summary fallback in Merge step 3 (job title, spec acceptance criteria as bullets), and the body line `Approved by the scrum approver. Spec, reviews and decision: scrum/jobs/$ID/` is replaced by `Clean round: check gate + reviews. Spec and reviews: scrum/jobs/$ID/`. The schema guard still runs unchanged. With no decision.md, the `Restart:` line counts as `none`.
   - `verdict` is `PASS` otherwise, including when you can't tell whether a condition above holds: go to **Approve**.
   - `verdict` is `CHANGES` and `round < limit`: resume the builder with `Review round N has CHANGES: read every review-*.md in JOB_DIR/round-N/, fix blocking findings, commit, update build.md.` Run `B set $ID stage=build`, then go to **Check gate**.
   - `verdict` is `CHANGES` and `round >= limit`: go to **Approve**.

## Approve

1. Run `B set $ID stage=approve`. Spawn `scrum-approver` and wait for it. Prompt: the 5 lines plus `Decide this job. Write decision.md.`
   - **Model:** pass the Agent tool override `model: "sonnet"` to `scrum-approver` only when all of these hold: the latest `round-$N/check.md` is `CHECK: PASS`; all four `round-$N/review-*.md` start `VERDICT: PASS` (orchestrator-written skip files count); the Merge schema guard regex matches nothing in the diff; and you know this round was not started by the Merge **Conflicts** step. In every other case (including when you can't tell, e.g. after a session restart) omit the override so the agent's default, Opus, runs.
2. Copy `decision.md` into `round-$N/decision.md`; that's how the approver later sees whether REWORK has already been used. Run `B sync $ID` and read `decision`.
3. **Follow-ups.** When `decision.md` has no `## Follow-ups` section, or it is empty, or its only bullet is `- none`, spawn nothing, run neither `backlog-spec` nor `backlog-add`, and go to step 4. Otherwise pre-write a spec per follow-up:
   - If the board's `specwriter` is a recorded agent id, use SendMessage to it, the same way **Resuming the builder** does. Spawn a fresh `scrum-spec-writer` (see **Routing**) instead when `specwriter` is `local`, missing or empty, or when SendMessage fails because the agent no longer exists. The message or prompt is:
     ```
     JOB_DIR=$F/jobs/$ID
     BACKLOG=$F/backlog.md
     PROJECT=$F/project.md
     Run follow-up mode: pre-write a spec for each Follow-ups bullet in decision.md.
     ```
   - Wait for it, then run `B backlog-spec $ID`. If it reports `skipped` files, name them in the final report only.
   - **Fallback:** if the spec writer fails, leaves no `$F/jobs/$ID/followups/*.md`, or `B backlog-spec $ID` exits non-zero, append the bullets with `B backlog-add "<item> (from $ID)" ...`, one argument per bullet. The lock keeps parallel sessions from clobbering each other.

   Approve never blocks or sets needs-human because of this step; go on to step 4.
4. Route:
   - `APPROVE`: go to **Merge**.
   - `REWORK` and sync's `"reworks"` is greater than 1: the approver broke the once-only rule. Run `B set $ID stage=needs-human reason="approver requested second rework. Fix: read decision.md, then click Approve & merge or Send back to builder."` and stop.
   - `REWORK` (first time): run `B set $ID limit=$((N+1)) stage=build`. Resume the builder with `The approver requested rework: read JOB_DIR/decision.md (Rulings marked fix-now), fix, commit, update build.md.` Then go to **Check gate**.
   - `ESCALATE` or `INVALID`: the reason is the second line of `decision.md` plus the fix for its hard-stop kind. If it starts `Hard stop: schema`, run `B set $ID stage=needs-human reason='<second line of decision.md>. Fix: click Approve & merge; it runs /trevskills-migrate first.'`. If it starts `Hard stop: money`, `Hard stop: auth` or `Hard stop: secrets`, run `B set $ID stage=needs-human reason='<second line of decision.md>. Fix: review the diff, then click Approve & merge.'`. If it starts `Hard stop: blocked`, run `B set $ID stage=needs-human reason='<second line of decision.md>. Fix: type what the builder needs and click Send back to builder.'`. For any other second line, run `B set $ID stage=needs-human reason='<second line of decision.md>. Fix: click Discuss first.'`. For INVALID, run `B set $ID stage=needs-human reason="approver output unreadable. Fix: click Discuss first."`. Report and stop.

## Merge (APPROVE, or /trevskills-scrum approve)

The steps below reuse the lessons from `/trevskills-commitpush`.

1. **Preconditions:**
   - `command -v gh && gh auth status` must succeed. If not, run `stage=needs-human reason="GitHub CLI is not installed or not signed in; branch scrum/$ID is local only. Fix: run brew install gh, then gh auth login in Terminal, then click Approve & merge."` and stop.
   - `git -C "$WT" status --porcelain` must be empty. If it isn't, resume the builder once with `Commit or remove uncommitted changes.` If it is still dirty, run `B set $ID stage=needs-human reason='Uncommitted files in the job worktree: <first files>. Fix: click Send back to builder and ask it to commit or remove them.'` and stop.
   - **Schema guard (deterministic; doesn't rely on any model):** if `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)prisma/(schema\.prisma|migrations/)|\.sql$'` prints anything and `$F/jobs/$ID/human-approval.md` doesn't exist, run `B set $ID stage=needs-human reason='Hard stop: schema — <first matching file>. Fix: click Approve & merge; it runs /trevskills-migrate first.'` and stop. Run this guard again right before step 6, because CI-fix commits skip the approver.
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
6. **Merge:** re-run the schema guard from step 1. If the job's `lane` is `debug` and step 4 made any CI fix commit, next to it re-run the three **Check gate** debug checks (Repro, Allowed files, Repro test untouched) in `$WT` on HEAD; if any fails, run `B set $ID stage=needs-human reason='debug: checks fail after CI fix — <first failing check>. Fix: click Send back to builder with what to change.'` and stop without merging. Then run `B sync $ID` right before merging; if it says the job was aborted, stop. Then `gh pr merge "scrum/$ID" --squash --subject "<title> (#<number>)" --body-file "$BODY"`. Never use `--auto`, `--admin` or `--delete-branch`. If the merge fails (branch protection, a required review, anything else), run `B set $ID stage=needs-human reason='merge refused: <first line of stderr>. Fix: clear that on GitHub, then click Approve & merge.'` and stop.
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
   - **Roadmap chaining.** If the job has no `parent`, after `stage=done` run `B roadmap-next $ID`. When it prints a step, do **Roadmap lane** **Starting a step** with it after the Digest check. A job in no roadmap prints `null`: nothing more happens.
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

Outside the **Lilguy lane**, the orchestrator never edits code or review files itself, except for these sanctioned review files: the UI/UX skip files and the security skip file in **Review** step 2, the `Carried forward from round` files in **Review** step 2, the `Reviewer produced no output.` fallback, and the fast lane skip files in **Fast lane** step 2.

## Digest

Learns from finished jobs. It runs from the main checkout (Setup applies, but not the Prerequisites: it needs no remote and no `gh`), and it never pushes, merges or opens a PR. It never edits an agent, skill, rule or memory file itself. Step 4 auto-approves the proposals the digester marked obvious, which only ever queues a repo backlog item. Trevor approves or rejects every other proposal from its needs-human card on the board or in the dashboard's **Digest** dialog. The last decision trims the digested job folders.

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
4. If the `proposals` list is empty, run `B digest-trim <id>`. Otherwise run `python3 ~/.claude/skills/trevskills-scrum/serve.py --digest-auto <id> --dir $F`. It prints `{"approved": [{"id", "target", "obvious_reason"}], "human": [{"id", "reason"}]}`. Report each approved proposal as `<pid> → <target>: <obvious_reason>`, then the number of `human` proposals left for Trevor on the board.

## Final report

End with the job id, the final stage, for a BigBoy parent or child the children this run started (or `none`) and the parent's stage, the PR URL, rounds used, any follow-ups added to the backlog, for merged jobs whether main was fast-forwarded (`main updated`, or `main not updated: <reason>`) the restart outcome (`restarted + verified`, `restarted + verified (behavioural)`, `restart failed`, `restart command not allowed`, `verify failed`, `Restart pending: <process> — <reason>`, or `none`), and whether the change is live (`live`, or `merged, not live: <why>` as written to the board), and, for needs-human, the exact reason and the next command (`/trevskills-scrum approve <id>`, `/trevskills-scrum rework <id> "<feedback>"`, or `/trevskills-scrum discuss <id>` when it's unclear which).
