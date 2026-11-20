"""Job 971: finish the task at hand before new work. No automatic new claim (backlog next, a Run-all or BigBoy child,
auto-continue, wake) in any project while a job anywhere waits on the Check or E2E queue, or a stalled job waits on
the machine gate; a stalled job whose own idle session is in the CPU load resumes past the cpu_load gate."""
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_VM_PRESSURE"] = "1"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
os.environ["SCRUM_SWAP_LOG"] = os.path.join(tempfile.mkdtemp(), "swap.json")
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_IDLE_CLEANUP"] = "0"
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))
import board  # noqa: E402
import serve  # noqa: E402

HOLD_E2E = "finishing work in flight first: other/050-queued waits on the E2E queue"


class FinishFirst(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.repo, self.other = base / "repo", base / "other"
        self.root = self.repo / "scrum"
        for r in (self.repo, self.other):
            (r / "scrum" / "jobs").mkdir(parents=True)
        (self.other / "scrum" / "board.json").write_text(json.dumps({"jobs": []}))
        reg = base / "projects.json"
        reg.write_text(json.dumps([str(self.repo), str(self.other)]))
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=str(reg), SCRUM_USAGE=str(base / "no-usage.json"))
        env.start()
        self.addCleanup(env.stop)
        guard = mock.patch.object(board, "merge_refusal", return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        play = mock.patch.object(board, "play")
        play.start()
        self.addCleanup(play.stop)

    # --- fixtures ---
    def other_jobs(self, *jobs):
        (self.other / "scrum" / "board.json").write_text(json.dumps({"jobs": list(jobs)}))

    def jobs(self):
        return {j["id"]: j for j in board.read_board(self.root)["jobs"]}

    def runall(self, n=2):
        (self.root / "backlog.md").write_text("".join(f"- [ ] item {chr(97 + i)}\n" for i in range(n)))
        out = board.cmd_runall_start(self.root)
        with board.locked_board(self.root) as b:  # past BigBoy step 2, as `ready --specs-done` leaves it (job 1275)
            board.find(b, out["id"]).pop("childSpecs", None)
        for i, k in enumerate(out["children"]):
            (self.root / "jobs" / k).mkdir(parents=True, exist_ok=True)
            (self.root / "jobs" / k / "spec.md").write_text(f"# x\n## Likely files\n- `src/f{i}.py`: why\n")
        return out["id"], out["children"]

    # --- (a) the hold ---
    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", 4)  # a heavy start counts 2 young
    def test_queue_wait_in_another_project_holds_child_claims(self):
        parent, (a, b) = self.runall()
        self.other_jobs({"id": "050-queued", "stage": "check", "reason": "waiting: E2E queue (lock busy)"})
        self.assertEqual(board.finish_first(self.root), HOLD_E2E)
        out = board.cmd_ready(self.root, parent)
        self.assertEqual(out["ready"], [])
        self.assertEqual(out["held"], HOLD_E2E)
        jobs = self.jobs()
        self.assertEqual((jobs[a]["stage"], jobs[b]["stage"]), ("waiting", "waiting"))
        self.assertEqual((jobs[parent]["stage"], jobs[parent]["reason"]), ("running", "waiting: " + HOLD_E2E))
        self.other_jobs({"id": "050-queued", "stage": "done"})
        self.assertIsNone(board.finish_first(self.root))
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [a, b], "claims again once the queue wait ends")

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", 4)  # a heavy start counts 2 young
    def test_trevor_click_claims_past_the_hold(self):
        parent, (a, b) = self.runall()
        self.other_jobs({"id": "050-queued", "stage": "check", "reason": "waiting: Check queue (lock busy)"})
        self.assertEqual(board.cmd_ready(self.root, parent, manual=True)["ready"], [a, b])

    def test_stalled_check_wait_holds_backlog_next_not_run_now(self):
        (self.root / "backlog.md").write_text("- [ ] Alpha\n- [ ] Beta\n")
        self.other_jobs({"id": "050-queued", "stage": "check", "stalled": True,
                         "reason": "stalled: waiting on the Check queue after two lock waits"})
        with self.assertRaises(SystemExit) as e:
            board.cmd_next(self.root)
        self.assertEqual(str(e.exception), "finishing work in flight first: other/050-queued waits on the Check queue: "
                                           "no new backlog claim. It claims again once that job moves on.")
        self.assertEqual((self.root / "backlog.md").read_text(), "- [ ] Alpha\n- [ ] Beta\n")
        self.assertEqual(board.cmd_next(self.root, 1)["feature"], "Beta", "Run now still claims")

    def test_build_queue_wait_holds_backlog_next(self):
        (self.root / "backlog.md").write_text("- [ ] Alpha\n")
        self.other_jobs({"id": "050-queued", "stage": "check", "reason": "waiting: Build queue"})
        with self.assertRaises(SystemExit) as e:
            board.cmd_next(self.root)
        self.assertEqual(str(e.exception), "finishing work in flight first: other/050-queued waits on the Build queue: "
                                           "no new backlog claim. It claims again once that job moves on.")
        self.assertEqual((self.root / "backlog.md").read_text(), "- [ ] Alpha\n")

    def test_paused_and_needs_human_never_hold(self):
        self.other_jobs({"id": "050-paused", "stage": "check", "paused": True, "reason": "waiting: E2E queue"},
                        {"id": "051-human", "stage": "needs-human", "reason": "stalled in build: no output"},
                        {"id": "052-paused-stall", "stage": "build", "stalled": True, "paused": True,
                         "reason": "stalled: waiting on the E2E queue"})
        with mock.patch.dict(os.environ, SCRUM_FREE_RAM="10"):
            self.assertIsNone(board.finish_first(self.root))

    def test_stalled_job_on_machine_gate_holds(self):
        self.other_jobs({"id": "060-stall", "stage": "build", "stalled": True,
                         "reason": "stalled: no board update for 30 min and no live session"})
        self.assertIsNone(board.finish_first(self.root), "the machine has room: auto_resume restarts it first")
        with mock.patch.dict(os.environ, SCRUM_FREE_RAM="10"):
            self.assertEqual(board.finish_first(self.root),
                             "finishing work in flight first: other/060-stall waits to resume (free RAM 10% (< 20%))")
        self.other_jobs({"id": "060-stall", "stage": "build", "stalled": True, "reason": "stalled: x",
                         "queued_launch": {"action": "resume", "prompt": "p", "stage": "build"}})
        self.assertEqual(board.finish_first(self.root),
                         "finishing work in flight first: other/060-stall waits to resume (its launch is queued)")

    def test_stalled_child_of_idle_parent_never_holds(self):
        self.other_jobs({"id": "070-parent", "stage": "running", "lane": "runall", "paused": True},
                        {"id": "071-kid", "parent": "070-parent", "stage": "build", "stalled": True, "reason": "stalled: x"})
        with mock.patch.dict(os.environ, SCRUM_FREE_RAM="10"):
            self.assertIsNone(board.finish_first(self.root))

    # --- (b) own idle session under the cpu_load gate ---
    def live_idle(self):
        return {"id": "080-idle", "stage": "build", "stalled": True,
                "reason": "stalled: no board or job-dir change for 2 h (session alive but idle)"}

    def test_resume_gate_skips_cpu_load_for_own_idle_session(self):
        cpu = f"CPU load 400% of {os.cpu_count()} cores (> 300%)"
        plain = {"id": "081-dead", "stage": "build", "stalled": True, "reason": "stalled: no live session"}
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT="400"):
            with mock.patch.object(board, "session_alive_fn", return_value=lambda j: True):
                self.assertIsNone(board.resume_gate(self.root, self.live_idle()))
                self.assertEqual(board.resume_gate(self.root, plain), cpu, "no live idle session: the gate holds")
                with mock.patch.dict(os.environ, SCRUM_FREE_RAM="10"):
                    self.assertEqual(board.resume_gate(self.root, self.live_idle()), "free RAM 10% (< 20%)")
                self.assertEqual(board.machine_ok(self.root, claim=True), cpu, "a new claim still waits on the load")
            with mock.patch.object(board, "session_alive_fn", return_value=lambda j: False):
                self.assertEqual(board.resume_gate(self.root, self.live_idle()), cpu, "its session died meanwhile")

    def test_resume_refusal_lets_own_idle_session_resume(self):
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT="400"), \
                mock.patch.object(board, "session_alive_fn", return_value=lambda j: True):
            self.assertIsNone(serve.resume_refusal("repo", self.root, self.live_idle()))
            self.assertTrue(serve.resume_refusal("repo", self.root, dict(self.live_idle(), reason="stalled: x"))
                            .startswith("waiting: CPU load 400%"))
            self.other_jobs(self.live_idle())
            self.assertIsNone(board.finish_first(self.root), "a resume that passes holds no claim")

    # --- serve.py claim paths ---
    def test_held_gate_token(self):
        self.assertEqual(serve.held_gate(HOLD_E2E), "finish_first")

    def test_wake_waiting_holds_plain_job_while_queue_waits(self):
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": "001-first", "stage": "done"},
            {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"]}]}))
        (self.root / "jobs" / "002-second").mkdir()
        self.other_jobs({"id": "050-queued", "stage": "check", "reason": "waiting: E2E queue"})
        with mock.patch.object(serve, "spawn") as spawn, mock.patch.object(board, "ram_room", return_value=2):
            serve.wake_waiting("repo", self.root)
            spawn.assert_not_called()
            self.assertEqual(self.jobs()["002-second"]["stage"], "waiting")
            self.assertEqual((self.root / "jobs" / "002-second" / "queue-gates.txt").read_text(), "finish_first\n")
            self.other_jobs()
            serve.wake_waiting("repo", self.root)
        self.assertEqual([c.args[2] for c in spawn.call_args_list], ["002-second"])

    def test_auto_continue_tick_starts_nothing_while_queue_waits(self):
        (self.root / "project.md").write_text("- Auto continue: 1\n")
        (self.root / "backlog.md").write_text("- [ ] Alpha\n")
        self.other_jobs({"id": "050-queued", "stage": "check", "reason": "waiting: Check queue"})
        with mock.patch.object(serve, "spawn") as spawn, mock.patch.object(serve, "running", return_value=False):
            serve.auto_continue_tick({"repo": False, "other": False})
            spawn.assert_not_called()
            self.other_jobs()
            serve.auto_continue_tick({"repo": False, "other": False})
        self.assertEqual([c.args[2] for c in spawn.call_args_list], ["run-all"])

    def test_idle_claim_keeps_queued_launch_drops_waiting_child(self):
        parent, (a, b) = self.runall(2)
        with board.locked_board(self.root) as bd:
            board.find(bd, b).update(stage="build", queued_launch={"action": "resume", "prompt": "p", "stage": "build"})
        self.other_jobs({"id": "050-queued", "stage": "check", "reason": "waiting: E2E queue"})
        jobs = list(self.jobs().values())
        with mock.patch.object(serve, "spawn", return_value="log") as spawn, \
                mock.patch.object(serve, "launched_since", return_value=False), \
                mock.patch.object(board, "session_alive_fn", return_value=lambda j: False), \
                mock.patch.object(serve, "IDLE_CLAIM_SECS", 0):
            serve.IDLE_SINCE.pop("repo", None)
            self.assertTrue(serve.idle_claim("repo", self.root, jobs))
        self.assertEqual([c.args[2:4] for c in spawn.call_args_list], [(b, "resume")])
        self.assertEqual(self.jobs()[a]["stage"], "waiting")


if __name__ == "__main__":
    unittest.main()
