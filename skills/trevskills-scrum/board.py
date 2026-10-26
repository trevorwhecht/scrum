#!/usr/bin/env python3
"""The scrum team's board. Only the /trevskills-scrum orchestrator calls this; nothing else writes board.json.

  board.py new "<title>" [--id ID] create jobs/<id>/ and a board entry, print the id (--id keeps a given id)
  board.py set <id> key=value ...  set stage/round/limit/pr/reason/worktree/builder/base/tty/runlog/lane/setup/waiting/specwriter/cloud/outcome (empty = null);
                                   stage=needs-human is refused: park a job with ask
  board.py set --unpause <id> ...  the same, on a job Trevor paused too (resume and rework only); with stage= it
                                   clears the pause
  board.py ask <id> "<q>" --a "Label=command" --b "Label=command" [--c ...] [--recommend KEY WHY]  park the job at
                                   needs-human with a closed question (command: approve|resume|abort <id>
                                   [--requeue|--cascade], rework <id> "<text>", shell: <cmd>), log it to questions.log;
                                   --recommend stores {"key","why"}, the option the agent advises, cleared with the
                                   question. With [--kind K] (K in UNBLOCK_KINDS, under 2 unblocks, not yet unblocked
                                   for K) the job is not parked: it keeps its stage, the unblock is logged and
                                   {"unblock": true, "n": N} is printed; else it parks and prints {"unblock": false}
                                   (lanes/unblock.md)
  board.py unblock-log <id>        read jobs/<id>/unblock-<unblocks>.md, log its verdict line to questions.log, print
                                   {"verdict","blocker","kind","n"} (verdict INVALID when missing or unreadable)
  board.py answer <id> <a|b|c>     log the pick on the job's open question to questions.log, print that option as JSON
  board.py sync <id>               re-read jobs/<id>/ into the board, print round status as JSON
  board.py next                    claim the first "- [ ]" backlog item that waits on no {needs #id} prerequisite and
                                   no {setup: …} Human setup as a new job, print {"id","feature"}
  board.py cloud-claim <N>         claim up to N open backlog items for the Cloud lane, skipping any that waits
                                   (prerequisite or Human setup), has no pre-written spec with Likely files, or shares a
                                   Likely file with an earlier pick or a cloud/build job; print {"claimed": [{"id","feature"}, ...]}
  board.py backlog-add [--setup "<step>; <step>"] [--priority N] "<item>"...  append "- [ ] <item>" lines to backlog.md
                                   (--setup adds a " {setup: step; step}" marker: next and runall-start skip the item until
                                   Trevor clicks Setup done; --priority adds a " {p:N}" importance marker, N 1-5), then
                                   estimate each in the background
  board.py rank-backlog            one-off backfill: Jev rates each open backlog item with no {p:N} marker (jev-gate.py
                                   rank, logged to jev.log), writes {p:N} where it gave one, print {"rated","unrated","skipped"}
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
  board.py digest-due              print {"due","undigested","questionsGrowth"}: done jobs in no digests/*/jobs.txt and
                                   questions.log lines since the last digest's questions.lines; due at 10+ jobs or 15+ lines
  board.py digest-start            claim them all as digests/<NNN>/jobs.txt (+ questions.lines), print {"id","jobs"}
                                   (id null = nothing new; starts with no jobs when the questions trigger fired)
  board.py digest-trim <NNN>       cut that digest's done job folders to feature.md, spec.md, decision.md
  board.py pipeline-fit <NNN>      print {"digest","jobs"}: each listed job's lane, agents, diff size, verdicts, fix rounds
                                   and whether a cheaper lane would have done (read-only; Digest step 1)
  board.py digest-verify <id> [--worktree PATH] [--base REF]
                                   exit 0 and print {"ok","files","proposals"} when the job worktree's rules-file diff
                                   (agents/scrum-*.md, SKILL.md, skills/trevskills-scrum/lanes/*.md) is exactly its feature.md's
                                   cited queued digest edits; else exit 1 and print {"ok": false, "error"}
                                   (SKILL.md Merge's Agent rules guard).
                                   --worktree/--base override the board's values (an empty one fails, never falls back)
  board.py rules-check <id> [--worktree PATH] [--base REF]
                                   exit 0 and print {"ok","files","failures"} when the job's diff changes a rules file and
                                   passes docs/skill-standards.md script rules 1-8; else exit 1 (lanes/rules-gate.md)
  board.py review-plan <id> [--incremental]  SKILL.md Review step 2 minus the Jev gate: incremental re-review (only with
                                   --incremental) or full review, write round-N's carried-forward or UI/UX and security
                                   skip files, print {"spawn","since"} (since null = full review)
  board.py move-ratio <id>         print {"added","moved","ratio"}: the share of the job worktree's BASE...HEAD added lines
                                   git marks as moved (SKILL.md Review MOVE_ONLY); else exit 1 and print {"ok": false, "error"}
  board.py lilguy-fit <id>         print {"fit","why"}: whether the job is tiny (backlog points 1, or jev.log's last model
                                   answer score < 1.5 at confidence >= 0.7) with no hard-stop word in feature.md
                                   (SKILL.md New job step 3's Lilguy route)
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
  board.py watchdog                flag jobs stuck 30+ min in spec/build/check/review/approve with no live session
                                   needs-human (reason "stalled in <stage>: ..."), print {"flagged"}; a stuck spec
                                   job with no feature.md is an orphaned claim: aborted and requeued, never flagged
  board.py cloud-sync              move each stage-cloud job whose [scrum <id>] PR finished (one gh REST pulls call):
                                   MERGED -> done, CLOSED -> aborted + requeued, open + scrum:needs-human -> needs-human with
                                   the PR comment's reason and a fetched worktree (a requeue:/obsolete:/looks already
                                   fixed: reason aborts it and closes the PR instead); only a same-repo scrum/<id> head PR and
                                   its author's comments count. A moved job with no scrum-artifacts/<id> branch yet is
                                   re-checked each run (24 h max); print {"moved","arrived","error"}, exit 1 on a gh
                                   error (nothing changed). serve.py runs it every 10 min while a job is in stage cloud
  board.py spawn <id> <action> ["<prompt>"] [--model M]  start a detached headless `claude -p <prompt>` (default
                                   "/trevskills-scrum <action> <id>") from the repo, logging to runs/; start/resume get the
                                   Orchestrator model unless --model; set the job's runlog (ignored when <id> is not on the
                                   board), print {"log","pid"}
  board.py hook                    Claude Code hook: read one event from stdin, set or clear `waiting` on this tty's job
  board.py statusline              Claude Code status line: save stdin's rate_limits to ~/.claude/usage.json, print "5h N% · 7d N%"

Verdicts are never typed in by hand: sync derives them from the first line of each file, so the board can't drift
from the files. --dir points at the project's scrum/ folder (default ./scrum).
"""
import argparse, fcntl, hashlib, importlib.util, json, os, re, secrets, shutil, subprocess, sys, tempfile, time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import permutations
from pathlib import Path

REVIEWERS = ("security", "ux", "ui", "code")
STAGES = ("plan", "running", "waiting", "spec", "build", "check", "review", "approve", "merging", "done", "needs-human",
          "aborted", "cloud")  # cloud: running in a claude.ai/code session (SKILL.md Cloud lane); never WATCHED
FIELDS = ("stage", "round", "limit", "pr", "reason", "worktree", "builder", "base", "tty", "runlog", "lane", "setup",
          "waiting", "specwriter", "cloud", "outcome")  # the `waiting` field (paused on Trevor) is unrelated to the bigboy "waiting" stage
ACTIVE = ("spec", "build", "check", "review", "approve", "merging")  # stages an interactive session can pause in
# Where the job's terminal and run log are: both are matched or read by path, so they're strict.
SHAPES = {"tty": re.compile(r"^ttys[0-9]+$"), "runlog": re.compile(r"^runs/[\w.-]+\.log$"),
          "lane": re.compile(r"^(?:fast|standard|debug|bigboy|runall|lilguy)$"),  # no lane key = standard
          "setup": re.compile(r"^(?:pending|done)$"),  # a bigboy child's Human setup wait
          "cloud": re.compile(r"^https://claude\.ai/code/session_[A-Za-z0-9_-]+$")}  # the dashboard links it
ID_RE = re.compile(r"^\d{3,}-[a-z0-9-]+$")
# The scrum commands a needs-human question's option may run (shape only: the id need not be the asked job's).
ASK_COMMAND_RE = re.compile(r'(?:(?:approve|resume) {id}|abort {id}(?: --requeue| --cascade)?|rework {id} "[^"]+"'
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


def play(path):
    """Fire-and-forget afplay; never blocks or breaks the board. SCRUM_MUTE (tests) silences it."""
    if os.environ.get("SCRUM_MUTE"):
        return
    try:
        subprocess.Popen(["afplay", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
        yield board
        for job in board["jobs"]:  # a question lives only while its job waits on Trevor, whoever moved it on
            if job.get("stage") != "needs-human":
                job.pop("question", None)
                job.pop("options", None)
                job.pop("recommend", None)
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
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "job"


def add_job(root, board, title, job_id=None):
    """Caller must hold the board lock. job_id keeps an id given elsewhere (a cloud job keeps its local board's id)."""
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
    })
    return job_id


def cmd_new(root, title, job_id=None):
    with locked_board(root) as board:
        return add_job(root, board, title, job_id)


# --- backlog.md: "- [ ] [5] Text {#k3f9} {p:4} {needs #a1b2} {setup: step; step} → 003-id <!-- why -->"; points, the id,
# priority (1-5, highest claimed first), needs and setup markers, the job and the estimate's reason are optional. An item's text excludes the markers, so its spec_path
# never changes. A setup marker is a Human setup checklist: next and runall-start skip the item until Setup done. ---
FIB = (1, 2, 3, 5, 8, 13)
ITEM_RE = re.compile(r"^- \[( |x)\] (?:\[(\d+|\?)\] )?(.*?)(?: \{#([a-z0-9]{4})\})?(?: \{p:([1-5])\})?(?: \{needs((?: #[a-z0-9]{4})+)\})?"
                     r"(?: \{setup: ([^{}]*)\})?(?: → (\d{3,}-[a-z0-9-]+))?(?: <!-- (.*?) -->)?\s*$")
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
            done, pts, text, item_id, prio, needs, setup, job, why = m.groups()
            items.append({"index": len(items), "line": n, "done": done == "x",
                          "points": int(pts) if pts and pts.isdigit() else None, "text": text.strip(), "why": why, "job": job,
                          "id": item_id, "priority": int(prio) if prio else None, "needs": needs.replace("#", "").split() if needs else [],
                          "setup": [s.strip() for s in setup.split(";") if s.strip()] if setup else []})
    return lines, items


def format_item(item):
    return (f"- [{'x' if item['done'] else ' '}] " + (f"[{item['points']}] " if item["points"] else "") + item["text"]
            + (f" {{#{item['id']}}}" if item.get("id") else "")
            + (f" {{p:{item['priority']}}}" if item.get("priority") else "")
            + (" {needs " + " ".join(f"#{n}" for n in item["needs"]) + "}" if item.get("needs") else "")
            + (" {setup: " + "; ".join(item["setup"]) + "}" if item.get("setup") else "")
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


def check_points(points):
    if points is not None and (isinstance(points, bool) or points not in FIB):
        raise SystemExit(f"points must be one of {FIB} or null, got {points!r}")


def backlog_op(root, op, index=None, text=None, points=KEEP, delta=0, setup=None, to=None, priority=None):
    """add / edit / delete / move / setup-done one backlog item under the board lock. Returns the new item list.
    add's setup ("step; step") parks the new item behind a Human setup checklist; setup-done removes that marker."""
    with locked_board(root):
        lines, items = read_backlog(root)
        if op == "add":
            if not clean(text or ""):
                raise SystemExit("backlog item text is empty")
            if points is not KEEP:
                check_points(points)
            check_priority(priority)
            lines.append(format_item({"done": False, "points": None if points is KEEP else points, "priority": priority,
                                      "text": clean(text, ITEM_MAX), "job": None, "why": None,
                                      "setup": None if setup is None else setup_steps(setup)}))
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


def cmd_rank_backlog(root) -> dict:
    """Rate every open, unmarked backlog item with jev-gate's rank step, one Jev call at a time outside the lock, then
    write each {p:N} under the lock on the first open, unmarked item with the exact same text (gone or edited = skip)."""
    # jev-gate.py has a hyphen, so no plain import; loaded only for this one-off
    spec = importlib.util.spec_from_file_location("jev_gate", Path(__file__).resolve().with_name("jev-gate.py"))
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    items = [i for i in read_backlog(root)[1] if not i["done"]]
    todo = [i["text"] for i in items if i["priority"] is None]
    rated = []
    for text in todo:
        decision = gate.run("rank", lambda asked, t=text: gate.rank_ticket(t, Path(root), asked), Path(root) / "jev.log")
        if m := re.fullmatch(r"p([1-5]) \S+", decision):
            rated.append((text, int(m[1])))
    written = 0
    if rated:
        with locked_board(root):
            lines, items_now = read_backlog(root)
            for text, n in rated:
                item = next((i for i in items_now if not i["done"] and i["priority"] is None and i["text"] == text), None)
                if item:
                    item["priority"] = n
                    lines[item["line"]] = format_item(item)
                    written += 1
            if written:
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
        job_id = add_job(root, board, item["text"][:60])
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
            job_id = add_job(root, board, item["text"][:60])
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
                            and (kid["stage"] in ("waiting", "needs-human") or kid.get("paused") or kid.get("play_queued")):
                        parent = jobs.get(kid.get("parent")) or {}
                        abort_job(root, kid, parent.get("lane") == "runall", f"Removed with {job_id}")
                        aborted.append(kid["id"])
    return aborted


def abort_job(root, job, requeue, reason):
    """cmd_abort's body; caller holds the lock. With no feature.md (a claim whose session died before writing it),
    the requeue reopens the claimed backlog line in place, points, id, needs and pre-written spec kept."""
    folder = Path(root) / "jobs" / job["id"]
    feature = folder / "feature.md"
    job.update(stage="aborted", reason=reason, updatedAt=now(), files=job_files(folder))
    job.pop("paused", None)  # an aborted job is never played
    job.pop("play_queued", None)  # nor started by serve.py's Play queue
    if not requeue:
        return
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


def cmd_register(repo):
    """Add a repo to the dashboard's project list. Idempotent; /trevskills-scrum calls it on every run."""
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name("projects.lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        paths = read_registry()
        repo = str(Path(repo).resolve())
        if repo not in paths:
            tmp = path.with_name("projects.json.tmp")
            tmp.write_text(json.dumps(paths + [repo], indent=2) + "\n")
            os.replace(tmp, path)


def projects():
    """{display name: repo path} for registered repos that still have a scrum/ folder. Names are the folder
    name, or parent/folder when two repos share one."""
    repos = [Path(p) for p in read_registry() if (Path(p) / "scrum").is_dir()]
    counts = {}
    for r in repos:
        counts[r.name] = counts.get(r.name, 0) + 1
    return {(r.name if counts[r.name] == 1 else f"{r.parent.name}/{r.name}"): r for r in repos}


def cmd_backlog_add(root, items, setup=None, priority=None):
    """Append each non-empty item, each with the Human setup checklist `setup` ("step; step") when given; returns the
    texts as stored. An empty checklist adds nothing."""
    if setup is not None:
        setup_steps(setup)
    check_priority(priority)
    added = []
    for item in items:
        if clean(item):
            backlog_op(root, "add", text=item, setup=setup, priority=priority)
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
TRIM_KEEP = {"feature.md", "spec.md", "decision.md"}
QUESTIONS_DIGEST_LINES = 15  # a digest is also due once questions.log grew this many lines since the last one


def digested_ids(root):
    """Every job id listed in any digest's jobs.txt, except a failed digest's (error.md), so the next digest re-claims them."""
    return {line.strip() for f in (Path(root) / "digests").glob("*/jobs.txt") if not f.with_name("error.md").exists()
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


def cmd_digest_due(root):
    path = Path(root) / "board.json"
    n = len(undigested(root, json.loads(path.read_text()) if path.exists() else {"jobs": []}))
    growth = questions_growth(root)
    return {"due": n >= 10 or growth >= QUESTIONS_DIGEST_LINES, "undigested": n, "questionsGrowth": growth}


def cmd_digest_start(root):
    """Claim every undigested done job as digest NNN, under the lock, so two triggers never share a job. Also starts
    with no jobs when questions.log grew QUESTIONS_DIGEST_LINES since the last digest; questions.lines records its count."""
    with locked_board(root) as board:
        jobs = undigested(root, board)
        if not jobs and questions_growth(root) < QUESTIONS_DIGEST_LINES:
            return {"id": None, "jobs": []}
        digest_id = claim_folder(Path(root) / "digests")
        (Path(root) / "digests" / digest_id / "jobs.txt").write_text("".join(f"{j}\n" for j in jobs))
        (Path(root) / "digests" / digest_id / "questions.lines").write_text(f"{questions_lines(root)}\n")
        return {"id": digest_id, "jobs": jobs}


def claim_folder(parent):
    """Create the next 3-digit folder (001, 002, ...) under parent and return its name. Caller holds the board lock."""
    parent.mkdir(exist_ok=True)
    name = f"{max((int(p.name) for p in parent.iterdir() if DIGEST_RE.fullmatch(p.name)), default=0) + 1:03d}"
    (parent / name).mkdir()
    return name


def cmd_digest_trim(root, digest_id):
    """Slim each listed done job's folder to feature.md, spec.md and decision.md; returns the trimmed ids. Idempotent."""
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
                if p.name in TRIM_KEEP and p.is_file():
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
    """(added, deleted, files) from the worktree, else the PR's REST totals; (None, None, None) when unreadable."""
    if job.get("worktree") and Path(job["worktree"]).is_dir():
        diff = _route_diff(job)
        if diff is None or any(a is None for a, _, _ in diff[0]):
            return None, None, None
        rows, names = diff
        return sum(a for a, _, _ in rows), sum(d for _, d, _ in rows), len(names)
    m = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)", job.get("pr") or "")
    if not m:
        return None, None, None
    try:
        pr = gh_api(Path(root), f"repos/{m[1]}/{m[2]}/pulls/{m[3]}")
        out = tuple(pr[k] for k in ("additions", "deletions", "changed_files"))
    except (GhError, TypeError, KeyError):
        return None, None, None
    return out if all(type(v) is int for v in out) else (None, None, None)


def cmd_pipeline_fit(root, digest_id: str) -> dict:
    """{"digest", "jobs"}: for each job in digests/<NNN>/jobs.txt, its lane, agents spawned, diff size, verdicts per
    round, fix rounds, and whether a standard/debug job that passed round 1 on a fast-sized diff was over-routed."""
    d = Path(root) / "digests" / str(digest_id)
    if not DIGEST_RE.fullmatch(str(digest_id)) or not (d / "jobs.txt").is_file():
        raise SystemExit(f"no digest {digest_id!r}")
    listed = [l.strip() for l in (d / "jobs.txt").read_text().splitlines() if ID_RE.match(l.strip())]
    jobs = {j["id"]: j for j in read_board(root)["jobs"]}
    out = []
    for job_id in listed:
        job, folder = jobs.get(job_id, {}), Path(root) / "jobs" / job_id
        lane = job.get("lane") or "standard"
        rounds = sorted(int(p.name[6:]) for p in folder.glob("round-*")
                        if re.fullmatch(r"round-\d+", p.name) and p.is_dir())
        agents = [a for a, f in (("spec", "spec.md"), ("builder", "build.md")) if (folder / f).is_file()]
        agents += [f"review-{r}" for r in REVIEWERS if any(_real_review(folder / f"round-{n}" / f"review-{r}.md")
                                                           for n in rounds)]
        agents += ["approver"] if (folder / "decision.md").is_file() else []
        verdicts = {str(n): {r: first_word(folder / f"round-{n}" / f"review-{r}.md", ("PASS", "CHANGES"))
                             for r in REVIEWERS} for n in rounds}
        added, deleted, files = _fit_diff(root, job)
        size = None if added is None else added + deleted
        over = (lane in ("standard", "debug") and "1" in verdicts and set(verdicts["1"].values()) == {"PASS"}
                and size is not None and size <= FAST_MAX_LINES and files <= FAST_MAX_FILES)
        fit = ("lilguy" if size <= LILGUY_MAX_LINES and files <= LILGUY_MAX_FILES else "fast") if over else lane
        out.append({"id": job_id, "lane": lane, "agents": agents, "added": added, "deleted": deleted, "files": files,
                    "verdicts": verdicts, "fix_rounds": max(max(rounds, default=1) - 1, 0), "over_routed": over,
                    "fit": fit})
    return {"digest": str(digest_id), "jobs": out}


# --- digest-verify: Merge's Agent rules guard lets a job through without a human when its rules-file diff is exactly
# the digest edits Trevor already approved (status queued) and nothing else. Any doubt fails safe to Trevor.
CITATION_RE = re.compile(r"(?:(\S+)\s+)?digest\s+(\d{3})\s+([\w-]+)")
RULES_RE = re.compile(r"(^|/)agents/scrum-[^/]*\.md$|(^|/)SKILL\.md$|(^|/)trevskills-scrum/lanes/[^/]*\.md$")
DIGEST_ORDERS_MAX = 6  # up to this many proposals in one file, every application order is tried


def digest_citations(root: Path, text: str) -> list[tuple[Path, str, str]]:
    """(scrum dir, digest id, pid) per unique `[<project>] digest NNN pid` citation in text, in order. A registered
    project name before `digest` means that repo's scrum/ folder; anything else means root."""
    names, out = projects(), []
    for m in CITATION_RE.finditer(text):
        scrum = names[m[1]] / "scrum" if m[1] in names else Path(root)
        cite = (scrum, m[2], m[3])
        if cite not in out:
            out.append(cite)
    return out


def _git(worktree, *args):
    r = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, timeout=60)
    if r.returncode:
        raise ValueError(f"git {' '.join(args[:2])} failed: {r.stderr.decode(errors='replace').strip()[:200]}")
    return r.stdout


def _cited_proposal(root, scrum, digest_id, pid):
    """(repo-relative file, proposal) for one citation; ValueError says why it doesn't count."""
    path = Path(scrum) / "digests" / digest_id / "proposals.json"
    try:
        raw = json.loads(path.read_text()).get("proposals")
    except (OSError, ValueError, AttributeError):
        raise ValueError(f"digest {digest_id} {pid}: no readable {path}")
    p = next((x for x in raw if isinstance(x, dict) and x.get("id") == pid), None) if isinstance(raw, list) else None
    if p is None:
        raise ValueError(f"digest {digest_id} {pid}: no such proposal in {path}")
    if not all(isinstance(p.get(k), str) for k in ("id", "target", "old", "new")) or p["old"] == p["new"] \
            or not p["old"] or p.get("kind", "edit") != "edit":
        raise ValueError(f"digest {digest_id} {pid}: not a valid edit proposal")
    if p.get("status") != "queued":
        raise ValueError(f"digest {digest_id} {pid}: status is {p.get('status')!r}, not queued")
    if not os.path.isabs(p["target"]):
        raise ValueError(f"digest {digest_id} {pid}: target {p['target']} is not an absolute path")
    rel = os.path.relpath(os.path.realpath(p["target"]), os.path.realpath(Path(root).resolve().parent))
    if rel == ".." or rel.startswith(".." + os.sep):
        raise ValueError(f"digest {digest_id} {pid}: target {p['target']} is outside this repo")
    return Path(rel).as_posix(), p


def _applies(base_text, props, head_text):
    """True when replacing the first occurrence of each old with its new, in citation order or (at most
    DIGEST_ORDERS_MAX proposals) any order, turns base_text into head_text. Each old must occur once in base_text."""
    if any(base_text.count(p["old"]) != 1 for p in props):
        return False
    orders = permutations(props) if len(props) <= DIGEST_ORDERS_MAX else [props]
    for order in orders:
        text = base_text
        for p in order:
            if p["old"] not in text:
                break
            text = text.replace(p["old"], p["new"], 1)
        else:
            if text == head_text:
                return True
    return False


def cmd_digest_verify(root: Path, job_id: str, worktree: str | None = None, base: str | None = None) -> dict:
    """{"ok": True, "files", "proposals"} when every rules file the job changed is exactly its cited queued digest edits,
    and every cited proposal's file changed; else {"ok": False, "error"}. worktree/base, when not None, replace the
    board's values (Merge passes its own $WT/$BASE so the verified range is the merged one); empty fails."""
    try:
        job = find(read_board(root), check_id(job_id))
        feature = Path(root) / "jobs" / job_id / "feature.md"
        cites = digest_citations(root, feature.read_text(errors="replace") if feature.is_file() else "")
        if not cites:
            raise ValueError("feature.md cites no digest proposal")
        wt = job.get("worktree") if worktree is None else worktree
        base = job.get("base") if base is None else base
        if not wt or not base:
            raise ValueError(f"no {'worktree' if not wt else 'base'}")
        if base.startswith("-"):
            raise ValueError(f"bad base {base!r}")
        by_file, labels = {}, []
        for scrum, digest_id, pid in cites:
            rel, p = _cited_proposal(root, scrum, digest_id, pid)
            by_file.setdefault(rel, []).append(p)
            labels.append(f"{Path(scrum).resolve().parent.name} digest {digest_id} {pid}")
        changed = [f for f in _git(wt, "diff", "--name-only", f"{base}...HEAD", "--").decode().splitlines() if RULES_RE.search(f)]
        if not changed:
            raise ValueError("the diff changes no rules file")
        if extra := next((f for f in changed if f not in by_file), None):
            raise ValueError(f"{extra} changed but no cited proposal targets it")
        if missing := next((f for f in by_file if f not in changed), None):
            raise ValueError(f"{missing} is a cited proposal's target but is not changed")
        mb = _git(wt, "merge-base", base, "HEAD").decode().strip()
        for f in changed:
            try:
                before = _git(wt, "show", f"{mb}:{f}").decode()
                after = _git(wt, "show", f"HEAD:{f}").decode()
            except (ValueError, UnicodeDecodeError):
                raise ValueError(f"{f}: missing or unreadable at the merge-base or HEAD")
            if not _applies(before, by_file[f], after):
                raise ValueError(f"{f}: HEAD is not exactly the merge-base with its cited proposals applied")
        return {"ok": True, "files": changed, "proposals": labels}
    except (ValueError, OSError, SystemExit, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)}


# --- rules-check: the script rules (1-8) of docs/skill-standards.md over a job's rules diff. Merge's Agent rules guard
# merges without a human when this exits 0 and scrum-review-rules writes VERDICT: PASS (lanes/rules-gate.md). Rule 8:
# this block and every board.py line naming rules-check are human-only, so no unattended diff can loosen them.
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PERSON_RE = re.compile(r"\b(I|[Yy]ou|[Yy]our|[Ww]e|[Oo]ur)\b")  # rule 3: descriptions are third person
AT_LINK_RE = re.compile(r"(^|\s)@[\w.~/-]*/[\w./-]*\.md\b", re.M)  # rule 5: an @path import loads the file eagerly
OTHER_LANE_RE = re.compile(r"lanes/([\w-]+)\.md")
NAME_MAX, DESC_MAX, AGENT_DESCS_MAX_TOKENS = 64, 1024, 15000  # the skill spec's limits; sub-agents warn past 15k tokens
BODY_MAX_LINES, BODY_MAX_TOKENS = 500, 5000  # skill best practices: under 500 lines; agentskills.io: 5k-token body
REF_TOC_LINES, TOC_WITHIN = 100, 10  # best practices: a reference over 100 lines starts with a contents list
HUMAN_ONLY_FILES = ("docs/skill-standards.md", "agents/scrum-review-rules.md", "skills/trevskills-scrum/lanes/rules-gate.md")
HUMAN_ONLY_SECTIONS = {
    "skills/trevskills-scrum/SKILL.md": [
        ("the never-list", "This skill is a sanctioned exception", "\n## Setup"),
        ("the Merge step 1 guard bullets", "1. **Preconditions:**", "\n2. Run `B set $ID stage=merging`")],
    "skills/trevskills-scrum/board.py": [("the rules-check code", "# --- rules-check:", "# --- end rules-check")],
}


def _section(text, start, end):
    """text from start up to end, or None when either marker is missing."""
    i = text.find(start) if text is not None else -1
    j = text.find(end, i) if i >= 0 else -1
    return text[i:j] if j >= 0 else None


def _frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return dict(l.split(": ", 1) for l in m.group(1).splitlines() if ": " in l) if m else None


def _tokens(text):
    return len(text) // 4  # ponytail: chars/4 estimate, a real tokenizer is not stdlib


def _file_problems(rel, text):
    """Rules 1, 2, 3 and 5 for one rules file's text. Messages carry no line numbers, so base and HEAD compare."""
    out = []
    if rel.endswith("SKILL.md") or rel.startswith("agents/") or "/agents/" in rel:
        fm = _frontmatter(text) or {}
        name, desc = fm.get("name", ""), fm.get("description", "")
        if not name or not desc:
            out.append(f"rule 1: {rel}: frontmatter needs name and description")
        if name and (not NAME_RE.match(name) or len(name) > NAME_MAX or re.search("claude|anthropic", name, re.I)):
            out.append(f"rule 2: {rel}: name must be lowercase-hyphenated, {NAME_MAX} chars or less, without claude or anthropic")
        if len(desc) > DESC_MAX:
            out.append(f"rule 3: {rel}: description is over {DESC_MAX} chars")
        out += [f"rule 3: {rel}: description has an angle bracket" for _ in re.findall("[<>]", desc)]
        out += [f"rule 3: {rel}: description is not third person ({m})" for m in PERSON_RE.findall(desc)]
    out += [f"rule 5: {rel}: has an @ link; name the file instead" for _ in AT_LINK_RE.finditer(text)]
    if "/lanes/" in rel:
        if text.count("\n") > REF_TOC_LINES and not re.search(r"contents", "\n".join(text.splitlines()[:TOC_WITHIN]), re.I):
            out.append(f"rule 5: {rel}: over {REF_TOC_LINES} lines with no contents list in its first {TOC_WITHIN} lines")
        if any(m != Path(rel).stem for m in OTHER_LANE_RE.findall(text)):
            out.append(f"rule 5: {rel}: points to another lanes file; keep references one level deep from SKILL.md")
    return out


def _over_budget(text):
    return text.count("\n") > BODY_MAX_LINES or _tokens(text) > BODY_MAX_TOKENS


def _human_only_parts(rel, text):
    parts = {label: _section(text, start, end) for label, start, end in HUMAN_ONLY_SECTIONS.get(rel, [])}
    if rel.endswith("board.py") and rel in HUMAN_ONLY_SECTIONS and text is not None:
        parts["the rules-check code"] = (parts["the rules-check code"], sorted(
            l for l in text.splitlines() if "rules-check" in l or "rules_check" in l))
    return parts


def _named(rel, texts):
    """Rule 7 (job 180's in-ticket rule): rel appears verbatim in one of texts, or a `<dir>/*.md` mention covers it."""
    for text in texts:
        if re.search(rf"(?<![\w./-]){re.escape(rel)}(?![\w/-]|\.\w)", text):
            return True
        if rel.endswith(".md") and any(g[:-5] == os.path.dirname(rel) for g in re.findall(r"[\w./-]+/\*\.md", text)):
            return True
    return False


def _first_line_pins(text):
    block = re.search(r"^FIRST_LINE = \{(.*?)^\}", text or "", re.M | re.S)
    return set(re.findall(r'"([\w-]+)": "([^"]*)"', block.group(1))) if block else set()


def cmd_rules_check(root: Path, job_id: str, worktree: str | None = None, base: str | None = None) -> dict:
    """{"ok", "files", "failures"}: ok only when the job's diff changes a rules file and breaks none of the script rules.
    worktree/base, when not None, replace the board's values, as in digest-verify; empty fails."""
    try:
        job = find(read_board(root), check_id(job_id))
        wt = job.get("worktree") if worktree is None else worktree
        base = job.get("base") if base is None else base
        if not wt or not base:
            raise ValueError(f"no {'worktree' if not wt else 'base'}")
        if base.startswith("-"):
            raise ValueError(f"bad base {base!r}")
        diff = _git(wt, "diff", "--name-only", f"{base}...HEAD", "--").decode().splitlines()
        rules = [f for f in diff if RULES_RE.search(f)]
        mb = _git(wt, "merge-base", base, "HEAD").decode().strip()

        def show(rev, f):
            try:
                return _git(wt, "show", f"{rev}:{f}").decode()
            except (ValueError, UnicodeDecodeError):
                return None

        guarded = rules or [f for f in diff if f in HUMAN_ONLY_FILES or f in HUMAN_ONLY_SECTIONS]
        fails = [] if guarded else ["the diff changes no rules file"]
        for f in rules:
            before, after = show(mb, f), show("HEAD", f)
            if after is None:
                continue
            # one message per occurrence, so a second @ link or bracket still fails when the base has one
            fails += list((Counter(_file_problems(f, after)) - Counter(_file_problems(f, before) if before else [])).elements())
            if _over_budget(after) and (before is None or after.count("\n") > before.count("\n")
                                        or len(after) > len(before)):
                fails.append(f"rule 4: {f}: {after.count(chr(10))} lines, ~{_tokens(after)} tokens: over the "
                             f"{BODY_MAX_LINES}-line / {BODY_MAX_TOKENS}-token budget and new or grown")
        descs = sum(len((_frontmatter(p.read_text(errors="replace")) or {}).get("description", ""))
                    for p in Path(wt).glob("agents/scrum-*.md"))
        if descs // 4 > AGENT_DESCS_MAX_TOKENS:
            fails.append(f"rule 3: agent descriptions total ~{descs // 4} tokens, over {AGENT_DESCS_MAX_TOKENS}")
        try:
            suite = subprocess.run([sys.executable, "-m", "unittest", "tests.test_contracts"], cwd=wt,
                                   capture_output=True, timeout=540).returncode  # under the 600 s Bash cap
        except subprocess.TimeoutExpired:
            suite = "timeout"
        if suite != 0:
            fails.append("rule 6: python3 -m unittest tests.test_contracts fails in the worktree")
        pins = _first_line_pins(show("HEAD", "tests/test_contracts.py"))
        for name, _ in sorted(_first_line_pins(show(mb, "tests/test_contracts.py")) - pins):
            fails.append(f"rule 6: FIRST_LINE pin for {name} removed or changed")
        jd = Path(root) / "jobs" / job_id
        feature, spec = (p.read_text(errors="replace") if p.is_file() else "" for p in (jd / "feature.md", jd / "spec.md"))
        likely = md_section(spec, "Likely files") or ""
        fails += [f"rule 7: {f} is not named in feature.md or spec.md ## Likely files" for f in diff
                  if not _named(f, (feature, likely))]
        for f in diff:
            if f in HUMAN_ONLY_FILES:
                fails.append(f"rule 8: {f} is human-only")
            before, after = _human_only_parts(f, show(mb, f)), _human_only_parts(f, show("HEAD", f))
            fails += [f"rule 8: {f}: {label} changed; it is human-only" for label in before
                      if before[label] != after.get(label) or after.get(label) is None]
        return {"ok": not fails, "files": rules, "failures": fails}
    except (ValueError, OSError, SystemExit, subprocess.SubprocessError) as e:
        return {"ok": False, "files": [], "failures": [str(e)]}
# --- end rules-check


# --- route-check: the Fast lane promotion, Review clean-round and Approve model decisions (SKILL.md), from files ---
SCHEMA_RE = re.compile(r"(^|/)prisma/(schema\.prisma|migrations/)|\.sql$")  # SKILL.md Merge's schema guard
ENV_RE = re.compile(r"(^|/)\.env")
SENSITIVE_RE = re.compile(r"(^|/)(middleware|proxy)\.[cm]?[jt]sx?$|auth|session|login|signin|signup|password|permission"
                          r"|payment|billing|checkout|stripe|webhook|secret|credential", re.I)  # SKILL.md Fast lane
FAST_MAX_LINES, FAST_MAX_FILES = 100, 3
LILGUY_MAX_LINES, LILGUY_MAX_FILES = 30, 3


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
DELETION_MIN_RATIO = 0.9


def ui_globs(root):
    """project.md's `- UI globs:` entries; None when the file or line is missing, empty or `none`."""
    try:
        text = (Path(root) / "project.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if m := re.match(r"^\s*-\s*UI globs:(.*)$", line):
            globs = [g.strip("`") for g in m[1].split() if g.strip("`")]
            return None if not globs or globs == ["none"] else globs
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
    "|".join(re.escape(t) for t in (UI_SKIP, SECURITY_SKIP, DELETION_SKIP)) + "|"
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


def cmd_review_plan(root: Path, job_id: str, incremental: bool = False) -> dict:
    """{"spawn": reviewers to spawn in REVIEWERS order, "since": SINCE sha or None}. Writes the round's carried-forward
    (incremental) or UI/UX (no UI file, or a deletion-dominated diff) and security skip files (full); never writes
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
        rd.mkdir(parents=True, exist_ok=True)
        for r in REVIEWERS:
            if verdicts[r] == "PASS":
                (rd / f"review-{r}.md").write_text(CARRIED.format(n - 1), encoding="utf-8")
        spawn = [r for r in REVIEWERS if verdicts[r] == "CHANGES"]
        _drop_stale(rd, spawn)
        return {"spawn": spawn, "since": since}
    spawn = list(REVIEWERS)
    files = None if base.startswith("-") else _names(wt, f"{base}...HEAD")
    if files is not None:
        skips = {}
        globs = ui_globs(root)
        if globs and not any(glob_match(f, globs) for f in files):
            skips.update(ui=UI_SKIP, ux=UI_SKIP)
        elif _deletion_dominated((_route_diff(job) or ([], []))[0]):
            skips.update(ui=DELETION_SKIP, ux=DELETION_SKIP)
        if not any(rx.search(f) for f in files for rx in SECURITY_RES):
            skips["security"] = SECURITY_SKIP
        if skips:
            rd.mkdir(parents=True, exist_ok=True)
        for r, text in skips.items():
            (rd / f"review-{r}.md").write_text(text, encoding="utf-8")
        spawn = [r for r in REVIEWERS if r not in skips]
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


def _deletion_dominated(rows):
    """True when at least DELETION_MIN_RATIO of the numstat rows' changed lines are deletions; False with no rows, a
    binary row or no changed lines."""
    if not rows or any(a is None for a, _, _ in rows):
        return False
    added, deleted = sum(a for a, _, _ in rows), sum(d for _, d, _ in rows)
    return added + deleted > 0 and deleted / (added + deleted) >= DELETION_MIN_RATIO


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
    if (lines := sum(a for a, _, _ in rows)) > LILGUY_MAX_LINES:
        return f"diff over {LILGUY_MAX_LINES} added lines ({lines})"
    if (files := len({p for a, _, p in rows if a})) > LILGUY_MAX_FILES:
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


def cmd_lilguy_fit(root, job_id: str) -> dict:
    """{"fit", "why"}: fit only for a job on no lane (or lilguy) that is tiny by backlog points or by Jev, with no
    LILGUY_HARD_STOP_RE word in its feature.md."""
    job = find(read_board(root), check_id(job_id))
    lane = job.get("lane")
    if lane and lane != "lilguy":
        return {"fit": False, "why": f"already on {lane} lane"}
    folder = Path(root) / "jobs" / job_id
    feature = folder / "feature.md"
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
                    item = {"done": False, "points": pts, "text": text, "job": None, "why": why, "id": None,
                            "priority": max((i["priority"] for i in got if i["priority"]), default=None),
                            "needs": list(dict.fromkeys(n for i in got for n in i["needs"] if n not in own)),
                            "setup": list(dict.fromkeys(st for i in got for st in i["setup"]))}  # still waits on setup
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
    """Not in progress: an IDLE stage, or paused by Trevor (it keeps its stage but holds no slot)."""
    return job.get("stage") in IDLE or bool(job.get("paused"))


BLOCKED = "bigboy blocked"
RUNALL_BLOCKED = "run-all blocked"
CHAIN_LOCKED = "bigboy chain lock held by"  # SKILL.md Chaining step 5; re-evaluated like a blocked parent
WAITING_ON = "waiting on you in: "  # a running parent whose children wait on Trevor (needs-human or Setup done)
MACHINE_WAIT = "waiting: "  # a running parent whose next claim waits on free RAM or disk (machine_ok) or usage


def resume_first(jobs: list[dict]) -> int:
    """How many jobs on this board must be played, resumed or aborted before any new claim in its project: the ones
    Trevor paused (not done or aborted), plus the unpaused needs-human ones stalled in a stage (not
    lilguy-in-checkout)."""
    return sum(bool(j.get("paused")) and j.get("stage") not in ("done", "aborted")
               or not j.get("paused") and j.get("stage") == "needs-human"
               and (j.get("reason") or "").startswith(STALLED) and not lilguy_in_checkout(j) for j in jobs)


def usage_path():
    return Path(os.environ.get("SCRUM_USAGE") or Path.home() / ".claude" / "usage.json")


def read_usage():
    try:
        u = json.loads(usage_path().read_text())
    except (OSError, ValueError):
        return None
    return u if isinstance(u, dict) else None


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
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
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


def pace_cap(usage, now, base):
    """Always None: usage pacing no longer caps sessions (job 282); machine_ok and the overlap rules gate instead.
    Kept for continue.py (outside this repo), which skips its tick when this is not None."""
    return None


def merge_limits(old, new, now):
    """New rate_limits over old: per window the later resets_at wins (tie: higher used_percentage); expired old windows drop."""
    def ok(w):
        return isinstance(w, dict) and is_num(w.get("used_percentage")) and is_num(w.get("resets_at"))
    merged = dict(new)
    for key in ("five_hour", "seven_day"):
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
    return " · ".join(f"{label} {round(w['used_percentage'])}%" for key, label in (("five_hour", "5h"), ("seven_day", "7d"))
                      if isinstance(w := limits.get(key), dict) and is_num(w.get("used_percentage")))


def likely_files(spec_text):
    """The backtick-quoted paths in a spec's `## Likely files` section."""
    return {p for p in re.findall(r"`([^`\s]+)`", md_section(spec_text, "Likely files") or "") if PATH_RE.match(p)}


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
    if set(names) - {exposure[0]["ticket"]} - set(exposure[0]["depends"]):
        raise SystemExit(f"plan.md: the Exposure: yes ticket {exposure[0]['ticket']} must depend on every other ticket")
    return (md_section(text, "Goal") or "").strip(), tickets


def add_child(root, board, parent, t, depends_on, goal, plain=False):
    """Create one waiting child job for ticket t and write its feature.md (just t's text when plain).
    Caller holds the board lock."""
    job_id = add_job(root, board, t["title"][:60])
    setup = t.get("setup", "none")
    setup = None if setup.lower() == "none" else setup
    feature = t["text"] + "\n" if plain else \
        f"{t['title']}\n\n{t['text']}\n\nTicket {t['ticket']} of BigBoy {parent['id']}: {parent['title']}.\n" \
        + (f"Goal: {goal}\n" if goal else "") + f"Hard stops: {t.get('hard', 'none')}\n" \
        + (f"Human setup: {setup}\n" if setup else "")
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
        parent_id = add_job(root, board, "Run all")
        parent = board["jobs"][-1]
        kids, by_id = [], {}
        for item in todo:
            t = {"ticket": None, "title": item["text"][:60], "text": item["text"], "parallel": True}
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
SWAP_FREE_RAM_PCT = 35  # ... but swap alone is stale (macOS keeps it until pressure returns): it blocks only below this free RAM
SWAP_GROWTH_SECS = 600  # ... or when swap grew within this window (2026-10-25: idle machine, 71% free, blocked for an hour)
SESSION_RAM_PCT = 5  # ram_room: estimated share of RAM one new headless session takes (16 GB Mac); tune here
MAX_SESSIONS = 14  # machine_ok: headless sessions may hold 70% of RAM in all (SESSION_RAM_PCT each); the rest is macOS and
#                   apps. Derived from the RAM share, not the fixed 8 job 279 removed; 19 sessions crashed the Mac (2026-10-24).
#                   14, not 12: Trevor keeps it as a backstop until further notice in case the RAM reading misleads (job 284)
SESSION_RAMP_SECS = 120  # ram_room: a session younger than this has not grown into its RAM yet, so free RAM % overstates
#                          the room; two projects claiming within that minute both burst (the 2026-10-24 pile-up)


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
    claims, Run-all child claims, auto-continue, cloud-claim, the next roadmap step); work already on the board finishes."""
    return Path(os.environ.get("SCRUM_COOLDOWN") or Path.home() / ".claude" / "trevskills-scrum" / "cooldown")


def cooling_down():
    return cooldown_path().exists()


def swap_grew(swap):
    """True when swap rose more than 1 point of RAM above the lowest reading of the last SWAP_GROWTH_SECS. Records swap
    in SCRUM_SWAP_LOG (default: system temp dir), pruned to that window; a missing or corrupt file means no growth."""
    log = os.environ.get("SCRUM_SWAP_LOG") or os.path.join(tempfile.gettempdir(), "scrum-swap-log.json")
    now = time.time()
    try:
        keep = [[t, v] for t, v in json.loads(Path(log).read_text()) if now - t < SWAP_GROWTH_SECS]
    except (OSError, ValueError, TypeError):
        keep = []
    grew = bool(keep) and swap - min(v for _, v in keep) > 1
    try:
        with open(log, "w") as fh:
            json.dump(keep + [[now, swap]], fh)
    except OSError:
        pass
    return grew


def machine_ok(path, manual=False, claim=False):
    """None when the machine has room for new work, else why not: cool-down (only for a new claim, claim=True, and
    skipped for Trevor's manual clicks), then free RAM, then swap, then free disk, then the session ceiling. Gates new
    claims, resumes and auto-continue starts only; a running job is never touched. An unknown reading passes."""
    if claim and not manual and cooling_down():
        return COOLING
    ram = free_ram_pct()
    if ram is not None and ram < MIN_FREE_RAM_PCT:
        return f"free RAM {ram:g}% (< {MIN_FREE_RAM_PCT}%)"
    swap = swap_used_pct()
    if swap is not None and swap > MAX_SWAP_PCT and ((ram is not None and ram < SWAP_FREE_RAM_PCT) or swap_grew(swap)):
        return f"swap used {swap:.1f}% of RAM (> {MAX_SWAP_PCT}%)"
    disk = free_disk_gb(path)
    if disk is not None and disk < MIN_FREE_DISK_GB:
        return f"free disk {disk:.1f} GB (< {MIN_FREE_DISK_GB} GB)"
    live = live_sessions()
    if live >= MAX_SESSIONS:
        return f"{live} sessions running (ceiling {MAX_SESSIONS})"
    return None


def ram_room():
    """How many new sessions one claim batch may start once machine_ok passed: the free RAM above MIN_FREE_RAM_PCT
    split into SESSION_RAM_PCT shares, minus one share per session younger than SESSION_RAMP_SECS (its RAM is spoken
    for but not used yet), never past MAX_SESSIONS in all, at least 1. An unknown reading allows 1, so a batch never
    bursts blind, and so does swap already past MAX_SWAP_PCT / 2: free RAM % reads healthy while the kernel is swapping."""
    ram = free_ram_pct()
    swap = swap_used_pct()
    if ram is None or (swap is not None and swap > MAX_SWAP_PCT / 2):
        return 1
    ages = session_ages()
    room = int((ram - MIN_FREE_RAM_PCT) // SESSION_RAM_PCT) - sum(a < SESSION_RAMP_SECS for a in ages)
    return max(1, min(room, MAX_SESSIONS - len(ages)))


SESSION_RE = re.compile(r"(\S*/)?claude -p /trevskills-scrum [a-z-]+")
ETIME_RE = re.compile(r"\s*(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+) (.*)")  # ps etime: [[dd-]hh:]mm:ss, then the command


def session_ages():
    """Age in seconds of every headless `/trevskills-scrum <action>` session (start, resume, approve, run-all, ...) on
    this machine, any project and any launcher (ps sees them all; serve.py's RUNS only knows its own). SCRUM_PS names
    a file read in place of ps's output; its lines may start with an etime token, and a line without one is old."""
    fake = os.environ.get("SCRUM_PS")
    out = Path(fake).read_text() if fake else \
        subprocess.run(["ps", "-Ao", "etime=,command="], capture_output=True, text=True).stdout
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
    child id to its Likely files. The rules `ready` and `resume_blocker` share: parallel=no, or
    no readable Likely files, runs alone; anything else never beside such a sibling or one sharing a Likely file."""
    busy = [o for o in busy if o["id"] != k["id"]]
    if not busy:
        return None
    alone = lambda j: not j.get("parallel") or not files.get(j["id"])  # unknown Likely files = may touch anything
    if alone(k):
        return "this job runs alone", [o["id"] for o in busy]
    clash = [(o["id"], "runs alone" if alone(o) else f"shares {min(files[k['id']] & files[o['id']])}")
             for o in busy if alone(o) or files[k["id"]] & files[o["id"]]]
    return ("; ".join(f"sibling {i} {why}" for i, why in clash), [i for i, _ in clash]) if clash else None


class Blocker(str):
    """resume_blocker's text; .ids names the siblings it waits on."""
    def __new__(cls, text, ids):
        self = super().__new__(cls, text)
        self.ids = ids
        return self


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
    spec = lambda k: (jobs_dir / k["id"] / "spec.md").read_text(encoding="utf-8", errors="replace") \
        if (jobs_dir / k["id"] / "spec.md").is_file() else ""
    files = {k["id"]: likely_files(spec(k)) for k in kids}
    # A sibling holds a slot only with a live session: `live`, or a WATCHED stage whose claude process is alive.
    # Needs-human, paused and limit-held (limitResetAt) siblings run nothing, so they never block each other.
    maybe = [k for k in kids if k["id"] not in live and k["id"] != job_id and not idle(k) and not k.get("limitResetAt")]
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


def cmd_ready(root, parent_id, live=()):
    """Claim (stage -> spec) every waiting child that may start now, under the lock, so no child starts twice.
    `live` ids count as in progress whatever their stage (see resume_blocker)."""
    jobs_dir = Path(root) / "jobs"
    with locked_board(root) as board:
        parent = find(board, check_id(parent_id))
        was = parent["stage"]
        kids = [find(board, k) for k in parent.get("children") or []]
        if not kids:
            raise SystemExit(f"job {parent_id} has no children")
        stage = {k["id"]: k["stage"] for k in kids}
        runall = parent.get("lane") == "runall"  # aborted children count as finished
        reason = parent.get("reason") or ""
        # A legacy needs-human parent (blocked before WAITING_ON existed, or parked on the chain lock) is
        # re-evaluated so existing boards recover.
        legacy = parent["stage"] == "needs-human" and reason.startswith((BLOCKED, RUNALL_BLOCKED, CHAIN_LOCKED))
        held = bool(parent.get("paused"))  # a paused parent claims nothing and keeps its stage and reason
        blocked = not held and (legacy or (parent["stage"] == "running"
                                           and reason.startswith((WAITING_ON, MACHINE_WAIT))))
        go = not held and (parent["stage"] == "running" or legacy)
        machine = go and machine_ok(root, claim=runall)  # checked once: a machine-wide state, so it gates the whole call
        # paused or stalled work goes before new claims; a job with a live session is already being resumed
        first = resume_first([j for j in board["jobs"] if j["id"] not in live]) if go and not machine else 0
        cap = None  # the usage ladder's slots left this call; None = no taper
        if go and not machine:
            n_live = live_sessions()
            allow = usage_allowance(read_usage(), time.time(), n_live)
            if allow is not None:
                cap = max(0, allow - n_live)
                if not cap:  # no slot under the budget: held like a machine wait, never needs-human
                    machine = allow.reason
        spec = lambda k: (jobs_dir / k["id"] / "spec.md").read_text(encoding="utf-8", errors="replace") \
            if (jobs_dir / k["id"] / "spec.md").is_file() else ""
        files = {k["id"]: likely_files(spec(k)) for k in kids}
        busy = [k for k in kids if not idle(k) or k["id"] in live]
        # held kids run no session: when the taper leaves fewer slots than there are held kids, they yield their
        # overlap slot; busy itself is kept so the parent stays running and in_progress counts them
        limited = [k for k in busy if k.get("limitResetAt") and not idle(k) and k["id"] not in live]
        slots = [k for k in busy if k not in limited] if cap is not None and allow < len(limited) else list(busy)
        room = ram_room() if go and not machine else 0  # one claim = one new session
        if cap is not None:
            room = min(room, cap)
        ready = []
        for k in kids if go and not machine else []:
            if len(ready) >= room:  # machine_ok passed for the first claim only: never burst past the free RAM
                break
            if k["stage"] != "waiting" or k.get("setup") == "pending" \
                    or any(stage.get(dep) != "done" for dep in k.get("depends_on") or []):
                continue
            if slot_conflict(k, slots, files):
                continue
            if first:  # a claim is due, but held like a machine wait (never needs-human) until those are dealt with
                machine = f"{first} paused job needs Play or Abort first" if first == 1 \
                    else f"{first} paused jobs need Play or Abort first"
                break
            k.update(stage="spec", updatedAt=now())
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
            aborted = [k["id"] for k in kids if k["stage"] == "aborted"]
            if waits:  # every action is on a child, so the parent keeps running and names them
                new = "running", WAITING_ON + ", ".join(waits)
            elif not runall and aborted and stuck_on(kids, set(aborted)):  # Resume skips the dependents
                new = "needs-human", f"{BLOCKED}: {', '.join(aborted)}. Fix: click Resume to skip the children " \
                    "that depend on them and run the final review."
            else:  # nothing on a child is actionable (e.g. a depends_on that is not a finished sibling)
                left = [k["id"] for k in kids if k["stage"] not in ("done", "aborted")]
                new = "needs-human", f"{BLOCKED}: {', '.join(left)}. Fix: check each listed child's Depends on, " \
                    "then click Run now on a waiting child."
        if new != (parent["stage"], parent.get("reason")):
            if (new[1] or "").startswith(MACHINE_WAIT) and not reason.startswith(MACHINE_WAIT):  # once per hold
                log_stop(root, parent["id"], "machine", new[1])
            elif (new[1] or "").startswith(BLOCKED):
                log_stop(root, parent["id"], "bigboy", new[1])
            parent.update(stage=new[0], reason=new[1], updatedAt=now())
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
        raise SystemExit(f'use board.py ask {job_id} "<question>" --a "Label=command" --b "Label=command": '
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
            job.pop("paused", None)  # resume and rework re-enter a stage; spawn bookkeeping keeps the pause
        if job["stage"] != was and "outcome" not in given:
            job.pop("outcome", None)  # the last dashboard run's outcome describes the stage it left
        if "tty" in given:
            job["pid"] = pid  # internal, not in FIELDS: a hand-set pid could mark a job alive forever
        if job["stage"] != was:
            job.pop("limitResetAt", None)  # serve.py's usage-limit hold ends when the job leaves its stage
        job["files"], job["diverged"] = files, div
        job["updatedAt"] = now()
        if given.get("stage") == "done" and (given.get("reason") or "").startswith("merged + gaps"):
            log_stop(root, job["id"], "bigboy", job["reason"])
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


def cmd_ask(root, job_id, question, options, kind=None, recommend=None):
    """Park the job at needs-human with a closed question: options are 2-3 "label=command" strings, keyed a, b, c in
    order. recommend is an optional (key, why) naming the option the agent advises. Returns the stored option dicts.
    An eligible kind (lanes/unblock.md) leaves the job in its stage and returns {"unblock": True, "n": N} instead."""
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
                             "abort <id> [--requeue|--cascade], resume <id>, shell: <command>")
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
        # a session that did not load the scrum agent types is a session fault: stalled, so auto_resume retries it
        reason = f"{STALLED}{was}: {question}" if was in WATCHED and AGENT_TYPES_RE.search(question) else question
        if job.get("reason") != reason:
            job.pop("outcome", None)  # a new blocker: the last run's outcome no longer applies
        job.update(stage="needs-human", reason=reason, question=question, options=parsed, updatedAt=now())
        entry = {"date": now(), "project": Path(root).resolve().parent.name, "job": job_id,
                 "question": question, "options": parsed, "reason": reason,
                 "kind": "bigboy" if question.startswith(("bigboy review: main not updated", BLOCKED)) else "ask"}
        if recommend:
            job["recommend"] = entry["recommend"] = recommend
        else:
            job.pop("recommend", None)  # a re-ask without one drops the old question's advice
        questions_log(root, entry)
    if was != "needs-human":
        play(sound("needs-human"))
    return parsed


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


def cmd_answer(root, job_id, key):
    """Log Trevor's pick on the job's open question and return that option; the stage is left to the command it names."""
    with locked_board(root) as board:
        job = find(board, check_id(job_id))
        if job["stage"] != "needs-human" or not job.get("options"):
            raise SystemExit(f"job {job_id} has no open question")
        option = next((o for o in job["options"] if o["key"] == key), None)
        if option is None:
            raise SystemExit(f"no option {key!r}; the question offers {', '.join(o['key'] for o in job['options'])}")
        questions_log(root, {"date": now(), "job": job_id, "pick": option["label"]})
    return option


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
    """Re-check every job carrying artifactsPending: drop the mark once scrum-artifacts/<id> exists (returned) or the
    mark is CLOUD_PENDING_HOURS old (not returned)."""
    pending = [j for j in read_board(root)["jobs"] if j.get("artifactsPending")]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CLOUD_PENDING_HOURS)
    arrived, drop = [], set()
    for job in pending:
        if artifacts_pushed(repo, job["id"]):
            arrived.append(job["id"])
            drop.add(job["id"])
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


# --- watchdog: a job whose orchestrator session died stays in its stage forever; flag it needs-human ---
WATCHED = ("spec", "build", "check", "review", "approve", "merging")
STALL_MINUTES = 30  # fixed, the same as the dashboard's STALE_MS; not a setting (UB-24)
IDLE_HOURS = 2  # a live session with no board or job-dir change this long is flagged too; fixed, not a setting
STALLED = "stalled in "  # reason prefix: serve.py's resume, the dashboard's Resume button and SKILL.md read it
AGENT_TYPES_RE = re.compile(r"not loaded as agent types|agent types (?:are )?not loaded", re.I)
# Every needs-human reason prefix whose card offers Resume (serve.py's resume action, the dashboard, SKILL.md `resume`).
RESUMABLE = (STALLED, "bigboy off track", "bigboy review: main not updated", BLOCKED, "Base branch ")
# Pause keeps the job in its stage with board `paused` true and the watchdog's stalled reason, so Play is the
# existing resume path.
PAUSABLE = ("spec", "build", "check", "review", "approve", "merging", "plan", "running")
PAUSED = "paused by Trevor"
PAUSED_RE = re.compile(rf"^{STALLED}(\w+): {PAUSED}")
ORPHANED = "requeue: orphaned claim, the session died before writing feature.md"


def migrate_paused(board: dict) -> list[str]:
    """Rewrite each legacy paused job (needs-human with a PAUSED_RE reason) to its stage plus `paused`, keeping the
    reason. Returns the migrated ids; a second run finds none."""
    out = []
    for job in board["jobs"]:
        m = job.get("stage") == "needs-human" and PAUSED_RE.match(job.get("reason") or "")
        if m:
            job.update(stage=m.group(1), paused=True)
            out.append(job["id"])
    return out


def cmd_migrate_paused(root) -> list[str]:
    """migrate_paused on board.json, written only when something migrated (locked_board migrates on every write)."""
    ids = migrate_paused(read_board(root))  # a read first: most ticks find nothing and write nothing
    if ids:
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
    """Flag every job stuck in a WATCHED stage with no board update for STALL_MINUTES and no live session.
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
                     and stalled_since(j, cutoff)]
            alive = alive or (session_alive_fn() if stale else None)  # ps only when something could be stalled
            idle_cutoff = datetime.now(timezone.utc) - timedelta(hours=IDLE_HOURS)
            for job in stale:
                live_idle = False
                if alive(job):
                    if not (stalled_since(job, idle_cutoff) and job_dir_idle(root, job["id"], idle_cutoff.timestamp())):
                        continue
                    live_idle = True
                if live_idle:
                    job.update(stage="needs-human", updatedAt=now(), reason=f"{STALLED}{job['stage']}: no board or job-dir "
                               f"change for {IDLE_HOURS} h (session alive but idle). Fix: click Resume.")
                    log_stop(root, job["id"], "stall", job["reason"])
                    roadmap_stall_locked(root, job)
                    flagged.append(job["id"])
                elif job["stage"] == "spec" and not job.get("parent") \
                        and not (Path(root) / "jobs" / job["id"] / "feature.md").exists():
                    abort_job(root, job, True, ORPHANED)  # nothing to resume: put the item back, no human needed
                    requeued.append(job["id"])
                else:
                    job.update(stage="needs-human", updatedAt=now(), reason=f"{STALLED}{job['stage']}: no board update "
                               f"for {STALL_MINUTES} min and no live session. Fix: click Resume.")
                    log_stop(root, job["id"], "stall", job["reason"])
                    roadmap_stall_locked(root, job)
                    flagged.append(job["id"])
            if not flagged and not requeued:
                raise _Gone
    except _Gone:
        pass
    if flagged:
        play(sound("needs-human"))
    return flagged


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
        stopped = lambda j: j.get("stage") == "needs-human" or j.get("paused")
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
    """A stalled job (just flagged needs-human) stops its roadmap step; a roadmap problem never undoes the flag."""
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


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", type=Path, default=Path("scrum"))
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("title")
    n.add_argument("--id")
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
    ak.add_argument("--recommend", nargs=2, metavar=("KEY", "WHY"))
    sub.add_parser("unblock-log").add_argument("id")
    an = sub.add_parser("answer")
    an.add_argument("id")
    an.add_argument("key", choices=("a", "b", "c"))
    sub.add_parser("next").add_argument("--index", type=int)
    sub.add_parser("cloud-claim").add_argument("n", type=int)
    ba = sub.add_parser("backlog-add")
    ba.add_argument("--setup", metavar="TEXT", help='Human setup checklist "step; step"')
    ba.add_argument("--priority", type=int, metavar="N", help="importance 1-5, highest claimed first")
    ba.add_argument("items", nargs="+")
    sub.add_parser("manual-add").add_argument("items", nargs="+")
    sub.add_parser("rank-backlog")
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
    sub.add_parser("digest-due")
    sub.add_parser("digest-start")
    sub.add_parser("digest-trim").add_argument("digest")
    sub.add_parser("pipeline-fit").add_argument("digest")
    dv = sub.add_parser("digest-verify")
    dv.add_argument("id")
    dv.add_argument("--worktree", default=None)
    dv.add_argument("--base", default=None)
    rules_check = sub.add_parser("rules-check")
    rules_check.add_argument("id")
    rules_check.add_argument("--worktree", default=None)
    rules_check.add_argument("--base", default=None)
    sub.add_parser("move-ratio").add_argument("id")
    sub.add_parser("lilguy-fit").add_argument("id")
    rc = sub.add_parser("route-check")
    rc.add_argument("id")
    rc.add_argument("--check-fails", type=int, default=0)
    rc.add_argument("--clean-start", action="store_true")
    sub.add_parser("triage-start")
    sub.add_parser("triage-apply").add_argument("triage")
    sub.add_parser("hook")
    sub.add_parser("statusline")
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
    if a.cmd == "statusline":
        # Never show a traceback in the status line: an empty line and exit 0 whatever happens.
        try:
            line = cmd_statusline(sys.stdin.read())
        except (Exception, SystemExit):
            line = ""
        print(line)
        return 0
    if a.cmd == "new":
        print(cmd_new(a.dir, a.title, a.id))
    elif a.cmd == "set":
        cmd_set(a.dir, a.id, a.pairs, unpause=a.unpause)
    elif a.cmd == "sync":
        print(json.dumps(cmd_sync(a.dir, a.id)))
    elif a.cmd == "ask":
        out = cmd_ask(a.dir, a.id, a.question, [o for o in (a.a, a.b, a.c) if o is not None], a.kind,
                      a.recommend)
        if a.kind is not None:
            print(json.dumps(out if isinstance(out, dict) else {"unblock": False}))
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
    elif a.cmd == "digest-due":
        print(json.dumps(cmd_digest_due(a.dir)))
    elif a.cmd == "digest-start":
        print(json.dumps(cmd_digest_start(a.dir)))
    elif a.cmd == "digest-trim":
        print(json.dumps(cmd_digest_trim(a.dir, a.digest)))
    elif a.cmd == "pipeline-fit":
        print(json.dumps(cmd_pipeline_fit(a.dir, a.digest)))
    elif a.cmd == "digest-verify":
        out = cmd_digest_verify(a.dir, a.id, a.worktree, a.base)
        print(json.dumps(out))
        return 0 if out["ok"] else 1
    elif a.cmd == "rules-check":
        out = cmd_rules_check(a.dir, a.id, a.worktree, a.base)
        print(json.dumps(out))
        return 0 if out["ok"] else 1
    elif a.cmd == "move-ratio":
        out = cmd_move_ratio(a.dir, a.id)
        print(json.dumps(out))
        return 1 if out.get("ok") is False else 0
    elif a.cmd == "lilguy-fit":
        print(json.dumps(cmd_lilguy_fit(a.dir, a.id)))
    elif a.cmd == "route-check":
        print(json.dumps(cmd_route_check(a.dir, a.id, a.check_fails, a.clean_start)))
    elif a.cmd == "triage-start":
        print(json.dumps(cmd_triage_start(a.dir)))
    elif a.cmd == "triage-apply":
        print(json.dumps(cmd_triage_apply(a.dir, a.triage)))
    elif a.cmd == "rank-backlog":
        print(json.dumps(cmd_rank_backlog(a.dir)))
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
    elif a.cmd == "spawn":
        proc, log = spawn(a.dir, a.id, a.action, a.prompt, model=a.model)
        print(json.dumps({"log": log, "pid": proc.pid}))
    elif a.cmd == "backlog-spec":
        out = cmd_backlog_spec(a.dir, a.id)
        print(json.dumps(out))
        spawn_estimates(a.dir, out["added"])
    else:
        spawn_estimates(a.dir, cmd_backlog_add(a.dir, a.items, a.setup, a.priority))


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
    return any(i.get("job") == job_id and (i.get("points") or 0) >= BIG_POINTS for i in read_backlog(root)[1])


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
          model: str | None = None) -> tuple[subprocess.Popen, str]:
    """Start `claude -p <prompt> <flags>` in the repo, detached, logging to scrum/runs/, and set the job's runlog.
    start/resume get `--model <Orchestrator model>` (or `<Big ticket model>`, see orchestrator_model) unless `model` is given. Returns (proc, log path relative to root)."""
    if not SPAWN_ID_RE.fullmatch(job_id):
        raise SystemExit(f"bad spawn id {job_id!r}")
    if not SPAWN_ACTION_RE.fullmatch(action):
        raise SystemExit(f"bad spawn action {action!r}")
    if model is not None and not MODEL_RE.fullmatch(model):
        raise SystemExit(f"bad model {model!r}; must match {MODEL_RE.pattern}")
    if model is None and action in ("start", "resume"):
        model = orchestrator_model(root, job_id)
    prompt = prompt if prompt is not None else f"/trevskills-scrum {action} {job_id}"
    logs = root / "runs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{datetime.now():%Y%m%d-%H%M%S}-{action}-{job_id}.log"
    argv = [CLAUDE, "-p", prompt, *(("--model", model) if model else ()), *flags]
    with open(log, "w") as fh:
        proc = subprocess.Popen(argv, cwd=root.parent,
                                stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                                env=dict(os.environ, CLAUDE_NOTIFIER_DISABLE="1",  # board.py plays scrum's sounds
                                         CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0"))  # -p kills background agents 10 min after the last turn otherwise
    try:  # the run log link reads this; a job that isn't on the board (run-all, digest) has no row to set
        cmd_set(root, job_id, [f"runlog=runs/{log.name}", "tty=", "outcome="], unpause=True)  # Play starts on a paused job; a stale interactive tty would still match the hook and liveness checks
    except SystemExit:
        pass
    return proc, f"runs/{log.name}"


if __name__ == "__main__":
    sys.exit(main())
