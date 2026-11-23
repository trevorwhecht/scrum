"""Job 1362 (was job 1340's video lane): the edit lane. A job whose feature.md has a `Kind: edit-<kind>` line runs
lane=edit (lanes/edit.md), which has no worktree, PR, Check gate or Merge; board.py stores the lane and the kind, lets
a PR-less edit job finish as done, keeps it out of process-health's not_shipped, and the shop Mac's `## Cannot run`
list keeps it on the main Mac. A project whose project.md says `- Git: none` is a no-git project (board.no_git)."""
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
KINDS = ("edit-reel", "edit-animation", "edit-vector", "edit-photo")


class EditLaneTest(unittest.TestCase):
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

    def test_no_git_marker(self):
        self.assertFalse(board.no_git(self.root), "a project.md with no Git line is a git project")
        for text in ("# Project\n- Stack: none\n- Git: none\n- Test: none\n", "- Git: none"):
            (self.root / "project.md").write_text(text)
            self.assertTrue(board.no_git(self.root), text)
        for text in ("# Project\n- Git: yes\n", "# Project\nNotes: - Git: none is for folders\n",
                     "# Project\n- Git: none of it\n", "# Project\n- Gitlab: none\n"):
            (self.root / "project.md").write_text(text)
            self.assertFalse(board.no_git(self.root), text)
        (self.root / "project.md").unlink()
        self.assertFalse(board.no_git(self.root), "a missing project.md is False")
        (self.root / "project.md").mkdir()
        self.assertFalse(board.no_git(self.root), "an unreadable project.md is False")
        self.assertFalse(board.no_git(self.base / "nowhere" / "scrum"))

    def test_edit_kind(self):
        for kind in KINDS:
            self.assertEqual(board.edit_kind(f"Fix the reef reel\nKind: {kind}\nRuns on: main\n"), kind)
            self.assertEqual(board.edit_kind(f"Kind: {kind}"), kind)
        self.assertEqual(board.edit_kind("Kind: edit-movie\nKind: edit-photo\n"), "edit-photo", "the first valid line")
        for text in ("Retouch the hoodie shot\n", "Kind: edit-movie\n", "Kind: reel\n", "kind: edit-reel\n",
                     "Kind: edit-reel please\n", " Kind: edit-reel\n", ""):
            self.assertIsNone(board.edit_kind(text), text)

    def test_set_lane_edit_and_kind(self):
        self.board({"id": JOB, "stage": "spec"})
        board.cmd_set(self.root, JOB, ["lane=edit", "kind=edit-animation"])
        self.assertEqual((self.job(JOB)["lane"], self.job(JOB)["kind"]), ("edit", "edit-animation"))
        for pairs in (["lane=video"], ["lane=movie"], ["kind=reel"], ["kind=edit-movie"],
                      ["lane=standard", "kind=reel"], ["kind=edit-photo", "lane=video"]):
            with self.assertRaises(SystemExit, msg=pairs):
                board.cmd_set(self.root, JOB, pairs)
            self.assertEqual((self.job(JOB)["lane"], self.job(JOB)["kind"]), ("edit", "edit-animation"), pairs)

    def test_edit_done_without_pr(self):
        self.assertIsNone(board.merge_refusal({"lane": "edit", "pr": None}))
        self.assertEqual(board.merge_refusal({"lane": "video", "pr": None}), "not done: no PR recorded")
        self.board({"id": JOB, "stage": "review", "lane": "edit", "kind": "edit-animation"})
        board.cmd_set(self.root, JOB, ["stage=done"])
        self.assertEqual(self.job(JOB)["stage"], "done")

    def test_standard_still_needs_pr(self):
        self.assertEqual(board.merge_refusal({"lane": "standard", "pr": None}), "not done: no PR recorded")
        self.assertEqual(board.merge_refusal({"pr": None}), "not done: no PR recorded")
        self.board({"id": "201-plain", "stage": "review", "lane": "standard"})
        with self.assertRaises(SystemExit) as cm:
            board.cmd_set(self.root, "201-plain", ["stage=done"])
        self.assertEqual(str(cm.exception), "not done: no PR recorded")
        self.assertEqual(self.job("201-plain")["stage"], "review")

    def test_edit_not_flagged_not_shipped(self):
        self.board({"id": JOB, "stage": "done", "lane": "edit", "pr": None, "reason": "approved"},
                   {"id": "201-plain", "stage": "done", "lane": "standard", "pr": None, "reason": "merged"})
        d = self.root / "digests" / "001"
        d.mkdir(parents=True)
        (d / "jobs.txt").write_text(f"{JOB}\n201-plain\n")
        out = io.StringIO()
        with redirect_stdout(out):
            board.main(["--dir", str(self.root), "process-health", "001"])
        self.assertEqual(json.loads(out.getvalue())["metrics"]["not_shipped"]["jobs"], ["201-plain"])

    def test_edit_terms_keep_job_on_main(self):
        # No workers.txt beside SCRUM_REGISTRY: shop.workers() is the default shopmac worker, read from the real notes.
        self.assertFalse((self.base / "workers.txt").exists())
        terms = board.main_only_terms()
        for term in ("Kind: edit-reel", "Kind: edit-animation", "Kind: edit-vector", "Kind: edit-photo",
                     "PhotoCraft", "Blender", "saas-animation", "vid-img-editing", "Video folder"):
            self.assertIn(term, terms)
        self.assertNotIn("VectorCraft", terms)  # installed on the shop Mac (#866); an edit-vector job is held by its Kind line
        self.assertTrue(board.names_main_only("Kind: edit-photo\nretouch the hoodie shot", terms))
        self.assertTrue(board.names_main_only("Kind: edit-reel", terms))
        self.assertFalse(board.names_main_only("Claude edits the widget", terms))
        self.assertFalse(board.names_main_only("Fix the widget", terms))


if __name__ == "__main__":
    unittest.main()
