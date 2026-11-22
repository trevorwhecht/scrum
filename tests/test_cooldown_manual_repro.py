"""Repro for job 967: cool down overrides Trevor's own Play and Resume clicks.

Jobs: a session Trevor's click launched (serve.spawn manual=True), or one whose Play he queued (play_queued with
play_queued_manual), parked itself at New job's `board.py cooldown-park` checkpoint (job 962). Since job 1346 that
checkpoint is gone and cooldown-park never parks any job, manual or automatic.
BigBoy parents: a manual Resume on a running, unpaused parent held with reason `waiting: cooling down` is answered 409
and its next ready child is never claimed (BigBoy 960, child 963)."""
import os, sys, tempfile, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # never the real home
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))  # never the real pulse.log (job 903)
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))  # never Trevor's real usage.json
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_IDLE_CLEANUP"] = "0"
os.environ["SCRUM_PS"] = os.devnull  # no live sessions
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_VM_PRESSURE"] = "1"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # each test turns its own flag on
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"

class CooldownManualReproTest(unittest.TestCase):
    def setUp(self):
        import serve
        self.serve, self.board = serve, serve.board
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "repo" / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        flag = Path(tmp.name) / "cooldown"
        flag.write_text("")  # cool down is on
        for p in (mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(flag)),
                  mock.patch.object(self.board, "ram_room", return_value=5),
                  mock.patch.object(self.board, "cpu_load_pct", return_value=0.0),
                  mock.patch.object(self.board, "caller_claude_pid", return_value=None),
                  mock.patch.object(self.serve, "run_terminal", side_effect=AssertionError("no Terminal in tests"))):
            p.start()
            self.addCleanup(p.stop)
        self.assertTrue(self.board.cooling_down())

    def job(self, stage, by="hand", **extra):
        job_id = self.board.cmd_new(self.root, f"job in {stage}", started_by=by)
        self.board.cmd_set(self.root, job_id, [f"stage={stage}"])
        if extra:
            with self.board.locked_board(self.root) as b:
                self.board.find(b, job_id).update(extra)
        self.addCleanup(lambda: self.serve.RUNS.pop(f"repo/{job_id}", None))
        return job_id

    def get(self, job_id):
        return self.board.find(self.board.read_board(self.root), job_id)

    def launch(self, job_id, action, manual):
        with mock.patch.object(self.board, "spawn", return_value=(mock.Mock(), f"runs/{job_id}-{action}.log")) as bspawn:
            out = self.serve.spawn("repo", self.root, job_id, action, f"/trevskills-scrum {action} {job_id}", manual=manual)
        self.assertEqual(out, f"runs/{job_id}-{action}.log")
        bspawn.assert_called_once()
        self.serve.RUNS.pop(f"repo/{job_id}", None)  # the mocked session ended

    # job 1346: neither a Play Trevor queued (job 962's shape) nor an automatic queued launch is parked
    def test_cooldown_park_skips_queued_manual_click(self):
        for stage in ("spec", "build"):
            launch = {"action": "resume", "prompt": "/trevskills-scrum resume 962", "stage": stage}
            j = self.job(stage, play_queued="2026-11-18T06:20:45+00:00", play_queued_manual=True, queued_launch=launch)
            before = self.get(j)
            self.assertEqual(self.board.cmd_cooldown_park(self.root, j), {"parked": False}, stage)
            self.assertEqual(self.get(j), before, f"{stage}: a queued manual click writes nothing")
        launch = {"action": "start", "prompt": "/trevskills-scrum start x", "stage": "build"}
        auto = self.job("build", play_queued="2026-11-18T06:20:45+00:00", queued_launch=launch)
        self.assertEqual(self.board.cmd_cooldown_park(self.root, auto), {"parked": False})
        got = self.get(auto)
        self.assertFalse(got.get("stalled"))
        self.assertEqual((got["play_queued"], got["queued_launch"]), ("2026-11-18T06:20:45+00:00", launch))

    # job 1346: a play_queued_manual left over from an old park is kept and the job is not parked
    def test_cooldown_park_drops_stale_manual_marker(self):
        j = self.job("build", play_queued_manual=True)
        self.assertEqual(self.board.cmd_cooldown_park(self.root, j), {"parked": False})
        got = self.get(j)
        self.assertEqual((got["stage"], got.get("stalled"), got["play_queued_manual"]), ("build", None, True))

    # job 1346: neither a session Trevor's click launched nor a later automatic launch is parked
    def test_manual_launch_not_parked_at_checkpoint(self):
        for action in ("start", "resume"):
            j = self.job("spec")
            self.launch(j, action, manual=True)
            self.assertEqual(self.board.cmd_cooldown_park(self.root, j), {"parked": False}, f"{action}: manual")
            self.launch(j, "resume", manual=False)  # an automatic launch clears the mark
            self.assertEqual(self.board.cmd_cooldown_park(self.root, j), {"parked": False}, f"{action}: then automatic")
            got = self.get(j)
            self.assertEqual((got["stage"], got.get("stalled")), ("spec", None))

    # criteria 5 and 6: BigBoy 960 held by cool down; Trevor's Resume claims its next ready child, an automatic one does not
    def test_cooldown_play_on_held_parent_claims_next_child(self):
        b = self.board
        parent = b.cmd_new(self.root, "Big held", started_by="hand")
        (self.root / "jobs" / parent / "plan.md").write_text(
            "PLAN: READY\n# Big\n## Goal\nG.\n## Done when\n1. x\n## Tickets\n"
            "### T1: Probe\nDepends on: none\nParallel: yes — alone\nExposure: no\nHard stops: none\nHuman setup: none\nProbe it.\n"
            "### T2: Setup\nDepends on: none\nParallel: yes — alone\nExposure: no\nHard stops: none\nHuman setup: Log in\nSet up.\n"
            "### T3: Sync\nDepends on: T1\nParallel: yes — alone\nExposure: yes\nHard stops: none\nHuman setup: none\nSync it.\n")
        done, setup, ready = b.cmd_plan_apply(self.root, parent)["children"]
        (self.root / "jobs" / ready / "spec.md").write_text(f"## Likely files\n- `src/{ready}.py`\n")
        with b.locked_board(self.root) as board:
            b.find(board, done).update(stage="done")
            b.find(board, parent).update(stage="running", reason="waiting: cooling down")
            b.find(board, parent).pop("childSpecs", None)  # past BigBoy step 2, as `ready --specs-done` leaves it (job 1275)
        self.assertEqual((self.get(setup)["stage"], self.get(setup)["setup"]), ("waiting", "pending"))
        self.assertEqual((self.get(ready)["stage"], self.get(ready)["depends_on"]), ("waiting", [done]))
        self.assertNotIn("paused", self.get(parent))
        route = lambda body: self.serve.Handler.route(None, "repo", self.root, f"/jobs/{parent}/resume", body)

        with mock.patch.object(self.serve, "spawn") as spawn:
            code, out = route({})  # continue.py's automatic Resume
        self.assertEqual(code, 409, out)
        spawn.assert_not_called()
        self.assertEqual(self.get(ready)["stage"], "waiting", "an automatic Resume claims nothing")

        with mock.patch.object(self.serve, "spawn") as spawn:
            code, out = route({"manual": True})  # the dashboard's Play/Resume click
        self.assertEqual(code, 202, out)
        self.assertEqual(self.get(ready)["stage"], "spec")
        self.assertEqual(self.get(setup)["stage"], "waiting")
        self.assertEqual([(c.args[2:], c.kwargs.get("manual")) for c in spawn.call_args_list],
                         [((ready, "start", f"/trevskills-scrum start {ready}"), True)])


if __name__ == "__main__":
    unittest.main()
