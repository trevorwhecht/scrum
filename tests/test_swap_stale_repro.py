"""Repro for job 759: on 2026-11-10 the swap verdict blocked every claim at 71% free RAM with 2 sessions. The real
swap log ($TMPDIR/scrum-swap-log.json) showed swap falling over the window (33.6 -> 36.7 -> 27.9 -> 26.3) and then a
rebound (29.2): a fall-then-rebound is not growth, yet swap_grew compares against the window's lowest reading."""
import json, os, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "trevskills-scrum"))
import board  # noqa: E402


class StaleSwap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "swap.json"
        self.ps = Path(self.tmp.name) / "ps.txt"
        self.ps.write_text("   30:00 claude -p /trevskills-scrum run-all\n   05:00 claude -p /trevskills-scrum start 1-a\n")
        env = mock.patch.dict(os.environ, SCRUM_FREE_RAM="71", SCRUM_SWAP_LOG=str(self.log), SCRUM_PS=str(self.ps),
                              SCRUM_COOLDOWN=os.path.join(os.devnull, "no"), SCRUM_CPU_BUSY_PCT="1",
                              SCRUM_CPU_LOAD_PCT="1", SCRUM_FREE_DISK_GB="1000", SCRUM_MUTE="1")
        env.start()
        self.addCleanup(env.stop)

    def falling_then_rebound(self):
        # ages in seconds, readings in % of RAM: net down 6.6 points over the window, one dip, then back up
        samples = [(590, 33.6), (580, 36.65), (470, 34.3), (400, 27.9), (230, 27.1), (100, 24.5)]
        self.log.write_text(json.dumps([[time.time() - age, v] for age, v in samples]))

    def test_stale_swap_does_not_block(self):
        self.falling_then_rebound()
        with mock.patch.dict(os.environ, SCRUM_SWAP_PCT="27"):
            self.assertIsNone(board.machine_ok(self.tmp.name, claim=True), "swap fell over the window: not growing")
        self.falling_then_rebound()
        self.ps.write_text("   30:00 claude -p /trevskills-scrum run-all\n   00:30 claude -p /trevskills-scrum start 1-a\n")
        with mock.patch.dict(os.environ, SCRUM_SWAP_PCT="27"):
            self.assertEqual(board.ram_room(floor=0), 9, "71% free (over 2x min): no young cap, 51 // 5 - 1 young")


if __name__ == "__main__":
    unittest.main()
