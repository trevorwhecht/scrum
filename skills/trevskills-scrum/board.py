#!/usr/bin/env python3
"""The scrum team's board. Only the /trevskills-scrum orchestrator calls this; nothing else writes board.json.

  board.py new "<title>"           create jobs/<id>/ and a board entry, print the id
  board.py set <id> key=value ...  set stage/round/limit/pr/reason/worktree/builder/base/tty/term/runlog/lane (empty = null)
  board.py sync <id>               re-read jobs/<id>/ into the board, print round status as JSON
  board.py next                    claim the first "- [ ]" backlog item as a new job, print {"id","feature"}
  board.py backlog-add "<item>"... append "- [ ] <item>" lines to backlog.md, then estimate each in the background
  board.py register <repo>         add a repo to the all-projects dashboard (idempotent)
  board.py abort <id> [--requeue] [--reason TEXT]  mark a job aborted (terminal); --requeue puts it back on the backlog
  board.py digest-due              print {"due","undigested"}: done jobs in no digests/*/jobs.txt; due at 10+
  board.py digest-start            claim them all as digests/<NNN>/jobs.txt, print {"id","jobs"} (id null = nothing new)
  board.py digest-trim <NNN>       cut that digest's done job folders to feature.md, spec.md, decision.md
  board.py triage-start            claim triage/<NNN>/ for the scrum-triager, print {"id","open"} (id null = backlog empty)
  board.py triage-apply <NNN>      apply triage/<NNN>/plan.json (merge/retire/estimate) to backlog.md, write report.md

Verdicts are never typed in by hand: sync derives them from the first line of each file, so the board can't drift
from the files. --dir points at the project's scrum/ folder (default ./scrum).
"""
import argparse, fcntl, json, os, re, shutil, subprocess, sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REVIEWERS = ("security", "ux", "ui", "code")
STAGES = ("spec", "build", "check", "review", "approve", "merging", "done", "needs-human", "aborted")
FIELDS = ("stage", "round", "limit", "pr", "reason", "worktree", "builder", "base", "tty", "term", "runlog", "lane")
TERMS = ("Apple_Terminal", "iTerm.app", "ghostty")
# Where the job's terminal is: serve.py's Open terminal button passes these to osascript/tail, so they're strict.
SHAPES = {"tty": re.compile(r"^ttys[0-9]+$"), "runlog": re.compile(r"^runs/[\w.-]+\.log$"),
          "term": re.compile("^(?:" + "|".join(map(re.escape, TERMS)) + ")$"),
          "lane": re.compile(r"^(?:fast|standard|debug|epic)$")}  # no lane key = standard
ID_RE = re.compile(r"^\d{3,}-[a-z0-9-]+$")
LINE_RE = re.compile(r"^(?:VERDICT|STATUS|CHECK|DECISION)?\s*:?\s*([A-Z-]+)\b", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


@contextmanager
def locked_board(root):
    """Exclusive lock across processes; writes only if the body didn't raise; atomic replace."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".board.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "board.json"
        try:
            board = json.loads(path.read_text()) if path.exists() else {"jobs": []}
        except json.JSONDecodeError as e:
            raise SystemExit(f"board.json is not valid JSON ({e}); fix or move it aside, it was not touched")
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


def live(board, job_id):
    """find() for the orchestrator: an aborted job refuses every further write, so a running session stops."""
    job = find(board, job_id)
    if job["stage"] == "aborted":
        raise SystemExit(f"job {job_id} was aborted by Trevor; stop working on it")
    return job


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "job"


def add_job(root, board, title):
    """Caller must hold the board lock."""
    jobs_dir = Path(root) / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    names = [p.name for p in jobs_dir.iterdir()] + [j.get("id", "") for j in board["jobs"]]
    nums = [int(m.group(1)) for name in names if (m := re.match(r"(\d+)-", name))]
    job_id = f"{max(nums, default=0) + 1:03d}-{slug(title)}"
    (jobs_dir / job_id).mkdir()
    board["jobs"].append({
        "id": job_id, "title": title, "branch": f"scrum/{job_id}", "stage": "spec", "round": 0, "limit": 2,
        "reviews": {r: "pending" for r in REVIEWERS}, "rounds": [], "files": [],
        "pr": None, "reason": None, "worktree": None, "builder": None, "base": None, "updatedAt": now(),
    })
    return job_id


def cmd_new(root, title):
    with locked_board(root) as board:
        return add_job(root, board, title)


# --- backlog.md: "- [ ] [5] Text → 003-id <!-- why -->"; points and the estimate's reason are optional ---
FIB = (1, 2, 3, 5, 8, 13)
ITEM_RE = re.compile(r"^- \[( |x)\] (?:\[(\d+|\?)\] )?(.*?)(?: → (\d{3,}-[a-z0-9-]+))?(?: <!-- (.*?) -->)?\s*$")
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
            done, pts, text, job, why = m.groups()
            items.append({"index": len(items), "line": n, "done": done == "x",
                          "points": int(pts) if pts and pts.isdigit() else None, "text": text.strip(), "why": why, "job": job})
    return lines, items


def format_item(item):
    return (f"- [{'x' if item['done'] else ' '}] " + (f"[{item['points']}] " if item["points"] else "") + item["text"]
            + (f" → {item['job']}" if item["job"] else "") + (f" <!-- {item['why']} -->" if item["why"] else ""))


def write_backlog(root, lines):
    (Path(root) / "backlog.md").write_text("\n".join(lines) + "\n")


def backlog_items(root):
    return [{k: v for k, v in item.items() if k != "line"} for item in read_backlog(root)[1]]


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
            if text is not None:
                if not clean(text):
                    raise SystemExit("backlog item text is empty")
                item["text"] = clean(text, ITEM_MAX)
            if points is not KEEP:
                check_points(points)
                item["points"] = points
            lines[item["line"]] = format_item(item)
        elif op == "delete":
            del lines[pick(items, index)["line"]]
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


def cmd_next(root, index=None):
    """Claim the first open backlog item (or item `index`) as a new job, under the lock, so no two sessions share one."""
    with locked_board(root) as board:
        lines, items = read_backlog(root)
        if index is None:
            item = next((i for i in items if not i["done"]), None)
            if item is None:
                return {"id": None, "feature": None}
        else:
            item = pick(items, index)
            if item["done"]:
                raise SystemExit(f"backlog item {index} is already claimed")
        job_id = add_job(root, board, item["text"][:60])
        item["done"], item["job"] = True, job_id
        lines[item["line"]] = format_item(item)
        write_backlog(root, lines)
        return {"id": job_id, "feature": item["text"]}


def cmd_abort(root, job_id, requeue, reason=None):
    """Mark a job aborted (terminal). Optionally put its full feature text back on the backlog as an open item."""
    feature = Path(root) / "jobs" / check_id(job_id) / "feature.md"
    with locked_board(root) as board:
        job = find(board, job_id)
        if job["stage"] in ("done", "aborted"):
            raise SystemExit(f"job {job_id} is already {job['stage']}")
        job.update(stage="aborted", reason=reason or f"Aborted by Trevor {now()}", updatedAt=now())
        if requeue:
            text = clean(feature.read_text() if feature.exists() else job["title"], ITEM_MAX) or job["title"]
            lines, _ = read_backlog(root)
            lines.append(format_item({"done": False, "points": None, "text": text, "job": None, "why": None}))
            write_backlog(root, lines)


def merge_summary(text):
    """The body of decision.md's '## Merge summary' section, or None if it has none."""
    m = re.search(r"^## Merge summary[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m and m.group(1).strip()


def cmd_reopen(root, job_id, note):
    """Start a new job that follows up a done or aborted one; its feature.md carries the old job's context."""
    old_dir = Path(root) / "jobs" / check_id(job_id)
    note = clean(note)
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


def job_files(d):
    """Every *.md in a job folder, relative and sorted; [] if the folder doesn't exist."""
    return sorted(str(p.relative_to(d)) for p in d.rglob("*.md")) if d.is_dir() else []


def diverged(d):
    """True if spec.md, build.md or assessment.md has a `## Diverged` section with a bullet that isn't `- none`."""
    for name in ("spec.md", "build.md", "assessment.md"):
        p = d / name
        if not p.is_file():
            continue
        inside = False
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("## "):
                inside = line == "## Diverged"
            elif inside and line.startswith("- ") and line[2:].strip().lower() != "none":
                return True
    return False


# --- digests: scrum/digests/<NNN>/jobs.txt lists the done jobs one digest learned from ---
DIGEST_RE = re.compile(r"^\d{3}$")
TRIM_KEEP = {"feature.md", "spec.md", "decision.md"}


def digested_ids(root):
    """Every job id listed in any digest's jobs.txt."""
    return {line.strip() for f in (Path(root) / "digests").glob("*/jobs.txt")
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


# --- triage: scrum-triager writes triage/<NNN>/plan.json; triage-apply turns it into backlog edits under the lock ---
TRIAGE_RE = DIGEST_RE


def cmd_triage_start(root):
    with locked_board(root):
        n = sum(not i["done"] for i in read_backlog(root)[1])
        return {"id": claim_folder(Path(root) / "triage"), "open": n} if n else {"id": None, "open": 0}


def cmd_triage_apply(root, triage_id):
    """Merge, retire and estimate open items by exact text. Stale, reused or bad entries are skipped and reported."""
    d = Path(root) / "triage" / str(triage_id)
    if not TRIAGE_RE.fullmatch(str(triage_id)) or not d.is_dir():
        raise SystemExit(f"no triage {triage_id!r}")
    try:
        plan = json.loads((d / "plan.json").read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"triage {triage_id}: plan.json is missing or not JSON ({e}); backlog.md was not touched")
    if not isinstance(plan, dict) or any(not isinstance(plan.get(k) or [], list) for k in ("merge", "retire", "estimate")):
        raise SystemExit(f"triage {triage_id}: plan.json must be an object of merge/retire/estimate lists; backlog.md was not touched")
    report = {"Merged": [], "Retired": [], "Estimated": [], "Skipped": []}
    gone = lambda text: format_item({"done": True, "points": None, "text": text, "job": None, "why": None})
    with locked_board(root):
        lines, items = read_backlog(root)
        used, before = set(), {}  # item indexes already consumed; line number -> combined lines inserted above it

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

        for kind in ("merge", "retire", "estimate"):
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
                elif got and kind == "retire" and not clean(e.get("reason") or ""):
                    cause = "no reason given"
                elif got and kind == "estimate" and got[0]["points"] is not None:
                    cause = "already pointed"
                elif got and kind == "estimate" and pts is None:
                    cause = f"points {e.get('points')!r} not in {', '.join(map(str, FIB))}"
                if cause:
                    report["Skipped"].append(f"- {label} — {cause}\n")
                    continue
                used.update(i["index"] for i in got)
                why = clean(e.get("why") or "") or None
                if kind == "merge":
                    text = clean(e["text"], ITEM_MAX)
                    for i in got:
                        lines[i["line"]] = gone(i["text"]) + f" <!-- merged into triage {triage_id} -->"
                    before.setdefault(min(i["line"] for i in got), []).append(
                        format_item({"done": False, "points": pts, "text": text, "job": None, "why": why}))
                    report["Merged"].append(f"- {text}\n" + "".join(f"  - replaced: {i['text']}\n" for i in got))
                elif kind == "retire":
                    reason = clean(e["reason"])
                    lines[got[0]["line"]] = gone(got[0]["text"]) + f" <!-- retired: {reason} -->"
                    report["Retired"].append(f"- {got[0]['text']} — {reason}\n")
                else:
                    item = got[0] | {"points": pts, "why": why}
                    lines[item["line"]] = format_item(item)
                    report["Estimated"].append(f"- [{pts}] {item['text']}" + (f" — {why}" if why else "") + "\n")
        write_backlog(root, [x for n, line in enumerate(lines) for x in (*before.get(n, []), line)])
        text = f"# Triage {triage_id} — {now()}\n" + "".join(
            f"\n## {title}\n" + ("".join(rows) or "None.\n") for title, rows in report.items())
        (d / "report.md").write_text(text)
        (Path(root) / "triage" / "latest.md").write_text(text)
    return {"merged": len(report["Merged"]), "retired": len(report["Retired"]),
            "estimated": len(report["Estimated"]), "skipped": len(report["Skipped"])}


def cmd_set(root, job_id, pairs):
    d = Path(root) / "jobs" / check_id(job_id)
    files, div = job_files(d), diverged(d)
    with locked_board(root) as board:
        job = live(board, check_id(job_id))
        for pair in pairs:
            key, sep, value = pair.partition("=")
            if not sep or key not in FIELDS:
                raise SystemExit(f"bad field {pair!r}; allowed: {', '.join(FIELDS)}")
            if key == "stage" and value not in STAGES:
                raise SystemExit(f"bad stage {value!r}; allowed: {', '.join(STAGES)}")
            if value and key in SHAPES and not SHAPES[key].fullmatch(value):
                raise SystemExit(f"bad field {pair!r}; {key} must match {SHAPES[key].pattern}")
            job[key] = int(value) if key in ("round", "limit") else (value or None)
        job["files"], job["diverged"] = files, div
        job["updatedAt"] = now()


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
    return {"round": last_n, "complete": complete, "verdict": verdict, "invalid": invalid,
            "check": last["check"] if last else None, "decision": decision, "reworks": reworks}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", type=Path, default=Path("scrum"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new").add_argument("title")
    s = sub.add_parser("set")
    s.add_argument("id")
    s.add_argument("pairs", nargs="+")
    sub.add_parser("sync").add_argument("id")
    sub.add_parser("next").add_argument("--index", type=int)
    sub.add_parser("backlog-add").add_argument("items", nargs="+")
    sub.add_parser("register").add_argument("repo", type=Path)
    ab = sub.add_parser("abort")
    ab.add_argument("id")
    ab.add_argument("--requeue", action="store_true")
    ab.add_argument("--reason")
    sub.add_parser("digest-due")
    sub.add_parser("digest-start")
    sub.add_parser("digest-trim").add_argument("digest")
    sub.add_parser("triage-start")
    sub.add_parser("triage-apply").add_argument("triage")
    a = p.parse_args(argv)
    if a.cmd == "new":
        print(cmd_new(a.dir, a.title))
    elif a.cmd == "set":
        cmd_set(a.dir, a.id, a.pairs)
    elif a.cmd == "sync":
        print(json.dumps(cmd_sync(a.dir, a.id)))
    elif a.cmd == "next":
        print(json.dumps(cmd_next(a.dir, a.index)))
    elif a.cmd == "register":
        cmd_register(a.repo)
    elif a.cmd == "abort":
        cmd_abort(a.dir, a.id, a.requeue, a.reason)
    elif a.cmd == "digest-due":
        print(json.dumps(cmd_digest_due(a.dir)))
    elif a.cmd == "digest-start":
        print(json.dumps(cmd_digest_start(a.dir)))
    elif a.cmd == "digest-trim":
        print(json.dumps(cmd_digest_trim(a.dir, a.digest)))
    elif a.cmd == "triage-start":
        print(json.dumps(cmd_triage_start(a.dir)))
    elif a.cmd == "triage-apply":
        print(json.dumps(cmd_triage_apply(a.dir, a.triage)))
    else:
        # The same Sonnet estimate a dashboard add gets, detached so this returns at once. Library callers spawn nothing.
        for text in cmd_backlog_add(a.dir, a.items):
            subprocess.Popen([sys.executable, str(Path(__file__).resolve().with_name("serve.py")), "--estimate", text,
                              "--dir", str(a.dir.resolve())], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)


if __name__ == "__main__":
    sys.exit(main())
