"""Repro (onewitharts 1091, 2026-11-18): a nested BigBoy parent (a Run-all/BigBoy child that New job 3c converted to
lane bigboy) gets a second final review. Its last child's session merged and ran `B set <parent> stage=review` (BigBoy
step 7), then kept running the review under the child's own id. Four minutes later the watchdog started the parent
again (`start`, manual false): sweep_parents' respawn_orphans sees a child of the running grandparent sitting in a
WATCHED stage (review) with no board update for ORPHAN_MINUTES, no tracked run and no ps line of its own id, and the
parent has no worktree, so it spawns `start`. The live session belongs to the parent's own child."""
import json, unittest
from datetime import datetime, timedelta

import test_serve  # its WatchdogIdleParentTest fixture, reached through the module so discover does not rerun it


class NestedBigBoyReviewReproTest(unittest.TestCase):
    _F = test_serve.WatchdogIdleParentTest
    setUp, job, tick = _F.setUp, _F.job, _F.tick  # reuse, without rerunning its tests

    def board_with_review_owned_by_child(self, grand_lane):
        four_min_ago = (datetime.now().astimezone() - timedelta(minutes=4)).isoformat(timespec="seconds")
        now = self.board.now()
        jobs = [
            {"id": "001-gp", "stage": "running", "lane": grand_lane, "children": ["002-par"], "updatedAt": now},
            # the nested BigBoy parent: its last child's session set stage=review 4 min ago and is reviewing it now
            {"id": "002-par", "stage": "review", "lane": "bigboy", "parent": "001-gp",
             "children": ["003-kid", "004-last"], "updatedAt": four_min_ago},
            {"id": "003-kid", "stage": "done", "parent": "002-par", "updatedAt": four_min_ago},
            {"id": "004-last", "stage": "done", "parent": "002-par", "updatedAt": four_min_ago},
        ]
        for j in jobs:
            j.setdefault("reason", None)
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))

    def test_parent_in_review_owned_by_live_child_session_is_not_started_again(self):
        live_child = lambda job: job["id"] == "004-last"  # the child's session (tracked run and ps line) runs the review
        for grand_lane in ("runall", "bigboy"):
            with self.subTest(grandparent=grand_lane):
                self.serve.ORPHAN_RESPAWN.clear()
                self.board_with_review_owned_by_child(grand_lane)
                spawns = []
                for _ in range(2):  # the same state on the next tick must not start it either
                    spawn, _, _ = self.tick(alive=live_child, running=lambda project, job_id: job_id == "004-last")
                    spawns += [c.args[2:4] for c in spawn.call_args_list]
                self.assertEqual(
                    [s for s in spawns if s[0] == "002-par"], [],
                    "the watchdog started the BigBoy parent 002-par while its child 004-last's live session runs "
                    "its final review (second final review, onewitharts 1091)")
                self.assertEqual(self.job("002-par")["stage"], "review")


if __name__ == "__main__":
    unittest.main()
