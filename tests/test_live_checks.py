"""Job 1496: `## Live checks` bullets. board.py live-record writes jobs/<id>/live-checks.json at Mark done, serve.py
live_check_tick runs one due check per watchdog tick, a failure files one debug backlog item (a chained one texts
Trevor), board_with_activity gives each job its live-check line, and live/pulse_gaps.py is the first user."""
import builtins, importlib.util, json, os, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # never the real registry
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))  # never the real pulse.log
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_IDLE_CLEANUP"] = "0"
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_VM_PRESSURE"] = "1"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"

import board  # noqa: E402

ID = "1500-fix-the-pulse"
BULLET = "- `python3 live/check.py` | from +6h | by +7d | the pulse never stops for 3 minutes"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class Base(unittest.TestCase):
    """A git repo with a tracked live/check.py, a package.json, and scrum/ holding one done job."""

    def setUp(self):
        self.base = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.repo = self.base / "app"
        self.root = self.repo / "scrum"
        (self.repo / "live").mkdir(parents=True)
        (self.repo / "live" / "check.py").write_text("print('ok')\n")
        (self.repo / "package.json").write_text(json.dumps({"scripts": {
            "check:e2e": "node scripts/read-e2e.js", "db:fix": "prisma migrate deploy", "shot": "playwright test",
            "build": "next build"}}))
        git(self.repo, "init", "-q")
        git(self.repo, "add", "live/check.py", "package.json")
        (self.repo / "live" / "untracked.py").write_text("print('x')\n")
        self.jobs = self.root / "jobs"
        self.job_dir(ID, spec=f"# Spec\n\n## Live checks\n{BULLET}\n")

    def job_dir(self, job_id, spec=None, decision=None, feature="Fix it\n", stage="done", reason=None, pr=42,
                live=None):
        d = self.jobs / job_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "feature.md").write_text(feature)
        if spec is not None:
            (d / "spec.md").write_text(spec)
        if decision is not None:
            (d / "decision.md").write_text(decision)
        b = board.read_board(self.root) if (self.root / "board.json").exists() else {"jobs": []}
        job = {"id": job_id, "title": "t", "stage": stage, "pr": pr}
        if reason:
            job["reason"] = reason
        if live:
            job["liveCheck"] = live
        b["jobs"] = [j for j in b["jobs"] if j["id"] != job_id] + [job]
        (self.root / "board.json").write_text(json.dumps(b))
        return d

    def job(self, job_id=ID):
        return next(j for j in board.read_board(self.root)["jobs"] if j["id"] == job_id)

    def checks(self, job_id=ID):
        return json.loads((self.jobs / job_id / "live-checks.json").read_text())


class LiveRecordTest(Base):
    def test_pending_written(self):
        with mock.patch.object(board.time, "time", return_value=1_000_000):
            self.assertEqual(board.cmd_live_record(self.root, ID), 1)
        self.assertEqual(self.checks(), [{
            "command": "python3 live/check.py", "from": 1_000_000 + 6 * 3600, "by": 1_000_000 + 7 * 86400,
            "proves": "the pulse never stops for 3 minutes", "state": "pending", "runs": [], "done_at": 1_000_000}])
        self.assertEqual(self.job()["liveCheck"], "waiting")

    def test_cli_subcommand(self):
        with mock.patch("sys.stdout"):
            board.main(["--dir", str(self.root), "live-record", ID])
        self.assertEqual(self.checks()[0]["state"], "pending")

    def test_decision_wins_over_spec(self):
        self.job_dir(ID, decision="APPROVE\n\n## Live checks\n"
                     "- `python3 live/check.py --day` | from merge | by +1d | decision's own check\n\n## Merge summary\n")
        with mock.patch.object(board.time, "time", return_value=500):
            board.cmd_live_record(self.root, ID)
        self.assertEqual([(c["command"], c["from"], c["by"], c["proves"]) for c in self.checks()],
                         [("python3 live/check.py --day", 500, 500 + 86400, "decision's own check")])

    def test_none_and_missing_section_write_nothing(self):
        self.job_dir(ID, decision="APPROVE\n\n## Live checks\n- none\n")
        self.assertEqual(board.cmd_live_record(self.root, ID), 0)
        self.assertFalse((self.jobs / ID / "live-checks.json").exists())
        self.assertNotIn("liveCheck", self.job())
        self.job_dir("1501-other", spec="# Spec\n\n## Scope\nIn: x\n")
        self.assertEqual(board.cmd_live_record(self.root, "1501-other"), 0)
        self.assertFalse((self.jobs / "1501-other" / "live-checks.json").exists())
        self.assertNotIn("liveCheck", self.job("1501-other"))

    def test_rerun_keeps_existing_file(self):
        board.cmd_live_record(self.root, ID)
        path = self.jobs / ID / "live-checks.json"
        kept = [{**self.checks()[0], "runs": [{"at": 1, "exit": 75, "tail": []}], "filed": "Live check failed: x"}]
        path.write_text(json.dumps(kept))
        self.assertEqual(board.cmd_live_record(self.root, ID), 0)
        self.assertEqual(self.checks(), kept)

    def test_not_live_and_not_done_are_not_recorded(self):
        self.job_dir(ID, spec=f"# Spec\n\n## Live checks\n{BULLET}\n", reason="merged, not live: verify failed")
        self.assertEqual(board.cmd_live_record(self.root, ID), 0)
        self.assertFalse((self.jobs / ID / "live-checks.json").exists())
        self.assertNotIn("liveCheck", self.job())
        self.job_dir(ID, spec=f"# Spec\n\n## Live checks\n{BULLET}\n", stage="merging")
        self.assertEqual(board.cmd_live_record(self.root, ID), 0)
        self.assertFalse((self.jobs / ID / "live-checks.json").exists())

    def test_refused_bullet_stored_refused(self):
        self.job_dir(ID, spec="# Spec\n\n## Live checks\n- `rm -rf /` | from merge | by +1d | nothing\n")
        board.cmd_live_record(self.root, ID)
        entry = self.checks()[0]
        self.assertEqual(entry["state"], "refused")
        self.assertTrue(entry["reason"])
        self.assertEqual(self.job()["liveCheck"], "refused")


class LiveCommandTest(Base):
    def refused(self, command):
        return board.live_command_refusal(self.repo, command)

    def test_metacharacters_refused(self):
        for cmd in ("python3 live/check.py; rm x", "python3 live/check.py | sh", "python3 live/check.py $(id)",
                    "npm run check:e2e -- a;b", "npm run check:e2e | sh"):
            self.assertIsNotNone(self.refused(cmd), cmd)

    def test_paths_refused(self):
        outside = self.base / "outside.py"
        outside.write_text("print(1)\n")
        for cmd in (f"python3 {self.repo}/live/check.py", "python3 ../outside.py", "python3 live/../live/check.py",
                    "python3 live/untracked.py", "python3 -c print", "python3"):
            self.assertIsNotNone(self.refused(cmd), cmd)

    def test_scripts_refused(self):
        for cmd in ("npm run nope", "npm run db:fix", "npm run shot", "npm run build", "bash live/check.py",
                    "npm test"):
            self.assertIsNotNone(self.refused(cmd), cmd)

    def test_allowed_shapes(self):
        self.assertIsNone(self.refused("npm run check:e2e"))
        self.assertIsNone(self.refused("npm run check:e2e -- --runs=3"))
        self.assertIsNone(self.refused("python3 live/check.py"))
        self.assertIsNone(self.refused("python3 live/check.py --hours=24"))


class TickBase(Base):
    NOW = 2_000_000

    def setUp(self):
        super().setUp()
        import serve
        self.serve = serve
        self.ran, self.sent = [], []
        self.hold = mock.patch.object(board, "heavy_hold", return_value=None)
        self.heavy = self.hold.start()
        self.addCleanup(self.hold.stop)
        self.exit = 0
        self.out = "line one\nline two\n"
        # The alert sender lives in HOME; alert-to.txt sits beside pulse.log.
        home = self.base / "home"
        script = home / ".claude" / "scripts" / "imsg-send.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        (self.base / "alert-to.txt").write_text("alert-handle\n")
        p = mock.patch.dict(os.environ, HOME=str(home), SCRUM_PULSE=str(self.base / "pulse.log"))
        p.start()
        self.addCleanup(p.stop)

    def record(self, job_id=ID, at=NOW - 7 * 3600):
        with mock.patch.object(board.time, "time", return_value=at):
            board.cmd_live_record(self.root, job_id)

    def run_fn(self, repo, argv, since):
        self.ran.append((repo, argv, since))
        return self.exit, self.out

    def seen(self, *extra):
        return [("app", self.repo, self.root, board.read_board(self.root)["jobs"], set()), *extra]

    def tick(self, now=NOW, seen=None):
        return self.serve.live_check_tick(seen or self.seen(), now=now, run=self.run_fn, send=self.sent.append)


class LiveCheckTickTest(TickBase):
    def test_pass(self):
        self.record()
        self.assertEqual(self.tick(), ID)
        self.assertEqual(self.ran, [(self.repo, ["python3", "live/check.py"], self.NOW - 7 * 3600)])
        entry = self.checks()[0]
        self.assertEqual(entry["state"], "passed")
        self.assertEqual(entry["runs"], [{"at": self.NOW, "exit": 0, "tail": ["line one", "line two"]}])
        self.assertEqual(self.job()["liveCheck"], "passed")

    def test_not_yet_stays_pending_and_waits_an_hour(self):
        self.record()
        self.exit = 75
        self.tick()
        self.assertEqual(self.checks()[0]["state"], "pending")
        self.assertEqual(self.job()["liveCheck"], "waiting")
        self.assertIsNone(self.tick(now=self.NOW + 3599))
        self.assertEqual(len(self.ran), 1)
        self.assertEqual(self.tick(now=self.NOW + 3600), ID)
        self.assertEqual(len(self.ran), 2)

    def test_fail(self):
        self.record()
        self.exit = 2
        self.tick()
        self.assertEqual(self.checks()[0]["state"], "failed")
        self.assertEqual(self.job()["liveCheck"], "failed")

    def test_deadline_gives_never_happened(self):
        self.record()
        self.exit = 75
        self.tick()
        self.assertIsNone(self.tick(now=self.NOW - 7 * 3600 + 7 * 86400 + 1))
        entry = self.checks()[0]
        self.assertEqual((entry["state"], entry["reason"]), ("failed", "never happened"))
        self.assertEqual(len(self.ran), 1)
        self.assertEqual(self.job()["liveCheck"], "failed")
        self.tick(now=self.NOW + 30 * 86400)
        self.assertEqual(len(self.ran), 1)

    def test_one_check_per_tick_across_projects(self):
        self.record()
        repo2 = self.base / "app2"
        root2 = repo2 / "scrum"
        shutil.copytree(self.repo, repo2)
        (root2 / "jobs" / ID / "live-checks.json").unlink()
        b = board.read_board(root2)
        for j in b["jobs"]:
            j.pop("liveCheck", None)
        (root2 / "board.json").write_text(json.dumps(b))
        with mock.patch.object(board.time, "time", return_value=self.NOW - 7 * 3600):
            board.cmd_live_record(root2, ID)
        seen = self.seen(("app2", repo2, root2, board.read_board(root2)["jobs"], set()))
        self.exit = 75
        self.tick(seen=seen)
        self.assertEqual(len(self.ran), 1)
        seen = self.seen(("app2", repo2, root2, board.read_board(root2)["jobs"], set()))
        self.tick(now=self.NOW + 1, seen=seen)
        self.assertEqual([r[0] for r in self.ran], [self.repo, repo2])

    def test_heavy_hold_runs_nothing(self):
        self.record()
        self.heavy.return_value = "CPU load 300% of 8 cores (> 150%)"
        self.assertIsNone(self.tick())
        self.assertEqual(self.ran, [])
        self.assertEqual(self.checks()[0]["state"], "pending")

    def test_from_in_future_does_not_run(self):
        self.record(at=self.NOW - 3600)  # from is +6h
        self.assertIsNone(self.tick())
        self.assertEqual(self.ran, [])
        self.heavy.assert_not_called()

    def test_idle_reads_no_job_folder(self):
        self.record()
        b = board.read_board(self.root)
        b["jobs"][0].pop("liveCheck")
        (self.root / "board.json").write_text(json.dumps(b))
        seen = self.seen()
        paths = []
        real_open, real_read = builtins.open, Path.read_text

        def spy_open(file, *a, **kw):
            paths.append(str(file))
            return real_open(file, *a, **kw)

        def spy_read(self_, *a, **kw):
            paths.append(str(self_))
            return real_read(self_, *a, **kw)
        with mock.patch("builtins.open", spy_open), mock.patch.object(Path, "read_text", spy_read):
            self.assertIsNone(self.serve.live_check_tick(seen, now=self.NOW, run=self.run_fn))
        self.assertEqual([p for p in paths if "/jobs/" in p], [])
        self.heavy.assert_not_called()
        self.assertEqual(self.ran, [])

    def test_hung_command_is_killed(self):
        """A real python3 script that sleeps 120 s, with a grandchild, is killed as a group at the timeout."""
        pidfile = self.base / "child.pid"
        (self.repo / "live" / "hang.py").write_text(
            "import subprocess, sys, time\n"
            f"p = subprocess.Popen(['sleep', '120'])\nopen({str(pidfile)!r}, 'w').write(str(p.pid))\n"
            "print('started', flush=True)\ntime.sleep(120)\n")
        start = time.monotonic()
        with mock.patch.object(self.serve, "LIVE_CHECK_TIMEOUT_S", 3):
            code, out = self.serve.live_check_run(self.repo, ["python3", "live/hang.py"], 123)
        self.assertLess(time.monotonic() - start, 65)
        self.assertEqual(code, self.serve.LIVE_CHECK_TIMED_OUT)
        self.assertIn("timed out after 3 s", out)
        child = int(pidfile.read_text())
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail("the grandchild sleep outlived the timeout")

    def test_run_passes_since_and_exit(self):
        (self.repo / "live" / "env.py").write_text(
            "import os, sys\nprint(os.environ['LIVE_CHECK_SINCE'])\nsys.exit(75)\n")
        code, out = self.serve.live_check_run(self.repo, ["python3", "live/env.py"], 4321)
        self.assertEqual((code, out.strip()), (75, "4321"))

    def test_timeout_marks_failed_with_reason(self):
        self.record()
        self.exit, self.out = self.serve.LIVE_CHECK_TIMED_OUT, "started\ntimed out after 60 s\n"
        self.tick()
        entry = self.checks()[0]
        self.assertEqual((entry["state"], entry["reason"]), ("failed", "timed out after 60 s"))


class LiveCheckFailTest(TickBase):
    def open_items(self):
        return [i["text"] for i in board.read_backlog(self.root)[1] if not i["done"]]

    def test_one_item_for_one_failure(self):
        self.record()
        self.exit = 1
        self.tick()
        self.assertEqual(self.open_items(), [
            f"Live check failed: {ID} (PR #42): the pulse never stops for 3 minutes; command python3 live/check.py; "
            "exit 1; last output: line one / line two; Lane: debug"])
        self.assertEqual(self.checks()[0]["filed"], self.open_items()[0])
        self.tick(now=self.NOW + 7200)
        self.assertEqual(len(self.open_items()), 1)
        self.assertEqual(self.sent, [])

    def test_failed_filing_retried_next_tick(self):
        """Round 1 finding 4: a failure whose filing raised is filed on the next tick, once."""
        self.record()
        self.exit = 1
        with mock.patch.object(board, "cmd_backlog_add", side_effect=OSError("disk full")), \
                mock.patch("sys.stderr"):
            self.tick()
        self.assertEqual(self.open_items(), [])
        self.assertEqual(self.job()["liveCheck"], "failed")
        self.tick(now=self.NOW + 60)
        self.assertEqual(len(self.open_items()), 1)
        self.assertEqual(self.checks()[0]["filed"], self.open_items()[0])
        self.assertNotIn("liveCheckUnfiled", self.job())
        self.tick(now=self.NOW + 120)
        self.assertEqual(len(self.open_items()), 1)
        self.assertEqual(len(self.ran), 1)

    def test_long_output_is_cut_to_item_max(self):
        self.record()
        self.exit = 1
        self.out = "\n".join("x" * 300 for _ in range(20)) + "\n"
        self.tick()
        item = self.open_items()[0]
        self.assertLessEqual(len(item), board.ITEM_MAX)
        self.assertTrue(item.endswith("; Lane: debug"), item[-60:])
        self.assertIn("… more in live-checks.json", item)

    def test_chained_failure_texts_once_and_files_nothing(self):
        self.job_dir(ID, spec=f"# Spec\n\n## Live checks\n{BULLET}\n",
                     feature="Live check failed: 1400-old (PR #7): it came back\n")
        self.record()
        self.exit = 1
        self.tick()
        self.assertEqual(self.open_items(), [])
        self.assertEqual(len(self.sent), 1)
        argv = self.sent[0]
        self.assertEqual(argv[1], "alert-handle")
        self.assertEqual(argv[2], f"Live check failed again after a fix: app {ID}: the pulse never stops for 3 minutes")
        self.assertEqual(self.checks()[0]["texted"], self.NOW)
        self.tick(now=self.NOW + 7200)
        self.assertEqual(len(self.sent), 1)


class LiveCheckInfoTest(TickBase):
    def info(self):
        import serve
        with mock.patch.object(serve, "job_costs", return_value={}):
            data = serve.board_with_activity(self.root, "app")
        return next(j for j in data["jobs"] if j["id"] == ID).get("liveCheckInfo")

    def test_states(self):
        self.assertIsNone(self.info())
        self.record()
        self.assertEqual(self.info(), {"state": "waiting", "until": self.NOW - 7 * 3600 + 7 * 86400})
        self.tick()
        self.assertEqual(self.info(), {"state": "passed", "at": self.NOW})

    def test_failed_and_refused(self):
        self.record()
        self.exit = 1
        self.tick()
        self.assertEqual(self.info(), {"state": "failed", "item": f"Live check failed: {ID}"})
        self.job_dir(ID, spec="# Spec\n\n## Live checks\n- `npm run nope` | from merge | by +1d | x\n")
        (self.jobs / ID / "live-checks.json").unlink()
        board.cmd_live_record(self.root, ID)
        self.assertEqual(self.info(), {"state": "refused", "reason": "nope is not a package.json script"})


class PulseGapsTest(unittest.TestCase):
    SINCE = 1_000_000

    def setUp(self):
        spec = importlib.util.spec_from_file_location("pulse_gaps", SKILL / "live" / "pulse_gaps.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.pulse = self.dir / "pulse.log"
        p = mock.patch.dict(os.environ, SCRUM_PULSE=str(self.pulse), LIVE_CHECK_SINCE=str(self.SINCE))
        p.start()
        self.addCleanup(p.stop)

    def write(self, times):
        self.pulse.write_text("".join(json.dumps({"t": t, "sessions": 0}) + "\n" for t in times))

    def main(self, now, sleeps=()):
        with mock.patch("sys.stdout") as out:
            code = self.mod.main(now=now, read_sleeps=lambda since, until: list(sleeps))
        return code, "".join(c.args[0] for c in out.write.call_args_list)

    def test_no_gap(self):
        self.write(range(self.SINCE - 600, self.SINCE + 86400 + 600, 60))
        self.assertEqual(self.main(self.SINCE + 86400 + 60)[0], 0)

    def test_awake_gap(self):
        times = [t for t in range(self.SINCE, self.SINCE + 86400, 60) if not self.SINCE + 3600 < t < self.SINCE + 4000]
        self.write(times)
        code, out = self.main(self.SINCE + 86400 + 60)
        self.assertEqual(code, 1)
        self.assertIn("420 s", out)

    def test_gap_holding_sleep(self):
        times = [t for t in range(self.SINCE, self.SINCE + 86400, 60) if not self.SINCE + 3600 < t < self.SINCE + 4000]
        self.write(times)
        self.assertEqual(self.main(self.SINCE + 86400 + 60, sleeps=[(self.SINCE + 3700, 200)])[0], 0)

    def test_log_ends_early(self):
        """Round 1 finding 1: the pulse stopping 1 h after the merge is a gap to the window's end."""
        self.write(range(self.SINCE, self.SINCE + 3600, 60))
        code, out = self.main(self.SINCE + 86400 + 60)
        self.assertEqual(code, 1)
        self.assertIn(f"{86400 - 3540} s", out)

    def test_log_starts_late(self):
        self.write(range(self.SINCE + 3600, self.SINCE + 86400, 60))
        code, out = self.main(self.SINCE + 86400 + 60)
        self.assertEqual(code, 1)
        self.assertIn("3600 s", out)

    def test_empty_window(self):
        self.write([self.SINCE - 7200, self.SINCE + 86400 + 7200])
        self.assertEqual(self.main(self.SINCE + 86400 + 60)[0], 1)

    def test_single_line(self):
        self.write([self.SINCE + 43200])
        self.assertEqual(self.main(self.SINCE + 86400 + 60)[0], 1)

    def test_edge_gap_holding_sleep(self):
        """A trailing silence is excused by a Sleep inside it, like any other gap."""
        self.write(range(self.SINCE, self.SINCE + 86400 - 3600, 60))
        self.assertEqual(self.main(self.SINCE + 86400 + 60, sleeps=[(self.SINCE + 86400 - 3000, 3000)])[0], 0)

    def test_too_early(self):
        self.write(range(self.SINCE, self.SINCE + 3600, 60))
        self.assertEqual(self.main(self.SINCE + 3600)[0], 75)


if __name__ == "__main__":
    unittest.main()
