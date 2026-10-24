"""Repro: Send back to builder (serve.rework_job) cuts the feedback to 300 characters, while the dashboard
textarea allows 2,000. A 900-character rework was cut mid-word and the rework run refused it."""
import os, sys, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
import serve  # noqa: E402


class ReworkFeedbackLengthTest(unittest.TestCase):
    def rework_prompt(self, feedback):
        with mock.patch.object(serve, "spawn") as spawn:
            serve.rework_job("repo", Path("/nowhere"), "179", feedback)
        spawn.assert_called_once()
        return spawn.call_args.args[4]

    def test_rework_keeps_1500_characters_whole(self):
        feedback = ("Don't touch the header. " * 63)[:1499] + "!"  # 1,500 chars, single spaces, no edge space
        self.assertEqual(len(feedback), 1500)
        self.assertEqual(self.rework_prompt(feedback), '/trevskills-scrum rework 179 "' + feedback + '"')

    def test_rework_clamps_to_textarea_maxlength_2000(self):
        prompt = self.rework_prompt("x" * 2500)
        self.assertEqual(prompt, '/trevskills-scrum rework 179 "' + "x" * 2000 + '"')


if __name__ == "__main__":
    unittest.main()
