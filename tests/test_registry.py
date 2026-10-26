import json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
import board  # noqa: E402


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        os.environ["SCRUM_REGISTRY"] = str(self.base / "registry" / "projects.json")

    def tearDown(self):
        os.environ.pop("SCRUM_REGISTRY", None)
        self.tmp.cleanup()

    def repo(self, *parts):
        path = self.base.joinpath(*parts)
        (path / "scrum").mkdir(parents=True)
        return path

    def test_register_is_idempotent_and_names_by_folder(self):
        a = self.repo("code", "boisepartyco")
        board.cmd_register(a)
        board.cmd_register(a)
        self.assertEqual(board.projects(), {"boisepartyco": a})

    def test_duplicate_folder_names_get_their_parent_prefixed(self):
        a, b = self.repo("nextjs", "shop"), self.repo("shopify", "shop")
        board.cmd_register(a)
        board.cmd_register(b)
        self.assertEqual(board.projects(), {"nextjs/shop": a, "shopify/shop": b})

    def test_projects_without_a_scrum_folder_are_skipped(self):
        a = self.repo("gone")
        board.cmd_register(a)
        (a / "scrum").rmdir()
        self.assertEqual(board.projects(), {})

    def test_missing_or_corrupt_registry_means_no_projects(self):
        self.assertEqual(board.projects(), {})
        Path(os.environ["SCRUM_REGISTRY"]).parent.mkdir(parents=True)
        Path(os.environ["SCRUM_REGISTRY"]).write_text("{oops")
        self.assertEqual(board.projects(), {})

    def stamp(self):  # os.replace gives the file a new inode
        st = Path(os.environ["SCRUM_REGISTRY"]).stat()
        return st.st_ino, st.st_mtime_ns

    def registry(self):
        return json.loads(Path(os.environ["SCRUM_REGISTRY"]).read_text())

    def test_move_project_reorders_and_persists(self):
        a, b, c = self.repo("a"), self.repo("b"), self.repo("c")
        gone = self.base / "gone"  # registered, no scrum/ folder: stays in the file where it was
        for r in (a, gone, b, c):
            board.cmd_register(r)
        self.assertEqual(board.move_project("c", 0), ["c", "a", "b"])
        self.assertEqual(list(board.projects()), ["c", "a", "b"])
        self.assertEqual(self.registry(), [str(c), str(gone), str(a), str(b)])
        self.assertEqual(board.move_project("c", 2), ["a", "b", "c"])
        self.assertEqual(self.registry(), [str(a), str(gone), str(b), str(c)])
        self.assertFalse(Path(os.environ["SCRUM_REGISTRY"]).with_name("projects.json.tmp").exists())
        before = self.stamp()
        self.assertEqual(board.move_project("b", 1), ["a", "b", "c"], "already there")
        self.assertEqual(self.stamp(), before, "no rewrite")
        for name, to in (("nope", 0), (None, 0), ("a", 3), ("a", -1), ("a", True), ("a", "1"), ("a", 1.0)):
            with self.subTest(name=name, to=to), self.assertRaises(SystemExit):
                board.move_project(name, to)
        self.assertEqual(self.registry(), [str(a), str(gone), str(b), str(c)])

    def test_register_after_move_appends_last(self):
        a, b = self.repo("a"), self.repo("b")
        board.cmd_register(a); board.cmd_register(b)
        board.move_project("b", 0)
        board.cmd_register(self.repo("new"))
        self.assertEqual(list(board.projects()), ["b", "a", "new"])

    def md(self, repo, text):
        (repo / "scrum" / "project.md").write_text(text)

    def test_migrate_focus_moves_to_top_and_strips_line(self):
        a, b, c, d = self.repo("a"), self.repo("b"), self.repo("c"), self.repo("d")
        for r in (a, b, c, d):
            board.cmd_register(r)
        self.md(a, "# P\n- Test: x\n")
        self.md(b, "# P\n- Focus: yes\n- Test: x\n")
        self.md(d, "# P\n- focus: YES  \n- Auto continue: 1\n")
        self.assertEqual(board.migrate_focus(), ["b", "d"])
        self.assertEqual(list(board.projects()), ["b", "d", "a", "c"])
        self.assertEqual((b / "scrum" / "project.md").read_text(), "# P\n- Test: x\n")
        self.assertEqual((d / "scrum" / "project.md").read_text(), "# P\n- Auto continue: 1\n")
        self.assertEqual((a / "scrum" / "project.md").read_text(), "# P\n- Test: x\n")

    def test_migrate_focus_idempotent_and_tolerates_bad_file(self):
        self.assertEqual(board.migrate_focus(), [], "no registry: nothing to do")
        a, b, c = self.repo("a"), self.repo("b"), self.repo("c")
        for r in (a, b, c):
            board.cmd_register(r)
        (a / "scrum" / "project.md").write_bytes(b"- Focus: yes\n\xff\xfe caf\xe9\n")  # not UTF-8: skipped
        self.md(c, "- Focus: yes\n")  # b has no project.md at all
        self.assertEqual(board.migrate_focus(), ["c"])
        self.assertEqual(list(board.projects()), ["c", "a", "b"])
        before = self.stamp()
        self.assertEqual(board.migrate_focus(), [])
        self.assertEqual(self.stamp(), before, "second call writes nothing")
        self.assertEqual(list(board.projects()), ["c", "a", "b"])


if __name__ == "__main__":
    unittest.main()
