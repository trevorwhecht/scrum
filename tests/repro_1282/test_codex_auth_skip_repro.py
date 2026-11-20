"""Repro for job 1282: a Codex run that dies on `401 Unauthorized` (Codex not logged in on the machine running the
review, e.g. the shop Mac) must be reported as an auth failure that names the fix, not as a bare skip."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "agents" / "scrum-review-code.md"


class CodexAuthSkipTest(unittest.TestCase):
    def test_code_reviewer_codex_auth_command(self):
        text = AGENT.read_text()
        reason = "`codex: skipped — codex auth failed (401): run codex login`"
        self.assertTrue(reason in text, f"{AGENT.name} has no 401 skip reason {reason}")
        # the existing skip line is sharpened, not duplicated
        self.assertEqual(text.count("codex auth failed (401)"), 1)
        line = next(l for l in text.splitlines() if reason in l)
        for phrase in ("401", "Unauthorized", "last error line"):
            self.assertIn(phrase, line, phrase)
        # the auth skip is still a skip: never a pass, never a round failure, one Codex run, one wait
        self.assertIn("A skip is never a pass", text)
        self.assertIn("never fails the round on its own", text)
        self.assertEqual(text.count("wait for the background"), 1)
        self.assertEqual(text.count("codex exec"), 1)
        self.assertIn("never retry it", text)


if __name__ == "__main__":
    unittest.main()
