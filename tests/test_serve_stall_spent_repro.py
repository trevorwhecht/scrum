"""Repro for job 744: a standalone job stalled in check whose two auto-resumes are spent (STALL_RESUMES) is skipped by
auto_resume, yet board.resume_first still counts it, so auto_continue_tick never starts a run-all in that project.
Nothing resumes it and nothing new starts (onewitharts job 911, 2026-11-10). Spent retries must park it for Trevor
(needs-human with Resume / Abort), which frees the project."""
import json, os, sys, tempfile, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_IDLE_CLEANUP"] = "0"  # a watchdog tick never signals a real dev server or quits Docker
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test runs top or reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"


class StallSpentReproTest(unittest.TestCase):
    def setUp(self):
        import serve
        self.serve, self.board = serve, serve.board
        self.base = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, SCRUM_USAGE=str(self.base / "no-usage.json"))
        env.start(); self.addCleanup(env.stop)
        for s in (serve.ORPHAN_RESPAWN, serve.STALL_RESUMED, serve.AUTO_RESUME):
            s.clear(); self.addCleanup(s.clear)
        self.root = self.base / "owa" / "scrum"
        (self.root / "jobs" / "911-x").mkdir(parents=True)
        (self.root / "runs").mkdir()
        (self.root / "runs" / "20261110-183838-resume-911-x.log").write_text("")  # the empty 18:38 resume log
        (self.root / "project.md").write_text("# Project\n- Test: x\n- Auto continue: 1\n")
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Open item\n- [ ] Another item\n")
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": "911-x", "stage": "check", "stalled": True, "updatedAt": "2026-11-10T18:40:00+00:00",
             "reason": "stalled: no board update for 30 min and no live session. Fix: click Resume.",
             "runlog": "runs/20261110-183838-resume-911-x.log"}]}))
        serve.STALL_RESUMED.update({"owa/911-x/check", "owa/911-x/check#2"})  # the 18:11 and 18:38 resumes

    def tick(self):
        with mock.patch.object(self.board, "projects", return_value={"owa": self.root.parent}), \
                mock.patch.object(self.board, "session_alive_fn", return_value=lambda job: False), \
                mock.patch.object(self.serve, "running", return_value=False), \
                mock.patch.object(self.serve, "spawn") as spawn:
            self.serve.watchdog_tick()
        return [c.args[2] for c in spawn.call_args_list]

    def test_spent_stall_is_parked_for_trevor_and_frees_the_project(self):
        spawned = self.tick() + self.tick()
        job = json.loads((self.root / "board.json").read_text())["jobs"][0]
        self.assertEqual(job["stage"], "needs-human", "spent retries must park the job for Trevor, not wait silently")
        self.assertEqual(sorted(o["command"].split()[0] for o in job.get("options") or []), ["abort", "resume"])
        self.assertFalse(self.board.stalled(job), "a parked job is a question for Trevor, no longer a stall")
        self.assertEqual(self.board.resume_first([job]), 0)
        stop = (self.root / "jobs" / "911-x" / "stop.md").read_text()  # lanes/stops.md: logs go in stop.md
        self.assertIn("20261110-183838-resume-911-x.log", stop, "stop.md names the last run log")
        self.assertNotIn("911-x", spawned, "no third auto-resume")
        self.assertIn("run-all", spawned, "with the stall handed to Trevor, auto continue claims new work")


if __name__ == "__main__":
    unittest.main()
