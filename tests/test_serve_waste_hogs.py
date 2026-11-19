"""Job 1179 (BigBoy 1165, waste kind `cpu-hog`): serve.py report_hogs finds a process outside the scrum that held more
than one core for every interval of the last 10 minutes, reports it in /api/machine "hogs", logs it once per run to
waste.log and never signals it."""
import json, os, tempfile, unittest
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


if __name__ == "__main__":
    unittest.main()
