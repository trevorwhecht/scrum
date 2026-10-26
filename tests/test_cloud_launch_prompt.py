import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = "~/.claude/skills/trevskills-scrum/SKILL.md"
LANE = "~/.claude/skills/trevskills-scrum/lanes/cloud.md"


def cloud_lane():
    return (ROOT / "skills" / "trevskills-scrum" / "lanes" / "cloud.md").read_text()


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
                 f"grep -q scrum-artifacts/ {LANE}", "Read tool",
                 "this cloud session is running an old copy of the scrum instructions; rerunning cloud setup refreshes it.")
        for phrase in steps + ("session start", "before New job", "Needs-human"):
            self.assertIn(phrase, prompt, phrase)
        idx = [prompt.index(p) for p in steps]
        self.assertEqual(idx, sorted(idx), "checks out of order: HEAD, marker, Read, stop reason")
        # The grepped file really holds the marker, so a fresh copy passes the check.
        self.assertIn("scrum-artifacts/", cloud)
        # The Read instruction names the file on disk again, after the grep.
        self.assertIn(SKILL, prompt[prompt.index(steps[2]) + len(steps[2]):])
        # The prompt sits in a double-quoted bash string on the Mac: nothing in it may expand there.
        self.assertNotIn("`", prompt)
        self.assertNotIn("$(", prompt)
        self.assertNotRegex(prompt, r"\$(?!ID\b|FEAT\b)")


if __name__ == "__main__":
    unittest.main()
