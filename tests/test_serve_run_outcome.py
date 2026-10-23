"""A dashboard approve/rework run that leaves its job where it was writes a one-line `outcome`; a Discuss click shows
in /api/runs while its claude process lives."""
import json, os, subprocess, sys, tempfile, threading, time, unittest, urllib.request
from datetime import datetime
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
import serve  # noqa: E402

board = serve.board
AT_4_21_PM = datetime(2026, 10, 22, 16, 21, 5).timestamp()  # local time, as serve.py formats it


class RunOutcomeTest(unittest.TestCase):
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

    def parked(self, reason="SKILL.md is over its size budget"):
        job_id = board.cmd_new(self.root, "Parked job")
        board.cmd_ask(self.root, job_id, reason, [f"A=approve {job_id}", f"B=abort {job_id}"])
        return job_id

    def exited(self, job_id, action, code, log_text, reason="SKILL.md is over its size budget"):
        """A RUNS entry for a finished dashboard run, as spawn leaves it, with its log written at 4:21 PM."""
        log = self.root / "runs" / f"x-{action}-{job_id}.log"
        log.parent.mkdir(exist_ok=True)
        log.write_text(log_text)
        os.utime(log, (AT_4_21_PM, AT_4_21_PM))
        proc = mock.Mock()
        proc.poll.return_value = code
        key = f"repo/{job_id}"
        with serve.RUNS_LOCK:
            serve.RUNS[key] = {"action": action, "started": time.time(), "proc": proc, "log": f"runs/{log.name}",
                               "reason": reason}
        self.addCleanup(lambda: serve.RUNS.pop(key, None))

    def test_refused_approve_sets_outcome_and_stays_needs_human(self):
        job_id = self.parked()
        board.cmd_set(self.root, job_id, ["outcome=Old outcome"])
        stub = Path(self.tmp.name) / "claude"
        stub.write_text("#!/bin/sh\nprintf '\\n  \\n## Can not merge: SKILL.md is over its size budget.\\nDetails.\\n'\n")
        stub.chmod(0o755)
        with mock.patch.object(serve, "CLAUDE", str(stub)):
            serve.approve_job("repo", self.root, job_id)
        self.addCleanup(lambda: serve.RUNS.pop(f"repo/{job_id}", None))
        run = serve.RUNS[f"repo/{job_id}"]
        self.assertEqual(run["reason"], "SKILL.md is over its size budget")
        self.assertIsNone(self.job(job_id).get("outcome"), "a new run never shows the old run's outcome")
        run["proc"].wait(10)
        os.utime(self.root / run["log"], (AT_4_21_PM, AT_4_21_PM))
        serve.watchdog_tick()
        job = self.job(job_id)
        self.assertEqual(job["outcome"],
                         "Approve refused at 4:21 PM: Can not merge: SKILL.md is over its size budget. Nothing changed.")
        self.assertEqual(job["stage"], "needs-human")
        self.assertEqual(job["reason"], "SKILL.md is over its size budget")

    def test_rework_refusal_and_failed_exit_wording(self):
        a, b = self.parked(), self.parked()
        self.exited(a, "rework", 0, "- **Nope, the blocker is still there**\n")
        self.exited(b, "approve", 2, "* " + "x" * 200 + "\n")
        self.assertEqual(sorted(serve.record_outcomes("repo", self.root)), sorted([a, b]))
        self.assertEqual(self.job(a)["outcome"], "Rework refused at 4:21 PM: Nope, the blocker is still there**. Nothing changed.")
        self.assertEqual(self.job(b)["outcome"], f"Approve failed (exit 2) at 4:21 PM: {'x' * 160}. Nothing changed.")

    def test_empty_log_has_no_message(self):
        job_id = self.parked()
        self.exited(job_id, "approve", 0, "\n   \n")
        serve.record_outcomes("repo", self.root)
        self.assertEqual(self.job(job_id)["outcome"], "Approve refused at 4:21 PM. Nothing changed.")

    def test_new_blocker_or_moved_job_gets_no_outcome(self):
        new_reason, moved, aborted, stopped = (self.parked() for _ in range(4))
        board.cmd_ask(self.root, new_reason, "A different blocker", [f"A=approve {new_reason}", f"B=abort {new_reason}"])
        board.cmd_set(self.root, moved, ["stage=done"])
        board.cmd_abort(self.root, aborted, False)
        for job_id in (new_reason, moved, aborted):
            self.exited(job_id, "approve", 0, "Refused.\n")
        self.exited(stopped, "rework", -15, "Refused.\n")
        self.assertEqual(serve.record_outcomes("repo", self.root), [])
        for job_id in (new_reason, moved, aborted, stopped):
            self.assertNotIn("outcome", self.job(job_id), job_id)

    def test_handled_once(self):
        job_id = self.parked()
        self.exited(job_id, "approve", 0, "Refused.\n")
        self.assertEqual(serve.record_outcomes("repo", self.root), [job_id])
        board.cmd_set(self.root, job_id, ["outcome=Trevor cleared it"])
        self.assertEqual(serve.record_outcomes("repo", self.root), [])
        self.assertEqual(self.job(job_id)["outcome"], "Trevor cleared it")


class BoardGetAndDiscussTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.root = self.repo / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        patch = mock.patch.object(board, "projects", return_value={"repo": self.repo})
        patch.start()
        self.addCleanup(patch.stop)
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as res:
            return json.loads(res.read())

    def test_board_get_writes_outcome(self):
        job_id = board.cmd_new(self.root, "Parked job")
        board.cmd_ask(self.root, job_id, "Blocked", [f"A=approve {job_id}", f"B=abort {job_id}"])
        proc = mock.Mock()
        proc.poll.return_value = 0
        with serve.RUNS_LOCK:
            serve.RUNS[f"repo/{job_id}"] = {"action": "approve", "started": 0, "proc": proc, "log": "runs/none.log",
                                            "reason": "Blocked"}
        self.addCleanup(lambda: serve.RUNS.pop(f"repo/{job_id}", None))
        job = next(j for j in self.get("/p/repo/board.json")["jobs"] if j["id"] == job_id)
        self.assertRegex(job["outcome"], r"^Approve refused at \d{1,2}:\d\d [AP]M\. Nothing changed\.$")

    def test_discuss_listed_while_process_alive(self):
        job_id = board.cmd_new(self.root, "Talk it over")
        board.cmd_ask(self.root, job_id, "Which way?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        others = mock.patch.dict(serve.DISCUSSES, clear=True)  # another test's Discuss click must not trigger ps here
        others.start()
        self.addCleanup(others.stop)
        real_run = subprocess.run
        with mock.patch.object(serve.subprocess, "run", wraps=real_run) as run:
            self.get("/api/runs")
            self.assertFalse([c for c in run.call_args_list if c.args and c.args[0][0] == "ps"],
                             "no discuss entry: no ps scan")
        before = time.time()
        r = urllib.request.Request(f"{self.base}/api/p/repo/jobs/{job_id}/discuss", method="POST", data=b"{}",
                                   headers={"Content-Type": "application/json"})
        with mock.patch.object(serve, "run_terminal", return_value=(200, {"message": "opened"})):
            with urllib.request.urlopen(r) as res:
                self.assertEqual(res.status, 200)
        after = time.time()
        stub = Path(self.tmp.name) / "claude"
        stub.write_text("#!/bin/sh\nsleep 30\n")
        stub.chmod(0o755)
        proc = subprocess.Popen([str(stub), f"/trevskills-scrum discuss {job_id}"])  # argv as the Terminal window has it
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        time.sleep(0.2)
        with mock.patch.object(serve, "DISCUSS_GRACE", 0):
            entry = [e for e in self.get("/api/runs") if e["id"] == job_id]
            self.assertEqual([(e["project"], e["action"], e["alive"]) for e in entry], [("repo", "discuss", True)])
            self.assertTrue(before <= entry[0]["started"] <= after)
            proc.kill()
            proc.wait()
            self.assertEqual([e for e in self.get("/api/runs") if e["id"] == job_id], [])
            self.assertNotIn(f"repo/{job_id}", serve.DISCUSSES)


if __name__ == "__main__":
    unittest.main()
