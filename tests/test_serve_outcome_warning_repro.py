"""outcome_line skips Claude CLI `Permission allow rule` warning lines when picking the message."""
import os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
import serve  # noqa: E402

WARN = "Permission allow rule (../../.claude/settings.json): Write(...) is not matched ..."


class OutcomeLineWarningTest(unittest.TestCase):
    def outcome(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run.log").write_text(text)
            return serve.outcome_line(root, {"log": "run.log", "action": "resume"}, 0)

    def test_outcome_line_skips_permission_warning(self):
        line = self.outcome(WARN + "\nResume refused: reason X\n")
        self.assertIn("reason X", line)
        self.assertNotIn("Permission allow rule", line)

    def test_outcome_line_only_warnings_gives_no_message(self):
        line = self.outcome(WARN + "\n\n" + WARN + "\n")
        self.assertRegex(line, r"^Resume refused at \d{1,2}:\d\d [AP]M\. Nothing changed\.$")

    def test_outcome_line_skips_indented_warning(self):
        line = self.outcome("- " + WARN + "\n  " + WARN + "\nreason Y\n")
        self.assertIn("reason Y", line)
        self.assertNotIn("Permission allow rule", line)


if __name__ == "__main__":
    unittest.main()
