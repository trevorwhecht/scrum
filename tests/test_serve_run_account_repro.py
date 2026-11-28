"""Repro (job 1220): a board job's run that died on account A's usage limit marks account B limited when the job's
board `account` moved to B before the tick (a shop dispatch's `account=`, a later spawn): serve.spawn keeps no
account for a board job's run, so note_run_limits reads the board job's current account instead."""
import json, os, stat, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # pulse.log, weekly/ never in the real home
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))  # never the real pulse.log (job 903)
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_IDLE_CLEANUP"] = "0"  # a watchdog tick never signals a real dev server or quits Docker
os.environ["SCRUM_PS"] = os.devnull  # no live sessions unless a test says so, whatever this machine runs
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_VM_PRESSURE"] = "1"  # kernel memory pressure normal unless a test says so; no test runs sysctl
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test runs top or reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ["SCRUM_NET_UP"] = "1"  # the network lookup passes unless a test says so; no test resolves api.anthropic.com
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
import serve  # noqa: E402

board = serve.board


class RunAccountTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(os.path.realpath(self.tmp.name))
        self.repo = base / "repo"
        self.root = self.repo / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        self.main, self.owa = base / "main", base / "owa"
        self.main.mkdir()
        self.owa.mkdir()
        accounts = json.dumps([["main", str(self.main), None], ["owa", str(self.owa), [80, 90]]])
        env = mock.patch.dict(os.environ, SCRUM_USAGE=str(self.main / "usage.json"), SCRUM_ACCOUNTS=accounts)
        env.start()
        self.addCleanup(env.stop)

    def test_window_tick_notes_the_limit_on_the_account_the_run_used(self):
        reset = int(time.time()) + 7200
        stub = Path(os.path.realpath(self.tmp.name)) / "claude"  # a `claude -p` that dies on its account's weekly limit
        stub.write_text(f"#!/bin/sh\necho \"You've hit your weekly limit · resets_at={reset}\"\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        job_id = board.cmd_new(self.root, "Cloud-home on main")
        key = f"repo/{job_id}"
        self.addCleanup(lambda: serve.RUNS.pop(key, None))
        with mock.patch.object(board, "CLAUDE", str(stub)), \
                mock.patch.object(board, "pick_account", return_value=("main", None)), \
                mock.patch.object(serve, "run_terminal"):
            serve.spawn("repo", self.root, job_id, "cloud-home", f"/trevskills-scrum cloud-home {job_id}")
        serve.RUNS[key]["proc"].wait(timeout=30)
        job = lambda: next(j for j in board.read_board(self.root)["jobs"] if j["id"] == job_id)
        self.assertEqual(job()["account"], "main", "board.spawn ran the session on main")
        board.cmd_set(self.root, job_id, ["account=owa"])  # serve.py shop dispatch: stage=cloud ... account=<its account>
        with mock.patch.object(board, "projects", return_value={"repo": self.repo}), \
                mock.patch.object(board, "cmd_window_report", return_value=[]), \
                mock.patch.object(board, "cmd_digest_due", return_value={"reason": "not due"}):
            serve.window_tick()
        now = time.time()
        self.assertEqual((board.limited_until("main", now), board.limited_until("owa", now)), (reset, None),
                         "the run died on main's limit: main is marked, owa (the board job's account now) is not")


if __name__ == "__main__":
    unittest.main()
