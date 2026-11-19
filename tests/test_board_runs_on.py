"""Job 1155: each job carries a Runs on tag (any, main, shop). feature.md's `Runs on:` header wins, else Jev over the
workers' `## Cannot run` lists decides once and the board stores it. serve.py's shop-room.json says whether a worker
has room; with room, cmd_ready leaves an `any` waiting child to the shop for up to SHOP_FIRST_MAX_S and never claims a
`shop` one."""
import json, os, sys, tempfile, time, unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
        self.assertIn("PhotoCraft", terms)
        self.assertEqual(log, self.root / "jobs" / "010-a" / "jev.log")
        self.jev(False)
        self.assertEqual(board.tag_runs_on(self.root, "011-b"), "any")
        self.assertEqual(self.job("011-b")["runs_on"], "any")

    def test_jev_down_falls_back_to_terms(self):
        self.jobs({"id": "010-a", "stage": "spec", "feature": "Separate the art in PhotoCraft\n"},
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
        self.assertNotIn("VectorCraft", terms)  # installed on the shop by hand, 2026-11-19
        for term in ("PhotoCraft", "claude-in-chrome", "computer use", "MCP", "logged-in Chrome",
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

    # --- criterion 3: the room file ---
    def test_shop_room_fresh_stale_missing(self):
        self.assertFalse(board.shop_room(self.root), "no file")
        self.room()
        self.assertTrue(board.shop_room(self.root))
        self.room(age=170)
        self.assertTrue(board.shop_room(self.root), "170 s old is still fresh")
        self.room(age=200)
        self.assertFalse(board.shop_room(self.root), "stale past 180 s")
        self.room(workers=())
        self.assertFalse(board.shop_room(self.root), "no worker has room")
        for text in ("not json", "[]", '{"workers": ["shopmac"]}', '{"at": "soon", "workers": ["shopmac"]}',
                     json.dumps({"at": time.time(), "workers": "shopmac"}), json.dumps({"at": time.time()})):
            with self.subTest(text):
                (self.base / "shop-room.json").write_text(text)
                self.assertFalse(board.shop_room(self.root))
        self.room()
        with mock.patch.dict(os.environ), mock.patch.object(board, "registry_path", return_value=self.base / "projects.json"):
            del os.environ["SCRUM_REGISTRY"]  # a test that forgot to move the registry never reads the real file
            self.assertFalse(board.shop_room(self.root))

    def test_shop_room_false_for_docker_and_base_branch(self):
        self.room()
        for profile in ("# Project\n- Base branch: dev\n", "# Project\n- E2E: DOCKER compose up\n",
                        "# Project\n- Notes: runs in a docker container\n"):
            with self.subTest(profile):
                (self.root / "project.md").write_text(profile)
                self.assertTrue(board.shop_project_excluded(self.root))
                self.assertFalse(board.shop_room(self.root))
        (self.root / "project.md").write_text("# Project\n- Test: x\n- Notes: the base branch is main\n")
        self.assertFalse(board.shop_project_excluded(self.root))
        self.assertTrue(board.shop_room(self.root))

    # --- criteria 5, 6, 7 and 9: cmd_ready with and without room ---
    def kid(self, job_id, src, **extra):
        """A parallel waiting child whose spec.md names src/<src>.py, so siblings never clash."""
        return {"id": job_id, "parallel": True, "spec": f"# Spec\n## Likely files\n- `src/{src}.py`\n", **extra}

    def ready(self, **kw):
        return board.cmd_ready(self.root, PAR, **kw)["ready"]

    def ago(self, seconds):
        return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")

    def test_ready_leaves_any_child_to_shop_and_claims_main(self):
        (self.root.parent / "src").mkdir()
        self.runall(self.kid("010-a", "a"), self.kid("011-b", "b", feature="Separate the art in PhotoCraft\n"))
        self.room()
        ask = self.jev(None)  # Jev down: the term list decides
        self.assertEqual(self.ready(), ["011-b"], "the main sibling is still claimed in the same call")
        a, b = self.job("010-a"), self.job("011-b")
        self.assertEqual((a["stage"], a["runs_on"]), ("waiting", "any"))
        self.assertEqual((b["stage"], b["runs_on"]), ("spec", "main"))
        self.assertNotIn("shop_first_since", b)
        since = a["shop_first_since"]
        for kw in ({}, {"manual": True}, {"only": "010-a"}):
            with self.subTest(**kw):
                self.assertEqual(self.ready(**kw), [])
                self.assertEqual(self.job("010-a")["shop_first_since"], since, "set once")
                self.assertEqual(self.job("010-a")["stage"], "waiting")
        self.assertEqual(ask.call_count, 2, "each child asked once, then read back")
        with self.subTest("a parent whose only open child waits for the shop keeps running"):
            self.runall(self.kid("010-a", "a"))
            self.assertEqual(self.ready(), [])
            self.assertEqual((self.job(PAR)["stage"], self.job(PAR)["reason"]), ("running", None))

    def test_ready_claims_any_child_when_no_room(self):
        (self.root.parent / "src").mkdir()
        self.runall(self.kid("010-a", "a"), self.kid("011-b", "b"))
        self.jev(AssertionError("no Jev without room"))
        self.assertEqual(self.ready(), ["010-a", "011-b"])
        for job_id in ("010-a", "011-b"):
            job = self.job(job_id)
            self.assertEqual(job["stage"], "spec")
            self.assertNotIn("shop_first_since", job)
            self.assertNotIn("runs_on", job)
            self.assertTrue((self.root / "jobs" / job_id / "claimed-at.txt").is_file())
        for workers, age in (((), 0), (("shopmac",), 200)):  # no worker with room, or a stale file
            with self.subTest(workers=workers, age=age):
                self.runall(self.kid("010-a", "a"))
                self.room(workers, age)
                self.assertEqual(self.ready(), ["010-a"])

    def test_ready_claims_lilguy_and_digest_children_despite_room(self):
        (self.root.parent / "src").mkdir()
        self.runall(self.kid("010-a", "a", lane="lilguy"),
                    self.kid("011-b", "b", feature="Fix the widget\n\n## Notes\nLane: lilguy\n"),
                    self.kid("012-c", "c", fit=True),
                    self.kid("013-d", "d", feature="Expand digests/042/proposals.json\n"),
                    self.kid("014-e", "e"))
        self.room()
        self.jev(False)
        self.assertEqual(self.ready(), ["010-a", "011-b", "012-c", "013-d"])
        self.assertEqual(self.job("014-e")["stage"], "waiting")
        jobs = [{"id": "020-p", "lane": "bigboy"}, {"id": "021-k", "parent": "020-p"}, {"id": "022-n"}]
        for job in jobs[1:]:
            (self.root / "jobs" / job["id"]).mkdir()
            (self.root / "jobs" / job["id"] / "lilguy-fit.json").write_text('{"fit": true}')
        self.assertFalse(board.shop_excluded(self.root, jobs[1], jobs), "a fit BigBoy child is not lilguy's")
        self.assertTrue(board.shop_excluded(self.root, jobs[2], jobs), "a fit parentless job is")

    def test_ready_claims_after_shop_first_max(self):
        (self.root.parent / "src").mkdir()
        self.runall(self.kid("010-a", "a", shop_first_since=self.ago(board.SHOP_FIRST_MAX_S + 1)),
                    self.kid("011-b", "b", shop_first_since=self.ago(200)),
                    self.kid("012-c", "c", shop_first_since="soon"))
        self.room()
        self.jev(False)
        self.assertEqual(board.SHOP_FIRST_MAX_S, 300)
        recent = self.job("011-b")["shop_first_since"]
        self.assertEqual(self.ready(), ["010-a"])
        self.assertNotIn("shop_first_since", self.job("010-a"), "a claim drops it")
        self.assertEqual(self.job("011-b")["shop_first_since"], recent)
        self.assertNotEqual(self.job("012-c")["shop_first_since"], "soon", "a malformed time starts again")
        self.assertEqual(self.job("012-c")["stage"], "waiting")

    def test_ready_never_claims_shop_child(self):
        (self.root.parent / "src").mkdir()
        self.runall(self.kid("010-a", "a", feature="Runs on: shop\n\nFix the widget\n"),
                    self.kid("011-b", "b", feature="Runs on: main\n\nFix the widget\n"))
        self.jev(AssertionError("the header decides"))
        self.assertEqual(self.ready(), ["011-b"])
        for kw in ({}, {"manual": True}, {"only": "010-a"}):
            with self.subTest(room=False, **kw):
                self.assertEqual(self.ready(**kw), [])
        self.room()
        for kw in ({}, {"manual": True}, {"only": "010-a"}):
            with self.subTest(room=True, **kw):
                self.assertEqual(self.ready(**kw), [])
        self.assertEqual(self.job("010-a")["stage"], "waiting")
        with self.subTest("a parent whose only open child is a shop one keeps running"):
            self.runall(self.kid("010-a", "a", feature="Runs on: shop\n"))
            (self.base / "shop-room.json").unlink()
            self.assertEqual(self.ready(), [])
            self.assertEqual((self.job(PAR)["stage"], self.job(PAR)["reason"]), ("running", None))
        with self.subTest("the shop claims it; a shop call never claims a main one"):
            self.runall(self.kid("010-a", "a", feature="Runs on: shop\n"), self.kid("011-b", "b", feature="Runs on: main\n"))
            self.assertEqual(self.ready(shop="011-b"), [])
            self.assertEqual(self.ready(shop="010-a"), ["010-a"])

    def test_ready_asks_no_jev_without_room(self):
        (self.root.parent / "src").mkdir()
        self.runall(self.kid("010-a", "a"))
        self.jev(AssertionError("no Jev without room"))
        with mock.patch.object(board, "tag_runs_on") as tag:
            self.assertEqual(self.ready(), ["010-a"])
            self.runall(self.kid("010-a", "a"))
            self.room()
            (self.root / "project.md").write_text("# Project\n- Base branch: dev\n")  # never a shop project
            self.assertEqual(self.ready(), ["010-a"])
        tag.assert_not_called()

    def test_ready_tags_before_the_lock(self):
        (self.root.parent / "src").mkdir()
        self.runall(self.kid("010-a", "a"), self.kid("011-b", "b"), self.kid("012-c", "c", lane="lilguy"))
        self.room()
        depth, real = [0], board.locked_board

        @contextmanager
        def watched(*a, **kw):
            depth[0] += 1
            try:
                with real(*a, **kw) as b:
                    yield b
            finally:
                depth[0] -= 1

        asked = []
        self.jev(lambda text, terms, log: asked.append((log.parent.name, depth[0])) or False)
        with mock.patch.object(board, "locked_board", watched):
            self.assertEqual(self.ready(), ["012-c"])
        self.assertEqual(asked, [("010-a", 0), ("011-b", 0)], "asked outside the lock; a lilguy child is not asked")
        with self.subTest("under the lock an untagged child counts as any"):
            self.runall(self.kid("010-a", "a"))
            with mock.patch.object(board, "tag_runs_on") as tag:
                self.assertEqual(self.ready(), [])
            tag.assert_called_once_with(self.root, "010-a")
            self.assertNotIn("runs_on", self.job("010-a"))
            self.assertIn("shop_first_since", self.job("010-a"))


if __name__ == "__main__":
    unittest.main()
