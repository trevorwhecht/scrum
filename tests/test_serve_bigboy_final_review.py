"""Repro: a finished BigBoy parent (every child done/aborted) whose last child skipped Merge step 7's chain-back sits at
stage running with no session forever. sweep_parents hits `if finished_bigboy(p, by_id): continue`, so nothing marks
it MAIN_FF and main_ff_tick never resumes it for its final review (lanes/bigboy.md step 7)."""
import json, unittest
from datetime import datetime, timedelta
from unittest import mock

import test_serve  # its WatchdogIdleParentTest fixture, reached through the module so discover does not rerun it

RESUME = ("001-par", "resume", "/trevskills-scrum resume 001-par")


class FinishedBigBoyReproTest(unittest.TestCase):
    _F = test_serve.WatchdogIdleParentTest
    setUp, write, job, tick = _F.setUp, _F.write, _F.job, _F.tick  # reuse, without rerunning its tests

    def finished(self, reason=None):
        self.write("running", {"002-done": "done", "003-gone": "aborted"}, lane="bigboy")
        old = (datetime.now().astimezone() - timedelta(minutes=10)).isoformat(timespec="seconds")
        data = json.loads((self.root / "board.json").read_text())
        for j in data["jobs"]:
            j["updatedAt"] = old
        data["jobs"][0]["reason"] = reason
        (self.root / "board.json").write_text(json.dumps(data))

    def run_tick(self, refusal=None):
        s = self.serve
        with mock.patch.object(s, "main_ready", return_value=True), \
                mock.patch.object(self.board, "cooling_down", return_value=False), \
                mock.patch.object(self.board, "machine_ok", return_value=refusal), \
                mock.patch.object(self.board, "ram_room", return_value=4), \
                mock.patch.object(self.board, "play") as play:
            spawn, _, _ = self.tick()
        return [c.args[2:] for c in spawn.call_args_list], play

    def test_finished_bigboy_parent_gets_final_review(self):
        stale = [None, "auto-played because no sessions were running; a pause left by an overload is no longer needed.",
                 "waiting on you in: 002-done"]
        for reason in stale:
            with self.subTest(reason=reason):
                self.serve.MAIN_FF_TRIED.clear()
                self.finished(reason)
                spawns, play = self.run_tick()
                self.assertEqual(spawns, [])
                play.assert_not_called()
                par = self.job("001-par")
                self.assertEqual((par["stage"], par["reason"]), ("running", "waiting: main fast-forward"))
                spawns, _ = self.run_tick(refusal="free RAM 9% (< 20%)")
                self.assertEqual(spawns, [], "machine guard holds the resume")
                self.assertEqual(self.job("001-par")["reason"], "waiting: main fast-forward")
                self.assertEqual(self.run_tick()[0], [RESUME])
                self.assertEqual(self.run_tick()[0], [], "MAIN_FF_TRIED: one resume per updatedAt")


class FamilyLiveFinalReviewTest(unittest.TestCase):
    """onewitharts 1091: a session of a BigBoy parent's own child (or its chain lock) owns the parent's final review, so
    no watchdog path (main_ff_tick, respawn_orphans, cmd_watchdog) starts or resumes the parent while it is live."""
    _F = test_serve.WatchdogIdleParentTest
    setUp, write, job, tick = _F.setUp, _F.write, _F.job, _F.tick  # reuse, without rerunning its tests

    def main_ff_parent(self):
        self.serve.MAIN_FF_TRIED.clear()
        self.write("running", {"002-done": "done", "003-last": "done"}, lane="bigboy")
        old = (datetime.now().astimezone() - timedelta(minutes=10)).isoformat(timespec="seconds")
        data = json.loads((self.root / "board.json").read_text())
        for j in data["jobs"]:
            j["updatedAt"] = old
        data["jobs"][0]["reason"] = "waiting: main fast-forward"
        (self.root / "board.json").write_text(json.dumps(data))

    def chain_lock(self, job_id):
        (self.root / "jobs" / job_id).mkdir(exist_ok=True)
        (self.root / "jobs" / job_id / ".chain.lock").write_text("003-last\n")

    def run_ticks(self, n, alive=lambda job: False, running=None):
        spawns = []
        with mock.patch.object(self.serve, "main_ready", return_value=True), \
                mock.patch.object(self.board, "cooling_down", return_value=False), \
                mock.patch.object(self.board, "machine_ok", return_value=None), \
                mock.patch.object(self.board, "ram_room", return_value=4), mock.patch.object(self.board, "play"):
            for _ in range(n):
                spawn, _, _ = self.tick(alive=alive, running=running)
                spawns += [c.args[2:] for c in spawn.call_args_list]
        return spawns

    def test_main_ff_parent_with_no_live_family_is_resumed(self):
        self.main_ff_parent()
        self.assertEqual(self.run_ticks(2), [RESUME], "a missed chain-back still recovers, once per updatedAt")

    def test_main_ff_parent_whose_child_session_is_live_is_not_resumed(self):
        cases = {"ps line": dict(alive=lambda job: job["id"] == "003-last"),
                 "tracked run": dict(running=lambda project, job_id: job_id == "003-last")}
        for name, kw in cases.items():
            with self.subTest(live=name):
                self.main_ff_parent()
                self.assertEqual(self.run_ticks(2, **kw), [])
                self.assertEqual(self.job("001-par")["stage"], "running")

    def test_main_ff_parent_with_live_chain_lock_is_not_resumed(self):
        self.main_ff_parent()
        self.chain_lock("001-par")
        self.assertEqual(self.run_ticks(2), [])

    def nested_review_parent(self, minutes):
        old = (datetime.now().astimezone() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
        jobs = [
            {"id": "001-gp", "stage": "running", "lane": "runall", "children": ["002-par"], "updatedAt": self.board.now()},
            {"id": "002-par", "stage": "review", "lane": "bigboy", "parent": "001-gp",
             "children": ["003-kid", "004-last"], "updatedAt": old},
            {"id": "003-kid", "stage": "done", "parent": "002-par", "updatedAt": old},
            {"id": "004-last", "stage": "done", "parent": "002-par", "updatedAt": old},
        ]
        for j in jobs:
            j["reason"] = None
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))

    def test_nested_review_parent_with_live_chain_lock_is_not_started(self):
        self.nested_review_parent(4)
        self.chain_lock("002-par")
        self.assertEqual([s for s in self.run_ticks(2) if s[0] == "002-par"], [])
        self.assertEqual(self.job("002-par")["stage"], "review")

    def test_nested_review_parent_with_no_live_family_is_still_started(self):
        self.nested_review_parent(4)
        self.assertEqual([s for s in self.run_ticks(2) if s[0] == "002-par"],
                         [("002-par", "start", "/trevskills-scrum start 002-par")])

    def test_cmd_watchdog_skips_review_parent_whose_child_session_is_live(self):
        self.nested_review_parent(35)
        self.assertEqual(self.board.cmd_watchdog(self.root, alive=lambda job: job["id"] == "004-last"), [])
        self.assertFalse(self.job("002-par").get("stalled"))
        self.chain_lock("002-par")
        self.assertEqual(self.board.cmd_watchdog(self.root, alive=lambda job: False), [])
        (self.root / "jobs" / "002-par" / ".chain.lock").unlink()
        self.assertEqual(self.board.cmd_watchdog(self.root, alive=lambda job: False), ["002-par"],
                         "with no live family the stalled parent is still flagged for auto_resume")


if __name__ == "__main__":
    unittest.main()
