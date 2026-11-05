"""serve.py re-execs itself when serve.py, board.py or route.py change on disk, once the new code imports, whatever
runs are live: RUNS is handed to the new process (restore_runs)."""
import io, json, os, signal, subprocess, sys, tempfile, time, unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_IDLE_CLEANUP"] = "0"  # a watchdog tick never signals a real dev server or quits Docker
os.environ["SCRUM_PS"] = os.devnull  # no live sessions unless a test says so, whatever this machine runs
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test runs top or reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
import serve  # noqa: E402


class FakeProc:
    def __init__(self, codes, pid=4242):
        self.codes, self.pid = list(codes), pid

    def poll(self):
        return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]


def ok_check(*a, **k):
    return subprocess.CompletedProcess(a[0], 0, b"", b"")


def bad_check(*a, **k):
    return subprocess.CompletedProcess(a[0], 1, b"", b"Traceback...\nSyntaxError: invalid syntax\n")


class SelfReloadTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.files = tuple(Path(tmp.name) / n for n in ("serve.py", "board.py", "route.py"))
        for f in self.files:
            f.write_text("x")
            os.utime(f, ns=(1_000_000_000, 1_000_000_000))
        for name, val in (("SELF_FILES", self.files), ("RELOAD_REFUSED", None)):
            p = mock.patch.object(serve, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(serve, "CODE_STAMP", (1_000_000_000,) * 3)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(serve.RUNS, clear=True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(sys, "argv", ["serve.py", "--port", "8799"])
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ)  # the RUNS handoff a reload leaves in os.environ stays in the test
        p.start()
        self.addCleanup(p.stop)
        self.out, self.err = io.StringIO(), io.StringIO()

    def bump(self, i=1, ns=2_000_000_000):
        os.utime(self.files[i], ns=(ns, ns))

    def call(self, execv, check):
        with redirect_stdout(self.out), redirect_stderr(self.err):
            return serve.reload_if_changed(execv=execv, check=check)

    def test_reload_execs_when_code_changed_and_idle(self):
        self.bump()
        execv, check = mock.Mock(), mock.Mock(side_effect=ok_check)
        self.assertTrue(self.call(execv, check))
        script = str(serve.HERE / "serve.py")
        execv.assert_called_once_with(sys.executable, [sys.executable, script, "--port", "8799"])
        self.assertEqual(check.call_args.args[0], [sys.executable, script, "--help"])
        self.assertEqual(check.call_args.kwargs, {"capture_output": True, "timeout": 60})
        self.assertIn("serve.py: code changed on disk, reloading", self.out.getvalue())

    def test_no_reload_when_unchanged(self):
        execv, check = mock.Mock(), mock.Mock(side_effect=ok_check)
        self.assertFalse(self.call(execv, check))
        execv.assert_not_called()
        check.assert_not_called()

    def test_reload_does_not_wait_for_live_run(self):
        self.bump()
        serve.RUNS["p/001"] = {"action": "start", "started": 5.0, "log": "runs/a.log", "proc": FakeProc([None])}
        serve.RUNS["p/002"] = {"action": "resume", "started": 6.0, "log": "runs/b.log", "reason": "r", "handled": True,
                               "proc": FakeProc([3], pid=4343)}
        snaps = []
        execv = mock.Mock(side_effect=lambda exe, argv: snaps.append(os.environ[serve.RELOAD_RUNS]))
        self.assertTrue(self.call(execv, mock.Mock(side_effect=ok_check)))
        execv.assert_called_once()
        self.assertEqual(json.loads(snaps[0]), {
            "p/001": {"action": "start", "started": 5.0, "log": "runs/a.log", "pid": 4242, "exit": None},
            "p/002": {"action": "resume", "started": 6.0, "log": "runs/b.log", "reason": "r", "handled": True,
                      "pid": 4343, "exit": 3}})
        self.assertNotIn(serve.RELOAD_RUNS, os.environ)  # execv returned (a double): no later spawn inherits it

    def reload_and_restore(self):
        """One reload with a recording execv, then the new process's restore_runs from the snapshot it was handed."""
        self.bump()
        snaps = []
        self.assertTrue(self.call(lambda exe, argv: snaps.append(os.environ[serve.RELOAD_RUNS]), ok_check))
        serve.RUNS.clear()  # the new process starts with an empty table
        os.environ[serve.RELOAD_RUNS] = snaps[0]
        serve.restore_runs()
        self.assertNotIn(serve.RELOAD_RUNS, os.environ)

    def live_child(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL,
                                start_new_session=True)
        self.addCleanup(lambda: proc.poll() is None and (proc.kill(), proc.wait()))
        return proc

    def test_reload_keeps_live_run_tracked(self):
        proc = self.live_child()
        serve.RUNS["p/001"] = {"action": "start", "started": 1.0, "proc": proc, "log": "runs/x.log"}
        self.reload_and_restore()
        run = serve.RUNS["p/001"]
        self.assertIsNot(run["proc"], proc)
        self.assertEqual((run["proc"].pid, run["action"], run["started"], run["log"]), (proc.pid, "start", 1.0, "runs/x.log"))
        self.assertTrue(serve.running("p", "001"))
        self.assertEqual(serve.live_ids("p"), {"001"})
        serve.stop("p", "001")  # Pause/Abort still reach the session's process group through .pid
        end = time.time() + 5
        while serve.running("p", "001") and time.time() < end:
            time.sleep(0.05)
        self.assertFalse(serve.running("p", "001"))
        self.assertEqual(run["proc"].poll(), -signal.SIGTERM)  # the real code, as record_outcomes reads it
        self.assertEqual(serve.live_ids("p"), set())

    def test_play_resumes_paused_job_after_code_reload(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo" / "scrum"
        (root / "jobs").mkdir(parents=True)
        job_id = serve.board.cmd_new(root, "Paused job")
        data = json.loads((root / "board.json").read_text())
        data["jobs"][0].update(stage="build", paused=True)
        (root / "board.json").write_text(json.dumps(data))
        live = self.live_child()
        serve.RUNS["repo/" + job_id] = {"action": "start", "started": 1.0, "proc": FakeProc([0], pid=1), "log": "x"}
        serve.RUNS["repo/other"] = {"action": "start", "started": 1.0, "proc": live, "log": "y"}
        self.reload_and_restore()
        with mock.patch.object(serve, "spawn", return_value="runs/r.log") as spawn:
            code, out = serve.Handler.route(None, "repo", root, f"/jobs/{job_id}/resume", {"manual": True})
        self.assertEqual((code, out), (202, {"id": job_id, "action": "resume"}))
        spawn.assert_called_once_with("repo", root, job_id, "resume", f"/trevskills-scrum resume {job_id}", manual=True)
        # a run still live across the reload is refused, never started a second time
        serve.RUNS["repo/" + job_id] = serve.RUNS.pop("repo/other")
        with mock.patch.object(serve, "spawn") as spawn:
            code, _ = serve.Handler.route(None, "repo", root, f"/jobs/{job_id}/resume", {"manual": True})
        self.assertEqual(code, 409)
        spawn.assert_not_called()

    def test_board_only_change_reloads_server(self):
        self.bump(i=1)  # only board.py changed, as a Restart: none / Lilguy / Fast merge leaves it
        execv = mock.Mock()
        self.assertTrue(self.call(execv, mock.Mock(side_effect=ok_check)))
        execv.assert_called_once_with(sys.executable, [sys.executable, str(serve.HERE / "serve.py"), "--port", "8799"])

    def test_malformed_handoff_is_ignored(self):
        os.environ[serve.RELOAD_RUNS] = "{not json"
        with redirect_stderr(self.err):
            serve.restore_runs()
        self.assertEqual(serve.RUNS, {})
        self.assertNotIn(serve.RELOAD_RUNS, os.environ)
        self.assertIn("serve.py: reload handoff ignored:", self.err.getvalue())

    def test_broken_code_keeps_old_server(self):
        self.bump()
        execv, check = mock.Mock(), mock.Mock(side_effect=bad_check)
        self.assertFalse(self.call(execv, check))
        self.assertFalse(self.call(execv, check))
        execv.assert_not_called()
        self.assertEqual(check.call_count, 1)  # no retry until the stamp changes again
        self.assertEqual(self.err.getvalue(), "serve.py: new code fails to load, still running the old code: "
                                              "SyntaxError: invalid syntax\n")
        for exc in (OSError("no python"), subprocess.TimeoutExpired("serve.py", 60)):
            self.bump(ns=self.files[1].stat().st_mtime_ns + 1)
            self.assertFalse(self.call(execv, mock.Mock(side_effect=exc)))
        execv.assert_not_called()

    def test_fixed_code_after_broken_reloads(self):
        self.bump()
        execv = mock.Mock()
        self.assertFalse(self.call(execv, mock.Mock(side_effect=bad_check)))
        self.bump(ns=3_000_000_000)
        self.assertTrue(self.call(execv, mock.Mock(side_effect=ok_check)))
        execv.assert_called_once()

    def test_missing_file_does_not_crash(self):
        self.files[2].unlink()
        execv = mock.Mock()
        self.assertFalse(self.call(execv, mock.Mock(side_effect=bad_check)))
        execv.assert_not_called()
        self.assertIn("still running the old code", self.err.getvalue())
        with mock.patch.object(serve, "code_stamp", side_effect=RuntimeError("boom")):
            self.assertFalse(self.call(execv, mock.Mock()))  # nothing escapes, the watchdog loop goes on

    def test_watchdog_loop_checks_after_tick(self):
        order = []
        with mock.patch.object(serve, "watchdog_tick", side_effect=lambda: order.append("tick")), \
                mock.patch.object(serve, "reload_if_changed", side_effect=lambda: order.append("reload")), \
                mock.patch.object(serve.time, "sleep", side_effect=StopIteration):
            with self.assertRaises(StopIteration):
                serve.watchdog_loop()
        self.assertEqual(order, ["tick", "reload"])


if __name__ == "__main__":
    unittest.main()
