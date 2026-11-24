"""board.py e2e-stopped (job 1497): reads jobs/<id>/e2e-stopped.json, the marker serve.py's e2e_runaway_tick writes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum"))
import board  # noqa: E402


class E2eStoppedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "jobs" / "1497-runaway-test").mkdir(parents=True)

    def write(self, text):
        (self.root / "jobs" / "1497-runaway-test" / "e2e-stopped.json").write_text(text)

    def test_e2e_stopped_reads_marker(self):
        self.write(json.dumps({"reason": "memory", "count": 1, "at": 5}))
        self.assertEqual(board.cmd_e2e_stopped(self.root, "1497-runaway-test"),
                         {"stopped": True, "count": 1, "reason": "memory", "line": "E2E stopped: memory"})
        self.write(json.dumps({"reason": "disk", "count": 2, "at": 6}))
        self.assertEqual(board.cmd_e2e_stopped(self.root, "1497-runaway-test"),
                         {"stopped": True, "count": 2, "reason": "disk", "line": "E2E: not run, stopped: disk twice"})

    def test_no_marker_is_not_stopped(self):
        none = {"stopped": False, "count": 0, "reason": None, "line": None}
        self.assertEqual(board.cmd_e2e_stopped(self.root, "1497-runaway-test"), none)
        for bad in ("not json", "[]", json.dumps({"reason": "x", "count": 1}), json.dumps({"reason": "disk", "count": 0})):
            self.write(bad)
            self.assertEqual(board.cmd_e2e_stopped(self.root, "1497-runaway-test"), none, bad)


if __name__ == "__main__":
    unittest.main()
