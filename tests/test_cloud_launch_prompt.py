import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = "~/.claude/skills/trevskills-scrum/SKILL.md"


def cloud_lane():
    text = (ROOT / "skills" / "trevskills-scrum" / "SKILL.md").read_text()
    start = text.index("\n## Cloud lane\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


class CloudLaunchPromptTest(unittest.TestCase):
    def test_cloud_launch_prompt_verifies_and_reads_skill_file(self):
        # The Skill tool serves the text registered at session start, before setup.sh refreshes ~/scrum, so the
        # always-fresh launch prompt carries the stale check and points the session at SKILL.md on disk.
        cloud = cloud_lane()
        m = re.search(r'--cloud "(First run: .*?/trevskills-scrum cloud-job \$ID \$FEAT)"', cloud)
        self.assertIsNotNone(m, "no --cloud launch prompt")
        prompt = m.group(1)
        self.assertTrue(prompt.startswith("First run: bash ~/scrum/cloud/setup.sh"), prompt)
        self.assertFalse("invoke the trevskills-scrum skill fresh" in cloud,
                         "launch prompt still invokes the cached skill: " + prompt)
        steps = ("git -C ~/scrum rev-parse HEAD", "git -C ~/scrum ls-remote origin refs/heads/main",
                 f"grep -q scrum-artifacts/ {SKILL}", "Read tool", "cloud skill copy is stale. Fix: rerun cloud setup.")
        for phrase in steps + ("session start", "before New job", "Needs-human"):
            self.assertIn(phrase, prompt, phrase)
        idx = [prompt.index(p) for p in steps]
        self.assertEqual(idx, sorted(idx), "checks out of order: HEAD, marker, Read, stop reason")
        # The Read instruction names the file on disk again, after the grep.
        self.assertIn(SKILL, prompt[prompt.index(steps[2]) + len(steps[2]):])
        # The prompt sits in a double-quoted bash string on the Mac: nothing in it may expand there.
        self.assertNotIn("`", prompt)
        self.assertNotIn("$(", prompt)
        self.assertNotRegex(prompt, r"\$(?!ID\b|FEAT\b)")


if __name__ == "__main__":
    unittest.main()
