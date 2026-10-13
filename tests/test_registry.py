import os, sys, tempfile, unittest
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


if __name__ == "__main__":
    unittest.main()
