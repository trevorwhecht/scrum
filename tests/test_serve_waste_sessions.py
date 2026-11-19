"""Job 1177 (BigBoy 1165, waste kind `two-sessions`): serve.py stop_two_sessions finds two live claude sessions
working one job in one project, keeps the one the recorded pid, the RUNS table or the parent's chain-lock holder points
to, stops the rest (stop_tree) with one waste line, and parks the job with one ask when the owner is unclear."""
import io, json, os, signal, tempfile, unittest
from pathlib import Path
from unittest import mock

import test_serve  # noqa: F401  its import-time env pins (SCRUM_IDLE_CLEANUP=0, SCRUM_PS, ...) apply first
import serve

board = serve.board


def cl(cmd, job_id):
    return f"/usr/local/bin/claude -p /trevskills-scrum {cmd} {job_id} --permission-mode bypassPermissions"


class TwoSessionsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(os.path.realpath(tmp.name))
        self.repo, self.repo2 = base / "app", base / "two"
        self.root, self.root2 = self.repo / "scrum", self.repo2 / "scrum"
        for root in (self.root, self.root2):
            (root / "jobs").mkdir(parents=True)
        self.wt = self.repo / ".claude" / "worktrees" / "scrum-1447-kid"
        self.wt.mkdir(parents=True)
        (base / "projects.json").write_text(json.dumps([str(self.repo), str(self.repo2)]))
        self.waste = base / "waste.log"
        env = mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="1", SCRUM_PULSE=str(base / "pulse.log"),
                              SCRUM_REGISTRY=str(base / "projects.json"))
        env.start()
        self.addCleanup(env.stop)
        for held in (serve.TWO_SESSIONS_LOGGED, serve.TWO_SESSIONS_ASKED):
            held.clear()
            self.addCleanup(held.clear)
        runs = mock.patch.dict(serve.RUNS, clear=True)
        runs.start()
        self.addCleanup(runs.stop)
        self.jobs = [{"id": "1091-parent", "stage": "bigboy", "children": ["1447-kid"]},
                     {"id": "1447-kid", "stage": "build", "parent": "1091-parent", "children": []},
                     {"id": "1500-plain", "stage": "build", "children": []}]
        self.write_board()
        (self.root2 / "board.json").write_text(json.dumps({"jobs": [{"id": "1500-plain", "stage": "build"}]}))
        self.cwds = {}

    def write_board(self):
        (self.root / "board.json").write_text(json.dumps({"jobs": self.jobs}))

    def edit(self, job_id, **fields):
        for j in self.jobs:
            if j["id"] == job_id:
                j.update(fields)
        self.write_board()

    def lock(self, holder):
        (self.root / "jobs" / "1091-parent").mkdir(exist_ok=True)
        (self.root / "jobs" / "1091-parent" / ".chain.lock").write_text(json.dumps({"holder": holder, "at": "x"}))

    def run_pass(self, procs):
        with mock.patch.object(serve, "proc_cwds", side_effect=lambda pids: {p: c for p, c in self.cwds.items()
                                                                             if p in pids}) as cwds, \
                mock.patch.object(serve.os, "kill") as kill, \
                mock.patch.object(board, "cmd_ask") as ask, \
                mock.patch.object(board, "stop_worktree_servers") as servers:
            got = serve.stop_two_sessions(procs)
        servers.assert_not_called()
        self.assertLessEqual(cwds.call_count, 1)
        return got, kill, ask

    def lines(self):
        return [json.loads(l) for l in self.waste.read_text().splitlines()] if self.waste.exists() else []

    def killed(self, kill):
        return sorted(c.args[0] for c in kill.call_args_list)

    def assert_left_alone(self, procs):
        got, kill, ask = self.run_pass(procs)
        self.assertEqual(got, [])
        kill.assert_not_called()
        ask.assert_not_called()
        self.assertEqual(self.lines(), [])

    def plain_pair(self):
        self.cwds = {300: str(self.repo), 400: str(self.repo / "sub")}
        return [(299, 1, 0.0, "/bin/sh -c serve-run"), (300, 299, 1.5, cl("build", "1500-plain")),
                (301, 300, 0.5, "node /usr/local/lib/claude-code/cli.js"),
                (400, 1, 2.0, cl("resume", "1500-plain")), (401, 400, 3.0, "python3 -m unittest discover -s tests")]

    def test_off_when_idle_cleanup_disabled(self):
        with mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="0"), \
                mock.patch.object(serve, "process_scan") as scan, mock.patch.object(serve.os, "kill") as kill, \
                mock.patch.object(board, "cmd_ask") as ask:
            self.assertEqual(serve.stop_two_sessions(), [])
            self.assertEqual(serve.stop_two_sessions(self.plain_pair()), [])
        scan.assert_not_called()
        kill.assert_not_called()
        ask.assert_not_called()
        self.assertEqual(self.lines(), [])

    def test_same_id_two_projects_not_a_catch(self):
        self.cwds = {300: str(self.repo), 400: str(self.repo2)}
        self.assert_left_alone([(300, 1, 1.0, cl("build", "1500-plain")), (400, 1, 1.0, cl("build", "1500-plain"))])

    def test_wrapper_and_claude_line_are_one_session(self):
        procs = [(300, 1, 0.0, "nohup claude -p /trevskills-scrum build 1500-plain"),
                 (301, 300, 0.0, "/bin/sh -c claude -p /trevskills-scrum build 1500-plain"),
                 (302, 301, 1.0, cl("build", "1500-plain"))]
        self.cwds = {300: str(self.repo), 301: str(self.repo), 302: str(self.repo)}
        self.assert_left_alone(procs)
        self.cwds[400] = str(self.repo)
        got, kill, ask = self.run_pass(procs + [(400, 1, 1.0, cl("build", "1500-plain"))])
        kill.assert_not_called()
        question = ask.call_args.args[2]
        self.assertIn("process 300 and process 400", question)
        self.assertNotIn("301", question)
        self.assertNotIn("302", question)

    def test_bigboy_parent_review_held_by_child(self):
        self.lock("1447-kid")
        self.cwds = {100: str(self.wt), 200: str(self.repo)}
        procs = [(100, 1, 1.0, cl("bigboy", "1447-kid")), (101, 100, 2.0, "python3 -m unittest discover -s tests"),
                 (200, 1, 3.0, cl("bigboy", "1091-parent")), (201, 200, 4.0, "python3 -m unittest discover -s tests")]
        got, kill, ask = self.run_pass(procs)
        self.assertEqual(sorted(c.args for c in kill.call_args_list), [(200, signal.SIGTERM), (201, signal.SIGTERM)])
        self.assertNotIn(100, self.killed(kill))
        self.assertNotIn(101, self.killed(kill))
        self.assertEqual(sorted(got), [200, 201])
        ask.assert_not_called()
        (line,) = self.lines()
        self.assertEqual(line["kind"], "two-sessions")
        self.assertEqual(line["project"], "app")
        self.assertEqual(line["jobs"], ["1091-parent", "1447-kid"])
        self.assertEqual(sorted(line["pids"]), [200, 201])
        self.assertEqual(line["cpu_min"], 7.0)
        self.assertEqual(line["owner"], 100)

    def test_bigboy_lock_without_holder_session_does_nothing(self):
        self.lock("1447-kid")
        self.cwds = {200: str(self.repo)}
        self.assert_left_alone([(200, 1, 3.0, cl("bigboy", "1091-parent"))])
        self.lock("9999-stranger")
        self.cwds = {100: str(self.wt), 200: str(self.repo)}
        self.assert_left_alone([(100, 1, 1.0, cl("bigboy", "9999-stranger")), (200, 1, 3.0, cl("bigboy", "1091-parent"))])

    def test_plain_job_recorded_pid_keeps_owner(self):
        self.edit("1500-plain", pid="301")  # a descendant of session 300
        got, kill, ask = self.run_pass(self.plain_pair())
        self.assertEqual(self.killed(kill), [400, 401])
        self.assertEqual(sorted(got), [400, 401])
        ask.assert_not_called()
        (line,) = self.lines()
        self.assertEqual((line["kind"], line["project"], line["jobs"]), ("two-sessions", "app", ["1500-plain"]))
        self.assertEqual(sorted(line["pids"]), [400, 401])
        self.assertEqual(line["cpu_min"], 5.0)
        self.assertEqual(line["owner"], 300)

    def test_plain_job_tracked_run_keeps_owner(self):
        serve.RUNS["app/1500-plain"] = {"proc": mock.Mock(pid=299, poll=mock.Mock(return_value=None))}
        got, kill, ask = self.run_pass(self.plain_pair())
        self.assertEqual(self.killed(kill), [400, 401])
        ask.assert_not_called()
        (line,) = self.lines()
        self.assertEqual(line["owner"], 300)
        self.assertEqual(sorted(line["pids"]), [400, 401])

    def test_unclear_owner_asks_once(self):
        procs = self.plain_pair()
        got, kill, ask = self.run_pass(procs)
        got2, kill2, ask2 = self.run_pass(procs)
        self.assertEqual((got, got2), ([], []))
        kill.assert_not_called()
        kill2.assert_not_called()
        ask2.assert_not_called()
        ask.assert_called_once()
        root, job_id, question, options = ask.call_args.args
        self.assertEqual((root, job_id), (self.root, "1500-plain"))
        self.assertIn("process 300", question)
        self.assertIn("process 400", question)
        self.assertEqual(options, ["Stop both and carry on=shell: kill 300 400",
                                   "Put back on the backlog=abort 1500-plain --requeue"])
        self.assertEqual(ask.call_args.kwargs["title"], "TWO_SESSIONS")
        self.assertEqual(ask.call_args.kwargs["recommend"][0], "a")
        self.assertEqual(self.lines(), [])

    def test_two_picks_is_unclear(self):
        self.edit("1500-plain", pid="300")
        serve.RUNS["app/1500-plain"] = {"proc": mock.Mock(pid=400, poll=mock.Mock(return_value=None))}
        got, kill, ask = self.run_pass(self.plain_pair())
        self.assertEqual(got, [])
        kill.assert_not_called()
        ask.assert_called_once()
        self.assertEqual(self.lines(), [])

    def test_single_session_does_nothing(self):
        self.cwds = {300: str(self.repo)}
        self.assert_left_alone([(300, 1, 1.0, cl("build", "1500-plain")), (301, 300, 1.0, "python3 -m unittest")])

    def test_finished_or_parked_job_skipped(self):
        for stage in ("done", "aborted", "needs-human"):
            with self.subTest(stage=stage):
                self.edit("1500-plain", stage=stage)
                self.assert_left_alone(self.plain_pair())
        self.edit("1500-plain", stage="build", id="1600-other")
        self.assert_left_alone(self.plain_pair())  # 1500-plain is no longer on the board

    def test_outside_projects_ignored(self):
        procs = self.plain_pair()
        self.cwds = {300: str(self.repo), 400: str(self.repo) + "-copy"}
        self.assert_left_alone(procs)
        self.cwds = {300: str(self.repo)}
        self.assert_left_alone(procs)

    def test_survivor_logged_once(self):
        self.edit("1500-plain", pid="300")
        procs = self.plain_pair()
        self.run_pass(procs)
        got, kill, ask = self.run_pass(procs)
        self.assertEqual(self.killed(kill), [400, 401])
        self.assertEqual(sorted(got), [400, 401])
        self.assertEqual(len(self.lines()), 1)

    def test_watchdog_failure_is_contained(self):
        s = serve
        with mock.patch.object(s.board, "projects", return_value={}), \
                mock.patch.object(s, "stop_leftovers") as leftovers, \
                mock.patch.object(s, "stop_two_sessions", side_effect=RuntimeError("boom")) as two, \
                mock.patch.object(s, "window_tick") as window, mock.patch.object(s, "idle_cleanup"), \
                mock.patch.object(s, "auto_continue_tick"), mock.patch.object(s.board, "record_cpu_sample"), \
                mock.patch.object(s, "weekly_tick"), mock.patch.object(s, "pulse_tick"), \
                mock.patch.object(s, "cooldown_chime"), mock.patch("sys.stderr", new=io.StringIO()) as err:
            s.watchdog_tick()
        leftovers.assert_called_once_with()
        two.assert_called_once_with()
        window.assert_called_once()
        self.assertIn("watchdog: two sessions: boom", err.getvalue())


if __name__ == "__main__":
    unittest.main()
