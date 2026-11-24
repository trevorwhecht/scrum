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
        self.cwds, self.ages, self.heads, self.rels = {}, {}, {}, {}

    def run_pass(self, procs):
        with mock.patch.object(serve, "proc_cwds", side_effect=lambda pids: {p: str(c) for p, c in self.cwds.items()
                                                                             if p in pids}) as cwds, \
                mock.patch.object(serve, "proc_ages", side_effect=lambda pids: {p: a for p, a in self.ages.items()
                                                                                if p in pids}) as ages, \
                mock.patch.object(serve, "clean_head", side_effect=lambda cwd: self.heads.get(cwd, HEAD)), \
                mock.patch.object(serve, "checkout_rel", side_effect=lambda cwd: self.rels.get(cwd, "")), \
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

    def test_via_is_nearest_shared_claude(self):
        """Claude chain 10 > 20 > 30; the kept run sits under 30, the stopped one under 40 (a claude below 30)."""
        self.cwds.update({101: self.wt["2001-a"], 201: self.wt["2002-b"]})
        self.ages.update({101: 20.0, 201: 2.0})
        procs = [(10, 1, 1.0, cl("2001-a")), (20, 10, 1.0, cl("2001-a")),
                 (30, 20, 1.0, "/usr/local/bin/claude -p /trevskills-scrum build 2001-a --agent scrum-builder"),
                 (40, 30, 1.0, cl("2002-b")), (100, 30, 0.1, "/bin/zsh -c y"),
                 (101, 100, 0.1, zsh(TEST)), (102, 101, 3.0, f"{PY}{TEST[7:]}"),
                 (200, 40, 0.1, "/bin/zsh -c z"), (201, 200, 0.1, zsh(TEST)), (202, 201, 3.0, f"{PY}{TEST[7:]}")]
        self.run_pass(procs)
        (line,) = self.lines()
        self.assertEqual(line["via"], {"pid": 30, "job": "2001-a", "agent": "scrum-builder"})
        self.assertEqual(line["ages"], {"kept": 20.0, "stopped": 2.0})

    def test_ages_and_via_on_twin_pair(self):
        procs = [(100, 1, 5.0, cl("2001-a")), *bash_run(100, TEST), (200, 100, 5.0, cl("2002-b")), *bash_run(200, TEST)]
        self.cwds.update({101: self.wt["2001-a"], 201: self.wt["2002-b"]})
        self.ages.update({101: 20.0, 201: 2.0})
        self.run_pass(procs)
        (line,) = self.lines()
        self.assertEqual(line["ages"], {"kept": 20.0, "stopped": 2.0})
        self.assertEqual(line["via"], {"pid": 100, "job": "2001-a", "agent": "build"})

    def test_no_shared_claude_via_none_still_stopped(self):
        procs = self.twin_pair()
        got, killed = self.run_pass(procs)
        self.assertEqual(killed, [201, 202, 203])
        (line,) = self.lines()
        self.assertIsNone(line["via"])
        self.assertEqual(line["ages"], {"kept": 20.0, "stopped": 2.0})

    def test_claude_step(self):
        self.assertEqual(serve.claude_step("/usr/local/bin/claude -p /trevskills-scrum build 1336-x --permission-mode b"),
                         ("1336-x", "build"))
        self.assertEqual(serve.claude_step('claude -p "/trevskills-scrum review 77-y" --agent=scrum-ux'),
                         ("77-y", "scrum-ux"))
        self.assertEqual(serve.claude_step("claude --agent scrum-builder"), (None, "scrum-builder"))
        self.assertEqual(serve.claude_step("claude -p hello"), (None, None))

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
        for dirty in (["2002-b"], ["2001-a"], ["2001-a", "2002-b"]):
            with self.subTest(dirty=dirty):
                self.heads = {str(self.wt[k]): None for k in dirty}
                self.assert_left_alone(procs)

    def test_different_subdirectories_not_twins(self):
        procs = self.twin_pair()
        self.rels = {str(self.wt["2002-b"]): "web"}
        self.assert_left_alone(procs)
        self.rels = {str(self.wt["2002-b"]): "web", str(self.wt["2001-a"]): "web"}
        got, killed = self.run_pass(procs)
        self.assertIn(201, killed)
        self.assertNotIn(101, killed)

    def test_checkout_rel_reads_git(self):
        with tempfile.TemporaryDirectory() as t:
            sub = Path(os.path.realpath(t)) / "web" / "x"
            sub.mkdir(parents=True)
            self.assertEqual(serve.checkout_rel(str(sub)), "")  # not a git checkout
            subprocess.run(["git", "init", "-q", t], check=True)
            self.assertEqual(serve.checkout_rel(str(sub)), "web/x")
            self.assertEqual(serve.checkout_rel(t), "")

    def test_two_commits_left_alone(self):
        procs = self.twin_pair()
        self.heads = {str(self.wt["2002-b"]): "beef002"}
        self.assert_left_alone(procs)

    def test_focused_run_beside_full_left_alone(self):
        procs = [*bash_run(100, TEST), *bash_run(200, f"{TEST} -k cmd_ready"),
                 *bash_run(300, E2E), *bash_run(400, f"{E2E} e2e/cart.spec.ts")]
        self.cwds = {101: self.wt["2001-a"], 201: self.wt["2002-b"], 301: self.wt["2003-c"], 401: self.repo}
        self.ages = {101: 20.0, 201: 2.0, 301: 20.0, 401: 2.0}
        self.assert_left_alone(procs)

    def record(self, rec):
        path = self.root / "e2e-full.json"
        path.unlink(missing_ok=True)
        if rec is not None:
            path.write_text(rec if isinstance(rec, str) else json.dumps(rec))

    def rerun_procs(self):
        """A full E2E run in worktree 2003-c and a full Test run in 2001-a, each alone."""
        self.cwds.update({401: self.wt["2003-c"], 101: self.wt["2001-a"]})
        self.ages.update({401: 3.0, 101: 3.0})
        return [(400, 1, 5.0, cl("2003-c")), *bash_run(400, E2E, cpu=6.0), *bash_run(100, TEST)]

    def test_rerun_on_fresh_head_logged_once(self):
        procs = self.rerun_procs()
        for result in ("pass", "fail"):
            with self.subTest(result=result):
                serve.SAME_TESTS_LOGGED.clear()
                self.waste.unlink(missing_ok=True)
                self.record({"at": 1, "head": HEAD, "result": result, "exit": 0, "failed": [], "lastGreen": None})
                self.assertEqual(self.run_pass(procs), ([], []))
                self.assertEqual(self.run_pass(procs), ([], []))
                (line,) = self.lines()
                line.pop("t")
                self.assertEqual(line, {"kind": "same-tests", "project": "app", "jobs": ["2003-c"], "pids": [],
                                        "cpu_min": 6.1, "rerun": True, "head": HEAD, "command": E2E,
                                        "via": {"pid": 400, "job": "2003-c", "agent": "build"},
                                        "cwd": str(self.wt["2003-c"])})

    def test_rerun_via_is_nearest_claude_ancestor(self):
        """Job 1517: claude 10 > claude 30 (--agent scrum-builder) > the E2E run; via names 30, the nearest."""
        self.record({"at": 1, "head": HEAD, "result": "fail", "exit": 1, "failed": [], "lastGreen": None})
        self.cwds.update({401: self.wt["2003-c"]})
        procs = [(10, 1, 1.0, cl("2001-a")),
                 (30, 10, 1.0, "/usr/local/bin/claude -p /trevskills-scrum build 2003-c --agent scrum-builder"),
                 (400, 30, 0.1, "/bin/zsh -c y"), (401, 400, 0.1, zsh(E2E)), (402, 401, 6.0, f"node /opt/homebrew/bin/{E2E}")]
        self.run_pass(procs)
        (line,) = self.lines()
        self.assertEqual(line["via"], {"pid": 30, "job": "2003-c", "agent": "scrum-builder"})
        self.assertEqual(line["cwd"], str(self.wt["2003-c"]))

    def test_rerun_with_no_claude_above_has_via_none(self):
        self.record({"at": 1, "head": HEAD, "result": "pass", "exit": 0, "failed": [], "lastGreen": HEAD})
        self.cwds.update({401: self.wt["2003-c"]})
        self.run_pass(bash_run(400, E2E))
        (line,) = self.lines()
        self.assertIsNone(line["via"])
        self.assertEqual((line["rerun"], line["cwd"]), (True, str(self.wt["2003-c"])))

    def test_e2e_full_worktree_rerun_not_logged(self):
        """Job 1517: e2e_full_run and its e2e_full_rerun one-worker re-run run in .claude/worktrees/e2e-full after the
        head's record is stored; that is serve.py's own run, never a waste line. A run in another worktree still is."""
        e2e_wt = self.repo / ".claude" / "worktrees" / "e2e-full"
        e2e_wt.mkdir(parents=True)
        self.record({"at": 1, "head": HEAD, "result": "fail", "exit": 1, "failed": [], "lastGreen": None})
        procs = [(300, os.getpid(), 0.5, f"{sys.executable} {Path(serve.buildlock.__file__).resolve()} {E2E}"),
                 (301, 300, 0.1, f"/bin/sh -c {E2E}"), (302, 301, 6.0, f"node /opt/homebrew/bin/{E2E}")]
        self.cwds = {300: e2e_wt}
        self.assert_left_alone(procs)
        procs += [(400, 1, 5.0, cl("2003-c")), *bash_run(400, E2E)]
        self.cwds[401] = self.wt["2003-c"]
        self.run_pass(procs)
        self.assertEqual([(l["jobs"], l["cwd"]) for l in self.lines()], [(["2003-c"], str(self.wt["2003-c"]))])

    def test_no_fresh_result_not_a_rerun(self):
        procs = self.rerun_procs()
        for state, rec in (("running", {"head": HEAD, "result": "running"}),
                           ("loaded", {"head": HEAD, "result": "loaded"}),
                           ("error", {"head": HEAD, "result": "error"}),
                           ("other head", {"head": "beef002", "result": "pass"}),
                           ("missing", None), ("unreadable", "{not json")):
            with self.subTest(state=state):
                self.record(rec)
                self.assert_left_alone(procs)

    def test_survivor_logged_once(self):
        self.record({"at": 1, "head": HEAD, "result": "pass", "exit": 0, "failed": [], "lastGreen": HEAD})
        procs = self.twin_pair(E2E)
        for _ in range(2):  # the newer run survived SIGTERM: stopped again, never logged again
            got, killed = self.run_pass(procs)
            self.assertEqual(killed, [201, 202, 203])
            self.assertEqual(sorted(got), [201, 202, 203])
        stops = [l for l in self.lines() if not l.get("rerun")]
        reruns = [l for l in self.lines() if l.get("rerun")]
        self.assertEqual([(l["jobs"], l["kept"]) for l in stops], [(["2002-b", "2001-a"], 101)])
        self.assertEqual([(l["jobs"], l["pids"]) for l in reruns], [(["2001-a"], [])])  # the kept run only

    def test_off_when_idle_cleanup_disabled(self):
        procs = self.twin_pair()
        with mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="0"), \
                mock.patch.object(serve, "process_scan") as scan, mock.patch.object(serve.os, "kill") as kill:
            self.assertEqual(serve.stop_same_tests(), [])
            self.assertEqual(serve.stop_same_tests(procs), [])
        scan.assert_not_called()
        kill.assert_not_called()
        self.assertEqual(self.lines(), [])

    def test_no_commands_no_scan(self):
        repo2 = self.base / "two"
        (repo2 / "scrum").mkdir(parents=True)
        (repo2 / "scrum" / "project.md").write_text(f"- Test: {TEST}\n")
        (self.base / "projects.json").write_text(json.dumps([str(self.repo), str(repo2)]))
        real = serve.e2e_command

        def unreadable(root, label="E2E"):
            if root == repo2 / "scrum":
                raise PermissionError("project.md")
            return real(root, label)

        for text, scans in (("- Test: none\n- E2E:\n- Lint: none\n", 0), ("- Test: NONE\n- E2E: None\n", 0),
                            (f"- Test: {TEST}\n- E2E: none\n", 1)):
            with self.subTest(text=text):
                (self.root / "project.md").write_text(text)
                with mock.patch.object(serve, "e2e_command", side_effect=unreadable), \
                        mock.patch.object(serve, "process_scan", return_value=[]) as scan:
                    self.assertEqual(serve.stop_same_tests(), [])
                self.assertEqual(scan.call_count, scans)

    def test_ps_lsof_or_age_failure_stops_nothing(self):
        procs = self.twin_pair()
        with mock.patch.object(serve, "process_scan", return_value=[]) as scan:
            self.assert_left_alone(None)  # ps failed
        scan.assert_called_once_with()
        cwds, ages = dict(self.cwds), dict(self.ages)
        for case in ("lsof failed", "ps etime failed", "a twin's age missing", "no clean head"):
            with self.subTest(case=case):
                self.cwds, self.ages, self.heads = dict(cwds), dict(ages), {}
                if case == "lsof failed":
                    self.cwds = {}
                elif case == "ps etime failed":
                    self.ages = {}
                elif case == "a twin's age missing":
                    del self.ages[201]
                else:
                    self.heads = {str(self.wt["2001-a"]): None, str(self.wt["2002-b"]): None}
                self.assert_left_alone(procs)
        self.cwds, self.ages, self.heads = cwds, ages, {}
        self.assertEqual(self.run_pass(procs)[1], [201, 202, 203])  # the same fixture with nothing failing stops one

    def test_test_and_e2e_not_twins(self):
        procs = [*bash_run(100, TEST), *bash_run(200, E2E)]
        self.cwds = {101: self.wt["2001-a"], 201: self.wt["2002-b"]}
        self.ages = {101: 20.0, 201: 2.0}
        self.assert_left_alone(procs)

    def test_watchdog_failure_is_contained(self):
        s = serve
        with mock.patch.object(s.board, "projects", return_value={}), \
                mock.patch.object(s, "stop_leftovers"), mock.patch.object(s, "stop_two_sessions") as two, \
                mock.patch.object(s, "stop_same_tests", side_effect=RuntimeError("boom")) as same, \
                mock.patch.object(s, "window_tick") as window, mock.patch.object(s, "idle_cleanup"), \
                mock.patch.object(s, "auto_continue_tick"), mock.patch.object(s.board, "record_cpu_sample"), \
                mock.patch.object(s, "weekly_tick"), mock.patch.object(s, "pulse_tick"), \
                mock.patch.object(s, "cooldown_chime"), mock.patch("sys.stderr", new=io.StringIO()) as err:
            s.watchdog_tick()
        two.assert_called_once_with()
        same.assert_called_once_with()
        window.assert_called_once()
        self.assertIn("watchdog: same tests: boom", err.getvalue())


def e2e_out(*specs):
    """Playwright output whose `N failed` block lists each (file, line, title) of specs."""
    lines = "".join(f"    [chromium] › {f}:{n}:1 › {t} ──────\n" for f, n, t in specs)
    return f"Running tests using 1 worker\n\n  {len(specs)} failed\n{lines}  2 passed (9s)\n"


class E2eFullFilingTest(unittest.TestCase):
    """Job 1283: e2e_full_run files only specs no live job owns that fail again on a one-worker re-run, and one
    combined item when 3 or more fail. e2e_full_exec is mocked: call 1 is the full run, call 2 the re-run."""
    A, B, C = ("a.spec.ts", 3, "A one"), ("b.spec.ts", 5, "B two"), ("c.spec.ts", 7, "C three")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(os.path.realpath(tmp.name)) / "app"
        self.root = self.repo / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        (self.repo / "e2e").mkdir()
        (self.root / "board.json").write_text('{"jobs": []}')
        (self.root / "backlog.md").write_text("# Backlog\n")
        for name, val in (("listeners", []),):
            p = mock.patch.object(board, name, return_value=val)
            p.start()
            self.addCleanup(p.stop)
        env = mock.patch.dict(os.environ, HOME=str(Path(tmp.name) / "home"))
        env.start()
        self.addCleanup(env.stop)
        self.cmds = []

    def jobs(self, *jobs):
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": i, "title": t, "stage": st} for i, t, st, _ in jobs]}))
        for i, _, _, feature in jobs:
            if feature is not None:
                (self.root / "jobs" / i).mkdir(parents=True, exist_ok=True)
                (self.root / "jobs" / i / "feature.md").write_text(feature)

    def run_full(self, full, rerun, cmd="npm run test:e2e", rerun_code=1):
        """e2e_full_run where the full run prints full and the re-run prints rerun."""
        outs = [(full, 1), (rerun, rerun_code)]

        def fake(repo, command, env, log, loads):
            self.cmds.append(command)
            out, code = outs[len(self.cmds) - 1]
            Path(log).write_text(out)
            return code

        with mock.patch.object(serve, "e2e_full_exec", side_effect=fake), \
                mock.patch.object(serve, "e2e_full_worktree", return_value=self.repo):  # exec is mocked: no git
            return serve.e2e_full_run(self.repo, self.root, cmd, "h" * 40, 1.0, None)

    def items(self):
        return [i["text"] for i in board.read_backlog(self.root)[1] if not i["done"]]

    def test_spec_owned_by_live_job_not_filed(self):
        self.jobs(("1", "Fix the a spec", "build", "Make e2e/a.spec.ts pass"),
                  ("2", "Old", "done", "e2e/b.spec.ts was broken"))
        self.run_full(e2e_out(self.A, self.B), e2e_out(self.B))
        items = self.items()
        self.assertEqual(len(items), 1, items)
        self.assertIn("e2e/b.spec.ts", items[0])
        self.assertEqual(self.cmds[1], "npm run test:e2e -- --workers=1 e2e/b.spec.ts")

    def test_spec_in_live_job_title_not_filed(self):
        self.jobs(("1", "Fix e2e/a.spec.ts", "check", None))
        self.run_full(e2e_out(self.A), "")
        self.assertEqual(self.items(), [])
        self.assertEqual(len(self.cmds), 1, "nothing left to re-run")

    def test_passing_on_rerun_is_flaky_not_filed(self):
        rec = self.run_full(e2e_out(self.A, self.B), e2e_out(self.B))
        self.assertEqual(rec["flaky"], ["e2e/a.spec.ts"])
        self.assertEqual(json.loads((self.root / "e2e-full.json").read_text())["flaky"], ["e2e/a.spec.ts"])
        (item,) = self.items()
        self.assertIn("e2e/b.spec.ts — b.spec.ts:5 B two", item)
        self.assertNotIn("a.spec.ts", item)
        self.assertEqual(self.cmds[1], "npm run test:e2e -- --workers=1 e2e/a.spec.ts e2e/b.spec.ts")

    def test_rerun_command_without_npm_script(self):
        self.run_full(e2e_out(self.A), "", cmd="npx playwright test", rerun_code=0)
        self.assertEqual(self.cmds[1], "npx playwright test --workers=1 e2e/a.spec.ts")
        self.assertEqual(self.items(), [])

    def test_failing_again_filed_as_one_item(self):
        self.run_full(e2e_out(self.A), e2e_out(self.A))
        (item,) = self.items()
        self.assertTrue(item.startswith("E2E full suite on main fails: e2e/a.spec.ts — a.spec.ts:3 A one"), item)

    def test_three_failures_give_one_combined_item(self):
        both = e2e_out(self.A, self.B, self.C)
        self.run_full(both, both)
        (item,) = self.items()
        self.assertTrue(item.startswith("E2E full suite on main fails in 3 specs: e2e/a.spec.ts — a.spec.ts:3 A one; "
                                        "e2e/b.spec.ts — b.spec.ts:5 B two; e2e/c.spec.ts — c.spec.ts:7 C three; "), item)

    def test_two_failures_stay_per_spec(self):
        both = e2e_out(self.A, self.B)
        self.run_full(both, both)
        self.assertEqual(len(self.items()), 2)

    def test_loaded_rerun_files_nothing(self):
        def fake(repo, command, env, log, loads):
            self.cmds.append(command)
            Path(log).write_text(e2e_out(self.A))
            if len(self.cmds) == 2:
                loads.append(board.MAX_CPU_LOAD_PCT + 50)
            return 1

        with mock.patch.object(serve, "e2e_full_exec", side_effect=fake), \
                mock.patch.object(serve, "e2e_full_worktree", return_value=self.repo):  # exec is mocked: no git
            serve.e2e_full_run(self.repo, self.root, "npm run test:e2e", "h" * 40, 1.0, None)
        self.assertEqual(self.items(), [])


if __name__ == "__main__":
    unittest.main()
