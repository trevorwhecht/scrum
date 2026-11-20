"""Job 976: the process registry (board.PROCESSES), the machine-wide processes.log (board.log_process) and the
digest's processes.md (board.write_processes), plus a coverage check that fails when serve.py or board.py gains a
watchdog process or a scrum-folder state file the registry does not name."""
import ast, io, json, os, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
os.environ["SCRUM_MUTE"] = "1"
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))
import board  # noqa: E402


class ProcessesLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "sub" / "processes.log"
        env = mock.patch.dict(os.environ, {"SCRUM_PULSE": str(self.log.with_name("pulse.log"))})
        env.start()
        self.addCleanup(env.stop)

    def test_processes_path_beside_pulse(self):
        self.assertEqual(board.processes_path(), self.log)

    def test_log_process_appends_one_line(self):
        with mock.patch.object(board.time, "time", return_value=1_700_000_000.7):
            board.log_process("Disk reclaim", "freed", repo="/r/app", removed=2)
            board.log_process("Weekly digest", "started", digest="004", at=Path("/x"))
        self.assertEqual(self.log.read_text(),
                         '{"t": 1700000000, "process": "Disk reclaim", "result": "freed", "repo": "/r/app", "removed": 2}\n'
                         '{"t": 1700000000, "process": "Weekly digest", "result": "started", "digest": "004", "at": "/x"}\n')

    def test_log_process_resolves_relative_repo(self):
        real = Path(self.tmp.name).resolve() / "real"
        real.mkdir()
        link = Path(self.tmp.name) / "link"
        link.symlink_to(real)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(link)
        board.log_process("Disk reclaim", "freed", repo=".")
        board.log_process("Disk reclaim", "freed", repo=str(link))
        board.log_process("Disk reclaim", "freed")
        lines = [json.loads(l) for l in self.log.read_text().splitlines()]
        self.assertEqual(lines[0]["repo"], str(real))
        self.assertEqual(lines[1]["repo"], str(real))
        self.assertNotIn("repo", lines[2])

    def test_log_process_never_raises(self):
        self.log.parent.parent.mkdir(parents=True, exist_ok=True)
        self.log.parent.write_text("a file, not a folder\n")
        err = io.StringIO()
        with redirect_stderr(err):
            board.log_process("Disk reclaim", "freed")
        self.assertTrue(err.getvalue().startswith("processes: "), err.getvalue())
        self.assertEqual(len(err.getvalue().splitlines()), 1)
        self.log.parent.unlink()
        self.log.parent.mkdir()
        self.log.write_text('{"t": 1}\n')
        err = io.StringIO()
        with redirect_stderr(err), mock.patch.object(board.os, "replace", side_effect=OSError("boom")):
            board.log_process("Disk reclaim", "freed")
        self.assertEqual(err.getvalue(), "processes: boom\n")

    NOW = 1_700_000_000
    DAY = 86400

    def seed(self, *lines):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text("".join(lines))

    def test_log_process_rotates_old_lines(self):
        old = self.NOW - board.PULSE_KEEP_SECS - 2 * self.DAY
        self.seed(f'{{"t": {old}, "process": "A"}}\n', f'{{"t": {self.NOW - 100}, "process": "B"}}\n')
        with mock.patch.object(board.time, "time", return_value=self.NOW):
            board.log_process("C", "ok")
        self.assertEqual(self.log.read_text(),
                         f'{{"t": {self.NOW - 100}, "process": "B"}}\n'
                         f'{{"t": {self.NOW}, "process": "C", "result": "ok"}}\n')
        self.assertFalse(self.log.with_name("processes.log.tmp").exists())

    def test_log_process_keeps_file_within_slack(self):
        slack = self.NOW - board.PULSE_KEEP_SECS - self.DAY // 2
        self.seed(f'{{"t": {slack}, "process": "A"}}\n')
        with mock.patch.object(board.time, "time", return_value=self.NOW):
            board.log_process("C", "ok")
        self.assertEqual(self.log.read_text(),
                         f'{{"t": {slack}, "process": "A"}}\n{{"t": {self.NOW}, "process": "C", "result": "ok"}}\n')

    def test_log_process_rotates_malformed_first_line(self):
        for first in ("not json\n", '{"process": "A"}\n'):
            self.seed(first, f'{{"t": {self.NOW - 5}, "process": "B"}}\n', "{bad\n", '{"process": "X"}\n')
            with mock.patch.object(board.time, "time", return_value=self.NOW):
                board.log_process("C", "ok")
            self.assertEqual(self.log.read_text(),
                             f'{{"t": {self.NOW - 5}, "process": "B"}}\n'
                             f'{{"t": {self.NOW}, "process": "C", "result": "ok"}}\n')
            self.assertFalse(self.log.with_name("processes.log.tmp").exists())

    def test_log_process_skips_real_log_under_unittest(self):
        home = Path(self.tmp.name) / "home"
        env = {k: v for k, v in os.environ.items() if k not in ("SCRUM_PULSE", "SCRUM_REGISTRY")}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(Path, "home", return_value=home):
            self.assertEqual(board.processes_path(), home / ".claude" / "trevskills-scrum" / "processes.log")
            board.log_process("Disk reclaim", "freed", removed=1)
        self.assertFalse(home.exists())


S = 1_700_000_000  # 2023-11-14T22:13:20Z
SESSION_CODE = ("Code: spawn, auto_continue_tick, play_queue_tick, auto_resume, auto_play, idle_claim, start_ready, "
                "wake_waiting, sweep_parents, main_ff_tick, terminal_batch_tick\n")


class ProcessesDigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "app"
        self.root = self.repo / "scrum"
        (self.root / "digests").mkdir(parents=True)
        self.log = Path(self.tmp.name) / "machine" / "processes.log"
        self.log.parent.mkdir()
        env = mock.patch.dict(os.environ, {"SCRUM_PULSE": str(self.log.with_name("pulse.log")),
                                           "SCRUM_REGISTRY": str(self.log.with_name("projects.json"))})
        env.start()
        self.addCleanup(env.stop)

    def digest(self, name, at, error=False):
        d = self.root / "digests" / name
        d.mkdir()
        (d / "jobs.txt").write_text("")
        os.utime(d / "jobs.txt", (at, at))
        if error:
            (d / "error.md").write_text("failed\n")

    def write_log(self, *lines):
        self.log.write_text("".join((l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines))

    def processes(self, digest_id="002"):
        (self.root / "digests" / digest_id).mkdir(exist_ok=True)
        board.write_processes(self.root, digest_id)
        return (self.root / "digests" / digest_id / "processes.md").read_text()

    def section(self, text, name):
        start = text.index(f"## {name}\n")
        end = text.find("\n## ", start + 1)
        return text[start:] if end < 0 else text[start:end + 1]

    def test_writes_sections_since_last_digest(self):
        self.digest("001", S)
        repo = str(self.repo)
        self.write_log(
            {"t": S - 60, "process": "Session starts", "result": "start", "repo": repo, "job": "1-old"},  # before
            {"t": S, "process": "Session starts", "result": "start", "repo": repo, "job": "2-a", "manual": False},
            {"t": S + 60, "process": "Session starts", "result": "resume", "repo": repo, "job": "3-b", "manual": True},
            {"t": S + 120, "process": "Session starts", "result": "start", "repo": repo, "job": "4-c", "manual": False},
            {"t": S + 120, "process": "E2E lock reaps", "result": "freed", "slot": "e2e.lock.0", "pid": 42, "dead": True})
        text = self.processes()
        self.assertTrue(text.startswith("# Processes: digest 002\n\nSince: 2023-11-14T22:13+00:00\n\n## Session starts\n"), text)
        self.assertEqual(self.section(text, "Session starts"),
                         "## Session starts\n" + SESSION_CODE +
                         "Runs: 3 (start 2, resume 1)\n"
                         f"- 2023-11-14T22:15+00:00 start repo={repo} job=4-c manual=false\n"
                         f"- 2023-11-14T22:14+00:00 resume repo={repo} job=3-b manual=true\n"
                         f"- 2023-11-14T22:13+00:00 start repo={repo} job=2-a manual=false\n"
                         "Files: none\n\n")
        self.assertEqual(self.section(text, "E2E lock reaps"),
                         "## E2E lock reaps\nCode: e2e_lock_reap\nRuns: 1 (freed 1)\n"
                         "- 2023-11-14T22:15+00:00 freed slot=e2e.lock.0 pid=42 dead=true\nFiles: none\n\n")
        self.assertEqual(self.section(text, "Held items"),
                         "## Held items\nCode: none\nRuns: none logged since the last digest\nFiles:\n- held.md: missing\n\n")
        self.assertEqual(text.count("\n## "), 24)
        names = [l[3:] for l in text.splitlines() if l.startswith("## ")]
        self.assertEqual(names[0], "Session starts")
        self.assertEqual(names[-1], "Manual checks")

    def test_relative_repo_run_lands_in_its_project(self):
        other = Path(self.tmp.name) / "lib"
        (other / "scrum" / "digests" / "002").mkdir(parents=True)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.repo)
        board.log_process("Disk reclaim", "freed", repo=".", removed=7)
        os.chdir(old)  # the digest runs elsewhere: a stored "." would resolve against this cwd
        mine = self.section(self.processes(), "Disk reclaim")
        board.write_processes(other / "scrum", "002")
        theirs = self.section((other / "scrum" / "digests" / "002" / "processes.md").read_text(), "Disk reclaim")
        self.assertIn("Runs: 1 (freed 1)", mine)
        self.assertIn("Runs: none logged", theirs)

    def test_newest_ten_lines(self):
        self.write_log(*({"t": S + i, "process": "Disk reclaim", "result": "freed", "removed": i} for i in range(12)))
        sec = self.section(self.processes(), "Disk reclaim")
        self.assertIn("Runs: 12 (freed 12)\n", sec)
        self.assertEqual(sec.count("\n- "), 10)
        self.assertIn("freed removed=11\n", sec)
        self.assertNotIn("removed=1\n", sec)

    def test_other_repo_lines_left_out(self):
        other = Path(self.tmp.name) / "lib"
        other.mkdir()
        link = Path(self.tmp.name) / "app-link"
        link.symlink_to(self.repo)
        self.write_log(
            {"t": S, "process": "Disk reclaim", "result": "freed", "repo": str(other), "removed": 9},
            {"t": S + 1, "process": "Disk reclaim", "result": "freed", "repo": str(link), "removed": 2},
            {"t": S + 2, "process": "Disk reclaim", "result": "freed", "removed": 3})
        sec = self.section(self.processes(), "Disk reclaim")
        self.assertIn("Runs: 2 (freed 2)\n", sec)
        self.assertNotIn("removed=9", sec)
        self.assertIn("removed=2", sec)
        self.assertIn("removed=3", sec)

    def test_false_alarms_and_time(self):
        line = lambda t, result, head, secs: {"t": S + t, "process": "Full E2E on main", "result": result,
                                              "head": head, "secs": secs}
        self.write_log(line(0, "fail", "aaa", 600), line(10, "fail", "bbb", 1200), line(20, "pass", "aaa", 300),
                       line(30, "loaded", "ccc", None), line(40, "fail", "ccc", 30))
        sec = self.section(self.processes(), "Full E2E on main")
        self.assertIn("Runs: 5 (fail 3, loaded 1, pass 1) · false alarms: 1 · time: 36 min total, longest 20 min\n", sec)
        self.write_log(line(0, "pass", "aaa", None), line(10, "fail", "aaa", None))  # the pass came first: no alarm
        sec = self.section(self.processes(), "Full E2E on main")
        self.assertIn("Runs: 2 (fail 1, pass 1)\n", sec)

    def test_files_lines(self):
        self.digest("001", S)
        for rel, at in (("e2e-full.json", S + 10), ("e2e-full.log", S - 10), ("ui-sweep/a/review.md", S + 5),
                        ("ui-sweep/b/review.md", S - 5), ("ui-sweep/c/review.md", S + 1)):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x\n")
            os.utime(p, (at, at))
        for i in range(12):
            p = self.root / "triage" / f"{i:02d}.md"
            p.parent.mkdir(exist_ok=True)
            p.write_text("x\n")
            os.utime(p, (S + 1, S + 1))
        text = self.processes()
        self.assertIn("Files:\n- e2e-full.json: changed since the last digest\n- e2e-full.log: unchanged\n",
                      self.section(text, "Full E2E on main"))
        self.assertIn("Files:\n- ui-sweep.json: missing\n"
                      "- ui-sweep/*/review.md: ui-sweep/a/review.md, ui-sweep/c/review.md\n",
                      self.section(text, "UI sweep"))
        self.assertIn("Files:\n- triage/*: " + ", ".join(f"triage/{i:02d}.md" for i in range(10)) + " (+2 more)\n",
                      self.section(text, "Run all and triage"))
        self.assertIn("- jobs/*/bigboy-review.md: none changed since the last digest\n",
                      self.section(text, "Roadmap and BigBoy"))

    def test_malformed_and_missing_log(self):
        text = self.processes()  # no processes.log at all
        self.assertEqual(text.count("Runs: none logged since the last digest\n"), 24)
        self.write_log("junk", "[1, 2]", {"t": "x", "process": "Disk reclaim", "result": "freed"},
                       {"t": True, "process": "Disk reclaim", "result": "freed"},
                       {"t": S, "process": 5, "result": "freed"}, {"t": S, "process": "Disk reclaim", "result": None},
                       {"t": S, "process": "Disk reclaim"})
        text = self.processes()
        self.assertEqual(text.count("Runs: none logged since the last digest\n"), 24)

    def test_since_the_start(self):
        self.write_log({"t": 5, "process": "Disk reclaim", "result": "freed", "removed": 1})
        text = self.processes("001")
        self.assertIn("\nSince: the start\n", text)
        self.assertIn("Runs: 1 (freed 1)\n", self.section(text, "Disk reclaim"))

    def test_failed_digest_keeps_cutoff(self):
        self.digest("001", S)
        self.digest("002", S + 100, error=True)
        self.write_log({"t": S + 50, "process": "Disk reclaim", "result": "freed", "removed": 1})
        text = self.processes("003")
        self.assertIn("\nSince: 2023-11-14T22:13+00:00\n", text)
        self.assertIn("Runs: 1 (freed 1)\n", self.section(text, "Disk reclaim"))

    def start(self):
        guard = mock.patch.object(board, "merge_refusal", return_value=None)  # PR-less fixture jobs may go done
        guard.start()
        self.addCleanup(guard.stop)
        job_id = board.cmd_new(self.root, "done 0")
        board.cmd_set(self.root, job_id, ["stage=done"], internal=True)
        err = io.StringIO()
        with redirect_stderr(err):
            out = board.cmd_digest_start(self.root)
        return job_id, out, err.getvalue()

    def test_digest_start_writes_processes_md(self):
        self.write_log({"t": S, "process": "Weekly digest", "result": "started", "digest": "004"})
        job_id, out, _ = self.start()
        self.assertEqual(out, {"id": "001", "jobs": [job_id], "windows": []})
        text = (self.root / "digests" / "001" / "processes.md").read_text()
        self.assertIn("## Weekly digest\nCode: weekly_tick\nRuns: 1 (started 1)\n", text)

    def test_processes_failure_never_stops_digest_start(self):
        with mock.patch.object(board, "write_processes", side_effect=OSError("boom")):
            job_id, out, err = self.start()
        self.assertEqual(out, {"id": "001", "jobs": [job_id], "windows": []})
        self.assertIn("digest-start: processes: boom\n", err)
        self.assertTrue((self.root / "digests" / "001" / "pulse.md").exists())
        self.assertTrue((self.root / "digests" / "001" / "jobs.txt").exists())
        self.assertFalse((self.root / "digests" / "001" / "processes.md").exists())


IGNORED_CALLS = {"live_sessions", "machine_ok", "projects", "ram_room", "session_alive_fn", "board_busy",
                 "launched_since", "once", "run_exits", "running"}  # watchdog_tick helpers, no process of their own
EXEMPT_FILES = {"jobs", "board.json", "project.md", "digests", "backlog.md", ".board.lock", "backlog-specs",
                "backlog-sources.done", "runs", ".claude", ".mcp.json", "CLAUDE.md", "CLAUDE.local.md",
                "backlog-spool.jsonl"}  # backlog-spool.jsonl: serve.py's async backlog-add queue, backlog.md plumbing


def _registry(board_tree):
    """PROCESSES as written in board_tree's source (so a test's edited source is read, not the imported module)."""
    for node in board_tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PROCESSES" for t in node.targets):
            return ast.literal_eval(node.value)
    return ()


def _top_defs(tree):
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _scrum_side(node):
    """True when node is the name `root`, `Path(root)` or `<expr> / "scrum"`."""
    if isinstance(node, ast.Name):
        return node.id == "root"
    if isinstance(node, ast.Call):
        return (isinstance(node.func, ast.Name) and node.func.id == "Path" and len(node.args) == 1
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "root")
    return (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant) and node.right.value == "scrum")


def uncovered(serve_src, board_src) -> list[str]:
    """One message per process or state file that board.PROCESSES does not cover (see the job 976 spec)."""
    serve, brd = ast.parse(serve_src), ast.parse(board_src)
    procs = _registry(brd)
    names = {p[0] for p in procs}
    codes = {c for p in procs for c in p[1]}
    files = {f for p in procs for f in p[2]}
    firsts = {f.split("/", 1)[0] for f in files}
    serve_defs, board_defs = _top_defs(serve), _top_defs(brd)
    out = []
    for name in serve_defs:
        if name.endswith("_tick") and name != "watchdog_tick" and name not in codes:
            out.append(f"serve.py {name}: a watchdog tick no entry runs; add it to board.PROCESSES")
    tick = serve_defs.get("watchdog_tick")
    for node in ast.walk(tick) if tick else []:
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = (f.id if isinstance(f, ast.Name) and f.id in serve_defs
                else f.attr if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "board"
                else None)
        if name and name not in codes and name not in IGNORED_CALLS:
            out.append(f"watchdog_tick calls {name}, which no entry names; add it to board.PROCESSES")
    for label, tree in (("serve.py", serve), ("board.py", brd)):
        for node in ast.walk(tree):
            if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant)
                    and isinstance(node.right.value, str) and _scrum_side(node.left)):
                lit = node.right.value.removesuffix(".tmp")
                if lit not in files and lit not in firsts and lit not in EXEMPT_FILES:
                    out.append(f'{label}: scrum-folder file "{lit}" is in no entry; add it to board.PROCESSES')
            if isinstance(node, ast.Call) and (
                    (isinstance(node.func, ast.Name) and node.func.id == "log_process")
                    or (isinstance(node.func, ast.Attribute) and node.func.attr == "log_process"
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "board")):
                arg = node.args[0] if node.args else None
                if not (isinstance(arg, ast.Constant) and arg.value in names):
                    shown = ast.unparse(arg) if arg is not None else "nothing"
                    out.append(f"{label}: log_process({shown}, ...) names no entry; add it to board.PROCESSES")
    for code in sorted(codes):
        if code not in serve_defs and code not in board_defs:
            out.append(f"board.PROCESSES names {code}, which is no top-level def in serve.py or board.py; "
                       f"fix it in board.PROCESSES")
    return out


class ProcessCoverageTest(unittest.TestCase):
    serve_src = (SKILL / "serve.py").read_text()
    board_src = (SKILL / "board.py").read_text()

    def test_registry_covers_feature_list(self):
        procs = board.PROCESSES
        self.assertIsInstance(procs, tuple)
        for entry in procs:
            self.assertEqual(len(entry), 3)
            self.assertIsInstance(entry[0], str)
            self.assertIsInstance(entry[1], tuple)
            self.assertIsInstance(entry[2], tuple)
        files = {f for p in procs for f in p[2]}
        codes = {c for p in procs for c in p[1]}
        for f in ("e2e-full.json", "e2e-full.log", "ui-sweep/*/review.md", "prod-errors.json", "triage/*",
                  "roadmap.md", "jobs/*/bigboy-review.md", "jev.log", "held.md", "manual-checks.md"):
            self.assertIn(f, files)
        for c in ("actions_alert", "cloud_tick", "main_ff_tick", "auto_continue_tick", "play_queue_tick",
                  "auto_resume", "reclaim_disk", "idle_cleanup", "docker_tick", "e2e_lock_reap", "digest_retry_tick",
                  "weekly_tick"):
            self.assertIn(c, codes)
        self.assertEqual([p[0] for p in procs], [
            "Session starts", "Stalls and exits", "Full E2E on main", "UI sweep", "Prod error sweep", "Actions alerts",
            "Disk reclaim", "Idle cleanup", "Leftover sessions", "Two sessions", "Same tests", "CPU hogs", "E2E lock reaps", "Agent links", "Digest retry",
            "Weekly digest", "Cloud jobs", "Usage windows", "Pulse", "Run all and triage", "Roadmap and BigBoy", "Backlog ranking", "Held items",
            "Manual checks"])

    def test_head_is_covered(self):
        self.assertEqual(uncovered(self.serve_src, self.board_src), [])

    def test_new_tick_fails(self):
        out = uncovered(self.serve_src + "\n\ndef foo_tick():\n    pass\n", self.board_src)
        self.assertEqual(len(out), 1)
        self.assertIn("foo_tick", out[0])
        self.assertIn("add it to board.PROCESSES", out[0])

    def test_new_watchdog_call_fails(self):
        src = self.serve_src.replace("def watchdog_tick():\n", "def watchdog_tick():\n    new_thing()\n", 1)
        self.assertNotEqual(src, self.serve_src)
        out = uncovered(src + "\n\ndef new_thing(): pass\n", self.board_src)
        self.assertEqual(len(out), 1)
        self.assertIn("new_thing", out[0])

    def test_new_state_file_fails(self):
        out = uncovered(self.serve_src, self.board_src + '\n\ndef f(root):\n    return root / "foo.json"\n')
        self.assertEqual(len(out), 1)
        self.assertIn('"foo.json"', out[0])
        self.assertIn("add it to board.PROCESSES", out[0])

    def test_unknown_log_name_fails(self):
        out = uncovered(self.serve_src + '\n\ndef g():\n    board.log_process("Nope", "pass")\n', self.board_src)
        self.assertEqual(len(out), 1)
        self.assertIn("'Nope'", out[0])
        out = uncovered(self.serve_src + '\n\ndef g(name):\n    board.log_process(name, "pass")\n', self.board_src)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
