"""Job 1397: a serve.py reload hands the full E2E run in flight to the new process (RELOAD_E2E_FULL), which keeps
watching it (hot_stop_tick, the E2E_FULL_STALE cap from the run's own start, the record by e2e_full_run's own path);
a real restart stops the orphaned buildlock child and its separate-group webServer, and never a reused pid."""
import io, json, os, signal, subprocess, sys, tempfile, threading, time, unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
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
os.environ["SCRUM_PULSE"] = os.path.join(tempfile.mkdtemp(), "pulse.log")
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))
import serve  # noqa: E402

CHILD = "import time,sys\nprint('ready', flush=True)\ntime.sleep(120)\n"


def gone(pid, wait=30.0):
    """True once pid is gone or a zombie, polled up to wait seconds."""
    deadline = time.time() + wait
    while True:
        if serve.e2e_full_pid_gone(pid):
            return True
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if not state or state.startswith("Z"):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.1)


def kill(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class ReloadedProcWaitTest(unittest.TestCase):
    def test_wait_returns_the_exit_code(self):
        p = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(3)"])
        self.assertEqual(serve.ReloadedProc(p.pid).wait(timeout=30), 3)
        p.returncode = 3  # reaped by ReloadedProc: Popen's own wait must not try again

    def test_wait_times_out(self):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(p.wait)
        self.addCleanup(p.kill)
        started = time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            serve.ReloadedProc(p.pid).wait(timeout=0.5)
        self.assertGreaterEqual(time.time() - started, 0.5)
        self.assertIsNone(p.poll())


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(os.path.realpath(tmp.name))
        self.repo = self.base / "repo"
        self.root = self.repo / "scrum"
        self.root.mkdir(parents=True)
        self.wt = self.repo / ".claude" / "worktrees" / "e2e-full"
        self.wt.mkdir(parents=True)
        (self.root / "project.md").write_text("# Project\n- E2E: sh run-e2e.sh\n")
        (self.base / "projects.json").write_text(json.dumps([str(self.repo)]))
        (self.base / "home").mkdir()
        for p in (mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(self.base / "projects.json"),
                                               "HOME": str(self.base / "home")}),
                  mock.patch.object(serve, "HOT_STOP_WAIT", 1),
                  mock.patch.object(serve.board, "live_sessions", return_value=1)):
            p.start()
            self.addCleanup(p.stop)
        serve.E2E_FULL.clear()
        serve.E2E_FULL["running"] = None
        self.addCleanup(lambda: (serve.E2E_FULL.clear(), serve.E2E_FULL.update(running=None)))
        self.procs = []
        self.addCleanup(self.reap)

    def reap(self):
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                p.wait(timeout=5)
            except (subprocess.TimeoutExpired, ChildProcessError):
                pass

    def record(self):
        return json.loads((self.root / "e2e-full.json").read_text())


class ReloadHandoverTest(Base):
    def setUp(self):
        super().setUp()
        files = tuple(self.base / n for n in ("serve.py", "board.py", "route.py"))
        for f in files:
            f.write_text("x")
            os.utime(f, ns=(1_000_000_000, 1_000_000_000))
        self.files = files
        for p in (mock.patch.object(serve, "SELF_FILES", files),
                  mock.patch.object(serve, "RELOAD_REFUSED", None),
                  mock.patch.object(serve, "CODE_STAMP", (1_000_000_000,) * 3),
                  mock.patch.object(serve, "e2e_full_worktree", return_value=self.wt),
                  mock.patch.object(serve.board, "listeners", return_value=[]),
                  mock.patch.object(sys, "argv", ["serve.py", "--port", "8799"])):
            p.start()
            self.addCleanup(p.stop)
        self.release = threading.Event()

    def old_run(self):
        """The old process's e2e_full_run with a real buildlock-like child; its thread is parked from then on, as
        execv would have ended it (released by SystemExit at cleanup, so it writes nothing)."""
        started = threading.Event()

        def fake_exec(repo, cmd, env, log, loads):
            with open(log, "w") as f:
                p = subprocess.Popen([sys.executable, "-c", CHILD], cwd=repo, stdin=subprocess.DEVNULL, stdout=f,
                                     stderr=subprocess.STDOUT, start_new_session=True)
            self.procs.append(p)
            serve.E2E_FULL["pid"] = p.pid
            started.set()
            self.release.wait()
            raise SystemExit  # the old process is gone: nothing after this runs in it

        serve.write_e2e_full(self.root, {"at": 123.0, "head": "h1", "result": "running", "exit": None, "failed": [],
                                         "lastGreen": "lg"})
        serve.E2E_FULL["running"] = "repo"
        patch = mock.patch.object(serve, "e2e_full_exec", side_effect=fake_exec)
        patch.start()
        t = threading.Thread(target=serve.e2e_full_run, args=(self.repo, self.root, "sh run-e2e.sh", "h1", 123.0, "lg"),
                             daemon=True)
        t.start()
        self.assertTrue(started.wait(30))
        patch.stop()
        self.addCleanup(lambda: (self.release.set(), t.join(30)))
        for _ in range(300):  # the child has printed, so the log holds output
            if "ready" in (self.root / "e2e-full.log").read_text():
                break
            time.sleep(0.1)
        return self.procs[-1]

    def reload(self):
        """reload_if_changed with a recording execv; returns (execv calls, the RELOAD_E2E_FULL value at execv)."""
        os.utime(self.files[0], ns=(2_000_000_000, 2_000_000_000))
        execs, seen = [], []

        def execv(exe, argv):
            execs.append(argv)
            seen.append(os.environ.get("SCRUM_RELOAD_E2E_FULL"))
        ok = lambda *a, **k: subprocess.CompletedProcess(a[0], 0, b"", b"")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertTrue(serve.reload_if_changed(execv=execv, check=ok))
        self.assertNotIn("SCRUM_RELOAD_E2E_FULL", os.environ, "no later spawn inherits the hand-over")
        return execs, seen[0]

    def restore(self, data):
        """The new process: empty state, then restore_e2e_full from the env var the old one left."""
        serve.E2E_FULL.clear()
        serve.E2E_FULL["running"] = None
        os.environ["SCRUM_RELOAD_E2E_FULL"] = data
        t = serve.restore_e2e_full()
        self.assertNotIn("SCRUM_RELOAD_E2E_FULL", os.environ)
        return t

    def test_reload_hands_the_run_over(self):
        child = self.old_run()
        execs, data = self.reload()
        self.assertEqual(len(execs), 1)
        self.assertIsNone(child.poll(), "the reload never stops the run")
        got = json.loads(data)
        self.assertEqual((got["running"], got["pid"]), ("repo", child.pid))
        ctx = got["ctx"]
        self.assertEqual((ctx["repo"], ctx["root"], ctx["cmd"], ctx["head"], ctx["at"], ctx["last_green"],
                          ctx["retried"], ctx["wt"], ctx["before"], ctx["project"]),
                         (str(self.repo), str(self.root), "sh run-e2e.sh", "h1", 123.0, "lg", False, str(self.wt), [],
                          "repo"))
        self.assertLessEqual(ctx["started"], time.time())
        t = self.restore(data)
        self.assertEqual((serve.E2E_FULL["running"], serve.E2E_FULL["pid"]), ("repo", child.pid))
        self.assertTrue(t.is_alive())
        self.assertEqual(self.record()["result"], "running")
        serve.e2e_full_tick("repo", self.repo, self.root)
        self.assertEqual(self.record()["result"], "running", "the tick sees the run in flight: no orphan rewrite")
        self.assertIsNone(child.poll())
        os.killpg(child.pid, signal.SIGKILL)
        t.join(30)
        self.assertFalse(t.is_alive())

    def test_reload_never_waits_or_signals(self):
        child = self.old_run()
        with mock.patch.object(serve.os, "killpg", side_effect=AssertionError("signalled")), \
                mock.patch.object(serve.os, "kill", side_effect=AssertionError("signalled")):
            started = time.time()
            execs, data = self.reload()
        self.assertLess(time.time() - started, 10)
        self.assertEqual(len(execs), 1)
        self.assertIsNone(child.poll())
        self.assertIsNotNone(data)

    def test_no_handover_while_hot_stopping(self):
        self.old_run()
        serve.E2E_FULL["hot_stop"] = "CPU load"
        _, data = self.reload()
        self.assertIsNone(data)

    def test_hot_stop_tick_stops_the_restored_run(self):
        child = self.old_run()
        _, data = self.reload()
        t = self.restore(data)
        with mock.patch.dict(os.environ, SCRUM_VM_PRESSURE="3"):
            self.assertEqual(serve.hot_stop_tick(), ["repo/e2e-full"])
        t.join(30)
        self.assertFalse(t.is_alive())
        rec = self.record()
        self.assertEqual((rec["result"], rec["reason"], rec["exit"], rec["lastGreen"], rec["loads"]),
                         ("loaded", "memory pressure warn (kernel level 3)", -15, "lg", 1))
        self.assertTrue(gone(child.pid))
        self.assertIsNone(serve.E2E_FULL["running"])
        self.assertNotIn("pid", serve.E2E_FULL)
        self.assertNotIn("ctx", serve.E2E_FULL)

    def test_cap_counts_from_the_runs_own_start(self):
        child = self.old_run()
        _, data = self.reload()
        got = json.loads(data)
        got["ctx"]["started"] = time.time() - 100  # the run began 100 s ago; the cap is 60 s
        with mock.patch.object(serve, "E2E_FULL_STALE", 60), mock.patch.object(serve, "E2E_FULL_LOAD_SECS", 0.2):
            t = self.restore(json.dumps(got))
            t.join(30)
        self.assertFalse(t.is_alive())
        rec = self.record()
        self.assertEqual((rec["result"], rec["exit"], rec["head"], rec["lastGreen"]), ("error", -15, "h1", "lg"),
                         "e2e_full_run's own path wrote it (an orphan rewrite keeps exit null)")
        self.assertTrue(gone(child.pid))

    def test_malformed_handover_is_ignored(self):
        os.environ["SCRUM_RELOAD_E2E_FULL"] = "{not json"
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertIsNone(serve.restore_e2e_full())
        self.assertIn("full E2E hand-over ignored", err.getvalue())
        self.assertIsNone(serve.E2E_FULL["running"])
        self.assertNotIn("SCRUM_RELOAD_E2E_FULL", os.environ)


BUILDLOCK = """import os, subprocess, sys, time
web = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
open(sys.argv[2], "w").write(str(web.pid))
time.sleep(120)
"""


class RealRestartTest(Base):
    def setUp(self):
        super().setUp()
        self.lock = Path(self.base / "home" / ".claude" / "trevskills-scrum" / "e2e.lock")
        self.lock.parent.mkdir(parents=True)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "buildlock.py").write_text(BUILDLOCK)
        serve.write_e2e_full(self.root, {"at": 123.0, "head": "h1", "result": "running", "exit": None, "failed": [],
                                         "lastGreen": "lg", "loads": 1})
        # the tick returns right after its orphan pass: this project's sweep holds the checkout
        (self.root / "ui-sweep.json").write_text(json.dumps({"at": time.time(), "result": "running"}))

    def holder(self, cmd, cwd):
        """A live buildlock-shaped child (own group, one webServer child in a group of its own), the holder file
        naming it at cwd; returns (proc, webServer pid)."""
        pidfile = self.base / f"web-{len(self.procs)}.pid"
        p = subprocess.Popen([sys.executable, str(self.bin / "buildlock.py"), cmd, str(pidfile)], cwd=cwd,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        self.procs.append(p)
        for _ in range(300):
            if pidfile.exists() and pidfile.read_text():
                break
            time.sleep(0.1)
        web = int(pidfile.read_text())
        self.addCleanup(kill, web)
        slot = serve.buildlock.slot_paths(self.lock)[0]
        serve.buildlock.holder_path(slot).write_text(f"{p.pid}\n{cwd}\n{int(time.time())}")
        return p, web

    def tick(self, listeners=()):
        with mock.patch.object(serve.board, "listeners", return_value=list(listeners)), \
                redirect_stderr(io.StringIO()):
            serve.e2e_full_tick("repo", self.repo, self.root)

    def test_orphan_and_its_webserver_are_stopped(self):
        p, web = self.holder("sh run-e2e.sh", self.wt)
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=self.wt,
                                 start_new_session=True)  # a listener in the worktree outside the tree
        self.procs.append(other)
        self.tick(listeners=[(other.pid, 3999, str(self.wt))])
        self.assertTrue(gone(p.pid), "the buildlock child is stopped")
        self.assertTrue(gone(web), "its webServer in its own group is stopped too")
        self.assertTrue(gone(other.pid), "a listener left in the worktree is stopped")
        self.assertEqual(self.record(), {"at": 123.0, "head": "h1", "result": "loaded", "exit": None, "failed": [],
                                         "lastGreen": "lg", "loads": 2,
                                         "reason": "serve.py restarted while the full run was in flight"})

    def test_reused_pid_other_command_is_left_alone(self):
        p, web = self.holder("npm run something-else", self.wt)
        self.tick()
        time.sleep(0.5)
        self.assertIsNone(p.poll(), "a pid running another command is never signalled")
        self.assertFalse(gone(web, 0))
        self.assertEqual(self.record()["result"], "error")
        self.assertIsNone(self.record()["exit"])

    def test_reused_pid_other_cwd_is_left_alone(self):
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        p, web = self.holder("sh run-e2e.sh", elsewhere)
        self.tick()
        time.sleep(0.5)
        self.assertIsNone(p.poll(), "a pid running in another directory is never signalled")
        self.assertEqual(self.record()["result"], "error")

    def test_holder_cwd_differs_from_live_cwd(self):
        """The holder file names the worktree but the live pid runs elsewhere (a reused pid): not signalled."""
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        p, _ = self.holder("sh run-e2e.sh", elsewhere)
        slot = serve.buildlock.slot_paths(self.lock)[0]
        serve.buildlock.holder_path(slot).write_text(f"{p.pid}\n{self.wt}\n{int(time.time())}")
        self.tick()
        time.sleep(0.5)
        self.assertIsNone(p.poll())
        self.assertEqual(self.record()["result"], "error")


if __name__ == "__main__":
    unittest.main()
