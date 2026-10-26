import hashlib, io, json, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
import board, jev  # noqa: E402


class BacklogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "scrum"
        self.root.mkdir()
        (self.root / "backlog.md").write_text(
            "# Backlog\n"
            "- [x] Old thing → 001-old-thing\n"
            "- [ ] [5] Add CSV export <!-- touches orders API and UI -->\n"
            "- [ ] Dark mode\n"
            "some note the user wrote\n"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def text(self):
        return (self.root / "backlog.md").read_text()

    def test_items_parse_points_why_done_and_job(self):
        items = board.backlog_items(self.root)
        self.assertEqual([(i["done"], i["points"], i["text"], i["why"], i["job"]) for i in items], [
            (True, None, "Old thing", None, "001-old-thing"),
            (False, 5, "Add CSV export", "touches orders API and UI", None),
            (False, None, "Dark mode", None, None),
        ])
        self.assertEqual([i["index"] for i in items], [0, 1, 2])

    def test_add_appends_and_keeps_other_lines(self):
        board.backlog_op(self.root, "add", text="  Export to PDF  ")
        self.assertTrue(self.text().endswith("- [ ] Export to PDF\n"))
        self.assertIn("some note the user wrote\n", self.text())

    def test_add_rejects_empty_and_strips_comment_markers_and_newlines(self):
        with self.assertRaises(SystemExit):
            board.backlog_op(self.root, "add", text="   ")
        board.backlog_op(self.root, "add", text="evil <!-- x --> \nsecond line")
        self.assertEqual(board.backlog_items(self.root)[-1]["text"], "evil x second line")

    def test_edit_text_and_points_round_trip(self):
        board.backlog_op(self.root, "edit", index=2, text="Dark mode toggle", points=8)
        item = board.backlog_items(self.root)[2]
        self.assertEqual((item["text"], item["points"]), ("Dark mode toggle", 8))
        self.assertIn("- [ ] [8] Dark mode toggle\n", self.text())
        board.backlog_op(self.root, "edit", index=2, points=None)
        self.assertIn("- [ ] Dark mode toggle\n", self.text())

    def test_edit_rejects_non_fibonacci_points_without_writing(self):
        before = self.text()
        for bad in (4, 0, 21, "5"):
            with self.assertRaises(SystemExit):
                board.backlog_op(self.root, "edit", index=1, points=bad)
        self.assertEqual(self.text(), before)

    def test_delete_and_bad_index(self):
        board.backlog_op(self.root, "delete", index=1)
        self.assertNotIn("CSV", self.text())
        for bad in (-1, 9, "1"):
            with self.assertRaises(SystemExit):
                board.backlog_op(self.root, "delete", index=bad)

    def test_move_swaps_items_and_stops_at_edges(self):
        board.backlog_op(self.root, "move", index=2, delta=-1)
        self.assertEqual([i["text"] for i in board.backlog_items(self.root)], ["Old thing", "Dark mode", "Add CSV export"])
        self.assertIn("- [ ] Dark mode\n- [ ] [5] Add CSV export", self.text())
        board.backlog_op(self.root, "move", index=0, delta=-1)  # already at top: no-op
        self.assertEqual(board.backlog_items(self.root)[0]["text"], "Old thing")

    def test_move_skips_finished_items_the_dashboard_hides(self):
        (self.root / "backlog.md").write_text("- [x] A → 001-a\n- [ ] B\n- [x] C → 002-c\n- [ ] D\n")
        board.backlog_op(self.root, "move", index=3, delta=-1)
        self.assertEqual([i["text"] for i in board.backlog_items(self.root)], ["A", "D", "C", "B"])
        board.backlog_op(self.root, "move", index=1, delta=-1)  # only finished items above: no-op
        self.assertEqual(board.backlog_items(self.root)[1]["text"], "D")

    def test_move_to_takes_that_items_place(self):
        (self.root / "backlog.md").write_text("# Backlog\n\n- [ ] A\n- [x] B → 001-b\n- [ ] C\n- [ ] D\n")
        texts = lambda: [i["text"] for i in board.backlog_items(self.root)]
        board.backlog_op(self.root, "move", index=3, to=0)  # up to the top: before A
        self.assertEqual(texts(), ["D", "A", "B", "C"])
        board.backlog_op(self.root, "move", index=0, to=3)  # down to the bottom: after C
        self.assertEqual(texts(), ["A", "B", "C", "D"])
        board.backlog_op(self.root, "move", index=0, to=2)  # drag down past a finished item: after C
        self.assertEqual(texts(), ["B", "C", "A", "D"])
        with self.assertRaises(SystemExit):
            board.backlog_op(self.root, "move", index=0, to=9)
        self.assertTrue(self.text().startswith("# Backlog\n\n- [x] B"))

    def test_estimate_fills_only_the_unestimated_matching_item(self):
        board.backlog_set_estimate(self.root, "Dark mode", 3, "one toggle and a CSS variable set")
        item = board.backlog_items(self.root)[2]
        self.assertEqual((item["points"], item["why"]), (3, "one toggle and a CSS variable set"))
        board.backlog_set_estimate(self.root, "Dark mode", 13, "late duplicate")  # already estimated: ignored
        self.assertEqual(board.backlog_items(self.root)[2]["points"], 3)

    def test_next_strips_points_and_keeps_them_on_the_done_line(self):
        out = board.cmd_next(self.root)
        self.assertEqual(out["feature"], "Add CSV export")
        self.assertIn(f"- [x] [5] Add CSV export → {out['id']} <!-- touches orders API and UI -->", self.text())

    def test_next_with_index_claims_that_item_only_if_open(self):
        out = board.cmd_next(self.root, index=2)
        self.assertEqual(out["feature"], "Dark mode")
        with self.assertRaises(SystemExit):
            board.cmd_next(self.root, index=2)  # already claimed
        with self.assertRaises(SystemExit):
            board.cmd_next(self.root, index=0)  # done item

    def test_backlog_item_text_cap_2000(self):
        board.backlog_op(self.root, "add", text="a" * 1999)
        self.assertEqual(board.backlog_items(self.root)[-1]["text"], "a" * 1999)
        board.backlog_op(self.root, "add", text="b" * 2500)
        self.assertEqual(board.backlog_items(self.root)[-1]["text"], "b" * 2000)
        board.backlog_op(self.root, "edit", index=2, text="c" * 2500)
        self.assertEqual(board.backlog_items(self.root)[2]["text"], "c" * 2000)
        self.assertEqual(board.clean("x" * 500), "x" * 300)

    def triage(self, backlog, plan):
        (self.root / "backlog.md").write_text(backlog)
        out = board.cmd_triage_start(self.root)
        (self.root / "triage" / out["id"] / "plan.json").write_text(plan if isinstance(plan, str) else json.dumps(plan))
        return out

    def test_triage_start_numbers_folders_and_skips_empty_backlog(self):
        self.assertEqual(board.cmd_triage_start(self.root), {"id": "001", "open": 2})
        self.assertEqual(board.cmd_triage_start(self.root), {"id": "002", "open": 2})
        (self.root / "backlog.md").write_text("# Backlog\n- [x] Old thing → 001-old-thing\n")
        self.assertEqual(board.cmd_triage_start(self.root), {"id": None, "open": 0})
        self.assertEqual(sorted(p.name for p in (self.root / "triage").iterdir()), ["001", "002"])

    def test_triage_merge_retire_estimate(self):
        out = self.triage(
            "# Backlog\n"
            "- [x] Old thing → 001-old-thing\n"
            "- [ ] Export orders as CSV\n"
            "## Later\n"
            "- [ ] [5] CSV export button <!-- UI only -->\n"
            "some note the user wrote\n"
            "- [ ] Remove legacy flag\n"
            "- [ ] Dark mode\n"
            "- [ ] [8] Rate limiting <!-- pointed by Trevor -->\n",
            {"merge": [{"items": ["Export orders as CSV", "CSV export button"],
                        "text": "Export orders as CSV from a button (merged: CSV export, CSV button)", "points": 5,
                        "why": "API plus one button"}],
             "retire": [{"item": "Remove legacy flag", "reason": "board.py has no legacy flag since 012-cleanup"}],
             "estimate": [{"item": "Dark mode", "points": 3, "why": "one toggle and a CSS variable set"}]})
        self.assertEqual(out, {"id": "001", "open": 5})
        res = board.cmd_triage_apply(self.root, "001")
        self.assertEqual(res, {"merged": 1, "retired": 1, "manual": 0, "estimated": 1, "depends": 0, "skipped": 0})
        self.assertEqual(self.text(),
            "# Backlog\n"
            "- [x] Old thing → 001-old-thing\n"
            "- [ ] [5] Export orders as CSV from a button (merged: CSV export, CSV button) <!-- API plus one button -->\n"
            "- [x] Export orders as CSV <!-- merged into triage 001 -->\n"
            "## Later\n"
            "- [x] CSV export button <!-- merged into triage 001 -->\n"
            "some note the user wrote\n"
            "- [x] Remove legacy flag <!-- retired: board.py has no legacy flag since 012-cleanup -->\n"
            "- [ ] [3] Dark mode <!-- one toggle and a CSS variable set -->\n"
            "- [ ] [8] Rate limiting <!-- pointed by Trevor -->\n")
        report = (self.root / "triage" / "001" / "report.md").read_text()
        self.assertEqual((self.root / "triage" / "latest.md").read_text(), report)
        self.assertRegex(report.splitlines()[0], r"^# Triage 001 — \d{4}-\d\d-\d\dT")
        self.assertEqual(report.split("\n", 1)[1],
            "\n## Merged\n"
            "- Export orders as CSV from a button (merged: CSV export, CSV button)\n"
            "  - replaced: Export orders as CSV\n"
            "  - replaced: CSV export button\n"
            "\n## Retired\n"
            "- Remove legacy flag — board.py has no legacy flag since 012-cleanup\n"
            "\n## Manual\n"
            "None.\n"
            "\n## Estimated\n"
            "- [3] Dark mode — one toggle and a CSS variable set\n"
            "\n## Depends\n"
            "None.\n"
            "\n## Skipped\n"
            "None.\n")

    def test_triage_skips_stale_duplicate_and_bad_points(self):
        backlog = ("# Backlog\n- [ ] Alpha\n- [ ] Beta\n- [ ] Gamma\n- [ ] [2] Delta <!-- set by Trevor -->\n- [x] Done one → 001-x\n")
        self.triage(backlog, {
            "merge": [{"items": ["Alpha", "Gone item"], "text": "Alpha plus gone"},
                      {"items": ["Alpha"], "text": "Only one"},
                      {"items": ["Alpha", "Beta"], "text": "Alpha and Beta (merged: A, B)", "points": 4, "why": "w"}],
            "retire": [{"item": "Beta", "reason": "already merged above"},
                       {"item": "Done one", "reason": "it's done"}],
            "estimate": [{"item": "Gamma", "points": 4, "why": "not fib"},
                         {"item": "Delta", "points": 5, "why": "overwrite attempt"},
                         {"item": "Alpha", "points": 1, "why": "consumed"}]})
        res = board.cmd_triage_apply(self.root, "001")
        self.assertEqual(res, {"merged": 1, "retired": 0, "manual": 0, "estimated": 0, "depends": 0, "skipped": 7})
        self.assertEqual(self.text(),
            "# Backlog\n- [ ] Alpha and Beta (merged: A, B) <!-- w -->\n- [x] Alpha <!-- merged into triage 001 -->\n"
            "- [x] Beta <!-- merged into triage 001 -->\n- [ ] Gamma\n- [ ] [2] Delta <!-- set by Trevor -->\n"
            "- [x] Done one → 001-x\n")
        skipped = (self.root / "triage" / "latest.md").read_text().split("## Skipped\n", 1)[1]
        self.assertEqual(skipped,
            '- merge "Alpha" + "Gone item" — no open item has the text "Gone item"\n'
            '- merge "Alpha" — a merge needs at least 2 items\n'
            '- retire "Beta" — already used by an earlier entry\n'
            '- retire "Done one" — no open item has the text "Done one"\n'
            '- estimate "Gamma" — points 4 not in 1, 2, 3, 5, 8, 13\n'
            '- estimate "Delta" — already pointed\n'
            '- estimate "Alpha" — already used by an earlier entry\n')

    def test_triage_bad_plan_leaves_backlog_untouched(self):
        before = self.text()
        for plan in ("not json {", "[1, 2]", '{"depends": {"item": "Dark mode"}}', None):
            out = board.cmd_triage_start(self.root)
            if plan is not None:
                (self.root / "triage" / out["id"] / "plan.json").write_text(plan)
            with self.assertRaises(SystemExit):
                board.cmd_triage_apply(self.root, out["id"])
            self.assertEqual(self.text(), before, plan)
        r = subprocess.run([sys.executable, str(ROOT / "skills" / "trevskills-scrum" / "board.py"), "--dir", str(self.root),
                            "triage-apply", "001"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("plan.json", r.stderr)
        self.assertEqual(self.text(), before)

    # --- dependencies: {#id} and {needs #id ...} markers ---
    def test_id_and_needs_markers_round_trip(self):
        (self.root / "backlog.md").write_text(
            "# Backlog\n"
            "- [ ] [3] Add X {#k3f9} {needs #a1b2 #wx0z} <!-- why -->\n"
            "- [ ] Base {#a1b2}\n"
            "- [x] Done one {#wx0z} → 001-done\n"
            "- [ ] Only needs {needs #a1b2}\n")
        items = board.backlog_items(self.root)
        self.assertEqual([(i["text"], i["id"], i["needs"], i["points"], i["job"], i["why"]) for i in items], [
            ("Add X", "k3f9", ["a1b2", "wx0z"], 3, None, "why"),
            ("Base", "a1b2", [], None, None, None),
            ("Done one", "wx0z", [], None, "001-done", None),
            ("Only needs", None, ["a1b2"], None, None, None),
        ])
        lines, parsed = board.read_backlog(self.root)
        self.assertEqual([board.format_item(i) for i in parsed], lines[1:])
        board.backlog_op(self.root, "edit", index=0, text="Add Y")
        self.assertIn("- [ ] [3] Add Y {#k3f9} {needs #a1b2 #wx0z} <!-- why -->\n", self.text())
        board.backlog_op(self.root, "edit", index=0, points=5)
        self.assertIn("- [ ] [5] Add Y {#k3f9} {needs #a1b2 #wx0z} <!-- why -->\n", self.text())
        board.backlog_op(self.root, "move", index=1, delta=-1)
        self.assertTrue(self.text().startswith("# Backlog\n- [ ] Base {#a1b2}\n- [ ] [5] Add Y {#k3f9} {needs #a1b2 #wx0z}"))
        self.assertTrue(board.backlog_set_estimate(self.root, "Base", 2, "tiny"))
        self.assertIn("- [ ] [2] Base {#a1b2} <!-- tiny -->\n", self.text())
        self.assertTrue(board.backlog_set_estimate(self.root, "Only needs", 1, "one line"))
        self.assertIn("- [ ] [1] Only needs {needs #a1b2} <!-- one line -->\n", self.text())

    def test_old_lines_parse_unchanged(self):
        (self.root / "backlog.md").write_text(
            "# Backlog\n"
            "- [ ] Plain item\n"
            "- [ ] [5] Pointed item <!-- reason here -->\n"
            "- [ ] [?] Unknown points\n"
            "- [x] Claimed {curly} item → 012-claimed <!-- done -->\n"
            "- [x] Merged one <!-- merged into triage 001 -->\n"
            "- [ ] Braces {#TOOLONG} stay text\n")
        items = board.backlog_items(self.root)
        self.assertEqual([(i["text"], i["points"], i["job"], i["why"], i["id"], i["needs"]) for i in items], [
            ("Plain item", None, None, None, None, []),
            ("Pointed item", 5, None, "reason here", None, []),
            ("Unknown points", None, None, None, None, []),
            ("Claimed {curly} item", None, "012-claimed", "done", None, []),
            ("Merged one", None, None, "merged into triage 001", None, []),
            ("Braces {#TOOLONG} stay text", None, None, None, None, []),
        ])

    def test_markers_do_not_change_spec_path(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Ship it {#ab12} {needs #cd34}\n")
        item = board.backlog_items(self.root)[0]
        self.assertEqual(board.spec_path(self.root, item["text"]), self.spec_file("Ship it"))
        self.put_spec("Ship it", "# Ship\n")
        out = board.cmd_next(self.root)
        self.assertEqual(out["feature"], "Ship it")
        self.assertEqual((self.root / "jobs" / out["id"] / "spec.md").read_text(), "# Ship\n")

    def set_stage(self, job_id, stage):
        with board.locked_board(self.root) as b:
            board.find(b, job_id)["stage"] = stage

    def test_next_skips_item_with_open_prerequisite(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Later {needs #aaaa}\n- [ ] First {#aaaa}\n")
        out = board.cmd_next(self.root)
        self.assertEqual(out["feature"], "First")
        self.assertIn("- [ ] Later {needs #aaaa}\n", self.text())
        self.assertEqual(board.backlog_items(self.root)[0]["waits"], ["aaaa"])

    def test_next_waits_until_prerequisite_job_done(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Later {needs #aaaa}\n- [ ] First {#aaaa}\n")
        first = board.cmd_next(self.root)["id"]
        self.assertIn(f"- [x] First {{#aaaa}} → {first}\n", self.text())
        self.assertEqual(board.cmd_next(self.root), {"id": None, "feature": None})  # First's job is still in spec
        for stage in ("build", "review", "needs-human"):
            self.set_stage(first, stage)
            self.assertEqual(board.cmd_next(self.root), {"id": None, "feature": None}, stage)
        self.set_stage(first, "done")
        self.assertEqual(board.backlog_items(self.root)[0]["waits"], [])
        self.assertEqual(board.cmd_next(self.root)["feature"], "Later")
        # aborted counts as finished too
        (self.root / "backlog.md").write_text(f"# Backlog\n- [ ] Again {{needs #aaaa}}\n- [x] First {{#aaaa}} → {first}\n")
        self.set_stage(first, "aborted")
        self.assertEqual(board.cmd_next(self.root)["feature"], "Again")

    def test_next_unknown_prerequisite_does_not_block(self):
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] Needy {needs #zzzz #cccc}\n- [x] Closed {#cccc} <!-- retired: gone -->\n")
        self.assertEqual(board.backlog_items(self.root)[0]["waits"], [])
        self.assertEqual(board.cmd_next(self.root)["feature"], "Needy")

    def test_next_index_refuses_waiting_item(self):
        board.cmd_new(self.root, "Something else")  # board.json exists
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] A {#aaaa}\n- [ ] B {#bbbb}\n- [ ] C {needs #aaaa #bbbb #zzzz}\n")
        before_backlog = self.text()
        before_board = (self.root / "board.json").read_bytes()
        with self.assertRaises(SystemExit) as e:
            board.cmd_next(self.root, 2)
        self.assertEqual(str(e.exception), "backlog item 2 waits on #aaaa, #bbbb")
        self.assertEqual(self.text(), before_backlog)
        self.assertEqual((self.root / "board.json").read_bytes(), before_board)
        self.assertEqual(sorted(p.name for p in (self.root / "jobs").iterdir()), ["001-something-else"])

    def test_next_all_waiting_returns_null(self):
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] A {#aaaa} {needs #bbbb}\n- [ ] B {#bbbb} {needs #aaaa}\n")
        self.assertEqual(board.cmd_next(self.root), {"id": None, "feature": None})
        self.assertFalse((self.root / "jobs").exists())

    def test_triage_depends_assigns_ids_and_needs(self):
        self.triage("# Backlog\n- [ ] Add API\n- [ ] Add UI {needs #qqqq}\n- [ ] Add schema {#s123}\n- [ ] Docs\n",
                    {"estimate": [{"item": "Add UI", "points": 3, "why": "one page"}],
                     "depends": [{"item": "Add UI", "needs": ["Add API", "Add schema", "Add API"], "why": "UI calls the API"},
                                 {"item": "Docs", "needs": ["Add UI"], "why": "documents the UI"}]})
        with mock.patch.object(board, "new_item_id", side_effect=["api1", "ui22"]):
            res = board.cmd_triage_apply(self.root, "001")
        self.assertEqual(res, {"merged": 0, "retired": 0, "manual": 0, "estimated": 1, "depends": 2, "skipped": 0})
        self.assertEqual(self.text(),
            "# Backlog\n- [ ] Add API {#api1}\n- [ ] [3] Add UI {#ui22} {needs #qqqq #api1 #s123} <!-- one page -->\n"
            "- [ ] Add schema {#s123}\n- [ ] Docs {needs #ui22}\n")
        report = (self.root / "triage" / "001" / "report.md").read_text()
        self.assertIn("\n## Depends\n- Add UI ← Add API; Add schema\n- Docs ← Add UI\n\n## Skipped\n", report)

    def test_new_item_id_is_four_chars_and_unique(self):
        items = [{"id": "aaaa"}, {"id": None}]
        for _ in range(50):
            new = board.new_item_id(items)
            self.assertRegex(new, r"^[a-z0-9]{4}$")
            self.assertNotEqual(new, "aaaa")
        with mock.patch.object(board.secrets, "choice", side_effect=list("aaaa") + list("bbbb")):
            self.assertEqual(board.new_item_id(items), "bbbb")

    def test_triage_depends_on_merged_text(self):
        self.triage("# Backlog\n- [ ] One\n- [ ] Two\n- [ ] Three\n",
                    {"merge": [{"items": ["One", "Two"], "text": "One and two (merged: one, two)"}],
                     "depends": [{"item": "Three", "needs": ["One and two (merged: one, two)"], "why": "builds on it"},
                                 {"item": "One and two (merged: one, two)", "needs": ["Three"], "why": "cycle"}]})
        with mock.patch.object(board, "new_item_id", side_effect=["m111"]):
            res = board.cmd_triage_apply(self.root, "001")
        self.assertEqual((res["merged"], res["depends"], res["skipped"]), (1, 1, 1))
        self.assertEqual(self.text(),
            "# Backlog\n- [ ] One and two (merged: one, two) {#m111}\n- [x] One <!-- merged into triage 001 -->\n"
            "- [x] Two <!-- merged into triage 001 -->\n- [ ] Three {needs #m111}\n")

    def test_triage_depends_skips_unknown_self_and_cycle(self):
        backlog = "# Backlog\n- [ ] A {#aaaa}\n- [ ] B {#bbbb} {needs #aaaa}\n- [ ] C\n- [x] Done {#dddd} → 001-x\n"
        self.triage(backlog, {"depends": [
            {"item": "A", "needs": ["Nope"], "why": "x"},
            {"item": "Nope", "needs": ["A"], "why": "x"},
            {"item": "C", "needs": ["Done"], "why": "x"},
            {"item": "A", "needs": ["A"], "why": "x"},
            {"item": "A", "needs": ["B"], "why": "x"},
            {"item": "C", "needs": [], "why": "x"},
            "not an object"]})
        res = board.cmd_triage_apply(self.root, "001")
        self.assertEqual((res["depends"], res["skipped"]), (0, 7))
        self.assertEqual(self.text(), backlog)
        skipped = (self.root / "triage" / "latest.md").read_text().split("## Skipped\n", 1)[1]
        self.assertEqual(skipped,
            '- depends "A" ← "Nope" — no open item has the text "Nope"\n'
            '- depends "Nope" ← "A" — no open item has the text "Nope"\n'
            '- depends "C" ← "Done" — no open item has the text "Done"\n'
            '- depends "A" ← "A" — an item cannot depend on itself\n'
            '- depends "A" ← "B" — would close a dependency cycle\n'
            '- depends "C" ← nothing — needs no prerequisites\n'
            '- depends "" ← nothing — needs no prerequisites\n')

    def test_triage_merge_rewrites_needs(self):
        self.triage("# Backlog\n- [ ] One {#o111} {needs #p999}\n- [ ] Two {#t222} {needs #o111 #q888}\n"
                    "- [ ] User {needs #o111 #t222 #p999}\n- [ ] Other {needs #t222}\n- [ ] Plain\n"
                    "- [ ] Pre {#p999}\n",
                    {"merge": [{"items": ["One", "Two"], "text": "One and two"},
                               {"items": ["Plain", "Other"], "text": "Plain and other"}]})
        with mock.patch.object(board, "new_item_id", side_effect=["m111"]):
            board.cmd_triage_apply(self.root, "001")
        self.assertEqual(self.text(),
            "# Backlog\n- [ ] One and two {#m111} {needs #p999 #q888}\n- [x] One <!-- merged into triage 001 -->\n"
            "- [x] Two <!-- merged into triage 001 -->\n- [ ] User {needs #m111 #p999}\n"
            "- [ ] Plain and other {needs #m111}\n- [x] Other <!-- merged into triage 001 -->\n"
            "- [x] Plain <!-- merged into triage 001 -->\n- [ ] Pre {#p999}\n")

    def test_triage_merge_without_references_assigns_no_id(self):
        self.triage("# Backlog\n- [ ] One {needs #p999}\n- [ ] Two\n- [ ] Pre {#p999}\n",
                    {"merge": [{"items": ["One", "Two"], "text": "One and two"}]})
        with mock.patch.object(board, "new_item_id", side_effect=AssertionError("no id needed")):
            board.cmd_triage_apply(self.root, "001")
        self.assertIn("- [ ] One and two {needs #p999}\n", self.text())

    def test_triage_merge_keeps_setup_marker(self):
        self.triage("# Backlog\n- [ ] One {setup: Buy a number; Set the key}\n- [ ] Two {setup: Set the key; Add DNS}\n"
                    "- [ ] Three\n- [ ] Free\n",
                    {"merge": [{"items": ["One", "Two", "Three"], "text": "One two three"}]})
        board.cmd_triage_apply(self.root, "001")
        self.assertIn("- [ ] One two three {setup: Buy a number; Set the key; Add DNS}\n", self.text())
        self.assertEqual(board.cmd_next(self.root)["feature"], "Free")
        self.assertEqual(board.cmd_next(self.root), {"id": None, "feature": None})

    def test_triage_retire_and_manual_drop_needs(self):
        self.triage("# Backlog\n- [ ] Old {#o111}\n- [ ] Phone {#p222}\n- [ ] User {needs #o111}\n"
                    "- [ ] Both {needs #p222 #o111 #k333}\n- [ ] Keep {#k333}\n",
                    {"retire": [{"item": "Old", "reason": "done in 010-x"}],
                     "manual": [{"item": "Phone", "reason": "needs a phone"}]})
        board.cmd_triage_apply(self.root, "001")
        self.assertEqual(self.text(),
            "# Backlog\n- [x] Old <!-- retired: done in 010-x -->\n- [x] Phone <!-- manual check: needs a phone -->\n"
            "- [ ] User\n- [ ] Both {needs #k333}\n- [ ] Keep {#k333}\n")

    def test_abort_requeue_keeps_long_feature_text(self):
        job_id = board.cmd_new(self.root, "Long merged item")
        (self.root / "jobs" / job_id / "feature.md").write_text("r" * 1000 + "\n")
        board.cmd_abort(self.root, job_id, requeue=True)
        self.assertTrue(self.text().endswith("- [ ] " + "r" * 1000 + "\n"))

    def aborted_files(self, job_id):
        with board.locked_board(self.root) as b:
            return board.find(b, job_id)["files"]

    def test_abort_requeue_moved_spec_not_in_files(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Ship it\n")
        self.put_spec("Ship it", "# Ship\n")
        job_id = board.cmd_next(self.root)["id"]
        board.cmd_abort(self.root, job_id, requeue=True)
        self.assertNotIn("spec.md", self.aborted_files(job_id))
        self.assertEqual(self.spec_file("Ship it").read_text(), "# Ship\n")

    def test_abort_keeps_spec_in_files(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Ship it\n")
        self.put_spec("Ship it", "# Ship\n")
        job_id = board.cmd_next(self.root)["id"]
        board.cmd_abort(self.root, job_id, requeue=False)
        self.assertEqual(self.aborted_files(job_id), ["spec.md"])

    # --- backlog-spec: pre-written specs for follow-up items ---
    JOB = "095-bigboy"

    def followup(self, name, text):
        d = self.root / "jobs" / self.JOB / "followups"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)

    def spec_file(self, text):
        return self.root / "backlog-specs" / (hashlib.sha1(text.encode()).hexdigest()[:12] + ".md")

    def test_backlog_spec_new_adds_item_and_spec(self):
        before = self.text()
        self.followup("a.md", "Backlog: new\nItem: Add retry to fetch\n\n# Retry\nDo it.\n\n")
        out = board.cmd_backlog_spec(self.root, self.JOB)
        self.assertEqual(out, {"added": ["Add retry to fetch (from 095-bigboy)"], "updated": [], "skipped": []})
        self.assertEqual(self.text(), before + "- [ ] Add retry to fetch (from 095-bigboy)\n")
        self.assertEqual(self.spec_file("Add retry to fetch (from 095-bigboy)").read_text(), "# Retry\nDo it.\n")

    def test_backlog_spec_writes_utf8(self):
        d = self.root / "jobs" / self.JOB / "followups"
        d.mkdir(parents=True, exist_ok=True)
        (d / "a.md").write_text("Backlog: new\nItem: Cafe sign\n\ncafé — ✓\n", encoding="utf-8")
        board.cmd_backlog_spec(self.root, self.JOB)
        self.assertEqual(self.spec_file("Cafe sign (from 095-bigboy)").read_text(encoding="utf-8"), "café — ✓\n")

    def test_backlog_spec_update_replaces_spec_keeps_line(self):
        before = self.text()
        self.followup("a.md", "Backlog: update Dark mode\n\nFirst body\n")
        self.assertEqual(board.cmd_backlog_spec(self.root, self.JOB),
                         {"added": [], "updated": ["Dark mode"], "skipped": []})
        self.assertEqual(self.text(), before)
        self.assertEqual(self.spec_file("Dark mode").read_text(), "First body\n")
        self.followup("a.md", "Backlog: update Dark mode\nSecond body\n")
        board.cmd_backlog_spec(self.root, self.JOB)
        self.assertEqual(self.text(), before)
        self.assertEqual(self.spec_file("Dark mode").read_text(), "Second body\n")

    def test_backlog_spec_update_without_match_adds_new(self):
        before = self.text()
        self.followup("a.md", "Backlog: update Light mode\nLight body\n")
        self.followup("b.md", "Backlog: update Old thing\nOld body\n")  # only a done item has this text
        out = board.cmd_backlog_spec(self.root, self.JOB)
        self.assertEqual(out, {"added": ["Light mode (from 095-bigboy)", "Old thing (from 095-bigboy)"],
                               "updated": [], "skipped": []})
        self.assertEqual(self.text(), before + "- [ ] Light mode (from 095-bigboy)\n- [ ] Old thing (from 095-bigboy)\n")
        self.assertEqual(self.spec_file("Light mode (from 095-bigboy)").read_text(), "Light body\n")
        self.assertEqual(self.spec_file("Old thing (from 095-bigboy)").read_text(), "Old body\n")
        self.assertFalse(self.spec_file("Old thing").exists())

    def test_backlog_spec_skips_malformed_and_fails_when_none_processed(self):
        before = self.text()
        with self.assertRaises(SystemExit):  # no followups/ folder
            board.cmd_backlog_spec(self.root, self.JOB)
        (self.root / "jobs" / self.JOB / "followups").mkdir(parents=True)
        with self.assertRaises(SystemExit):  # empty folder
            board.cmd_backlog_spec(self.root, self.JOB)
        self.followup("1.md", "Backlog: maybe\nbody\n")
        self.followup("2.md", "Backlog: update   \nbody\n")
        self.followup("3.md", "Backlog: new\nNot an item line\nbody\n")
        self.followup("4.md", "Backlog: new\nItem:   \nbody\n")
        self.followup("5.md", "Backlog: new\nItem: Empty body\n\n  \n")
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit):  # every file skipped
            board.cmd_backlog_spec(self.root, self.JOB)
        lines = err.getvalue().splitlines()
        self.assertEqual([line.split(":")[1].strip() for line in lines], ["skipped 1.md", "skipped 2.md", "skipped 3.md",
                                                                       "skipped 4.md", "skipped 5.md"])
        self.assertTrue(all(line.startswith("backlog-spec: skipped ") for line in lines))
        self.assertEqual(self.text(), before)
        self.assertFalse((self.root / "backlog-specs").exists())
        self.followup("6.md", "Backlog: new\nItem: Good one\nbody\n")
        with redirect_stderr(io.StringIO()):
            out = board.cmd_backlog_spec(self.root, self.JOB)
        self.assertEqual(out, {"added": ["Good one (from 095-bigboy)"], "updated": [],
                               "skipped": ["1.md", "2.md", "3.md", "4.md", "5.md"]})
        self.assertEqual(self.text(), before + "- [ ] Good one (from 095-bigboy)\n")
        self.assertEqual(sorted(p.name for p in (self.root / "backlog-specs").iterdir()),
                         [self.spec_file("Good one (from 095-bigboy)").name])

    def test_backlog_spec_cli_prints_json(self):
        self.followup("a.md", "Backlog: update Dark mode\nBody\n")
        r = subprocess.run([sys.executable, str(ROOT / "skills" / "trevskills-scrum" / "board.py"), "--dir",
                            str(self.root), "backlog-spec", self.JOB], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"added": [], "updated": ["Dark mode"], "skipped": []})

    def test_next_moves_prewritten_spec(self):
        spec = self.spec_file("Add CSV export")
        spec.parent.mkdir()
        spec.write_text("# CSV\n")
        out = board.cmd_next(self.root)
        self.assertEqual(out, {"id": "001-add-csv-export", "feature": "Add CSV export"})
        self.assertEqual((self.root / "jobs" / "001-add-csv-export" / "spec.md").read_text(), "# CSV\n")
        self.assertFalse(spec.exists())
        out = board.cmd_next(self.root)  # no spec file for this one: unchanged behaviour
        self.assertEqual(out, {"id": "002-dark-mode", "feature": "Dark mode"})
        self.assertEqual(list((self.root / "jobs" / "002-dark-mode").iterdir()), [])
        self.assertIn("- [x] Dark mode → 002-dark-mode\n", self.text())

    # --- pre-written specs are dropped when their item is edited, deleted or consumed by triage ---
    def put_spec(self, text, body):
        spec = self.spec_file(text)
        spec.parent.mkdir(exist_ok=True)
        spec.write_text(body)
        return spec

    def test_edit_text_drops_prewritten_spec(self):
        old = self.put_spec("Dark mode", "# Dark\n")
        other = self.put_spec("Add CSV export", "# CSV\n")
        board.backlog_op(self.root, "edit", index=2, text="Dark mode toggle")
        self.assertFalse(old.exists())
        self.assertFalse(self.spec_file("Dark mode toggle").exists())
        self.assertEqual(other.read_text(), "# CSV\n")
        out = board.cmd_next(self.root, 2)
        self.assertEqual(out, {"id": "001-dark-mode-toggle", "feature": "Dark mode toggle"})
        self.assertEqual(list((self.root / "jobs" / "001-dark-mode-toggle").iterdir()), [])

    def test_edit_points_or_same_text_keeps_spec(self):
        spec = self.put_spec("Dark mode", "# Dark\nbody\n")
        board.backlog_op(self.root, "edit", index=2, points=3)
        self.assertEqual(spec.read_bytes(), b"# Dark\nbody\n")
        board.backlog_op(self.root, "edit", index=2, text="  Dark \n mode <!-- -->")  # cleans to "Dark mode"
        self.assertEqual(spec.read_bytes(), b"# Dark\nbody\n")
        self.assertIn("- [ ] [3] Dark mode\n", self.text())

    def test_delete_drops_prewritten_spec(self):
        spec = self.put_spec("Dark mode", "# Dark\n")
        other = self.put_spec("Add CSV export", "# CSV\n")
        board.backlog_op(self.root, "delete", index=2)
        self.assertFalse(spec.exists())
        self.assertEqual(other.read_text(), "# CSV\n")
        board.backlog_op(self.root, "delete", index=0)  # a done item, no spec
        board.backlog_op(self.root, "add", text="No spec here")
        board.backlog_op(self.root, "delete", index=1)  # open item, no spec
        self.assertEqual([i["text"] for i in board.backlog_items(self.root)], ["Add CSV export"])
        self.assertEqual(other.read_text(), "# CSV\n")

    def test_delete_without_specs_folder_does_not_raise(self):
        board.backlog_op(self.root, "delete", index=2)
        self.assertFalse((self.root / "backlog-specs").exists())

    def test_spec_kept_while_another_open_item_has_text(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Twin\n- [ ] Twin\n- [x] Gone\n")
        spec = self.put_spec("Twin", "# Twin\n")
        board.backlog_op(self.root, "edit", index=0, text="Twin renamed")
        self.assertEqual(spec.read_text(), "# Twin\n")
        board.backlog_op(self.root, "add", text="Twin")
        board.backlog_op(self.root, "delete", index=1)
        self.assertEqual(spec.read_text(), "# Twin\n")
        board.backlog_op(self.root, "delete", index=2)  # the last open "Twin"
        self.assertFalse(spec.exists())

    def test_triage_apply_drops_specs_of_consumed_items(self):
        self.triage(
            "# Backlog\n- [ ] Alpha\n- [ ] Beta\n- [ ] Gamma\n- [ ] Delta\n- [ ] Epsilon\n- [ ] Zeta\n- [ ] Keep me\n",
            {"merge": [{"items": ["Alpha", "Beta"], "text": "Alpha and Beta"},
                       {"items": ["Zeta", "Nope"], "text": "Zeta and nope"}],
             "retire": [{"item": "Gamma", "reason": "obsolete"},
                        {"item": "Zeta", "reason": ""}],
             "manual": [{"item": "Delta", "reason": "needs a phone"}],
             "estimate": [{"item": "Epsilon", "points": 3, "why": "small"},
                          {"item": "Zeta", "points": 4}]})
        specs = {t: self.put_spec(t, f"# {t}\n") for t in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Keep me")}
        res = board.cmd_triage_apply(self.root, "001")
        self.assertEqual(res, {"merged": 1, "retired": 1, "manual": 1, "estimated": 1, "depends": 0, "skipped": 3})
        for t in ("Alpha", "Beta", "Gamma", "Delta"):
            self.assertFalse(specs[t].exists(), t)
        for t in ("Epsilon", "Zeta", "Keep me"):
            self.assertEqual(specs[t].read_text(), f"# {t}\n")
        self.assertFalse(self.spec_file("Alpha and Beta").exists())

    # --- Human setup: a " {setup: step; step}" marker parks an item until Trevor clicks Setup done ---
    SETUP_LINE = ("- [ ] [3] Send SMS alerts {#k3f9} {needs #a1b2} {setup: Buy a Twilio number; Add TWILIO_TOKEN to .env}"
                  " → 003-x <!-- why -->")

    def test_setup_marker_round_trip(self):
        (self.root / "backlog.md").write_text(
            "# Backlog\n" + self.SETUP_LINE + "\n"
            "- [ ] Park me {setup: Add a DNS record}\n"
            "- [ ] Plain item\n")
        items = board.backlog_items(self.root)
        self.assertEqual([(i["text"], i["setup"]) for i in items], [
            ("Send SMS alerts", ["Buy a Twilio number", "Add TWILIO_TOKEN to .env"]),
            ("Park me", ["Add a DNS record"]),
            ("Plain item", []),
        ])
        first = items[0]
        self.assertEqual((first["id"], first["needs"], first["points"], first["job"], first["why"]),
                         ("k3f9", ["a1b2"], 3, "003-x", "why"))
        lines, parsed = board.read_backlog(self.root)
        self.assertEqual([board.format_item(i) for i in parsed], lines[1:])
        board.backlog_op(self.root, "edit", index=1, text="Park me now")
        self.assertIn("- [ ] Park me now {setup: Add a DNS record}\n", self.text())
        board.backlog_op(self.root, "edit", index=1, points=2)
        self.assertIn("- [ ] [2] Park me now {setup: Add a DNS record}\n", self.text())
        board.backlog_op(self.root, "move", index=2, delta=-1)
        self.assertTrue(self.text().endswith("- [ ] Plain item\n- [ ] [2] Park me now {setup: Add a DNS record}\n"))
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Park me {setup: Add a DNS record}\n")
        self.assertTrue(board.backlog_set_estimate(self.root, "Park me", 5, "two files"))
        self.assertEqual(self.text(), "# Backlog\n- [ ] [5] Park me {setup: Add a DNS record} <!-- two files -->\n")

    def test_backlog_add_setup(self):
        with mock.patch.object(board, "spawn_estimates") as spawn:
            board.main(["--dir", str(self.root), "backlog-add", "--setup",
                        "Buy a Twilio number; Add TWILIO_TOKEN to .env", "Send SMS alerts (from 152-x)"])
        spawn.assert_called_once_with(self.root, ["Send SMS alerts (from 152-x)"])
        self.assertTrue(self.text().endswith(
            "some note the user wrote\n"
            "- [ ] Send SMS alerts (from 152-x) {setup: Buy a Twilio number; Add TWILIO_TOKEN to .env}\n"))
        # split on ";", trimmed, empty steps dropped, braces removed
        board.cmd_backlog_add(self.root, ["Messy"], setup=" ;  Get {a} key ;; Set }DNS{ ;  ")
        self.assertTrue(self.text().endswith("- [ ] Messy {setup: Get a key; Set DNS}\n"))
        self.assertEqual(board.backlog_items(self.root)[-1]["setup"], ["Get a key", "Set DNS"])
        # without --setup nothing changes
        board.cmd_backlog_add(self.root, ["No setup here"])
        self.assertTrue(self.text().endswith("- [ ] Messy {setup: Get a key; Set DNS}\n- [ ] No setup here\n"))

    def test_backlog_add_setup_empty_checklist(self):
        before = self.text()
        r = subprocess.run([sys.executable, str(ROOT / "skills" / "trevskills-scrum" / "board.py"), "--dir", str(self.root),
                            "backlog-add", "--setup", " ; {} ;", "Send SMS alerts"], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("setup checklist is empty", r.stderr)
        self.assertEqual(self.text(), before)
        with self.assertRaises(SystemExit) as e:
            board.backlog_op(self.root, "add", text="Send SMS alerts", setup="  ")
        self.assertEqual(str(e.exception), "setup checklist is empty")
        self.assertEqual(self.text(), before)

    def test_next_skips_setup_item(self):
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] Parked {#park} {setup: Buy a number}\n- [ ] Needs parked {needs #park}\n- [ ] Free one\n")
        out = board.cmd_next(self.root)
        self.assertEqual(out["feature"], "Free one")
        self.assertEqual(self.text(), "# Backlog\n- [ ] Parked {#park} {setup: Buy a number}\n- [ ] Needs parked {needs #park}\n"
                                      f"- [x] Free one → {out['id']}\n")
        self.assertEqual(board.cmd_next(self.root), {"id": None, "feature": None})
        self.assertEqual(sorted(p.name for p in (self.root / "jobs").iterdir()), [out["id"]])

    def test_next_index_refuses_setup_item(self):
        board.cmd_new(self.root, "Something else")  # board.json exists
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Free\n- [ ] Parked {setup: Buy a number; Set the key}\n")
        before_backlog = self.text()
        before_board = (self.root / "board.json").read_bytes()
        with self.assertRaises(SystemExit) as e:
            board.cmd_next(self.root, 1)
        self.assertEqual(str(e.exception), "backlog item 1 waits on Human setup")
        self.assertEqual(self.text(), before_backlog)
        self.assertEqual((self.root / "board.json").read_bytes(), before_board)
        self.assertEqual(sorted(p.name for p in (self.root / "jobs").iterdir()), ["001-something-else"])

    def test_runall_start_skips_setup_items(self):
        backlog = ("# Backlog\n- [ ] Parked {#park} {setup: Buy a number}\n- [ ] Needs parked {needs #park}\n"
                   "- [ ] Free one\n")
        (self.root / "backlog.md").write_text(backlog)
        out = board.cmd_runall_start(self.root)
        self.assertEqual(out, {"id": "001-run-all", "children": ["002-free-one"]})
        self.assertEqual(self.text(), "# Backlog\n- [ ] Parked {#park} {setup: Buy a number}\n"
                                      "- [ ] Needs parked {needs #park}\n- [x] Free one → 002-free-one\n")
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Parked {setup: Buy a number}\n")
        self.assertEqual(board.cmd_runall_start(self.root), {"id": None, "children": []})
        self.assertEqual(self.text(), "# Backlog\n- [ ] Parked {setup: Buy a number}\n")

    def test_setup_done_op(self):
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] [?] Parked {#park} {setup: Buy a number; Set the key} <!-- why -->\n"
            "- [ ] Needs parked {needs #park}\n- [x] Done parked {setup: Old step} → 001-old\n- [ ] Plain\n")
        items = board.backlog_op(self.root, "setup-done", index=0)
        self.assertEqual(items[0]["setup"], [])
        self.assertEqual(self.text(), "# Backlog\n- [ ] [?] Parked {#park} <!-- why -->\n"
                                      "- [ ] Needs parked {needs #park}\n- [x] Done parked {setup: Old step} → 001-old\n"
                                      "- [ ] Plain\n")
        for index in (0, 2, 3):
            before = self.text()
            with self.assertRaises(SystemExit) as e:
                board.backlog_op(self.root, "setup-done", index=index)
            self.assertEqual(str(e.exception), f"backlog item {index} has no Human setup")
            self.assertEqual(self.text(), before)
        self.assertEqual(board.cmd_next(self.root)["feature"], "Parked")

    # --- {p:N} importance marker ---
    def test_priority_marker_round_trip(self):
        backlog = ("# Backlog\n"
                   "- [ ] Plain {p:3}\n"
                   "- [ ] [5] Pointed {p:1} <!-- why -->\n"
                   "- [ ] [8] Unknown {#k3f9} {p:5}\n"
                   "- [ ] Needs {p:2} {needs #k3f9}\n"
                   "- [ ] Setup {p:4} {setup: Buy a number}\n"
                   "- [x] [3] All {#a1b2} {p:5} {needs #k3f9} {setup: Step one; Step two} → 003-x <!-- why -->\n"
                   "- [x] Claimed {p:1} → 004-y\n"
                   "- [ ] Zero {p:0}\n"
                   "- [ ] Six {p:6}\n"
                   "- [ ] Letter {p:x}\n"
                   "- [ ] Unmarked\n")
        (self.root / "backlog.md").write_text(backlog)
        lines, parsed = board.read_backlog(self.root)
        self.assertEqual([board.format_item(i) for i in parsed], lines[1:])
        self.assertEqual([(i["text"], i["priority"]) for i in parsed], [
            ("Plain", 3), ("Pointed", 1), ("Unknown", 5), ("Needs", 2), ("Setup", 4), ("All", 5), ("Claimed", 1),
            ("Zero {p:0}", None), ("Six {p:6}", None), ("Letter {p:x}", None), ("Unmarked", None)])
        all_ = parsed[5]
        self.assertEqual((all_["id"], all_["needs"], all_["setup"], all_["job"], all_["why"], all_["points"]),
                         ("a1b2", ["k3f9"], ["Step one", "Step two"], "003-x", "why", 3))

    def test_priority_marker_survives_rewrites(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] One {#o111} {p:4} {needs #t222}\n- [ ] Two {#t222} {p:2}\n"
                                              "- [ ] Three {p:5}\n")
        board.backlog_op(self.root, "edit", index=0, text="One edited", points=3)
        self.assertIn("- [ ] [3] One edited {#o111} {p:4} {needs #t222}\n", self.text())
        board.backlog_op(self.root, "move", index=0, delta=1)
        self.assertEqual(self.text(), "# Backlog\n- [ ] Two {#t222} {p:2}\n- [ ] [3] One edited {#o111} {p:4} {needs #t222}\n"
                                      "- [ ] Three {p:5}\n")
        board.backlog_op(self.root, "move", index=2, to=0)
        self.assertEqual(self.text(), "# Backlog\n- [ ] Three {p:5}\n- [ ] Two {#t222} {p:2}\n"
                                      "- [ ] [3] One edited {#o111} {p:4} {needs #t222}\n")
        self.assertTrue(board.backlog_set_estimate(self.root, "Three", 2, "tiny"))
        self.assertIn("- [ ] [2] Three {p:5} <!-- tiny -->\n", self.text())
        out = board.cmd_next(self.root)
        self.assertIn(f"- [x] [2] Three {{p:5}} → {out['id']} <!-- tiny -->\n", self.text())
        # triage-apply depends and estimate rewrites
        self.triage("# Backlog\n- [ ] Api {p:3}\n- [ ] Ui {p:5}\n",
                    {"estimate": [{"item": "Ui", "points": 5, "why": "page"}],
                     "depends": [{"item": "Ui", "needs": ["Api"], "why": "calls it"}]})
        with mock.patch.object(board, "new_item_id", side_effect=["api1"]):
            board.cmd_triage_apply(self.root, "001")
        self.assertEqual(self.text(), "# Backlog\n- [ ] Api {#api1} {p:3}\n- [ ] [5] Ui {p:5} {needs #api1} <!-- page -->\n")
        # cloud-claim and runall-start claims
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Cloudy {p:4}\n")
        (self.root / "backlog-specs").mkdir(exist_ok=True)
        board.spec_path(self.root, "Cloudy").write_text("## Likely files\n- `c.py`\n")
        cid = board.cmd_cloud_claim(self.root, 1)["claimed"][0]["id"]
        self.assertEqual(self.text(), f"# Backlog\n- [x] Cloudy {{p:4}} → {cid}\n")
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Runner {#r111} {p:1}\n")
        kid = board.cmd_runall_start(self.root)["children"][0]
        self.assertEqual(self.text(), f"# Backlog\n- [x] Runner {{#r111}} {{p:1}} → {kid}\n")

    def test_setup_done_keeps_priority_marker(self):
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] [?] Parked {#park} {p:4} {needs #zzzz} {setup: Buy a number; Set the key} <!-- why -->\n")
        board.backlog_op(self.root, "setup-done", index=0)
        self.assertEqual(self.text(), "# Backlog\n- [ ] [?] Parked {#park} {p:4} {needs #zzzz} <!-- why -->\n")

    def test_backlog_add_priority_flag(self):
        with mock.patch.object(board, "spawn_estimates"):
            board.main(["--dir", str(self.root), "backlog-add", "--priority", "4", "a", "b"])
        self.assertTrue(self.text().endswith("some note the user wrote\n- [ ] a {p:4}\n- [ ] b {p:4}\n"))
        board.backlog_op(self.root, "add", text="c", priority=4)
        self.assertTrue(self.text().endswith("- [ ] b {p:4}\n- [ ] c {p:4}\n"))
        board.cmd_backlog_add(self.root, ["d"], setup="Buy a number", priority=2)
        self.assertTrue(self.text().endswith("- [ ] d {p:2} {setup: Buy a number}\n"))
        with mock.patch.object(board, "spawn_estimates"):
            board.main(["--dir", str(self.root), "backlog-add", "e"])
        self.assertTrue(self.text().endswith("- [ ] d {p:2} {setup: Buy a number}\n- [ ] e\n"))

    def test_backlog_add_priority_rejects_out_of_range(self):
        before = self.text()
        for bad in (0, 6, True, "4", 2.0):
            with self.assertRaises(SystemExit, msg=bad):
                board.cmd_backlog_add(self.root, ["a", "b"], priority=bad)
            with self.assertRaises(SystemExit, msg=bad):
                board.backlog_op(self.root, "add", text="a", priority=bad)
        for bad in ("0", "6", "abc"):
            with mock.patch.object(board, "spawn_estimates"), redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit, msg=bad):
                board.main(["--dir", str(self.root), "backlog-add", "--priority", bad, "a"])
        self.assertEqual(self.text(), before)

    def test_next_claims_highest_priority_first(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Unmarked\n- [ ] Two {p:2}\n- [ ] Three {p:3}\n"
                                              "- [ ] Five A {p:5}\n- [ ] Five B {p:5}\n")
        got = [board.cmd_next(self.root)["feature"] for _ in range(6)]
        self.assertEqual(got, ["Five A", "Five B", "Three", "Unmarked", "Two", None])

    def test_next_priority_skips_waiting_item(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Low {#low1} {p:1}\n- [ ] Parked {p:5} {setup: Buy}\n"
                                              "- [ ] Blocked {p:5} {needs #low1}\n- [ ] Mid {p:3}\n")
        self.assertEqual(board.cmd_next(self.root)["feature"], "Mid")
        self.assertEqual(board.cmd_next(self.root)["feature"], "Low")

    def test_next_index_ignores_priority(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] High {p:5}\n- [ ] Low {p:1}\n")
        self.assertEqual(board.cmd_next(self.root, index=1)["feature"], "Low")

    def test_triage_merge_takes_max_priority(self):
        self.triage("# Backlog\n- [ ] One {p:2}\n- [ ] Two\n- [ ] Three {p:4}\n",
                    {"merge": [{"items": ["One", "Two", "Three"], "text": "All three"}]})
        board.cmd_triage_apply(self.root, "001")
        self.assertIn("- [ ] All three {p:4}\n", self.text())

    def test_triage_merge_without_priority_has_none(self):
        self.triage("# Backlog\n- [ ] One\n- [ ] Two\n",
                    {"merge": [{"items": ["One", "Two"], "text": "Both"}]})
        board.cmd_triage_apply(self.root, "001")
        self.assertTrue(self.text().startswith("# Backlog\n- [ ] Both\n"))
        self.assertEqual(board.backlog_items(self.root)[0]["priority"], None)

    def test_backlog_items_carry_priority(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Marked {p:5}\n- [ ] Unmarked\n")
        items = board.backlog_items(self.root)
        self.assertEqual([(i["text"], i["priority"]) for i in items], [("Marked", 5), ("Unmarked", None)])


    # --- rank-backlog ---
    RANK_BACKLOG = ("# Backlog\n"
                    "- [ ] [5] Add CSV export {#ab12} {needs #cd34} {setup: Buy a key} <!-- touches orders API -->\n"
                    "- [ ] Already rated {p:3}\n"
                    "- [x] Old thing → 001-old-thing\n"
                    "- [x] Closed unmarked\n"
                    "note line\n"
                    "- [ ] Polish the footer\n"
                    "- [ ] Jev chokes on this\n")

    def rank_backlog(self, answers, during=None):
        """Run rank-backlog via main with jev.ask stubbed; answers maps ticket text -> (importance, necessity, progress,
        kind) or None (Jev error). Returns (printed JSON, the tickets Jev was asked about)."""
        (self.root / "project.md").write_text("- Notes: Ship the orders app\n")
        asked = []

        def fake(state, questions, timeout=jev.TIMEOUT, key=None):
            asked.append(state["ticket"])
            if during:
                during(state["ticket"])
            a = answers[state["ticket"]]
            if a is None:
                raise jev.JevError("down")
            return {"importance": {"score": a[0]}, "necessity": {"score": a[1]}, "progress": {"noul": a[2]},
                    "kind": {"choice": a[3]}}
        out = io.StringIO()
        with mock.patch.object(jev, "ask", side_effect=fake), mock.patch("sys.stdout", out):
            board.main(["--dir", str(self.root), "rank-backlog"])
        return json.loads(out.getvalue()), asked

    ANSWERS = {"Add CSV export": (3.8, 2, 0.9, "feature"), "Polish the footer": (2, 2, 0.2, "ui-polish"),
               "Jev chokes on this": None}

    def test_rank_backlog_rates_only_unmarked_open_items(self):
        (self.root / "backlog.md").write_text(self.RANK_BACKLOG)
        out, asked = self.rank_backlog(self.ANSWERS)
        self.assertEqual(out, {"rated": 2, "unrated": 1, "skipped": 1})
        self.assertEqual(asked, ["Add CSV export", "Polish the footer", "Jev chokes on this"])
        self.assertEqual(self.text(), "# Backlog\n"
                         "- [ ] [5] Add CSV export {#ab12} {p:5} {needs #cd34} {setup: Buy a key} <!-- touches orders API -->\n"
                         "- [ ] Already rated {p:3}\n"
                         "- [x] Old thing → 001-old-thing\n"
                         "- [x] Closed unmarked\n"
                         "note line\n"
                         "- [ ] Polish the footer {p:2}\n"
                         "- [ ] Jev chokes on this\n")
        log = (self.root / "jev.log").read_text().splitlines()
        self.assertEqual([(len(l.split("\t")), l.split("\t")[1], l.split("\t")[4]) for l in log],
                         [(6, "rank", "p5 feature"), (6, "rank", "p2 ui-polish"), (6, "rank", "none")])

    def test_rank_backlog_second_run_makes_no_calls(self):
        (self.root / "backlog.md").write_text(self.RANK_BACKLOG)
        self.rank_backlog(self.ANSWERS | {"Jev chokes on this": (1, 2, 0.9, "tests")})
        before = (self.root / "backlog.md").read_bytes()
        out, asked = self.rank_backlog({})
        self.assertEqual((out, asked), ({"rated": 0, "unrated": 0, "skipped": 4}, []))
        self.assertEqual((self.root / "backlog.md").read_bytes(), before)

    def test_rank_backlog_skips_item_edited_mid_run(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Edit me\n- [ ] Delete me\n- [ ] Keep me\n")

        def during(ticket):
            if ticket == "Keep me":  # the last call: change the file after rank-backlog read it
                (self.root / "backlog.md").write_text("# Backlog\n- [ ] Edit me please\n- [ ] Keep me\n"
                                                      "- [ ] Added meanwhile\n")
        out, asked = self.rank_backlog({t: (2, 2, 0.9, "bug") for t in ("Edit me", "Delete me", "Keep me")}, during)
        self.assertEqual(out, {"rated": 1, "unrated": 2, "skipped": 0})
        self.assertEqual(self.text(), "# Backlog\n- [ ] Edit me please\n- [ ] Keep me {p:3}\n- [ ] Added meanwhile\n")

if __name__ == "__main__":
    unittest.main()
