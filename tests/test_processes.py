"""Job 976: the process registry (board.PROCESSES), the machine-wide processes.log (board.log_process) and the
digest's processes.md (board.write_processes), plus a coverage check that fails when serve.py or board.py gains a
watchdog process or a scrum-folder state file the registry does not name."""
import ast, io, json, os, sys, tempfile, time, unittest
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

    def test_log_process_never_raises(self):
        self.log.parent.parent.mkdir(parents=True, exist_ok=True)
        self.log.parent.write_text("a file, not a folder\n")
        err = io.StringIO()
        with redirect_stderr(err):
            board.log_process("Disk reclaim", "freed")
        self.assertTrue(err.getvalue().startswith("processes: "), err.getvalue())
        self.assertEqual(len(err.getvalue().splitlines()), 1)

    def test_log_process_skips_real_log_under_unittest(self):
        home = Path(self.tmp.name) / "home"
        env = {k: v for k, v in os.environ.items() if k not in ("SCRUM_PULSE", "SCRUM_REGISTRY")}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(Path, "home", return_value=home):
            self.assertEqual(board.processes_path(), home / ".claude" / "trevskills-scrum" / "processes.log")
            board.log_process("Disk reclaim", "freed", removed=1)
        self.assertFalse(home.exists())


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
            "Disk reclaim", "Idle cleanup", "E2E lock reaps", "Digest retry", "Weekly digest", "Cloud jobs",
            "Usage windows", "Pulse", "Run all and triage", "Roadmap and BigBoy", "Backlog ranking", "Held items",
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
