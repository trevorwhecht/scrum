import json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
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
    def test_pace_cap_always_none(self):
        """Usage pacing gates nothing (job 282); continue.py reads pace_cap, so it must stay importable and say None."""
        for u in (usage(five=(62.5, 9000)), usage(five=(100, 9000), seven=(100, 302400)), usage(five=(20, 9000)),
                  None, {}, "x"):
            for base in (None, 1, 3, 5):
                self.assertIsNone(board.pace_cap(u, NOW, base), (u, base))

    def test_no_fixed_session_caps(self):
        self.assertFalse(hasattr(board, "slot_cap"))
        self.assertFalse(hasattr(board, "RUNALL_MAX_IN_PROGRESS"))


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

    def merge(self, old, new):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if old is not None:
            self.path.write_text(old if isinstance(old, str) else json.dumps({"rate_limits": old, "written_at": 1}))
        board.cmd_statusline(json.dumps({"rate_limits": new}))
        return json.loads(self.path.read_text())

    def test_statusline_stale_partial_payload_keeps_higher(self):
        t = int(time.time()) + 5000
        got = self.merge({"five_hour": {"used_percentage": 80, "resets_at": t},
                          "seven_day": {"used_percentage": 50, "resets_at": t + 9}},
                         {"seven_day": {"used_percentage": 29, "resets_at": t + 9}})
        self.assertEqual(got["rate_limits"], {"five_hour": {"used_percentage": 80, "resets_at": t},
                                              "seven_day": {"used_percentage": 50, "resets_at": t + 9}})

    def test_statusline_merge_drops_expired_keeps_unexpired(self):
        t = int(time.time())
        got = self.merge({"five_hour": {"used_percentage": 80, "resets_at": t - 5},
                          "seven_day": {"used_percentage": 50, "resets_at": t + 500}}, {"extra": 1})
        self.assertEqual(got["rate_limits"], {"extra": 1, "seven_day": {"used_percentage": 50, "resets_at": t + 500}})

    def test_statusline_merge_later_resets_at_wins(self):
        t = int(time.time()) + 500
        old = {"five_hour": {"used_percentage": 80, "resets_at": t}}
        new = {"five_hour": {"used_percentage": 3, "resets_at": t + 100}}
        self.assertEqual(self.merge(old, new)["rate_limits"], new)
        older = {"five_hour": {"used_percentage": 1, "resets_at": t - 100}}
        self.assertEqual(self.merge(old, older)["rate_limits"], old)

    def test_statusline_merge_equal_resets_higher_used(self):
        t = int(time.time()) + 500
        lo, hi = {"five_hour": {"used_percentage": 10, "resets_at": t}}, {"five_hour": {"used_percentage": 60, "resets_at": t}}
        self.assertEqual(self.merge(lo, hi)["rate_limits"], hi)
        self.assertEqual(self.merge(hi, lo)["rate_limits"], hi)

    def test_statusline_merge_bad_or_missing_old_file(self):
        new = {"five_hour": {"used_percentage": 5, "resets_at": 1}}
        for old in (None, "not json", "[1]", '{"rate_limits": 3}'):
            self.path.unlink(missing_ok=True)
            got = self.merge(old, new)
            self.assertEqual(got["rate_limits"], new, old)
            self.assertTrue(abs(got["written_at"] - time.time()) < 60, old)


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

    def test_ready_ignores_usage_pacing_and_runall_cap(self):
        """8 waiting non-overlapping children beside 6 in progress: only free RAM (ram_room) and machine_ok limit the
        batch, never usage.json or a Run-all count cap."""
        for ram, claims, reason in (("90", 8, None), ("14", 0, "waiting: free RAM 14% (< 20%)")):
            self.tmp.cleanup()
            self.root.parent.mkdir(parents=True, exist_ok=True)
            self.write_usage(130)  # projected 130 %: the old pace cap was 1
            parent, kids = self.runall(14)
            for k in kids[:6]:
                board.cmd_set(self.root, k, ["stage=build", "round=1", "builder=claude"])
            with mock.patch.dict(os.environ, SCRUM_FREE_RAM=ram, SCRUM_SWAP_PCT="0"):
                out = board.cmd_ready(self.root, parent)
            self.assertEqual((out["ready"], out["in_progress"]), (kids[6:6 + claims], 6 + claims), ram)
            self.assertEqual(self.jobs()[parent].get("reason"), reason, ram)

if __name__ == "__main__":
    unittest.main()
