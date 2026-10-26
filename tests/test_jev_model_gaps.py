"""Repro for job 219: jev model decision skipped for pre-written specs and builder respawns."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from skilltext import skill_text

SKILL = Path(__file__).resolve().parents[1] / "skills" / "trevskills-scrum" / "SKILL.md"


def section(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


class JevModelGaps(unittest.TestCase):
    def test_skill_jev_model_before_spec_shortcut(self):
        new_job = section(skill_text(), "## New job", "## Run all")
        self.assertLess(new_job.index("jev-gate.py model"), new_job.index("pre-written from the backlog"))

    def test_skill_resume_keeps_jev_model(self):
        resume = section(skill_text(), "## Resuming the builder", "## Digest")
        step1 = section(resume, "1. Spawn a fresh `scrum-builder`", "\n2. ")
        for phrase in ("jev.log", 'model: "sonnet"', "promote"):
            self.assertIn(phrase, step1, phrase)


if __name__ == "__main__":
    unittest.main()
