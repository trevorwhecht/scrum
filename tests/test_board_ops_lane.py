"""Job 1423: board support for the ops lane (lanes/ops.md). A `Kind: ops-data|ops-content` line routes a job to
lane=ops: board.py stores the lane and kinds, lets a PR-less ops job finish, keeps it out of not_shipped, and accepts
the three ops stop titles."""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))
os.environ["SCRUM_MUTE"] = "1"
os.environ.setdefault("SCRUM_PS", os.devnull)
import board  # noqa: E402

JOB = "300-prod-data-run"


class OpsLaneTest(unittest.TestCase):
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

    def test_ops_kind(self):
        for kind in ("ops-data", "ops-content"):
            self.assertEqual(board.ops_kind(f"Run it\nKind: {kind}\nRuns on: main\n"), kind)
            self.assertEqual(board.ops_kind(f"Kind: {kind}"), kind)
        self.assertEqual(board.ops_kind("Kind: ops-other\nKind: ops-content\n"), "ops-content")
        for text in ("Kind: knowledge\n", "Kind: ops-other\n", "kind: ops-data\n", " Kind: ops-data\n",
                     "Kind: ops-data x\n", "Kind: edit-reel\n", ""):
            self.assertIsNone(board.ops_kind(text), text)
        self.assertEqual(board.edit_kind("Kind: edit-reel\n"), "edit-reel")
        self.assertIsNone(board.edit_kind("Kind: ops-data\n"))

    def test_set_lane_ops_and_kind(self):
        self.board({"id": JOB, "stage": "spec"})
        board.cmd_set(self.root, JOB, ["lane=ops", "kind=ops-data"])
        self.assertEqual((self.job(JOB)["lane"], self.job(JOB)["kind"]), ("ops", "ops-data"))
        for kind in ("ops-content", "knowledge", "edit-reel", "edit-animation", "edit-vector", "edit-photo", "edit-embroidery"):
            board.cmd_set(self.root, JOB, [f"kind={kind}"])
            self.assertEqual(self.job(JOB)["kind"], kind)
        board.cmd_set(self.root, JOB, ["kind=ops-data"])
        for bad in ("ops", "ops-movie", "reel"):
            with self.assertRaises(SystemExit, msg=bad):
                board.cmd_set(self.root, JOB, [f"kind={bad}"])
            self.assertEqual((self.job(JOB)["lane"], self.job(JOB)["kind"]), ("ops", "ops-data"), bad)

    def test_ops_done_without_pr(self):
        self.assertIsNone(board.merge_refusal({"lane": "ops", "pr": None}))
        self.assertEqual(board.merge_refusal({"lane": "standard", "pr": None}), "not done: no PR recorded")
        self.board({"id": JOB, "stage": "approve", "lane": "ops", "kind": "ops-data"})
        board.cmd_set(self.root, JOB, ["stage=done"])
        self.assertEqual(self.job(JOB)["stage"], "done")

    def test_ops_not_flagged_not_shipped(self):
        self.board({"id": JOB, "stage": "done", "lane": "ops", "pr": None, "reason": "approved"},
                   {"id": "301-plain", "stage": "done", "lane": "standard", "pr": None, "reason": "merged"})
        d = self.root / "digests" / "001"
        d.mkdir(parents=True)
        (d / "jobs.txt").write_text(f"{JOB}\n301-plain\n")
        out = io.StringIO()
        with redirect_stdout(out):
            board.main(["--dir", str(self.root), "process-health", "001"])
        self.assertEqual(json.loads(out.getvalue())["metrics"]["not_shipped"]["jobs"], ["301-plain"])

    def test_ops_stop_titles(self):
        stops = (ROOT / "skills" / "trevskills-scrum" / "lanes" / "stops.md").read_text()
        opts = [f"Go=approve {JOB}", f"Drop=abort {JOB} --cascade"]
        for key in ("CONTENT_QUESTIONS", "CONTENT_DRAFT", "DATA_RUN"):
            self.assertIn(f"`{key}`: ", stops)
            self.board({"id": JOB, "stage": "approve", "lane": "ops"})
            board.cmd_ask(self.root, JOB, "Which one?", opts, title=key)
            self.assertEqual(self.job(JOB)["stopTitle"], key)
        with self.assertRaises(SystemExit):
            board.cmd_ask(self.root, JOB, "Which one?", opts, title="OPS_OTHER")


if __name__ == "__main__":
    unittest.main()
