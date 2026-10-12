#!/usr/bin/env python3
"""The software factory's board. Only the /factory orchestrator calls this; nothing else writes board.json.

  board.py new "<title>"           create jobs/<id>/ and a board entry, print the id
  board.py set <id> key=value ...  set stage/round/limit/pr/reason/worktree/builder/base (empty value = null)
  board.py sync <id>               re-read jobs/<id>/ into the board, print round status as JSON

Verdicts are never typed in by hand: sync derives them from the first line of each file, so the board can't drift
from the files. --dir points at the project's factory/ folder (default ./factory).
"""
import argparse, fcntl, json, os, re, sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REVIEWERS = ("security", "ux", "ui", "code")
STAGES = ("spec", "build", "check", "review", "approve", "merging", "done", "needs-human")
FIELDS = ("stage", "round", "limit", "pr", "reason", "worktree", "builder", "base")
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


def slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "job"


def cmd_new(root, title):
    jobs_dir = Path(root) / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    with locked_board(root) as board:
        nums = [int(m.group(1)) for p in jobs_dir.iterdir() if (m := re.match(r"(\d+)-", p.name))]
        job_id = f"{max(nums, default=0) + 1:03d}-{slug(title)}"
        (jobs_dir / job_id).mkdir()
        board["jobs"].append({
            "id": job_id, "title": title, "branch": f"factory/{job_id}", "stage": "spec", "round": 0, "limit": 2,
            "reviews": {r: "pending" for r in REVIEWERS}, "rounds": [], "files": [],
            "pr": None, "reason": None, "worktree": None, "builder": None, "base": None, "updatedAt": now(),
        })
    return job_id


def cmd_set(root, job_id, pairs):
    with locked_board(root) as board:
        job = find(board, check_id(job_id))
        for pair in pairs:
            key, sep, value = pair.partition("=")
            if not sep or key not in FIELDS:
                raise SystemExit(f"bad field {pair!r}; allowed: {', '.join(FIELDS)}")
            if key == "stage" and value not in STAGES:
                raise SystemExit(f"bad stage {value!r}; allowed: {', '.join(STAGES)}")
            job[key] = int(value) if key in ("round", "limit") else (value or None)
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
    files = sorted(str(p.relative_to(d)) for p in d.rglob("*.md"))
    decision = first_word(d / "decision.md", ("APPROVE", "REWORK", "ESCALATE"))
    last = rounds[-1] if rounds else None
    last_n = int(round_dirs[-1].name[6:]) if round_dirs else 0
    reviews = {r: last[r] for r in REVIEWERS} if last else {r: "pending" for r in REVIEWERS}
    with locked_board(root) as board:
        job = find(board, job_id)
        job.update(rounds=rounds, files=files, reviews=reviews, round=max(job["round"], last_n), updatedAt=now())
    complete = bool(last) and "pending" not in reviews.values()
    invalid = [r for r, v in reviews.items() if v == "INVALID"]
    verdict = None if not complete else "INVALID" if invalid else \
        "PASS" if all(v == "PASS" for v in reviews.values()) else "CHANGES"
    return {"round": last_n, "complete": complete, "verdict": verdict, "invalid": invalid,
            "check": last["check"] if last else None, "decision": decision}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", type=Path, default=Path("factory"))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("new").add_argument("title")
    s = sub.add_parser("set")
    s.add_argument("id")
    s.add_argument("pairs", nargs="+")
    sub.add_parser("sync").add_argument("id")
    a = p.parse_args(argv)
    if a.cmd == "new":
        print(cmd_new(a.dir, a.title))
    elif a.cmd == "set":
        cmd_set(a.dir, a.id, a.pairs)
    else:
        print(json.dumps(cmd_sync(a.dir, a.id)))


if __name__ == "__main__":
    sys.exit(main())
