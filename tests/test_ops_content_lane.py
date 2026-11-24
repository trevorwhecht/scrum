"""Job 1425: lanes/ops-content.md, the content track (questions, draft, Trevor's approval)."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "skills" / "trevskills-scrum" / "lanes" / "ops-content.md"
NAMES = ["Ledger", "Questions", "Draft", "Approval", "Publish"]


def step(n):
    text = LANE.read_text()
    m = re.search(rf"^{n}\. \*\*.*?(?=^{n + 1}\. \*\*|\Z)", text, re.S | re.M)
    assert m, f"step {n} missing"
    return m.group(0)


class OpsContentLane(unittest.TestCase):
    def test_steps(self):
        heads = re.findall(r"^(\d)\. \*\*([^*]+?)\.?\*\*", LANE.read_text(), re.M)
        self.assertEqual(heads, [(str(i + 1), n) for i, n in enumerate(NAMES)])

    def test_ledger(self):
        s = step(1)
        for p in ("content.md", "Questions: pending | answered", "## Drafts", "Trevor: pending | notes | approved",
                  "## Trevor's notes", "word for word", "never re-asks answered questions", "never reuses a draft number"):
            self.assertIn(p, s, p)

    def test_questions(self):
        s = step(2)
        for p in ("stage=spec", "questions.md", "--title CONTENT_QUESTIONS", "Send back with a note=rework $ID", "Remove this job", "skip the ask"):
            self.assertIn(p, s, p)

    def test_draft(self):
        s = step(3)
        for p in ("stage=build", "draft-<N>.md", "no agent is spawned", "no dashes of any kind", "- Content draft:", "the file is the draft"):
            self.assertIn(p, s, p)

    def test_approval(self):
        s = step(4)
        for p in ("--title CONTENT_DRAFT", "approve $ID", "rework $ID", "Remove this job", "draft-<N>.md tab",
                  "d<N+1>", "Only Trevor's approval ends the job", "stage=done"):
            self.assertIn(p, s, p)

    def test_no_publish_step(self):
        s = step(5)
        self.assertIn("No step here publishes", s)
        self.assertIn("Trevor publishes the approved draft himself", s)
        self.assertNotIn("stage=done", s)
        for cmd in ("git push", "gh ", "B prod-ok", "B spawn"):
            self.assertNotIn(cmd, LANE.read_text(), cmd)


if __name__ == "__main__":
    unittest.main()
