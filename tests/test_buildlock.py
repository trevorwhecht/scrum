import fcntl, importlib.util, os, signal, subprocess, sys, tempfile, time, unittest
from pathlib import Path
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
        self.env = {**os.environ, "SCRUM_BUILD_LOCK": str(self.lock)}
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
        time.sleep(1.2)
        holder.kill()
        out, err = waiter.communicate(timeout=10)
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

    def test_missing_command_returns_127(self):
        self.assertEqual(self.run_wrap("no-such-cmd-buildlock-xyz", "arg").returncode, 127)
        self.assertEqual(self.run_wrap("no-such-cmd-buildlock-xyz").returncode, 127)
        with open(self.lock, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if the lock was left held


if __name__ == "__main__":
    unittest.main()
