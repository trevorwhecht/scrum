# Cloud lane

Runs backlog jobs in Claude Code cloud sessions (claude.ai/code), paid by Trevor's cloud-session credit instead of his weekly plan. The cloud environment's setup script is `cloud/setup.sh` from the scrum repo, so the session loads this same skill and agents. Only the differences are listed; every other step runs as written.

1. **Dispatch** (`/trevskills-scrum cloud [N]`, N defaults to 4; from the main checkout; Setup and Prerequisites apply). First run **Sync** (step 3). Then refuse with a plain message and start nothing when:
   - `$F/project.md` has a `Base branch:` line: `Cloud lane does not support Base branch yet. Fix: run these jobs locally.`
   - `git -C "$REPO" status --porcelain -- . ':(exclude)scrum'` prints anything, `git -C "$REPO" symbolic-ref -q --short HEAD` is not `$DEFAULT` (found as in **New job** step 2), or after `git fetch origin` `git -C "$REPO" rev-list "origin/$DEFAULT..HEAD"` prints anything: `<repo name> must be clean, on <default> and pushed. Fix: commit and push or discard, then run cloud again.`
   - **Credit check (before every batch).** The credit balance has no API. When the Claude in Chrome tools are available (`mcp__claude-in-chrome__*`; read the chrome-browser skill first), open https://claude.ai/settings/usage in a new tab and read `Cloud session credits ... $X of $250 left`. If X is under $25: `Cloud credit is $X, under $25. Fix: top up, then run cloud again.` If the tools are missing or X can't be read, ask Trevor once with AskUserQuestion whether at least $25 is left; anything but a yes refuses with `Cloud credit unreadable and unconfirmed.`

   Then up to N times: run `B next`; stop when `id` is null. Write the feature text to `$F/jobs/$ID/feature.md` (**New job** step 1b). The cloud session sees neither `jobs/` nor `digests/` (both stay on this Mac), so make `feature.md` self-contained before the session reads it:
   - **Pre-written spec.** When `$F/jobs/$ID/spec.md` exists (`B next` moved it there from the backlog), append it to `feature.md` under a `## Pre-written spec` heading.
   - **Digest proposals.** When the feature text names a local `.../digests/<NNN>/proposals.json` path (older digest items), read that digest's proposals from `$F/digests/<NNN>/proposals.json` and, for each proposal id the text names (`digest <NNN> <PID>`), append a `## Digest proposal <NNN> <PID>` section with the target relative to the repo, the why, and the old and new text, each in a backtick fence longer than any backtick run inside it. End the section with: `This section replaces the local proposals.json path: do not open proposals.json or run --digest-skill-check. The item is obsolete when the old text is not found exactly once in the target (edit) or the target already exists (skill, empty old).`
   - **Missing proposal.** When a proposal the text names is not in that file (or the file is missing), start no session for this job and run `B set $ID stage=needs-human reason='digest proposal <NNN> <PID> not found in proposals.json. Fix: click Abort job with Put back in backlog ticked, then run it locally.'`.

   Then start the session (macOS `script` gives `claude --cloud` the TTY it needs; the feature text stays inside a variable so the shell expands nothing in it; the environment goes in through `--settings`, because the environment flag takes only self-hosted `ccpool_` ids, and nothing may sit between `--cloud` and its prompt, or that flag swallows it):
   ```bash
   CE=$(sed -n 's/^- Cloud environment: *//p' "$F/project.md" | head -1 | sed 's/[[:space:]]*$//'); E=()
   printf '%s' "$CE" | grep -qE '^[A-Za-z0-9_-]+$' && E=(--settings "{\"remote\":{\"defaultEnvironmentId\":\"$CE\"}}")
   FEAT=$(cat "$F/jobs/$ID/feature.md")
   OUT=$(script -q /dev/null claude "${E[@]}" --cloud "First run: bash ~/scrum/cloud/setup.sh (the environment caches an old copy of the skill). Then invoke the trevskills-scrum skill fresh and run: /trevskills-scrum cloud-job $ID $FEAT" < /dev/null 2>&1)
   URL=$(printf '%s' "$OUT" | grep -oE 'https://claude\.ai/code/session_[A-Za-z0-9_-]+' | head -1)
   ```
   With a `URL`, run `B set $ID stage=cloud cloud=$URL`. Without one, run `B set $ID stage=needs-human reason='claude --cloud did not start: <last line of OUT>. Fix: click Abort job with Put back in backlog ticked, then run cloud again.'`. Stage `cloud` is never flagged by `B watchdog`. The final report lists each id with its session URL.
2. **Cloud job** (`/trevskills-scrum cloud-job <id> <feature text>`, inside the cloud session). The job runs **New job** end to end (spec → build → Check gate → Review → Approve → Merge) with these deltas:
   - **Setup:** the cloned repo is the main checkout, and its `scrum/` is a throwaway board: first-run setup as usual, minus step 5. Prerequisites check `gh api user` instead of `gh auth status` (cloud `gh` is signed in through a proxy that `gh auth status` rejects). Skip Roadmap resume and **Record your terminal**: no dashboard, tty or terminal recording here.
     When this session's skill copy lacks the **Artifacts** step below, the launch prompt's setup.sh refresh did not take: it stops before New job with needs-human reason `cloud skill copy is stale. Fix: rerun cloud setup.` and reports to GitHub as **Needs-human** does.
   - **Job:** New job step 1 is `B new "<title>" --id <id>`, so the job keeps the id it was given; then step 1b, then step 2 on. A spec that says `Lane: bigboy` counts as `standard`, as for a BigBoy child.
   - **Routing** is always cloud: never call route.py; every routed step spawns with the Agent tool as written.
   - **GitHub:** cloud blocks GitHub GraphQL, so each `gh pr` call in **Merge** becomes its REST twin, with `R='repos/{owner}/{repo}'` (`gh` fills it in from origin). These are the same sanctioned PR create and squash-merge.
     - step 3 lookup: `gh api "$R/pulls?head={owner}:scrum/$ID&state=all" --jq '.[0] | {number, html_url, state, merged_at}'` (`merged_at` set is MERGED);
     - step 3 create: the title starts `[scrum <id>] ` (that is how **Sync** finds it): `gh api "$R/pulls" -f title="[scrum $ID] <title>" -f head="scrum/$ID" -f base="$DEFAULT" -F body=@"$BODY" --jq .html_url`;
     - step 4 checks, in the background: `SHA=$(git -C "$WT" rev-parse HEAD)`, then every 15 s `gh api "$R/commits/$SHA/check-runs" --jq '[.check_runs[] | .conclusion // "pending"] | unique | join(" ")'` until it has no `pending`; still empty after 90 s is "no CI ran"; anything but `success`, `skipped` and `neutral` is a failure, and `ci.md` gets each failing run's name, conclusion, `html_url` and `output.summary`;
     - step 5: `gh api "$R/pulls/<number>" --jq .mergeable`, where `null` is `UNKNOWN` and `false` is `CONFLICTING`; the **Conflicts** steps then run unchanged, which is also how parallel cloud jobs settle conflicts;
     - step 6: `gh api -X PUT "$R/pulls/<number>/merge" -f merge_method=squash -f commit_title="<title> (#<number>)" -F commit_message=@"$BODY"`.
   - **Merge** auto-merges under exactly the local rules: every hard stop (schema, agent rules, money, auth, secrets, blocked) still stops. Skip step 1's main checkout guard. Step 7 is only `B set $ID stage=done reason=`: no worktree removal, fast-forward, restart, verify, chaining or Digest (local **Sync** fast-forwards Trevor's checkout).
   - **Never migrate in cloud:** never run `/trevskills-migrate`, `prisma migrate` or `prisma db push`; `approve` and its migrate step only ever run locally. A `Hard stop: schema` (from the approver or the Merge schema guard) is reported as **Needs-human** below, so its comment's first line starts `Hard stop: schema`, and **Sync** migrates it locally.
   - **Needs-human:** every time this job would set `stage=needs-human` (or abort itself as obsolete, with its `obsolete: ...` reason), it also reports to GitHub, then stops: push `scrum/$ID` (with no commits beyond `$BASE`, push `$(git commit-tree "$BASE^{tree}" -p "$BASE" -m "[scrum $ID] needs-human")` to `refs/heads/scrum/$ID` so a PR can exist), open the PR as above or keep the open one, add the label with `gh api "$R/issues/<number>/labels" -f "labels[]=scrum:needs-human"`, and post a comment whose first line is the reason and whose second line is `<!-- scrum needs-human -->`, with `gh api "$R/issues/<number>/comments" -F body=@<file holding it>`.
   - **Artifacts:** every time the job ends (merged, needs-human or obsolete abort), as its last action before it stops (after Merge step 7's `B set`, or after the **Needs-human** PR, label and comment), push the job folder to `scrum-artifacts/<id>` without touching the checkout or its index, so local **Sync** can bring it home:
     ```bash
     I=$(mktemp -u); cd "$F"
     B artifacts $ID | tr '\n' '\0' | GIT_INDEX_FILE=$I xargs -0 git add -f --
     T=$(GIT_INDEX_FILE=$I git write-tree); C=$(git commit-tree "$T" -m "[scrum $ID] artifacts")
     git push origin "$C:refs/heads/scrum-artifacts/$ID"; rm -f "$I"; cd "$REPO"
     ```
     `B artifacts` prints only the files that are safe to push and names the rest in `skipped-secrets.txt`. The branch is never merged and never has a PR. A failed push is reported in the final report but does not change the job's outcome.
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
   - **Artifacts home.** For a `MERGED`, `scrum:needs-human` or `CLOSED` PR, right after its `B set` (and before **Schema auto-migrate** starts the detached approve), bring the job folder home. A missing branch means the fetch fails: extract nothing, report no error, and go on. The copy never overwrites the local `feature.md`: it copies all but `feature.md`. The branch is deleted only after the copy succeeds, and never force:
     ```bash
     cd "$REPO"
     if git fetch origin scrum-artifacts/$ID 2>/dev/null; then
       T=$(mktemp -d)
       git archive FETCH_HEAD scrum/jobs/$ID | tar -x -C "$T" && rm -f "$T/scrum/jobs/$ID/feature.md" &&
         mkdir -p "$F/jobs/$ID" && cp -R "$T/scrum/jobs/$ID/." "$F/jobs/$ID/" &&
         git push origin --delete scrum-artifacts/$ID
       rm -rf "$T"
     fi
     ```
   - **Follow-ups.** Then, as **Approve** step 3 (including its Fallback) does on its own board: when `$F/jobs/$ID/followups/*.md` exist, run `B backlog-spec $ID`; otherwise, when `decision.md` has a non-empty `## Follow-ups` section that is not just `- none`, run `B backlog-add "<item> (from $ID)" ...`, one argument per bullet. Separately, when `decision.md` has a non-empty `## Manual checks` section that is not just `- none`, run `B manual-add "<item> (from $ID)" ...`, one argument per bullet, whatever `## Follow-ups` holds; a failing `manual-add` never blocks the sync. Spawn no spec writer here.
   - **Digest-approved rules edits.** For a `scrum:needs-human` PR whose reason starts `Hard stop: agent rules` and whose worktree add succeeded, after **Artifacts home** and **Follow-ups**, run `B digest-verify $ID` (a cloud session has no digests folder, so it always stops there). When it exits 0, run **Merge** for that job in this session with `ID=$ID`, `WT=$REPO/.claude/worktrees/scrum-$ID` and `BASE=origin/<baseRefName>`; every Merge guard re-runs, including this check. Never start an `approve` for it: that writes `human-approval.md`, which would claim Trevor approved the diff. When it exits non-zero, leave the job `needs-human` for Trevor.

   When any job went `done`, run **Merge** step 7's **Fast-forward main** once; if it fails, run `B set <each such id> reason='merged, not live: <why>'`. Then run `B digest-due`, and when it prints `"due": true`, run **Digest**.
