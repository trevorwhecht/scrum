"""Job 934: Merge's prod `migrate status` was denied in onewitharts job 1278.

The job worktree had no `.env.prod`: new-job step 4 links the untracked `.env*` files with
`find "$REPO" -maxdepth 1 ...`, and BSD find does not descend into a starting path that is a symlink
(~/Developer/repos/onewitharts -> nextjs/onewitharts), so nothing was linked. The prescribed
`npx dotenv -e .env.prod -- npx prisma migrate status` then failed with P1012 and the session
improvised `ls <main>/.env.prod && npx dotenv -e <abs path> ...`, which the permission rules denied.
"""
import os, re, subprocess, tempfile, unittest
from pathlib import Path

LANES = Path(__file__).resolve().parents[1] / "skills" / "trevskills-scrum" / "lanes"
STATUS = "`npx dotenv -e .env.prod -- npx prisma migrate status`"


def env_link_line(text):
    """The shell line that links the main checkout's untracked .env* files into $WT."""
    return next(m.group(1).strip() for m in re.finditer(r"^\s*`?(find [^`\n]*'\.env\*'[^`\n]*ln -sfn[^`\n]*done)`?", text, re.M))


def migrate_section():
    merge = (LANES / "merge.md").read_text()
    return merge.split("## Migrate (Merge's schema guard)")[1].split("\n## ")[0]


class MergeMigrateProdStatus(unittest.TestCase):
    def run_link(self, line):
        with tempfile.TemporaryDirectory() as tmp:
            real, wt = Path(tmp, "nextjs", "proj"), Path(tmp, "wt")
            real.mkdir(parents=True)
            wt.mkdir()
            subprocess.run(["git", "init", "-q", str(real)], check=True)
            (real / ".env.prod").write_text("DATABASE_URL=postgres://x\n")
            (real / ".env.local").write_text("DATABASE_URL=postgres://y\n")
            link = Path(tmp, "proj")
            link.symlink_to(real)  # $REPO reached through a symlink, as ~/Developer/repos/onewitharts is
            subprocess.run(["bash", "-c", line], env={**os.environ, "REPO": str(link), "WT": str(wt)}, check=True)
            return sorted(p.name for p in wt.iterdir())

    def test_merge_migrate_prod_status_runs_exact_allowed_command(self):
        newjob_line = env_link_line((LANES / "newjob.md").read_text())
        # root cause: the worktree must get .env.prod even when $REPO is a symlinked path
        self.assertEqual(self.run_link(newjob_line), [".env.local", ".env.prod"])
        mig = migrate_section()
        # Migrate re-links the env files (rework and cloud recreate worktrees without them)
        self.assertIn(newjob_line, mig)
        self.assertEqual(self.run_link(env_link_line(mig)), [".env.local", ".env.prod"])
        # the exact command the global allow rule matches, un-wrapped, and .env.prod is never read
        self.assertIn(STATUS, mig)
        self.assertIn("as its own Bash call", mig)
        self.assertIn("no `cd`, `&&`, pipe, redirect or env prefix", mig)
        self.assertIn("never read, cat, ls or grep `.env.prod`", mig)
        # the root cause, named in one sentence
        self.assertIn("`find` skips a symlinked `$REPO`", mig)


if __name__ == "__main__":
    unittest.main()
