"""Job 1178 (BigBoy 1165, waste kind `same-tests`): serve.py stop_same_tests stops the newer of two identical full
Test or E2E runs on one clean commit (keeping the older) and logs a full E2E run of a head e2e-full.json already holds
a finished result for, without stopping it."""
import io, json, os, signal, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

import test_serve  # noqa: F401  its import-time env pins (SCRUM_IDLE_CLEANUP=0, SCRUM_PS, ...) apply first
import serve

board = serve.board
TEST = "python3 -m unittest discover -s tests -v"
E2E = "npx playwright test"
PORT_E2E = ("E2E_PORT=$(python3 -c 'import socket;s=socket.socket();s.bind((\"\",0));print(s.getsockname()[1])') "
            "npm run test:e2e")
PY = "/Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python"  # macOS python3
HEAD = "c0ffee1"


def cl(job_id):
    return f"/usr/local/bin/claude -p /trevskills-scrum build {job_id} --permission-mode bypassPermissions"


def zsh(cmd):
    """The Bash tool's wrapper line around cmd."""
    return f"/bin/zsh -c -l source /x/snap.sh && eval '{cmd} 2>&1 | tail -40' < /dev/null"


def bash_run(top, cmd, cpu=3.0):
    """A Bash-tool run under session pid top: zsh wrapper top+1 runs cmd, top+2 is the suite, top+3 is tail."""
    suite = f"{PY}{cmd[7:]}" if cmd.startswith("python3") else f"node /opt/homebrew/bin/{cmd}"
    return [(top + 1, top, 0.1, zsh(cmd)), (top + 2, top + 1, cpu, suite), (top + 3, top + 1, 0.0, "tail -40")]


class SuiteRunTest(unittest.TestCase):
    def test_suite_run_matching(self):
        true = [(TEST, TEST),
                (f"/opt/homebrew/bin/python3 /x/buildlock.py {TEST}", TEST),
                (f"/bin/zsh -c -l source /x/snap.sh && eval '{TEST} 2>&1 | tail -40' < /dev/null", TEST),
                ("node /opt/homebrew/bin/npx playwright test", E2E),
                (f"/opt/homebrew/bin/python3 /x/buildlock.py {PORT_E2E}", PORT_E2E)]
        false = [(f"{TEST} -k cmd_ready", TEST),
                 ("python3 -m unittest discover -s tests -p 'test_x.py' -v", TEST),
                 ("npx playwright test e2e/cart.spec.ts", E2E),
                 ("npm run test:e2e -- e2e/cart.spec.ts", PORT_E2E)]
        for line, cmd in true:
            with self.subTest(line=line):
                self.assertTrue(serve.suite_run(line, cmd))
        for line, cmd in false:
            with self.subTest(line=line):
                self.assertFalse(serve.suite_run(line, cmd))

    def test_proc_ages_parses_etime(self):
        out = mock.Mock(returncode=0, stdout="  100 03:10\n  200 1-02:00:00\n")
        with mock.patch.object(serve.subprocess, "run", return_value=out) as run:
            self.assertEqual(serve.proc_ages([100, 200, 300]), {100: 3.17, 200: 1560.0})
        self.assertEqual(run.call_args.args[0], ["ps", "-o", "pid=,etime=", "-p", "100,200,300"])
        self.assertEqual(run.call_args.kwargs.get("timeout"), 5)
        for err in (OSError("no ps"), subprocess.TimeoutExpired("ps", 5)):
            with self.subTest(err=err), mock.patch.object(serve.subprocess, "run", side_effect=err):
                self.assertEqual(serve.proc_ages([100]), {})

    def test_clean_head_reads_git(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo, plain = Path(tmp.name) / "repo", Path(tmp.name) / "plain"
        repo.mkdir()
        plain.mkdir()
        git = lambda *args: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                                            *args], capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q")
        (repo / "a.txt").write_text("one\n")
        git("add", "a.txt")
        git("commit", "-q", "-m", "one")
        sha = git("rev-parse", "HEAD")
        self.assertEqual(len(sha), 40)
        self.assertEqual(serve.clean_head(str(repo)), sha)
        (repo / "new.txt").write_text("untracked\n")
        self.assertEqual(serve.clean_head(str(repo)), sha)
        (repo / "a.txt").write_text("two\n")
        self.assertIsNone(serve.clean_head(str(repo)))
        self.assertIsNone(serve.clean_head(str(plain)))


class SameTestsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(os.path.realpath(tmp.name))
        self.repo = base / "app"
        self.root = self.repo / "scrum"
        self.root.mkdir(parents=True)
        (self.root / "project.md").write_text(f"# Project profile\n- Test: {TEST}\n- E2E: {E2E}\n- Lint: none\n")
        self.wt = {k: self.repo / ".claude" / "worktrees" / f"scrum-{k}" for k in ("2001-a", "2002-b", "2003-c")}
        for wt in self.wt.values():
            wt.mkdir(parents=True)
        (self.root / "board.json").write_text(json.dumps(
            {"jobs": [{"id": k, "stage": "check", "worktree": str(wt)} for k, wt in self.wt.items()]}))
        (base / "projects.json").write_text(json.dumps([str(self.repo)]))
        self.base, self.waste = base, base / "waste.log"
        env = mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="1", SCRUM_PULSE=str(base / "pulse.log"),
                              SCRUM_REGISTRY=str(base / "projects.json"))
        env.start()
        self.addCleanup(env.stop)
        serve.SAME_TESTS_LOGGED.clear()
        self.addCleanup(serve.SAME_TESTS_LOGGED.clear)
        self.cwds, self.ages, self.heads = {}, {}, {}

    def run_pass(self, procs):
        with mock.patch.object(serve, "proc_cwds", side_effect=lambda pids: {p: str(c) for p, c in self.cwds.items()
                                                                             if p in pids}) as cwds, \
                mock.patch.object(serve, "proc_ages", side_effect=lambda pids: {p: a for p, a in self.ages.items()
                                                                                if p in pids}) as ages, \
                mock.patch.object(serve, "clean_head", side_effect=lambda cwd: self.heads.get(cwd, HEAD)), \
                mock.patch.object(serve.os, "kill") as kill:
            got = serve.stop_same_tests(procs)
        self.assertLessEqual(cwds.call_count, 1)
        self.assertLessEqual(ages.call_count, 1)
        self.assertTrue(all(c.args[1] == signal.SIGTERM for c in kill.call_args_list))
        return got, sorted(c.args[0] for c in kill.call_args_list)

    def lines(self):
        return [json.loads(l) for l in self.waste.read_text().splitlines()] if self.waste.exists() else []

    def assert_left_alone(self, procs):
        got, killed = self.run_pass(procs)
        self.assertEqual((got, killed), ([], []))
        self.assertEqual(self.lines(), [])

    def twin_pair(self, cmd=TEST):
        """cmd run in worktree 2001-a (20 min old) and in 2002-b (2 min old)."""
        self.cwds.update({101: self.wt["2001-a"], 201: self.wt["2002-b"]})
        self.ages.update({101: 20.0, 201: 2.0})
        return [*bash_run(100, cmd), *bash_run(200, cmd)]

    def test_twin_runs_newer_stopped_older_kept(self):
        procs = [(100, 1, 5.0, cl("2001-a")), *bash_run(100, TEST),
                 (200, 1, 5.0, cl("2002-b")), (201, 200, 0.1, f"/opt/homebrew/bin/python3 /x/buildlock.py {TEST}"),
                 (202, 201, 0.2, f"/bin/sh -c {TEST}"), (203, 202, 4.0, f"{PY} -m unittest discover -s tests -v")]
        self.cwds = {101: self.wt["2001-a"], 201: self.wt["2002-b"]}
        self.ages = {101: 20.0, 201: 2.0}
        got, killed = self.run_pass(procs)
        self.assertEqual(killed, [201, 202, 203])
        self.assertEqual(sorted(got), [201, 202, 203])
        (line,) = self.lines()
        self.assertEqual((line["kind"], line["project"], line["jobs"]), ("same-tests", "app", ["2002-b", "2001-a"]))
        self.assertEqual(sorted(line["pids"]), [201, 202, 203])
        self.assertEqual(line["cpu_min"], 4.3)
        self.assertEqual((line["kept"], line["head"], line["command"]), (101, HEAD, TEST))
        self.assertNotIn("rerun", line)

    def test_e2e_full_tick_run_kept_as_older(self):
        tick = f"{sys.executable} {Path(serve.buildlock.__file__).resolve()} {E2E}"  # e2e_full_run's Popen argv
        procs = [(300, os.getpid(), 0.5, tick), (301, 300, 0.1, f"/bin/sh -c {E2E}"),
                 (302, 301, 6.0, f"node /opt/homebrew/bin/{E2E}"),
                 (400, 1, 5.0, cl("2003-c")), *bash_run(400, E2E)]
        self.cwds = {300: self.repo, 401: self.wt["2003-c"]}
        self.ages = {300: 30.0, 401: 1.0}
        got, killed = self.run_pass(procs)
        self.assertEqual(killed, [401, 402, 403])
        (line,) = self.lines()
        self.assertEqual((line["jobs"], line["kept"], line["command"]), (["2003-c"], 300, E2E))

    def test_three_twins_keep_oldest(self):
        procs = [*bash_run(100, TEST), *bash_run(200, TEST), *bash_run(300, TEST)]
        self.cwds = {101: self.wt["2001-a"], 201: self.wt["2002-b"], 301: self.wt["2003-c"]}
        self.ages = {101: 5.0, 201: 30.0, 301: 10.0}
        got, killed = self.run_pass(procs)
        self.assertEqual(killed, [101, 102, 103, 301, 302, 303])
        self.assertEqual(sorted((l["jobs"], l["kept"]) for l in self.lines()),
                         [(["2001-a", "2002-b"], 201), (["2003-c", "2002-b"], 201)])
        serve.SAME_TESTS_LOGGED.clear()
        self.waste.unlink()
        self.ages = {101: 7.0, 201: 7.0, 301: 7.0}  # equal ages: the lower pid is kept
        got, killed = self.run_pass(procs)
        self.assertEqual(killed, [201, 202, 203, 301, 302, 303])
        self.assertEqual([l["kept"] for l in self.lines()], [101, 101])

    def test_wrapper_and_child_are_one_run(self):
        procs = [(100, 1, 5.0, cl("2001-a")), (101, 100, 0.1, zsh(f"python3 /x/buildlock.py {TEST}")),
                 (102, 101, 0.1, f"/opt/homebrew/bin/python3 /x/buildlock.py {TEST}"),
                 (103, 102, 0.1, f"/bin/sh -c {TEST}"), (104, 103, 3.0, f"{PY} -m unittest discover -s tests -v")]
        self.cwds = {p: self.wt["2001-a"] for p in (101, 102, 103)}
        self.ages = {101: 9.0, 102: 8.0, 103: 7.0}
        self.assert_left_alone(procs)

    def test_claude_line_never_a_run(self):
        quoting = f'/usr/local/bin/claude --permission-mode bypassPermissions -p "run {TEST}"'
        self.assertTrue(serve.suite_run(quoting, TEST))
        procs = [(100, 1, 5.0, quoting), *bash_run(100, TEST), (200, 1, 5.0, quoting), *bash_run(200, TEST)]
        self.cwds = {100: self.wt["2001-a"], 101: self.wt["2001-a"], 200: self.wt["2002-b"], 201: self.wt["2002-b"]}
        self.ages = {100: 20.0, 101: 20.0, 200: 2.0, 201: 2.0}
        got, killed = self.run_pass(procs)
        self.assertEqual(killed, [201, 202, 203])
        self.assertEqual([l["kept"] for l in self.lines()], [101])

    def test_dirty_checkout_not_a_twin(self):
        procs = self.twin_pair()
        for dirty in ("2002-b", "2001-a"):
            with self.subTest(dirty=dirty):
                self.heads = {str(self.wt[dirty]): None}
                self.assert_left_alone(procs)


if __name__ == "__main__":
    unittest.main()
