"""Job 1426: board.tag_kind / jev_ops_kind / `B ops-kind` route a job to the ops lane (lanes/ops.md), the routing text in
newjob.md, SKILL.md, lilguy.md and the shop notes."""
import io, json, os, re, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))
os.environ["SCRUM_MUTE"] = "1"
os.environ.setdefault("SCRUM_PS", os.devnull)
import board, jev  # noqa: E402

JOB = "310-prod-run"
DATA_Q = "existing data script"
CONTENT_Q = "writes content"


def answers(data, content):
    """A jev.noul stand-in: (score, raw) by question; a float or an exception per question."""
    calls = []

    def fake(text, question, timeout=20):
        calls.append(question)
        v = data if "script" in question else content
        if isinstance(v, BaseException):
            raise v
        return v, {"type": "noul", "noul": v}
    fake.calls = calls
    return fake


class TagKindTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "repo" / "scrum"
        self.dir = self.root / "jobs" / JOB
        self.dir.mkdir(parents=True)
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=str(self.base / "projects.json"))
        env.start()
        self.addCleanup(env.stop)
        self.put({"id": JOB, "stage": "spec"})

    def put(self, job):
        (self.root / "board.json").write_text(json.dumps({"jobs": [{"updatedAt": board.now(), "reason": None, **job}]}))

    def feature(self, text):
        (self.dir / "feature.md").write_text(text)

    def stored(self):
        return board.find(board.read_board(self.root), JOB).get("kind")

    def tag(self, fake=None):
        fake = fake or answers(AssertionError("Jev was called"), AssertionError("Jev was called"))
        with mock.patch.object(jev, "noul", side_effect=fake):
            return board.tag_kind(self.root, JOB), fake

    def test_kind_line_wins_without_jev(self):
        for kind in ("ops-data", "ops-content"):
            self.feature(f"Run it\n\nSome text\nKind: {kind}\n")
            self.assertEqual(self.tag()[0], kind)
            self.assertEqual(self.stored(), kind)
        self.put({"id": JOB, "stage": "spec"})
        for line in ("Kind: edit-reel", "Kind: edit-photo", "Kind: knowledge"):
            self.feature(f"x\n{line}\n")
            self.assertIsNone(self.tag()[0])
            self.assertIsNone(self.stored())

    def test_kind_answer_cached(self):
        self.feature("Run npm run fix:prod\nRun: npm run fix:prod\n")
        fake = answers(0.9, 0.1)
        self.assertEqual(self.tag(fake)[0], "ops-data")
        self.assertEqual(len(fake.calls), 2)
        log = [l.split("\t") for l in (self.dir / "jev.log").read_text().splitlines()]
        self.assertEqual([(f[1], f[4]) for f in log], [("kind", "ops-data")])
        self.assertEqual(self.tag(fake)[0], "ops-data")
        self.assertEqual(len(fake.calls), 2)  # reused, no new Jev call

    def test_kind_content_from_jev(self):
        self.feature("Write a blog post for Trevor to publish\n")
        self.assertEqual(self.tag(answers(0.2, 0.7))[0], "ops-content")

    def test_kind_unsure_stays_code(self):
        self.feature("Fix the login bug\nRun: npm run x:prod\n")
        for data, content in ((0.69, 0.1), (0.1, 0.1), (0.9, 0.9), (0.69, 0.69)):
            with self.subTest(data=data, content=content):
                (self.dir / "jev.log").unlink(missing_ok=True)
                self.assertIsNone(self.tag(answers(data, content))[0])
                self.assertIsNone(self.stored())

    def test_kind_jev_error_stays_code(self):
        self.feature("Do the thing\n")
        for err in (jev.JevError("down"), TimeoutError("t"), RuntimeError("boom")):
            with self.subTest(err=type(err).__name__):
                (self.dir / "jev.log").unlink(missing_ok=True)
                self.assertIsNone(self.tag(answers(err, 0.9))[0])
        (self.dir / "jev.log").unlink(missing_ok=True)
        fake = mock.Mock(side_effect=jev.JevError("no score"))
        with mock.patch.object(jev, "noul", fake):
            self.assertIsNone(board.tag_kind(self.root, JOB))

    def test_jev_ops_data_without_run_line_falls_back(self):
        self.feature("Re-run the backfill on prod\n")
        self.assertIsNone(self.tag(answers(0.95, 0.0))[0])
        self.feature("Re-run the backfill on prod\nRun: npm run backfill:prod -- --x\n")
        self.assertEqual(self.tag(answers(0.95, 0.0))[0], "ops-data")

    def test_stored_kind_kept_and_line_replaces(self):
        self.put({"id": JOB, "stage": "spec", "kind": "ops-content"})
        self.feature("No kind line here\n")
        self.assertEqual(self.tag()[0], "ops-content")
        self.feature("Kind: ops-data\n")
        self.assertEqual(self.tag()[0], "ops-data")
        self.assertEqual(self.stored(), "ops-data")

    def test_ops_kind_command_prints(self):
        self.feature("Kind: ops-content\n")
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(sys, "argv", ["board.py", "--dir", str(self.root), "ops-kind", JOB]):
            board.main()
        self.assertEqual(out.getvalue().strip(), "ops-content")
        self.feature("Kind: knowledge\n")
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(sys, "argv", ["board.py", "--dir", str(self.root), "ops-kind", JOB]):
            board.main()
        self.assertEqual(out.getvalue().strip(), "none")


class OpsRouteTextTest(unittest.TestCase):
    def test_newjob_ops_route(self):
        text = (SKILL / "lanes" / "newjob.md").read_text()
        route = text[text.index("   1d. **Ops route"):text.index("\n2. **Base:**")]
        for phrase in ("B ops-kind $ID", "B set $ID lane=ops kind=<kind>", "lanes/ops.md"):
            self.assertIn(phrase, route)
        self.assertLess(text.index("1d. **Ops route"), text.index("2. **Base:**"))
        self.assertNotIn("ops-kind", (SKILL / "lanes" / "edit.md").read_text())

    def test_skill_ops_lane_section(self):
        text = (SKILL / "SKILL.md").read_text()
        sec = text[text.index("\n## Ops lane\n"):]
        sec = sec[:sec.find("\n## ", 5)] if "\n## " in sec[5:] else sec
        self.assertIn("$HOME/.claude/skills/trevskills-scrum/lanes/ops.md", sec)
        edit = text[text.index("\n## Edit lane\n"):]
        edit = edit[:edit.index("\n## ", 5)]
        self.assertIn("`Kind: edit-*` line", edit)
        self.assertNotIn("has a `Kind:` line", edit)
        self.assertLessEqual(len(text), 20000)

    def test_lilguy_knowledge_kind(self):
        text = (SKILL / "lanes" / "lilguy.md").read_text()
        step1 = text[text.index("1. **Worktree.**"):text.index("2. **Build.**")]
        self.assertIn("`Lane: lilguy — knowledge save`", step1)
        self.assertIn("B set $ID kind=knowledge", step1)
        self.assertIn("B set $ID lane=lilguy", step1)

    def test_shop_notes_cannot_run_ops_kinds(self):
        terms = board.main_only_terms()
        self.assertIn("Kind: ops-data", terms)
        self.assertIn("Kind: ops-content", terms)
        self.assertTrue(board.names_main_only("x\nKind: ops-data\n", terms))


if __name__ == "__main__":
    unittest.main()
