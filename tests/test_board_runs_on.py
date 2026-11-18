"""Job 1155: each job carries a Runs on tag (any, main, shop). feature.md's `Runs on:` header wins, else Jev over the
workers' `## Cannot run` lists decides once and the board stores it. serve.py's shop-room.json says whether a worker
has room; with room, cmd_ready leaves an `any` waiting child to the shop for up to SHOP_FIRST_MAX_S and never claims a
`shop` one."""
import json, os, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # never the real home
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_VM_PRESSURE"] = "1"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
import board  # noqa: E402
import jev  # noqa: E402

PAR = "100-run-all"


class RunsOnTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "repo" / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        (self.root / "project.md").write_text("# Project\n- Test: x\n")
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=str(self.base / "projects.json"))  # no workers.txt: shopmac
        env.start()
        self.addCleanup(env.stop)
        for p in (mock.patch.object(board, "ram_room", return_value=5), mock.patch.object(board, "play")):
            p.start()
            self.addCleanup(p.stop)

    # --- fixtures ---
    def jobs(self, *jobs):
        """board.json holding `jobs`; a job's "feature" key is its feature.md (default "Fix the widget"), "spec" its spec.md."""
        out = []
        for j in jobs:
            j = dict(j)
            d = self.root / "jobs" / j["id"]
            d.mkdir(exist_ok=True)
            (d / "feature.md").write_text(j.pop("feature", "Fix the widget\n"))
            if spec := j.pop("spec", None):
                (d / "spec.md").write_text(spec)
            if j.pop("fit", None):
                (d / "lilguy-fit.json").write_text('{"fit": true, "why": "tiny"}')
            out.append({"updatedAt": board.now(), "reason": None, **j})
        (self.root / "board.json").write_text(json.dumps({"jobs": out}))

    def runall(self, *kids):
        self.jobs({"id": PAR, "stage": "running", "lane": "runall", "children": [k["id"] for k in kids]},
                  *({"stage": "waiting", "parent": PAR, **k} for k in kids))

    def job(self, job_id):
        return board.find(board.read_board(self.root), job_id)

    def room(self, workers=("shopmac",), age=0):
        (self.base / "shop-room.json").write_text(json.dumps({"at": time.time() - age, "workers": list(workers)}))

    def jev(self, answer):
        """board.jev_main_only patched to `answer` (an exception raises, a function is called)."""
        kw = {"side_effect": answer} if callable(answer) or isinstance(answer, BaseException) else {"return_value": answer}
        p = mock.patch.object(board, "jev_main_only", **kw)
        self.addCleanup(p.stop)
        return p.start()

    # --- criterion 1: the tag ---
    def test_header_wins(self):
        self.jobs({"id": "010-a", "stage": "spec", "runs_on": "main",
                   "feature": "# Use VectorCraft\nRuns on: any\n\n## Problem\nOpen `.env.prod`, then brew and iMessage\n"},
                  {"id": "011-b", "stage": "spec", "feature": "Runs on: SHOP\n\nFix it\n"},
                  {"id": "012-c", "stage": "spec", "feature": "# Fix\n## Notes\nRuns on: shop\n"})  # below a heading: no header
        ask = self.jev(AssertionError("no Jev call when the header decides"))
        self.assertEqual(board.tag_runs_on(self.root, "010-a"), "any")
        self.assertEqual(self.job("010-a")["runs_on"], "any", "a header that differs from the stored field is stored")
        self.assertEqual(board.tag_runs_on(self.root, "011-b"), "shop")
        self.assertEqual(self.job("011-b")["runs_on"], "shop")
        ask.assert_not_called()
        self.jev(False)
        self.assertEqual(board.tag_runs_on(self.root, "012-c"), "any")

    def test_jev_yes_no(self):
        self.jobs({"id": "010-a", "stage": "spec", "feature": "Fix the widget\n", "spec": "# Spec\nLikely files\n"},
                  {"id": "011-b", "stage": "spec"})
        ask = self.jev(True)
        self.assertEqual(board.tag_runs_on(self.root, "010-a"), "main")
        self.assertEqual(self.job("010-a")["runs_on"], "main")
        text, terms, log = ask.call_args.args
        self.assertIn("Fix the widget", text)
        self.assertIn("# Spec\nLikely files", text, "spec.md is asked about too")
        self.assertIn("VectorCraft", terms)
        self.assertEqual(log, self.root / "jobs" / "010-a" / "jev.log")
        self.jev(False)
        self.assertEqual(board.tag_runs_on(self.root, "011-b"), "any")
        self.assertEqual(self.job("011-b")["runs_on"], "any")

    def test_jev_down_falls_back_to_terms(self):
        self.jobs({"id": "010-a", "stage": "spec", "feature": "Redraw the logo in VectorCraft\n"},
                  {"id": "011-b", "stage": "spec", "feature": "Fix the widget\n"})
        self.jev(None)
        self.assertEqual(board.tag_runs_on(self.root, "010-a"), "main")
        self.assertEqual(board.tag_runs_on(self.root, "011-b"), "any")
        self.assertEqual([self.job(j)["runs_on"] for j in ("010-a", "011-b")], ["main", "any"])

    def test_jev_seam_cutoffs_and_log(self):
        log = self.base / "jev.log"
        for value, want in ((0.7, True), (0.9, True), (0.3, False), (0.0, False), (0.5, None), (0.31, None)):
            with self.subTest(value=value), mock.patch.object(jev, "noul", return_value=(value, "raw")) as noul:
                self.assertIs(board.jev_main_only("Fix it", ["VectorCraft", "brew"], log), want)
                self.assertEqual(noul.call_args.args[1],
                                 "Does this job need any of these, which only this Mac has: VectorCraft, brew?")
                self.assertEqual(noul.call_args.kwargs["timeout"], 20)
        with mock.patch.object(jev, "noul", side_effect=TimeoutError("slow")):
            self.assertIsNone(board.jev_main_only("Fix it", ["VectorCraft"], log))
        fields = [line.split("\t") for line in log.read_text().splitlines()]
        self.assertEqual([f[1] for f in fields], ["runs-on"] * 7)
        self.assertEqual([f[4] for f in fields], ["main", "main", "any", "any", "unsure", "unsure", "unsure"])

    def test_stored_tag_is_not_re_asked(self):
        self.jobs({"id": "010-a", "stage": "spec", "runs_on": "main"}, {"id": "011-b", "stage": "spec"})
        ask = self.jev(False)
        self.assertEqual(board.tag_runs_on(self.root, "010-a"), "main")
        ask.assert_not_called()
        self.assertEqual(board.tag_runs_on(self.root, "011-b"), "any")
        self.assertEqual(board.tag_runs_on(self.root, "011-b"), "any")
        self.assertEqual(ask.call_count, 1, "decided once, then read back")
        with self.subTest("a tag stored meanwhile is kept, not overwritten"):
            self.jobs({"id": "012-c", "stage": "spec"})

            def racing(*a):
                with board.locked_board(self.root) as b:
                    board.find(b, "012-c")["runs_on"] = "any"  # another caller stored it during the Jev call
                return True

            self.jev(racing)
            self.assertEqual(board.tag_runs_on(self.root, "012-c"), "any")
            self.assertEqual(self.job("012-c")["runs_on"], "any")

    def test_empty_list_asks_nothing(self):
        self.jobs({"id": "010-a", "stage": "spec", "feature": "Redraw the logo in VectorCraft\n"})
        ask = self.jev(AssertionError("no Jev call with no list"))
        with mock.patch.object(board, "main_only_terms", return_value=[]):
            self.assertEqual(board.tag_runs_on(self.root, "010-a"), "any")
        ask.assert_not_called()
        self.assertEqual(self.job("010-a")["runs_on"], "any")

    # --- criterion 2: the main-only list ---
    def test_terms_from_machine_notes(self):
        (self.base / "workers.txt").write_text("alpha 1 owa\nbeta 2 main\ngamma 1 owa\ndelta 1 main\n")
        notes = self.base / "notes"
        notes.mkdir()
        (notes / "machine-notes-alpha.md").write_text(
            "# Alpha\n- Python 3\n\n## Cannot run\n- VectorCraft, MCP\n- printer\n\n## Other\n- not, a, term\n")
        (notes / "machine-notes-beta.md").write_text("# Beta\n## Cannot run\n- MCP, .env.prod\n  continued text\n")
        (notes / "machine-notes-delta.md").write_text("# Delta\n- iMessage\n")  # no section; gamma has no file
        with mock.patch.object(board, "SHOP_NOTES", notes):
            self.assertEqual(board.main_only_terms(), ["VectorCraft", "MCP", "printer", ".env.prod"])
        (self.base / "workers.txt").unlink()  # shopmac, today's real notes file
        terms = board.main_only_terms()
        for term in ("VectorCraft", "PhotoCraft", "claude-in-chrome", "computer use", "MCP", "logged-in Chrome",
                     ".env.prod", "/trevskills-migrate", "/trevskills-datafix", "film printing", "iMessage",
                     "Keychain", "Homebrew", "brew", "PR merge"):
            self.assertIn(term, terms)
        self.assertEqual(len(terms), len(set(terms)))

    def test_term_match_whole_word(self):
        terms = ["brew", ".env.prod", "VectorCraft", "computer use", "PR merge", "/trevskills-migrate"]
        for text, want in (("Install it with Homebrew", False), ("run brew install x", True), ("BREW it", True),
                           ("copy `.env.prod` to the box", True), ("read .env.production", False),
                           ("open vectorcraft", True), ("VectorCrafty", False), ("needs Computer\n use", True),
                           ("the PR merged", False), ("then /trevskills-migrate", True), ("Fix the widget", False)):
            with self.subTest(text):
                self.assertIs(board.names_main_only(text, terms), want)
        self.assertFalse(board.names_main_only("brew", []))


if __name__ == "__main__":
    unittest.main()
