import json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
import board  # noqa: E402

BOARD_PY = ROOT / "skills" / "trevskills-scrum" / "board.py"

# A fake `claude` that answers the estimate prompt with a fixed estimate (same as tests/test_serve.py's stub).
STUB = r'''#!/usr/bin/env python3
import sys
if any("estimating" in a for a in sys.argv):
    print("{\"points\": 5, \"why\": \"several files\"}")
'''


class SmallFixesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "scrum"
        self.root.mkdir()
        guard = mock.patch.object(board, "merge_refusal", return_value=None)  # PR-less fixture jobs may go done
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, job_id):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id)

    def set_files(self, job_id, files):
        data = json.loads((self.root / "board.json").read_text())
        next(j for j in data["jobs"] if j["id"] == job_id)["files"] = files
        (self.root / "board.json").write_text(json.dumps(data))

    def test_abort_refreshes_files(self):
        for requeue in (False, True):
            job_id = board.cmd_new(self.root, f"obsolete {requeue}")
            (self.root / "jobs" / job_id / "feature.md").write_text("Feature\n")
            (self.root / "jobs" / job_id / "spec.md").write_text("OBSOLETE: done already\n")
            board.cmd_abort(self.root, job_id, requeue)
            self.assertEqual(self.job(job_id)["files"], ["feature.md", "spec.md"], f"requeue={requeue}")
        gone = board.cmd_new(self.root, "no folder")
        self.set_files(gone, ["stale.md"])
        shutil.rmtree(self.root / "jobs" / gone)
        board.cmd_abort(self.root, gone, False)
        self.assertEqual(self.job(gone)["files"], [])

    def test_reopen_keeps_long_note(self):
        old = board.cmd_new(self.root, "old")
        board.cmd_set(self.root, old, ["stage=done"])
        note = ("word " * 300).strip()  # 1499 chars after whitespace collapse
        self.assertEqual(len(note), 1499)
        new = board.cmd_reopen(self.root, old, "  " + note.replace(" ", " \n ") + "  ")
        feature = (self.root / "jobs" / new / "feature.md").read_text()
        self.assertEqual(feature.split("\n", 1)[0], note)

        old2 = board.cmd_new(self.root, "old2")
        board.cmd_set(self.root, old2, ["stage=done"])
        new2 = board.cmd_reopen(self.root, old2, "y" * 2500)
        self.assertEqual((self.root / "jobs" / new2 / "feature.md").read_text().split("\n", 1)[0], "y" * 2000)

        old3 = board.cmd_new(self.root, "old3")
        board.cmd_set(self.root, old3, ["stage=done"])
        with self.assertRaises(SystemExit) as e:
            board.cmd_reopen(self.root, old3, " \n\t ")
        self.assertIn("note is empty", str(e.exception))

    def test_backlog_add_cli_estimates_dash_item(self):
        # One word on purpose: argparse reads a dash-led argument with a space in it as a value, not an option.
        stub = Path(self.tmp.name) / "claude"
        stub.write_text(STUB)
        stub.chmod(0o755)
        (self.root / "backlog.md").write_text("# Backlog\n")
        env = dict(os.environ, SCRUM_CLAUDE=str(stub))
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "backlog-add", "--", "-dash"],
                           capture_output=True, text=True, timeout=5, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        end = time.time() + 10
        while time.time() < end and board.backlog_items(self.root)[0]["points"] is None:
            time.sleep(0.05)
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [ ] [5] -dash <!-- several files -->\n")

    def test_triage_skips_overlong_merge(self):
        backlog = "# Backlog\n- [ ] Alpha\n- [ ] Beta\n- [ ] Gamma\n- [ ] Delta\n"
        (self.root / "backlog.md").write_text(backlog)
        self.assertEqual(board.cmd_triage_start(self.root)["id"], "001")
        exact = "e" * 2000
        plan = {"merge": [{"items": ["Alpha", "Beta"], "text": "a " * 1000 + "z"},  # 2001 chars once cleaned
                          {"items": ["Alpha", "Beta"], "text": "Alpha and Beta"},  # may reuse the skipped items
                          {"items": ["Gamma", "Delta"], "text": exact}]}
        (self.root / "triage" / "001" / "plan.json").write_text(json.dumps(plan))
        res = board.cmd_triage_apply(self.root, "001")
        self.assertEqual(res, {"merged": 2, "retired": 0, "estimated": 0, "skipped": 1})
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [ ] Alpha and Beta\n- [x] Alpha <!-- merged into triage 001 -->\n"
                         "- [x] Beta <!-- merged into triage 001 -->\n"
                         f"- [ ] {exact}\n- [x] Gamma <!-- merged into triage 001 -->\n"
                         "- [x] Delta <!-- merged into triage 001 -->\n")
        skipped = (self.root / "triage" / "001" / "report.md").read_text().split("## Skipped\n", 1)[1]
        self.assertEqual(skipped, '- merge "Alpha" + "Beta" — merged text is over 2000 characters\n')


if __name__ == "__main__":
    unittest.main()
