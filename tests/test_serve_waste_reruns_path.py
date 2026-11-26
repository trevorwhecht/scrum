"""Job 1577: stop_same_tests reads the same twins whatever the checkout path is. A job worktree named after a Claude Code
topic (`<repo>/.claude/worktrees/scrum-<id>-claude-code-...`) puts `claude-code` in the e2e_full_run Popen argv's
buildlock path, and board._is_claude must not take that path for a claude process."""
import sys, unittest

import test_serve_waste_reruns as base

E2E = base.E2E
FAKE_LOCK = "/r/.claude/worktrees/scrum-1576-hold-jobs-on-claude-code-s-refusal/skills/trevskills-scrum/buildlock.py"


class CheckoutPathTest(unittest.TestCase):
    setUp = base.SameTestsTest.setUp
    run_pass = base.SameTestsTest.run_pass
    lines = base.SameTestsTest.lines

    def test_tick_run_under_claude_code_worktree_path_is_kept_as_older(self):
        tick = f"{sys.executable} {FAKE_LOCK} {E2E}"
        procs = [(300, 1, 0.5, tick), (301, 300, 0.1, f"/bin/sh -c {E2E}"),
                 (302, 301, 6.0, f"node /opt/homebrew/bin/{E2E}"),
                 (400, 1, 5.0, base.cl("2003-c")), *base.bash_run(400, E2E)]
        self.cwds = {300: self.repo, 401: self.wt["2003-c"]}
        self.ages = {300: 30.0, 401: 1.0}
        got, killed = self.run_pass(procs)
        self.assertEqual(killed, [401, 402, 403])
        (line,) = self.lines()
        self.assertEqual((line["jobs"], line["kept"], line["command"]), (["2003-c"], 300, E2E))
