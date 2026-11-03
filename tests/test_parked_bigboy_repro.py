import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
os.environ.setdefault("SCRUM_PS", os.devnull)
import board  # noqa: E402


class ParkedBigboyReproTest(unittest.TestCase):
    """Job 573: a running BigBoy child whose own child waits on Trevor holds no Run-all slot."""

    def test_ready_claims_beside_parked_bigboy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "scrum"
            root.mkdir()
            job = lambda i, **kw: {"id": i, "title": i, "stage": "waiting", "updatedAt": "2026-01-01T00:00:00+00:00", **kw}
            jobs = [
                job("070-all", stage="running", lane="runall", children=["107-big", "108-a", "109-b"]),
                job("107-big", stage="running", lane="bigboy", parent="070-all", reason="waiting on you in: 285-gc", children=["285-gc"]),
                job("108-a", parent="070-all", lane="fast", parallel=True),
                job("109-b", parent="070-all", lane="fast", parallel=True),
                job("285-gc", parent="107-big", lane="fast", setup="pending"),
            ]
            (root / "board.json").write_text(json.dumps({"jobs": jobs}))
            with mock.patch.object(board, "usage_allowance", return_value=None):
                out = board.cmd_ready(root, "070-all")
            self.assertTrue(out["ready"], out)
            got = {j["id"]: j["stage"] for j in board.read_board(root)["jobs"]}
            self.assertEqual(got["070-all"], "running")


if __name__ == "__main__":
    unittest.main()
