import hashlib, io, json, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
import board  # noqa: E402


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
        self.assertEqual(res, {"merged": 1, "retired": 1, "estimated": 1, "skipped": 0})
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
            "\n## Estimated\n"
            "- [3] Dark mode — one toggle and a CSS variable set\n"
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
        self.assertEqual(res, {"merged": 1, "retired": 0, "estimated": 0, "skipped": 7})
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
        for plan in ("not json {", "[1, 2]", None):
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

    def test_abort_requeue_keeps_long_feature_text(self):
        job_id = board.cmd_new(self.root, "Long merged item")
        (self.root / "jobs" / job_id / "feature.md").write_text("r" * 1000 + "\n")
        board.cmd_abort(self.root, job_id, requeue=True)
        self.assertTrue(self.text().endswith("- [ ] " + "r" * 1000 + "\n"))

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


if __name__ == "__main__":
    unittest.main()
