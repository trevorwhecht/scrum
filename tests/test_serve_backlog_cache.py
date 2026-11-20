"""Job 1232: serve.py cached_backlog_items re-reads an open item's {after repo:job} wait once that repo's board.json
changes, and keeps its one-stat-per-file hit for a backlog with no such item."""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

import test_serve  # noqa: F401  its import-time env pins (SCRUM_IDLE_CLEANUP=0, SCRUM_PS, ...) apply first
import serve


class BacklogCacheAfterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(os.path.realpath(tmp.name))
        self.root = base / "app" / "scrum"
        self.other = base / "otherrepo" / "scrum"
        self.root.mkdir(parents=True)
        self.other.mkdir(parents=True)
        self.registry = base / "projects.json"
        self.registry.write_text(json.dumps([str(base / "app"), str(base / "otherrepo")]))
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=str(self.registry))
        env.start()
        self.addCleanup(env.stop)
        serve.BACKLOG_CACHE.clear()
        self.addCleanup(serve.BACKLOG_CACHE.clear)

    def other_job(self, stage):
        (self.other / "board.json").write_text(json.dumps({"jobs": [{"id": "1600-thing", "stage": stage}]}))

    def test_after_wait_clears_when_the_other_board_changes(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Later {after otherrepo:1600}\n")
        self.other_job("build")
        self.assertEqual(serve.cached_backlog_items(self.root)[0]["waits"], ["otherrepo:1600"])
        self.other_job("done")
        self.assertEqual(serve.cached_backlog_items(self.root)[0]["waits"], [])

    def test_after_wait_rechecked_when_the_registry_changes(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Later {after otherrepo:1600}\n")
        self.other_job("done")
        self.registry.write_text(json.dumps([str(self.root.parent)]))  # otherrepo unregistered: its ref blocks
        self.assertEqual(serve.cached_backlog_items(self.root)[0]["waits"], ["otherrepo:1600"])
        self.registry.write_text(json.dumps([str(self.root.parent), str(self.other.parent)]))
        self.assertEqual(serve.cached_backlog_items(self.root)[0]["waits"], [])

    def test_no_after_item_keeps_the_hit_when_another_board_changes(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Plain\n")
        self.other_job("build")
        first = serve.cached_backlog_items(self.root)
        self.other_job("done")
        self.assertIs(serve.cached_backlog_items(self.root), first)


if __name__ == "__main__":
    unittest.main()
