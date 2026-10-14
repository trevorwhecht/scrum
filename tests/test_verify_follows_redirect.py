import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum" / "SKILL.md"
APPROVER = ROOT / "agents" / "scrum-approver.md"


def cleanup_section(text):
    start = text.index("7. **Clean up:**")
    return text[start:text.index("## Resuming the builder", start)]


class VerifyFollowsRedirectTest(unittest.TestCase):
    """serve.py answers / with 302 -> /dashboard.html; curl -sf without -L sees an empty body."""

    def test_skill_verify_uses_curl_sfL(self):
        cleanup = cleanup_section(SKILL.read_text())
        restart = cleanup[cleanup.index("**Restart.**"):]
        self.assertIn("run only `curl -sfL localhost:<port>/<path>`", restart)
        self.assertIn('curl -sfL localhost:<port>/<path> | grep -F -- "$VERIFY"', restart)
        self.assertIn("and `curl -sfL localhost:<port>/<path>` exits 0", restart)
        self.assertIn("any other shape, do not run it", restart)
        self.assertNotIn("curl -sf localhost", cleanup)

    def test_approver_restart_line_uses_curl_sfL(self):
        text = APPROVER.read_text()
        self.assertIn("curl -sfL localhost:<N>/", text)
        self.assertIn("verify: curl -sfL localhost:8765/ | grep -F -- '<string the diff added>'", text)
        self.assertNotIn("curl -sf localhost", text)


if __name__ == "__main__":
    unittest.main()
