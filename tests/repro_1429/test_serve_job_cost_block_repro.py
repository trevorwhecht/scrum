"""Repro for job 1429: board.json waits on a job_costs transcript read (JOB_COST_LOCK is held for the whole read)
instead of serving the last known costs, so a poll takes as long as the 9.8 GB read."""
import os, sys, tempfile, threading, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))


class JobCostBlockReproTest(unittest.TestCase):
    def test_job_costs_returns_last_known_while_a_read_runs(self):
        import serve
        serve.JOB_COST_CACHE.clear()
        self.addCleanup(serve.JOB_COST_CACHE.clear)
        release, started = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        row = {"ts": 1, "model": "claude-opus-4-5", "project": "p", "job": "1-a", "agent": "main", "skill": None,
               "input_tokens": 0, "output_tokens": 1_000_000, "cache_read_input_tokens": 0,
               "cache_creation_input_tokens": 0}
        # last known costs, past their TTL so the next poll starts a refresh
        serve.JOB_COST_CACHE.update(at=time.monotonic() - serve.JOB_COST_TTL - 1, costs={"p": {"1-a": (1_000_000, 25.0)}})

        def slow(start, end, projects_dir=None):
            started.set()
            release.wait(30)
            return [row]

        with mock.patch.object(serve.board, "transcript_tokens", slow):
            threading.Thread(target=serve.job_costs, args=("p",), daemon=True).start()
            self.assertTrue(started.wait(5))
            got, done = [], threading.Event()

            def poll():
                got.append(serve.job_costs("p"))
                done.set()

            threading.Thread(target=poll, daemon=True).start()
            returned = done.wait(2)
            release.set()
        self.assertTrue(returned, "job_costs (board.json) waited on the running transcript read")
        self.assertEqual(got[0], {"1-a": (1_000_000, 25.0)})


if __name__ == "__main__":
    unittest.main()
