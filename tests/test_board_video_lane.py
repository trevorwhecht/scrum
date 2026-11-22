"""Job 1340: the video lane. A job whose feature.md names a `Video folder:` runs lane=video, which has no worktree,
PR, Check gate or Merge; board.py stores the lane, lets a PR-less video job finish as done, keeps it out of
process-health's not_shipped, and the shop Mac's `## Cannot run` list keeps it on the main Mac."""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # never the real home
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))
os.environ["SCRUM_MUTE"] = "1"
os.environ.setdefault("SCRUM_PS", os.devnull)
import board  # noqa: E402

JOB = "200-owa-order-ad"


class VideoLaneTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "repo" / "scrum"
        (self.root / "jobs" / JOB).mkdir(parents=True)
        (self.root / "project.md").write_text("# Project\n- Test: x\n")
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=str(self.base / "projects.json"),
                              SCRUM_PULSE=str(self.base / "pulse.log"),
                              SCRUM_WINDOWS_FLAGGED=str(self.base / "flagged.json"))
        env.start()
        self.addCleanup(env.stop)

    def board(self, *jobs):
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"updatedAt": board.now(), "reason": None, **j} for j in jobs]}))

    def job(self, job_id):
        return board.find(board.read_board(self.root), job_id)

    def test_set_lane_video(self):
        self.board({"id": JOB, "stage": "spec"})
        board.cmd_set(self.root, JOB, ["lane=video"])
        self.assertEqual(self.job(JOB)["lane"], "video")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, JOB, ["lane=movie"])
        self.assertEqual(self.job(JOB)["lane"], "video")

    def test_video_done_without_pr(self):
        self.assertIsNone(board.merge_refusal({"lane": "video", "pr": None}))
        self.board({"id": JOB, "stage": "review", "lane": "video"})
        board.cmd_set(self.root, JOB, ["stage=done"])
        self.assertEqual(self.job(JOB)["stage"], "done")

    def test_standard_still_needs_pr(self):
        self.assertEqual(board.merge_refusal({"lane": "standard", "pr": None}), "not done: no PR recorded")
        self.assertEqual(board.merge_refusal({"pr": None}), "not done: no PR recorded")
        self.board({"id": "201-plain", "stage": "review", "lane": "standard"})
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, "201-plain", ["stage=done"])
        self.assertEqual(self.job("201-plain")["stage"], "review")

    def test_video_not_flagged_not_shipped(self):
        self.board({"id": JOB, "stage": "done", "lane": "video", "pr": None, "reason": "approved"},
                   {"id": "201-plain", "stage": "done", "lane": "standard", "pr": None, "reason": "merged"})
        d = self.root / "digests" / "001"
        d.mkdir(parents=True)
        (d / "jobs.txt").write_text(f"{JOB}\n201-plain\n")
        out = io.StringIO()
        with redirect_stdout(out):
            board.main(["--dir", str(self.root), "process-health", "001"])
        self.assertEqual(json.loads(out.getvalue())["metrics"]["not_shipped"]["jobs"], ["201-plain"])

    def test_video_terms_keep_job_on_main(self):
        # No workers.txt beside SCRUM_REGISTRY: shop.workers() is the default shopmac worker, read from the real notes.
        self.assertFalse((self.base / "workers.txt").exists())
        terms = board.main_only_terms()
        for term in ("Blender", "saas-animation", "vid-img-editing", "Video folder"):
            self.assertIn(term, terms)
        self.assertTrue(board.names_main_only(
            "Video folder: ~/Developer/vid-img-editing/motion/video/owa-order-ad", terms))
        self.assertFalse(board.names_main_only("Fix the widget", terms))


if __name__ == "__main__":
    unittest.main()
