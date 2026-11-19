"""Job 1179 (BigBoy 1165, waste kind `cpu-hog`): serve.py report_hogs finds a process outside the scrum that held more
than one core for every interval of the last 10 minutes, reports it in /api/machine "hogs", logs it once per run to
waste.log and never signals it."""
import copy, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

import test_serve  # noqa: F401  its import-time env pins (SCRUM_IDLE_CLEANUP=0, SCRUM_PS, ...) apply first
import serve

board = serve.board
SPIN = "/opt/fake/bin/spin --x"


def steady(pid, pct, cmd, ppid=1, start=0):
    """A process at a steady pct % of one core since start: its scan line at time t (CPU minutes from 10)."""
    return lambda t: (pid, ppid, 10 + pct / 100 * max(t - start, 0) / 60, cmd)


class HogsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(os.path.realpath(tmp.name))
        self.repo = base / "app"
        (self.repo / "scrum").mkdir(parents=True)
        (base / "projects.json").write_text(json.dumps([str(self.repo)]))
        self.waste = base / "waste.log"
        env = mock.patch.dict(os.environ, SCRUM_IDLE_CLEANUP="1", SCRUM_PULSE=str(base / "pulse.log"),
                              SCRUM_REGISTRY=str(base / "projects.json"))
        env.start()
        self.addCleanup(env.stop)
        serve.HOG_READINGS.clear()
        self.addCleanup(serve.HOG_READINGS.clear)
        hogs = mock.patch.object(serve, "HOGS", [])
        hogs.start()
        self.addCleanup(hogs.stop)
        self.cwds, self.cwd_calls = {}, []

    def run_pass(self, procs, now):
        """report_hogs(procs, now) with proc_cwds answering from self.cwds; nothing is ever signalled."""
        with mock.patch.object(serve, "proc_cwds", side_effect=lambda pids: {p: c for p, c in self.cwds.items()
                                                                             if p in pids}) as cwds, \
                mock.patch.object(serve.os, "kill") as kill, mock.patch.object(serve.os, "killpg") as killpg, \
                mock.patch.object(serve, "stop_tree") as tree:
            got = serve.report_hogs(procs, now=now)
        kill.assert_not_called()
        killpg.assert_not_called()
        tree.assert_not_called()
        self.assertLessEqual(cwds.call_count, 1)
        self.cwd_calls += [(now, c.args[0]) for c in cwds.call_args_list]
        return got

    def series(self, scan, times):
        """run_pass at each t in times on scan(t)'s process lines."""
        return [self.run_pass(scan(t), t) for t in times]

    def lines(self):
        """waste.log's lines, each without its wall-clock t."""
        if not self.waste.exists():
            return []
        return [{k: v for k, v in json.loads(l).items() if k != "t"} for l in self.waste.read_text().splitlines()]

    def test_hog_reported_and_logged_once(self):
        self.cwds = {4242: "/opt/fake"}
        spin = lambda t: [(4242, 1, 10 + 1.5 * (t // 60), SPIN)]  # 1.5 CPU minutes a call, one call a minute
        got = self.series(spin, range(0, 601, 60))
        self.assertEqual(got[:-1], [[]] * 10, "not before 10 minutes over the line")
        hog = [{"name": "spin", "pid": 4242, "pct": 150, "minutes": 10}]
        self.assertEqual(got[-1], hog)
        self.assertEqual(serve.HOGS, hog)
        logged = [{"kind": "cpu-hog", "project": None, "jobs": [], "pids": [], "cpu_min": 15.0, "name": "spin",
                   "pid": 4242, "pct": 150}]
        self.assertEqual(self.lines(), logged)
        later = self.series(spin, range(660, 901, 60))
        self.assertEqual(later, [[{"name": "spin", "pid": 4242, "pct": 150, "minutes": m}] for m in (11, 12, 13, 14, 15)])
        self.assertEqual(self.lines(), logged, "one line per run")

    def test_hog_name(self):
        with tempfile.TemporaryDirectory() as d:
            tool = Path(d) / "My Tool Helper"
            tool.write_text("")
            (Path(d) / "My Tool").mkdir()  # a directory on the way is not the binary
            self.assertEqual(serve.hog_name(f"{tool} --type=x"), "My Tool Helper")
        self.assertEqual(serve.hog_name("/opt/fake/bin/spin --x"), "spin")
        self.assertEqual(serve.hog_name("spin"), "spin")
        self.assertEqual(serve.hog_name(""), "")

    def test_short_or_light_cpu_not_reported(self):
        cases = {"5 minutes at 300%": (steady(5001, 300, "/opt/fake/a"), range(0, 301, 60)),
                 # its 10-minute average at t=600 is 150%, but it was over the line for only the last 5 minutes
                 "0% then 300%": (steady(5002, 300, "/opt/fake/b", start=300), range(0, 601, 60)),
                 "steady 30%": (steady(5003, 30, "/opt/fake/c"), range(0, 901, 60)),
                 "exactly one core": (steady(5004, 100, "/opt/fake/d"), range(0, 901, 60))}
        for name, (proc, times) in cases.items():
            with self.subTest(name):
                serve.HOG_READINGS.clear()
                self.assertEqual(self.series(lambda t: [proc(t)], times), [[]] * len(times))
        self.assertEqual(self.lines(), [])
        self.assertEqual(serve.HOGS, [])

    def test_scrum_processes_not_reported(self):
        me = os.getpid()
        procs = [steady(me, 200, "/usr/bin/python3 serve.py", ppid=os.getppid()),
                 steady(7001, 200, "/opt/fake/bin/e2e", ppid=me),  # a child of this process
                 steady(7100, 200, "/usr/local/bin/claude -p /trevskills-scrum build 1-a"),
                 steady(7101, 0, "/bin/zsh -c make", ppid=7100),
                 steady(7102, 200, "/opt/fake/bin/make", ppid=7101),  # a claude line's grandchild
                 steady(7200, 200, "node /opt/homebrew/bin/codex exec --full-auto x"),
                 steady(7201, 200, "/opt/fake/bin/rg foo", ppid=7200),
                 steady(7300, 200, "/opt/fake/node --x /lib/node_modules/@openai/codex/vendor/x"),
                 steady(7400, 200, "/opt/fake/bin/build"),  # cwd: the registered repo
                 steady(7401, 200, "/opt/fake/bin/build2"),  # cwd: inside it
                 steady(7500, 200, "/opt/fake/bin/vite /u/app/.claude/worktrees/scrum-1-a"),
                 steady(7600, 200, SPIN),  # no cwd from proc_cwds: still reported
                 steady(7650, 200, "/opt/fake/bin/next"),  # cwd: a sibling folder whose name starts with the repo's
                 steady(7700, 200, "/opt/fake/bin/elsewhere"),
                 steady(7800, 200, "/opt/fake/bin/loop-a", ppid=7801),  # a ppid cycle in a bad scan
                 steady(7801, 200, "/opt/fake/bin/loop-b", ppid=7800),
                 steady(7900, 30, "/opt/fake/bin/light")]  # never meets the span rule
        self.cwds = {7400: str(self.repo), 7401: str(self.repo / "web"), 7650: str(self.repo) + "2",
                     7700: "/opt/elsewhere", 7900: str(self.repo)}
        got = self.series(lambda t: [p(t) for p in procs], range(0, 601, 60))
        self.assertEqual(got[:-1], [[]] * 10)
        self.assertEqual([(h["pid"], h["pct"]) for h in got[-1]], [(7600, 200), (7650, 200), (7700, 200), (7800, 200),
                                                                  (7801, 200)])
        self.assertEqual([l["pid"] for l in self.lines()], [7600, 7650, 7700, 7800, 7801])
        self.assertEqual(self.cwd_calls, [(600, [7400, 7401, 7600, 7650, 7700, 7800, 7801])],
                         "one lsof call, on only the pids past the span, ancestry and command checks")

    def test_reused_pid_starts_over(self):
        other = "/opt/fake/bin/other"
        scan = lambda t: [steady(4242, 150, SPIN)(t) if t < 360 else steady(4242, 150, other, start=360)(t)]
        got = self.series(scan, range(0, 901, 60))
        self.assertEqual(got, [[]] * 16, "the new command has not spent a fresh 10 minutes over the line")
        self.assertNotIn((4242, SPIN), serve.HOG_READINGS, "the old command's readings are gone")
        self.assertEqual(self.run_pass(scan(960), 960), [{"name": "other", "pid": 4242, "pct": 150, "minutes": 10}])

    def test_gone_pid_dropped(self):
        spin, bystander = steady(4242, 150, SPIN), steady(5000, 0, "/opt/fake/idle")
        self.assertEqual(self.series(lambda t: [spin(t), bystander(t)], range(0, 541, 60)), [[]] * 10)
        self.assertEqual(self.run_pass([bystander(600)], 600), [], "missing from a non-empty scan")
        self.assertNotIn((4242, SPIN), serve.HOG_READINGS)
        got = self.series(lambda t: [spin(t), bystander(t)], range(660, 1261, 60))
        self.assertEqual(got[:-1], [[]] * 10, "back one call later: it starts over")
        self.assertEqual(got[-1], [{"name": "spin", "pid": 4242, "pct": 150, "minutes": 10}])

    def test_empty_scan_keeps_state(self):
        spin = steady(4242, 150, SPIN)
        self.series(lambda t: [spin(t)], range(0, 301, 60))
        before = copy.deepcopy(serve.HOG_READINGS)
        self.assertEqual(self.run_pass([], 360), [])
        with mock.patch.object(serve, "process_scan", return_value=[]) as scan:
            self.assertEqual(self.run_pass(None, 420), [])
        scan.assert_called_once_with()
        self.assertEqual(serve.HOG_READINGS, before, "an empty scan changes nothing")
        got = self.series(lambda t: [spin(t)], (480, 540, 600))  # 300 -> 480 is one interval at 150%
        hog = [{"name": "spin", "pid": 4242, "pct": 150, "minutes": 10}]
        self.assertEqual(got, [[], [], hog])
        held, before = serve.HOGS, copy.deepcopy(serve.HOG_READINGS)
        self.assertIs(self.run_pass([], 660), held, "an empty scan keeps the last list")
        self.assertIs(serve.HOGS, held)
        self.assertEqual(serve.HOG_READINGS, before)
        self.assertEqual(self.run_pass([spin(720)], 720), [{**hog[0], "minutes": 12}], "CPU growth measured across the gap")
        self.assertEqual(len(self.lines()), 1)

    def test_hog_logged_again_after_dropping(self):
        # 150% to t=600, one interval at 50% (600 -> 660), then 150% again from t=660
        cpu = lambda t: 10 + 1.5 * min(t, 600) / 60 + (0.5 if t >= 660 else 0) + 1.5 * max(t - 660, 0) / 60
        scan = lambda t: [(4242, 1, cpu(t), SPIN)]
        hog = {"name": "spin", "pid": 4242, "pct": 150}
        self.assertEqual(self.series(scan, range(0, 601, 60))[-1], [{**hog, "minutes": 10}])
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.series(scan, range(660, 1201, 60)), [[]] * 10, "it left the list at the 50% interval")
        self.assertEqual(len(self.lines()), 1, "never logged again in between")
        self.assertEqual(self.run_pass(scan(1260), 1260), [{**hog, "minutes": 10}])
        self.assertEqual([l["pct"] for l in self.lines()], [150, 150], "logged again after a full span back over the line")


if __name__ == "__main__":
    unittest.main()
