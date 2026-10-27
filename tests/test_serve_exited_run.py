"""Repro: a dashboard-started `claude -p` start/resume run that exits while its job is still in a WATCHED stage
is never noticed by watchdog_tick; the job sits in its stage until the 30-minute watchdog flags it."""
import json, os, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_PS"] = os.devnull  # no live sessions unless a test says so, whatever this machine runs
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test runs top or reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
import serve  # noqa: E402

board = serve.board


class ExitedRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.root = self.repo / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        guard = mock.patch.object(board, "merge_refusal", return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    def job(self, job_id):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id)

    def edit_job(self, job_id, **fields):
        data = json.loads((self.root / "board.json").read_text())
        next(j for j in data["jobs"] if j["id"] == job_id).update(fields)
        (self.root / "board.json").write_text(json.dumps(data))

    def test_exited_start_run_respawns_resume_once(self):
        job_id = board.cmd_new(self.root, "Exited headless run")
        self.edit_job(job_id, stage="build", reason=None)  # updatedAt is fresh: the 30-minute watchdog won't fire
        key = f"repo/{job_id}"
        dead = mock.Mock()
        dead.poll.return_value = 0  # the `claude -p` start run ended its turn and exited
        with serve.RUNS_LOCK:
            serve.RUNS[key] = {"action": "start", "started": time.time(), "proc": dead, "log": "runs/x.log"}
        self.addCleanup(lambda: serve.RUNS.pop(key, None))

        def fake_spawn(project, root, jid, action, prompt, flags=()):
            proc = mock.Mock()
            proc.poll.return_value = None
            with serve.RUNS_LOCK:
                serve.RUNS[f"{project}/{jid}"] = {"action": action, "started": time.time(), "proc": proc,
                                                  "log": "runs/y.log"}
            return "runs/y.log"

        with mock.patch.object(board, "projects", return_value={"repo": self.repo}), \
                mock.patch.object(board, "session_alive_fn", return_value=lambda job: False), \
                mock.patch.object(serve, "spawn", side_effect=fake_spawn) as spawn, \
                mock.patch.object(board, "play") as play:
            serve.watchdog_tick()
            calls = lambda: [(c.args[2], c.args[3], c.args[4]) for c in spawn.call_args_list]
            self.assertEqual(calls(), [(job_id, "resume", f"/trevskills-scrum resume {job_id}")],
                             "the exited start run mid-build must be respawned as resume")
            self.assertEqual((self.job(job_id)["stage"], self.job(job_id)["stalled"]), ("build", True))
            self.assertEqual(self.job(job_id)["reason"], "stalled: session exited while the job was still in build.")
            # the respawned resume run's `B set --unpause stage=build reason=` drops `stalled`, then it exits too
            self.edit_job(job_id, stage="build", reason=None, stalled=None)
            serve.RUNS[key]["proc"].poll.return_value = 0
            serve.watchdog_tick()
            self.assertEqual(len(calls()), 1, "the auto-respawn happens only once")
        self.assertEqual((self.job(job_id)["stage"], self.job(job_id)["stalled"]), ("build", True))
        self.assertEqual(self.job(job_id)["reason"], "stalled: session exited while the job was still in build.")
        self.assertNotIn(mock.call(board.sound("needs-human")), play.call_args_list, "a stall plays no sound")


    def held_after_exit(self, line, now):
        """A start run that exited mid-build with `line` in its runlog; respawn_exited at time `now`.
        Returns (flagged ids, job id, spawn mock, play mock)."""
        job_id = board.cmd_new(self.root, "Limit-killed run")
        (self.root / "runs").mkdir(exist_ok=True)
        (self.root / "runs" / "x.log").write_text(f"working...\n{line}\n")
        self.edit_job(job_id, stage="build", reason="kept reason", runlog="runs/x.log")
        key = f"repo/{job_id}"
        dead = mock.Mock()
        dead.poll.return_value = 0
        serve.RUNS[key] = {"action": "start", "started": time.time(), "proc": dead, "log": "runs/x.log"}
        self.addCleanup(lambda: serve.RUNS.pop(key, None))
        with mock.patch.object(board, "session_alive_fn", return_value=lambda job: False), \
                mock.patch.object(serve.time, "time", return_value=now), \
                mock.patch.object(serve, "spawn") as spawn, mock.patch.object(board, "play") as play:
            flagged = serve.respawn_exited("repo", self.root)
        self.assertIs(serve.RUNS[key]["proc"], dead, "no new RUNS entry")
        return flagged, job_id, spawn, play

    def test_exited_limit_run_holds_stage(self):
        now = 1_800_000_000.0
        flagged, job_id, spawn, play = self.held_after_exit("rate_limit: rejected (five_hour) resets_at=1800003600", now)
        self.assertEqual(flagged, [])
        job = self.job(job_id)
        self.assertEqual((job["stage"], job["reason"], job["limitResetAt"]), ("build", "kept reason", 1800003600))
        spawn.assert_not_called()
        self.assertNotIn(mock.call(board.sound("needs-human")), play.call_args_list)

    def test_exited_limit_run_without_future_reset_holds_30_min(self):
        now = 1_800_000_000.0
        for line in ("You've hit your usage limit", "rate_limit: rejected (five_hour) resets_at=1799999880"):
            with self.subTest(line=line):
                flagged, job_id, spawn, _ = self.held_after_exit(line, now)
                self.assertEqual(flagged, [])
                self.assertEqual(self.job(job_id)["stage"], "build")
                self.assertEqual(self.job(job_id)["limitResetAt"], 1_800_001_800)
                spawn.assert_not_called()

    def test_exited_roadmap_job_logs_roadmap_step(self):
        step_job, child = "017-step-job", "018-child-fix"
        (self.root / "roadmap.md").write_text("ROADMAP: x\n## P1 A\n- [~] S1 standard 017-step-job: a\n"
                                              "- [~] S2 bigboy 019-other: b\n\n## Log\n- 2026-10-15 09:12 P1 S1 x\n")
        board.cmd_new(self.root, "Step job", step_job)
        board.cmd_new(self.root, "Child", child)
        self.edit_job(step_job, stage="build", reason=None)
        self.edit_job(child, stage="check", reason=None, parent="019-other")
        dead = mock.Mock()
        dead.poll.return_value = 0
        for jid in (step_job, child):
            serve.RUNS[f"repo/{jid}"] = {"action": "start", "started": time.time(), "proc": dead, "log": "runs/x.log"}
            self.addCleanup(lambda k=f"repo/{jid}": serve.RUNS.pop(k, None))
        with mock.patch.object(board, "session_alive_fn", return_value=lambda job: False), \
                mock.patch.object(serve, "resume_job") as resume:
            self.assertEqual(sorted(serve.respawn_exited("repo", self.root)), [step_job, child])
        self.assertEqual(sorted(c.args[2]["id"] for c in resume.call_args_list), [step_job, child])
        text = (self.root / "roadmap.md").read_text()
        self.assertIn("- [!] S1 standard 017-step-job: a\n- [!] S2 bigboy 019-other: b\n", text)
        logs = text.split("## Log\n")[1].strip().splitlines()
        self.assertEqual(len(logs), 3)
        self.assertRegex(logs[1] if "P1 S1" in logs[1] else logs[2], r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} P1 S1 stopped: "
                         r"017-step-job stalled: session exited while the job was still in build\.$")
        self.assertRegex(logs[2] if "P1 S2" in logs[2] else logs[1], r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} P1 S2 stopped: "
                         r"018-child-fix stalled: session exited while the job was still in check\.$")

if __name__ == "__main__":
    unittest.main()
