import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ.pop("SCRUM_SHOP", None)  # a shop Mac sets it; cmd_set refuses lane=fast before B lilguy-fit (job 1400)
import board  # noqa: E402


class MergingReviewGuardTest(unittest.TestCase):
    """Job 1044: a fast or standard job cannot reach merging with no review file (a shop session skipped it)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.id = board.cmd_new(self.root, "x")

    def job(self, job_id):
        return next(j for j in board.read_board(self.root)["jobs"] if j["id"] == job_id)

    def stage(self, job_id):
        return self.job(job_id)["stage"]

    def test_fast_without_review_refused_then_allowed(self):
        board.cmd_set(self.root, self.id, ["lane=fast", "stage=review"])
        with self.assertRaises(SystemExit) as e:
            board.cmd_set(self.root, self.id, ["stage=merging"])
        self.assertIn("review-code.md", str(e.exception))
        self.assertEqual(self.stage(self.id), "review")
        r = self.root / "jobs" / self.id / "round-1"
        r.mkdir(parents=True)
        (r / "review-code.md").write_text("VERDICT: PASS\n")
        board.cmd_set(self.root, self.id, ["stage=merging"])
        self.assertEqual(self.stage(self.id), "merging")

    def test_standard_and_lane_in_same_call_refused(self):
        board.cmd_set(self.root, self.id, ["lane=standard", "stage=build"])
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, self.id, ["stage=merging"])
        other = board.cmd_new(self.root, "y")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, other, ["lane=fast", "stage=merging"])
        self.assertEqual(self.stage(self.id), "build")
        self.assertEqual((self.job(other)["stage"], self.job(other).get("lane")), ("spec", None))

    def test_lilguy_decision_and_human_approval_exempt(self):
        board.cmd_set(self.root, self.id, ["lane=lilguy", "stage=merging"])
        other = board.cmd_new(self.root, "y")
        board.cmd_set(self.root, other, ["lane=standard"])
        (self.root / "jobs" / other / "decision.md").write_text("APPROVE\n")
        board.cmd_set(self.root, other, ["stage=merging"])
        third = board.cmd_new(self.root, "z")
        board.cmd_set(self.root, third, ["lane=fast"])
        (self.root / "jobs" / third / "human-approval.md").write_text("Approved by Trevor 2026-11-18\n")
        board.cmd_set(self.root, third, ["stage=merging"])
        self.assertEqual([self.stage(i) for i in (self.id, other, third)], ["merging"] * 3)

    def test_job_already_merging_is_not_refused(self):
        # A job that reached merging before the guard existed can still be resumed there.
        board.cmd_set(self.root, self.id, ["stage=merging"])
        board.cmd_set(self.root, self.id, ["lane=fast"])
        board.cmd_set(self.root, self.id, ["stage=merging"])
        self.assertEqual(self.stage(self.id), "merging")


if __name__ == "__main__":
    unittest.main()
