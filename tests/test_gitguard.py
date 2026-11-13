"""The Go git-guard hook (skills/trevskills-scrum/gitguard, job 812): run its go test so the Check gate covers it."""
import shutil, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITGUARD = ROOT / "skills" / "trevskills-scrum" / "gitguard"
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
import board  # noqa: E402


class GitGuardGoTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("go"), "go is not installed")
    def test_go_test_passes(self):
        result = subprocess.run(["go", "test", "./..."], cwd=GITGUARD, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_active_stages_match_board(self):
        main_go = (GITGUARD / "main.go").read_text()
        for stage in board.ACTIVE:
            self.assertIn(f'"{stage}"', main_go, stage)


if __name__ == "__main__":
    unittest.main()
