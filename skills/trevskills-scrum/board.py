#!/usr/bin/env python3
"""The scrum team's board. Only the /trevskills-scrum orchestrator calls this; nothing else writes board.json.

  board.py new "<title>" [--id ID] create jobs/<id>/ and a board entry, print the id (--id keeps a given id)
  board.py set <id> key=value ...  set stage/round/limit/pr/reason/worktree/builder/base/tty/term/runlog/lane/setup/waiting/specwriter/cloud (empty = null)
  board.py set --unpause <id> ...  the same, on a job Trevor paused too (resume and rework only)
  board.py sync <id>               re-read jobs/<id>/ into the board, print round status as JSON
  board.py next                    claim the first "- [ ]" backlog item that waits on no {needs #id} prerequisite as a
                                   new job, print {"id","feature"}
  board.py backlog-add "<item>"... append "- [ ] <item>" lines to backlog.md, then estimate each in the background
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
  board.py abort <id> [--requeue] [--reason TEXT]  mark a job aborted (terminal); --requeue puts it back on the backlog
  board.py artifacts <id>          print jobs/<id>/... paths safe to push (regular, under 1 MB, UTF-8, no secret); name the
                                   rest in jobs/<id>/skipped-secrets.txt (Cloud lane's scrum-artifacts/<id> branch)
  board.py digest-due              print {"due","undigested"}: done jobs in no digests/*/jobs.txt; due at 10+
  board.py digest-start            claim them all as digests/<NNN>/jobs.txt, print {"id","jobs"} (id null = nothing new)
  board.py digest-trim <NNN>       cut that digest's done job folders to feature.md, spec.md, decision.md
  board.py digest-verify <id> [--worktree PATH] [--base REF]
                                   exit 0 and print {"ok","files","proposals"} when the job worktree's rules-file diff
                                   (agents/scrum-*.md, SKILL.md) is exactly its feature.md's cited queued digest edits;
                                   else exit 1 and print {"ok": false, "error"} (SKILL.md Merge's Agent rules guard).
                                   --worktree/--base override the board's values (an empty one fails, never falls back)
  board.py triage-start            claim triage/<NNN>/ for the scrum-triager, print {"id","open"} (id null = backlog empty)
  board.py triage-apply <NNN>      apply triage/<NNN>/plan.json (merge/retire/manual/estimate/depends) to backlog.md (manual
                                   items move to manual-checks.md; depends adds {#id} and {needs #id} markers), write report.md
  board.py plan-apply <id> [--fix] turn a bigboy parent's plan.md into waiting child jobs, print {"children"};
                                   --fix adds the one FIX child from bigboy-review.md's ## Fix ticket
  board.py ready <id>              claim the bigboy parent's startable children (stage -> spec; the in-progress cap is paced
                                   by ~/.claude/usage.json), print
                                   {"ready","merged","total","in_progress","all_merged"}
  board.py runall-start           make a Run-all parent with every open backlog item as a waiting child (needs become
                                   depends_on; items waiting on an outside job stay open), print {"id","children"}
                                   (id null = nothing to claim); `ready <id>` then schedules them
  board.py chain-lock <id> <holder> [--wait S]  take the bigboy parent's jobs/<id>/.chain.lock (poll 2 s, up to S,
                                   default 540; stale after 1800 s), print {"acquired","holder"}
  board.py chain-unlock <id> <holder>  remove that lock if holder holds it, print {"released"}
  board.py watchdog                flag jobs stuck 30+ min in spec/build/check/review/approve with no live session
                                   needs-human (reason "stalled in <stage>: ..."), print {"flagged"}; a stuck spec
                                   job with no feature.md is an orphaned claim: aborted and requeued, never flagged
  board.py hook                    Claude Code hook: read one event from stdin, set or clear `waiting` on this tty's job
  board.py statusline              Claude Code status line: save stdin's rate_limits to ~/.claude/usage.json, print "5h N% · 7d N%"

Verdicts are never typed in by hand: sync derives them from the first line of each file, so the board can't drift
from the files. --dir points at the project's scrum/ folder (default ./scrum).
"""
import argparse, fcntl, hashlib, json, os, re, secrets, shutil, subprocess, sys, time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import permutations
from pathlib import Path

REVIEWERS = ("security", "ux", "ui", "code")
STAGES = ("plan", "running", "waiting", "spec", "build", "check", "review", "approve", "merging", "done", "needs-human",
          "aborted", "cloud")  # cloud: running in a claude.ai/code session (SKILL.md Cloud lane); never WATCHED
FIELDS = ("stage", "round", "limit", "pr", "reason", "worktree", "builder", "base", "tty", "term", "runlog", "lane", "setup",
          "waiting", "specwriter", "cloud")  # the `waiting` field (paused on Trevor) is unrelated to the bigboy "waiting" stage
ACTIVE = ("spec", "build", "check", "review", "approve", "merging")  # stages an interactive session can pause in
TERMS = ("Apple_Terminal", "iTerm.app", "ghostty")
# Where the job's terminal is: serve.py's Open terminal button passes these to osascript/tail, so they're strict.
SHAPES = {"tty": re.compile(r"^ttys[0-9]+$"), "runlog": re.compile(r"^runs/[\w.-]+\.log$"),
          "term": re.compile("^(?:" + "|".join(map(re.escape, TERMS)) + ")$"),
          "lane": re.compile(r"^(?:fast|standard|debug|bigboy|runall|lilguy)$"),  # no lane key = standard
          "setup": re.compile(r"^(?:pending|done)$"),  # a bigboy child's Human setup wait
          "cloud": re.compile(r"^https://claude\.ai/code/session_[A-Za-z0-9_-]+$")}  # the dashboard links it
ID_RE = re.compile(r"^\d{3,}-[a-z0-9-]+$")
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
        yield board
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
    if not unpause and job["stage"] == "needs-human" and PAUSED_RE.match(job.get("reason") or ""):
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


# --- backlog.md: "- [ ] [5] Text {#k3f9} {needs #a1b2} → 003-id <!-- why -->"; points, the id and needs markers, the job
# and the estimate's reason are optional. An item's text excludes the markers, so its spec_path never changes. ---
FIB = (1, 2, 3, 5, 8, 13)
ITEM_RE = re.compile(r"^- \[( |x)\] (?:\[(\d+|\?)\] )?(.*?)(?: \{#([a-z0-9]{4})\})?(?: \{needs((?: #[a-z0-9]{4})+)\})?"
                     r"(?: → (\d{3,}-[a-z0-9-]+))?(?: <!-- (.*?) -->)?\s*$")
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
            done, pts, text, item_id, needs, job, why = m.groups()
            items.append({"index": len(items), "line": n, "done": done == "x",
                          "points": int(pts) if pts and pts.isdigit() else None, "text": text.strip(), "why": why, "job": job,
                          "id": item_id, "needs": needs.replace("#", "").split() if needs else []})
    return lines, items


def format_item(item):
    return (f"- [{'x' if item['done'] else ' '}] " + (f"[{item['points']}] " if item["points"] else "") + item["text"]
            + (f" {{#{item['id']}}}" if item.get("id") else "")
            + (" {needs " + " ".join(f"#{n}" for n in item["needs"]) + "}" if item.get("needs") else "")
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


def check_points(points):
    if points is not None and (isinstance(points, bool) or points not in FIB):
        raise SystemExit(f"points must be one of {FIB} or null, got {points!r}")


def backlog_op(root, op, index=None, text=None, points=KEEP, delta=0):
    """add / edit / delete / move one backlog item under the board lock. Returns the new item list."""
    with locked_board(root):
        lines, items = read_backlog(root)
        if op == "add":
            if not clean(text or ""):
                raise SystemExit("backlog item text is empty")
            if points is not KEEP:
                check_points(points)
            lines.append(format_item({"done": False, "points": None if points is KEEP else points,
                                      "text": clean(text, ITEM_MAX), "job": None, "why": None}))
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
        elif op == "move":
            a = pick(items, index)
            # Swap with the nearest open item that way; finished items are hidden in the dashboard.
            step = range(index - 1, -1, -1) if delta == -1 else range(index + 1, len(items)) if delta == 1 else []
            b = next((items[j] for j in step if not items[j]["done"]), None)
            if b:
                lines[a["line"]], lines[b["line"]] = lines[b["line"]], lines[a["line"]]
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
    """Claim the first open backlog item (or item `index`) as a new job, under the lock, so no two sessions share one."""
    with locked_board(root) as board:
        lines, items = read_backlog(root)
        if index is None:
            item = next((i for i in items if not i["done"] and not waiting_on(i, items, board)), None)
            if item is None:
                return {"id": None, "feature": None}
        else:
            item = pick(items, index)
            if item["done"]:
                raise SystemExit(f"backlog item {index} is already claimed")
            if waits := waiting_on(item, items, board):
                raise SystemExit(f"backlog item {index} waits on " + ", ".join(f"#{n}" for n in waits))
        job_id = add_job(root, board, item["text"][:60])
        take_spec(root, item["text"], job_id)
        claim_item(lines, item, job_id)
        write_backlog(root, lines)
        return {"id": job_id, "feature": item["text"]}


def cmd_abort(root, job_id, requeue, reason=None):
    """Mark a job aborted (terminal). Optionally put its full feature text back on the backlog as an open item."""
    with locked_board(root) as board:
        job = find(board, check_id(job_id))
        if job["stage"] in ("done", "aborted"):
            raise SystemExit(f"job {job_id} is already {job['stage']}")
        abort_job(root, job, requeue, reason or f"Aborted by Trevor {now()}")


def abort_job(root, job, requeue, reason):
    """cmd_abort's body; caller holds the lock. With no feature.md (a claim whose session died before writing it),
    the requeue reopens the claimed backlog line in place, points, id, needs and pre-written spec kept."""
    folder = Path(root) / "jobs" / job["id"]
    feature = folder / "feature.md"
    job.update(stage="aborted", reason=reason, updatedAt=now(), files=job_files(folder))
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


def cmd_backlog_add(root, items):
    """Append each non-empty item; returns the texts as stored."""
    added = []
    for item in items:
        if clean(item):
            backlog_op(root, "add", text=item)
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


def digested_ids(root):
    """Every job id listed in any digest's jobs.txt, except a failed digest's (error.md), so the next digest re-claims them."""
    return {line.strip() for f in (Path(root) / "digests").glob("*/jobs.txt") if not f.with_name("error.md").exists()
            for line in f.read_text().splitlines() if line.strip()}


def undigested(root, board):
    seen = digested_ids(root)
    return [j["id"] for j in board["jobs"] if j.get("stage") == "done" and j["id"] not in seen]


def cmd_digest_due(root):
    path = Path(root) / "board.json"
    n = len(undigested(root, json.loads(path.read_text()) if path.exists() else {"jobs": []}))
    return {"due": n >= 10, "undigested": n}


def cmd_digest_start(root):
    """Claim every undigested done job as digest NNN, under the lock, so two triggers never share a job."""
    with locked_board(root) as board:
        jobs = undigested(root, board)
        if not jobs:
            return {"id": None, "jobs": []}
        digest_id = claim_folder(Path(root) / "digests")
        (Path(root) / "digests" / digest_id / "jobs.txt").write_text("".join(f"{j}\n" for j in jobs))
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


# --- digest-verify: Merge's Agent rules guard lets a job through without a human when its rules-file diff is exactly
# the digest edits Trevor already approved (status queued) and nothing else. Any doubt fails safe to Trevor.
CITATION_RE = re.compile(r"(?:(\S+)\s+)?digest\s+(\d{3})\s+([\w-]+)")
RULES_RE = re.compile(r"(^|/)agents/scrum-[^/]*\.md$|(^|/)SKILL\.md$")
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
                            "needs": list(dict.fromkeys(n for i in got for n in i["needs"] if n not in own))}
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
PATH_RE = re.compile(r"^[\w.@~+/-]*[./][\w.@~+/-]*$")  # a backticked token with a / or . and nothing code-like
IDLE = ("waiting", "done", "aborted", "needs-human")  # every other child stage counts as in progress
BLOCKED = "bigboy blocked"
RUNALL_BLOCKED = "run-all blocked"
CHAIN_LOCKED = "bigboy chain lock held by"  # SKILL.md Chaining step 5; re-evaluated like a blocked parent
WAITING_ON = "waiting on you in: "  # a running parent whose children wait on Trevor (needs-human or Setup done)
RUNALL_MAX_IN_PROGRESS = 3  # a Run-all parent's in-progress cap when usage pacing has no say (see pace_cap)
WINDOWS = {"five_hour": 18000, "seven_day": 604800}  # Claude Code's rate_limits windows and their length in seconds
USAGE_FRESH = 300  # seconds; an older usage.json means no status line is running, so no pacing


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


def pace_cap(usage, now, base):
    """The in-progress cap for this `ready` call from usage.json, or None (no pacing, so base stands). Each usable
    window is projected to its reset at the current burn rate; the highest projection P picks the tier."""
    limits = usage.get("rate_limits") if isinstance(usage, dict) else None
    at = usage.get("written_at") if isinstance(limits, dict) else None
    if not is_num(at) or now - at > USAGE_FRESH:
        return None
    projected = []
    for name, length in WINDOWS.items():
        w = limits.get(name)
        used, resets = (w.get("used_percentage"), w.get("resets_at")) if isinstance(w, dict) else (None, None)
        if not (is_num(used) and 0 <= used <= 100 and is_num(resets) and resets > now):
            continue
        left = resets - now
        elapsed = length - left
        if elapsed < length / 10:  # a few minutes of data extrapolate wildly
            continue
        projected.append(used + used / elapsed * left)
    if not projected:
        return None
    p = max(projected)
    if p < 60:
        return None if base is None else base + 2
    if p < 100:
        return base
    if p < 125:
        return 2 if base is None else min(base, 2)
    return 1


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
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # pid: several sessions may write at once
    tmp.write_text(json.dumps({"rate_limits": limits, "written_at": int(time.time())}))
    os.replace(tmp, path)
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
    """One Run-all parent whose waiting children are every open backlog item, claimed in backlog order under the lock.
    An item that waits, directly or through its prerequisites, on a job claimed outside this run stays open. A child
    whose item needs another item claimed here depends_on that sibling's child."""
    with locked_board(root) as board:
        lines, items = read_backlog(root)
        held = set()  # indexes of open items left open
        while True:
            more = {i["index"] for i in items if not i["done"] and i["index"] not in held
                    and any(o["id"] == n and (o["done"] or o["index"] in held)
                            for n in waiting_on(i, items, board) for o in items)}
            if not more:
                break
            held |= more
        todo = [i for i in items if not i["done"] and i["index"] not in held]
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


def slot_cap(runall):
    """The in-progress cap for a parent's children, or None (no cap). Usage pacing only gates new claims (and
    resumes); it is always >= 1, so with nothing in progress one child still starts."""
    cap = pace_cap(read_usage(), time.time(), RUNALL_MAX_IN_PROGRESS if runall else None)
    return RUNALL_MAX_IN_PROGRESS if runall and cap is None else cap


def slot_conflict(k, busy, files, cap):
    """(text, sibling ids) when child k may not run beside the in-progress siblings `busy`, else None. files maps a
    child id to its Likely files. The rules `ready` and `resume_blocker` share: the in-progress cap; parallel=no, or
    no readable Likely files, runs alone; anything else never beside such a sibling or one sharing a Likely file."""
    busy = [o for o in busy if o["id"] != k["id"]]
    if cap is not None and len(busy) >= cap:
        return f"{len(busy)} siblings in progress (cap {cap})", [o["id"] for o in busy]
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


def resume_blocker(root, job_id):
    """Why a stalled child may not resume now (a Blocker), or None. Applies `ready`'s cap and overlap rules
    (slot_conflict) against its in-progress siblings. Reads the board without writing or claiming anything."""
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
    busy = [k for k in kids if k["stage"] not in IDLE and k["id"] != job_id]
    if not busy:
        return None
    hit = slot_conflict(job, busy, files, slot_cap(parent.get("lane") == "runall"))
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


def cmd_ready(root, parent_id):
    """Claim (stage -> spec) every waiting child that may start now, under the lock, so no child starts twice."""
    jobs_dir = Path(root) / "jobs"
    with locked_board(root) as board:
        parent = find(board, check_id(parent_id))
        was = parent["stage"]
        kids = [find(board, k) for k in parent.get("children") or []]
        if not kids:
            raise SystemExit(f"job {parent_id} has no children")
        stage = {k["id"]: k["stage"] for k in kids}
        runall = parent.get("lane") == "runall"  # aborted children count as finished, and a count cap always applies
        reason = parent.get("reason") or ""
        # A legacy needs-human parent (blocked before WAITING_ON existed, or parked on the chain lock) is
        # re-evaluated so existing boards recover.
        legacy = parent["stage"] == "needs-human" and reason.startswith((BLOCKED, RUNALL_BLOCKED, CHAIN_LOCKED))
        blocked = legacy or (parent["stage"] == "running" and reason.startswith(WAITING_ON))
        spec = lambda k: (jobs_dir / k["id"] / "spec.md").read_text(encoding="utf-8", errors="replace") \
            if (jobs_dir / k["id"] / "spec.md").is_file() else ""
        files = {k["id"]: likely_files(spec(k)) for k in kids}
        busy = [k for k in kids if k["stage"] not in IDLE]
        cap = slot_cap(runall)
        ready = []
        for k in kids if parent["stage"] == "running" or legacy else []:
            if k["stage"] != "waiting" or k.get("setup") == "pending" \
                    or any(stage.get(dep) != "done" for dep in k.get("depends_on") or []):
                continue
            if slot_conflict(k, busy, files, cap):
                continue
            k.update(stage="spec", updatedAt=now())
            busy.append(k)
            ready.append(k["id"])
        merged = sum(k["stage"] == "done" for k in kids)
        finished = sum(k["stage"] in ("done", "aborted") for k in kids)  # an aborted child never runs again
        new = parent["stage"], parent.get("reason")
        if blocked and (ready or busy or finished == len(kids)):
            new = "running", None
        elif not ready and not busy and finished < len(kids) and (parent["stage"] == "running" or legacy):
            human = [k["id"] for k in kids if k["stage"] == "needs-human"]
            waits = human or [k["id"] for k in kids if k.get("setup") == "pending"]
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
            parent.update(stage=new[0], reason=new[1], updatedAt=now())
        out = {"ready": ready, "merged": merged, "total": len(kids), "in_progress": len(busy),
               "all_merged": finished == len(kids)}
    if was != "needs-human" and parent["stage"] == "needs-human":
        play(sound("needs-human"))
    return out


CHAIN_LOCK_STALE = 1800  # seconds; a crashed chaining session's lock is taken over after this


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


def merge_refusal(job: dict) -> str | None:
    """Why `job` may not move to done, or None. Its PR must be MERGED; a PR-less job may finish only on a parent
    (bigboy/runall) or lilguy lane."""
    pr = job.get("pr")
    if not pr:
        return None if job.get("lane") in ("bigboy", "runall", "lilguy") else "not done: no PR recorded"
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


def cmd_set(root, job_id, pairs, unpause=False):
    """unpause writes to a paused job. Only the caller grants it: serve.py's Play and spawn bookkeeping, and
    `set --unpause`, which resume and rework use. An empty reason= alone never un-pauses."""
    d = Path(root) / "jobs" / check_id(job_id)
    files, div = job_files(d), diverged(d)
    given = dict(pair.partition("=")[::2] for pair in pairs)
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
            job[key] = int(value) if key in ("round", "limit") else (value or None)
        job["files"], job["diverged"] = files, div
        job["updatedAt"] = now()
    if job["stage"] != was and job["stage"] in ("done", "needs-human"):
        play(sound(job["stage"]))


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
    invalid = [r for r, v in reviews.items() if v == "INVALID"]
    verdict = None if not complete else "INVALID" if invalid else \
        "PASS" if all(v == "PASS" for v in reviews.values()) else "CHANGES"
    missing = [f"review-{r}.md" for r, v in reviews.items() if v == "pending"]
    return {"round": last_n, "complete": complete, "verdict": verdict, "invalid": invalid, "missing": missing,
            "check": last["check"] if last else None, "decision": decision, "reworks": reworks}


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
        line = next((l.strip() for l in str(event.get("last_assistant_message") or "").splitlines() if l.strip()), "")
        return f"reply needed: {line}" if line else "reply needed"
    if name in ("UserPromptSubmit", "PostToolUse"):
        return None
    return KEEP


class _Gone(Exception):
    """The matched job changed under the lock; leave the board unwritten."""


def cmd_hook(event, tty):
    """Set or clear `waiting` on the active job recorded on this tty (newest updatedAt across every registered repo).
    Writes nothing when no job matches or a clear finds it already clear, so PostToolUse stays cheap."""
    if event.get("hook_event_name") == "PreToolUse" and event.get("tool_name") == "AskUserQuestion" and notifier_disabled():
        play(sound("question"))  # the notifier skips silenced (scrum-launched) sessions, so the question sound comes from here
    text = waiting_text(event)
    if text is KEEP or not SHAPES["tty"].fullmatch(tty or ""):
        return
    text = clean(text, 200) if text else None
    match = None
    for repo in read_registry():
        root = Path(repo) / "scrum"
        try:
            jobs = json.loads((root / "board.json").read_text())["jobs"]
            for job in jobs:
                if job.get("tty") == tty and job.get("stage") in ACTIVE and (
                        match is None or str(job.get("updatedAt")) > str(match[1].get("updatedAt"))):
                    match = (root, job)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    if match is None or (text is None and match[1].get("waiting") is None):
        return
    try:
        with locked_board(match[0]) as board:
            job = next((j for j in board["jobs"] if j.get("id") == match[1].get("id")), None)
            if not job or job.get("tty") != tty or job.get("stage") not in ACTIVE or (text is None and job.get("waiting") is None):
                raise _Gone
            job.update(waiting=text, updatedAt=now())
    except _Gone:
        pass


# --- watchdog: a job whose orchestrator session died stays in its stage forever; flag it needs-human ---
WATCHED = ("spec", "build", "check", "review", "approve")
STALL_MINUTES = 30  # fixed, the same as the dashboard's STALE_MS; not a setting (UB-24)
STALLED = "stalled in "  # reason prefix: serve.py's resume, the dashboard's Resume button and SKILL.md read it
# Every needs-human reason prefix whose card offers Resume (serve.py's resume action, the dashboard, SKILL.md `resume`).
RESUMABLE = (STALLED, "bigboy off track", "bigboy review: main not updated", BLOCKED, "Base branch ")
# Pause reuses the watchdog's stalled reason, so Play is the existing resume path unchanged.
PAUSABLE = ("spec", "build", "check", "review", "approve", "merging", "plan", "running")
PAUSED = "paused by Trevor"
PAUSED_RE = re.compile(rf"^{STALLED}\w+: {PAUSED}")
ORPHANED = "requeue: orphaned claim, the session died before writing feature.md"


def cmd_pause(root, job_id):
    """Mark a job in progress (and its children in progress) needs-human with a stalled reason naming its stage.
    Every other field is kept, so resume picks up where it stopped. Returns the paused ids; plays no sound."""
    with locked_board(root) as board:
        job = find(board, check_id(job_id))
        if job["stage"] not in PAUSABLE:
            raise SystemExit(f"job {job_id} is {job['stage']}; only a job in progress can be paused")
        by_id = {j["id"]: j for j in board["jobs"]}
        hit = [job] + [by_id[k] for k in job.get("children") or [] if k in by_id and by_id[k]["stage"] in PAUSABLE]
        for j in hit:
            j.update(stage="needs-human", reason=f"{STALLED}{j['stage']}: {PAUSED}. Fix: click Play.", updatedAt=now())
        return [j["id"] for j in hit]


def _is_claude(command):
    """True when claude is the program: argv0 named `claude`, a bare `claude` token, or the claude-code package.
    A path that merely passes through `.claude/` (a worktree's dev server) does not count."""
    toks = command.split()
    return bool(toks) and (os.path.basename(toks[0]) == "claude" or "claude" in toks or "claude-code" in command)


def session_alive_fn():
    """One `ps` scan; a job is alive when a claude process line has its id or runs on its recorded tty.
    When ps can't be read, every job counts as alive, so the watchdog never flags on a guess."""
    try:
        r = subprocess.run(["ps", "-axo", "tty=,command="], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return lambda job: True
    out = r.stdout or ""
    if r.returncode != 0 or not out.strip():  # denied (a sandboxed call) or empty: unknown, never "all dead"
        return lambda job: True
    lines = [l.strip() for l in out.splitlines() if _is_claude((l.split(None, 1) + [""])[1])]  # drop the tty field
    ttys = {l.split(None, 1)[0] for l in lines if l}
    # ponytail: a reused tty or an id inside another command reads as alive; an accepted miss, never a false flag
    return lambda job: (job.get("tty") or "") in ttys or any(job["id"] in l for l in lines)


def stalled_since(job, cutoff):
    try:
        return datetime.fromisoformat(job["updatedAt"]) < cutoff
    except (KeyError, TypeError, ValueError):
        return False


def cmd_watchdog(root, alive=None):
    """Flag every job stuck in a WATCHED stage with no board update for STALL_MINUTES and no live session.
    A stuck spec job with no feature.md is an orphaned claim instead: aborted and requeued, not flagged.
    Returns the flagged ids; writes board.json only when it flags something."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALL_MINUTES)
    flagged, requeued = [], []
    try:
        with locked_board(root) as board:
            # lilguy has no pipeline to resume: its session runs in the main checkout with no worktree or builder.
            stale = [j for j in board["jobs"] if j.get("stage") in WATCHED and not j.get("waiting")
                     and j.get("lane") != "lilguy" and stalled_since(j, cutoff)]
            alive = alive or (session_alive_fn() if stale else None)  # ps only when something could be stalled
            for job in stale:
                if alive(job):
                    continue
                if job["stage"] == "spec" and not job.get("parent") \
                        and not (Path(root) / "jobs" / job["id"] / "feature.md").exists():
                    abort_job(root, job, True, ORPHANED)  # nothing to resume: put the item back, no human needed
                    requeued.append(job["id"])
                else:
                    job.update(stage="needs-human", updatedAt=now(), reason=f"{STALLED}{job['stage']}: no board update "
                               f"for {STALL_MINUTES} min and no live session. Fix: click Resume.")
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
        hit = next((j for j in jobs if j.get("id") == job_id and j.get("stage") == "needs-human"), None) \
            or next((j for j in jobs if j.get("parent") == job_id and j.get("stage") == "needs-human"), None)
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
    """Mark job_id's step done and return the next todo step. A job in no step (or no roadmap.md) changes nothing."""
    if not (Path(root) / "roadmap.md").is_file():
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


def cmd_roadmap_stop(root, job_id, reason):
    """Mark job_id's step stopped (needs a human) and log the reason."""
    with locked_board(root):
        lines, rm = roadmap_locked(root)
        hit = roadmap_job_step(rm, job_id)
        if hit is None:
            raise SystemExit(f"job {job_id!r} is in no roadmap.md step")
        ph, st = hit
        st["status"] = "stopped"
        lines[st["line"]] = format_step(st)
        roadmap_log(lines, ph["n"], st["n"], f"stopped: {reason}")
        write_roadmap(root, lines)


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
    sub.add_parser("next").add_argument("--index", type=int)
    sub.add_parser("backlog-add").add_argument("items", nargs="+")
    sub.add_parser("manual-add").add_argument("items", nargs="+")
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
    ab.add_argument("--reason")
    sub.add_parser("artifacts").add_argument("id")
    sub.add_parser("digest-due")
    sub.add_parser("digest-start")
    sub.add_parser("digest-trim").add_argument("digest")
    dv = sub.add_parser("digest-verify")
    dv.add_argument("id")
    dv.add_argument("--worktree", default=None)
    dv.add_argument("--base", default=None)
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
    cl = sub.add_parser("chain-lock")
    cl.add_argument("id")
    cl.add_argument("holder")
    cl.add_argument("--wait", type=int, default=540)
    cu = sub.add_parser("chain-unlock")
    cu.add_argument("id")
    cu.add_argument("holder")
    a = p.parse_args(argv)
    if a.cmd == "hook":
        # Never block Claude Code: no output, exit 0, whatever happens (exit 2 would block the tool call).
        try:
            cmd_hook(json.loads(sys.stdin.read()), caller_tty())
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
    elif a.cmd == "next":
        print(json.dumps(cmd_next(a.dir, a.index)))
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
        cmd_abort(a.dir, a.id, a.requeue, a.reason)
    elif a.cmd == "artifacts":
        print("".join(f"{line}\n" for line in cmd_artifacts(a.dir, a.id)), end="")
    elif a.cmd == "digest-due":
        print(json.dumps(cmd_digest_due(a.dir)))
    elif a.cmd == "digest-start":
        print(json.dumps(cmd_digest_start(a.dir)))
    elif a.cmd == "digest-trim":
        print(json.dumps(cmd_digest_trim(a.dir, a.digest)))
    elif a.cmd == "digest-verify":
        out = cmd_digest_verify(a.dir, a.id, a.worktree, a.base)
        print(json.dumps(out))
        return 0 if out["ok"] else 1
    elif a.cmd == "triage-start":
        print(json.dumps(cmd_triage_start(a.dir)))
    elif a.cmd == "triage-apply":
        print(json.dumps(cmd_triage_apply(a.dir, a.triage)))
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
    elif a.cmd == "chain-lock":
        print(json.dumps(cmd_chain_lock(a.dir, a.id, a.holder, a.wait)))
    elif a.cmd == "chain-unlock":
        print(json.dumps(cmd_chain_unlock(a.dir, a.id, a.holder)))
    elif a.cmd == "backlog-spec":
        out = cmd_backlog_spec(a.dir, a.id)
        print(json.dumps(out))
        spawn_estimates(a.dir, out["added"])
    else:
        spawn_estimates(a.dir, cmd_backlog_add(a.dir, a.items))


def spawn_estimates(root, texts):
    """The same Sonnet estimate a dashboard add gets, detached so this returns at once. Library callers spawn nothing."""
    for text in texts:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve().with_name("serve.py")), f"--estimate={text}",
                          "--dir", str(Path(root).resolve())], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    sys.exit(main())
