"""Repro for job 219: jev model decision skipped for pre-written specs and builder respawns."""
import unittest
from pathlib import Path

LANES = Path(__file__).resolve().parents[1] / "skills" / "trevskills-scrum" / "lanes"


def section(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


class JevModelGaps(unittest.TestCase):
    def test_skill_jev_model_before_spec_shortcut(self):
        new_job = (LANES / "newjob.md").read_text()
        self.assertLess(new_job.index("jev-gate.py model"), new_job.index("pre-written from the backlog"))

    def test_skill_resume_keeps_jev_model(self):
        resume = (LANES / "resume.md").read_text()
        step1 = section(resume, "1. Spawn a fresh `scrum-builder`", "\n2. ")
        for phrase in ("jev.log", 'model: "sonnet"', "promote"):
            self.assertIn(phrase, step1, phrase)


if __name__ == "__main__":
    unittest.main()
