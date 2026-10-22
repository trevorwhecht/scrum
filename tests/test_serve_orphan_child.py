"""Repro: a chaining child ran `board.py ready` (a sibling waiting -> spec) and ended without spawning it. sweep_parents
skips every parent with a child outside board.IDLE, so the claimed child sits in spec with no session forever."""
import json, unittest
from datetime import datetime, timedelta

import test_serve  # its WatchdogIdleParentTest fixture: one board, a mocked tick

Fixture = test_serve.WatchdogIdleParentTest


class OrphanChildReproTest(unittest.TestCase):
    setUp, write, job, tick = Fixture.setUp, Fixture.write, Fixture.job, Fixture.tick  # reuse, without rerunning its tests

    def test_claimed_child_never_started_gets_started(self):
        old = (datetime.now().astimezone() - timedelta(minutes=4)).isoformat(timespec="seconds")
        for lane in ("runall", "bigboy"):
            with self.subTest(lane=lane):
                self.serve.__dict__.get("ORPHAN_RESPAWN", {}).clear()
                self.write("running", {"002-claimed": "spec", "003-wait": "waiting"}, lane=lane)
                data = json.loads((self.root / "board.json").read_text())
                data["jobs"][1]["updatedAt"] = old
                (self.root / "board.json").write_text(json.dumps(data))
                spawn, ready, _ = self.tick()
                self.assertEqual([c.args for c in spawn.call_args_list],
                                 [("idle", self.root, "002-claimed", "start", "/trevskills-scrum start 002-claimed")])
                ready.assert_not_called()
                self.assertEqual(self.job("003-wait")["stage"], "waiting")


if __name__ == "__main__":
    unittest.main()
