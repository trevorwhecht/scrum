# Software Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `/factory` Claude Code skill and its agents. It turns a feature request into a squash-merged PR, and a one-file dashboard shows each job's progress.

**Architecture:**
- **One orchestrator skill** (`skills/factory/SKILL.md`) runs the loop and spawns seven subagents (`agents/factory-*.md`). Each agent writes exactly one markdown file per step.
- **`board.py` is the only writer of `board.json`.** It is stdlib Python and uses a file lock with atomic replace. It derives review verdicts from the first lines of the files on disk, so the board can't drift from the files.
- **`dashboard.html` polls `board.json`.** It is a single static file.
- **`install.sh` symlinks everything into `~/.claude`.** That makes the factory work in every repo.

**Tech Stack:** Markdown (skill and agents), Python 3 stdlib with unittest, plain HTML/CSS/JS with marked@12.0.2 from cdnjs, bash, git worktrees, and the `gh` CLI.

**Spec:** `docs/spec.md`

## Global Constraints

- Every agent file is named `factory-<role>.md`, and its frontmatter `name` matches the filename.
- Models: spec-writer, builder, security and approver run on `opus`. The ux, ui and code reviewers run on `sonnet`.
- First-line contracts, all case-insensitive and tolerant of markdown decoration:
  - reviews: `VERDICT: PASS|CHANGES`
  - `build.md`: `STATUS: READY|BLOCKED`
  - `check.md`: `CHECK: PASS|FAIL`
  - `decision.md`: `APPROVE|REWORK|ESCALATE`
- Reviewers: `CHANGES` only for a `[blocking]` finding with confidence ≥ 80.
- The default review round limit is 2. The approver may REWORK at most once per job. `/factory rework` adds 2 rounds.
- Escalation reasons are hard stops only:
  - schema/migrations
  - money/auth/secrets
  - builder BLOCKED
  - infrastructure: `gh` missing, or a PR conflict or CI still failing after 2 builder fixes
- Never run anywhere: `prisma migrate`, `prisma db push`, `git reset`, `git rebase`, force-push, `gh pr merge --auto/--admin`, or a push to `main`/`master`.
- The only `git merge` allowed: the orchestrator runs `git -C $WT merge origin/$DEFAULT` to resolve a PR conflict on its own `factory/*` branch. Agents never run `git merge`.
- The only merge is `gh pr merge <factory/id> --squash`, after checks pass.
- Python is stdlib only. The dashboard has no build step and exactly one CDN script, pinned to `marked@12.0.2`.
- Tests run with `python3 -m unittest discover -s tests -v` from the repo root.

## Review Focus

1. **Two `/factory` sessions create jobs at the same moment.** Expected: unique ids and no lost board entries. Test: `test_concurrent_new_jobs_get_unique_ids`, Task 1.
2. **A reviewer decorates or mangles its first line** (bold, heading, lowercase, BOM, leading blank lines, prose). Expected: decorated verdicts parse, and garbage reads as `INVALID`, never as PASS. Tests: `test_first_word_*`, Task 1.
3. **`board.json` is corrupt or hand-edited badly.** Expected: a clear error, and the board is never silently replaced with an empty one. Test: `test_corrupt_board_is_not_overwritten`, Task 1.
4. **The dashboard faces an empty project**: no `board.json`, a job with zero rounds, a 404 on a markdown file, or the CDN offline. Expected: an empty-state line or plain text, never a blank page or a JS crash. Fixture plus browser check, Task 4.
5. **`install.sh` is re-run, or `~/.claude/agents` already holds a real file with the same name.** Expected: re-running is safe, and the script refuses to overwrite a real file. Test: `test_install_*`, Task 5.

Also pinned: a job id containing `../` is rejected (`test_rejects_path_traversal_id`, Task 1).

---

## File Structure

```
software-factory/
  README.md                      # what it is, install, commands, loop diagram
  install.sh                     # symlinks skill + agents into ~/.claude
  .gitignore
  agents/
    factory-spec-writer.md       # writes spec.md
    factory-builder.md           # writes code + commits in the worktree, writes build.md
    factory-review-security.md   # writes round-N/review-security.md
    factory-review-ux.md         # writes round-N/review-ux.md
    factory-review-ui.md         # writes round-N/review-ui.md
    factory-review-code.md       # writes round-N/review-code.md
    factory-approver.md          # writes decision.md
  skills/factory/
    SKILL.md                     # the orchestrator
    board.py                     # the only writer of board.json
    dashboard.html               # symlinked into each project's factory/
  tests/
    test_board.py
    test_contracts.py
    test_install.py
    fixture/factory/...          # sample board + job files for the dashboard
  docs/spec.md, docs/plans/...
```

Each project gets this, created by `/factory` on its first run and gitignored through `.git/info/exclude`:

```
factory/
  board.json  backlog.md  project.md  dashboard.html -> ~/.claude/skills/factory/dashboard.html
  jobs/<id>/
    feature.md  spec.md  build.md  decision.md  rework.md  ci.md
    round-N/  check.md  review-security.md  review-ux.md  review-ui.md  review-code.md  decision.md
```

---

### Task 1: board.py (the board's only writer)

**Files:**
- Create: `skills/factory/board.py`
- Create: `.gitignore`
- Test: `tests/test_board.py`

**Interfaces:**
- Produces, as a CLI (default `--dir factory`):
  - `board.py new "<title>"` prints the new job id, e.g. `004-rate-limiting`.
  - `board.py set <id> key=value ...` sets fields. Keys are `stage round limit pr reason worktree builder base`. Stages are `spec build check review approve merging done needs-human`. An empty value means null.
  - `board.py sync <id>` re-reads `jobs/<id>/`, updates the board, and prints JSON: `{"round": int, "complete": bool, "verdict": "PASS"|"CHANGES"|"INVALID"|null, "invalid": [reviewer...], "check": "PASS"|"FAIL"|"pending"|null, "decision": "APPROVE"|"REWORK"|"ESCALATE"|"INVALID"|null}`
- Produces, as Python functions used by the tests: `first_word(path, allowed) -> str|None`, `cmd_new(root, title) -> str`, `cmd_set(root, job_id, pairs)`, `cmd_sync(root, job_id) -> dict`.
- Job shape in `board.json`: `{id, title, branch, stage, round, limit, reviews:{security,ux,ui,code}, rounds:[{check,security,ux,ui,code}], files:[relpath], pr, reason, worktree, builder, base, updatedAt}`

- [ ] **Step 1: Create the branch and `.gitignore`**

```bash
cd ~/Developer/repos/software-factory
git switch -c feat/factory-v1
printf '__pycache__/\n*.pyc\n' > .gitignore
```

- [ ] **Step 2: Write the failing tests**

`tests/test_board.py`:

```python
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "factory"))
import board  # noqa: E402

BOARD_PY = ROOT / "skills" / "factory" / "board.py"


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "factory"

    def tearDown(self):
        self.tmp.cleanup()

    def jobs(self):
        return json.loads((self.root / "board.json").read_text())["jobs"]

    def write(self, rel, text):
        p = self.root / "jobs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # --- new ---
    def test_new_creates_job_folder_and_entry(self):
        job_id = board.cmd_new(self.root, "Add Rate Limiting!")
        self.assertEqual(job_id, "001-add-rate-limiting")
        self.assertTrue((self.root / "jobs" / job_id).is_dir())
        job = self.jobs()[0]
        self.assertEqual(job["branch"], "factory/001-add-rate-limiting")
        self.assertEqual(job["stage"], "spec")
        self.assertEqual(job["limit"], 2)
        self.assertEqual(job["reviews"], {r: "pending" for r in board.REVIEWERS})

    def test_new_numbers_continue_past_existing_folders(self):
        (self.root / "jobs" / "007-old").mkdir(parents=True)
        self.assertTrue(board.cmd_new(self.root, "next").startswith("008-"))

    def test_new_with_symbol_only_title_gets_fallback_slug(self):
        self.assertEqual(board.cmd_new(self.root, "!!!"), "001-job")

    def test_concurrent_new_jobs_get_unique_ids(self):
        procs = [subprocess.Popen([sys.executable, str(BOARD_PY), "--dir", str(self.root), "new", f"job {i}"],
                                  stdout=subprocess.PIPE, text=True) for i in range(8)]
        ids = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(len(self.jobs()), 8)

    # --- set ---
    def test_set_updates_fields_and_casts_round(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=review", "round=2", "pr=https://x/1", "reason="])
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["round"], job["pr"], job["reason"]), ("review", 2, "https://x/1", None))

    def test_set_rejects_unknown_field_and_bad_stage_without_writing(self):
        job_id = board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, job_id, ["stage=review", "colour=red"])
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, job_id, ["stage=shipping"])
        self.assertEqual(self.jobs()[0]["stage"], "spec")

    def test_set_unknown_job_fails(self):
        board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, "999-nope", ["stage=done"])

    def test_rejects_path_traversal_id(self):
        board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_sync(self.root, "../../etc")

    def test_corrupt_board_is_not_overwritten(self):
        job_id = board.cmd_new(self.root, "x")
        (self.root / "board.json").write_text("{not json")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, job_id, ["stage=done"])
        self.assertEqual((self.root / "board.json").read_text(), "{not json")

    # --- first_word ---
    def test_first_word_tolerates_decoration(self):
        allowed = ("PASS", "CHANGES")
        for text in ["VERDICT: PASS\n", "**VERDICT: PASS**", "# Verdict: pass", "\n\n  verdict:PASS — fine",
                     "﻿VERDICT: CHANGES"]:
            p = self.write("t/r.md", text)
            self.assertIn(board.first_word(p, allowed), allowed, text)

    def test_first_word_garbage_is_invalid_not_pass(self):
        p = self.write("t/r.md", "Looks good to me!\nVERDICT: PASS")
        self.assertEqual(board.first_word(p, ("PASS", "CHANGES")), "INVALID")
        p = self.write("t/e.md", "")
        self.assertEqual(board.first_word(p, ("PASS", "CHANGES")), "INVALID")

    def test_first_word_missing_file_is_none(self):
        self.assertIsNone(board.first_word(self.root / "nope.md", ("PASS",)))

    # --- sync ---
    def test_sync_incomplete_round_is_not_complete(self):
        job_id = board.cmd_new(self.root, "x")
        self.write(f"{job_id}/spec.md", "# spec")
        self.write(f"{job_id}/round-1/check.md", "CHECK: PASS")
        self.write(f"{job_id}/round-1/review-security.md", "VERDICT: PASS")
        self.write(f"{job_id}/round-1/review-ux.md", "VERDICT: CHANGES")
        status = board.cmd_sync(self.root, job_id)
        self.assertEqual(status["round"], 1)
        self.assertFalse(status["complete"])
        self.assertIsNone(status["verdict"])
        self.assertEqual(status["check"], "PASS")
        job = self.jobs()[0]
        self.assertEqual(job["reviews"], {"security": "PASS", "ux": "CHANGES", "ui": "pending", "code": "pending"})
        self.assertIn("round-1/review-ux.md", job["files"])
        self.assertIn("spec.md", job["files"])

    def test_sync_complete_rounds_and_verdicts(self):
        job_id = board.cmd_new(self.root, "x")
        for r in board.REVIEWERS:
            self.write(f"{job_id}/round-1/review-{r}.md", "VERDICT: CHANGES" if r == "code" else "VERDICT: PASS")
            self.write(f"{job_id}/round-2/review-{r}.md", "VERDICT: PASS")
        self.write(f"{job_id}/round-10/check.md", "CHECK: FAIL")  # sorted numerically, not as text
        status = board.cmd_sync(self.root, job_id)
        self.assertEqual(status["round"], 10)
        job = self.jobs()[0]
        self.assertEqual(job["rounds"][0]["code"], "CHANGES")
        self.assertEqual(job["rounds"][1]["code"], "PASS")
        self.assertEqual(job["rounds"][2]["check"], "FAIL")

    def test_sync_reports_pass_changes_and_invalid(self):
        job_id = board.cmd_new(self.root, "x")
        for r in board.REVIEWERS:
            self.write(f"{job_id}/round-1/review-{r}.md", "VERDICT: PASS")
        self.assertEqual(board.cmd_sync(self.root, job_id)["verdict"], "PASS")
        self.write(f"{job_id}/round-1/review-ui.md", "VERDICT: CHANGES")
        self.assertEqual(board.cmd_sync(self.root, job_id)["verdict"], "CHANGES")
        self.write(f"{job_id}/round-1/review-ux.md", "I think it's fine")
        status = board.cmd_sync(self.root, job_id)
        self.assertTrue(status["complete"])
        self.assertEqual((status["verdict"], status["invalid"]), ("INVALID", ["ux"]))

    def test_sync_reads_decision(self):
        job_id = board.cmd_new(self.root, "x")
        self.assertIsNone(board.cmd_sync(self.root, job_id)["decision"])
        self.write(f"{job_id}/decision.md", "**ESCALATE**\nHard stop: auth")
        self.assertEqual(board.cmd_sync(self.root, job_id)["decision"], "ESCALATE")

    def test_cli_set_and_sync(self):
        run = lambda *a: subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), *a],
                                        capture_output=True, text=True)
        job_id = run("new", "cli job").stdout.strip()
        self.assertEqual(run("set", job_id, "stage=build").returncode, 0)
        out = run("sync", job_id)
        self.assertEqual(json.loads(out.stdout)["round"], 0)
        bad = run("set", job_id, "nope=1")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("nope", bad.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `python3 -m unittest discover -s tests -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'board'`.

- [ ] **Step 4: Write `skills/factory/board.py`**

```python
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
```

Note: `round-10` sorts numerically because of the sort key. The `round` field is never lowered by sync, so an orchestrator `set round=N` made before the folder exists still sticks.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests in `test_board.py` PASS.

- [ ] **Step 6: Commit**

```bash
chmod +x skills/factory/board.py
git add .gitignore skills/factory/board.py tests/test_board.py docs/
git commit -m "Add factory board: locked, file-derived job state

- board.py new/set/sync, the single writer of board.json
- verdicts parsed from first lines, tolerant of markdown, garbage = INVALID
- spec and implementation plan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The seven agents

**Files:**
- Create: `agents/factory-spec-writer.md`, `agents/factory-builder.md`, `agents/factory-review-security.md`, `agents/factory-review-ux.md`, `agents/factory-review-ui.md`, `agents/factory-review-code.md`, `agents/factory-approver.md`
- Test: `tests/test_contracts.py`

**Interfaces:**
- Consumes: the job folder layout and first-line contracts from Task 1.
- Produces: subagent types `factory-spec-writer`, `factory-builder`, `factory-review-security`, `factory-review-ux`, `factory-review-ui`, `factory-review-code`, `factory-approver`. Every spawn prompt from the orchestrator (Task 3) passes exactly these lines: `JOB_DIR=<abs path>`, `WORKTREE=<abs path or none>`, `BASE=<base ref>`, `ROUND=<n>`, `PROJECT=<abs path to factory/project.md>`.

- [ ] **Step 1: Write the failing contract test**

`tests/test_contracts.py`:

```python
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = {
    "factory-spec-writer": "opus", "factory-builder": "opus", "factory-review-security": "opus",
    "factory-review-ux": "sonnet", "factory-review-ui": "sonnet", "factory-review-code": "sonnet",
    "factory-approver": "opus",
}
FIRST_LINE = {
    "factory-builder": "STATUS: READY", "factory-approver": "ESCALATE", "factory-review-security": "VERDICT: PASS",
    "factory-review-ux": "VERDICT: PASS", "factory-review-ui": "VERDICT: PASS", "factory-review-code": "VERDICT: PASS",
}


def frontmatter(path):
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path.name}: no frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


class ContractTest(unittest.TestCase):
    def test_exactly_the_expected_agents_exist(self):
        self.assertEqual({p.stem for p in (ROOT / "agents").glob("*.md")}, set(AGENTS))

    def test_frontmatter(self):
        for name, model in AGENTS.items():
            fm = frontmatter(ROOT / "agents" / f"{name}.md")
            self.assertEqual(fm.get("name"), name)
            self.assertEqual(fm.get("model"), model, name)
            self.assertTrue(fm.get("description"), name)
            self.assertIn("Read", fm.get("tools", ""), name)
            self.assertNotIn("Agent", fm.get("tools", ""), f"{name} must not spawn agents")

    def test_first_line_contracts_are_documented(self):
        for name, phrase in FIRST_LINE.items():
            self.assertIn(phrase, (ROOT / "agents" / f"{name}.md").read_text(), name)

    def test_every_agent_forbids_migrations_and_merges(self):
        for name in AGENTS:
            text = (ROOT / "agents" / f"{name}.md").read_text()
            self.assertIn("prisma migrate", text, name)
            self.assertIn("git merge", text, name)


if __name__ == "__main__":
    unittest.main()
```

The `SKILL.md` checks are added to this file in Task 3.

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python3 -m unittest tests.test_contracts -v`
Expected: FAIL in `test_exactly_the_expected_agents_exist`, because the set is empty.

- [ ] **Step 3: Write `agents/factory-spec-writer.md`**

```markdown
---
name: factory-spec-writer
description: Factory step 1. Turns a feature request (feature.md) into a testable spec.md. Spawned only by the /factory orchestrator.
tools: Read, Grep, Glob, Bash, Write
model: opus
---

You are the spec writer in an unattended software factory. **No human is watching.** Never ask questions; when something is unclear, choose the most reasonable reading and record it under Assumptions.

**Inputs** (paths are in your prompt): `JOB_DIR/feature.md` (the request), `PROJECT` (the repo profile: stack, commands, conventions), and the repository itself (read-only). Read the convention files that `PROJECT` lists before writing.

**Output:** write exactly one file, `JOB_DIR/spec.md`, in this shape:

    # <Feature title>
    UI surface: yes|no
    Hard stops: none | schema | money | auth | secrets   (comma-separated if more than one)

    ## Problem
    ## Scope
    In: ... / Out: ...
    ## Acceptance criteria
    1. <observable behaviour> (verify: <test name to write, command, or manual step>)
    ## Likely files
    ## Assumptions

Rules:
- Acceptance criteria are numbered, observable and testable. Aim for 3–8. Each one says how it will be verified.
- `UI surface: no` only if the change renders nothing a user sees. The ux and ui reviewers skip the job when it says no.
- `Hard stops` flags early whether the feature needs a schema/migration change or touches payments, auth/sessions/permissions, or secrets/env vars. The approver checks the actual diff later; this is the early warning.
- Keep scope minimal: the smallest change that delivers the request. List "nice to haves" under Out.
- Write no code and touch no file except `spec.md`. Never run `prisma migrate`, `prisma db push`, `git merge`, `git reset`, `git rebase`, or any push.
```

- [ ] **Step 4: Write `agents/factory-builder.md`**

```markdown
---
name: factory-builder
description: Factory builder. Implements spec.md in the job's worktree, commits on its factory/<id> branch, and writes build.md; it is resumed for each fix round. Spawned only by the /factory orchestrator.
tools: Read, Grep, Glob, Bash, Edit, Write
model: opus
---

You are the builder in an unattended software factory. **No human is watching.** Never ask questions; make the reasonable call and note it in build.md.

**Inputs** (paths are in your prompt): `JOB_DIR/spec.md`, `PROJECT` (stack, commands, conventions — read every convention file it lists), and `WORKTREE` (your checkout, already on branch `factory/<id>`).

**First run:**
1. `cd WORKTREE`. Run the project's install command from `PROJECT` if dependencies are missing.
2. Implement the spec. Follow the repo's conventions exactly; reuse existing components and helpers before writing new ones.
3. For each acceptance criterion: if the repo has a test runner, write a test that proves it. If it doesn't, verify it another way (a command, a script, a build) and record how.
4. Run the project's test, typecheck, lint and build commands from `PROJECT`. Fix whatever you broke.
5. Commit on your branch as you go: `git add -A && git commit -m "<imperative summary>"`, ending the message with the `Co-Authored-By:` trailer the harness gives you.
6. Write `JOB_DIR/build.md`.

**build.md** (rewrite the whole file each time and keep earlier round sections):

    STATUS: READY            ← or BLOCKED (only when the spec cannot be built at all; say why)
    ## Summary
    ## Acceptance criteria
    1. <criterion> — verified by <test name / command> — PASS
    ## Commits
    ## Round N response      ← added for each fix round
    - <reviewer> finding K: fixed in <commit> | declined: <reason>

**Resumed runs.** You'll be pointed at a round folder (`JOB_DIR/round-N/`) holding `check.md` and/or `review-*.md`, or at `JOB_DIR/decision.md`, `JOB_DIR/rework.md` or `JOB_DIR/ci.md`:
- If the worktree is mid-merge (the orchestrator merged the default branch in, and there are conflict markers): resolve every conflict, keeping both sides' intent. Then `git add -A && git commit --no-edit`, and note what you resolved in build.md.
- Fix every failing check, and every finding marked `[blocking]` in a CHANGES review. `[minor]` findings and Notes are optional.
- You may decline a finding that is wrong; give the reason in build.md.
- Do not start a new review yourself, and do not edit any review file.
- Commit, re-run the checks, and update build.md.

**Hard limits:**
- Change files only inside `WORKTREE`. The one exception is `JOB_DIR/build.md`.
- Never push, and never run `git merge`, `git reset`, `git rebase`, `git push`, `git checkout main`, or any `gh` command.
- Never run `prisma migrate` or `prisma db push`. If the spec needs a schema change, edit `prisma/schema.prisma` only and write "MIGRATION NEEDED: <what>" in build.md; a human applies it.
- Never commit `.env*` files or secrets. The `.env*` files in the worktree are symlinks to the main checkout; leave them alone.
```

- [ ] **Step 5: Write `agents/factory-review-security.md`**

```markdown
---
name: factory-review-security
description: Factory security reviewer. Reviews one round's diff for exploitable problems and writes round-N/review-security.md. Spawned only by the /factory orchestrator.
tools: Read, Grep, Glob, Bash, Write
model: opus
---

You review one build round for security. **No human is watching**, so never ask questions.

**Inputs** (paths are in your prompt): `JOB_DIR/spec.md`, `JOB_DIR/build.md`, `PROJECT`, the diff from `git -C WORKTREE diff BASE...HEAD`, and your own review from the previous round (`JOB_DIR/round-<N-1>/review-security.md`) if there is one.

**Look for:**
- auth and authorization on every new route or action, and IDOR
- injection: SQL, command, path, HTML/XSS
- input validation at trust boundaries
- secrets in code or logs; committed `.env*` files
- sensitive data reaching clients, e.g. cost fields reaching non-admin payloads
- SSRF and open redirects
- unsafe new dependencies: unknown, unmaintained or typosquatted packages
- missing rate limits on abusable endpoints

**Output:** write exactly one file, `JOB_DIR/round-ROUND/review-security.md`:

    VERDICT: PASS            ← or VERDICT: CHANGES
    ## Findings
    1. [blocking|minor] (confidence NN) path:line — the problem — the concrete fix
    ## Notes
    - non-blocking observations, taste

**Rules:**
- `VERDICT: CHANGES` only when at least one finding is `[blocking]` with confidence ≥ 80, meaning a real, reachable problem in *this diff*. Anything else is PASS. Theoretical issues and pre-existing code go in Notes.
- Round 2 and later: first check that your earlier blocking findings were fixed. Raise new blocking issues only if they are real; don't move the goalposts.
- Don't edit code. Bash is only for read-only commands (`git diff`, `grep`, running tests). Never run `prisma migrate`, `prisma db push`, `git merge`, `git reset`, `git rebase`, or any push.
```

- [ ] **Step 6: Write `agents/factory-review-ux.md`**

```markdown
---
name: factory-review-ux
description: Factory UX reviewer. Reviews one round's user flows, states, copy and accessibility, and writes round-N/review-ux.md. Spawned only by the /factory orchestrator.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
---

You review one build round for user experience. **No human is watching**, so never ask questions.

**Shortcut:** if `JOB_DIR/spec.md` says `UI surface: no`, and the diff (`git -C WORKTREE diff --stat BASE...HEAD`) touches no UI files, write `VERDICT: PASS` followed by `No UI surface.` and stop.

**Inputs** (paths are in your prompt): `JOB_DIR/spec.md`, `JOB_DIR/build.md`, `PROJECT` and the convention files it lists (especially any UI behaviour or UI copy rules, which you cite by rule ID), the diff (`git -C WORKTREE diff BASE...HEAD`), and your previous round's review if there is one.

**Look for:**
- whether the flow actually delivers each acceptance criterion
- loading, empty and error states
- disabled states that reflect reality
- forms submit on Enter and show pending progress
- copy: labels, not explanations
- accessibility basics: labels, focus, keyboard, aria on icon buttons
- mobile at 390px: touch targets, keyboard, full-width modals
- one way to do a thing

**Output:** write exactly one file, `JOB_DIR/round-ROUND/review-ux.md`:

    VERDICT: PASS            ← or VERDICT: CHANGES
    ## Findings
    1. [blocking|minor] (confidence NN) path:line — the problem (rule ID if one applies) — the concrete fix
    ## Notes

**Rules:**
- `VERDICT: CHANGES` only when at least one finding is `[blocking]` with confidence ≥ 80. Taste goes in Notes.
- Judge new violations in this diff, not existing debt.
- Round 2 and later: check your earlier blocking findings first, and don't move the goalposts.
- Don't edit code. Bash is read-only. Never run `prisma migrate`, `prisma db push`, `git merge`, `git reset`, `git rebase`, or any push.
```

- [ ] **Step 7: Write `agents/factory-review-ui.md`**

```markdown
---
name: factory-review-ui
description: Factory UI design reviewer. Reviews one round's visual consistency, theming and layout, and writes round-N/review-ui.md. Spawned only by the /factory orchestrator.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
---

You review one build round for visual design. **No human is watching**, so never ask questions.

**Shortcut:** if `JOB_DIR/spec.md` says `UI surface: no`, and the diff (`git -C WORKTREE diff --stat BASE...HEAD`) touches no UI files, write `VERDICT: PASS` followed by `No UI surface.` and stop.

**Inputs** (paths are in your prompt): `JOB_DIR/spec.md`, `JOB_DIR/build.md`, `PROJECT` and the convention files it lists (cite UI rule IDs where they exist), the diff (`git -C WORKTREE diff BASE...HEAD`), the existing components near the change, and your previous round's review if there is one.

**Look for:**
- reuse of existing components instead of visual twins
- theme variables instead of hex values, raw palette classes, font names or `dark:` colour variants
- spacing taken from the scale, matching its neighbours
- nothing overlapping, clipped or overflowing at 390px and 1440px
- floating elements have explicit backgrounds
- numbers formatted through the app's single formatter
- one icon library and one spinner

**Output:** write exactly one file, `JOB_DIR/round-ROUND/review-ui.md`:

    VERDICT: PASS            ← or VERDICT: CHANGES
    ## Findings
    1. [blocking|minor] (confidence NN) path:line — the problem (rule ID if one applies) — the concrete fix
    ## Notes

**Rules:**
- `VERDICT: CHANGES` only when at least one finding is `[blocking]` with confidence ≥ 80. Taste goes in Notes.
- Judge new violations in this diff, not existing debt.
- Round 2 and later: check your earlier blocking findings first, and don't move the goalposts.
- Don't edit code. Bash is read-only. Never run `prisma migrate`, `prisma db push`, `git merge`, `git reset`, `git rebase`, or any push.
```

- [ ] **Step 8: Write `agents/factory-review-code.md`**

```markdown
---
name: factory-review-code
description: Factory code reviewer. Reviews one round's correctness against the acceptance criteria, its tests, conventions and simplicity, and writes round-N/review-code.md. Spawned only by the /factory orchestrator.
tools: Read, Grep, Glob, Bash, Write
model: sonnet
---

You review one build round for code quality. **No human is watching**, so never ask questions.

**Inputs** (paths are in your prompt): `JOB_DIR/spec.md`, `JOB_DIR/build.md`, `JOB_DIR/round-ROUND/check.md`, `PROJECT` and the convention files it lists, the diff (`git -C WORKTREE diff BASE...HEAD`), and your previous round's review if there is one.

**Look for:**
- every acceptance criterion actually implemented and actually verified; run the tests yourself if in doubt
- bugs and missing edge cases
- logic duplicated where something existing could be reused
- unrequested abstractions and over-engineering
- the repo's conventions: file naming, file size, the Result pattern if used, the TODO format
- fetching only what is needed: no `SELECT *`, no over-fetching
- dead code

**Output:** write exactly one file, `JOB_DIR/round-ROUND/review-code.md`:

    VERDICT: PASS            ← or VERDICT: CHANGES
    ## Findings
    1. [blocking|minor] (confidence NN) path:line — the problem — the concrete fix
    ## Notes

**Rules:**
- `VERDICT: CHANGES` only when at least one finding is `[blocking]` with confidence ≥ 80. Taste goes in Notes.
- Round 2 and later: check your earlier blocking findings first, and don't move the goalposts.
- Don't edit code. Bash is for read-only commands and running tests. Never run `prisma migrate`, `prisma db push`, `git merge`, `git reset`, `git rebase`, or any push.
```

- [ ] **Step 9: Write `agents/factory-approver.md`**

```markdown
---
name: factory-approver
description: Factory approver. Makes the final call on a job (APPROVE, REWORK or ESCALATE) and writes decision.md; it escalates to a human only on hard stops. Spawned only by the /factory orchestrator.
tools: Read, Grep, Glob, Bash, Write
model: opus
---

You are the final gate of an unattended software factory, and a senior engineer who ships. **The human wants to be asked almost never.** Your job is to decide, not to defer.

**Inputs** (paths are in your prompt): everything in `JOB_DIR` (`spec.md`, `build.md`, every `round-*/` folder with its check and reviews, any earlier `round-*/decision.md`, `rework.md`, `ci.md`), `PROJECT`, and the full diff (`git -C WORKTREE diff BASE...HEAD`, plus `--name-only`).

**Output:** write exactly one file, `JOB_DIR/decision.md`. Its first line is exactly one of `APPROVE`, `REWORK` or `ESCALATE`.

    APPROVE
    ## Rulings
    - <reviewer> finding K: fixed | defer | override — reason
    ## Follow-ups
    - <one-line backlog item>      ← deferred work; the orchestrator appends these to backlog.md
    ## Merge summary
    Title: <imperative, high-level, ≤ 70 chars>
    - <high-level change 1>
    - <high-level change 2>

**ESCALATE only for a hard stop**, and name it on the second line as `Hard stop: <which> — <evidence>`:
1. **schema**: the diff touches `prisma/schema.prisma`, `prisma/migrations/`, or any SQL migration (a human must run `/trevskills-migrate`)
2. **money**: payment, checkout, pricing-calculation or billing logic changed
3. **auth**: authentication, session, role or permission logic changed
4. **secrets**: env-var handling, key management, or secrets changed
5. **blocked**: `build.md` says `STATUS: BLOCKED`

Judge hard stops from the actual diff (`--name-only` and content), not from the spec's flags. A file that merely *reads* the session to show a name is not an auth change. Unresolved review findings, new dependencies and matters of taste are **not** hard stops; you rule on them.

**REWORK** sends the job back for one more round, and is allowed only if no earlier `round-*/decision.md` starts with REWORK. Use it when a remaining blocking finding is real and must be fixed before shipping. List exactly what must be fixed under Rulings (as `fix-now`). The next round's reviewers will check it.

**APPROVE** when a reasonable senior engineer would ship it:
- **All reviews PASS and the check passed.** Approve; Rulings may be empty.
- **Findings remain at the round limit.** Rule on each one: `override` (wrong or not worth it, give a reason) or `defer` (real but non-urgent, add it to Follow-ups).
- **`check.md` is FAIL.** Approve only if the same failures already happen on `BASE`. To check, run `git -C WORKTREE worktree add --detach /tmp/factory-base-<id> BASE`, run the failing command there, then `git -C WORKTREE worktree remove --force /tmp/factory-base-<id>`. Otherwise use REWORK if it's still available, else ESCALATE with `Hard stop: blocked — checks fail`.

Don't edit code. Never run `prisma migrate`, `prisma db push`, `git merge`, `git reset`, `git rebase`, any push, or any `gh` command.
```

- [ ] **Step 10: Run the tests and confirm they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 11: Commit**

```bash
git add agents tests/test_contracts.py
git commit -m "Add the seven factory agents

- spec-writer, builder, four reviewers, approver; one output file each
- reviewers block only on confidence >= 80; approver escalates on hard stops only
- contract test pins names, models, first-line formats, forbidden commands

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The orchestrator skill

**Files:**
- Create: `skills/factory/SKILL.md`
- Modify: `tests/test_contracts.py` (add the SKILL.md checks)

**Interfaces:**
- Consumes: the `board.py` CLI (Task 1); the agent names and the prompt keys `JOB_DIR WORKTREE BASE ROUND PROJECT` (Task 2).
- Produces: the `/factory` skill with subcommands `<feature>`, `next`, `approve <id>`, `rework <id> <feedback>`, and no args.

- [ ] **Step 1: Add the failing SKILL.md tests to `tests/test_contracts.py`**

Add these methods to `ContractTest`:

```python
    def test_skill_references_every_agent_and_board_command(self):
        text = (ROOT / "skills" / "factory" / "SKILL.md").read_text()
        for name in AGENTS:
            self.assertIn(name, text)
        for cmd in ("board.py", " new ", " set ", " sync "):
            self.assertIn(cmd, text)
        fm = frontmatter(ROOT / "skills" / "factory" / "SKILL.md")
        self.assertEqual(fm.get("name"), "factory")

    def test_skill_only_merges_via_gh_squash(self):
        text = (ROOT / "skills" / "factory" / "SKILL.md").read_text()
        self.assertIn("gh pr merge", text)
        self.assertIn("--squash", text)
        for line in text.splitlines():
            for banned in ("--auto", "--admin", "--force", "git push origin main"):
                if banned in line:
                    self.assertIn("never", line.lower(), f"{banned!r} outside a 'never' line: {line}")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python3 -m unittest tests.test_contracts -v`
Expected: ERROR with `FileNotFoundError: ... SKILL.md`.

- [ ] **Step 3: Write `skills/factory/SKILL.md`**

````markdown
---
name: factory
description: Run the software factory. "/factory <feature>" builds a feature end to end (spec → build → check → 4 parallel reviews → approver → squash-merged PR). Also "/factory next", "/factory approve <id>", "/factory rework <id> <feedback>", and bare "/factory" for status.
---

# Software Factory: orchestrator

The session running this skill **is the orchestrator**. It spawns every agent, moves files between steps, and is the only caller of `board.py`. It never writes code, and it never reads diffs or reviews beyond their first lines, which keeps its context small. Agents get their context from files, never from this conversation.

This skill is a sanctioned exception to the global git rules: it may push its own `factory/*` branch, `gh pr create`, and `gh pr merge --squash` that PR once checks pass. Nothing else:
- never `git merge`, `git reset`, `git rebase`, or `--force`
- never push `main`/`master`
- never `--auto` or `--admin`
- never `prisma migrate` or `prisma db push`

## Setup (start of every invocation)

Run from the repo's **main checkout**, not a worktree:

```bash
test "$(git rev-parse --git-dir)" = "$(git rev-parse --git-common-dir)" || echo "NOT MAIN CHECKOUT"
REPO="$(git rev-parse --show-toplevel)"; F="$REPO/factory"
BOARD="python3 $HOME/.claude/skills/factory/board.py --dir $F"
```

If this isn't the main checkout, stop and say so. If `$F/project.md` is missing, do the **first-run setup** below. Otherwise go to the command.

### First-run setup (once per repo)

1. Run `mkdir -p "$F/jobs"`, then `ln -sfn "$HOME/.claude/skills/factory/dashboard.html" "$F/dashboard.html"`.
2. Add `factory/` and `.claude/worktrees/` to `$(git rev-parse --git-common-dir)/info/exclude` unless they're already there. This keeps your tracked `.gitignore` untouched.
3. If `$F/backlog.md` is missing, create it containing `# Backlog` plus one blank line.
4. Detect the project and write `$F/project.md`:
   - Read the repo `CLAUDE.md`/`AGENTS.md`, every `CLAUDE.md` in parent folders up to `$HOME`, and `.claude/rules/*.md` at each of those levels.
   - Then read `package.json` scripts and the lockfile, or `pyproject.toml`/`Makefile`/`go.mod`/`Cargo.toml`.
   - Prefer commands written explicitly in CLAUDE.md. Otherwise use package scripts (`test`, `lint`, `typecheck`, `build`). For TypeScript with no typecheck script, use `npx tsc --noEmit`. Write `none` when a command doesn't exist. Never invent a test runner.

```markdown
# Project profile (written by /factory; edit freely)
- Stack: <language / framework>
- Package manager: <npm|pnpm|yarn|pip|...>
- Install: <command>
- Test: <command|none>
- Typecheck: <command|none>
- Lint: <command|none>
- Build: <command|none>
- Has UI: <yes|no>
- Conventions to read: <absolute paths of every CLAUDE.md / AGENTS.md / rules file found>
- Notes: <anything an agent must know, e.g. "tests need .env">
```

5. Tell the user: `Dashboard: cd factory && python3 -m http.server 8765` → http://localhost:8765/dashboard.html

## Commands

For `approve` and `rework`, load the job from `$F/board.json`: `WT` is its `worktree`, `BASE` is its `base`, and `DEFAULT` is `BASE` with the `origin/` prefix removed. `N` is its `round`.

- **`/factory`** (no args): print each job's `id stage round reason pr` from `$F/board.json`, and the dashboard command.
- **`/factory next`**: take the first `- [ ] ` line in `$F/backlog.md`. If there is none, say the backlog is empty and stop. Run **New job** with that text. Once the id exists, change that line to `- [x] <text> → <id>`.
- **`/factory <feature text>`**: run **New job**.
- **`/factory approve <id>`**: the job must be `needs-human`. Write `$F/jobs/<id>/human-approval.md` containing `Approved by Trevor <ISO date>`. If the reason starts `schema`, remind the user to run `/trevskills-migrate` in the worktree first, and stop if they haven't confirmed. Then run **Merge**.
- **`/factory rework <id> <feedback>`**: append `## <ISO date>\n<feedback>` to `$F/jobs/<id>/rework.md`. Run `$BOARD set <id> stage=build reason= limit=<round+2>`. If the worktree is gone, recreate it from the branch with `git worktree add "$REPO/.claude/worktrees/factory-<id>" factory/<id>`. Resume the builder (see **Resuming the builder**) pointing it at `rework.md`, then continue at **Check gate**.

## New job

1. `ID=$($BOARD new "<title>")`. The title is the feature's first line, at most 60 characters. Write the full feature text to `$F/jobs/$ID/feature.md`.
2. **Base:** run `git fetch origin` (skip it if there is no remote). `DEFAULT=$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's#^origin/##')`, then `BASE=origin/$DEFAULT`. With no remote, use the current branch, but only if it's `main` or `master`; otherwise stop. Run `$BOARD set $ID base=$BASE`.
3. **Spec:** spawn `factory-spec-writer` and wait for it. Prompt:
   ```
   JOB_DIR=$F/jobs/$ID
   WORKTREE=none
   BASE=$BASE
   ROUND=0
   PROJECT=$F/project.md
   Write spec.md for this job.
   ```
   If `spec.md` is missing afterwards, spawn it once more. If it's still missing, set `stage=needs-human reason="spec writer produced nothing"` and stop.
4. **Worktree:**
   ```bash
   WT="$REPO/.claude/worktrees/factory-$ID"
   git worktree add "$WT" -b "factory/$ID" "$BASE"
   for e in "$REPO"/.env*; do [ -e "$e" ] && ln -sfn "$e" "$WT/$(basename "$e")"; done
   ```
   Then `$BOARD set $ID worktree=$WT stage=build`.
5. **Build:** spawn `factory-builder` and wait for it. Name it `builder-$ID` if the Agent tool accepts a name. Prompt: the 5 lines with `WORKTREE=$WT` and `ROUND=0`, plus `Implement spec.md. Write build.md.` Record the returned agent id/name with `$BOARD set $ID builder=<id>`. If `build.md` starts `STATUS: BLOCKED`, run `$BOARD set $ID stage=needs-human reason="blocked: <first reason line>"` and stop.
6. Continue at **Check gate**.

## Check gate

1. `N = round + 1` (round as stored on the board). Run `mkdir -p $F/jobs/$ID/round-$N`, then `$BOARD set $ID round=$N stage=check`.
2. In `$WT`, run each of Test / Typecheck / Lint / Build from `project.md` that isn't `none`. Also run `git -C "$WT" diff --name-only "$BASE"...HEAD | grep -E '(^|/)\.env'`; any output is a failure ("committed .env file").
3. Write `round-$N/check.md`: first line `CHECK: PASS` or `CHECK: FAIL`, then for each command its exit code and the last 40 lines of output in a fenced block.
4. If it says FAIL, resume the builder with `Checks failed: read JOB_DIR/round-N/check.md, fix, commit, update build.md.` Then re-run steps 2–3, overwriting `check.md`. Allow up to **3** fix attempts. If it still fails, skip the review and go to **Approve**; the approver rules on the failing check.
5. If it says PASS, go to **Review**.

## Review (WAIT FOR ALL)

1. Run `$BOARD set $ID stage=review`.
2. Spawn **all four reviewers in ONE message**, in the background: `factory-review-security`, `factory-review-ux`, `factory-review-ui`, `factory-review-code`. Each gets the 5 lines with `ROUND=$N` plus `Review this round. Write only your own review file.`
3. **WAIT FOR ALL.** Do nothing else until all four have completed. Then run `$BOARD sync $ID`.
   - `complete` must be `true`. If a file is missing, re-spawn only that reviewer, once.
   - If `invalid` is non-empty, delete those files and re-spawn those reviewers, once. If they come back invalid again, treat them as CHANGES.
   - **Never resume the builder mid-round.**
4. Route:
   - `verdict` is `PASS`: go to **Approve**.
   - `verdict` is `CHANGES` and `round < limit`: resume the builder with `Review round N has CHANGES: read every review-*.md in JOB_DIR/round-N/, fix blocking findings, commit, update build.md.` Run `$BOARD set $ID stage=build`, then go to **Check gate**.
   - `verdict` is `CHANGES` and `round >= limit`: go to **Approve**.

## Approve

1. Run `$BOARD set $ID stage=approve`. Spawn `factory-approver` and wait for it. Prompt: the 5 lines plus `Decide this job. Write decision.md.`
2. Copy `decision.md` into `round-$N/decision.md`; that's how the approver later sees whether REWORK has already been used. Run `$BOARD sync $ID` and read `decision`.
3. Append each `## Follow-ups` bullet in `decision.md` to `$F/backlog.md` as `- [ ] <item> (from $ID)`.
4. Route:
   - `APPROVE`: go to **Merge**.
   - `REWORK`: run `$BOARD set $ID limit=$((N+1)) stage=build`. Resume the builder with `The approver requested rework: read JOB_DIR/decision.md (Rulings marked fix-now), fix, commit, update build.md.` Then go to **Check gate**.
   - `ESCALATE` or `INVALID`: run `$BOARD set $ID stage=needs-human reason="<second line of decision.md>"`. Report and stop. For INVALID, use reason `approver output unreadable`.

## Merge (APPROVE, or /factory approve)

The steps below reuse the lessons from `/trevskills-commitpush`.

1. **Preconditions:**
   - `command -v gh && gh auth status` must succeed. If not, run `stage=needs-human reason="gh unavailable; branch factory/$ID is local"` and stop.
   - `git -C "$WT" status --porcelain` must be empty. If it isn't, resume the builder once with `Commit or remove uncommitted changes.`
2. Run `$BOARD set $ID stage=merging`. Then `git -C "$WT" push -u origin "factory/$ID"`. That pushes the factory branch only.
3. **PR.** Run `gh pr view "factory/$ID" --json number,url,state`:
   - `OPEN`: reuse it.
   - `MERGED`: run `stage=done` and stop.
   - `CLOSED`: run `stage=needs-human reason="PR was closed by someone"` and stop.
   - No PR: write the body to a temp file and pass it with `--body-file`. The body is the Merge summary bullets, then `Approved by the factory approver. Spec, reviews and decision: factory/jobs/$ID/`, then a line `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Create it with `gh pr create --base "$DEFAULT" --head "factory/$ID" --title "<Merge summary title>" --body-file "$BODY"`.

   Then `$BOARD set $ID pr=<url>`.
4. **Checks.** Run this in the **background**, because foreground `sleep` is blocked:
   ```bash
   for i in 1 2 3 4; do out=$(gh pr checks "factory/$ID" --watch --fail-fast --interval 15 2>&1); code=$?
     echo "$out" | grep -q "no checks reported" || break; sleep 20; done; echo "exit=$code"; echo "$out" | tail -40
   ```
   - `exit=0`: continue to step 5.
   - Still "no checks reported": the repo has no CI. Continue, and note "no CI ran" in the final report.
   - Any other failure: write the failing output to `$F/jobs/$ID/ci.md`, resume the builder with `CI failed: read JOB_DIR/ci.md, fix, commit.`, push again, and re-check. Allow at most **2** CI fix attempts. After that, run `stage=needs-human reason="CI failing"` and stop.
5. **Conflicts.** Run `gh pr view "factory/$ID" --json mergeable --jq .mergeable`. If it returns `CONFLICTING`, resolve it. This is the one sanctioned `git merge`, and it only ever goes into this job's own branch. Allow at most **2** attempts; after that, run `stage=needs-human reason="conflicts with $DEFAULT"` and stop. Each attempt:
   1. `git -C "$WT" fetch origin`, then `git -C "$WT" merge "origin/$DEFAULT" --no-edit`.
   2. If that merge itself conflicts, resume the builder with `The default branch was merged into your branch and has conflicts: resolve them, commit, update build.md.`
   3. Run `$BOARD set $ID limit=$((N+1))` and go to **Check gate**. That gives a fresh check and full review round, then the approver, then Merge again, reusing the open PR.
6. **Merge:** `gh pr merge "factory/$ID" --squash --subject "<title> (#<number>)" --body-file "$BODY"`. Never use `--auto`, `--admin` or `--delete-branch`.
7. **Clean up:**
   - Run `git worktree remove "$WT"`. If git refuses because of local changes, leave the worktree in place and mention it.
   - Run `git fetch origin`.
   - Run `$BOARD set $ID stage=done reason=`.

## Resuming the builder

Use SendMessage to the recorded `builder` (the name `builder-$ID`, or the stored agent id) with a message naming the exact file(s) to read. If SendMessage fails because the agent no longer exists (for example after a session restart):
1. Spawn a fresh `factory-builder` with the 5 lines plus `You are resuming this job. Read spec.md, build.md, and <the file(s) above>, then continue.`
2. Run `$BOARD set $ID builder=<new id>`.

The orchestrator never edits code or review files itself.

## Final report

End with the job id, the final stage, the PR URL, rounds used, any follow-ups added to the backlog, and, for needs-human, the exact reason and the next command (`/factory approve <id>` or `/factory rework <id> "<feedback>"`).
````

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS. `test_skill_only_merges_via_gh_squash` requires every line that mentions a banned flag to also say "never". If it fails, fix the SKILL.md line; don't weaken the test.

- [ ] **Step 5: Commit**

```bash
git add skills/factory/SKILL.md tests/test_contracts.py
git commit -m "Add /factory orchestrator skill

- setup, project detection, new/next/approve/rework commands
- check gate, wait-for-all review rounds, approver routing
- merge via PR + checks + gh squash, with commitpush's safety lessons

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Dashboard

**Files:**
- Create: `skills/factory/dashboard.html`
- Create: `tests/fixture/factory/board.json`, `tests/fixture/factory/jobs/003-rate-limiting/spec.md`, `tests/fixture/factory/jobs/003-rate-limiting/round-1/review-security.md`, `tests/fixture/factory/jobs/002-stripe-refunds/decision.md`, and the symlink `tests/fixture/factory/dashboard.html`

**Interfaces:**
- Consumes: the `board.json` job shape from Task 1 (`id title stage round reviews rounds[{check,security,ux,ui,code}] files pr reason updatedAt`), and files under `jobs/<id>/<relpath>`.
- Produces: `dashboard.html`, served from any `factory/` folder.

- [ ] **Step 1: Write the fixture**

`tests/fixture/factory/board.json`:

```json
{
  "jobs": [
    {"id": "001-dark-mode", "title": "Dark mode toggle", "branch": "factory/001-dark-mode", "stage": "done", "round": 1, "limit": 2,
     "reviews": {"security": "PASS", "ux": "PASS", "ui": "PASS", "code": "PASS"},
     "rounds": [{"check": "PASS", "security": "PASS", "ux": "PASS", "ui": "PASS", "code": "PASS"}],
     "files": [], "pr": "https://github.com/example/repo/pull/12", "reason": null, "updatedAt": "2026-10-12T10:00:00+00:00"},
    {"id": "002-stripe-refunds", "title": "Stripe refunds", "branch": "factory/002-stripe-refunds", "stage": "needs-human", "round": 2, "limit": 2,
     "reviews": {"security": "CHANGES", "ux": "PASS", "ui": "PASS", "code": "PASS"},
     "rounds": [{"check": "PASS", "security": "CHANGES", "ux": "PASS", "ui": "PASS", "code": "CHANGES"},
                {"check": "PASS", "security": "CHANGES", "ux": "PASS", "ui": "PASS", "code": "PASS"}],
     "files": ["decision.md", "missing.md"], "pr": null, "reason": "Hard stop: money — refund amount calculation changed", "updatedAt": "2026-10-12T11:00:00+00:00"},
    {"id": "003-rate-limiting", "title": "Rate limiting on login", "branch": "factory/003-rate-limiting", "stage": "review", "round": 2, "limit": 2,
     "reviews": {"security": "CHANGES", "ux": "PASS", "ui": "pending", "code": "PASS"},
     "rounds": [{"check": "PASS", "security": "CHANGES", "ux": "PASS", "ui": "INVALID", "code": "PASS"},
                {"check": "PASS", "security": "CHANGES", "ux": "PASS", "ui": "pending", "code": "PASS"}],
     "files": ["spec.md", "round-1/review-security.md"], "pr": null, "reason": null, "updatedAt": "2020-01-01T00:00:00+00:00"},
    {"id": "004-csv-export", "title": "CSV export for orders", "branch": "factory/004-csv-export", "stage": "spec", "round": 0, "limit": 2,
     "reviews": {"security": "pending", "ux": "pending", "ui": "pending", "code": "pending"},
     "rounds": [], "files": [], "pr": null, "reason": null, "updatedAt": "2099-01-01T00:00:00+00:00"}
  ]
}
```

`jobs/003-rate-limiting/spec.md`:

```markdown
# Rate limiting on login
UI surface: no
Hard stops: auth

## Acceptance criteria
1. 6th failed login within 60s returns 429 (verify: `rate-limit.test.ts`)

<script>alert("xss")</script>
```

`jobs/003-rate-limiting/round-1/review-security.md`:

```markdown
VERDICT: CHANGES
## Findings
1. [blocking] (confidence 90) src/app/api/login/route.ts:14 — limiter keyed on email only — key on IP + email
```

`jobs/002-stripe-refunds/decision.md`:

```markdown
ESCALATE
Hard stop: money — refund amount calculation changed in src/lib/refunds.ts
```

Then: `cd tests/fixture/factory && ln -s ../../../skills/factory/dashboard.html dashboard.html`

- [ ] **Step 2: Write `skills/factory/dashboard.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Software Factory</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1c1b19;--muted:#76736b;--line:#e3e0d8;--accent:#2457d6;
  --pass:#1e8449;--changes:#c4520f;--invalid:#7a3fd6;--human:#d32f2f;--pending:#c8c4ba}
@media (prefers-color-scheme:dark){:root{--bg:#131312;--card:#1d1c1a;--ink:#ecebe6;--muted:#9b978e;--line:#2f2d2a;--pending:#55524c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;align-items:baseline;gap:12px;padding:16px}
h1{font-size:16px;margin:0}
#status{color:var(--muted);font-size:12px}
main{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(210px,1fr);gap:12px;padding:0 16px 16px;overflow-x:auto}
.col h2{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 8px}
.col.human h2{color:var(--human)}
.card{display:block;width:100%;text-align:left;font:inherit;color:inherit;background:var(--card);border:1px solid var(--line);
  border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer}
.card:hover,.card:focus-visible{border-color:var(--accent);outline:none}
.card.human{border:2px solid var(--human);box-shadow:0 0 0 3px color-mix(in srgb,var(--human) 15%,transparent)}
.id{font:12px ui-monospace,monospace;color:var(--muted)}
.title{display:block;margin:2px 0 4px;font-weight:600}
.row{display:flex;gap:4px;align-items:center;margin-top:4px}
.row b{font:600 11px ui-monospace,monospace;color:var(--muted);width:22px}
.chip{font-size:11px;padding:1px 7px;border-radius:99px;color:#fff;background:var(--pending)}
.chip.PASS{background:var(--pass)}.chip.CHANGES,.chip.FAIL{background:var(--changes)}.chip.INVALID{background:var(--invalid)}
.chip.pending{background:transparent;color:var(--muted);border:1px dashed var(--pending)}
.meta{display:block;font-size:12px;color:var(--muted);margin-top:6px}
.reason{display:block;font-size:12px;color:var(--human);margin-top:6px}
.stale{color:var(--changes)}
.empty{color:var(--muted);font-size:12px}
dialog{width:min(900px,94vw);max-height:88dvh;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);padding:0}
dialog::backdrop{background:#0007}
.tabs{display:flex;flex-wrap:wrap;gap:4px;padding:10px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--card)}
.tabs button{font:12px ui-monospace,monospace;border:1px solid var(--line);background:none;color:var(--ink);border-radius:6px;padding:4px 8px;cursor:pointer}
.tabs button[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:#fff}
.tabs .close{margin-left:auto}
article{padding:4px 20px 20px;overflow-wrap:anywhere}
article pre{overflow-x:auto;background:var(--bg);padding:8px;border-radius:6px;white-space:pre-wrap}
article a{color:var(--accent)}
@media (max-width:640px){main{grid-auto-flow:row;grid-auto-columns:auto}}
</style>
</head>
<body>
<header><h1>Software Factory</h1><span id="status" aria-live="polite">loading…</span></header>
<main id="board"></main>
<dialog id="viewer" aria-label="Job files"><div class="tabs" id="tabs"></div><article id="doc"></article></dialog>
<script>
const STAGES = ["spec", "build", "check", "review", "approve", "merging", "needs-human", "done"];
const REVIEWERS = [["security", "sec"], ["ux", "ux"], ["ui", "ui"], ["code", "code"]];
const STALE_MS = 30 * 60 * 1000; // ponytail: fixed threshold; make it a URL param if long builds trip it
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
// Agents write the markdown, so any raw HTML in it is shown as text, never run.
if (window.marked) marked.use({renderer: {html: h => esc(typeof h === "object" ? h.text : h)}});
const $ = id => document.getElementById(id);
let jobs = [], lastText = "";

const chip = (verdict, label) => `<span class="chip ${esc(verdict)}" title="${esc(label)}: ${esc(verdict)}">${esc(label)}</span>`;
const roundRow = (r, i) => `<span class="row"><b>R${i + 1}</b>${chip(r.check || "pending", "check")}${REVIEWERS.map(([k, l]) => chip(r[k] || "pending", l)).join("")}</span>`;

function card(job) {
  const human = job.stage === "needs-human";
  const stale = !["done", "needs-human"].includes(job.stage) && Date.now() - Date.parse(job.updatedAt) > STALE_MS;
  return `<button class="card${human ? " human" : ""}" data-id="${esc(job.id)}">
    <span class="id">${esc(job.id)}</span><span class="title">${esc(job.title)}</span>
    ${(job.rounds || []).map(roundRow).join("")}
    ${human && job.reason ? `<span class="reason">${esc(job.reason)}</span>` : ""}
    <span class="meta">${job.pr ? "PR ready · " : ""}${stale ? `<span class="stale">stale since ${esc(new Date(job.updatedAt).toLocaleString())}</span>` : esc(new Date(job.updatedAt).toLocaleTimeString())}</span>
  </button>`;
}

function render() {
  const extra = [...new Set(jobs.map(j => j.stage).filter(s => !STAGES.includes(s)))];
  $("board").innerHTML = [...STAGES, ...extra].map(stage => {
    const inCol = jobs.filter(j => j.stage === stage);
    return `<section class="col${stage === "needs-human" ? " human" : ""}"><h2>${esc(stage)} · ${inCol.length}</h2>
      ${inCol.map(card).join("") || '<p class="empty">—</p>'}</section>`;
  }).join("");
}

async function poll() {
  try {
    const res = await fetch("board.json", {cache: "no-store"});
    if (!res.ok) { $("status").textContent = "No board.json yet. Run /factory in this repo."; jobs = []; render(); return; }
    const text = await res.text();
    if (text !== lastText) { jobs = JSON.parse(text).jobs || []; lastText = text; render(); }
    $("status").textContent = `${jobs.length} job${jobs.length === 1 ? "" : "s"} · updated ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    $("status").textContent = `Can't read board.json (${e.message}). Showing the last good state.`;
  }
}

async function show(job, file) {
  [...$("tabs").querySelectorAll("button[data-file]")].forEach(b => b.setAttribute("aria-pressed", b.dataset.file === file));
  const url = `jobs/${encodeURIComponent(job.id)}/${file.split("/").map(encodeURIComponent).join("/")}`;
  try {
    const res = await fetch(url, {cache: "no-store"});
    if (!res.ok) throw new Error(`${res.status}`);
    const md = await res.text();
    $("doc").innerHTML = window.marked ? marked.parse(md) : `<pre>${esc(md)}</pre>`;
  } catch (e) {
    $("doc").innerHTML = `<p class="empty">Couldn't load ${esc(file)} (${esc(e.message)}).</p>`;
  }
}

function open(job) {
  $("viewer").dataset.job = job.id;
  const files = job.files || [];
  const pr = job.pr ? `<a href="${esc(job.pr)}" target="_blank" rel="noopener">PR ↗</a>` : "";
  $("tabs").innerHTML = files.map(f => `<button data-file="${esc(f)}" aria-pressed="false">${esc(f)}</button>`).join("")
    + pr + '<button class="close" aria-label="Close">✕</button>';
  $("doc").innerHTML = files.length ? "" : '<p class="empty">No files yet.</p>';
  $("viewer").showModal();
  const first = files.includes("decision.md") ? "decision.md" : files.includes("spec.md") ? "spec.md" : files[0];
  if (first) show(job, first);
}

$("board").addEventListener("click", e => {
  const el = e.target.closest(".card");
  const job = el && jobs.find(j => j.id === el.dataset.id);
  if (job) open(job);
});
$("tabs").addEventListener("click", e => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.classList.contains("close")) return $("viewer").close();
  const job = jobs.find(j => j.id === $("viewer").dataset.job);
  if (job) show(job, b.dataset.file);
});
$("viewer").addEventListener("click", e => { if (e.target === $("viewer")) $("viewer").close(); });

poll();
setInterval(poll, 2000);
</script>
</body>
</html>
```

- [ ] **Step 3: Verify in a browser against the fixture**

Run in the background: `cd tests/fixture/factory && python3 -m http.server 8799`
Using the Playwright MCP, navigate to `http://localhost:8799/dashboard.html` and check:
1. There are 8 columns. `003-rate-limiting` sits in **review** with two chip rows. Its R1 `ui` chip is purple (INVALID), its R2 `ui` chip is dashed (pending), and it shows "stale since …".
2. `002-stripe-refunds` sits in **needs-human** with a red border and the "Hard stop: money…" reason.
3. Clicking 003 opens the dialog on `spec.md`. The `<script>alert("xss")</script>` line shows as **text** and no alert fires. The `round-1/review-security.md` tab renders.
4. Clicking 002 and opening the `missing.md` tab shows "Couldn't load missing.md (404)", with no console errors.
5. `004-csv-export` (zero rounds) renders without chip rows.
6. Resize to 390px: the columns stack vertically with no horizontal page scroll.
7. Run `mv board.json board.json.bak`; within 2 seconds the status reads "No board.json yet…". Run `mv board.json.bak board.json`; the board returns.
8. Block `cdnjs.cloudflare.com` (Playwright route abort) and reload. Files render as `<pre>` plain text.

Take a screenshot (`dashboard-fixture.png` in the scratchpad) for the final report. Stop the server.

- [ ] **Step 4: Commit**

```bash
git add skills/factory/dashboard.html tests/fixture
git commit -m "Add factory dashboard

- one static file polling board.json; jobs move across stage columns
- per-round reviewer chips, needs-human highlighted, stale jobs flagged
- click a card to read its markdown (raw HTML escaped, plain-text fallback)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: install.sh and README

**Files:**
- Create: `install.sh`, `README.md`
- Test: `tests/test_install.py`

**Interfaces:**
- Consumes: the `agents/*.md` and `skills/factory/` layout.
- Produces: the symlinks `$CLAUDE_HOME/skills/factory` → `<repo>/skills/factory` and `$CLAUDE_HOME/agents/<name>.md` → `<repo>/agents/<name>.md`. `CLAUDE_HOME` defaults to `~/.claude`.

- [ ] **Step 1: Write the failing test**

`tests/test_install.py`:

```python
import os, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallTest(unittest.TestCase):
    def run_install(self, home):
        return subprocess.run(["bash", str(ROOT / "install.sh")], capture_output=True, text=True,
                              env={**os.environ, "CLAUDE_HOME": str(home)})

    def test_install_links_skill_and_agents_and_is_rerunnable(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            for _ in range(2):
                self.assertEqual(self.run_install(home).returncode, 0)
            self.assertEqual((home / "skills" / "factory").resolve(), ROOT / "skills" / "factory")
            for agent in (ROOT / "agents").glob("*.md"):
                self.assertEqual((home / "agents" / agent.name).resolve(), agent)

    def test_install_refuses_to_clobber_a_real_file(self):
        with tempfile.TemporaryDirectory() as t:
            home = Path(t)
            (home / "agents").mkdir(parents=True)
            real = home / "agents" / "factory-builder.md"
            real.write_text("mine")
            result = self.run_install(home)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing", result.stderr)
            self.assertEqual(real.read_text(), "mine")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python3 -m unittest tests.test_install -v`
Expected: FAIL, because `bash: .../install.sh: No such file or directory` gives a non-zero return code.

- [ ] **Step 3: Write `install.sh`**

```bash
#!/usr/bin/env bash
# Links the factory into ~/.claude so /factory works in every repo. Safe to re-run; edits here go live instantly.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${CLAUDE_HOME:-$HOME/.claude}"
mkdir -p "$dest/skills" "$dest/agents"

link() {
  if [ -e "$2" ] && [ ! -L "$2" ]; then echo "refusing to replace real file: $2" >&2; exit 1; fi
  ln -sfn "$1" "$2"
  echo "linked $2"
}

# Check everything first so a refusal leaves nothing half-installed.
for f in "$here"/agents/*.md; do
  t="$dest/agents/$(basename "$f")"
  if [ -e "$t" ] && [ ! -L "$t" ]; then echo "refusing to replace real file: $t" >&2; exit 1; fi
done
link "$here/skills/factory" "$dest/skills/factory"
for f in "$here"/agents/*.md; do link "$f" "$dest/agents/$(basename "$f")"; done
echo "Done. In any repo: /factory <feature>"
```

Then: `chmod +x install.sh`

- [ ] **Step 4: Run all tests and confirm they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all tests PASS.

- [ ] **Step 5: Write `README.md`**

````markdown
# Software Factory

`/factory <feature>` turns a feature request into a squash-merged PR. A spec writer, a builder, four parallel reviewers and an approver hand off through markdown files, and a one-file dashboard shows each job's progress.

```
feature → spec-writer → builder → check gate → security · ux · ui · code → approver
                           ▲          (tests/lint/build)   (wait for all 4)    │
                           └──────── CHANGES, round < 2 ◄──────────────────────┤
                                                    APPROVE → PR → CI → squash-merge
                                                    REWORK  → one more round (once)
                                                    ESCALATE → needs-human (hard stops only)
```

**Escalates only for:** DB schema/migrations, money, auth, secrets, a blocked builder, or infrastructure (no `gh`, merge conflicts, CI failing after 2 fixes). The Opus approver decides everything else.

## Install (once)

```bash
brew install gh && gh auth login   # needed to open and merge PRs
./install.sh                       # links skills/factory and agents/* into ~/.claude
```

## Use (in any repo, from its main checkout)

| Command | Does |
| --- | --- |
| `/factory <feature>` | runs a new job |
| `/factory next` | runs the first `- [ ]` item in `factory/backlog.md` |
| `/factory approve <id>` | merges a needs-human job |
| `/factory rework <id> "<feedback>"` | sends a job back to the builder with 2 more rounds |
| `/factory` | shows the board |

Dashboard: `cd factory && python3 -m http.server 8765`, then open http://localhost:8765/dashboard.html

The first run writes `factory/project.md` (stack, test/lint/build commands, convention files). Edit it if detection got something wrong. To run several jobs at once, open several Claude sessions; each job gets its own worktree.

## Change the factory

- Agents: `agents/factory-*.md`. A repo can override one with its own `.claude/agents/<same name>.md`.
- The loop: `skills/factory/SKILL.md`
- Tests: `python3 -m unittest discover -s tests -v`
````

- [ ] **Step 6: Commit**

```bash
git add install.sh README.md tests/test_install.py
git commit -m "Add installer and README

- install.sh symlinks skill + agents into ~/.claude, rerunnable, never clobbers
- README: loop, escalation policy, commands, dashboard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Install and run a smoke test on a throwaway repo

**Files:** none in this repo; everything happens in the scratchpad.

**Interfaces:**
- Consumes: everything above.
- Produces: evidence that `/factory` is discovered and that one job runs from spec to approve.

- [ ] **Step 1: Install for real and confirm Claude Code sees it**

```bash
./install.sh
ls -l ~/.claude/skills/factory ~/.claude/agents/
```

Expected: 8 symlinks. Then in a **new** Claude Code session, run `/agents` and confirm the seven `factory-*` agents are listed, and type `/factory` and confirm the skill loads. If symlinked agents or skills are not discovered, stop and report it; don't switch to copying files without asking.

- [ ] **Step 2: Smoke run without a remote**

Create a scratch repo (not under `~/Developer`):

```bash
S=/private/tmp/claude-501/factory-smoke && mkdir -p $S && cd $S && git init -q -b main
printf '{"name":"smoke","scripts":{"test":"node --test"}}\n' > package.json
printf 'export const add = (a, b) => a + b;\n' > math.mjs
printf 'import test from "node:test"; import assert from "node:assert"; import {add} from "./math.mjs";\ntest("add", () => assert.equal(add(1,2),3));\n' > math.test.mjs
git add -A && git commit -qm "init"
```

In a Claude session in `$S`, run `/factory add a multiply(a, b) function with tests`. Expected:
- `factory/project.md` is created, with Test `npm test`.
- The job moves spec → build → check → review → approve, and the dashboard shows it live.
- Because there's no remote, the job stops at **Merge** step 1 with `needs-human reason="gh unavailable…"` or a push failure. That's expected for this smoke test.
- Its round-1 files all exist, and `decision.md` starts `APPROVE`.

- [ ] **Step 3: Report**

Report what happened at each stage, the dashboard screenshot, and any step in SKILL.md that the orchestrator had to improvise. Fix any wording that caused improvisation, re-run the tests, and commit:

```bash
git add -A && git commit -m "Tighten orchestrator wording from smoke run

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Then hand off with `/trevskills-commitpush` (Path B, branch `feat/factory-v1`). That needs a GitHub remote: create the repo first, with `gh repo create software-factory --private --source . --push=false`, **only if Trevor says so**.
````
