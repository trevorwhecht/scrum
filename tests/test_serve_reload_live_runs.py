"""Job 653: serve.py must move to new code on disk within a few watchdog ticks even while a dashboard-started run
stays live the whole time (a busy day), instead of waiting forever for RUNS to go idle."""
import io, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_IDLE_CLEANUP"] = "0"
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
import serve  # noqa: E402


class ReloadWhileRunsLiveTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.files = tuple(Path(tmp.name) / n for n in ("serve.py", "board.py", "route.py"))
        for f in self.files:
            f.write_text("x")
            os.utime(f, ns=(1_000_000_000, 1_000_000_000))
        for p in (mock.patch.object(serve, "SELF_FILES", self.files),
                  mock.patch.object(serve, "RELOAD_REFUSED", None),
                  mock.patch.object(serve, "CODE_STAMP", (1_000_000_000,) * 3),
                  mock.patch.dict(serve.RUNS, clear=True),
                  mock.patch.dict(os.environ),  # whatever a reload hands to the new process is undone here
                  mock.patch.object(sys, "argv", ["serve.py", "--port", "8799"])):
            p.start()
            self.addCleanup(p.stop)
        # a real dashboard-style run that outlives every tick of this test
        self.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(self.proc.wait)
        self.addCleanup(self.proc.kill)

    def test_reload_happens_while_runs_stay_live(self):
        serve.RUNS["p/001"] = {"action": "start", "started": 1.0, "proc": self.proc, "log": "runs/x.log"}
        os.utime(self.files[0], ns=(2_000_000_000, 2_000_000_000))  # serve.py changed on disk after start
        execs = []
        ok = lambda *a, **k: subprocess.CompletedProcess(a[0], 0, b"", b"")
        reloaded = False
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for _ in range(3):  # three watchdog ticks, the run live through all of them
                if serve.reload_if_changed(execv=lambda exe, argv: execs.append(argv), check=ok):
                    reloaded = True
                    break
        self.assertIsNone(self.proc.poll(), "the live run must not be killed by the reload")
        self.assertTrue(reloaded, "server still on old code after 3 ticks with a run live the whole time")
        self.assertEqual(execs, [[sys.executable, str(serve.HERE / "serve.py"), "--port", "8799"]])


if __name__ == "__main__":
    unittest.main()
