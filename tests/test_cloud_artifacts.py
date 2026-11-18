import os, re, shutil, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOB = "970-zsh-artifacts"
SHELLS = ("bash", "zsh")  # the shop's Bash tool runs zsh, claude.ai cloud sessions run bash


def block():
    """lanes/cloud.md's Cloud job Artifacts fenced bash block, indent stripped, with <id> filled in."""
    text = (ROOT / "skills" / "trevskills-scrum" / "lanes" / "cloud.md").read_text()
    part = text[text.index("- **Artifacts:**"):text.index("3. **Sync**")]
    start = part.index("```bash\n") + len("```bash\n")
    return textwrap.dedent(part[start:part.index("```", start)]).replace("<id>", JOB)


class CloudArtifactsBlockTest(unittest.TestCase):
    """A temp bare origin, a main checkout with scrum/jobs/<id>/ (scrum/ excluded, as the shop clone does), a job
    worktree, a temp HOME linking the repo's skill, git identity env vars, and stub sleep and git on PATH that log."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        home, stubs = self.tmp / "home", self.tmp / "bin"
        (home / ".claude" / "skills").mkdir(parents=True)
        (home / ".claude" / "skills" / "trevskills-scrum").symlink_to(ROOT / "skills" / "trevskills-scrum")
        stubs.mkdir()
        self.sleeps, self.pushes = self.tmp / "sleeps.log", self.tmp / "pushes.log"
        (stubs / "sleep").write_text(f'#!/bin/sh\necho "$*" >> "{self.sleeps}"\n')
        (stubs / "git").write_text(f'#!/bin/sh\ncase " $* " in *" push "*) echo push >> "{self.pushes}";; esac\n'
                                   f'exec "{shutil.which("git")}" "$@"\n')
        (stubs / "python3").symlink_to(sys.executable)  # board.py needs 3.10+, as the shop's ~/.local/bin one is
        for stub in ("sleep", "git"):
            (stubs / stub).chmod(0o755)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("GIT_") and k not in ("REPO", "F", "ID", "B", "ZDOTDIR", "BASH_ENV", "ENV")}
        self.env = {**env, "HOME": str(home), "PATH": f"{stubs}:{os.environ['PATH']}", "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        self.main, self.origin = self.tmp / "main", self.tmp / "origin.git"
        self.git("init", "-q", "--bare", str(self.origin), cwd=self.tmp)
        self.git("init", "-q", "-b", "main", str(self.main), cwd=self.tmp)
        (self.main / "README.md").write_text("repo\n")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "init")
        self.git("remote", "add", "origin", str(self.origin))
        (self.main / ".git" / "info" / "exclude").write_text("scrum/\n.claude/worktrees/\n")
        self.job = self.main / "scrum" / "jobs" / JOB
        (self.job / "round-1").mkdir(parents=True)
        (self.job / "feature.md").write_text("feature\n")
        (self.job / "spec.md").write_text("# spec\n")
        (self.job / "round-1" / "review code.md").write_text("APPROVE\n")  # a space: the list is NUL-split
        self.wt = self.main / ".claude" / "worktrees" / f"scrum-{JOB}"
        self.git("worktree", "add", "-q", "-b", f"scrum/{JOB}", str(self.wt))

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.main, env=self.env, check=True, capture_output=True,
                              text=True).stdout

    def state(self):
        """The main checkout's index bytes and `git status --porcelain`."""
        return (self.main / ".git" / "index").read_bytes(), self.git("status", "--porcelain")

    def run_block(self, shell, cwd):
        for log in (self.sleeps, self.pushes):
            log.unlink(missing_ok=True)
        out = subprocess.run([shutil.which(shell), "-c", block()], cwd=cwd, env=self.env, capture_output=True,
                             text=True, timeout=60)
        lines = out.stdout.splitlines()
        return (lines[-1] if lines else ""), out

    def count(self, log):
        return len(log.read_text().splitlines()) if log.exists() else 0

    def test_pushes_from_worktree_and_scrum_dir_in_bash_and_zsh(self):
        for shell in SHELLS:
            for cwd in (self.wt, self.main / "scrum"):
                with self.subTest(shell=shell, cwd=cwd.name):
                    if not shutil.which(shell):
                        self.skipTest(f"{shell} not installed")
                    shutil.rmtree(self.origin)  # a fresh origin per run: a second parentless commit is no fast-forward
                    self.git("init", "-q", "--bare", str(self.origin), cwd=self.tmp)
                    before = self.state()
                    last, out = self.run_block(shell, cwd)
                    self.assertEqual(last, "artifacts: pushed", out.stdout + out.stderr)
                    sha = self.git("rev-parse", f"refs/heads/scrum-artifacts/{JOB}", cwd=self.origin).strip()
                    files = self.git("ls-tree", "-r", "--name-only", sha, cwd=self.origin).splitlines()
                    self.assertEqual(sorted(files), [f"scrum/jobs/{JOB}/feature.md",
                                                     f"scrum/jobs/{JOB}/round-1/review code.md",
                                                     f"scrum/jobs/{JOB}/spec.md"])
                    self.assertEqual((self.count(self.pushes), self.count(self.sleeps)), (1, 0))
                    self.assertEqual(self.state(), before)

    def test_push_failure_retries_three_times_and_reports(self):
        text = block()
        self.assertIn("git push", text)
        for bad in ("--force", "--delete"):
            self.assertNotIn(bad, text, bad)
        self.assertNotRegex(text, r"""push[^\n]*\s["']?\+""")  # a + refspec forces too
        self.git("remote", "set-url", "origin", str(self.tmp / "missing.git"))
        for shell in SHELLS:
            with self.subTest(shell=shell):
                if not shutil.which(shell):
                    self.skipTest(f"{shell} not installed")
                last, out = self.run_block(shell, self.wt)
                self.assertEqual(last, "artifacts: push failed", out.stdout + out.stderr)
                self.assertEqual((self.count(self.pushes), self.count(self.sleeps)), (3, 2))

    def test_missing_job_folder_pushes_nothing(self):
        shutil.rmtree(self.job)
        for shell in SHELLS:
            with self.subTest(shell=shell):
                if not shutil.which(shell):
                    self.skipTest(f"{shell} not installed")
                last, out = self.run_block(shell, self.main / "scrum")
                self.assertEqual(last, "artifacts: push failed", out.stdout + out.stderr)
                self.assertEqual(self.count(self.pushes), 0)
                self.assertEqual(self.git("ls-remote", "origin"), "")

    def test_nothing_staged_pushes_no_empty_branch(self):
        shutil.rmtree(self.job)
        self.job.mkdir()  # a job folder with no file: board.py lists nothing
        for shell in SHELLS:
            with self.subTest(shell=shell):
                if not shutil.which(shell):
                    self.skipTest(f"{shell} not installed")
                last, out = self.run_block(shell, self.wt)
                self.assertEqual(last, "artifacts: nothing staged", out.stdout + out.stderr)
                self.assertEqual(self.count(self.pushes), 0)
                self.assertEqual(self.git("ls-remote", "origin"), "")


if __name__ == "__main__":
    unittest.main()
