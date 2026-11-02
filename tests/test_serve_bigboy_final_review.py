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


if __name__ == "__main__":
    unittest.main()
