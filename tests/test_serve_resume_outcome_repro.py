"""Job 527 repro: a dashboard resume run that exits and leaves the old needs-human question on the board gets an
`outcome` line, so Trevor sees his Carry on click ran. A resume that hits a new blocker re-asks and replaces the
question instead."""
import json, os, sys, tempfile, time, unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
import serve  # noqa: E402

board = serve.board
AT_4_21_PM = datetime(2026, 10, 22, 16, 21, 5).timestamp()
DIRTY_Q = "Uncommitted change in repo: README.md. Stash or commit them yourself, then pick Keep my changes and carry on."


class ResumeOutcomeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.root = self.repo / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        for patch in (mock.patch.object(board, "merge_refusal", return_value=None),
                      mock.patch.object(board, "projects", return_value={"repo": self.repo}),
                      mock.patch.object(board, "session_alive_fn", return_value=lambda job: False),
                      mock.patch.dict(os.environ, {"SCRUM_USAGE": str(Path(self.tmp.name) / "no-usage.json")})):
            patch.start()
            self.addCleanup(patch.stop)

    def job(self, job_id):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id)

    def parked(self):
        job_id = board.cmd_new(self.root, "Merge stopped on the main checkout guard")
        board.cmd_ask(self.root, job_id, DIRTY_Q,
                      [f"Keep my changes and carry on=resume {job_id}", f"Remove this job=abort {job_id} --cascade"],
                      recommend=("a", "the change is Trevor's own"))
        return job_id

    def run_resume(self, job_id, script):
        """Start a real dashboard resume run (serve.spawn via resume_job) whose claude stub runs `script`."""
        stub = Path(self.tmp.name) / "claude"
        stub.write_text("#!/bin/sh\n" + script)
        stub.chmod(0o755)
        with mock.patch.object(serve.board, "CLAUDE", str(stub)):
            serve.resume_job("repo", self.root, self.job(job_id), [self.job(job_id)], manual=True)
        self.addCleanup(lambda: serve.RUNS.pop(f"repo/{job_id}", None))
        run = serve.RUNS[f"repo/{job_id}"]
        run["proc"].wait(10)
        os.utime(self.root / run["log"], (AT_4_21_PM, AT_4_21_PM))
        return run

    def test_resume_run_leaving_old_question_writes_outcome(self):
        job_id = self.parked()
        run = self.run_resume(job_id, "printf '\\n## Action Needed: push it or merge anyway\\nDetails.\\n'\n")
        self.assertEqual(run["action"], "resume")
        self.assertEqual(run.get("reason"), DIRTY_Q, "spawn records the spawn-time reason for a resume run")
        self.assertEqual(serve.record_outcomes("repo", self.root), [job_id])
        job = self.job(job_id)
        self.assertEqual(job["outcome"], "Resume refused at 4:21 PM: Action Needed: push it or merge anyway. Nothing changed.")
        self.assertEqual(job["stage"], "needs-human")
        self.assertEqual(job["reason"], DIRTY_Q)

    def test_resume_new_blocker_replaces_question(self):
        job_id = self.parked()
        new_q = "Unpushed commits in repo: the main copy has commits that are not on GitHub."
        self.run_resume(job_id, "")
        board.cmd_ask(self.root, job_id, new_q, [f"Carry on=resume {job_id}", f"Remove this job=abort {job_id} --cascade"],
                      recommend=("a", "push first"))
        self.assertEqual(serve.record_outcomes("repo", self.root), [])
        job = self.job(job_id)
        self.assertEqual(job["stage"], "needs-human")
        self.assertEqual(job["question"], new_q)
        self.assertEqual(job["reason"], new_q)
        self.assertEqual([o["label"] for o in job["options"]], ["Carry on", "Remove this job"])
        self.assertEqual(job["recommend"], {"key": "a", "why": "push first"})
        self.assertNotIn("outcome", job)

    def test_killed_resume_gets_no_outcome(self):
        job_id = self.parked()
        proc = mock.Mock()
        proc.poll.return_value = -15
        with serve.RUNS_LOCK:
            serve.RUNS[f"repo/{job_id}"] = {"action": "resume", "started": time.time(), "proc": proc,
                                            "log": "runs/none.log", "reason": DIRTY_Q}
        self.addCleanup(lambda: serve.RUNS.pop(f"repo/{job_id}", None))
        self.assertEqual(serve.record_outcomes("repo", self.root), [])
        self.assertNotIn("outcome", self.job(job_id))


if __name__ == "__main__":
    unittest.main()
