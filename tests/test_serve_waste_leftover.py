"""Job 1176 (BigBoy 1165 T2): serve.py process_scan (ps with CPU time), stop_tree (SIGTERM a process tree, never
serve.py or its ancestors) and stop_leftovers (a claude session still running tests, a server or a build 10+ min
after its job and its whole hand-off family finished: stopped and logged as waste kind `leftover`)."""
import io, json, os, signal, subprocess, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import test_serve  # noqa: F401  its import-time env pins (SCRUM_IDLE_CLEANUP=0, SCRUM_PS, ...) apply first
import serve

board = serve.board
SERVE = os.getpid()


def ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


class ProcessScanTest(unittest.TestCase):
    def test_parses_cpu_time_forms(self):
        out = ("  100     1 44:07.23 /usr/local/bin/claude -p /trevskills-scrum build 002-kid\n"
               "  101   100 0:03.00 /bin/zsh -c python3 -m unittest\n"
               "  102   101 1:02:30 node next dev\n"
               "  103   101 2-03:04:30 tsc --watch\n"
               "  104   101 garbage vite\n"
               "  105     1 0:00.00\n"
               "bad line\n")
        with mock.patch.object(serve.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=out)) as run:
            got = serve.process_scan()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["ps", "-axo", "pid=,ppid=,time=,command="])
        self.assertEqual(run.call_args.kwargs.get("timeout"), 5)
        self.assertEqual(got, [(100, 1, 44.12, "/usr/local/bin/claude -p /trevskills-scrum build 002-kid"),
                               (101, 100, 0.05, "/bin/zsh -c python3 -m unittest"),
                               (102, 101, 62.5, "node next dev"),
                               (103, 101, 3064.5, "tsc --watch"),
                               (104, 101, 0.0, "vite"),
                               (105, 1, 0.0, "")])

    def test_ps_failure_gives_empty(self):
        for result in (OSError("no ps"), subprocess.TimeoutExpired("ps", 5),
                       mock.Mock(returncode=1, stdout="  100 1 0:01.00 claude\n")):
            with self.subTest(result=result):
                kw = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
                with mock.patch.object(serve.subprocess, "run", **kw):
                    self.assertEqual(serve.process_scan(), [])


class StopTreeTest(unittest.TestCase):
    PROCS = [(100, 1, 1.0, "claude"), (101, 100, 0.5, "zsh"), (102, 101, 3.2, "python3 -m unittest"),
             (103, 102, 0.25, "python3 worker"), (104, 100, 0.1, "node"), (200, 1, 9.0, "other")]

    def test_signals_whole_tree_and_sums_cpu(self):
        with mock.patch.object(serve.os, "kill") as kill:
            pids, cpu = serve.stop_tree(100, self.PROCS)
        self.assertEqual(sorted(pids), [100, 101, 102, 103, 104])
        self.assertEqual(sorted(c.args for c in kill.call_args_list),
                         [(100, signal.SIGTERM), (101, signal.SIGTERM), (102, signal.SIGTERM),
                          (103, signal.SIGTERM), (104, signal.SIGTERM)])
        self.assertEqual(cpu, 5.0)
        with mock.patch.object(serve.os, "kill") as kill:
            self.assertEqual(serve.stop_tree(999, self.PROCS), ([999], 0.0))
        self.assertEqual([c.args for c in kill.call_args_list], [(999, signal.SIGTERM)])

    def test_never_signals_self_or_ancestors(self):
        procs = [(50, 1, 0.0, "launchd child"), (60, 50, 0.0, "python3 serve.py"),  # serve's ancestors
                 (SERVE, 60, 0.0, "serve"), (100, SERVE, 1.0, "claude"), (101, 100, 2.0, "zsh")]
        with mock.patch.object(serve.os, "kill") as kill:
            self.assertEqual(serve.stop_tree(50, procs), ([], 0.0))
            kill.assert_not_called()
            pids, cpu = serve.stop_tree(100, procs)
        self.assertEqual(sorted(pids), [100, 101])
        self.assertEqual(cpu, 3.0)
        with mock.patch.object(serve.os, "kill") as kill:
            serve.stop_tree(os.getppid(), [(os.getppid(), 1, 0.0, "shell")])
            kill.assert_not_called()

    def test_vanished_pid_left_out(self):
        def kill(pid, sig):
            if pid == 101:
                raise ProcessLookupError
            if pid == 102:
                raise PermissionError
        with mock.patch.object(serve.os, "kill", side_effect=kill):
            pids, cpu = serve.stop_tree(100, self.PROCS)
        self.assertEqual(sorted(pids), [100, 103, 104])
        self.assertEqual(cpu, 1.4)


class LeftoverTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(os.path.realpath(tmp.name))
        self.repo = base / "app"
        self.root = self.repo / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        self.wt = self.repo / ".claude" / "worktrees" / "scrum-002-kid"
        self.wt.mkdir(parents=True)
        (base / "projects.json").write_text(json.dumps([str(self.repo)]))
        self.waste = base / "waste.log"
        env = mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="1", SCRUM_PULSE=str(base / "pulse.log"),
                              SCRUM_REGISTRY=str(base / "projects.json"))
        env.start()
        self.addCleanup(env.stop)
        serve.LEFTOVER_LOGGED.clear()
        self.addCleanup(serve.LEFTOVER_LOGGED.clear)
        self.board([("001-par", "done", 30, None, ["002-kid", "003-sib"]), ("002-kid", "done", 30, "001-par", []),
                    ("003-sib", "aborted", 30, "001-par", [])])
        self.cwds = {100: str(self.wt)}
        self.procs = [(100, 1, 1.0, "/usr/local/bin/claude -p /trevskills-scrum build 002-kid --permission-mode x"),
                      (101, 100, 0.5, "/bin/zsh -c cd x && python3 -m unittest discover -s tests"),
                      (102, 101, 3.2, "python3 -m unittest discover -s tests"),
                      (200, 1, 2.0, "node next dev -p 3005"),
                      (300, 1, 7.0, "python3 -m unittest other")]

    def board(self, rows):
        jobs = []
        for job_id, stage, age, parent, kids in rows:
            job = {"id": job_id, "stage": stage, "updatedAt": ago(age), "children": kids}
            if parent:
                job["parent"] = parent
            if job_id == "002-kid":
                job["worktree"] = str(self.wt)
            jobs.append(job)
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))

    def edit(self, job_id, **fields):
        data = json.loads((self.root / "board.json").read_text())
        for j in data["jobs"]:
            if j["id"] == job_id:
                j.update(fields)
        (self.root / "board.json").write_text(json.dumps(data))

    def run_pass(self, procs=None, servers=(200,)):
        with mock.patch.object(serve, "proc_cwds", side_effect=lambda pids: {p: c for p, c in self.cwds.items()
                                                                             if p in pids}), \
                mock.patch.object(serve.os, "kill") as kill, \
                mock.patch.object(board, "stop_worktree_servers", return_value=list(servers)) as servers_stop:
            got = serve.stop_leftovers(self.procs if procs is None else procs)
        return got, kill, servers_stop

    def lines(self):
        return [json.loads(l) for l in self.waste.read_text().splitlines()] if self.waste.exists() else []

    def assert_left_alone(self):
        got, kill, _ = self.run_pass()
        self.assertEqual(got, [])
        kill.assert_not_called()
        self.assertEqual(self.lines(), [])

    def test_leftover_session_tree_stopped_and_logged(self):
        got, kill, servers = self.run_pass()
        self.assertEqual(sorted(c.args for c in kill.call_args_list),
                         [(100, signal.SIGTERM), (101, signal.SIGTERM), (102, signal.SIGTERM)])
        self.assertEqual(servers.call_args.args, (self.repo, str(self.wt)))
        self.assertEqual(sorted(got), [100, 101, 102, 200])
        (line,) = self.lines()
        self.assertEqual(line["kind"], "leftover")
        self.assertEqual(line["project"], "app")
        self.assertEqual(line["jobs"], ["002-kid"])
        self.assertEqual(sorted(line["pids"]), [100, 101, 102, 200])
        self.assertEqual(line["cpu_min"], 6.7)

    def test_grace_period_left_alone(self):
        self.edit("002-kid", updatedAt=ago(5))
        self.assert_left_alone()

    def test_live_parent_chain_lock_left_alone(self):
        (self.root / "jobs" / "001-par").mkdir()
        (self.root / "jobs" / "001-par" / ".chain.lock").write_text("003-sib")
        self.assert_left_alone()

    def test_unfinished_parent_left_alone(self):
        self.edit("001-par", stage="running")
        self.assert_left_alone()

    def test_unfinished_sibling_left_alone(self):
        self.edit("003-sib", stage="spec")
        self.assert_left_alone()

    def test_no_work_in_tree_left_alone(self):
        self.procs = self.procs[:2]
        self.procs[1] = (101, 100, 0.5, "/bin/zsh")
        self.assert_left_alone()

    def test_unfinished_job_left_alone(self):
        self.edit("002-kid", stage="build")
        self.assert_left_alone()

    def test_unknown_job_or_outside_repo_left_alone(self):
        self.edit("002-kid", parent="009-gone")
        self.assert_left_alone()
        self.edit("002-kid", parent="001-par", id="004-renamed")
        self.assert_left_alone()
        self.edit("004-renamed", id="002-kid")
        self.cwds = {100: str(self.repo) + "-two/.claude/worktrees/scrum-002-kid"}
        self.assert_left_alone()
        self.cwds = {}
        self.assert_left_alone()

    def test_serve_pid_never_signalled(self):
        procs = [(1, 0, 0.0, "launchd"), (SERVE, 1, 0.0, "python3 serve.py"), (100, SERVE, 1.0, self.procs[0][3]),
                 (101, 100, 0.5, "/bin/zsh"), (102, 101, 3.2, "python3 -m unittest")]
        got, kill, _ = self.run_pass(procs, servers=())
        self.assertEqual(sorted(c.args for c in kill.call_args_list),
                         [(100, signal.SIGTERM), (101, signal.SIGTERM), (102, signal.SIGTERM)])
        serve.LEFTOVER_LOGGED.clear()
        procs = [(100, 1, 1.0, self.procs[0][3]), (101, 100, 0.5, "/bin/zsh"), (SERVE, 101, 0.0, "python3 serve.py"),
                 (102, 101, 3.2, "python3 -m unittest")]
        got, kill, _ = self.run_pass(procs, servers=())
        self.assertNotIn(SERVE, [c.args[0] for c in kill.call_args_list])
        self.assertIn((102, signal.SIGTERM), [c.args for c in kill.call_args_list])

    def test_second_pass_logs_once(self):
        self.run_pass()
        got, kill, _ = self.run_pass()
        self.assertIn((100, signal.SIGTERM), [c.args for c in kill.call_args_list])
        self.assertEqual(len(self.lines()), 1)

    def test_idle_cleanup_off_skips_scan(self):
        with mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="0"), \
                mock.patch.object(serve, "process_scan") as scan, mock.patch.object(serve.os, "kill") as kill:
            self.assertEqual(serve.stop_leftovers(), [])
        scan.assert_not_called()
        kill.assert_not_called()

    def test_empty_scan_does_nothing(self):
        with mock.patch.object(serve, "process_scan", return_value=[]):
            got, kill, servers = self.run_pass([])
            with mock.patch.object(serve.os, "kill") as kill2:
                self.assertEqual(serve.stop_leftovers(), [])
        self.assertEqual(got, [])
        kill.assert_not_called()
        kill2.assert_not_called()
        servers.assert_not_called()
        self.assertEqual(self.lines(), [])

    def test_watchdog_failure_is_contained(self):
        s = serve
        with mock.patch.object(s.board, "projects", return_value={}), \
                mock.patch.object(s, "stop_leftovers", side_effect=RuntimeError("boom")) as leftovers, \
                mock.patch.object(s, "window_tick") as window, mock.patch.object(s, "idle_cleanup"), \
                mock.patch.object(s, "auto_continue_tick"), mock.patch.object(s.board, "record_cpu_sample"), \
                mock.patch.object(s, "weekly_tick"), mock.patch.object(s, "pulse_tick"), \
                mock.patch.object(s, "cooldown_chime"), mock.patch("sys.stderr", new=io.StringIO()) as err:
            s.watchdog_tick()
        leftovers.assert_called_once_with()
        window.assert_called_once()
        self.assertIn("watchdog: leftover sessions: boom", err.getvalue())


if __name__ == "__main__":
    unittest.main()
