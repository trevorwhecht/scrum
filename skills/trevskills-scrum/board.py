#!/usr/bin/env python3
"""The scrum team's board. Only the /trevskills-scrum orchestrator calls this; nothing else writes board.json.

  board.py new "<title>" [--id ID] [--by <serve|runall|wake|hand>] create jobs/<id>/ and a board entry, print the id (--id keeps a given id; --by records who started it, default hand)
  board.py set <id> key=value ...  set stage/round/limit/pr/reason/worktree/builder/base/tty/runlog/lane/setup/waiting/specwriter/cloud/outcome (empty = null);
                                   stage=needs-human is refused: park a job with ask
  board.py set --unpause <id> ...  the same, on a job Trevor paused too (resume and rework only); with stage= it
                                   clears the pause
  board.py ask <id> "<q>" --a "Label=command" --b "Label=command" [--c ...] --title TITLE [--recommend KEY WHY]  park
                                   the job at needs-human with a closed question (command: approve|resume|abort <id>
                                   [--requeue|--cascade], rework <id> "<text>", shell: <cmd>), log it to questions.log;
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
  board.py sync <id>               re-read jobs/<id>/ into the board, print round status as JSON
  board.py next                    claim the first "- [ ]" backlog item that waits on no {needs #id} prerequisite and
                                   no {setup: …} Human setup as a new job, print {"id","feature"}
  board.py cloud-claim <N>         claim up to N open backlog items for the Cloud lane, skipping any that waits
                                   (prerequisite or Human setup), has no pre-written spec with Likely files, or shares a
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
  board.py rank-backlog [--all]    Jev rates each open backlog item with no {p:N} marker, or every open item with --all
                                   (jev-gate.py rank, plus critical for an agent "Critical:" item, logged to jev.log), writes
                                   the source-capped {p:N} where it changed, print {"rated","unrated","skipped"}
  board.py manual-add "<item>"...  append "- [ ] <item>" lines to manual-checks.md (human-only checks; open duplicates
                                   and empty items are skipped), print the added texts as JSON
  board.py backlog-spec <id>       ingest jobs/<id>/followups/*.md: add or match backlog items, store each spec in
                                   backlog-specs/ (moved to the job's spec.md when claimed), print {"added","updated","skipped"};
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
  board.py cooldown-park <id>      while cooling down, stall a round-0 spec/build job at this checkpoint (serve.py resumes
                                   it after cool down); print {"parked": bool}
  board.py dev-clear <id>          stop every server listening from inside the job's .claude/worktrees/ worktree (TERM,
                                   up to 5 s, then KILL), print {"killed": [pids]}
  board.py digest-due              print {"due","undigested","questionsGrowth","reason"}: done jobs in no digests/*/jobs.txt
                                   and questions.log lines since the last digest's questions.lines; due at 10+ jobs ("10
                                   done"), 15+ lines ("questions"), or 3+ jobs and a bad windows/ scorecard (wasted >20%,
                                   or first pass <0.5 over 3+ jobs) no digests/*/windows.txt lists, written after the
                                   newest digest folder ("bad window <file>"); reason null when not due
  board.py digest-start            claim them all as digests/<NNN>/jobs.txt (+ questions.lines), and every windows/
                                   scorecard no live digest lists as windows.txt + windows.json, plus timing.md (per-job wall
                                   time, rounds, no-change rounds, E2E lock waits; jobs waiting on the E2E queue),
                                   and escapes.md (each debug job's origin job by git blame, with its PASS reviewers),
                                   print {"id","jobs","windows"}
                                   (id null = nothing new; starts with no jobs when the questions trigger fired); then a
                                   pipeline health check parks one "Pipeline health: <tool>" job at needs-human per tool
                                   (codex-review, review-e2e, check) that failed in half the claimed jobs (2+)
  board.py digest-trim <NNN>       cut that digest's done job folders to feature.md, spec.md, decision.md
  board.py pipeline-fit <NNN>      print {"digest","jobs"}: each listed job's lane, agents, diff size, verdicts, fix rounds
                                   and whether a cheaper lane would have done (read-only; Digest step 1)
  board.py digest-trevor <NNN>     write digests/<NNN>/trevor.md (Trevor's Jev-ranked chat messages, feature.md quotes,
                                   new (Trevor …) backlog tags, answer notes since the last digest), print
                                   {"id","chat","quotes","backlog","notes"}; a failed source is a one-line note
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
                                   lanes/newjob.md Check gate step 2)
  board.py render-paths <id>       print {"paths","skipped"}: the app paths the diff's UI runtime files render, at most 8,
                                   dynamic routes skipped, ["/"] when none maps (lanes/review.md step 2 Shared render)
  board.py check-reuse <id>        print {"reused"}: copy round-(n-1)'s CHECK: PASS into round-n/check.md when HEAD equals
                                   round-(n-1)/head.txt, else null (Check gate step 1)
  board.py move-ratio <id>         print {"added","moved","ratio"}: the share of the job worktree's BASE...HEAD added lines
                                   git marks as moved (SKILL.md Review MOVE_ONLY); else exit 1 and print {"ok": false, "error"}
  board.py lilguy-fit <id>         print {"fit","why"}: whether the job is tiny (backlog points 1, or jev.log's last model
                                   answer score < 1.5 at confidence >= 0.7) with no hard-stop word in feature.md
                                   (SKILL.md New job step 3's Lilguy route)
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
  board.py ready <id>              claim the bigboy parent's startable children (stage -> spec; gated by machine_ok, free RAM
                                   per batch and the file-overlap rules), print
                                   {"ready","merged","total","in_progress","all_merged"}
  board.py runall-start           make a Run-all parent with every open backlog item as a waiting child (needs become
                                   depends_on; items waiting on an outside job or on Human setup stay open), print {"id","children"}
                                   (id null = nothing to claim); `ready <id>` then schedules them
  board.py chain-lock <id> <holder> [--wait S]  take the bigboy parent's jobs/<id>/.chain.lock (poll 2 s, up to S,
                                   default 540; stale after 1800 s), print {"acquired","holder"}
  board.py chain-unlock <id> <holder>  remove that lock if holder holds it, print {"released"}
  board.py watchdog                flag jobs stuck 30+ min in spec/build/check/review/approve with no live session:
                                   kept in their stage with `stalled` true (reason "stalled: ..."), print {"flagged"};
                                   a stuck spec job with no feature.md is an orphaned claim: aborted and requeued, never flagged
  board.py cloud-sync              move each stage-cloud job whose [scrum <id>] PR finished (one gh REST pulls call):
                                   MERGED -> done, CLOSED -> aborted + requeued, open + scrum:needs-human -> needs-human with
                                   the PR comment's reason and a fetched worktree (a requeue:/obsolete:/looks already
                                   fixed: reason aborts it and closes the PR instead); only a same-repo scrum/<id> head PR and
                                   its author's comments count. A moved job with no scrum-artifacts/<id> branch yet is
                                   re-checked each run and keeps its mark until cloud-home starts, or until 24 h pass
                                   with no branch; print {"moved","arrived","error"}, exit 1 on a gh error (nothing
                                   changed). serve.py runs it every 10 min while a job is in stage cloud
  board.py spawn <id> <action> ["<prompt>"] [--model M]  start a detached headless `claude -p <prompt>` (default
                                   "/trevskills-scrum <action> <id>") from the repo, logging to runs/; start/resume get the
                                   Orchestrator model unless --model; set the job's runlog (ignored when <id> is not on the
                                   board), print {"log","pid"}
  board.py hook                    Claude Code hook: read one event from stdin, set or clear `waiting` on this tty's job
  board.py fable-ok <id> <planner|spec-writer>  print the Agent model override (claude-fable-5-1) or none: the planner, or
                                   the spec-writer on lane standard (or unset), of a complex job (header `Complex: yes`
                                   in feature.md, else spec.md) gets Fable only while fable_state is ok; each such call
                                   appends a line to jobs/<id>/fable.log
  board.py prod-ok <id> '<bullet>'  gate one decision.md `## Prod runs` bullet: print dev or ok, else exit non-zero
                                   (schema/deploy/fixture scripts always; a :prod run without a passing dev dry run
                                   and apply recorded in jobs/<id>/prod.md)
  board.py statusline              Claude Code status line: save stdin's rate_limits to <CLAUDE_CONFIG_DIR or ~/.claude>/usage.json, print "5h N% · 7d N%"

Verdicts are never typed in by hand: sync derives them from the first line of each file, so the board can't drift
from the files. --dir points at the project's scrum/ folder (default ./scrum).
"""
import argparse, fcntl, hashlib, importlib.util, json, os, re, secrets, shlex, shutil, signal, socket, string, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

REVIEWERS = ("security", "ux", "ui", "code")
FABLE_MODEL = "claude-fable-5-1"  # fable-ok: the planner and standard spec-writers of complex jobs, in the ok band only
FABLE_WARN_5H_PCT = 65  # used % at which Fable is near its limit: fable-ok answers none, the weekly digest keeps Fable
FABLE_WARN_7D_PCT = 75
FABLE_SWITCH_5H_PCT = 80  # used % at which fable-ok answers none (frontmatter Opus) until the window resets
FABLE_SWITCH_7D_PCT = 85
STAGES = ("plan", "running", "waiting", "spec", "build", "check", "review", "approve", "merging", "deploying", "done",
          "needs-human", "aborted", "cloud")  # cloud: running in a claude.ai/code session (SKILL.md Cloud lane); never WATCHED
FIELDS = ("stage", "round", "limit", "pr", "reason", "worktree", "builder", "base", "tty", "runlog", "lane", "setup",
          "waiting", "specwriter", "cloud", "outcome", "account")  # the `waiting` field (paused on Trevor) is unrelated to the bigboy "waiting" stage
ACTIVE = ("spec", "build", "check", "review", "approve", "merging", "deploying")  # stages an interactive session can pause in
# Where the job's terminal and run log are: both are matched or read by path, so they're strict.
SHAPES = {"tty": re.compile(r"^ttys[0-9]+$"), "runlog": re.compile(r"^runs/[\w.-]+\.log$"),
          "lane": re.compile(r"^(?:fast|standard|debug|bigboy|runall|lilguy)$"),  # no lane key = standard
          "setup": re.compile(r"^(?:pending|done)$"),  # a bigboy child's Human setup wait
          "account": re.compile(r"^[a-z0-9-]{1,20}$"),  # the accounts() name board.spawn ran the session on
          "cloud": re.compile(r"^https://claude\.ai/code/session_[A-Za-z0-9_-]+$")}  # the dashboard links it
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
}

# The scrum commands a needs-human question's option may run (shape only: the id need not be the asked job's).
ASK_COMMAND_RE = re.compile(r'(?:(?:approve|resume|lilguy|apply) {id}|abort {id}(?: --requeue| --cascade)?|rework {id} "[^"]+"'
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


STARTED_BY = ("serve", "runall", "wake", "hand")  # a job's started_by: who started it (write_pulse's cool-down claims skip hand)


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


def cmd_new(root, title, job_id=None, unique=False, started_by="hand"):
    """unique: return None, adding nothing, while a job with this exact title is neither done nor aborted."""
    with locked_board(root) as board:
        if unique and any(j["title"] == title and j["stage"] not in ("done", "aborted") for j in board["jobs"]):
            return None
        return add_job(root, board, title, job_id, started_by)


# --- backlog.md: "- [ ] [5] Text {#k3f9} {p:4} {needs #a1b2} {setup: step; step} {by:t} → 003-id <!-- why -->"; points, the id,
# priority (1-5, highest claimed first), needs, setup and source markers, the job and the estimate's reason are optional.
# The source marker is {by:t} (Trevor's item) or {by:back} (Trevor's, back of the backlog); no marker means an agent item.
# An item's text excludes the markers, so its spec_path never changes. A setup marker is a Human setup checklist: next and runall-start skip the item until Setup done. ---
FIB = (1, 2, 3, 5, 8, 13)
ITEM_RE = re.compile(r"^- \[( |x)\] (?:\[(\d+|\?)\] )?(.*?)(?: \{#([a-z0-9]{4})\})?(?: \{p:([1-5])\})?(?: \{needs((?: #[a-z0-9]{4})+)\})?"
                     r"(?: \{setup: ([^{}]*)\})?(?: \{by:(t|back)\})?(?: → (\d{3,}-[a-z0-9-]+))?(?: <!-- (.*?) -->)?\s*$")
ID_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
KEEP = object()
ITEM_MAX = 2000  # backlog item text; long enough that a triage merge keeps every original requirement


def clean(text, limit=300):
    return re.sub(r"\s+", " ", str(text).replace("<!--", "").replace("-->", "")).strip()[:limit]


def read_backlog(root):
    """(lines, items). Items remember their line so writes leave headings and notes alone."""
    path = Path(root) / "backlog.md"
    lines = path.read_text().splitlines() if path.exists() else ["# Backlog"]
    items = []
    for n, line in enumerate(lines):
        if m := ITEM_RE.match(line):
            done, pts, text, item_id, prio, needs, setup, by, job, why = m.groups()
            items.append({"index": len(items), "line": n, "done": done == "x",
                          "points": int(pts) if pts and pts.isdigit() else None, "text": text.strip(), "why": why, "job": job,
                          "id": item_id, "priority": int(prio) if prio else None, "needs": needs.replace("#", "").split() if needs else [],
                          "setup": [s.strip() for s in setup.split(";") if s.strip()] if setup else [], "by": by})
    return lines, items


def format_item(item):
    return (f"- [{'x' if item['done'] else ' '}] " + (f"[{item['points']}] " if item["points"] else "") + item["text"]
            + (f" {{#{item['id']}}}" if item.get("id") else "")
            + (f" {{p:{item['priority']}}}" if item.get("priority") else "")
            + (" {needs " + " ".join(f"#{n}" for n in item["needs"]) + "}" if item.get("needs") else "")
            + (" {setup: " + "; ".join(item["setup"]) + "}" if item.get("setup") else "")
            + (f" {{by:{item['by']}}}" if item.get("by") else "")
            + (f" → {item['job']}" if item["job"] else "") + (f" <!-- {item['why']} -->" if item["why"] else ""))


def new_item_id(items):
    """4 random [a-z0-9] chars that no item in `items` carries as its id."""
    taken = {i.get("id") for i in items}
    while (new := "".join(secrets.choice(ID_CHARS) for _ in range(4))) in taken:
        pass
    return new


def waiting_on(item, items, board):
    """The ids in item's needs that still block it: a line with that id is open, or is claimed by a job whose board
    stage is not done or aborted. An id no line carries, a closed line with no job, or a job missing from the board
    does not block."""
    if not item["needs"]:
        return []  # most items: skip building the board's stage map
    stage = {j.get("id"): j.get("stage") for j in board.get("jobs") or []}
    blocks = lambda i: not i["done"] or (i["job"] in stage and stage[i["job"]] not in ("done", "aborted"))
    return [n for n in item["needs"] if any(i["id"] == n and blocks(i) for i in items)]


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
    above the current priority (unmarked counts as 2.5, as priority_key does), else changes nothing."""
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
                                "setup": None if setup is None else setup_steps(setup), "by": by, "id": new_item_id(items)})
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


def cmd_rank_backlog(root, all_items=False) -> dict:
    """Rate open backlog items with jev-gate's rank step (unmarked ones, or every one with all_items) outside the lock,
    plus its critical step for an agent item whose text starts with "Critical:"; back items get no Jev call. Then, under
    one lock, re-read backlog.md and write source_priority on the first open item with the same text and source (and
    still unmarked without all_items), only when it changed. A none rank, or an item gone or edited meanwhile, is left
    byte for byte."""
    # jev-gate.py has a hyphen, so no plain import; loaded only here
    spec = importlib.util.spec_from_file_location("jev_gate", Path(__file__).resolve().with_name("jev-gate.py"))
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
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


def spec_path(root, text):
    """Where a backlog item's pre-written spec waits, keyed by its stored text."""
    return Path(root) / "backlog-specs" / (hashlib.sha1(text.encode()).hexdigest()[:12] + ".md")


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


def claim_item(lines, item, job_id):
    """Mark one backlog item claimed by job_id in lines. Caller holds the lock and writes the backlog once."""
    item["done"], item["job"] = True, job_id
    lines[item["line"]] = format_item(item)


def cmd_next(root, index=None):
    """Claim the highest-priority open backlog item (or item `index`) as a new job, under the lock, so no two sessions share one.
    Cool-down refuses the automatic claim (no index); an explicit index is Trevor's Run now and still claims."""
    if index is None and cooling_down():
        raise SystemExit(COOLING_CLAIM)
    with locked_board(root) as board:
        lines, items = read_backlog(root)
        if index is None:
            item = next((i for i in sorted(items, key=priority_key) if not i["done"] and not i["setup"] and not waiting_on(i, items, board)), None)
            if item is None:
                return {"id": None, "feature": None}
        else:
            item = pick(items, index)
            if item["done"]:
                raise SystemExit(f"backlog item {index} is already claimed")
            if item["setup"]:
                raise SystemExit(f"backlog item {index} waits on Human setup")
            if waits := waiting_on(item, items, board):
                raise SystemExit(f"backlog item {index} waits on " + ", ".join(f"#{n}" for n in waits))
        job_id = add_job(root, board, short_title(item["text"]), started_by="runall" if index is None else "hand")
        take_spec(root, item["text"], job_id)
        claim_item(lines, item, job_id)
        write_backlog(root, lines)
        return {"id": job_id, "feature": item["text"]}


def cmd_cloud_claim(root, n) -> dict:
    """Claim up to n open backlog items for cloud sessions, in priority order (priority_key), under one lock and one backlog write.
    An item is skipped (left open) when it waits on a prerequisite or Human setup, has no pre-written spec with readable Likely files,
    or shares a Likely file with an item claimed in this call or with a board job in stage cloud or build, or in stage spec
    carrying cloudClaim (claimed here, not yet moved to cloud). Such a job with no readable Likely files may touch
    anything, so it blocks every item."""
    if n < 1:
        raise SystemExit("N must be at least 1")
    if cooling_down():  # cool-down: no new backlog claim
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
            if item["done"] or item["setup"] or waiting_on(item, items, board):
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
            jobs = {j["id"]: j for j in board["jobs"]}
            for gone in aborted:  # grows while it runs: each aborted dependent is followed in turn
                for kid in board["jobs"]:
                    if gone in (kid.get("depends_on") or []) and kid["stage"] not in ("done", "aborted") \
                            and (kid["stage"] in ("waiting", "needs-human") or kid.get("paused") or kid.get("play_queued")
                                 or stalled(kid)):
                        parent = jobs.get(kid.get("parent")) or {}
                        abort_job(root, kid, parent.get("lane") == "runall", f"Removed with {job_id}")
                        aborted.append(kid["id"])
    return aborted


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
    if requeue:
        requeue_job(root, job, folder, feature)
    job["files"] = job_files(folder)  # after the spec move, so it never names a file that left the folder


def requeue_job(root, job, folder, feature):
    lines, items = read_backlog(root)
    claimed = next((i for i in items if i["job"] == job["id"]), None)
    if claimed and not feature.exists():
        claimed.update(done=False, job=None)
        lines[claimed["line"]] = format_item(claimed)
        if (folder / "spec.md").is_file():
            spec_path(root, claimed["text"]).parent.mkdir(exist_ok=True)
            os.replace(folder / "spec.md", spec_path(root, claimed["text"]))
    else:
        text = clean(feature.read_text() if feature.exists() else job["title"], ITEM_MAX) or job["title"]
        lines.append(format_item({"done": False, "points": None, "text": text, "job": None, "why": None}))
    write_backlog(root, lines)


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
    under the add's lock); skipped items are left out of the result."""
    check_source(by, priority, top, critical)
    if setup is not None:
        setup_steps(setup)
    check_priority(priority)
    added = []
    for item in items:
        if clean(item):
            if backlog_op(root, "add", text=item, setup=setup, priority=priority, top=top, by=by, critical=critical,
                          unless_open=unless_open) is not None:
                added.append(clean(item, ITEM_MAX))
    return added


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


def parse_followup(text):
    """(kind, item text, body) for one followups/*.md file; raises ValueError with the reason when malformed."""
    lines = text.splitlines()
    head = lines[0].strip() if lines else ""
    if head == "Backlog: new":
        m = re.match(r"^Item:\s*(.*)$", lines[1].strip() if len(lines) > 1 else "")
        if not m or not m.group(1).strip():
            raise ValueError("second line is not 'Item: <text>'")
        kind, item, rest = "new", m.group(1).strip(), lines[2:]
    elif (m := re.match(r"^Backlog: update\s+(\S.*)$", head)):
        kind, item, rest = "update", m.group(1).strip(), lines[1:]
    else:
        raise ValueError("first line is not 'Backlog: new' or 'Backlog: update <text>'")
    body = "\n".join(rest).strip("\n")
    if not body.strip():
        raise ValueError("spec body is empty")
    return kind, item, body + "\n"


def cmd_backlog_spec(root, job_id):
    """Ingest jobs/<id>/followups/*.md under the lock: each file adds an item (or matches an open one by exact text)
    and stores its spec at spec_path. Appends lines itself: backlog_op would flock .board.lock again and deadlock."""
    folder = Path(root) / "jobs" / check_id(job_id) / "followups"
    out = {"added": [], "updated": [], "skipped": []}
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
            if kind == "update" and any(not i["done"] and i["text"] == text for i in items):
                out["updated"].append(text)
            else:
                text = clean(text + f" (from {job_id})", ITEM_MAX)
                lines.append(format_item({"done": False, "points": None, "text": text, "job": None, "why": None}))
                out["added"].append(text)
            specs[text] = body
        if not specs:
            raise SystemExit(f"backlog-spec {job_id}: no usable followups/*.md; backlog.md was not touched")
        if out["added"]:
            write_backlog(root, lines)
        for text, body in specs.items():
            path = spec_path(root, text)
            path.parent.mkdir(exist_ok=True)
            path.write_text(body, encoding="utf-8")
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
QUESTIONS_DIGEST_LINES = 15  # a digest is also due once questions.log grew this many lines since the last one
BAD_WASTED_PCT = 20  # a window scorecard is bad above this wasted_pct
BAD_FIRST_PASS = 0.5  # ... or below this first_pass_rate, once it has BAD_MIN_JOBS done jobs
BAD_MIN_JOBS = 3
EARLY_DIGEST_MIN = 3  # a bad window brings the digest forward once this many done jobs are undigested
WINDOW_FILE_RE = re.compile(r"(five_hour|seven_day)-\d+\.json")


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
    """Number of newline bytes in <scrum>/questions.log; 0 when it is missing."""
    path = Path(root) / "questions.log"
    return path.read_bytes().count(b"\n") if path.is_file() else 0


def questions_growth(root):
    """questions.log lines added since the newest digest with an integer questions.lines and no error.md, floored at 0.
    With no such digest, the whole line count."""
    d = Path(root) / "digests"
    for p in sorted((x for x in d.iterdir() if DIGEST_RE.fullmatch(x.name)), reverse=True) if d.is_dir() else []:
        try:
            if not (p / "error.md").exists() and re.fullmatch(r"\d+", text := (p / "questions.lines").read_text().strip()):
                return max(questions_lines(root) - int(text), 0)
        except (OSError, UnicodeDecodeError):
            pass
    return questions_lines(root)


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
    reason = "10 done" if n >= 10 else "questions" if growth >= QUESTIONS_DIGEST_LINES else None
    if reason is None and n >= EARLY_DIGEST_MIN and (name := early_window(root)):
        reason = f"bad window {name}"
    return {"due": reason is not None, "undigested": n, "questionsGrowth": growth, "reason": reason}


def cmd_digest_start(root):
    """Claim every undigested done job as digest NNN, under the lock, so two triggers never share a job. Also starts
    with no jobs when questions.log grew QUESTIONS_DIGEST_LINES since the last digest; questions.lines records its count.
    Also claims every valid windows/ scorecard no live digest lists: names to windows.txt, contents to windows.json."""
    with locked_board(root) as board:
        jobs = undigested(root, board)
        if not jobs and questions_growth(root) < QUESTIONS_DIGEST_LINES:
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
    """The serve.py watchdog's pulse log (one JSON line a tick), beside projects.json (SCRUM_REGISTRY moves both)."""
    return registry_path().parent / "pulse.log"


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


def _hand_started(cache, name, n):
    """True when project `name`'s board job numbered n has started_by "hand". A project not in projects(), an
    unreadable board or a missing job is not hand, so write_pulse still counts its claim. cache: {name: board jobs}."""
    if name not in cache:
        try:
            cache[name] = read_board(projects()[name] / "scrum")["jobs"]
        except (KeyError, OSError, ValueError, SystemExit):
            cache[name] = []
    return any(j.get("started_by") == "hand" for j in cache[name]
               if (m := re.match(r"(\d+)-", str(j.get("id")))) and int(m.group(1)) == n)


def write_pulse(root, digest_id):
    """digests/<NNN>/pulse.md: pulse.log totals since the last digest (_pulse_since), one line = one minute. Idle with
    claimable work (no session, no cool-down, some project with claimable work and Auto continue on (`auto`; a line
    without it is off) or waiting work), idle held (no session, some claimable or waiting work, not idle: Auto continue
    off or cool-down), peaks, claims (each job number in a rise of a project's top job number) during cool-down, less
    jobs started_by hand (_hand_started), or at CPU load over 500%, and minutes the focus project had claimable work
    while another project was busy."""
    since = _pulse_since(root, digest_id)
    lines = [l for l in _json_lines(pulse_path()) if is_num(l.get("t")) and (since is None or l["t"] >= since)]
    out = [f"# Pulse: digest {digest_id}", ""]
    if not lines:
        out.append("No pulse lines since the last digest.")
    else:
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="minutes")
        projs = lambda l: {k: v for k, v in (l.get("projects") if isinstance(l.get("projects"), dict) else {}).items()
                           if isinstance(v, dict)}
        pos = lambda v: is_num(v) and v > 0
        idle = held = streak = longest = nonfocus = 0
        for l in lines:
            ps = projs(l)
            if l.get("sessions") == 0 and not l.get("cooldown") and any(
                    (pos(p.get("claimable")) and p.get("auto") is True) or pos(p.get("waiting")) for p in ps.values()):
                idle, streak = idle + 1, streak + 1
                longest = max(longest, streak)
            else:
                streak = 0
                held += l.get("sessions") == 0 and any(pos(p.get("claimable")) or pos(p.get("waiting")) for p in ps.values())
            f = l.get("focus") if isinstance(l.get("focus"), str) else None
            if pos(ps.get(f, {}).get("claimable")) and any(p.get("busy") is True for k, p in ps.items() if k != f):
                nonfocus += 1
        cool, hot, claimed, boards = 0, 0, {}, {}
        for a, b in zip(lines, lines[1:]):
            pa, pb = projs(a), projs(b)
            for name, p in pb.items():
                was, top = pa.get(name, {}).get("top"), p.get("top")
                if name in pa and was is None:
                    was = 0  # no jobs yet: the first job is a claim
                if not (is_num(was) and is_num(top) and top > was):
                    continue
                if b.get("cooldown") is True:
                    for n in range(int(was) + 1, int(top) + 1):
                        if not _hand_started(boards, name, n):
                            cool += 1
                            claimed.setdefault(name, []).append(str(n))
                if is_num(b.get("cpu_load")) and b["cpu_load"] > 500:
                    hot += top - was

        def peak(key):
            nums = [l for l in lines if is_num(l.get(key))]
            return max(nums, key=lambda l: l[key]) if nums else None
        s, c = peak("sessions"), peak("cpu_load")
        focus = next((l["focus"] for l in reversed(lines) if isinstance(l.get("focus"), str)), "none")
        out += [f"Window: {iso(lines[0]['t'])} to {iso(lines[-1]['t'])} · ticks: {len(lines)}",
                f"Idle with claimable work: {idle} min (longest stretch {longest} min)",
                f"Idle held by Auto continue off or cool down: {held} min",
                f"Peak sessions: {s['sessions']} at {iso(s['t'])}" if s else "Peak sessions: unknown",
                f"Peak CPU load: {c['cpu_load']:.0f}% at {iso(c['t'])}" if c else "Peak CPU load: unknown",
                f"Claims during cool down: {cool}"
                + (" — " + ", ".join(f"{n} {' '.join(v)}" for n, v in claimed.items()) if claimed else ""),
                f"Claims while CPU load over 500%: {hot}",
                f"Non-focus work while focus had claimable work: {nonfocus} min (focus: {focus})"]
    (Path(root) / "digests" / digest_id / "pulse.md").write_text("\n".join(out) + "\n")


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
    return not ORCH_REVIEW_RE.fullmatch(text) and FAST_STUB not in text


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


def _fit_job(root, job_id: str, job: dict, globs) -> dict:
    """One pipeline-fit row for job_id (its board entry `job`, {} when gone): lane, agents spawned, diff size,
    verdicts per round, fix rounds, over_routed and the cheapest lane that would have done."""
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
    over = (lane in ("standard", "debug") and "1" in verdicts and set(verdicts["1"].values()) == {"PASS"}
            and size is not None and size <= FAST_MAX_LINES and files <= FAST_MAX_FILES
            and paths is not None and _promote_trigger(*paths) is None
            and not (globs and any(glob_match(n, globs) for n in paths[1])))
    fit = ("lilguy" if size <= LILGUY_MAX_LINES and files <= LILGUY_MAX_FILES else "fast") if over else lane
    return {"id": job_id, "lane": lane, "agents": agents, "added": added, "deleted": deleted, "files": files,
            "verdicts": verdicts, "fix_rounds": max(max(rounds, default=1) - 1, 0), "over_routed": over, "fit": fit}


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
TREVOR_QUOTE_MAX = 400
TREVOR_SKIP_PREFIXES = ("<command-", "<local-command", "Caveat:")


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
    """[(date, one-line text)] Trevor typed in interactive sessions since `since` (epoch), about this repo or scrum."""
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
            for d in _json_lines(f):
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
                    out.append((_iso(at), re.sub(r"\s+", " ", text)[:TREVOR_CHAT_MAX]))
    return out


def _trevor_chat(root, since):
    """The ## Chat lines: Jev's pick of Trevor's messages, or one failure line."""
    try:
        msgs = _trevor_messages(root, since)
    except OSError as e:
        return [f"- Transcripts failed: {e}"]
    if not msgs:
        return []
    dates = {}
    for at, text in msgs:
        dates.setdefault(text, at)
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
    out = []
    for line in r.stdout.splitlines():
        score, sep, text = line.partition("\t")
        if sep and text.strip():
            out.append(f'- {dates.get(text, "?")} {score}: "{text[:TREVOR_QUOTE_MAX]}"')
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
    """Write digests/<NNN>/trevor.md: Trevor's typed chat messages (Jev-ranked), feature.md quotes, new backlog tags and
    answer notes since the previous live digest (else 7 days). A failing source is a one-line note; never raises then."""
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
        sections[heading], counts[key] = items or ["None"], 0 if failed else len(items)
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


# --- process-health: 10 fixed metrics per digest, each compared with the previous digest's (Digest step 1). ---
HEALTH_LIMITS = {"stops_per_job": 0.5, "resume_abort_stops": 0, "waiting_on_job_stops": 0, "unreadable_asks": 0,
                 "cheaper_lane_jobs": 0, "test_waste_jobs": 0, "fable_misuse": 0, "unused_windows": 0,
                 "overburned_windows": 0, "not_shipped": 0}
HEALTH_UNUSED_PCT = 15  # a window left more than this % unused at reset
HEALTH_EARLY_90_SECS = 3600  # a window that reached 90% more than this long before reset burned too early
HEALTH_WAITING_RE = re.compile(r"(?i)blocked on sibling|waiting (?:on|for) (?:job |another job|\d{3})")
HEALTH_UNREADABLE_RE = re.compile(r"[\w.-]*/[\w.-]+\.[A-Za-z]{1,5}\b|\brule \d+\b", re.I)
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


def cmd_process_health(root, digest_id: str) -> dict:
    """{"digest", "previous", "metrics"}: HEALTH_LIMITS' metrics over the jobs in digests/<NNN>/jobs.txt, from
    questions.log, each job's routing.log, fable.log and round reviews, the digest's pipeline-fit.json and windows.json,
    and board.json; each carries the previous digest's value and a flag ("worse", "over twice" or null). A missing or
    broken input counts 0. Writes digests/<NNN>/health.json."""
    root = Path(root)
    d = root / "digests" / str(digest_id)
    if not DIGEST_RE.fullmatch(str(digest_id)) or not (d / "jobs.txt").is_file():
        raise SystemExit(f"no digest {digest_id!r}")
    listed = [l.strip() for l in (d / "jobs.txt").read_text().splitlines() if ID_RE.match(l.strip())]
    claimed = set(listed)
    board = {j["id"]: j for j in read_board(root)["jobs"] if isinstance(j, dict) and str(j.get("id")) in claimed}
    hits = {name: [] for name in HEALTH_LIMITS}  # one entry per counted line, job or window
    for q in _json_lines(root / "questions.log"):
        job, kind = q.get("job"), q.get("kind")
        if str(job) not in claimed or not (kind in HEALTH_STOP_KINDS or "question" in q and kind is None):
            continue
        hits["stops_per_job"].append(job)
        if HEALTH_WAITING_RE.search(str(q.get("reason") or q.get("question") or "")):
            hits["waiting_on_job_stops"].append(job)
        if kind not in (None, "ask"):
            continue
        opts = q.get("options") if isinstance(q.get("options"), list) else []
        if opts and all(isinstance(o, dict) and str(o.get("command") or "").startswith(("resume ", "abort "))
                        for o in opts):
            hits["resume_abort_stops"].append(job)
        question = str(q.get("question") or "")
        if len(question.split()) > 40 or HEALTH_UNREADABLE_RE.search(question):
            hits["unreadable_asks"].append(job)
    for e in _health_file(d / "pipeline-fit.json", dict).get("jobs") or []:
        if not isinstance(e, dict) or str(e.get("id")) not in claimed:
            continue
        added, files, lane = e.get("added"), e.get("files"), e.get("lane") or "standard"
        if type(added) is int and type(files) is int and files <= LILGUY_MAX_FILES and (
                lane in ("fast", "standard", "debug") and added <= LILGUY_MAX_LINES
                or lane in ("standard", "debug") and added <= FAST_MAX_LINES):
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
        no_ui = not globs or not any(glob_match(p, globs) for p in likely_files(spec))
        if reviewed and (lane in ("lilguy", "fast") or no_ui):
            hits["test_waste_jobs"].append(job_id)
            seconds += sum(r["duration_s"] for r in routed if is_num(r.get("duration_s"))
                           and any(t in str(r.get("role") or "") for t in HEALTH_TEST_ROLES))
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
                                          or job.get("lane") not in ("lilguy", "runall", "bigboy") and not job.get("pr")):
            hits["not_shipped"].append(job_id)
    for card in _health_file(d / "windows.json", list):
        b = card.get("budget") if isinstance(card, dict) else None
        if not isinstance(b, dict):
            continue
        name, reset = f"{card.get('window')}-{card.get('resets_at')}", card.get("resets_at")
        if is_num(b.get("left_at_reset_pct")) and b["left_at_reset_pct"] > HEALTH_UNUSED_PCT:
            hits["unused_windows"].append(name)
        if (is_num(b.get("cap_idle_secs")) and b["cap_idle_secs"] > 0
                or is_num(b.get("hit_90_at")) and is_num(reset) and reset - b["hit_90_at"] > HEALTH_EARLY_90_SECS):
            hits["overburned_windows"].append(name)
    prev_id, prev = _previous_health(root, str(digest_id))
    metrics = {}
    for name, limit in HEALTH_LIMITS.items():
        value = (round(len(hits[name]) / len(listed), 2) if listed else None) if name == "stops_per_job" \
            else len(hits[name])
        old = prev.get(name, {}).get("value") if isinstance(prev.get(name), dict) else None
        old = old if is_num(old) else None
        flag = None
        if value is not None and old is not None:
            flag = "worse" if value > old else "over twice" if value > limit and old > limit else None
        metrics[name] = {"value": value, "previous": old, "limit": limit, "jobs": sorted(set(hits[name])), "flag": flag}
    metrics["test_waste_jobs"]["minutes"] = round(seconds / 60)
    out = {"digest": str(digest_id), "previous": prev_id, "metrics": metrics}
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


def _waited(prev, end, starts, mtimes):
    """Secs of [prev, end] spent waiting: each start in the window runs to the next file mtime (else end); overlaps count once."""
    spans = sorted((w, min(next((t for t in mtimes if t > w), end), end)) for w in starts if prev <= w < end)
    total, upto = 0, prev
    for a, b in spans:
        a = max(a, upto)
        if b > a:
            total, upto = total + b - a, b
    return total


def _timing_row(root, job_id, job, stalls, waits=()):
    """(row cells, wall secs, rounds, no-change rounds, E2E lock waits) for one claimed job. The no-change cell is the count and the later round of each
    equal pair, e.g. `2 (rounds 2,3)`. Created is feature.md's
    mtime (else spec.md's), Spec starts at claimed-at.txt (cmd_ready) when sane, the wait before it counting as Queue; done is the board updatedAt; each round's time runs from the previous round's last file
    (round 1: the build start, see _build_start) to its own last file, less the queue/machine waits in `waits` (epoch secs)."""
    folder = Path(root) / "jobs" / job_id
    created = _mtime(folder / "feature.md") or _mtime(folder / "spec.md")
    done, spec_at = _epoch(job.get("updatedAt")), _mtime(folder / "spec.md")
    wall = done - created if done and created else None
    rounds = sorted(int(p.name[6:]) for p in folder.glob("round-*") if re.fullmatch(r"round-\d+", p.name) and p.is_dir())
    start = _build_start(root, job_id)
    if spec_at and start and start >= spec_at:
        queue = start - spec_at
    else:
        start, queue = spec_at, 0 if spec_at else None
    times, heads, prev = [], [], start or created
    mtimes = sorted(t for q in folder.rglob("*") if (t := _mtime(q))) if waits else []
    for n in rounds:
        rd = folder / f"round-{n}"
        end = max((t for q in rd.iterdir() if (t := _mtime(q))), default=None)
        times.append(_mins(end - prev - _waited(prev, end, waits, mtimes) if end and prev else None))
        prev = end or prev
        try:
            heads.append((rd / "head.txt").read_text(encoding="utf-8", errors="replace").strip())
        except OSError:
            heads.append("")
    same = [n for n, a, b in zip(rounds[1:], heads, heads[1:]) if a and a == b]
    waits = sum(len(E2E_LOCK_RE.findall(t)) for t in _round_text(folder, "check.md"))
    spec = spec_at - created if spec_at and created else None
    try:  # cmd_ready's claim: a BigBoy child's dependency wait counts as Queue, not Spec
        claim = float((folder / "claimed-at.txt").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        claim = None
    if claim and spec_at and created and created <= claim <= spec_at:
        spec, queue = spec_at - claim, queue + claim - created
    try:  # serve.py note_queue_gate: the launch gates that queued it
        gates = ", ".join((folder / "queue-gates.txt").read_text(encoding="utf-8", errors="replace").split()) or "-"
    except OSError:
        gates = "-"
    cells = [job_id, _mins(wall), _mins(spec), _mins(queue), gates, str(len(rounds)), ", ".join(times) or "-",
             f"{len(same)} (rounds {','.join(map(str, same))})" if same else "0", str(waits),
             str(stalls.get(job_id, 0))]
    return cells, wall, len(rounds), len(same), waits


def write_timing(root, digest_id, jobs):
    """digests/<NNN>/timing.md: one row per claimed job (wall, spec, queue, queue gate = queue-gates.txt, rounds, round times, no-change rounds = a
    head.txt equal to the previous round's, E2E lock waits = `exit 124` in check.md, questions.log stall lines),
    totals, and every job on every registered board (and this one) now stalled waiting on the E2E queue."""
    board = {j["id"]: j for j in read_board(root)["jobs"]}
    stalls, waits = {}, {}
    for q in _json_lines(Path(root) / "questions.log"):
        at = _epoch(q.get("date"))
        if at and isinstance(q.get("job"), str) and (q.get("kind") == "machine" or (
                q.get("kind") == "stall" and E2E_WAIT_REASON in str(q.get("reason") or ""))):
            waits.setdefault(q["job"], []).append(at)
        if q.get("kind") == "stall" and isinstance(q.get("job"), str):
            stalls[q["job"]] = stalls.get(q["job"], 0) + 1
    rows = [_timing_row(root, j, board.get(j, {}), stalls, waits.get(j, ())) for j in jobs]
    lines = [f"# Timing: digest {digest_id}", "",
             "| Job | Wall | Spec | Queue | Queue gate | Rounds | Round times | No-change rounds | E2E lock waits | Stalls |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    lines += ["| " + " | ".join(r[0]) + " |" for r in rows]
    lines += ["", "## Totals",
              f"Jobs: {len(rows)} · wall {_mins(sum(r[1] for r in rows if r[1]))} · rounds {sum(r[2] for r in rows)}"
              f" · no-change rounds {sum(r[3] for r in rows)} in {sum(1 for r in rows if r[3])} jobs"
              f" · E2E lock waits {sum(r[4] for r in rows)} in {sum(1 for r in rows if r[4])} jobs"
              f" · stalls {sum(stalls.get(j, 0) for j in jobs)}", "", "## Waiting on the E2E queue"]
    waiting, t = [], time.time()
    for scrum in dict.fromkeys([Path(root).resolve(), *((p / "scrum").resolve() for p in projects().values())]):
        try:
            other = read_board(scrum)
        except SystemExit:
            continue
        for j in other["jobs"]:
            at = _epoch(j.get("updatedAt"))
            if stalled(j) and E2E_WAIT_REASON in str(j.get("reason") or "") and at:
                waiting.append(f"- {scrum.parent.name}/{j['id']}: {_mins(t - at)}")
    lines += waiting or ["None"]
    (Path(root) / "digests" / digest_id / "timing.md").write_text("\n".join(lines) + "\n")


# --- escapes: digest-start writes digests/<NNN>/escapes.md, each debug job traced by git blame to its origin job ---
ESCAPE_SKIP_RE = re.compile(r"(^|/)(__tests__|e2e|tests?)/|(^|/)test_[^/]*\.py$|\.(test|spec)\.[cm]?[jt]sx?$")
ESCAPE_JOB_RE = re.compile(r"scrum/jobs/([^/\s]+)/")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? ", re.M)
BLAME_SHA_RE = re.compile(r"^([0-9a-f]{40,64}) \d+ \d+", re.M)


def _escape_lines(repo, bug, board):
    """The escapes.md lines for debug job `bug`: its newest HEAD commit naming scrum/jobs/<bug>/, each non-test file's
    -a,b hunks blamed on <sha>^, and every other board job named in a blamed commit's body, with its last-round PASSes."""
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
    out = []
    for origin, files in origins.items():
        rounds = board[origin].get("rounds") or [{}]
        passed = sorted(k for k, v in rounds[-1].items() if v == "PASS" and k != "check") or ["none"]
        out.append(f"- {bug} ← {origin} · {sum(files.values())} lines in {', '.join(files)} · passed by: {', '.join(passed)}")
    return out


def write_escapes(root, digest_id, jobs):
    """digests/<NNN>/escapes.md: for every claimed `"lane": "debug"` job, the origin jobs whose lines its fix changed
    (_escape_lines, git in the repo that holds root), or `No bug jobs`."""
    board = {j["id"]: j for j in read_board(root)["jobs"]}
    repo = Path(root).resolve().parent
    lines = [l for j in jobs if board.get(j, {}).get("lane") == "debug" for l in _escape_lines(repo, j, board)]
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
    return any(not i["done"] and not i["setup"] and not waiting_on(i, items, board) for i in items)


def _scorecard(root, e, t, board, questions):
    """The scorecard dict for one remembered window entry `e` (resets_at <= t)."""
    root = Path(root)
    end = e["resets_at"]
    start = end - WINDOW_SECS[e["window"]]
    within = lambda ts: ts is not None and start <= ts < end
    jobs = {j["id"]: j for j in board["jobs"] if isinstance(j, dict) and isinstance(j.get("id"), str)}
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
    rows = [r for r in transcript_tokens(start, end) if r["project"] == name] \
        if name is not None and transcripts_dir().is_dir() else None
    tok = lambda r: sum(r[k] for k in TOKEN_KEYS)
    tokens = model_mix = None
    if rows is not None:
        by_job, model_mix = {}, {}
        for r in rows:
            if r["job"]:
                by_job[r["job"]] = by_job.get(r["job"], 0) + tok(r)
            mix = model_mix.setdefault(r["agent"], {})
            mix[r["model"] or "unknown"] = mix.get(r["model"] or "unknown", 0) + tok(r)
        tokens = {"total": sum(tok(r) for r in rows), "by_job": by_job}
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
            if not within(p.stat().st_mtime) or not _real_review(p):
                continue
            body = md_section(p.read_text(encoding="utf-8"), "Findings") or ""
        except (OSError, ValueError):
            continue
        findings += len(re.findall(r"^\d+\. \[", body, re.M))
    review_tokens = rows and sum(tok(r) for r in rows if str(r["agent"]).startswith("scrum-review"))
    # local routing
    routed = [d for p in root.glob("jobs/*/routing.log") for d in _json_lines(p) if within(_epoch(d.get("ts")))]
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
        if "options" not in q or q["_ts"] is None:
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
        "window": e["window"], "label": label, "resets_at": end, "start": start, "end": end,
        "written_at": datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds"),
        "budget": budget, "headline": round(points_done / used, 3) if is_num(used) and used else None,
        "points_done": points_done, "done_jobs": done_jobs, "tokens": tokens,
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
    open.json. Returns the scorecards written this run. The whole run holds windows/.lock."""
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
        usage = read_usage() or {}
        limits = usage.get("rate_limits") if isinstance(usage.get("rate_limits"), dict) else {}
        at = usage["written_at"] if is_num(usage.get("written_at")) else t
        board, idle = read_board(root), None
        for key, _ in WINDOWS:
            w = limits.get(key)
            if not isinstance(w, dict) or not is_num(w.get("resets_at")):
                continue
            r = int(w["resets_at"])
            e = opened.setdefault(f"{key}-{r}", {"window": key, "resets_at": r, "used_pct": None, "hit_90_at": None,
                                                 "hit_cap_at": None, "idle_secs": 0, "last_tick": None})
            used = w.get("used_percentage")
            if is_num(used):
                e["used_pct"] = used
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
                card = _scorecard(root, e, t, board, questions)
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
    "|".join(re.escape(t) for t in (UI_SKIP, SECURITY_SKIP, DELETION_SKIP, VISUAL_SKIP)) + "|"
    + re.escape(CARRIED).replace(r"\{\}", r"\d+"))


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


def _e2e_command(cmd, specs):
    """The E2E command narrowed to specs: after `--` for npm run, appended for playwright test, else
    `npx playwright test` keeping the leading NAME=value tokens."""
    args = " ".join(shlex.quote(s) for s in specs)
    if re.search(r"\bnpm run\b", cmd):
        return f"{cmd} -- {args}"
    if re.search(r"\bplaywright test\b", cmd):
        return f"{cmd} {args}"
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
    for f in ui:
        routes, seen, todo = set(), {f}, [f]
        while todo:  # follow importers until they reach route files
            g = todo.pop()
            if (r := _route_of(g)) is not None:
                routes.add(r)
                if "pages" in g.split("/")[:-1] or APP_ROUTE_FILE_RE.search(g):
                    continue  # a route file; a colocated app/ module also maps through its importers
            for imp in _importers(index, g):
                if imp not in seen:
                    seen.add(imp)
                    todo.append(imp)
        out[f] = routes
    return out


def e2e_specs(wt, base: str, project_file) -> dict:
    """{"mode", "command", "specs", "uncovered", "trigger"} for the diff base...HEAD in wt (lanes/newjob.md Check gate
    step 2). full: a diff file matches `- E2E full globs:` (default E2E_FULL_DEFAULT; `none` = never); scoped: the specs
    whose string literals name a route a changed UI runtime file renders; none: no spec covers it. An unreadable diff
    runs the full suite (the safe direction)."""
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
        return {**out, "mode": "full", "command": cmd, "trigger": hit if files is not None else "diff unreadable"}
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
        hits = {s for s, body in spec_text.items() for r in routes if _route_re(*r).search(body)}
        if not hits:
            out["uncovered"].append(f)
        specs |= hits
    if specs:
        out.update(mode="scoped", specs=sorted(specs), command=_e2e_command(cmd, sorted(specs)) if cmd else None)
    return out


def cmd_e2e_specs(root, job_id) -> dict:
    """e2e_specs for the job's worktree and base with root/project.md."""
    job = find(read_board(root), check_id(job_id))
    if not job.get("worktree") or not job.get("base"):
        raise SystemExit(f"job {job_id} has no {'worktree' if not job.get('worktree') else 'base'} on the board")
    return e2e_specs(job["worktree"], job["base"], Path(root) / "project.md")


RENDER_CAP = 8  # pages per shared review render (lanes/review.md step 2); the rest fall back to the reviewers


def render_paths(wt, base: str, project_file) -> dict:
    """{"paths", "skipped"} for the diff base...HEAD in wt (lanes/review.md step 2 Shared render): the sorted routes the
    changed UI runtime files render, minus dynamic ([param]) routes and those past RENDER_CAP, which go to skipped.
    A UI runtime file that maps to no renderable route gives ["/"]; no UI runtime file (or an unreadable diff) gives
    empty lists."""
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
    routes = sorted({r for pairs in changed_routes(wt, ui).values() for r, _ in pairs})
    skipped = [f"{r}: dynamic route" for r in routes if "[" in r]
    static = [r for r in routes if "[" not in r]
    skipped += [f"{r}: over the {RENDER_CAP}-page cap" for r in static[RENDER_CAP:]]
    return {"paths": static[:RENDER_CAP] or ["/"], "skipped": skipped}


def cmd_render_paths(root, job_id) -> dict:
    """render_paths for the job's worktree and base with root/project.md."""
    job = find(read_board(root), check_id(job_id))
    if not job.get("worktree") or not job.get("base"):
        raise SystemExit(f"job {job_id} has no {'worktree' if not job.get('worktree') else 'base'} on the board")
    return render_paths(job["worktree"], job["base"], Path(root) / "project.md")


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
    (incremental) or UI/UX (no UI file) and security skip files (full); never writes
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
        if globs and not any(glob_match(f, globs) for f in files):
            skips.update(ui=UI_SKIP, ux=UI_SKIP)
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
    if not mechanical and (lines := sum(a for a, _, _ in rows)) > LILGUY_MAX_LINES:
        return f"diff over {LILGUY_MAX_LINES} added lines ({lines})"
    if not mechanical and (files := len({p for a, _, p in rows if a})) > LILGUY_MAX_FILES:
        return f"more than {LILGUY_MAX_FILES} files with added lines ({files})"
    for p in names:
        if RULES_RE.search(p) and p not in feature_text and f"{p.rpartition('/')[0]}/*.md" not in feature_text:
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
    diff = _route_diff(job)
    names = diff[1] if diff else []
    promote = None
    if lane == "fast" and check == "FAIL" and check_fails >= 2:
        promote = "check failed twice"
    elif lane == "fast" and check == "PASS":
        promote = _promote_trigger(*diff) if diff else "diff unreadable"
    elif lane == "lilguy" and job.get("worktree"):
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


# --- lilguy-fit: SKILL.md New job step 3's Lilguy route. Tiny (1 point, or Jev confident it is trivial) and no hard-stop
# word in feature.md. Anything unreadable counts as not tiny.
LILGUY_HARD_STOP_RE = re.compile(
    r"\b(?:schema|migrations?|migrate|prisma|sql|money|payments?|pricing|billing|checkout|stripe|auth[nz]?"
    r"|authenticat(?:ion|e)|authoriz(?:ation|e)|sessions?|login|passwords?|permissions?|secrets?|credentials?"
    r"|api\s+keys?|env\s+vars?|environment\s+variables?)\b|\.env\b", re.I)
LILGUY_JEV_MAX_SCORE, LILGUY_JEV_MIN_CONFIDENCE = 1.5, 0.7
# A repo-relative .claude/ path (not ~/.claude, $HOME/.claude, an absolute path or a job worktree): Claude Code refuses
# edits there in an unattended session, so such a job never takes the unattended Lilguy route.
CLAUDE_DIR_RE = re.compile(r"(?<![\w~/.$}])\.claude/(?!worktrees/)")


def _jev_model(folder: Path) -> dict | None:
    """The raw JSON answer of the last `model` line in folder/jev.log (fields: time, step, question, raw, decision,
    seconds), or None when there is no such line or it isn't a JSON object."""
    try:
        lines = (folder / "jev.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    fields = next((f for f in (l.split("\t") for l in reversed(lines)) if len(f) > 3 and f[1] == "model"), None)
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
    m = re.search(rf"^{key}:\s*({'|'.join(words)})\b", re.split(r"^## ", text, maxsplit=1, flags=re.M)[0], re.M | re.I)
    return m[1].lower() if m else None


def job_complex(root: Path, job_id: str) -> bool:
    """True only when feature.md's header `Complex:` is yes, or, with no such line there, spec.md's is."""
    d = Path(root) / "jobs" / job_id
    return (header_value(d / "feature.md", "Complex", ("yes", "no"))
            or header_value(d / "spec.md", "Complex", ("yes", "no"))) == "yes"


def cmd_lilguy_fit(root, job_id: str) -> dict:
    """{"fit", "why"}: a job already on another lane never fits, nor one whose feature.md or spec.md names a
    repo-relative `.claude/` path (CLAUDE_DIR_RE); then a feature.md header `Lane:` line decides (lilguy
    fits, any other lane doesn't); else fit only when tiny by backlog points or by Jev, with no LILGUY_HARD_STOP_RE word
    in its feature.md."""
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
    if m := LILGUY_HARD_STOP_RE.search(feature.read_text(encoding="utf-8", errors="replace") if feature.is_file() else ""):
        return {"fit": False, "why": f"hard-stop word {m[0]!r} in feature.md"}
    item = next((i for i in read_backlog(root)[1] if i["job"] == job_id), None)
    if item and item["points"] == 1:
        return {"fit": True, "why": "backlog item is 1 point"}
    raw = _jev_model(folder) or {}
    score, conf = raw.get("score"), raw.get("confidence")
    if is_num(score) and is_num(conf) and score < LILGUY_JEV_MAX_SCORE and conf >= LILGUY_JEV_MIN_CONFIDENCE:
        return {"fit": True, "why": f"Jev score {score} at confidence {conf}"}
    pts = f"{item['points']} points" if item and item["points"] else "no points"
    jev = f"Jev score {score} at confidence {conf}" if raw else "no Jev model answer"
    return {"fit": False, "why": f"not tiny: {pts}, {jev}"}


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
               or stalled(j) and not lilguy_in_checkout(j) and not parent_idle(j) for j in jobs)


# The Claude accounts automated sessions may run on, in order: (name, config dir, reserve) where reserve is
# (5h used %, 7d used %) at which the account is kept for Trevor, or None. SCRUM_ACCOUNTS (JSON) replaces it.
ACCOUNTS = (("main", "~/.claude", None), ("owa", "~/.claude-owa", (80, 90)))
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
    model, and the project, job, agent and skill it is attributed to. Reads <dir>/*/*.jsonl (main sessions) and
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
    for path in files:  # main sessions first, so a subagent finds its parent's tags
        try:
            if path.stat().st_mtime < start:
                continue
        except OSError:
            continue
        rows, first = read_transcript(path)
        job, skill = first_prompt_tags(first)
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
                out.append({**row, "project": project, "job": wt or job, "agent": agent, "skill": skill})
    return sorted(out, key=lambda r: r["ts"])


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


USAGE_LOW_PCT = 10  # remaining % below which automated claims taper (USAGE_STEPS[0])
USAGE_LOWER_PCT = 5  # remaining % below which the taper drops to USAGE_STEPS[1]
USAGE_STOP_PCT = 2  # remaining % below which automated claims stop (USAGE_STEPS[2])
USAGE_STEPS = (3, 1, 0)  # live-session allowance at each rung; None (above the ladder) means unlimited
USAGE_RELAX_SECS = 1200  # a window resetting within this many seconds relaxes one rung
USAGE_TIGHTEN_SECS = 10800  # a low window resetting further away than this tightens one rung
USAGE_STALE_SECS = 300  # usage.json older than this is unknown, and unknown never tapers


class Allowance(int):
    """usage_allowance's number of live sessions; .reason says which window bound it and why."""
    def __new__(cls, n, reason):
        self = super().__new__(cls, n)
        self.reason = reason
        return self


def usage_allowance(usage, now, live):
    """How many live headless sessions automated claims may run under the 5h and 7d budgets (an Allowance), or None
    for no taper. Each window's remaining % picks a rung of USAGE_STEPS; a reset within USAGE_RELAX_SECS relaxes
    one rung, a reset beyond USAGE_TIGHTEN_SECS tightens one. The stricter window wins (five_hour on a tie). Stale,
    missing or malformed data, or a window whose reset already passed, limits nothing. `live` (an int or a list)
    only feeds the reason text. Trevor's own Play/Resume never call this."""
    if not isinstance(usage, dict) or not isinstance(usage.get("rate_limits"), dict):
        return None
    at = usage.get("written_at")
    if not is_num(at) or now - at > USAGE_STALE_SECS:
        return None
    rungs = (None,) + USAGE_STEPS
    best = None
    for key, label in WINDOWS:
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


def reserve_hit(acc, usage, now):
    """Why the account's reserve keeps it for Trevor, or None: a window with resets_at > now whose used % is at or
    above its reserve value. written_at is ignored (used % only grows inside one window)."""
    limits = usage.get("rate_limits") if isinstance(usage, dict) else None
    if not acc.reserve or not isinstance(limits, dict):
        return None
    for (key, label), cap in zip(WINDOWS, acc.reserve):
        w = limits.get(key)
        if isinstance(w, dict) and is_num(w.get("used_percentage")) and is_num(w.get("resets_at")) \
                and w["resets_at"] > now and w["used_percentage"] >= cap:
            return f"reserve {label} {round(w['used_percentage'])}% used (keeps {cap}%)"
    return None


def pick_account(now, live=0, prefer=None):
    """(name, allowance) of the first account with room, `prefer` first when listed, else (None, Allowance(0,
    reason)) naming every account and why. Room: no limit_until marker ahead, usage_allowance None or above 0, and no
    reserve window reached (reserve_hit)."""
    accs = accounts()
    why = []
    for acc in sorted(accs, key=lambda a: a.name != prefer):
        if until := limited_until(acc.name, now):
            why.append(f"{acc.name} limited until {datetime.fromtimestamp(until):%H:%M}")
            continue
        usage = read_usage(acc.name)
        allow = usage_allowance(usage, now, live)
        if allow is not None and allow <= 0:
            why.append(f"{acc.name} {allow.reason}")
            continue
        if held := reserve_hit(acc, usage, now):
            why.append(f"{acc.name} {held}")
            continue
        return acc.name, allow
    return None, Allowance(0, "no account has room: " + "; ".join(why))


def fallback_account(now, recorded):
    """Account for a spawn when none has room: the one whose limit marker ends soonest (no marker counts as now), the
    recorded one winning ties or when it is not limited; the first account when `recorded` is unlisted."""
    accs = accounts()
    names = [a.name for a in accs]
    first = recorded if recorded in names else names[0]
    return min([first] + [n for n in names if n != first], key=lambda n: limited_until(n, now) or now)


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


def cmd_statusline(text):
    """Claude Code's status line: save stdin's rate_limits to usage.json (temp file + os.replace), return the line."""
    try:
        limits = json.loads(text).get("rate_limits")
    except (ValueError, AttributeError):
        return ""
    if not isinstance(limits, dict):
        return ""  # no rate_limits (yet): leave the old file alone
    path = usage_path()
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
    return " · ".join(f"{label} {round(w['used_percentage'])}%" for key, label in WINDOWS
                      if isinstance(w := limits.get(key), dict) and is_num(w.get("used_percentage")))


def child_files(jobs_dir, job_id):
    """A child's Likely files: from spec.md, or from feature.md (plan-apply's Parallel: paths) while it has no spec."""
    for name in ("spec.md", "feature.md"):
        if (f := Path(jobs_dir) / job_id / name).is_file():
            return likely_files(f.read_text(encoding="utf-8", errors="replace"))
    return set()


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
    return {p for p in found if PATH_RE.match(p)}


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
    feature = t["text"] + "\n" if plain else \
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
    Every check runs before the first job is created, so a refused plan creates nothing."""
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
        parent.update(children=kids + new, stage="running", reason=None, updatedAt=now())
        parent["files"], parent["diverged"] = job_files(d), diverged(d)
        return {"children": new}


def cmd_runall_start(root):
    """One Run-all parent whose waiting children are every open backlog item, claimed in priority order (priority_key) under the lock.
    An item that waits, directly or through its prerequisites, on a job claimed outside this run stays open. A child
    whose item needs another item claimed here depends_on that sibling's child. An item waiting on Human setup stays
    open, and so does every item that needs it. Cool-down refuses it (COOLING_CLAIM)."""
    if cooling_down():
        raise SystemExit(COOLING_CLAIM)
    with locked_board(root) as board:
        lines, items = read_backlog(root)
        held = {i["index"] for i in items if not i["done"] and i["setup"]}  # indexes of open items left open
        while True:
            more = {i["index"] for i in items if not i["done"] and i["index"] not in held
                    and any(o["id"] == n and (o["done"] or o["index"] in held)
                            for n in waiting_on(i, items, board) for o in items)}
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
            t = {"ticket": None, "title": short_title(item["text"]), "text": item["text"], "parallel": True}
            kids.append(add_child(root, board, parent, t, [], "", plain=True))
            take_spec(root, item["text"], kids[-1])
            claim_item(lines, item, kids[-1])
            if item["id"]:
                by_id.setdefault(item["id"], []).append(kids[-1])
        for item, kid in zip(todo, kids):  # after all are created: an item may need one listed after it
            find(board, kid)["depends_on"] = list(dict.fromkeys(k for n in item["needs"] for k in by_id.get(n, [])
                                                                if k != kid))
        write_backlog(root, lines)
        parent.update(lane="runall", stage="running", children=kids, updatedAt=now())
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
MAX_CPU_LOAD_PCT = 150  # ... or with the 1-minute load average above this share of the cores (cpu_load_pct): load 13.4 on 8
#                        cores (168%) timed out next dev, jest and Playwright while busy read 51% (2026-10-26, job 459)
MAX_LAUNCH_CPU_LOAD_PCT = 500  # serve.spawn queues every non-manual job launch (resume, approve, rework, start) above this load
CPU_SAMPLES = 3  # cpu_busy_pct: the mean of at most this many watchdog samples (record_cpu_sample) ...
CPU_SAMPLE_SECS = 300  # ... from the last this many seconds (about 3 watchdog ticks), so one spike never flips the gate
SWAP_FREE_RAM_PCT = 35  # ... but swap alone is stale (macOS keeps it until pressure returns): it blocks only below this free RAM
SWAP_GROWTH_SECS = 600  # ... or when swap grew within this window (2026-10-25: idle machine, 71% free, blocked for an hour)
SESSION_RAM_PCT = 5  # ram_room: estimated share of RAM one new headless session takes (16 GB Mac); tune here
MAX_SESSIONS = 14  # machine_ok: headless sessions may hold 70% of RAM in all (SESSION_RAM_PCT each); the rest is macOS and
#                   apps. Derived from the RAM share, not the fixed 8 job 279 removed; 19 sessions crashed the Mac (2026-10-24).
#                   14, not 12: Trevor keeps it as a backstop until further notice in case the RAM reading misleads (job 284)
SESSION_RAMP_SECS = 120  # ram_room: a session younger than this has not grown into its RAM yet, so free RAM % overstates
#                          the room; two projects claiming within that minute both burst (the 2026-10-24 pile-up)
MAX_YOUNG_SESSIONS = 2  # ram_room: at most this many sessions younger than SESSION_RAMP_SECS at once, so starts ramp 2 per
#                         2 min and the CPU gates see each pair's load first (2026-11-04: 10 started on wake, load 70 on 8 cores)


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
    m = re.search(r"System-wide memory free percentage: (\d+(?:\.\d+)?)%", out)
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


def cooldown_path():
    """Trevor's cool-down flag (the dashboard's Cool down button): while it exists no new work starts on its own (backlog
    claims, Run-all and BigBoy child claims, wake-waiting, auto-continue, cloud-claim, the next roadmap step, the
    bad-window digest); work already started finishes, and Trevor's own clicks still start work."""
    return Path(os.environ.get("SCRUM_COOLDOWN") or Path.home() / ".claude" / "trevskills-scrum" / "cooldown")


def cooling_down():
    return cooldown_path().exists()


def swap_grew(swap):
    """True when swap is more than 1 point of RAM above the oldest reading of the last SWAP_GROWTH_SECS (net growth: a
    fall then a rebound is not growth). Records swap
    in SCRUM_SWAP_LOG (default: system temp dir), pruned to that window; a missing or corrupt file means no growth."""
    log = os.environ.get("SCRUM_SWAP_LOG") or os.path.join(tempfile.gettempdir(), "scrum-swap-log.json")
    now = time.time()
    try:
        keep = [[t, v] for t, v in json.loads(Path(log).read_text()) if now - t < SWAP_GROWTH_SECS]
    except (OSError, ValueError, TypeError):
        keep = []
    grew = bool(keep) and swap - keep[0][1] > 1
    try:
        with open(log, "w") as fh:
            json.dump(keep + [[now, swap]], fh)
    except OSError:
        pass
    return grew


def swap_pressing(ram, swap, limit):
    """True when swap is past `limit` and either free RAM is under SWAP_FREE_RAM_PCT or swap grew over the window."""
    return swap is not None and swap > limit and ((ram is not None and ram < SWAP_FREE_RAM_PCT) or swap_grew(swap))


def machine_ok(path, manual=False, claim=False):
    """None when the machine has room for new work, else why not: cool-down (only for an automatic start of new or
    not-yet-started work, claim=True, and skipped for Trevor's manual clicks), then free RAM, then swap, then free
    disk, then CPU busy, then CPU load (the 5-minute load average over the cores; both CPU checks also skipped for
    manual clicks), then the session ceiling.
    Gates new claims, resumes and auto-continue starts only; a running job is never touched. An unknown reading passes."""
    if claim and not manual and cooling_down():
        return COOLING
    ram = free_ram_pct()
    if ram is not None and ram < MIN_FREE_RAM_PCT:
        return f"free RAM {ram:g}% (< {MIN_FREE_RAM_PCT}%)"
    swap = swap_used_pct()
    if swap_pressing(ram, swap, MAX_SWAP_PCT):
        return f"swap used {swap:.1f}% of RAM (> {MAX_SWAP_PCT}%)"
    disk = free_disk_gb(path)
    if disk is not None and disk < MIN_FREE_DISK_GB:
        return f"free disk {disk:.1f} GB (< {MIN_FREE_DISK_GB} GB)"
    cpu = None if manual else cpu_busy_pct()
    if cpu is not None and cpu > MAX_CPU_BUSY_PCT:
        return f"CPU busy {cpu:.0f}% (> {MAX_CPU_BUSY_PCT}%)"
    load = None if manual else cpu_load_pct()
    if load is not None and load > MAX_CPU_LOAD_PCT:
        return f"CPU load {load:.0f}% of {os.cpu_count()} cores (> {MAX_CPU_LOAD_PCT}%)"
    live = live_sessions()
    if live >= MAX_SESSIONS:
        return f"{live} sessions running (ceiling {MAX_SESSIONS})"
    return None


def ram_room(floor=1):
    """How many new sessions one claim batch may start once machine_ok passed: the free RAM above MIN_FREE_RAM_PCT
    split into SESSION_RAM_PCT shares, minus one share per session younger than SESSION_RAMP_SECS (its RAM is spoken
    for but not used yet), never past MAX_SESSIONS in all nor MAX_YOUNG_SESSIONS young ones, at least `floor`. An unknown reading allows 1, so a batch never
    bursts blind, and so does swap past MAX_SWAP_PCT / 2 while free RAM is low or swap is growing (swap_pressing); stale swap at healthy free RAM uses the RAM math.
    floor=0 (serve.py's launch gate) returns the raw room, 0 or less when full, and in the swap or unknown case 1 only
    while no session is younger than SESSION_RAMP_SECS."""
    ram = free_ram_pct()
    swap = swap_used_pct()
    if ram is None or swap_pressing(ram, swap, MAX_SWAP_PCT / 2):
        return 1 if floor or not any(a < SESSION_RAMP_SECS for a in session_ages()) else 0
    ages = session_ages()
    young = sum(a < SESSION_RAMP_SECS for a in ages)
    room = min(int((ram - MIN_FREE_RAM_PCT) // SESSION_RAM_PCT) - young, MAX_SESSIONS - len(ages), MAX_YOUNG_SESSIONS - young)
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


def live_sessions():
    """How many headless scrum sessions run on this machine (see session_ages)."""
    return len(session_ages())


def slot_conflict(k, busy, files):
    """(text, sibling ids) when child k may not run beside the in-progress siblings `busy`, else None. files maps a
    child id to its Likely files (child_files). The rules `ready` and `resume_blocker` share: parallel=no, or
    no readable Likely files, runs alone; anything else never beside such a sibling or one sharing a Likely file
    (shared_files: a folder shares every file under it)."""
    busy = [o for o in busy if o["id"] != k["id"]]
    if not busy:
        return None
    alone = lambda j: not j.get("parallel") or not files.get(j["id"])  # unknown Likely files = may touch anything
    if alone(k):
        return "this job runs alone", [o["id"] for o in busy]
    clash = [(o["id"], "runs alone" if alone(o) else f"shares {min(shared_files(files[k['id']], files[o['id']]))}")
             for o in busy if alone(o) or shared_files(files[k["id"]], files[o["id"]])]
    return ("; ".join(f"sibling {i} {why}" for i, why in clash), [i for i, _ in clash]) if clash else None


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
    read needs-human until they write the board) and the non-idle ones with a live session (see below). Reads the board without writing anything."""
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
    busy = [k for k in kids if k["id"] != job_id and (k["id"] in live or (
        k in maybe and (alive(k) if k.get("stage") in WATCHED else True)))]
    if not busy:
        return None
    hit = slot_conflict(job, busy, files)
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


def note_queue_gate(root, job_id, gate):
    """Add `gate` to jobs/<id>/queue-gates.txt once, for timing.md's Queue gate column (serve.py's note_queue_gate
    writes ram_room and cpu_load the same way). A write error never blocks the queue."""
    path = Path(root) / "jobs" / job_id / "queue-gates.txt"
    try:
        if gate not in (path.read_text(encoding="utf-8").split() if path.exists() else []):
            with path.open("a", encoding="utf-8") as f:
                f.write(gate + "\n")
    except OSError:
        pass


def cmd_ready(root, parent_id, live=(), manual=False):
    """Claim (stage -> spec) every waiting child that may start now, under the lock, so no child starts twice.
    `live` ids count as in progress whatever their stage (see resume_blocker). Paused and stalled siblings keep their
    overlap slot, and every live, paused or stalled leaf job of another tree is an outside holder: a child clashes with
    one only by shared Likely files or unreadable ones (slot_conflict, both sides parallel), never by parallel=no.
    Paused or stalled work never holds a claim otherwise (job 751). Cool-down holds every claim (Run-all and
    BigBoy alike) unless `manual` (Trevor's Setup done or Play); a parent whose children all finished still reports
    all_merged, so its final review runs. A child held on an overlap gets `overlap_hold` {ids, text} (the card's
    "Waiting on" line); a claim or a depends_on wait drops it."""
    jobs_dir = Path(root) / "jobs"
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
        held = bool(parent.get("paused"))  # a paused parent claims nothing and keeps its stage and reason
        blocked = not held and (legacy or (parent["stage"] == "running"
                                           and reason.startswith((WAITING_ON, MACHINE_WAIT))))
        go = not held and (parent["stage"] == "running" or legacy)
        # checked once: a machine-wide state, so it gates the whole call
        machine = go and machine_ok(root, manual=manual, claim=True)
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
        slots += [k for k in kids if k not in busy and parked(k)]  # a paused or stalled sibling resumes on its files
        outside = [dict(j, parallel=True) for j in board["jobs"] if go and not machine and j["id"] not in sibs
                   and j["id"] != parent["id"] and not j.get("children")
                   and j["stage"] not in ("waiting", "done", "aborted") and (not idle(j) or j["id"] in live or parked(j))]
        files.update({j["id"]: child_files(jobs_dir, j["id"]) for j in outside})
        overlap = []  # outside holder ids that alone hold a waiting child
        room = ram_room() if go and not machine else 0  # one claim = one new session
        if cap is not None:
            room = min(room, cap)
        ready = []
        for k in kids if go and not machine else []:
            if len(ready) >= room:  # machine_ok passed for the first claim only: never burst past the free RAM
                break
            if k["stage"] != "waiting" or k.get("setup") == "pending" or k.get("wake"):
                continue
            undone = [dep for dep in k.get("depends_on") or [] if stage.get(dep) != "done"]
            if undone:
                k.pop("overlap_hold", None)
                for dep in undone:
                    note_queue_gate(root, k["id"], f"depends_on:{dep}")
                continue
            hit = slot_conflict(k, slots, files)
            out_hit = None if hit else slot_conflict(dict(k, parallel=True), outside, files)
            if out_hit:
                overlap += out_hit[1]
            if hit or out_hit:
                hit = hit or out_hit
                k["overlap_hold"] = {"ids": list(hit[1]), "text": hit[0]}  # serve.py's waitingOn for the card
                for g in ["runs_alone"] if hit[0] == "this job runs alone" else [f"overlap:{i}" for i in hit[1]]:
                    note_queue_gate(root, k["id"], g)
                continue
            k.update(stage="spec", updatedAt=now())
            k.pop("overlap_hold", None)
            try:  # the claim time, written once, for timing.md's Spec start (see _timing_row)
                with (jobs_dir / k["id"] / "claimed-at.txt").open("x", encoding="utf-8") as f:
                    f.write(f"{int(time.time())}\n")
            except OSError:
                pass
            busy.append(k)
            slots.append(k)
            ready.append(k["id"])
        merged = sum(k["stage"] == "done" for k in kids)
        finished = sum(k["stage"] in ("done", "aborted") for k in kids)  # an aborted child never runs again
        new = parent["stage"], parent.get("reason")
        if machine:  # wait for RAM, disk or usage; never needs-human, and a legacy parent keeps its reason to re-evaluate
            if parent["stage"] == "running" and finished < len(kids):
                new = "running", MACHINE_WAIT + machine
        elif blocked and (ready or busy or finished == len(kids)):
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
                log_stop(root, parent["id"], "machine", new[1])
            elif (new[1] or "").startswith(BLOCKED):
                log_stop(root, parent["id"], "bigboy", new[1])
            parent.update(stage=new[0], reason=new[1], updatedAt=now())
            if new[0] == "needs-human":
                parent["stopTitle"] = "BIGBOY_BLOCKED"
        out = {"ready": ready, "merged": merged, "total": len(kids), "in_progress": len(busy),
               "all_merged": finished == len(kids)}
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
    job with a worktree (Lilguy lane Worktree mode) is a normal PR job."""
    return job.get("lane") == "lilguy" and not job.get("worktree")


def merge_refusal(job: dict) -> str | None:
    """Why `job` may not move to done, or None. Its PR must be MERGED; a PR-less job may finish only on a parent
    (bigboy/runall) lane or a lilguy job in the main checkout."""
    pr = job.get("pr")
    if not pr:
        return None if job.get("lane") in ("bigboy", "runall") or lilguy_in_checkout(job) else "not done: no PR recorded"
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


def cmd_set(root, job_id, pairs, unpause=False, expect=None, internal=False):
    """unpause writes to a paused job. Only the caller grants it: serve.py's Play and spawn bookkeeping, and
    `set --unpause`, which resume and rework use. Only an unpause write with stage= clears `paused`. expect: write only
    while the job is still in that stage (checked under the lock), else raise SystemExit and write nothing.
    stage=needs-human is refused (a stop is a closed question: `ask`) unless internal, which only cmd_cloud_sync passes."""
    if "stage=needs-human" in pairs and not internal:
        raise SystemExit(f'use board.py ask {job_id} "<question>" --a "Label=command" --b "Label=command" --title TITLE: '
                         "set never parks a job at needs-human")
    d = Path(root) / "jobs" / check_id(job_id)
    files, div = job_files(d), diverged(d)
    given = dict(pair.partition("=")[::2] for pair in pairs)
    pid = (caller_claude_pid() if given["tty"] else None) if "tty" in given else None  # ps before the lock, never under it
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
        job["files"], job["diverged"] = files, div
        job["updatedAt"] = now()
    if job["stage"] != was and job["stage"] in ("done", "needs-human"):
        play(sound(job["stage"]))


def questions_log(root, entry):
    """Append one JSON line to <scrum>/questions.log. Caller holds the board lock, so lines never interleave."""
    with open(Path(root) / "questions.log", "a") as f:
        f.write(json.dumps(entry) + "\n")


def log_stop(root, job_id, kind, reason):
    """Append one stop line (kind: stall, machine, bigboy or refused) to questions.log. Caller holds the board lock."""
    questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id, "kind": kind,
                         "reason": reason})


UNBLOCK_KINDS = ("round-limit", "check-fail", "ci-fail", "conflict", "blocked", "render")
UNBLOCK_MAX = 2  # unblocks per job, ever; a kind is unblocked at most once (the loop guard compares kinds, not text)


def park(root, job, question, parsed, title, recommend=None):
    """The needs-human field update and questions.log line of cmd_ask. Caller holds the board lock and plays the sound."""
    if job.get("reason") != question:
        job.pop("outcome", None)  # a new blocker: the last run's outcome no longer applies
    job.update(stage="needs-human", reason=question, question=question, options=parsed, stopTitle=title,
               updatedAt=now())
    job.pop("stalled", None)  # a question, not a stall: a later `set --unpause stage=` must not bring the flag back
    job.pop("limitResetAt", None)
    entry = {"date": now(), "project": Path(root).resolve().parent.name, "job": job["id"],
             "question": question, "options": parsed, "reason": question, "stopTitle": title,
             "kind": "bigboy" if question.startswith(("bigboy review: main not updated", BLOCKED)) else "ask"}
    if recommend:
        job["recommend"] = entry["recommend"] = recommend
    else:
        job.pop("recommend", None)  # a re-ask without one drops the old question's advice
    questions_log(root, entry)


def cmd_ask(root, job_id, question, options, kind=None, recommend=None, *, title):
    """Park the job at needs-human with a closed question: options are 2-3 "label=command" strings, keyed a, b, c in
    order. recommend is an optional (key, why) naming the option the agent advises. Returns the stored option dicts.
    An eligible kind (lanes/unblock.md) leaves the job in its stage and returns {"unblock": True, "n": N} instead.
    title must be a STOP_TITLES key; it is stored as stopTitle on a parked job (not on an unblock or a stall)."""
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
                             "abort <id> [--requeue|--cascade], resume <id>, lilguy <id>, apply <id>, shell: <command>")
        parsed.append({"key": key, "label": label, "command": command})
    if recommend is not None:
        rkey, why = recommend[0].strip(), clean(recommend[1])
        if rkey not in [o["key"] for o in parsed]:
            raise SystemExit(f"bad recommend key {rkey!r}; the question offers {', '.join(o['key'] for o in parsed)}")
        if not why:
            raise SystemExit("recommend needs a reason")
        recommend = {"key": rkey, "why": why}
    with locked_board(root) as board:
        job = live(board, check_id(job_id))
        kinds = job.get("unblockKinds", [])
        if kind in UNBLOCK_KINDS and job.get("unblocks", 0) < UNBLOCK_MAX and kind not in kinds:
            n = job.get("unblocks", 0) + 1
            job.update(unblocks=n, unblockKinds=[*kinds, kind], updatedAt=now())
            questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id,
                                 "kind": kind, "unblock": n, "question": question})
            return {"unblock": True, "n": n}
        was = job["stage"]
        # a session that did not load the scrum agent types is a session fault: stalled in its stage, so
        # auto_resume retries it; not a human stop, so no question and no sound
        if was in WATCHED and AGENT_TYPES_RE.search(question):
            reason = f"{STALL}{question}"
            if job.get("reason") != reason:
                job.pop("outcome", None)
            for k in ("question", "options", "recommend", "stopTitle"):
                job.pop(k, None)
            job.update(stalled=True, reason=reason, updatedAt=now())
            questions_log(root, {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id,
                                 "question": question, "reason": reason, "kind": "stall"})
            return {"stalled": True}
        park(root, job, question, parsed, title, recommend)
    if was != "needs-human":
        play(sound("needs-human"))
    return parsed


def cmd_wait_on(root, job_id, blocker, then=None) -> dict:
    """Park a builder-blocked job at stage waiting on another job on this board (SKILL.md New job step 5), so
    wake_waiting restarts it once that job merges. blocker is a full id or a number matching one id's NNN- start.
    then="approve <job_id>" (SKILL.md Migrate step 2) keeps the worktree and records it as `wake`: wake_waiting then
    parks the job at needs-human with Try again, and serve.py spawns approve."""
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
        if job.get("parent") and dep["id"] not in (find(board, job["parent"]).get("children") or []):
            raise SystemExit(f"job {job_id} is a child of {job['parent']}; it may only wait on a sibling")
        job.update(stage="waiting", depends_on=[dep["id"]], reason=f"waiting on {dep['id']}", updatedAt=now(),
                   **({"wake": then} if then else {"worktree": None}))
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


def cmd_answer(root, job_id, key, note=None):
    """Log Trevor's pick on the job's open question and return that option; the stage is left to the command it names.
    A non-blank note he typed with the pick goes on the same line."""
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
        questions_log(root, entry)
    return option


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


def cloud_worktree(repo: Path, job_id: str) -> str | None:
    """`git fetch origin`, then `git worktree add <repo>/.claude/worktrees/scrum-<id> scrum/<id>`, as rework does.
    Returns the path, or None when the add failed."""
    repo = Path(repo).resolve()
    path = repo / ".claude" / "worktrees" / f"scrum-{check_id(job_id)}"  # an id starts with a digit, never "-"
    try:
        subprocess.run(["git", "-C", str(repo), "fetch", "origin"], capture_output=True, timeout=120)
        r = subprocess.run(["git", "-C", str(repo), "worktree", "add", str(path), f"scrum/{job_id}"],
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


def _login(item):
    """item's user.login (a REST PR or comment), or None."""
    user = item.get("user")
    return user.get("login") if isinstance(user, dict) else None


def _cloud_trusted(pr, job_id):
    """Whether pr's head is this repo's own scrum/<id> branch: a fork PR, or one from another branch, steers nothing."""
    head, base = pr.get("head"), pr.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict) or head.get("ref") != f"scrum/{job_id}":
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


def cloud_pending_clear(root: Path, job_id: str) -> None:
    """Drop job_id's artifactsPending mark under the board lock (serve.py calls it once cloud-home spawned). A missing
    job or mark is a no-op."""
    with locked_board(root) as board:
        for job in board["jobs"]:
            if job["id"] == job_id:
                job.pop("artifactsPending", None)


def _cloud_plan(repo, job_id, prs):
    """(state, pairs, reason, needs a worktree, abort) for this job's newest [scrum <id>] PR, or None while it still
    runs. abort is None, or (requeue, PR number to close or None). Makes the one comments call a needs-human PR needs;
    raises GhError."""
    pr = next((p for p in prs if isinstance(p, dict) and str(p.get("title") or "").startswith(f"[scrum {job_id}]")
               and _cloud_trusted(p, job_id)), None)
    if not pr:
        return None
    url = pr.get("html_url") or ""
    lane = [f"lane={m[1]}"] if (m := CLOUD_LANE.search(str(pr.get("body") or ""))) else []  # first line wins
    if pr.get("merged_at"):
        return "MERGED", ["stage=done", f"pr={url}", "reason="] + lane, None, False, None
    if pr.get("state") == "closed":
        return "CLOSED", [f"pr={url}"] + lane, CLOUD_CLOSED, False, (True, None)
    if CLOUD_LABEL not in [l.get("name") for l in pr.get("labels") or [] if isinstance(l, dict)]:
        return None
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
    if reason.startswith(CLOUD_SELF_ABORT):
        return "ABORTED", [f"pr={url}"] + lane, reason, False, (reason.startswith("requeue:"), number)
    pairs = ["stage=needs-human", f"pr={url}"]
    ref = (pr.get("base") or {}).get("ref")
    if ref:
        pairs.append(f"base=origin/{ref}")
    return "NEEDS-HUMAN", pairs + lane + [f"reason={reason}"], reason, True, None


def _cloud_abort(root, job_id, url, requeue, reason, lane=None):
    """Record pr= (and lane= when given) and abort a job still in stage cloud, atomically; requeue skips a BigBoy
    child (Auto-abort rule)."""
    with locked_board(root) as board:
        job = live(board, check_id(job_id))
        if job["stage"] != "cloud":
            raise SystemExit(f"job {job_id} is {job['stage']}, not cloud; left alone")
        job["pr"] = url
        if lane:
            job["lane"] = lane
        abort_job(root, job, requeue and not job.get("parent"), reason)


def cmd_cloud_sync(root: Path) -> dict:
    """Move every stage-`cloud` job whose PR finished: MERGED -> done, CLOSED -> aborted and requeued, open with the
    scrum:needs-human label -> needs-human with the comment's reason and a local worktree, or, for a requeue:,
    obsolete: or looks already fixed: reason, aborted with the PR closed. Every gh read runs before any write, so a
    gh failure changes nothing. A job that left stage cloud meanwhile is skipped. A moved job with no artifacts branch
    yet gets the internal artifactsPending mark; every run re-checks marked jobs and lists those whose branch arrived.
    Returns {"moved": [{"id","state","pr","reason","worktree","artifacts"}], "arrived": [ids], "error"}."""
    root = Path(root)
    repo = root.parent
    cloud = [j["id"] for j in read_board(root)["jobs"] if j.get("stage") == "cloud"]
    arrived = _cloud_arrivals(root, repo)
    if not cloud:
        return {"moved": [], "arrived": arrived, "error": None}
    try:
        prs = gh_api(repo, CLOUD_PULLS)
        if not isinstance(prs, list):
            raise GhError(f"gh api {CLOUD_PULLS} did not return a list")
        plans = [(job_id, plan) for job_id in cloud if (plan := _cloud_plan(repo, job_id, prs))]
    except GhError as e:
        return {"moved": [], "arrived": arrived, "error": str(e) or type(e).__name__}
    moved = []
    for job_id, (state, pairs, reason, wants_worktree, abort) in plans:
        worktree, url = None, next(p[3:] for p in pairs if p.startswith("pr="))
        try:
            if live(read_board(root), job_id)["stage"] != "cloud":
                continue  # moved meanwhile: add no worktree for it
            if abort:
                lane = next((p[5:] for p in pairs if p.startswith("lane=")), None)
                _cloud_abort(root, job_id, url, abort[0], reason, lane)
            else:
                worktree = cloud_worktree(repo, job_id) if wants_worktree else None
                cmd_set(root, job_id, pairs + ([f"worktree={worktree}"] if worktree else []), expect="cloud",
                        internal=True)
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
                      "artifacts": artifacts_pushed(repo, job_id)})
    pending = {m["id"] for m in moved if not m["artifacts"]}
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
             "BUILDER_BLOCKED", {"key": "a", "why": "Only a Terminal window can approve project .claude edits."})
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
STALLED = "stalled in "  # reason prefix: serve.py's resume, the dashboard's Resume button and SKILL.md read it
STALL = "stalled: "  # new-shape reason prefix: the job keeps its WATCHED stage and has board `stalled` true
AGENT_TYPES_RE = re.compile(r"not loaded as agent types|agent types (?:are )?not loaded|^waiting on the (?:E2E|Check) queue", re.I)
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
    """cooldown-park: while cooling down, stall a round-0 spec or build job (not paused, not stalled, not lilguy or
    cloud) in its stage with reason `stalled: parked for cool down; ...`, so it stops at this checkpoint and
    serve.py's auto_resume restarts it once cool down ends. Every condition is re-read under the board lock; any
    other case writes nothing. Returns {"parked": bool}."""
    try:
        with locked_board(root) as board:
            job = find(board, check_id(job_id))
            if not (cooling_down() and job.get("stage") in PARK_STAGES and not job.get("round")
                    and not job.get("paused") and not job.get("stalled") and job.get("lane") not in ("lilguy", "cloud")):
                raise _Gone
            job.update(stalled=True, reason=f"{STALL}{COOLDOWN_PARK}", updatedAt=now())
    except _Gone:
        return {"parked": False}
    return {"parked": True}


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
            if j.get("autoPlayed"):
                j["holdPause"] = True  # re-paused after an auto-play: deliberate, so the watchdog leaves it paused
        return [j["id"] for j in hit]


def _is_claude(command):
    """True when claude is the program: argv0 named `claude`, a bare `claude` token, or the claude-code package.
    A path that merely passes through `.claude/` (a worktree's dev server) does not count."""
    toks = command.split()
    return bool(toks) and (os.path.basename(toks[0]) == "claude" or "claude" in toks or "claude-code" in command)


def session_alive_fn():
    """One `ps` scan; a job is alive when a claude process line has its id, or when its recorded claude pid is live
    (a job with no pid: when a claude process runs on its recorded tty). When ps can't be read, every job counts as
    alive, so the watchdog never flags on a guess."""
    try:
        r = subprocess.run(["ps", "-axo", "pid=,tty=,command="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return lambda job: True
    out = r.stdout or ""
    if r.returncode != 0 or not out.strip():  # denied (a sandboxed call) or empty: unknown, never "all dead"
        return lambda job: True
    lines = [l.strip() for l in out.splitlines() if _is_claude((l.split(None, 2) + ["", ""])[2])]  # drop pid and tty
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


def cmd_watchdog(root, alive=None):
    """Flag every job stuck in a WATCHED stage with no board update for STALL_MINUTES and no live session: it keeps
    its stage with `stalled` true and a STALL reason, and plays no sound.
    A stuck spec job with no feature.md is an orphaned claim instead: aborted and requeued, not flagged.
    Returns the flagged ids; writes board.json only when it flags something."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALL_MINUTES)
    flagged, requeued = [], []
    try:
        with locked_board(root) as board:
            # a lilguy job in the main checkout has no pipeline to resume: no worktree or builder.
            # limitResetAt: serve.py holds the job until its usage limit resets, then auto_resume restarts it.
            stale = [j for j in board["jobs"] if j.get("stage") in WATCHED and not j.get("waiting")
                     and not j.get("paused") and not lilguy_in_checkout(j) and not j.get("limitResetAt")
                     and not j.get("stalled") and stalled_since(j, cutoff)]
            alive = alive or (session_alive_fn() if stale else None)  # ps only when something could be stalled
            idle_cutoff = datetime.now(timezone.utc) - timedelta(hours=IDLE_HOURS)
            for job in stale:
                live_idle = False
                if alive(job):
                    if not (stalled_since(job, idle_cutoff) and job_dir_idle(root, job["id"], idle_cutoff.timestamp())):
                        continue
                    live_idle = True
                if live_idle:
                    job.update(stalled=True, updatedAt=now(), reason=f"{STALL}no board or job-dir "
                               f"change for {IDLE_HOURS} h (session alive but idle)")
                    log_stop(root, job["id"], "stall", job["reason"])
                    roadmap_stall_locked(root, job)
                    flagged.append(job["id"])
                elif job["stage"] == "spec" and not job.get("parent") \
                        and not (Path(root) / "jobs" / job["id"] / "feature.md").exists():
                    abort_job(root, job, True, ORPHANED)  # nothing to resume: put the item back, no human needed
                    requeued.append(job["id"])
                else:
                    job.update(stalled=True, updatedAt=now(), reason=f"{STALL}no board update "
                               f"for {STALL_MINUTES} min and no live session")
                    log_stop(root, job["id"], "stall", job["reason"])
                    roadmap_stall_locked(root, job)
                    flagged.append(job["id"])
            if not flagged and not requeued:
                raise _Gone
    except _Gone:
        pass
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
    if cooling_down() or not (Path(root) / "roadmap.md").is_file():
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
    (default start_local_db) once, re-probe every 5 s for up to wait seconds, and return {"up", "started": true}, plus
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
        error = (start or start_local_db)()
    except Exception as e:  # a starter failure is reported, never raised
        error = f"database start failed: {e}"
    up = False
    for _ in range(max(1, int(wait // 5))):
        sleep(5)
        if probe(host, port):
            up = True
            break
    return {"up": up, "started": True, **({"error": error} if error and not up else {})}


def stop_worktree_servers(repo: Path, wt: str | None, listening=None, wait: float = 0.0) -> list[int]:
    """SIGTERM every listener whose cwd is the job worktree wt or under it; returns the pids signalled, in order.
    wt must sit strictly inside <repo>/.claude/worktrees/ and exist, else nothing is read or signalled (a main-checkout
    job never loses Trevor's own server). Never a pid that also listens on a KEEP_PORTS port, never this process.
    listening defaults to listeners(). With wait > 0, each pid still alive after polling every 0.25 s for wait
    seconds gets SIGKILL: a wedged Node event loop may never run its SIGTERM handler."""
    if not wt:
        return []
    base = os.path.realpath(Path(repo) / ".claude" / "worktrees") + os.sep
    wt = os.path.realpath(wt)
    if not wt.startswith(base) or not os.path.isdir(wt):
        return []
    listening = listeners() if listening is None else listening
    keep = {pid for pid, port, _ in listening if port in KEEP_PORTS} | {os.getpid()}
    killed = []
    for pid, _, cwd in listening:
        if pid in keep or pid in killed or not (cwd == wt or cwd.startswith(wt + os.sep)):
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
    sub.add_parser("process-health").add_argument("digest")
    sub.add_parser("window-report")
    sub.add_parser("move-ratio").add_argument("id")
    sub.add_parser("lilguy-fit").add_argument("id")
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
    fo = sub.add_parser("fable-ok")
    fo.add_argument("id")
    fo.add_argument("role")
    po = sub.add_parser("prod-ok")
    po.add_argument("id")
    po.add_argument("bullet")
    pa = sub.add_parser("plan-apply")
    pa.add_argument("id")
    pa.add_argument("--fix", action="store_true")
    sub.add_parser("ready").add_argument("id")
    sub.add_parser("runall-start")
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
    sub.add_parser("check-reuse").add_argument("id")
    sub.add_parser("render-paths").add_argument("id")
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
        print(cmd_new(a.dir, a.title, a.id, started_by=a.by))
    elif a.cmd == "set":
        cmd_set(a.dir, a.id, a.pairs, unpause=a.unpause)
    elif a.cmd == "sync":
        print(json.dumps(cmd_sync(a.dir, a.id)))
    elif a.cmd == "ask":
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
        print(json.dumps({"killed": stop_worktree_servers(Path(a.dir).resolve().parent, wt, wait=5)}))
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
    elif a.cmd == "process-health":
        print(json.dumps(cmd_process_health(a.dir, a.digest)))
    elif a.cmd == "window-report":
        print(json.dumps(cmd_window_report(a.dir)))
    elif a.cmd == "move-ratio":
        out = cmd_move_ratio(a.dir, a.id)
        print(json.dumps(out))
        return 1 if out.get("ok") is False else 0
    elif a.cmd == "lilguy-fit":
        print(json.dumps(cmd_lilguy_fit(a.dir, a.id)))
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
        print(json.dumps(cmd_ready(a.dir, a.id)))
    elif a.cmd == "runall-start":
        print(json.dumps(cmd_runall_start(a.dir)))
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
    elif a.cmd == "check-reuse":
        print(json.dumps(cmd_check_reuse(a.dir, a.id)))
    elif a.cmd == "render-paths":
        print(json.dumps(cmd_render_paths(a.dir, a.id)))
    elif a.cmd == "fable-ok":
        print(cmd_fable_ok(a.dir, a.id, a.role))
    elif a.cmd == "prod-ok":
        print(cmd_prod_ok(a.dir, a.id, a.bullet))
    elif a.cmd == "spawn":
        proc, log = spawn(a.dir, a.id, a.action, a.prompt, model=a.model)
        print(json.dumps({"log": log, "pid": proc.pid}))
    elif a.cmd == "backlog-spec":
        out = cmd_backlog_spec(a.dir, a.id)
        print(json.dumps(out))
        spawn_estimates(a.dir, out["added"])
    else:
        spawn_estimates(a.dir, cmd_backlog_add(a.dir, a.items, a.setup, a.priority, a.top,
                                                    "back" if a.back else "t" if a.trevor else None, a.critical))


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
    """fable-ok: FABLE_MODEL or "none" for a new planner or spec-writer spawn. Only a job_complex job on the board is
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
    state = fable_state(usage, now)
    model = FABLE_MODEL if state == "ok" else "none"
    job = Path(root) / "jobs" / job_id
    if job.is_dir():
        pct = {k: "—" if v is None else f"{round(v)}%" for k, v in fable_used(usage, now).items()}
        with open(job / "fable.log", "a") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')}\t{role}\t{'opus' if model == 'none' else 'fable'}"
                     f"\t5h {pct['5h']}\t7d {pct['7d']}\t{state}\n")
    return model


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


def spawn(root: Path, job_id: str, action: str, prompt: str | None = None, flags=("--permission-mode", "acceptEdits"),
          model: str | None = None, account: str | None = None) -> tuple[subprocess.Popen, str]:
    """Start `claude -p <prompt> <flags>` in the repo, detached, logging to scrum/runs/, and set the job's runlog and account.
    start/resume get `--model <Orchestrator model>` (or `<Big ticket model>`, see orchestrator_model) unless `model` is given.
    `account` None: pick_account, preferring the job's recorded account; with none free, the one whose limit ends soonest
    (the recorded account on a tie), else the first (Trevor's Play and Resume are never refused on usage). Any account but the first runs with
    CLAUDE_CONFIG_DIR=<its dir>; the first runs with CLAUDE_CONFIG_DIR removed. Returns (proc, log path relative to root)."""
    if not SPAWN_ID_RE.fullmatch(job_id):
        raise SystemExit(f"bad spawn id {job_id!r}")
    if not SPAWN_ACTION_RE.fullmatch(action):
        raise SystemExit(f"bad spawn action {action!r}")
    if model is not None and not MODEL_RE.fullmatch(model):
        raise SystemExit(f"bad model {model!r}; must match {MODEL_RE.pattern}")
    if model is None and action in ("start", "resume"):
        model = orchestrator_model(root, job_id)
    prompt = prompt if prompt is not None else f"/trevskills-scrum {action} {job_id}"
    accs = accounts()
    if account is None:
        try:
            recorded = find(read_board(root), job_id).get("account")
        except (SystemExit, OSError):  # not on the board (run-all, digest, weekly), or no board yet
            recorded = None
        account = pick_account(time.time(), prefer=recorded)[0] or fallback_account(time.time(), recorded)
    acc = next((a for a in accs if a.name == account), accs[0])  # an unlisted account (its dir gone) runs on the first
    env = dict(os.environ, CLAUDE_NOTIFIER_DISABLE="1",  # board.py plays scrum's sounds
               CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0")  # -p kills background agents 10 min after the last turn otherwise
    env.pop("CLAUDE_CONFIG_DIR", None)
    if acc != accs[0]:
        env["CLAUDE_CONFIG_DIR"] = str(acc.dir)
    logs = root / "runs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{action}-{job_id}.log"
    argv = [CLAUDE, "-p", prompt, *(("--model", model) if model else ()), *flags]
    try:
        with open(log, "w") as fh:
            proc = subprocess.Popen(argv, cwd=root.parent,
                                    stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                                    env=env)
    except OSError:  # never started (e.g. the claude CLI missing mid-update): no empty log that reads like a dead session
        log.unlink(missing_ok=True)
        raise
    try:  # the run log link reads this; a job that isn't on the board (run-all, digest) has no row to set
        cmd_set(root, job_id, [f"runlog=runs/{log.name}", "tty=", "outcome=", f"account={acc.name}"], unpause=True)  # Play starts on a paused job; a stale interactive tty would still match the hook and liveness checks
    except SystemExit:
        pass
    return proc, f"runs/{log.name}"


if __name__ == "__main__":
    sys.exit(main())
