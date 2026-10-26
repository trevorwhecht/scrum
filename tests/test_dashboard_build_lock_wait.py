"""A Check job whose build is queued for the machine-wide build lock says so on its status line."""
import json, shutil, subprocess, unittest

from test_dashboard_job_modal import DASHBOARD


def status(job):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    pick = lambda *starts: "\n".join(l for l in text.splitlines() if l.startswith(starts))
    src = pick("const paused = ", "const setupWait = ", "const playQueued = ")
    src += "\n" + text[text.index("const noPaths = "):text.index("// A needs-human job's closed question")]
    script = f"{src}\nconsole.log(JSON.stringify(statusLine({json.dumps(job)})));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


class BuildLockWait(unittest.TestCase):
    def test_flag_shows_the_line(self):
        self.assertEqual(status({"stage": "check", "buildLockWait": True, "updatedAt": "2026-01-01T00:00:00Z"}),
                         "Waiting for the build lock")

    def test_without_flag_unchanged(self):
        self.assertRegex(status({"stage": "check", "updatedAt": "2026-01-01T00:00:00Z"}), r"^Checking, \d+ min$")

    def test_other_cases_keep_their_line(self):
        base = {"stage": "check", "buildLockWait": True, "updatedAt": "2026-01-01T00:00:00Z"}
        self.assertEqual(status({**base, "paused": True}), "Paused by you")
        self.assertEqual(status({**base, "waitingOn": {"ids": ["2-b"], "why": "not merged yet"}}),
                         "Waiting on 2-b (not merged yet)")
        self.assertEqual(status({**base, "stage": "needs-human", "question": "Pick one"}), "Waiting on you: Pick one")


if __name__ == "__main__":
    unittest.main()
