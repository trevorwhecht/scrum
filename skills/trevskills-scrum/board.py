#!/usr/bin/env python3
"""The scrum team's board. Only the /trevskills-scrum orchestrator calls this; nothing else writes board.json.

  board.py new "<title>" [--id ID] [--by <serve|runall|wake|hand>] create jobs/<id>/ and a board entry, print the id (--id keeps a given id; --by records who started it, default hand; without --id it refuses a title an open job already has, naming that job)
  board.py set <id> key=value ...  set stage/round/limit/pr/reason/worktree/builder/base/tty/runlog/lane/setup/waiting/specwriter/cloud/outcome/account/shop/worker (empty = null);
                                   stage=needs-human is refused: park a job with ask
  board.py set --unpause <id> ...  the same, on a job Trevor paused too (resume and rework only); with stage= it
                                   clears the pause
  board.py ask <id> "<q>" --a "Label=command" --b "Label=command" [--c ...] --title TITLE [--recommend KEY WHY]  park
                                   the job at needs-human with a closed question (command: approve|resume|abort <id>
                                   [--requeue|--cascade], rework <id> "<text>", followup <id> "<fix>", shell: <cmd>), log it to questions.log;
                                   --title (a STOP_TITLES key) is stored as stopTitle; --recommend stores {"key","why"},
                                   the option the agent advises; both are cleared with the question. With [--kind K]
                                   (K in UNBLOCK_KINDS, under 2 unblocks, not yet unblocked for K) the job is not parked: it keeps its stage, the unblock is logged and
                                   {"unblock": true, "n": N} is printed; else it parks and prints {"unblock": false}
                                   (lanes/unblock.md)
  board.py wait-on <id> <blocker> [--then "approve <id>"]
                                   park a builder-blocked job at stage waiting with depends_on=[blocker] (a full id or a
                                   number like 001); serve.py starts it once that job is done, print {"id","waiting_on"}.
                                   With --then the worktree is kept and the wake goes to needs-human with Try again, and
                                   serve.py spawns approve (SKILL.md Migrate step 2)
  board.py unblock-log <id>        read jobs/<id>/unblock-<unblocks>.md, log its verdict line to questions.log, print
                                   {"verdict","blocker","kind","n"} (verdict INVALID when missing or unreadable)
  board.py answer <id> <a|b|c>     log the pick on the job's open question to questions.log, print that option as JSON
  board.py followup <id> "<fix>"   a Prod check stop's follow-up answer: add "<fix> (from <id>)" to the backlog (once),
                                   then set the job stage=done
  board.py project-note "<line>"   append a spec's Project note line to project.md's "- Notes:" line (backup in
                                   project.md.bak; a line already in the file writes nothing), print {"added"}
  board.py sync <id>              re-read jobs/<id>/ into the board, print round status as JSON
  board.py next                    claim the first "- [ ]" backlog item that waits on no {needs #id} prerequisite,
                                   no {after repo:job} job of another registered repo that is not done, no {setup: …} Human
                                   setup, no trailing "(from <id>)" job still open, and is not held by the requeue loop
                                   guard (its last 3 claims were requeue aborts within 24 h, until Trevor edits it), as a
                                   new job, print {"id","feature"}
  board.py cloud-claim <N>         claim up to N open backlog items for the Cloud lane, skipping any that waits (as next
                                   skips it: prerequisite, after, loop guard or Human setup), has no pre-written spec with Likely files, or shares a
                                   Likely file with an earlier pick or a cloud/build job; print {"claimed": [{"id","feature"}, ...]}
  board.py backlog-add [--setup "<step>; <step>"] [--priority N | --top] [--trevor | --back] [--critical] "<item>"...
                                   append "- [ ] <item>" lines to backlog.md
                                   (--setup adds a " {setup: step; step}" marker: next and runall-start skip the item until
                                   Trevor clicks Setup done; --priority adds a " {p:N}" importance marker, N 1-5; --top
                                   inserts above the first item with {p:5}, so next claims it first, and implies --trevor;
                                   --trevor marks Trevor's item " {by:t}" at p:4, p:5 with --priority 5; --back marks it
                                   " {by:back}" at p:1; with neither it is an agent item, capped at p:3 unless --critical,
                                   passed after jev-gate.py critical confirmed, makes it p:5), then
                                   estimate each in the background
  board.py backlog-add --job <id> [--project <folder>] [flags] "<item>"...
                                   write each item, with its flags and target project folder, as a "Backlog: add" file
                                   jobs/<id>/followups/add-<n>.md instead (the job folder syncs home; the home backlog-spec
                                   files it); on a shop or cloud worker (SCRUM_SHOP set, CLAUDE_CODE_REMOTE=true) backlog-add
                                   without --job is refused, as that worker's backlog.md never syncs home
  board.py rank-backlog [--all]    Jev rates each open backlog item with no {p:N} marker, or every open item with --all
                                   (jev-gate.py rank, plus critical for an agent "Critical:" item, logged to jev.log), writes
                                   the source-capped {p:N} where it changed, print {"rated","unrated","skipped"}
  board.py manual-add "<item>"...  append "- [ ] <item>" lines to manual-checks.md (human-only checks; open duplicates
                                   and empty items are skipped), print the added texts as JSON
  board.py backlog-spec <id>       ingest jobs/<id>/followups/*.md: add or match backlog items, store each spec in
                                   backlog-specs/ (moved to the job's spec.md when claimed), print {"added","updated","skipped"};
                                   a "Backlog: add" file is filed in its Project's backlog (listed under "moved"), else here
                                   (ignored on a worker);
                                   a backlog edit of the text, a delete or a triage merge/retire/manual drops the item's spec
  board.py roadmap-show            print roadmap.md as {"name","phases","current","next","blocker"} (null = no roadmap)
  board.py roadmap-link <P> <S> <id>  write the job id into step P/S and mark it [~] (also resumes a [!] step)
  board.py roadmap-next <id>       mark the step holding <id> [x], print the next [ ] step {"p","s","kind","request"}
                                   or null; a job in no step (or no roadmap.md) changes nothing
  board.py roadmap-insert <P> <afterS> <bigboy|standard> <request>  add a [ ] step after S, renumber the rest of P
  board.py roadmap-stop <id> <reason>  mark the step holding <id> [!] and log the reason
  board.py register <repo>         add a repo to the all-projects dashboard (idempotent)
  board.py abort <id> [--requeue] [--cascade] [--reason TEXT]  mark a job aborted (terminal); --requeue puts it back on
                                   the backlog; --cascade also aborts its waiting, needs-human, paused or queued dependents
                                   (depends_on, transitively; Run-all ones requeued), prints {"aborted": [ids]}
  board.py artifacts <id>          print jobs/<id>/... paths safe to push (regular, under 1 MB, UTF-8, no secret); name the
                                   rest in jobs/<id>/skipped-secrets.txt (Cloud lane's scrum-artifacts/<id> branch)
  board.py db-up --env <file>      read DATABASE_URL from the env file; when its local host:port refuses, start the local
                                   database (brew postgres* service, else docker compose up -d) and re-probe every 5 s for
                                   up to 120 s; print {"up","started"} (exit 1 when still down), or {"up": null,"skipped"}
                                   for a missing file or URL or a non-local host (Check gate step 2)
  board.py cooldown-park <id>      never parks: cool down holds only new claims, so a started job carries on; prints
                                   {"parked": false} for a session on an older lane copy (job 1346)
  board.py dev-clear <id>          stop every server listening from inside the job worktree, its -base sibling or
                                   /tmp/scrum-base-<id>, even once the worktree is removed (TERM, up to 5 s, then
                                   KILL), print {"killed": [pids]}
  board.py digest-due              print {"due","undigested","questionsGrowth","reason"}: done jobs in no digests/*/jobs.txt
                                   and questions.log lines since the last digest's questions.lines; due at 10+ jobs ("10
                                   done"), 15+ lines ("questions"), or 3+ jobs and a bad windows/ scorecard (wasted >20%,
                                   or first pass <0.5 over 3+ jobs) no digests/*/windows.txt lists, written after the
                                   newest digest folder ("bad window <file>"); reason null when not due
  board.py digest-start            claim them all as digests/<NNN>/jobs.txt (+ questions.lines), and every windows/
                                   scorecard no live digest lists as windows.txt + windows.json, plus timing.md (per-job wall
                                   time, rounds, no-change rounds, E2E lock waits; jobs waiting on the E2E queue),
                                   and escapes.md (each bug job's origin job by git blame, with its PASS reviewers; a
                                   bug job is a debug job or one whose feature.md or spec.md Lane: line says bug),
                                   print {"id","jobs","windows"}
                                   (id null = nothing new; starts with no jobs when the questions trigger fired); then a
                                   pipeline health check parks one "Pipeline health: <tool>" job at needs-human per tool
                                   (codex-review, review-e2e, check) that failed in half the claimed jobs (2+)
  board.py digest-trim <NNN>       cut that digest's done job folders to feature.md, spec.md, decision.md
  board.py pipeline-fit <NNN>      print {"digest","jobs"}: each listed job's lane, agents, diff size, verdicts, fix rounds
                                   and whether a cheaper lane would have done (read-only; Digest step 1)
  board.py digest-trevor <NNN>     write digests/<NNN>/trevor.md (Trevor's Jev-ranked chat messages, each with the
                                   jobs in any registered project whose feature.md quotes it, feature.md quotes,
                                   new (Trevor …) backlog tags, answer notes since the last digest), print
                                   {"id","chat","quotes","backlog","notes"}; a failed source is a one-line note
  board.py digest-questions <NNN>  write digests/<NNN>/questions.md: the ## Repeated questions lines and ## Stops table
                                   computed from questions.log's last 7 days, runs/ names and trevor.md's Since: line
                                   (run after digest-trevor), print {"id","questions","stops"}
  board.py process-health <NNN>    write and print digests/<NNN>/health.json {"digest","previous","metrics"}: 10 fixed
                                   metrics for the listed jobs, each with the previous digest's value, its limit and a
                                   flag ("worse", "over twice" or null) (Digest step 1)
  board.py window-report           remember each open usage window in windows/open.json; for each one that has closed,
                                   write windows/<window>-<resets_at>.json once (points, tokens, waste, lane fit, idle)
                                   and print the scorecards written as a JSON list
  board.py review-plan <id> [--incremental]  SKILL.md Review step 2 minus the Jev gate: incremental re-review (only with
                                   --incremental) or full review, write round-N's carried-forward or UI/UX and security
                                   skip files, print {"spawn","since"} (since null = full review)
  board.py e2e-specs <id> | --worktree <dir> --base <ref> --project <file>  print {"mode","command","specs",
                                   "uncovered","trigger"}: the E2E specs the diff's UI files map to (full, scoped or none;
                                   lanes/newjob.md Check gate step 2); the <id> form adds a 10 min
                                   --global-timeout and leaves out the diff's changed spec files
  board.py related-tests <id>      print the test files a fast-lane Check gate runs for a Test that is not jest, one per
                                   line: each test_*.py or *_test.py file the diff changes, plus tests/**/test_<stem>*.py
                                   for each other changed .py file; nothing printed: run the full Test (lanes/newjob.md)
  board.py e2e-budget <id> <log>   print {"over_budget","passed","failed","not_run","slowest","line","backlog"} for a
                                   job E2E run's output; over budget with no failed test files one deduped
                                   "Speed up the slowest job E2E spec files" backlog item (lanes/newjob.md Check gate)
  board.py e2e-stopped <id> [--since <epoch>]  print {"stopped","count","reason","line"} from jobs/<id>/e2e-stopped.json, the marker
                                   serve.py's e2e_runaway_tick writes when it stops the job's E2E (lanes/newjob.md Check gate)
  board.py render-paths <id>       print {"paths","skipped"}: the app paths the diff's UI runtime files render plus spec.md
                                   `Render path:` URLs, at most 8, dynamic routes and placeholder URLs skipped, ["/"]
                                   when none maps (lanes/review.md step 2 Shared render)
  board.py ui-sweep-record <review.md>  file a UI sweep review's findings and unrendered screens as p4 Trevor backlog
                                   items and close scrum/ui-sweep.json (lanes/uisweep.md)
  board.py check-reuse <id>        print {"reused"}: copy round-(n-1)'s CHECK: PASS into round-n/check.md when HEAD equals
                                   round-(n-1)/head.txt, else null (Check gate step 1)
  board.py move-ratio <id>         print {"added","moved","ratio"}: the share of the job worktree's BASE...HEAD added lines
                                   git marks as moved (SKILL.md Review MOVE_ONLY); else exit 1 and print {"ok": false, "error"}
  board.py lane-read <part>        print one line `read: <sed -n commands>` for one part of the lane files a fast or standard
                                   job runs (`start`: lanes/newjob.md from step 2 and review.md; `merge`: merge.md from
                                   step 3), or `read: none`
  board.py lilguy-fit <id>         print {"fit","why"} (+ "read": a sed command for the lane parts a lilguy job runs, when fit): whether the job is tiny (backlog points 1 or 2, or jev.log's last model
                                   answer score < 1.5 at confidence >= 0.7, or feature.md names a file path, or names
                                   none and quotes a text or dollar amount it changes from that 1-10 repo files hold) with no
                                   hard-stop word in feature.md and an estimate (10 lines per named path) within 30
                                   lines, 10 files (SKILL.md New job step 3's Lilguy route)
  board.py claude-paths <id>       print {"paths","headless"}: the project .claude/ files spec.md's Likely files name, and
                                   whether this session is unattended (claude -p, or no claude ancestor found)
                                   (lanes/newjob.md step 3c)
  board.py claude-batch <id>       print {"batch","only","created"}: move the job's project .claude/ edits into the open
                                   "Terminal batch: project .claude edits" job (else create and park one), mark spec.md
                                   `## Moved to Terminal batch`; only = every Likely file is a .claude/ path (step 3c); on only,
                                   it also moves its dependents' `depends_on` to the batch
  board.py claude-migrate [--dry-run]  move every job parked on the old 3c question into the Terminal batch (abort an
                                   only job, stall the rest in spec), print [{"id","batch","only"}] (serve.py watchdog)
  board.py route-check <id> [--check-fails N] [--clean-start]  print {"promote","clean_round","approver_sonnet"}: the
                                   Fast or Lilguy Worktree mode promotion trigger (or null), whether a PASS round is a clean round, and
                                   whether scrum-approver gets Sonnet (SKILL.md Fast lane 1, Review 5, Approve 1)
  board.py triage-start            claim triage/<NNN>/ for the scrum-triager, print {"id","open"} (id null = backlog empty)
  board.py triage-apply <NNN>      apply triage/<NNN>/plan.json (merge/retire/manual/estimate/depends) to backlog.md (manual
                                   items move to manual-checks.md; depends adds {#id} and {needs #id} markers), write report.md
  board.py plan-apply <id> [--fix] turn a bigboy parent's plan.md into waiting child jobs, print {"children"};
                                   --fix adds the one FIX child from bigboy-review.md's ## Fix ticket
  board.py ready <id> [--specs-done]  claim the bigboy parent's startable children (stage -> spec; gated by machine_ok,
                                   free RAM per batch and the file-overlap rules), print
                                   {"ready","merged","total","in_progress","all_merged","held"}; nothing while the
                                   childSpecs mark from plan-apply/runall-start is under an hour old, unless --specs-done
                                   (BigBoy step 3) drops it first
  board.py runall-start           make a Run-all parent with every open backlog item as a waiting child (needs become
                                   depends_on; items waiting on an outside job, an {after repo:job} job, the requeue loop
                                   guard or Human setup stay open), print {"id","children"}
                                   (id null = nothing to claim); `ready <id>` then schedules them
  board.py runall-start --match <words>  the same for only the open items whose text holds every word (case-insensitive);
                                   the rest stay open, and so does a matching item that needs one of them
  board.py chain-lock <id> <holder> [--wait S]  take the bigboy parent's jobs/<id>/.chain.lock (poll 2 s, up to S,
                                   default 540; stale after 1800 s), print {"acquired","holder"}
  board.py chain-unlock <id> <holder>  remove that lock if holder holds it, print {"released"}
  board.py watchdog                flag jobs stuck 30+ min in spec/build/check/review/approve with no live session:
                                   kept in their stage with `stalled` true (reason "stalled: ..."), print {"flagged"};
                                   a stuck spec job with no feature.md is an orphaned claim: aborted and requeued, never flagged
  board.py cloud-sync              move each stage-cloud job whose [scrum <id>] PR finished (one gh REST pulls call):
                                   MERGED -> done, CLOSED -> aborted + requeued, open + scrum:needs-human -> needs-human with
                                   the PR comment's reason and a fetched worktree (a requeue:/obsolete:/looks already
                                   fixed: reason aborts it and closes the PR instead); only a same-repo scrum/<id>,
                                   scrum/<number> or scrum/<number>-<slug> head PR and its author's comments count. A
                                   moved job with no scrum-artifacts/<id> branch yet is
                                   re-checked each run and keeps its mark until cloud-home starts, or until 24 h pass
                                   with no branch; print {"moved","arrived","error"}, exit 1 on a gh error (nothing
                                   changed). serve.py runs it every 10 min while a job is in stage cloud, passing the
                                   ids whose shop session ended: such a job's open PR or pushed scrum/<id> branch is
                                   brought home as a spec stall on a local worktree (HOME); this CLI never passes any
  board.py spawn <id> <action> ["<prompt>"] [--model M]  start a detached headless `claude -p <prompt>` (default
                                   "/trevskills-scrum <action> <id>") from the repo, logging to runs/; start/resume get the
                                   Orchestrator model unless --model; set the job's runlog (ignored when <id> is not on the
                                   board), print {"log","pid"}; a board job whose session is alive (not this caller's)
                                   starts nothing and exits 1: "job <id> already has a live session (pid N)"
  board.py hook                    Claude Code hook: read one event from stdin, set or clear `waiting` on this tty's job
  board.py ops-kind <id>           print ops-data, ops-content or none: feature.md's `Kind:` line, else a stored ops kind, else
                                   Jev's one cached sort (tag_kind); New job step 1d routes an ops kind to lanes/ops.md
  board.py fable-ok <id> <planner|spec-writer>  print the Agent model override (fable) or none: the planner, or
                                   the spec-writer on lane standard (or unset), of a complex job (header `Complex: yes`
                                   in feature.md, else spec.md) gets Fable only while fable_state is ok; each such call
                                   appends a line to jobs/<id>/fable.log
  board.py spec-models <id>...     run-all: print {"<id>": "<model>"|null} per child, the spec-writer Agent override: fable-ok's
                                   model when not none, else the jev-gate.py spec-model decision (the last one in the
                                   child's jev.log, else a fresh run, 90 s each in parallel) when sonnet or opus, else null
  board.py prod-ok <id> '<bullet>'  gate one decision.md `## Prod runs` bullet: print dev or ok, else exit non-zero
                                   (schema/deploy/fixture scripts always; a :prod run without a passing dev dry run
                                   and apply recorded in jobs/<id>/prod.md)
  board.py live-record <id>        Mark done: write jobs/<id>/live-checks.json from decision.md's `## Live checks`, else
                                   spec.md's, and set the job's liveCheck; print the count (0: nothing, or already recorded)
  board.py statusline              Claude Code status line: save stdin's rate_limits to <CLAUDE_CONFIG_DIR or ~/.claude>/usage.json, print "5h N% · 7d N%"

Verdicts are never typed in by hand: sync derives them from the first line of each file, so the board can't drift
from the files. --dir points at the project's scrum/ folder (default ./scrum).
"""
import argparse, fcntl, hashlib, importlib.util, json, os, re, secrets, shlex, shutil, signal, socket, string, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter, namedtuple
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

REVIEWERS = ("security", "ux", "ui", "code")
FABLE_MODEL = "claude-fable-5-1"  # the weekly digester's override (lanes/digest.md), a full model id
FABLE_AGENT = "fable"  # fable-ok and spec-models print this: the Agent tool takes only sonnet, opus, haiku or fable (job 1461)
FABLE_WARN_5H_PCT = 65  # used % at which Fable is near its limit: fable-ok answers none, the weekly digest keeps Fable
FABLE_WARN_7D_PCT = 75
FABLE_SWITCH_5H_PCT = 80  # used % at which fable-ok answers none (frontmatter Opus) until the window resets
FABLE_SWITCH_7D_PCT = 85
STAGES = ("plan", "running", "waiting", "spec", "build", "check", "review", "approve", "merging", "deploying", "done",
          "needs-human", "aborted", "cloud")  # cloud: running in a claude.ai/code session (SKILL.md Cloud lane); never WATCHED
FIELDS = ("stage", "round", "limit", "pr", "reason", "worktree", "builder", "base", "tty", "runlog", "lane", "setup",
          "waiting", "specwriter", "cloud", "outcome", "account", "reset", "shop", "worker", "kind")  # the `waiting` field (paused on Trevor) is unrelated to the bigboy "waiting" stage
ACTIVE = ("spec", "build", "check", "review", "approve", "merging", "deploying")  # stages an interactive session can pause in
# Where the job's terminal and run log are: both are matched or read by path, so they're strict.
SHAPES = {"tty": re.compile(r"^ttys[0-9]+$"), "runlog": re.compile(r"^runs/[\w.-]+\.log$"),
          "lane": re.compile(r"^(?:fast|standard|debug|bigboy|runall|lilguy|edit|ops)$"),  # no lane key = standard
          "kind": re.compile(r"^(?:edit-(?:reel|animation|vector|photo|embroidery)|ops-data|ops-content|knowledge)$"),  # an edit or ops job's kind (edit_kind, ops_kind, lanes/edit.md, lanes/ops.md)
          "setup": re.compile(r"^(?:pending|done)$"),  # a bigboy child's Human setup wait
          "account": re.compile(r"^[a-z0-9-]{1,20}$"),  # the accounts() name board.spawn ran the session on
          "reset": re.compile(r"^[0-9]{0,12}$"),  # the account's seven_day resets_at when board.spawn recorded it: fallback_account favours the recorded account only until then
          "cloud": re.compile(r"^https://claude\.ai/code/session_[A-Za-z0-9_-]+$"),  # the dashboard links it
          "shop": re.compile(r"^[0-9]{1,10}$"),  # the shop Mac pid of a stage-cloud job's session (serve.py shop_tick)
          "worker": re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")}  # the workers.txt ssh alias that session runs on
ID_RE = re.compile(r"^\d{3,}-[a-z0-9-]+$")
# Every needs-human stop's fixed title (lanes/stops.md): key -> one-line meaning. The dashboard shows the key with
# "_" replaced by a space.
STOP_TITLES = {
    "UNCOMMITTED_CHANGES": "the main checkout or the job's worktree has files nobody committed",
    "WRONG_BRANCH": "the main checkout is on another branch, or the profile's Base branch line is malformed or missing "
                    "on origin",
    "MERGE_CONFLICT": "the branch still conflicts with the default branch after two tries",
    "CHECKS_FAILING": "tests or CI still fail after the allowed fix attempts (debug fixes included)",
    "MERGE_BLOCKED": "GitHub will not take the merge (the PR was closed, the merge or done step was refused, or the "
                     "GitHub CLI is missing or signed out)",
    "PROD_CHECK_FAILED": "the change merged, but the production deploy, a production data run or the production check "
                         "failed",
    "DATABASE_CHANGE": "the job changes the database structure, and the migrate needs an OK or it stopped",
    "PROD_APPROVAL": "the database update needs Trevor's OK before it runs on production",
    "ROUND_LIMIT": "the approver asked for a second round of fixes, and a job only gets one",
    "BUILDER_BLOCKED": "the builder, debugger or approver could not go on (blocked:, debug: blocked, Hard stop: blocked)",
    "REVIEW_ESCALATED": "the approver escalated for another reason (Hard stop: render, any other decision line, or "
                        "output that could not be read)",
    "BIGBOY_OFF_TRACK": "the tracker says the remaining tickets no longer reach the goal",
    "BIGBOY_BLOCKED": "a multi-ticket job cannot start its next ticket, because the chain lock is held or its "
                      "children are blocked",
    "DEPENDENCY": "a job this one waited on finished, was aborted or was removed",
    "MD_CONTRADICTION": "a knowledge-save job found a fact that contradicts the target .md or the code",
    "DIGEST": "a weekly digest proposal, a digest edit that failed to apply, or a pipeline-health finding",
    "TWO_SESSIONS": "two sessions were working the same job at once and the watchdog could not tell which one owns it",
    "AGENT_MISSING": "a scrum agent could not be loaded (Agent type not found), so the job stopped instead of running a stand-in agent",
    "VIDEO_REVIEW": "a video job needs Trevor to approve its storyboard or a cut, or to send notes",
    "EDIT_APPROVE": "an edit is ready: Trevor views it and approves, or sends notes",
    "CONTENT_QUESTIONS": "an ops content job needs Trevor's answers before it can write the draft",
    "CONTENT_DRAFT": "an ops content job has a draft ready for Trevor to approve or send notes on",
    "DATA_RUN": "an ops data job needs Trevor's OK before it runs on production data",
}

# The scrum commands a needs-human question's option may run (shape only: the id need not be the asked job's).
ASK_COMMAND_RE = re.compile(r'(?:(?:approve|resume|lilguy|apply) {id}|abort {id}(?: --requeue| --cascade)?|(?:rework|followup) {id} "[^"]+"'
                            r'|shell: \S.*)'
                            .format(id=ID_RE.pattern[1:-1]))
LINE_RE = re.compile(r"^(?:VERDICT|STATUS|CHECK|DECISION)?\s*:?\s*([A-Z-]+)\b", re.I)
# Scrum's only sounds: done, needs-human, and a question in a silenced session. Each is a clip in SOUNDS_DIR (not in
# the repo), or its system sound when the clip is missing.
SOUNDS_DIR = "~/.claude/trevskills-scrum/sounds"
SOUNDS = {"done": ("done.mp3", "/System/Library/Sounds/Blow.aiff"),
          "needs-human": ("needs-human.mp3", "/System/Library/Sounds/Morse.aiff"),
          "question": ("question.mp3", "/System/Library/Sounds/Funk.aiff")}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sound(kind):
    name, fallback = SOUNDS[kind]
    p = Path(SOUNDS_DIR).expanduser() / name  # checked per call, so adding or removing a clip needs no restart
    return str(p) if p.is_file() else fallback


def volume_path():
    """The dashboard's sound setting (POST /api/volume), JSON {"level": 0-100, "muted": bool}; SCRUM_VOLUME overrides."""
    return Path(os.environ.get("SCRUM_VOLUME") or Path.home() / ".claude" / "trevskills-scrum" / "volume")


def volume() -> tuple[int, bool]:
    """(level, muted) from volume_path(); a missing, unreadable or malformed file, or a bad level, is (100, False)."""
    try:
        v = json.loads(volume_path().read_text())
        level, muted = v["level"], v.get("muted")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return 100, False
    if type(level) is not int or not 0 <= level <= 100:
        return 100, False
    return level, muted is True


def play(path):
    """Fire-and-forget afplay at the dashboard's volume(); never blocks or breaks the board. SCRUM_MUTE (tests) silences it."""
    if os.environ.get("SCRUM_MUTE"):
        return
    level, muted = volume()
    if muted or not level:
        return
    try:
        subprocess.Popen(["afplay", "-v", str(level / 100), path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def notifier_disabled():
    """Same test as isDisabled in ~/.claude/hooks/_lib/config.js (the Claude Notifier)."""
    v = os.environ.get("CLAUDE_NOTIFIER_DISABLE")
    return bool(v) and v != "0" and v.lower() != "false"


def first_word(path, allowed):
    """Verdict word on the first non-blank line. None = file missing, 'INVALID' = present but unreadable."""
    path = Path(path)
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = re.sub(r"[*#_`>]+", " ", line).strip()
        if line:
            m = LINE_RE.match(line)
            word = m.group(1).upper() if m else ""
            return word if word in allowed else "INVALID"
    return "INVALID"


def read_board(root):
    """board.json as a dict (empty board when missing). Needs no lock: writers replace the file atomically."""
    path = Path(root) / "board.json"
    try:
        return json.loads(path.read_text()) if path.exists() else {"jobs": []}
    except json.JSONDecodeError as e:
        raise SystemExit(f"board.json is not valid JSON ({e}); fix or move it aside, it was not touched")


@contextmanager
def locked_board(root):
    """Exclusive lock across processes; writes only if the body didn't raise; atomic replace."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".board.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "board.json"
        board = read_board(root)
        migrate_paused(board)
        clear_heavy_wait(board)
        yield board
        for job in board["jobs"]:  # a question lives only while its job waits on Trevor, whoever moved it on
            if job.get("stage") != "needs-human":
                job.pop("question", None)
                job.pop("options", None)
                job.pop("recommend", None)
                job.pop("stopTitle", None)
        tmp = path.with_name("board.json.tmp")
        tmp.write_text(json.dumps(board, indent=2) + "\n")
        os.replace(tmp, path)


def check_id(job_id):
    if not ID_RE.match(job_id):
        raise SystemExit(f"bad job id {job_id!r}")
    return job_id


def find(board, job_id):
    for job in board["jobs"]:
        if job["id"] == job_id:
            return job
    raise SystemExit(f"no job {job_id!r} on the board")


def live(board, job_id, unpause=False):
    """find() for the orchestrator: an aborted job refuses every further write, so a running session stops. So does a
    paused one, unless this write un-pauses it (unpause)."""
    job = find(board, job_id)
    if job["stage"] == "aborted":
        raise SystemExit(f"job {job_id} was aborted by Trevor; stop working on it")
    if not unpause and job.get("paused"):
        raise SystemExit(f"job {job_id} was paused by Trevor; stop working on it")
    return job


def slug(title):
    title = re.sub(r"\[screenshot:[^\]]*\]", " ", title, flags=re.I)  # the path would become the id
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "job"


def short_title(text, n=60) -> str:
    """text when it fits in n chars, else cut at the last space in the first n-1 chars (trailing spaces and punctuation
    stripped) plus "…"; with no such space, the first n-1 chars plus "…". Never longer than n."""
    if len(text) <= n:
        return text
    head = text[:n - 1]
    cut = head[:head.rfind(" ")].rstrip(" " + string.punctuation) if " " in head else ""
    return (cut or head) + "…"


STARTED_BY = ("serve", "runall", "wake", "hand", "shop", "digest")  # a job's started_by: who started it (write_pulse's cool-down claims skip hand, shop and digest)


def add_job(root, board, title, job_id=None, started_by="hand"):
    """Caller must hold the board lock. job_id keeps an id given elsewhere (a cloud job keeps its local board's id).
    started_by (STARTED_BY) records who started the job."""
    jobs_dir = Path(root) / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    names = [p.name for p in jobs_dir.iterdir()] + [j.get("id", "") for j in board["jobs"]]
    if job_id is None:
        nums = [int(m.group(1)) for name in names if (m := re.match(r"(\d+)-", name))]
        job_id = f"{max(nums, default=0) + 1:03d}-{slug(title)}"
    elif check_id(job_id) in names:
        raise SystemExit(f"job {job_id!r} already exists")
    (jobs_dir / job_id).mkdir()
    board["jobs"].append({
        "id": job_id, "title": title, "branch": f"scrum/{job_id}", "stage": "spec", "round": 0, "limit": 2,
        "reviews": {r: "pending" for r in REVIEWERS}, "rounds": [], "files": [],
        "pr": None, "reason": None, "worktree": None, "builder": None, "base": None, "updatedAt": now(),
        "started_by": started_by,
    })
    return job_id


def cmd_new(root, title, job_id=None, unique=False, started_by="hand", refuse=False):
    """unique: return None, adding nothing, while a job with this exact title is neither done nor aborted. refuse (the
    CLI `new` without --id, job 1414): raise SystemExit naming that open job's id and stage instead, writing nothing."""
    with locked_board(root) as board:
        twin = (unique or refuse) and next((j for j in board["jobs"] if j.get("title") == title
                                            and j.get("stage") not in ("done", "aborted")), None)
        if twin and refuse:
            raise SystemExit(f"job {twin['id']} (in {twin['stage']}) already has the title {title!r}: "
                             "work on that job, or give this one a different title")
        if twin and unique:
            return None
        return add_job(root, board, title, job_id, started_by)


# --- backlog.md: "- [ ] [5] Text {#k3f9} {p:4} {needs #a1b2} {setup: step; step} {after repo:1600} {by:t} → 003-id <!-- why -->";
# points, the id, priority (1-5, highest claimed first), needs, setup, after and source markers, the job and the estimate's
# reason are optional. The source marker is {by:t} (Trevor's item) or {by:back} (Trevor's, back of the backlog); no marker means an agent item.
# An item's text excludes the markers, so its spec_path never changes. A setup marker is a Human setup checklist: next and runall-start skip the item until Setup done.
# An after marker names jobs on other registered repos' boards (repo:job, space-separated): next, cloud-claim and runall-start skip the item until each is done. ---
FIB = (1, 2, 3, 5, 8, 13)
AFTER_REF = r"[\w./-]+:\d+(?:-[a-z0-9-]+)?"  # one {after} ref: a registered repo's folder or dashboard name, then a job number or id
ITEM_RE = re.compile(r"^- \[( |x)\] (?:\[(\d+|\?)\] )?(.*?)(?: \{#([a-z0-9]{4})\})?(?: \{p:([1-5])\})?(?: \{needs((?: #[a-z0-9]{4})+)\})?"
                     r"(?: \{setup: ([^{}]*)\})?(?: \{after((?: " + AFTER_REF + r")+)\})?(?: \{by:(t|back)\})?(?: → (\d{3,}-[a-z0-9-]+))?(?: <!-- (.*?) -->)?\s*$")
ID_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
KEEP = object()
ITEM_MAX = 2000  # backlog item text; long enough that a triage merge keeps every original requirement


def clean(text, limit=300):
    return re.sub(r"\s+", " ", str(text).replace("<!--", "").replace("-->", "")).strip()[:limit]


LOOSE_MARK_RE = re.compile(r" \{(?:#[a-z0-9]{4}|p:[1-5]|needs(?: #[a-z0-9]{4})+|setup: [^{}]*|after(?: " + AFTER_REF + r")+|by:(?:t|back))\}| → \d{3,}-[a-z0-9-]+")
LOOSE_WHY_RE = re.compile(r" <!-- (.*?) -->")


def loose_item(line):
    """ITEM_RE's groups for a backlog line, with the markers in any order: the text ends at the first well-formed marker
    (or the trailing estimate comment) when only markers follow it, else ITEM_RE decides, so prose that mentions marker
    syntax stays text. A repeated {p:N} keeps the lowest N; repeated needs or after markers join. None when it is not an item line."""
    m = re.match(r"^- \[( |x)\] (?:\[(\d+|\?)\] )?(.*)$", line)
    if not m:
        return None
    rest = m[3]
    # the estimate comment is the first one with only markers after it, wherever it sits; markers inside it are not markers
    why = next((w for w in LOOSE_WHY_RE.finditer(rest) if not LOOSE_MARK_RE.sub("", rest[w.end():]).strip()), None)
    body = rest[:why.start()] + rest[why.end():] if why else rest
    cut = LOOSE_MARK_RE.search(body)
    text, tail = (body[:cut.start()], body[cut.start():]) if cut else (body, "")
    if LOOSE_MARK_RE.sub("", tail).strip():
        return g.groups() if (g := ITEM_RE.match(line)) else None  # prose after a marker-like mention: the text keeps it
    one = lambda pat: (re.search(pat, tail) or [None, None])[1]
    prios = re.findall(r" \{p:([1-5])\}", tail)
    needs = "".join(re.findall(r" \{needs((?: #[a-z0-9]{4})+)\}", tail))
    after = "".join(re.findall(r" \{after((?: " + AFTER_REF + r")+)\}", tail))
    return (m[1], m[2], text, one(r" \{#([a-z0-9]{4})\}"), min(prios) if prios else None, needs or None,
            one(r" \{setup: ([^{}]*)\}"), after or None, one(r" \{by:(t|back)\}"), (re.search(r" → (\d{3,}-[a-z0-9-]+)", re.sub(r" \{setup: [^{}]*\}", "", tail)) or [None, None])[1], why[1] if why else None)


def read_backlog(root):
    """(lines, items). Items remember their line so writes leave headings and notes alone."""
    path = Path(root) / "backlog.md"
    lines = path.read_text().splitlines() if path.exists() else ["# Backlog"]
    items = []
    for n, line in enumerate(lines):
        if g := loose_item(line):
            done, pts, text, item_id, prio, needs, setup, after, by, job, why = g
            items.append({"index": len(items), "line": n, "done": done == "x",
                          "points": int(pts) if pts and pts.isdigit() else None, "text": text.strip(), "why": why, "job": job,
                          "id": item_id, "priority": int(prio) if prio else None, "needs": needs.replace("#", "").split() if needs else [],
                          "setup": [s.strip() for s in setup.split(";") if s.strip()] if setup else [],
                          "after": list(dict.fromkeys(after.split())) if after else [], "by": by})
    return lines, items


def format_item(item):
    return (f"- [{'x' if item['done'] else ' '}] " + (f"[{item['points']}] " if item["points"] else "") + item["text"]
            + (f" {{#{item['id']}}}" if item.get("id") else "")
            + (f" {{p:{item['priority']}}}" if item.get("priority") else "")
            + (" {needs " + " ".join(f"#{n}" for n in item["needs"]) + "}" if item.get("needs") else "")
            + (" {setup: " + "; ".join(item["setup"]) + "}" if item.get("setup") else "")
            + (" {after " + " ".join(item["after"]) + "}" if item.get("after") else "")
            + (f" {{by:{item['by']}}}" if item.get("by") else "")
            + (f" → {item['job']}" if item["job"] else "") + (f" <!-- {item['why']} -->" if item["why"] else ""))


def new_item_id(items):
    """4 random [a-z0-9] chars that no item in `items` carries as its id."""
    taken = {i.get("id") for i in items}
    while (new := "".join(secrets.choice(ID_CHARS) for _ in range(4))) in taken:
        pass
    return new


def waiting_on(item, items, board):
    """What still blocks item, in this order. First the ids in its needs whose line is open, or is claimed by a job whose
    board stage is not done or aborted (an id no line carries, a closed line with no job, or a job missing from the board
    does not block). Then each {after repo:job} ref that after_blocks, as written. Then REQUEUE_LOOP while requeue_loop
    holds it. wait_label names each one."""
    out = []
    if item["needs"]:  # most items: skip building the board's stage map
        stage = {j.get("id"): j.get("stage") for j in board.get("jobs") or []}
        blocks = lambda i: not i["done"] or (i["job"] in stage and stage[i["job"]] not in ("done", "aborted"))
        out = [n for n in item["needs"] if any(i["id"] == n and blocks(i) for i in items)]
    return out + [a for a in item.get("after") or [] if after_blocks(a)] + requeue_loop(item, board)


def after_blocks(ref):
    """False only once the job a cross-repo {after repo:job} ref names is done on its own board. repo is a registered
    project's folder or dashboard name (projects(), any case); job is its full id, or a number equal to the id's leading
    number. An unregistered repo, an unreadable board, a job that board does not list, or one in any other stage (aborted
    too: what the item waits on never landed) blocks, so a typo shows on the dashboard instead of claiming early."""
    repo, _, job = ref.rpartition(":")
    path = next((p for name, p in projects().items() if repo.casefold() in (name.casefold(), p.name.casefold())), None)
    if path is None:
        return True
    try:
        jobs = read_board(path / "scrum").get("jobs") or []
    except (SystemExit, OSError, AttributeError):  # read_board exits on bad JSON; a non-dict board has no .get
        return True
    num = lambda i: int(m[1]) if (m := re.match(r"(\d+)(?:-|$)", str(i))) else None
    same = (lambda i: i == job) if "-" in job else (lambda i: num(i) == int(job))
    return not any(isinstance(j, dict) and same(j.get("id")) and j.get("stage") == "done" for j in jobs)


LOOP_CLAIMS, LOOP_HOURS = 3, 24  # requeue_loop: this many requeue aborts in a row, spanning at most this many hours, hold an item
REQUEUE_LOOP = "requeue loop"  # requeue_loop's waits entry; wait_label and the dashboard's needsTag name it


def requeue_loop(item, board):
    """[REQUEUE_LOOP] while an open item's last LOOP_CLAIMS claims were all requeue aborts within LOOP_HOURS, else [].
    Its claims are the board jobs titled short_title of its text, in board order. All of them must be aborted with a
    "requeue:" reason, their updatedAt span at most LOOP_HOURS, and the newest must have put back this very line (its
    `requeued` equals item_key(item)). There is no expiry: it holds until Trevor edits the text or adds a needs or after
    marker, which changes item_key. A newest job from before requeue_job recorded `requeued` never holds."""
    if item["done"]:
        return []
    title = short_title(item["text"])
    last = [j for j in board.get("jobs") or [] if isinstance(j, dict) and j.get("title") == title][-LOOP_CLAIMS:]
    if len(last) < LOOP_CLAIMS or last[-1].get("requeued") != item_key(item) \
            or not all(j.get("stage") == "aborted" and str(j.get("reason") or "").startswith("requeue:") for j in last):
        return []
    try:
        at = [datetime.fromisoformat(j["updatedAt"]) for j in last]
        return [REQUEUE_LOOP] if max(at) - min(at) <= timedelta(hours=LOOP_HOURS) else []
    except (KeyError, TypeError, ValueError):  # a missing or unreadable time, or naive and aware ones mixed
        return []


def wait_label(wait):
    """One waiting_on entry as words: #<id> for a needs id, "<repo> job <job>" for an after ref, and what to do for
    REQUEUE_LOOP."""
    if wait == REQUEUE_LOOP:
        return f"an edit: its last {LOOP_CLAIMS} claims were requeue aborts within {LOOP_HOURS} h"
    repo, colon, job = wait.rpartition(":")
    return f"{repo} job {job}" if colon else f"#{wait}"


def origin_open(item, board):
    """The id in the trailing " (from <id>)" of item's text when that board job exists and is not done or aborted, else None.
    A follow-up waits for its origin to merge; a missing, done or aborted origin does not block."""
    m = re.search(r"[ \t]\(from (\d+-[\w-]+)\)\s*\Z", item["text"])
    if m and any(j.get("id") == m[1] and j.get("stage") not in ("done", "aborted") for j in board.get("jobs") or []):
        return m[1]
    return None


def setup_steps(raw):
    """A Human setup checklist "step; step" as its list of steps: split on ";", braces removed, trimmed, empties dropped.
    Raises when no step is left or the checklist would not fit on one backlog line."""
    steps = [s for s in (clean(part.replace("{", "").replace("}", ""), None) for part in str(raw or "").split(";")) if s]
    if not steps:
        raise SystemExit("setup checklist is empty")
    if len("; ".join(steps)) > ITEM_MAX:
        raise SystemExit(f"setup checklist is longer than {ITEM_MAX} characters")
    return steps


def write_backlog(root, lines):
    (Path(root) / "backlog.md").write_text("\n".join(lines) + "\n")


def backlog_items(root):
    items = read_backlog(root)[1]
    try:
        board = read_board(root)
    except SystemExit:  # a broken board.json must not break the backlog list; waits then only counts open lines
        board = {"jobs": []}
    return [{k: v for k, v in item.items() if k != "line"} | {"waits": waiting_on(item, items, board)} for item in items]


def pick(items, index):
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
        raise SystemExit(f"no backlog item {index!r}")
    return items[index]


FLAG_HINT = 'flags go before -- (backlog-add --priority 3 -- "item text")'


def flag_item(text) -> bool:
    """A backlog item whose cleaned text starts with `--` is a flag passed as the item (job 1414: argparse keeps a quoted
    "--priority 3" as a positional, and cmd_next claimed that line as a job four times); it is never saved or claimed."""
    return clean(text, ITEM_MAX).startswith("--")


def check_priority(priority):
    if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 5):
        raise SystemExit(f"priority must be 1-5 or null, got {priority!r}")


def priority_key(item) -> float:
    """sorted() key: highest priority first, unmarked items between p2 and p3; sorted is stable, so ties keep file order."""
    return -(item.get("priority") or 2.5)


def source_priority(by, n, critical=False, current=None):
    """The priority an item may hold given its source: a back item 1; Trevor's item 4, or 5 when n or current is 5;
    an agent item min(n, 3) (None stays None), or 5 when critical (the lane passes that after jev-gate.py critical)."""
    if by == "back":
        return 1
    if by == "t":
        return 5 if 5 in (n, current) else 4
    return 5 if critical else None if n is None else min(n, 3)


def check_source(by, priority, top, critical):
    """Refuse the add flags that cannot go together."""
    if top and priority is not None:
        raise SystemExit("--top and --priority cannot be combined")
    if by == "back" and (top or priority is not None):
        raise SystemExit("--back cannot be combined with --top or --priority")
    if critical and (by or top):
        raise SystemExit("--critical is only for agent items")


def check_points(points):
    if points is not None and (isinstance(points, bool) or points not in FIB):
        raise SystemExit(f"points must be one of {FIB} or null, got {points!r}")


def backlog_op(root, op, index=None, text=None, points=KEEP, delta=0, setup=None, to=None, priority=None, top=False,
               by=None, critical=False, unless_open=None, id=None):
    """add / edit / delete / move / setup-done / priority one backlog item under the board lock. Returns the new item list.
    add with unless_open writes nothing and returns None when an open item's text contains it.
    add's setup ("step; step") parks the new item behind a Human setup checklist; setup-done removes that marker.
    add with top inserts the item above the first item line with {p:5}, so next claims it first (newest top wins).
    add's by ("t", "back" or None = agent; top implies "t") and critical set the priority through source_priority.
    priority finds the open item by its {#id} on the freshly read file and only raises: it writes {p:priority} when that is
    above the current priority (unmarked counts as 2.5, as priority_key does), else changes nothing.
    add's id (4 [a-z0-9] chars the caller already told someone) is used instead of a fresh one."""
    with locked_board(root):
        lines, items = read_backlog(root)
        if op == "add":
            if not clean(text or ""):
                raise SystemExit("backlog item text is empty")
            if unless_open and any(unless_open in i["text"] for i in items if not i["done"]):
                return None
            if points is not KEEP:
                check_points(points)
            check_priority(priority)
            check_source(by, priority, top, critical)
            by = "t" if top else by
            line = format_item({"done": False, "points": None if points is KEEP else points,
                                "priority": source_priority(by, 5 if top else priority, critical),
                                "text": clean(text, ITEM_MAX), "job": None, "why": None,
                                "setup": None if setup is None else setup_steps(setup), "by": by, "id": id or new_item_id(items)})
            if top and items:
                lines.insert(items[0]["line"], line)
            else:
                lines.append(line)
        elif op == "edit":
            item = pick(items, index)
            old = item["text"]
            if text is not None:
                if not clean(text):
                    raise SystemExit("backlog item text is empty")
                item["text"] = clean(text, ITEM_MAX)
            if points is not KEEP:
                check_points(points)
                item["points"] = points
            lines[item["line"]] = format_item(item)
            if item["text"] != old:
                drop_spec(root, old, items)
        elif op == "delete":
            item = pick(items, index)
            del lines[item["line"]]
            drop_spec(root, item["text"], [i for i in items if i is not item])
        elif op == "move" and to is not None:
            # Take item `to`'s place: lands after it when moving down, before it when moving up (top, bottom, drag).
            a, b = pick(items, index), pick(items, to)
            lines.insert(b["line"], lines.pop(a["line"]))
        elif op == "move":
            a = pick(items, index)
            # Swap with the nearest open item that way; finished items are hidden in the dashboard.
            step = range(index - 1, -1, -1) if delta == -1 else range(index + 1, len(items)) if delta == 1 else []
            b = next((items[j] for j in step if not items[j]["done"]), None)
            if b:
                lines[a["line"]], lines[b["line"]] = lines[b["line"]], lines[a["line"]]
        elif op == "setup-done":
            item = pick(items, index)
            if item["done"] or not item["setup"]:
                raise SystemExit(f"backlog item {index} has no Human setup")
            line = lines[item["line"]]
            if (ITEM_RE.match(line) or [None] * 4)[3] != item["text"]:
                line = format_item(item)  # out-of-order markers: rewrite in order first
            m = ITEM_RE.match(line)  # cut just the marker, so the rest of the line stays byte for byte
            lines[item["line"]] = line[:m.start(7) - len(" {setup: ")] + line[m.end(7) + 1:]
        elif op == "priority":
            if priority is None:
                raise SystemExit("priority must be 1-5")
            check_priority(priority)
            item = next((i for i in items if isinstance(id, str) and i["id"] == id and not i["done"]), None)
            if item is None:
                raise SystemExit(f"no open backlog item with id {id!r}")
            if -priority >= priority_key(item):
                return backlog_items(root)
            line = lines[item["line"]]
            if (ITEM_RE.match(line) or [None] * 4)[3] != item["text"]:
                line = format_item(item)  # out-of-order markers: rewrite in order first
            m = ITEM_RE.match(line)  # splice just the marker, so the rest of the line stays byte for byte
            start, end = m.span(5) if m.group(5) else (m.end(4) + 1, m.end(4) + 1)  # after the "}" of {#id}
            lines[item["line"]] = line[:start] + (str(priority) if m.group(5) else f" {{p:{priority}}}") + line[end:]
        else:
            raise SystemExit(f"unknown backlog op {op!r}")
        write_backlog(root, lines)
    return backlog_items(root)


def backlog_set_estimate(root, text, points, why):
    """Fill in the AI estimate for the first open, unestimated item with this text. False if it's gone or set."""
    check_points(points)
    with locked_board(root):
        lines, items = read_backlog(root)
        for item in items:
            if not item["done"] and item["points"] is None and item["text"] == text:
                item["points"], item["why"] = points, clean(why or "") or None
                lines[item["line"]] = format_item(item)
                write_backlog(root, lines)
                return True
    return False


def jev_gate():
    """jev-gate.py as a module: its name has a hyphen, so no plain import."""
    spec = importlib.util.spec_from_file_location("jev_gate", Path(__file__).resolve().with_name("jev-gate.py"))
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def cmd_rank_backlog(root, all_items=False) -> dict:
    """Rate open backlog items with jev-gate's rank step (unmarked ones, or every one with all_items) outside the lock,
    plus its critical step for an agent item whose text starts with "Critical:"; back items get no Jev call. Then, under
    one lock, re-read backlog.md and write source_priority on the first open item with the same text and source (and
    still unmarked without all_items), only when it changed. A none rank, or an item gone or edited meanwhile, is left
    byte for byte."""
    gate = jev_gate()
    log = Path(root) / "jev.log"
    items = [i for i in read_backlog(root)[1] if not i["done"]]
    picked = [i for i in items if all_items or i["priority"] is None]
    todo = [(i["text"], i["by"]) for i in picked if i["by"] != "back"]

    def rate(text, by):
        decision = gate.run("rank", lambda asked: gate.rank_ticket(text, Path(root), asked), log)
        if not (m := re.fullmatch(r"p([1-5]) \S+", decision)):
            return None
        critical = by is None and text.startswith("Critical:") and gate.run(
            "critical", lambda asked: gate.critical_ticket(text, asked), log) == "critical"
        return int(m[1]), critical

    with ThreadPoolExecutor(max_workers=8 if all_items else 1) as pool:  # 1 worker keeps the one-off run in file order
        ranks = list(pool.map(lambda t: rate(*t), todo))
    rated = [(text, by, r) for (text, by), r in zip(todo, ranks) if r]
    rated += [(i["text"], "back", None) for i in picked if i["by"] == "back"]
    written = 0
    if rated:
        with locked_board(root):
            lines, now_items = read_backlog(root)
            used, changed = set(), False
            for text, by, r in rated:
                item = next((i for i in now_items if not i["done"] and i["index"] not in used and i["text"] == text
                             and i["by"] == by and (all_items or i["priority"] is None)), None)
                if item is None:
                    continue
                used.add(item["index"])
                written += by != "back"
                n, critical = r or (None, False)
                new = source_priority(by, n, critical, item["priority"])
                if new != item["priority"]:
                    item["priority"] = new
                    lines[item["line"]] = format_item(item)
                    changed = True
            if changed:
                write_backlog(root, lines)
    return {"rated": written, "unrated": len(todo) - written, "skipped": len(items) - len(todo)}


def text_key(text):
    """The first 12 hex chars of text's sha1: spec_path's file name and item_key's value."""
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def item_key(item):
    """text_key of a backlog item's text plus its needs and after markers: what Trevor's edit changes, while an
    estimate, a priority or Setup done does not. requeue_job records it as `requeued`; requeue_loop compares it."""
    return text_key(" ".join([item["text"], *(f"#{n}" for n in item.get("needs") or []), *(item.get("after") or [])]))


def spec_path(root, text):
    """Where a backlog item's pre-written spec waits, keyed by its stored text."""
    return Path(root) / "backlog-specs" / (text_key(text) + ".md")


def drop_spec(root, text, items):
    """Delete the item's pre-written spec unless an open item in `items` (the list after the change) still has this
    text. A missing file or folder is a no-op. Caller holds the lock."""
    if not any(not i["done"] and i["text"] == text for i in items):
        spec_path(root, text).unlink(missing_ok=True)


def take_spec(root, text, job_id):
    """Move the item's pre-written spec, if any, to the new job's spec.md. Caller holds the lock."""
    src = spec_path(root, text)
    if src.is_file():
        os.replace(src, Path(root) / "jobs" / job_id / "spec.md")


E2E_FULL_MAIN = "E2E full suite on main"


def e2e_full_duplicate(board, jobs_dir, text, job_id):
    """The id of another live board job (not job_id, nor job_id's parent; stage not done or aborted) whose title or
    feature.md names a spec path in text, when text starts with E2E_FULL_MAIN (a trailing `:<line>` ignored); else
    None. The same test as serve.py e2e_full_owned, run at claim time (job 1301). Caller holds the lock."""
    text = str(text or "").lstrip()
    if not text.startswith(E2E_FULL_MAIN):
        return None
    specs = set(re.findall(r"e2e/\S+?\.spec\.ts", text))
    if not specs:
        return None
    jobs = [j for j in board.get("jobs") or [] if isinstance(j, dict)]
    parent = next((j.get("parent") for j in jobs if j.get("id") == job_id), None)
    for job in jobs:
        if job.get("id") in (job_id, parent) or job.get("stage") in ("done", "aborted"):
            continue
        seen = str(job.get("title") or "")
        try:
            seen += "\n" + (Path(jobs_dir) / str(job.get("id")) / "feature.md").read_text(errors="replace")
        except OSError:
            pass
        if any(spec in seen for spec in specs):
            return job.get("id")
    return None


def claim_item(lines, item, job_id):
    """Mark one backlog item claimed by job_id in lines. Caller holds the lock and writes the backlog once."""
    item["done"], item["job"] = True, job_id
    lines[item["line"]] = format_item(item)


def cmd_next(root, index=None, shop=None):
    """Claim the highest-priority open backlog item (or item `index`) as a new job, under the lock, so no two sessions share one.
    Cool-down refuses the automatic claim (no index), and so does finish_first; an explicit index is Trevor's Run now
    and still claims. `shop` (serve.py's shop_tick, a claim for the shop Mac) is a predicate the automatic pick must
    also pass; neither cool-down nor finish_first refuses it (the shop runs on its own CPU and e2e.lock), and the job is started_by shop.
    Without `shop` and index, while heavy_cap_reason(root) holds, a heavy line (heavy_job) is skipped for the shop Mac (job 1314)."""
    if index is None and shop is None and cooling_down():
        raise SystemExit(COOLING_CLAIM)
    if index is None and shop is None and (soft := soft_cap_reason()):
        raise SystemExit(f"{soft}: no new backlog claim.")
    if index is None and shop is None and (hold := finish_first(root)):
        raise SystemExit(f"{hold}: no new backlog claim. It claims again once that job moves on.")
    with locked_board(root) as board:
        lines, items = read_backlog(root)
        capped = index is None and shop is None and heavy_cap_reason(root)  # job 1314: heavy lines wait for the shop Mac
        if index is None:
            item = next((i for i in sorted(items, key=priority_key) if not i["done"] and not i["setup"] and not flag_item(i["text"])
                         and not waiting_on(i, items, board) and not origin_open(i, board)
                         and (shop is None or shop(i)) and not (capped and heavy_job(root, i))), None)
            if item is None:
                return {"id": None, "feature": None}
        else:
            item = pick(items, index)
            if item["done"]:
                raise SystemExit(f"backlog item {index} is already claimed")
            if flag_item(item["text"]):
                raise SystemExit(f"backlog item {index} is only a flag ({item['text']!r}), not work: {FLAG_HINT}")
            if item["setup"]:
                raise SystemExit(f"backlog item {index} waits on Human setup")
            if waits := waiting_on(item, items, board):
                raise SystemExit(f"backlog item {index} waits on " + ", ".join(map(wait_label, waits)))
            if origin := origin_open(item, board):
                raise SystemExit(f"backlog item {index} waits on job {origin}")
        job_id = add_job(root, board, short_title(item["text"]),
                         started_by="hand" if index is not None else "runall" if shop is None else "shop")
        take_spec(root, item["text"], job_id)
        claim_item(lines, item, job_id)
        write_backlog(root, lines)
        if twin := e2e_full_duplicate(board, Path(root) / "jobs", item["text"], job_id):
            abort_job(root, find(board, job_id), False, f"duplicate of {twin}")  # job 1301: the line stays claimed
            return {"id": None, "feature": None}
        return {"id": job_id, "feature": item["text"], "points": item["points"]}


def cmd_cloud_claim(root, n) -> dict:
    """Claim up to n open backlog items for cloud sessions, in priority order (priority_key), under one lock and one backlog write.
    An item is skipped (left open) when it waits (waiting_on: a needs or after marker, or the requeue loop guard) or on Human
    setup, has no pre-written spec with readable Likely files,
    or shares a Likely file with an item claimed in this call or with a board job in stage cloud or build, or in stage spec
    carrying cloudClaim (claimed here, not yet moved to cloud). Such a job with no readable Likely files may touch
    anything, so it blocks every item."""
    if n < 1:
        raise SystemExit("N must be at least 1")
    if cooling_down() or soft_cap_reason():  # cool-down (and soft cool down at its cap): no new backlog claim
        return {"claimed": []}
    with locked_board(root) as board:
        lines, items = read_backlog(root)
        taken, blocked_all = set(), False
        for job in board["jobs"]:
            if job.get("stage") in ("cloud", "build") or (job.get("stage") == "spec" and job.get("cloudClaim")):
                spec = Path(root) / "jobs" / job.get("id", "") / "spec.md"
                files = likely_files(spec.read_text(encoding="utf-8")) if spec.is_file() else set()
                blocked_all |= not files
                taken |= files
        claimed = []
        for item in sorted(items, key=priority_key):
            if blocked_all or len(claimed) >= n:
                break
            if item["done"] or item["setup"] or waiting_on(item, items, board) or origin_open(item, board):
                continue
            spec = spec_path(root, item["text"])
            files = likely_files(spec.read_text(encoding="utf-8")) if spec.is_file() else set()
            if not files or files & taken:
                continue
            job_id = add_job(root, board, short_title(item["text"]), started_by="serve")
            board["jobs"][-1]["cloudClaim"] = True  # keeps its files reserved until the dispatcher moves it to stage cloud
            take_spec(root, item["text"], job_id)
            claim_item(lines, item, job_id)
            taken |= files
            claimed.append({"id": job_id, "feature": item["text"]})
        if claimed:
            write_backlog(root, lines)
        return {"claimed": claimed}


def cmd_abort(root, job_id, requeue, reason=None, cascade=False):
    """Mark a job aborted (terminal). Optionally put its full feature text back on the backlog as an open item.
    With cascade, also abort every waiting, needs-human, paused or play-queued job that depends_on an aborted one,
    transitively (a Run-all child is requeued). Returns the aborted ids, the root first."""
    with locked_board(root) as board:
        job = find(board, check_id(job_id))
        if job["stage"] in ("done", "aborted"):
            raise SystemExit(f"job {job_id} is already {job['stage']}")
        abort_job(root, job, requeue, reason or f"Aborted by Trevor {now()}")
        aborted = [job_id]
        if cascade:
            for gone in aborted:  # grows while it runs: each aborted dependent is followed in turn
                for kid in board["jobs"]:
                    if gone in (kid.get("depends_on") or []) and kid["stage"] not in ("done", "aborted") \
                            and (kid["stage"] in ("waiting", "needs-human") or kid.get("paused") or kid.get("play_queued")
                                 or stalled(kid)):
                        abort_job(root, kid, runall_child(board, kid), f"Removed with {job_id}")
                        aborted.append(kid["id"])
    return aborted


def runall_child(board, job) -> bool:
    """True when job's parent on board is a Run-all job (lane runall); no parent, or one missing from the board, is
    False. Caller holds the board lock."""
    parent = job.get("parent")
    return bool(parent) and any(j["id"] == parent and j.get("lane") == "runall" for j in board["jobs"])


def abort_job(root, job, requeue, reason):
    """cmd_abort's body; caller holds the lock. With no feature.md (a claim whose session died before writing it),
    the requeue reopens the claimed backlog line in place, points, id, needs and pre-written spec kept."""
    folder = Path(root) / "jobs" / job["id"]
    feature = folder / "feature.md"
    job.update(stage="aborted", reason=reason, updatedAt=now())
    job.pop("paused", None)  # an aborted job is never played
    job.pop("play_queued", None)  # nor started by serve.py's Play queue
    job.pop("play_queued_manual", None)
    job.pop("queued_launch", None)
    job.pop("ram_hold", None)
    job.pop("machine_hold", None)  # job 1540: never a stale machine_ok reason on an aborted card
    if requeue:
        requeue_job(root, job, folder, feature)
    job["files"] = job_files(folder)  # after the spec move, so it never names a file that left the folder


def requeue_after(root, job):
    """{after <repo>:<job>} refs for a `requeue: depends on jobs 1362-1365, not merged` reason: one per job on this board
    (not job itself) that is not done and whose number or full id the reason names after `job` or `jobs` (a comma or `and` list); a `1362-1365` range names every number
    from 1362 to 1365 (at most 20 apart). [] for any other reason. Caller holds the lock."""
    reason = str(job.get("reason") or "")
    if not reason.startswith("requeue:"):
        return []
    named, repo = job_refs(reason), Path(root).resolve().parent.name
    return [f"{repo}:{j['id']}" for j in read_board(root).get("jobs") or []
            if j.get("id") != job["id"] and j.get("stage") != "done" and names_job(named, j.get("id"))]


def job_refs(text):
    """The job numbers (ints) and full ids text names after `job` or `jobs` (a comma or `and` list; a `1362-1365` range
    names every number from 1362 to 1365, at most 20 apart). Never a number elsewhere, such as `after 5 minutes`."""
    named = set()
    ref = r"\d+(?:-[a-z0-9-]*[a-z0-9])?"
    cued = re.findall(rf"\bjobs?\s+({ref}(?:(?:,\s*|\s+and\s+){ref})*)", text)
    for tok in re.findall(ref, " ".join(cued)):
        if m := re.fullmatch(r"(\d+)-(\d+)", tok):
            lo, hi = int(m[1]), int(m[2])
            named.update(range(lo, hi + 1) if lo <= hi <= lo + 20 else (lo, hi))
        else:
            named.add(int(tok) if tok.isdigit() else tok)
    return named


def names_job(named, job_id):
    """True when job_refs' set names job_id by full id or by its leading number."""
    m = re.match(r"(\d+)(?:-|$)", str(job_id))
    return job_id in named or (m is not None and int(m[1]) in named)


MAIN_MAC_RE = re.compile(r"\bmain\s+mac\b", re.I)  # a requeue reason that wants this Mac, not the shop (jobs 1507, 1513)
REQUEUE_MARKS = ("priority", "by", "needs", "setup")  # the claimed line's markers a new requeue line keeps; never its id


def requeue_job(root, job, folder, feature):
    """Put an aborted job's item back on the backlog: its claimed line reopened in place when there is no feature.md,
    else a new line with feature.md's text (the title with neither) and the claimed line's REQUEUE_MARKS when there is
    one (its id stays on the done line). Caller holds the lock. job["requeued"] records the
    item_key of the line put back, as the next read parses it, for requeue_loop. A `requeue: depends on jobs ...`
    reason adds an {after <repo>:<job>} marker for each named job on this board that is not done (requeue_after).
    A shop job (a `shop` field) whose reason names the main Mac (MAIN_MAC_RE, any case) gets a new line ending
    ` Runs on: main.`, which serve.py shop_tick's fits skips, unless its text already reads Runs on main there."""
    lines, items = read_backlog(root)
    after = requeue_after(root, job)
    claimed = next((i for i in items if i["job"] == job["id"]), None)
    if claimed and not feature.exists():
        claimed.update(done=False, job=None, after=list(dict.fromkeys(claimed["after"] + after)))
        at = claimed["line"]
        lines[at] = format_item(claimed)
        if (folder / "spec.md").is_file():
            spec_path(root, claimed["text"]).parent.mkdir(exist_ok=True)
            os.replace(folder / "spec.md", spec_path(root, claimed["text"]))
    else:
        text = clean(feature.read_text() if feature.exists() else job["title"], ITEM_MAX) or job["title"]
        if job.get("shop") and MAIN_MAC_RE.search(str(job.get("reason") or "")) \
                and header_in(feature_text(text), "Runs on", RUNS_ON) != "main":
            text += " Runs on: main."  # after the cut, so ITEM_MAX never drops it
        marks = {k: claimed[k] for k in REQUEUE_MARKS} if claimed else {}
        lines.append(format_item({"done": False, "points": None, "text": text, "job": None, "why": None, "after": after,
                                  **marks}))
        at = len(lines) - 1
    write_backlog(root, lines)
    if back := next((i for i in read_backlog(root)[1] if i["line"] == at), None):
        job["requeued"] = item_key(back)


def md_section(text, heading):
    """The body of a `## <heading>` section, up to the next `## ` heading, or None if it has none."""
    m = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m and m.group(1)


def merge_summary(text):
    """The body of decision.md's '## Merge summary' section, or None if it has none."""
    body = md_section(text, "Merge summary")
    return body and body.strip()


def cmd_reopen(root, job_id, note):
    """Start a new job that follows up a done or aborted one; its feature.md carries the old job's context."""
    old_dir = Path(root) / "jobs" / check_id(job_id)
    note = clean(note, ITEM_MAX)
    with locked_board(root) as board:
        old = find(board, job_id)
        if old["stage"] not in ("done", "aborted"):
            raise SystemExit(f"job {job_id} is {old['stage']}; only done or aborted jobs can be reopened")
        if old.get("reopened_to"):
            raise SystemExit(f"job {job_id} was already reopened as {old['reopened_to']}")
        if not note:
            raise SystemExit("note is empty")
        read = lambda name: (old_dir / name).read_text().strip() if (old_dir / name).is_file() else None
        decision = read("decision.md")
        parts = [("feature.md", read("feature.md")), ("spec.md", read("spec.md")),
                 ("Merge summary", decision and merge_summary(decision))]
        text = f"{note}\nReopened from {job_id}." + (f" PR: {old['pr']}" if old.get("pr") else "") + "\n" \
            + "".join(f"\n## Original {name}\n\n{body}\n" for name, body in parts if body)
        new_id = add_job(root, board, f"Reopen {job_id.split('-')[0]}: {note}"[:60])
        (Path(root) / "jobs" / new_id / "feature.md").write_text(text)
        board["jobs"][-1]["reopened_from"] = job_id
        old["reopened_to"] = new_id
        return new_id


# --- the project list behind the one all-projects dashboard ---
def registry_path():
    return Path(os.environ.get("SCRUM_REGISTRY") or Path.home() / ".claude" / "trevskills-scrum" / "projects.json")


def read_registry():
    try:
        paths = json.loads(registry_path().read_text())
        return [p for p in paths if isinstance(p, str)] if isinstance(paths, list) else []
    except (OSError, ValueError):
        return []


@contextmanager
def registry_lock():
    """projects.lock: every read-modify-write of projects.json runs inside it."""
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name("projects.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def write_registry(paths):
    """Replace projects.json atomically (tmp + os.replace). Call it under registry_lock()."""
    path = registry_path()
    tmp = path.with_name("projects.json.tmp")
    tmp.write_text(json.dumps(paths, indent=2) + "\n")
    os.replace(tmp, path)


def cmd_register(repo):
    """Add a repo to the dashboard's project list. Idempotent; /trevskills-scrum calls it on every run."""
    with registry_lock():
        paths = read_registry()
        repo = str(Path(repo).resolve())
        if repo not in paths:
            write_registry(paths + [repo])


def ranked(paths):
    """{display name: index in paths} for the registry entries that have a scrum/ folder, in registry order. Names
    are the folder name, or parent/folder when two repos share one."""
    repos = [(i, Path(p)) for i, p in enumerate(paths) if (Path(p) / "scrum").is_dir()]
    counts = {}
    for _, r in repos:
        counts[r.name] = counts.get(r.name, 0) + 1
    return {(r.name if counts[r.name] == 1 else f"{r.parent.name}/{r.name}"): i for i, r in repos}


def projects():
    """{display name: repo path} for registered repos that still have a scrum/ folder, in rank (registry) order."""
    paths = read_registry()
    return {name: Path(paths[i]) for name, i in ranked(paths).items()}


def rerank(paths, slots, names):
    """Write the registry with the projects in `names` order. Entries without a scrum/ folder keep their places;
    an unchanged order writes nothing."""
    if names != list(slots):
        new = list(paths)
        for slot, name in zip(slots.values(), names):  # slots.values() is ascending: registry order
            new[slot] = paths[slots[name]]
        write_registry(new)


def move_project(name, to):
    """Put project `name` at rank `to` (0-based) of projects(); returns the names in the new order. The lookup, the
    bounds check and the write all run under projects.lock, so a stale caller gets a SystemExit, not a wrong move."""
    with registry_lock():
        paths = read_registry()
        slots = ranked(paths)
        if not slots:
            raise SystemExit("no projects registered")
        if not isinstance(name, str) or name not in slots:
            raise SystemExit("no such project")
        if type(to) is not int or not 0 <= to < len(slots):
            raise SystemExit(f"to must be a whole number from 0 to {len(slots) - 1}")
        names = [n for n in slots if n != name]
        names.insert(to, name)
        rerank(paths, slots, names)
        return names


FOCUS_RE = re.compile(r"^- Focus: *yes\s*$", re.M | re.I)


def migrate_focus():
    """One-time move from `- Focus: yes` to rank: every project whose scrum/project.md has the line goes to the top,
    keeping its relative order, and the line is deleted. Returns the names moved; a second call finds none. A
    missing, unreadable or non-UTF-8 project.md is skipped."""
    with registry_lock():
        paths = read_registry()
        slots = ranked(paths)
        focused = {}
        for name, i in slots.items():
            md = Path(paths[i]) / "scrum" / "project.md"
            try:
                text = md.read_text()
            except (OSError, ValueError):
                continue
            if FOCUS_RE.search(text):
                focused[name] = (md, text)
        if not focused:
            return []
        rerank(paths, slots, list(focused) + [n for n in slots if n not in focused])
        for md, text in focused.values():  # after the registry write: a failed strip only leaves a no-op line
            try:
                md.write_text("".join(line for line in text.splitlines(True) if not FOCUS_RE.match(line)))
            except OSError:
                pass
        return list(focused)


AGENT_TAG_RE = re.compile(r"from \d{3,}-[a-z0-9-]+\)|\(gap of |\(Phase 2 of |\(merged: digest|^(?:Apply|Create) digest \d")


def migrate_backlog_sources():
    """One-time source marking, per registered project with no scrum/backlog-sources.done: under its board lock, each
    open item with no {by:…} marker is an agent item when AGENT_TAG_RE finds a tag (p:4/p:5 drop to p:3), else
    Trevor's (gets {by:t} and p:4, or keeps p:5); then the sentinel is written. No Jev call. Returns the names migrated;
    a second call finds none. A project whose lock or files fail is skipped and retried at the next start."""
    done = []
    for name, repo in projects().items():
        root = repo / "scrum"
        sentinel = root / "backlog-sources.done"
        if sentinel.exists():
            continue
        try:
            with locked_board(root):
                if (root / "backlog.md").exists():
                    lines, items = read_backlog(root)
                    changed = False
                    for item in items:
                        if item["done"] or item["by"]:
                            continue
                        if AGENT_TAG_RE.search(item["text"]):
                            new = 3 if (item["priority"] or 0) > 3 else item["priority"]
                        else:
                            item["by"], new = "t", source_priority("t", item["priority"])
                        if new != item["priority"] or item["by"]:
                            item["priority"] = new
                            lines[item["line"]] = format_item(item)
                            changed = True
                    if changed:
                        write_backlog(root, lines)
                sentinel.write_text(now() + "\n")
        except (OSError, SystemExit) as e:
            print(f"backlog source migration skipped {name}: {e}", file=sys.stderr)
            continue
        done.append(name)
    return done


def cmd_backlog_add(root, items, setup=None, priority=None, top=False, by=None, critical=False, unless_open=None):
    """Append each non-empty item, each with the Human setup checklist `setup` ("step; step") when given; returns the
    texts as stored. An empty checklist adds nothing. top puts each item first with {p:5}; by and critical set the
    source and priority (see backlog_op). unless_open skips an item while an open item's text contains it (checked
    under the add's lock); skipped items are left out of the result. An item that is only a flag (flag_item) refuses
    the whole call before any write."""
    check_source(by, priority, top, critical)
    if setup is not None:
        setup_steps(setup)
    check_priority(priority)
    if flags := [clean(item, ITEM_MAX) for item in items if flag_item(item)]:
        raise SystemExit(f"backlog item {flags[0]!r} is a flag, not work; nothing added: {FLAG_HINT}")
    added = []
    for item in items:
        if clean(item):
            if backlog_op(root, "add", text=item, setup=setup, priority=priority, top=top, by=by, critical=critical,
                          unless_open=unless_open) is not None:
                added.append(clean(item, ITEM_MAX))
    return added


def on_worker() -> bool:
    """A shop Mac run (SCRUM_SHOP non-empty) or a claude.ai cloud session (CLAUDE_CODE_REMOTE=true): its scrum/ is a
    throwaway board, and only jobs/<id>/ comes home (the Artifacts push)."""
    return bool(os.environ.get("SCRUM_SHOP")) or os.environ.get("CLAUDE_CODE_REMOTE") == "true"


FOLDER_RE = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._-]*")  # a repo folder name a worker add may name (--project)


def worker_add(root, job_id, items, project=None, setup=None, priority=None, top=False, by=None, critical=False) -> list[str]:
    """Write each non-empty item as its own "Backlog: add" file jobs/<id>/followups/add-<n>.md (n the first free number,
    never overwriting a file), with Project / Top / By / Priority / Critical / Setup lines for the flags given; the
    home backlog-spec files it (job 1504). The same flag checks as cmd_backlog_add run before anything is written.
    project is a repo folder name, not checked against projects.json (a worker's registry is not the home one).
    Returns the item texts written."""
    folder = Path(root) / "jobs" / check_id(job_id) / "followups"
    check_source(by, priority, top, critical)
    steps = setup_steps(setup) if setup is not None else None
    check_priority(priority)
    if project is not None and not FOLDER_RE.fullmatch(project):
        raise SystemExit(f"--project must be a repo folder name, got {project!r}")
    if flags := [clean(item, ITEM_MAX) for item in items if flag_item(item)]:
        raise SystemExit(f"backlog item {flags[0]!r} is a flag, not work; nothing added: {FLAG_HINT}")
    extra = [f"Project: {project}" if project else None, "Top: yes" if top else None, f"By: {by}" if by else None,
             f"Priority: {priority}" if priority is not None else None, "Critical: yes" if critical else None,
             f"Setup: {'; '.join(steps)}" if steps else None]
    written = []
    for item in items:
        text = clean(item, ITEM_MAX)
        if not text:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        body = "\n".join(["Backlog: add", f"Item: {text}", *(line for line in extra if line)]) + "\n"
        n = 1
        while True:
            try:
                with open(folder / f"add-{n}.md", "x", encoding="utf-8") as f:
                    f.write(body)
                break
            except FileExistsError:
                n += 1
        written.append(text)
    return written


# --- manual-checks.md: "- [ ] text" follow-ups only a human can do; Trevor ticks them on the dashboard ---
MANUAL_HEADER = "# Manual checks"
MANUAL_RE = re.compile(r"^- \[( |x)\] (.*?)\s*$")


def read_manual(root):
    """(lines, items) of manual-checks.md; items remember their line so a tick leaves headings and notes alone."""
    path = Path(root) / "manual-checks.md"
    lines = path.read_text().splitlines() if path.exists() else [MANUAL_HEADER]
    items = []
    for n, line in enumerate(lines):
        if m := MANUAL_RE.match(line):
            items.append({"index": len(items), "line": n, "done": m.group(1) == "x", "text": m.group(2)})
    return lines, items


def manual_items(root):
    return [{k: v for k, v in item.items() if k != "line"} for item in read_manual(root)[1]]


def _append_manual(root, texts):
    """Append "- [ ] <text>" for each text that is non-empty and not already open. Caller holds the board lock.
    Returns the texts as stored."""
    lines, items = read_manual(root)
    open_texts, added = {i["text"] for i in items if not i["done"]}, []
    for t in texts:
        t = clean(t, ITEM_MAX)
        if t and t not in open_texts:
            open_texts.add(t)
            added.append(t)
            lines.append(f"- [ ] {t}")
    if added:
        (Path(root) / "manual-checks.md").write_text("\n".join(lines) + "\n")
    return added


def cmd_manual_add(root, items):
    """Append each non-empty item that isn't already an open check; returns the texts added."""
    with locked_board(root):
        return _append_manual(root, items)


def manual_tick(root, index):
    """Mark one manual check [x] under the board lock. Returns the new item list."""
    with locked_board(root):
        lines, items = read_manual(root)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
            raise SystemExit(f"no manual check {index!r}")
        lines[items[index]["line"]] = f"- [x] {items[index]['text']}"
        (Path(root) / "manual-checks.md").write_text("\n".join(lines) + "\n")
    return manual_items(root)


ADD_KEYS = ("Project", "Top", "By", "Priority", "Critical", "Setup")  # worker_add's lines after Item:


def parse_followup(text):
    """(kind, item text, body) for one followups/*.md file; raises ValueError with the reason when malformed.
    A "Backlog: add" file (worker_add) gives ("add", item, {"project", "top", "by", "priority", "critical", "setup"})
    once its flags pass the same checks as backlog-add."""
    lines = text.splitlines()
    head = lines[0].strip() if lines else ""
    if head == "Backlog: add":
        m = re.match(r"^Item:\s*(.*)$", lines[1].strip() if len(lines) > 1 else "")
        if not m or not m.group(1).strip():
            raise ValueError("second line is not 'Item: <text>'")
        fields = {}
        for line in lines[2:]:
            key, sep, value = line.partition(":")
            if not line.strip():
                continue
            if not sep or key.strip() not in ADD_KEYS:
                raise ValueError(f"unknown line {line.strip()[:60]!r}")
            fields[key.strip()] = value.strip()
        priority = fields.get("Priority")
        if priority is not None and not re.fullmatch(r"[1-5]", priority):
            raise ValueError(f"Priority must be 1-5, got {priority!r}")
        by = fields.get("By")
        if by is not None and by not in ("t", "back"):
            raise ValueError(f"By must be t or back, got {by!r}")
        opts = {"project": fields.get("Project") or None, "top": fields.get("Top") == "yes", "by": by,
                "priority": int(priority) if priority else None, "critical": fields.get("Critical") == "yes",
                "setup": fields.get("Setup") or None}
        try:
            check_source(opts["by"], opts["priority"], opts["top"], opts["critical"])
            if opts["setup"] is not None:
                setup_steps(opts["setup"])
        except SystemExit as e:
            raise ValueError(str(e)) from None
        return "add", m.group(1).strip(), opts
    if head == "Backlog: new":
        m = re.match(r"^Item:\s*(.*)$", lines[1].strip() if len(lines) > 1 else "")
        if not m or not m.group(1).strip():
            raise ValueError("second line is not 'Item: <text>'")
        kind, item, rest = "new", m.group(1).strip(), lines[2:]
    elif (m := re.match(r"^Backlog: update\s+(\S.*)$", head)):
        kind, item, rest = "update", m.group(1).strip(), lines[1:]
    else:
        raise ValueError("first line is not 'Backlog: new', 'Backlog: update <text>' or 'Backlog: add'")
    body = "\n".join(rest).strip("\n")
    if not body.strip():
        raise ValueError("spec body is empty")
    return kind, item, body + "\n"


def add_target(root, project):
    """The scrum/ dir a "Backlog: add" file's Project names: root for none or root's own repo folder, the registered
    project (projects() display name or repo folder name) otherwise, None when no registered project has that name."""
    home = Path(root).resolve()
    if not project or project == home.parent.name:
        return Path(root)
    for name, repo in projects().items():
        if project in (name, repo.name):
            return Path(root) if (repo / "scrum").resolve() == home else repo / "scrum"
    return None


def cmd_backlog_spec(root, job_id):
    """Ingest jobs/<id>/followups/*.md under the lock: each file adds an item (or matches an open one by exact text)
    and stores its spec at spec_path. Appends lines itself: backlog_op would flock .board.lock again and deadlock.
    "Backlog: add" files (worker_add, job 1504) are filed after that lock is released, each through cmd_backlog_add with
    its flags and unless_open=<its text> (E2E_SLOW_ITEM for that item), so a rerun adds no copy: in add_target's backlog,
    listed under "moved" as {"project", "text"} when that is another project, else here under "added"; an unregistered
    Project is filed here as "<text> (for <folder>: not a registered project)". On a worker (on_worker) they are left
    alone and counted nowhere. "moved" is in the result only when something was filed in another project."""
    folder = Path(root) / "jobs" / check_id(job_id) / "followups"
    out = {"added": [], "updated": [], "skipped": []}
    worker, adds = on_worker(), []
    with locked_board(root):
        lines, items = read_backlog(root)
        specs = {}
        for f in sorted(folder.glob("*.md")) if folder.is_dir() else []:
            try:
                kind, text, body = parse_followup(f.read_text(encoding="utf-8", errors="replace"))
            except ValueError as e:
                print(f"backlog-spec: skipped {f.name}: {e}", file=sys.stderr)
                out["skipped"].append(f.name)
                continue
            if kind == "add":
                if not worker:
                    adds.append((text, body))
                continue
            if kind == "update" and any(not i["done"] and i["text"] == text for i in items):
                out["updated"].append(text)
            else:
                text = clean(text + f" (from {job_id})", ITEM_MAX)
                lines.append(format_item({"done": False, "points": None, "text": text, "job": None, "why": None}))
                out["added"].append(text)
            specs[text] = body
        if not specs and not adds:
            raise SystemExit(f"backlog-spec {job_id}: no usable followups/*.md; backlog.md was not touched")
        if out["added"]:
            write_backlog(root, lines)
        for text, body in specs.items():
            path = spec_path(root, text)
            path.parent.mkdir(exist_ok=True)
            path.write_text(body, encoding="utf-8")
    for text, opts in adds:
        target = add_target(root, opts["project"])
        if target is None:
            target, text = Path(root), f"{text} (for {opts['project']}: not a registered project)"
        text = clean(text, ITEM_MAX)
        filed = cmd_backlog_add(target, [text], opts["setup"], opts["priority"], opts["top"], opts["by"],
                                opts["critical"], unless_open=E2E_SLOW_ITEM if text.startswith(E2E_SLOW_ITEM) else text)
        if target == Path(root):
            out["added"] += filed
        elif filed:
            out.setdefault("moved", []).extend({"project": opts["project"], "text": t} for t in filed)
    return out


def job_files(d):
    """Every *.md in a job folder, relative and sorted; [] if the folder doesn't exist."""
    return sorted(str(p.relative_to(d)) for p in d.rglob("*.md")) if d.is_dir() else []


def _fence_run(line):
    """(char, run length, rest of line) if the stripped line starts with 3+ backticks or tildes, else None."""
    s = line.lstrip()
    if not s.startswith(("```", "~~~")):
        return None
    n = len(s) - len(s.lstrip(s[0]))
    return s[0], n, s[n:]


def diverged(d):
    """True if spec.md, build.md, assessment.md or plan.md has a `## Diverged` section with a bullet that isn't `- none`, outside fenced code."""
    for name in ("spec.md", "build.md", "assessment.md", "plan.md"):
        p = d / name
        if not p.is_file():
            continue
        inside, fence = False, None  # fence: (char, length) of the open fence
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            # Same fence rule as divergedBullets() in dashboard.html: close only on the same char, a run at least
            # as long, and nothing but whitespace after it.
            run = _fence_run(line)
            if fence:
                if run and run[0] == fence[0] and run[1] >= fence[1] and not run[2].strip():
                    fence = None
                continue
            if run:
                fence = run[:2]
            elif line.startswith("## "):
                inside = line == "## Diverged"
            elif inside and line.startswith("- ") and line[2:].strip().lower() != "none":
                return True
    return False


# --- digests: scrum/digests/<NNN>/jobs.txt lists the done jobs one digest learned from ---
DIGEST_RE = re.compile(r"^\d{3}$")
TRIM_KEEP = {"feature.md", "spec.md", "decision.md", "build.md", "rework.md", "nh-comment.txt"}  # plus unblock-*.md (UNBLOCK_RE)
UNBLOCK_RE = re.compile(r"unblock-.*\.md")
ROUND_KEEP = {"review-code.md", "review-ui.md", "review-ux.md", "review-security.md", "review-e2e.md", "check.md"}  # kept inside each round-<N>/ of a trimmed job
QUESTIONS_DIGEST_LINES = 15  # a digest is also due once questions.log grew this many own-project lines since the last one ...
QUESTIONS_DIGEST_MIN_SECS = 6 * 3600  # ... and the last digest is this old
BAD_WASTED_PCT = 20  # a window scorecard is bad above this wasted_pct
BAD_FIRST_PASS = 0.5  # ... or below this first_pass_rate, once it has BAD_MIN_JOBS done jobs
BAD_MIN_JOBS = 3
EARLY_DIGEST_MIN = 3  # a bad window brings the digest forward once this many done jobs are undigested
WINDOW_FILE_RE = re.compile(r"(five_hour|seven_day)-\d+(-[a-z0-9-]{1,20})?\.json")


def digested_ids(root):
    """Every job id listed in any digest's jobs.txt, except a failed digest's (error.md), so the next digest re-claims them."""
    return {line.strip() for f in (Path(root) / "digests").glob("*/jobs.txt") if not f.with_name("error.md").exists()
            for line in f.read_text().splitlines() if line.strip()}


def claimed_windows(root):
    """Every scorecard name listed in any digest's windows.txt, except a failed digest's (error.md), like digested_ids."""
    return {line.strip() for f in (Path(root) / "digests").glob("*/windows.txt") if not f.with_name("error.md").exists()
            for line in f.read_text().splitlines() if line.strip()}


def undigested(root, board):
    seen = digested_ids(root)
    return [j["id"] for j in board["jobs"] if j.get("stage") == "done" and j["id"] not in seen]


def questions_lines(root):
    """Number of this project's lines in <scrum>/questions.log: JSON objects whose `project` is the project folder's name
    or is missing. Blank and unparseable lines do not count; 0 when the file is missing."""
    path = Path(root) / "questions.log"
    if not path.is_file():
        return 0
    name = Path(root).resolve().parent.name
    n = 0
    for line in path.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        n += isinstance(d, dict) and d.get("project", name) == name
    return n


def questions_marker(root):
    """(count, mtime) of the questions.lines of the newest digest with an integer marker and no error.md; None when none."""
    d = Path(root) / "digests"
    for p in sorted((x for x in d.iterdir() if DIGEST_RE.fullmatch(x.name)), reverse=True) if d.is_dir() else []:
        try:
            if not (p / "error.md").exists() and re.fullmatch(r"\d+", text := (p / "questions.lines").read_text().strip()):
                return int(text), (p / "questions.lines").stat().st_mtime
        except (OSError, UnicodeDecodeError):
            pass
    return None


def questions_growth(root):
    """Own questions.log lines added since the newest digest with an integer questions.lines and no error.md, floored
    at 0. With no such digest, the whole line count."""
    m = questions_marker(root)
    return max(questions_lines(root) - m[0], 0) if m else questions_lines(root)


def questions_due(root):
    """True when questions_growth reaches QUESTIONS_DIGEST_LINES and the last digest (questions_marker) is at least
    QUESTIONS_DIGEST_MIN_SECS old; with no such digest there is no age gate."""
    m = questions_marker(root)
    return questions_growth(root) >= QUESTIONS_DIGEST_LINES and (m is None or time.time() - m[1] >= QUESTIONS_DIGEST_MIN_SECS)


def bad_window(card: dict) -> bool:
    """True when a scorecard's wasted_pct is above BAD_WASTED_PCT, or its first_pass_rate is below BAD_FIRST_PASS over
    BAD_MIN_JOBS+ done jobs. A null or missing field is never bad."""
    jobs = card.get("done_jobs")
    return (is_num(card.get("wasted_pct")) and card["wasted_pct"] > BAD_WASTED_PCT) or (
        is_num(card.get("first_pass_rate")) and card["first_pass_rate"] < BAD_FIRST_PASS
        and isinstance(jobs, list) and len(jobs) >= BAD_MIN_JOBS)


def early_window(root) -> str | None:
    """The first (by name) bad windows/<window>-<resets_at>.json no digests/*/windows.txt lists, written after the
    newest NNN digest folder was created (st_birthtime, else st_mtime); None when there is none. Junk is skipped."""
    root = Path(root)
    listed, newest = set(), None
    d = root / "digests"
    for p in d.iterdir() if d.is_dir() else []:
        try:
            if DIGEST_RE.fullmatch(p.name):
                st = p.stat()
                newest = max(newest or 0, getattr(st, "st_birthtime", st.st_mtime))
            if (p / "windows.txt").is_file():
                listed |= {x.strip() for x in (p / "windows.txt").read_text().splitlines() if x.strip()}
        except (OSError, UnicodeDecodeError):
            pass
    w = root / "windows"
    for p in sorted(w.iterdir()) if w.is_dir() else []:
        if not WINDOW_FILE_RE.fullmatch(p.name) or p.name in listed:
            continue
        try:
            card = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        at = _epoch(card.get("written_at")) if isinstance(card, dict) else None
        if at is not None and (newest is None or at > newest) and bad_window(card):
            return p.name
    return None


def cmd_digest_due(root):
    """{"due","undigested","questionsGrowth","reason"}. reason, in this order: "10 done", "questions" or
    "bad window <file>" (early_window, at EARLY_DIGEST_MIN+ undigested jobs); null when not due."""
    path = Path(root) / "board.json"
    n = len(undigested(root, json.loads(path.read_text()) if path.exists() else {"jobs": []}))
    growth = questions_growth(root)
    reason = "10 done" if n >= 10 else "questions" if questions_due(root) else None
    if reason is None and n >= EARLY_DIGEST_MIN and (name := early_window(root)):
        reason = f"bad window {name}"
    return {"due": reason is not None, "undigested": n, "questionsGrowth": growth, "reason": reason}


def cmd_digest_start(root):
    """Claim every undigested done job as digest NNN, under the lock, so two triggers never share a job. Also starts
    with no jobs when questions.log grew QUESTIONS_DIGEST_LINES own lines and the last digest is QUESTIONS_DIGEST_MIN_SECS old; questions.lines records its count.
    Also claims every valid windows/ scorecard no live digest lists: names to windows.txt, contents to windows.json."""
    with locked_board(root) as board:
        jobs = undigested(root, board)
        if not jobs and not questions_due(root):
            return {"id": None, "jobs": [], "windows": []}
        digest_id = claim_folder(Path(root) / "digests")
        d = Path(root) / "digests" / digest_id
        d.joinpath("jobs.txt").write_text("".join(f"{j}\n" for j in jobs))
        d.joinpath("questions.lines").write_text(f"{questions_lines(root)}\n")
        names, cards, seen, w = [], [], claimed_windows(root), Path(root) / "windows"
        for p in sorted(w.iterdir()) if w.is_dir() else []:
            if not WINDOW_FILE_RE.fullmatch(p.name) or p.name in seen:
                continue
            try:
                card = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(card, dict):
                names.append(p.name)
                cards.append(card)
        d.joinpath("windows.txt").write_text("".join(f"{n}\n" for n in names))
        d.joinpath("windows.json").write_text(json.dumps(cards, indent=2) + "\n")
        out = {"id": digest_id, "jobs": jobs, "windows": names}
    try:  # after the lock: pipeline_health takes it itself
        pipeline_health(root, digest_id, jobs)
    except (SystemExit, OSError) as e:
        print(f"digest-start: pipeline health: {e}", file=sys.stderr)
    try:
        write_timing(root, digest_id, jobs)
    except (SystemExit, OSError) as e:
        print(f"digest-start: timing: {e}", file=sys.stderr)
    try:
        write_escapes(root, digest_id, jobs)
    except (SystemExit, OSError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"digest-start: escapes: {e}", file=sys.stderr)
    try:
        write_history(root, out["id"])
    except (SystemExit, OSError) as e:
        print(f"digest-start: history: {e}", file=sys.stderr)
    try:
        write_pulse(root, digest_id)
    except (SystemExit, OSError, ValueError, TypeError) as e:
        print(f"digest-start: pulse: {e}", file=sys.stderr)
    try:
        write_processes(root, digest_id)
    except (SystemExit, OSError, ValueError, TypeError) as e:
        print(f"digest-start: processes: {e}", file=sys.stderr)
    try:
        write_waste(root, digest_id)
    except (SystemExit, OSError, ValueError, TypeError) as e:
        print(f"digest-start: waste: {e}", file=sys.stderr)
    try:
        write_tokens(root, digest_id)
    except (SystemExit, OSError, ValueError, TypeError, subprocess.TimeoutExpired) as e:
        print(f"digest-start: tokens: {e}", file=sys.stderr)
    return out


HISTORY_DIGESTS, HISTORY_DAYS = 5, 14  # write_history: how many earlier digests and how many days of closed backlog items


def write_history(root, digest_id):
    """digests/<NNN>/history.md: the proposals of the last HISTORY_DIGESTS earlier digests across every registered project
    (newest first, with status), and the backlog items closed or retired in the last HISTORY_DAYS days, so the digester
    does not re-propose them. Backlog lines carry no close date except `retired YYYY-MM-DD`, so undated [x] lines are the last 20."""
    me = Path(root).resolve().parent
    repos = [me] + [p for p in projects().values() if p.resolve() != me]
    found = []
    for repo in repos:
        for f in (repo / "scrum" / "digests").glob("*/proposals.json"):
            if not (repo == me and f.parent.name == digest_id):
                try:
                    found.append((f.stat().st_mtime, repo.name, f.parent.name, json.loads(f.read_text())["proposals"]))
                except (OSError, ValueError, KeyError, TypeError):
                    pass
    out = ["# History", "", "## Earlier proposals"]
    for _, name, did, props in sorted(found, reverse=True)[:HISTORY_DIGESTS]:
        for p in props if isinstance(props, list) else []:
            if isinstance(p, dict):
                out.append(f"- {name} {did} {p.get('id')} [{p.get('status', 'pending')}] {p.get('target') or p.get('kind')}: "
                           f"{str(p.get('why'))[:160]}")
    out += ["", "## Backlog closed"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
    closed = []
    for repo in repos:
        try:
            lines = [l for l in (repo / "scrum" / "backlog.md").read_text().splitlines() if l.startswith("- [x]")]
        except OSError:
            continue
        dated = [(m.group(1), l) for l in lines if (m := re.search(r"retired (\d{4}-\d\d-\d\d)", l))]
        closed += [f"- {repo.name}: {l[6:160]}" for d, l in dated if d >= cutoff]
        closed += [f"- {repo.name}: {l[6:160]}" for l in lines[-20:] if not re.search(r"retired \d{4}", l)]
    (Path(root) / "digests" / digest_id / "history.md").write_text("\n".join(out + closed) + "\n")


def claim_folder(parent):
    """Create the next 3-digit folder (001, 002, ...) under parent and return its name. Caller holds the board lock."""
    parent.mkdir(exist_ok=True)
    name = f"{max((int(p.name) for p in parent.iterdir() if DIGEST_RE.fullmatch(p.name)), default=0) + 1:03d}"
    (parent / name).mkdir()
    return name


WEEKLY_LATE_SECS = 172800  # serve.py weekly_tick runs the cross-project Fable digest in the 7d window's last 2 days


def weekly_dir():
    """The cross-project weekly digests, beside projects.json (SCRUM_REGISTRY moves both)."""
    return registry_path().parent / "weekly"


PULSE_KEEP_SECS = 14 * 86400  # serve.py pulse_tick keeps this much of pulse.log


def pulse_path():
    """The serve.py watchdog's pulse log (one JSON line a tick): $SCRUM_PULSE when set and non-empty, else beside
    projects.json (SCRUM_REGISTRY moves both)."""
    return Path(os.environ.get("SCRUM_PULSE") or registry_path().parent / "pulse.log")


# Every process the scrum runs on its own, for the digest (write_processes): (name, serve.py/board.py functions,
# state files relative to the scrum folder, globs allowed). tests/test_processes.py fails on a watchdog call, *_tick
# or scrum-folder file no entry names, and on a log_process name that is no entry.
PROCESSES = (
    ("Session starts", ("spawn", "auto_continue_tick", "play_queue_tick", "auto_resume", "auto_play", "idle_claim",
                        "start_ready", "wake_waiting", "queue_ready_waiting", "sweep_parents", "main_ff_tick", "terminal_batch_tick",
                        "resume_budget", "hand_queue_tick", "launch_queued"), ()),
    ("Stalls and exits", ("cmd_watchdog", "respawn_exited", "record_outcomes", "cmd_migrate_paused", "claude_migrate"),
     ("questions.log",)),
    ("Full E2E on main", ("e2e_full_tick", "e2e_full_run", "hot_stop_tick"), ("e2e-full.json", "e2e-full.log", "e2e-full-rerun.log")),
    ("UI sweep", ("ui_sweep_tick", "cmd_ui_sweep_record", "hot_stop_tick"), ("ui-sweep.json", "ui-sweep/*/review.md")),
    ("Prod error sweep", ("prod_errors_tick",), ("prod-errors.json",)),
    ("Actions alerts", ("actions_alert",), ()),
    ("Disk reclaim", ("reclaim_disk", "shop_reclaim_tick", "shop_reclaim",
                      "shop_stats", "refresh_shop_stats"), ()),
    ("Idle cleanup", ("idle_cleanup", "stop_dev_servers", "stop_orphans", "docker_tick", "prune_worktrees"), ()),
    ("Leftover sessions", ("stop_leftovers", "stop_tree", "process_scan"), ()),
    ("Two sessions", ("stop_two_sessions",), ()),
    ("Same tests", ("stop_same_tests",), ()),
    ("CPU hogs", ("report_hogs",), ()),
    ("E2E lock reaps", ("e2e_lock_reap", "render_reap_tick"), ()),
    ("E2E runaway stop", ("e2e_runaway_tick",), ()),
    ("Agent links", ("agent_links_tick",), ()),
    ("Digest retry", ("digest_retry_tick",), ()),
    ("Weekly digest", ("weekly_tick",), ()),
    ("Cloud jobs", ("cloud_tick", "cmd_cloud_sync", "cmd_cloud_claim", "shop_tick", "write_shop_room",
                    "project_notes_tick"), ()),
    ("Usage windows", ("window_tick", "usage_refresh_tick", "hard_stop_tick"), ("windows",)),
    ("Pulse", ("pulse_tick", "publish_busy", "record_cpu_sample", "cooldown_chime"), ()),
    ("Stuck alert", ("stuck_alert", "stuck_process", "disk_alert_tick", "claude_missing_tick", "signin_alert_tick"), ()),
    ("Live checks", ("live_check_tick",), ("jobs/*/live-checks.json",)),
    ("Run all and triage", ("cmd_runall_start", "cmd_triage_start", "cmd_triage_apply"), ("triage/*",)),
    ("Roadmap and BigBoy", ("cmd_roadmap_next",), ("roadmap.md", "jobs/*/track-*.md", "jobs/*/bigboy-review.md")),
    ("Backlog ranking", ("cmd_rank_backlog",), ("jev.log",)),
    ("Held items", (), ("held.md",)),
    ("Manual checks", ("cmd_manual_add",), ("manual-checks.md",)),
)


def processes_path():
    """The machine-wide process run log (one JSON line a run, log_process), beside pulse.log (SCRUM_PULSE moves it)."""
    return pulse_path().with_name("processes.log")


def _append_log(path: Path, record: dict, label: str) -> None:
    """Append record as one JSON line to path (log_process, log_waste). When the first line is older than
    PULSE_KEEP_SECS plus a day (or unreadable, or has no numeric t), the file is first rewritten (<name>.tmp +
    os.replace) to the last PULSE_KEEP_SECS, like serve.pulse_tick does pulse.log; no lock, so a line appended during a
    rotation may be lost. Never raises: an OSError prints one `<label>: ` stderr line. Under unittest the real default
    ~/.claude/trevskills-scrum/<name> is never written (a silent return)."""
    if "unittest" in sys.modules and path == Path.home() / ".claude" / "trevskills-scrum" / path.name:
        return  # a test run would add fixture lines to the live log the digest reads
    now = record["t"]
    line = json.dumps(record, default=str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                first = json.loads(f.readline() or "{}")
        except OSError:
            first = {}  # no file yet: nothing to rotate
        except ValueError:
            first = {"t": None}  # a malformed first line never ages out by itself: rotate it away
        if first and not (isinstance(first, dict) and is_num(first.get("t")) and first["t"] >= now - PULSE_KEEP_SECS - 86400):
            keep = [l for l in _json_lines(path) if is_num(l.get("t")) and l["t"] >= now - PULSE_KEEP_SECS]
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("".join(json.dumps(l) + "\n" for l in keep))
            os.replace(tmp, path)
        with open(path, "a") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"{label}: {e}", file=sys.stderr)


def log_process(process: str, result: str, **fields) -> None:
    """Append one {"t", "process", "result", **fields} JSON line to processes_path() through _append_log (rotation,
    never raises, `processes: ` stderr prefix, unittest guard): one PROCESSES entry's run, for the digest's
    processes.md (write_processes). A `repo` field is stored as its realpath."""
    if "repo" in fields:
        try:
            fields["repo"] = os.path.realpath(str(fields["repo"]))  # a relative repo would resolve against the digest's cwd
        except (OSError, ValueError):
            pass  # unresolvable: keep as given, never raise
    _append_log(processes_path(), {"t": int(time.time()), "process": process, "result": result, **fields}, "processes")


WASTE_KINDS = ("two-sessions", "same-tests", "leftover", "cpu-hog")  # log_waste: the wasted-work catches (BigBoy 1165)


def waste_path():
    """The machine-wide wasted-work catch log (one JSON line a catch, log_waste), beside pulse.log (SCRUM_PULSE moves it)."""
    return pulse_path().with_name("waste.log")


def log_waste(kind: str, project, jobs, pids, cpu_min, **fields) -> None:
    """Append one {"t", "kind", "project", "jobs", "pids", "cpu_min", **fields} JSON line to waste_path() through
    _append_log, for the digest's waste.md (write_waste). project is a registered project name or None; jobs and pids
    are lists. A kind not in WASTE_KINDS writes nothing and prints one `waste: unknown kind '<kind>'` stderr line.
    Never raises."""
    if kind not in WASTE_KINDS:
        print(f"waste: unknown kind {kind!r}", file=sys.stderr)
        return
    _append_log(waste_path(), {"t": int(time.time()), "kind": kind, "project": project, "jobs": jobs, "pids": pids,
                               "cpu_min": cpu_min, **fields}, "waste")


def pulse_auto(lines, project=None):
    """[(t, auto)] for each pulse.log line (board._json_lines) with a numeric t, in file order: auto is True when the
    line's projects.<project>.auto is True (any project's, when project is None)."""
    out = []
    for l in lines:
        ps = l.get("projects") if isinstance(l.get("projects"), dict) else {}
        if is_num(l.get("t")):
            vals = [ps.get(project)] if project is not None else list(ps.values())
            out.append((l["t"], any(isinstance(v, dict) and v.get("auto") is True for v in vals)))
    return out


def _pulse_since(root, digest_id):
    """The jobs.txt mtime of the newest digest before digest_id with no error.md, or None (every pulse line counts)."""
    d = Path(root) / "digests"
    for p in sorted((x for x in d.iterdir() if DIGEST_RE.fullmatch(x.name) and x.name < digest_id), reverse=True):
        try:
            if not (p / "error.md").exists():
                return (p / "jobs.txt").stat().st_mtime
        except OSError:
            pass
    return None


def _pulse_since_any(root, digest_id):
    """The newest of _pulse_since(root, digest_id) and every other registered project's (projects(), this repo skipped
    by resolved path) digest jobs.txt mtime, or None when none counts: pulse.log is machine-wide, so write_pulse never
    re-reports what another project's digest already did. A digest counts when its name matches DIGEST_RE, it has no
    error.md and its jobs.txt mtime is before this digest's own digests/<digest_id>/jobs.txt mtime (now when missing).
    An OSError on a project's digests skips that project."""
    found = [t] if (t := _pulse_since(root, digest_id)) is not None else []
    cutoff = _mtime(Path(root) / "digests" / digest_id / "jobs.txt")
    cutoff = time.time() if cutoff is None else cutoff
    me = Path(root).resolve().parent
    for repo in projects().values():
        try:
            if repo.resolve() == me:
                continue
            for p in (repo / "scrum" / "digests").iterdir():
                if DIGEST_RE.fullmatch(p.name) and not (p / "error.md").exists():
                    if (at := _mtime(p / "jobs.txt")) is not None and at < cutoff:
                        found.append(at)
        except OSError:
            continue
    return max(found, default=None)


def _board_job(cache, name, n):
    """Project `name`'s board job numbered n, or None (a project not in projects(), an unreadable board or a missing
    job). cache: {name: board jobs}."""
    if name not in cache:
        try:
            cache[name] = read_board(projects()[name] / "scrum")["jobs"]
        except (KeyError, OSError, ValueError, SystemExit):
            cache[name] = []
    return next((j for j in cache[name] if (m := re.match(r"(\d+)-", str(j.get("id")))) and int(m.group(1)) == n), None)


PULSE_TICK_CAP_S = 120  # write_pulse: a pulse.log line counts as at most this many seconds (a gap means no ticks)
PULSE_STRETCH_MIN = 30  # write_pulse: an idle stretch over this many rounded minutes is listed with its times
PULSE_LAST_S = 60  # write_pulse: the last line counts one tick


def write_pulse(root, digest_id):
    """digests/<NNN>/pulse.md: pulse.log totals since the newest digest of any registered project (_pulse_since_any:
    pulse.log is machine-wide, so every figure below uses that one window). Lines sort by time; a line lasts
    the seconds to the next line, capped at PULSE_TICK_CAP_S (the last line PULSE_LAST_S), so no total passes the window plus one
    tick, however many lines a minute holds; totals are rounded whole minutes. Only projects with Auto continue on
    (`auto` True; a line without it is off) count toward idle. Idle with claimable work (no session, no cool-down,
    some auto-on project with claimable or waiting work, and the line's cpu_load and swap within MAX_CPU_LOAD_PCT /
    MAX_SWAP_PCT; then, only when one qualifies, `Idle stretches over PULSE_STRETCH_MIN min:` each stretch whose
    rounded minutes pass it, oldest first, joined by `; `: its first idle line's t to its last idle line's t plus that
    line's seconds), held by machine guard (would be idle but over either limit; ends an idle stretch), gated (would be
    idle, within both limits, but the line's top-level `gates` (serve.py pulse_tick) is non-empty, or no auto-on
    project has claimable work and every auto-on project with waiting work has non-empty `gates`; ends an idle
    stretch; minutes per token, overlap:<id> counted as overlap; a missing or null `gates` is ungated), idle held by
    cool down (no session, cool-down, some claimable or waiting work), idle paused (no session, no cool-down, work
    only in projects with Auto continue off), idle held by the machine guard (would be idle with claimable work, but
    the line's `guard` (serve.py pulse_tick) is a non-empty string; ends an idle stretch; a line without it counts
    as before), peaks, claims during cool-down (each job number in a rise of a project's numeric top job number
    between two lines at most PULSE_TICK_CAP_S apart; a null top in the earlier line is 0, a project absent from it
    rises nothing; only jobs on the board (_board_job), started_by hand listed apart as Hand-started, started_by shop
    skipped: cool-down never stops the shop, started_by digest skipped: serve.py digest_apply's bookkeeping job), claims while
    CPU load over 500% (only the lines' `started` entries, serve.py's own non-manual starts, whose launch-time `cpu`
    is a number over 500; a missing or malformed `started` adds nothing), other starts while CPU load over 500% (rise
    jobs at a line whose cpu_load is over 500 that no `started` entry names (started_by runall and shop skipped): hand, unregistered (project not in
    projects()) or other; a registered project's job off the board is skipped), minutes the focus project had
    claimable work while another project was busy, and every claim (any cool-down or load, less hand) by its board
    job's `account` (none: the first account; job not on the board: unknown), in accounts() order. A line's per-project
    readings count only for projects in projects() (test fixtures never inflate a total; Other starts still names an
    unregistered one); no filter when it is empty."""
    since = _pulse_since_any(root, digest_id)
    lines = sorted((l for l in _json_lines(pulse_path()) if is_num(l.get("t")) and "orphan_killed" not in l
                    and "idle_release" not in l
                    and (since is None or l["t"] >= since)),  # serve.py stop_orphans' kill lines are no tick
                   key=lambda l: l["t"])  # in time order, so no total passes the window when two writers interleave
    out = [f"# Pulse: digest {digest_id}", ""]
    if not lines:
        out.append("No pulse lines since the last digest.")
    else:
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes")
        known = set(projects())
        raw = lambda l: {k: v for k, v in (l.get("projects") if isinstance(l.get("projects"), dict) else {}).items()
                         if isinstance(v, dict)}
        projs = lambda l: {k: v for k, v in raw(l).items() if not known or k in known}  # test fixtures count nothing
        pos = lambda v: is_num(v) and v > 0
        over = lambda l, key, cap: is_num(l.get(key)) and l[key] > cap
        gates = lambda v: [g for g in v if isinstance(g, str)] if isinstance(v, list) else []
        idle = cooled = paused = guard = streak = longest = nonfocus = gated = guarded = 0
        by_gate, stretches = {}, []  # stretches: [first idle t, last idle t + its secs, streak secs] per idle stretch
        for l, nxt in zip(lines, lines[1:] + [None]):
            dt = min(nxt["t"] - l["t"], PULSE_TICK_CAP_S) if nxt else PULSE_LAST_S
            ps = projs(l)
            on = [p for p in ps.values() if p.get("auto") is True]  # Auto continue off never counts as idle
            work = lambda p: pos(p.get("claimable")) or pos(p.get("waiting"))
            if l.get("sessions") == 0 and not l.get("cooldown") and any(work(p) for p in on):
                # a project's gates gate it when it has no claimable work, or when they hold a `held:<why>` token
                # (serve.py pulse_tick: the hold that skipped its ready job or run-all start)
                waits = [[g for g in gates(p.get("gates")) if not pos(p.get("claimable")) or g.startswith("held:")]
                         for p in on if work(p)]
                why = gates(l.get("gates")) or (sum(waits, []) if all(waits) else [])
                if over(l, "cpu_load", MAX_CPU_LOAD_PCT) or over(l, "swap", MAX_SWAP_PCT):
                    guard, streak = guard + dt, 0
                elif why:
                    gated, streak = gated + dt, 0
                    for g in dict.fromkeys("overlap" if g.startswith("overlap:") else g for g in why):
                        by_gate[g] = by_gate.get(g, 0) + dt
                elif isinstance(l.get("guard"), str) and l["guard"]:
                    guarded, streak = guarded + dt, 0
                else:
                    if not streak:  # this line starts a stretch
                        stretches.append([l["t"], 0, 0])
                    idle, streak = idle + dt, streak + dt
                    longest = max(longest, streak)
                    stretches[-1][1:] = [l["t"] + dt, streak]
            else:
                streak = 0
                if l.get("sessions") == 0 and any(work(p) for p in ps.values()):
                    if l.get("cooldown"):
                        cooled += dt
                    else:
                        paused += dt  # work only in projects with Auto continue off
            f = l.get("focus") if isinstance(l.get("focus"), str) else None
            if pos(ps.get(f, {}).get("claimable")) and any(p.get("busy") is True for k, p in ps.items() if k != f):
                nonfocus += dt
        idle, cooled, paused, guard, longest, nonfocus, gated, guarded = (
            round(x / 60) for x in (idle, cooled, paused, guard, longest, nonfocus, gated, guarded))
        long_idle = [(a, b, m) for a, b, secs in stretches if (m := round(secs / 60)) > PULSE_STRETCH_MIN]
        num = lambda j: str(int(m[1])) if (m := re.match(r"(\d+)-", j)) else j
        hot, started = {}, set()
        for l in lines:
            for e in l.get("started") if isinstance(l.get("started"), list) else []:
                if isinstance(e, dict) and isinstance(e.get("project"), str) and isinstance(e.get("job"), str):
                    started.add((e["project"], num(e["job"])))
                    if is_num(e.get("cpu")) and e["cpu"] > 500:
                        hot.setdefault(e["project"], []).append(num(e["job"]))
        claimed, handed, boards, by_acc = {}, {}, {}, {}
        others = {"hand": {}, "unregistered": {}, "other": {}}
        names = [a.name for a in accounts()]
        for a, b in zip(lines, lines[1:]):
            if b["t"] - a["t"] > PULSE_TICK_CAP_S:
                continue  # a gap: the rise may span a reset or pruned board, so it counts no claim
            pa, pb = raw(a), raw(b)  # unfiltered, so Other starts can name an unregistered project
            for name, p in pb.items():
                was, top = pa.get(name, {}).get("top"), p.get("top")
                if name in pa and was is None:
                    was = 0  # no jobs yet: the first job is a claim
                if not (is_num(was) and is_num(top) and top > was):
                    continue
                for n in range(int(was) + 1, int(top) + 1):
                    job = _board_job(boards, name, n)
                    hand = (job or {}).get("started_by") == "hand"
                    shop = (job or {}).get("started_by") == "shop"  # a shop Mac claim: cool-down and this Mac's CPU never hold the shop
                    if (is_num(b.get("cpu_load")) and b["cpu_load"] > 500 and (name, str(n)) not in started
                            and (job or {}).get("started_by") != "runall" and not shop):  # a run-all job creation is no start: its launch is a later serve.py start
                        group = "unregistered" if name not in known else None if job is None else "hand" if hand else "other"
                        if group:  # a registered project's job off the board: pruned or reset, no start to name
                            others[group].setdefault(name, []).append(str(n))
                    if known and name not in known:
                        continue  # an unregistered project's rise is no claim
                    digest = (job or {}).get("started_by") == "digest"  # digest_apply's bookkeeping job: no claim, not Trevor's
                    if job is not None and b.get("cooldown") is True and not shop and not digest:
                        (handed if hand else claimed).setdefault(name, []).append(str(n))
                    if hand:
                        continue
                    acc = "unknown" if job is None else job.get("account") or names[0]  # no account: the first
                    by_acc[acc] = by_acc.get(acc, 0) + 1
        jobs = lambda d: ", ".join(f"{n} {' '.join(v)}" for n, v in d.items())
        count = lambda d: f"{sum(map(len, d.values()))}" + (" — " + jobs(d) if d else "")
        groups = [f"{g} {jobs(d)}" for g, d in others.items() if d]

        def peak(key):
            nums = [l for l in lines if is_num(l.get(key))]
            return max(nums, key=lambda l: l[key]) if nums else None
        s, c = peak("sessions"), peak("cpu_load")
        focus = next((l["focus"] for l in reversed(lines) if isinstance(l.get("focus"), str)), "none")
        out += [f"Window: {iso(lines[0]['t'])} to {iso(lines[-1]['t'])} · ticks: {len(lines)}",
                f"Idle with claimable work: {idle} min (longest stretch {longest} min)",
                *([f"Idle stretches over {PULSE_STRETCH_MIN} min: " + "; ".join(
                    f"{iso(a)} to {iso(b)} ({m} min)" for a, b, m in long_idle)] if long_idle else []),
                f"Gated with claimable work: {gated} min"
                + (" (" + ", ".join(f"{g} {round(v / 60)}" for g, v in by_gate.items()) + ")" if gated else ""),
                f"Held by machine guard: {guard} min",
                f"Idle held by cool down: {cooled} min",
                f"Idle paused: Auto continue off: {paused} min",
                f"Idle held by the machine guard: {guarded} min",
                f"Peak sessions: {s['sessions']} at {iso(s['t'])}" if s else "Peak sessions: unknown",
                f"Peak CPU load: {c['cpu_load']:.0f}% at {iso(c['t'])}" if c else "Peak CPU load: unknown",
                f"Claims during cool down: {count(claimed)}",
                f"Hand-started during cool down: {count(handed)}",
                f"Claims while CPU load over 500%: {count(hot)}",
                f"Other starts while CPU load over 500%: {sum(len(v) for d in others.values() for v in d.values())}"
                + (" — " + "; ".join(groups) if groups else ""),
                f"Non-focus work while focus had claimable work: {nonfocus} min (focus: {focus})",
                "Claims by account: " + (", ".join(f"{k} {by_acc[k]}" for k in sorted(by_acc, key=lambda k: (
                    k == "unknown", names.index(k) if k in names else len(names)))) or "none")]
    (Path(root) / "digests" / digest_id / "pulse.md").write_text("\n".join(out) + "\n")


PROCESSES_NEWEST = 10  # write_processes: run lines and changed glob matches shown per process


def write_processes(root, digest_id):
    """digests/<NNN>/processes.md: per PROCESSES entry, in order, its code, its processes.log runs since the last
    digest (_pulse_since; none: every line) and its state files. A run counts when its t is numeric and at or after the
    cutoff, its process is the entry's name and its result a string; a run whose `repo` resolves to another checkout
    than root's parent is left out (no repo: every project's). Runs: the count by result (most first, ties by name),
    false alarms (a fail whose string head a later counted pass of the same process has), and the time from numeric
    `secs` (whole minutes), then the PROCESSES_NEWEST newest lines, newest first. Files: a plain path is missing,
    changed since the last digest (mtime at or after the cutoff, or no cutoff) or unchanged; a glob lists its changed
    matches relative to root, sorted, PROCESSES_NEWEST at most."""
    since = _pulse_since(root, digest_id)
    me = os.path.realpath(Path(root).parent)
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes")
    show = lambda v: v if isinstance(v, str) else json.dumps(v, default=str)
    changed = lambda p: since is None or p.stat().st_mtime >= since
    runs = [l for l in _json_lines(processes_path()) if is_num(l.get("t")) and (since is None or l["t"] >= since)
            and isinstance(l.get("process"), str) and isinstance(l.get("result"), str)
            and ("repo" not in l or os.path.realpath(str(l["repo"])) == me)]
    runs = [l for _, l in sorted(enumerate(runs), key=lambda x: (x[1]["t"], x[0]))]  # time order, file order on ties
    out = [f"# Processes: digest {digest_id}", "",
           f"Since: {iso(since)}" if since is not None else "Since: the start"]
    for name, code, files in PROCESSES:
        mine = [l for l in runs if l["process"] == name]
        out += ["", f"## {name}", "Code: " + (", ".join(code) or "none")]
        if mine:
            counts = {}
            for l in mine:
                counts[l["result"]] = counts.get(l["result"], 0) + 1
            line = f"Runs: {len(mine)} (" + ", ".join(
                f"{r} {n}" for r, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))) + ")"
            alarms = sum(1 for i, l in enumerate(mine) if l["result"] == "fail" and isinstance(l.get("head"), str)
                         and any(m["result"] == "pass" and m.get("head") == l["head"] for m in mine[i + 1:]))
            if alarms:
                line += f" · false alarms: {alarms}"
            secs = [l["secs"] for l in mine if is_num(l.get("secs"))]
            if secs:
                line += f" · time: {round(sum(secs) / 60)} min total, longest {round(max(secs) / 60)} min"
            out.append(line)
            for l in reversed(mine[-PROCESSES_NEWEST:]):
                rest = " ".join(f"{k}={show(v)}" for k, v in l.items() if k not in ("t", "process", "result"))
                out.append(f"- {iso(l['t'])} {l['result']}" + (f" {rest}" if rest else ""))
        else:
            out.append("Runs: none logged since the last digest")
        out.append("Files:" if files else "Files: none")
        for f in files:
            if "*" in f:
                hits = sorted(str(p.relative_to(root)) for p in Path(root).glob(f) if changed(p))
                more = f" (+{len(hits) - PROCESSES_NEWEST} more)" if len(hits) > PROCESSES_NEWEST else ""
                out.append(f"- {f}: " + (", ".join(hits[:PROCESSES_NEWEST]) + more if hits
                                         else "none changed since the last digest"))
            else:
                p = Path(root) / f
                out.append(f"- {f}: " + ("missing" if not p.exists() else "changed since the last digest"
                                         if changed(p) else "unchanged"))
    (Path(root) / "digests" / digest_id / "processes.md").write_text("\n".join(out) + "\n")


def write_waste(root, digest_id):
    """digests/<NNN>/waste.md: every project's waste.log catches since the last digest (_pulse_since; none: every
    line). A catch counts when its t is numeric (not a bool) and at or after the cutoff and its kind is in WASTE_KINDS.
    `## Counts` gives each kind's catches in WASTE_KINDS order (zeros too; a catch naming two jobs counts once), then
    `## Catches` one line per catch, oldest first (file order on ties): `- <UTC time> <kind>` and every other key as
    key=value, strings bare and other values as JSON. With no catch the file is `No catches since the last digest`."""
    since = _pulse_since(root, digest_id)
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes")
    show = lambda v: v if isinstance(v, str) else json.dumps(v, default=str)
    catches = [l for l in _json_lines(waste_path()) if is_num(l.get("t")) and (since is None or l["t"] >= since)
               and isinstance(l.get("kind"), str) and l["kind"] in WASTE_KINDS]
    catches = [l for _, l in sorted(enumerate(catches), key=lambda x: (x[1]["t"], x[0]))]  # time order, file order on ties
    path = Path(root) / "digests" / digest_id / "waste.md"
    if not catches:
        path.write_text("No catches since the last digest\n")
        return
    out = [f"# Waste: digest {digest_id}", "", f"Since: {iso(since)}" if since is not None else "Since: the start",
           "", "## Counts"]
    out += [f"- {k}: {sum(1 for l in catches if l['kind'] == k)}" for k in WASTE_KINDS]
    out += ["", "## Catches"]
    for l in catches:
        rest = " ".join(f"{k}={show(v)}" for k, v in l.items() if k not in ("t", "kind"))
        out.append(f"- {iso(l['t'])} {l['kind']}" + (f" {rest}" if rest else ""))
    path.write_text("\n".join(out) + "\n")


MODEL_RANK = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}  # write_tokens' pricier-model rule, cheapest first
TOKENS_FLAG = {"median_x": 2, "top": 3, "agent_share": 0.4, "agent_share_min_usd": 1.00, "round_share": 0.8,
              "top_cost_min_usd": 1.00}  # write_tokens' ## Flagged limits
TOKENS_TRANSCRIPTS = 6  # transcript lines under a flagged job's costliest agent


def _model_family(model):
    """The MODEL_RANK family a transcript model string names, else None (`<synthetic>`, a missing model)."""
    return next((f for f in MODEL_RANK if f in model.lower()), None) if isinstance(model, str) else None


def _token_reasons(job, usd, groups, lane_median, top):
    """write_tokens' ## Flagged reasons for one job, in the fixed order: pricier model than the agent's pin, over
    TOKENS_FLAG median_x its lane median, a top-cost job costing at least top_cost_min_usd, one of 2 or more agents over agent_share of a job costing at least agent_share_min_usd, a
    reviewer's later round at round_share or more of its round 1. (write_tokens adds _two_sessions and _two_agents after them.)"""
    out, by_agent, by_round = [], {}, {}
    for (agent, rnd, model), (_, a) in groups.items():
        by_agent[agent] = by_agent.get(agent, 0) + a
        by_round[agent, rnd] = by_round.get((agent, rnd), 0) + a
    for (agent, _, model), _ in sorted(groups.items(), key=lambda g: -g[1][1]):
        pin, fam = agent_pin(agent) if agent != "main" else None, _model_family(model)
        reason = f"{agent} ran on {model}, pinned {pin}"
        if pin in ("sonnet", "haiku") and fam and MODEL_RANK[fam] > MODEL_RANK[pin] and reason not in out:
            out.append(reason)
    if lane_median and usd > TOKENS_FLAG["median_x"] * lane_median:
        out.append(f"{usd / lane_median:.1f}x lane median (${lane_median:.2f})")
    if job in top and usd >= TOKENS_FLAG["top_cost_min_usd"]:
        out.append("top 3 cost")
    for agent, a in sorted(by_agent.items(), key=lambda x: -x[1]):  # a one-agent job is always 100% that agent
        if usd >= TOKENS_FLAG["agent_share_min_usd"] and len(by_agent) > 1 and a > TOKENS_FLAG["agent_share"] * usd:
            out.append(f"{agent} {100 * a / usd:.0f}% of job cost")
    for (agent, rnd), a in sorted(by_round.items(), key=lambda x: (x[0][0], x[0][1] or 0)):
        base = by_round.get((agent, 1), 0)
        if agent.startswith("scrum-review-") and isinstance(rnd, int) and rnd >= 2 and base > 0 \
                and a >= TOKENS_FLAG["round_share"] * base:
            out.append(f"{agent} round {rnd} ${a:.2f} = {100 * a / base:.0f}% of round 1 ${base:.2f}")
    return out


def _two_sessions(rows):
    """write_tokens' `two sessions` reasons for one job's rows: for each agent type, every pair of its subagent
    transcripts under different parent sessions (<session>/subagents/agent-*.jsonl -> <session>) whose spans (min to max
    ts of that transcript's rows) overlap. Each reads `two sessions: <agent> HH:MM-HH:MM and HH:MM-HH:MM, wasted $x`,
    the USD being the shorter run's (local time)."""
    runs = {}
    for r in rows:
        p = Path(r["transcript"])
        if p.parent.name != "subagents":
            continue
        run = runs.setdefault((r["agent"], str(p)), {"parent": p.parent.parent, "lo": r["ts"], "hi": r["ts"], "usd": 0})
        run["lo"], run["hi"], run["usd"] = min(run["lo"], r["ts"]), max(run["hi"], r["ts"]), run["usd"] + row_cost(r)
    out, hm = [], lambda t: datetime.fromtimestamp(t).strftime("%H:%M")
    items = sorted(runs.items(), key=lambda kv: (kv[0][0], kv[1]["lo"], kv[0][1]))
    for i, ((agent, _), a) in enumerate(items):
        for (agent2, _), b in items[i + 1:]:
            if agent2 == agent and a["parent"] != b["parent"] and a["lo"] < b["hi"] and b["lo"] < a["hi"]:
                short = min(a, b, key=lambda x: (x["hi"] - x["lo"], x["usd"]))
                out.append(f"two sessions: {agent} {hm(a['lo'])}-{hm(a['hi'])} and {hm(b['lo'])}-{hm(b['hi'])}, "
                           f"wasted ${short['usd']:.2f}")
    return out


def _two_agents(rows):
    """write_tokens' `two agents` reasons for one job's rows: every pair of subagent transcripts of the same agent type
    under the SAME parent session, naming the same job in their own first prompt (row `prompt_job`), whose spans overlap.
    Runs with no prompt job or the unknown agent `subagent` are skipped. Reads `two agents: <agent> HH:MM-HH:MM and
    HH:MM-HH:MM, wasted $x`, the USD being the shorter run's (local time)."""
    runs = {}
    for r in rows:
        p = Path(r["transcript"])
        pj = r.get("prompt_job")
        if p.parent.name != "subagents" or r["agent"] == "subagent" or not isinstance(pj, str) or not pj:
            continue
        run = runs.setdefault((r["agent"], str(p)), {"parent": p.parent.parent, "job": pj, "lo": r["ts"],
                                                     "hi": r["ts"], "usd": 0})
        run["lo"], run["hi"], run["usd"] = min(run["lo"], r["ts"]), max(run["hi"], r["ts"]), run["usd"] + row_cost(r)
    out, hm = [], lambda t: datetime.fromtimestamp(t).strftime("%H:%M")
    items = sorted(runs.items(), key=lambda kv: (kv[0][0], kv[1]["lo"], kv[0][1]))
    for i, ((agent, _), a) in enumerate(items):
        for (agent2, _), b in items[i + 1:]:
            if agent2 == agent and a["parent"] == b["parent"] and a["job"] == b["job"] \
                    and a["lo"] < b["hi"] and b["lo"] < a["hi"]:
                short = min(a, b, key=lambda x: (x["hi"] - x["lo"], x["usd"]))
                out.append(f"two agents: {agent} {hm(a['lo'])}-{hm(a['hi'])} and {hm(b['lo'])}-{hm(b['hi'])}, "
                           f"wasted ${short['usd']:.2f}")
    return out


def _costliest_detail(rows):
    """The indented lines under a flagged job: its costliest agent, that agent's tool calls and image Reads (over its
    distinct transcripts), its peak context and at most TOKENS_TRANSCRIPTS transcript lines."""
    by_agent = {}
    for r in rows:
        by_agent[r["agent"]] = by_agent.get(r["agent"], 0) + row_cost(r)
    agent = max(by_agent, key=lambda a: (by_agent[a], a))
    mine = [r for r in rows if r["agent"] == agent]
    paths = list(dict.fromkeys(r["transcript"] for r in mine))
    tools, images = {}, 0
    for p in paths:
        names, n = transcript_tools(p)
        images += n
        for k, v in names.items():
            tools[k] = tools.get(k, 0) + v
    top = sorted(tools.items(), key=lambda x: (-x[1], x[0]))[:10]
    out = [f"  - costliest: {agent} ${by_agent[agent]:.2f}",
           "  - tools: " + (", ".join(f"{k} {v}" for k, v in top) or "none"),
           f"  - image reads: {images}",
           f"  - peak context: {max(r['input_tokens'] + r['cache_read_input_tokens'] for r in mine):,} tokens"]
    if len(paths) > TOKENS_TRANSCRIPTS:
        keep = TOKENS_TRANSCRIPTS - 1
        return out + [f"  - transcript: {p}" for p in paths[:keep]] + [f"  - transcript: +{len(paths) - keep} more"]
    return out + [f"  - transcript: {p}" for p in paths]


def write_tokens(root, digest_id):
    """digests/<NNN>/tokens.md: what each job in the digest's jobs.txt cost and why, from transcript_tokens over a window
    from the earliest listed job's creation (feature.md, else spec.md, mtime) to now, never longer than JOB_COST_DAYS,
    kept to this root's registered project and the listed jobs. `Window:` names it in UTC minutes. `## Jobs`: one line
    per job with rows, costliest first (lane, added lines from _fit_diff, usd, tokens, tokens per added line or `-`) and
    one indented line per (agent, round, model), costliest first; then each job with no rows, in listed order, which
    says so and never reads its diff. `## Flagged`: the jobs _token_reasons flags, costliest first, each with
    _costliest_detail. A lane's median leaves out jobs whose board entry has shop, worker or cloud (None when the lane
    has no other job). Under unittest with no SCRUM_TRANSCRIPTS it reads no transcripts (job_costs' guard), and an
    unregistered root reads none. Overwrites the file on every run."""
    d = Path(root) / "digests" / digest_id
    listed = list(dict.fromkeys(l.strip() for l in (d / "jobs.txt").read_text().splitlines() if l.strip()))
    path = d / "tokens.md"
    if not listed:
        path.write_text("No jobs in this digest\n")
        return
    rows, now = [], time.time()
    floor = now - JOB_COST_DAYS * 86400
    # ponytail: a job created more than JOB_COST_DAYS ago is undercounted, and a feature.md rewritten after creation
    # drops the rows written before the rewrite; the window stays short because transcript_tokens reads ~10 s a day
    made = [t for t in (_mtime(Path(root) / "jobs" / j / "feature.md") or _mtime(Path(root) / "jobs" / j / "spec.md")
                        for j in listed) if t]
    start = max(min(made, default=floor), floor)
    if not ("unittest" in sys.modules and not os.environ.get("SCRUM_TRANSCRIPTS")) and transcripts_dir().is_dir():
        me = Path(root).resolve().parent
        name, want = next((n for n, p in projects().items() if p.resolve() == me), None), set(listed)
        rows = [r for r in transcript_tokens(start, now)
                if r["project"] == name and r["job"] in want] if name is not None else []
    if not rows:
        path.write_text("No transcript rows for this digest's jobs\n")
        return
    try:
        board = {j["id"]: j for j in read_board(root)["jobs"] if isinstance(j, dict) and isinstance(j.get("id"), str)}
    except SystemExit:
        board = {}
    costs = next(iter(cost_by_job(rows).values()))
    groups, by_job = {}, {}
    for r in rows:
        by_job.setdefault(r["job"], []).append(r)
        g = groups.setdefault(r["job"], {})
        tok, usd = g.get((r["agent"], r["round"], r["model"]), (0, 0))
        g[r["agent"], r["round"], r["model"]] = (tok + sum(r[k] for k in TOKEN_KEYS), usd + row_cost(r))
    lane = {j: board.get(j, {}).get("lane") or "standard" for j in costs}
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes")  # write_pulse's format
    out = [f"# Tokens: digest {digest_id}", "", f"Window: {iso(start)} to {iso(now)}", "", "## Jobs"]
    for j in sorted((j for j in listed if j in costs), key=lambda j: -costs[j][1]) + [j for j in listed if j not in costs]:
        if j not in costs:
            out.append(f"- {j} · no transcript rows")
            continue
        try:
            added = _fit_diff(Path(root), board[j])[0] if j in board else None
        except (OSError, ValueError, SystemExit, subprocess.SubprocessError):
            added = None
        tok, usd = costs[j]
        per = f"{round(tok / added):,}" if added else "-"
        out.append(f"- {j} · lane {lane[j]} · +{'?' if added is None else added} lines · ${usd:.2f} · {tok:,} tokens"
                   f" · {per} tokens per added line")
        for (agent, rnd, model), (t, u) in sorted(groups[j].items(), key=lambda g: (-g[1][1], -g[1][0])):
            out.append(f"  - {agent} · round {'-' if rnd is None else rnd} · {model or 'unknown'} · ${u:.2f} · {t:,} tokens")
    ranked = sorted(costs, key=lambda j: (-costs[j][1], j))
    top = {j for j in ranked[:TOKENS_FLAG["top"]] if costs[j][1] > 0}
    medians = {}
    for ln in set(lane.values()):  # a shop, worker or cloud run's agents are not in these transcripts: no median input
        vals = sorted(costs[j][1] for j in costs if lane[j] == ln
                      and not any(board.get(j, {}).get(k) for k in ("shop", "worker", "cloud")))
        mid = len(vals) // 2
        medians[ln] = None if not vals else vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    out += ["", "## Flagged"]
    for j in ranked:
        reasons = _token_reasons(j, costs[j][1], groups[j], medians[lane[j]], top) + _two_sessions(by_job[j]) \
            + _two_agents(by_job[j])
        if reasons:
            out.append(f"- {j} · ${costs[j][1]:.2f} · " + "; ".join(reasons))
            out += _costliest_detail(by_job[j])
    if out[-1] == "## Flagged":
        out.append("None")
    path.write_text("\n".join(out) + "\n")


def weekly_ran(resets_at):
    """True when a weekly/*/window file already holds this 7d window's integer resets_at."""
    d = weekly_dir()
    return any(p.read_text().strip() == str(int(resets_at)) for p in (d.glob("*/window") if d.is_dir() else []))


def cmd_weekly_start(resets_at, now):
    """Claim this 7d window's done jobs from every registered project as weekly digest NNN, under registry_lock(): every
    done job whose updatedAt is in [resets_at - 7 days, now] and that no earlier weekly/*/jobs.txt lists, one absolute
    job-folder path per jobs.txt line. Writes `window` even when no job qualifies (id None then), so a window is tried
    once. A window already claimed claims nothing. Never touches any project's digests/."""
    with registry_lock():
        if weekly_ran(resets_at):
            return {"id": None, "jobs": []}
        d, seen = weekly_dir(), set()
        for p in d.glob("*/jobs.txt") if d.is_dir() else []:
            seen.update(l.strip() for l in p.read_text().splitlines() if l.strip())
        jobs, since = [], resets_at - 7 * 86400
        for repo in projects().values():
            try:
                board = read_board(repo / "scrum")
            except SystemExit as e:  # one broken board.json never holds the other projects' week
                print(f"weekly-start: {repo}: {e}", file=sys.stderr)
                continue
            for j in board["jobs"]:
                path, at = str(repo / "scrum" / "jobs" / j["id"]), _epoch(j.get("updatedAt"))
                if j.get("stage") == "done" and at is not None and since <= at <= now and path not in seen:
                    jobs.append(path)
        digest_id = claim_folder(d)
        (d / digest_id / "window").write_text(f"{int(resets_at)}\n")
        (d / digest_id / "jobs.txt").write_text("".join(f"{j}\n" for j in jobs))
    return {"id": digest_id if jobs else None, "jobs": jobs}


def cmd_digest_trim(root, digest_id):
    """Slim each listed done job's folder to TRIM_KEEP and unblock-*.md, plus ROUND_KEEP in each
    round-<N>/ dir (a round dir with neither is removed); returns the trimmed ids. Idempotent."""
    d = Path(root) / "digests" / str(digest_id)
    if not DIGEST_RE.fullmatch(str(digest_id)) or not (d / "jobs.txt").is_file():
        raise SystemExit(f"no digest {digest_id!r}")
    listed = [l.strip() for l in (d / "jobs.txt").read_text().splitlines() if ID_RE.match(l.strip())]
    trimmed = []
    with locked_board(root) as board:
        for job in board["jobs"]:
            folder = Path(root) / "jobs" / job["id"]
            if job["id"] not in listed or job.get("stage") != "done" or not folder.is_dir():
                continue
            for p in folder.iterdir():
                if (p.name in TRIM_KEEP or UNBLOCK_RE.fullmatch(p.name)) and p.is_file():
                    continue
                if re.fullmatch(r"round-\d+", p.name) and p.is_dir() and not p.is_symlink():
                    for q in p.iterdir():
                        if not (q.name in ROUND_KEEP and q.is_file() and not q.is_symlink()):
                            shutil.rmtree(q) if q.is_dir() and not q.is_symlink() else q.unlink()
                    if not any(p.iterdir()):
                        p.rmdir()
                    continue
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink()
            job["files"], job["diverged"] = job_files(folder), diverged(folder)
            trimmed.append(job["id"])
        (d / "trimmed").write_text(now() + "\n")
    return trimmed


# --- pipeline-fit: per-job routing facts for the digest reader's ## Pipeline fit section. Read-only. ---
FAST_STUB = "Skipped by orchestrator: fast lane."


def _real_review(p):
    """True when p is a review a reviewer wrote, not an orchestrator skip or carried-forward stub."""
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    lines = text.splitlines()
    stub = (len(lines) >= 2 and lines[0].strip() == "VERDICT: PASS"
            and lines[1].startswith(("Carried forward from round", "Skipped by orchestrator:"))
            and "## Findings" not in text)
    return not stub and not ORCH_REVIEW_RE.fullmatch(text) and FAST_STUB not in text


def _fit_diff(root, job):
    """(added, deleted, files, paths) from the worktree, else the PR's REST totals; paths is the (rows, names) pair
    _promote_trigger takes, None when unreadable. (None, None, None, None) when the diff is unreadable."""
    if job.get("worktree") and Path(job["worktree"]).is_dir():
        diff = _route_diff(job)
        if diff is None or any(a is None for a, _, _ in diff[0]):
            return None, None, None, None
        rows, names = diff
        return sum(a for a, _, _ in rows), sum(d for _, d, _ in rows), len(names), diff
    m = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)", job.get("pr") or "")
    if not m:
        return None, None, None, None
    try:
        pr = gh_api(Path(root), f"repos/{m[1]}/{m[2]}/pulls/{m[3]}")
        out = tuple(pr[k] for k in ("additions", "deletions", "changed_files"))
    except (GhError, TypeError, KeyError):
        return None, None, None, None
    if not all(type(v) is int for v in out):
        return None, None, None, None
    if out[0] + out[1] > FAST_MAX_LINES or out[2] > FAST_MAX_FILES:
        return *out, None  # too big to be over-routed: no files call
    try:  # one page is enough: at most FAST_MAX_FILES files
        listed = gh_api(Path(root), f"repos/{m[1]}/{m[2]}/pulls/{m[3]}/files")
        rows = [(f["additions"], f["deletions"], f["filename"]) for f in listed]
        names = [n for f in listed for n in (f["filename"], f.get("previous_filename")) if n is not None]
    except (GhError, TypeError, KeyError, AttributeError):
        return *out, None
    ok = all(type(a) is int and type(d) is int and type(p) is str for a, d, p in rows) \
        and all(type(n) is str for n in names)
    return *out, ((rows, names) if ok else None)


FIT_PATH_RE = re.compile(r"prod|migrat|payment", re.I)


def _bumped_lane(folder) -> bool:
    """True when feature.md's first block (before the first `## ` line) has a `Lane:` line naming both `bumped` and
    `sensitive`: the spec writer raised the lane on purpose."""
    try:
        text = (folder / "feature.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False
    for line in text.splitlines():
        if line.startswith("## "):
            return False
        low = line.lower()
        if line.startswith("Lane:") and "bumped" in low and "sensitive" in low:
            return True
    return False


def _fit_excluded(folder, lane: str, paths) -> bool:
    """True when a job could never have run on a cheaper lane: a diff name matches SENSITIVE_RE (Fast lane would
    promote it), spec.md's `Hard stops:` is not `none`, feature.md starts with `Critical:` or has a
    LILGUY_HARD_STOP_RE word, or a debug job has assessment.md."""
    if paths and any(SENSITIVE_RE.search(n) for n in paths[1]):
        return True
    read = lambda f: f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
    hard = re.search(r"^\s*Hard stops:(.*)$", read(folder / "spec.md"), re.M)
    feature = read(folder / "feature.md")
    return bool(hard and hard[1].strip().lower() != "none" or feature.startswith("Critical:")
                or LILGUY_HARD_STOP_RE.search(_request_text(feature)) or lane == "debug" and (folder / "assessment.md").is_file())


def _fit_job(root, job_id: str, job: dict, globs) -> dict:
    """One pipeline-fit row for job_id (its board entry `job`, {} when gone): lane, agents spawned, diff size,
    verdicts per round, fix rounds, over_routed and the cheapest lane that would have done; `excluded`
    (_fit_excluded) is never over_routed. A fast job fits lilguy on one clean round with a lilguy-sized, readable,
    non-UI diff that _promote_trigger passes."""
    folder = Path(root) / "jobs" / job_id
    lane = job.get("lane") or "standard"
    rounds = sorted(int(p.name[6:]) for p in folder.glob("round-*")
                    if re.fullmatch(r"round-\d+", p.name) and p.is_dir())
    agents = [a for a, f in (("spec", "spec.md"), ("builder", "build.md")) if (folder / f).is_file()]
    agents += [f"review-{r}" for r in REVIEWERS if any(_real_review(folder / f"round-{n}" / f"review-{r}.md")
                                                       for n in rounds)]
    agents += ["approver"] if (folder / "decision.md").is_file() else []
    verdicts = {str(n): {r: first_word(folder / f"round-{n}" / f"review-{r}.md", ("PASS", "CHANGES"))
                         for r in REVIEWERS} for n in rounds}
    added, deleted, files, paths = _fit_diff(root, job)
    size = None if added is None else added + deleted
    sensitive = _bumped_lane(folder) or bool(paths and any(FIT_PATH_RE.search(n) for n in paths[1]))
    excluded = _fit_excluded(folder, lane, paths)
    over = (not sensitive and not excluded and lane in ("standard", "debug") and "1" in verdicts and set(verdicts["1"].values()) == {"PASS"}
            and size is not None and size <= FAST_MAX_LINES and files <= FAST_MAX_FILES
            and paths is not None and _promote_trigger(*paths) is None
            and not (globs and any(glob_match(n, globs) for n in paths[1])))
    fit = ("lilguy" if size <= LILGUY_MAX_LINES and files <= LILGUY_MAX_FILES else "fast") if over else lane
    if (lane == "fast" and not sensitive and not excluded and len(rounds) <= 1  # one clean round, lilguy-sized
            and "CHANGES" not in verdicts.get("1", {}).values()
            and size is not None and size <= LILGUY_MAX_LINES and files <= LILGUY_MAX_FILES
            and paths is not None and _promote_trigger(*paths) is None
            and not (globs and any(glob_match(n, globs) for n in paths[1]))):
        fit = "lilguy"  # over_routed stays False: it scores standard/debug only
    return {"id": job_id, "lane": lane, "agents": agents, "added": added, "deleted": deleted, "files": files,
            "verdicts": verdicts, "fix_rounds": max(max(rounds, default=1) - 1, 0), "over_routed": over, "fit": fit,
            "sensitive": sensitive, "excluded": excluded}


def cmd_pipeline_fit(root, digest_id: str) -> dict:
    """{"digest", "jobs"}: for each job in digests/<NNN>/jobs.txt, its lane, agents spawned, diff size, verdicts per
    round, fix rounds, and whether a standard/debug job that passed round 1 on a fast-sized diff was over-routed: never
    when its paths are unreadable, _promote_trigger would have promoted it, or a path matches UI globs."""
    d = Path(root) / "digests" / str(digest_id)
    if not DIGEST_RE.fullmatch(str(digest_id)) or not (d / "jobs.txt").is_file():
        raise SystemExit(f"no digest {digest_id!r}")
    listed = [l.strip() for l in (d / "jobs.txt").read_text().splitlines() if ID_RE.match(l.strip())]
    jobs = {j["id"]: j for j in read_board(root)["jobs"]}
    globs = ui_globs(root)
    return {"digest": str(digest_id), "jobs": [_fit_job(root, job_id, jobs.get(job_id, {}), globs) for job_id in listed]}


# --- digest-trevor: Trevor's own words (chat, feature.md quotes, backlog tags, answer notes) for the digest reader ---
TREVOR_MAX_BYTES = 40000
TREVOR_JEV_QUESTION = ("Trevor is correcting or complaining about how the dev pipeline behaved, or stating a rule it "
                       "should follow from now on")
TREVOR_CHAT_MAX = 1500  # per message sent to Jev; jev-rank.py's own MAX_CHARS
TREVOR_CONTEXT_MAX = 300  # chars of the assistant message a chat quote replied to
TREVOR_QUOTE_MAX = 400
TREVOR_SKIP_PREFIXES = ("<command-", "<local-command", "Caveat:")
TREVOR_MATCH_WORDS = 6  # words in a row a job's feature.md must share with a chat quote to be listed under it


def jev_rank_path() -> Path:
    return Path(os.environ.get("SCRUM_JEV_RANK") or Path.home() / ".claude" / "scripts" / "jev-rank.py")


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _trevor_previous(root, digest_id):
    """The highest-numbered digest folder below digest_id with no error.md, or None."""
    d = Path(root) / "digests"
    below = [p for p in d.iterdir() if DIGEST_RE.fullmatch(p.name) and int(p.name) < int(digest_id) and p.is_dir()
             and not (p / "error.md").exists()]
    return max(below, key=lambda p: int(p.name), default=None)


def _trevor_text(content):
    """A user entry's typed text, or None when it carries a tool_result or no text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    return "\n".join(b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"
                     and isinstance(b.get("text"), str))


def _trevor_messages(root, since):
    """[(date, one-line text, context)] Trevor typed in interactive sessions since `since` (epoch), about this repo or scrum."""
    repo = Path(root).resolve().parent
    out = []
    for proj in sorted(transcripts_dir().iterdir()):  # OSError here (no transcripts dir) fails the whole section
        for f in sorted(proj.glob("*.jsonl")) if proj.is_dir() else []:
            try:
                if f.stat().st_mtime < since:
                    continue
            except OSError:
                continue
            first = True
            context = ""  # latest assistant text in this file, cut to TREVOR_CONTEXT_MAX
            for d in _json_lines(f):
                if d.get("type") == "assistant":
                    am = d.get("message")
                    ac = am.get("content") if isinstance(am, dict) else None
                    if isinstance(ac, str):
                        atext = ac
                    elif isinstance(ac, list):
                        atext = " ".join(b["text"] for b in ac if isinstance(b, dict) and b.get("type") == "text"
                                         and isinstance(b.get("text"), str))
                    else:
                        atext = ""
                    atext = re.sub(r"\s+", " ", atext).strip()
                    if atext:
                        context = atext[:TREVOR_CONTEXT_MAX]
                    continue
                if d.get("type") != "user":
                    continue
                if first and d.get("entrypoint") == "sdk-cli":
                    break  # a headless scrum session, not Trevor
                first = False
                at = _epoch(d.get("timestamp"))
                msg = d.get("message")
                text = _trevor_text(msg.get("content")) if isinstance(msg, dict) else None
                if d.get("isMeta") or d.get("isCompactSummary") or at is None or at < since or text is None:
                    continue
                text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.S).strip()
                if not text or text.startswith(TREVOR_SKIP_PREFIXES):
                    continue
                cwd = d.get("cwd")
                here = isinstance(cwd, str) and Path(cwd).resolve().is_relative_to(repo)
                if here or "scrum" in text.lower():
                    out.append((_iso(at), re.sub(r"\s+", " ", text)[:TREVOR_CHAT_MAX], context))
    return out


def _trevor_words(text):
    """text's words for _trevor_matches: lowercased, apostrophes dropped (`don't` is `dont`), split at every other
    non-word character."""
    return re.findall(r"\w+", re.sub(r"['’]", "", text.lower()))


def _trevor_matches(root, quotes):
    """{quote: [`<repo>/<job id> (<stage>)`]}: every job, in this project then each registered one (projects()), whose
    jobs/*/feature.md holds TREVOR_MATCH_WORDS words of the quote in a row (_trevor_words folds case and punctuation).
    <stage> is the job's board stage, `?` when it is off the board; an unreadable board or feature.md is skipped. A
    quote shorter than that matches nothing."""
    n, grams = TREVOR_MATCH_WORDS, {}
    for q in quotes:
        w = _trevor_words(q)
        for i in range(len(w) - n + 1):
            grams.setdefault(tuple(w[i:i + n]), set()).add(q)
    out, firsts = {q: [] for q in quotes}, {g[0] for g in grams}
    scrums = dict.fromkeys([Path(root).resolve(), *((p / "scrum").resolve() for p in projects().values())])
    for scrum in scrums if grams else []:
        try:
            stages = {j.get("id"): j.get("stage") for j in read_board(scrum)["jobs"]}
        except (SystemExit, OSError):
            stages = {}
        for feature in sorted((scrum / "jobs").glob("*/feature.md")):
            try:
                w = _trevor_words(feature.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            hit = set()
            for i in range(len(w) - n + 1):
                if w[i] in firsts:
                    hit |= grams.get(tuple(w[i:i + n]), set())
            for q in hit:
                out[q].append(f"{scrum.parent.name}/{feature.parent.name} ({stages.get(feature.parent.name) or '?'})")
    return out


def _trevor_chat(root, since):
    """The ## Chat lines: Jev's pick of Trevor's messages, each followed by its context line and its _trevor_matches
    lines, or one failure line."""
    try:
        msgs = _trevor_messages(root, since)
    except OSError as e:
        return [f"- Transcripts failed: {e}"]
    if not msgs:
        return []
    dates = {}
    for at, text, context in msgs:
        dates.setdefault(text, (at, context))
    script = jev_rank_path()
    if not script.is_file():
        return [f"- Jev failed: no script at {script}"]
    try:
        r = subprocess.run([sys.executable, str(script), TREVOR_JEV_QUESTION, "--top", "60", "--min", "0.8"],
                           input="".join(f"{t}\n" for t in dates), capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return ["- Jev failed: timed out after 300 s"]
    except OSError as e:
        return [f"- Jev failed: {e}"]
    if r.returncode:
        tail = (r.stderr.strip().splitlines() or [""])[-1]
        return [f"- Jev failed: exit {r.returncode}" + (f": {tail[:300]}" if tail else "")]
    picks = [(score, text) for score, sep, text in (l.partition("\t") for l in r.stdout.splitlines())
             if sep and text.strip()]
    matched = _trevor_matches(root, [text for _, text in picks])
    out = []
    for score, text in picks:
        at, context = dates.get(text, ("?", ""))
        out.append(f'- {at} {score}: "{text[:TREVOR_QUOTE_MAX]}"')
        if context:
            out.append(f"  context: {context}")
        out += [f"  matched: {m}" for m in matched[text]]
    return out


def _trevor_tags(line):
    """Each `(Trevor …)` in line, from `(Trevor` to its matching `)`."""
    tags, i = [], line.find("(Trevor")
    while i >= 0:
        depth = 0
        for j in range(i, len(line)):
            depth += {"(": 1, ")": -1}.get(line[j], 0)
            if depth == 0:
                tags.append(line[i:j + 1])
                break
        else:
            break  # unclosed: no tag
        i = line.find("(Trevor", j + 1)
    return tags


def _trevor_backlog(root, d, prev, since):
    """The ## Backlog lines: backlog lines with a Trevor tag new since the previous digest. Writes trevor-backlog.txt."""
    path = Path(root) / "backlog.md"
    if not path.is_file():
        return []
    lines = [l.strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.startswith("- [")]
    seen_file = prev / "trevor-backlog.txt" if prev else None
    seen = set(seen_file.read_text().splitlines()) if seen_file and seen_file.is_file() else None
    day = datetime.fromtimestamp(since, timezone.utc).date().isoformat()
    out, every = [], []
    for line in lines:
        tags = _trevor_tags(line)
        every += tags
        if seen is not None:
            new = any(t not in seen for t in tags)
        else:
            new = any((m := re.match(r"\(Trevor (\d{4}-\d{2}-\d{2})", t)) and m.group(1) >= day for t in tags)
        if new:
            out.append(f"- {line[2:]}")
    (d / "trevor-backlog.txt").write_text("".join(f"{t}\n" for t in dict.fromkeys(every)))
    return out


def _trevor_quotes(root, d):
    """The ## Feature quotes lines: each `Trevor YYYY-MM-DD` line of every digested job's feature.md."""
    out, jobs_txt = [], d / "jobs.txt"
    for job_id in (l.strip() for l in jobs_txt.read_text().splitlines()) if jobs_txt.is_file() else []:
        feature = Path(root) / "jobs" / job_id / "feature.md"
        if ID_RE.match(job_id) and feature.is_file():
            out += [f"- {job_id}: {l.strip()[:TREVOR_QUOTE_MAX]}"
                    for l in feature.read_text(encoding="utf-8", errors="replace").splitlines()
                    if re.search(r"Trevor \d{4}-\d{2}-\d{2}", l)]
    return out


def _trevor_notes(root, since):
    """The ## Answer notes lines: questions.log lines since `since` that carry a typed note."""
    out = []
    for q in _json_lines(Path(root) / "questions.log"):
        at, note = _epoch(q.get("date")), q.get("note")
        if at is not None and at >= since and isinstance(note, str) and note.strip():
            out.append(f'- {q["date"]} {q.get("job")} {q.get("pick") or q.get("action")}: "{note}"')
    return out


def cmd_digest_trevor(root, digest_id) -> dict:
    """Write digests/<NNN>/trevor.md: Trevor's typed chat messages (Jev-ranked, each with a `  matched:` line per job
    whose feature.md quotes it), feature.md quotes, new backlog tags and answer notes since the previous live digest
    (else 7 days). A failing source is a one-line note; never raises then."""
    d = Path(root) / "digests" / str(digest_id)
    if not DIGEST_RE.fullmatch(str(digest_id)) or not d.is_dir():
        raise SystemExit(f"no digest {digest_id!r}")
    prev = _trevor_previous(root, digest_id)
    if prev:
        st = prev.stat()
        since = getattr(st, "st_birthtime", st.st_mtime)
    else:
        since = time.time() - 7 * 86400
    sections, counts = {}, {}
    for key, heading, read in (("chat", "## Chat", lambda: _trevor_chat(root, since)),
                               ("quotes", "## Feature quotes", lambda: _trevor_quotes(root, d)),
                               ("backlog", "## Backlog", lambda: _trevor_backlog(root, d, prev, since)),
                               ("notes", "## Answer notes", lambda: _trevor_notes(root, since))):
        try:
            items = read()
        except (OSError, ValueError) as e:  # one broken source never costs the digest the others
            items = [f"- {heading[3:]} failed: {e}"]
        failed = len(items) == 1 and items[0].startswith(("- Jev failed:", "- Transcripts failed:",
                                                          f"- {heading[3:]} failed:"))
        quotes = [i for i in items if not i.startswith(("  context: ", "  matched: "))]
        sections[heading], counts[key] = items or ["None"], 0 if failed else len(quotes)
    body = [f"# Trevor: digest {digest_id}", f"Since: {_iso(since)}"]
    for heading, items in sections.items():
        body += [heading, *items]
    text = "".join(f"{l}\n" for l in body)
    if len(text.encode()) > TREVOR_MAX_BYTES:
        marker = f"- truncated at {TREVOR_MAX_BYTES} bytes\n"
        kept, size = [], len(marker.encode())
        for l in body:
            if size + len(l.encode()) + 1 > TREVOR_MAX_BYTES:
                break
            kept.append(l)
            size += len(l.encode()) + 1
        text = "".join(f"{l}\n" for l in kept) + marker
    (d / "trevor.md").write_text(text)
    return {"id": str(digest_id), **counts}


# --- digest-questions: questions.md's ## Repeated questions and ## Stops, computed from questions.log (Digest step 1)
QUESTIONS_WINDOW_DAYS = 7  # only lines dated within this many days of the log's newest date count


def _trevor_since(d):
    """(value, epoch) of digests/<NNN>/trevor.md's `Since:` line, or (None, None) when the file, the line or a value
    _epoch parses is missing."""
    try:
        text = (d / "trevor.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    value = next((l[len("Since:"):].strip() for l in text.splitlines() if l.startswith("Since:")), None)
    at = _epoch(value)
    return (value, at) if at is not None else (None, None)


QUESTION_NORM_RES = tuple(re.compile(p) for p in (r"\b\d{3,}-[a-z0-9-]+",  # job ids
                                                  r"\S*/\S*",  # whitespace-free tokens holding `/`: paths, branches
                                                  r"\b[\w-]+\.[a-z0-9]{1,5}\b",  # file names
                                                  r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b",  # commit hashes
                                                  r"\d+"))  # the remaining digits


def question_norm(text: str) -> str:
    """text lowercased, then job ids, tokens holding `/`, file names, commit hashes and digits removed in that order,
    whitespace collapsed: the key that groups one question asked about different jobs."""
    text = text.lower()
    for pattern in QUESTION_NORM_RES:
        text = pattern.sub("", text)
    return " ".join(text.split())


STOP_CAUSE_CUT_RE = re.compile(r"\. |[(,;]| — | (?=\d)")
STOP_CAUSE_WORDS = 6


def stop_cause(text: str) -> str:
    """A stop's cause from its reason (else question): `can't resume yet` read as `cannot resume yet`, cut at the first
    `. `, `(`, `,`, `;`, ` — ` or space before a digit, the first STOP_CAUSE_WORDS words, trailing spaces and colons
    stripped; `(no reason)` when nothing is left."""
    text = STOP_CAUSE_CUT_RE.split(text.replace("can't resume yet", "cannot resume yet"), maxsplit=1)[0]
    return " ".join(text.split()[:STOP_CAUSE_WORDS]).rstrip(" :") or "(no reason)"


def _join_picks(keys, picks, jobs):
    """{ask index: pick index}: each ask (keys maps its line index to its question or cause key) takes the next pick
    line (an index in picks) of its job (jobs[i]) after it, unless that job asks a different key first. An ask with no
    such pick is left out: unanswered."""
    pending, joined = {}, {}
    for i in sorted([*keys, *picks]):
        job = jobs[i]
        if i not in keys:
            joined.update(dict.fromkeys(pending.pop(job, (None, []))[1], i))
        elif job in pending and pending[job][0] == keys[i]:
            pending[job][1].append(i)
        else:
            pending[job] = (keys[i], [i])
    return joined


RESUME_RUN_RE = re.compile(r"(\d{8}-\d{6})-resume-(.+)\.log")


def _resume_runs(root):
    """{job id: newest UTC stamp (epoch)} of runs/<YYYYMMDD-HHMMSS>-resume-<job>.log names, read in one pass; {} when
    runs/ is missing."""
    newest = {}
    try:
        names = os.listdir(Path(root) / "runs")
    except OSError:
        return newest
    for name in names:
        if not (m := RESUME_RUN_RE.fullmatch(name)):
            continue
        try:
            at = datetime.strptime(m[1], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        newest[m[2]] = max(at, newest.get(m[2], at))
    return newest


def _pick_counts(labels):
    """`<label> <n>` entries joined by `, `: highest count first, then by label."""
    return ", ".join(f"{l} {n}" for l, n in sorted(Counter(labels).items(), key=lambda c: (-c[1], c[0])))


def cmd_digest_questions(root, digest_id) -> dict:
    """Write digests/<NNN>/questions.md, the `## Repeated questions` lines and `## Stops` table the digest reader copies
    as written, from this project's questions.log (only lines dated within QUESTIONS_WINDOW_DAYS of its newest date),
    runs/ file names and trevor.md's `Since:` line (missing or unparseable: any date counts as after it). Same inputs,
    same bytes. Returns {"id", "questions": entries listed, "stops": table rows}."""
    root = Path(root)
    d = root / "digests" / str(digest_id)
    if not DIGEST_RE.fullmatch(str(digest_id)) or not d.is_dir():
        raise SystemExit(f"no digest {digest_id!r}")
    since_text, since = _trevor_since(d)
    dated = [(at, q) for q in _json_lines(root / "questions.log") if (at := _epoch(q.get("date"))) is not None]
    newest = max((at for at, _ in dated), default=None)
    cutoff = None if newest is None else newest - QUESTIONS_WINDOW_DAYS * 86400
    log = [(at, q) for at, q in dated if at >= cutoff]  # file order
    jobs = [str(q.get("job")) for _, q in log]
    batch_open = TERMINAL_BATCH_QUESTION.split(":", 1)[0] + ":"  # `project .claude edits:`
    asks = [i for i, (_, q) in enumerate(log) if q.get("pick") is None and isinstance(q.get("question"), str)
            and q["question"].strip()]
    batch = {i for i in asks if log[i][1]["question"].startswith(batch_open)}
    counted = {i: question_norm(log[i][1]["question"]) for i in asks if i not in batch
               and log[i][1].get("auto") is not True and log[i][1].get("kind") not in ("stall", "machine", "refused")}
    picks = [i for i, (_, q) in enumerate(log) if q.get("pick") is not None and q.get("auto") is not True]
    # a Terminal batch ask's pick is dropped with it, so first join the batch asks along with the counted ones
    joined = _join_picks({**counted, **{i: question_norm(log[i][1]["question"]) for i in batch}}, picks, jobs)
    batch_picks = {joined[i] for i in batch if i in joined}
    picks = [i for i in picks if i not in batch_picks]

    def label(i):
        return str(log[i][1]["pick"]).strip().lower()

    def after_since(idx):
        return any(since is None or log[i][0] > since for i in idx)

    joined = _join_picks(counted, picks, jobs)
    groups = {}
    for i, text in counted.items():
        groups.setdefault(text, []).append(i)
    entries = []
    for text, idx in groups.items():
        if len(idx) < 3 or not after_since(idx):
            continue
        labels = [label(joined[i]) if i in joined else "unanswered" for i in idx]
        line = (f'- {len(idx)} × "{text}" — picks: {_pick_counts(labels)} — jobs: '
                f'{", ".join(dict.fromkeys(jobs[i] for i in idx))}')
        won = sorted(((n, l) for l, n in Counter(labels).items() if l != "unanswered"), reverse=True)
        if won and won[0][0] >= 3 and (len(won) == 1 or won[1][0] < won[0][0]):
            line += f" — DEFAULT: {won[0][1]}" + (" (unanimous)" if won[0][0] == len(idx) else "")
        entries.append((-len(idx), text, line))
    repeated = [line for *_, line in sorted(entries)]

    def cell(text):
        return text.replace("|", "/")  # a `|` would split the table cell

    causes = {}
    for i, (_, q) in enumerate(log):
        if q.get("pick") is None and i not in batch and (
                q.get("kind") in HEALTH_STOP_KINDS or (q.get("kind") is None and q.get("question") is not None)):
            causes[i] = stop_cause(next((t for t in (q.get("reason"), q.get("question")) if isinstance(t, str)
                                         and t.strip()), ""))
    joined = _join_picks({i: c.casefold() for i, c in causes.items()}, picks, jobs)
    resumed = _resume_runs(root) if causes else {}
    rows = {}
    for i, cause in causes.items():
        rows.setdefault(cause.casefold(), []).append(i)
    table = []
    for idx in rows.values():
        cause, stopped = causes[idx[0]], [log[i][1] for i in idx]
        labels = [label(joined[i]) if i in joined else "resume" if resumed.get(jobs[i], log[i][0]) > log[i][0]
                  else "unanswered" for i in idx]
        recent = list(dict.fromkeys(jobs[i] for i in reversed(idx)))[:3][::-1]
        automate = (len(idx) >= 2 and "unanswered" not in labels and len(set(labels)) == 1 and after_since(idx)
                    and not all(q.get("kind") == "refused" for q in stopped)
                    and not all(q.get("auto") is True for q in stopped))
        table.append((-len(idx), cause, f"| {cell(cause)} | {len(idx)} | {cell(', '.join(recent))} | "
                                        f"{cell(_pick_counts(labels))} | {'yes' if automate else 'no'} |"))
    stops = [line for *_, line in sorted(table)]
    body = [f"# Questions: digest {digest_id}", f"Since: {since_text or 'none'}",
            f"Window: {_iso(cutoff)} to {_iso(newest)}" if newest is not None else "Window: none",
            "## Repeated questions", *(repeated or ["None"]),
            "## Stops", *(["| Cause | Count | Jobs | Picks | Automate |", "|---|---|---|---|---|", *stops] if stops
                          else ["None"])]
    (d / "questions.md").write_text("".join(f"{l}\n" for l in body), encoding="utf-8")
    return {"id": str(digest_id), "questions": len(repeated), "stops": len(stops)}


# --- process-health: 10 fixed metrics per digest, each compared with the previous digest's (Digest step 1). ---
HEALTH_LIMITS = {"stops_per_job": 0.5, "resume_abort_stops": 0, "waiting_on_job_stops": 0, "unreadable_asks": 0,
                 "cheaper_lane_jobs": 0, "test_waste_jobs": 0, "fable_misuse": 0, "unused_windows": 0,
                 "overburned_windows": 0, "not_shipped": 0}
HEALTH_UNUSED_PCT = 15  # a window left more than this % unused at reset
HEALTH_EARLY_90_SHARE = 0.2  # a window that reached 90% more than this share of its span before reset burned too early
HEALTH_WAITING_RE = re.compile(r"(?i)blocked on sibling|waiting (?:on|for) (?:job |another job|\d{3})")
HEALTH_UNREADABLE_RE = re.compile(r"[\w.-]*/[\w.-]+\.[A-Za-z]{1,5}\b|\brule \d+\b", re.I)


def unreadable_question(question):
    """True when an ask question is over 40 words or names a path or "rule N"."""
    return len(question.split()) > 40 or bool(HEALTH_UNREADABLE_RE.search(question))


def resume_abort_only(commands):
    """True when an ask offers options and every option command is a `resume ` or `abort ` (lanes/stops.md)."""
    return bool(commands) and all(isinstance(c, str) and c.startswith(("resume ", "abort ")) for c in commands)


HEALTH_STOP_KINDS = ("ask", "stall", "machine", "refused", "bigboy")
HEALTH_TEST_ROLES = ("review-e2e", "review-ui", "review-ux")


def _health_file(path, kind):
    """path's JSON when it parses as `kind` (list or dict), else an empty one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return kind()
    return data if isinstance(data, kind) else kind()


def _previous_health(root, digest_id):
    """(name, metrics) of the highest-numbered earlier digest with a readable health.json and no error.md."""
    digests = Path(root) / "digests"
    for n in sorted((p.name for p in digests.iterdir() if DIGEST_RE.fullmatch(p.name) and p.name < digest_id),
                    reverse=True):
        if (digests / n / "error.md").exists():
            continue
        metrics = _health_file(digests / n / "health.json", dict).get("metrics")
        if isinstance(metrics, dict):
            return n, metrics
    return None, {}


def windows_flagged_path():
    """Which digest first flagged each account-wide window: $SCRUM_WINDOWS_FLAGGED, else beside projects.json."""
    return Path(os.environ.get("SCRUM_WINDOWS_FLAGGED") or registry_path().parent / "windows-flagged.json")


def _first_flag_only(owner, hits):
    """Drop from hits (metric -> window names) every window an earlier digest of any project already flagged for that
    metric, so one account-wide window counts once; names carry the card's account (`seven_day-<reset>-owa`), so two
    accounts sharing a reset count apart. Records the new ones under owner; a rerun by the same owner keeps them."""
    path = windows_flagged_path()
    seen = _health_file(path, dict)
    for metric in ("unused_windows", "overburned_windows"):
        mine = []
        for name in hits[metric]:
            if seen.setdefault(f"{metric}:{name}", owner) == owner:
                mine.append(name)
        hits[metric] = mine
    try:  # ponytail: no lock, two digests finishing in the same instant could both count a window
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, seen)
    except OSError:
        pass


def _burned_early(b, span, reset):
    """True when a window sat at its cap (cap_idle_secs) or reached 90% more than HEALTH_EARLY_90_SHARE of its span
    before its reset."""
    return bool(is_num(b.get("cap_idle_secs")) and b["cap_idle_secs"] > 0
                or span and is_num(b.get("hit_90_at")) and is_num(reset)
                and reset - b["hit_90_at"] > HEALTH_EARLY_90_SHARE * span)


def _flag_weekly(weekly, flagged):
    """Append to flagged the names of the seven_day cards that overburned. With one account that is _burned_early; with
    several, pick_account drains one on purpose while another carries the work, so a card counts only for the time every
    account sat at its cap at once before its reset (cap_idle_secs back from its resets_at). Returns {name: hours} for
    those multi-account flags. Once a card names an account, every configured account (accounts()) counts too, so an
    account with no card in this digest (staggered resets) counts as never held."""
    accounts_seen = {a for _, a, *_ in weekly}
    if any(accounts_seen):
        try:
            accounts_seen |= {a.name for a in accounts()}
        except SystemExit:  # a bad SCRUM_ACCOUNTS: the cards' own accounts only
            pass
    if len(accounts_seen) < 2:
        flagged += [n for n, _, reset, b, span in weekly if _burned_early(b, span, reset)]
        return {}
    held = {}  # account -> (start, end) intervals held at the cap
    for _, acc, reset, b, _ in weekly:
        if is_num(reset) and is_num(b.get("cap_idle_secs")) and b["cap_idle_secs"] > 0:
            held.setdefault(acc, []).append((reset - b["cap_idle_secs"], reset))
    names = sorted(accounts_seen)
    both = held.get(names[0], [])
    for acc in names[1:]:
        both = [(max(s, c), min(e, f)) for s, e in both for c, f in held.get(acc, []) if max(s, c) < min(e, f)]
    hours = {}
    for name, acc, reset, b, _ in weekly:
        if acc in held and is_num(reset) and is_num(b.get("cap_idle_secs")) and b["cap_idle_secs"] > 0:
            lo = reset - b["cap_idle_secs"]
            secs = sum(max(0, min(reset, e) - max(lo, s)) for s, e in both)
            if secs > 0:
                hours[name] = round(secs / 3600, 1)
    flagged += list(hours)
    return hours


FIT_RANK = {"lilguy": 0, "fast": 1, "standard": 2, "debug": 2}  # cheaper_lane_jobs: a fit below its lane


def cmd_process_health(root, digest_id: str) -> dict:
    """{"digest", "previous", "metrics", "auto_stalls"}: HEALTH_LIMITS' metrics over the jobs in digests/<NNN>/jobs.txt, from
    questions.log, each job's routing.log, fable.log and round reviews, the digest's pipeline-fit.json and windows.json,
    pulse.log (unused_windows skips a window whose pulse lines all have Auto continue off in every project) and
    board.json; a window counts only in the first digest, across projects, that flags it (windows_flagged_path); each carries the previous digest's value and a flag ("worse", "over twice" or null). A missing or
    broken input counts 0. auto_stalls ({"value", "jobs"}, no limit or flag) counts the auto stall lines of those jobs.
    A questions.log line dated at or before the previous digest's Since (cmd_digest_trevor's) is skipped.
    Writes digests/<NNN>/health.json."""
    root = Path(root)
    d = root / "digests" / str(digest_id)
    if not DIGEST_RE.fullmatch(str(digest_id)) or not (d / "jobs.txt").is_file():
        raise SystemExit(f"no digest {digest_id!r}")
    listed = [l.strip() for l in (d / "jobs.txt").read_text().splitlines() if ID_RE.match(l.strip())]
    claimed = set(listed)
    every = {j["id"]: j for j in read_board(root)["jobs"] if isinstance(j, dict) and "id" in j}
    board = {i: j for i, j in every.items() if str(i) in claimed}
    hits = {name: [] for name in HEALTH_LIMITS}  # one entry per counted line, job or window
    main_prs = []  # PR numbers on origin/main, read once and only when a flagged job has a PR

    def on_main():
        if not main_prs:
            try:  # any git failure: empty set, so the flag stands
                subjects = _git(root.parent, "log", "--format=%s", "origin/main").decode(errors="replace").splitlines()
            except (ValueError, OSError, subprocess.SubprocessError):
                subjects = []
            main_prs.append({m[1] for m in map(PR_SUBJECT_RE.search, subjects) if m})
        return main_prs[0]
    last = {}  # job -> kind of its last counted stop line: a stall right after a stall is the same episode
    auto_stalls = []  # one job id per auto stall line: cleared without Trevor, shown on its own line
    earlier = _trevor_previous(root, digest_id)  # cmd_digest_trevor's Since: a job listed again keeps no old lines
    since = getattr(earlier.stat(), "st_birthtime", earlier.stat().st_mtime) if earlier else None
    for q in _json_lines(root / "questions.log"):
        job, kind = q.get("job"), q.get("kind")
        if since is not None and (at := _epoch(q.get("date"))) is not None and at <= since:
            continue  # counted by an earlier digest; a dateless line still counts
        if q.get("auto") is True:  # cleared without Trevor (log_stop auto): never a stop
            if kind == "stall" and str(job) in claimed:
                auto_stalls.append(job)
            continue
        if str(job) not in claimed or not (kind in HEALTH_STOP_KINDS or "question" in q and kind is None):
            continue
        if kind == "machine":
            continue  # every machine wait clears on its own (serve.py, cmd_ready), like an auto line
        if not (kind == "stall" == last.get(job)):
            hits["stops_per_job"].append(job)
        last[job] = kind
        if HEALTH_WAITING_RE.search(str(q.get("reason") or q.get("question") or "")):
            hits["waiting_on_job_stops"].append(job)
        if kind not in (None, "ask"):
            continue
        opts = q.get("options") if isinstance(q.get("options"), list) else []
        if resume_abort_only([str(o.get("command") or "") if isinstance(o, dict) else None for o in opts]):
            hits["resume_abort_stops"].append(job)
        question = str(q.get("question") or "")
        if unreadable_question(question):
            hits["unreadable_asks"].append(job)
    for e in _health_file(d / "pipeline-fit.json", dict).get("jobs") or []:
        if not isinstance(e, dict) or str(e.get("id")) not in claimed:
            continue
        lane, fit = FIT_RANK.get(e.get("lane")), FIT_RANK.get(e.get("fit"))
        if lane is not None and fit is not None and fit < lane and not e.get("sensitive") \
                and e.get("excluded") is not True:  # the pipeline-fit row's own fit; no second heuristic here
            if e.get("lane") == "fast":
                folder = root / "jobs" / str(e["id"])
                recorded = _health_file(folder / "lilguy-fit.json", dict).get("fit")
                if recorded is False or (recorded is not True and _lilguy_refuses(folder)):
                    continue  # lilguy-fit refused it (recorded, else re-checked), so fast was the cheapest lane it could get
            parent = board.get(e["id"], {}).get("parent")
            if parent and every.get(parent, {}).get("lane") != "runall":
                continue  # a fix child of a non-runall (or unknown) parent never reaches Lilguy
            hits["cheaper_lane_jobs"].append(e["id"])
    globs, seconds = ui_globs(root), 0
    for job_id in listed:
        folder = root / "jobs" / job_id
        routed = _json_lines(folder / "routing.log")
        lane = board.get(job_id, {}).get("lane") or "standard"
        reviewed = any(_real_review(p) for r in HEALTH_TEST_ROLES for p in folder.glob(f"round-*/{r}.md"))
        try:
            spec = (folder / "spec.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            spec = ""
        likely = likely_files(spec)
        if globs and not likely:  # no Likely files: ask the real diff; unreadable diff = UI unknown, not waste
            paths = _fit_diff(root, board.get(job_id, {}))[3]
            likely, unknown = (paths[1], False) if paths else ([], True)
        else:
            unknown = False
        no_ui = not unknown and (not globs or not any(glob_match(p, globs) for p in likely))
        if reviewed and (lane == "lilguy" or no_ui):
            spent = sum(r["duration_s"] for r in routed if is_num(r.get("duration_s"))
                        and any(t in str(r.get("role") or "") for t in HEALTH_TEST_ROLES))
            if round(spent / 60) > 0:  # under 30 s shows as 0 minutes: wasted nothing
                hits["test_waste_jobs"].append(job_id)
                seconds += spent
        simple = not job_complex(root, job_id)
        for r in routed:
            role = str(r.get("role") or "")
            if "fable" in str(r.get("model") or "") and (simple or ("planner" not in role and "spec-writer" not in role)):
                hits["fable_misuse"].append(job_id)
        try:
            fable = (folder / "fable.log").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            fable = []
        hits["fable_misuse"] += [job_id for line in fable if simple and line.split("\t")[2:3] == ["fable"]]
        job = board.get(job_id, {})
        if job.get("stage") == "done" and (str(job.get("reason") or "").startswith("merged, not live")
                                          or job.get("lane") not in ("lilguy", "runall", "bigboy", "edit", "ops") and not job.get("pr")):
            m = re.search(r"/pull/(\d+)/?$", str(job.get("pr") or ""))
            if m and m[1] in on_main():  # main holds the PR: a stale reason must not flag it
                continue
            hits["not_shipped"].append(job_id)
    pulse = pulse_auto(_json_lines(pulse_path()))
    weekly = []  # (name, account, reset, budget, span) of every seven_day card, flagged after the loop
    for card in _health_file(d / "windows.json", list):
        b = card.get("budget") if isinstance(card, dict) else None
        if not isinstance(b, dict):
            continue
        account = f"-{card['account']}" if card.get("account") else ""  # main and owa can share a reset
        name, reset = f"{card.get('window')}-{card.get('resets_at')}{account}", card.get("resets_at")
        tokens = card.get("tokens") if isinstance(card.get("tokens"), dict) else {}
        burned = b.get("used_pct") == 0 and is_num(tokens.get("total")) and tokens["total"] > 0  # stale 0% sample
        span = WINDOW_SECS.get(card.get("window"))
        inside = [a for t, a in pulse if span and is_num(reset) and reset - span <= t <= reset]
        paused = bool(inside) and not any(inside)  # Auto continue off in every project all window: a deliberate pause
        if is_num(b.get("left_at_reset_pct")) and b["left_at_reset_pct"] > HEALTH_UNUSED_PCT and not burned and not paused:
            hits["unused_windows"].append(name)
        if card.get("window") == "seven_day":
            weekly.append((name, card.get("account") or "", reset, b, span))
        elif _burned_early(b, span, reset):
            hits["overburned_windows"].append(name)
    held_hours = _flag_weekly(weekly, hits["overburned_windows"])
    _first_flag_only(f"{root}:{digest_id}", hits)
    hits["overburned_windows"] = [f"{n} (every account held {held_hours[n]}h)" if n in held_hours else n
                                  for n in hits["overburned_windows"]]
    prev_id, prev = _previous_health(root, str(digest_id))
    metrics = {}
    for name, limit in HEALTH_LIMITS.items():
        value = (round(len(hits[name]) / len(listed), 2) if listed else None) if name == "stops_per_job" \
            else len(hits[name])
        old = prev.get(name, {}).get("value") if isinstance(prev.get(name), dict) else None
        old = old if is_num(old) else None
        flag = None
        if value is not None and old is not None:
            trend = value > old and (name != "stops_per_job" or len(hits[name]) >= 2)  # one stop is not a trend
            flag = "worse" if trend else "over twice" if value > limit and old > limit else None
        metrics[name] = {"value": value, "previous": old, "limit": limit, "jobs": sorted(set(hits[name])), "flag": flag}
    metrics["test_waste_jobs"]["minutes"] = round(seconds / 60)
    out = {"digest": str(digest_id), "previous": prev_id, "metrics": metrics,
           "auto_stalls": {"value": len(auto_stalls), "jobs": sorted(set(auto_stalls))}}
    _write_json(d / "health.json", out)
    return out


# --- pipeline health: digest-start raises one needs-human job per tool that failed in half its claimed jobs. ---
HEALTH_TITLE = "Pipeline health: "
CHECK_TIMEOUT_RE = re.compile(r"(?i)\btimed out\b")


def _codex_failures(folder):
    """The codex-review routing.log lines that are an invalid artifact or a skip; bad lines and a missing file: none."""
    return [d for d in _json_lines(folder / "routing.log") if d.get("role") == "codex-review"
            and (d.get("outcome") == "invalid-artifact" or d.get("runner") == "skip")]


def _round_text(folder, name):
    """Each round-*/<name> under folder that reads, as text; a trimmed or unreadable one is skipped."""
    out = []
    for p in sorted(folder.glob(f"round-*/{name}")):
        try:
            out.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return out


def pipeline_health_counts(root, jobs: list[str]) -> dict:
    """{tool: [failing job ids]} for codex-review, review-e2e and check; a job counts once per tool."""
    out = {"codex-review": [], "review-e2e": [], "check": []}
    for job_id in jobs:
        folder = Path(root) / "jobs" / job_id
        if _codex_failures(folder):
            out["codex-review"].append(job_id)
        if any("Reviewer produced no output." in t for t in _round_text(folder, "review-e2e.md")):
            out["review-e2e"].append(job_id)
        if any(CHECK_TIMEOUT_RE.search(t) for t in _round_text(folder, "check.md")):
            out["check"].append(job_id)
    return out


def pipeline_health(root, digest_id: str, jobs: list[str]) -> list[str]:
    """For each tool that failed in at least half of jobs (and 2+), create one board job parked at needs-human with a
    closed question, unless a live job of that title is already open. Returns the created ids. cmd_new and cmd_ask
    errors (SystemExit, OSError) propagate."""
    created = []
    for tool, failed in pipeline_health_counts(root, jobs).items():
        if len(failed) < 2 or len(failed) * 2 < len(jobs):
            continue
        title = HEALTH_TITLE + tool
        if tool == "codex-review":
            secs = sum(d["duration_s"] for j in failed for d in _codex_failures(Path(root) / "jobs" / j)
                       if type(d.get("duration_s")) in (int, float))
            lost = f"{round(secs / 60)} min lost"
        else:
            lost = "time lost not logged"
        # unique re-checks the live board under the lock: an open job of this title (needs-human, or one cmd_ask failed
        # to park) means no second one
        if (job_id := cmd_new(root, title, unique=True)) is None:
            continue
        (Path(root) / "jobs" / job_id / "feature.md").write_text(
            f"{title} failed in {len(failed)} of {len(jobs)} jobs in digest {digest_id}, {lost}.\n\n"
            f"Find and fix why {tool} fails across jobs. Failing jobs:\n\n" + "".join(f"- {j}\n" for j in failed))
        cmd_ask(root, job_id, f"pipeline health: {tool} failed in {len(failed)} of {len(jobs)} jobs in digest "
                              f"{digest_id}, {lost}",
                [f"Got it=abort {job_id}", f"Add a fix to the backlog=abort {job_id} --requeue"], title="DIGEST")
        created.append(job_id)
    return created


# --- timing: digest-start writes digests/<NNN>/timing.md, the time each claimed job cost, for ## Time sinks ---
E2E_WAIT_REASON = "waiting on the E2E queue"  # newjob.md Check gate step 2 stalls a job on it (serve.py E2E_WAIT)
CHECK_WAIT_REASON = "waiting on the Check queue"  # the same stall on check.lock (serve.py CHECK_WAIT)
E2E_LOCK_RE = re.compile(r"\bexit 124\b")


def _mins(secs):
    """A duration as `1h05m` or `12m`, rounded to the minute; `-` for None."""
    if secs is None:
        return "-"
    m = max(round(secs / 60), 0)
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m"


def _mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return None


def _build_start(root, job_id):
    """Epoch secs of the earliest runs/*-start-<job_id>.log (named by its UTC spawn time), else None."""
    for p in sorted((Path(root) / "runs").glob(f"*-start-{job_id}.log")):
        try:
            return datetime.strptime(p.name[:15], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _run_starts(root, job_id, skip=()):
    """Sorted epoch secs of every runs/<YYYYMMDD-HHMMSS>-<action>-<job_id>.log (one per board.spawn), any action but `skip`."""
    out = []
    for p in (Path(root) / "runs").glob(f"*-{job_id}.log"):
        if (m := re.fullmatch(r"\d{8}-\d{6}-([a-z]+)-" + re.escape(job_id) + r"\.log", p.name)) and m[1] not in skip:
            try:
                out.append(datetime.strptime(p.name[:15], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).timestamp())
            except ValueError:
                continue
    return sorted(out)


def _waited(prev, end, starts, mtimes, human=()):
    """Secs of [prev, end] spent waiting: each start in the window runs to the next file mtime (else end), and each
    `human` (start, end) span is clipped to the window; overlaps count once."""
    spans = sorted([(w, min(next((t for t in mtimes if t > w), end), end)) for w in starts if prev <= w < end]
                   + [(max(a, prev), min(b, end)) for a, b in human])
    total, upto = 0, prev
    for a, b in spans:
        a = max(a, upto)
        if b > a:
            total, upto = total + b - a, b
    return total


def _deps_done_at(job, by_id):
    """The latest board updatedAt (epoch secs) of job's depends_on blockers when every one is in by_id ({id: board
    job}) at stage done with an updatedAt _epoch reads; None otherwise (no depends_on, no by_id, a blocker missing, not
    done or undated)."""
    deps = job.get("depends_on")
    if by_id is None or not isinstance(deps, list) or not deps:
        return None
    ends = []
    for d in deps:
        b = by_id.get(d) if isinstance(d, str) else None
        if not isinstance(b, dict) or b.get("stage") != "done" or (at := _epoch(b.get("updatedAt"))) is None:
            return None
        ends.append(at)
    return max(ends)


def _head_spans(v):
    """The (start, end) epoch spans a current-gates.json head entry holds (note_current_gate, job 1593); an entry with no
    usable `spans` (old shape, bare epoch) is its "held" secs as one span from 0, else none: old heads all start together,
    so their union is the longest, the result before spans existed."""
    if not isinstance(v, dict):
        return []
    spans = v.get("spans")
    if isinstance(spans, list):
        good = [(a, b) for sp in spans if isinstance(sp, (list, tuple)) and len(sp) == 2
                for a, b in [sp] if type(a) in (int, float) and type(b) in (int, float) and b >= a]
        if good:
            return good
    held = v.get("held")
    if type(held) in (int, float) and held > 0:
        return [(0, held)]
    return []


def _union_secs(spans):
    """Total seconds covered by `spans` (start, end pairs), overlaps counted once."""
    total, upto = 0, None
    for a, b in sorted(spans):
        a = a if upto is None else max(a, upto)
        if b > a:
            total, upto = total + b - a, b
    return total


def _timing_row(root, job_id, job, stalls, waits=(), human=(), queued=(), by_id=None):
    """(row cells, wall secs, rounds, no-change rounds, E2E lock waits, stall secs to resume) for one claimed job. The no-change cell is the count and the later round of each
    equal pair, e.g. `2 (rounds 2,3)`. Created is feature.md's
    mtime (else spec.md's), Spec starts at claimed-at.txt (cmd_ready) when sane, the wait before it counting as Queue; a shop run (board `worker`/`shop`) ends Spec at shop-at.txt (serve.py shop_tick; else the claim, else feature.md) and shows done minus that as Cloud, the last cell; with no spec.md (a lilguy job) feature.md to the first run log is Queue; done is the board updatedAt; each round's time runs from the previous round's last file
    (round 1: the build start, see _build_start) to its own last file, less the queue/machine waits in `waits` (epoch secs) and the needs-human `human` (start, end) spans, shown in Human wait.
    Each dep-waits.txt line (cmd_wait_on: `<epoch> <blocker>`) runs to the job's next run log (_run_starts), else
    spec.md's mtime; clipped to the Spec window, it moves from Spec to Queue. `stalls` maps a job id to its stall
    epochs (None: no date); the Stalls cell gives each one's minutes to the next run log, `open` when none, `?` for None,
    then `limit <min>` (`limit open`) for each limit-holds.txt line (serve.py hold_limited: `<epoch> <account>`, job 1561)
    to the next run log, lines before the same run log counted once from the earliest, its span subtracted from the
    round like `waits`, then ` (held: <tokens>)` from stall-holds.txt (serve.py note_stall_hold: what auto_resume passed it over for).
    Each `queued` epoch (a questions.log queue-wait line) runs to the job's next run log, else the round's end, is
    subtracted like `waits` and adds one to E2E lock waits. An autoPlayed job's Round times start `paused `, and a job
    whose board entry lists depends_on gets each `depends_on:<id>` added to queue-gates.txt's gates (job 1587). Every
    gate prints its held minutes, longest first, ties in file order (job 1558): its head's "held" seconds in
    current-gates.json (note_current_gate), 0m with none, e.g. `vm_pressure 6h10m, cpu_queue 0m`; a depends_on:<id>
    gate's are the Queue pieces before that blocker's updatedAt when by_id has it at stage done, else its held
    seconds, else the whole Queue. With a Queue over 0, each head's minutes are clipped to it and the Queue less the
    longest depends_on head less the union of the other heads' held spans (job 1593), floored at 0, prints last as `unnamed <m>` when it rounds to
    1m or more (jobs 1568, 1587).
    by_id (write_timing's {id: board job}): when every depends_on blocker is on it at stage done (_deps_done_at), the
    Queue cell is `<total> (<after> after depends_on)`, <after> being the part of each Queue piece (feature.md to the
    claim, each dep-waits.txt span, spec.md to round 1's start) after the latest blocker's updatedAt."""
    folder = Path(root) / "jobs" / job_id
    created = _mtime(folder / "feature.md") or _mtime(folder / "spec.md")
    done, spec_at = _epoch(job.get("updatedAt")), _mtime(folder / "spec.md")
    wall = done - created if done and created else None
    try:  # cmd_ready's claim (a BigBoy child; a hand start has none)
        claimed = float((folder / "claimed-at.txt").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        claimed = None
    cloud = None
    if job.get("worker") or job.get("shop"):  # a shop run: spec.md and every round file are stamped when its artifacts came home, so Spec ends at the dispatch
        try:
            cloud = float((folder / "shop-at.txt").read_text(encoding="utf-8").strip())  # serve.py shop_tick, at the stage-cloud mark
        except (OSError, ValueError):
            cloud = claimed or created  # jobs dispatched before shop-at.txt: the claim wrote feature.md within minutes of it
        spec_at = cloud
    rounds = sorted(int(p.name[6:]) for p in folder.glob("round-*") if re.fullmatch(r"round-\d+", p.name) and p.is_dir())
    start = _build_start(root, job_id)
    qfrom = spec_at or created  # no spec.md (a lilguy job): feature.md to the first run log is Queue
    pre_human = 0  # a shop job that stopped needs-human before its home build: the shop run and the wait are not Queue (job 1508)
    if cloud and start and start >= qfrom:
        stop = min((a for a, _ in human if qfrom <= a < start), default=None)
        rework = next((r for r in _run_starts(root, job_id) if stop is not None and stop < r <= start), None)
        if rework:
            pre_human, qfrom = rework - stop, rework
    if qfrom and start and start >= qfrom:
        queue = start - qfrom
    else:  # no start log (a Run all or BigBoy child): round 1 starts at the claim or first run log after spec.md, the gap is Queue
        runs = _run_starts(root, job_id, ("resume",))  # a resume continues a session, it never starts round 1
        claim = claimed
        first = None if start or not qfrom else claim if claim and claim > qfrom else next((r for r in runs if r > qfrom), None)
        start, queue = (first, first - qfrom) if first else (spec_at, 0 if spec_at else None)
    pieces = [(qfrom, qfrom + queue)] if queue else []  # each (from, to) the Queue adds up, for `after depends_on`
    times, hwaits, heads, prev = [], [], [], start or created
    mtimes = sorted(t for q in folder.rglob("*") if (t := _mtime(q))) if waits else []
    runs = _run_starts(root, job_id)
    after = lambda t: next((r for r in runs if r > t), None)
    qspans = [(w, after(w) or float("inf")) for w in queued]
    try:  # serve.py hold_limited: a usage-limit pause (a hard stop) runs to the next run log, else the round's end
        holds = [float(l.split()[0]) for l in (folder / "limit-holds.txt").read_text(encoding="utf-8").splitlines()
                 if re.fullmatch(r"\d+(\.\d+)? \S+", l.strip())]
    except OSError:
        holds = []
    limits = {}  # next run log (None: open) -> earliest hold before it, so one stop held twice counts once
    for w in sorted(holds):
        limits.setdefault(after(w), w)
    qspans += [(w, nxt or float("inf")) for nxt, w in limits.items()]
    for n in rounds:
        rd = folder / f"round-{n}"
        end = max((t for q in rd.iterdir() if (t := _mtime(q))), default=None)
        machine = _waited(prev, end, waits, mtimes, qspans) if end and prev else 0
        both = _waited(prev, end, waits, mtimes, [*qspans, *human]) if end and prev else 0
        times.append(_mins(end - prev - both if end and prev else None))
        hwaits.append(both - machine)
        prev = end or prev
        try:
            heads.append((rd / "head.txt").read_text(encoding="utf-8", errors="replace").strip())
        except OSError:
            heads.append("")
    same = [n for n, a, b in zip(rounds[1:], heads, heads[1:]) if a and a == b]
    waits = sum(len(E2E_LOCK_RE.findall(t)) for t in _round_text(folder, "check.md")) + len(queued)
    spec = spec_at - created if spec_at and created else None
    # cmd_ready's claim: a BigBoy child's dependency wait counts as Queue, not Spec; with no claim (a hand start) the first run log before spec.md stands in
    claim = claimed if claimed is not None else next((r for r in runs if created and spec_at and created <= r <= spec_at), None)
    spec_from = created
    if claim and spec_at and created and created <= claim <= spec_at:
        spec, queue, spec_from = spec_at - claim, queue + claim - created, claim
        pieces.append((created, claim))
    try:  # cmd_wait_on: a parentless job's dependency wait counts as Queue, not Spec
        dep = [float(l.split()[0]) for l in (folder / "dep-waits.txt").read_text(encoding="utf-8").splitlines()
               if re.fullmatch(r"\d+(\.\d+)? \S+", l.strip())]
    except OSError:
        dep = []
    if dep and spec is not None:
        spans = sorted((max(w, spec_from), min(after(w) or spec_at, spec_at)) for w in dep)
        total, upto = 0, spec_from
        for a, b in spans:  # overlaps count once
            a = max(a, upto)
            if b > a:
                total, upto = total + b - a, b
                pieces.append((a, b))
        total = min(total, spec)
        spec, queue = spec - total, queue + total
    try:  # serve.py note_queue_gate: the launch gates that queued it
        gates = list(dict.fromkeys((folder / "queue-gates.txt").read_text(encoding="utf-8", errors="replace").split()))
    except OSError:
        gates = []
    try:  # note_current_gate's held seconds per head: every gate prints its held time, 0m with none (jobs 1485, 1558)
        seen = json.loads((folder / CURRENT_GATES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = None
    seen = seen if isinstance(seen, dict) else {}
    secs = lambda v: v["held"] if isinstance(v, dict) and type(v.get("held")) in (int, float) and v["held"] > 0 else 0
    held = {g: secs(seen.get(g.split("(", 1)[0])) for g in gates}
    stall_cell, resume = [], 0
    for at in sorted(stalls.get(job_id, ()), key=lambda t: (t is None, t or 0)):  # dated in order, then undated
        nxt = None if at is None else after(at)
        stall_cell.append("?" if at is None else "open" if nxt is None else _mins(nxt - at))
        resume += nxt - at if nxt else 0
    stall_cell += [f"limit {_mins(nxt - w) if nxt else 'open'}" for nxt, w in sorted(limits.items(), key=lambda x: x[1])]
    paused = "paused " if job.get("autoPlayed") and times else ""  # sat paused until serve.py auto_play played it
    if pre_human:  # the stop-to-rework span lies before round 1: it is the first round's Human wait
        hwaits = [(hwaits[0] if hwaits else 0) + pre_human, *hwaits[1:]]
    if queue and wall is not None:  # Queue is part of Wall, never more
        queue = min(queue, wall)
    if isinstance(job.get("depends_on"), list):  # waited on an earlier job by plan, beside any other gate (job 1587)
        gates = list(dict.fromkeys([*gates, *(f"depends_on:{d}" for d in job["depends_on"])]))
    for g in gates:  # job 1558: a depends_on head holds the Queue before its blocker's done updatedAt, else its held time, else all of it
        if g.startswith("depends_on:"):
            dep = (by_id or {}).get(g[11:])
            end = _epoch(dep.get("updatedAt")) if isinstance(dep, dict) and dep.get("stage") == "done" else None
            held[g] = ((held.get(g) or queue or 0) if end is None
                       else min(sum(max(min(b, end) - a, 0) for a, b in pieces), queue or 0))
    if queue:  # job 1568: a head never holds more than the job's own Queue; the rest the longest leaves is unnamed
        held = {g: min(h, queue) for g, h in held.items()}
    cells_g = [f"{g} {_mins(held[g])}" for g in sorted(gates, key=lambda g: -held[g])]
    dep_wait = max((h for g, h in held.items() if g.startswith("depends_on:")), default=0)  # blockers overlap: never summed
    other = _union_secs([sp for g in gates if not g.startswith("depends_on:") for sp in _head_spans(seen.get(g.split("(", 1)[0]))])  # job 1593: heads held at different times add up; overlaps count once
    if queue and _mins(rest := max(queue - dep_wait - other, 0)) != "0m":  # job 1587: a machine gate holds after the depends_on wait
        cells_g.append(f"unnamed {_mins(rest)}")
    gate_cell = ", ".join(cells_g) or "-"
    queue_cell = _mins(queue)
    if queue is not None and (blocked := _deps_done_at(job, by_id)) is not None:  # the part after the planned wait
        after = min(sum(max(b - max(a, blocked), 0) for a, b in pieces), queue)
        queue_cell += f" ({_mins(after)} after depends_on)"
    cells = [job_id, _mins(wall), _mins(spec), queue_cell, gate_cell, str(len(rounds)), paused + ", ".join(times) or "-",
             ", ".join(map(_mins, hwaits)) or "-", f"{len(same)} (rounds {','.join(map(str, same))})" if same else "0", str(waits), ", ".join(stall_cell) or "0",
             _mins(done - cloud if cloud and done and done >= cloud else None)]
    try:  # serve.py note_stall_hold: what held its stalls
        held = (folder / "stall-holds.txt").read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        held = []
    if held:
        cells[10] += f" (held: {', '.join(held)})"
    return cells, wall, len(rounds), len(same), waits, resume


RAM_HOLD_RE = re.compile(r"^\S+ free=(?:(\d+)%|unknown) sessions=(\d+)$", re.M)  # a serve.py note_ram_hold line


def write_timing(root, digest_id, jobs):
    """digests/<NNN>/timing.md: one row per claimed job (wall, spec, queue (with the part after a done depends_on
    blocker's updatedAt: _timing_row's by_id is this board), queue gate = queue-gates.txt (every gate with its held minutes, 0m with none, longest first), rounds, round times, no-change rounds = a
    head.txt equal to the previous round's, E2E lock waits = `exit 124` in check.md plus queue-wait lines, questions.log stall lines, each as
    its minutes to the next run log),
    totals, every job on every registered board (and this one) now stalled or held (queue_waiting) on the E2E queue, and per claimed
    job its ram-holds.txt lines (serve.py note_ram_hold): hold count, free RAM range and session range."""
    board = {j["id"]: j for j in read_board(root)["jobs"]}
    stalls, waits, human, queue = {}, {}, {}, {}
    log, now = list(_json_lines(Path(root) / "questions.log")), time.time()
    for n, q in enumerate(log):  # needs-human spans: as the usage-window "needs-human time" loop
        at = _epoch(q.get("date"))
        if "options" not in q or not at or not isinstance(q.get("job"), str):
            continue
        nxt = next((x_at for x in log[n + 1:] if x.get("job") == q["job"] and (x_at := _epoch(x.get("date")))
                    and not (x.get("kind") == "note" and x.get("action") == "discuss")), None)
        if nxt is None and board.get(q["job"], {}).get("stage") == "needs-human":
            nxt = now
        if nxt is not None:
            human.setdefault(q["job"], []).append((at, nxt))
    for q in log:
        at = _epoch(q.get("date"))
        if at and isinstance(q.get("job"), str) and (q.get("kind") == "machine" or (
                q.get("kind") == "stall" and E2E_WAIT_REASON in str(q.get("reason") or ""))):
            waits.setdefault(q["job"], []).append(at)
        if q.get("kind") == "stall" and isinstance(q.get("job"), str):
            stalls.setdefault(q["job"], []).append(at)
        if q.get("kind") == "queue-wait" and at and isinstance(q.get("job"), str):
            queue.setdefault(q["job"], []).append(at)
    rows = [_timing_row(root, j, board.get(j, {}), stalls, waits.get(j, ()), human.get(j, ()), queue.get(j, ()), board)
            for j in jobs]
    lines = [f"# Timing: digest {digest_id}", "",
             "| Job | Wall | Spec | Queue | Queue gate | Rounds | Round times | Human wait | No-change rounds | E2E lock waits | Stalls | Cloud |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(r[0]) + " |" for r in rows]
    lines += ["", "## Totals",
              f"Jobs: {len(rows)} · wall {_mins(sum(r[1] for r in rows if r[1]))} · rounds {sum(r[2] for r in rows)}"
              f" · no-change rounds {sum(r[3] for r in rows)} in {sum(1 for r in rows if r[3])} jobs"
              f" · E2E lock waits {sum(r[4] for r in rows)} in {sum(1 for r in rows if r[4])} jobs"
              f" · stalls {sum(len(stalls.get(j, ())) for j in jobs)} ({_mins(sum(r[5] for r in rows))} to resume)",
              "", "## Waiting on the E2E queue"]
    waiting, t = [], time.time()
    for scrum in dict.fromkeys([Path(root).resolve(), *((p / "scrum").resolve() for p in projects().values())]):
        try:
            other = read_board(scrum)
        except SystemExit:
            continue
        for j in other["jobs"]:
            at = _epoch(j.get("updatedAt"))
            if at and (stalled(j) and E2E_WAIT_REASON in str(j.get("reason") or "")
                       or queue_waiting(j) and j["reason"].startswith(E2E_QUEUE_WAIT)):
                waiting.append(f"- {scrum.parent.name}/{j['id']}: {_mins(t - at)}")
    lines += waiting or ["None"]
    lines += ["", "## RAM holds"]
    holds = []
    for j in jobs:
        try:
            text = (Path(root) / "jobs" / j / "ram-holds.txt").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        got = RAM_HOLD_RE.findall(text)
        if not got:
            continue
        free = [int(f) for f, _ in got if f]
        n = [int(c) for _, c in got]
        holds.append(f"- {j}: {len(got)} holds, free RAM " + (f"{min(free)}%-{max(free)}%" if free else "unknown")
                     + f", sessions {min(n)}-{max(n)}")
    lines += holds or ["None"]
    (Path(root) / "digests" / digest_id / "timing.md").write_text("\n".join(lines) + "\n")


# --- escapes: digest-start writes digests/<NNN>/escapes.md, each bug job traced by git blame to its origin job ---
ESCAPE_SKIP_RE = re.compile(r"(^|/)(__tests__|e2e|tests?)/|(^|/)test_[^/]*\.py$|\.(test|spec)\.[cm]?[jt]sx?$")
ESCAPE_JOB_RE = re.compile(r"scrum/jobs/([^/\s]+)/")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? ", re.M)
BLAME_SHA_RE = re.compile(r"^([0-9a-f]{40,64}) \d+ \d+", re.M)
ESCAPE_UI_RE = re.compile(r"\.(tsx|jsx|css|scss|html)$", re.I)
ESCAPE_SECURITY_RE = re.compile(r"auth|injection|secret|token|password|session|permission|xss|data exposure", re.I)
ESCAPE_BUG_LANE_RE = re.compile(r"^Lane:.*\bbug\b", re.M | re.I)  # `Lane: lilguy — bug, cause pinned: ...`


def _escape_lines(repo, bug, board, root=None):
    """The escapes.md lines for bug job `bug` (_bug_job): its newest HEAD commit naming scrum/jobs/<bug>/, each non-test
    file's -a,b hunks blamed on <sha>^, and every other board job named in a blamed commit's body, with its last-round PASSes
    (a PASS whose jobs/<origin>/round-<last>/review-<name>.md under `root` is missing or a skip stub is left out; `ui` is left out
    unless a blamed file matches ESCAPE_UI_RE, `security` unless the bug's feature.md matches ESCAPE_SECURITY_RE)."""
    shas = _git(repo, "log", "HEAD", "-F", f"--grep=scrum/jobs/{bug}/", "--format=%H").decode().split()
    if not shas:
        return [f"- {bug} ← origin unknown: no merge commit"]
    sha = shas[0]
    changed = _git(repo, "show", "--format=", "--name-only", "--no-renames", sha).decode().splitlines()
    if not [f for f in changed if f and not ESCAPE_SKIP_RE.search(f)]:
        return [f"- {bug} ← origin unknown: only test files changed"]
    # an added file has no lines in <sha>^ to blame
    old = _git(repo, "show", "--format=", "--name-only", "--no-renames", "--diff-filter=a", sha).decode().splitlines()
    origins, bodies = {}, {}
    for f in (f for f in old if f and not ESCAPE_SKIP_RE.search(f)):
        diff = _git(repo, "show", "--format=", "--unified=0", "--no-renames", sha, "--", f).decode(errors="replace")
        ranges = []
        for a, b in HUNK_RE.findall(diff):
            a, b = int(a), 1 if b == "" else int(b)
            ranges += ["-L", f"{a},{a + b - 1}" if b else f"{max(a, 1)},{max(a, 1)}"]
        if not ranges:
            continue
        blame = _git(repo, "blame", "--porcelain", *ranges, f"{sha}^", "--", f).decode(errors="replace")
        for c in BLAME_SHA_RE.findall(blame):
            if c not in bodies:
                body = _git(repo, "show", "-s", "--format=%B", c).decode(errors="replace")
                bodies[c] = next((j for j in ESCAPE_JOB_RE.findall(body) if j != bug and j in board), None)
            if bodies[c]:
                files = origins.setdefault(bodies[c], {})
                files[f] = files.get(f, 0) + 1
    if not origins:
        return [f"- {bug} ← origin unknown: no scrum job in blame"]
    try:
        secure = bool(ESCAPE_SECURITY_RE.search((Path(root) / "jobs" / bug / "feature.md").read_text(errors="replace")))
    except (OSError, TypeError):
        secure = False
    out = []
    for origin, files in origins.items():
        ui = any(ESCAPE_UI_RE.search(f) for f in files)
        rounds = board[origin].get("rounds") or [{}]
        folder = Path(root) / "jobs" / origin / f"round-{len(board[origin].get('rounds') or [])}" if root else None
        passed = sorted(k for k, v in rounds[-1].items() if v == "PASS" and k != "check"
                        and not (folder and not _real_review(folder / f"review-{k}.md"))
                        and not (k == "ui" and not ui) and not (k == "security" and not secure)) or ["none"]
        out.append(f"- {bug} ← {origin} · {sum(files.values())} lines in {', '.join(files)} · passed by: {', '.join(passed)}")
    return out


def _bug_job(root, job_id, lane) -> bool:
    """True when job_id is a bug fix: board lane `debug`, or a `Lane:` line in its feature.md or spec.md naming the word
    bug (ESCAPE_BUG_LANE_RE, a lilguy or fast bug fix, job 1528); an unreadable file counts as no line."""
    if lane == "debug":
        return True
    d = Path(root) / "jobs" / job_id
    for name in ("feature.md", "spec.md"):
        try:
            if ESCAPE_BUG_LANE_RE.search((d / name).read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            pass
    return False


def write_escapes(root, digest_id, jobs):
    """digests/<NNN>/escapes.md: for every claimed bug job (_bug_job), the origin jobs whose lines its fix changed
    (_escape_lines, git in the repo that holds root), or `No bug jobs`."""
    board = {j["id"]: j for j in read_board(root)["jobs"]}
    repo = Path(root).resolve().parent
    bugs = [j for j in jobs if _bug_job(root, j, board.get(j, {}).get("lane"))]
    lines = [l for j in bugs for l in _escape_lines(repo, j, board, root)]
    (Path(root) / "digests" / digest_id / "escapes.md").write_text("\n".join(lines or ["No bug jobs"]) + "\n")


# --- window-report: remembers each open usage window in windows/open.json (merge_limits drops closed ones) and, once
# one has closed, writes a zero-LLM scorecard windows/<window>-<resets_at>.json. Every timestamp in it is epoch seconds.
WINDOW_SECS = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
HIT_PCT = 90  # budget.hit_90_at: the first sighting at or above this used %
IDLE_SAMPLE_MAX_SECS = 300  # a gap between two runs longer than this is no idle sample


def _epoch(s):
    """An ISO timestamp as epoch seconds, None when it is not one."""
    try:
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def _json_lines(path):
    """The dict lines of a JSON-lines file; bad lines and an unreadable file are skipped."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


def _project_idle(root, board) -> bool:
    """True when no board job is in an ACTIVE stage and some open backlog item could be claimed now (cmd_next's test)."""
    if any(j.get("stage") in ACTIVE for j in board["jobs"]):
        return False
    _, items = read_backlog(root)
    return any(not i["done"] and not i["setup"] and not waiting_on(i, items, board) and not origin_open(i, board) for i in items)


def _scorecard(root, e, t, board, questions, acc=None):
    """The scorecard dict for one remembered window entry `e` (resets_at <= t) of account `acc` (default: the first).
    Only that account's jobs (a job with no `account` is the first account's) and transcripts are counted."""
    root = Path(root)
    first = accounts()[0]
    acc = acc or first
    end = e["resets_at"]
    start = end - WINDOW_SECS[e["window"]]
    within = lambda ts: ts is not None and start <= ts < end
    jobs = {j["id"]: j for j in board["jobs"] if isinstance(j, dict) and isinstance(j.get("id"), str)
            and (j.get("account") or first.name) == acc.name}
    # budget
    used = e.get("used_pct")
    if is_num(used):
        budget = {"used_pct": used, "hit_90_at": e.get("hit_90_at"), "left_at_reset_pct": 100 - used,
                  "cap_idle_secs": end - e["hit_cap_at"] if is_num(e.get("hit_cap_at")) else 0}
    else:
        budget = dict.fromkeys(("used_pct", "hit_90_at", "left_at_reset_pct", "cap_idle_secs"))
    # done jobs and points
    _, items = read_backlog(root)
    done = sorted(i for i, j in jobs.items() if j.get("stage") == "done" and within(_epoch(j.get("updatedAt"))))
    done_jobs = []
    for i in done:
        pts = [it["points"] for it in items if it["job"] == i and it["points"] is not None]
        done_jobs.append({"id": i, "points": sum(pts) if pts else None})
    points_done = sum(d["points"] or 0 for d in done_jobs)
    globs = ui_globs(root)
    fits = [_fit_job(root, i, jobs[i], globs) for i in done if jobs[i].get("lane") not in ("bigboy", "runall")]
    # tokens: only this project's rows
    me = root.resolve().parent
    name = next((n for n, p in projects().items() if p.resolve() == me), None)
    pdir = transcripts_dir() if acc.name == first.name else acc.dir / "projects"
    rows = [r for r in transcript_tokens(start, end, pdir) if r["project"] == name] \
        if name is not None and pdir.is_dir() else None
    tok = lambda r: sum(r[k] for k in TOKEN_KEYS)
    tokens = model_mix = cost_usd = None
    if rows is not None:
        by_job, model_mix = {}, {}
        for r in rows:
            if r["job"]:
                by_job[r["job"]] = by_job.get(r["job"], 0) + tok(r)
            mix = model_mix.setdefault(r["agent"], {})
            mix[r["model"] or "unknown"] = mix.get(r["model"] or "unknown", 0) + tok(r)
        tokens = {"total": sum(tok(r) for r in rows), "by_job": by_job}
        lane = {j["id"]: j.get("lane") or "standard" for j in board["jobs"]
                if isinstance(j, dict) and isinstance(j.get("id"), str)}
        cost_usd = {"total": 0, "by_job": {}, "by_lane": {}}
        for r in rows:
            usd = row_cost(r)
            cost_usd["total"] += usd
            if r["job"]:
                cost_usd["by_job"][r["job"]] = cost_usd["by_job"].get(r["job"], 0) + usd
        for i, usd in cost_usd["by_job"].items():
            ln = lane.get(i, "unknown")
            cost_usd["by_lane"][ln] = cost_usd["by_lane"].get(ln, 0) + usd
    total = tokens and tokens["total"]
    share = lambda ids: None if tokens is None else sum(tokens["by_job"].get(i, 0) for i in ids)
    pct = lambda n: round(100 * n / total, 1) if n is not None and total else None
    cache_read = rows and sum(r["cache_read_input_tokens"] for r in rows)
    fresh = rows and sum(r["input_tokens"] for r in rows)
    # wasted spend: aborted, stalled or unblocked in the window
    wasted = {i for i, j in jobs.items() if j.get("stage") == "aborted" and within(_epoch(j.get("updatedAt")))}
    for q in questions:
        if q.get("job") in jobs and within(q["_ts"]) and (
                q.get("kind") == "stall" or "unblock" in q
                or ("options" in q and str(q.get("reason") or "").startswith((STALLED, STALL)))):
            wasted.add(q["job"])
    wasted = sorted(wasted)
    over = [f["id"] for f in fits if f["over_routed"]]
    # reviewer yield
    findings = 0
    for p in root.glob("jobs/*/round-*/review-*.md"):
        try:
            if p.parts[-3] not in jobs or not within(p.stat().st_mtime) or not _real_review(p):
                continue
            body = md_section(p.read_text(encoding="utf-8"), "Findings") or ""
        except (OSError, ValueError):
            continue
        findings += len(re.findall(r"^\d+\. \[", body, re.M))
    review_tokens = rows and sum(tok(r) for r in rows if str(r["agent"]).startswith("scrum-review"))
    # local routing
    routed = [d for p in root.glob("jobs/*/routing.log")
              if p.parent.name in jobs for d in _json_lines(p) if within(_epoch(d.get("ts")))]
    # escapes: merged-with-gaps bigboy parents, and done jobs a later debug-lane job names
    escaped, escapes = set(), 0
    for i in done:  # one per parent from board.json; step 7 files the gaps, so no questions.log line
        if jobs[i].get("lane") == "bigboy" and str(jobs[i].get("reason") or "").startswith("merged + gaps"):
            escapes += 1
            escaped.add(i)
    all_done = {i: _epoch(j.get("updatedAt")) for i, j in jobs.items() if j.get("stage") == "done"}
    for i, j in jobs.items():
        f = root / "jobs" / i / "feature.md"
        try:
            if j.get("lane") != "debug" or not within(mtime := f.stat().st_mtime):
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        nums = set(re.findall(r"\bjob (\d{3,})\b", text))
        named = [d for d, at in all_done.items() if d != i and at is not None and at < mtime
                 and (re.search(rf"(?<![\w-]){re.escape(d)}(?![\w-])", text) or d.split("-", 1)[0] in nums)]
        if named:
            escapes += 1
            escaped.update(named)
    # needs-human time: each ask line's span until the job's next questions.log line, clipped to the window; a Discuss
    # note leaves the job waiting, so it ends no span
    needs_human = 0
    for n, q in enumerate(questions):
        if "options" not in q or q["_ts"] is None or q.get("job") not in jobs:
            continue
        nxt = next((x["_ts"] for x in questions[n + 1:] if x.get("job") == q.get("job") and x["_ts"] is not None
                    and not (x.get("kind") == "note" and x.get("action") == "discuss")), None)
        if nxt is None:
            if jobs.get(q.get("job"), {}).get("stage") != "needs-human":
                continue
            nxt = end
        needs_human += max(0, min(nxt, end) - max(q["_ts"], start))
    label = dict(WINDOWS)[e["window"]]
    return {
        "account": acc.name, "window": e["window"], "label": label, "resets_at": end, "start": start, "end": end,
        "written_at": datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds"),
        "budget": budget, "headline": round(points_done / used, 3) if is_num(used) and used else None,
        "points_done": points_done, "done_jobs": done_jobs, "tokens": tokens, "cost_usd": cost_usd,
        "tokens_per_point": round(total / points_done, 3) if tokens is not None and points_done else None,
        "first_pass_rate": round(sum(f["fix_rounds"] == 0 for f in fits) / len(fits), 3) if fits else None,
        "cache_hit_rate": round(cache_read / (fresh + cache_read), 3) if rows and fresh + cache_read else None,
        "model_mix": model_mix,
        "wasted_jobs": wasted, "wasted_tokens": share(wasted), "wasted_pct": pct(share(wasted)),
        "lane_fit": {"over_routed": over, "over_routed_tokens": share(over), "over_routed_pct": pct(share(over))},
        "reviewer_yield": round(findings / (review_tokens / 1000), 3) if tokens is not None and review_tokens else None,
        "local_routing": round(sum(d.get("runner") != "skip" and d.get("outcome") == "ok" for d in routed)
                               / len(routed), 3) if routed else None,
        "escapes": escapes, "escaped_jobs": sorted(x for x in escaped if isinstance(x, str)),
        "idle": {"ready_idle_secs": e.get("idle_secs") or 0, "needs_human_secs": round(needs_human)},
    }


def _write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def cmd_window_report(root, now=None) -> list[dict]:
    """Record every usage.json window into windows/open.json, then score each remembered window whose resets_at has
    passed into windows/<window>-<resets_at>.json (once: an existing scorecard is never rewritten) and drop it from
    open.json. A seven_day sample whose resets_at is under WINDOW_SECS['seven_day'] after (or before) that account's
    latest open or scored seven_day reset is dropped: another account's reset. Returns the scorecards written this run.
    The whole run holds windows/.lock."""
    t = time.time() if now is None else now
    wdir = Path(root) / "windows"
    wdir.mkdir(parents=True, exist_ok=True)
    with open(wdir / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            raw = json.loads((wdir / "open.json").read_text())
        except (OSError, ValueError):
            raw = {}
        opened = {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("window") in WINDOW_SECS
                  and type(v.get("resets_at")) is int} if isinstance(raw, dict) else {}
        board, idle, accs = read_board(root), None, accounts()
        week = {}  # account -> its latest open or scored seven_day reset
        for p in wdir.glob("seven_day-*.json"):
            if m := re.fullmatch(r"seven_day-(\d+)(?:-(.+))?\.json", p.name):
                week[m[2] or accs[0].name] = max(int(m[1]), week.get(m[2] or accs[0].name, 0))
        for v in opened.values():
            if v["window"] == "seven_day":
                name = v.get("account") or accs[0].name
                week[name] = max(v["resets_at"], week.get(name, 0))
        for acc in accs:
            usage = read_usage(acc.name) or {}
            limits = usage.get("rate_limits") if isinstance(usage.get("rate_limits"), dict) else {}
            at = usage["written_at"] if is_num(usage.get("written_at")) else t
            for key, _ in WINDOWS:
                w = limits.get(key)
                if not isinstance(w, dict) or not is_num(w.get("resets_at")):
                    continue
                r = int(w["resets_at"])
                last = week.get(acc.name)
                if key == "seven_day" and last is not None and r != last and r - last < WINDOW_SECS["seven_day"]:
                    continue  # another account's reset in this one's sample (digest 121): no phantom window
                e = opened.setdefault(f"{key}-{r}" + ("" if acc is accs[0] else f"-{acc.name}"), {
                    "window": key, "resets_at": r, "used_pct": None, "hit_90_at": None, "hit_cap_at": None,
                    "idle_secs": 0, "last_tick": None, **({} if acc is accs[0] else {"account": acc.name})})
                used = w.get("used_percentage")
                if is_num(used):
                    e["used_pct"] = max(used, e["used_pct"]) if is_num(e.get("used_pct")) else used  # the peak
                    if used >= HIT_PCT and e.get("hit_90_at") is None:
                        e["hit_90_at"] = at
                    if 100 - used < USAGE_STOP_PCT and e.get("hit_cap_at") is None:
                        e["hit_cap_at"] = at
                if r > t:
                    gap = t - e["last_tick"] if is_num(e.get("last_tick")) else None
                    if gap is not None and 0 < gap <= IDLE_SAMPLE_MAX_SECS:
                        if idle is None:
                            idle = _project_idle(root, board)
                        if idle:
                            e["idle_secs"] = (e.get("idle_secs") or 0) + gap
                    e["last_tick"] = t
        written, questions = [], None
        for name, e in sorted(opened.items()):
            if e["resets_at"] > t:
                continue
            path = wdir / f"{name}.json"
            if not path.exists():
                if questions is None:
                    questions = [{**q, "_ts": _epoch(q.get("date"))} for q in _json_lines(Path(root) / "questions.log")]
                acc = next((a for a in accounts() if a.name == (e.get("account") or accounts()[0].name)), None)
                if acc is None:  # an account since removed: drop the entry, write no card
                    del opened[name]
                    continue
                card = _scorecard(root, e, t, board, questions, acc)
                _write_json(path, card)
                written.append(card)
            del opened[name]
        _write_json(wdir / "open.json", opened)
    return written


# Rules files: the scrum's own agents, SKILL.md and lane files, on which Lilguy promotes (_lilguy_trigger).
RULES_RE = re.compile(r"(^|/)agents/scrum-[^/]*\.md$|(^|/)trevskills-scrum/SKILL\.md$|(^|/)trevskills-scrum/lanes/[^/]*\.md$")


def _git(worktree, *args):
    r = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, timeout=60)
    if r.returncode:
        raise ValueError(f"git {' '.join(args[:2])} failed: {r.stderr.decode(errors='replace').strip()[:200]}")
    return r.stdout


# --- route-check: the Fast lane promotion, Review clean-round and Approve model decisions (SKILL.md), from files ---
SCHEMA_RE = re.compile(r"(^|/)prisma/(schema\.prisma|migrations/)|\.sql$")  # SKILL.md Merge's schema guard
ENV_RE = re.compile(r"(^|/)\.env")
SENSITIVE_RE = re.compile(r"(^|/)(middleware|proxy)\.[cm]?[jt]sx?$|auth|session|login|signin|signup|password|permission"
                          r"|payment|billing|checkout|stripe|webhook|secret|credential", re.I)  # SKILL.md Fast lane
FAST_MAX_LINES, FAST_MAX_FILES = 100, 10
LILGUY_MAX_LINES, LILGUY_MAX_FILES = 30, 10


# --- review-plan: SKILL.md Review step 2 minus the Jev gate. Decides incremental vs full and writes the carried-forward
# and skip files before any spawn; behaviour-preserving move of the old prose, so every rule here is SKILL.md's.
SECURITY_RES = tuple(re.compile(p, re.I) for p in (
    SENSITIVE_RE.pattern,  # Fast lane sensitive-path regex
    SCHEMA_RE.pattern,  # Merge schema guard regex
    ENV_RE.pattern,
    r"(^|/)(package\.json|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|requirements[^/]*\.txt|pyproject\.toml|go\.mod"
    r"|Cargo\.toml)$",  # manifest regex
    r"(^|/)api/|(^|/)route\.[cm]?[jt]sx?$",  # API regex
))
CARRIED = "VERDICT: PASS\nCarried forward from round {}: no blocking findings.\n"
UI_SKIP = "VERDICT: PASS\nSkipped by orchestrator: no UI files in diff.\n"
SECURITY_SKIP = "VERDICT: PASS\nSkipped by orchestrator: no sensitive files in diff.\n"
DELETION_SKIP = "VERDICT: PASS\nSkipped by orchestrator: diff is at least 90% deletions.\n"
NOMARKUP_SKIP = "VERDICT: PASS\nSkipped by orchestrator: no UI file's diff touches markup, styling or copy.\n"
VISUAL_SKIP = "VERDICT: PASS\nSkipped by orchestrator: visual diff found every captured pair identical and the spec says no visual change.\n"


def ui_globs(root):
    """project.md's `- UI globs:` entries; None when the file or line is missing, empty or `none`."""
    try:
        text = (Path(root) / "project.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _project_list(text, "UI globs") or None


def _project_list(text, label):
    """The entries of project.md's `- <label>:` line; None when there is no such line, [] when it is empty or `none`."""
    for line in text.splitlines():
        if m := re.match(rf"^\s*-\s*{re.escape(label)}:(.*)$", line):
            globs = [g.strip("`") for g in m[1].split() if g.strip("`")]
            return [] if globs == ["none"] else globs
    return None


SERVER_ONLY_RE = re.compile(r"(^|/)app/api/|(^|/)route\.(ts|js|tsx)$")


def glob_match(path, globs):
    """First-run setup's matching: `*.ext` is a suffix, `dir/` a directory path component, anything else an exact path.
    A server-only path (an `api/` directly under `app/`, or a `route.ts|js|tsx` basename) is never UI, whatever the globs."""
    if SERVER_ONLY_RE.search(path):
        return False
    for g in globs:
        if g.startswith("*."):
            if path.endswith(g[1:]):
                return True
        elif g.endswith("/"):
            if ("/" + g) in ("/" + path):
                return True
        elif path == g:
            return True
    return False


def _names(wt, *args):
    """git diff --name-only <args> as a set of paths; None when the diff can't be read."""
    try:
        return set(_git(wt, "-c", "core.quotePath=false", "diff", "--name-only", *args, "--").decode().splitlines())
    except (ValueError, OSError, UnicodeDecodeError, subprocess.SubprocessError):
        return None


ORCH_REVIEW_RE = re.compile(
    "|".join(re.escape(t) for t in (UI_SKIP, SECURITY_SKIP, DELETION_SKIP, VISUAL_SKIP, NOMARKUP_SKIP)) + "|"
    + re.escape(CARRIED).replace(r"\{\}", r"\d+"))


SCRIPT_EXT_RE = re.compile(r"\.(tsx?|jsx?|mjs|cjs)$")
_KW = r"(return|const|let|var|if|else|import|export|throw|await|break|continue|case|default|function|type|interface|async|new)\b"
MARKUP_LINE_RE = re.compile(
    r"(?<![\w>)\]])</?[A-Za-z>]"  # a JSX tag (not a generic like useState<Foo>)
    r"|/>|\bclassName\b|\bclass\s*=|\bstyle\b|\bsx\s*=|\b(cn|clsx|cva|twMerge)\("  # markup and styling
    r"|[\"'`][^\"'`]*[A-Za-z]{2,}\s+[A-Za-z]{2,}[^\"'`]*[\"'`]"  # a quoted string of two or more words (copy)
    rf"|^\s*(?!{_KW})[A-Za-z][A-Za-z,.'!?:-]*(\s+[A-Za-z][A-Za-z,.'!?:-]*)+\s*$")  # bare JSX text of two or more words


def _no_markup_change(wt, base, files):
    """True when every file of `files` (UI-glob runtime paths) is a script file (ts/tsx/js/jsx) whose added and removed
    lines in base...HEAD match none of MARKUP_LINE_RE: a logic-only change. Any other extension, an unreadable diff or
    an empty `files` is False, so the reviewers run."""
    if not files:
        return False
    for f in files:
        if not SCRIPT_EXT_RE.search(f):
            return False
        try:
            out = _git(wt, "-c", "core.quotePath=false", "diff", "-U0", "--no-color", f"{base}...HEAD", "--", f).decode()
        except (ValueError, OSError, UnicodeDecodeError, subprocess.SubprocessError):
            return False
        for line in out.splitlines():
            if line[:1] in "+-" and not line.startswith(("+++", "---")) and MARKUP_LINE_RE.search(line[1:]):
                return False
    return True


def _drop_stale(rd, spawn):
    """Delete an earlier run's skip or carried-forward file for each spawned role; real review output stays."""
    for r in spawn:
        p = rd / f"review-{r}.md"
        try:
            if ORCH_REVIEW_RE.fullmatch(p.read_text(encoding="utf-8")):
                p.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def _incremental_since(prev, wt, base):
    """(SINCE, round-(N-1) verdicts) when an incremental re-review holds, else None (the full-review fallback)."""
    try:
        since = (prev / "head.txt").read_text(encoding="utf-8", errors="replace").strip()
        if not since or since.startswith("-"):
            return None
        _git(wt, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}")
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
    verdicts = {r: first_word(prev / f"review-{r}.md", ("PASS", "CHANGES")) for r in REVIEWERS}
    if any(v not in ("PASS", "CHANGES") for v in verdicts.values()):
        return None  # a re-review would have no findings to check
    fix, seen = _names(wt, since, "HEAD"), _names(wt, f"{base}...{since}")
    if fix is None or seen is None or not fix <= seen:
        return None  # the fix touched a file the earlier reviews never saw
    return since, verdicts


def _rework_roles(prev):
    """Roles named on a `fix-now` line of prev/decision.md when that decision is REWORK; else empty."""
    if first_word(prev / "decision.md", ("REWORK",)) != "REWORK":
        return set()
    text = (prev / "decision.md").read_text(encoding="utf-8", errors="replace")
    return {r.lower() for line in text.splitlines() if "fix-now" in line.lower()
            for r in re.findall(r"\b(security|ux|ui|code)\b", line, re.I)}


def _unrendered_roles(root, jobdir, n, wt, base):
    """{"ui", "ux"} minus each role that rendered (a `^Rendered:` line) in an earlier round at the current HEAD; empty
    when the diff hits no UI globs. The approver only accepts a same-HEAD render, so an older one is never carried."""
    globs, files = ui_globs(root), _names(wt, f"{base}...HEAD")
    if not globs or files is None or not any(glob_match(f, globs) for f in files):
        return set()
    try:
        head = _git(wt, "rev-parse", "HEAD").decode().strip()
    except (ValueError, OSError, subprocess.SubprocessError):
        return {"ui", "ux"}
    out = {"ui", "ux"}
    for k in range(1, n):
        d = jobdir / f"round-{k}"
        try:
            if (d / "head.txt").read_text(encoding="utf-8", errors="replace").strip() != head:
                continue
            out -= {r for r in ("ui", "ux") if (d / f"review-{r}.md").is_file() and re.search(
                r"^Rendered:", (d / f"review-{r}.md").read_text(encoding="utf-8", errors="replace"), re.M)}
        except OSError:
            continue
    return out


# --- e2e-specs: the Check gate's and trevskills-e2e's route-to-spec mapping, so a job runs only the specs its diff needs.
RUNTIME_EXCLUDE_RE = re.compile(r"(^|/)(__tests__|e2e|tests?|docs?)/|\.(test|spec)\.[cm]?[jt]sx?$|\.(md|mdx|txt)$")  # newjob.md
E2E_FULL_DEFAULT = ["src/app/layout.tsx", "app/layout.tsx", "src/app/globals.css", "app/globals.css",
                    "src/middleware.ts", "middleware.ts", "src/proxy.ts", "proxy.ts", "playwright.config.ts",
                    "playwright.config.js"]
APP_ROUTE_FILE_RE = re.compile(r"(^|/)(page|layout|template|loading|error|not-found|default)\.[^/]*$")
SOURCE_RE = re.compile(r"\.([cm]?[jt]sx?|vue|svelte|astro)$")
IMPORT_RE = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"]([^'"]+)['"]""")
# One shell word: quoted runs, a $( ... ) with one level of nested parens, or plain characters.
SHELL_WORD = r"""(?:'[^']*'|"[^"]*"|\$\((?:'[^']*'|"[^"]*"|\([^()]*\)|[^()'"])*\)|[^\s'"])+"""
ENV_PREFIX_RE = re.compile(rf"^(?:\s*[A-Za-z_][A-Za-z0-9_]*={SHELL_WORD})*")
# The Playwright wrapper that sets use.channel from SCRUM_PW_CHANNEL (a machine without Playwright's own Chromium).
PW_CHANNEL_CONFIG = '"$HOME/.claude/skills/trevskills-e2e/channel.config.mjs"'
E2E_BUDGET_MS = 600000  # job E2E runs (B e2e-specs <id>, the Check gate) stop at 10 min (job 1311)
E2E_SLOW_ITEM = "Speed up the slowest job E2E spec files"  # cmd_e2e_budget's backlog item, deduped by unless_open
VIEW_DIR_RE = re.compile(r"(?:^|/)views/([^/]+)/")  # a dashboard views/<name>/ folder: its specs name `view=<name>`


def _route_of(path):
    """(route, prefix) for a file under an `app/` or `pages/` directory, else None. app/: the directory's route without
    (group) and @slot segments, and a layout.* covers its route as a prefix; pages/: the path, index -> its parent."""
    parts = path.split("/")
    if "app" in parts[:-1]:
        segs = [s for s in parts[parts.index("app") + 1:-1] if not (s.startswith("(") and s.endswith(")"))
                and not s.startswith("@")]
        return "/" + "/".join(segs), parts[-1].split(".")[0] == "layout"
    if "pages" in parts[:-1]:
        segs = parts[parts.index("pages") + 1:]
        segs[-1] = segs[-1].split(".")[0]
        if segs[-1] == "index":
            segs.pop()
        return "/" + "/".join(segs), False
    return None


def _route_re(route, prefix):
    """A route as it appears in a spec string literal; a [param] segment matches any one segment, [...x] one or more
    and [[...x]] zero or more. A body that can match empty (a root [[...x]]) still needs its leading /."""
    seg = r"/[^/'\"`?#]+"
    body = "".join(f"(?:{seg})*" if s.startswith("[[...") else f"(?:{seg})+" if s.startswith("[...")
                   else seg if s.startswith("[") else "/" + re.escape(s) for s in route.split("/") if s)
    if body and re.fullmatch(body, ""):
        body = "(?=/)" + body
    end = r"(?=['\"`?#])"
    if prefix:
        return re.compile(rf"['\"`]{body}(?:/[^'\"`?#\s]*)?{end}" if body else rf"['\"`]/[^'\"`?#\s]*{end}")
    return re.compile(rf"['\"`]{body or '/'}/?{end}")


def _e2e_dir(wt):
    """testDir from playwright.config.*, else e2e/, else tests/ (repo-relative, no trailing slash)."""
    for cfg in sorted(wt.glob("playwright.config.*")):
        if m := re.search(r"""testDir\s*:\s*['"`]([^'"`]+)""", cfg.read_text(encoding="utf-8", errors="replace")):
            return m[1].strip().removeprefix("./").rstrip("/")
    return "e2e" if (wt / "e2e").is_dir() else "tests"


def _import_index(sources):
    """{last segment of an import specifier: files importing it} over the tracked source files."""
    index = {}
    for f, text in sources.items():
        for spec in IMPORT_RE.findall(text):
            index.setdefault(spec.rstrip("/").rsplit("/", 1)[-1], set()).add(f)
    return index


def _importers(index, path):
    """Files with an import specifier ending in path's basename (its directory for index.*)."""
    p = Path(path)
    names = {p.parent.name} if p.stem == "index" else {p.name, p.stem}
    return sorted(set().union(*(index.get(n, set()) for n in names)) - {path})


def _e2e_command(cmd, specs=(), budget=False):
    """The E2E command narrowed to specs: after `--` for npm run, appended for playwright test, else
    `npx playwright test` keeping the leading NAME=value tokens. budget puts `--global-timeout=E2E_BUDGET_MS` first;
    with SCRUM_PW_CHANNEL set, `--config PW_CHANNEL_CONFIG` goes before the specs; with no specs (the full suite) any
    other command stays as it is."""
    cap = [f"--global-timeout={E2E_BUDGET_MS}"] if budget else []
    conf = ["--config", PW_CHANNEL_CONFIG] if os.environ.get("SCRUM_PW_CHANNEL", "").strip() else []
    args = " ".join([*cap, *conf, *(shlex.quote(s) for s in specs)])
    if not args:
        return cmd
    if re.search(r"\bnpm run\b", cmd):
        return f"{cmd} -- {args}"
    if re.search(r"\bplaywright test\b", cmd):
        return f"{cmd} {args}"
    if not specs:
        return cmd
    env = ENV_PREFIX_RE.match(cmd)[0].strip()
    return f"{env} npx playwright test {args}".lstrip()


def changed_routes(wt: Path, ui: list[str]) -> dict[str, set[tuple[str, bool]]]:
    """{changed UI file: its (route, prefix) pairs}: follow each file's importers over wt's tracked source files until
    they reach route files (_route_of). Shared by e2e_specs and render_paths."""
    wt = Path(wt)
    try:
        tracked = _git(wt, "ls-files").decode(errors="replace").splitlines()
    except (ValueError, OSError, subprocess.SubprocessError):
        tracked = []
    sources = {}
    for f in tracked:
        if SOURCE_RE.search(f) and not RUNTIME_EXCLUDE_RE.search(f) and "node_modules/" not in f:
            try:
                sources[f] = (wt / f).read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    index, out = _import_index(sources), {}
    # app/ folders that hold a route file: a colocated module only maps to its own folder's route when it is one of them
    route_dirs = {f.rsplit("/", 1)[0] for f in tracked if "app" in f.split("/")[:-1] and APP_ROUTE_FILE_RE.search(f)}
    for f in ui:
        routes, seen, todo = set(), {f}, [f]
        while todo:  # follow importers until they reach route files
            g = todo.pop()
            if (r := _route_of(g)) is not None:
                if "pages" in g.split("/")[:-1] or APP_ROUTE_FILE_RE.search(g) or g.rsplit("/", 1)[0] in route_dirs:
                    routes.add(r)
                if "pages" in g.split("/")[:-1] or APP_ROUTE_FILE_RE.search(g):
                    continue  # a route file; a colocated app/ module also maps through its importers
            for imp in _importers(index, g):
                if imp not in seen:
                    seen.add(imp)
                    todo.append(imp)
        out[f] = routes
    return out


def e2e_specs(wt, base: str, project_file, budget=False) -> dict:
    """{"mode", "command", "specs", "uncovered", "trigger"} for the diff base...HEAD in wt (lanes/newjob.md Check gate
    step 2). full: a diff file matches `- E2E full globs:` (default E2E_FULL_DEFAULT; `none` = never); scoped: the specs
    whose string literals name a route a changed UI runtime file renders (a file under a views/<name>/ folder: the
    specs naming `view=<name>`, else its route's); none: no spec covers it. An unreadable diff runs the full suite (the
    safe direction). budget (the job form): the command takes `--global-timeout` and leaves out spec files the diff
    adds or changes, which the Check gate runs on their own."""
    if base.startswith("-"):
        raise SystemExit(f"base {base!r} starts with '-'")
    wt = Path(wt)
    try:
        text = Path(project_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise SystemExit(f"cannot read {project_file}")
    m = re.search(r"^\s*-\s*E2E:(.*)$", text, re.M)
    cmd = m[1].strip() if m and m[1].strip().lower() not in ("", "none") else None
    full = _project_list(text, "E2E full globs")
    full = E2E_FULL_DEFAULT if full is None else full
    out = {"mode": "none", "command": None, "specs": [], "uncovered": [], "trigger": None}
    files = _names(wt, f"{base}...HEAD")
    if files is None or (full and (hit := next((f for f in sorted(files) if glob_match(f, full)), None))):
        return {**out, "mode": "full", "command": _e2e_command(cmd, budget=budget) if cmd else None,
                "trigger": hit if files is not None else "diff unreadable"}
    globs = _project_list(text, "UI globs") or []
    ui = sorted(f for f in files if f and not RUNTIME_EXCLUDE_RE.search(f) and glob_match(f, globs))
    if not ui:
        return out
    tdir = _e2e_dir(wt)
    spec_text = {}
    if (wt / tdir).is_dir():
        for p in sorted((wt / tdir).rglob("*")):
            if p.is_file() and "node_modules" not in p.parts and re.search(r"\.(spec|test)\.", p.name):
                spec_text[p.relative_to(wt).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    specs = set()
    for f, routes in changed_routes(wt, ui).items():
        view = VIEW_DIR_RE.search(f)
        view_re = view and re.compile(rf"\bview={re.escape(view[1])}(?![\w-])")
        hits = {s for s, body in spec_text.items() if view_re and view_re.search(body)}
        hits = hits or {s for s, body in spec_text.items() for r in routes if _route_re(*r).search(body)}
        if not hits:
            out["uncovered"].append(f)
        specs |= hits
    if budget:
        specs -= set(files)  # changed spec files run on their own, unbudgeted (newjob.md "Whatever the `mode`")
    if specs:
        out.update(mode="scoped", specs=sorted(specs),
                   command=_e2e_command(cmd, sorted(specs), budget) if cmd else None)
    return out


def worktree_job(root, job_id) -> dict:
    """The board job, for a command that reads its worktree's diff: SystemExit when it has no worktree or no base."""
    job = find(read_board(root), check_id(job_id))
    if not job.get("worktree") or not job.get("base"):
        raise SystemExit(f"job {job_id} has no {'worktree' if not job.get('worktree') else 'base'} on the board")
    return job


def cmd_e2e_specs(root, job_id) -> dict:
    """e2e_specs for the job's worktree and base with root/project.md, with the job E2E time budget."""
    job = worktree_job(root, job_id)
    return e2e_specs(job["worktree"], job["base"], Path(root) / "project.md", budget=True)


def related_tests(wt, base: str) -> list:
    """The test files a fast-lane Check gate runs for a `Test:` that is not jest (lanes/newjob.md **Fast lane Test**),
    sorted: each test_*.py or *_test.py file the diff base...HEAD adds or changes that still exists, plus every
    test_<stem>*.py under wt/tests/ (any depth) for each other .py file the diff touches, a deleted one included; a
    stem's `-` also matches `_` (edit-check.py: test_edit_check.py, as a test module name holds no `-`).
    [] when nothing matches or the diff can't be read: the gate then runs the full Test."""
    if base.startswith("-"):
        raise SystemExit(f"base {base!r} starts with '-'")
    wt = Path(wt)
    out, stems = set(), set()
    for f in _names(wt, f"{base}...HEAD") or ():
        if not f.endswith(".py"):
            continue
        if is_test_path(Path(f).name):
            if (wt / f).is_file():
                out.add(f)
        else:
            stems.update({Path(f).stem, Path(f).stem.replace("-", "_")})
    if stems and (wt / "tests").is_dir():
        out.update(p.relative_to(wt).as_posix() for p in (wt / "tests").rglob("test_*.py")
                   if any(p.name.startswith(f"test_{s}") for s in stems))
    return sorted(out)


def cmd_related_tests(root, job_id) -> list:
    """related_tests for the job's worktree and base."""
    job = worktree_job(root, job_id)
    return related_tests(job["worktree"], job["base"])


PW_TIMEOUT_RE = re.compile(r"Timed out waiting \d+(?:\.\d+)?s for the")
PW_SUMMARY_RE = re.compile(r"^\s*(\d+) (passed|failed|flaky|interrupted|did not run)\b", re.M)
PW_TEST_RE = re.compile(r"›\s*(\S+?):\d+:\d+\s*›.*\((\d+(?:\.\d+)?)(ms|s|m)\)\s*$", re.M)


def e2e_budget(text: str) -> dict:
    """{"over_budget", "passed", "failed", "not_run", "slowest", "line"} from a Playwright run's output: over_budget when
    the --global-timeout fired; passed (incl. flaky), failed and not_run (did not run + interrupted) from the summary
    lines; slowest = up to 5 [spec file, seconds] by the list reporter's per-test durations (lanes/newjob.md Check gate)."""
    counts = {}
    for n, kind in PW_SUMMARY_RE.findall(text):
        counts[kind] = int(n)  # the last summary wins
    totals = {}
    for spec, n, unit in PW_TEST_RE.findall(text):
        totals[spec] = totals.get(spec, 0) + float(n) * {"ms": 0.001, "s": 1, "m": 60}[unit]
    passed = counts.get("passed", 0) + counts.get("flaky", 0)
    not_run = counts.get("did not run", 0) + counts.get("interrupted", 0)
    slowest = [[f, round(t, 1)] for f, t in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
    return {"over_budget": bool(PW_TIMEOUT_RE.search(text)), "passed": passed, "failed": counts.get("failed", 0),
            "not_run": not_run, "slowest": slowest, "line": f"E2E: over budget, {passed} passed, {not_run} not run"}


def cmd_e2e_stopped(root, job_id, since=None) -> dict:
    """{"stopped", "count", "reason", "line"} from jobs/<id>/e2e-stopped.json (serve.py e2e_runaway_tick's marker).
    Missing, unreadable or malformed: {"stopped": False, "count": 0, "reason": None, "line": None}. `line` is the
    check.md line: `E2E stopped: <reason>` for count 1, `E2E: not run, stopped: <reason> twice` for 2 or more.
    With `since` (epoch seconds), a marker whose `at` is older, or has no numeric `at`, is a stale stop: not stopped."""
    job_id = check_id(job_id)
    out = {"stopped": False, "count": 0, "reason": None, "line": None}
    try:
        rec = json.loads((Path(root) / "jobs" / job_id / "e2e-stopped.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(rec, dict) or not is_num(rec.get("count")) or rec["count"] < 1 or rec.get("reason") not in ("memory", "disk"):
        return out
    if since is not None and not (is_num(rec.get("at")) and rec["at"] >= since):
        return out
    count = int(rec["count"])
    out.update(stopped=True, count=count, reason=rec["reason"],
               line=f"E2E stopped: {rec['reason']}" if count == 1 else f"E2E: not run, stopped: {rec['reason']} twice")
    return out


def cmd_e2e_budget(root, job_id, log) -> dict:
    """e2e_budget of the log file plus "backlog": when over budget with no failed test, the one E2E_SLOW_ITEM backlog
    item this run filed (None when one is already open or nothing is filed). On a worker (on_worker) the item is
    written as a "Backlog: add" file in jobs/<id>/followups/ (worker_add) instead, and backlog.md is left alone."""
    job_id = check_id(job_id)
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise SystemExit(f"cannot read {log}")
    out = {**e2e_budget(text), "backlog": None}
    if out["over_budget"] and not out["failed"]:
        times = ", ".join(f"{f} {s:g}s" for f, s in out["slowest"]) or "no per-test times in the log"
        item = f"{E2E_SLOW_ITEM}: {times} (job {job_id} E2E ran past the {E2E_BUDGET_MS // 60000} min budget)"
        if on_worker():  # a worker's backlog.md never comes home: the job's followups do (job 1504)
            out["backlog"] = next(iter(worker_add(root, job_id, [item])), None)
        else:
            out["backlog"] = next(iter(cmd_backlog_add(root, [item], unless_open=E2E_SLOW_ITEM)), None)
    return out


def _page_routes(wt) -> set[str]:
    """The routes (_route_of) of wt's tracked app/ page.* files."""
    try:
        tracked = _git(Path(wt), "ls-files").decode(errors="replace").splitlines()
    except (ValueError, OSError, subprocess.SubprocessError):
        return set()
    return {_route_of(f)[0] for f in tracked if "app" in f.split("/")[:-1] and f.rsplit("/", 1)[-1].split(".")[0] ==
            "page" and SOURCE_RE.search(f) and "node_modules/" not in f}


def concrete_routes(route, prefix, pages) -> set[str]:
    """The page routes a (route, prefix) pair covers: for a prefix (a layout), every route in pages at or below it;
    else, or when no page lies there, the route itself."""
    if not prefix:
        return {route}
    return {r for r in pages if r == route or r.startswith(route.rstrip("/") + "/")} or {route}


RENDER_CAP = 8  # pages per shared review render (lanes/review.md step 2); the rest fall back to the reviewers
RENDER_PATH_LINE_RE = re.compile(r"^\s*(?:-\s+)?render path:(.*)$", re.I | re.M)
RENDER_URL_RE = re.compile(r"`([^`]+)`|(/[^\s,`<]*(?:<[^>]*>[^\s,`<]*)*)")


def spec_render_paths(spec_file) -> list:
    """The app URLs the spec's `Render path:` lines name (case-insensitive, optional leading `- `; backticks or
    commas between URLs), in order and deduped; [] when spec_file is None or unreadable (job 1247)."""
    if not spec_file:
        return []
    try:
        text = Path(spec_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    urls = []
    for line in RENDER_PATH_LINE_RE.findall(text):
        for quoted, bare in RENDER_URL_RE.findall(line):
            url = (quoted or bare).strip()
            if url.startswith("/") and url not in urls:
                urls.append(url)
    return urls


def render_paths(wt, base: str, project_file, spec_file=None) -> dict:
    """{"paths", "skipped"} for the diff base...HEAD in wt (lanes/review.md step 2 Shared render): the sorted routes the
    changed UI runtime files render, minus dynamic ([param]) routes, then each spec_file `Render path:` URL not
    already listed (a URL holding `<`, `>` or `[` goes to skipped as needing a real id); entries past RENDER_CAP go
    to skipped. A UI runtime file that maps to no renderable route and no spec URL gives ["/"]; no UI runtime file
    (or an unreadable diff) gives empty lists."""
    if base.startswith("-"):
        raise SystemExit(f"base {base!r} starts with '-'")
    try:
        text = Path(project_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise SystemExit(f"cannot read {project_file}")
    globs = _project_list(text, "UI globs") or []
    files = _names(Path(wt), f"{base}...HEAD") or set()
    ui = sorted(f for f in files if f and not RUNTIME_EXCLUDE_RE.search(f) and glob_match(f, globs))
    if not ui:
        return {"paths": [], "skipped": []}
    pages = _page_routes(wt)
    routes = sorted({c for pairs in changed_routes(wt, ui).values() for r in pairs for c in concrete_routes(*r, pages)})
    skipped = [f"{r}: dynamic route" for r in routes if "[" in r]
    static = [r for r in routes if "[" not in r]
    for url in spec_render_paths(spec_file):
        if any(c in url for c in "<>["):
            skipped.append(f"{url}: needs a real id")
        elif url not in static:
            static.append(url)
    skipped += [f"{r}: over the {RENDER_CAP}-page cap" for r in static[RENDER_CAP:]]
    return {"paths": static[:RENDER_CAP] or ["/"], "skipped": skipped}


def cmd_render_paths(root, job_id) -> dict:
    """render_paths for the job's worktree and base with root/project.md and the job's spec.md."""
    job = worktree_job(root, job_id)
    return render_paths(job["worktree"], job["base"], Path(root) / "project.md",
                        Path(root) / "jobs" / job["id"] / "spec.md")


# --- ui-sweep: serve.py ui_sweep_tick's later visual re-check of the screens merged on main (lanes/uisweep.md).
PR_SUBJECT_RE = re.compile(r"\(#(\d+)\)\s*$")


def ui_sweep_screens(text) -> list[tuple[str, str]]:
    """decision.md's `## UI sweep` bullets as [(screen, why)]; `- <screen>` alone gives why "". [] when the section is
    missing, empty or only `- none`."""
    out = []
    for line in (md_section(text, "UI sweep") or "").splitlines():
        if (m := re.match(r"^\s*-\s+(.+?)\s*$", line)) and m[1].lower() != "none":
            screen, _, why = m[1].partition(" — ")
            out.append((screen.strip(), why.strip()))
    return out


def ui_sweep_targets(repo, root, since: str, head: str) -> dict:
    """{"since", "head", "targets": [{"path", "jobs", "marked", "why"}]} for the commits since..head in repo. A commit
    whose subject ends `(#n)` is labelled with the board job whose pr ends `/pull/n` (else `commit <sha7>`); its UI-glob
    runtime files map to routes through changed_routes (none: `/`), and that job's decision.md `## UI sweep` screens come
    first as marked. Each path appears once, with every label that touched it."""
    for ref in (since, head):
        if not ref or ref.startswith("-"):
            raise SystemExit(f"ref {ref!r} is empty or starts with '-'")
    repo, root = Path(repo), Path(root)
    globs = ui_globs(root) or []
    try:
        by_pr = {m[1]: j["id"] for j in read_board(root)["jobs"]
                 if (m := re.search(r"/pull/(\d+)$", str(j.get("pr") or "")))}
    except (OSError, ValueError, KeyError):
        by_pr = {}
    commits = _git(repo, "rev-list", "--reverse", f"{since}..{head}", "--").decode().split()
    marked, changed = {}, []  # changed: (label, ui files) per commit
    for sha in commits:
        subject = _git(repo, "log", "-1", "--format=%s", sha, "--").decode(errors="replace").strip()
        job = by_pr.get(m[1]) if (m := PR_SUBJECT_RE.search(subject)) else None
        label = job or f"commit {sha[:7]}"
        if job:
            try:
                screens = ui_sweep_screens((root / "jobs" / job / "decision.md").read_text(errors="replace"))
            except OSError:
                screens = []
            for screen, why in screens:
                t = marked.setdefault(screen, {"path": screen, "jobs": [], "marked": True, "why": why})
                t["jobs"] += [label] if label not in t["jobs"] else []
        files = _git(repo, "-c", "core.quotePath=false", "diff-tree", "--no-commit-id", "--name-only", "-r", sha,
                     "--").decode(errors="replace").splitlines()
        ui = [f for f in files if f and not RUNTIME_EXCLUDE_RE.search(f) and glob_match(f, globs)]
        if ui:
            changed.append((label, ui))
    routes = changed_routes(repo, sorted({f for _, ui in changed for f in ui})) if changed else {}
    pages = _page_routes(repo) if changed else set()
    plain = {}
    for label, ui in changed:
        for f in ui:
            for path in sorted({c for r in routes.get(f) or () for c in concrete_routes(*r, pages)}) or ["/"]:
                t = marked.get(path) or plain.setdefault(path, {"path": path, "jobs": [], "marked": False, "files": []})
                t["jobs"] += [label] if label not in t["jobs"] else []
                if not t["marked"] and f not in t["files"]:
                    t["files"].append(f)
    targets = list(marked.values()) + [
        {"path": t["path"], "jobs": t["jobs"], "marked": False, "why": "changed " + ", ".join(t["files"])}
        for t in sorted(plain.values(), key=lambda t: t["path"])]
    try:  # screens the last sweep could only time out on under machine load (cmd_ui_sweep_record) get another look
        retry = json.loads((root / "ui-sweep.json").read_text()).get("retry") or []
    except (OSError, ValueError, AttributeError):
        retry = []
    have = {t["path"] for t in targets}
    targets += [{"path": p, "jobs": [], "marked": False, "why": "timed out under load in the last sweep"}
                for p in dict.fromkeys(retry) if isinstance(p, str) and p and p not in have]
    return {"since": since, "head": head, "targets": targets}


SWEEP_BLOCKING_RE = re.compile(r"^- \[blocking\] (.+?) — (.+) — (.+?)\s*$")
SWEEP_UNRENDERED_RE = re.compile(r"^- Unrendered: (.+?)(?: — (.*?))?\s*$")
SWEEP_LOAD_RE = re.compile(r"(?=.*\btime[sd]?[ -]?outs?\b)(?=.*\bload(?:ed)?\b)", re.I)  # "timed out under load"


def _load_timeout(reason) -> bool:
    """True when an `- Unrendered:` reason says the page only timed out because the machine was loaded."""
    return bool(SWEEP_LOAD_RE.search(reason or ""))


SWEEP_OK_RE = re.compile(r"^- ok (.+)")  # the rest is the path plus any note; cmd_ui_sweep_record matches known paths


def _ui_sweep_live(root, d):
    """The ui-sweep.json record when its dir is d, else SystemExit (a stale session)."""
    try:
        rec = json.loads((Path(root) / "ui-sweep.json").read_text())
    except (OSError, ValueError):
        rec = None
    if not isinstance(rec, dict) or not rec.get("dir") or Path(rec["dir"]).resolve() != d.resolve():
        raise SystemExit(f"{d} is not the current UI sweep (ui-sweep.json dir {(rec or {}).get('dir')!r})")
    return rec


def cmd_ui_sweep_record(root, review_file) -> dict:
    """File the sweep review's findings (lanes/uisweep.md): each `- [blocking] <path> — <finding> — <png>` and each
    target that is `- Unrendered:` or not named becomes a p4 Trevor backlog item (an open one is never added twice; an
    unrendered line whose reason says it timed out under load files nothing and its path goes to ui-sweep.json `retry`,
    which ui_sweep_targets adds to the next sweep), then ui-sweep.json gets result fail (anything filed) or pass and the count. A missing review.md or targets.json, or a
    folder that is not the record's dir, changes nothing."""
    review = Path(review_file)
    d = review.parent
    _ui_sweep_live(root, d)
    try:
        text = review.read_text(errors="replace")
        targets = json.loads((d / "targets.json").read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"cannot read the sweep review or targets: {e}")
    jobs = {t["path"]: ", ".join(t.get("jobs") or []) or "?" for t in targets.get("targets") or []}
    named, items, retry = set(), [], []  # items: (text, unless_open); retry: paths that only timed out under load
    by_len = sorted(jobs, key=len, reverse=True)  # a path may hold spaces, "/admin (Orders)": longest known path wins
    known = lambda s: next((p for p in by_len if s == p or s.startswith(p + " ") or s.startswith(p + " —")), s)
    for line in text.splitlines():
        if m := SWEEP_BLOCKING_RE.match(line):
            named.add(known(m[1]))
            key = f"UI sweep: {m[1]}: {m[2]}"
            items.append((f"{key} (merged job {jobs.get(m[1], '?')}; screenshot {m[3]})", key))
        elif m := SWEEP_UNRENDERED_RE.match(line):
            named.add(known(m[1]))
            if _load_timeout(m[2]):  # not a finding: ui_sweep_targets adds the page to the next sweep
                retry.append(known(m[1]))
                continue
            items.append((f"UI sweep could not render {m[1]} (merged job {jobs.get(m[1], '?')}): "
                          f"{m[2] or 'no reason given'}", f"UI sweep could not render {m[1]} ("))
        elif m := SWEEP_OK_RE.match(line):
            named.add(known(m[1]))
    items += [(f"UI sweep could not render {p} (merged job {ids}): not in the sweep review",
               f"UI sweep could not render {p} (") for p, ids in jobs.items() if p not in named]
    for item, key in items:
        if len(item) > ITEM_MAX:  # never cut silently: say where the rest is
            item = item[:ITEM_MAX - 40] + " … (cut; full line in review.md)"
        cmd_backlog_add(root, [item], priority=4, by="t", unless_open=key)
    rec = _ui_sweep_live(root, d)  # re-read: a newer sweep may have started meanwhile
    out = {"at": time.time(), "head": targets.get("head") or rec.get("head"), "since": targets.get("since") or rec.get("since"),
           "result": "fail" if items else "pass", "findings": len(items), "dir": rec["dir"]}
    if retry:
        out["retry"] = list(dict.fromkeys(retry))
    tmp = Path(root) / "ui-sweep.json.tmp"
    tmp.write_text(json.dumps(out, indent=1) + "\n")
    os.replace(tmp, Path(root) / "ui-sweep.json")
    log_process("UI sweep", out["result"], repo=str(Path(root).parent), findings=out["findings"], dir=out["dir"])
    return out


def cmd_check_reuse(root, job_id) -> dict:
    """{"reused": n-1} after writing round-n/check.md from round-(n-1)'s when that round passed at the worktree's current
    HEAD (round-(n-1)/head.txt); else {"reused": None} and nothing written (Check gate step 1)."""
    job = find(read_board(root), check_id(job_id))
    try:
        n = int(job.get("round") or 0)
    except (TypeError, ValueError):
        n = 0
    d = Path(root) / "jobs" / job_id
    prev = d / f"round-{n - 1}"
    if n < 2 or not job.get("worktree"):
        return {"reused": None}
    try:
        head = (prev / "head.txt").read_text(encoding="utf-8").strip()
        lines = (prev / "check.md").read_text(encoding="utf-8").splitlines()
        now = _git(job["worktree"], "rev-parse", "HEAD").decode().strip()
    except (ValueError, OSError, subprocess.SubprocessError):
        return {"reused": None}
    if not head or head != now or not lines or lines[0].strip() != "CHECK: PASS":
        return {"reused": None}
    body = [l for l in lines[1:] if not l.startswith("Check: reused")]
    (d / f"round-{n}").mkdir(parents=True, exist_ok=True)
    (d / f"round-{n}" / "check.md").write_text(
        "\n".join(["CHECK: PASS", f"Check: reused from round {n - 1}, HEAD unchanged", *body]) + "\n", encoding="utf-8")
    return {"reused": n - 1}


def _visual_skip(root, job_id, rd) -> bool:
    """True when rd/visual-diff.md's first line is exactly `VISUAL: same` and spec.md says `UI surface: no` and
    `Complex: no` (the Check gate's Visual diff found nothing on screen changed and none was asked for)."""
    try:
        first = (rd / "visual-diff.md").read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        spec = (Path(root) / "jobs" / job_id / "spec.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    fields = [re.search(rf"^\s*{f}:(.*)$", spec, re.M) for f in ("UI surface", "Complex")]
    return first == ["VISUAL: same"] and all(m and m.group(1).strip().lower() == "no" for m in fields)


def _apply_visual_skip(root, job_id, rd, spawn, keep=()):
    """spawn minus each spawned ui/ux role not in `keep`, after writing its VISUAL_SKIP file, when _visual_skip holds;
    else spawn unchanged."""
    if not _visual_skip(root, job_id, rd):
        return spawn
    for r in ("ui", "ux"):
        if r in spawn and r not in keep:
            (rd / f"review-{r}.md").write_text(VISUAL_SKIP, encoding="utf-8")
    return [r for r in spawn if r not in ("ui", "ux") or r in keep]


def cmd_review_plan(root: Path, job_id: str, incremental: bool = False) -> dict:
    """{"spawn": reviewers to spawn in REVIEWERS order, "since": SINCE sha or None}. Writes the round's carried-forward
    (incremental) or UI/UX (no UI file, or project.md `- Has UI: no`) and security skip files (full); never writes
    board.json."""
    job = live(read_board(root), check_id(job_id))
    wt, base = job.get("worktree"), job.get("base")
    if not wt or not base:
        raise SystemExit(f"job {job_id} has no {'worktree' if not wt else 'base'} on the board")
    try:
        n = int(job.get("round") or 0)
    except (TypeError, ValueError):
        n = 0
    if n < 1:
        raise SystemExit(f"job {job_id} has no round on the board")
    rd = Path(root) / "jobs" / job_id / f"round-{n}"
    inc = _incremental_since(rd.parent / f"round-{n - 1}", wt, base) if incremental and n >= 2 \
        and not base.startswith("-") else None
    if inc:
        since, verdicts = inc
        rework = _rework_roles(rd.parent / f"round-{n - 1}")
        extra = rework | _unrendered_roles(root, rd.parent, n, wt, base)
        spawn = [r for r in REVIEWERS if verdicts[r] == "CHANGES" or r in extra]
        rd.mkdir(parents=True, exist_ok=True)
        for r in REVIEWERS:
            if r not in spawn:
                (rd / f"review-{r}.md").write_text(CARRIED.format(n - 1), encoding="utf-8")
        spawn = _apply_visual_skip(root, job_id, rd, spawn, keep=rework | {r for r in REVIEWERS if verdicts[r] == "CHANGES"})
        _drop_stale(rd, spawn)
        return {"spawn": spawn, "since": since}
    spawn = list(REVIEWERS)
    files = None if base.startswith("-") else _names(wt, f"{base}...HEAD")
    if files is not None:
        skips = {}
        globs = ui_globs(root)
        ui_files = [f for f in sorted(files) if f and not RUNTIME_EXCLUDE_RE.search(f) and glob_match(f, globs or [])]
        if (globs and not ui_files) or project_has_no_ui(root):
            skips.update(ui=UI_SKIP, ux=UI_SKIP)
        elif globs and _no_markup_change(wt, base, ui_files):
            skips.update(ui=NOMARKUP_SKIP, ux=NOMARKUP_SKIP)
        if not any(rx.search(f) for f in files for rx in SECURITY_RES):
            skips["security"] = SECURITY_SKIP
        if skips:
            rd.mkdir(parents=True, exist_ok=True)
        for r, text in skips.items():
            (rd / f"review-{r}.md").write_text(text, encoding="utf-8")
        spawn = [r for r in REVIEWERS if r not in skips]
    if rd.is_dir():  # no round folder means no visual-diff.md
        spawn = _apply_visual_skip(root, job_id, rd, spawn)
    _drop_stale(rd, spawn)
    return {"spawn": spawn, "since": None}


def _route_diff(job):
    """(numstat rows [(added, deleted, path)], changed paths) of base...HEAD in the job's worktree; None when unreadable.
    added/deleted are None for a binary file."""
    wt, base = job.get("worktree"), job.get("base")
    if not wt or not base or base.startswith("-"):
        return None
    try:
        rows = []
        for line in _git(wt, "diff", "--numstat", f"{base}...HEAD", "--").decode().splitlines():
            a, d, path = line.split("\t", 2)
            rows.append((None, None, path) if a == "-" or d == "-" else (int(a), int(d), path))
    except (ValueError, OSError, subprocess.SubprocessError):  # UnicodeDecodeError is a ValueError
        return None
    names = _names(wt, f"{base}...HEAD")
    return None if names is None else (rows, sorted(n for n in names if n))


def _promote_trigger(rows, names):
    """The first Fast lane promotion trigger the diff hits after CHECK: PASS, else None."""
    if binary := next((p for a, _, p in rows if a is None), None):
        return f"binary file {binary}"
    if (lines := sum(a for a, _, _ in rows)) > FAST_MAX_LINES:  # size counts added lines only
        return f"diff over {FAST_MAX_LINES} lines ({lines})"
    if (files := len({p for a, _, p in rows if a})) > FAST_MAX_FILES:
        return f"more than {FAST_MAX_FILES} files ({files})"
    for label, hit in (("schema path", SCHEMA_RE.search), ("env file", ENV_RE.search),
                       ("sensitive path", SENSITIVE_RE.search)):
        if path := next((p for p in names if hit(p)), None):
            return f"{label} {path}"
    return None


def _lilguy_trigger(rows, names, feature_text: str) -> str | None:
    """The first Lilguy Worktree mode promotion trigger the diff hits, else None. Deleted lines never count."""
    if binary := next((p for a, _, p in rows if a is None), None):
        return f"binary file {binary}"
    mechanical = re.search(r"^Lane: lilguy — mechanical", feature_text, re.M)  # renames, config, docs: any size
    if re.search(r"^Lane: lilguy — bug, cause pinned", feature_text, re.M):  # its required repro test is not counted
        rows = [r for r in rows if not is_test_path(r[2])]
    if not mechanical and (lines := sum(a for a, _, _ in rows)) > LILGUY_MAX_LINES:
        return f"diff over {LILGUY_MAX_LINES} added lines ({lines})"
    if not mechanical and (files := len({p for a, _, p in rows if a})) > LILGUY_MAX_FILES:
        return f"more than {LILGUY_MAX_FILES} files with added lines ({files})"
    for p in names:
        short = p.removeprefix("skills/trevskills-scrum/") if p.startswith("skills/trevskills-scrum/") else ""
        named = p in feature_text or f"{p.rpartition('/')[0]}/*.md" in feature_text or ("/" in short and short in feature_text)
        if RULES_RE.search(p) and not named:
            return f"rules file {p} not in feature.md"
    return None


def cmd_route_check(root, job_id: str, check_fails: int = 0, clean_start: bool = False) -> dict:
    """{"promote", "clean_round", "approver_sonnet"} for the job's latest round. Whatever can't be read counts against
    the shortcut: an unreadable diff promotes a passed fast job and gives neither a clean round nor a Sonnet approver."""
    d = Path(root) / "jobs" / check_id(job_id)
    if not d.is_dir():
        raise SystemExit(f"no job folder {d}")
    job = find(read_board(root), job_id)
    lane = job.get("lane") or "standard"
    rounds = sorted((int(p.name[6:]) for p in d.iterdir() if p.is_dir() and re.fullmatch(r"round-\d+", p.name)))
    last_n = rounds[-1] if rounds else 0
    last = d / f"round-{last_n}"
    check = first_word(last / "check.md", ("PASS", "FAIL")) if rounds else None
    reviews_pass = bool(rounds) and all(first_word(last / f"review-{r}.md", ("PASS", "CHANGES")) == "PASS"
                                        for r in REVIEWERS)
    if lane == "lilguy" and not job.get("worktree"):
        # job 1960: a lilguy job built with no board worktree merged unchecked; find its folder or promote
        wt = Path(root).resolve().parent / ".claude" / "worktrees" / f"scrum-{check_id(job_id)}"
        if wt.is_dir():
            cmd_set(root, job_id, [f"worktree={wt}"])
            job = dict(job, worktree=str(wt))
    diff = _route_diff(job)
    names = diff[1] if diff else []
    promote = None
    if lane == "fast" and check == "FAIL" and check_fails >= 2:
        promote = "check failed twice"
    elif lane == "fast" and check == "PASS":
        promote = _promote_trigger(*diff) if diff else "diff unreadable"
    elif lane == "lilguy" and not job.get("worktree"):
        promote = "worktree unset"
    elif lane == "lilguy":
        feature = d / "feature.md"
        feature = feature.read_text(encoding="utf-8", errors="replace") if feature.is_file() else ""
        promote = "check failed 3 times" if check_fails >= 3 else \
            _lilguy_trigger(*diff, feature) if diff else "diff unreadable"
    spec = d / "spec.md"
    hard = re.search(r"^\s*Hard stops:(.*)$", spec.read_text(encoding="utf-8", errors="replace"), re.M) \
        if spec.is_file() else None
    green = check == "PASS" and reviews_pass and clean_start and diff is not None \
        and not any(SCHEMA_RE.search(p) for p in names)
    blocked = any(re.search(r"^Rendered: blocked", f.read_text(encoding="utf-8", errors="replace"), re.M)
                  for f in last.glob("review-*.md")) if rounds else False
    clean_round = green and lane == "standard" and last_n == 1 and bool(hard) and hard.group(1).strip() == "none" \
        and not blocked and not any(ENV_RE.search(p) or SENSITIVE_RE.search(p) for p in names)
    return {"promote": promote, "clean_round": bool(clean_round), "approver_sonnet": bool(green)}


LANE_DIR = Path(__file__).resolve().parent / "lanes"
# (file, start-line regex, end-line regex) for the lane lines a lilguy job runs; the end line is not read
LILGUY_READ_PARTS = (
    ("newjob.md", r"2\. \*\*Base:\*\*", r"3\. \*\*Spec:\*\*"),
    ("newjob.md", r"4\. \*\*Worktree:\*\*", r"5\. \*\*Build:\*\*"),
    ("newjob.md", r"2\. \*\*Runtime files\*\*", r"4\. "),
    ("merge.md", r"3\. \*\*PR\.\*\*", r"## Migrate"),
)


# Same shape for a fast or standard job, keyed by the part `lane-read` takes: `start` at the job's start, `merge` when
# the session first reaches Merge (job 1553: merge.md read at the start rode every later turn); an end of None reads to
# the file's last line
PIPELINE_READ_PARTS = {
    "start": (
        ("newjob.md", r"2\. \*\*Base:\*\*", None),
        ("review.md", r"# Review", None),
    ),
    "merge": (
        ("merge.md", r"3\. \*\*PR\.\*\*", None),
    ),
}


def lilguy_read(lane_dir: Path | None = None) -> str | None:
    """One `sed -n` shell command per lane file for the lines a lilguy job runs, or None when a file or anchor is missing."""
    return _read_parts(LILGUY_READ_PARTS, lane_dir)


def pipeline_read(part: str, lane_dir: Path | None = None) -> str | None:
    """The same for one PIPELINE_READ_PARTS part (`start` or `merge`) of the lane files a fast or standard job runs, or
    None when one of that part's files or anchors is missing."""
    return _read_parts(PIPELINE_READ_PARTS[part], lane_dir)


def _read_parts(parts, lane_dir: Path | None) -> str | None:
    lane_dir = Path(lane_dir) if lane_dir is not None else LANE_DIR
    ranges: dict[str, list[str]] = {}
    for name, start, end in parts:
        try:
            lines = (lane_dir / name).read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        starts = [i for i, ln in enumerate(lines) if re.match(start, ln)]
        if len(starts) != 1:
            return None
        stop = len(lines) if end is None else \
            next((i for i in range(starts[0] + 1, len(lines)) if re.match(end, lines[i])), None)
        if stop is None:
            return None
        ranges.setdefault(name, []).append(f"{starts[0] + 1},{stop}p")
    return "; ".join(f"sed -n {shlex.quote(';'.join(r))} {shlex.quote(str(lane_dir / n))}" for n, r in ranges.items())


# --- lilguy-fit: SKILL.md New job step 3's Lilguy route. Tiny (1 or 2 points, Jev confident it is trivial, a named file,
# or a copy or price literal it changes that few repo files hold) with no hard-stop word in feature.md and a small size
# estimate. Anything unreadable counts as not tiny.
LILGUY_HARD_STOP_RE = re.compile(
    r"\b(?:schema|migrations?|migrate|prisma|sql|money|payments?|pricing|billing|checkout|stripe|auth[nz]?"
    r"|authenticat(?:ion|e)|authoriz(?:ation|e)|login|passwords?|permissions?|secrets?|credentials?"
    r"|api\s+keys?|env\s+vars?|environment\s+variables?)\b|\.env\b"
    r"|\b(?:login|auth|user|cookie|token)\w*\s+sessions?\b|\bsessions?\s+(?:login|auth|user|cookie|token)", re.I)
LILGUY_JEV_MAX_SCORE, LILGUY_JEV_MIN_CONFIDENCE = 1.5, 0.7
# lilguy_estimate: a feature.md's named file paths that exist in the repo (or name a new file in an existing folder), at
# LILGUY_LINES_PER_FILE added lines each (a heuristic; Route still promotes from the real diff).
LILGUY_LINES_PER_FILE = 10
LILGUY_PATH_RE = re.compile(r"[\w./~$-]+\.(?:py|md|html|js|ts|tsx|json|css|sh|ya?ml)\b")
# A repo-relative .claude/ path (not ~/.claude, $HOME/.claude, an absolute path or a job worktree): Claude Code refuses
# edits there in an unattended session, so such a job never takes the unattended Lilguy route.
CLAUDE_DIR_RE = re.compile(r"(?<![\w~/.$}])\.claude/(?!worktrees/)")


def _request_text(feature_text: str) -> str:
    """feature_text without a trailing ` (from <parent job id>)` suffix: that slug is copied from another ticket's
    title, so it is not part of the request and never trips LILGUY_HARD_STOP_RE."""
    return re.sub(r"[ \t]\(from \d+-[\w-]+\)\s*\Z", "", feature_text)


def lilguy_estimate(text: str, repo) -> tuple[int, int]:
    """(files, lines): the distinct file paths text names that exist under repo, or hold a `/` with their folder
    existing there (a new file), and LILGUY_LINES_PER_FILE added lines per file. A bare or short name matching no
    repo path (an example in the prose) is not counted (job 1339)."""
    repo = Path(repo)
    files = sum(1 for p in set(LILGUY_PATH_RE.findall(text))
                if (repo / p).exists() or ("/" in p and (repo / p).parent.is_dir()))
    return files, files * LILGUY_LINES_PER_FILE


# copy_from_literals: a literal a request quotes or prices ("text", “text”, 'text', ‘text’ or a dollar amount), the
# words that join the literal it changes from to the one it changes to, and how many of those words may sit between.
COPY_LITERAL_RE = re.compile(r"\"([^\"\n]+)\"|“([^”\n]+)”|(?<!\w)'([^'\n]+)'(?!\w)|‘([^’\n]+)’|(\$\d+(?:,\d{3})*(?:\.\d+)?)")
COPY_TO_RE = re.compile(r"\b(?:to|with|into|becomes?|should\s+(?:be|read|say))\b|→|->|=>", re.I)
COPY_GAP_MAX_WORDS = 5


def copy_from_literals(text: str) -> list[str]:
    """The quoted or dollar-amount literals text changes from, in order without repeats: of two literals with at most
    COPY_GAP_MAX_WORDS words and no sentence end between them, the first when those words hold a COPY_TO_RE connector
    ("from starting at $75 to starting at $90" gives $75), the second when they are `instead of`."""
    lits = [(m.start(), m.end(), next(g for g in m.groups() if g is not None).strip())
            for m in COPY_LITERAL_RE.finditer(text)]
    out: list[str] = []
    for (_, end, a), (start, _, b) in zip(lits, lits[1:]):
        gap = text[end:start]
        if not a or not b or a == b or re.search(r"[.;!?\n]", gap) or len(gap.split()) > COPY_GAP_MAX_WORDS:
            continue
        lit = b if re.fullmatch(r"\W*instead\s+of\W*", gap, re.I) else a if COPY_TO_RE.search(gap) else None
        if lit and lit not in out:
            out.append(lit)
    return out


def copy_literal_files(literals: list[str], root) -> int | None:
    """How many files tracked in root's repo (root's parent, root's own folder left out: it holds the job's feature.md)
    hold any of literals, by `git grep -lF`; None when there is no literal, the repo has no .git or git fails. The
    literals reach git on stdin (`-f -`), so one that starts with `-` is never read as an option."""
    repo = Path(root).parent
    if not literals or not (repo / ".git").exists():
        return None
    try:
        r = subprocess.run(["git", "-C", str(repo), "grep", "--no-color", "-lzIF", "-f", "-", "--", ".",
                            f":(exclude){Path(root).name}"], input="\n".join(literals).encode(), capture_output=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return len({p for p in r.stdout.split(b"\0") if p}) if r.returncode in (0, 1) else None


def _lilguy_refuses(folder: Path) -> bool:
    """True when cmd_lilguy_fit would refuse the job by text: feature.md or spec.md names a repo-relative `.claude/`
    path, or feature.md holds a LILGUY_HARD_STOP_RE word. Missing files count as no match."""
    def read(name):
        try:
            return (folder / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    feature = read("feature.md")
    return bool(CLAUDE_DIR_RE.search(feature) or CLAUDE_DIR_RE.search(read("spec.md"))
                or LILGUY_HARD_STOP_RE.search(_request_text(feature)))


def _jev_model(folder: Path) -> dict | None:
    """The raw JSON answer of the last `model` line in folder/jev.log (fields: time, step, question, raw, decision,
    seconds), else of the last `spec-model` line (the only one written before New job's lilguy-fit), or None when
    there is no such line or it isn't a JSON object."""
    try:
        lines = (folder / "jev.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    rows = [f for f in (l.split("\t") for l in reversed(lines)) if len(f) > 3]
    fields = next((f for f in rows if f[1] == "model"), None) or next((f for f in rows if f[1] == "spec-model"), None)
    try:
        raw = json.loads(fields[3]) if fields else None
    except ValueError:
        return None
    return raw if isinstance(raw, dict) else None


LANES = ("fast", "standard", "debug", "bigboy", "lilguy")  # the words a feature.md `Lane:` header line may pin


def header_value(path: Path, key: str, words: tuple[str, ...]) -> str | None:
    """The lowercased first word after `<key>:` on a line above path's first `## ` heading, when it is one of words;
    None for a missing or unreadable file or no such line."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return header_in(text, key, words)


def header_in(text: str, key: str, words: tuple[str, ...]) -> str | None:
    """header_value over text already read."""
    w = "|".join(words)
    m = re.search(rf"^{key}:\s*({w})\b(?!\W*\s+or\s+(?:{w})\b)", re.split(r"^## ", text, maxsplit=1, flags=re.M)[0], re.M | re.I)
    return m[1].lower() if m else None  # `Lane: lilguy or fast.` names two words: pins neither (job 1560)


def feature_text(text: str, points: int | None = None) -> str:
    """text as a feature.md body: an inline `Lane:` / `Complex:` / `Runs on:` clause (a backlog item is one line) is also
    written on its own header line after the first line, where header_value reads it. The last valid clause of each key wins.
    A key inside a backtick span is a quote, not a clause (job 1570's `Lane: fast (feature.md)`), and pins nothing.
    points (the claimed backlog item's) is written as a `Points: <n>` header line first (job 1586: a shop run's throwaway
    board has no backlog item for lilguy-fit to read it from)."""
    hdr = {"Points": str(points)} if type(points) is int and points in FIB else {}
    for m in re.finditer(r"\b(Lane|Complex|Runs on):\s*(\w+\b.*?)(?=\s+(?:Lane|Complex|Runs on):|\Z)", text, re.S):
        if text.count("`", 0, m.start()) % 2:  # inside a backtick span
            continue
        key, rest = m[1], " ".join(m[2].split())
        words = {"Lane": LANES, "Complex": ("yes", "no")}.get(key, RUNS_ON)
        if re.match(r"\w+", rest)[0].lower() in words and not re.match(rf"\w+\W*\s+or\s+(?:{'|'.join(words)})\b", rest, re.I):  # "debug," / "no." count; `<lane> or <lane>` pins none
            hdr[key] = rest
    first, _, more = text.rstrip("\n").partition("\n")
    return first + "\n" + "".join(f"{k}: {v}\n" for k, v in hdr.items()) + (more + "\n" if more else "")


def job_complex(root: Path, job_id: str) -> bool:
    """True only when feature.md's header `Complex:` is yes, or, with no such line there, spec.md's is."""
    d = Path(root) / "jobs" / job_id
    return (header_value(d / "feature.md", "Complex", ("yes", "no"))
            or header_value(d / "spec.md", "Complex", ("yes", "no"))) == "yes"


# --- Runs on (job 1155): which machine may run a job. `shop` jobs never start here, `main` jobs never go to a worker,
# and an `any` waiting child goes to a worker with room first (cmd_ready, serve.py shop_tick).
RUNS_ON = ("any", "main", "shop")
SHOP_NOTES = Path(__file__).resolve().with_name("shop")  # machine-notes-<alias>.md, one per worker Mac
SHOP_ROOM_TTL = 180  # seconds serve.py's shop-room.json counts as fresh
SHOP_FIRST_MAX_S = 300  # seconds an `any` waiting child is left to the shop before this Mac claims it anyway


def stored_runs_on(root, job: dict) -> str | None:
    """The job's tag as it stands: feature.md's header `Runs on:`, else its board `runs_on`; None when untagged.
    Never asks Jev and never writes, so it is safe under the board lock."""
    return header_value(Path(root) / "jobs" / str(job.get("id")) / "feature.md", "Runs on", RUNS_ON) \
        or (job.get("runs_on") if job.get("runs_on") in RUNS_ON else None)


def main_only_terms() -> list[str]:
    """The terms of every shop.workers() worker's `## Cannot run` section (each `- ` bullet a comma-separated list) in
    SHOP_NOTES/machine-notes-<alias>.md, in order with no repeats. A worker with no file or no section adds none."""
    import shop  # shop.py never imports board.py; only the tag needs it here
    terms = []
    for w in shop.workers():
        try:
            text = (SHOP_NOTES / f"machine-notes-{w.alias}.md").read_text(encoding="utf-8")
        except OSError:
            continue
        for line in (md_section(text, "Cannot run") or "").splitlines():
            if line.startswith("- "):
                terms += [t.strip() for t in line[2:].split(",") if t.strip()]
    return list(dict.fromkeys(terms))


def names_main_only(text: str, terms: list[str]) -> bool:
    """True when text names a term, any case, never inside a longer word (`brew` is not in `Homebrew`)."""
    return any(re.search(r"(?<!\w)" + r"\s+".join(map(re.escape, t.split())) + r"(?!\w)", text, re.I)
               for t in terms if t.split())


def jev_main_only(text: str, terms: list[str], log_path: Path) -> bool | None:
    """Jev's answer to jev-gate.py's runs-on question, logged to log_path: True (needs this Mac), False, or None when
    unsure or on any error. A network call: never under the board lock."""
    gate = jev_gate()
    decision = gate.run("runs-on", lambda asked: gate.runs_on(text, terms, asked), log_path)
    return {"main": True, "any": False}.get(decision)


def tag_runs_on(root, job_id: str) -> str:
    """The job's Runs on tag. feature.md's header wins and is stored when it differs from the board's `runs_on`; else
    the stored tag; else it is decided once: `main` for an edit kind (feature.md `Kind: edit-*`), `any` for an empty main_only_terms() (no Jev call), else jev_main_only
    over feature.md plus spec.md (`main` / `any`), falling back to names_main_only when Jev is unsure or down. A
    decided tag is stored under the lock only when the job is still untagged. Call it outside the board lock."""
    job = find(read_board(root), check_id(job_id))
    folder = Path(root) / "jobs" / job_id
    head = header_value(folder / "feature.md", "Runs on", RUNS_ON)
    stored = job.get("runs_on") if job.get("runs_on") in RUNS_ON else None
    if stored and head in (None, stored):
        return stored
    tag = head
    if not tag and edit_kind((folder / "feature.md").read_text(errors="replace") if (folder / "feature.md").is_file() else ""):
        tag = "main"  # an edit job drives apps on this Mac (Edits, Blender, QuickTime): never sent to a shop worker
    if not tag:
        text = "\n\n".join(f.read_text(encoding="utf-8", errors="replace")
                           for f in (folder / "feature.md", folder / "spec.md") if f.is_file())
        terms = main_only_terms()
        main = jev_main_only(text, terms, folder / "jev.log") if terms else False
        tag = "main" if (names_main_only(text, terms) if main is None else main) else "any"
    with locked_board(root) as board:
        live = find(board, job_id)
        if head or live.get("runs_on") not in RUNS_ON:
            live["runs_on"] = tag
        return live["runs_on"]


def shop_room_path() -> Path:
    """shop-room.json beside projects.json: serve.py's write_shop_room lists the workers with room each tick."""
    return registry_path().parent / "shop-room.json"


NO_GIT_RE = re.compile(r"^- Git: *none\s*$", re.M | re.I)
EDIT_KIND_RE = re.compile(r"^Kind: (edit-reel|edit-animation|edit-vector|edit-photo|edit-embroidery)\s*$", re.M)
OPS_KIND_RE = re.compile(r"^Kind: (ops-data|ops-content)\s*$", re.M)


def no_git(root) -> bool:
    """True only when root/project.md has the line `- Git: none` (job 1362): a project kept in a plain folder with no
    git, which Setup marks and every per-project git or gh pass skips. A missing or unreadable project.md is False."""
    try:
        return bool(NO_GIT_RE.search((Path(root) / "project.md").read_text(errors="replace")))
    except OSError:
        return False


def edit_kind(text: str) -> str | None:
    """The kind on the first `Kind: edit-reel|edit-animation|edit-vector|edit-photo|edit-embroidery` line of a feature.md text, else
    None (job 1362). A job with a kind runs lane=edit (lanes/edit.md)."""
    return _kind_match(EDIT_KIND_RE, text)


def _kind_match(pattern, text: str) -> str | None:
    """The kind in the first line of `text` that `pattern` (EDIT_KIND_RE or OPS_KIND_RE) matches, else None."""
    m = pattern.search(text or "")
    return m.group(1) if m else None


def ops_kind(text: str) -> str | None:
    """The kind on the first `Kind: ops-data|ops-content` line of a feature.md text, else None (`Kind: knowledge` is a
    label only and never matches). A job with a kind runs lane=ops (lanes/ops.md)."""
    return _kind_match(OPS_KIND_RE, text)


OPS_KIND_CUTOFF = 0.7  # jev-gate.py kind: a confident yes
OTHER_KIND_RE = re.compile(r"^Kind: (?:edit-(?:reel|animation|vector|photo|embroidery)|knowledge)\s*$", re.M)
RUN_LINE_RE = re.compile(r"^Run: ", re.M)


def jev_ops_kind(text: str, log_path: Path) -> str | None:
    """`ops-data` or `ops-content` when Jev confidently sorts text (a feature.md) as one, logged to log_path as a `kind`
    line; None when unsure, on any error or for `code`. The last `kind` line already in log_path answers with no new
    Jev call. A network call: never under the board lock."""
    try:
        for fields in reversed([l.split("\t") for l in log_path.read_text(encoding="utf-8", errors="replace").splitlines()]):
            if len(fields) > 4 and fields[1] == "kind":
                return fields[4] if fields[4] in ("ops-data", "ops-content") else None
    except OSError:
        pass
    try:
        gate = jev_gate()
        decision = gate.run("kind", lambda asked: gate.kind_of(text, asked), log_path)
    except (Exception, SystemExit):
        return None
    return decision if decision in ("ops-data", "ops-content") else None


def tag_kind(root, job_id: str) -> str | None:
    """The job's ops kind (`ops-data` or `ops-content`), else None (a code job). A feature.md `Kind:` line wins with no
    Jev call and is stored on the board job when it differs: an ops line returns it; an edit-* or knowledge line returns
    None. Else a stored ops kind. Else jev_ops_kind over feature.md (cached in jev.log); a Jev-sorted `ops-data` with no
    `Run: ` line in feature.md is None. A Jev answer is not stored: New job's `B set` does that. Never raises on a Jev
    problem. Call it outside the board lock."""
    job = find(read_board(root), check_id(job_id))
    folder = Path(root) / "jobs" / job_id
    try:
        text = (folder / "feature.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    line = ops_kind(text)
    if line:
        if job.get("kind") != line:
            with locked_board(root) as board:
                find(board, job_id)["kind"] = line
        return line
    if OTHER_KIND_RE.search(text):
        return None
    if job.get("kind") in ("ops-data", "ops-content"):
        return job["kind"]
    if not text.strip():
        return None
    kind = jev_ops_kind(text, folder / "jev.log")
    return None if kind == "ops-data" and not RUN_LINE_RE.search(text) else kind


def cmd_ops_kind(root, job_id: str) -> str:
    """ops-kind: tag_kind as a word, `ops-data`, `ops-content` or `none`."""
    return tag_kind(root, check_id(job_id)) or "none"


def shop_project_excluded(root) -> bool:
    """A project the shop never runs: project.md has a `- Base branch:` line, names docker (any case), or marks a
    no-git project (no_git: `- Git: none`)."""
    try:
        profile = (Path(root) / "project.md").read_text(errors="replace")
    except OSError:
        profile = ""
    return bool(re.search(r"^- Base branch:", profile, re.M) or "docker" in profile.lower()  # docker: as docker_projects reads it
                or NO_GIT_RE.search(profile))


def shop_room(root) -> bool:
    """True when shop-room.json is at most SHOP_ROOM_TTL seconds old, lists a worker and the project is not
    shop_project_excluded. A missing, stale or malformed file is False; so is any read under unittest with the registry
    not moved (SCRUM_REGISTRY unset)."""
    if "unittest" in sys.modules and not os.environ.get("SCRUM_REGISTRY"):
        return False
    try:
        room = json.loads(shop_room_path().read_text())
        fresh = abs(time.time() - float(room["at"])) <= SHOP_ROOM_TTL  # abs: a clock stepped back is not "fresh forever"
        workers = room["workers"]
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return fresh and isinstance(workers, list) and bool(workers) and not shop_project_excluded(root)


DIGEST_PROPOSALS_RE = re.compile(r"digests/\d+/proposals\.json")  # cloud.md expands these; shop dispatch does not
SHOP_LILGUY_HELD_SECS = 7200  # seconds this Mac's gates hold a lilguy job before the shop may take it (job 1246)
SHOP_LILGUY_MEM_HELD_SECS = 1800  # the same for a swap or vm_pressure hold (job 1518)
SHOP_MEM_GATES = frozenset({"swap", "vm_pressure"})  # gate heads SHOP_LILGUY_MEM_HELD_SECS applies to


def shop_excluded(root, job: dict, jobs: list) -> bool:
    """A job shop dispatch never takes: a feature.md naming a digest proposals.json, always; or lilguy as the local
    lilguy route takes it (board lane, `Lane: lilguy` anywhere in feature.md, or lilguy-fit.json fit true with no parent
    or a Run-all parent) unless this Mac's gates have held it long enough: its queue-gates.txt names a gate and a gate
    head's "held" seconds in current-gates.json (note_current_gate, job 1485) are over SHOP_LILGUY_MEM_HELD_SECS for a
    swap or vm_pressure head that queue-gates.txt names, else over SHOP_LILGUY_HELD_SECS (jobs 1246, 1518; play_queued
    and updatedAt never count, as later board writes push them forward; a missing or empty file, or a missing,
    malformed or non-positive held, keeps it excluded). cmd_ready never leaves an excluded job to the shop."""
    folder = Path(root) / "jobs" / job["id"]
    try:
        feature = (folder / "feature.md").read_text(errors="replace")
    except OSError:
        feature = ""  # dispatched, then failed as a step: the claim is put back
    if DIGEST_PROPOSALS_RE.search(feature):
        return True
    runall = not job.get("parent") or next((j.get("lane") for j in jobs if j["id"] == job["parent"]), None) == "runall"
    if not (job_lane(root, job) == "lilguy" or re.search(r"\bLane:\s*lilguy\b", feature, re.I)
            or runall and _health_file(folder / "lilguy-fit.json", dict).get("fit") is True):
        return False
    try:
        gates = (folder / "queue-gates.txt").read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        gates = []
    mem = SHOP_MEM_GATES & {g.split("(", 1)[0] for g in gates}
    for head, rec in _health_file(folder / CURRENT_GATES, dict).items():
        held = rec.get("held") if isinstance(rec, dict) else None
        limit = SHOP_LILGUY_MEM_HELD_SECS if head in mem else SHOP_LILGUY_HELD_SECS
        if gates and type(held) in (int, float) and held > limit:
            return False
    return True


def cmd_lilguy_fit(root, job_id: str) -> dict:
    """The _lilguy_verdict, also written to jobs/<id>/lilguy-fit.json when that folder exists (process-health reads it)."""
    verdict = _lilguy_verdict(root, job_id)
    folder = Path(root) / "jobs" / job_id
    hand_off = None
    if verdict["fit"] and not os.environ.get("SCRUM_SPAWN"):  # job 1261: a hand-started job builds headless on the Orchestrator model, not in Trevor's Opus session
        if find(read_board(root), check_id(job_id)).get("started_by") == "hand":
            hand_off = f"B spawn {job_id} start"
            cmd_set(root, job_id, ["lane=lilguy"])  # spawn() keeps CLAUDE.md only for a lilguy-lane job
    if folder.is_dir():
        out = folder / "lilguy-fit.json"
        try:
            old = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = None
        if isinstance(old, dict) and old.get("fit") is False and verdict["why"].startswith("already on "):
            return verdict  # the first refusal is the cause; a re-run after promotion must not hide it
        feature = folder / "feature.md"
        text = _request_text(feature.read_text(encoding="utf-8", errors="replace")) if feature.is_file() else ""
        parent = re.search(r"[ \t]\(from (\d+-[\w-]+)\)\s*\Z", feature.read_text(encoding="utf-8", errors="replace")) if feature.is_file() else None
        pts = _job_points(root, job_id)
        raw = _jev_model(folder) or {}
        files, lines = lilguy_estimate(text, Path(root).parent)
        hard = LILGUY_HARD_STOP_RE.search(text)
        _write_json(out, {**verdict, "parent": parent[1] if parent else None, "points": pts,
                          "hard_stop": hard[0] if hard else None, "estimate": {"files": files, "lines": lines},
                          "jev": {"score": raw.get("score"), "confidence": raw.get("confidence")} if raw else None})
    return {**verdict, "hand off": hand_off} if hand_off else verdict


def _job_points(root, job_id: str) -> int | None:
    """The job's points: its backlog item's, else feature.md's header `Points:` line (job 1586: a shop run's throwaway
    board has no backlog item naming the job; the claim wrote the points there)."""
    item = next((i for i in read_backlog(root)[1] if i["job"] == job_id), None)
    if item and item["points"] is not None:
        return item["points"]
    got = header_value(Path(root) / "jobs" / job_id / "feature.md", "Points", tuple(map(str, FIB)))
    return int(got) if got else None


def _lilguy_verdict(root, job_id: str) -> dict:
    """{"fit", "why"}: a job already on another lane never fits, nor one whose feature.md or spec.md names a
    repo-relative `.claude/` path (CLAUDE_DIR_RE); then a feature.md header `Lane:` line decides (lilguy
    fits, any other lane doesn't); then a LILGUY_HARD_STOP_RE word in feature.md, or a lilguy_estimate over
    LILGUY_MAX_LINES / LILGUY_MAX_FILES, refuses; else fit when tiny by 1 backlog point, by Jev, by naming a file, by 2
    backlog points, or, naming no file, by a copy_from_literals literal that 1 to LILGUY_MAX_FILES repo files hold."""
    job = find(read_board(root), check_id(job_id))
    lane = job.get("lane")
    if lane and lane != "lilguy":
        return {"fit": False, "why": f"already on {lane} lane"}
    folder = Path(root) / "jobs" / job_id
    feature = folder / "feature.md"
    for f in (feature, folder / "spec.md"):
        if f.is_file() and CLAUDE_DIR_RE.search(f.read_text(encoding="utf-8", errors="replace")):
            return {"fit": False, "why": "names a .claude/ path"}
    if pinned := header_value(feature, "Lane", LANES):
        return {"fit": pinned == "lilguy", "why": f"feature.md Lane: {pinned}"}
    text = _request_text(feature.read_text(encoding="utf-8", errors="replace")) if feature.is_file() else ""
    if m := LILGUY_HARD_STOP_RE.search(text):
        return {"fit": False, "why": f"hard-stop word {m[0]!r} in feature.md"}
    files, lines = lilguy_estimate(text, Path(root).parent)
    if lines > LILGUY_MAX_LINES or files > LILGUY_MAX_FILES:
        return {"fit": False, "why": f"estimate over lilguy limits: about {lines} added lines in {files} files "
                                     f"(limits {LILGUY_MAX_LINES} lines, {LILGUY_MAX_FILES} files)"}
    pts = _job_points(root, job_id)
    if pts == 1:
        return {"fit": True, "why": "backlog item is 1 point"}
    raw = _jev_model(folder) or {}
    score, conf = raw.get("score"), raw.get("confidence")
    if is_num(score) and is_num(conf) and score < LILGUY_JEV_MAX_SCORE and conf >= LILGUY_JEV_MIN_CONFIDENCE:
        return {"fit": True, "why": f"Jev score {score} at confidence {conf}"}
    if files:
        return {"fit": True, "why": f"names {files} file(s), estimate about {lines} added lines"}
    if pts == 2:  # the estimate is within the limits here: an over-limit one was refused above
        return {"fit": True, "why": "backlog item is 2 points, estimate within lilguy limits"}
    lits = copy_from_literals(text)  # names no file here: a named one fit above
    held = copy_literal_files(lits, root)
    quoted = ", ".join(map(repr, lits))
    if held and held <= LILGUY_MAX_FILES:
        return {"fit": True, "why": f"names no file; changes {quoted}, held by {held} repo file(s)"}
    pts = f"{pts} points" if pts else "no points"
    jev = f"Jev score {score} at confidence {conf}" if raw else "no Jev model answer"
    copy = f", {quoted} in {held} files" if held is not None else ""
    return {"fit": False, "why": f"not tiny: {pts}, {jev}{copy}"}


# --- move-ratio: SKILL.md Review gives reviewers MOVE_ONLY=yes when nearly every added line is a verbatim move.
# Colours are pinned so the user's git config can't change what is parsed; the meta colour keeps `+++` headers apart.
MOVE_COLORS = ("color.diff.new=green", "color.diff.newMoved=bold cyan", "color.diff.meta=bold")
NEW_SGR, MOVED_SGR = b"\x1b[32m+", b"\x1b[1;36m+"


def cmd_move_ratio(root: Path, job_id: str) -> dict:
    """{"added", "moved", "ratio"} for the job worktree's BASE...HEAD diff (ratio = moved / added, 2 decimals, 0.0 when
    nothing is added); else {"ok": False, "error"}."""
    try:
        job = find(read_board(root), check_id(job_id))
        wt, base = job.get("worktree"), job.get("base")
        if not wt or not base:
            raise ValueError(f"job has no {'worktree' if not wt else 'base'} on the board")
        if base.startswith("-"):
            raise ValueError(f"bad base {base!r}")
        pins = [a for c in MOVE_COLORS for a in ("-c", c)]
        out = _git(wt, *pins, "diff", "--no-ext-diff", "--color=always", "--color-moved=plain", "--color-moved-ws=no", f"{base}...HEAD", "--")
        added = moved = 0
        for line in out.splitlines():
            if line.startswith(MOVED_SGR):
                added, moved = added + 1, moved + 1
            elif line.startswith(NEW_SGR):
                added += 1
        return {"added": added, "moved": moved, "ratio": round(moved / added, 2) if added else 0.0}
    except (ValueError, OSError, SystemExit, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)}

# --- artifacts: what a cloud job may push to scrum-artifacts/<id> (SKILL.md Cloud lane); files are left out whole ---
ARTIFACT_MAX = 1024 * 1024
SKIPPED = "skipped-secrets.txt"
SECRET_RES = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?<![A-Za-z0-9_-])(?:sk-|ghp_|gho_|ghs_|github_pat_|xox[abprs]-)[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}"),
    re.compile(r"postgres(?:ql)?://[^\s:/@]+:[^\s/@]+@"),
    re.compile(r"^[ \t]*(?:export[ \t]+)?[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|KEY)[A-Z0-9_]*[ \t]*=[ \t]*\S", re.M),
)


def secret_filter(text):
    """True when text holds something that looks like a credential (private key, API token, DB URL, NAME=secret line)."""
    return any(r.search(text) for r in SECRET_RES)


def cmd_artifacts(root, job_id):
    """Paths (relative to root) of the job's files that are safe to push; every other file is named in skipped-secrets.txt."""
    folder = Path(root) / "jobs" / check_id(job_id)
    if not folder.is_dir():
        raise SystemExit(f"no job folder {folder}")
    ok, skipped = [], []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        for name in sorted(filenames) + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            p = Path(dirpath) / name
            rel = p.relative_to(folder).as_posix()
            if rel == SKIPPED:
                continue
            try:
                if p.is_symlink() or not p.is_file() or p.stat().st_size >= ARTIFACT_MAX:
                    raise ValueError
                text = p.read_bytes().decode("utf-8")
            except (OSError, ValueError):  # UnicodeDecodeError is a ValueError
                skipped.append(rel)
                continue
            (skipped if secret_filter(text) else ok).append(rel)
    listing = folder / SKIPPED
    if listing.is_symlink():  # never write through a link out of the job folder
        listing.unlink()
    if skipped:
        body = "".join(f"{r}\n" for r in skipped)
        listing.write_text(body, encoding="utf-8")
        if not secret_filter(body):
            ok.append(SKIPPED)
    elif listing.exists():
        listing.unlink()
    return [f"jobs/{job_id}/{r}" for r in ok]


# --- triage: scrum-triager writes triage/<NNN>/plan.json; triage-apply turns it into backlog edits under the lock ---
TRIAGE_RE = DIGEST_RE


def cmd_triage_start(root):
    with locked_board(root):
        n = sum(not i["done"] for i in read_backlog(root)[1])
        return {"id": claim_folder(Path(root) / "triage"), "open": n} if n else {"id": None, "open": 0}


def retire_blocker(board: dict, item: dict, reason: str, items: list) -> str | None:
    """Why a triage retire of an open item must be refused, or None. The cited jobs are the board jobs the reason names
    (full id, or number after `job`/`jobs`), the → job of each closed line with the item's text, and any job whose
    `requeued` is the item's item_key. Refused when there is at least one and every one is aborted without evidence: its
    reason is not `obsolete:`/`looks already fixed:`, or the item is Trevor self-text (job 1511)."""
    jobs = [j for j in board.get("jobs") or [] if isinstance(j, dict) and j.get("id")]
    full = {t.rstrip("-") for t in re.findall(r"\d{3,}-[a-z0-9-]+", reason)}
    named, key = job_refs(reason), item_key(item)
    closed = {i["job"] for i in items if i["done"] and i["job"] and i["text"] == item["text"]}
    cited = [j for j in jobs if j["id"] in full or names_job(named, j["id"]) or j["id"] in closed or j.get("requeued") == key]
    evidence = tuple(p for p in CLOUD_SELF_ABORT if p != "requeue:")
    self_text = "trevor self-text" in item["text"].lower()
    bare = lambda j: j.get("stage") == "aborted" and (self_text or not str(j.get("reason") or "").startswith(evidence))
    if cited and all(map(bare, cited)):
        return f"cites only aborted job(s) {', '.join(j['id'] for j in cited)}; left open"
    return None


def cmd_triage_apply(root, triage_id):
    """Merge, retire, move to manual-checks.md and estimate open items by exact text, then add dependencies. Merges
    rewrite needs references to the merged item; retires and manual moves drop them. Stale, reused or bad entries are
    skipped and reported."""
    d = Path(root) / "triage" / str(triage_id)
    if not TRIAGE_RE.fullmatch(str(triage_id)) or not d.is_dir():
        raise SystemExit(f"no triage {triage_id!r}")
    try:
        plan = json.loads((d / "plan.json").read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"triage {triage_id}: plan.json is missing or not JSON ({e}); backlog.md was not touched")
    if not isinstance(plan, dict) or any(not isinstance(plan.get(k) or [], list)
                                         for k in ("merge", "retire", "manual", "estimate", "depends")):
        raise SystemExit(f"triage {triage_id}: plan.json must be an object of merge/retire/manual/estimate/depends lists; "
                         "backlog.md was not touched")
    report = {"Merged": [], "Retired": [], "Manual": [], "Estimated": [], "Depends": [], "Skipped": []}
    manual = []  # texts moved to manual-checks.md
    consumed, merged = [], []  # items merged, retired or moved to manual; the new merged items
    gone = lambda text: format_item({"done": True, "points": None, "text": text, "job": None, "why": None})
    with locked_board(root):
        lines, items = read_backlog(root)
        was = {i["index"]: (i["id"], list(i["needs"])) for i in items}
        used, before = set(), {}  # item indexes already consumed; line number -> merged items inserted above it
        remap, dropped = {}, set()  # id of a merged-away item -> its merged item; ids of retired and manual items

        def claim(texts):
            """The open item for each text (first free one wins), or (None, cause)."""
            got = []
            for t in texts:
                match = [i for i in items if not i["done"] and i["text"] == t]
                free = [i for i in match if i["index"] not in used and i not in got]
                if not free:
                    return None, "already used by an earlier entry" if match else f'no open item has the text "{clean(t, ITEM_MAX)}"'
                got.append(free[0])
            return got, None

        for kind in ("merge", "retire", "manual", "estimate"):
            for e in plan.get(kind) or []:
                e = e if isinstance(e, dict) else {}
                texts = e.get("items") if kind == "merge" else [e.get("item")]
                texts = texts if isinstance(texts, list) else []
                label = f"{kind} " + " + ".join(f'"{clean(t, ITEM_MAX)}"' for t in texts)
                got, cause = (None, "a merge needs at least 2 items") if len(texts) < 2 and kind == "merge" else claim(texts)
                pts = e.get("points")
                pts = pts if type(pts) is int and pts in FIB else None  # bool and 5.0 are not points
                if got and kind == "merge" and not clean(e.get("text") or ""):
                    cause = "merged text is empty"
                elif got and kind == "merge" and len(clean(e["text"], None)) > ITEM_MAX:
                    cause = "merged text is over 2000 characters"
                elif got and kind in ("retire", "manual") and not clean(e.get("reason") or ""):
                    cause = "no reason given"
                elif got and kind == "retire" and (cause := retire_blocker(read_board(root), got[0], clean(e["reason"]), items)):
                    print(f'triage {triage_id}: kept open "{clean(got[0]["text"], ITEM_MAX)}" — '
                          f'{cause.removesuffix("; left open")}', file=sys.stderr)
                elif got and kind == "estimate" and got[0]["points"] is not None:
                    cause = "already pointed"
                elif got and kind == "estimate" and pts is None:
                    cause = f"points {e.get('points')!r} not in {', '.join(map(str, FIB))}"
                if cause:
                    report["Skipped"].append(f"- {label} — {cause}\n")
                    continue
                used.update(i["index"] for i in got)
                if kind != "estimate":
                    consumed.extend(got)
                why = clean(e.get("why") or "") or None
                if kind == "merge":
                    text = clean(e["text"], ITEM_MAX)
                    own = {i["id"] for i in got if i["id"]}
                    by = "t" if any(i["by"] == "t" for i in got) else "back" if any(i["by"] == "back" for i in got) else None
                    n = max((i["priority"] for i in got if i["priority"]), default=None)
                    item = {"done": False, "points": pts, "text": text, "job": None, "why": why, "id": None,
                            "priority": source_priority(by, n, critical=(by is None and n == 5), current=n),
                            "needs": list(dict.fromkeys(n for i in got for n in i["needs"] if n not in own)),
                            "setup": list(dict.fromkeys(st for i in got for st in i["setup"])),  # still waits on setup
                            "after": list(dict.fromkeys(a for i in got for a in i["after"])),  # and on other repos' jobs
                            "by": by}
                    merged.append(item)
                    remap.update((n, item) for n in own)
                    for i in got:
                        lines[i["line"]] = gone(i["text"]) + f" <!-- merged into triage {triage_id} -->"
                    before.setdefault(min(i["line"] for i in got), []).append(item)
                    report["Merged"].append(f"- {text}\n" + "".join(f"  - replaced: {i['text']}\n" for i in got))
                elif kind == "retire":
                    reason = clean(e["reason"])
                    lines[got[0]["line"]] = gone(got[0]["text"]) + f" <!-- retired: {reason} -->"
                    dropped.add(got[0]["id"])
                    report["Retired"].append(f"- {got[0]['text']} — {reason}\n")
                    if got[0]["by"] in ("t", "back"):  # Trevor's own item: he sees the retire in manual-checks.md too
                        manual.append(got[0]["text"])
                        report["Manual"].append(f"- {got[0]['text']} — retired, check: {reason}\n")
                elif kind == "manual":
                    reason = clean(e["reason"])
                    lines[got[0]["line"]] = gone(got[0]["text"]) + f" <!-- manual check: {reason} -->"
                    dropped.add(got[0]["id"])
                    manual.append(got[0]["text"])
                    report["Manual"].append(f"- {got[0]['text']} — {reason}\n")
                else:
                    got[0].update(points=pts, why=why)
                    lines[got[0]["line"]] = format_item(got[0])
                    report["Estimated"].append(f"- [{pts}] {got[0]['text']}" + (f" — {why}" if why else "") + "\n")
        gone_idx = {i["index"] for i in consumed}
        live = [i for i in items if not i["done"] and i["index"] not in gone_idx] + merged  # the open items now
        ids = items + merged  # every id in backlog.md, for new_item_id

        def give_id(item):
            if not item["id"]:
                item["id"] = new_item_id(ids)
            return item["id"]

        for i in live:  # point references at the merged item, and forget retired and manual items
            needs = []
            for n in i["needs"]:
                if n in remap:
                    n = give_id(remap[n])
                if n not in dropped and n not in needs and n != i["id"]:
                    needs.append(n)
            i["needs"] = needs

        def reaches(start, goal):
            """True when goal is start or is among start's needs, followed through the open items."""
            seen, todo = set(), [start]
            while todo:
                cur = todo.pop()
                if cur is goal:
                    return True
                if id(cur) not in seen:
                    seen.add(id(cur))
                    todo.extend(o for n in cur["needs"] for o in live if o["id"] == n)
            return False

        for e in plan.get("depends") or []:
            e = e if isinstance(e, dict) else {}
            text = e.get("item") if isinstance(e.get("item"), str) else ""
            needs = [t for t in e.get("needs") if isinstance(t, str)] if isinstance(e.get("needs"), list) else []
            label = f'depends "{clean(text, ITEM_MAX)}" ← ' + (" + ".join(f'"{clean(t, ITEM_MAX)}"' for t in needs) or "nothing")
            find_open = lambda t: next((i for i in live if i["text"] == t), None)
            item, pre = find_open(text), [find_open(t) for t in needs]
            missing = next((t for t, p in zip(needs, pre) if p is None), None)
            if not needs:
                cause = "needs no prerequisites"
            elif item is None or missing is not None:
                cause = f'no open item has the text "{clean(text if item is None else missing, ITEM_MAX)}"'
            elif any(p is item for p in pre):
                cause = "an item cannot depend on itself"
            elif any(reaches(p, item) for p in pre):
                cause = "would close a dependency cycle"
            else:
                cause = None
            if cause:
                report["Skipped"].append(f"- {label} — {cause}\n")
                continue
            pre = [p for n, p in enumerate(pre) if all(p is not q for q in pre[:n])]
            for p in pre:
                if (n := give_id(p)) not in item["needs"]:
                    item["needs"].append(n)
            report["Depends"].append(f"- {item['text']} ← " + "; ".join(p["text"] for p in pre) + "\n")
        for i in live:
            if "index" in i and (i["id"], i["needs"]) != was[i["index"]]:
                lines[i["line"]] = format_item(i)
        write_backlog(root, [x for n, line in enumerate(lines) for x in (*map(format_item, before.get(n, [])), line)])
        _append_manual(root, manual)
        for i in consumed:
            drop_spec(root, i["text"], live)
        text = f"# Triage {triage_id} — {now()}\n" + "".join(
            f"\n## {title}\n" + ("".join(rows) or "None.\n") for title, rows in report.items())
        (d / "report.md").write_text(text)
        (Path(root) / "triage" / "latest.md").write_text(text)
    return {"merged": len(report["Merged"]), "retired": len(report["Retired"]), "manual": len(report["Manual"]),
            "estimated": len(report["Estimated"]), "depends": len(report["Depends"]), "skipped": len(report["Skipped"])}


# --- bigboy: plan.md becomes 2-5 child jobs; `ready` claims the ones that may start ---
PLAN_FIELDS = {"Depends on": "depends", "Parallel": "parallel", "Exposure": "exposure", "Hard stops": "hard",
               "Human setup": "setup"}
TICKET_RE = re.compile(r"^### (T\d+):[ \t]*(.*?)\s*$")
PATH_RE = re.compile(r"^[\w.@~+/()\[\]-]*[./][\w.@~+/()\[\]-]*$")  # a backticked token with a / or . and nothing code-like; () and [] for Next.js route folders
IDLE = ("waiting", "done", "aborted", "needs-human")  # every other child stage counts as in progress


def idle(job) -> bool:
    """Not in progress: an IDLE stage, paused by Trevor or stalled in its own stage (it keeps its stage but holds no
    slot)."""
    return job.get("stage") in IDLE or bool(job.get("paused")) or stalled(job)


BLOCKED = "bigboy blocked"
RUNALL_BLOCKED = "run-all blocked"
CHAIN_LOCKED = "bigboy chain lock held by"  # SKILL.md Chaining step 5; re-evaluated like a blocked parent
WAITING_ON = "waiting on you in: "  # a running parent whose children wait on Trevor (needs-human or Setup done)
MACHINE_WAIT = "waiting: "  # a running parent whose next claim waits on free RAM or disk (machine_ok) or usage
OVERLAP_WAIT = MACHINE_WAIT + "files overlap "  # its waiting children share Likely files with another tree's live job


def resume_first(jobs: list[dict]) -> int:
    """How many jobs on this board Trevor paused (not done or aborted), plus the unpaused stalled ones, either shape
    (not lilguy-in-checkout). A stalled child whose parent is on the board but paused or not running is skipped:
    auto_resume leaves it alone. Since job 751 they no longer hold new claims (cmd_ready checks their Likely files)."""
    by_id = {j.get("id"): j for j in jobs}

    def parent_idle(j):
        p = by_id.get(j.get("parent")) if j.get("parent") else None
        return bool(p) and (bool(p.get("paused")) or p.get("stage") != "running")

    return sum(bool(j.get("paused")) and j.get("stage") not in ("done", "aborted")
               or stalled(j) and not lilguy_in_checkout(j) and not no_pr_job(j) and not parent_idle(j) for j in jobs)


# The Claude accounts automated sessions may run on, in order: (name, config dir, reserve) where reserve is
# (5h used %, 7d used %) at which a backup account is kept for Trevor (None for a window it never holds on), or None.
# The primary account (primary_account) is held only at its PRIMARY_RESERVE. SCRUM_ACCOUNTS (JSON) replaces ACCOUNTS.
ACCOUNTS = (("main", "~/.claude", (None, 90)), ("owa", "~/.claude-owa", (None, 90)))
# (5h, 7d) used % at which an account is held while it is primary_account; an unlisted account has no primary cap.
# Trevor 2026-11-18 (job 1208): OWA as primary hands new work to main at 97% 7d, keeping room for messageManager and his chats.
# Trevor 2026-11-19 (job 1228): main as primary keeps 1% so a Trevor-run job (grocery run) can still start.
# Trevor 2026-11-20: main's cap is the HARD_STOP_PCT line, so pick_account never picks what spawn would refuse.
PRIMARY_RESERVE = {"owa": (None, 97), "main": (None, 98)}
# Trevor 2026-11-20 "set a hard stop to scrum for if we hit 98%": no scrum session runs on an account whose 7d window is
# at this used %, his clicks included (spawn's HardStop), and serve.py hard_stop_tick stops the running ones.
HARD_STOP_PCT = 98
# Trevor 2026-11-21: in the last hour before the seven_day window resets its unused quota is lost, so neither
# HARD_STOP_PCT nor a 7d reserve holds the account then; only a used-up window (100 %) does.
FINAL_HOUR_SECS = 3600
Account = namedtuple("Account", "name dir reserve")
ACCOUNT_RE = re.compile(r"[a-z0-9-]{1,20}")


def accounts():
    """ACCOUNTS (or SCRUM_ACCOUNTS) as Account tuples with dir expanded, in order. SCRUM_USAGE set without
    SCRUM_ACCOUNTS means the first account only (tests stay hermetic); an account after the first whose dir is
    missing is left out."""
    raw = os.environ.get("SCRUM_ACCOUNTS")
    try:
        rows = json.loads(raw) if raw else ACCOUNTS[:1] if os.environ.get("SCRUM_USAGE") else ACCOUNTS
        out = [Account(str(n), Path(os.path.expanduser(d)), tuple(r) if r else None) for n, d, r in rows]
    except (ValueError, TypeError):
        raise SystemExit(f"bad SCRUM_ACCOUNTS {raw!r}; must be a JSON list of [name, dir, reserve]")
    if not out or not all(ACCOUNT_RE.fullmatch(a.name) for a in out):
        raise SystemExit(f"bad accounts {[a.name for a in out]}; names must match {ACCOUNT_RE.pattern}")
    return out[:1] + [a for a in out[1:] if a.dir.is_dir()]


def usage_path(account=None):
    """The usage.json the status line writes. No account: SCRUM_USAGE, else <CLAUDE_CONFIG_DIR or the first
    account's dir>/usage.json (this session's own account). A named account: SCRUM_USAGE for the first one when
    set, else <its dir>/usage.json. An unknown name raises SystemExit."""
    env, accs = os.environ.get("SCRUM_USAGE"), accounts()
    if account is None:
        return Path(env or Path(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or accs[0].dir)) / "usage.json")
    if env and account == accs[0].name:
        return Path(env)
    acc = next((a for a in accs if a.name == account), None)
    if acc is None:
        raise SystemExit(f"unknown account {account!r}")
    return acc.dir / "usage.json"


def read_usage(account=None):
    try:
        u = json.loads(usage_path(account).read_text())
    except (OSError, ValueError):
        return None
    return u if isinstance(u, dict) else None


WINDOWS = (("five_hour", "5h"), ("seven_day", "7d"))  # usage.json's rate-limit windows and their short labels
TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


# API-equivalent list prices, USD per million tokens, in TOKEN_KEYS order (input, output, cache read, cache creation; cache
# read is 0.1x input, cache creation 1.25x). Keyed by a family substring of the transcript's model string; edit here.
PRICES_USD_PER_MTOK = {"opus": (5, 25, 0.5, 6.25), "sonnet": (3, 15, 0.3, 3.75), "haiku": (1, 5, 0.1, 1.25)}


def row_cost(row):
    """USD for one transcript_tokens row: each TOKEN_KEYS count x its PRICES_USD_PER_MTOK price / 1e6, summed. 0 when the
    model is missing or names no listed family."""
    model = row.get("model")
    price = next((p for fam, p in PRICES_USD_PER_MTOK.items() if fam in model), None) \
        if isinstance(model, str) else None
    return sum(token_count(row.get(k)) * p for k, p in zip(TOKEN_KEYS, price)) / 1e6 if price else 0


JOB_COST_DAYS = 7  # how far back job costs (serve.py job_costs, write_tokens) read transcripts; an older job shows no cost


def cost_by_job(rows):
    """{project: {job: (tokens, usd)}} over the transcript_tokens rows whose project and job are both set: tokens the
    TOKEN_KEYS sum, usd the row_cost sum. serve.py job_costs and write_tokens share it."""
    costs = {}
    for r in rows:
        if r["project"] and r["job"]:
            tok, usd = costs.setdefault(r["project"], {}).get(r["job"], (0, 0))
            costs[r["project"]][r["job"]] = (tok + sum(r[k] for k in TOKEN_KEYS), usd + row_cost(r))
    return costs


def token_count(v):
    """A usage count as an int; anything else (a string, None, a bool, NaN, Infinity) is 0."""
    try:
        return int(v) if is_num(v) else 0
    except (OverflowError, ValueError):
        return 0


def transcripts_dir():
    return Path(os.environ.get("SCRUM_TRANSCRIPTS") or Path.home() / ".claude" / "projects")


def first_prompt_tags(text):
    """(job, skill) from a transcript's first prompt: JOB_DIR=<path>/jobs/<id>, else a <command-args> whose second
    word starts with a digit; skill is the /trevskills-… in <command-name>, without the slash."""
    m = re.search(r"JOB_DIR=\S*/jobs/([^/\s]+)", text)
    job = m and m.group(1)
    if not job and (m := re.search(r"<command-args>(.*?)</command-args>", text, re.S)):
        words = m.group(1).split()
        job = words[1] if len(words) > 1 and words[1][0].isdigit() else None
    m = re.search(r"<command-name>/?(trevskills-[\w-]*)</command-name>", text)
    return job or None, m and m.group(1)


def prompt_round(text):
    """The int of the first ROUND=<digits> in a transcript's first prompt (the round a scrum agent was spawned for),
    else None; a bad value such as ROUND=x is None."""
    m = re.search(r"(?<![\w])ROUND=([0-9]+)(?![\w])", text)
    return int(m.group(1)) if m else None


def read_transcript(path):
    """({message.id: row} for the file's assistant messages, last line per id winning, first prompt text). Bad
    lines are skipped; an unreadable file gives ({}, "")."""
    rows, first = {}, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if first is not None and '"usage"' not in line:
                    continue  # most lines are tool output; skip parsing what cannot hold a usage dict
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(d, dict) or not isinstance(msg := d.get("message"), dict):
                    continue
                if d.get("type") == "user" and first is None and not d.get("isMeta"):
                    c = msg.get("content")
                    first = c if isinstance(c, str) else "\n".join(
                        b["text"] for b in c if isinstance(b, dict) and isinstance(b.get("text"), str)
                    ) if isinstance(c, list) else ""
                if d.get("type") != "assistant" or not isinstance(u := msg.get("usage"), dict):
                    continue
                try:
                    ts = datetime.fromisoformat(d["timestamp"]).timestamp()
                except (KeyError, TypeError, ValueError):
                    continue
                row = {"ts": ts, **{k: token_count(u.get(k)) for k in TOKEN_KEYS},
                       "model": msg.get("model"),
                       "cwd": d.get("cwd") if isinstance(d.get("cwd"), str) else None}
                mid = msg.get("id")
                rows[mid if isinstance(mid, str) and mid else object()] = row  # no id: a key of its own
    except OSError:
        return {}, ""
    return rows, first or ""


def transcript_tokens(start, end, projects_dir=None):
    """One row per Claude Code assistant message stamped in [start, end) (epoch seconds), sorted by ts: token counts,
    model, the project, job, agent and skill it is attributed to, its `round` (prompt_round of that file's own first
    prompt; a subagent never inherits its parent's), `prompt_job` (the job that file's own first prompt names, else None,
    before a subagent falls back to its parent's job) and its `transcript` path as a str. Reads <dir>/*/*.jsonl (main sessions) and
    <dir>/*/<session>/subagents/agent-*.jsonl; files last written before start are never opened. Read-only."""
    root = Path(projects_dir) if projects_dir else transcripts_dir()
    repos = sorted(((n, p.resolve()) for n, p in projects().items()), key=lambda r: -len(r[1].parts))
    tags, out, where = {}, [], {}

    def place(cwd):  # (project, worktree job) for a cwd; the longest (deepest) repo path wins
        if cwd not in where:
            where[cwd] = None, None
            try:
                c = Path(cwd).resolve() if isinstance(cwd, str) and cwd else None
            except (OSError, ValueError):  # a NUL byte, a symlink loop
                c = None
            if c:
                for name, repo in repos:
                    if c.is_relative_to(repo):
                        rel = c.relative_to(repo).parts
                        wt = rel[2].removeprefix("scrum-") if len(rel) > 2 and rel[:2] == (".claude", "worktrees") \
                            else None
                        where[cwd] = name, wt or None
                        break
        return where[cwd]

    files = sorted(root.glob("*/*.jsonl")) + sorted(root.glob("*/*/subagents/agent-*.jsonl"))
    seen = set()
    for path in files:  # main sessions first, so a subagent finds its parent's tags
        try:
            if path.stat().st_mtime < start:
                continue
            real = path.resolve()
        except OSError:
            continue
        if real in seen:  # a symlinked project dir lists the same transcript again
            continue
        seen.add(real)
        rows, first = read_transcript(path)
        job, skill = first_prompt_tags(first)
        prompt_job = job or None
        rnd = prompt_round(first)
        if path.parent.name == "subagents":
            pjob, skill = tags.get(path.parent.parent.with_suffix(".jsonl"), (None, None))
            job = job or pjob
            try:
                meta = json.loads(path.with_name(path.stem + ".meta.json").read_text())
                agent = meta["agentType"] if isinstance(meta.get("agentType"), str) else "subagent"
            except (OSError, ValueError, AttributeError, KeyError):
                agent = "subagent"
        else:
            tags[path] = job, skill
            agent = "main"
        for row in rows.values():
            if start <= row["ts"] < end:
                project, wt = place(row.pop("cwd"))
                out.append({**row, "project": project, "job": wt or job, "agent": agent, "skill": skill,
                            "round": rnd, "prompt_job": prompt_job, "transcript": str(path)})
    return sorted(out, key=lambda r: r["ts"])


AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"  # this repo's agents/, the folder beside skills/


def agent_pin(agent):
    """The frontmatter `model:` of AGENTS_DIR/<agent>.md, or None when the name is not a plain agent name, the file is
    missing or it has no frontmatter or no model line."""
    if not isinstance(agent, str) or not re.fullmatch(r"[\w-]+", agent):
        return None
    try:
        text = (AGENTS_DIR / f"{agent}.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    parts = text.split("---", 2)
    m = re.search(r"^model:\s*(\S+)\s*$", parts[1], re.M) if text.startswith("---") and len(parts) == 3 else None
    return m and m.group(1)


IMAGE_EXTS = (".png", ".jpg", ".jpeg")


def transcript_tools(path):
    """({tool name: tool_use calls}, image Reads) for one transcript, read line by line: each tool_use block counts once
    by its id (a message written again repeats its blocks), an image Read is a Read whose file_path ends in IMAGE_EXTS
    (any case). Bad lines are skipped; an unreadable file gives ({}, 0)."""
    names, images, seen = {}, 0, set()
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"tool_use"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                msg = d.get("message") if isinstance(d, dict) else None
                content = msg.get("content") if isinstance(msg, dict) else None
                for b in content if isinstance(content, list) else []:
                    if not isinstance(b, dict) or b.get("type") != "tool_use" or not isinstance(b.get("name"), str):
                        continue
                    bid = b.get("id")
                    if isinstance(bid, str) and bid:
                        if bid in seen:
                            continue
                        seen.add(bid)
                    names[b["name"]] = names.get(b["name"], 0) + 1
                    fp = b.get("input").get("file_path") if isinstance(b.get("input"), dict) else None
                    if b["name"] == "Read" and isinstance(fp, str) and fp.lower().endswith(IMAGE_EXTS):
                        images += 1
    except OSError:
        return {}, 0
    return names, images


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


USAGE_LOW_PCT = 10  # remaining % below which automated claims taper (USAGE_STEPS[0])
USAGE_LOWER_PCT = 5  # remaining % below which the taper drops to USAGE_STEPS[1]
USAGE_STOP_PCT = 2  # remaining % below which automated claims stop (USAGE_STEPS[2])
USAGE_STEPS = (3, 1, 0)  # live-session allowance at each rung; None (above the ladder) means unlimited
USAGE_RELAX_SECS = 1200  # a window resetting within this many seconds relaxes one rung
USAGE_TIGHTEN_SECS = 10800  # a low window resetting further away than this tightens one rung
USAGE_HOLD_PCT = 90  # a window at or past this used % holds every automated claim until it resets
USAGE_STALE_SECS = 300  # usage.json older than this is unknown, and unknown never tapers
PACE_LEAD_PCT = 15  # a 5h or 7d window's used % this many points ahead of its elapsed % holds automated claims (allowance 0)


class Allowance(int):
    """usage_allowance's number of live sessions; .reason says which window bound it and why."""
    def __new__(cls, n, reason):
        self = super().__new__(cls, n)
        self.reason = reason
        return self


def held_windows(usage, now):
    """[(key, label, window)] in WINDOWS order for each window of usage.json at USAGE_HOLD_PCT used or more with a numeric
    used_percentage and a resets_at after `now`: the windows that hold every automated claim. [] for malformed data."""
    limits = usage.get("rate_limits") if isinstance(usage, dict) else None
    if not isinstance(limits, dict):
        return []
    return [(key, label, w) for key, label in WINDOWS if isinstance(w := limits.get(key), dict)
            and is_num(w.get("used_percentage")) and is_num(w.get("resets_at")) and w["resets_at"] > now
            and w["used_percentage"] >= USAGE_HOLD_PCT]


def usage_allowance(usage, now, live, windows=WINDOWS):
    """How many live headless sessions automated claims may run under the 5h and 7d budgets (an Allowance), or None
    for no taper. Each window's remaining % picks a rung of USAGE_STEPS; a reset within USAGE_RELAX_SECS relaxes
    one rung, a reset beyond USAGE_TIGHTEN_SECS tightens one. The stricter window wins (five_hour on a tie). Stale,
    missing or malformed data, or a window whose reset already passed, limits nothing. `live` (an int or a list)
    only feeds the reason text. Trevor's own Play/Resume never call this, nor pick_account for a primary with a backup. Pace: a five_hour or seven_day window whose used % runs
    PACE_LEAD_PCT or more points ahead of its elapsed % (0..100) gives Allowance(0, "pace 5h ..." or "pace 7d ...", five_hour first) before the ladder.
    Hold: a window at USAGE_HOLD_PCT used or more gives Allowance(0, "hold 5h ..." or "hold 7d ...") after pace, before the ladder, with no relax near its reset.
    `windows` (a slice of WINDOWS) limits pace, hold and ladder to those windows: pick_account passes five_hour only for a backup."""
    if not isinstance(usage, dict) or not isinstance(usage.get("rate_limits"), dict):
        return None
    at = usage.get("written_at")
    if not is_num(at) or now - at > USAGE_STALE_SECS:
        return None
    for key, label in windows:  # five_hour first, so its reason wins when both are over the lead
        w = usage["rate_limits"].get(key)
        if isinstance(w, dict) and is_num(w.get("used_percentage")) and is_num(w.get("resets_at")) and w["resets_at"] > now:
            span = WINDOW_SECS[key]
            elapsed = min(100, max(0, (span - (w["resets_at"] - now)) / span * 100))
            if w["used_percentage"] - elapsed >= PACE_LEAD_PCT:
                return Allowance(0, f"pace {label} {round(w['used_percentage'])}% used at {round(elapsed)}% elapsed, "
                                    f"resets {datetime.fromtimestamp(w['resets_at']):%H:%M} (lead {PACE_LEAD_PCT}+ points)")
    for key, label, w in held_windows(usage, now):
        if (key, label) not in windows:
            continue
        return Allowance(0, f"hold {label} {round(w['used_percentage'])}% used ({USAGE_HOLD_PCT}% cap), "
                            f"resets {datetime.fromtimestamp(w['resets_at']):%H:%M}")
    rungs = (None,) + USAGE_STEPS
    best = None
    for key, label in windows:
        w = usage["rate_limits"].get(key)
        if not isinstance(w, dict) or not is_num(w.get("used_percentage")) or not is_num(w.get("resets_at")):
            continue
        used, resets = w["used_percentage"], w["resets_at"]
        left = 100 - used
        if left >= USAGE_LOW_PCT or resets <= now:
            continue
        i = 3 if left < USAGE_STOP_PCT else 2 if left < USAGE_LOWER_PCT else 1
        if resets - now <= USAGE_RELAX_SECS:
            i -= 1
        elif resets - now > USAGE_TIGHTEN_SECS:
            i = min(i + 1, len(USAGE_STEPS))
        n = rungs[i]
        if n is not None and (best is None or n < best[0]):
            best = n, label, used, resets
    if best is None:
        return None
    n, label, used, resets = best
    count = live if isinstance(live, int) else len(live)
    return Allowance(n, f"usage {label} {round(used)}% used, resets {datetime.fromtimestamp(resets):%H:%M} "
                        f"(allowance {n}, {count} live)")


def limit_path(account):
    """The account's usage-limit marker: an epoch beside its usage.json."""
    if "unittest" in sys.modules and not (os.environ.get("SCRUM_ACCOUNTS") or os.environ.get("SCRUM_USAGE")):
        raise SystemExit("limit markers refused under unittest without SCRUM_ACCOUNTS or SCRUM_USAGE")
    return usage_path(account).with_name("limit_until")


def note_limit(account, reset):
    """Mark the account limited until `reset` (epoch seconds), tmp file + os.replace. No folder to write in (tests'
    SCRUM_USAGE=/dev/null/...) skips it; a failed write is logged to stderr and skipped: the marker only saves retries."""
    if reset > time.time() + 8 * 86400:  # a reset that far out is a misread, not a limit
        return
    try:
        path = limit_path(account)
        if not path.parent.is_dir():
            return
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(f"{int(reset)}\n")
        os.replace(tmp, path)
    except (OSError, SystemExit) as e:
        print(f"note_limit {account}: {e}", file=sys.stderr)


def limited_until(account, now):
    """The account's limit_until epoch while it is after `now`, else None (missing, malformed or past)."""
    try:
        at = int(limit_path(account).read_text().strip())
    except (OSError, ValueError, SystemExit):
        return None
    return at if at > now else None


def primary_account(now):
    """Name of the account whose seven_day resets_at is the soonest one after `now` (ACCOUNTS order within ties and
    when none has one): its unused quota is lost at reset, so only its PRIMARY_RESERVE holds it (account_reserve)."""
    def at(acc):
        v = (seven_day_window(acc.name) or {}).get("resets_at")
        return v if is_num(v) and v > now else float("inf")
    return min(accounts(), key=at).name  # min keeps the first of equal keys


def account_reserve(acc, now):
    """The (5h, 7d) reserve that holds the account now: PRIMARY_RESERVE's (None when unlisted) for primary_account,
    else acc.reserve."""
    return PRIMARY_RESERVE.get(acc.name) if primary_account(now) == acc.name else acc.reserve


def reserve_hit(acc, usage, now):
    """Why the account's reserve (account_reserve) keeps it for Trevor, or None: a window with resets_at > now whose
    used % is at or above its reserve value. A None value, or no reserve at all (the primary), holds only a used-up
    window (100 %, job 1216: Claude refuses it, so no account is ever picked full). None when usage.json's written_at
    is missing or older than USAGE_STALE_SECS (unknown holds nothing)."""
    limits = usage.get("rate_limits") if isinstance(usage, dict) else None
    at = usage.get("written_at") if isinstance(usage, dict) else None
    if not isinstance(limits, dict) or not is_num(at) or now - at > USAGE_STALE_SECS:
        return None
    for (key, label), cap in zip(WINDOWS, account_reserve(acc, now) or (None, None)):
        w = limits.get(key)
        if not (isinstance(w, dict) and is_num(w.get("used_percentage")) and is_num(w.get("resets_at")) and w["resets_at"] > now):
            continue
        cap = 100 if cap is None or key == "seven_day" and w["resets_at"] - now <= FINAL_HOUR_SECS else cap
        if w["used_percentage"] >= cap:
            return f"reserve {label} {round(w['used_percentage'])}% used (keeps {cap}%)" if cap < 100 else f"{label} used up"
    return None


def hard_stop(account, now):
    """Why HARD_STOP_PCT stops every scrum session on the account now (its seven_day window at or above it, more than
    FINAL_HOUR_SECS before resets_at), else None. Only as fresh as usage.json: the statusline of an interactive chat on
    that account writes it, or refresh_usage; None when written_at is missing or older than USAGE_STALE_SECS."""
    at = (read_usage(account) or {}).get("written_at")
    if not is_num(at) or now - at > USAGE_STALE_SECS:
        return None
    w = seven_day_window(account) or {}
    pct, at = w.get("used_percentage"), w.get("resets_at")
    if is_num(pct) and is_num(at) and at - FINAL_HOUR_SECS > now and pct >= HARD_STOP_PCT:
        return f"hard stop: {account} {round(pct)}% weekly, back {datetime.fromtimestamp(at - FINAL_HOUR_SECS):%a %-I:%M %p}"
    return None


def pick_account(now, live=0, prefer=None):
    """(name, allowance): name is the first account with room, `prefer` first when listed, then the soonest seven_day reset
    first (no future 7d window last, ACCOUNTS order within ties), else (None, Allowance(0, reason)) naming every account and why. Room: no limit_until marker ahead, usage_allowance None or above the live
    count (`live` an int or a list), and no
    reserve window reached (reserve_hit). With a backup listed, the primary (primary_account) skips usage_allowance
    (job 1182: no pace, hold or taper), so it stops only on its limit marker, PRIMARY_RESERVE (job 1208) or a used-up window (job 1216); a lone account keeps them.
    A backup gets five_hour pace, hold and taper only (job 1242): the primary's fresh week arrives before the backup's reset, so its 7d budget needs no pacing; its reserve still holds it. allowance is the claims cap across every account with room (job 1130):
    None when any of them has no taper, else the largest of their allowances."""
    accs = accounts()
    why, room = [], []
    usages = {a.name: read_usage(a.name) for a in accs}

    def order(acc):
        limits = (usages[acc.name] or {}).get("rate_limits")
        w = limits.get("seven_day") if isinstance(limits, dict) else None
        at = w.get("resets_at") if isinstance(w, dict) else None
        return acc.name != prefer, not (is_num(at) and at > now), at if is_num(at) and at > now else 0

    primary = min(accs, key=lambda a: order(a)[1:]).name if len(accs) > 1 else None  # primary_account, no re-read

    for acc in sorted(accs, key=order):
        if until := limited_until(acc.name, now):
            why.append(f"{acc.name} limited until {datetime.fromtimestamp(until):%H:%M}")
            continue
        usage = usages[acc.name]
        allow = None if acc.name == primary else usage_allowance(usage, now, live, WINDOWS[:1] if primary else WINDOWS)
        if allow is not None and allow <= (live if isinstance(live, int) else len(live)):  # no slot left
            why.append(f"{acc.name} {allow.reason}")
            continue
        if held := reserve_hit(acc, usage, now):
            why.append(f"{acc.name} {held}")
            continue
        room.append((acc.name, allow))
    if not room:
        return None, Allowance(0, "no account has room: " + "; ".join(why))
    caps = [a for _, a in room]
    return room[0][0], None if any(a is None for a in caps) else max(caps)


def seven_day_window(account):
    """The account's usage.json seven_day window dict, None when the file, rate_limits or window is not a dict."""
    limits = (read_usage(account) or {}).get("rate_limits")
    w = limits.get("seven_day") if isinstance(limits, dict) else None
    return w if isinstance(w, dict) else None


def seven_day_reset(account):
    """The account's seven_day resets_at as an int string, "" when usage.json has none."""
    at = (seven_day_window(account) or {}).get("resets_at")
    return str(int(at)) if is_num(at) else ""


def fallback_account(now, recorded):
    """Account for a spawn when none has room: the one whose limit marker ends soonest (no marker counts as now), the
    recorded one winning ties or when it is not limited; the first account when `recorded` is unlisted."""
    accs = accounts()
    names = [a.name for a in accs]
    first = recorded if recorded in names else names[0]
    return min([first] + [n for n in names if n != first],
               key=lambda n: (hard_stop(n, now) is not None, limited_until(n, now) or now))  # a hard-stopped one last


def fable_used(usage, now):
    """{"5h": %, "7d": %} for the Fable guard: a window whose reset is at or before now reads 0, an unreadable one None; an absent five_hour key
    reads 0 (no 5h window is active), an absent seven_day stays None."""
    limits = usage.get("rate_limits") if isinstance(usage, dict) else None
    out = {}
    for key, label in WINDOWS:
        if key == "five_hour" and isinstance(limits, dict) and key not in limits:
            out[label] = 0
            continue
        w = limits.get(key) if isinstance(limits, dict) else None
        ok = isinstance(w, dict) and is_num(w.get("used_percentage")) and is_num(w.get("resets_at"))
        out[label] = None if not ok else 0 if w["resets_at"] <= now else w["used_percentage"]
    return out


def fable_state(usage, now):
    """"paused" at 5h >= FABLE_SWITCH_5H_PCT or 7d >= FABLE_SWITCH_7D_PCT used, else "warn" at the WARN levels, else
    "ok"; "unknown" when usage.json is missing, malformed, missing a window or older than USAGE_STALE_SECS."""
    used = fable_used(usage, now)
    at = usage.get("written_at") if isinstance(usage, dict) else None
    if None in used.values() or not is_num(at) or now - at > USAGE_STALE_SECS:
        return "unknown"
    five, seven = used["5h"], used["7d"]
    if five >= FABLE_SWITCH_5H_PCT or seven >= FABLE_SWITCH_7D_PCT:
        return "paused"
    if five >= FABLE_WARN_5H_PCT or seven >= FABLE_WARN_7D_PCT:
        return "warn"
    return "ok"


def fable_ok(usage, now):
    """True when a new eligible spawn may run on Fable: unknown usage never does."""
    return fable_state(usage, now) in ("ok", "warn")


def pace_cap(usage, now, base):
    """Always None: usage pacing no longer caps sessions (job 282); machine_ok and the overlap rules gate instead.
    Kept for continue.py (outside this repo), which skips its tick when this is not None."""
    return None


def merge_limits(old, new, now):
    """New rate_limits over old: per window the later resets_at wins (tie: higher used_percentage); expired old windows drop."""
    def ok(w):
        return isinstance(w, dict) and is_num(w.get("used_percentage")) and is_num(w.get("resets_at"))
    merged = dict(new)
    for key, _ in WINDOWS:
        o = old.get(key) if isinstance(old, dict) else None
        if not ok(o) or o["resets_at"] <= now:
            continue
        n = new.get(key)
        if not ok(n) or (n["resets_at"], n["used_percentage"]) < (o["resets_at"], o["used_percentage"]):
            merged[key] = o
    return merged


def save_limits(path, limits):
    """Merge limits into the usage.json at path (merge_limits, written_at now) under its lock: temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f"{path.name}.lock")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # pid: several sessions may write at once
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)  # read old, merge, write as one step
        try:
            old = json.loads(path.read_text()).get("rate_limits")
        except (OSError, ValueError, AttributeError):
            old = None
        now = int(time.time())
        tmp.write_text(json.dumps({"rate_limits": merge_limits(old, limits, now), "written_at": now}))
        os.replace(tmp, path)
        # ponytail: unlinking under the lock can let a racing session lock a new inode; the worst case is one lost merge
        lock.unlink(missing_ok=True)


def usage_from_stream(text):
    """rate_limits from `claude -p --output-format stream-json` output: per rate_limit_event, each unifiedWindows
    five_hour/seven_day entry as {used_percentage: utilization*100, resets_at}; later events win; {} when none or malformed."""
    out = {}
    for line in str(text).splitlines():
        try:
            ev = json.loads(line)
            wins = ev["rate_limit_info"]["unifiedWindows"] if ev.get("type") == "rate_limit_event" else None
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        if not isinstance(wins, dict):
            continue
        for key, _ in WINDOWS:
            w = wins.get(key)
            if isinstance(w, dict) and is_num(w.get("utilization")) and is_num(w.get("resetsAt")):
                out[key] = {"used_percentage": w["utilization"] * 100, "resets_at": w["resetsAt"]}
    return out


USAGE_REFRESH_SECS = 180  # a usage.json older than this is due a headless refresh


def usage_refresh_due(acc, now):
    """True when the account's usage.json is missing or its written_at is older than USAGE_REFRESH_SECS."""
    at = (read_usage(acc.name) or {}).get("written_at")
    return not is_num(at) or now - at > USAGE_REFRESH_SECS


def refresh_usage(acc, run=subprocess.run, _real=subprocess.run):
    """Headless usage refresh: one tiny haiku turn under the account's CLAUDE_CONFIG_DIR, its rate_limit_event windows
    saved to the account's usage.json through save_limits. True when it wrote, False on any failure (never raises).
    Under unittest the real subprocess.run is refused (False), so no test ever launches a headless claude."""
    if run is _real and "unittest" in sys.modules:
        return False
    try:
        with tempfile.TemporaryDirectory() as cwd:
            r = run(["claude", "-p", ".", "--output-format", "stream-json", "--verbose", "--max-turns", "1", "--model", "haiku"],
                    cwd=cwd, env={**os.environ, "CLAUDE_CONFIG_DIR": str(acc.dir)}, capture_output=True, text=True, timeout=90)
        if r.returncode != 0:
            return False
        limits = usage_from_stream(r.stdout)
        if not limits:
            return False
        save_limits(usage_path(acc.name), limits)
        return True
    except Exception:
        return False


def cmd_statusline(text):
    """Claude Code's status line: save stdin's rate_limits to usage.json (temp file + os.replace), return the line."""
    try:
        limits = json.loads(text).get("rate_limits")
    except (ValueError, AttributeError):
        return ""
    if not isinstance(limits, dict):
        return ""  # no rate_limits (yet): leave the old file alone
    save_limits(usage_path(), limits)
    return " · ".join(f"{label} {round(w['used_percentage'])}%" for key, label in WINDOWS
                      if isinstance(w := limits.get(key), dict) and is_num(w.get("used_percentage")))


KNOWN_EXTS = {"py", "md", "json", "js", "jsx", "ts", "tsx", "html", "css", "sh", "yml", "yaml", "toml", "txt", "sql", "prisma", "mjs", "cjs"}


def repo_path(p):
    """True when a PATH_RE token can be a repo file: not a version number, a bracket-led token, a dotted code name (`board.spawn`),
    or a home/URL path without a known extension (`~/.local`, `/login`; `/other/repo/x.py` stays so outside_repo_files can see it)."""
    ext = p.rsplit(".", 1)[-1] in KNOWN_EXTS and "." in p
    if p[:1] in "([" or re.match(r"\d+(\.\d+)+$", p):
        return False
    return ext if p[:1] in "~/" else "/" in p or ext


def child_files(jobs_dir, job_id):
    """A child's Likely files: from spec.md, or from feature.md (plan-apply's Parallel: paths) while it has no spec."""
    for name in ("spec.md", "feature.md"):
        if (f := Path(jobs_dir) / job_id / name).is_file():
            return text_files(Path(jobs_dir).parent.parent, f.read_text(encoding="utf-8", errors="replace"),
                              spec=name == "spec.md")
    return set()


def text_files(root, text, spec=False):
    """child_files for one text in repo `root`: a spec.md's when `spec`, else a feature.md's (serve.py's shop_tick also
    reads a backlog item not claimed yet this way)."""
    if not spec and TERMINAL_BATCH_TITLE in text:
        # the Terminal batch has no spec: its files are the .claude/ paths its bullets name (not the bare `.claude/` folder)
        return {p for p in re.findall(r"`([^`\s]+)`", text)
                if p.startswith(".claude/") and len(p) > 8 and PATH_RE.match(p)}
    found = likely_files(text)
    if found or spec and re.search(r"^#+\s*Likely files", text, re.M | re.I):
        return found  # a Likely files heading that names no path still means "files unknown"
    # no spec, or a spec with no Likely files section: the paths the text names; slash-less names must resolve in git
    root = Path(root)
    tracked = git_tracked(root)
    # a path that exists on disk as written (even git-ignored, like scrum/backlog.md) is never remapped
    return {p if p in tracked or (root / p).exists() or len(m := [t for t in tracked if t.endswith("/" + p)]) != 1 else m[0]
            for p in prose_paths(text) if "/" in p} | bare_name_paths(text, tracked)


def holder_files(jobs_dir, job):
    """An outside holder's files while it has no spec.md: the backticked PATH_RE paths in its feature.md, plus the
    paths its worktree diff touches (_route_diff). Prose words are never read, so an unwritten spec holds nothing."""
    try:
        text = (Path(jobs_dir) / job["id"] / "feature.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    diff = _route_diff(job) if job.get("worktree") else None
    return {p for p in re.findall(r"`([^`\s]+)`", text) if PATH_RE.match(p) and repo_path(p)} | set(diff[1] if diff else ())


def strip_line_ref(token):
    """token without one trailing `:<line>`, `:<line>-<line>` or `:<line>:<col>` (`a.py:12-40` -> `a.py`)."""
    return re.sub(r":\d+(?:-\d+|:\d+)?$", "", token)


def prose_paths(text):
    """Every backticked token, and every bare token with a /, in text that matches PATH_RE."""
    def wraps(t):  # True when the first ( closes at the last char: `(a/b.ts)` wraps, `(shop)/page.tsx` does not
        depth = 0
        for i, c in enumerate(t):
            depth += (c == "(") - (c == ")")
            if depth == 0:
                return i == len(t) - 1
        return False

    def unparen(t):  # an unmatched leading ( or trailing ) is prose punctuation; a balanced pair is a Next.js route folder
        if t.count("(") != t.count(")"):
            t = t[1:] if t.startswith("(") else t[:-1] if t.endswith(")") else t
        elif t.startswith("(") and wraps(t):
            t = t[1:-1]  # a pair wrapping the whole token is prose: `(e2e/x.spec.ts).`
        return t
    bare = (unparen(strip_line_ref(t.rstrip(".,;:"))) for t in re.sub(r"`[^`]*`", " ", text).split())
    ticked = (strip_line_ref(p) for p in re.findall(r"`([^`\s]+)`", text))
    return {p for p in ticked if PATH_RE.match(p) and repo_path(p)} | \
           {t for t in bare if PATH_RE.match(t) and repo_path(t) and "/" in t}


def git_tracked(repo):
    """`git ls-files` of repo as a list, or [] with no repo or when git fails."""
    try:
        return subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, timeout=20, check=True).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []


def bare_name_paths(text, tracked):
    """Tracked full paths for the slash-less file names in text (`useX.ts`) that exactly one tracked entry (git_tracked) carries by base name."""
    names = {strip_line_ref(t.lstrip("`(").rstrip(".,;:`)")) for t in text.split()}
    names = {n for n in names if "/" not in n and PATH_RE.match(n) and repo_path(n)}
    return {m[0] for n in names if len(m := [t for t in tracked if t.rsplit("/", 1)[-1] == n]) == 1}


def shared_files(a, b):
    """The paths of a that clash with b: equal, or one is a folder holding the other (`src/app/` holds `src/app/x.ts`).
    Of each clashing pair the longer path is kept."""
    under = lambda p, q: q.startswith(p.rstrip("/") + "/")
    return {max(p, q, key=len) for p in a for q in b if p == q or under(p, q) or under(q, p)}


def likely_files(spec_text):
    """The backtick-quoted paths in a spec's `## Likely files` section, plus the first token of each bullet that has no backticks."""
    found = set()
    for line in (md_section(spec_text, "Likely files") or "").splitlines():
        if "`" in line:
            found.update(re.findall(r"`([^`\s]+)`", line))
        elif line.startswith("- ") and line[2:].split():
            found.add(re.sub(r"[:,]$", "", line[2:].split()[0]))
    return {p for p in found if PATH_RE.match(p) and repo_path(p)}


def spec_funcs(jobs_dir, job_id):
    """likely_funcs of a job's spec.md, or {} with no readable spec."""
    try:
        return likely_funcs((Path(jobs_dir) / job_id / "spec.md").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def likely_funcs(spec_text):
    """{path: set of function names} for each `## Likely files` bullet whose backticked path is followed by
    `(functions: a, b)`; slot_conflict uses them so fast jobs may share a BIG_SHARED_FILES path."""
    found = {}
    for line in (md_section(spec_text, "Likely files") or "").splitlines():
        if m := re.match(r"\s*- `([^`\s]+)`.*?\(functions:\s*((?:[^()]|\(\))*)\)", line):
            names = {n.strip(" `").removesuffix("()") for n in m.group(2).split(",")} - {""}
            if names:
                found.setdefault(m.group(1), set()).update(names)
    return found


def parse_plan(text):
    """(goal, tickets) from plan.md, or SystemExit naming the first problem. Each ticket's depends are ticket names."""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if first != "PLAN: READY":
        raise SystemExit(f"plan.md: first line must be PLAN: READY, not {first[:60]!r}")
    tickets, cur = [], None
    for line in (md_section(text, "Tickets") or "").splitlines():
        if m := TICKET_RE.match(line):
            cur = {"ticket": m.group(1), "title": m.group(2), "text": []}
            tickets.append(cur)
        elif cur is not None:
            key, sep, value = line.partition(":")
            if sep and PLAN_FIELDS.get(key.strip()) and PLAN_FIELDS[key.strip()] not in cur:
                cur[PLAN_FIELDS[key.strip()]] = value.strip()
            else:
                cur["text"].append(line)
    if not 2 <= len(tickets) <= 5:
        raise SystemExit(f"plan.md has {len(tickets)} tickets under ## Tickets; 2-5 allowed")
    names = [t["ticket"] for t in tickets]
    if len(set(names)) != len(names):
        raise SystemExit("plan.md: two tickets share a name")
    for t in tickets:
        name = t["ticket"]
        missing = next((k for k, v in PLAN_FIELDS.items() if v not in t), None)
        if missing or not t["title"]:
            raise SystemExit(f"plan.md {name}: missing {missing + ': line' if missing else 'title'}")
        deps = [] if t["depends"].lower() == "none" else [d.strip() for d in t["depends"].split(",") if d.strip()]
        if name in deps:
            raise SystemExit(f"plan.md {name}: depends on itself")
        if bad := [d for d in deps if d not in names]:
            raise SystemExit(f"plan.md {name}: depends on unknown ticket {bad[0]}")
        t["depends"] = deps
        # the backticked paths on a Parallel: yes line become the child's Likely files until its spec has some
        t["paths"] = [p for p in dict.fromkeys(re.findall(r"`([^`\s]+)`", t["parallel"])) if PATH_RE.match(p)]
        for key in ("parallel", "exposure"):
            if not (m := re.match(r"(yes|no)\b", t[key], re.I)):
                raise SystemExit(f"plan.md {name}: {key.capitalize()}: must start with yes or no")
            t[key] = m.group(1).lower() == "yes"
        t["text"] = "\n".join(t["text"]).strip()
    merged, todo = set(), {t["ticket"]: set(t["depends"]) for t in tickets}
    while todo:
        free = [k for k, deps in todo.items() if deps <= merged]
        if not free:
            raise SystemExit(f"plan.md: dependency cycle among {', '.join(sorted(todo))}")
        merged.update(free)
        for k in free:
            del todo[k]
    exposure = [t for t in tickets if t["exposure"]]
    if len(exposure) != 1:
        raise SystemExit(f"plan.md has {len(exposure)} Exposure: yes tickets; exactly 1 allowed")
    if tickets[-1] is not exposure[0]:
        raise SystemExit(f"plan.md: the Exposure: yes ticket {exposure[0]['ticket']} must be the last ticket")
    return (md_section(text, "Goal") or "").strip(), tickets


def add_child(root, board, parent, t, depends_on, goal, plain=False):
    """Create one waiting child job for ticket t and write its feature.md (just t's text when plain).
    Caller holds the board lock. It copies the parent's started_by (runall when the parent has none)."""
    job_id = add_job(root, board, short_title(t["title"]), started_by=parent.get("started_by") or "runall")
    setup = t.get("setup", "none")
    setup = None if setup.lower() == "none" else setup
    feature = feature_text(t["text"], t.get("points")) if plain else \
        f"{t['title']}\n\n{t['text']}\n\nTicket {t['ticket']} of BigBoy {parent['id']}: {parent['title']}.\n" \
        + (f"Goal: {goal}\n" if goal else "") + f"Hard stops: {t.get('hard', 'none')}\n" \
        + (f"Human setup: {setup}\n" if setup else "") \
        + ("\n## Likely files\n" + "".join(f"- `{p}`\n" for p in t["paths"]) if t["parallel"] and t.get("paths") else "")
    (Path(root) / "jobs" / job_id / "feature.md").write_text(feature)
    board["jobs"][-1].update(stage="waiting", files=["feature.md"], parent=parent["id"], ticket=t["ticket"],
                             depends_on=depends_on, parallel=t["parallel"], setup=setup and "pending", setup_text=setup)
    return job_id


def cmd_plan_apply(root, parent_id, fix=False):
    """Create the children from plan.md (or, with fix, the one FIX child from bigboy-review.md) under the lock.
    Every check runs before the first job is created, so a refused plan creates nothing. The parent gets a childSpecs
    mark (child_specs_pending) until BigBoy step 3's `ready --specs-done`."""
    d = Path(root) / "jobs" / check_id(parent_id)
    read = lambda name: (d / name).read_text(encoding="utf-8", errors="replace") if (d / name).is_file() else ""
    with locked_board(root) as board:
        parent = live(board, parent_id)
        kids = parent.get("children") or []
        if fix:
            if not kids:
                raise SystemExit(f"job {parent_id} has no children yet; run plan-apply without --fix first")
            if any(find(board, k).get("ticket") == "FIX" for k in kids):
                raise SystemExit(f"job {parent_id} already has its one FIX child")
            text = (md_section(read("bigboy-review.md"), "Fix ticket") or "").strip()
            if not text:
                raise SystemExit(f"job {parent_id}: bigboy-review.md has no ## Fix ticket text")
            ticket = {"ticket": "FIX", "title": f"Fix {parent['title']}", "text": text, "parallel": False}
            new = [add_child(root, board, parent, ticket, [], "")]
        else:
            if kids:
                raise SystemExit(f"job {parent_id} already has children: {', '.join(kids)}")
            goal, tickets = parse_plan(read("plan.md"))
            ids = {}
            for t in tickets:  # create all first: a ticket may depend on one listed after it
                ids[t["ticket"]] = add_child(root, board, parent, t, [], goal)
            for t in tickets:
                find(board, ids[t["ticket"]])["depends_on"] = [ids[x] for x in t["depends"]]
            new = list(ids.values())
        # childSpecs: no claim until BigBoy step 3's `ready --specs-done` (child_specs_pending)
        parent.update(children=kids + new, stage="running", reason=None, updatedAt=now(), childSpecs=now())
        parent["files"], parent["diverged"] = job_files(d), diverged(d)
        return {"children": new}


def match_words(text, match):
    """True when text holds every whitespace-separated word of match, case-insensitive; a blank match matches nothing."""
    words = match.lower().split()
    return bool(words) and all(w in text.lower() for w in words)


def cmd_runall_start(root, match=None):
    """One Run-all parent whose waiting children are every open backlog item, claimed in priority order (priority_key) under the lock.
    An item that waits, directly or through its prerequisites, on a job claimed outside this run stays open, and so does
    one held by an {after repo:job} marker or the requeue loop guard (waiting_on), with every item that needs it. A child
    whose item needs another item claimed here depends_on that sibling's child. An item waiting on Human setup stays
    open, and so does every item that needs it. With match only items match_words accepts are claimed: the rest are held,
    so a matching item that needs one stays open too. Cool-down refuses it (COOLING_CLAIM). The parent gets a
    childSpecs mark, as in cmd_plan_apply."""
    if cooling_down():
        raise SystemExit(COOLING_CLAIM)
    if soft := soft_cap_reason():
        raise SystemExit(f"{soft}: no new backlog claim.")
    with locked_board(root) as board:
        lines, items = read_backlog(root)
        waits = {i["index"]: waiting_on(i, items, board) for i in items if not i["done"]}  # once: after refs read other boards
        held = {i["index"] for i in items if not i["done"]  # indexes of open items left open
                and (i["setup"] or origin_open(i, board) or any(w not in i["needs"] for w in waits[i["index"]])
                     or match is not None and not match_words(i["text"], match))}
        while True:
            more = {i["index"] for i in items if not i["done"] and i["index"] not in held
                    and any(o["id"] == n and (o["done"] or o["index"] in held)
                            for n in waits[i["index"]] for o in items)}
            if not more:
                break
            held |= more
        todo = sorted((i for i in items if not i["done"] and i["index"] not in held), key=priority_key)
        if not todo:
            return {"id": None, "children": []}
        parent_id = add_job(root, board, "Run all", started_by="runall")
        parent = board["jobs"][-1]
        kids, by_id = [], {}
        for item in todo:
            t = {"ticket": None, "title": short_title(item["text"]), "text": item["text"], "parallel": True,
                 "points": item["points"]}
            kids.append(add_child(root, board, parent, t, [], "", plain=True))
            take_spec(root, item["text"], kids[-1])
            claim_item(lines, item, kids[-1])
            if item["id"]:
                by_id.setdefault(item["id"], []).append(kids[-1])
        for item, kid in zip(todo, kids):  # after all are created: an item may need one listed after it
            find(board, kid)["depends_on"] = list(dict.fromkeys(k for n in item["needs"] for k in by_id.get(n, [])
                                                                if k != kid))
        write_backlog(root, lines)
        parent.update(lane="runall", stage="running", children=kids, updatedAt=now(), childSpecs=now())  # as plan-apply
        return {"id": parent_id, "children": kids}


MIN_FREE_RAM_PCT = 20  # machine_ok: no new claim or resume below this much free RAM
MIN_FREE_DISK_GB = 10  # ... or below this much free disk on the repo volume
MAX_SWAP_PCT = 25  # ... or with more swap in use than this much of physical RAM (4 GB on 16 GB): memory_pressure's
#                    free % counts inactive pages as free, so 19 sessions ran at "32% free" with 9 GB swapped (2026-10-24).
#                    A share of RAM, not of the swap file: macOS resizes the swap file as it frees, so used/total lies too
MAX_CPU_BUSY_PCT = 90  # ... or with the CPU busier than this (cpu_busy_pct, 0-100 over all cores): under about 10% idle an
#                       8-core Mac has less than one core free, where E2E runs and next dev start time out; below it more
#                       sessions still add throughput. The load is gated too (MAX_CPU_LOAD_PCT): busy % misses threads
#                       queued behind the cores, and the 1-minute average lets a post-reboot spike (681%) clear in minutes
MAX_CPU_LOAD_PCT = 300  # ... or with the 1-minute load average above this share of the cores (cpu_load_pct): load 13.4 on 8
#                        cores (168%) timed out next dev, jest and Playwright while busy read 51% (2026-10-26, job 459);
#                        150 -> 300 by job 958: load counts disk/swap waits; 150 held claims ~16 h in 3 days at 30% idle
# Jobs 1373, 1403, 1420, 1386: cache-tax drops a cold session's wake prompt, so the -p session exits mid-job.
# Job 1240: agent-model-clamp.py keeps a sonnet/haiku-pinned scrum agent off an Opus `model` override; --settings
# hooks merge with settings.json's (code.claude.com/docs/en/hooks: "Hook entries merge across settings levels")
NO_CACHE_TAX = json.dumps({"enabledPlugins": {"cache-tax@claude-code-mods": False}, "hooks": {"PreToolUse": [
    {"matcher": "Agent|Task", "hooks": [{"type": "command", "command": "python3 " + shlex.quote(
        str(Path(__file__).resolve().parent / "agent-model-clamp.py"))}]}]}})
SESSION_NICE = 10  # spawn: every headless claude -p session runs at this nice level, below Trevor's own apps
MAX_LAUNCH_CPU_LOAD_PCT = 500  # serve.spawn queues every non-manual job launch (resume, approve, rework, start) above this load
CPU_SAMPLES = 3  # cpu_busy_pct: the mean of at most this many watchdog samples (record_cpu_sample) ...
CPU_SAMPLE_SECS = 300  # ... from the last this many seconds (about 3 watchdog ticks), so one spike never flips the gate
SWAP_FREE_RAM_PCT = 35  # ... but swap alone is stale (macOS keeps it until pressure returns): it blocks only below this free RAM
SWAP_GROWTH_SECS = 600  # ... or when swap grew within this window (2026-10-25: idle machine, 71% free, blocked for an hour)
IDLE_HOLD_SECS = 1800  # machine_ok: a memory warn or swap hold with no live session releases one claim after this long
#                        (2026-11-24: warn with no job running and the biggest process 0.3 GB held the queue about 14 h)
WARN_SESSIONS = 3  # vm_pressure_reason: up to this many live sessions, kernel level 2 with free RAM at SWAP_FREE_RAM_PCT or
#                    more and swap flat is no reason (Trevor 2026-11-23: held 81% of a day at 36-43% free, 1 session live).
#                    pulse.log 11-10 to 11-23, 15 min after a warn: critical 0 of 749 readings at 0-4 sessions, 5.4% of 445 at 5+
SESSION_RAM_PCT = 5  # ram_room: share of RAM one new headless session takes when session_rss_pct is unknown; tune here
LIGHT_SESSION_RAM_PCT = 3  # ram_room(light=True): a fast or lilguy job's share (no E2E, related tests only), never above
#                           the standard share; a guess, tune here
MIN_SESSION_RAM_PCT = 2  # ram_room: the measured share (session_rss_pct) never counts below this (claude only, not its children)
MAX_SESSIONS = 14  # machine_ok: headless sessions may hold 70% of RAM in all (SESSION_RAM_PCT each); the rest is macOS and
#                   apps. Derived from the RAM share, not the fixed 8 job 279 removed; 19 sessions crashed the Mac (2026-10-24).
#                   14, not 12: Trevor keeps it as a backstop until further notice in case the RAM reading misleads (job 284)
SESSION_RAMP_SECS = 120  # ram_room: a session younger than this has not grown into its RAM yet, so free RAM % overstates
#                          the room; two projects claiming within that minute both burst (the 2026-10-24 pile-up)
MAX_YOUNG_SESSIONS = 2  # ram_room: at most this many sessions younger than SESSION_RAMP_SECS at once, so starts ramp 2 per
#                         2 min and the CPU gates see each pair's load first (2026-11-04: 10 started on wake, load 70 on 8 cores)
FREE_RAM_RE = re.compile(r"System-wide memory free percentage: (\d+(?:\.\d+)?)%")  # memory_pressure; serve.py: the shop Mac


def free_ram_pct():
    """System-wide free memory in percent, or None when unknown (no memory_pressure, as on Linux). SCRUM_FREE_RAM
    stands in for the reading."""
    fake = os.environ.get("SCRUM_FREE_RAM")
    if fake:
        return float(fake)
    try:
        out = subprocess.run(["/usr/bin/memory_pressure"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = FREE_RAM_RE.search(out)
    return float(m.group(1)) if m else None


def swap_used_pct():
    """Swap in use as a percent of physical RAM, or None when unknown (no sysctl, as on Linux, or unreadable output).
    SCRUM_SWAP_PCT stands in for the reading."""
    fake = os.environ.get("SCRUM_SWAP_PCT")
    if fake:
        return float(fake)
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "vm.swapusage", "hw.memsize"], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"used = ([\d.]+)M.*\n(\d+)\s*$", out)
    return float(m.group(1)) * 1048576 / int(m.group(2)) * 100 if m and int(m.group(2)) else None


def vm_pressure_level() -> int | None:
    """The kernel's memory pressure level (1 normal, 2 warn, 4 critical), or None when unknown (no sysctl, as on Linux,
    or a non-integer reading). Unlike free_ram_pct it does not count inactive pages as free: on 2026-11-17 it read 2
    while free RAM flickered between 32% and 61% (job 966). SCRUM_VM_PRESSURE stands in for the reading."""
    fake = os.environ.get("SCRUM_VM_PRESSURE")
    if fake:
        return int(fake)
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True,
                             text=True, timeout=10).stdout
        return int(out.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def cpu_busy_sample():
    """How busy the CPU is right now, 0-100 over all cores: 100 - idle from top's second sample (the first covers no
    interval). Takes 1-2 s, so only the serve.py watchdog calls it (record_cpu_sample). None when unknown (no top -l, as
    on Linux, a timeout or no CPU usage line)."""
    try:
        out = subprocess.run(["top", "-l", "2", "-n", "0", "-s", "1"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    idle = re.findall(r"CPU usage: .*?(\d+(?:\.\d+)?)% idle", out or "")
    return 100 - float(idle[-1]) if idle else None


def cpu_log_path():
    return os.environ.get("SCRUM_CPU_LOG") or os.path.join(tempfile.gettempdir(), "scrum-cpu-log.json")


def cpu_samples(now):
    """The [time, busy] samples in the CPU log from the last CPU_SAMPLE_SECS; a missing or corrupt log has none."""
    try:
        return [[t, float(v)] for t, v in json.loads(Path(cpu_log_path()).read_text()) if now - t < CPU_SAMPLE_SECS]
    except (OSError, ValueError, TypeError):
        return []


def record_cpu_sample():
    """Append one cpu_busy_sample to SCRUM_CPU_LOG (default: system temp dir), keeping the last CPU_SAMPLES from the
    last CPU_SAMPLE_SECS. The serve.py watchdog is its one writer, so no lock. A None sample is not recorded; with
    SCRUM_CPU_BUSY_PCT set it does nothing."""
    if os.environ.get("SCRUM_CPU_BUSY_PCT"):
        return
    busy = cpu_busy_sample()
    if busy is None:
        return
    now = time.time()
    keep = (cpu_samples(now) + [[now, busy]])[-CPU_SAMPLES:]  # read before open(..., "w") truncates the log
    try:
        with open(cpu_log_path(), "w") as fh:
            json.dump(keep, fh)
    except OSError:
        pass


def cpu_busy_pct():
    """The mean of the CPU log's recent samples (cpu_samples), or None when there are none. Never runs top: the
    dashboard reads it every 2 s. SCRUM_CPU_BUSY_PCT stands in for the reading."""
    fake = os.environ.get("SCRUM_CPU_BUSY_PCT")
    if fake:
        return float(fake)
    samples = cpu_samples(time.time())
    return sum(v for _, v in samples) / len(samples) if samples else None


def cpu_load_pct():
    """The 1-minute load average as a percent of all cores (100 = one runnable thread per core), or None when unknown
    (no getloadavg, or no core count). The kernel already smooths it, so no sample log; the 5-minute one read near 0
    right after sleep, so a wake burst passed it. SCRUM_CPU_LOAD_PCT stands in
    for the reading."""
    fake = os.environ.get("SCRUM_CPU_LOAD_PCT")
    if fake:
        return float(fake)
    try:
        load = os.getloadavg()[0]
    except (OSError, AttributeError):
        return None
    cores = os.cpu_count()
    return load / cores * 100 if cores else None


def free_disk_gb(path):
    """Free disk in GB on path's volume, or None when unknown. SCRUM_FREE_DISK_GB stands in for the reading."""
    fake = os.environ.get("SCRUM_FREE_DISK_GB")
    if fake:
        return float(fake)
    try:
        return shutil.disk_usage(path).free / 1e9
    except OSError:
        return None


COOLING = "cooling down"  # machine_ok's reason (claim=True) while Trevor's cool-down flag is on
COOLING_CLAIM = f"{COOLING}: no new backlog claim. Fix: click Resume work in the header."


def cooldown_path(worker=None):
    """Trevor's cool-down flag (the dashboard's Cool down button): while it exists no new work starts on its own (backlog
    claims, Run-all and BigBoy child claims, wake-waiting, auto-continue, cloud-claim, the next roadmap step, the
    bad-window digest); work already started finishes, and Trevor's own clicks still start work. The shop Mac (serve.shop_tick) is not held: it still claims and
    launches work while cool-down is on. worker= (a shop.workers() alias) names that worker's own flag beside it,
    cooldown-<alias> (its Cool down button in the meter): while it exists serve.shop_worker sends that worker no new work."""
    path = Path(os.environ.get("SCRUM_COOLDOWN") or Path.home() / ".claude" / "trevskills-scrum" / "cooldown")
    return path.with_name(f"cooldown-{worker}") if worker else path


def cooling_down(worker=None):
    return cooldown_path(worker).exists()


SOFT_COOLING = "soft cool down"  # prefix of machine_ok's reason (claim=True) while soft cool down holds new work at its cap
SOFT_COOLDOWN_SESSIONS = 4  # soft cool down (job 1308): while it is on, new work waits at this many sessions, this Mac plus the shop Macs; tune here


def soft_cooldown_path():
    """The soft cool-down flag (the dashboard's Soft cool down button), beside the cool-down flag so SCRUM_COOLDOWN moves it."""
    return cooldown_path().with_name("soft-cooldown")


def soft_cooling_down():
    return soft_cooldown_path().exists()


def shop_jobs_by_worker():
    """Counter of the jobs in flight on the shop Macs per worker alias: every registered board's jobs in stage cloud
    with a `shop` field (no `worker` field: shopmac, the alias jobs ran under before workers.txt)."""
    return Counter(j.get("worker") or "shopmac" for r in projects().values()
                               for j in read_board(r / "scrum")["jobs"] if j.get("stage") == "cloud" and j.get("shop"))


def shop_jobs_running():
    """How many jobs run on the shop Macs, all workers together."""
    return sum(shop_jobs_by_worker().values())


def soft_sessions():
    """The count soft cool down compares with SOFT_COOLDOWN_SESSIONS: this Mac's live sessions plus the shop Macs' jobs."""
    return live_sessions() + shop_jobs_running()


def soft_cap_reason():
    """None, or why soft cool down holds new work: it is on and soft_sessions() has reached SOFT_COOLDOWN_SESSIONS.
    Started work is never held by it; manual clicks skip it."""
    if not soft_cooling_down():
        return None
    n = soft_sessions()
    if n < SOFT_COOLDOWN_SESSIONS:
        return None
    return f"{SOFT_COOLING}: {n} of {SOFT_COOLDOWN_SESSIONS} sessions running (this Mac + shop)"


def swap_grew(swap):
    """True when swap is more than 1 point of RAM above the oldest reading of the last SWAP_GROWTH_SECS, or more than
    5 points above the lowest reading in that window (a large rebound after a fall). Records swap
    in SCRUM_SWAP_LOG (default: system temp dir), pruned to that window; a missing or corrupt file means no growth."""
    log = os.environ.get("SCRUM_SWAP_LOG") or os.path.join(tempfile.gettempdir(), "scrum-swap-log.json")
    now = time.time()
    try:
        keep = [[t, v] for t, v in json.loads(Path(log).read_text()) if now - t < SWAP_GROWTH_SECS]
    except (OSError, ValueError, TypeError):
        keep = []
    grew = bool(keep) and (swap - keep[0][1] > 1 or swap - min(v for _, v in keep) > 5)
    try:
        with open(log, "w") as fh:
            json.dump(keep + [[now, swap]], fh)
    except OSError:
        pass
    return grew


def vm_pressure_reason(new=None) -> str | None:
    """Why the kernel memory pressure level (vm_pressure_level) refuses new work: level 2 or more, else None (level 1 or
    an unknown reading). With `new` (the sessions about to start: machine_ok 1, heavy_hold 0; job 1312) level 2 is also
    no reason while the live sessions plus `new` are at most WARN_SESSIONS, free RAM is at least SWAP_FREE_RAM_PCT and
    swap is not growing (swap_grew); an unknown RAM or swap reading keeps the hold. Without `new` level 2 always refuses:
    the UI sweep and the full E2E on main (serve.py), which are no job's work."""
    level = vm_pressure_level()
    if level == 2 and new is not None:
        ram, swap = free_ram_pct(), swap_used_pct()
        if ram is not None and ram >= SWAP_FREE_RAM_PCT and swap is not None and not swap_grew(swap) \
                and live_sessions() + new <= WARN_SESSIONS:
            return None
    if level is not None and level >= 2:
        return f"memory pressure {'critical' if level >= 4 else 'warn'} (kernel level {level})"
    return None


def swap_pressing(ram, swap, limit):
    """True when swap is past `limit` and either free RAM is under SWAP_FREE_RAM_PCT or swap grew over the window."""
    return swap is not None and swap > limit and ((ram is not None and ram < SWAP_FREE_RAM_PCT) or swap_grew(swap))


def idle_hold_release(held) -> bool:
    """True when `held` (a memory warn or swap reason from machine_ok) has refused work for IDLE_HOLD_SECS with no live
    session, so one claim may start (job 1460). The first refusal time is kept in SCRUM_IDLE_HOLD (default: system temp
    dir, like swap_grew's log) and dropped when nothing is held or a session is live, so the next release waits another
    IDLE_HOLD_SECS. Critical memory pressure (kernel level 4+) never releases. The release is one line in pulse.log:
    {"t", "idle_release": reason}. An unreadable or unwritable file never releases."""
    log = Path(os.environ.get("SCRUM_IDLE_HOLD") or os.path.join(tempfile.gettempdir(), "scrum-idle-hold.json"))
    level = vm_pressure_level()
    if not held or (level is not None and level >= 4) or live_sessions() > 0:
        log.unlink(missing_ok=True)
        return False
    now = time.time()
    try:
        state = json.loads(log.read_text())
        since = float(state["since"])
    except (OSError, ValueError, TypeError, KeyError):
        state, since = {}, None
    if since is None or since > now:
        try:
            log.write_text(json.dumps({"since": now}))
        except OSError:
            pass
        return False
    if now - since < IDLE_HOLD_SECS:
        return False
    if not state.get("released"):  # one pulse line a release, not one a caller
        try:
            with open(pulse_path(), "a") as fh:
                fh.write(json.dumps({"t": int(now), "idle_release": held}) + "\n")
            log.write_text(json.dumps({"since": since, "released": now}))
        except OSError:
            pass
    return True


def machine_ok(path, manual=False, claim=False, own_load=False):
    """None when the machine has room for new work, else why not: cool-down (only for an automatic start of new or
    not-yet-started work, claim=True, and skipped for Trevor's manual clicks), then free RAM, then the kernel memory
    pressure level (vm_pressure_reason: 4 and 3 refuse, 2 past its limits), then swap, then free
    disk, then CPU busy, then CPU load (the 5-minute load average over the cores; both CPU checks also skipped for
    manual clicks; CPU load also skipped with own_load, a resume whose own idle session is already in it: resume_gate),
    then the session ceiling.
    Gates new claims, resumes and auto-continue starts only; a running job's heavy steps wait on heavy_hold instead.
    An unknown reading passes."""
    if claim and not manual and cooling_down():
        return COOLING
    if claim and not manual and (soft := soft_cap_reason()):
        return soft
    ram = free_ram_pct()
    if ram is not None and ram < MIN_FREE_RAM_PCT:
        return f"free RAM {ram:g}% (< {MIN_FREE_RAM_PCT}%)"
    swap = swap_used_pct()
    held = vm_pressure_reason(new=1)
    if not held and swap_pressing(ram, swap, MAX_SWAP_PCT):
        held = f"swap used {swap:.1f}% of RAM (> {MAX_SWAP_PCT}%)"
    if not idle_hold_release(held):
        if held:
            return held
    disk = free_disk_gb(path)
    if disk is not None and disk < MIN_FREE_DISK_GB:
        return f"free disk {disk:.1f} GB (< {MIN_FREE_DISK_GB} GB)"
    cpu = None if manual else cpu_busy_pct()
    if cpu is not None and cpu > MAX_CPU_BUSY_PCT:
        return f"CPU busy {cpu:.0f}% (> {MAX_CPU_BUSY_PCT}%)"
    load = None if manual or own_load else cpu_load_pct()
    if load is not None and load > MAX_CPU_LOAD_PCT:
        return f"CPU load {load:.0f}% of {os.cpu_count()} cores (> {MAX_CPU_LOAD_PCT}%)"
    live = live_sessions()
    if live >= MAX_SESSIONS:
        return f"{live} sessions running (ceiling {MAX_SESSIONS})"
    return None


def heavy_hold(warn_ok=False) -> str | None:
    """machine_ok's CPU load reason, else its memory pressure reason (vm_pressure_reason, kernel level 2+), else its swap
    reason, else None: gates running jobs' Build, Test/Typecheck/Lint, E2E and render.py starts (buildlock.py on
    build.lock, check.lock and e2e.lock, render.py; jobs 1227, 1312) and the hot stop of a UI sweep or full E2E on main
    (serve.py hot_stop_tick). No cool-down, disk, busy or session check; free RAM is read only when swap is over
    MAX_SWAP_PCT. An unknown reading passes. warn_ok=True lets kernel level 2 (warn) pass, so the swap check still
    runs; critical, CPU load and swap still hold (serve.py hot_stop_tick keeps a full E2E that caused the warn)."""
    load = cpu_load_pct()
    if load is not None and load > MAX_CPU_LOAD_PCT:
        return f"CPU load {load:.0f}% of {os.cpu_count()} cores (> {MAX_CPU_LOAD_PCT}%)"
    if (mem := vm_pressure_reason(new=0)) and not (warn_ok and vm_pressure_level() == 2):
        return mem
    swap = swap_used_pct()
    if swap is not None and swap > MAX_SWAP_PCT and swap_pressing(free_ram_pct(), swap, MAX_SWAP_PCT):
        return f"swap used {swap:.1f}% of RAM (> {MAX_SWAP_PCT}%)"
    return None


def hand_hold(root) -> str | None:
    """Why Trevor's hand start (Run now, Start now, a chat hand-off) of a not-yet-started job waits: heavy_hold, else
    machine_ok(root, manual=True) (memory, swap, disk; no CPU checks), else None (job 1312)."""
    return heavy_hold() or machine_ok(root, manual=True)


LIGHT_LANES = ("fast", "lilguy")  # light_job: lanes that run no E2E, so ram_room sizes them at LIGHT_SESSION_RAM_PCT


def job_lane(root, job: dict):
    """The job's board `lane`; with none, feature.md's header `Lane:`, or, with no such line there, spec.md's. None when
    the job has no id, no folder or no lane."""
    lane = job.get("lane")
    if not lane and job.get("id"):
        d = Path(root) / "jobs" / str(job["id"])
        lane = header_value(d / "feature.md", "Lane", LANES) or header_value(d / "spec.md", "Lane", LANES)
    return lane


def _has_ui_no(text) -> bool:
    """True when project.md text has a `- Has UI:` line whose first word is `no`; a missing line is False."""
    ui = _project_list(text, "Has UI")
    return bool(ui) and ui[0].lower().rstrip(".,;:") == "no"


def _project_light(root) -> bool:
    """True when root/project.md has a `- Build:` line of `none` and a `- Has UI:` line whose first word is `no`;
    a missing file or line is False."""
    try:
        text = (Path(root) / "project.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _project_list(text, "Build") == [] and _has_ui_no(text)


def project_has_no_ui(root) -> bool:
    """True when root/project.md says `- Has UI: no` (_has_ui_no); a missing file or line is False."""
    try:
        return _has_ui_no((Path(root) / "project.md").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def light_job(root, job: dict) -> bool:
    """True when the job's lane (job_lane) is in LIGHT_LANES, or project.md says no Build and no UI (_project_light).
    A job with no id or no folder is not light by lane."""
    return job_lane(root, job) in LIGHT_LANES or _project_light(root)


HEAVY_PER_MAC = 2  # job 1314: heavy jobs (heavy_job) this Mac runs at once; further heavy work waits for the shop Mac
SHOP_HEAVY_PER_WORKER = 1  # heavy jobs one shop worker runs at once (serve.py shop_tick)


def heavy_job(root, job: dict, parent_lane=None) -> bool:
    """True when `job` is heavy (job 1314: it runs jest, tsc and lint). A board job (it has a `stage`): job_lane
    standard or debug, no readable lane (crash prevention), or a child of a BigBoy parent (`parent_lane` bigboy, else
    the parent's lane on root's board). A backlog item (no `stage`): points of BIG_POINTS or more; with no points, a
    `Lane:` of its pre-written spec or its text that is not fast or lilguy, and no `Lane:` at all; any other points
    are light. Never in a no-git project (no_git): an edit job runs none of them, and has no lane until its Route."""
    if no_git(root):
        return False
    if "stage" in job:
        if parent_lane is None and job.get("parent"):
            try:
                parent_lane = job_lane(root, find(read_board(root), job["parent"]))
            except (SystemExit, OSError):
                parent_lane = None
        lane = job_lane(root, job)
        return parent_lane == "bigboy" or lane in ("standard", "debug", None)
    points = job.get("points")
    if points is not None:
        return points >= BIG_POINTS
    text = str(job.get("text") or "")
    lane = header_value(spec_path(root, text), "Lane", LANES) if text else None
    if not lane and (m := re.search(r"\bLane:\s*(" + "|".join(LANES) + r")\b", text, re.I)):
        lane = m[1].lower()
    return lane not in LIGHT_LANES


def heavy_ids(root, skip=None) -> list[str]:
    """The ids of the heavy_job jobs on this Mac's boards (job 1314): jobs on any registered board (and root's, first)
    in a WATCHED stage with no `shop` field, no queued launch and not paused by Trevor (a paused job runs no session),
    except the job id `skip` on root's board."""
    here = Path(root).resolve()
    roots = {here: Path(root)}
    for repo in projects().values():
        roots.setdefault((repo / "scrum").resolve(), repo / "scrum")
    ids = []
    for key, r in roots.items():
        try:
            jobs = read_board(r)["jobs"]
        except (SystemExit, OSError):
            continue
        by_id = {j["id"]: j for j in jobs}
        for j in jobs:
            if j.get("stage") not in WATCHED or j.get("shop") or j.get("queued_launch") or j.get("paused") \
                    or (skip == j["id"] and key == here):
                continue
            pl = job_lane(r, by_id[j["parent"]]) if j.get("parent") in by_id else None
            if heavy_job(r, j, parent_lane=pl):
                ids.append(j["id"])
    return ids


def heavy_interactive(root, ids) -> int:
    """How many of the heavy job `ids` run in an interactive session (job 1392): the job has a non-empty `tty` (a
    headless spawn clears it) and session_alive_fn() says its session is alive. live_sessions() counts headless only."""
    want = set(ids)
    if not want:
        return 0
    roots = {Path(root).resolve(): Path(root)}
    for repo in projects().values():
        roots.setdefault((repo / "scrum").resolve(), repo / "scrum")
    cands = {}
    for r in roots.values():
        try:
            jobs = read_board(r)["jobs"]
        except (SystemExit, OSError):
            continue
        cands.update({j["id"]: j for j in jobs if j["id"] in want and j.get("tty")})
    if not cands:  # no interactive job: no ps scan (the watchdog tests count scans)
        return 0
    alive = session_alive_fn()
    return sum(1 for j in cands.values() if alive(j))


def heavy_counted(root, skip=None) -> tuple[list[str], int]:
    """(heavy_ids(root, skip), how many of them count): at most live_sessions() headless sessions plus the alive
    interactive ones, never more than the ids (jobs 1381, 1392: a WATCHED job with no running session fills no slot)."""
    ids = heavy_ids(root, skip)
    if not ids:
        return ids, 0
    return ids, min(len(ids), live_sessions() + heavy_interactive(root, ids))


def heavy_count(root, skip=None) -> int:
    """How many heavy jobs run on this Mac: heavy_counted(root, skip)'s count."""
    return heavy_counted(root, skip)[1]


def heavy_cap_reason(root, job=None) -> str | None:
    """None, or why this Mac takes no more heavy work (job 1314): heavy_count(root), leaving out `job` itself, is
    HEAVY_PER_MAC or more; the text names the first N counted job ids (job 1381). With `job` (a board job or a backlog
    item) that is not heavy, None. Soft cool down counts both Macs together; this only places work."""
    if job is not None and not heavy_job(root, job):
        return None
    ids, n = heavy_counted(root, skip=(job or {}).get("id") if job is not None and "stage" in job else None)
    return f"heavy_cap({n}/{HEAVY_PER_MAC}): {n} heavy jobs on this Mac ({', '.join(ids[:n])})" if n >= HEAVY_PER_MAC else None


def shop_heavy_by_worker():
    """Counter of the heavy (heavy_job) stage-cloud `shop` jobs per worker alias, every registered board (shop_jobs_by_worker's
    alias rule); serve.py shop_tick keeps a worker at SHOP_HEAVY_PER_WORKER."""
    return Counter(j.get("worker") or "shopmac" for r in projects().values()
                   for j in read_board(r / "scrum")["jobs"]
                   if j.get("stage") == "cloud" and j.get("shop") and heavy_job(r / "scrum", j))


def ram_share(light=False):
    """The RAM % ram_room counts per new session: the measured session_rss_pct (SESSION_RAM_PCT when unknown, never
    below MIN_SESSION_RAM_PCT), or for a light job that capped at LIGHT_SESSION_RAM_PCT."""
    share = max(session_rss_pct() or SESSION_RAM_PCT, MIN_SESSION_RAM_PCT)
    return min(share, LIGHT_SESSION_RAM_PCT) if light else share


def outside_repo_files(files, repo):
    """True when `files` is non-empty and every path is absolute outside `repo`, `~`-prefixed, or a relative path whose
    first folder is not in `repo`. An empty set is False: unknown files may touch anything."""
    repo = Path(repo)
    def foreign(f):
        if f.startswith("~"):
            return True
        if f.startswith("/"):
            return not Path(f).is_relative_to(repo)
        return not (repo / Path(f).parts[0]).exists() if Path(f).parts else False
    return bool(files) and all(foreign(f) for f in files)


def ram_room_reason(light=False):
    """The queue-gates.txt token for a RAM hold, no whitespace: ram_room(free=<x>%,est=<share>%,min=<MIN_FREE_RAM_PCT>%,
    young=<n>/<MAX_YOUNG_SESSIONS>,sessions=<n>/<MAX_SESSIONS>); free=unknown when free_ram_pct is None."""
    free, ages = free_ram_pct(), session_ages()
    young = sum(a < SESSION_RAMP_SECS for a in ages)
    return (f"ram_room(free={'unknown' if free is None else f'{free:.0f}%'},est={round(ram_share(light), 1):g}%,"
            f"min={MIN_FREE_RAM_PCT}%,young={young}/{MAX_YOUNG_SESSIONS},sessions={len(ages)}/{MAX_SESSIONS})")


def ram_room(floor=1, light=False):
    """How many new sessions one claim batch may start once machine_ok passed: the free RAM above MIN_FREE_RAM_PCT
    split into shares of the measured session_rss_pct (SESSION_RAM_PCT when unknown, never below MIN_SESSION_RAM_PCT),
    minus one share per session younger than SESSION_RAMP_SECS (its RAM is spoken
    for but not used yet), never past MAX_SESSIONS in all nor MAX_YOUNG_SESSIONS young ones, at least `floor`. An unknown reading allows 1, so a batch never
    bursts blind, and so does swap past MAX_SWAP_PCT / 2 while free RAM is low or swap is growing (swap_pressing); stale swap at healthy free RAM uses the RAM math.
    A kernel memory pressure level (vm_pressure_level) of 2 or more also allows 1.
    floor=0 (serve.py's launch gate) returns the raw room, 0 or less when full, and in the swap, pressure or unknown case 1 only
    while no session is younger than SESSION_RAMP_SECS. light (serve.py, light_job): the free RAM left after the young
    sessions' standard shares, split into ram_share(light=True) shares; the swap, unknown and ceiling cases are the same."""
    ram = free_ram_pct()
    swap = swap_used_pct()
    if ram is None or (vm_pressure_level() or 0) >= 2 or swap_pressing(ram, swap, MAX_SWAP_PCT / 2):
        return 1 if floor or not any(a < SESSION_RAMP_SECS for a in session_ages()) else 0
    ages = session_ages()
    young = sum(a < SESSION_RAMP_SECS for a in ages)
    share = ram_share()
    if light:
        fit = int((ram - MIN_FREE_RAM_PCT - young * share) // ram_share(True))
    else:
        fit = int((ram - MIN_FREE_RAM_PCT) // share) - young
    young_room = MAX_YOUNG_SESSIONS - young if light else (MAX_YOUNG_SESSIONS - young) // 2  # a heavy start counts as 2 young
    room = min(fit, MAX_SESSIONS - len(ages), young_room)
    return max(floor, room) if floor else room


SESSION_RE = re.compile(r"(\S*/)?claude -p /trevskills-scrum [a-z-]+")
ETIME_RE = re.compile(r"\s*(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+) (.*)")  # ps etime: [[dd-]hh:]mm:ss, then the command


def session_ages():
    """Age in seconds of every headless `/trevskills-scrum <action>` session (start, resume, approve, run-all, ...) on
    this machine, any project and any launcher (ps sees them all; serve.py's RUNS only knows its own). SCRUM_PS names
    a file read in place of ps's output; its lines may start with an etime token, and a line without one is old.
    A ps that times out or fails counts as a full machine: MAX_SESSIONS old sessions."""
    fake = os.environ.get("SCRUM_PS")
    if fake:
        out = Path(fake).read_text()
    else:
        try:
            out = subprocess.run(["ps", "-Ao", "etime=,command="], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            # ponytail: unknown counts as full (fails closed, like session_alive_fn); a slow ps is itself heavy load
            return [10 ** 9] * MAX_SESSIONS
    ages = []
    for line in out.splitlines():
        m = ETIME_RE.match(line)
        d, h, mi, sec, cmd = m.groups() if m else (None, None, None, None, line)
        if SESSION_RE.match(cmd):
            ages.append(int(d or 0) * 86400 + int(h or 0) * 3600 + int(mi) * 60 + int(sec) if m else 10 ** 9)
    return ages


def session_rss_pct():
    """The mean RSS of the running sessions SESSION_RE matches, as a percent of physical RAM (ps rss is KB), or None
    when no session runs or ps/sysctl fails. SCRUM_SESSION_RSS_PCT stands in for the reading; with SCRUM_PS set and
    no stand-in it is None, so a test never reads the real ps."""
    fake = os.environ.get("SCRUM_SESSION_RSS_PCT")
    if fake:
        return float(fake)
    if "SCRUM_PS" in os.environ:
        return None
    try:
        out = subprocess.run(["ps", "-Ao", "rss=,command="], capture_output=True, text=True, timeout=10).stdout
        mem = int(subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                 timeout=10).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    rss = [int(m.group(1)) for line in out.splitlines()
           if (m := re.match(r"\s*(\d+) (.*)", line)) and SESSION_RE.match(m.group(2))]
    return sum(rss) / len(rss) * 1024 / mem * 100 if rss and mem > 0 else None


def live_sessions():
    """How many headless scrum sessions run on this machine (see session_ages)."""
    return len(session_ages())


# Files nearly every job names; two jobs may share one, the third waits (git merges edits to different parts).
BIG_SHARED_FILES = {"skills/trevskills-scrum/board.py", "skills/trevskills-scrum/serve.py"}
SHARED_BIG_LIMIT = 2


def big_shared(root):
    """BIG_SHARED_FILES plus the exact paths of project.md's `- Shared files:` line (none, empty or missing adds nothing)."""
    try:
        text = (Path(root) / "project.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set(BIG_SHARED_FILES)
    return BIG_SHARED_FILES | set(_project_list(text, "Shared files") or [])
OVERLAP_HOLD_MAX_S = 2 * 3600  # a waiting child held on an overlap longer than this is claimed anyway
CHILD_SPECS_MAX_S = 3600  # a parent's childSpecs mark older than this holds nothing: it died in BigBoy step 2


def child_specs_pending(parent) -> bool:
    """True while a parent's childSpecs mark (plan-apply, runall-start: BigBoy step 2 is writing the child specs) is
    at most CHILD_SPECS_MAX_S old; cmd_ready claims none of its children then (job 1275). A malformed mark holds nothing."""
    try:
        return time.time() - datetime.fromisoformat(parent["childSpecs"]).timestamp() <= CHILD_SPECS_MAX_S
    except (KeyError, TypeError, ValueError):
        return False


def is_test_path(p):
    """True for a test file: under tests/ or __tests__/, or named test_*.py, *_test.py, *.test.* or *.spec.*."""
    parts = p.split("/")
    return bool({"tests", "__tests__"} & set(parts[:-1] if not p.endswith("/") else parts)) or bool(
        re.fullmatch(r"test_.*\.py|.*_test\.py|.*\.(test|spec)\..*", parts[-1]))


# A holder past review (only approve, merge and deploy remain) no longer holds a slot.
PAST_REVIEW = {"approve", "merging", "deploying"}
# A holder that has finished building holds no overlap slot in cmd_ready or resume_blocker (job 865); back in build it holds again.
POST_BUILD = ("check", "review", "approve", "merging", "deploying")


def slot_conflict(k, busy, files, extra=(), fast=False, funcs=None, big=BIG_SHARED_FILES):
    """(text, sibling ids) when child k may not run beside the in-progress siblings `busy`, else None. files maps a
    child id to its Likely files (child_files). The rules `ready` and `resume_blocker` share: parallel=no, or
    no readable Likely files, runs alone; anything else never beside such a sibling or one sharing a Likely file
    (shared_files: a folder shares every file under it), except `big` (BIG_SHARED_FILES plus the project's big_shared(root)), which clash only once 2 siblings name one.
    Siblings in PAST_REVIEW stages never hold, and shared test files (is_test_path) never clash. `extra` is the
    other pool's holders (cmd_ready's outside jobs or in-tree slots): they count toward the BIG_SHARED_FILES limit only.
    `fast` (a Lane: fast kid) with readable Likely files of its own is held only by a sharing or parallel=no holder:
    one with unreadable Likely files no longer clashes. `funcs` maps an id to its likely_funcs: a fast k does not
    share a BIG_SHARED_FILES path with a holder when both name functions for it and the two sets are disjoint."""
    busy = [o for o in busy if o["id"] != k["id"] and o.get("stage") not in PAST_REVIEW]
    if not busy:
        return None
    extra = [o for o in extra if o["id"] != k["id"] and o.get("stage") not in PAST_REVIEW]
    alone = lambda j: not j.get("parallel") or not files.get(j["id"])  # unknown Likely files = may touch anything
    if alone(k):
        return "this job runs alone", [o["id"] for o in busy]
    lone = (lambda o: not o.get("parallel")) if fast else alone  # k has files here, so a fast k skips unknown-file holders
    fn = funcs or {}
    mine = fn.get(k["id"]) or {}
    apart = lambda o, p: fast and p in BIG_SHARED_FILES and bool(mine.get(p)) \
        and bool((fn.get(o["id"]) or {}).get(p)) and not mine[p] & fn[o["id"]][p]  # named, disjoint functions
    shared = {o["id"]: set() if lone(o) else
              {p for p in shared_files(files[k["id"]], files.get(o["id"], set())) if not is_test_path(p) and not apart(o, p)}
              for o in busy}
    extra_shared = [set() if lone(o) or not files.get(o["id"]) else
                    {p for p in shared_files(files[k["id"]], files[o["id"]]) if not is_test_path(p) and not apart(o, p)}
                    for o in extra]
    held = lambda p: p not in big or sum(p in s for s in [*shared.values(), *extra_shared]) >= SHARED_BIG_LIMIT
    clash = [(o["id"], "runs alone" if lone(o) else f"shares {min(p for p in shared[o['id']] if held(p))}")
             for o in busy if lone(o) or any(held(p) for p in shared[o["id"]])]
    return ("; ".join(f"sibling {i} {why}" for i, why in clash), [i for i, _ in clash]) if clash else None


def unbuilt(root, job) -> bool:
    """True when `job` is in stage spec or stalled and has no commits on its branch (no worktree or base recorded,
    or `<base>..HEAD` is empty). A Critical waiting kid skips such a holder in cmd_ready (job 855). A git failure
    or a base starting with `-` counts as built, so the holder still holds."""
    if job.get("stage") != "spec" and not stalled(job):
        return False
    wt, base = job.get("worktree"), job.get("base")
    if not wt or not base:
        return True
    if str(base).startswith("-"):
        return False
    try:
        return int(_git(wt, "rev-list", "--count", f"{base}..HEAD", "--")) == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


class Blocker(str):
    """resume_blocker's text; .ids names the siblings it waits on."""
    def __new__(cls, text, ids):
        self = super().__new__(cls, text)
        self.ids = ids
        return self


def parked_bigboy(k, by_id, live, root) -> bool:
    """A running, unpaused BigBoy job that runs no session: it has children, all idle and none live, and none waits
    to start (a waiting child with setup not pending and every depends_on job done is about to be claimed), and no
    chain lock is held. Such a job
    holds no Run-all slot, so it never blocks a sibling's overlap check."""
    kids = [by_id[c] for c in k.get("children") or [] if c in by_id]
    # A waiting child behind a not-done sibling (e.g. one with setup pending) can't be claimed, so it isn't starting.
    starts = lambda c: c.get("stage") == "waiting" and c.get("setup") != "pending" \
        and all(by_id.get(d, {}).get("stage") == "done" for d in c.get("depends_on") or [])
    return k.get("lane") == "bigboy" and k.get("stage") == "running" and not k.get("paused") and bool(kids) \
        and all(idle(c) and c["id"] not in live and not starts(c) for c in kids) and not chain_lock_live(root, k["id"])


def resume_blocker(root, job_id, live=()):
    """Why a stalled child may not resume now (a Blocker), or None. Applies `ready`'s overlap rules
    (slot_conflict) against its in-progress siblings: the ids in `live` (serve.py's running sessions, which still
    read needs-human until they write the board) and the non-idle ones with a live session (see below); a sibling in
    POST_BUILD never blocks, live or not. Reads the board without writing anything."""
    jobs_dir = Path(root) / "jobs"
    jobs = {j["id"]: j for j in read_board(root)["jobs"]}
    job = jobs.get(job_id)
    parent = jobs.get(job.get("parent")) if job else None
    if not parent:
        return None
    kids = [jobs[k] for k in parent.get("children") or [] if k in jobs]
    if job not in kids:
        kids.append(job)
    files = {k["id"]: child_files(jobs_dir, k["id"]) for k in kids}
    # A sibling holds a slot only with a live session: `live`, or a WATCHED stage whose claude process is alive.
    # Needs-human, paused and limit-held (limitResetAt) siblings run nothing, so they never block each other.
    maybe = [k for k in kids if k["id"] not in live and k["id"] != job_id and not idle(k) and not k.get("limitResetAt")
             and not parked_bigboy(k, jobs, live, root)]
    alive = session_alive_fn() if any(k.get("stage") in WATCHED for k in maybe) else None  # ps only when needed
    busy = [k for k in kids if k["id"] != job_id and k.get("stage") not in POST_BUILD and (k["id"] in live or (
        k in maybe and (alive(k) if k.get("stage") in WATCHED else True)))]
    if not busy:
        return None
    fast = (header_value(jobs_dir / job_id / "spec.md", "Lane", LANES)
            or header_value(jobs_dir / job_id / "feature.md", "Lane", LANES)) == "fast"  # as cmd_ready
    hit = slot_conflict(job, busy, files, fast=fast, big=big_shared(root), funcs={k["id"]: spec_funcs(jobs_dir, k["id"]) for k in kids})
    return Blocker(*hit) if hit else None


def stuck_on(kids, aborted):
    """True when some waiting child depends on an aborted id, directly or through other waiting children."""
    deps = {k["id"]: k.get("depends_on") or [] for k in kids if k["stage"] == "waiting"}
    stuck, grew = set(), True
    while grew:
        grew = False
        for kid, on in deps.items():
            if kid not in stuck and any(d in aborted or d in stuck for d in on):
                stuck.add(kid)
                grew = True
    return bool(stuck)


def overlap_gate(holder, mine, theirs):
    """queue-gates.txt's `overlap:<holder>:<file>` for the first shared file (a non-test one when any), or a bare
    `overlap:<holder>` when nothing is shared (the holder runs alone)."""
    shared = shared_files(mine, theirs)
    shared = {p for p in shared if not is_test_path(p)} or shared
    return f"overlap:{holder}:{min(shared)}" if shared else f"overlap:{holder}"


CURRENT_GATES = "current-gates.json"  # {gate head: {"at": epoch seconds last hit, "text": why, "held": secs held, "spans": [[start, end], ...]}} (a bare epoch number is the old shape); serve.py gate_heads reads it (job 1408)
GATE_HELD_GAP_SECS = 300  # note_current_gate: a hit this soon after the head's last one adds the gap to its "held" secs (job 1485)


def note_current_gate(root, job_id: str, gate: str, reason: str | None = None) -> None:
    """Stamp `gate`'s head (text before `(`) with {"at": time now, "text": reason, else the full gate string} in
    jobs/<id>/current-gates.json, so serve.py gate_heads and held_by name only gates hit lately while queue-gates.txt
    stays the cumulative log. When the head's last hit was under GATE_HELD_GAP_SECS ago, the gap is added to its
    "held" seconds (kept only once above 0; a malformed one starts over), which _timing_row's Queue gate cell prints
    (job 1485). Read, set and os.replace run under one
    flock on jobs/<id>/.current-gates.lock, so a board.py and a serve.py writer never drop each other's entry. A
    malformed record starts over; a write error never blocks the queue."""
    folder = Path(root) / "jobs" / job_id
    path = folder / CURRENT_GATES
    tmp = folder / f"{CURRENT_GATES}.{os.getpid()}.tmp"
    try:
        with open(folder / ".current-gates.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                seen = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                seen = {}
            if not isinstance(seen, dict):
                seen = {}
            head, now = gate.split("(", 1)[0], time.time()
            prior = seen.get(head)
            last = prior.get("at") if isinstance(prior, dict) else prior
            held = prior.get("held", 0) if isinstance(prior, dict) else 0
            held = held if type(held) in (int, float) and held > 0 else 0
            spans = prior.get("spans") if isinstance(prior, dict) else None  # job 1593: the spans the head was held; malformed starts over
            spans = [[a, b] for sp in spans if isinstance(sp, (list, tuple)) and len(sp) == 2
                     for a, b in [sp] if type(a) in (int, float) and type(b) in (int, float)] if isinstance(spans, list) else []
            near = type(last) in (int, float) and 0 <= now - last < GATE_HELD_GAP_SECS
            if near:
                held += now - last
            if near and spans and spans[-1][1] == last:
                spans[-1][1] = now
            else:
                spans.append([now, now])
            seen[head] = {"at": now, "text": reason or gate, **({"held": held} if held else {}), "spans": spans}
            try:
                tmp.write_text(json.dumps(seen), encoding="utf-8")
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def note_queue_gate(root, job_id, gate, reason=None):
    """Add `gate` to jobs/<id>/queue-gates.txt once, for timing.md's Queue gate column (serve.py's note_queue_gate
    writes ram_room and cpu_load the same way), and stamp it in current-gates.json (note_current_gate, with the optional
    `reason` text, else the gate string). A write error
    never blocks the queue."""
    path = Path(root) / "jobs" / job_id / "queue-gates.txt"
    try:
        if gate not in (path.read_text(encoding="utf-8").split() if path.exists() else []):
            with path.open("a", encoding="utf-8") as f:
                f.write(gate + "\n")
    except OSError:
        pass
    note_current_gate(root, job_id, gate, reason)


def cmd_ready(root, parent_id, live=(), manual=False, only: str | None = None, shop: str | None = None,
              specs_done=False):
    """Claim (stage -> spec) every waiting child that may start now, under the lock, so no child starts twice.
    While child_specs_pending(parent) (BigBoy step 2 writing the child specs, job 1275) it claims nothing and leaves
    the parent, as for a paused one; `specs_done` (step 3's `ready --specs-done`, never serve.py) first drops the mark.
    `live` ids count as in progress whatever their stage (see resume_blocker). A sibling or outside job in POST_BUILD
    holds no slot (it still counts in in_progress), and a `Lane: fast` kid (spec.md header, else feature.md) passes
    slot_conflict's `fast`, with every kid's and holder's spec_funcs as its `funcs`. Paused and stalled siblings with readable Likely files keep their
    overlap slot (one that runs alone holds nothing without a live session, job 951), and every live or in-progress (not paused, stalled or needs-human) leaf job of another tree is an outside holder: a child clashes with
    one only by shared Likely files or unreadable ones (slot_conflict, both sides parallel), never by parallel=no; one
    with no spec.md uses holder_files and holds nothing when that is empty. An overlap gate names the file (overlap_gate).
    Paused or stalled work never holds a claim otherwise (job 751). Cool-down holds every claim (Run-all and
    BigBoy alike) unless `manual` (Trevor's Setup done or Play), and so does finish_first, held like a machine wait; a parent whose children all finished still reports
    all_merged, so its final review runs. A child held on an overlap gets `overlap_hold` {ids, text, since} (the card's
    "Waiting on" line; `since` is set once and a hold past OVERLAP_HOLD_MAX_S is released); a claim or a depends_on wait drops it.
    `only` (serve.py's idle_claim) claims that one waiting child or nothing, as a parallel child checked only against
    siblings and outside jobs with a live session or in stage cloud (parked ones do not count), with room 1 in place of
    ram_room(); machine_ok and a zero usage allowance still hold it, and the parent's stage and reason change only on a claim.
    `shop` (serve.py's shop_tick) claims that one waiting child or nothing, with room 1, for a session on the shop Mac:
    it skips machine_ok and ram_room but keeps the usage cap and every overlap rule of a normal call (a parallel: no
    child still runs alone), and the parent's stage and reason change only on a claim.
    Otherwise room is ram_room(floor=0): with none, nothing is claimed and the parent is left as it was, except that
    one light kid (LIGHT_LANES, its lane read as for the skip below) still claims when ram_room(floor=0, light=True),
    spawn's size for it, is at least 1 and the call has claimed nothing else. `held` in the output: the machine_ok or usage refusal,
    `ram_room` when the standard room is 0, else None (serve.py's start_ready notes it as a queue gate).
    Runs on (job 1155): a call without `shop` never claims a `shop` child (it waits for a worker, the parent keeps
    running) and a `shop` call never claims a `main` one. When shop_room(root) says a worker has room, a call without
    `shop` (only= and manual included) first tags each waiting child that is not shop_excluded with tag_runs_on, before
    the lock (Jev is a network call), then leaves an `any` child (an untagged one counts as any; under the lock only the
    header and stored field are read) in waiting for the shop, setting `shop_first_since` once, until it is older than
    SHOP_FIRST_MAX_S; a claim drops it. Job 1314: a call without `shop` and not `manual`, while heavy_cap_reason(root)
    holds, leaves each heavy_job child waiting for the shop Mac (like a `shop` tag), so only light children claim here."""
    jobs_dir = Path(root) / "jobs"
    shop_first = not shop and shop_room(root)  # a worker has room: an `any` child goes there first
    if shop_first:
        jobs = read_board(root)["jobs"]
        by_id = {j["id"]: j for j in jobs}
        for k in [by_id[i] for i in (by_id.get(parent_id) or {}).get("children") or [] if i in by_id]:
            if k["stage"] == "waiting" and k.get("setup") != "pending" and not k.get("wake") \
                    and only in (None, k["id"]) and not shop_excluded(root, k, jobs):
                try:
                    tag_runs_on(root, k["id"])
                except SystemExit:
                    pass  # gone meanwhile: the lock below reads the live board
    with locked_board(root) as board:
        parent = find(board, check_id(parent_id))
        was = parent["stage"]
        kids = [find(board, k) for k in parent.get("children") or []]
        if not kids:
            raise SystemExit(f"job {parent_id} has no children")
        sibs = {k["id"] for k in kids}
        stage = {j["id"]: j["stage"] for j in board["jobs"]}  # a non-sibling dep (a Terminal batch) counts by its stage
        runall = parent.get("lane") == "runall"  # aborted children count as finished
        reason = parent.get("reason") or ""
        # A legacy needs-human parent (blocked before WAITING_ON existed, or parked on the chain lock) is
        # re-evaluated so existing boards recover.
        legacy = parent["stage"] == "needs-human" and reason.startswith((BLOCKED, RUNALL_BLOCKED, CHAIN_LOCKED))
        if specs_done:
            parent.pop("childSpecs", None)
        # a paused parent, or one still writing its child specs, claims nothing and keeps its stage and reason
        held = bool(parent.get("paused")) or child_specs_pending(parent)
        blocked = not held and (legacy or (parent["stage"] == "running"
                                           and reason.startswith((WAITING_ON, MACHINE_WAIT))))
        go = not held and (parent["stage"] == "running" or legacy)
        # checked once: a machine-wide state, so it gates the whole call
        machine = go and not shop and machine_ok(root, manual=manual, claim=True)  # a shop claim runs off this Mac
        if go and not shop and not manual and not machine:  # job 971: work in flight finishes before new claims
            machine = finish_first(root, board["jobs"]) or False
        cap = None  # the usage ladder's slots left this call; None = no taper
        if go and not machine:
            n_live = live_sessions()
            allow = pick_account(time.time(), n_live)[1]
            if allow is not None:
                cap = max(0, allow - n_live)
                if not cap:  # no slot under the budget: held like a machine wait, never needs-human
                    machine = allow.reason
        files = {k["id"]: child_files(jobs_dir, k["id"]) for k in kids}
        busy = [k for k in kids if not idle(k) or k["id"] in live]
        # held kids run no session: when the taper leaves fewer slots than there are held kids, they yield their
        # overlap slot; busy itself is kept so the parent stays running and in_progress counts them
        limited = [k for k in busy if k.get("limitResetAt") and not idle(k) and k["id"] not in live]
        slots = [k for k in busy if k not in limited] if cap is not None and allow < len(limited) else list(busy)
        by_id = {j["id"]: j for j in board["jobs"]}
        slots = [k for k in slots if not parked_bigboy(k, by_id, live, root)]  # a parked BigBoy child runs no session
        parked = lambda j: (j.get("paused") or stalled(j)) and j["stage"] not in ("done", "aborted")
        # a paused or stalled sibling resumes on its files; one that runs alone and has no live session holds nothing (job 951)
        slots += [k for k in kids if k not in busy and parked(k) and k.get("parallel") and files.get(k["id"])]
        slots = [k for k in slots if k["stage"] not in POST_BUILD]  # built: holds no slot, still counts in busy
        outside = [dict(j, parallel=True) for j in board["jobs"] if go and not machine and j["id"] not in sibs
                   and j["id"] != parent["id"] and not j.get("children") and j["stage"] not in POST_BUILD
                   and j["stage"] not in ("waiting", "done", "aborted") and (not idle(j) or j["id"] in live)]
        if only:  # the idle claim: only jobs with a live session, local or on the shop Mac (stage cloud), hold it
            alive = session_alive_fn() if any(j.get("stage") in WATCHED for j in slots + outside) else None
            has_session = lambda j: j["id"] in live or j.get("stage") == "cloud" \
                or (not idle(j) and j.get("stage") in WATCHED and alive(j))
            slots = [k for k in slots if has_session(k)]
            outside = [j for j in outside if has_session(j)]
        specced = {j["id"] for j in outside if (jobs_dir / j["id"] / "spec.md").is_file()}
        files.update({j["id"]: child_files(jobs_dir, j["id"]) if j["id"] in specced else holder_files(jobs_dir, j)
                      for j in outside})
        outside = [j for j in outside if j["id"] in specced or files[j["id"]]]  # a no-spec holder naming no file holds nothing
        outside = [j for j in outside if not outside_repo_files(files[j["id"]], Path(root).parent)]  # another repo's job cannot clash
        funcs = {j["id"]: spec_funcs(jobs_dir, j["id"]) for j in kids + outside}  # (functions: ...) per Likely file
        big = big_shared(root)
        overlap = []  # outside holder ids that alone hold a waiting child
        room = (1 if only or shop else max(0, ram_room(floor=0))) if go and not machine else 0  # one claim = one new session
        ram_full = not room and go and not machine  # no RAM room: claim nothing, leave the parent; start_ready retries
        if cap is not None:
            room = min(room, cap)
        light_room = None  # read once a light kid meets a spent standard room: spawn's size for it (job 955)
        ready = []
        heavy_n = None  # heavy_count read once the first heavy waiting child is met (job 1314)
        left = []  # children left in waiting for a shop Mac: the parent keeps running
        critical = lambda j: str(j.get("title") or "").startswith("Critical")
        built = {}  # holder id -> not unbuilt(), so each holder's branch is read once per call
        held_by = lambda pool: [o for o in pool  # a Critical kid skips holders that produced nothing (job 855)
                                if built.setdefault(o["id"], not unbuilt(root, o))]
        # Critical kids first, so they take the first ram_room slots; sorted is stable, so the rest keep plan order
        for k in sorted(kids, key=lambda j: not critical(j)) if go and not machine else []:
            if k["stage"] != "waiting" or k.get("setup") == "pending" or k.get("wake") or only and k["id"] != only \
                    or shop and k["id"] != shop:
                continue
            tag = stored_runs_on(root, k) or "any"  # never Jev under the lock: untagged counts as any
            if tag == ("main" if shop else "shop"):
                left.append(k["id"])
                continue
            heavy = not shop and not manual and heavy_job(root, k, parent_lane=parent.get("lane"))
            if heavy:  # job 1314: counted once per call, then each heavy claim adds one
                if heavy_n is None:
                    heavy_n = heavy_count(root)
                if heavy_n >= HEAVY_PER_MAC:
                    left.append(k["id"])  # at this Mac's heavy cap: waits for the shop Mac
                    continue
            light = (k.get("lane") or header_value(jobs_dir / k["id"] / "spec.md", "Lane", LANES)
                     or header_value(jobs_dir / k["id"] / "feature.md", "Lane", LANES)) in LIGHT_LANES
            if len(ready) >= room:  # machine_ok passed for the first claim only: never burst past the free RAM
                # standard room spent; a light kid may still fit the light share, as spawn sizes it, but only as the
                # call's first claim: spawn counts each earlier claim as a young standard session
                if not light or ready:
                    continue
                if light_room is None:
                    light_room = ram_room(floor=0, light=True)
                if light_room < 1:
                    continue
            undone = [dep for dep in k.get("depends_on") or [] if stage.get(dep) != "done"]
            if undone:
                k.pop("overlap_hold", None)
                for dep in undone:
                    note_queue_gate(root, k["id"], f"depends_on:{dep}")
                continue
            try:
                feature = (jobs_dir / k["id"] / "feature.md").read_text(errors="replace")
            except OSError:
                feature = ""
            if twin := e2e_full_duplicate(board, jobs_dir, feature, k["id"]):  # job 1301: never claimed, never ready
                abort_job(root, k, False, f"duplicate of {twin}")
                continue
            k_slots, k_outside = (held_by(slots), held_by(outside)) if critical(k) else (slots, outside)
            skipped = []
            if light:  # skips a holder still in spec (nothing in its tree yet) unless Likely files meet
                skipped = [o["id"] for o in k_slots + k_outside
                           if o.get("stage") == "spec" and not shared_files(files[k["id"]], files[o["id"]])]
                k_slots, k_outside = ([o for o in pool if o["id"] not in skipped] for pool in (k_slots, k_outside))
            fast = (header_value(jobs_dir / k["id"] / "spec.md", "Lane", LANES)
                    or header_value(jobs_dir / k["id"] / "feature.md", "Lane", LANES)) == "fast"
            hit = slot_conflict(dict(k, parallel=True) if only else k, k_slots, files, k_outside, fast, funcs, big=big)  # only: never runs alone
            out_hit = None if hit else slot_conflict(dict(k, parallel=True), k_outside, files, k_slots, fast, funcs, big)
            since = (k.get("overlap_hold") or {}).get("since")
            try:  # a hold older than OVERLAP_HOLD_MAX_S is released: the Merge Conflicts step handles any clash
                expired = bool(since) and time.time() - datetime.fromisoformat(since).timestamp() > OVERLAP_HOLD_MAX_S
            except (TypeError, ValueError):
                expired = False
            if (hit or out_hit) and not expired:
                if out_hit and not hit:
                    overlap += out_hit[1]
                hit = hit or out_hit
                k["overlap_hold"] = {"ids": list(hit[1]), "text": hit[0], "since": since or now()}  # serve.py's waitingOn for the card
                for g in [f"runs_alone:{i}" for i in hit[1]] if hit[0] == "this job runs alone" \
                        else [overlap_gate(i, files[k["id"]], files.get(i, set())) for i in hit[1]]:
                    note_queue_gate(root, k["id"], g)
                continue
            if shop_first and tag == "any" and not shop_excluded(root, k, board["jobs"]):
                try:
                    waited = time.time() - datetime.fromisoformat(k["shop_first_since"]).timestamp()
                except (KeyError, TypeError, ValueError):
                    k["shop_first_since"], waited = now(), 0  # set once; a malformed one starts again
                if waited <= SHOP_FIRST_MAX_S:
                    k.pop("overlap_hold", None)
                    left.append(k["id"])
                    continue
            for i in skipped:
                note_queue_gate(root, k["id"], f"overlap_skipped:{i}")
            k.update(stage="spec", updatedAt=now())
            k.pop("overlap_hold", None)
            k.pop("shop_first_since", None)
            try:  # the claim time, written once, for timing.md's Spec start (see _timing_row)
                with (jobs_dir / k["id"] / "claimed-at.txt").open("x", encoding="utf-8") as f:
                    f.write(f"{int(time.time())}\n")
            except OSError:
                pass
            busy.append(k)
            slots.append(k)
            ready.append(k["id"])
            if heavy:
                heavy_n += 1
        shop_left = list(left)  # the BLOCKED branch below reuses `left` for its own list
        merged = sum(k["stage"] == "done" for k in kids)
        finished = sum(k["stage"] in ("done", "aborted") for k in kids)  # an aborted child never runs again
        new = parent["stage"], parent.get("reason")
        if (only or shop or ram_full) and not ready:  # an idle or shop claim that claimed nothing leaves the parent as it was
            pass
        elif machine:  # wait for RAM, disk or usage; never needs-human, and a legacy parent keeps its reason to re-evaluate
            if parent["stage"] == "running" and finished < len(kids):
                new = "running", MACHINE_WAIT + machine
        elif blocked and (ready or busy or left or finished == len(kids)):
            new = "running", None
        elif not ready and not busy and finished < len(kids) and go:
            human = [k["id"] for k in kids if k["stage"] == "needs-human" or k.get("paused")]
            waits = human or [k["id"] for k in kids
                           if k.get("setup") == "pending" and k["stage"] not in ("done", "aborted")]
            waits = waits or list(dict.fromkeys(  # a live outside job a waiting child depends on; a missing one blocks
                d for k in kids if k["stage"] == "waiting" for d in k.get("depends_on") or []
                if d not in sibs and stage.get(d) not in (None, "done", "aborted")))
            aborted = [k["id"] for k in kids if k["stage"] == "aborted"]
            if waits:  # every action is on a child, so the parent keeps running and names them
                new = "running", WAITING_ON + ", ".join(waits)
            elif overlap:  # another tree's job holds the files; sweep_parents' start_ready retries each tick
                new = "running", OVERLAP_WAIT + ", ".join(dict.fromkeys(overlap))
            elif left:  # a child waits for a shop Mac: shop_tick or a later call here claims it
                new = "running", None
            elif any(stalled(k) for k in kids):  # a child stalled in its own stage is auto-resumed; keep running
                new = "running", None
            elif not runall and aborted and stuck_on(kids, set(aborted)):  # Resume skips the dependents
                new = "needs-human", f"{BLOCKED}: {', '.join(aborted)}. Fix: click Resume to skip the children " \
                    "that depend on them and run the final review."
            else:  # nothing on a child is actionable (e.g. a depends_on that is not a finished sibling)
                left = [k["id"] for k in kids if k["stage"] not in ("done", "aborted")]
                new = "needs-human", f"{BLOCKED}: {', '.join(left)}. Fix: check each listed child's Depends on, " \
                    "then click Run now on a waiting child."
        if new != (parent["stage"], parent.get("reason")):
            if (new[1] or "").startswith(MACHINE_WAIT) and not (new[1].startswith(OVERLAP_WAIT)
                                                                or reason.startswith(MACHINE_WAIT)):  # once per hold
                # every machine wait (RAM, swap, CPU, cooling down, usage) clears on its own while the parent keeps
                # running: no stop for Trevor
                log_stop(root, parent["id"], "machine", new[1], auto=True)
            elif (new[1] or "").startswith(BLOCKED):
                log_stop(root, parent["id"], "bigboy", new[1])
            parent.update(stage=new[0], reason=new[1], updatedAt=now())
            if new[0] == "needs-human":
                parent["stopTitle"] = "BIGBOY_BLOCKED"
        out = {"ready": ready, "merged": merged, "total": len(kids), "in_progress": len(busy),
               "all_merged": finished == len(kids), "held": machine or ("ram_room" if ram_full else None),
               **({"left": shop_left} if shop_left else {})}  # `left`: waiting children kept for the shop (serve.py start_ready notes it)
    if was != "needs-human" and parent["stage"] == "needs-human":
        play(sound("needs-human"))
    return out


CHAIN_LOCK_STALE = 1800  # seconds; a crashed chaining session's lock is taken over after this


def chain_lock_live(root, parent_id) -> bool:
    """True when jobs/<parent>/.chain.lock exists and is no older than CHAIN_LOCK_STALE (a crashed holder's lock is not)."""
    try:
        return time.time() - (Path(root) / "jobs" / parent_id / ".chain.lock").stat().st_mtime <= CHAIN_LOCK_STALE
    except OSError:
        return False


def cmd_chain_lock(root, parent_id, holder, wait=540):
    """Take jobs/<parent>/.chain.lock for holder, polling every 2 s for up to `wait` seconds.
    The same holder re-acquires (refreshing it); a lock older than CHAIN_LOCK_STALE is taken over."""
    root, holder = Path(root), check_id(holder)
    lock = root / "jobs" / check_id(parent_id) / ".chain.lock"
    if not lock.parent.is_dir():
        raise SystemExit(f"no job folder {lock.parent}")
    deadline = time.monotonic() + wait
    while True:
        # The guard makes read-check-take atomic, so two waiters can never both take over a stale lock.
        with open(root / ".board.lock", "w") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                other = lock_holder(lock)
                if other != holder and time.time() - lock.stat().st_mtime <= CHAIN_LOCK_STALE:
                    fd = None
                else:
                    fd = os.open(lock, os.O_WRONLY | os.O_TRUNC)
            if fd is not None:
                with os.fdopen(fd, "w") as f:
                    f.write(json.dumps({"holder": holder, "at": now()}) + "\n")
                return {"acquired": True, "holder": holder}
        if time.monotonic() >= deadline:
            return {"acquired": False, "holder": other}
        time.sleep(2)


def lock_holder(lock):
    try:
        return json.loads(lock.read_text()).get("holder") or ""
    except (OSError, ValueError, AttributeError):
        return ""


def cmd_chain_unlock(root, parent_id, holder):
    """Remove jobs/<parent>/.chain.lock only when holder holds it."""
    root = Path(root)
    lock = root / "jobs" / check_id(parent_id) / ".chain.lock"
    with open(root / ".board.lock", "w") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        if lock.is_file() and lock_holder(lock) == check_id(holder):
            lock.unlink()
            return {"released": True}
    return {"released": False}


def lilguy_in_checkout(job: dict) -> bool:
    """True for a manual lilguy job: it runs in the main checkout with no worktree, builder or PR to wait on. A lilguy
    job with a worktree (Lilguy lane Worktree mode) is a normal PR job. A job with a runlog was launched by the
    pipeline (`spawn` writes it on every headless launch), so one that died before `B set worktree=` is stalled, not
    hand-run."""
    return job.get("lane") == "lilguy" and not job.get("worktree") and not job.get("runlog")


def no_pr_job(job: dict) -> bool:
    """True for an ops job (lanes/ops.md): no worktree, branch, PR or builder session, so nothing resumes it."""
    return job.get("lane") == "ops"


def merge_refusal(job: dict) -> str | None:
    """Why `job` may not move to done, or None. Its PR must be MERGED; a PR-less job may finish only on a parent
    (bigboy/runall) lane, an edit job (lanes/edit.md: no worktree or PR) or a lilguy job in the main checkout."""
    pr = job.get("pr")
    if not pr:
        return None if job.get("lane") in ("bigboy", "runall", "edit", "ops") or lilguy_in_checkout(job) else "not done: no PR recorded"
    m = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)", pr)
    if not m:
        return f"not done: could not confirm PR {pr} is merged: not a GitHub pull request URL"
    try:  # REST, not `gh pr view`: cloud sessions block GitHub GraphQL (SKILL.md Cloud lane)
        r = subprocess.run(["gh", "api", f"repos/{m[1]}/{m[2]}/pulls/{m[3]}", "--jq",
                            'if .merged then "MERGED" else (.state | ascii_upcase) end'],
                           capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        why = "timed out"
    except OSError as e:  # FileNotFoundError names the missing executable
        why = str(e)
    else:
        if r.returncode == 0:
            state = r.stdout.strip()
            return None if state == "MERGED" else f"not done: PR {pr} is {state}, not merged"
        why = next((l.strip() for l in r.stderr.splitlines() if l.strip()), f"gh exited {r.returncode}")
    return f"not done: could not confirm PR {pr} is merged: {why}"


def cmd_set(root, job_id, pairs, unpause=False, expect=None, internal=False, spawn_pid=None):
    """unpause writes to a paused job. Only the caller grants it: serve.py's Play and spawn bookkeeping, and
    `set --unpause`, which resume and rework use. Only an unpause write with stage= clears `paused`. expect: write only
    while the job is still in that stage (checked under the lock), else raise SystemExit and write nothing.
    stage=needs-human is refused (a stop is a closed question: `ask`) unless internal, which only cmd_cloud_sync passes.
    Entering stage=merging is refused for a fast or standard job with no round-N/review-code.md, decision.md or
    human-approval.md."""
    if "stage=needs-human" in pairs and not internal:
        raise SystemExit(f'use board.py ask {job_id} "<question>" --a "Label=command" --b "Label=command" --title TITLE: '
                         "set never parks a job at needs-human")
    d = Path(root) / "jobs" / check_id(job_id)
    files, div = job_files(d), diverged(d)
    given = dict(pair.partition("=")[::2] for pair in pairs)
    pid = (caller_claude_pid() if given["tty"] else None) if "tty" in given else None  # ps before the lock, never under it
    if isinstance(spawn_pid, int) and "tty" in given and not given["tty"]:  # int: a mock Popen has a MagicMock pid
        pid = spawn_pid  # job 1274: spawn passes its child's pid (a keyword, not a set key), so a short-id prompt reads alive
    if given.get("stage") == "done":
        # Read without the lock so `gh` never runs while holding it; only one orchestrator marks a given job done,
        # so the read-then-write race is accepted.
        job = dict(live(read_board(root), job_id, unpause))
        if job["stage"] != "done":
            job.update({k: given[k] or None for k in ("pr", "lane") if k in given})
            msg = merge_refusal(job)
            if msg:
                raise SystemExit(msg)
    with locked_board(root) as board:
        job = live(board, check_id(job_id), unpause)
        was = job["stage"]
        if expect and was != expect:
            raise SystemExit(f"job {job_id} is {was}, not {expect}; left alone")
        lane = given.get("lane") or job.get("lane")  # job 1044: a shop fast job merged with no reviewer
        if given.get("stage") == "merging" and was != "merging" and lane in ("fast", "standard") \
                and not any((d / f).exists() for f in ("decision.md", "human-approval.md")) \
                and not any(d.glob("round-*/review-code.md")):
            raise SystemExit(f"not merging: {lane} job {job_id} has no round-N/review-code.md, decision.md or "
                             "human-approval.md; run the code review (Fast lane step 2 / Review) first")
        if os.environ.get("SCRUM_SHOP") and given.get("lane") in ("fast", "standard") and not (d / "lilguy-fit.json").exists() \
                and (not job.get("parent") or next((j.get("lane") for j in board["jobs"] if j["id"] == job["parent"]), None) == "runall"):
            raise SystemExit(f"run B lilguy-fit {job_id} first (New job step 3 Lilguy route)")  # digest 113: shop jobs skipped the route
        for pair in pairs:
            key, sep, value = pair.partition("=")
            if not sep or key not in FIELDS:
                raise SystemExit(f"bad field {pair!r}; allowed: {', '.join(FIELDS)}")
            if key == "stage" and value not in STAGES:
                raise SystemExit(f"bad stage {value!r}; allowed: {', '.join(STAGES)}")
            if value and key in SHAPES and not SHAPES[key].fullmatch(value):
                raise SystemExit(f"bad field {pair!r}; {key} must match {SHAPES[key].pattern}")
            if key == "waiting":
                value = clean(value, 200)
            if key == "outcome":
                value = clean(value, 300)
            job[key] = int(value) if key in ("round", "limit") else (value or None)
        if unpause and "stage" in given:
            job.pop("holdPause", None)  # Trevor's Play: a later overload pause may be auto-played again
            job.pop("paused", None)  # resume and rework re-enter a stage; spawn bookkeeping keeps the pause
            job.pop("limitResetAt", None)  # resume re-enters the same stage, so the stage-change drop below never runs
            job.pop("stalled", None)
        if job["stage"] != was and "outcome" not in given:
            job.pop("outcome", None)  # the last dashboard run's outcome describes the stage it left
        if "tty" in given:
            job["pid"] = pid  # internal, not in FIELDS: a hand-set pid could mark a job alive forever
        if job["stage"] != was:
            job.pop("limitResetAt", None)  # serve.py's usage-limit hold ends when the job leaves its stage
            job.pop("stalled", None)  # so does a stall in that stage
            job.pop("soloRun", None)  # and a solo run's reservation (job 1361)
            job.pop("soloAt", None)
        job["files"], job["diverged"] = files, div
        job["updatedAt"] = now()
    if job["stage"] != was and job["stage"] in ("done", "needs-human"):
        play(sound(job["stage"]))


def questions_log(root, entry):
    """Append one JSON line to <scrum>/questions.log. Caller holds the board lock, so lines never interleave."""
    with open(Path(root) / "questions.log", "a") as f:
        f.write(json.dumps(entry) + "\n")


def log_stop(root, job_id, kind, reason, auto=False, **extra):
    """Append one stop line (kind: stall, machine, bigboy or refused) to questions.log. Caller holds the board lock.
    `auto`: the scrum clears it on its own (a stall auto_resume retries, any machine wait); the line carries
    "auto": true and process-health counts it for no metric. `extra` keys go on the line as they are."""
    questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id, "kind": kind,
                         "reason": reason, **({"auto": True} if auto else {}), **extra})


UNBLOCK_KINDS = ("round-limit", "check-fail", "ci-fail", "conflict", "blocked", "render")
UNBLOCK_MAX = 2  # unblocks per job, ever; a kind is unblocked at most once (the loop guard compares kinds, not text)


GUARD_ASK_PREFIXES = ("Uncommitted change in", "Unpushed commits in")  # SKILL.md Merge "Main checkout guard" asks
GUARD_ASK_WRONG_BRANCH = " main checkout is on "  # the WRONG_BRANCH ask opens with the repo name, so it is matched inside


def is_guard_ask(reason) -> bool:
    """True when reason opens like one of Merge's Main checkout guard asks (SKILL.md)."""
    reason = str(reason or "")
    return reason.startswith(GUARD_ASK_PREFIXES) or GUARD_ASK_WRONG_BRANCH in reason[:80]


def park(root, job, question, parsed, title, recommend=None, auto=False):
    """The needs-human field update and questions.log line of cmd_ask. Caller holds the board lock and plays the sound.
    auto: the scrum answers it itself (claude_batch's Terminal batch), so the line carries "auto": true."""
    if job.get("reason") != question:
        job.pop("outcome", None)  # a new blocker: the last run's outcome no longer applies
    job.update(stage="needs-human", reason=question, question=question, options=parsed, stopTitle=title,
               updatedAt=now())
    job.pop("stalled", None)  # a question, not a stall: a later `set --unpause stage=` must not bring the flag back
    job.pop("limitResetAt", None)
    entry = {"date": now(), "project": Path(root).resolve().parent.name, "job": job["id"],
             "question": question, "options": parsed, "reason": question, "stopTitle": title,
             "kind": "bigboy" if question.startswith(("bigboy review: main not updated", BLOCKED)) else "ask"}
    if auto or is_guard_ask(question):
        entry["auto"] = True  # the scrum resumes or answers it itself: no stop for process_health
    if recommend:
        job["recommend"] = entry["recommend"] = recommend
    else:
        job.pop("recommend", None)  # a re-ask without one drops the old question's advice
    questions_log(root, entry)


def _behind_main_prisma(root, job_id):
    """True when the job's worktree lacks its base and base differs under prisma/, with no behind-main rework yet:
    the Merge step "Auto-rework: behind main" applies, not a DATABASE_CHANGE ask. Any git failure is False."""
    job = next((j for j in read_board(root)["jobs"] if j["id"] == job_id), None)
    wt, base = (job or {}).get("worktree"), (job or {}).get("base")
    if not wt or not base or not Path(wt).is_dir() or base.startswith("-"):
        return False
    rework = Path(root) / "jobs" / job_id / "rework.md"
    if rework.exists() and any(l.startswith("Auto-rework: behind main") for l in rework.read_text(errors="replace").splitlines()):
        return False
    try:
        if subprocess.run(["git", "-C", str(wt), "merge-base", "--is-ancestor", base, "HEAD"], capture_output=True, timeout=60).returncode == 0:
            return False
        return bool(_git(wt, "diff", "--name-only", "HEAD", base, "--", "prisma").strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return False


def cmd_ask(root, job_id, question, options, kind=None, recommend=None, *, title):
    """Park the job at needs-human with a closed question: options are 2-3 "label=command" strings, keyed a, b, c in
    order. recommend is an optional (key, why) naming the option the agent advises. Returns the stored option dicts.
    An eligible kind (lanes/unblock.md) leaves the job in its stage and returns {"unblock": True, "n": N} instead.
    title must be a STOP_TITLES key; it is stored as stopTitle on a parked job (not on an unblock, a stall or a queue wait: a check job asking `waiting on the
    E2E|Check|Build queue` stays in check with reason E2E_QUEUE_WAIT, CHECK_QUEUE_WAIT or BUILD_QUEUE_WAIT and returns {"waiting": True})."""
    if title not in STOP_TITLES:
        raise SystemExit(f"ask needs --title, one of: {', '.join(STOP_TITLES)} (got {title!r})")
    question = question.strip()
    if not question:
        raise SystemExit("ask needs a question")
    if kind is not None and not re.fullmatch(r"[a-z][a-z-]*", kind):
        raise SystemExit(f"bad kind {kind!r}; expected lowercase words joined by hyphens")
    if not 2 <= len(options) <= 3:
        raise SystemExit(f"ask needs 2 or 3 options, got {len(options)}")
    parsed = []
    for key, raw in zip("abc", options):
        label, sep, command = raw.partition("=")
        label, command = label.strip(), command.strip()
        if not sep or not label:
            raise SystemExit(f"bad option {raw!r}; expected label=command")
        if not ASK_COMMAND_RE.fullmatch(command):
            raise SystemExit(f"bad option command {command!r}; allowed: approve <id>, rework <id> \"<text>\", "
                             "followup <id> \"<fix>\", abort <id> [--requeue|--cascade], resume <id>, lilguy <id>, apply <id>, shell: <command>")
        parsed.append({"key": key, "label": label, "command": command})
    if recommend is not None:
        rkey, why = recommend[0].strip(), clean(recommend[1])
        if rkey not in [o["key"] for o in parsed]:
            raise SystemExit(f"bad recommend key {rkey!r}; the question offers {', '.join(o['key'] for o in parsed)}")
        if not why:
            raise SystemExit("recommend needs a reason")
        recommend = {"key": rkey, "why": why}
    if title == "DATABASE_CHANGE" and _behind_main_prisma(root, job_id):
        raise SystemExit("this job is behind main with a prisma diff: do not ask. Append `Auto-rework: behind main` to "
                         "rework.md, merge origin/<default> per Conflicts sub-steps 1-4, go to the Check gate (no `B ask`)")
    with locked_board(root) as board:
        job = live(board, check_id(job_id))
        # job 1536: a CHECKS_FAILING ask whose last local Test or E2E run had load5 over cores is load too
        loaded = title == "CHECKS_FAILING" and job["stage"] in WATCHED and job["stage"] not in ("merging", "deploying") \
            and checks_load(job)
        if job["stage"] in WATCHED and (_load_ask(question, title) or loaded):  # the machine, not the bug: wait, no unblocker
            waits = job.get("loadWaits", 0)
            solo = waits >= LOAD_WAITS_MAX and not job.get("loadSolo")
            if waits < LOAD_WAITS_MAX or solo:
                wait = LOAD_SOLO_WAIT if solo else f"{QUIET_CHECK_WAIT} {loaded}" if loaded else LOAD_BLOCK_WAIT
                reason = f"{STALL}{wait}"
                for k in ("question", "options", "recommend", "stopTitle", "outcome"):
                    job.pop(k, None)
                job.update(stalled=True, reason=reason, updatedAt=now(), **({"loadSolo": 1} if solo else {"loadWaits": waits + 1}))
                questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id,
                                     "question": question, "reason": reason, "kind": "stall", "auto": True})
                return {"stalled": True}
            question = f"Failed under machine load {LOAD_WAITS_MAX} times on a quiet machine: {question}"
            kind = None  # parked for Trevor: never spend an unblocker session on it
        kinds = job.get("unblockKinds", [])
        if kind in UNBLOCK_KINDS and job.get("unblocks", 0) < UNBLOCK_MAX and kind not in kinds:
            n = job.get("unblocks", 0) + 1
            job.update(unblocks=n, unblockKinds=[*kinds, kind], updatedAt=now())
            questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id,
                                 "kind": kind, "unblock": n, "question": question})
            return {"unblock": True, "n": n}
        was = job["stage"]
        if was == "check" and (m := QUEUE_ASK_RE.match(question)):  # a capacity wait, not a stall: no try spent
            reason = {"E2E": E2E_QUEUE_WAIT, "BUILD": BUILD_QUEUE_WAIT}.get(m[1].upper(), CHECK_QUEUE_WAIT)
            for k in ("question", "options", "recommend", "stopTitle", "outcome", "stalled"):
                job.pop(k, None)
            job.update(reason=reason, updatedAt=now())
            questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id,
                                 "reason": reason, "kind": "queue-wait", "auto": True})
            return {"waiting": True}
        # a session that did not load the scrum agent types is a session fault: stalled in its stage, so
        # auto_resume retries it; not a human stop, so no question and no sound. A GitHub billing CI refusal stalls
        # the same way: its answer is always Try again, which auto_resume gives
        billing = was in WATCHED and CI_BILLING_RE.search(question)
        if billing or (was in WATCHED and AGENT_TYPES_RE.search(question)):
            reason = f"{STALL}{CI_BILLING_WAIT if billing else question}"
            hit = [job]
            if billing:  # one refusal parks every job waiting on CI, and alerts Trevor once (the first time only)
                alert = not any(j.get("reason") == reason for j in board["jobs"] if j["stage"] not in ("done", "aborted"))
                hit += [j for j in board["jobs"] if j is not job and j["stage"] == "merging"
                        and not j.get("paused") and not j.get("stalled")]
            for j in hit:
                if j.get("reason") != reason:
                    j.pop("outcome", None)
                for k in ("question", "options", "recommend", "stopTitle"):
                    j.pop(k, None)
                j.update(stalled=True, reason=reason, updatedAt=now())
                questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": j["id"],
                                     "question": question, "reason": reason, "kind": "stall", "auto": True})
            if billing and alert:
                play(sound("needs-human"))
            return {"stalled": True}
        park(root, job, question, parsed, title, recommend)
    if was != "needs-human":
        play(sound("needs-human"))
    return parsed


def cmd_wait_on(root, job_id, blocker, then=None) -> dict:
    """Park a builder-blocked job at stage waiting on another job on this board (SKILL.md New job step 5), so
    wake_waiting restarts it once that job merges. blocker is a full id or a number matching one id's NNN- start.
    then="approve <job_id>" (SKILL.md Migrate step 2) keeps the worktree and records it as `wake`: wake_waiting then
    parks the job at needs-human with Try again, and serve.py spawns approve. Appends `<epoch> <blocker>` to
    dep-waits.txt and a `depends_on:<blocker>` queue gate, for timing.md."""
    if then is not None and then != f"approve {job_id}":
        raise SystemExit(f"bad --then {then!r}; expected \"approve {job_id}\"")
    with locked_board(root) as board:
        job = live(board, check_id(job_id))
        ids = [j["id"] for j in board["jobs"]]
        hits = [blocker] if blocker in ids else [i for i in ids if blocker.isdigit() and i.startswith(blocker + "-")]
        if len(hits) != 1:
            raise SystemExit(f"blocker {blocker!r} matches {len(hits)} jobs on the board; expected one")
        dep = find(board, hits[0])
        if dep["id"] == job_id:
            raise SystemExit(f"job {job_id} cannot wait on itself")
        if dep["id"] == job.get("parent"):
            raise SystemExit(f"job {job_id} cannot wait on its parent {dep['id']}; the parent waits on its children")
        if dep["stage"] in ("done", "aborted"):
            raise SystemExit(f"blocker {dep['id']} is {dep['stage']}; there is nothing to wait for")
        seen, todo = set(), [dep["id"]]
        while todo:  # follow depends_on from the blocker: reaching job_id would leave the whole cycle waiting for good
            i = todo.pop()
            if i == job_id:
                raise SystemExit(f"blocker {dep['id']} already waits on {job_id}")
            if i not in seen:
                seen.add(i)
                todo += next((j.get("depends_on") or [] for j in board["jobs"] if j["id"] == i), [])
        job.update(stage="waiting", depends_on=[dep["id"]], reason=f"waiting on {dep['id']}", updatedAt=now(),
                   **({"wake": then} if then else {"worktree": None}))
    try:  # timing.md: _timing_row moves this wait from Spec to Queue
        with (Path(root) / "jobs" / job_id / "dep-waits.txt").open("a", encoding="utf-8") as f:
            f.write(f"{int(time.time())} {dep['id']}\n")
    except OSError:
        pass
    note_queue_gate(root, job_id, f"depends_on:{dep['id']}")
    return {"id": job_id, "waiting_on": dep["id"]}


def parked_waiting(job) -> bool:
    """A job wake_waiting may claim or park: waiting on depends_on, with no parent (cmd_ready's) unless it has `wake`,
    and no Human setup or pause."""
    return bool(job["stage"] == "waiting" and (job.get("wake") or not job.get("parent")) and job.get("setup") != "pending"
                and not job.get("paused") and job.get("depends_on"))


def wake_waiting(root, room=None, hold=None) -> dict:
    """Claim (stage -> spec) up to room (None = no cap) parentless waiting jobs whose depends_on are all done; park one
    whose dependency was aborted or is gone with cmd_ask. A BigBoy/Run-all child is left to cmd_ready. A `wake` job
    (cmd_wait_on then=, child or not) is never claimed into spec: it goes back to needs-human with Try again, counts
    against room and is listed under "retry" (only when any is). A job for which `hold(job)` is truthy (a sibling blocks
    the restart) is left as it is, waiting with its wake, outside room. Returns {"ready", "lost"[, "retry"]}."""
    ready, lost, retry = [], {}, []
    if not any(map(parked_waiting, read_board(root)["jobs"])):  # nothing parked: never rewrite board.json each tick
        return {"ready": ready, "lost": []}
    with locked_board(root) as board:
        stage = {j["id"]: j["stage"] for j in board["jobs"]}
        for j in filter(parked_waiting, board["jobs"]):
            deps = j["depends_on"]
            gone = [d for d in deps if stage.get(d) in (None, "aborted")]
            if gone:
                lost[j["id"]] = (gone[0], j.pop("wake", None))
            elif all(stage[d] == "done" for d in deps) and (room is None or len(ready) + len(retry) < room):  # rest wait a tick
                if hold and hold(j):  # inside the lock: hold must not re-read board.json
                    continue
                if j.get("wake"):  # no sound: serve.py spawns the retry right away, the card only covers a dead session
                    q = f"retry: {deps[0]} is done, so this job tries again."
                    j.update(stage="needs-human", question=q, reason=q, stopTitle="DEPENDENCY", updatedAt=now(), options=[
                        {"key": "a", "label": "Try again", "command": f"approve {j['id']}"},
                        {"key": "b", "label": "Remove this job", "command": f"abort {j['id']} --cascade"}])
                    j.pop("wake")
                    j.pop("recommend", None)
                    retry.append(j["id"])
                else:
                    j.update(stage="spec", reason=None, updatedAt=now())
                    ready.append(j["id"])
                j["started_by"] = "wake"  # serve.py's cool-down refusal lets a woken start through
    for job_id, (dep, wake) in lost.items():
        try:  # one refused ask (the job was aborted meanwhile) must not hide the claimed ready jobs from the caller
            if wake:
                cmd_ask(root, job_id, f"retry: {dep} was aborted or removed, so this job no longer waits on it.",
                        [f"Try again=approve {job_id}", f"Remove this job=abort {job_id} --cascade"], title="DEPENDENCY")
            else:
                cmd_ask(root, job_id, f"blocked: {dep} was aborted or removed, so this job has nothing to wait for.",
                        [f"Put back on the backlog=abort {job_id} --requeue", f"Remove this job=abort {job_id} --cascade"],
                        title="DEPENDENCY")
        except SystemExit as e:
            print(f"wake_waiting: {job_id}: {e}", file=sys.stderr)
    return {"ready": ready, "lost": list(lost), **({"retry": retry} if retry else {})}


def cmd_unblock_log(root, job_id):
    """Log the verdict of the job's latest scrum-unblocker file (jobs/<id>/unblock-<unblocks>.md) to questions.log."""
    with locked_board(root) as board:
        job = live(board, check_id(job_id))
        n, kind = job.get("unblocks", 0), (job.get("unblockKinds") or [None])[-1]
        try:
            lines = (Path(root) / "jobs" / job_id / f"unblock-{n}.md").read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        first = lines[0].strip() if lines else ""
        verdict = first[9:] if first in ("VERDICT: REWORK", "VERDICT: RESPEC", "VERDICT: ESCALATE") else "INVALID"
        blocker = lines[1].strip() if len(lines) > 1 else ""
        questions_log(root, {"date": now(), "job": job_id, "kind": kind, "verdict": verdict, "blocker": blocker})
    return {"verdict": verdict, "blocker": blocker, "kind": kind, "n": n}


def cmd_answer(root, job_id, key, note=None, auto=False):
    """Log Trevor's pick on the job's open question and return that option; the stage is left to the command it names.
    A non-blank note he typed with the pick goes on the same line; auto (the scrum picked it) adds "auto": true."""
    with locked_board(root) as board:
        job = find(board, check_id(job_id))
        if job["stage"] != "needs-human" or not job.get("options"):
            raise SystemExit(f"job {job_id} has no open question")
        option = next((o for o in job["options"] if o["key"] == key), None)
        if option is None:
            raise SystemExit(f"no option {key!r}; the question offers {', '.join(o['key'] for o in job['options'])}")
        entry = {"date": now(), "job": job_id, "pick": option["label"]}
        if note := clean(note or "", ITEM_MAX):
            entry["note"] = note
        if auto:
            entry["auto"] = True
        questions_log(root, entry)
    return option


FOLLOWUP_REASON = "prod check failed; fix filed on the backlog"


def cmd_followup(root, job_id, fix):
    """A `followup <id> "<fix>"` answer: add "<fix> (from <id>)" to the backlog, then set the job stage=done with
    FOLLOWUP_REASON. Each write takes its own lock; unless_open skips the item when it is still open, so a re-run after
    a failed done write adds no second copy. The PR merged before the Prod check, so merge_refusal passes."""
    fix = clean(fix or "", ITEM_MAX + 1)
    item = f"{fix} (from {check_id(job_id)})"
    if not fix:
        raise SystemExit("followup needs the fix text")
    if len(item) > ITEM_MAX:
        raise SystemExit(f"followup fix text is too long; the backlog item must fit {ITEM_MAX} characters")
    live(read_board(root), job_id)  # an unknown or aborted job files nothing
    cmd_backlog_add(root, [item], unless_open=item)
    cmd_set(root, job_id, ["stage=done", f"reason={FOLLOWUP_REASON}"])


def cmd_project_note(root, line) -> dict:
    """`project-note '<line>'` (job 1369): append a spec's `Project note:` line to the first `- Notes:` line of
    <root>/project.md, or add `- Notes: <line>` as a new last line when there is none. Under an fcntl lock on
    .project.md.lock: a line whose stripped text is already in the file writes nothing ({"added": false}); otherwise
    the old bytes go to project.md.bak, then the new text is written through a tmp file and os.replace. Every other
    byte, line endings included, stays. Never creates project.md."""
    note = (line or "").strip()
    if not note or "\n" in note or "\r" in note:
        raise SystemExit("project-note: the line is empty or has a newline")
    path = Path(root) / "project.md"
    if not path.is_file():
        raise SystemExit("project-note: scrum/project.md is missing")
    with open(path.with_name(".project.md.lock"), "w") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        try:
            before = path.read_bytes()
        except FileNotFoundError:
            raise SystemExit("project-note: scrum/project.md is missing") from None
        text = before.decode()
        if note in text:
            return {"added": False}
        lines = re.findall(r"[^\n]*\n|[^\n]+", text)  # each keeps its own line ending
        hit = next((i for i, l in enumerate(lines) if l.startswith("- Notes:")), None)
        if hit is None:
            lines.append(("\n" if text and not text.endswith("\n") else "") + f"- Notes: {note}\n")
        else:
            body = lines[hit].rstrip("\r\n")
            lines[hit] = f"{body.rstrip()} {note}" + lines[hit][len(body):]
        path.with_name("project.md.bak").write_bytes(before)
        tmp = path.with_name(f"project.md.{os.getpid()}.tmp")
        tmp.write_bytes("".join(lines).encode())
        os.replace(tmp, path)
    return {"added": True}


def log_note(root, job_id, action, text):
    """Append Trevor's typed rework or discuss text to questions.log as a `kind: note` line; blank text logs nothing.
    Takes the board's flock only, like serve.py `refused`: board.json is left as it was."""
    if not (note := clean(text or "", ITEM_MAX)):
        return
    with open(Path(root) / ".board.lock", "w") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id, "kind": "note",
                             "action": action, "note": note})


def cmd_sync(root, job_id):
    d = Path(root) / "jobs" / check_id(job_id)
    if not d.is_dir():
        raise SystemExit(f"no job folder {d}")
    round_dirs = sorted((p for p in d.iterdir() if p.is_dir() and re.fullmatch(r"round-\d+", p.name)),
                        key=lambda p: int(p.name[6:]))
    rounds = [{"check": first_word(p / "check.md", ("PASS", "FAIL")) or "pending",
               **{r: first_word(p / f"review-{r}.md", ("PASS", "CHANGES")) or "pending" for r in REVIEWERS}}
              for p in round_dirs]
    files = job_files(d)
    decision = first_word(d / "decision.md", ("APPROVE", "REWORK", "ESCALATE"))
    reworks = sum(first_word(p / "decision.md", ("APPROVE", "REWORK", "ESCALATE")) == "REWORK" for p in round_dirs)
    last = rounds[-1] if rounds else None
    last_n = int(round_dirs[-1].name[6:]) if round_dirs else 0
    reviews = {r: last[r] for r in REVIEWERS} if last else {r: "pending" for r in REVIEWERS}
    with locked_board(root) as board:
        job = live(board, job_id)
        job.update(rounds=rounds, files=files, diverged=diverged(d), reviews=reviews, round=max(job["round"], last_n), updatedAt=now())
    complete = bool(last) and "pending" not in reviews.values()
    # Optional e2e review: counts toward verdict and invalid when present, never reported missing.
    e2e = first_word(round_dirs[-1] / "review-e2e.md", ("PASS", "CHANGES")) if round_dirs else None
    counted = {**reviews, **({"e2e": e2e} if e2e else {})}
    invalid = [r for r, v in counted.items() if v == "INVALID"]
    verdict = None if not complete else "INVALID" if invalid else \
        "PASS" if all(v == "PASS" for v in counted.values()) else "CHANGES"
    missing = [f"review-{r}.md" for r, v in reviews.items() if v == "pending"]
    return {"round": last_n, "complete": complete, "verdict": verdict, "invalid": invalid, "missing": missing,
            "check": last["check"] if last else None, "decision": decision, "reworks": reworks, "e2e": e2e}


# --- cloud-sync: lanes/cloud.md Sync's PR lookup and board updates, in plain Python (serve.py polls it) ---
CLOUD_PULLS = "repos/{owner}/{repo}/pulls?state=all&per_page=100&sort=created&direction=desc"  # gh fills in origin
CLOUD_MARK = "<!-- scrum needs-human -->"  # second line of the cloud session's needs-human comment
CLOUD_LABEL = "scrum:needs-human"
CLOUD_CLOSED = "requeue: cloud PR closed without merging"
CLOUD_SELF_ABORT = ("requeue:", "obsolete:", "looks already fixed:")  # the cloud job aborted itself (Auto-abort)
CLOUD_MOVED = re.compile(r"moved to [\w.-]+ backlog")  # New job 3b Wrong-project abort (job 1521); fullmatch only
CLOUD_LANE = re.compile(r"^Scrum lane: (fast|standard|debug|lilguy)[ \t]*$", re.M)  # the PR body's lane line
CLOUD_PENDING_HOURS = 24  # how long a moved job waits for its scrum-artifacts/<id> push; fixed, not a setting


class GhError(Exception):
    """A failed `gh api` call; the message is the reason."""


def gh_api(repo: Path, endpoint: str, *flags: str) -> list | dict:
    """`gh api <flags> <endpoint>` in repo, parsed. REST only: cloud sessions block GitHub GraphQL. Raises GhError."""
    try:
        r = subprocess.run(["gh", "api", *flags, endpoint], cwd=repo, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise GhError(f"gh api {endpoint} timed out") from None
    except OSError as e:  # FileNotFoundError names the missing executable
        raise GhError(str(e)) from None
    if r.returncode != 0:
        raise GhError(next((l.strip() for l in r.stderr.splitlines() if l.strip()), f"gh exited {r.returncode}"))
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise GhError(f"gh api {endpoint} printed no JSON ({e})") from None


def cloud_worktree(repo: Path, job_id: str, ref: str | None = None) -> str | None:
    """`git fetch origin`, then `git worktree add <repo>/.claude/worktrees/scrum-<id> <ref>` (ref defaults to
    scrum/<id>; the PR's head ref can be the short scrum/<number>), as rework does. Returns the path, or None when the
    add failed."""
    repo = Path(repo).resolve()
    path = repo / ".claude" / "worktrees" / f"scrum-{check_id(job_id)}"  # an id starts with a digit, never "-"
    try:
        subprocess.run(["git", "-C", str(repo), "fetch", "origin"], capture_output=True, timeout=120)
        r = subprocess.run(["git", "-C", str(repo), "worktree", "add", str(path), ref or f"scrum/{job_id}"],
                           capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return str(path) if r.returncode == 0 else None


def cloud_worktree_remove(repo: Path, path: str) -> None:
    """`git -C <repo> worktree remove <path>` for a worktree cloud_worktree just added; a failure is printed, not
    raised. path is cloud_worktree's absolute path, so it never starts with "-"."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "worktree", "remove", path], capture_output=True, timeout=60)
        err = r.returncode and (r.stderr.decode(errors="replace").strip() or f"git exited {r.returncode}")
    except (subprocess.TimeoutExpired, OSError) as e:
        err = str(e)
    if err:
        print(f"cloud-sync: worktree remove {path} failed: {err}", file=sys.stderr)


def artifacts_pushed(repo: Path, job_id: str) -> bool:
    """Whether the cloud session pushed scrum-artifacts/<id> (Artifacts home then has work to do)."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "ls-remote", "--exit-code", "origin",
                            f"refs/heads/scrum-artifacts/{check_id(job_id)}"], capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def branch_pushed(repo: Path, job_id: str) -> bool:
    """Whether an ended shop session pushed scrum/<id> (job 1414: its work, with no PR, comes home). An offline or failed
    ls-remote reads as no branch."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "ls-remote", "--exit-code", "origin",
                            f"refs/heads/scrum/{check_id(job_id)}"], capture_output=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def _login(item):
    """item's user.login (a REST PR or comment), or None."""
    user = item.get("user")
    return user.get("login") if isinstance(user, dict) else None


def _cloud_trusted(pr, job_id):
    """Whether pr is this job's: its head is this repo's own scrum/<id> (or scrum/<number>, or scrum/<number>-<one or
    more chars> for this job's own number: a session's own slug, job 1414) branch, and a leading `[scrum <tag>]` names
    the id or its number. An untagged title is matched by its head; a fork PR, another branch or another job's tag
    steers nothing."""
    head, base = pr.get("head"), pr.get("base")
    number = job_id.split("-", 1)[0]
    names = {job_id, number}
    ref = head.get("ref") if isinstance(head, dict) else None
    if not isinstance(base, dict) or not isinstance(ref, str) or not (
            ref in {f"scrum/{n}" for n in names} or re.fullmatch(rf"scrum/{re.escape(number)}-.+", ref)):
        return False
    tag = re.match(r"\[scrum ([^\]]*)\]", str(pr.get("title") or ""))
    if tag and tag[1] not in names:
        return False
    full = [r.get("full_name") if isinstance(r, dict) else None for r in (head.get("repo"), base.get("repo"))]
    return bool(full[0]) and full[0] == full[1]


def _cloud_arrivals(root, repo):
    """Re-check every job carrying artifactsPending: return those whose scrum-artifacts/<id> exists, keeping their mark
    until cloud_pending_clear runs once cloud-home spawns; drop the mark, unreturned, when the branch is missing and
    the mark is CLOUD_PENDING_HOURS old or unreadable."""
    pending = [j for j in read_board(root)["jobs"] if j.get("artifactsPending")]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CLOUD_PENDING_HOURS)
    arrived, drop = [], set()
    for job in pending:
        if artifacts_pushed(repo, job["id"]):
            arrived.append(job["id"])
            continue
        try:
            stale = datetime.fromisoformat(job["artifactsPending"]) < cutoff
        except (TypeError, ValueError):
            stale = True  # an unreadable mark would cost an ls-remote every poll forever
        if stale:
            drop.add(job["id"])
    if drop:
        with locked_board(root) as board:
            for job in board["jobs"]:
                if job["id"] in drop:
                    job.pop("artifactsPending", None)
    return arrived


def cloud_pending_mark(root: Path, job_id: str) -> None:
    """Set job_id's artifactsPending mark to now() under the board lock, so cloud-sync reports it once its
    scrum-artifacts/<id> branch arrives (serve.py cloud_tick, after a shop `moved to <folder> backlog` abort: job 1504).
    A missing job is a no-op."""
    with locked_board(root) as board:
        for job in board["jobs"]:
            if job["id"] == job_id:
                job["artifactsPending"] = now()  # internal, not in FIELDS, like pid


def cloud_pending_clear(root: Path, job_id: str) -> None:
    """Drop job_id's artifactsPending mark under the board lock (serve.py calls it once cloud-home spawned). A missing
    job or mark is a no-op."""
    with locked_board(root) as board:
        for job in board["jobs"]:
            if job["id"] == job_id:
                job.pop("artifactsPending", None)


def _cloud_home_plan(job_id, head, url=None, ref=None):
    """_cloud_plan's HOME tuple for an ended shop job (job 1414): its open PR (url, head, base ref), or, with url None,
    its pushed scrum/<id> branch head. reason is the spec stall's; pairs are the needs-human fallback's cmd_set pairs,
    used when its worktree cannot be added. No lane: the local New job's spec decides it."""
    left = f"PR {url} open" if url else f"branch {head} pushed with no PR"
    reason = f"{STALL}shop session ended leaving {left}; {f'its branch {head}' if url else 'it'} is home for the local pipeline"
    pairs = ["stage=needs-human", *([f"pr={url}"] if url else []), *([f"base=origin/{ref}"] if url and ref else []),
             f"reason=shop session ended leaving {left}, but its worktree could not be added here. "
             f"Fix: free .claude/worktrees/scrum-{job_id}, then rework or abort the job."]
    return "HOME", pairs, reason, True, None, head


def _cloud_plan(repo, job_id, prs, ended=False):
    """(state, pairs, reason, needs a worktree, abort, head ref) for this job's newest PR (_cloud_trusted), or None while it still
    runs. abort is None, or (requeue, PR number to close or None). Makes the one comments call a needs-human PR needs;
    raises GhError. ended (its shop session ended, job 1414): an open PR without the scrum:needs-human label is HOME
    (_cloud_home_plan) instead of None."""
    pr = next((p for p in prs if isinstance(p, dict) and _cloud_trusted(p, job_id)), None)
    if not pr:
        return None
    url, head = pr.get("html_url") or "", pr["head"]["ref"]  # _cloud_trusted checked head is a dict with a ref
    lane = [f"lane={m[1]}"] if (m := CLOUD_LANE.search(str(pr.get("body") or ""))) else []  # first line wins
    if pr.get("merged_at"):
        return "MERGED", ["stage=done", f"pr={url}", "reason="] + lane, None, False, None, head
    if pr.get("state") == "closed":
        return "CLOSED", [f"pr={url}"] + lane, CLOUD_CLOSED, False, (True, None), head
    if CLOUD_LABEL not in [l.get("name") for l in pr.get("labels") or [] if isinstance(l, dict)]:
        return _cloud_home_plan(job_id, head, url, (pr.get("base") or {}).get("ref")) if ended else None
    number = pr.get("number")
    if not isinstance(number, int):
        raise GhError(f"PR {url} has no number")
    comments = gh_api(repo, f"repos/{{owner}}/{{repo}}/issues/{number}/comments?per_page=100")
    if not isinstance(comments, list):
        raise GhError(f"gh api comments for PR {url} did not return a list")
    author = _login(pr)  # only the PR author (the cloud session's account) may steer the job
    bodies = [str(c.get("body") or "") for c in comments
              if isinstance(c, dict) and author and _login(c) == author and CLOUD_MARK in str(c.get("body") or "")]
    reason = clean(bodies[-1].split("\n")[0], 300) if bodies else ""
    reason = reason or f"cloud job needs a human; no reason comment on {url}. Fix: read the PR."
    if reason.startswith(CLOUD_SELF_ABORT) or CLOUD_MOVED.fullmatch(reason):
        return "ABORTED", [f"pr={url}"] + lane, reason, False, (reason.startswith("requeue:"), number), head
    pairs = ["stage=needs-human", f"pr={url}"]
    ref = (pr.get("base") or {}).get("ref")
    if ref:
        pairs.append(f"base=origin/{ref}")
    return "NEEDS-HUMAN", pairs + lane + [f"reason={reason}"], reason, True, None, head


def _cloud_abort(root, job_id, url, requeue, reason, lane=None):
    """Record pr= (and lane= when given) and abort a job still in stage cloud, atomically. With requeue, a BigBoy child
    is aborted without a requeue (Auto-abort rule); a Run-all child is requeued, as cmd_abort's cascade does."""
    with locked_board(root) as board:
        job = live(board, check_id(job_id))
        if job["stage"] != "cloud":
            raise SystemExit(f"job {job_id} is {job['stage']}, not cloud; left alone")
        job["pr"] = url
        if lane:
            job["lane"] = lane
        abort_job(root, job, requeue and (not job.get("parent") or runall_child(board, job)), reason)


def _cloud_home(root: Path, job_id: str, url: str | None, base: str | None, worktree: str, head: str,
                reason: str) -> None:
    """Bring an ended shop job's work home (job 1414) in one locked_board: still in stage cloud (else SystemExit, the
    job left as it was), it becomes a spec stall on worktree and branch head, with pr and base when given, and loses its
    shop pid. No lane is written. serve.py auto_resume's spec-stall rule then resumes it."""
    with locked_board(root) as board:
        job = live(board, check_id(job_id))
        if job["stage"] != "cloud":
            raise SystemExit(f"job {job_id} is {job['stage']}, not cloud; left alone")
        job.update(stage="spec", stalled=True, reason=reason, worktree=worktree, branch=head, updatedAt=now())
        if url:
            job["pr"] = url
        if base:
            job["base"] = base
        job.pop("shop", None)


def cmd_cloud_sync(root: Path, ended=()) -> dict:
    """Move every stage-`cloud` job whose PR finished: MERGED -> done, CLOSED -> aborted and requeued, open with the
    scrum:needs-human label -> needs-human with the comment's reason and a local worktree, or, for a requeue:,
    obsolete: or looks already fixed: reason or exactly `moved to <folder> backlog` (CLOUD_MOVED, no requeue), aborted
    with the PR closed. ended (serve.py cloud_tick: ids whose shop
    session ended, job 1414) brings that job's work home (HOME): its open unlabelled PR, or with no trusted PR at all its
    pushed scrum/<id> branch (branch_pushed), gets a local worktree (cloud_worktree on the PR head, or scrum/<id>) and the
    job becomes a spec stall on it (_cloud_home), the PR left open; when the worktree add fails it goes to needs-human
    instead; a job with neither is left in cloud for cloud_tick's abort. Without ended an open unlabelled PR's job stays
    in cloud. Every gh and branch read runs before any write, so a gh failure changes nothing. A job that left stage
    cloud meanwhile is skipped, and a worktree added for it removed. A moved job with no artifacts branch yet gets the
    internal artifactsPending mark (a HOME plan's move never does, nor reads that branch); every run re-checks marked
    jobs and lists those whose branch arrived.
    Returns {"moved": [{"id","state","pr","reason","worktree","artifacts"}], "arrived": [ids], "error"}."""
    root = Path(root)
    repo = root.parent
    cloud = [j["id"] for j in read_board(root)["jobs"] if j.get("stage") == "cloud"]
    arrived = _cloud_arrivals(root, repo)
    if not cloud:
        return {"moved": [], "arrived": arrived, "error": None}
    ended = set(ended)
    try:
        prs = gh_api(repo, CLOUD_PULLS)
        if not isinstance(prs, list):
            raise GhError(f"gh api {CLOUD_PULLS} did not return a list")
        plans = [(job_id, plan) for job_id in cloud if (plan := _cloud_plan(repo, job_id, prs, job_id in ended))]
    except GhError as e:
        return {"moved": [], "arrived": arrived, "error": str(e) or type(e).__name__}
    planned = {job_id for job_id, _ in plans}
    plans += [(job_id, _cloud_home_plan(job_id, f"scrum/{job_id}")) for job_id in cloud
              if job_id in ended and job_id not in planned
              and not any(isinstance(p, dict) and _cloud_trusted(p, job_id) for p in prs) and branch_pushed(repo, job_id)]
    moved, homed = [], set()
    for job_id, (state, pairs, reason, wants_worktree, abort, head) in plans:
        worktree, url = None, next((p[3:] for p in pairs if p.startswith("pr=")), None)
        try:
            if live(read_board(root), job_id)["stage"] != "cloud":
                continue  # moved meanwhile: add no worktree for it
            if state == "HOME":
                homed.add(job_id)
                worktree = cloud_worktree(repo, job_id, head) if url else cloud_worktree(repo, job_id)
                if worktree:
                    _cloud_home(root, job_id, url, next((p[5:] for p in pairs if p.startswith("base=")), None),
                                worktree, head, reason)
                else:  # with no worktree, New job step 4 would branch afresh from BASE and lose the shop commits
                    state, reason = "NEEDS-HUMAN", pairs[-1][len("reason="):]
                    cmd_set(root, job_id, pairs, expect="cloud", internal=True)
            elif abort:
                lane = next((p[5:] for p in pairs if p.startswith("lane=")), None)
                if reason.startswith("obsolete: needs Trevor"):  # newjob 3b's manual-add, lost on the cloud's own board
                    try:
                        cmd_manual_add(root, [f"{reason[len('obsolete: '):]} (from {job_id})"])
                    except (OSError, SystemExit) as e:  # never blocks the abort
                        print(f"cloud-sync: {job_id}: manual-add failed: {e}", file=sys.stderr)
                if reason.startswith("obsolete:"):  # newjob 3b's Closed unwatched check, for Trevor's own words
                    try:
                        first = (Path(root) / "jobs" / job_id / "feature.md").read_text().splitlines()[:1]
                    except OSError:  # no readable feature.md adds nothing
                        first = []
                    if first and not re.search(r" \(from [^)]*\)\s*$", first[0]):
                        try:
                            cmd_manual_add(root, [f"Closed unwatched, check: {reason[len('obsolete:'):].strip()} (from {job_id})"])
                        except (OSError, SystemExit) as e:  # never blocks the abort
                            print(f"cloud-sync: {job_id}: manual-add failed: {e}", file=sys.stderr)
                _cloud_abort(root, job_id, url, abort[0], reason, lane)
            else:
                worktree = cloud_worktree(repo, job_id, head) if wants_worktree else None
                cmd_set(root, job_id, pairs + ([f"worktree={worktree}"] if worktree else []), expect="cloud",
                        internal=True)
                if wants_worktree:  # branch is not in FIELDS, so cmd_set cannot write it
                    with locked_board(root) as board:
                        job = live(board, job_id)
                        if job["branch"] != head:
                            job["branch"] = head
        except SystemExit as e:  # aborted or moved meanwhile, or the done guard refused: it stays where it is
            print(f"cloud-sync: {job_id}: {e}", file=sys.stderr)
            if worktree:  # added for a move that did not happen: leave no orphan behind
                cloud_worktree_remove(repo, worktree)
            continue
        if abort and abort[1]:
            try:  # best effort: the job is already aborted, so a later poll skips it either way
                gh_api(repo, f"repos/{{owner}}/{{repo}}/pulls/{abort[1]}", "-X", "PATCH", "-f", "state=closed")
            except GhError as e:
                print(f"cloud-sync: {job_id}: PR close failed: {e}", file=sys.stderr)
        moved.append({"id": job_id, "state": state, "pr": url, "reason": reason, "worktree": worktree,
                      "artifacts": job_id not in homed and artifacts_pushed(repo, job_id)})
    pending = {m["id"] for m in moved if not m["artifacts"] and m["id"] not in homed}  # HOME: rebuilt locally
    if pending:  # the session pushes scrum-artifacts/<id> last, so a poll can land between its label and that push
        with locked_board(root) as board:
            for job in board["jobs"]:
                if job["id"] in pending:
                    job["artifactsPending"] = now()  # internal, not in FIELDS, like pid
    return {"moved": moved, "arrived": arrived, "error": None}


# --- `waiting`: Claude Code hooks in the orchestrator's terminal mark the job paused on Trevor, and clear it ---
def caller_tty():
    """The calling terminal's tty: the first ancestor (at most 10 up) with a ttysN, since Claude Code may start hooks
    under a detached parent whose tty is ??. The same tty "Record your terminal" stores. "??" when none has one."""
    pid = os.getppid()
    for _ in range(10):
        out = subprocess.run(["ps", "-o", "ppid=,tty=", "-p", str(pid)], capture_output=True, text=True,
                             timeout=2).stdout.split()
        if len(out) != 2:
            break
        if SHAPES["tty"].fullmatch(out[1]):
            return out[1]
        if not out[0].isdigit() or int(out[0]) <= 1:
            break
        pid = int(out[0])
    return "??"


def caller_claude_pid():
    """The pid of the nearest claude ancestor (at most 10 up), so `set tty=` and the hook know which session they are.
    None when no ancestor is claude or ps fails; never raises."""
    pid = os.getppid()
    try:
        for _ in range(10):
            out = subprocess.run(["ps", "-o", "ppid=,command=", "-p", str(pid)], capture_output=True, text=True,
                                 timeout=2).stdout.strip().split(None, 1)
            if len(out) != 2:
                return None
            if _is_claude(out[1]):
                return pid
            if not out[0].isdigit() or int(out[0]) <= 1:
                return None
            pid = int(out[0])
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def ancestor_pids() -> set:
    """Every ancestor of this process, from one ps scan (empty when ps fails): a chat's own `zsh -c` line holds the job id."""
    try: rows = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError): return set()
    parent, found, pid = dict(zip(rows[::2], rows[1::2])), [], str(os.getppid())
    while pid.isdigit() and int(pid) > 1 and int(pid) not in found:
        found.append(int(pid))
        pid = parent.get(pid, "")
    return set(found)


def caller_headless() -> bool:
    """True when the nearest claude ancestor runs with `-p`/`--print` (unattended), and also when none is found or ps
    fails (fail closed: an unattended session can't approve a `.claude/` edit)."""
    pid = caller_claude_pid()
    if pid is None:
        return True
    try:
        toks = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                              timeout=2).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return True
    return not toks or "-p" in toks or "--print" in toks


def cmd_claude_paths(root, job_id: str) -> dict:
    """{"paths", "headless"}: spec.md's `## Likely files` backticked paths under `.claude/` (not `.claude/worktrees/` or `.claude/skills/`),
    in file order, [] for a missing spec or section; headless from caller_headless (lanes/newjob.md step 3c)."""
    try:
        text = (Path(root) / "jobs" / check_id(job_id) / "spec.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    return {"paths": [p for p in likely_backticked(text) if is_claude_path(p)], "headless": caller_headless()}


def likely_backticked(spec: str) -> list[str]:
    """spec.md's `## Likely files` backticked paths, deduplicated in file order."""
    return list(dict.fromkeys(re.findall(r"`([^`\s]+)`", md_section(spec, "Likely files") or "")))


def is_claude_path(path: str) -> bool:
    # .claude/skills/** is allowed in settings.json, so a headless builder edits it like any file.
    return path.startswith(".claude/") and not path.startswith((".claude/worktrees/", ".claude/skills/"))


TERMINAL_BATCH_TITLE = "Terminal batch: project .claude edits"
# The old lanes/newjob.md 3c park reason; cmd_claude_migrate moves such jobs into the batch once.
LEGACY_CLAUDE_PARK = "blocked: this job changes files in the project .claude folder"
# Never starts with a RESUMABLE prefix: a parked batch is run in a Terminal window, never resumed headless.
TERMINAL_BATCH_QUESTION = ("project .claude edits: Claude Code refuses those edits in a session that runs on its own; "
                           "approve each in a Terminal window.")
TERMINAL_BATCH_INTRO = ("Lane: lilguy\nComplex: no\n\n# Terminal batch: project .claude edits\n\n"
                        "Headless jobs moved these project `.claude/` edits here, because Claude Code refuses them in a "
                        "session that runs on its own. Make every edit below in this repo as one change.\n")


def claude_split(root, job) -> tuple[str, list[str], bool]:
    """(spec text, its .claude/ Likely files, only): only is True when every backticked Likely file is one. Raises
    SystemExit, before any write, for the batch job itself or a spec naming no .claude/ path."""
    if job.get("title") == TERMINAL_BATCH_TITLE:
        raise SystemExit(f"job {job['id']} is the Terminal batch; run it in a Terminal window")
    try:
        spec = (Path(root) / "jobs" / job["id"] / "spec.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        spec = ""
    likely = likely_backticked(spec)
    paths = [p for p in likely if is_claude_path(p)]
    if not paths:
        raise SystemExit(f"job {job['id']} names no project .claude/ path")
    return spec, paths, len(paths) == len(likely)


def open_batch(board):
    return next((j for j in board["jobs"] if j["title"] == TERMINAL_BATCH_TITLE and j["stage"] == "needs-human"), None)


def redirect_dependents(board, old_id: str, new_id: str) -> list[str]:
    """Replace old_id with new_id (same position, duplicates dropped) in the depends_on of every job not done or aborted;
    returns the ids changed. Caller holds the lock."""
    changed = []
    for j in board["jobs"]:
        deps = j.get("depends_on") or []
        if j["id"] == old_id or old_id not in deps or j["stage"] in ("done", "aborted"):
            continue
        j["depends_on"] = list(dict.fromkeys(new_id if d == old_id else d for d in deps))
        j["updatedAt"] = now()
        changed.append(j["id"])
    return changed


def claude_batch(root, board, job) -> tuple[dict, bool]:
    """cmd_claude_batch's body; caller holds the lock and plays the needs-human sound when the bool (a batch was
    created) is True."""
    spec, paths, only = claude_split(root, job)
    job_id = job["id"]
    moved = md_section(spec, "Moved to Terminal batch")
    if moved is not None:
        m = re.search(r"`(\d{3,}-[a-z0-9-]+)`", moved)
        if only and m:
            redirect_dependents(board, job_id, m[1])
        return {"batch": m and m[1], "only": only, "created": False}, False
    batch, created = open_batch(board), False
    if batch is None:
        bid = add_job(root, board, TERMINAL_BATCH_TITLE)
        (Path(root) / "jobs" / bid / "feature.md").write_text(TERMINAL_BATCH_INTRO)
        batch = find(board, bid)
        batch["base"] = job.get("base")
        park(root, batch, TERMINAL_BATCH_QUESTION,
             [{"key": "a", "label": "Run it in a Terminal window", "command": f"lilguy {bid}"},
              {"key": "b", "label": "Remove this job", "command": f"abort {bid} --cascade"}],
             "BUILDER_BLOCKED", {"key": "a", "why": "Only a Terminal window can approve project .claude edits."},
             auto=True)  # serve.py terminal_batch_tick opens it
        created = True
    bid = batch["id"]
    feature_path = Path(root) / "jobs" / bid / "feature.md"
    feature = feature_path.read_text(encoding="utf-8", errors="replace") if feature_path.is_file() else ""
    if not re.search(rf"^## From {re.escape(job_id)}:", feature, re.M):
        body = (md_section(spec, "Claude edits") or "").strip()
        if not body:
            criteria = [l.strip() for l in (md_section(spec, "Acceptance criteria") or "").splitlines()
                        if CLAUDE_DIR_RE.search(l)]
            body = "\n".join([f"- `{p}`" for p in paths] + (["", "Criteria that name them:", *criteria] if criteria else [])
                             + ["", f"Read `{(Path(root) / 'jobs' / job_id / 'spec.md').resolve()}` for the full requirements."])
        with open(feature_path, "a", encoding="utf-8") as f:
            f.write(f"\n## From {job_id}: {job.get('title', job_id)}\n{body}\n")
    marker = (f"\n## Moved to Terminal batch\nBatch job: `{bid}`. Paths: {', '.join(f'`{p}`' for p in paths)}.\n"
              "This job's diff makes none of those edits. A criterion only they meet is met by the batch job.\n")
    with open(Path(root) / "jobs" / job_id / "spec.md", "a", encoding="utf-8") as f:
        f.write(marker if spec.endswith("\n") or not spec else "\n" + marker)
    if only:
        redirect_dependents(board, job_id, bid)
    return {"batch": bid, "only": only, "created": created}, created


def cmd_claude_batch(root, job_id: str) -> dict:
    """{"batch", "only", "created"}: move the job's project .claude/ edits into the open Terminal batch job (the first
    TERMINAL_BATCH_TITLE job at needs-human; else a new one, parked BUILDER_BLOCKED), and mark its spec.md
    `## Moved to Terminal batch`. only: every Likely file is a .claude/ path. A re-run writes nothing (lanes/newjob.md 3c)."""
    with locked_board(root) as board:
        out, created = claude_batch(root, board, live(board, check_id(job_id)))
    if created:
        play(sound("needs-human"))
    return out


def legacy_claude_parks(board):
    return [j for j in board["jobs"] if j["stage"] == "needs-human" and j.get("title") != TERMINAL_BATCH_TITLE
            and (j.get("reason") or "").startswith(LEGACY_CLAUDE_PARK)]


def cmd_claude_migrate(root, dry_run=False) -> list[dict]:
    """[{"id", "batch", "only"}]: the one-time move of jobs parked on the old lanes/newjob.md 3c question
    (LEGACY_CLAUDE_PARK) into the Terminal batch. An `only` job is aborted `moved to Terminal batch <batch>`; any
    other is left stalled in spec, so resume re-enters New job step 3. A job claude_split refuses stays parked.
    dry_run writes nothing (batch: the open batch's id, None when one would be created). Nothing to move writes no
    board.json (serve.py's watchdog runs this every tick)."""
    snapshot = read_board(root)  # a read first: most ticks find nothing and write nothing
    if not legacy_claude_parks(snapshot):
        return []
    if dry_run:
        batch, out = open_batch(snapshot), []
        for job in legacy_claude_parks(snapshot):
            try:
                out.append({"id": job["id"], "batch": batch and batch["id"], "only": claude_split(root, job)[2]})
            except SystemExit:
                continue
        return out
    out, sound_due = [], False
    with locked_board(root) as board:
        for job in legacy_claude_parks(board):  # re-read under the lock
            try:
                res, created = claude_batch(root, board, job)
            except SystemExit:
                continue  # the checks run before any write, so this job is left exactly as it was
            sound_due = sound_due or created
            note = f"moved to Terminal batch {res['batch']}"
            if res["only"]:
                abort_job(root, job, False, note)
            else:
                job.update(stage="spec", stalled=True, reason=f"{STALL}.claude edits {note}", updatedAt=now())
            out.append({"id": job["id"], "batch": res["batch"], "only": res["only"]})
    if sound_due:
        play(sound("needs-human"))
    return out


ACTION_NEEDED_RE = re.compile(r"[\s*_>•-]*action needed[\s*_:–—-]*(.*)", re.I)


def waiting_text(event):
    """The `waiting` value a hook event sets, None for an event that clears it, KEEP for one that changes nothing."""
    name, tool, inp = event.get("hook_event_name"), event.get("tool_name"), event.get("tool_input") or {}
    if name == "PermissionRequest":
        cmd = inp.get("command") if tool == "Bash" else None
        return f"permission: {tool}" + (f": {str(cmd)[:80]}" if cmd else "")
    if name == "PreToolUse" and tool == "AskUserQuestion":
        try:
            return f"question: {inp['questions'][0]['question']}"
        except (KeyError, IndexError, TypeError):
            return "question"
    if name == "Stop":
        for line in str(event.get("last_assistant_message") or "").splitlines():
            m = ACTION_NEEDED_RE.match(line)
            if m:  # only a session that asks Trevor something waits; a plain status report clears it
                rest = m.group(1).rstrip("*_ \t")[:160]
                return f"reply needed: {rest}" if rest else "reply needed"
        return None
    if name in ("UserPromptSubmit", "PostToolUse"):
        return None
    return KEEP


class _Gone(Exception):
    """The matched job changed under the lock; leave the board unwritten."""


def cmd_hook(event, tty, pid=None):
    """Set or clear `waiting` on the active job recorded on this claude pid, or on this tty when the job has no pid
    (newest updatedAt across every registered repo). Writes nothing when no job matches or a clear finds it already clear, so PostToolUse stays cheap."""
    if event.get("hook_event_name") == "PreToolUse" and event.get("tool_name") == "AskUserQuestion" and notifier_disabled():
        play(sound("question"))  # the notifier skips silenced (scrum-launched) sessions, so the question sound comes from here
    text = waiting_text(event)
    if text is KEEP or not SHAPES["tty"].fullmatch(tty or ""):
        return
    text = clean(text, 200) if text else None
    # A job with a recorded claude pid is this session's only by pid: macOS reuses ttys, so a later chat on the same
    # tty must not write into a dead job. A job without one (recorded before pids were) still matches by tty.
    mine = lambda job: job.get("pid") == pid if job.get("pid") else job.get("tty") == tty
    match = None
    for repo in read_registry():
        root = Path(repo) / "scrum"
        try:
            jobs = json.loads((root / "board.json").read_text())["jobs"]
            for job in jobs:
                if mine(job) and job.get("stage") in ACTIVE and (
                        match is None or str(job.get("updatedAt")) > str(match[1].get("updatedAt"))):
                    match = (root, job)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    if match is None or (text is None and match[1].get("waiting") is None):
        return
    try:
        with locked_board(match[0]) as board:
            job = next((j for j in board["jobs"] if j.get("id") == match[1].get("id")), None)
            if not job or not mine(job) or job.get("stage") not in ACTIVE or (text is None and job.get("waiting") is None):
                raise _Gone
            job.update(waiting=text, updatedAt=now())
    except _Gone:
        pass


# --- watchdog: a job whose orchestrator session died stays in its stage forever; flag it stalled in that stage ---
WATCHED = ("spec", "build", "check", "review", "approve", "merging", "deploying")
STALL_MINUTES = 30  # fixed, the same as the dashboard's STALE_MS; not a setting (UB-24)
IDLE_HOURS = 2  # a live session with no board or job-dir change this long is flagged too; fixed, not a setting
LIVE_IDLE = "(session alive but idle)"  # cmd_watchdog's live-idle stall reason ends on it; resume_gate reads it
STALLED = "stalled in "  # reason prefix: serve.py's resume, the dashboard's Resume button and SKILL.md read it
STALL = "stalled: "  # new-shape reason prefix: the job keeps its WATCHED stage and has board `stalled` true
AGENT_TYPES_RE = re.compile(r"not loaded as agent types|agent types (?:are )?not loaded|^agent missing:|^waiting on the (?:E2E|Check) queue", re.I)
QUEUE_ASK_RE = re.compile(r"^waiting on the (E2E|Check|Build) queue", re.I)  # cmd_ask holds a check job on it as waiting, not stalled
E2E_QUEUE_WAIT, CHECK_QUEUE_WAIT = "waiting: E2E queue", "waiting: Check queue"  # serve.py auto_resume starts it once the lock frees
BUILD_QUEUE_WAIT = "waiting: Build queue"  # a second Build 124 (job 1250): auto_resume starts it once build.lock frees
CI_BILLING_RE = re.compile(r"failed account payments|spending limit|CI refused: GitHub billing", re.I)
LOAD_BLOCK_RE = re.compile(r"CPU load|machine load|overload|load average|\bload \d|swap|out of memory|low memory|memory pressure|free RAM", re.I)
LOAD_BLOCK_WAIT = "failed under machine load; retrying on a quiet machine"  # serve.py auto_resume re-runs the stage
LOAD_WAITS_MAX = 3  # load waits per job; the next load ask waits for a solo run, the one after parks at needs-human
LOAD_SOLO_WAIT = "waiting for a solo run: failed under machine load 3 times"  # serve.py auto_resume resumes when live_sessions() == 0
SOLO_RUN_MAX_S = 3 * 3600  # a solo run (soloRun/soloAt, mark_solo_run) holds the Mac at most this long: solo_hold
LOAD_ASK_TITLES = ("CHECKS_FAILING", "BUILDER_BLOCKED", "REVIEW_ESCALATED")
QUIET_PREFIX = "waiting on a quiet machine"  # a lane asks it on purpose


def _load_ask(question, title) -> bool:
    """True for a stop that is machine load, not the job's code: the explicit QUIET_PREFIX, `debug: blocked` or a
    LOAD_ASK_TITLES stop whose text matches LOAD_BLOCK_RE."""
    q = question.lower()
    return q.startswith(QUIET_PREFIX) or bool(LOAD_BLOCK_RE.search(question) and (q.startswith("debug: blocked") or title in LOAD_ASK_TITLES))


QUIET_CHECK_WAIT = f"{QUIET_PREFIX}: the checks ran at load5"  # serve.py auto_resume re-runs them at cpu_load_pct <= 100
HEAVY_CHECK_STEMS = ("check", "e2e")  # heavy-steps.log stems of a Test or Typecheck (check.lock) and an E2E (e2e.lock) run


def checks_load(job) -> str | None:
    """`<load5> on <cores> cores` when the last heavy-steps.log line (buildlock.log_step; SCRUM_HEAVY_STEPS_LOG
    overrides the path) of a HEAVY_CHECK_STEMS run in the job's worktree shows load5 over cores, else None (job 1536).
    A job with no worktree, an unreadable log or no such line gives None."""
    if not job.get("worktree"):
        return None
    name = Path(job["worktree"]).name
    log = Path(os.environ.get("SCRUM_HEAVY_STEPS_LOG") or Path.home() / ".claude" / "trevskills-scrum" / "heavy-steps.log")
    try:
        lines = log.read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        parts = line.split()
        if len(parts) >= 3 and parts[1] in HEAVY_CHECK_STEMS and parts[2] == name:
            m = re.search(r"\bload5=(\d+(?:\.\d+)?) cores=(\d+)\b", line)
            return f"{m[1]} on {m[2]} cores" if m and int(m[2]) and float(m[1]) > int(m[2]) else None
    return None
CI_BILLING_WAIT = "waiting on GitHub billing to run CI"  # serve.py auto_resume retries it after 60 s, then when the banner clears
# Every needs-human reason prefix whose card offers Resume (serve.py's resume action, the dashboard, SKILL.md `resume`).
RESUMABLE = (STALLED, STALL, "bigboy off track", "bigboy review: main not updated", BLOCKED, "Base branch ")
# Pause keeps the job in its stage with board `paused` true and the watchdog's stalled reason, so Play is the
# existing resume path.
PAUSABLE = ("spec", "build", "check", "review", "approve", "merging", "deploying", "plan", "running")
PAUSED = "paused by Trevor"
PAUSED_RE = re.compile(rf"^{STALLED}(\w+): {PAUSED}")
ORPHANED = "requeue: orphaned claim, the session died before writing feature.md"


def stalled(job: dict) -> bool:
    """Stalled and not paused, in either shape: legacy (needs-human, reason `stalled in <stage>: `) or new (its own
    WATCHED stage with board `stalled` true). A leftover `stalled` on any other stage is ignored."""
    if job.get("paused"):
        return False
    if job.get("stalled"):
        return job.get("stage") in WATCHED
    return job.get("stage") == "needs-human" and str(job.get("reason") or "").startswith(STALLED)


def queue_waiting(job: dict) -> bool:
    """A check job cmd_ask holds on the E2E, Check or Build queue (reason E2E_QUEUE_WAIT, CHECK_QUEUE_WAIT or
    BUILD_QUEUE_WAIT): not stalled, not paused; serve.py auto_resume starts it as soon as that lock is free, spending no try."""
    return job.get("stage") == "check" and not job.get("paused") and not job.get("stalled") \
        and str(job.get("reason") or "").startswith((E2E_QUEUE_WAIT, CHECK_QUEUE_WAIT, BUILD_QUEUE_WAIT))


FINISH_FIRST = "finishing work in flight first"  # finish_first's reason prefix; serve.py held_gate's finish_first token


def resume_waits(job: dict, by_id: dict) -> bool:
    """A stalled job serve.py auto_resume restarts once the machine lets it: stalled in its own WATCHED stage (never
    needs-human, never paused: job 751), not lilguy-in-checkout, not parked for cool down or GitHub billing, with no
    parent or a running, unpaused Run-all/BigBoy parent."""
    reason = str(job.get("reason") or "")
    if not stalled(job) or job.get("stage") == "needs-human" or lilguy_in_checkout(job) or no_pr_job(job) \
            or reason.startswith((STALL + COOLDOWN_PARK, STALL + CI_BILLING_WAIT)):
        return False
    p = by_id.get(job.get("parent")) if job.get("parent") else None
    return not job.get("parent") or bool(p) and p.get("stage") == "running" and not p.get("paused") \
        and p.get("lane") in ("runall", "bigboy")


def mark_solo_run(root, job_id) -> None:
    """Reserve the Mac for job_id's solo run (job 1361): soloRun = its current stage, soloAt = now. serve.py auto_resume
    calls it just before it resumes a LOAD_SOLO_WAIT job; solo_hold reads it, cmd_set drops it on a stage change."""
    with locked_board(root) as b:
        job = find(b, job_id)
        job["soloRun"], job["soloAt"] = job.get("stage"), now()


def solo_hold(root=None, jobs=None, waiting=True) -> str | None:
    """`<project>/<id> runs alone` for the first solo holder on root's board (`jobs` when given) or any registered
    project's, else, only when `waiting`, `<project>/<id> waits for a solo run` for the first solo waiter, else None
    (job 1361). A holder has soloRun equal to its stage (not needs-human, done or aborted), is not paused, has a soloAt
    at most SOLO_RUN_MAX_S old, and is not stalled, or still stalled on its LOAD_SOLO_WAIT reason (resumed, its session
    has not cleared the stall yet). A waiter is stalled on LOAD_SOLO_WAIT with no soloRun and resume_waits."""
    here = Path(root).resolve() if root else None
    first_wait = None
    for scrum in dict.fromkeys(([here] if here else []) + [(p / "scrum").resolve() for p in projects().values()]):
        try:
            js = jobs if jobs is not None and scrum == here else read_board(scrum)["jobs"]
        except SystemExit:
            continue
        name, by_id = scrum.parent.name, {j.get("id"): j for j in js}
        for j in js:
            solo = str(j.get("reason") or "").startswith(STALL + LOAD_SOLO_WAIT)
            at = _epoch(j.get("soloAt"))
            if j.get("soloRun") and j.get("soloRun") == j.get("stage") \
                    and j.get("stage") not in ("needs-human", "done", "aborted") and not j.get("paused") \
                    and at is not None and time.time() - at <= SOLO_RUN_MAX_S and (not stalled(j) or solo):
                return f"{name}/{j.get('id')} runs alone"
            if waiting and first_wait is None and solo and not j.get("soloRun") and stalled(j) and resume_waits(j, by_id):
                first_wait = f"{name}/{j.get('id')} waits for a solo run"
    return first_wait


def hand_queued(root, job: dict) -> bool:
    """A start Trevor or a chat queued by hand (job 1454): a parentless, unpaused job with play_queued and a `start`
    queued_launch still in its stage, not tagged Runs on shop (stored_runs_on), that a dashboard click queued
    (play_queued_manual) or a hand claim made (started_by "hand": cmd_new, `next <index>`). serve.py hand_queue_tick
    launches these first, oldest first across projects; finish_first holds every new claim while one waits."""
    launch = job.get("queued_launch") or {}
    return not job.get("parent") and bool(job.get("play_queued")) and launch.get("action") == "start" \
        and launch.get("stage") == job.get("stage") and not job.get("paused") \
        and bool(job.get("play_queued_manual") or job.get("started_by") == "hand") \
        and stored_runs_on(root, job) != "shop"


def finish_first(root=None, jobs=None) -> str | None:
    """Why no automatic new claim (backlog next, a Run-all or BigBoy child, auto-continue, wake) may start in any
    project now, or None (job 971: finish the task at hand first). Read across root's board (`jobs` when given: the
    caller's locked copy) and every registered project's: a job held on the E2E, Check or Build queue (queue_waiting, or
    stalled on E2E_WAIT_REASON or CHECK_WAIT_REASON), else a hand-queued start still waiting (hand_queued, job 1454),
    else a stalled job auto_resume restarts (resume_waits) that waits
    on the machine gate: spawn's gate queued its resume (queued_launch), or resume_gate refuses it. Paused and
    needs-human jobs never hold it (job 751); Trevor's clicks (Play, Resume, Run now) never ask it. Before those checks, a
    solo run in flight or a job waiting for one (solo_hold, job 1361) holds it too."""
    if solo := solo_hold(root, jobs):
        return f"{FINISH_FIRST}: {solo}"
    here = Path(root).resolve() if root else None
    waiting, hand = [], None
    for scrum in dict.fromkeys(([here] if here else []) + [(p / "scrum").resolve() for p in projects().values()]):
        try:
            js = jobs if jobs is not None and scrum == here else read_board(scrum)["jobs"]
        except SystemExit:
            continue
        name, by_id = scrum.parent.name, {j.get("id"): j for j in js}
        for j in js:
            reason = str(j.get("reason") or "")
            if queue_waiting(j) or stalled(j) and j.get("stage") != "needs-human" \
                    and reason.startswith((STALL + E2E_WAIT_REASON, STALL + CHECK_WAIT_REASON)):
                queue = "E2E" if reason.startswith((E2E_QUEUE_WAIT, STALL + E2E_WAIT_REASON)) \
                    else "Build" if reason.startswith(BUILD_QUEUE_WAIT) else "Check"
                return f"{FINISH_FIRST}: {name}/{j.get('id')} waits on the {queue} queue"
            if hand is None and hand_queued(scrum, j):
                hand = f"{FINISH_FIRST}: {name}/{j.get('id')} hand start is queued"
            if resume_waits(j, by_id):
                waiting.append((scrum, name, j))
    if hand:  # after every board's queue waits, before the resume waits
        return hand
    for scrum, name, j in waiting:  # the machine readings only when a stalled job could be waiting on them
        why = "its launch is queued" if j.get("queued_launch") else resume_gate(scrum, j)
        if why:
            return f"{FINISH_FIRST}: {name}/{j.get('id')} waits to resume ({why})"
    return None


def resume_gate(root, job: dict, manual=False) -> str | None:
    """machine_ok for resuming `job`. A stalled job whose own session is still alive and idle (cmd_watchdog's LIVE_IDLE
    stall, and session_alive_fn still sees it) skips the CPU load gate: that session is already counted in the load."""
    why = machine_ok(root, manual=manual)
    if why and why.startswith("CPU load") and stalled(job) and LIVE_IDLE in str(job.get("reason") or "") \
            and session_alive_fn()(job):
        why = machine_ok(root, manual=manual, own_load=True)
    return why


def stall_stage(job: dict) -> str | None:
    """The stage a stalled job stalled in, or None when `stalled(job)` is False."""
    if not stalled(job):
        return None
    if job.get("stalled"):
        return job["stage"]
    m = re.match(rf"{STALLED}(\w+):", job.get("reason") or "")
    return m and m.group(1)


LEGACY_STALL_RE = re.compile(rf"^{STALLED}(\w+): (.*)$", re.S)

# --- cool down drains fast: lock waiters are served by progress, and far-off jobs park at their next checkpoint ---
COOLDOWN_PARK = "parked for cool down; resumes when cool down ends"  # serve.py auto_resume resumes it after cool down
PARK_STAGES = ("spec", "build")  # a job that has not reached its first Check gate (board round 0)


def lock_rank(cwd) -> int:
    """buildlock.py's place in the cool-down queue for a waiter in cwd: 3 approved or merging (stage approve, merging,
    deploying, or an APPROVE round-*/decision.md: the Merge Conflicts re-check), 2 back from a review round (stage
    review or board round >= 2), 1 a first check, 0 anything else: no matching job (serve.py's full E2E run on main)
    or any read error. The job is the one not done or aborted, on any registered board, whose worktree holds cwd."""
    try:
        cwd = os.path.realpath(cwd)
        for repo in projects().values():
            try:
                jobs = read_board(repo / "scrum")["jobs"]
            except (OSError, SystemExit, KeyError, TypeError):
                continue  # one broken board never ranks another project's waiter
            for job in jobs:
                wt = job.get("worktree")
                if job.get("stage") in ("done", "aborted") or not wt:
                    continue
                wt = os.path.realpath(wt)
                if cwd != wt and not cwd.startswith(wt + os.sep):
                    continue
                stage = job.get("stage")
                folder = repo / "scrum" / "jobs" / check_id(job["id"])
                if stage in ("approve", "merging", "deploying") or any(
                        first_word(d, ("APPROVE", "REWORK", "ESCALATE")) == "APPROVE"
                        for d in folder.glob("round-*/decision.md")):
                    return 3
                if stage == "review" or int(job.get("round") or 0) >= 2:
                    return 2
                return 1 if stage == "check" else 0
    except (Exception, SystemExit):
        pass
    return 0


def cmd_cooldown_park(root, job_id) -> dict:
    """cooldown-park: Never parks and writes nothing (job 1346): cool down holds only new claims, so a started job
    carries on. Kept for sessions running an older lane copy that still calls it. Returns {"parked": False}."""
    return {"parked": False}


def migrate_paused(board: dict) -> list[str]:
    """Rewrite each legacy needs-human job in place: a PAUSED_RE reason to its stage plus `paused`, keeping the
    reason; any other `stalled in <WATCHED stage>: <rest>` (not paused) to that stage plus `stalled`, reason
    `stalled: <rest>`, with no question. A non-WATCHED stage stays legacy (stalled() reads `stalled` only in WATCHED).
    Returns the migrated ids; a second run finds none."""
    out = []
    for job in board["jobs"]:
        if job.get("stage") != "needs-human":
            continue
        reason = job.get("reason") or ""
        if m := PAUSED_RE.match(reason):
            job.update(stage=m.group(1), paused=True)
            out.append(job["id"])
        elif (m := LEGACY_STALL_RE.match(reason)) and m.group(1) in WATCHED and not job.get("paused"):
            for k in ("question", "options", "recommend", "stopTitle"):
                job.pop(k, None)
            job.update(stage=m.group(1), stalled=True, reason=f"{STALL}{m.group(2)}")
            out.append(job["id"])
    return out


def clear_heavy_wait(board: dict) -> list[str]:
    """Drop the `reason` of each job still carrying the removed usage hold's text; returns the cleaned ids."""
    out = []
    for job in board["jobs"]:
        if "heavy jobs" + " wait" in (job.get("reason") or ""):
            del job["reason"]
            out.append(job["id"])
    return out


def cmd_migrate_paused(root) -> list[str]:
    """migrate_paused on board.json, written only when something migrated or a stale heavy-wait reason needs
    cleaning (locked_board does both on every write). Returns the migrated ids only."""
    b = read_board(root)  # a read first: most ticks find nothing and write nothing
    ids = migrate_paused(b)
    if ids or clear_heavy_wait(b):
        with locked_board(root):
            pass
    return ids


def cmd_pause(root, job_id):
    """Pause a job in progress (and its children in progress): it keeps its stage, gets `paused` and a stalled reason
    naming its stage. Every other field is kept, so resume picks up where it stopped. Returns the paused ids; plays no
    sound."""
    with locked_board(root) as board:
        job = find(board, check_id(job_id))
        if job["stage"] not in PAUSABLE:
            raise SystemExit(f"job {job_id} is {job['stage']}; only a job in progress can be paused")
        if job.get("paused"):
            raise SystemExit(f"job {job_id} is already paused; click Play to restart it")
        by_id = {j["id"]: j for j in board["jobs"]}
        hit = [job] + [by_id[k] for k in job.get("children") or []
                       if k in by_id and by_id[k]["stage"] in PAUSABLE and not by_id[k].get("paused")]
        for j in hit:
            j.update(paused=True, reason=f"{STALLED}{j['stage']}: {PAUSED}. Fix: click Play.", updatedAt=now())
            j.pop("limitResetAt", None)
            j.pop("play_queued", None)  # a pause cancels a queued Play
            j.pop("play_queued_manual", None)
            j.pop("queued_launch", None)
            j.pop("ram_hold", None)
            j.pop("machine_hold", None)
            if j.get("autoPlayed"):
                j["holdPause"] = True  # re-paused after an auto-play: deliberate, so the watchdog leaves it paused
        return [j["id"] for j in hit]


def _is_claude(command):
    """True when claude is the program: argv0 named `claude`, a bare `claude` token, or the claude-code package.
    A path that merely passes through `.claude/` (a worktree's dev server) does not count, nor does a checkout slug
    holding `claude-code`."""
    toks = command.split()
    return bool(toks) and (os.path.basename(toks[0]) == "claude" or "claude" in toks
                                  or "claude-code" in re.sub(r"/\.claude/worktrees/[^/\s]+", "", command))


def session_alive_fn(skip: int | set | None = None):
    """One `ps` scan; a job is alive when a claude process line has its id, or when its recorded claude pid is live
    (a job with no pid: when a claude process runs on its recorded tty). When ps can't be read, every job counts as
    alive, so the watchdog never flags on a guess. `skip` (spawn's caller, job 1275) is a pid or set of pids whose lines
    are left out: the calling session never counts as the job's live session (job 1329: nor its Bash `zsh -c` line)."""
    try:
        r = subprocess.run(["ps", "-axo", "pid=,tty=,command="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return lambda job: True
    out = r.stdout or ""
    if r.returncode != 0 or not out.strip():  # denied (a sandboxed call) or empty: unknown, never "all dead"
        return lambda job: True
    skipped = {str(p) for p in ({skip} if isinstance(skip, int) else skip or ())}
    lines = [l.strip() for l in out.splitlines() if _is_claude((l.split(None, 2) + ["", ""])[2]) and l.split()[0] not in skipped]
    pids = {int(l.split()[0]) for l in lines if l.split()[0].isdigit()}
    ttys = {l.split()[1] for l in lines if len(l.split()) > 1}
    # ponytail: a reused tty (pid-less jobs only), a recycled claude pid, or an id inside another command reads as
    # alive; an accepted miss, never a false flag
    return lambda job: any(job["id"] in l for l in lines) or (
        job["pid"] in pids if job.get("pid") else (job.get("tty") or "") in ttys)


def stalled_since(job, cutoff):
    try:
        return datetime.fromisoformat(job["updatedAt"]) < cutoff
    except (KeyError, TypeError, ValueError):
        return False


def job_dir_idle(root, job_id, cutoff):
    """True when no file under root/jobs/<id>/ (any depth) has an mtime at or after the epoch-seconds cutoff."""
    for d, _, names in os.walk(Path(root) / "jobs" / job_id):
        for n in names:
            try:
                if os.stat(os.path.join(d, n)).st_mtime >= cutoff:
                    return False
            except OSError:
                pass
    return True


def last_log_line(root, runlog):
    """The last non-empty line of the last 8 KB of root/<runlog>, cut to 300 characters; None when there is no runlog,
    the file can't be read or holds no text."""
    if not runlog:
        return None
    try:
        with (Path(root) / runlog).open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(f.tell() - 8192, 0))
            tail = f.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    return next((l.strip()[:300] for l in reversed(tail.splitlines()) if l.strip()), None)


DEAD_HOURS = 24  # job 1498: no board update this long, no live session and not held by anything: dead, whatever skipped it


def dead_net_job(job):
    """job 1498 (a): a WATCHED job the watchdog's skip reasons passed over that is nobody's to wait for: not paused or
    stalled, no wait on Trevor, no queue wait (it starts itself), no shop or cloud worker holding it, no future
    limitResetAt and no play queue holding it. Its age is the caller's test."""
    return job.get("stage") in WATCHED and not job.get("paused") and not job.get("stalled") and not job.get("waiting") \
        and not queue_waiting(job) and not (job.get("shop") or job.get("worker") or job.get("cloud")) \
        and not job.get("play_queued") and not job.get("queued_launch") \
        and not (is_num(job.get("limitResetAt")) and job["limitResetAt"] > time.time())


def dead_wait_cause(job, by_id):
    """job 1498 (b): why a `waiting` job can never wake (its parent is done, aborted or missing; a depends_on id is
    aborted or missing), else None. A live or unmerged sibling is no cause."""
    parent = job.get("parent")
    if parent and (by_id.get(parent) or {}).get("stage") in (None, "done", "aborted"):
        return f"its parent {parent} is {(by_id.get(parent) or {}).get('stage') or 'gone'}"
    gone = next((d for d in job.get("depends_on") or () if (by_id.get(d) or {}).get("stage") in (None, "aborted")), None)
    return f"{gone} was aborted or removed" if gone else None


QUEUE_WAIT_HOURS = 24  # job 1519: a queue wait this old with no live session asks Trevor; its lock may be held by a dead process
QUEUE_NAMES = {E2E_QUEUE_WAIT: "E2E", CHECK_QUEUE_WAIT: "Check", BUILD_QUEUE_WAIT: "Build"}


def cmd_watchdog(root, alive=None, exits=None, hold=None):
    """Flag every job stuck in a WATCHED stage with no board update for STALL_MINUTES and no live session (for a parent,
    a live child session or its live chain lock counts as its own): it keeps
    its stage with `stalled` true and a STALL reason, and plays no sound. Its stall line carries "exit" (exits, serve.py's
    {run log: exit code}, looked up by the job's runlog) and "last_log" (last_log_line), each None when unknown.
    Every stall line is "auto" when auto_resume will retry it (no parent, or a running unpaused runall/bigboy parent).
    A live-idle stall for which `hold(job)` (serve.py stall_hold) names a gate token (e2e_lock, cpu_load(<pct>%)) is
    logged "auto" with that "hold": the gate, not the session, held it, so process-health counts no stop.
    A job whose launch serve.py queued (`play_queued`) is waiting on its own gate and is never flagged.
    A stuck spec job with no feature.md is an orphaned claim instead: aborted and requeued, not flagged.
    A queue wait (queue_waiting) with no update for QUEUE_WAIT_HOURS and no live session is asked once (CHECKS_FAILING).
    Returns the flagged ids; writes board.json only when it flags something."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALL_MINUTES)
    flagged, requeued = [], []
    try:
        with locked_board(root) as board:
            # a lilguy job in the main checkout has no pipeline to resume: no worktree or builder.
            # limitResetAt: serve.py holds the job until its usage limit resets, then auto_resume restarts it.
            # play_queued: serve.py's own CPU/RAM launch gate holds the launch: waiting, not stalled.
            stale = [j for j in board["jobs"] if j.get("stage") in WATCHED and not j.get("waiting") and not queue_waiting(j)
                     and not j.get("paused") and not lilguy_in_checkout(j) and not no_pr_job(j) and not j.get("limitResetAt") and not j.get("play_queued")
                     and not j.get("stalled") and stalled_since(j, cutoff)]
            # job 1498: a net for a job that sat DEAD_HOURS with no update under any skip reason above
            dead_cutoff = datetime.now(timezone.utc) - timedelta(hours=DEAD_HOURS)
            net = [j for j in board["jobs"] if j not in stale and dead_net_job(j) and stalled_since(j, dead_cutoff)]
            net_ids = {j["id"] for j in net}
            stale += net
            alive = alive or (session_alive_fn() if stale else None)  # ps only when something could be stalled
            idle_cutoff = datetime.now(timezone.utc) - timedelta(hours=IDLE_HOURS)
            for job in stale:
                # auto: serve.py's auto_resume retries it (its run_child test), so it is no stop for Trevor
                parent = next((j for j in board["jobs"] if j["id"] == job.get("parent")), None)
                auto = not job.get("parent") or bool(parent and parent.get("stage") == "running"
                                                     and not parent.get("paused")
                                                     and parent.get("lane") in ("runall", "bigboy"))
                live_idle = False
                # a parent's final review runs in its child's session (onewitharts 1091): its family counts as its own
                kids = [j for j in board["jobs"] if j["id"] in (job.get("children") or ())]
                if alive(job) or (kids and (chain_lock_live(root, job["id"]) or any(alive(k) for k in kids))):
                    if job["id"] in net_ids:
                        continue  # a live session is no dead job; the 2 h idle rule is for the jobs above
                    if not (stalled_since(job, idle_cutoff) and job_dir_idle(root, job["id"], idle_cutoff.timestamp())):
                        continue
                    live_idle = True
                if live_idle:
                    job.update(stalled=True, updatedAt=now(), reason=f"{STALL}no board or job-dir "
                               f"change for {IDLE_HOURS} h {LIVE_IDLE}")
                    gate = hold(job) if hold else None
                    log_stop(root, job["id"], "stall", job["reason"], auto=auto or bool(gate), **({"hold": gate} if gate else {}))
                    roadmap_stall_locked(root, job)
                    flagged.append(job["id"])
                elif job["stage"] == "spec" and not job.get("parent") \
                        and not (Path(root) / "jobs" / job["id"] / "feature.md").exists():
                    abort_job(root, job, True, ORPHANED)  # nothing to resume: put the item back, no human needed
                    requeued.append(job["id"])
                else:
                    job.update(stalled=True, updatedAt=now(), reason=f"{STALL}no board update "
                               + (f"for {DEAD_HOURS} h" if job["id"] in net_ids else f"for {STALL_MINUTES} min") + " and no live session")
                    log_stop(root, job["id"], "stall", job["reason"], auto=auto,
                             exit=(exits or {}).get(job.get("runlog")), last_log=last_log_line(root, job.get("runlog")))
                    roadmap_stall_locked(root, job)
                    flagged.append(job["id"])
            by_id = {j["id"]: j for j in board["jobs"]}
            lost = [(j["id"], cause) for j in board["jobs"]
                    if j.get("stage") == "waiting" and j.get("setup") != "pending" and not j.get("paused")
                    and stalled_since(j, dead_cutoff) and (cause := dead_wait_cause(j, by_id))]
            queue_cutoff = datetime.now(timezone.utc) - timedelta(hours=QUEUE_WAIT_HOURS)
            queued = [j for j in board["jobs"] if queue_waiting(j) and stalled_since(j, queue_cutoff)]
            alive = alive or (session_alive_fn() if queued else None)  # ps only when something could be stuck
            queued = [j["id"] for j in queued if not alive(j)]
            if not flagged and not requeued:
                raise _Gone
    except _Gone:
        pass
    for job_id, cause in lost:  # once per job: cmd_ask moves it out of `waiting`
        try:
            if find(read_board(root), job_id).get("stage") != "waiting":
                continue  # moved on since the snapshot
            cmd_ask(root, job_id, f"blocked: {cause}, so this job has nothing to wait for.",
                    [f"Put it back on the backlog=abort {job_id} --requeue", f"Remove it=abort {job_id}"],
                    recommend=("a", "Nothing can wake it, so the item goes back to be claimed again"), title="DEPENDENCY")
        except SystemExit as e:
            print(f"watchdog: {job_id}: {e}", file=sys.stderr)
    for job_id in queued:  # once per job: cmd_ask moves it out of the queue wait
        try:
            job = find(read_board(root), job_id)
            if not queue_waiting(job) or not stalled_since(job, queue_cutoff):
                continue  # resumed or moved on since the snapshot
            name = next(n for r, n in QUEUE_NAMES.items() if job["reason"].startswith(r))
            # never `waiting on the ...`: cmd_ask would hold it as a queue wait again
            cmd_ask(root, job_id, f"blocked: waited on the {name} queue "
                    f"for over {QUEUE_WAIT_HOURS} h with no live session. Its lock may be held by a dead process.",
                    [f"Try again=resume {job_id}",
                     f"Put it back on the backlog=abort {job_id}" + ("" if job.get("parent") else " --requeue")],
                    recommend=("a", "A fresh start takes the queue lock again once it is free"), title="CHECKS_FAILING")
        except SystemExit as e:
            print(f"watchdog: {job_id}: {e}", file=sys.stderr)
    return flagged  # no sound: a stall is not a human stop, serve.py resumes it


# --- roadmap.md: ordered phases of bigboy/standard steps; the orchestrator's resume doc ---
ROADMAP_STEP_RE = re.compile(r"^- \[(?P<status>[ ~x!])\] S(?P<n>\d+) (?P<kind>bigboy|standard)"
                             r"(?: (?P<job>\d{3,}-[a-z0-9-]+))?: (?P<request>.*)$")
ROADMAP_PHASE_RE = re.compile(r"^## P(\d+) (.+)$")
ROADMAP_BOX = {" ": "todo", "~": "running", "x": "done", "!": "stopped"}
ROADMAP_STATUS_BOX = {v: k for k, v in ROADMAP_BOX.items()}
ROADMAP_KINDS = ("bigboy", "standard")


def parse_roadmap(lines):
    """The parsed roadmap; each phase and step remembers its line index. SystemExit names a malformed line."""
    first = next((i for i, line in enumerate(lines) if line.strip()), 0)
    m = re.match(r"^ROADMAP: (.*\S)", lines[first].strip() if lines else "")
    if not m:
        raise SystemExit(f"roadmap.md line {first + 1}: first line must be 'ROADMAP: <name>'")
    rm, phase = {"name": m.group(1), "phases": []}, None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            pm = ROADMAP_PHASE_RE.match(line)
            phase = pm and {"n": int(pm.group(1)), "title": pm.group(2).strip(), "line": i, "steps": []}
            if phase:
                rm["phases"].append(phase)
        elif phase is not None and line.strip():
            if not (sm := ROADMAP_STEP_RE.match(line)):
                raise SystemExit(f"roadmap.md line {i + 1}: not a step "
                                 f"'- [ |~|x|!] S<n> <bigboy|standard>[ <job-id>]: <request>': {line[:80]!r}")
            phase["steps"].append({"n": int(sm["n"]), "kind": sm["kind"], "job": sm["job"],
                                   "status": ROADMAP_BOX[sm["status"]], "request": sm["request"].strip(), "line": i})
    return rm


def read_roadmap(root):
    """(lines, roadmap), or None when roadmap.md is missing. Split on \\n so writing the lines back is byte-exact."""
    path = Path(root) / "roadmap.md"
    if not path.is_file():
        return None
    lines = path.read_text(encoding="utf-8").split("\n")
    return lines, parse_roadmap(lines)


def write_roadmap(root, lines):
    path = Path(root) / "roadmap.md"
    tmp = path.with_name("roadmap.md.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, path)


def roadmap_steps(rm):
    return [(ph, st) for ph in rm["phases"] for st in ph["steps"]]


def roadmap_next_step(rm):
    """The first todo step as {p, s, kind, request}, or None."""
    return next(({"p": ph["n"], "s": st["n"], "kind": st["kind"], "request": st["request"]}
                 for ph, st in roadmap_steps(rm) if st["status"] == "todo"), None)


def roadmap_show(root):
    """The roadmap for the orchestrator, serve.py and the dashboard, or None when there is no roadmap.md."""
    got = read_roadmap(root)
    if got is None:
        return None
    rm, steps = got[1], roadmap_steps(got[1])
    cur = next(((ph, st) for ph, st in steps if st["status"] in ("running", "stopped")), None) \
        or next(((ph, st) for ph, st in steps if st["status"] == "todo"), None)
    blocker = None
    if cur and cur[1]["job"]:
        job_id, jobs = cur[1]["job"], read_board(root)["jobs"]
        stopped = lambda j: j.get("stage") == "needs-human" or j.get("paused") or stalled(j)
        hit = next((j for j in jobs if j.get("id") == job_id and stopped(j)), None) \
            or next((j for j in jobs if j.get("parent") == job_id and stopped(j)), None)
        blocker = hit and {"job": hit["id"], "reason": hit.get("reason") or ""}
    return {"name": rm["name"],
            "phases": [{"n": ph["n"], "title": ph["title"],
                        "steps": [{k: st[k] for k in ("n", "kind", "job", "status", "request")} for st in ph["steps"]]}
                       for ph in rm["phases"]],
            "current": cur and {"p": cur[0]["n"], "s": cur[1]["n"]}, "next": roadmap_next_step(rm), "blocker": blocker}


def format_step(st):
    box = ROADMAP_STATUS_BOX[st["status"]]
    return f"- [{box}] S{st['n']} {st['kind']}" + (f" {st['job']}" if st["job"] else "") + f": {st['request']}"


def roadmap_log(lines, p, s, event):
    """Append one log line at the end of ## Log, creating the section at the end of the file when missing."""
    entry = f"- {datetime.now().strftime('%Y-%m-%d %H:%M')} P{p} S{s} {clean(event, ITEM_MAX)}"
    head = next((i for i, line in enumerate(lines) if line.rstrip() == "## Log"), None)
    if head is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", "## Log", entry, ""])
        return
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while end > head + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, entry)


def roadmap_locked(root):
    """(lines, roadmap) under the caller's lock; SystemExit when there is no roadmap.md."""
    got = read_roadmap(root)
    if got is None:
        raise SystemExit(f"no roadmap.md in {root}")
    return got


def roadmap_job_step(rm, job_id):
    return next(((ph, st) for ph, st in roadmap_steps(rm) if st["job"] == job_id), None)


def cmd_roadmap_link(root, p, s, job_id):
    """Write job_id into step P/S and mark it running (also resumes a stopped step)."""
    check_id(job_id)
    with locked_board(root):
        lines, rm = roadmap_locked(root)
        st = next((st for ph, st in roadmap_steps(rm) if ph["n"] == p and st["n"] == s), None)
        if st is None:
            raise SystemExit(f"roadmap.md has no step P{p} S{s}")
        st.update(job=job_id, status="running")
        lines[st["line"]] = format_step(st)
        roadmap_log(lines, p, s, f"started: {job_id}")
        write_roadmap(root, lines)


def cmd_roadmap_next(root, job_id):
    """Mark job_id's step done and return the next todo step. A job in no step (or no roadmap.md) changes nothing.
    Cool-down holds the next step: the step stays running and None is returned; Roadmap resume marks it done later."""
    if cooling_down() or soft_cap_reason() or not (Path(root) / "roadmap.md").is_file():
        return None
    with locked_board(root):
        lines, rm = roadmap_locked(root)
        hit = roadmap_job_step(rm, job_id)
        if hit is None:
            return None
        ph, st = hit
        st["status"] = "done"
        lines[st["line"]] = format_step(st)
        roadmap_log(lines, ph["n"], st["n"], f"done: {job_id}")
        write_roadmap(root, lines)
        return roadmap_next_step(parse_roadmap(lines))


def cmd_roadmap_insert(root, p, after, kind, request):
    """Add a todo step S<after+1> to phase P and renumber the later steps of that phase by position."""
    request = clean(request, ITEM_MAX)
    if kind not in ROADMAP_KINDS:
        raise SystemExit(f"bad kind {kind!r}; allowed: {', '.join(ROADMAP_KINDS)}")
    if not request:
        raise SystemExit("roadmap step request is empty")
    with locked_board(root):
        lines, rm = roadmap_locked(root)
        ph = next((ph for ph in rm["phases"] if ph["n"] == p), None)
        if ph is None:
            raise SystemExit(f"roadmap.md has no phase P{p}")
        steps = ph["steps"]
        if not 0 <= after <= len(steps):
            raise SystemExit(f"roadmap.md P{p} has {len(steps)} steps; cannot insert after S{after}")
        for st in steps[after:]:
            st["n"] += 1
            lines[st["line"]] = format_step(st)
        at = steps[after - 1]["line"] + 1 if after else steps[0]["line"] if steps else ph["line"] + 1
        new = {"n": after + 1, "kind": kind, "job": None, "status": "todo", "request": request}
        lines.insert(at, format_step(new))
        roadmap_log(lines, p, after + 1, f"inserted: {request}")
        write_roadmap(root, lines)
    return {"p": p, "s": after + 1, "kind": kind, "request": request}


def roadmap_stop_locked(root, job_id, reason, parent=None):
    """Under the caller's board lock: mark the step of job_id (else of parent) stopped and log the reason.
    False, changing nothing, when there is no roadmap.md, no such step, or the step is done.
    SystemExit when roadmap.md is malformed."""
    got = read_roadmap(root)
    if got is None:
        return False
    lines, rm = got
    hit = roadmap_job_step(rm, job_id) or (parent and roadmap_job_step(rm, parent))
    if not hit or hit[1]["status"] == "done":
        return False
    ph, st = hit
    st["status"] = "stopped"
    lines[st["line"]] = format_step(st)
    roadmap_log(lines, ph["n"], st["n"], f"stopped: {reason}")
    write_roadmap(root, lines)
    return True


def roadmap_stall_locked(root, job):
    """A stalled job (just flagged `stalled` in its stage) stops its roadmap step; a roadmap problem never undoes the
    flag."""
    try:
        roadmap_stop_locked(root, job["id"], f"{job['id']} {job['reason']}", job.get("parent"))
    except SystemExit as e:
        print(f"watchdog: roadmap: {e}", file=sys.stderr, flush=True)


def cmd_roadmap_stop(root, job_id, reason):
    """Mark job_id's step stopped (needs a human) and log the reason."""
    with locked_board(root):
        lines, rm = roadmap_locked(root)
        if roadmap_job_step(rm, job_id) is None:
            raise SystemExit(f"job {job_id!r} is in no roadmap.md step")
        roadmap_stop_locked(root, job_id, reason)


KEEP_PORTS = (3001, 8765)  # Trevor's prod-env dev port and serve.py itself: never stopped


def listeners() -> list[tuple[int, int, str]]:
    """(pid, port, realpath cwd) of every listening TCP socket this user owns: one lsof for the sockets, one for their
    cwds. lsof missing, failing or timing out (5 s) gives [], so nothing is killed."""
    def lsof(*args):
        out = subprocess.run(["lsof", *args], capture_output=True, text=True, timeout=5)
        if out.returncode:
            raise OSError(out.stderr.strip())
        return out.stdout.splitlines()
    try:
        ports, pid = [], None
        for line in lsof("-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"):
            if line[:1] == "p":
                pid = int(line[1:])
            elif line[:1] == "n" and pid is not None and (pid, int(line.rsplit(":", 1)[1])) not in ports:
                ports.append((pid, int(line.rsplit(":", 1)[1])))
        if not ports:
            return []
        cwds, pid = {}, None
        for line in lsof("-a", "-d", "cwd", "-Fpn", "-p", ",".join(str(p) for p in dict.fromkeys(p for p, _ in ports))):
            if line[:1] == "p":
                pid = int(line[1:])
            elif line[:1] == "n" and pid is not None:
                cwds[pid] = os.path.realpath(line[1:])
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return [(p, port, cwds[p]) for p, port in ports if p in cwds]


LOCAL_DB_HOSTS = ("localhost", "127.0.0.1", "::1")
COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml")


def port_open(host: str, port: int) -> bool:
    """True when a TCP connect to host:port succeeds within 2 s."""
    try:
        socket.create_connection((host, port), timeout=2).close()
        return True
    except OSError:
        return False


def start_local_db(cwd=None, sleep=time.sleep) -> str | None:
    """Start the local database: `brew services start` the first postgres* service `brew services list` names, else
    `docker compose up -d` when cwd (default the current folder) holds a compose file, after waiting up to 120 s for
    Docker (`open -a Docker`, then `docker info` every 5 s). Returns None when the start command succeeded, else the
    reason; never raises."""
    def run(*argv):
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=120)
    try:
        listed = run("brew", "services", "list").stdout.splitlines()[1:]
        name = next((ln.split()[0] for ln in listed if ln.split() and ln.split()[0].startswith("postgres")), None)
    except (OSError, subprocess.SubprocessError):
        name = None
    try:
        if name:
            r = run("brew", "services", "start", name)
            return None if r.returncode == 0 else f"brew services start {name} exited {r.returncode}: {r.stderr.strip()}"
        if not any((Path(cwd or ".") / f).exists() for f in COMPOSE_FILES):
            return "no postgres brew service and no compose file"
        if run("docker", "info").returncode != 0:
            run("open", "-a", "Docker")
            for _ in range(24):
                sleep(5)
                if run("docker", "info").returncode == 0:
                    break
            else:
                return "Docker did not start within 120 s"
        r = subprocess.run(["docker", "compose", "up", "-d"], capture_output=True, text=True, timeout=300, cwd=cwd)
        return None if r.returncode == 0 else f"docker compose up -d exited {r.returncode}: {r.stderr.strip()}"
    except (OSError, subprocess.SubprocessError) as e:
        return f"database start failed: {e}"


def db_up(env_file, wait=120, start=None, probe=None, sleep=None) -> dict:
    """The Check gate's database probe. Reads DATABASE_URL (quotes stripped) from env_file and TCP-probes its host:port
    (5432 when the URL has none). Open: {"up": true, "started": false}. Refused on a LOCAL_DB_HOSTS host: call start
    (default start_local_db in env_file's folder) once, re-probe every 5 s for up to wait seconds, and return {"up", "started": true}, plus
    "error" when the start failed. A missing file, a missing or unparsable URL, or a non-local host returns
    {"up": null, "skipped": reason} and starts nothing."""
    probe, sleep = probe or port_open, sleep or time.sleep
    try:
        text = Path(env_file).read_text()
    except (OSError, UnicodeDecodeError):
        return {"up": None, "skipped": f"no readable env file {env_file}"}
    m = re.search(r"^\s*(?:export\s+)?DATABASE_URL\s*=\s*(.*)$", text, re.M)
    if not m:
        return {"up": None, "skipped": "no DATABASE_URL"}
    try:
        u = urlsplit(m.group(1).strip().strip("\"'"))
        host, port = u.hostname, u.port or 5432
    except ValueError:
        host = None
    if not host:
        return {"up": None, "skipped": "DATABASE_URL has no parsable host:port"}
    if host not in LOCAL_DB_HOSTS:
        return {"up": None, "skipped": f"{host} is not a local host"}
    if probe(host, port):
        return {"up": True, "started": False}
    try:
        error = start() if start else start_local_db(cwd=Path(env_file).parent)  # compose file sits beside env_file
    except Exception as e:  # a starter failure is reported, never raised
        error = f"database start failed: {e}"
    up = False
    for _ in range(max(1, int(wait // 5))):
        sleep(5)
        if probe(host, port):
            up = True
            break
    return {"up": up, "started": True, **({"error": error} if error and not up else {})}


def stop_worktree_servers(repo: Path, wt: str | None, listening=None, wait: float = 0.0,
                          job_id: str | None = None) -> list[int]:
    """SIGTERM every listener whose cwd is the job worktree wt, its wt + "-base" sibling (the Check gate's base copy)
    or, with job_id, /tmp/scrum-base-<job_id> (the Review BASE copy), or a path under one; returns the pids signalled,
    in order. wt must sit strictly inside <repo>/.claude/worktrees/, else nothing is read or signalled (a main-checkout
    job never loses Trevor's own server); it need not exist, so a removed worktree's servers still stop. Never a pid
    that also listens on a KEEP_PORTS port, never this process. listening defaults to listeners(). With wait > 0,
    each pid still alive after polling every 0.25 s for wait seconds gets SIGKILL: a wedged Node event loop may never
    run its SIGTERM handler."""
    if not wt:
        return []
    base = os.path.realpath(Path(repo) / ".claude" / "worktrees") + os.sep
    wt = os.path.realpath(wt)
    if not wt.startswith(base):
        return []
    roots = [wt, wt + "-base"]
    if isinstance(job_id, str) and job_id and os.sep not in job_id:
        roots.append(os.path.join(os.path.realpath("/tmp"), f"scrum-base-{job_id}"))
    listening = listeners() if listening is None else listening
    keep = {pid for pid, port, _ in listening if port in KEEP_PORTS} | {os.getpid()}
    killed = []
    for pid, _, cwd in listening:
        if pid in keep or pid in killed or not any(cwd == r or cwd.startswith(r + os.sep) for r in roots):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except (ProcessLookupError, PermissionError):
            pass
    def gone(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        return False
    alive = list(killed)
    for _ in range(int(wait / 0.25)):
        if not alive:
            break
        time.sleep(0.25)
        alive = [pid for pid in alive if not gone(pid)]
    for pid in alive if wait > 0 else []:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return killed


def require_scrum_dir(d: Path) -> Path:
    """Refuse a git checkout root: .board.lock and runs/ would land in the repo (a worktree has a .git file)."""
    if (d / ".git").exists():
        raise SystemExit(f"--dir must be the project's scrum/ folder, not the repo root: {d}")
    return d


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", type=Path, default=Path("scrum"))
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("title")
    n.add_argument("--id")
    n.add_argument("--by", choices=STARTED_BY, default="hand")
    s = sub.add_parser("set")
    s.add_argument("--unpause", action="store_true")
    s.add_argument("id")
    s.add_argument("pairs", nargs="+")
    sub.add_parser("sync").add_argument("id")
    ak = sub.add_parser("ask")
    ak.add_argument("id")
    ak.add_argument("question")
    ak.add_argument("--a", required=True, metavar="LABEL=COMMAND")
    ak.add_argument("--b", required=True, metavar="LABEL=COMMAND")
    ak.add_argument("--c", metavar="LABEL=COMMAND")
    ak.add_argument("--kind")
    ak.add_argument("--title")
    ak.add_argument("--recommend", nargs=2, metavar=("KEY", "WHY"))
    wo = sub.add_parser("wait-on")
    wo.add_argument("id")
    wo.add_argument("blocker")
    wo.add_argument("--then")
    sub.add_parser("unblock-log").add_argument("id")
    an = sub.add_parser("answer")
    an.add_argument("id")
    an.add_argument("key", choices=("a", "b", "c"))
    sub.add_parser("project-note").add_argument("line")
    fu = sub.add_parser("followup")
    fu.add_argument("id")
    fu.add_argument("fix")
    sub.add_parser("next").add_argument("--index", type=int)
    sub.add_parser("cloud-claim").add_argument("n", type=int)
    ba = sub.add_parser("backlog-add")
    ba.add_argument("--setup", metavar="TEXT", help='Human setup checklist "step; step"')
    ba.add_argument("--priority", type=int, metavar="N", help="importance 1-5, highest claimed first")
    ba.add_argument("--top", action="store_true", help="insert first with {p:5}, so next claims it first")
    src = ba.add_mutually_exclusive_group()
    src.add_argument("--trevor", action="store_true", help="Trevor's item: {by:t}, p:4 (p:5 with --priority 5)")
    src.add_argument("--back", action="store_true", help="Trevor's item for the back of the backlog: {by:back}, p:1")
    ba.add_argument("--critical", action="store_true", help="agent item jev-gate.py critical confirmed: p:5")
    ba.add_argument("--job", metavar="ID", help="write each item as jobs/<id>/followups/add-<n>.md, not backlog.md")
    ba.add_argument("--project", metavar="FOLDER", help="with --job: the repo folder whose backlog files it at home")
    ba.add_argument("items", nargs="+")
    sub.add_parser("manual-add").add_argument("items", nargs="+")
    sub.add_parser("rank-backlog").add_argument("--all", action="store_true", dest="all_items")
    sub.add_parser("roadmap-show")
    rl = sub.add_parser("roadmap-link")
    rl.add_argument("p", type=int)
    rl.add_argument("s", type=int)
    rl.add_argument("id")
    sub.add_parser("roadmap-next").add_argument("id")
    ri = sub.add_parser("roadmap-insert")
    ri.add_argument("p", type=int)
    ri.add_argument("after", type=int)
    ri.add_argument("kind")
    ri.add_argument("request", nargs="+")
    rs = sub.add_parser("roadmap-stop")
    rs.add_argument("id")
    rs.add_argument("reason", nargs="+")
    sub.add_parser("backlog-spec").add_argument("id")
    sub.add_parser("register").add_argument("repo", type=Path)
    ab = sub.add_parser("abort")
    ab.add_argument("id")
    ab.add_argument("--requeue", action="store_true")
    ab.add_argument("--cascade", action="store_true")
    ab.add_argument("--reason")
    sub.add_parser("artifacts").add_argument("id")
    sub.add_parser("dev-clear").add_argument("id")
    sub.add_parser("db-up").add_argument("--env", required=True)
    sub.add_parser("cooldown-park").add_argument("id")
    sub.add_parser("digest-due")
    sub.add_parser("digest-start")
    sub.add_parser("digest-trim").add_argument("digest")
    sub.add_parser("pipeline-fit").add_argument("digest")
    sub.add_parser("digest-trevor").add_argument("digest")
    sub.add_parser("digest-questions").add_argument("digest")
    sub.add_parser("process-health").add_argument("digest")
    sub.add_parser("window-report")
    sub.add_parser("move-ratio").add_argument("id")
    sub.add_parser("lilguy-fit").add_argument("id")
    sub.add_parser("lane-read").add_argument("part", choices=list(PIPELINE_READ_PARTS))
    sub.add_parser("claude-paths").add_argument("id")
    sub.add_parser("claude-batch").add_argument("id")
    sub.add_parser("claude-migrate").add_argument("--dry-run", action="store_true")
    rc = sub.add_parser("route-check")
    rc.add_argument("id")
    rc.add_argument("--check-fails", type=int, default=0)
    rc.add_argument("--clean-start", action="store_true")
    sub.add_parser("triage-start")
    sub.add_parser("triage-apply").add_argument("triage")
    sub.add_parser("hook")
    sub.add_parser("git-guard")
    sub.add_parser("statusline")
    sm = sub.add_parser("spec-models")
    sm.add_argument("ids", nargs="+")
    sub.add_parser("ops-kind").add_argument("id")
    fo = sub.add_parser("fable-ok")
    fo.add_argument("id")
    fo.add_argument("role")
    po = sub.add_parser("prod-ok")
    po.add_argument("id")
    po.add_argument("bullet")
    sub.add_parser("live-record").add_argument("id")
    pa = sub.add_parser("plan-apply")
    pa.add_argument("id")
    pa.add_argument("--fix", action="store_true")
    rd = sub.add_parser("ready")
    rd.add_argument("id")
    rd.add_argument("--specs-done", action="store_true")
    sub.add_parser("runall-start").add_argument("--match")
    sub.add_parser("watchdog")
    sub.add_parser("cloud-sync")
    cl = sub.add_parser("chain-lock")
    cl.add_argument("id")
    cl.add_argument("holder")
    cl.add_argument("--wait", type=int, default=540)
    rp = sub.add_parser("review-plan")
    rp.add_argument("id")
    rp.add_argument("--incremental", action="store_true")
    es = sub.add_parser("e2e-specs")
    es.add_argument("id", nargs="?")
    es.add_argument("--worktree")
    es.add_argument("--base")
    es.add_argument("--project")
    eb = sub.add_parser("e2e-budget")
    eb.add_argument("id")
    eb.add_argument("log")
    es2 = sub.add_parser("e2e-stopped")
    es2.add_argument("id")
    es2.add_argument("--since", type=float)
    sub.add_parser("check-reuse").add_argument("id")
    sub.add_parser("related-tests").add_argument("id")
    sub.add_parser("render-paths").add_argument("id")
    sub.add_parser("ui-sweep-record").add_argument("review")
    cu = sub.add_parser("chain-unlock")
    cu.add_argument("id")
    cu.add_argument("holder")
    sp = sub.add_parser("spawn")
    sp.add_argument("id")
    sp.add_argument("action")
    sp.add_argument("prompt", nargs="?")
    sp.add_argument("--model")
    a = p.parse_args(argv)
    if a.cmd == "hook":
        # Never block Claude Code: no output, exit 0, whatever happens (exit 2 would block the tool call).
        try:
            cmd_hook(json.loads(sys.stdin.read()), caller_tty(), caller_claude_pid())
        except (Exception, SystemExit):
            pass
        return 0
    if a.cmd == "git-guard":
        # Retired (job 812): the Go binary gitguard/gitguard is the hook now. Kept as a silent exit-0 no-op because a
        # settings.json not yet migrated by ./install.sh still calls it, and an unknown subcommand's exit 2 would block
        # every Bash call.
        return 0
    if a.cmd == "statusline":
        # Never show a traceback in the status line: an empty line and exit 0 whatever happens.
        try:
            line = cmd_statusline(sys.stdin.read())
        except (Exception, SystemExit):
            line = ""
        print(line)
        return 0
    if a.cmd == "db-up":
        out = db_up(a.env)
        print(json.dumps(out))
        return 1 if out["up"] is False else 0
    require_scrum_dir(a.dir)
    if a.cmd == "new":
        print(cmd_new(a.dir, a.title, a.id, started_by=a.by, refuse=a.id is None))
    elif a.cmd == "set":
        cmd_set(a.dir, a.id, a.pairs, unpause=a.unpause)
    elif a.cmd == "sync":
        print(json.dumps(cmd_sync(a.dir, a.id)))
    elif a.cmd == "ask":
        if unreadable_question(a.question):
            raise SystemExit("ask refused: keep the question to 40 words or fewer, with no file path or "
                             "\"rule N\"; move the detail into stop.md and ask again.")
        commands = [o.partition("=")[2].strip() for o in (a.a, a.b, a.c) if o is not None]
        q = a.question.strip()  # cmd_ask stores it stripped
        # the automatic asks process_health already ignores keep Carry on=resume / Remove this job=abort
        exempt = is_guard_ask(q) or QUEUE_ASK_RE.match(q) or CI_BILLING_RE.search(q) or AGENT_TYPES_RE.search(q) \
            or q.lower().startswith(QUIET_PREFIX)
        if resume_abort_only(commands) and not exempt:
            raise SystemExit('ask refused: add a followup <id> "<fix>" option, or run B wait-on <id> <blocker> '
                             'instead of asking')
        out = cmd_ask(a.dir, a.id, a.question, [o for o in (a.a, a.b, a.c) if o is not None], a.kind,
                      a.recommend, title=a.title)
        if a.kind is not None:
            print(json.dumps(out if isinstance(out, dict) else {"unblock": False}))
    elif a.cmd == "wait-on":
        print(json.dumps(cmd_wait_on(a.dir, a.id, a.blocker, a.then)))
    elif a.cmd == "unblock-log":
        print(json.dumps(cmd_unblock_log(a.dir, a.id)))
    elif a.cmd == "answer":
        print(json.dumps(cmd_answer(a.dir, a.id, a.key)))
    elif a.cmd == "followup":
        cmd_followup(a.dir, a.id, a.fix)
    elif a.cmd == "project-note":
        print(json.dumps(cmd_project_note(a.dir, a.line)))
    elif a.cmd == "next":
        print(json.dumps(cmd_next(a.dir, a.index)))
    elif a.cmd == "cloud-claim":
        print(json.dumps(cmd_cloud_claim(a.dir, a.n)))
    elif a.cmd == "roadmap-show":
        print(json.dumps(roadmap_show(a.dir)))
    elif a.cmd == "roadmap-link":
        cmd_roadmap_link(a.dir, a.p, a.s, a.id)
    elif a.cmd == "roadmap-next":
        print(json.dumps(cmd_roadmap_next(a.dir, a.id)))
    elif a.cmd == "roadmap-insert":
        print(json.dumps(cmd_roadmap_insert(a.dir, a.p, a.after, a.kind, " ".join(a.request))))
    elif a.cmd == "roadmap-stop":
        cmd_roadmap_stop(a.dir, a.id, " ".join(a.reason))
    elif a.cmd == "register":
        cmd_register(a.repo)
    elif a.cmd == "abort":
        aborted = cmd_abort(a.dir, a.id, a.requeue, a.reason, a.cascade)
        if a.cascade:
            print(json.dumps({"aborted": aborted}))
    elif a.cmd == "artifacts":
        print("".join(f"{line}\n" for line in cmd_artifacts(a.dir, a.id)), end="")
    elif a.cmd == "dev-clear":
        wt = find(read_board(a.dir), a.id).get("worktree")
        print(json.dumps({"killed": stop_worktree_servers(Path(a.dir).resolve().parent, wt, wait=5, job_id=a.id)}))
    elif a.cmd == "cooldown-park":
        print(json.dumps(cmd_cooldown_park(a.dir, a.id)))
    elif a.cmd == "digest-due":
        print(json.dumps(cmd_digest_due(a.dir)))
    elif a.cmd == "digest-start":
        print(json.dumps(cmd_digest_start(a.dir)))
    elif a.cmd == "digest-trim":
        print(json.dumps(cmd_digest_trim(a.dir, a.digest)))
    elif a.cmd == "pipeline-fit":
        print(json.dumps(cmd_pipeline_fit(a.dir, a.digest)))
    elif a.cmd == "digest-trevor":
        print(json.dumps(cmd_digest_trevor(a.dir, a.digest)))
    elif a.cmd == "digest-questions":
        print(json.dumps(cmd_digest_questions(a.dir, a.digest)))
    elif a.cmd == "process-health":
        print(json.dumps(cmd_process_health(a.dir, a.digest)))
    elif a.cmd == "window-report":
        print(json.dumps(cmd_window_report(a.dir)))
    elif a.cmd == "move-ratio":
        out = cmd_move_ratio(a.dir, a.id)
        print(json.dumps(out))
        return 1 if out.get("ok") is False else 0
    elif a.cmd == "lilguy-fit":
        out = cmd_lilguy_fit(a.dir, a.id)
        read = lilguy_read() if out.get("fit") else None
        if read:
            out = {**out, "read": read}
        print(json.dumps(out))
    elif a.cmd == "lane-read":
        print(f"read: {pipeline_read(a.part) or 'none'}")
    elif a.cmd == "claude-paths":
        print(json.dumps(cmd_claude_paths(a.dir, a.id)))
    elif a.cmd == "claude-batch":
        print(json.dumps(cmd_claude_batch(a.dir, a.id)))
    elif a.cmd == "claude-migrate":
        print(json.dumps(cmd_claude_migrate(a.dir, a.dry_run)))
    elif a.cmd == "route-check":
        print(json.dumps(cmd_route_check(a.dir, a.id, a.check_fails, a.clean_start)))
    elif a.cmd == "triage-start":
        print(json.dumps(cmd_triage_start(a.dir)))
    elif a.cmd == "triage-apply":
        print(json.dumps(cmd_triage_apply(a.dir, a.triage)))
    elif a.cmd == "rank-backlog":
        print(json.dumps(cmd_rank_backlog(a.dir, a.all_items)))
    elif a.cmd == "manual-add":
        print(json.dumps(cmd_manual_add(a.dir, a.items)))
    elif a.cmd == "plan-apply":
        print(json.dumps(cmd_plan_apply(a.dir, a.id, a.fix)))
    elif a.cmd == "ready":
        print(json.dumps(cmd_ready(a.dir, a.id, specs_done=a.specs_done)))
    elif a.cmd == "runall-start":
        print(json.dumps(cmd_runall_start(a.dir, a.match)))
    elif a.cmd == "watchdog":
        print(json.dumps({"flagged": cmd_watchdog(a.dir)}))
    elif a.cmd == "cloud-sync":
        out = cmd_cloud_sync(a.dir)
        print(json.dumps(out))
        return 1 if out["error"] else 0
    elif a.cmd == "chain-lock":
        print(json.dumps(cmd_chain_lock(a.dir, a.id, a.holder, a.wait)))
    elif a.cmd == "chain-unlock":
        print(json.dumps(cmd_chain_unlock(a.dir, a.id, a.holder)))
    elif a.cmd == "review-plan":
        print(json.dumps(cmd_review_plan(a.dir, a.id, a.incremental)))
    elif a.cmd == "e2e-specs":
        if a.id:
            print(json.dumps(cmd_e2e_specs(a.dir, a.id)))
        elif a.worktree and a.base and a.project:
            print(json.dumps(e2e_specs(a.worktree, a.base, a.project)))
        else:
            raise SystemExit("e2e-specs needs <id>, or --worktree, --base and --project")
    elif a.cmd == "e2e-budget":
        print(json.dumps(cmd_e2e_budget(a.dir, a.id, a.log)))
    elif a.cmd == "e2e-stopped":
        print(json.dumps(cmd_e2e_stopped(a.dir, a.id, a.since)))
    elif a.cmd == "check-reuse":
        print(json.dumps(cmd_check_reuse(a.dir, a.id)))
    elif a.cmd == "related-tests":
        if files := cmd_related_tests(a.dir, a.id):
            print("\n".join(files))
    elif a.cmd == "render-paths":
        print(json.dumps(cmd_render_paths(a.dir, a.id)))
    elif a.cmd == "ui-sweep-record":
        print(json.dumps(cmd_ui_sweep_record(a.dir, a.review)))
    elif a.cmd == "ops-kind":
        print(cmd_ops_kind(a.dir, a.id))
    elif a.cmd == "fable-ok":
        print(cmd_fable_ok(a.dir, a.id, a.role))
    elif a.cmd == "spec-models":
        print(json.dumps(cmd_spec_models(a.dir, a.ids)))
    elif a.cmd == "prod-ok":
        print(cmd_prod_ok(a.dir, a.id, a.bullet))
    elif a.cmd == "live-record":
        print(cmd_live_record(a.dir, a.id))
    elif a.cmd == "spawn":
        proc, log = spawn(a.dir, a.id, a.action, a.prompt, model=a.model, caller=caller_claude_pid(), hot_hold=False)
        print(json.dumps({"log": log, "pid": proc.pid}))
    elif a.cmd == "backlog-spec":
        out = cmd_backlog_spec(a.dir, a.id)
        print(json.dumps(out))
        spawn_estimates(a.dir, out["added"])
        for m in out.get("moved") or []:
            if (target := add_target(a.dir, m["project"])) is not None:
                spawn_estimates(target, [m["text"]])
    else:
        by = "back" if a.back else "t" if a.trevor else None
        if a.project is not None and a.job is None:
            raise SystemExit("backlog-add --project needs --job <id>: it names the project a worker's add is filed in")
        if a.job is not None:
            worker_add(a.dir, a.job, a.items, a.project, a.setup, a.priority, a.top, by, a.critical)
        elif on_worker():
            raise SystemExit("backlog-add on a shop or cloud worker needs --job <id>: this machine's backlog.md never "
                             "syncs home, so the add goes to jobs/<id>/followups/ instead; nothing added")
        else:
            spawn_estimates(a.dir, cmd_backlog_add(a.dir, a.items, a.setup, a.priority, a.top, by, a.critical))


def spawn_estimates(root, texts):
    """The same Sonnet estimate a dashboard add gets, detached so this returns at once. Library callers spawn nothing."""
    for text in texts:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve().with_name("serve.py")), f"--estimate={text}",
                          "--dir", str(Path(root).resolve())], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


# Started from the app icon, PATH can be bare, so look in the usual install spots too. Tests set SCRUM_CLAUDE.
CLAUDE = os.environ.get("SCRUM_CLAUDE") or shutil.which("claude") or next(
    (str(p) for p in (Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude"), Path.home() / ".claude/local/claude")
     if p.exists()), "claude")
MODEL_RE = re.compile(r"[A-Za-z0-9._-]+")
SPAWN_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")  # job ids plus run-all, digest, research-<hash>; it names the log file
SPAWN_ACTION_RE = re.compile(r"[a-z-]+")


BIG_LANES = ("bigboy", "roadmap")
BIG_POINTS = 5


def big_ticket(root: Path, job_id: str) -> bool:
    """A job on a BIG_LANES lane, or claimed from a backlog line of BIG_POINTS or more."""
    try:
        job = find(read_board(root), job_id)
    except SystemExit:  # not on the board (run-all, digest) or a broken board.json
        job = {}
    if job.get("lane") in BIG_LANES:
        return True
    try:
        items = read_backlog(root)[1]
    except (OSError, ValueError):  # unreadable or non-UTF-8 backlog.md: not big by points
        return False
    return any(i.get("job") == job_id and (i.get("points") or 0) >= BIG_POINTS for i in items)


def cmd_fable_ok(root: Path, job_id: str, role: str) -> str:
    """fable-ok: FABLE_AGENT or "none" for a new planner or spec-writer spawn. Only a job_complex job on the board is
    eligible, and its spec-writer only when the board lane is missing, empty or standard. An eligible call gets Fable
    only while fable_state is ok, and appends a tab-separated line to jobs/<id>/fable.log (skipped when that dir is
    missing); an ineligible one writes nothing."""
    if role not in ("planner", "spec-writer"):
        raise SystemExit(f"fable-ok: role must be planner or spec-writer, not {role!r}")
    check_id(job_id)
    try:
        lane = find(read_board(root), job_id).get("lane")
    except SystemExit:  # not on the board, or a broken board.json
        return "none"
    if not job_complex(root, job_id) or role == "spec-writer" and lane not in (None, "", "standard"):
        return "none"
    now = time.time()
    usage = read_usage()
    if isinstance(usage, dict) and is_num(usage.get("written_at")):
        # Only the interactive statusline refreshes usage.json, so a headless job reads it hours old. Trust its windows anyway:
        # a reset window reads 0 (fable_used) and a live one is a lower bound. ponytail: a stale 7d reading can undercount.
        usage = {**usage, "written_at": now}
    state = fable_state(usage, now)
    model = FABLE_AGENT if state == "ok" else "none"
    job = Path(root) / "jobs" / job_id
    if job.is_dir():
        pct = {k: "—" if v is None else f"{round(v)}%" for k, v in fable_used(usage, now).items()}
        with open(job / "fable.log", "a") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')}\t{role}\t{'opus' if model == 'none' else 'fable'}"
                     f"\t5h {pct['5h']}\t7d {pct['7d']}\t{state}\n")
    return model


SPEC_MODEL_TIMEOUT = 90  # seconds per child for one jev-gate.py spec-model run
JEV_GATE_PY = Path(__file__).resolve().with_name("jev-gate.py")


def _spec_model_decision(root: Path, job_id: str) -> str | None:
    """The jev-gate.py spec-model decision for one child ("sonnet" or "opus"), else None: the last spec-model line of
    its jev.log when there is one, else a fresh gate run (which logs its own line). A timeout, a non-zero exit or any
    other output gives None."""
    folder = Path(root) / "jobs" / job_id
    try:
        lines = (folder / "jev.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in reversed(lines):
        f = line.split("\t")
        if len(f) > 4 and f[1] == "spec-model":
            return f[4] if f[4] in ("sonnet", "opus") else None
    try:
        r = subprocess.run([sys.executable, str(JEV_GATE_PY), "spec-model", str(folder)], capture_output=True, text=True,
                           timeout=SPEC_MODEL_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out in ("sonnet", "opus") else None


def cmd_spec_models(root: Path, ids: list[str]) -> dict:
    """spec-models: {child: model or None} for the run-all spec-writer spawn. fable-ok's model wins when it is not
    "none"; else the jev decision when sonnet or opus; else None (no override, frontmatter Opus)."""
    ids = [check_id(i) for i in ids]
    with ThreadPoolExecutor(max_workers=max(1, len(ids))) as pool:
        decisions = list(pool.map(lambda i: _spec_model_decision(root, i), ids))
    out = {}
    for job_id, decision in zip(ids, decisions):
        fable = cmd_fable_ok(root, job_id, "spec-writer")
        out[job_id] = fable if fable != "none" else decision
    return out


PROD_TOKEN_RE = re.compile(r"[A-Za-z0-9=_.:/-]+")
PROD_DENY_RE = re.compile(r"(?i)prisma|vercel|migrate|db:push|accept-data-loss|force-reset|\b(e2e|fixtures?|test)\b")
PROD_RUN_RE = re.compile(r"- run: (.+) exit (-?\d+)")


def prod_bullet(bullet: str):
    """(script, args) of a `npm run <script>[ -- <args>]` bullet, or SystemExit("prod-ok: ...")."""
    m = re.fullmatch(r"npm run (\S+)(?: -- (\S+(?: \S+)*))?", bullet)
    args = m[2].split(" ") if m and m[2] else []
    if not m or m[1].startswith("-") or not all(PROD_TOKEN_RE.fullmatch(t) for t in [m[1], *args]):
        raise SystemExit(f"prod-ok: not an npm run bullet: {bullet!r}")
    return m[1], args


def prod_records(path: Path):
    """[(script, args, passed)] for each `- run: <bullet> exit <code>` record in prod.md; a record passes when its
    code is 0 and no output line (up to the next `- run:` line or `## ` heading) has the word error, or the record holds
    Merge's `    error found in output (Jev: handled): ` marker and no plain `    error found in output: ` marker."""
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):  # no prod.md: no records
        return []
    out, cur = [], None
    for line in lines:
        m = PROD_RUN_RE.fullmatch(line)
        if m:
            try:
                script, args = prod_bullet(m[1])
            except SystemExit:
                cur = None
                continue
            cur = [script, args, m[2] == "0", False, False, False]  # + error word, handled marker, plain marker
            out.append(cur)
        elif line.startswith("## "):
            cur = None
        elif cur is not None:
            cur[3] |= bool(re.search(r"(?i)\berror\b", line))
            cur[4] |= line.startswith("    error found in output (Jev: handled): ")
            cur[5] |= line.startswith("    error found in output: ")
    return [(s, a, ok and (not err or (handled and not plain))) for s, a, ok, err, handled, plain in out]


def cmd_prod_ok(root: Path, job_id: str, bullet: str) -> str:
    """prod-ok: gate one decision.md `## Prod runs` bullet before Merge's Prod check runs it. Refuses (SystemExit
    "prod-ok: ...") a malformed bullet, a script missing from the repo's package.json, and any schema, deploy or
    fixture script (PROD_DENY_RE over name, args and command). "dev" for a non-prod run; a prod run (name ends
    `:prod`, or its command reads .env.prod*) is "ok" only when jobs/<id>/prod.md holds a passing dev dry run (args
    without --apply) and dev apply (same args plus --apply) of the script with `:prod` stripped.
    A `--prod` arg (a script's own prod guard) is dropped before matching, since dev never takes it."""
    check_id(job_id)
    script, args = prod_bullet(bullet)
    try:
        scripts = json.loads((Path(root).parent / "package.json").read_text()).get("scripts")
    except (OSError, ValueError, AttributeError):
        raise SystemExit("prod-ok: cannot read scripts from package.json")
    if not isinstance(scripts, dict) or script not in scripts:
        raise SystemExit(f"prod-ok: {script} is not a package.json script")
    command = str(scripts[script])
    m = PROD_DENY_RE.search(" ".join([script, *args, command]))
    if m:
        raise SystemExit(f"prod-ok: refused {bullet!r}: matches {m[0]!r}")
    if not script.endswith(":prod") and ".env.prod" not in command:
        return "dev"
    if not script.endswith(":prod"):
        raise SystemExit(f"prod-ok: no dev script for {script}")
    dev = script[:-len(":prod")]
    base = [a for a in args if a not in ("--apply", "--prod")]
    records = prod_records(Path(root) / "jobs" / job_id / "prod.md")
    dry = any(s == dev and a == base and ok for s, a, ok in records)
    applied = any(s == dev and "--apply" in a and [x for x in a if x != "--apply"] == base and ok for s, a, ok in records)
    missing = [f"npm run {dev}" + (f" -- {' '.join(want)}" if want else "")
               for want, have in ((base, dry), (base + ["--apply"], applied)) if not have]
    if missing:
        raise SystemExit("prod-ok: " + "; ".join(f"no passing dev run of {b!r} in prod.md" for b in missing))
    return "ok"


# --- live-record: a decision.md or spec.md `## Live checks` bullet, run after the merge by serve.py live_check_tick ---
LIVE_DENY_RE = re.compile(r"(?i)prisma|migrate|db:push|playwright|next (build|dev)|vercel|npm run (build|dev)")
LIVE_BULLET_RE = re.compile(r"- `([^`]+)` \| from (merge|\+6h|\+1d) \| by (\+1d|\+7d) \| (.+)")
LIVE_OFFSETS = {"merge": 0, "+6h": 6 * 3600, "+1d": 86400, "+7d": 7 * 86400}
LIVE_SHAPE = "not in the shape - `<command>` | from <merge|+6h|+1d> | by <+1d|+7d> | <proves>"


def live_check_bullets(text: str) -> list[dict]:
    """The `## Live checks` bullets of text as {command, from, by, proves}, from and by as seconds after Mark done.
    No section, or only `- none`, gives []. A bullet in another shape gives {command: <bullet>, from 0, by 0, proves
    "", refused: LIVE_SHAPE}, so it is stored as refused instead of vanishing."""
    out = []
    for line in (md_section(text, "Live checks") or "").splitlines():
        line = line.strip()
        if not line.startswith("- ") or line.lower() in ("- none", "- none."):
            continue
        if m := LIVE_BULLET_RE.fullmatch(line):
            out.append({"command": m[1].strip(), "from": LIVE_OFFSETS[m[2]], "by": LIVE_OFFSETS[m[3]],
                        "proves": m[4].strip()})
        else:
            out.append({"command": line[2:].strip(), "from": 0, "by": 0, "proves": "", "refused": LIVE_SHAPE})
    return out


def live_command_refusal(repo: Path, command: str) -> str | None:
    """None when a live check may run command from repo, else why not. Two shapes only: `npm run <script>[ -- <args>]`
    (prod_bullet: PROD_TOKEN_RE tokens; the script is in repo/package.json and neither its name, args nor command
    matches LIVE_DENY_RE) and `python3 <path>[ <args>]` (PROD_TOKEN_RE tokens; a relative path with no `..` part that
    git tracks in repo)."""
    if command.startswith("npm run "):
        try:
            script, args = prod_bullet(command)
        except SystemExit:
            return "not an npm run command with plain arguments"
        try:
            scripts = json.loads((Path(repo) / "package.json").read_text()).get("scripts")
        except (OSError, ValueError, AttributeError):
            return "cannot read scripts from package.json"
        if not isinstance(scripts, dict) or script not in scripts:
            return f"{script} is not a package.json script"
        if m := LIVE_DENY_RE.search(" ".join([script, *args, str(scripts[script])])):
            return f"{script} runs {m[0]}, which a live check never may"
        return None
    tokens = command.split(" ")
    if tokens[0] != "python3" or len(tokens) < 2:
        return "only npm run <script> or python3 <tracked file> may run"
    if not all(PROD_TOKEN_RE.fullmatch(t) for t in tokens[1:]):
        return "an argument holds a character other than letters, digits or = _ . : / -"
    path = tokens[1]
    if path.startswith(("/", "-")) or ".." in path.split("/"):
        return f"{path} is not a relative path inside the repo"
    r = subprocess.run(["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", path], capture_output=True,
                       timeout=60)
    return None if r.returncode == 0 else f"{path} is not a file git tracks"


def live_state(checks: list) -> str:
    """The board `liveCheck` for a live-checks.json list: failed when any check failed, else waiting while any is
    pending, else refused when any was refused, else passed."""
    states = {c.get("state") for c in checks if isinstance(c, dict)}
    return next((s for s, k in (("failed", "failed"), ("waiting", "pending"), ("refused", "refused")) if k in states),
                "passed")


def cmd_live_record(root: Path, job_id: str) -> int:
    """live-record (Merge's Mark done): write jobs/<id>/live-checks.json from decision.md's `## Live checks` section,
    else spec.md's, and set the board job's `liveCheck` (live_state) under locked_board. Each entry: command, from and
    by as epoch seconds counted from now, proves, state pending (refused, with reason, when live_command_refusal or the
    bullet shape refuses it), runs [] and done_at. Writes nothing for no section, only `- none`, a job not at stage
    done, a `merged, not live` reason, or an existing live-checks.json (a resumed Merge keeps its runs). Returns the
    number of checks recorded."""
    root = Path(root)
    d = root / "jobs" / check_id(job_id)
    path = d / "live-checks.json"
    recordable = lambda j: j.get("stage") == "done" and not str(j.get("reason") or "").startswith("merged, not live") \
        and not path.exists()
    if not recordable(find(read_board(root), job_id)):
        return 0  # no lock taken, so board.json is not rewritten
    text = ""
    for name in ("decision.md", "spec.md"):
        try:
            body = (d / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if md_section(body, "Live checks") is not None:
            text = body
            break
    bullets = live_check_bullets(text)
    if not bullets:
        return 0
    now = int(time.time())
    checks = []
    for b in bullets:
        reason = b.get("refused") or live_command_refusal(root.parent, b["command"])
        checks.append({"command": b["command"], "from": now + b["from"], "by": now + b["by"], "proves": b["proves"],
                       "state": "refused" if reason else "pending", **({"reason": reason} if reason else {}),
                       "runs": [], "done_at": now})
    with locked_board(root) as board:
        job = find(board, job_id)
        if not recordable(job):  # re-checked under the lock: a racing live-record or stage change wins
            return 0
        tmp = path.with_name("live-checks.json.tmp")
        tmp.write_text(json.dumps(checks, indent=1) + "\n")
        os.replace(tmp, path)
        job["liveCheck"] = live_state(checks)
    return len(checks)


def orchestrator_model(root: Path, job_id: str | None = None) -> str | None:
    """The `- Orchestrator model:` line of scrum/project.md: None for `inherit` (no --model), else the model.
    Missing, blank or malformed values give `sonnet`. The optional `- Big ticket model:` line wins for a big_ticket
    job; the board and backlog are only read when that line is present and valid."""
    try:
        text = (root / "project.md").read_text()
    except (OSError, ValueError):  # missing, or not UTF-8
        return "sonnet"
    big = re.search(r"^- Big ticket model: *(.*?) *$", text, re.M)
    if job_id and big and MODEL_RE.fullmatch(big.group(1)) and big_ticket(root, job_id):
        return big.group(1)
    m = re.search(r"^- Orchestrator model: *(.*)$", text, re.M)
    value = m.group(1).strip() if m else ""
    if value.lower() == "inherit":
        return None
    return value if MODEL_RE.fullmatch(value) else "sonnet"


def spawn_settings(config_dir: Path, repo: Path) -> str:
    """The --settings JSON for a headless run: NO_CACHE_TAX plus every plugin named in the account's settings.json or the
    repo's .claude/settings(.local).json turned off (job 1253: ~10k tokens a session start), read at spawn time so a newly
    installed plugin is covered too. hookify stays on while the repo has .claude/hookify.*.md rule files."""
    settings = json.loads(NO_CACHE_TAX)
    hookify = any((repo / ".claude").glob("hookify.*.md"))
    for f in (config_dir / "settings.json", repo / ".claude" / "settings.json", repo / ".claude" / "settings.local.json"):
        try:
            plugins = json.loads(f.read_text()).get("enabledPlugins")
        except (OSError, ValueError, AttributeError):  # missing, unreadable or not a JSON object
            continue
        for name in plugins if isinstance(plugins, dict) else ():
            if not (hookify and name.startswith("hookify@")):
                settings["enabledPlugins"][name] = False
    return json.dumps(settings)


class LiveSession(SystemExit):
    """spawn's refusal (job 1275): the job already has a live session, so a second one would fight it."""


class HardStop(SystemExit):
    """spawn's refusal while hard_stop holds the account it would run on (Trevor 2026-11-20), his clicks included.
    serve.spawn keeps the launch queued like a HeldStart, so play_queue_tick starts it once the stop lifts."""


class HeldStart(SystemExit):
    """spawn's hold (job 1312): a hand start of a not-yet-started job while this Mac is hot is queued as a `start` launch
    for the shop Mac (or this one once its guard clears) instead of launching."""


def queue_start(root, job_id: str, prompt: str | None = None) -> bool:
    """Leave a spec-stage job with no `shop` field queued as a `start` launch (play_queued, queued_launch), under one
    locked_board that re-reads the job; an earlier play_queued is kept. True when it is left queued, False when the job
    is gone, past spec or already shop-bound. serve.py hold_start and spawn's hold call it."""
    prompt = prompt if prompt is not None else f"/trevskills-scrum start {job_id}"
    with locked_board(root) as b:
        live = next((j for j in b["jobs"] if j["id"] == job_id), {})
        if live.get("stage") != "spec" or live.get("shop"):
            return False
        live.setdefault("play_queued", now())
        live.setdefault("queued_launch", {"action": "start", "prompt": prompt, "stage": "spec"})
        return True


EDIT_MCP = {"edit-vector": ("vectorcraft", "~/.local/bin/vectorcraft-cli", ["mcp"]),
            "edit-photo": ("photocraft", "/Applications/PhotoCraft.app/Contents/MacOS/photocraft-cli", ["mcp"])}


def edit_mcp_config(root: Path, kind: str) -> Path | None:
    """Job 1365: write `<root>/runs/mcp-<kind>.json` with the one MCP server an edit-vector or edit-photo job needs and
    return its path; None for any other kind. The entry is `mcpServers.<name>` of the primary account's
    `Path.home()/.claude.json` (never CLAUDE_CONFIG_DIR), else the default command; only type, command and args are
    copied, never `env`, so no secret reaches the file."""
    if kind not in EDIT_MCP:
        return None
    name, command, args = EDIT_MCP[kind]
    command = os.path.expanduser(command)
    server = {"type": "stdio", "command": command, "args": list(args)}
    try:
        entry = json.loads((Path.home() / ".claude.json").read_text())["mcpServers"][name]
        if isinstance(entry.get("command"), str) and entry["command"] and isinstance(entry.get("args", []), list) \
                and all(isinstance(a, str) for a in entry.get("args", [])):
            server = {"type": "stdio", "command": entry["command"], "args": list(entry.get("args", []))}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    path = Path(root) / "runs" / f"mcp-{kind}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"mcpServers": {name: server}}, indent=2) + "\n")
    return path


# Job 1469: tools no scrum session uses (headless ScheduleWakeup dies with the process; scrum runs no Workflow, review
# findings go to files). Dropping their schemas cuts ~5k tokens from every turn's re-read, measured with `claude -p`.
UNUSED_TOOLS = ("ReportFindings", "ScheduleWakeup", "Workflow", "ListAgents")


def spawn(root: Path, job_id: str, action: str, prompt: str | None = None, flags=("--permission-mode", "acceptEdits"),
          model: str | None = None, account: str | None = None, nice: int = SESSION_NICE,
          caller: int | None = None, hot_hold: bool = True) -> tuple[subprocess.Popen, str]:
    """Start `claude -p <prompt> <flags>` in the repo, detached, logging to scrum/runs/, and set the job's runlog and account.
    A job on the board whose session reads alive (session_alive_fn, ps unreadable counting as alive) launches nothing:
    LiveSession (a SystemExit) names it. `caller` (`B spawn`'s caller_claude_pid) is left out of that scan, so the job's
    own session may hand it off (a lilguy hand-off, a cloud-home auto-migrate). A job not on the board is never checked.
    start/resume/run-all/cloud-home/rework/approve get `--model <Orchestrator model>` (or `<Big ticket model>`, see orchestrator_model) unless `model` is given.
    `account` None: pick_account, preferring the job's recorded account; with none free, the one whose limit ends soonest
    (the recorded account on a tie), else the first (Trevor's Play and Resume are never refused on usage). Any account but the first runs with
    CLAUDE_CONFIG_DIR=<its dir>; the first runs with CLAUDE_CONFIG_DIR removed. The session runs at `nice` (SESSION_NICE;
    the UI sweep passes 19). `flags` without their own get --strict-mcp-config and --settings spawn_settings(...); a job
    whose job_lane is not lilguy runs with CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 and CLAUDE_CODE_DISABLE_AUTO_MEMORY=1, and `flags` without --disallowedTools get UNUSED_TOOLS. With `hot_hold` (the `B spawn` CLI passes
    False), a `start` of a board job at stage spec with no `shop` field launches nothing while hand_hold(root) gives a
    reason, or heavy_cap_reason(root, job) gives one (job 1314: a heavy job at this Mac's heavy cap): queue_start queues it
    and HeldStart (a SystemExit) says so (job 1312). Returns (proc, log path relative to root)."""
    root = Path(root)  # a chat hand-off passes a str
    if not SPAWN_ID_RE.fullmatch(job_id):
        raise SystemExit(f"bad spawn id {job_id!r}")
    if not SPAWN_ACTION_RE.fullmatch(action):
        raise SystemExit(f"bad spawn action {action!r}")
    if model is not None and not MODEL_RE.fullmatch(model):
        raise SystemExit(f"bad model {model!r}; must match {MODEL_RE.pattern}")
    if model is None and action in ("start", "resume", "run-all", "cloud-home", "rework", "approve"):  # job 1261: run-all and cloud-home no longer run on the CLI default Opus; job 1344: rework and approve too
        model = orchestrator_model(root, job_id)
    prompt = prompt if prompt is not None else f"/trevskills-scrum {action} {job_id}"
    accs = accounts()
    try:
        job = find(read_board(root), job_id)
    except (SystemExit, OSError):  # not on the board (run-all, digest, weekly), or no board yet
        job = {}
    if job and session_alive_fn(skip=({caller} | ancestor_pids()) if caller else None)(job):  # job 1329: caller's whole tree  # job 1275: two sessions on one job fight over its worktree
        pid = job.get("pid") if job.get("pid") != caller else None  # the caller's own pid is not the live one
        raise LiveSession(f"job {job_id} already has a live session (pid {pid or 'unknown'})")
    if hot_hold and action == "start" and job.get("stage") == "spec" and not job.get("shop") \
            and (why := hand_hold(root) or heavy_cap_reason(root, job)) and queue_start(root, job_id, prompt):
        raise HeldStart(f"job {job_id} queued, not started on this Mac: {why}; the shop Mac takes it when a worker has "
                        "room, else it starts here once this Mac's guard clears")
    if account is None:
        recorded = job.get("account")
        if recorded and str(job.get("reset") or "").isdigit() and time.time() >= int(job["reset"]):
            recorded = None  # its seven_day window reset since: fallback_account no longer favours it
        # job 1184: never prefer the recorded account, so a restart takes the primary whenever it has room
        account = pick_account(time.time())[0] or fallback_account(time.time(), recorded)
    acc = next((a for a in accs if a.name == account), accs[0])  # an unlisted account (its dir gone) runs on the first
    if why := hard_stop(acc.name, time.time()):
        raise HardStop(f"job {job_id} not started: {why}")
    env = dict(os.environ, CLAUDE_NOTIFIER_DISABLE="1",  # board.py plays scrum's sounds
               CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0")  # -p kills background agents 10 min after the last turn otherwise
    env.pop("CLAUDE_CONFIG_DIR", None)
    env["SCRUM_SPAWN"] = "1"  # job 1261: lilguy-fit tells a spawn session from Trevor's interactive one
    if acc != accs[0]:
        env["CLAUDE_CONFIG_DIR"] = str(acc.dir)
    if job_lane(root, job) == "lilguy":  # its orchestrator writes the code, so it keeps CLAUDE.md and the rules
        env.pop("CLAUDE_CODE_DISABLE_CLAUDE_MDS", None)  # a Run-all parent's own setting is inherited otherwise
        env.pop("CLAUDE_CODE_DISABLE_AUTO_MEMORY", None)  # job 1481: so is its memory setting (a spawned session sets it)
    else:  # job 1253: every other orchestrator writes no code; CLAUDE.md, rules and AGENTS.md cost ~30k tokens a start
        env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] = "1"
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"  # job 1469: the memory index (~0.7k tokens) is never used by an orchestrator
    logs = root / "runs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{action}-{job_id}.log"
    mcp = None  # job 1365: edit-vector and edit-photo jobs load their one MCP server
    if "--mcp-config" not in flags:
        try:
            kind = job.get("kind") or edit_kind((root / "jobs" / job_id / "feature.md").read_text(errors="replace"))
        except OSError:
            kind = None
        mcp = edit_mcp_config(root, kind) if kind else None
    argv = [CLAUDE, "-p", prompt, *(("--model", model) if model else ()), *flags,
            *(() if "--strict-mcp-config" in flags else ("--strict-mcp-config",)),  # job 1253: no MCP server loads
            *(("--mcp-config", str(mcp)) if mcp else ()),
            *(() if "--settings" in flags else ("--settings", spawn_settings(acc.dir, root.parent))),
            *(() if {"--disallowedTools", "--disallowed-tools"} & set(flags) else ("--disallowedTools", *UNUSED_TOOLS))]  # job 1469
    try:
        with open(log, "w") as fh:
            proc = subprocess.Popen(argv, cwd=root.parent,
                                    stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                                    env=env)
    except OSError:  # never started (e.g. the claude CLI missing mid-update): no empty log that reads like a dead session
        log.unlink(missing_ok=True)
        raise
    try:  # job 958: below Trevor's apps (its tools inherit it); not taskpolicy -b, which pins to the efficiency cores
        os.setpriority(os.PRIO_PROCESS, proc.pid, nice)
    except (OSError, TypeError):  # already exited, or a test's mock pid
        pass
    proc.account = acc.name  # the account the session really runs on; serve.spawn records it in RUNS
    try:  # the run log link reads this; a job that isn't on the board (run-all, digest) has no row to set
        cmd_set(root, job_id, [f"runlog=runs/{log.name}", "tty=", "outcome=", f"account={acc.name}", f"reset={seven_day_reset(acc.name)}"], unpause=True, spawn_pid=proc.pid)  # Play starts on a paused job; a stale interactive tty would still match the hook and liveness checks
    except SystemExit:
        pass
    return proc, f"runs/{log.name}"


if __name__ == "__main__":
    sys.exit(main())
