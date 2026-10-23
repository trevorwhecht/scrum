import json, os, subprocess, sys, tempfile, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
import board  # noqa: E402

BOARD_PY = ROOT / "skills" / "trevskills-scrum" / "board.py"
PR = "https://github.com/x/y/pull/35"


class DoneGuardTest(unittest.TestCase):
    """`set stage=done` refuses unless the job's PR is merged (or it is a PR-less parent/lilguy job)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "scrum"
        self.bin = base / "bin"
        self.bin.mkdir()
        self.marker = base / "gh-called"
        env = mock.patch.dict(os.environ, {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"})
        env.start()
        self.addCleanup(env.stop)

    def fake_gh(self, body):
        gh = self.bin / "gh"
        gh.write_text(f"#!/bin/sh\necho called > '{self.marker}'\n{body}\n")
        gh.chmod(0o755)

    def stage(self, job_id):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id)["stage"]

    def job_with_pr(self):
        job_id = board.cmd_new(self.root, "with pr")
        board.cmd_set(self.root, job_id, ["stage=merging", f"pr={PR}"])
        return job_id

    def test_done_with_merged_pr_allowed(self):
        self.fake_gh("echo MERGED")
        job_id = self.job_with_pr()
        board.cmd_set(self.root, job_id, ["stage=done", "reason="])
        self.assertEqual(self.stage(job_id), "done")
        self.assertTrue(self.marker.exists())

    def test_done_with_open_pr_refused(self):
        self.fake_gh("echo OPEN")
        job_id = self.job_with_pr()
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "set", job_id, "stage=done"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(f"not done: PR {PR} is OPEN, not merged", r.stderr)
        self.assertEqual(self.stage(job_id), "merging")

    def test_done_gh_failure_refused(self):
        self.fake_gh("echo boom >&2\nexit 1")
        job_id = self.job_with_pr()
        with self.assertRaises(SystemExit) as e:
            board.cmd_set(self.root, job_id, ["stage=done"])
        self.assertEqual(str(e.exception.code), f"not done: could not confirm PR {PR} is merged: boom")
        self.assertEqual(self.stage(job_id), "merging")

    def test_done_gh_missing_refused(self):
        job_id = self.job_with_pr()
        with mock.patch.dict(os.environ, {"PATH": str(self.bin)}):  # empty dir: no gh anywhere
            with self.assertRaises(SystemExit) as e:
                board.cmd_set(self.root, job_id, ["stage=done"])
        msg = str(e.exception.code)
        self.assertTrue(msg.startswith(f"not done: could not confirm PR {PR} is merged: "), msg)
        self.assertIn("gh", msg[len(f"not done: could not confirm PR {PR} is merged: "):])
        self.assertEqual(self.stage(job_id), "merging")

    def test_done_gh_timeout_refused(self):
        job_id = self.job_with_pr()
        with mock.patch.object(board.subprocess, "run", side_effect=subprocess.TimeoutExpired(["gh"], 15)) as run:
            with self.assertRaises(SystemExit) as e:
                board.cmd_set(self.root, job_id, ["stage=done"])
        self.assertEqual(str(e.exception.code), f"not done: could not confirm PR {PR} is merged: timed out")
        self.assertEqual(run.call_args.kwargs.get("timeout"), 15)
        self.assertEqual(self.stage(job_id), "merging")

    def test_done_without_pr_refused_on_standard(self):
        self.fake_gh("echo MERGED")
        for lane in (None, "standard", "fast", "debug"):
            job_id = board.cmd_new(self.root, f"lane {lane}")
            if lane:
                board.cmd_set(self.root, job_id, [f"lane={lane}"])
            with self.assertRaises(SystemExit) as e:
                board.cmd_set(self.root, job_id, ["stage=done"])
            self.assertEqual(str(e.exception.code), "not done: no PR recorded", lane)
            self.assertNotEqual(self.stage(job_id), "done", lane)
        self.assertFalse(self.marker.exists())

    def test_done_without_pr_allowed_on_parent_and_lilguy(self):
        self.fake_gh("echo OPEN")
        for lane in ("bigboy", "runall", "lilguy"):
            job_id = board.cmd_new(self.root, f"lane {lane}")
            board.cmd_set(self.root, job_id, [f"lane={lane}"])
            board.cmd_set(self.root, job_id, ["stage=done", "reason="])
            self.assertEqual(self.stage(job_id), "done", lane)
        # a lane given in the same call counts too
        job_id = board.cmd_new(self.root, "same call")
        board.cmd_set(self.root, job_id, ["lane=lilguy", "stage=done"])
        self.assertEqual(self.stage(job_id), "done")
        self.assertFalse(self.marker.exists())

    def test_done_refused_for_lilguy_with_worktree_and_no_pr(self):
        self.fake_gh("echo OPEN")
        job_id = board.cmd_new(self.root, "lil in worktree")
        board.cmd_set(self.root, job_id, ["lane=lilguy", "worktree=/tmp/wt-lil"])
        with self.assertRaises(SystemExit) as e:
            board.cmd_set(self.root, job_id, ["stage=done"])
        self.assertEqual(str(e.exception.code), "not done: no PR recorded")
        self.assertNotEqual(self.stage(job_id), "done")
        board.cmd_set(self.root, job_id, [f"pr={PR}"])
        with self.assertRaises(SystemExit) as e:
            board.cmd_set(self.root, job_id, ["stage=done"])
        self.assertEqual(str(e.exception.code), f"not done: PR {PR} is OPEN, not merged")
        self.assertNotEqual(self.stage(job_id), "done")

    def test_set_on_done_job_skips_check(self):
        self.fake_gh("echo MERGED")
        job_id = self.job_with_pr()
        board.cmd_set(self.root, job_id, ["stage=done"])
        self.marker.unlink()
        self.fake_gh("echo OPEN")
        board.cmd_set(self.root, job_id, ["reason="])
        board.cmd_set(self.root, job_id, ["stage=done", "reason=merged, not live: verify failed"])
        self.assertEqual(self.stage(job_id), "done")
        self.assertFalse(self.marker.exists())

    def test_done_check_uses_rest_not_graphql(self):
        self.fake_gh('echo "$@" > "%s.args"\necho MERGED' % self.marker)
        job_id = self.job_with_pr()
        board.cmd_set(self.root, job_id, ["stage=done"])
        args = Path(f"{self.marker}.args").read_text()
        self.assertTrue(args.startswith("api repos/x/y/pulls/35 --jq"), args)

    def test_done_with_non_github_pr_refused(self):
        self.fake_gh("echo MERGED")
        job_id = board.cmd_new(self.root, "odd pr")
        board.cmd_set(self.root, job_id, ["stage=merging", "pr=https://x/1"])
        with self.assertRaises(SystemExit) as e:
            board.cmd_set(self.root, job_id, ["stage=done"])
        self.assertIn("not a GitHub pull request URL", str(e.exception))
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
