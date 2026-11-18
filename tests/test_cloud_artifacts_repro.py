"""Repro: job 984's shop run pushed scrum-artifacts/<id> with an empty tree. Its session defined the board function
with `--dir "$PWD/scrum"`, and lanes/cloud.md's Artifacts step runs `cd "$F"` before `B artifacts`, so B looked in
scrum/scrum/jobs/<id>, printed nothing, and the empty tree from `git write-tree` was committed and pushed anyway."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "skills" / "trevskills-scrum" / "lanes" / "cloud.md"
BOARD = ROOT / "skills" / "trevskills-scrum" / "board.py"
JOB = "984-shop-py-run-permissions-before-owa-links"


def artifacts_block():
    text = LANE.read_text()
    start = text.index("- **Artifacts:**")
    body = text.index("```bash\n", start) + len("```bash\n")
    return textwrap.dedent(text[body:text.index("```", body)])


class CloudArtifactsRepro(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        cfg = base / "gitconfig"
        cfg.write_text("")
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": str(cfg), "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.origin, self.repo = base / "origin.git", base / "repo"
        self.git(base, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(base, "init", "-q", "-b", "main", str(self.repo))
        (self.repo / "README.md").write_text("x\n")
        self.git(self.repo, "add", "README.md")
        self.git(self.repo, "commit", "-q", "-m", "init")
        self.git(self.repo, "remote", "add", "origin", str(self.origin))
        self.git(self.repo, "push", "-q", "origin", "main")
        with open(self.repo / ".git" / "info" / "exclude", "a") as f:  # shop.profile_copy's exclude lines
            f.write("scrum/\n.claude/worktrees/\n")
        job = self.repo / "scrum" / "jobs" / JOB
        job.mkdir(parents=True)
        (job / "feature.md").write_text("shop.py: run permissions before owa links\n")
        (job / "build.md").write_text("# Build\nDone.\n")

    def git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True, text=True)

    def test_cloud_artifacts_step_pushes_job_files(self):
        # The board function exactly as job 984's shop session defined it (its transcript), from the main checkout.
        script = ('B() { python3 "$BOARD" --dir "$PWD/scrum" "$@"; }\n'
                  'ID=$JOB; REPO=$PWD; F=$PWD/scrum\n' + artifacts_block())
        run = subprocess.run(["bash", "-c", script], cwd=self.repo, capture_output=True, text=True, timeout=60,
                             env={**self.env, "BOARD": str(BOARD), "JOB": JOB})
        tree = subprocess.run(["git", "--git-dir", str(self.origin), "ls-tree", "-r", "--name-only",
                               f"refs/heads/scrum-artifacts/{JOB}"], env=self.env, capture_output=True, text=True)
        self.assertIn(f"scrum/jobs/{JOB}/build.md", tree.stdout.splitlines(),
                      f"pushed tree: {tree.stdout!r} (ls-tree exit {tree.returncode}: {tree.stderr.strip()})\n"
                      f"step exit {run.returncode}\nstdout: {run.stdout}\nstderr: {run.stderr}")


if __name__ == "__main__":
    unittest.main()
