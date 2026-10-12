import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = {
    "factory-spec-writer": "opus", "factory-builder": "opus", "factory-review-security": "opus",
    "factory-review-ux": "sonnet", "factory-review-ui": "sonnet", "factory-review-code": "sonnet",
    "factory-approver": "opus",
}
FIRST_LINE = {
    "factory-builder": "STATUS: READY", "factory-approver": "ESCALATE", "factory-review-security": "VERDICT: PASS",
    "factory-review-ux": "VERDICT: PASS", "factory-review-ui": "VERDICT: PASS", "factory-review-code": "VERDICT: PASS",
}


def frontmatter(path):
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert m, f"{path.name}: no frontmatter"
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)


class ContractTest(unittest.TestCase):
    def test_exactly_the_expected_agents_exist(self):
        self.assertEqual({p.stem for p in (ROOT / "agents").glob("*.md")}, set(AGENTS))

    def test_frontmatter(self):
        for name, model in AGENTS.items():
            fm = frontmatter(ROOT / "agents" / f"{name}.md")
            self.assertEqual(fm.get("name"), name)
            self.assertEqual(fm.get("model"), model, name)
            self.assertTrue(fm.get("description"), name)
            self.assertIn("Read", fm.get("tools", ""), name)
            self.assertNotIn("Agent", fm.get("tools", ""), f"{name} must not spawn agents")

    def test_first_line_contracts_are_documented(self):
        for name, phrase in FIRST_LINE.items():
            self.assertIn(phrase, (ROOT / "agents" / f"{name}.md").read_text(), name)

    def test_every_agent_forbids_migrations_and_merges(self):
        for name in AGENTS:
            text = (ROOT / "agents" / f"{name}.md").read_text()
            self.assertIn("prisma migrate", text, name)
            self.assertIn("git merge", text, name)

    def test_skill_references_every_agent_and_board_command(self):
        text = (ROOT / "skills" / "factory" / "SKILL.md").read_text()
        for name in AGENTS:
            self.assertIn(name, text)
        for cmd in ("board.py", " new ", " set ", " sync "):
            self.assertIn(cmd, text)
        fm = frontmatter(ROOT / "skills" / "factory" / "SKILL.md")
        self.assertEqual(fm.get("name"), "factory")

    def test_skill_only_merges_via_gh_squash(self):
        text = (ROOT / "skills" / "factory" / "SKILL.md").read_text()
        self.assertIn("gh pr merge", text)
        self.assertIn("--squash", text)
        for line in text.splitlines():
            for banned in ("--auto", "--admin", "--force", "git push origin main"):
                if banned in line:
                    self.assertIn("never", line.lower(), f"{banned!r} outside a 'never' line: {line}")

    def test_skill_guards_against_review_findings(self):
        text = (ROOT / "skills" / "factory" / "SKILL.md").read_text()
        for phrase in (
            "Hard stop: schema",                 # approve reminder matches the stored reason
            r"prisma/(schema\.prisma|migrations/)",  # deterministic schema guard before merge
            "human-approval.md",
            '"reworks"',                         # REWORK-once enforced by the orchestrator
            "second rework",
            'reason="worktree dirty"',           # no dead ends
            "merge refused",
            "UNKNOWN",
            "still missing after the re-spawn",
            "refuse",                            # approve refuses jobs with nothing to merge
            "board.py --dir",                    # next/backlog go through the locked board
            " next",
            "backlog-add",
        ):
            self.assertIn(phrase, text, phrase)


if __name__ == "__main__":
    unittest.main()
