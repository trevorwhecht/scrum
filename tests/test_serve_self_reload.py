"""serve.py re-execs itself when serve.py, board.py or route.py change on disk, once the new code imports and no
dashboard-started run is live."""
import io, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_PS"] = os.devnull  # no live sessions unless a test says so, whatever this machine runs
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly idle unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
import serve  # noqa: E402


class FakeProc:
    def __init__(self, codes):
        self.codes = list(codes)

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

    def test_reload_waits_for_live_run(self):
        self.bump()
        serve.RUNS["p/001"] = {"action": "start", "proc": FakeProc([None, 0])}
        execv, check = mock.Mock(), mock.Mock(side_effect=ok_check)
        self.assertFalse(self.call(execv, check))
        execv.assert_not_called()
        check.assert_not_called()
        self.assertTrue(self.call(execv, check))
        execv.assert_called_once()

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
