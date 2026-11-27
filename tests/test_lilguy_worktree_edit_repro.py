"""Job 1649 repro: a lilguy session runs in the orchestrator's own session, whose cwd is the main checkout ($REPO),
and lanes/lilguy.md never says every edit path is under $WT or what to do when $WT is missing. onewitharts job 2202's
session left an uncommitted docs/logic/file-storage.md edit in the main checkout that blocked 7 merges."""
import unittest
from pathlib import Path

LILGUY = Path(__file__).resolve().parents[1] / "skills" / "trevskills-scrum" / "lanes" / "lilguy.md"


class LilguyWorktreeOnlyEdits(unittest.TestCase):
    def setUp(self):
        self.text = LILGUY.read_text()

    def test_every_edit_path_is_under_wt_never_repo(self):
        self.assertIn("Every edit of the target repo uses a path under `$WT/`, never `$REPO`", self.text)

    def test_missing_worktree_asks_and_never_falls_back_to_repo(self):
        self.assertIn('git -C "$WT" rev-parse --is-inside-work-tree', self.text)
        self.assertIn("never fall back to editing `$REPO`", self.text)


if __name__ == "__main__":
    unittest.main()
