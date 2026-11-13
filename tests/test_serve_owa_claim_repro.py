"""Repro for job 810: after the account failover (809), with main limited and OWA free, watchdog_tick claimed
nothing. Real chain (onewitharts job 1063, 2026-11-13 09:16-09:17): a job held on main's limit was resumed early on
owa, its session declined in prose ("held by a usage limit"), limit_reset read that prose as a usage-limit exit, and
hold_limited held the job again on owa and wrote an owa limit_until marker. With both accounts marked, or with the
job held on its own (owa) account until its new reset, watchdog_tick's claim pass never ran."""
import json, os, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # pulse.log, weekly/ never in the real home
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_IDLE_CLEANUP"] = "0"  # a watchdog tick never signals a real dev server or quits Docker
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"

STALE = "waiting: usage 5h 99% used, resets 01:50 (allowance 0, 3 live)"  # left by a tick on the main account
# The tail of onewitharts runs/20261113-171617-resume-1063-...log: the resumed session declined, it hit no limit.
DECLINED = ("**Action Needed** — job 1063 is held by a usage limit until Sat Nov 14, 17:00 PST, so I did not "
            "resume it.\n\nResuming now would start agents that hit the same limit, so I spawned nothing.\n\n"
            "## Summary\n- **Action Needed**: the job is held until Nov 14, 17:00 PST by a usage limit.\n"
            "- Nothing was spawned, pushed or merged.\n")


class OwaClaimReproTest(unittest.TestCase):
    def setUp(self):
        import serve
        self.serve, self.board = serve, serve.board
        self.base = Path(tempfile.mkdtemp())
        self.main, self.owa = self.base / "main", self.base / "owa"
        self.main.mkdir()
        self.owa.mkdir()
        env = mock.patch.dict(os.environ, SCRUM_USAGE=str(self.main / "usage.json"), SCRUM_ACCOUNTS=json.dumps(
            [["main", str(self.main), None], ["owa", str(self.owa), [80, 90]]]))
        env.start()
        self.addCleanup(env.stop)
        self.reset = int(time.time()) + 86400
        (self.main / "limit_until").write_text(f"{self.reset}\n")  # main limited for a day; owa free
        for s in (serve.ORPHAN_RESPAWN, serve.STALL_RESUMED, serve.AUTO_RESUME, serve.RUNS):
            s.clear()
            self.addCleanup(s.clear)
        self.projects = {}

    def project(self, name, jobs):
        root = self.base / name / "scrum"
        (root / "jobs").mkdir(parents=True)
        (root / "project.md").write_text("# Project\n- Test: x\n")
        (root / "backlog.md").write_text("# Backlog\n")
        (root / "board.json").write_text(json.dumps({"jobs": [{"updatedAt": self.board.now(), "reason": None, **j}
                                                              for j in jobs]}))
        self.projects[name] = root.parent
        return root

    def runall(self):
        return [{"id": "041-run-all", "stage": "running", "lane": "runall", "reason": STALE,
                 "children": ["043-a", "044-b"]},
                {"id": "043-a", "stage": "waiting", "parent": "041-run-all"},
                {"id": "044-b", "stage": "waiting", "parent": "041-run-all"}]

    def tick(self):
        """One watchdog_tick; [(id, action, CLAUDE_CONFIG_DIR)] for every claude session it launched (each stays
        alive). git and the other subprocesses run for real; the GitHub Actions poll is skipped."""
        real = self.board.subprocess.Popen

        def popen(argv, **kw):
            if argv[1:2] != ["-p"]:
                return real(argv, **kw)
            proc = mock.Mock()
            proc.poll.return_value = None
            return proc

        with mock.patch.object(self.board, "projects", return_value=self.projects), \
                mock.patch.object(self.board, "session_alive_fn", return_value=lambda job: False), \
                mock.patch.object(self.serve, "actions_alert", return_value=None), \
                mock.patch.object(self.board.subprocess, "Popen", side_effect=popen) as p:
            self.serve.watchdog_tick()
        return [(c.args[0][2].split()[-1], c.args[0][2].split()[-2], c.kwargs["env"].get("CLAUDE_CONFIG_DIR"))
                for c in p.call_args_list if c.args[0][1:2] == ["-p"]]

    def test_stale_usage_wait_parent_claims_its_children_on_owa(self):
        root = self.project("mm", self.runall())
        self.assertIn(("043-a", "start", str(self.owa)), self.tick())
        self.assertIsNone(self.board.find(self.board.read_board(root), "041-run-all").get("reason"))

    def test_declined_failover_resume_neither_marks_owa_nor_stops_the_claims(self):
        # 1063 as it stood at 09:17: 809's failover resumed it on owa before main's reset (board.spawn recorded
        # account=owa and left limitResetAt), and that session has exited after declining in prose.
        held = {"id": "1063-held", "stage": "check", "lane": "fast", "limitResetAt": self.reset, "account": "owa",
                "runlog": "runs/resume-1063.log"}
        root = self.project("owa-held", [held])
        (root / "runs").mkdir()
        (root / "runs" / "resume-1063.log").write_text(DECLINED)
        done = mock.Mock()
        done.poll.return_value = 0
        self.serve.RUNS["owa-held/1063-held"] = {"action": "resume", "started": time.time() - 60, "proc": done,
                                                 "log": "runs/resume-1063.log", "account": None}
        self.project("mm", self.runall())
        started = self.tick()
        self.assertFalse((self.owa / "limit_until").exists(), "a session that declined in prose hit no owa limit")
        self.assertIn(("043-a", "start", str(self.owa)), started, "owa is free: the Run-all child must be claimed")


if __name__ == "__main__":
    unittest.main()
