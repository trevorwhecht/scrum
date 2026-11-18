import json, os, subprocess, sys, tempfile, time, unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_VM_PRESSURE"] = "1"  # kernel memory pressure normal unless a test says so; no test runs sysctl
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test runs top or reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ.setdefault("SCRUM_PS", os.devnull)  # no live sessions unless a test says so, whatever this machine runs
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))  # job 971: finish_first reads every registered board; never the real ones
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

    def test_statusline_writes_the_config_dir_usage_file(self):
        """An OWA session (CLAUDE_CONFIG_DIR set, no SCRUM_USAGE) writes its own usage.json, never main's."""
        owa, main = Path(self.tmp.name) / "owa", Path(self.tmp.name) / "main"
        owa.mkdir()
        main.mkdir()
        accounts = json.dumps([["main", str(main), None], ["owa", str(owa), [80, 90]]])
        env = {k: v for k, v in os.environ.items() if k != "SCRUM_USAGE"}
        with mock.patch.dict(os.environ, {**env, "CLAUDE_CONFIG_DIR": str(owa), "SCRUM_ACCOUNTS": accounts}, clear=True):
            board.cmd_statusline(json.dumps({"rate_limits": {"five_hour": {"used_percentage": 33, "resets_at": 9}}}))
        self.assertEqual(json.loads((owa / "usage.json").read_text())["rate_limits"]["five_hour"]["used_percentage"], 33)
        self.assertFalse((main / "usage.json").exists())

    def test_scrum_usage_wins_over_config_dir(self):
        owa = Path(self.tmp.name) / "owa"
        owa.mkdir()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(owa)}):
            board.cmd_statusline(json.dumps({"rate_limits": {"five_hour": {"used_percentage": 44, "resets_at": 9}}}))
        self.assertEqual(json.loads(self.path.read_text())["rate_limits"]["five_hour"]["used_percentage"], 44)
        self.assertFalse((owa / "usage.json").exists())

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
        pace = mock.patch.object(board, "PACE_LEAD_PCT", 1000)  # these fixtures sit at 50 % elapsed: test the ladder alone
        pace.start()
        self.addCleanup(pace.stop)
        hold = mock.patch.object(board, "USAGE_HOLD_PCT", 101)  # the 90 % hold has its own tests: here the ladder alone
        hold.start()
        self.addCleanup(hold.stop)

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
        """8 waiting non-overlapping children beside 6 in progress: only free RAM and, at 40% free or less, the young-session ramp (ram_room)
        and machine_ok limit the batch, never usage.json or a Run-all count cap."""
        for ram, claims, reason in (("40", board.MAX_YOUNG_SESSIONS, None), ("14", 0, "waiting: free RAM 14% (< 20%)")):
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

    def test_ram_room_ramps_young_sessions(self):
        """Free RAM at 2x the minimum still starts at most MAX_YOUNG_SESSIONS at once: the 2026-11-04 wake burst started 10."""
        for young, room in ((0, 2), (1, 1), (2, 0)):
            ages = [5] * young + [600] * 3
            with mock.patch.dict(os.environ, SCRUM_FREE_RAM="40", SCRUM_SWAP_PCT="0"), \
                    mock.patch.object(board, "session_ages", return_value=ages):
                self.assertEqual(board.ram_room(floor=0), room, young)

    def held_board(self, held, pct):
        """Run-all parent with 3 children sharing Likely file x: `held` of A, C limit-held in build, B waiting."""
        self.usage.write_text(json.dumps(usage(five=(pct, 9000), written_at=int(time.time()))))
        parent, (a, b, c) = self.runall(3)
        for k in (a, b, c):
            self.spec(k, "x")
        board.cmd_set(self.root, b, ["lane=fast"])
        for k in held:
            job = {"A": a, "C": c}[k]
            board.cmd_set(self.root, job, ["stage=build", "round=1", "builder=claude"])
            self.set_hold(job)
        return parent, b

    def set_hold(self, job_id):
        path = self.root / "board.json"
        data = json.loads(path.read_text())
        for j in data["jobs"]:
            if j["id"] == job_id:
                j["limitResetAt"] = int(time.time()) + 3600
        path.write_text(json.dumps(data))

    def claimed(self, held, pct):
        parent, b = self.held_board(held, pct)
        board.cmd_ready(self.root, parent)
        return self.jobs()[b]["stage"] == "spec"

    def test_ready_held_kids_yield_when_cap_below_held(self):
        self.assertTrue(self.claimed("AC", 96))  # allowance 1 < 2 held

    def test_ready_held_kids_keep_slot_when_cap_covers_them(self):
        self.assertFalse(self.claimed("A", 96))  # allowance 1 >= 1 held

    def test_ready_held_kids_keep_slot_without_taper(self):
        self.assertFalse(self.claimed("A", 0))  # 0 % used: no taper

    def test_ready_held_kids_yield_still_respects_zero_cap(self):
        self.assertFalse(self.claimed("AC", 99))  # allowance 0: nothing is claimed

    def two_accounts(self, main_pct, owa_pct):
        """SCRUM_ACCOUNTS main (SCRUM_USAGE) + owa, each with a fresh five_hour reading at that used %."""
        owa = Path(self.tmp.name) / "owa"
        owa.mkdir(exist_ok=True)
        now = int(time.time())
        self.usage.write_text(json.dumps(usage(five=(main_pct, 9000), written_at=now)))
        (owa / "usage.json").write_text(json.dumps(usage(five=(owa_pct, 9000), written_at=now)))
        env = mock.patch.dict(os.environ, SCRUM_ACCOUNTS=json.dumps([["main", "/unused", None], ["owa", str(owa), [80, 90]]]))
        env.start()
        self.addCleanup(env.stop)

    def test_ready_claims_when_only_main_is_full(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.two_accounts(99, 10)
        parent, kids = self.runall(1)
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], kids)

    def test_ready_holds_when_every_account_is_full(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.two_accounts(99, 85)
        board.note_limit("main", int(time.time()) + 3600)  # the primary stops only on its limit (job 1182)
        parent, kids = self.runall(1)
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        job = self.jobs()[parent]
        self.assertEqual(job["stage"], "running")
        self.assertTrue(job["reason"].startswith("waiting: no account has room: main limited until"), job["reason"])
        self.assertIn("; owa reserve 5h 85% used", job["reason"])

    def test_ready_only_held_kids_left_keeps_parent_running(self):
        parent, b = self.held_board("AC", 96)  # allowance 1 < 2 held, and no waiting sibling to claim
        path = self.root / "board.json"
        data = json.loads(path.read_text())
        next(j for j in data["jobs"] if j["id"] == b)["stage"] = "done"
        path.write_text(json.dumps(data))
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), ([], 2))
        self.assertEqual(self.jobs()[parent]["stage"], "running")

class UsageHoldTest(unittest.TestCase):
    def test_usage_hold_90(self):
        for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
            kw = lambda pct: {"five" if key == "five_hour" else "seven": (pct, 7200)}
            with mock.patch.object(board, "PACE_LEAD_PCT", 1000):
                held = board.usage_allowance(usage(**kw(90)), NOW, 0)
                self.assertEqual(held, 0)
                self.assertTrue(held.reason.startswith(f"hold {label} 90% used (90% cap), resets "), held.reason)
                self.assertIsNone(board.usage_allowance(usage(**kw(89)), NOW, 0))

    def test_usage_hold_near_reset(self):
        held = board.usage_allowance(usage(five=(95, 600)), NOW, 0)
        self.assertEqual(held, 0)
        self.assertTrue(held.reason.startswith("hold 5h 95%"), held.reason)

    def test_usage_hold_expired_or_stale(self):
        self.assertIsNone(board.usage_allowance(usage(five=(95, 0)), NOW, 0))
        self.assertIsNone(board.usage_allowance(usage(five=(95, -5)), NOW, 0))
        self.assertIsNone(board.usage_allowance(usage(five=(95, 600), written_at=NOW - 301), NOW, 0))


class AccountEnv(unittest.TestCase):
    """A main and an owa config dir under a temp folder, listed through SCRUM_ACCOUNTS; SCRUM_USAGE unset."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.main, self.owa = base / "main", base / "owa"
        self.main.mkdir()
        self.owa.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ("SCRUM_USAGE", "CLAUDE_CONFIG_DIR")}
        env["SCRUM_ACCOUNTS"] = json.dumps([["main", str(self.main), None], ["owa", str(self.owa), [80, 90]]])
        patch = mock.patch.dict(os.environ, env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        pace = mock.patch.object(board, "PACE_LEAD_PCT", 1000)  # 9000 s fixtures are 50 % elapsed: the ladder and reserves alone
        pace.start()
        self.addCleanup(pace.stop)
        hold = mock.patch.object(board, "USAGE_HOLD_PCT", 101)  # the 90 % hold has its own tests: here the ladder alone
        hold.start()
        self.addCleanup(hold.stop)

    def write(self, folder, five=None, seven=None, written_at=NOW):
        (folder / "usage.json").write_text(json.dumps(usage(five, seven, written_at)))


class AccountsTest(AccountEnv):
    def test_accounts_order_env_override_and_missing_dir(self):
        self.assertEqual(board.ACCOUNTS, (("main", "~/.claude", (None, 90)), ("owa", "~/.claude-owa", (None, 90))))
        self.assertEqual(board.accounts(), [("main", self.main, None), ("owa", self.owa, (80, 90))])
        self.assertEqual(board.accounts()[1].reserve, (80, 90))
        gone = Path(self.tmp.name) / "gone"
        with mock.patch.dict(os.environ, SCRUM_ACCOUNTS=json.dumps([["main", str(gone), None], ["owa", str(gone), None]])):
            self.assertEqual(board.accounts(), [("main", gone, None)])  # the first stays, a later missing dir drops
        del os.environ["SCRUM_ACCOUNTS"]
        home = Path(self.tmp.name)
        (home / ".claude-owa").mkdir()
        with mock.patch.dict(os.environ, HOME=str(home)):
            self.assertEqual(board.accounts(), [("main", home / ".claude", (None, 90)), ("owa", home / ".claude-owa", (None, 90))])
            with mock.patch.dict(os.environ, SCRUM_USAGE="/x/usage.json"):
                self.assertEqual(board.accounts(), [("main", home / ".claude", (None, 90))])

    def test_usage_path_per_account(self):
        self.assertEqual(board.usage_path(), self.main / "usage.json")
        self.assertEqual(board.usage_path("owa"), self.owa / "usage.json")
        with mock.patch.dict(os.environ, CLAUDE_CONFIG_DIR=str(self.owa)):
            self.assertEqual(board.usage_path(), self.owa / "usage.json")
            self.assertEqual(board.usage_path("main"), self.main / "usage.json")
        with mock.patch.dict(os.environ, SCRUM_USAGE="/x/u.json"):
            self.assertEqual(board.usage_path(), Path("/x/u.json"))
            self.assertEqual(board.usage_path("main"), Path("/x/u.json"))
            self.assertEqual(board.usage_path("owa"), self.owa / "usage.json")
        self.write(self.owa, five=(12, 9000))
        self.assertEqual(board.read_usage("owa")["rate_limits"]["five_hour"]["used_percentage"], 12)
        self.assertIsNone(board.read_usage("main"))


class PickAccountTest(AccountEnv):
    FULL = (99, 9000)  # 1 % left, resetting in 2.5 h: usage_allowance 0

    def test_tapered_main_with_owa_clear_gives_no_taper(self):
        """Job 1130: one account near its limit never caps claims while another has room with no taper."""
        self.write(self.main, five=(91, 9000))  # fresh, 9 % left: allowance 3
        self.assertEqual(int(board.usage_allowance(board.read_usage("main"), NOW, 0)), 3)
        self.assertEqual(board.pick_account(NOW), ("main", None))
        self.assertEqual(board.pick_account(NOW, 2), ("main", None))

    def test_owa_at_reserve_with_main_full_gives_none(self):
        self.write(self.main, seven=(10, 50000))  # main resets first: order stays main, owa
        board.note_limit("main", NOW + 60)  # the primary stops only on its limit (job 1182)
        for five, seven in (((80, 9000), (10, 90000)), ((10, 9000), (90, 90000))):
            self.write(self.owa, five=five, seven=seven, written_at=NOW - 3600)  # stale: the reserve still counts
            name, allow = board.pick_account(NOW)
            self.assertEqual((name, allow), (None, 0), (five, seven))
            self.assertTrue(allow.reason.startswith("no account has room: main limited until"), allow.reason)
            self.assertIn("owa reserve", allow.reason)

    def test_primary_is_never_held_and_the_roles_flip(self):
        """Job 1139: the account whose 7d resets soonest has no reserve; the other is held at 90 %."""
        os.environ["SCRUM_ACCOUNTS"] = json.dumps([["main", str(self.main), [80, 90]], ["owa", str(self.owa), [80, 90]]])
        self.write(self.main, seven=(95, 90000))
        self.write(self.owa, seven=(95, 50000))  # owa resets first: primary, not held
        self.assertEqual(board.primary_account(NOW), "owa")
        self.assertIsNone(board.reserve_hit(board.accounts()[1], board.read_usage("owa"), NOW))
        self.assertIn("reserve 7d 95%", board.reserve_hit(board.accounts()[0], board.read_usage("main"), NOW))
        self.assertEqual(board.pick_account(NOW)[0], "owa")
        self.write(self.owa, seven=(95, 100000))  # owa now resets last: it flips to backup
        self.assertEqual(board.primary_account(NOW), "main")
        self.assertIn("reserve 7d", board.reserve_hit(board.accounts()[1], board.read_usage("owa"), NOW))

    def test_primary_never_held_by_pace_hold_or_taper(self):
        """Job 1182: the primary has no cap: pace, the 90 % hold and the taper never skip it; only its limit marker fails over."""
        with mock.patch.object(board, "PACE_LEAD_PCT", 15), mock.patch.object(board, "USAGE_HOLD_PCT", 90):
            self.write(self.main, seven=(72, 300000))  # 72 % used at 50 % elapsed: 22 points ahead of pace
            self.write(self.owa, seven=(4, 600000))
            self.assertEqual(board.pick_account(NOW), ("main", None))
            self.write(self.main, seven=(97, 300000))  # past the hold and the taper
            self.assertEqual(board.pick_account(NOW, 5), ("main", None))
            board.note_limit("main", NOW + 60)
            self.assertEqual(board.pick_account(NOW)[0], "owa")
            self.write(self.owa, seven=(90, 600000))  # the backup still stops at its 90 % reserve
            self.assertIsNone(board.pick_account(NOW)[0])

    def test_non_dict_rate_limits_never_crash_primary_or_reset(self):
        """Job 1146: a usage.json whose rate_limits is a list or string must not crash primary_account or seven_day_reset."""
        self.write(self.main, seven=(95, 90000))
        for bad in (["x"], "x", 5):
            (self.owa / "usage.json").write_text(json.dumps({"rate_limits": bad, "written_at": NOW}))
            self.assertEqual(board.primary_account(NOW), "main")
            self.assertEqual(board.seven_day_reset("owa"), "")
            self.assertEqual(board.pick_account(NOW)[0], "main")

    def test_default_reserve_holds_the_backup_at_90_seven_day_only(self):
        """Job 1139: ACCOUNTS gives main and owa the same reserve, 90 % 7d and no 5h value: a backup's 5h never holds it."""
        os.environ["SCRUM_ACCOUNTS"] = json.dumps([[n, str(d), r] for (n, _, r), d in zip(board.ACCOUNTS, (self.main, self.owa))])
        main, owa = board.accounts()
        self.write(self.main, seven=(10, 50000))  # main resets first: owa is the backup
        self.write(self.owa, five=(99, 9000), seven=(89, 90000))
        self.assertIsNone(board.reserve_hit(owa, board.read_usage("owa"), NOW))
        self.write(self.owa, seven=(90, 90000))
        self.assertEqual(board.reserve_hit(owa, board.read_usage("owa"), NOW), "reserve 7d 90% used (keeps 90%)")
        self.write(self.main, seven=(95, 95000))  # owa now resets first: primary, so main is the one held
        self.assertIsNone(board.reserve_hit(owa, board.read_usage("owa"), NOW))
        self.assertEqual(board.reserve_hit(main, board.read_usage("main"), NOW), "reserve 7d 95% used (keeps 90%)")

    def test_owa_below_reserve_with_main_full_gives_owa(self):
        self.write(self.main, five=self.FULL)
        self.write(self.owa, five=(79, 9000), seven=(89, 90000))
        self.assertEqual(board.pick_account(NOW)[0], "owa")

    def test_both_free_gives_main(self):
        self.write(self.main, five=(10, 9000))
        self.write(self.owa, five=(10, 9000))
        self.assertEqual(board.pick_account(NOW)[0], "main")

    def test_prefer_owa_with_both_free_gives_owa(self):
        self.assertEqual(board.pick_account(NOW, prefer="owa")[0], "owa")

    def test_prefer_owa_with_owa_full_gives_main(self):
        self.write(self.owa, five=self.FULL)
        self.assertEqual(board.pick_account(NOW, prefer="owa")[0], "main")

    def test_soonest_weekly_reset_first(self):
        self.write(self.main, seven=(10, 90000))
        self.write(self.owa, seven=(10, 80000))
        self.assertEqual(board.pick_account(NOW)[0], "owa")

    def test_soonest_reset_account_has_no_reserve(self):
        self.write(self.main, seven=(10, 90000))
        self.write(self.owa, seven=(95, 80000))  # job 1139: primary, so 95 % does not hold it
        self.assertEqual(board.pick_account(NOW)[0], "owa")

    def test_soonest_reset_prefer_wins(self):
        self.write(self.main, seven=(10, 90000))
        self.write(self.owa, seven=(10, 80000))
        self.assertEqual(board.pick_account(NOW, prefer="main")[0], "main")

    def test_no_weekly_window_keeps_accounts_order(self):
        read = board.read_usage
        with mock.patch.object(board, "read_usage", wraps=read) as spy:
            self.assertEqual(board.pick_account(NOW)[0], "main")
            self.assertEqual(spy.call_count, 2)
        self.write(self.main, seven=(10, -5))
        self.write(self.owa, seven=(10, -9))  # both expired
        self.assertEqual(board.pick_account(NOW)[0], "main")
        self.write(self.owa, seven=(10, 80000))  # only owa has one
        self.assertEqual(board.pick_account(NOW)[0], "owa")

    def test_limit_marker_and_reset_window(self):
        board.note_limit("main", NOW + 60)
        self.assertEqual(board.pick_account(NOW)[0], "owa")
        self.assertEqual(board.pick_account(NOW + 61)[0], "main")
        self.write(self.owa, five=(95, -10))  # the reserve window already reset: no hold
        board.note_limit("main", NOW + 60)
        self.assertEqual(board.pick_account(NOW)[0], "owa")


class LimitBoundsTest(AccountEnv):
    def test_note_limit_bounds_reset_to_8_days(self):
        now = 1_800_000_000
        with mock.patch.object(board.time, "time", return_value=now):
            board.note_limit("owa", now + 8 * 86400 + 1)
            self.assertFalse((self.owa / "limit_until").exists())
            board.note_limit("owa", now + 8 * 86400 - 1)
            self.assertEqual((self.owa / "limit_until").read_text().strip(), str(now + 8 * 86400 - 1))

    def test_pick_account_switches_back_to_main(self):
        self.assertEqual(board.pick_account(NOW)[0], "main")  # both free
        board.note_limit("main", NOW + 60)
        with mock.patch.object(board.time, "time", return_value=NOW):
            board.note_limit("main", NOW + 60)
        self.assertEqual(board.pick_account(NOW)[0], "owa")
        self.assertEqual(board.pick_account(NOW + 61)[0], "main")

    def test_unittest_refuses_real_account_dirs(self):
        home = Path(self.tmp.name) / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude-owa").mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ("SCRUM_ACCOUNTS", "SCRUM_USAGE")}
        with mock.patch.dict(os.environ, {**env, "HOME": str(home)}, clear=True):
            board.note_limit("main", time.time() + 60)
            board.note_limit("owa", time.time() + 60)
            self.assertIsNone(board.limited_until("owa", 0))
        self.assertEqual([p.name for p in home.rglob("limit_until")], [])


class FallbackAccountTest(AccountEnv):
    def test_all_limited_takes_the_soonest_reset(self):
        board.note_limit("main", NOW + 100000)
        board.note_limit("owa", NOW + 1800)
        self.assertEqual(board.fallback_account(NOW, "main"), "owa")

    def test_recorded_kept_when_tied_or_not_limited(self):
        self.assertEqual(board.fallback_account(NOW, "main"), "main")  # no marker: counts as now
        board.note_limit("main", NOW + 600)
        board.note_limit("owa", NOW + 600)
        self.assertEqual(board.fallback_account(NOW, "main"), "main")
        self.assertEqual(board.fallback_account(NOW, "owa"), "owa")


class LimitMarkerTest(AccountEnv):
    def test_limit_marker(self):
        self.assertEqual(board.limit_path("owa"), self.owa / "limit_until")
        self.assertIsNone(board.limited_until("owa", NOW))  # missing
        with mock.patch.object(board.os, "replace", wraps=os.replace) as rep:
            board.note_limit("owa", NOW + 100)
        self.assertEqual(Path(rep.call_args[0][1]), self.owa / "limit_until")
        self.assertEqual(board.limited_until("owa", NOW), NOW + 100)
        self.assertIsNone(board.limited_until("owa", NOW + 100))  # past
        self.assertIsNone(board.limited_until("main", NOW))  # per account
        (self.owa / "limit_until").write_text("soon")
        self.assertIsNone(board.limited_until("owa", NOW))  # malformed
        self.assertEqual(sorted(p.name for p in self.owa.iterdir()), ["limit_until"])  # no temp left behind


class SpawnAccountTest(AccountEnv):
    def setUp(self):
        super().setUp()
        self.root = Path(self.tmp.name) / "scrum"
        self.root.mkdir()
        self.job = board.cmd_new(self.root, "x")

    def spawn(self, job_id=None, environ=None):
        with mock.patch.object(board.subprocess, "Popen") as popen, mock.patch.dict(os.environ, environ or {}):
            board.spawn(self.root, job_id or self.job, "resume")
        return popen.call_args.kwargs["env"]

    def account(self):
        return json.loads((self.root / "board.json").read_text())["jobs"][0].get("account")

    def test_spawn_sets_config_dir_and_records_account(self):
        board.note_limit("main", int(time.time()) + 3600)
        env = self.spawn()
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.owa))
        self.assertEqual(self.account(), "owa")
        self.assertIn("runlog", json.loads((self.root / "board.json").read_text())["jobs"][0])
        env = self.spawn("run-all")  # not on the board: still starts
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.owa))

    def test_spawn_accepts_str_root(self):
        (self.root / "project.md").write_text("- Orchestrator model: sonnet\n")
        with mock.patch.object(board.subprocess, "Popen") as popen:
            _, log = board.spawn(str(self.root), self.job, "resume")
        argv = popen.call_args.args[0]
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertRegex(log, r"^runs/[0-9]{8}-[0-9]{6}-resume-" + self.job + r"\.log$")
        self.assertTrue((self.root / log).exists())

    def test_main_spawn_drops_inherited_config_dir(self):
        env = self.spawn(environ={"CLAUDE_CONFIG_DIR": str(self.owa)})
        self.assertIsNone(env.get("CLAUDE_CONFIG_DIR"))  # never assertNotIn: it would print the whole env
        self.assertEqual(self.account(), "main")

    def test_resume_keeps_recorded_account_while_it_has_room(self):
        board.cmd_set(self.root, self.job, ["account=owa"])
        self.assertEqual(self.spawn()["CLAUDE_CONFIG_DIR"], str(self.owa))
        self.assertEqual(self.account(), "owa")

    def test_recorded_account_dropped_once_its_seven_day_reset_passed(self):
        board.cmd_set(self.root, self.job, ["account=owa", f"reset={int(time.time()) + 3600}"])
        self.assertEqual(self.spawn()["CLAUDE_CONFIG_DIR"], str(self.owa))  # window still ahead: kept
        board.cmd_set(self.root, self.job, ["account=owa", f"reset={int(time.time()) - 1}"])
        self.assertIsNone(self.spawn().get("CLAUDE_CONFIG_DIR"))  # reset passed: the first pick (main)
        self.assertEqual(self.account(), "main")

    def test_spawn_falls_back_when_every_account_is_full(self):
        later = int(time.time()) + 3600
        board.note_limit("main", later)
        board.note_limit("owa", later)
        self.assertIsNone(self.spawn().get("CLAUDE_CONFIG_DIR"))  # no recorded account: the first
        self.assertEqual(self.account(), "main")
        board.cmd_set(self.root, self.job, ["account=owa"])
        self.assertEqual(self.spawn()["CLAUDE_CONFIG_DIR"], str(self.owa))  # the recorded one
        self.assertEqual(self.account(), "owa")

    def test_account_field_shape(self):
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, self.job, ["account=OWA main"])


if __name__ == "__main__":
    unittest.main()
