"""Job 1497: e2e_runaway_tick stops a job E2E lock holder's group on a runaway footprint or low disk, disk_alert_tick
texts low disk, claude_missing_tick texts a missing claude CLI. Real `sleep`-like processes stand in for holders."""
import json, os, signal, subprocess, sys, tempfile, threading, time, unittest
from datetime import datetime
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
os.environ["SCRUM_PULSE"] = os.path.join(tempfile.mkdtemp(), "pulse.log")
import serve  # noqa: E402

REAL_LARGEST = serve.largest_process
SLEEP = "import time; time.sleep(300)"


def alive(pid):
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def gone(pid, wait=30.0):
    end = time.time() + wait
    while alive(pid):
        if time.time() > end:
            return False
        time.sleep(0.1)
    return True


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.procs = []
        self.addCleanup(self.cleanup)
        home = self.tmp / "home"
        (home / ".claude" / "trevskills-scrum").mkdir(parents=True)
        env = {"HOME": str(home), "SCRUM_FREE_DISK_GB": "50", "SCRUM_PULSE": str(self.tmp / "pulse" / "pulse.log")}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.repo = self.tmp / "repo"
        (self.repo / "scrum" / "jobs" / "1497-runaway-test").mkdir(parents=True)
        self.wt = self.tmp / "wt"
        (self.wt / "sub").mkdir(parents=True)
        (self.repo / "scrum" / "board.json").write_text(json.dumps(
            {"jobs": [{"id": "1497-runaway-test", "stage": "check", "worktree": str(self.wt)}]}))
        for target, value in (("projects", {"p": self.repo}),):
            q = mock.patch.object(serve.board, target, return_value=value)
            q.start()
            self.addCleanup(q.stop)
        q = mock.patch.object(serve, "port_listeners", return_value=set())
        q.start()
        self.addCleanup(q.stop)
        q = mock.patch.object(serve.board, "log_process")
        self.log = q.start()
        self.addCleanup(q.stop)
        self.marker = self.repo / "scrum" / "jobs" / "1497-runaway-test" / "e2e-stopped.json"

    def cleanup(self):
        for p in self.procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except OSError:
                pass
            try:
                p.kill()
            except OSError:
                pass

    def start(self, argv, **kw):
        kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, **kw}
        p = subprocess.Popen(argv, start_new_session=True, **kw)
        self.procs.append(p)
        threading.Thread(target=p.wait, daemon=True).start()  # reap, so a stopped group leaves no zombie
        return p

    def holder(self, cwd=None):
        """A lock holder: a shell that runs a next-server-named sleeper in its own group. Returns (holder, server pid)."""
        cmd = f"{sys.executable} -c '{SLEEP}' next-server & echo $!; wait"
        p = self.start(["sh", "-c", cmd], stdout=subprocess.PIPE)
        child = int(p.stdout.readline())
        p.stdout.close()
        slot = Path.home() / ".claude" / "trevskills-scrum" / "e2e.lock"
        serve.buildlock.holder_path(slot).write_text(f"{p.pid}\n{cwd or self.wt / 'sub'}\n{int(time.time())}")
        return p, child

    def server(self):
        return self.start([sys.executable, "-c", SLEEP, "next-server"])


class RunawayTest(Base):
    def test_no_holder_runs_nothing(self):
        with mock.patch.object(serve, "processes") as ps, mock.patch.object(serve.subprocess, "run") as run:
            self.assertEqual(serve.e2e_runaway_tick(footprint=lambda p: self.fail("footprint")), [])
        ps.assert_not_called()
        run.assert_not_called()

    def test_under_limits_stops_nothing(self):
        h, child = self.holder()
        self.assertEqual(serve.e2e_runaway_tick(footprint=lambda p: 2.0), [])
        self.assertTrue(alive(h.pid) and alive(child))
        self.assertFalse(self.marker.exists())
        self.log.assert_not_called()

    def test_over_memory_stops_only_that_group(self):
        h, child = self.holder()
        outside, inside_other_group = self.server(), self.start(["sleep", "300"])
        seen = []
        out = serve.e2e_runaway_tick(footprint=lambda p: seen.append(p) or 13.0)
        self.assertEqual(out, [f"{h.pid}:memory"])
        self.assertEqual(seen, [child])  # only the holder's tree is measured
        self.assertTrue(gone(h.pid) and gone(child))
        self.assertTrue(alive(outside.pid) and alive(inside_other_group.pid))
        self.log.assert_called_once_with("E2E runaway stop", "stopped", reason="memory", pid=h.pid, gb=13.0,
                                         job="1497-runaway-test")

    def test_healthy_dev_server_keeps_running(self):
        h, child = self.holder()
        self.assertEqual(serve.e2e_runaway_tick(footprint=lambda p: 9.4), [])
        self.assertTrue(alive(h.pid) and alive(child))
        self.assertFalse(self.marker.exists())
        self.log.assert_not_called()

    def test_outside_tree_never_signalled(self):
        h, child = self.holder()
        outside = self.server()
        with mock.patch.object(serve, "port_listeners", return_value={outside.pid}):
            serve.e2e_runaway_tick(footprint=lambda p: 13.0)
        self.assertTrue(gone(h.pid) and gone(child))
        self.assertTrue(alive(outside.pid))  # outside the tree, even though it listens on a kept port

    def test_kept_port_in_tree_stops_nothing(self):
        h, child = self.holder()
        with mock.patch.object(serve, "port_listeners", return_value={child}):
            self.assertEqual(serve.e2e_runaway_tick(footprint=lambda p: 13.0), [])
        self.assertTrue(alive(h.pid) and alive(child))

    def test_low_disk_stops_holder_group(self):
        h, child = self.holder()
        with mock.patch.dict(os.environ, {"SCRUM_FREE_DISK_GB": "2"}):
            out = serve.e2e_runaway_tick(footprint=lambda p: 1.0)
        self.assertEqual(out, [f"{h.pid}:disk"])
        self.assertTrue(gone(h.pid) and gone(child))
        self.assertEqual(json.loads(self.marker.read_text())["reason"], "disk")

    def test_unreadable_footprint_stops_nothing(self):
        h, child = self.holder()
        self.assertEqual(serve.e2e_runaway_tick(footprint=lambda p: None), [])
        self.assertTrue(alive(h.pid) and alive(child))

    def test_stop_writes_marker_and_counts(self):
        h, _ = self.holder()
        serve.e2e_runaway_tick(now=123.0, footprint=lambda p: 13.0)
        self.assertEqual(json.loads(self.marker.read_text()), {"reason": "memory", "count": 1, "at": 123.0})
        self.assertTrue(gone(h.pid))
        self.holder()
        serve.e2e_runaway_tick(now=456.0, footprint=lambda p: 13.0)
        self.assertEqual(json.loads(self.marker.read_text()), {"reason": "memory", "count": 2, "at": 456.0})

    def test_main_checkout_run_stops_without_marker(self):
        other = self.tmp / "main"
        other.mkdir()
        h, _ = self.holder(cwd=other)
        self.assertEqual(serve.e2e_runaway_tick(footprint=lambda p: 13.0), [f"{h.pid}:memory"])
        self.assertTrue(gone(h.pid))
        self.assertFalse(self.marker.exists())

    def test_tick_cost_with_run_live(self):
        self.holder()
        start = time.time()
        serve.e2e_runaway_tick(footprint=lambda p: 1.0)
        took = time.time() - start
        print(f"e2e_runaway_tick with a live holder: {took:.3f}s", file=sys.stderr)
        self.assertLess(took, 1.0)

    def test_footprint_parser(self):
        out = CompletedProcess([], 0, stdout="====\nnode [9]: 64-bit    Footprint: 17 GB (16384 bytes per page)\n", stderr="")
        with mock.patch.object(serve.subprocess, "run", return_value=out):
            self.assertEqual(serve.footprint_gb(9), 17.0)
        out = CompletedProcess([], 0, stdout="Footprint: 2048 MB (x)", stderr="")
        with mock.patch.object(serve.subprocess, "run", return_value=out):
            self.assertEqual(serve.footprint_gb(9), 2.0)
        with mock.patch.object(serve.subprocess, "run", return_value=CompletedProcess([], 0, stdout="nothing", stderr="")):
            self.assertIsNone(serve.footprint_gb(9))
        with mock.patch.object(serve.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(serve.footprint_gb(9))


class AlertBase(Base):
    def setUp(self):
        super().setUp()
        self.sent = []
        for target, value in (("alert_missing", None), ("alert_argv", lambda t: ["send", "h", t]),
                              ("largest_process", "node pid 4242 (9.0 GB)")):
            q = mock.patch.object(serve, target, **({"side_effect": value} if callable(value) else {"return_value": value}))
            q.start()
            self.addCleanup(q.stop)
        self.ok = True

    def send(self, argv):
        self.sent.append(argv[-1])
        return CompletedProcess(argv, 0 if self.ok else 1, stdout="", stderr="bad")

    def pulse(self, free, now=1000.0):
        with mock.patch.dict(os.environ, {"SCRUM_FREE_DISK_GB": str(free)}):
            return serve.disk_alert_tick(now, send=self.send)


class DiskAlertTest(AlertBase):
    def test_disk_alert_two_pulses_once_per_episode(self):
        self.assertIsNone(self.pulse(2))  # a single low pulse
        self.assertEqual(len(self.sent), 0)
        text = self.pulse(2)
        self.assertEqual(self.sent, [text])
        self.assertIn("pid 4242", text)
        self.assertIn("2.0 GB free", text)
        self.assertNotRegex(text, r"^\w+:")
        self.assertIsNone(self.pulse(2))  # a third low pulse, same episode
        self.assertEqual(len(self.sent), 1)
        for _ in range(5):
            self.pulse(50)
        self.assertIsNone(self.pulse(2))  # 5 clear pulses did not end the episode
        self.pulse(2)
        self.assertEqual(len(self.sent), 1)
        for _ in range(6):
            self.pulse(50)
        self.assertIsNone(self.pulse(2))
        self.assertIsNotNone(self.pulse(2))  # a new episode texts again
        self.assertEqual(len(self.sent), 2)

    def test_disk_alert_failed_send_retried(self):
        self.ok = False
        self.pulse(2)
        self.assertIsNone(self.pulse(2))
        self.assertEqual(len(self.sent), 1)
        self.ok = True
        self.assertIsNotNone(self.pulse(2))
        self.assertEqual(len(self.sent), 2)
        self.assertIsNone(self.pulse(2))
        self.assertEqual(len(self.sent), 2)

    def test_stuck_alert_keeps_disk_keys(self):
        self.pulse(2)
        serve.stuck_alert(2000.0, None, 1)
        state = json.loads((Path(os.environ["SCRUM_PULSE"]).parent / "stuck-alert.json").read_text())
        self.assertEqual((state["dlow"], state["dclear"]), (1, 0))

    def test_missing_alert_to_marks_sent_without_text(self):
        with mock.patch.object(serve, "alert_missing", return_value="alert-to.txt"):
            self.pulse(2)
            self.assertIsNone(self.pulse(2))
        self.assertEqual(self.sent, [])
        self.assertIn("dsent", json.loads((Path(os.environ["SCRUM_PULSE"]).parent / "stuck-alert.json").read_text()))

    def test_largest_process_prefers_footprint(self):
        ps = CompletedProcess([], 0, stdout="10 900 /bin/aaa\n11 800 /usr/bin/node /x/next-server\n12 5 /bin/z\n", stderr="")
        real = REAL_LARGEST
        with mock.patch.object(serve.subprocess, "run", return_value=ps), \
                mock.patch.object(serve, "footprint_gb", side_effect=lambda pid: {10: 0.5, 11: 17.0, 12: 1.0}[pid]):
            self.assertEqual(real(), "node next-server pid 11 (17.0 GB)")
        with mock.patch.object(serve.subprocess, "run", return_value=ps), mock.patch.object(serve, "footprint_gb", return_value=None):
            self.assertIn("pid 10", real())


class ClaudeMissingTest(AlertBase):
    def fail_spawn(self):
        with mock.patch.object(serve.board, "read_board", side_effect=OSError), \
                mock.patch.object(serve.board, "pick_account", return_value=(None, None)), \
                mock.patch.object(serve.board, "spawn", side_effect=FileNotFoundError("claude")):
            with self.assertRaises(FileNotFoundError):
                serve.spawn("p", self.repo / "scrum", "digest", "digest", "go")

    def record(self):
        return json.loads((Path(os.environ["SCRUM_PULSE"]).parent / "claude-missing.json").read_text())

    def tick(self, now, ok=False):
        return serve.claude_missing_tick(now, probe=lambda: ok, send=self.send)

    def test_claude_missing_one_pulse_no_text(self):
        with mock.patch.object(serve.time, "time", return_value=1000.0):
            self.fail_spawn()
        self.assertEqual(self.record(), {"since": 1000.0, "sent": None})
        self.assertIsNone(self.tick(1060.0))
        self.assertEqual(self.sent, [])

    def test_claude_missing_past_5_minutes_one_text(self):
        with mock.patch.object(serve.time, "time", return_value=1000.0):
            self.fail_spawn()
        with mock.patch.object(serve.time, "time", return_value=1100.0):
            self.fail_spawn()
        self.assertEqual(self.record()["since"], 1000.0)  # the first failure is kept
        text = self.tick(1300.0)
        self.assertIn("npm install -g @anthropic-ai/claude-code", text)
        self.assertNotRegex(text, r"^\w+:")
        self.assertIsNone(self.tick(1360.0))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.record()["sent"], 1300.0)

    def test_claude_missing_back_clears(self):
        with mock.patch.object(serve.time, "time", return_value=1000.0):
            self.fail_spawn()
        self.assertIsNone(self.tick(1400.0, ok=True))
        self.assertFalse((Path(os.environ["SCRUM_PULSE"]).parent / "claude-missing.json").exists())
        self.assertEqual(self.sent, [])
        with mock.patch.object(serve.time, "time", return_value=5000.0):
            self.fail_spawn()
        self.assertEqual(self.record(), {"since": 5000.0, "sent": None})
        self.assertIsNotNone(self.tick(5300.0))  # a new episode texts again

    def test_successful_spawn_clears_record(self):
        with mock.patch.object(serve.time, "time", return_value=1000.0):
            self.fail_spawn()
        proc = mock.Mock(pid=1)
        with mock.patch.object(serve.board, "read_board", side_effect=OSError), \
                mock.patch.object(serve.board, "pick_account", return_value=(None, None)), \
                mock.patch.object(serve.board, "spawn", return_value=(proc, "log")):
            serve.spawn("p", self.repo / "scrum", "digest", "digest", "go")
        self.assertFalse((Path(os.environ["SCRUM_PULSE"]).parent / "claude-missing.json").exists())

    def test_no_record_does_nothing(self):
        probe = mock.Mock(return_value=False)
        self.assertIsNone(serve.claude_missing_tick(9999.0, probe=probe, send=self.send))
        probe.assert_not_called()


class TailnetDownTest(AlertBase):
    """Job 1652: tailnet_down_tick runs tailscale up once, then texts once, per episode."""

    def setUp(self):
        super().setUp()
        self.ups = 0
        q = mock.patch.object(serve, "TAILNET", {"mac.tail.ts.net"})
        q.start()
        self.addCleanup(q.stop)

    def up(self):
        self.ups += 1

    def tick(self, state, now=1000.0):
        return serve.tailnet_down_tick(now, state=lambda: state, up=self.up, send=self.send)

    def record(self):
        return Path(os.environ["SCRUM_PULSE"]).parent / "tailnet-down.json"

    def test_unset_tailnet_does_nothing(self):
        with mock.patch.object(serve, "TAILNET", set()):
            self.assertIsNone(self.tick("Stopped"))
            self.assertIsNone(self.tick("Stopped", 1060.0))
        self.assertEqual((self.ups, self.sent), (0, []))
        self.assertFalse(self.record().exists())

    def test_one_up_then_one_text_no_repeat(self):
        self.assertIsNone(self.tick("Stopped", 1000.0))
        self.assertEqual((self.ups, self.sent), (1, []))
        text = self.tick("Stopped", 1060.0)
        self.assertEqual(text, "Tailscale stopped on this Mac, so the phone dashboard link is down. Open Tailscale or run tailscale up.")
        self.assertNotRegex(text, r"^\w+:")
        for n in range(3):
            self.assertIsNone(self.tick("NeedsLogin", 1120.0 + n))
        self.assertEqual((self.ups, len(self.sent)), (1, 1))
        self.assertEqual(json.loads(self.record().read_text())["sent"], 1060.0)

    def test_running_clears_episode(self):
        self.tick("Stopped", 1000.0)
        self.tick("Stopped", 1060.0)
        self.assertIsNone(self.tick("Running", 1120.0))
        self.assertFalse(self.record().exists())
        self.tick("Stopped", 2000.0)
        self.assertIsNotNone(self.tick("Stopped", 2060.0))  # a new episode: up again, text again
        self.assertEqual((self.ups, len(self.sent)), (2, 2))

    def test_unreadable_state_is_no_pulse(self):
        self.assertIsNone(self.tick(None))
        self.assertEqual(self.ups, 0)


class SigninAlertTest(AlertBase):
    """Job 1527: signin_alert_tick texts once per account and end date, read from each account's newest run log."""
    NOW = datetime(2026, 11, 23, 12).timestamp()

    def setUp(self):
        super().setUp()
        owa = self.tmp / "home" / ".claude-owa"
        owa.mkdir()
        accs = json.dumps([["main", str(self.tmp / "home" / ".claude"), None], ["owa", str(owa), None]])
        q = mock.patch.dict(os.environ, {"SCRUM_ACCOUNTS": accs})
        q.start()
        self.addCleanup(q.stop)
        (self.repo / "scrum" / "runs").mkdir()
        self.jobs = []

    def runlog(self, job, account, text, age):
        name = f"runs/{job}.log"
        path = self.repo / "scrum" / name
        path.write_text(text + "\nrest of the run\n")
        os.utime(path, (self.NOW - age, self.NOW - age))
        self.jobs.append({"id": job, "stage": "done", "account": account, "runlog": name})
        (self.repo / "scrum" / "board.json").write_text(json.dumps({"jobs": self.jobs}))

    def warn(self, a, b):
        return f"Warning: this sign-in ends between {a} and {b} (in 4 days at the earliest). Renewing it does not move those dates."

    def tick(self, days=0):
        return serve.signin_alert_tick(self.NOW + days * 86400, send=self.send)

    def test_main_text_once_per_end_date(self):
        self.runlog("1-old", "main", self.warn("2026-12-20", "2026-12-23"), 600)
        self.runlog("2-new", "main", self.warn("2026-11-27", "2026-11-30"), 60)
        self.runlog("2b-running", "main", "", 0)
        (self.repo / "scrum" / "runs" / "2b-running.log").write_text("")  # a running session's log is still empty
        text = self.tick()
        self.assertIn("The main Claude sign-in ends between 2026-11-27 and 2026-11-30", text)
        self.assertIn("Run claude auth login before 2026-11-27", text)
        self.assertNotIn("CLAUDE_CONFIG_DIR", text)
        self.assertNotRegex(text, r"^\w+:")
        self.assertIsNone(self.tick(1))
        self.assertEqual(len(self.sent), 1)
        self.runlog("3-renewed", "main", self.warn("2027-01-05", "2027-01-08"), 0)
        self.assertIsNone(self.tick(1))  # 43 days out: no text
        self.assertIsNone(self.tick(37))
        self.assertIsNotNone(self.tick(38))  # the new end date texts once more
        self.assertEqual(len(self.sent), 2)

    def test_owa_names_config_dir(self):
        self.runlog("1-main", "main", "no warning here", 0)
        self.runlog("2-owa", "owa", self.warn("2026-11-28", "2026-12-01"), 0)
        text = self.tick()
        self.assertIn("The owa Claude sign-in", text)
        self.assertIn("Run CLAUDE_CONFIG_DIR=~/.claude-owa claude auth login before 2026-11-28", text)

    def test_far_or_missing_end_no_text(self):
        self.runlog("1-main", "main", self.warn("2026-11-29", "2026-12-02"), 0)  # 6 days away
        self.assertIsNone(self.tick())
        self.assertEqual(self.sent, [])
        self.assertIsNotNone(self.tick(1))

    def test_failed_send_retried(self):
        self.runlog("1-main", "main", self.warn("2026-11-27", "2026-11-30"), 0)
        self.ok = False
        self.assertIsNone(self.tick())
        self.ok = True
        self.assertIsNotNone(self.tick())
        self.assertIsNone(self.tick())
        self.assertEqual(len(self.sent), 2)


if __name__ == "__main__":
    unittest.main()
