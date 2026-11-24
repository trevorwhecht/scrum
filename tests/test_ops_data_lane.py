"""Job 1424: lanes/ops-data.md, the data-run track (dev runs, then prod, every command gated by `B prod-ok`)."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT / "skills" / "trevskills-scrum" / "lanes" / "ops-data.md"
NAMES = ["Scripts", "Main", "Dev runs", "Result shown", "Prod runs", "Check", "Resume"]


def step(n):
    text = LANE.read_text()
    m = re.search(rf"^{n}\. \*\*.*?(?=^{n + 1}\. \*\*|\Z)", text, re.S | re.M)
    assert m, f"step {n} missing"
    return m.group(0)


class OpsDataLane(unittest.TestCase):
    def test_steps(self):
        text = LANE.read_text()
        heads = re.findall(r"^(\d)\. \*\*([^*]+?)\.?\*\*", text, re.M)
        self.assertEqual(heads, [(str(i + 1), n) for i, n in enumerate(NAMES)])

    def test_scripts_and_ask(self):
        s = step(1)
        for p in ("`Run:", "dev dry run", "dev apply", "prod dry run", "prod apply", "closing prod dry run",
                  "`:prod`", "--title DATA_RUN", "runs.md", "no `Run:` line", "Send back with a note", "Remove this job"):
            self.assertIn(p, s, p)
        self.assertIn("never asks Trevor to approve", s)

    def test_main_and_dev_runs(self):
        self.assertIn("**Fast-forward main**", step(2))
        self.assertIn("BUILDER_BLOCKED", step(2))
        self.assertIn("`1. Deploy`", step(2))
        s = step(3)
        for p in ("stage=build", "`## Runs`", "runs.md", "- run: <bullet> exit <code>"):
            self.assertIn(p, s, p)

    def test_result_shown(self):
        s = step(4)
        for p in ("dev-output.md", "PROD_CHECK_FAILED", "prod never starts"):
            self.assertIn(p, s, p)

    def test_prod_runs(self):
        s = step(5)
        for p in ("stage=deploying", "B prod-ok $ID '<bullet>'", "prod run refused: "):
            self.assertIn(p, s, p)

    def test_check_and_resume(self):
        c = step(6)
        for p in ("prod dry run still reports pending work", "PROD_CHECK_FAILED", "**Finish**"):
            self.assertIn(p, c, p)
        r = step(7)
        for p in ("runs.md", "re-runs the dev pair", "prod.md"):
            self.assertIn(p, r, p)

    def test_points_to_merge(self):
        text = LANE.read_text()
        for p in ("merge.md", "**Prod runs**", "jev-gate.py prod-error"):
            self.assertIn(p, text, p)
        for p in ("PROD_RUN_RE", "prisma migrate", "db:push", "[A-Za-z0-9=_.:/-]"):
            self.assertNotIn(p, text, p)

    def test_merge_prod_refused_offers_ops_data(self):
        text = (LANE.parent / "merge.md").read_text()
        s = text[text.index("     5. On any failure"):]
        s = s[:s.index("\n") if "\n" in s else len(s)]
        for p in ("prod run refused", 'followup $ID \\"Kind: ops-data run: npm run <script>:prod -- <args>; ...\\"',
                  "one `npm run` command per refused bullet", "--title PROD_CHECK_FAILED"):
            self.assertIn(p, s, p)

    def test_prod_refused_followup_option_valid(self):
        import sys
        sys.path.insert(0, str(LANE.parents[1]))
        import board
        cmd = 'followup 1475-hand-existing-stops "Kind: ops-data run: npm run fix-x:prod -- --limit=5; npm run fix-y:prod"'
        self.assertTrue(board.ASK_COMMAND_RE.fullmatch(cmd))
        text = (LANE.parent / "merge.md").read_text()
        self.assertIn("Kind: ops-data run: npm run <script>:prod -- <args>; ...", text)
        self.assertNotIn('"', "Kind: ops-data run: npm run <script>:prod -- <args>; ...")

    def test_review_datafix_becomes_ops_data(self):
        text = (LANE.parent / "review.md").read_text()
        s = text[text.index("starting `Datafix:`"):]
        s = s[:s.index("\n")]
        for p in ("Kind: ops-data datafix:", "--trevor --top", "every single quote removed", "one call per bullet"):
            self.assertIn(p, s, p)
        self.assertNotIn("--setup='run /trevskills-datafix", s)

    def test_datafix_job(self):
        s = step(1)
        for p in ("`Datafix:` line", "- datafix: <text>", "stage=build", "--title DATA_RUN", "Done, mark finished=approve $ID",
                  "steps 2 to 6 never run", "`prod-ok` is never called"):
            self.assertIn(p, s, p)


if __name__ == "__main__":
    unittest.main()
