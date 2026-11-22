import fcntl, importlib.util, io, os, re, select, signal, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "trevskills-scrum" / "buildlock.py"
HOLD = ("import fcntl, sys, time\n"
        "f = open(sys.argv[1], 'a')\n"
        "fcntl.flock(f, fcntl.LOCK_EX)\n"
        "print('locked', flush=True)\n"
        "time.sleep(60)\n")


def load():
    spec = importlib.util.spec_from_file_location("buildlock", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BuildLockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.lock = self.dir / "sub" / "build.lock"
        self.env = {**os.environ, "SCRUM_BUILD_LOCK": str(self.lock),
                    "SCRUM_REGISTRY": str(self.dir / "none.json"),  # never Trevor's real boards
                    "SCRUM_COOLDOWN": str(self.dir / "no-cooldown"),  # never Trevor's real cool-down flag
                    "SCRUM_CPU_LOAD_PCT": "0", "SCRUM_SWAP_PCT": "0",  # calm: no test holds on this machine's readings
                    "SCRUM_VM_PRESSURE": "1",  # kernel memory pressure normal: heavy_hold never runs sysctl
                    "SCRUM_HEAVY_STEPS_LOG": str(self.dir / "heavy-steps.log")}  # never the real heavy-steps.log
        self.env.pop("SCRUM_BUILD_LOCK_TIMEOUT", None)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            for s in (p.stdout, p.stderr):
                if s:
                    s.close()
        self.tmp.cleanup()

    def run_wrap(self, *args, **env):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env={**self.env, **env},
                              capture_output=True, text=True, timeout=30)

    def start_wrap(self, *args, **env):
        p = subprocess.Popen([sys.executable, str(SCRIPT), *args], env={**self.env, **env},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        return p

    def hold(self):
        self.lock.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen([sys.executable, "-c", HOLD, str(self.lock)], stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.assertEqual(p.stdout.readline(), "locked\n")
        return p

    def test_exit_code_passed_through(self):
        self.assertEqual(self.run_wrap(sys.executable, "-c", "raise SystemExit(3)").returncode, 3)
        self.assertEqual(self.run_wrap(sys.executable, "-c", "pass").returncode, 0)
        self.assertEqual(self.run_wrap("exit 3").returncode, 3)

    def test_single_arg_runs_through_shell(self):
        r = self.run_wrap("echo one && echo two | tr a-z A-Z")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "one\nTWO\n")
        # two or more args are argv: no shell expansion of `$HOME`
        r = self.run_wrap("echo", "$HOME")
        self.assertEqual(r.stdout, "$HOME\n")

    def test_output_unchanged(self):
        r = self.run_wrap(sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)")
        self.assertEqual(r.stdout, "out\n")
        self.assertEqual(r.stderr, "err\n")

    def test_concurrent_runs_serialize(self):
        log = self.dir / "log.txt"
        child = ("import sys, time\n"
                 "open(sys.argv[1], 'a').write(sys.argv[2] + ' start %r\\n' % time.time())\n"
                 "time.sleep(0.6)\n"
                 "open(sys.argv[1], 'a').write(sys.argv[2] + ' end %r\\n' % time.time())\n")
        a = self.start_wrap(sys.executable, "-c", child, str(log), "A")
        b = self.start_wrap(sys.executable, "-c", child, str(log), "B")
        self.assertEqual(a.wait(timeout=30), 0)
        self.assertEqual(b.wait(timeout=30), 0)
        rows = [l.split() for l in log.read_text().splitlines()]
        self.assertEqual(len(rows), 4)
        first, second = rows[0][0], [r[0] for r in rows if r[0] != rows[0][0]][0]
        t = {(r[0], r[1]): float(r[2]) for r in rows}
        self.assertGreaterEqual(t[(second, "start")], t[(first, "end")])

    def test_sigkilled_holder_releases_lock(self):
        holder = self.hold()
        waiter = self.start_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="20")
        time.sleep(0.8)
        self.assertIsNone(waiter.poll())
        holder.send_signal(signal.SIGKILL)
        t0 = time.time()
        self.assertEqual(waiter.wait(timeout=10), 0)
        self.assertLess(time.time() - t0, 5)

    def test_timeout_exits_nonzero_with_message(self):
        self.hold()
        marker = self.dir / "ran"
        r = self.run_wrap(sys.executable, "-c", f"open({str(marker)!r}, 'w')", SCRUM_BUILD_LOCK_TIMEOUT="1")
        self.assertEqual(r.returncode, 124)
        self.assertFalse(marker.exists())
        lines = r.stderr.splitlines()
        self.assertEqual(sum(l.startswith("buildlock: timed out") for l in lines), 1)
        self.assertTrue(any(l.startswith(f"buildlock: timed out after 1 s waiting for the build lock ({self.lock})")
                            for l in lines), r.stderr)

    def test_waiting_message_only_when_contended(self):
        r = self.run_wrap(sys.executable, "-c", "pass")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        holder = self.hold()
        waiter = self.start_wrap(sys.executable, "-c", "print('built')", SCRUM_BUILD_LOCK_TIMEOUT="20")
        deadline = time.monotonic() + 20
        if not select.select([waiter.stderr], [], [], max(0, deadline - time.monotonic()))[0]:
            holder.kill()
            waiter.kill()
            self.fail("waiter never printed the waiting line within 20 s")
        first = waiter.stderr.readline()
        holder.kill()
        out, rest = waiter.communicate(timeout=10)
        err = first + rest
        self.assertEqual(waiter.returncode, 0)
        self.assertEqual(out, "built\n")
        self.assertEqual(err, f"buildlock: waiting for the build lock ({self.lock})\n")

    def test_default_lock_path_and_timeout(self):
        mod = load()
        with mock.patch.dict(os.environ, {"HOME": str(self.dir)}):
            os.environ.pop("SCRUM_BUILD_LOCK", None)
            os.environ.pop("SCRUM_BUILD_LOCK_TIMEOUT", None)
            self.assertEqual(mod.lock_path(), self.dir / ".claude" / "trevskills-scrum" / "build.lock")
            self.assertEqual(mod.timeout_s(), 1800)
            for bad in ("", "abc"):
                os.environ["SCRUM_BUILD_LOCK_TIMEOUT"] = bad
                self.assertEqual(mod.timeout_s(), 1800)
            os.environ["SCRUM_BUILD_LOCK_TIMEOUT"] = "7"
            self.assertEqual(mod.timeout_s(), 7)
            os.environ["SCRUM_BUILD_LOCK"] = "/x/y.lock"
            self.assertEqual(mod.lock_path(), Path("/x/y.lock"))
        # parent directory is created when missing
        self.assertFalse(self.lock.parent.exists())
        self.assertEqual(self.run_wrap(sys.executable, "-c", "pass").returncode, 0)
        self.assertTrue(self.lock.exists())

    def test_stale_lock_file_does_not_block(self):
        self.lock.parent.mkdir(parents=True)
        self.lock.write_text("12345\n")
        r = self.run_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="1")
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_no_args_usage(self):
        r = self.run_wrap()
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.startswith("usage: buildlock.py"), r.stderr)

    def test_killed_wrapper_keeps_lock_until_build_exits(self):
        log = self.dir / "log.txt"
        release = self.dir / "release"
        child = ("import os, sys, time\n"
                 "open(sys.argv[1], 'a').write('start %d\\n' % os.getpid())\n"
                 "deadline = time.monotonic() + 120\n"
                 "while not os.path.exists(sys.argv[2]) and time.monotonic() < deadline:\n"
                 "    time.sleep(0.05)\n"
                 "open(sys.argv[1], 'a').write('end\\n')\n")
        a = self.start_wrap(sys.executable, "-c", child, str(log), str(release))
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not (log.exists() and log.read_text().endswith("\n")):
                time.sleep(0.05)
            self.assertTrue(log.read_text().startswith("start "))
            a.send_signal(signal.SIGKILL)  # orphans the child, which waits on the release file
            b = self.start_wrap(sys.executable, "-c", "open(%r, 'a').write('B\\n')" % str(log),
                                SCRUM_BUILD_LOCK_TIMEOUT="100")
            # B is blocked on the lock once it has printed its waiting line; only then release the child
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if select.select([b.stderr], [], [], 0.2)[0]:
                    break
            first = b.stderr.readline()
            self.assertEqual(first, f"buildlock: waiting for the build lock ({self.lock})\n")
            release.write_text("")
            out, rest = b.communicate(timeout=120)
            self.assertEqual(b.returncode, 0)
            self.assertEqual(rest, "")
            self.assertEqual(log.read_text().split("\n")[1:], ["end", "B", ""])
        finally:
            release.write_text("")
            first = log.read_text().split("\n")[0].split()
            if len(first) == 2:
                try:
                    os.kill(int(first[1]), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def marker_dir(self):
        return self.lock.with_name("build.lock.waiting")

    def test_waiting_marker_created_and_removed(self):
        holder = self.hold()
        waiter = self.start_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="20")
        marker = self.marker_dir() / str(waiter.pid)
        for _ in range(50):
            if marker.exists() and marker.read_text():
                break
            time.sleep(0.1)
        self.assertEqual(marker.read_text().split("\n")[0], os.getcwd())
        self.assertEqual(marker.read_text().split("\n")[1], "0", "no board job holds this cwd: rank 0")
        holder.kill()
        self.assertEqual(waiter.wait(timeout=10), 0)
        self.assertFalse(marker.exists())

    def peer(self, rank, pid=None):
        """A live (or the given pid's) waiting marker of `rank`, older than any marker a waiter writes next."""
        self.marker_dir().mkdir(parents=True, exist_ok=True)
        if pid is None:
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            self.procs.append(p)
            pid = p.pid
        m = self.marker_dir() / str(pid)
        m.write_text(f"/elsewhere\n{rank}")
        os.utime(m, (time.time() - 60, time.time() - 60))
        return m

    def cooling(self):
        flag = self.dir / "cooldown"
        flag.write_text("")
        return {"SCRUM_COOLDOWN": str(flag)}

    def wait_marker(self, pid):
        m = self.marker_dir() / str(pid)
        for _ in range(100):
            if m.exists() and m.read_text():
                return m
            time.sleep(0.1)
        self.fail("no marker")

    def test_cooldown_serves_higher_rank_first(self):
        holder = self.hold()
        self.peer(3)
        waiter = self.start_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="3", **self.cooling())
        self.wait_marker(waiter.pid)
        holder.kill()
        holder.wait()
        self.assertEqual(waiter.wait(timeout=20), 124, "the rank-3 peer is alive, so the free lock stays its turn")

    def test_cooldown_equal_rank_older_marker_first(self):
        holder = self.hold()
        self.peer(0)
        waiter = self.start_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="3", **self.cooling())
        self.wait_marker(waiter.pid)
        holder.kill()
        holder.wait()
        self.assertEqual(waiter.wait(timeout=20), 124, "an older marker of the same rank goes first")

    def test_dead_peer_marker_never_blocks(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        holder = self.hold()
        self.peer(3, pid=dead.pid)
        waiter = self.start_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="20", **self.cooling())
        self.wait_marker(waiter.pid)
        holder.kill()
        self.assertEqual(waiter.wait(timeout=10), 0)

    def test_unparseable_peer_rank_is_zero(self):
        mod = load()
        self.marker_dir().mkdir(parents=True)
        for text, rank in (("/x", 0), ("/x\nabc", 0), ("/x\n2", 2)):
            (self.marker_dir() / "1").write_text(text)
            self.assertEqual(mod.marker_rank(self.marker_dir() / "1"), rank, text)

    def test_rank_ignored_outside_cooldown(self):
        holder = self.hold()
        self.peer(3)
        waiter = self.start_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="20")
        self.wait_marker(waiter.pid)
        holder.kill()
        self.assertEqual(waiter.wait(timeout=10), 0)

    def dead_pid(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        return p.pid

    def test_prune_dead_waiters(self):
        bl = load()
        wd = bl.waiting_dir(self.lock)
        wd.mkdir(parents=True)
        dead, live, odd = wd / str(self.dead_pid()), wd / str(os.getpid()), wd / "notapid"
        for m in (dead, live, odd):
            m.write_text("x\n0")
        bl.prune_dead_waiters(self.lock)
        self.assertFalse(dead.exists())
        self.assertTrue(live.exists())
        self.assertTrue(odd.exists())
        bl.prune_dead_waiters(self.dir / "missing.lock")  # no dir: no raise

    def test_waiter_prunes_dead_marker(self):
        self.hold()
        wd = self.lock.with_name(self.lock.name + ".waiting")
        wd.mkdir(parents=True, exist_ok=True)
        dead = wd / str(self.dead_pid())
        dead.write_text("x\n0")
        r = self.run_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="1")
        self.assertEqual(r.returncode, 124)
        self.assertFalse(dead.exists())
        self.assertEqual(list(wd.iterdir()), [])

    def test_no_marker_when_lock_free(self):
        self.assertEqual(self.run_wrap(sys.executable, "-c", "pass").returncode, 0)
        self.assertEqual(list(self.marker_dir().glob("*")) if self.marker_dir().exists() else [], [])

    def test_marker_removed_on_timeout(self):
        self.hold()
        r = self.run_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="1")
        self.assertEqual(r.returncode, 124)
        self.assertEqual(list(self.marker_dir().glob("*")), [])

    def run_inproc_unlink_fails(self, argv, holder_dies_after=None, **env):
        """Run main() in-process while the marker unlink raises OSError; return its exit code."""
        holder = self.hold()
        if holder_dies_after:
            threading.Timer(holder_dies_after, holder.kill).start()
        with mock.patch.dict(os.environ, {**self.env, **env}), \
                mock.patch.object(Path, "unlink", side_effect=PermissionError("denied")), \
                mock.patch("sys.stderr", new=io.StringIO()):
            return load().main(argv)

    def test_marker_unlink_failure_keeps_exit_code(self):
        code = self.run_inproc_unlink_fails([sys.executable, "-c", "raise SystemExit(7)"], holder_dies_after=1,
                                            SCRUM_BUILD_LOCK_TIMEOUT="20")
        self.assertEqual(code, 7)

    def test_marker_unlink_failure_on_timeout(self):
        code = self.run_inproc_unlink_fails([sys.executable, "-c", "pass"], SCRUM_BUILD_LOCK_TIMEOUT="1")
        self.assertEqual(code, 124)

    def project(self, build):
        f = self.dir / "project.md"
        f.write_text(f"# p\n- Test: x\n- Build: {build}\n- Other: y\n")
        return str(f)

    def test_project_flag_runs_build_line(self):
        self.assertEqual(self.run_wrap("--project", self.project("  exit 3  ")).returncode, 3)
        r = self.run_wrap("--project", self.project("echo one && echo two | tr a-z A-Z"))
        self.assertEqual((r.returncode, r.stdout), (0, "one\nTWO\n"))

    def test_project_flag_build_with_single_quote(self):
        r = self.run_wrap("--project", self.project("""printf '%s\\n' 'it'"'"'s ok'"""))
        self.assertEqual((r.returncode, r.stdout), (0, "it's ok\n"))

    def test_project_flag_missing_or_none_build(self):
        marker = self.dir / "ran"
        nobuild = self.dir / "nobuild.md"
        nobuild.write_text("- Test: x\n")
        cases = [str(self.dir / "missing.md"), str(nobuild), self.project("none"), self.project("NONE"), self.project("")]
        for path in cases:
            r = self.run_wrap("--project", path)
            self.assertEqual(r.returncode, 2, path)
            self.assertRegex(r.stderr, r"\Abuildlock:[^\n]*" + re.escape(path) + r"[^\n]*\n\Z")
        r = self.run_wrap("--project")
        self.assertEqual(r.returncode, 2)
        self.assertRegex(r.stderr, r"\Abuildlock:[^\n]*\n\Z")
        self.assertFalse(marker.exists())
        self.assertFalse(self.lock.exists())

    def test_project_flag_bad_path_fails_without_waiting(self):
        self.hold()
        start = time.monotonic()
        r = self.run_wrap("--project", str(self.dir / "missing.md"), SCRUM_BUILD_LOCK_TIMEOUT="120")
        self.assertEqual(r.returncode, 2)
        self.assertLess(time.monotonic() - start, 20)  # a wait for the held lock would run to run_wrap's 30 s timeout

    def test_missing_command_returns_127(self):
        self.assertEqual(self.run_wrap("no-such-cmd-buildlock-xyz", "arg").returncode, 127)
        self.assertEqual(self.run_wrap("no-such-cmd-buildlock-xyz").returncode, 127)
        with open(self.lock, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if the lock was left held

    def hold_path(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen([sys.executable, "-c", HOLD, str(path)], stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.assertEqual(p.stdout.readline(), "locked\n")
        return p

    def test_two_slots_run_two_at_once(self):
        x = self.dir / "sub" / "x.lock"
        go = self.dir / "go"
        child = ("import os, sys, time\n"
                 "open(sys.argv[1], 'w').close()\n"
                 "while not os.path.exists(sys.argv[2]): time.sleep(0.05)\n")
        env = {"SCRUM_BUILD_LOCK": str(x), "SCRUM_X_LOCK_SLOTS": "2", "SCRUM_BUILD_LOCK_TIMEOUT": "30"}
        runs = [self.start_wrap(sys.executable, "-c", child, str(self.dir / f"r{i}"), str(go), **env)
                for i in range(3)]
        started = lambda: [i for i in range(3) if (self.dir / f"r{i}").exists()]
        deadline = time.time() + 10
        while len(started()) < 2 and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(started()), 2)
        time.sleep(1.5)
        self.assertEqual(len(started()), 2)  # the third waits for a slot
        self.assertEqual(sum(p.poll() is None for p in runs), 3)
        self.assertTrue((self.dir / "sub" / "x.lock.0").exists())
        self.assertTrue((self.dir / "sub" / "x.lock.1").exists())
        self.assertFalse(x.exists())
        go.touch()
        for p in runs:
            self.assertEqual(p.wait(timeout=10), 0)
        self.assertEqual(started(), [0, 1, 2])

    def test_slots_full_times_out_124(self):
        x = self.dir / "sub" / "x.lock"
        self.hold_path(self.dir / "sub" / "x.lock.0")
        self.hold_path(self.dir / "sub" / "x.lock.1")
        ran = self.dir / "ran"
        r = self.run_wrap(sys.executable, "-c", f"open({str(ran)!r}, 'w')", SCRUM_BUILD_LOCK=str(x),
                          SCRUM_X_LOCK_SLOTS="2", SCRUM_BUILD_LOCK_TIMEOUT="1")
        self.assertEqual(r.returncode, 124)
        self.assertFalse(ran.exists())
        self.assertIn(f"buildlock: timed out after 1 s waiting for the build lock ({x})", r.stderr)

    def test_bad_slots_value_uses_default(self):
        mod = load()
        with mock.patch.dict(os.environ, {}):
            for name in ("SCRUM_CHECK_LOCK_SLOTS", "SCRUM_BUILD_LOCK_SLOTS", "SCRUM_E2E_LOCK_SLOTS"):
                os.environ.pop(name, None)
            self.assertEqual(mod.slots(Path("/a/check.lock")), 2)
            self.assertEqual(mod.slots(Path("/a/build.lock")), 1)
            self.assertEqual(mod.slots(Path("/a/e2e.lock")), 1)
            for bad in ("", "abc", "0", "-1", "1.5"):
                os.environ["SCRUM_CHECK_LOCK_SLOTS"] = bad
                os.environ["SCRUM_BUILD_LOCK_SLOTS"] = bad
                self.assertEqual(mod.slots(Path("/a/check.lock")), 2, bad)
                self.assertEqual(mod.slots(Path("/a/build.lock")), 1, bad)
            os.environ["SCRUM_CHECK_LOCK_SLOTS"] = "3"
            self.assertEqual(mod.slots(Path("/a/check.lock")), 3)

    def test_holder_file_written_and_removed(self):
        holder = self.dir / "sub" / "build.lock.holder"
        out, start = self.dir / "seen", time.time()
        copy = f"import shutil; shutil.copy({str(holder)!r}, {str(out)!r}); raise SystemExit(3)"
        p = subprocess.Popen([sys.executable, str(SCRIPT), sys.executable, "-c", copy], env=self.env,
                             cwd=self.dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.assertEqual(p.wait(timeout=30), 3)
        pid, cwd, at = out.read_text().split("\n")
        self.assertEqual(int(pid), p.pid)
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(self.dir))
        self.assertLessEqual(abs(int(at) - start), 5)
        self.assertFalse(holder.exists())
        self.hold()  # a waiter that times out never leaves a holder file
        self.assertEqual(self.run_wrap(sys.executable, "-c", "pass", SCRUM_BUILD_LOCK_TIMEOUT="1").returncode, 124)
        self.assertFalse(holder.exists())

    def test_holder_write_failure_keeps_exit_code(self):
        (self.dir / "sub" / "build.lock.holder").mkdir(parents=True)  # a directory: write and unlink both fail
        self.assertEqual(self.run_wrap(sys.executable, "-c", "raise SystemExit(7)").returncode, 7)

class HeavyHoldTest(unittest.TestCase):
    """buildlock.py on build.lock and e2e.lock waits, marker written and no slot taken, while board.heavy_hold gives a
    reason (job 1227)."""
    setUp, tearDown, run_wrap, marker_dir = (BuildLockTest.setUp, BuildLockTest.tearDown, BuildLockTest.run_wrap,
                                             BuildLockTest.marker_dir)
    LOAD = "CPU load 400% of 8 cores (> 300%)"

    def board(self, *reasons, seen=None):
        """A fake board whose heavy_hold gives `reasons` in turn (the last for ever after), raising an exception reason;
        each call first appends seen_now() to `seen`. calls counts them."""
        def heavy_hold():
            fake.calls += 1
            if seen is not None:
                seen.append(self.seen_now())
            r = reasons[min(fake.calls, len(reasons)) - 1]
            if isinstance(r, BaseException):
                raise r
            return r
        fake = SimpleNamespace(calls=0, heavy_hold=heavy_hold, lock_rank=lambda cwd: 0, cooling_down=lambda: False)
        return fake

    def seen_now(self):
        """(the lock is flocked, this process's waiting marker exists, the command has run)."""
        lock = Path(os.environ["SCRUM_BUILD_LOCK"])
        with open(lock, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = False
            except BlockingIOError:
                locked = True
        marker = lock.with_name(lock.name + ".waiting") / str(os.getpid())
        return locked, marker.exists(), (self.dir / "ran").exists()

    def main_inproc(self, board, lock="build.lock", code=0, poll=0, **env):
        """main() in-process on `lock` with board_module() giving `board` and HOLD_POLL `poll`; (exit code, stderr,
        whether the command ran)."""
        bl = load()
        self.assertEqual(bl.HOLD_POLL, 5)
        bl.HOLD_POLL = poll
        ran = self.dir / "ran"
        with mock.patch.dict(os.environ, {**self.env, "SCRUM_BUILD_LOCK": str(self.dir / "sub" / lock), **env}), \
                mock.patch.object(bl, "board_module", return_value=board), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            got = bl.main([sys.executable, "-c", f"open({str(ran)!r}, 'w').close(); raise SystemExit({code})"])
        return got, err.getvalue(), ran.exists()

    def test_held_over_load_times_out_124(self):
        ran = self.dir / "ran"
        r = self.run_wrap(sys.executable, "-c", f"open({str(ran)!r}, 'w')", SCRUM_CPU_LOAD_PCT="400",
                          SCRUM_BUILD_LOCK_TIMEOUT="1")
        load = f"CPU load 400% of {os.cpu_count()} cores (> 300%)"
        self.assertEqual((r.returncode, r.stderr), (124, f"buildlock: holding for the machine: {load} ({self.lock})\n"
                         f"buildlock: timed out after 1 s waiting for the build lock ({self.lock})\n"))
        self.assertFalse(ran.exists())
        self.assertEqual(list(self.marker_dir().glob("*")), [])

    def test_hold_lifts_then_runs(self):
        seen = []
        got = self.main_inproc(self.board(self.LOAD, None, seen=seen), code=5)
        self.assertEqual(got, (5, f"buildlock: holding for the machine: {self.LOAD} ({self.lock})\n", True))
        self.assertEqual(seen, [(False, False, False), (False, True, False)], "slot free yet untaken, marker written")
        self.assertEqual(list(self.marker_dir().glob("*")), [])

    def test_e2e_stem_held(self):
        board, e2e = self.board(self.LOAD), self.dir / "sub" / "e2e.lock"
        got = self.main_inproc(board, "e2e.lock", poll=30, SCRUM_BUILD_LOCK_TIMEOUT="1")
        self.assertEqual(got, (124, f"buildlock: holding for the machine: {self.LOAD} ({e2e})\n"
                                    f"buildlock: timed out after 1 s waiting for the build lock ({e2e})\n", False))
        self.assertEqual(board.calls, 1, "re-read at most every HOLD_POLL s")
        self.assertEqual(list((self.dir / "sub" / "e2e.lock.waiting").glob("*")), [])

    def test_check_lock_held_then_runs(self):
        """job 1312: check.lock waits on a hot Mac like build.lock, taking no slot, and keeps its 2 slots."""
        seen = []
        lock = self.dir / "sub" / "check.lock"
        got = self.main_inproc(self.board(self.LOAD, None, seen=seen), "check.lock", code=4)
        self.assertEqual(got, (4, f"buildlock: holding for the machine: {self.LOAD} ({lock})\n", True))
        self.assertEqual(seen, [(False, False, False), (False, True, False)], "slot free yet untaken, marker written")
        self.assertEqual(load().slots(lock), 2)

    def test_other_lock_never_held(self):
        r = self.run_wrap(sys.executable, "-c", "raise SystemExit(4)", SCRUM_CPU_LOAD_PCT="400",
                          SCRUM_BUILD_LOCK=str(self.dir / "sub" / "x.lock"), SCRUM_BUILD_LOCK_TIMEOUT="1")
        self.assertEqual((r.returncode, r.stderr), (4, ""))
        board = self.board(self.LOAD)
        self.assertEqual(self.main_inproc(board, "x.lock", code=4), (4, "", True))
        self.assertEqual(board.calls, 0)

    def test_board_import_failure_never_holds(self):
        self.assertEqual(self.main_inproc(None, code=6, SCRUM_CPU_LOAD_PCT="400"), (6, "", True))

    def test_hold_error_never_holds(self):
        self.assertIsNone(load().machine_hold(None))
        for boom in (RuntimeError("boom"), SystemExit("board says no")):
            with self.subTest(boom=boom):
                board = self.board(boom)
                self.assertIsNone(load().machine_hold(board))
                self.assertEqual(self.main_inproc(board, code=6), (6, "", True))


class HeavyStepsLogTest(unittest.TestCase):
    """Job 1244: buildlock.py appends one line per run to heavy-steps.log (SCRUM_HEAVY_STEPS_LOG overrides it) and
    never changes the exit code over it."""
    setUp, tearDown, run_wrap = BuildLockTest.setUp, BuildLockTest.tearDown, BuildLockTest.run_wrap
    LINE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ check work wait=\d+\.\ds run=\d+\.\ds load5=\d+\.\d\d "
                      r"cores=\d+$")

    def wrap_in(self, *args, **env):
        work = self.dir / "work"
        work.mkdir(exist_ok=True)
        return subprocess.run([sys.executable, str(SCRIPT), *args], env={**self.env, **env}, cwd=work,
                              capture_output=True, text=True, timeout=30)

    def test_one_line_per_run_and_exit_code_kept(self):
        lock = str(self.dir / "sub" / "check.lock")
        self.assertEqual(self.wrap_in("exit 3", SCRUM_BUILD_LOCK=lock).returncode, 3)
        self.assertEqual(self.wrap_in("exit 0", SCRUM_BUILD_LOCK=lock).returncode, 0)
        lines = (self.dir / "heavy-steps.log").read_text().splitlines()
        self.assertEqual(len(lines), 2, lines)
        for line in lines:
            self.assertRegex(line, self.LINE)

    def test_run_seconds_measured(self):
        self.wrap_in(sys.executable, "-c", "import time; time.sleep(1.2)", SCRUM_BUILD_LOCK=str(self.dir / "sub" / "check.lock"))
        run = float(re.search(r" run=(\d+\.\d)s ", (self.dir / "heavy-steps.log").read_text()).group(1))
        self.assertGreaterEqual(run, 1.2)

    def test_unwritable_log_keeps_exit_code(self):
        bad = self.dir / "is-a-dir"
        bad.mkdir()
        r = self.wrap_in("exit 5", SCRUM_HEAVY_STEPS_LOG=str(bad))
        self.assertEqual((r.returncode, r.stderr), (5, ""))
        r = self.wrap_in("exit 0", SCRUM_HEAVY_STEPS_LOG=str(self.dir / "missing" / "deeper" / "x.log"))
        self.assertEqual(r.returncode, 0)

    def test_trims_to_5000_past_10000(self):
        log = self.dir / "heavy-steps.log"
        log.write_text("".join(f"old {i}\n" for i in range(10000)))
        self.wrap_in("exit 0", SCRUM_BUILD_LOCK=str(self.dir / "sub" / "check.lock"))
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 5000)
        self.assertEqual(lines[0], "old 5001")
        self.assertRegex(lines[-1], self.LINE)

    def test_no_trim_at_10000(self):
        log = self.dir / "heavy-steps.log"
        log.write_text("".join(f"old {i}\n" for i in range(9999)))
        self.wrap_in("exit 0", SCRUM_BUILD_LOCK=str(self.dir / "sub" / "check.lock"))
        self.assertEqual(len(log.read_text().splitlines()), 10000)


if __name__ == "__main__":
    unittest.main()
