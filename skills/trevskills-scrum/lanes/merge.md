# Merge

3. **PR.** Run `gh pr view "scrum/$ID" --json number,url,state`:
   - `OPEN`: reuse it.
   - `MERGED`: skip steps 4–6 and go to step 7 (Clean up).
   - `CLOSED`: run `B ask $ID "The pull request for this job was closed on GitHub, so it cannot merge; reopen it on GitHub, then pick Try again." --a "Try again=approve $ID" --b "Put back on the backlog=abort $ID --requeue" --c "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop.
   - No PR, or reusing one: the title is the decision.md `Merge summary` title. If there is no Merge summary (a human-approved ESCALATE), use the job title and the spec's acceptance criteria as bullets. Either way write the body to `BODY=$F/jobs/$ID/pr-body.txt`, which is also used in step 6. The body is the Merge summary bullets, then `Approved by the scrum approver. Spec, reviews and decision: scrum/jobs/$ID/` (for a fast-lane job, the line in **Fast lane** step 3 instead; for a Clean round, the `Clean round:` line in **Review** step 5 instead), then a line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Create it with `gh pr create --base "$DEFAULT" --head "scrum/$ID" --title "<Merge summary title>" --body-file "$BODY"`.

   Then `B set $ID pr=<url>`.
4. **Checks.** Run this in the **background**:
   ```bash
   for i in 1 2 3 4; do out=$(gh pr checks "scrum/$ID" --watch --fail-fast --interval 15 2>&1); code=$?
     echo "$out" | grep -q "no checks reported" || break; sleep 20; done; echo "exit=$code"; echo "$out" | tail -40
   ```
   - `exit=0`: continue to step 5.
   - Still "no checks reported": the repo has no CI. Continue, and note "no CI ran" in the final report.
   - Any other failure: write the failing output to `$F/jobs/$ID/ci.md`, resume the builder with `CI failed: read JOB_DIR/ci.md, fix, commit.`, push again, and re-check. Allow at most **2** CI fix attempts. After that, run `B ask $ID "CI still fails after 2 fix attempts: the automated tests on GitHub kept failing after two automatic fixes, and the failure log is in the ci.md tab of this job." --kind ci-fail --a "Send back with a note=rework $ID \"CI still fails: read ci.md and fix the root cause\"" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop.
5. **Conflicts.** Run `gh pr view "scrum/$ID" --json mergeable --jq .mergeable`. On `UNKNOWN`, re-run it in the background every 10 seconds, up to 6 times. If it returns `CONFLICTING`, resolve it. This merge (like the pre-build sync in **New job**) only ever goes into this job's own branch. Allow at most **2** attempts; only after both fail, run `B ask $ID "merge conflicts with $DEFAULT after 2 tries: newer changes on $DEFAULT edit the same lines as this job, and two automatic attempts to combine them failed." --kind conflict --a "Put back on the backlog=abort $ID --requeue" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop. Each attempt:
   1. `git -C "$WT" fetch origin`, record the pre-merge HEAD with `git -C "$WT" rev-parse HEAD`, then `git -C "$WT" merge "origin/$DEFAULT" --no-edit`.
   2. If that merge itself conflicts, resume the builder with `The default branch was merged into your branch and has conflicts: resolve them, commit, update build.md.`
   3. If `git -C "$WT" diff --name-only <pre-merge HEAD> HEAD -- package-lock.json` prints anything (also after the builder resolved conflicts), run `Install` from `project.md` in `$WT` before the Check gate; skip it when `Install` is `none` or the lockfile did not change, and never symlink `node_modules`. If the install fails, carry on to the Check gate, which reports the failure; add no `B ask`.
   4. Run `B set $ID limit=$((N+1))` and go to **Check gate**. That gives a fresh check and full review round, then the approver, then Merge again, reusing the open PR.
6. **Merge:** re-run the schema guard from step 1. If the job's `lane` is `debug` and step 4 made any CI fix commit, next to it re-run the three **Check gate** debug checks (Repro, Allowed files, Repro test untouched) in `$WT` on HEAD; if any fails, run `B ask $ID 'debug: after the fix for the GitHub test failure, the bug fix no longer passes its own checks: <first failing check, in plain words>.' --a "Send back with a note=rework $ID \"the debug checks fail after the CI fix: make the repro, allowed files and repro test checks pass\"" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` and stop without merging. Then run `B sync $ID` right before merging; if it says the job was aborted, stop. Then `gh pr merge "scrum/$ID" --squash --subject "<title> (#<number>)" --body-file "$BODY"`. Never use `--auto`, `--admin` or `--delete-branch`. If the merge fails (branch protection, a required review, anything else), run `B ask $ID 'merge refused: <first line of stderr>; clear that on GitHub, then pick Try again.' --a "Try again=approve $ID" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` (`<first line of stderr>` rewritten to the **Issue** bar in `lanes/stops.md` with its prefix kept) and stop.
7. **Clean up:**
   - **Pick the verify string** (only when the decision.md `Restart:` line is not `Restart: none`), before removing the worktree: a distinctive piece of one line this job's diff added to a served file (a new CSS class, copy string or JSON key), from `git -C "$WT" diff "$BASE"...HEAD`. Prefer a substring of at least 8 characters that contains none of `'` `"` `` ` `` `$` `\` `!` or a newline. If none exists, use the line as is; Verify passes it through a quoted heredoc. If the diff adds no line to a served file, there is no verify string and Verify uses the behavioural check.
   - Run `git worktree remove "$WT"`. If git refuses because of local changes, leave the worktree in place and mention it.
   - Run `git fetch origin`.
   - **Fast-forward main (always, whatever the `Restart:` line says).** The dashboard and this skill are served from the main checkout, so it must not stay behind origin:
     1. **Guard (same test as step 1):** `git -C "$REPO" symbolic-ref --short HEAD` must equal `$DEFAULT`, and `git -C "$REPO" status --porcelain --untracked-files=no` must be empty.
     2. If both pass, run `git -C "$REPO" pull --ff-only`.
     3. If a guard check or the fast-forward fails, report `main not updated: <reason>`, where reason is `not on <default>`, `uncommitted changes` or `fast-forward failed`. Never merge, reset, rebase or stash to make it work.
   - **Restart.** Read the `Restart:` line from `$F/jobs/$ID/decision.md` (no line, e.g. a human-approved ESCALATE without one, counts as `none`). If it is not `Restart: none`, in order:
     1. **Skip if main wasn't updated:** if the fast-forward above did not succeed, do not restart. Report `Restart pending: <process> — <reason>`, with the same reason as `main not updated`.
     2. **Restart:** `<port>` is the number in the `Restart:` line's `on port <N>`; when the line names serve.py and gives no port, use 8765. A non-serve.py line with no port is not restarted: report `Restart pending: <process> — no port in Restart line` and treat it as `restart failed`. Start only an allowed command, and never one taken from the `Restart:` line:
        - serve.py: `mkdir -p ~/.claude/trevskills-scrum && nohup python3 ~/.claude/skills/trevskills-scrum/serve.py >> ~/.claude/trevskills-scrum/serve.log 2>&1 &`;
        - anything else: the exact `Dev command:` value from `$F/project.md`, run as `nohup <Dev command> >> "$F/dev.log" 2>&1 &` from `$REPO`.

        If the line names any other start command, or `Dev command:` is `none` or missing for a non-serve.py process, run nothing: report `Restart pending: <process> — restart command not allowed` and treat it as `restart command not allowed`. Otherwise record the old PID with `lsof -ti tcp:<port> -sTCP:LISTEN`, stop it with `lsof -ti tcp:<port> -sTCP:LISTEN | xargs kill`, and start the allowed command.
     3. **Verify:** run only `curl -sfL localhost:<port>/<path>`, alone or piped to `grep -F -- <string>`. If the `Restart:` line's `verify:` has any other shape, do not run it; build this form from the port and the changed path (`/` when none is more specific). Retry in the background for a few seconds while it starts.
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
   - **Mark done, only now.** If the guard, the fast-forward, the restart or the verify failed, run `B set $ID stage=done reason='merged, not live: <why>'`, where `<why>` is `not on <default>`, `uncommitted changes`, `fast-forward failed`, `restart failed`, `restart command not allowed` or `verify failed`. The three main-checkout reasons also carry a fix sentence right after `<why>` in the reason: `not on <default>` gets ` Fix: run git checkout <default> in <repo name>, then git pull --ff-only.`, `uncommitted changes` gets ` Fix: stash or commit the changes in <repo name> (git stash or git commit), then git pull --ff-only.`, and `fast-forward failed` gets ` Fix: if local main holds commits origin lacks, push them or run git reset --hard origin/<default> yourself, then git pull --ff-only.` Trevor runs these fixes; agents never do. Otherwise (including `Restart: none` after a successful fast-forward) run `B set $ID stage=done reason=`. Trevor clears that reason with `B set <id> reason=` once the change is live.
   - If `B set ... stage=done` refuses, run `B ask $ID '<its error, quotes stripped>; merge the pull request on GitHub, then pick Try again.' --a "Try again=approve $ID" --b "Remove this job=abort $ID --cascade" --recommend <key> '<why>'` (`<its error>` rewritten to the **Issue** bar in `lanes/stops.md` with its prefix kept) and stop.
   - **Scrum map.** After `stage=done`, read each `- Scrum map:` line under `## Scrum map` in `$F/jobs/$ID/build.md` and apply it to `~/.claude/scrum-map.md` (`add "<line>" under <map heading>` or `replace "<old line>" with "<new line>"`, exact text). Edit no other file outside `$REPO`. No section, or only `- none`, means do nothing. Skip an `add` whose line, or a `replace` whose new line, is already in the map, so a re-run changes nothing. A line whose old text is not in the map, a missing map, or a line in neither shape is skipped as `Scrum map not applied: <line>`; it never stops the job; name it in the final report only.
   - **Spec follow-ups.** After `stage=done`, when `spec.md`'s `## Scope` has `Follow-up: <text>` lines, remove every `'` from each, run the **Dupe check** and **Rank** (3c, `jev-gate.py dupe`) on each, then `B backlog-add '<text> (from <job id>)' ...`, one argument per line. A failing `backlog-add` never stops the job; name it in the final report only.
   - **Roadmap chaining.** If the job has no `parent`, after `stage=done` run `B roadmap-next $ID`. When it prints a step, do **Roadmap lane** **Starting a step** with it after the Digest check. When it prints `null`, do **Roadmap lane** step 6 (**Roadmap done**) after the Digest check.
   - **BigBoy chaining.** If the job has a `parent`, after `stage=done` run **BigBoy lane** step 5 (tracker, `B ready`, start the next children or the final review).
   - **Digest check.** After `stage=done`, run `B digest-due`. If it prints `"due": true`, run **Digest** in this same session before the final report.

## Resuming the builder

Use SendMessage to the recorded `builder` (the name `builder-$ID`, or the stored agent id) with a message naming the exact file(s) to read. If SendMessage fails because the agent no longer exists (for example after a session restart):
1. Spawn a fresh `scrum-builder` with the 5 lines plus `You are resuming this job. Read spec.md, build.md, and <the file(s) above>, then continue.` Pass Agent override `model: "sonnet"` only when `$F/jobs/$ID/jev.log` has a `model` line that decided `sonnet` and no `promote` line; otherwise (jev.log missing included) no override (Opus). It makes no Jev call.
2. Run `B set $ID builder=<new id>`.

In a headless (`claude -p`) session, skip SendMessage: its reply would arrive after the turn ends, and the process exits with it (see **Headless sessions block.**). Resume through step 1 instead (spawn a fresh `scrum-builder` in the foreground and wait for it to return), then step 2.

**Sonnet promotion.** A cloud builder runs as Sonnet while `$F/jobs/$ID/jev.log`'s `model` line decided `sonnet` and it has no `promote` line. On its first `CHECK: FAIL` (**Check gate** step 4) or `VERDICT: CHANGES` round (**Review** step 5), instead of SendMessage:
1. Run `printf '%s\n' '<check-fail round N|changes round N>' | python3 ~/.claude/skills/trevskills-scrum/jev-gate.py promote $F/jobs/$ID` with Bash timeout 90000.
2. Spawn a fresh `scrum-builder` with Agent override `model: "opus"`: step 1's prompt above plus the resume text.
3. Run `B set $ID builder=<new id>`.

A builder already promoted is never promoted again.

Outside the **Lilguy lane**, the orchestrator never edits code or review files itself, except for these sanctioned review files: the UI/UX skip, security skip and `Carried forward from round` files that `B review-plan` writes in **Review** step 2, the `Reviewer produced no output.` fallback, and the fast lane skip files in **Fast lane** step 2.
