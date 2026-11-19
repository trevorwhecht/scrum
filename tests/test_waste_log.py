"""Job 1175: the machine-wide waste.log of wasted-work catches (board.log_waste, sharing board._append_log with
log_process) and the digest's waste.md (board.write_waste, called by cmd_digest_start)."""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
os.environ["SCRUM_MUTE"] = "1"
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))
import board  # noqa: E402


class WasteLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "sub" / "waste.log"
        env = mock.patch.dict(os.environ, {"SCRUM_PULSE": str(self.log.with_name("pulse.log"))})
        env.start()
        self.addCleanup(env.stop)

    def test_waste_path_beside_pulse(self):
        self.assertEqual(board.waste_path(), self.log)
        reg = Path(self.tmp.name) / "reg" / "projects.json"
        with mock.patch.dict(os.environ, {"SCRUM_PULSE": "", "SCRUM_REGISTRY": str(reg)}):
            self.assertEqual(board.waste_path(), reg.with_name("waste.log"))
            self.assertEqual(board.waste_path().parent, board.processes_path().parent)

    def test_log_waste_appends_one_line(self):
        self.assertEqual(board.WASTE_KINDS, ("two-sessions", "same-tests", "leftover", "cpu-hog"))
        with mock.patch.object(board.time, "time", return_value=1_700_000_000.7):
            board.log_waste("two-sessions", "app", ["1-a", "2-b"], [11, 12], 4.5, owner="1-a")
            board.log_waste("cpu-hog", project=None, jobs=[], pids=[], cpu_min=12, name="x", pid=5, pct=180)
        self.assertEqual(self.log.read_text(),
                         '{"t": 1700000000, "kind": "two-sessions", "project": "app", "jobs": ["1-a", "2-b"], '
                         '"pids": [11, 12], "cpu_min": 4.5, "owner": "1-a"}\n'
                         '{"t": 1700000000, "kind": "cpu-hog", "project": null, "jobs": [], "pids": [], "cpu_min": 12, '
                         '"name": "x", "pid": 5, "pct": 180}\n')

    def test_log_waste_unknown_kind(self):
        err = io.StringIO()
        with redirect_stderr(err):
            board.log_waste("nope", "app", [], [], 1)
        self.assertEqual(err.getvalue(), "waste: unknown kind 'nope'\n")
        self.assertFalse(self.log.exists())
        self.assertFalse(self.log.parent.exists())

    def test_log_waste_never_raises(self):
        self.log.parent.parent.mkdir(parents=True, exist_ok=True)
        self.log.parent.write_text("a file, not a folder\n")
        err = io.StringIO()
        with redirect_stderr(err):
            board.log_waste("leftover", "app", ["1-a"], [1], 1)
        self.assertTrue(err.getvalue().startswith("waste: "), err.getvalue())
        self.assertEqual(len(err.getvalue().splitlines()), 1)
        self.log.parent.unlink()
        self.log.parent.mkdir()
        self.log.write_text('{"t": 1}\n')
        err = io.StringIO()
        with redirect_stderr(err), mock.patch.object(board.os, "replace", side_effect=OSError("boom")):
            board.log_waste("leftover", "app", ["1-a"], [1], 1)
        self.assertEqual(err.getvalue(), "waste: boom\n")

    NOW = 1_700_000_000
    DAY = 86400

    def seed(self, *lines):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text("".join(lines))

    NEW = f'{{"t": {NOW}, "kind": "leftover", "project": "app", "jobs": [], "pids": [], "cpu_min": 1}}\n'

    def test_log_waste_rotates_old_lines(self):
        old = self.NOW - board.PULSE_KEEP_SECS - 2 * self.DAY
        self.seed(f'{{"t": {old}, "kind": "A"}}\n', f'{{"t": {self.NOW - 100}, "kind": "B"}}\n')
        with mock.patch.object(board.time, "time", return_value=self.NOW):
            board.log_waste("leftover", "app", [], [], 1)
        self.assertEqual(self.log.read_text(), f'{{"t": {self.NOW - 100}, "kind": "B"}}\n' + self.NEW)
        self.assertFalse(self.log.with_name("waste.log.tmp").exists())

    def test_log_waste_keeps_file_within_slack(self):
        slack = self.NOW - board.PULSE_KEEP_SECS - self.DAY // 2
        self.seed(f'{{"t": {slack}, "kind": "A"}}\n')
        with mock.patch.object(board.time, "time", return_value=self.NOW):
            board.log_waste("leftover", "app", [], [], 1)
        self.assertEqual(self.log.read_text(), f'{{"t": {slack}, "kind": "A"}}\n' + self.NEW)

    def test_log_waste_rotates_malformed_first_line(self):
        for first in ("not json\n", '{"kind": "A"}\n', '{"t": "x"}\n'):
            self.seed(first, f'{{"t": {self.NOW - 5}, "kind": "B"}}\n', "{bad\n", '{"kind": "X"}\n')
            with mock.patch.object(board.time, "time", return_value=self.NOW):
                board.log_waste("leftover", "app", [], [], 1)
            self.assertEqual(self.log.read_text(), f'{{"t": {self.NOW - 5}, "kind": "B"}}\n' + self.NEW, first)
            self.assertFalse(self.log.with_name("waste.log.tmp").exists())

    def test_log_waste_skips_real_log_under_unittest(self):
        home = Path(self.tmp.name) / "home"
        env = {k: v for k, v in os.environ.items() if k not in ("SCRUM_PULSE", "SCRUM_REGISTRY")}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(Path, "home", return_value=home):
            self.assertEqual(board.waste_path(), home / ".claude" / "trevskills-scrum" / "waste.log")
            board.log_waste("leftover", "app", ["1-a"], [1], 1)
        self.assertFalse(home.exists())

    def test_one_rotation_copy_in_board_py(self):
        src = (SKILL / "board.py").read_text()
        self.assertEqual(src.count("PULSE_KEEP_SECS - 86400"), 1)
        self.assertIn("_append_log(", src[src.index("def log_process("):src.index("def pulse_auto(")])


S = 1_700_000_000  # 2023-11-14T22:13:20Z


class WasteDigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "app"
        self.root = self.repo / "scrum"
        (self.root / "digests").mkdir(parents=True)
        self.log = Path(self.tmp.name) / "machine" / "waste.log"
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

    def waste(self, digest_id="002"):
        (self.root / "digests" / digest_id).mkdir(exist_ok=True)
        board.write_waste(self.root, digest_id)
        return (self.root / "digests" / digest_id / "waste.md").read_text()

    def test_writes_counts_and_catches_since_last_digest(self):
        self.digest("001", S)
        self.write_log(
            {"t": S - 60, "kind": "two-sessions", "project": "app", "jobs": ["0-old"], "pids": [1], "cpu_min": 1},
            {"t": S + 120, "kind": "leftover", "project": "lib", "jobs": ["7-x"], "pids": [21, 22, 23], "cpu_min": 10.25},
            {"t": S, "kind": "two-sessions", "project": "app", "jobs": ["1-a", "2-b"], "pids": [11, 12], "cpu_min": 4.5},
            {"t": S + 180, "kind": "cpu-hog", "project": None, "jobs": [], "pids": [], "cpu_min": 12, "pct": 180},
            {"t": S + 60, "kind": "two-sessions", "project": "app", "jobs": ["3-c"], "pids": [13], "cpu_min": 2})
        self.assertEqual(self.waste(), (
            "# Waste: digest 002\n"
            "\n"
            "Since: 2023-11-14T22:13+00:00\n"
            "\n"
            "## Counts\n"
            "- two-sessions: 2\n"
            "- same-tests: 0\n"
            "- leftover: 1\n"
            "- cpu-hog: 1\n"
            "\n"
            "## Catches\n"
            '- 2023-11-14T22:13+00:00 two-sessions project=app jobs=["1-a", "2-b"] pids=[11, 12] cpu_min=4.5\n'
            '- 2023-11-14T22:14+00:00 two-sessions project=app jobs=["3-c"] pids=[13] cpu_min=2\n'
            '- 2023-11-14T22:15+00:00 leftover project=lib jobs=["7-x"] pids=[21, 22, 23] cpu_min=10.25\n'
            "- 2023-11-14T22:16+00:00 cpu-hog project=null jobs=[] pids=[] cpu_min=12 pct=180\n"))

    def test_catches_keep_file_order_on_ties(self):
        self.write_log({"t": S, "kind": "leftover", "project": "b", "jobs": [], "pids": [], "cpu_min": 1},
                       {"t": S, "kind": "leftover", "project": "a", "jobs": [], "pids": [], "cpu_min": 1})
        text = self.waste("001")
        self.assertLess(text.index("project=b"), text.index("project=a"))

    def test_empty_missing_and_malformed_log(self):
        self.digest("001", S)
        self.assertEqual(self.waste(), "No catches since the last digest\n")  # no waste.log
        self.write_log({"t": S - 1, "kind": "leftover", "project": "app", "jobs": [], "pids": [], "cpu_min": 1})
        self.assertEqual(self.waste(), "No catches since the last digest\n")  # before the cutoff
        self.write_log("not json", "[1, 2]", '"text"',
                       {"kind": "leftover", "project": "app"},
                       {"t": str(S + 5), "kind": "leftover"},
                       {"t": True, "kind": "leftover"},
                       {"t": S + 5, "kind": "nope", "project": "app"},
                       {"t": S + 5, "project": "app"})
        self.assertEqual(self.waste(), "No catches since the last digest\n")  # every line malformed

    def test_since_the_start(self):
        self.write_log({"t": 5, "kind": "same-tests", "project": "app", "jobs": ["1-a"], "pids": [], "cpu_min": 1},
                       {"t": S, "kind": "same-tests", "project": "app", "jobs": ["2-b"], "pids": [], "cpu_min": 1})
        text = self.waste("001")
        self.assertIn("\nSince: the start\n", text)
        self.assertIn("- same-tests: 2\n", text)

    def test_failed_digest_keeps_cutoff(self):
        self.digest("001", S)
        self.digest("002", S + 100, error=True)
        self.write_log({"t": S + 50, "kind": "leftover", "project": "app", "jobs": ["1-a"], "pids": [], "cpu_min": 1})
        text = self.waste("003")
        self.assertIn("\nSince: 2023-11-14T22:13+00:00\n", text)
        self.assertIn("- leftover: 1\n", text)

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

    def test_digest_start_writes_waste_md(self):
        self.write_log({"t": S, "kind": "cpu-hog", "project": None, "jobs": [], "pids": [9], "cpu_min": 3})
        job_id, out, _ = self.start()
        self.assertEqual(out, {"id": "001", "jobs": [job_id], "windows": []})
        text = (self.root / "digests" / "001" / "waste.md").read_text()
        self.assertIn("- cpu-hog: 1\n", text)
        self.assertIn("- 2023-11-14T22:13+00:00 cpu-hog project=null jobs=[] pids=[9] cpu_min=3\n", text)

    def test_waste_failure_never_stops_digest_start(self):
        with mock.patch.object(board, "write_waste", side_effect=OSError("boom")):
            job_id, out, err = self.start()
        self.assertEqual(out, {"id": "001", "jobs": [job_id], "windows": []})
        self.assertIn("digest-start: waste: boom\n", err)
        d = self.root / "digests" / "001"
        self.assertTrue((d / "pulse.md").exists())
        self.assertTrue((d / "processes.md").exists())
        self.assertFalse((d / "waste.md").exists())


if __name__ == "__main__":
    unittest.main()
