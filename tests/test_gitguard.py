"""The Go git-guard hook (skills/trevskills-scrum/gitguard, job 812): run its go test so the Check gate covers it."""
import shutil, subprocess, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITGUARD = ROOT / "skills" / "trevskills-scrum" / "gitguard"


class GitGuardGoTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("go"), "go is not installed")
    def test_go_test_passes(self):
        result = subprocess.run(["go", "test", "./..."], cwd=GITGUARD, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
