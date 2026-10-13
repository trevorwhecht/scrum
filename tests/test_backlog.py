import sys, tempfile, unittest
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


if __name__ == "__main__":
    unittest.main()
