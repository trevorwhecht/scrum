import json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ.setdefault("SCRUM_PS", os.devnull)  # no live sessions unless a test says so, whatever this machine runs
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
import board  # noqa: E402

BOARD_PY = ROOT / "skills" / "trevskills-scrum" / "board.py"
NOW = 1_000_000


def usage(five=None, seven=None, written_at=NOW):
    """A usage.json dict. five/seven = (used_percentage, seconds until resets_at)."""
    limits = {}
    for key, w, base in (("five_hour", five, written_at), ("seven_day", seven, written_at)):
        if w is not None:
            limits[key] = {"used_percentage": w[0], "resets_at": base + w[1]}
    return {"rate_limits": limits, "written_at": written_at}


class PaceCapTest(unittest.TestCase):
    # five_hour with 9000 s left = half elapsed, so projected = 2 * used.
    def test_pace_cap_math(self):
        cap = lambda u, base=3: board.pace_cap(u, NOW, base)
        # tiers
        self.assertEqual(cap(usage(five=(20, 9000))), 5)            # P=40
        self.assertIsNone(cap(usage(five=(20, 9000)), None))         # under pace, no base: no cap
        self.assertEqual(cap(usage(five=(29.9, 9000))), 5)          # P just under 60
        self.assertEqual(cap(usage(five=(30, 9000))), 3)            # P=60
        self.assertEqual(cap(usage(five=(40, 9000))), 3)            # P=80
        self.assertIsNone(cap(usage(five=(40, 9000)), None))         # on pace, no base: no cap
        self.assertEqual(cap(usage(five=(50, 9000))), 2)            # P=100
        self.assertEqual(cap(usage(five=(55, 9000))), 2)            # P=110
        self.assertEqual(cap(usage(five=(55, 9000)), None), 2)      # min(None, 2) = 2
        self.assertEqual(cap(usage(five=(55, 9000)), 1), 1)         # min(1, 2)
        self.assertEqual(cap(usage(five=(62.5, 9000))), 1)          # P=125
        # the Run-all base of 5: under 60% gives 7, 100% and 125% still give 2 and 1
        self.assertEqual(cap(usage(five=(20, 9000)), 5), 7)         # P=40
        self.assertEqual(cap(usage(five=(50, 9000)), 5), 2)         # P=100
        self.assertEqual(cap(usage(five=(62.5, 9000)), 5), 1)       # P=125
        self.assertEqual(cap(usage(five=(100, 9000)), None), 1)     # P=200
        # the highest window wins: 5h P=40, 7d (half of 604800 left) P=130
        self.assertEqual(cap(usage(five=(20, 9000), seven=(65, 302400))), 1)
        # missing / unparseable
        self.assertIsNone(cap(None))
        self.assertIsNone(cap({}))
        self.assertIsNone(cap({"rate_limits": "x", "written_at": NOW}))
        self.assertIsNone(cap({"rate_limits": {"five_hour": {"used_percentage": 55, "resets_at": NOW + 9000}}}))
        self.assertIsNone(cap(usage()))  # no windows
        # stale: more than 300 s old; exactly 300 s and future still count as fresh
        self.assertIsNone(cap(usage(five=(55, 9000 + 301), written_at=NOW - 301)))
        self.assertEqual(cap(usage(five=(55, 9000 + 300), written_at=NOW - 300)), 2)
        self.assertEqual(cap(usage(five=(55, 9000 - 60), written_at=NOW + 60)), 2)
        # early window: under 10% elapsed (17000 s left of 18000) is skipped
        self.assertIsNone(cap(usage(five=(50, 17000))))
        self.assertEqual(cap(usage(five=(50, 16200))), 1)  # exactly 10% elapsed counts
        # past resets_at: the window already rolled over
        self.assertIsNone(cap(usage(five=(55, 0))))
        self.assertIsNone(cap(usage(five=(55, -10))))
        # used_percentage must be a number from 0 to 100
        self.assertIsNone(cap(usage(five=(150, 9000))))
        self.assertIsNone(cap(usage(five=(-1, 9000))))
        self.assertIsNone(cap(usage(five=("55", 9000))))
        self.assertIsNone(cap(usage(five=(True, 9000))))
        # an unusable window is ignored, the other still counts
        self.assertEqual(cap(usage(five=(55, 0), seven=(40, 302400))), 3)


class StatuslineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sub" / "usage.json"
        env = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(self.path)})
        env.start()
        self.addCleanup(env.stop)

    def run_cli(self, stdin):
        return subprocess.run([sys.executable, str(BOARD_PY), "statusline"], input=stdin, capture_output=True,
                              text=True, env={**os.environ, "SCRUM_USAGE": str(self.path)})

    def test_statusline_writes_usage_and_prints_summary(self):
        limits = {"five_hour": {"used_percentage": 42, "resets_at": 1760000000},
                  "seven_day": {"used_percentage": 18.4, "resets_at": 1760500000}}
        before = int(time.time())
        with mock.patch.object(board.os, "replace", wraps=os.replace) as rep:
            self.assertEqual(board.cmd_statusline(json.dumps({"model": {"id": "x"}, "rate_limits": limits})),
                             "5h 42% · 7d 18%")
        (src, dst), _ = rep.call_args
        self.assertEqual((Path(src).parent, Path(dst)), (self.path.parent, self.path))
        data = json.loads(self.path.read_text())
        self.assertEqual(data["rate_limits"], limits)
        self.assertEqual(sorted(data), ["rate_limits", "written_at"])
        self.assertIsInstance(data["written_at"], int)
        self.assertTrue(before <= data["written_at"] <= int(time.time()))
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["usage.json"])  # no temp left behind
        out = self.run_cli(json.dumps({"rate_limits": limits}))
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "5h 42% · 7d 18%\n", ""))

    def test_statusline_without_rate_limits_writes_nothing(self):
        for stdin in ('{"model": {"id": "x"}}', "not json", "", "[1, 2]", '{"rate_limits": null}'):
            out = self.run_cli(stdin)
            self.assertEqual((out.returncode, out.stdout, out.stderr), (0, "\n", ""), stdin)
            self.assertFalse(self.path.exists(), stdin)
        self.path.parent.mkdir(parents=True)
        self.path.write_text("old")
        self.assertEqual(self.run_cli("{}").stdout, "\n")
        self.assertEqual(self.path.read_text(), "old")
        # only one window present: only that one is printed
        self.assertEqual(board.cmd_statusline('{"rate_limits": {"seven_day": {"used_percentage": 7.6, "resets_at": 1}}}'),
                         "7d 8%")
        self.assertEqual(board.cmd_statusline('{"rate_limits": {"five_hour": {"used_percentage": 99, "resets_at": 1}}}'),
                         "5h 99%")


class ReadyPacingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.usage = Path(self.tmp.name) / "usage.json"
        env = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(self.usage)})
        env.start()
        self.addCleanup(env.stop)

    def write_usage(self, p5):
        """A fresh usage file whose five_hour window projects to p5 % (half the window elapsed)."""
        now = int(time.time())
        self.usage.write_text(json.dumps(usage(five=(p5 / 2, 9000), written_at=now)))

    def jobs(self):
        return {j["id"]: j for j in json.loads((self.root / "board.json").read_text())["jobs"]}

    def spec(self, job_id, path):
        p = self.root / "jobs" / job_id / "spec.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# x\n## Likely files\n- `{path}`: why\n")

    def runall(self, n):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "backlog.md").write_text("".join(f"- [ ] item {i}\n" for i in range(n)))
        out = board.cmd_runall_start(self.root)
        for i, k in enumerate(out["children"]):
            self.spec(k, f"src/{i}.py")
        return out["id"], out["children"]

    def bigboy(self, n):
        parent = board.cmd_new(self.root, "Big")
        board.cmd_set(self.root, parent, ["lane=bigboy", "stage=plan"])
        tickets = "".join(f"### T{i}: Part {i}\nDepends on: {'none' if i < n else ', '.join(f'T{j}' for j in range(1, n))}\n"
                          f"Parallel: yes — disjoint\nExposure: {'yes' if i == n else 'no'}\nHard stops: none\n"
                          f"Human setup: none\nBuild part {i}.\n" for i in range(1, n + 1))
        (self.root / "jobs" / parent / "plan.md").write_text(
            "PLAN: READY\n# Big\n## Goal\nShip it.\n## Done when\n1. Works.\n## Tickets\n" + tickets + "## Assumptions\n- none\n")
        kids = board.cmd_plan_apply(self.root, parent)["children"]
        for i, k in enumerate(kids):
            self.spec(k, f"src/{i}.py")
        return parent, kids[:-1]  # the last (exposure) child depends on all the others

    def test_ready_runall_cap_follows_pacing(self):
        for p5, claims in ((40, 7), (80, 5), (110, 2), (130, 1), (None, 5)):
            self.tmp.cleanup()
            self.root.parent.mkdir(parents=True, exist_ok=True)
            if p5 is not None:
                self.write_usage(p5)
            parent, kids = self.runall(8)
            out = board.cmd_ready(self.root, parent)
            self.assertEqual((out["ready"], out["in_progress"]), (kids[:claims], claims), p5)
        # a stale usage file means no throttling
        self.tmp.cleanup()
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.usage.write_text(json.dumps(usage(five=(55, 9000), written_at=int(time.time()) - 301)))
        parent, kids = self.runall(8)
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], kids[:5])

    def test_ready_bigboy_throttled_when_over_pace(self):
        for p5, claims in ((None, 4), (40, 4), (80, 4), (110, 2), (130, 1)):
            self.tmp.cleanup()
            self.root.parent.mkdir(parents=True, exist_ok=True)
            if p5 is not None:
                self.write_usage(p5)
            parent, kids = self.bigboy(5)
            out = board.cmd_ready(self.root, parent)
            self.assertEqual((out["ready"], out["in_progress"]), (kids[:claims], claims), p5)

    def test_ready_pacing_never_below_one_and_leaves_busy_alone(self):
        now = int(time.time())
        maxed = {"rate_limits": {"five_hour": {"used_percentage": 100, "resets_at": now + 9000},
                                 "seven_day": {"used_percentage": 100, "resets_at": now + 302400}}, "written_at": now}
        for make in (self.runall, self.bigboy):
            self.tmp.cleanup()
            self.root.parent.mkdir(parents=True, exist_ok=True)
            self.usage.write_text(json.dumps(maxed))
            parent, kids = make(4)
            out = board.cmd_ready(self.root, parent)  # nothing in progress: still claims 1
            self.assertEqual((out["ready"], out["in_progress"]), (kids[:1], 1))
            # over the cap: a second child already in progress is left exactly as it is
            board.cmd_set(self.root, kids[1], ["stage=build", "round=2", "builder=claude"])
            before = self.jobs()
            out = board.cmd_ready(self.root, parent)
            self.assertEqual((out["ready"], out["in_progress"]), ([], 2))
            after = self.jobs()
            self.assertEqual(after, before)  # no child or parent field changed, no reason set
            self.assertIsNone(after[parent].get("reason"))
            self.assertEqual(after[parent]["stage"], "running")


if __name__ == "__main__":
    unittest.main()
