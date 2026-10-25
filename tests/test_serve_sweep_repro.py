"""Repro for job 225: three serve.py watchdog sweep defects (limit-stalled job counted idle, stale chain lock
blocks forever, orphan respawn ignores resume_refusal)."""
import json, os, sys, tempfile, time, unittest
from datetime import datetime, timedelta
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_FREE_DISK_GB"] = "1000"

LIKELY = "# x\n## Likely files\n- `src/shared.py`: why\n- `src/{}.py`: why\n"


class SweepReproTest(unittest.TestCase):
    def setUp(self):
        import serve
        self.serve, self.board = serve, serve.board
        self.repo = Path(tempfile.mkdtemp()); self.root = self.repo / "scrum"
        (self.root / "jobs").mkdir(parents=True); (self.root / "runs").mkdir()
        env = mock.patch.dict(os.environ, SCRUM_USAGE=str(self.repo / "no-usage.json"))
        env.start(); self.addCleanup(env.stop)
        for s in (serve.LAST_BUSY, serve.ORPHAN_RESPAWN, serve.STALL_RESUMED, serve.AUTO_RESUME):
            s.clear(); self.addCleanup(s.clear)

    def write(self, jobs):
        for j in jobs:
            j.setdefault("updatedAt", self.board.now()); j.setdefault("reason", None)
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))

    def job(self, job_id):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id)

    def tick(self, alive=lambda job: False):
        s = self.serve
        with mock.patch.object(self.board, "projects", return_value={"p": self.repo}), \
                mock.patch.object(self.board, "session_alive_fn", return_value=alive), \
                mock.patch.object(s, "running", return_value=False), mock.patch.object(s, "spawn") as spawn:
            s.watchdog_tick()
        return [(c.args[2], c.args[3]) for c in spawn.call_args_list]

    def test_limit_stalled_job_resumed_blocks_run_all(self):
        (self.root / "project.md").write_text("# Project\n- Test: x\n- Auto continue: 1\n")
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Open item\n")
        (self.root / "runs" / "001-a.log").write_text("rate_limit: rejected (five_hour) resets_at=1700000000")
        # plan is not WATCHED, so a limit hit resumes it here rather than holding it in its stage
        self.write([{"id": "001-a", "stage": "needs-human", "reason": "stalled in plan: no live session",
                     "runlog": "runs/001-a.log"}])
        self.assertEqual(self.tick(), [("001-a", "resume")], "the resumed job makes the project busy: no run-all")

    def test_limit_stalled_build_job_held_in_its_stage_blocks_run_all(self):
        (self.root / "project.md").write_text("# Project\n- Test: x\n- Auto continue: 1\n")
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Open item\n")
        (self.root / "runs" / "001-a.log").write_text("rate_limit: rejected (five_hour) resets_at=1700000000")
        self.write([{"id": "001-a", "stage": "needs-human", "reason": "stalled in build: no live session",
                     "runlog": "runs/001-a.log"}])
        self.assertEqual(self.tick(), [], "held for its reset, and the held job makes the project busy: no run-all")
        self.assertEqual(self.job("001-a")["stage"], "build")
        self.assertIn("limitResetAt", self.job("001-a"))

    def test_stale_chain_lock_does_not_block(self):
        self.write([{"id": "001-par", "stage": "running", "lane": "runall", "children": ["002-done", "003-wait"]},
                    {"id": "002-done", "stage": "done", "parent": "001-par"},
                    {"id": "003-wait", "stage": "waiting", "parent": "001-par"}])
        lock = self.root / "jobs" / "001-par" / ".chain.lock"
        lock.parent.mkdir(); lock.write_text("002-done")
        old = time.time() - 3600  # older than board.CHAIN_LOCK_STALE (1800 s): a crashed chaining session
        os.utime(lock, (old, old))
        self.assertEqual(self.tick(), [("003-wait", "start")])

    def test_orphan_blocked_by_resume_blocker_stays_eligible(self):
        for jid in ("002-kid", "003-sib"):
            (self.root / "jobs" / jid).mkdir()
            (self.root / "jobs" / jid / "spec.md").write_text(LIKELY.format(jid))
        stale = (datetime.now().astimezone() - timedelta(minutes=4)).isoformat()
        self.write([{"id": "001-par", "stage": "running", "lane": "runall", "children": ["002-kid", "003-sib"]},
                    {"id": "002-kid", "stage": "spec", "parent": "001-par", "parallel": True, "updatedAt": stale},
                    {"id": "003-sib", "stage": "build", "parent": "001-par", "parallel": True}])
        self.assertEqual(self.tick(alive=lambda job: job["id"] == "003-sib"), [], "003-sib shares src/shared.py: 002-kid must wait")
        self.assertEqual(self.job("002-kid")["stage"], "spec")
        self.assertNotIn("p/002-kid", self.serve.ORPHAN_RESPAWN, "a refused orphan keeps its one attempt")


if __name__ == "__main__":
    unittest.main()
