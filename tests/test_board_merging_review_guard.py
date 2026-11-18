import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
import board  # noqa: E402


class MergingReviewGuardTest(unittest.TestCase):
    """Job 1044: a fast or standard job cannot reach merging with no review file (a shop session skipped it)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.id = board.cmd_new(self.root, "x")

    def test_fast_without_review_refused_then_allowed(self):
        board.cmd_set(self.root, self.id, ["lane=fast"])
        with self.assertRaises(SystemExit) as e:
            board.cmd_set(self.root, self.id, ["stage=merging"])
        self.assertIn("review-code.md", str(e.exception))
        r = self.root / "jobs" / self.id / "round-1"
        r.mkdir(parents=True)
        (r / "review-code.md").write_text("VERDICT: PASS\n")
        board.cmd_set(self.root, self.id, ["stage=merging"])

    def test_lilguy_and_decision_exempt(self):
        board.cmd_set(self.root, self.id, ["lane=lilguy", "stage=merging"])
        other = board.cmd_new(self.root, "y")
        board.cmd_set(self.root, other, ["lane=standard"])
        (self.root / "jobs" / other / "decision.md").write_text("APPROVE\n")
        board.cmd_set(self.root, other, ["stage=merging"])


if __name__ == "__main__":
    unittest.main()
