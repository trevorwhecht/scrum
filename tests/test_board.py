import hashlib, io, json, os, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
import board  # noqa: E402

BOARD_PY = ROOT / "skills" / "trevskills-scrum" / "board.py"


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "scrum"
        guard = mock.patch.object(board, "merge_refusal", return_value=None)  # PR-less fixture jobs may go done
        guard.start()
        self.addCleanup(guard.stop)
        usage = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(Path(self.tmp.name) / "no-usage.json")})  # no pacing
        usage.start()
        self.addCleanup(usage.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def jobs(self):
        return json.loads((self.root / "board.json").read_text())["jobs"]

    def write(self, rel, text):
        p = self.root / "jobs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # --- new ---
    def test_new_creates_job_folder_and_entry(self):
        job_id = board.cmd_new(self.root, "Add Rate Limiting!")
        self.assertEqual(job_id, "001-add-rate-limiting")
        self.assertTrue((self.root / "jobs" / job_id).is_dir())
        job = self.jobs()[0]
        self.assertEqual(job["branch"], "scrum/001-add-rate-limiting")
        self.assertEqual(job["stage"], "spec")
        self.assertEqual(job["limit"], 2)
        self.assertEqual(job["reviews"], {r: "pending" for r in board.REVIEWERS})

    def test_new_numbers_continue_past_existing_folders(self):
        (self.root / "jobs" / "007-old").mkdir(parents=True)
        self.assertTrue(board.cmd_new(self.root, "next").startswith("008-"))

    def test_new_numbers_continue_past_board_jobs_without_folders(self):
        self.root.mkdir(parents=True)
        (self.root / "board.json").write_text('{"jobs": [{"id": "004-csv-export"}]}')
        self.assertTrue(board.cmd_new(self.root, "next").startswith("005-"))

    def test_new_with_symbol_only_title_gets_fallback_slug(self):
        self.assertEqual(board.cmd_new(self.root, "!!!"), "001-job")

    def test_concurrent_new_jobs_get_unique_ids(self):
        procs = [subprocess.Popen([sys.executable, str(BOARD_PY), "--dir", str(self.root), "new", f"job {i}"],
                                  stdout=subprocess.PIPE, text=True) for i in range(8)]
        ids = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual(len(self.jobs()), 8)

    # --- set ---
    def test_set_updates_fields_and_casts_round(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=review", "round=2", "pr=https://x/1", "reason="])
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["round"], job["pr"], job["reason"]), ("review", 2, "https://x/1", None))

    def test_set_rejects_unknown_field_and_bad_stage_without_writing(self):
        job_id = board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, job_id, ["stage=review", "colour=red"])
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, job_id, ["stage=shipping"])
        self.assertEqual(self.jobs()[0]["stage"], "spec")

    def test_set_tty_term_runlog_stored(self):
        job_id = board.cmd_new(self.root, "x")
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "set", job_id,
                              "tty=ttys003", "term=Apple_Terminal", "runlog=runs/x.log"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        job = self.jobs()[0]
        self.assertEqual((job["tty"], job["term"], job["runlog"]), ("ttys003", "Apple_Terminal", "runs/x.log"))
        board.cmd_set(self.root, job_id, ["tty=", "term=", "runlog="])
        job = self.jobs()[0]
        self.assertEqual((job["tty"], job["term"], job["runlog"]), (None, None, None))

    def test_set_waiting_stored_and_cleared(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ['waiting=permission: Bash'])
        self.assertEqual(self.jobs()[0]["waiting"], "permission: Bash")
        board.cmd_set(self.root, job_id, ["waiting=  a \n <!--b-->  " + "c" * 300])
        self.assertEqual(self.jobs()[0]["waiting"], "a b " + "c" * 196)
        board.cmd_set(self.root, job_id, ["waiting="])
        self.assertIsNone(self.jobs()[0]["waiting"])

    def test_set_specwriter_field(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["specwriter=abc123"])
        self.assertEqual(self.jobs()[0]["specwriter"], "abc123")
        board.cmd_set(self.root, job_id, ["specwriter="])
        self.assertIsNone(self.jobs()[0]["specwriter"])

    def test_set_rejects_bad_tty(self):
        job_id = board.cmd_new(self.root, "x")
        before = (self.root / "board.json").read_text()
        for bad in ("tty=ttys1; rm", "tty=/dev/ttys1", "tty=??", "tty=ttys1\n", "runlog=runs/../board.json", "runlog=x.log"):
            out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "set", job_id, "stage=review", bad],
                                 capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0, bad)
            self.assertIn("bad field", out.stderr, bad)
        self.assertEqual((self.root / "board.json").read_text(), before)

    def test_set_rejects_unknown_term(self):
        job_id = board.cmd_new(self.root, "x")
        with self.assertRaisesRegex(SystemExit, "bad field"):
            board.cmd_set(self.root, job_id, ["tty=ttys2", "term=xterm"])
        self.assertNotIn("tty", self.jobs()[0])

    def test_set_lane_stored(self):
        job_id = board.cmd_new(self.root, "x")
        self.assertNotIn("lane", self.jobs()[0])  # no lane key = standard
        for lane in ("fast", "standard", "debug", "bigboy", "lilguy"):
            board.cmd_set(self.root, job_id, [f"lane={lane}"])
            self.assertEqual(self.jobs()[0]["lane"], lane)
        board.cmd_set(self.root, job_id, ["lane="])
        self.assertIsNone(self.jobs()[0]["lane"])
        (self.root / "backlog.md").write_text("- [ ] y\n")
        nxt = board.cmd_next(self.root)
        self.assertNotIn("lane", next(j for j in self.jobs() if j["id"] == nxt["id"]))

    def test_set_rejects_bad_lane_without_writing(self):
        job_id = board.cmd_new(self.root, "x")
        before = (self.root / "board.json").read_text()
        for bad in ("lane=quick", "lane=FAST", "lane=fast ", "lane=fast\n"):
            out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "set", job_id, "stage=review", bad],
                                 capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0, bad)
            self.assertIn("fast|standard|debug|bigboy", out.stderr, bad)
        self.assertEqual((self.root / "board.json").read_text(), before)

    def test_lane_accepts_bigboy_rejects_epic(self):
        job_id = board.cmd_new(self.root, "x")
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "set", job_id, "lane=bigboy"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.jobs()[0]["lane"], "bigboy")
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "set", job_id, "lane=epic"],
                             capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.jobs()[0]["lane"], "bigboy")

    # --- bigboy: plan-apply / ready ---
    @staticmethod
    def ticket(n, deps="none", parallel="yes — disjoint files", exposure="no", setup="none", title=None):
        return (f"### T{n}: {title or f'Part {n}'}\nDepends on: {deps}\nParallel: {parallel}\nExposure: {exposure}\n"
                f"Hard stops: none\nHuman setup: {setup}\nBuild part {n}.\n")

    def plan(self, *tickets, first="PLAN: READY"):
        """A bigboy parent titled Big, with plan.md holding these tickets."""
        parent = board.cmd_new(self.root, "Big")
        board.cmd_set(self.root, parent, ["lane=bigboy", "stage=plan"])
        self.write(f"{parent}/plan.md", f"{first}\n# Big\n## Goal\nShip the big thing.\n## Done when\n1. It works on main.\n"
                   "## Tickets\n" + "".join(tickets) + "## Assumptions\n- none\n")
        return parent

    def child(self, job_id):
        return next(j for j in self.jobs() if j["id"] == job_id)

    def spec(self, job_id, *paths):
        self.write(f"{job_id}/spec.md", "# x\n## Likely files\n" + "".join(f"- `{p}`: why\n" for p in paths) + "## Assumptions\n- `other/file.py`\n")

    def assert_refused(self, parent, *, fix=False):
        before = (self.root / "board.json").read_text()
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "plan-apply", parent]
                             + (["--fix"] if fix else []), capture_output=True, text=True)
        self.assertNotEqual(out.returncode, 0, out.stdout)
        self.assertEqual((self.root / "board.json").read_text(), before)
        return out.stderr

    def three(self, setup="none"):
        """T1, T2 (optional setup) independent; T3 is the exposure ticket. Children are 002, 003, 004."""
        parent = self.plan(self.ticket(1), self.ticket(2, setup=setup),
                           self.ticket(3, deps="T1, T2", parallel="no — wires both", exposure="yes"))
        return parent, board.cmd_plan_apply(self.root, parent)["children"]

    def test_plan_apply_creates_waiting_children(self):
        parent = self.plan(self.ticket(1), self.ticket(2, setup="Add STRIPE_KEY to .env"),
                           self.ticket(3, deps="T1, T2", parallel="no — wires both", exposure="yes", title="Show the button"))
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "plan-apply", parent],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"children": ["002-part-1", "003-part-2", "004-show-the-button"]})
        p = self.child("001-big")
        self.assertEqual((p["stage"], p["children"]), ("running", ["002-part-1", "003-part-2", "004-show-the-button"]))
        c1, c2, c3 = (self.child(i) for i in ("002-part-1", "003-part-2", "004-show-the-button"))
        self.assertEqual((c1["stage"], c1["parent"], c1["ticket"], c1["depends_on"], c1["parallel"], c1["setup"]),
                         ("waiting", "001-big", "T1", [], True, None))
        self.assertEqual((c2["setup"], c2["setup_text"]), ("pending", "Add STRIPE_KEY to .env"))
        self.assertEqual(c2["files"], ["feature.md"])
        self.assertEqual((c3["ticket"], c3["depends_on"], c3["parallel"]), ("T3", ["002-part-1", "003-part-2"], False))
        feature = (self.root / "jobs" / "004-show-the-button" / "feature.md").read_text()
        self.assertTrue(feature.startswith("Show the button\n\nBuild part 3.\n"), feature)
        self.assertIn("Ship the big thing.", feature)
        self.assertNotIn("Depends on:", feature)

    def test_plan_apply_rejects_ticket_count(self):
        exposure = lambda deps: self.ticket(9, deps=deps, exposure="yes")
        for tickets in ([exposure("none")], [self.ticket(n) for n in range(1, 6)] + [exposure("T1, T2, T3, T4, T5")]):
            self.tmp.cleanup()
            parent = self.plan(*tickets)
            self.assertIn("tickets", self.assert_refused(parent))
            self.assertEqual(len(self.jobs()), 1)
            self.assertEqual([p.name for p in (self.root / "jobs").iterdir()], ["001-big"])

    def test_plan_apply_rejects_not_ready(self):
        parent = self.plan(self.ticket(1), self.ticket(2, deps="T1", exposure="yes"), first="PLAN: DRAFT")
        self.assertIn("PLAN: READY", self.assert_refused(parent))

    def test_plan_apply_rejects_bad_dependencies(self):
        cases = {"unknown": [self.ticket(1, deps="T7"), self.ticket(2, deps="T1", exposure="yes")],
                 "self": [self.ticket(1, deps="T1"), self.ticket(2, deps="T1", exposure="yes")],
                 "cycle": [self.ticket(1, deps="T2"), self.ticket(2, deps="T1"), self.ticket(3, deps="T1, T2", exposure="yes")]}
        for name, tickets in cases.items():
            self.tmp.cleanup()
            self.assertIn(name, self.assert_refused(self.plan(*tickets)), name)
            self.assertEqual(len(self.jobs()), 1, name)

    def test_plan_apply_requires_exposure_last(self):
        cases = [[self.ticket(1), self.ticket(2, deps="T1")],                                          # none
                 [self.ticket(1, exposure="yes"), self.ticket(2, deps="T1", exposure="yes")],           # two
                 [self.ticket(1), self.ticket(2), self.ticket(3, deps="T1", exposure="yes")]]           # not last
        for tickets in cases:
            self.tmp.cleanup()
            self.assertIn("Exposure", self.assert_refused(self.plan(*tickets)))
            self.assertEqual(len(self.jobs()), 1)

    def test_plan_apply_twice_refused(self):
        parent, kids = self.three()
        self.assertIn("already", self.assert_refused(parent))
        self.assertEqual(len(self.jobs()), 4)

    def gaps(self, parent, fix="## Fix ticket\nWire the missing button.\n"):
        board.cmd_set(self.root, parent, ["stage=review"])
        self.write(f"{parent}/bigboy-review.md", "BIGBOY: GAPS\nThe button is missing.\n" + fix)

    def test_plan_apply_fix_adds_one_child(self):
        parent, kids = self.three()
        for k in kids:
            board.cmd_set(self.root, k, ["stage=done"])
        self.gaps(parent)
        self.assertEqual(board.cmd_plan_apply(self.root, parent, fix=True), {"children": ["005-fix-big"]})
        fix = self.child("005-fix-big")
        self.assertEqual((fix["stage"], fix["ticket"], fix["depends_on"], fix["parent"], fix["setup"]),
                         ("waiting", "FIX", [], "001-big", None))
        p = self.child(parent)
        self.assertEqual((p["stage"], p["children"]), ("running", kids + ["005-fix-big"]))
        self.assertIn("Wire the missing button.", (self.root / "jobs" / "005-fix-big" / "feature.md").read_text())
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], ["005-fix-big"])

    def test_plan_apply_fix_refused_twice(self):
        parent, kids = self.three()
        self.gaps(parent, fix="")
        self.assertIn("Fix ticket", self.assert_refused(parent, fix=True))
        self.gaps(parent)
        board.cmd_plan_apply(self.root, parent, fix=True)
        self.gaps(parent)
        self.assertIn("already", self.assert_refused(parent, fix=True))
        self.assertEqual(len(self.jobs()), 5)

    def test_ready_waits_for_dependencies(self):
        parent = self.plan(self.ticket(1), self.ticket(2, deps="T1"), self.ticket(3, deps="T1, T2", exposure="yes"))
        c1, c2, c3 = board.cmd_plan_apply(self.root, parent)["children"]
        self.assertEqual(board.cmd_ready(self.root, parent),
                         {"ready": [c1], "merged": 0, "total": 3, "in_progress": 1, "all_merged": False})
        self.assertEqual(self.child(c1)["stage"], "spec")
        board.cmd_set(self.root, c1, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c2])
        board.cmd_set(self.root, c2, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c3])
        board.cmd_set(self.root, c3, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent),
                         {"ready": [], "merged": 3, "total": 3, "in_progress": 0, "all_merged": True})
        self.assertEqual(self.child(parent)["stage"], "running")

    def test_ready_claims_once(self):
        parent, (c1, c2, c3) = self.three()
        self.spec(c1, "src/a.py")
        self.spec(c2, "src/b.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1, c2])
        again = board.cmd_ready(self.root, parent)
        self.assertEqual((again["ready"], again["in_progress"]), ([], 2))
        self.assertEqual([self.child(c)["stage"] for c in (c1, c2, c3)], ["spec", "spec", "waiting"])

    def test_ready_skips_pending_setup(self):
        parent, (c1, c2, c3) = self.three(setup="Create the S3 bucket")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1])
        board.cmd_set(self.root, c1, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        board.cmd_set(self.root, c2, ["setup=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c2])

    def test_ready_serializes_overlapping_likely_files(self):
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3), self.ticket(4, deps="T1, T2, T3", exposure="yes"))
        c1, c2, c3, c4 = board.cmd_plan_apply(self.root, parent)["children"]
        self.spec(c1, "src/a.py", "src/b.py")
        self.spec(c2, "src/b.py")
        self.spec(c3, "src/c.py")  # `other/file.py` sits outside Likely files in every spec, so it never counts
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1, c3])
        board.cmd_set(self.root, c1, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c2])
        # A parallel=no child starts only when no sibling is in progress.
        parent = self.plan(self.ticket(1), self.ticket(2, parallel="no — touches everything"), self.ticket(3, deps="T1, T2", exposure="yes"))
        d1, d2, _ = board.cmd_plan_apply(self.root, parent)["children"]
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d1])
        board.cmd_set(self.root, d1, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d2])

    def test_ready_unknown_likely_files_runs_alone(self):
        # T2 has no spec, then a Likely files section holding only a non-path token: both mean "files unknown".
        for unknown in (None, "# x\n## Likely files\n- `cmd_ready(root)`: the scheduler\n## Assumptions\n- `src/z.py`\n"):
            parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3, deps="T1, T2", exposure="yes"))
            c1, c2, _ = board.cmd_plan_apply(self.root, parent)["children"]
            self.spec(c1, "src/a.py")
            if unknown:
                self.write(f"{c2}/spec.md", unknown)
            self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1], unknown)
            board.cmd_set(self.root, c1, ["stage=done"])
            self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c2], unknown)
        # Reversed: the spec-less child is claimed first, and a disjoint sibling waits until it is done.
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3, deps="T1, T2", exposure="yes"))
        d1, d2, _ = board.cmd_plan_apply(self.root, parent)["children"]
        self.spec(d2, "src/c.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d1])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        board.cmd_set(self.root, d1, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d2])

    def test_chain_lock_acquire_wait_reenter_stale(self):
        parent, _ = self.three()
        lock = self.root / "jobs" / parent / ".chain.lock"
        self.assertEqual(board.CHAIN_LOCK_STALE, 1800)
        self.assertEqual(board.cmd_chain_lock(self.root, parent, "002-part-1"), {"acquired": True, "holder": "002-part-1"})
        self.assertIn("002-part-1", lock.read_text())
        self.assertEqual(board.cmd_chain_lock(self.root, parent, "003-part-2", wait=0),
                         {"acquired": False, "holder": "002-part-1"})
        old = lock.stat().st_mtime - 1000
        os.utime(lock, (old, old))
        self.assertEqual(board.cmd_chain_lock(self.root, parent, "002-part-1", wait=0), {"acquired": True, "holder": "002-part-1"})
        self.assertGreater(lock.stat().st_mtime, old + 900)  # re-acquiring refreshed it
        stale = lock.stat().st_mtime - 1801
        os.utime(lock, (stale, stale))
        self.assertEqual(board.cmd_chain_lock(self.root, parent, "003-part-2", wait=0), {"acquired": True, "holder": "003-part-2"})
        self.assertIn("003-part-2", lock.read_text())
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "chain-lock", parent, "002-part-1",
                              "--wait", "0"], capture_output=True, text=True)
        self.assertEqual((out.returncode, json.loads(out.stdout)), (0, {"acquired": False, "holder": "003-part-2"}))

    def test_chain_unlock_only_by_holder(self):
        parent, _ = self.three()
        lock = self.root / "jobs" / parent / ".chain.lock"
        self.assertEqual(board.cmd_chain_unlock(self.root, parent, "002-part-1"), {"released": False})
        board.cmd_chain_lock(self.root, parent, "002-part-1")
        self.assertEqual(board.cmd_chain_unlock(self.root, parent, "003-part-2"), {"released": False})
        self.assertTrue(lock.exists())
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "chain-unlock", parent, "002-part-1"],
                             capture_output=True, text=True)
        self.assertEqual((out.returncode, json.loads(out.stdout)), (0, {"released": True}))
        self.assertFalse(lock.exists())
        self.assertEqual(board.cmd_chain_lock(self.root, parent, "003-part-2", wait=0)["acquired"], True)

    def test_likely_files_reads_only_that_section(self):
        text = "## Problem\n`a/x.py`\n## Likely files\n- `skills/board.py`: `SHAPES[\"lane\"]` and `cmd_ready(root)`\n- `tests/t.py`\n## Assumptions\n- `b/y.py`\n"
        self.assertEqual(board.likely_files(text), {"skills/board.py", "tests/t.py"})
        self.assertEqual(board.likely_files("# no section\n"), set())

    def five(self):
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3, deps="T1"), self.ticket(4, deps="T2"),
                           self.ticket(5, deps="T1, T2, T3, T4", exposure="yes"))
        return parent, board.cmd_plan_apply(self.root, parent)["children"]

    def test_ready_failed_child_blocks_only_dependents(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        for k in (c1, c2, c4):
            self.spec(k, f"src/{k}.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1, c2])
        board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_set(self.root, c2, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c4])
        self.assertEqual((self.child(parent)["stage"], self.child(c3)["stage"]), ("running", "waiting"))

    def test_ready_marks_parent_blocked(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_abort(self.root, c2, requeue=False)
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"], out["all_merged"]), ([], 0, False))
        p = self.child(parent)  # a needs-human child is actionable, so the parent keeps running
        self.assertEqual((p["stage"], p["reason"]), ("running", f"waiting on you in: {c1}"))
        board.cmd_set(self.root, c1, ["stage=done", "reason="])  # Trevor approved it and it merged
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c3])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_bigboy_aborted_child_blocks_with_resume(self):
        # Blocked: c2 aborted, and waiting c4 (and c5 through c4) depend on it; nothing else to act on.
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=done"])
        board.cmd_abort(self.root, c2, requeue=False)
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c3, ["stage=done"])
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"], out["all_merged"]), ([], 0, False))
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("needs-human", "bigboy blocked: 003-part-2. Fix: click Resume to "
                         "skip the children that depend on them and run the final review."))
        self.assertNotIn("Abort", p["reason"])
        # Resume aborts the waiting dependents; every child is then done or aborted, so all_merged is true.
        board.cmd_abort(self.root, c4, requeue=False)
        board.cmd_abort(self.root, c5, requeue=False)
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "ready", parent],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual((json.loads(out.stdout)["all_merged"], json.loads(out.stdout)["merged"]), (True, 2))
        # One aborted child plus one needs-human child: the parent keeps running and names the needs-human one.
        parent, (d1, d2, d3, d4, d5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_abort(self.root, d1, requeue=False)
        board.cmd_set(self.root, d2, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        with mock.patch.object(board, "play") as play:
            board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", f"waiting on you in: {d2}"))
        play.assert_not_called()

    def test_ready_parent_waits_on_needs_human_children(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c2, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        with mock.patch.object(board, "play") as play:
            out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"], out["all_merged"]), ([], 0, False))
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", "waiting on you in: 002-part-1, 003-part-2"))
        play.assert_not_called()

    def test_ready_parent_waits_on_setup_children(self):
        parent, (c1, c2, c3) = self.three(setup="Create the S3 bucket")
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=done"])
        with mock.patch.object(board, "play") as play:
            self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", "waiting on you in: 003-part-2"))
        play.assert_not_called()

    def test_ready_clears_waiting_note(self):
        parent, (c1, c2, c3) = self.three(setup="Create the S3 bucket")
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=done"])
        board.cmd_ready(self.root, parent)
        self.assertEqual(self.child(parent)["reason"], "waiting on you in: 003-part-2")
        board.cmd_set(self.root, c2, ["setup=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c2])  # a claim clears it
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))
        parent, (d1, d2, d3, d4, d5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, d1, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_set(self.root, d2, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_ready(self.root, parent)
        self.assertEqual(self.child(parent)["reason"], f"waiting on you in: {d1}, {d2}")
        board.cmd_set(self.root, d2, ["stage=build", "reason="])  # Send back to builder: in progress, nothing new ready
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_ready_recovers_legacy_blocked_parent(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_set(self.root, c2, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_set(self.root, parent, ["stage=needs-human", f"reason=bigboy blocked: {c1}, {c2}. Fix: y"])
        with mock.patch.object(board, "play") as play:
            board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", "waiting on you in: 002-part-1, 003-part-2"))
        play.assert_not_called()
        board.cmd_set(self.root, parent, ["stage=needs-human", "reason=bigboy blocked: old. Fix: y"])
        board.cmd_set(self.root, c1, ["stage=build", "reason="])
        board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))
        rparent, (a, b) = self.runall(2)
        board.cmd_ready(self.root, rparent)
        board.cmd_set(self.root, rparent, ["stage=needs-human", "reason=run-all blocked: x. Fix: y"])
        board.cmd_ready(self.root, rparent)  # a is in progress
        p = self.child(rparent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_ready_leaves_other_parent_stops_alone(self):
        parent, kids = self.three()
        board.cmd_set(self.root, parent, ["stage=needs-human", "reason=bigboy off track: x. Fix: y"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("needs-human", "bigboy off track: x. Fix: y"))
        self.assertEqual([self.child(k)["stage"] for k in kids], ["waiting"] * 3)

    def test_ready_recovers_chain_lock_parent(self):
        parent, (c1, c2, c3) = self.three()
        board.cmd_set(self.root, parent, ["stage=needs-human", "reason=bigboy chain lock held by 005-x. Fix: wait, "
                                          "or clear the lock and click Run now on a waiting child."])
        with mock.patch.object(board, "play") as play:
            out = board.cmd_ready(self.root, parent)
        self.assertEqual(out["ready"], ["002-part-1"])
        self.assertEqual(self.child(c1)["stage"], "spec")
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))
        play.assert_not_called()

    def test_ready_never_writes_empty_waiting_list(self):
        parent, (c1, c2, c3) = self.three()
        board.cmd_set(self.root, c1, ["stage=done"])
        board.cmd_set(self.root, c2, ["stage=done"])
        data = json.loads((self.root / "board.json").read_text())
        next(j for j in data["jobs"] if j["id"] == c3)["depends_on"] = ["099-not-a-sibling"]
        (self.root / "board.json").write_text(json.dumps(data))
        with mock.patch.object(board, "play"):
            self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertNotEqual(p["reason"], "waiting on you in: ")
        self.assertEqual((p["stage"], p["reason"]), ("needs-human", "bigboy blocked: 004-part-3. Fix: check each "
                         "listed child's Depends on, then click Run now on a waiting child."))
        board.cmd_set(self.root, c3, ["stage=build"])
        board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_stage_sounds(self):
        clip = "/clips/needs-human"
        with mock.patch.object(board, "play") as play, mock.patch.object(board, "sound", lambda kind: f"/clips/{kind}"):
            job = board.cmd_new(self.root, "noisy")
            board.cmd_set(self.root, job, ["stage=build"])
            play.assert_not_called()
            board.cmd_set(self.root, job, ["stage=needs-human", "reason=x"])
            play.assert_called_once_with(clip)
            play.reset_mock()
            board.cmd_set(self.root, job, ["stage=needs-human"])  # already there: no sound
            play.assert_not_called()
            board.cmd_set(self.root, job, ["stage=done"])
            play.assert_called_once_with("/clips/done")
            play.reset_mock()
            board.cmd_set(self.root, job, ["stage=done"])
            play.assert_not_called()
            parent, (c1, c2, c3, c4, c5) = self.five()
            board.cmd_ready(self.root, parent)
            board.cmd_abort(self.root, c1, requeue=False)
            board.cmd_abort(self.root, c2, requeue=False)
            play.reset_mock()
            board.cmd_ready(self.root, parent)
            self.assertEqual(self.child(parent)["stage"], "needs-human")
            play.assert_called_once_with(clip)
        with mock.patch.object(board.subprocess, "Popen", side_effect=FileNotFoundError("afplay")):
            with mock.patch.dict(os.environ, {"SCRUM_MUTE": ""}):
                board.cmd_set(self.root, job, ["stage=build"])
                board.cmd_set(self.root, job, ["stage=done"])
        self.assertEqual(self.child(job)["stage"], "done")
        seen = []  # the sound starts after the board is written and the lock released
        with mock.patch.object(board, "play", lambda p: seen.append(self.child(job)["stage"])):
            board.cmd_set(self.root, job, ["stage=needs-human"])
        self.assertEqual(seen, ["needs-human"])

    def test_play_is_detached_and_muted_by_env(self):
        with mock.patch.object(board.subprocess, "Popen") as popen:
            board.play("/x.aiff")
            popen.assert_not_called()
            with mock.patch.dict(os.environ, {"SCRUM_MUTE": ""}):
                board.play("/x.aiff")
        popen.assert_called_once_with(["afplay", "/x.aiff"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, start_new_session=True)

    def test_needs_human_sound_fallback(self):  # covers every scrum sound: a clip when present, else its system sound
        home = Path(self.tmp.name) / "home"
        sounds = home / ".claude" / "trevskills-scrum" / "sounds"
        cases = {"done": ("done.mp3", "/System/Library/Sounds/Blow.aiff"),
                 "needs-human": ("needs-human.mp3", "/System/Library/Sounds/Morse.aiff"),
                 "question": ("question.mp3", "/System/Library/Sounds/Funk.aiff")}
        with mock.patch.object(board.Path, "home", return_value=home), mock.patch.dict(os.environ, {"HOME": str(home)}):
            for kind, (name, fallback) in cases.items():
                clip = sounds / name
                self.assertEqual(board.sound(kind), fallback, kind)
                clip.mkdir(parents=True)
                self.assertEqual(board.sound(kind), fallback, kind)
                clip.rmdir()
                clip.write_bytes(b"ID3")
                self.assertEqual(board.sound(kind), str(clip), kind)
                self.assertEqual([board.sound(k) for k in cases if k != kind], [cases[k][1] for k in cases if k != kind])
                clip.unlink()
                self.assertEqual(board.sound(kind), fallback, kind)

    def test_next_skips_bigboy_children(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Dark mode\n")
        parent, kids = self.three()
        self.assertEqual(board.cmd_next(self.root), {"id": "005-dark-mode", "feature": "Dark mode"})
        self.assertEqual(board.cmd_next(self.root), {"id": None, "feature": None})
        self.assertEqual([self.child(k)["stage"] for k in kids], ["waiting"] * 3)
        self.assertEqual(self.child(parent)["stage"], "running")

    # --- run all: runall-start / ready ---
    def test_lane_accepts_runall(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["lane=runall"])
        self.assertEqual(self.jobs()[0]["lane"], "runall")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, job_id, ["lane=epic"])
        self.assertEqual(self.jobs()[0]["lane"], "runall")

    def test_runall_start_without_open_items_creates_nothing(self):
        for backlog in (None, "# Backlog\n- [x] old → 001-old\n", "# Backlog\n## Later\n"):
            self.tmp.cleanup()
            self.root.mkdir(parents=True)
            if backlog is not None:
                (self.root / "backlog.md").write_text(backlog)
            self.assertEqual(board.cmd_runall_start(self.root), {"id": None, "children": []})
            self.assertFalse((self.root / "jobs").exists() and any((self.root / "jobs").iterdir()), backlog)
            self.assertEqual(self.jobs() if (self.root / "board.json").exists() else [], [], backlog)

    def test_runall_start_claims_every_open_item(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] [3] Add CSV export <!-- small -->\n"
                                              "- [x] Old thing → 009-old\n- [ ] Dark mode\n")
        out = board.cmd_runall_start(self.root)
        self.assertEqual(out, {"id": "001-run-all", "children": ["002-add-csv-export", "003-dark-mode"]})
        p = self.child("001-run-all")
        self.assertEqual((p["title"], p["lane"], p["stage"], p["children"]),
                         ("Run all", "runall", "running", ["002-add-csv-export", "003-dark-mode"]))
        for kid, text in (("002-add-csv-export", "Add CSV export"), ("003-dark-mode", "Dark mode")):
            c = self.child(kid)
            self.assertEqual((c["stage"], c["parent"], c["depends_on"], c["parallel"]), ("waiting", "001-run-all", [], True))
            self.assertEqual((self.root / "jobs" / kid / "feature.md").read_text(), text + "\n")
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [x] [3] Add CSV export → 002-add-csv-export <!-- small -->\n"
                         "- [x] Old thing → 009-old\n- [x] Dark mode → 003-dark-mode\n")

    def test_runall_start_moves_prewritten_specs(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Add CSV export\n- [ ] Dark mode\n")
        specs = self.root / "backlog-specs"
        specs.mkdir()
        spec = specs / (hashlib.sha1(b"Dark mode").hexdigest()[:12] + ".md")
        spec.write_text("# Dark mode\nbody\n")
        out = board.cmd_runall_start(self.root)
        self.assertEqual(out["children"], ["002-add-csv-export", "003-dark-mode"])
        self.assertEqual((self.root / "jobs" / "003-dark-mode" / "spec.md").read_text(), "# Dark mode\nbody\n")
        self.assertFalse(spec.exists())
        self.assertFalse((self.root / "jobs" / "002-add-csv-export" / "spec.md").exists())

    # --- cloud-claim ---
    def cloud_backlog(self, specs):
        """backlog.md with one open item per (text, likely files) pair; files None = no backlog-specs file."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "backlog.md").write_text("# Backlog\n" + "".join(f"- [ ] {t}\n" for t, _ in specs))
        (self.root / "backlog-specs").mkdir(exist_ok=True)
        for text, files in specs:
            if files is not None:
                self.spec_file(text).write_text(
                    f"# {text}\n\n## Likely files\n" + "".join(f"- `{f}`: edit\n" for f in files))

    def spec_file(self, text):
        return self.root / "backlog-specs" / (hashlib.sha1(text.encode()).hexdigest()[:12] + ".md")

    def in_flight(self, job_id, stage, files):
        """A board job in `stage`; files None = no jobs/<id>/spec.md."""
        board_path = self.root / "board.json"
        data = json.loads(board_path.read_text()) if board_path.exists() else {"jobs": []}
        data["jobs"].append({"id": job_id, "title": job_id, "stage": stage})
        board_path.write_text(json.dumps(data))
        (self.root / "jobs" / job_id).mkdir(parents=True)
        if files is not None:
            self.write(f"{job_id}/spec.md", "# x\n\n## Likely files\n" + "".join(f"- `{f}`\n" for f in files))

    def test_cloud_claim_claims_up_to_n_disjoint_items(self):
        self.cloud_backlog([("Alpha", ["a.py"]), ("Beta", ["b.py"]), ("Gamma", ["c.py"])])
        out = board.cmd_cloud_claim(self.root, 2)
        self.assertEqual(out, {"claimed": [{"id": "001-alpha", "feature": "Alpha"}, {"id": "002-beta", "feature": "Beta"}]})
        self.assertEqual((self.root / "jobs" / "001-alpha" / "spec.md").read_text(),
                         "# Alpha\n\n## Likely files\n- `a.py`: edit\n")
        self.assertTrue((self.root / "jobs" / "002-beta" / "spec.md").is_file())
        self.assertFalse(self.spec_file("Alpha").exists())
        self.assertTrue(self.spec_file("Gamma").exists())
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [x] Alpha → 001-alpha\n- [x] Beta → 002-beta\n- [ ] Gamma\n")
        self.assertEqual([(j["id"], j["stage"]) for j in self.jobs()], [("001-alpha", "spec"), ("002-beta", "spec")])

    def test_cloud_claim_cuts_title_to_60_and_skips_waiting_items(self):
        long = "L" * 70
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text(f"# Backlog\n- [ ] Blocked {{needs #aaaa}}\n- [ ] Pre {{#aaaa}}\n- [ ] {long}\n")
        (self.root / "backlog-specs").mkdir()
        for t, f in (("Blocked", "z.py"), ("Pre", "p.py"), (long, "l.py")):
            self.spec_file(t).write_text(f"## Likely files\n- `{f}`\n")
        out = board.cmd_cloud_claim(self.root, 5)
        self.assertEqual([c["feature"] for c in out["claimed"]], ["Pre", long])
        self.assertEqual(self.jobs()[1]["title"], "L" * 60)
        self.assertTrue((self.root / "backlog.md").read_text().startswith("# Backlog\n- [ ] Blocked {needs #aaaa}\n"))

    def test_cloud_claim_skips_item_overlapping_earlier_pick(self):
        self.cloud_backlog([("A", ["a.py"]), ("B", ["a.py", "b.py"]), ("C", ["c.py"])])
        out = board.cmd_cloud_claim(self.root, 3)
        self.assertEqual(out, {"claimed": [{"id": "001-a", "feature": "A"}, {"id": "002-c", "feature": "C"}]})
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [x] A → 001-a\n- [ ] B\n- [x] C → 002-c\n")
        self.assertTrue(self.spec_file("B").exists())

    def test_cloud_claim_skips_items_without_spec(self):
        self.cloud_backlog([("Nospec", None), ("Empty", []), ("Good", ["g.py"])])
        out = board.cmd_cloud_claim(self.root, 3)
        self.assertEqual(out, {"claimed": [{"id": "001-good", "feature": "Good"}]})
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [ ] Nospec\n- [ ] Empty\n- [x] Good → 001-good\n")
        self.assertTrue(self.spec_file("Empty").exists())

    def test_cloud_claim_respects_in_flight_jobs(self):
        self.cloud_backlog([("X item", ["x.py"]), ("Y item", ["y.py"])])
        self.in_flight("010-cloudy", "cloud", ["x.py"])
        self.in_flight("011-reviewing", "review", ["y.py"])
        out = board.cmd_cloud_claim(self.root, 2)
        self.assertEqual(out, {"claimed": [{"id": "012-y-item", "feature": "Y item"}]})
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [ ] X item\n- [x] Y item → 012-y-item\n")

    def test_cloud_claim_in_flight_job_without_spec_blocks_all(self):
        self.cloud_backlog([("X item", ["x.py"]), ("Y item", ["y.py"])])
        self.in_flight("010-building", "build", None)
        before = (self.root / "backlog.md").read_text()
        self.assertEqual(board.cmd_cloud_claim(self.root, 2), {"claimed": []})
        self.assertEqual((self.root / "backlog.md").read_text(), before)

    def test_cloud_claim_rejects_n_below_one(self):
        self.cloud_backlog([("A", ["a.py"])])
        before = (self.root / "backlog.md").read_bytes()
        for n in ("0", "-1"):
            out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "cloud-claim", n],
                                 capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("N must be at least 1", out.stderr)
            self.assertEqual((self.root / "backlog.md").read_bytes(), before)
        self.assertFalse((self.root / "jobs").exists())

    def test_cloud_claim_cli_prints_json(self):
        self.cloud_backlog([("A", ["a.py"])])
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "cloud-claim", "4"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"claimed": [{"id": "001-a", "feature": "A"}]})

    def test_runall_start_maps_needs_to_depends_on(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] Add UI {needs #api1 #sch2}\n- [ ] Add API {#api1} {needs #sch2}\n- [ ] Add schema {#sch2}\n"
            "- [ ] Docs {needs #zzzz}\n")
        out = board.cmd_runall_start(self.root)
        self.assertEqual(out, {"id": "001-run-all",
                               "children": ["002-add-ui", "003-add-api", "004-add-schema", "005-docs"]})
        self.assertEqual(self.child("002-add-ui")["depends_on"], ["003-add-api", "004-add-schema"])
        self.assertEqual(self.child("003-add-api")["depends_on"], ["004-add-schema"])
        self.assertEqual(self.child("004-add-schema")["depends_on"], [])
        self.assertEqual(self.child("005-docs")["depends_on"], [])
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [x] Add UI {needs #api1 #sch2} → 002-add-ui\n"
                         "- [x] Add API {#api1} {needs #sch2} → 003-add-api\n- [x] Add schema {#sch2} → 004-add-schema\n"
                         "- [x] Docs {needs #zzzz} → 005-docs\n")

    def test_runall_start_leaves_items_waiting_on_outside_job_open(self):
        self.root.mkdir(parents=True)
        outside = board.cmd_new(self.root, "Outside")  # 001-outside, stage spec
        finished = board.cmd_new(self.root, "Finished")  # 002-finished
        board.cmd_set(self.root, finished, ["stage=done"])
        backlog = (f"# Backlog\n- [x] Outside {{#out1}} → {outside}\n- [x] Finished {{#fin2}} → {finished}\n"
                   "- [ ] Blocked {#blk3} {needs #out1}\n- [ ] Chained {needs #blk3}\n- [ ] Free {needs #fin2}\n")
        (self.root / "backlog.md").write_text(backlog)
        out = board.cmd_runall_start(self.root)
        self.assertEqual(out, {"id": "003-run-all", "children": ["004-free"]})
        self.assertEqual(self.child("004-free")["depends_on"], [])
        self.assertEqual((self.root / "backlog.md").read_text(),
                         f"# Backlog\n- [x] Outside {{#out1}} → {outside}\n- [x] Finished {{#fin2}} → {finished}\n"
                         "- [ ] Blocked {#blk3} {needs #out1}\n- [ ] Chained {needs #blk3}\n"
                         "- [x] Free {needs #fin2} → 004-free\n")
        # every open item held back: no parent
        jobs = len(self.jobs())
        self.assertEqual(board.cmd_runall_start(self.root), {"id": None, "children": []})
        self.assertEqual(len(self.jobs()), jobs)

    def test_ready_holds_dependent_runall_child(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Second {needs #aaaa}\n- [ ] First {#aaaa}\n")
        out = board.cmd_runall_start(self.root)
        parent, (second, first) = out["id"], out["children"]
        self.spec(second, "src/second.py")
        self.spec(first, "src/first.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [first])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        board.cmd_set(self.root, first, ["stage=review"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        board.cmd_set(self.root, first, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [second])

    def runall(self, n):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "backlog.md").write_text("".join(f"- [ ] item {chr(97 + i)}\n" for i in range(n)))
        out = board.cmd_runall_start(self.root)
        return out["id"], out["children"]

    def test_runall_ready_disjoint_parallel_shared_serial(self):
        parent, (a, b, c) = self.runall(3)
        self.spec(a, "src/a.py", "src/b.py")
        self.spec(b, "src/b.py")
        self.spec(c, "src/c.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [a, c])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        board.cmd_set(self.root, a, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [b])

    def test_runall_ready_caps_in_progress_at_three(self):
        self.assertEqual(board.RUNALL_MAX_IN_PROGRESS, 3)
        parent, kids = self.runall(5)
        for i, k in enumerate(kids):
            self.spec(k, f"src/{i}.py")
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), (kids[:3], 3))
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        board.cmd_set(self.root, kids[0], ["stage=done"])
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), ([kids[3]], 3))
        # A spec-less Run-all child starts only alone.
        parent, (a, b) = self.runall(2)
        self.spec(b, "src/b.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [a])
        board.cmd_set(self.root, a, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [b])

    def test_runall_ready_aborted_counts_as_finished(self):
        parent, (a, b, c) = self.runall(3)
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, a, ["stage=done"])
        board.cmd_set(self.root, b, ["stage=done"])
        board.cmd_abort(self.root, c, requeue=False)
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["merged"], out["total"], out["in_progress"], out["all_merged"]), (2, 3, 0, True))
        self.assertEqual(self.child(parent)["stage"], "running")

    def test_runall_ready_parent_waits_and_resumes(self):
        parent, (a, b, c) = self.runall(3)
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, a, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_abort(self.root, b, requeue=False)
        board.cmd_set(self.root, c, ["stage=done"])
        with mock.patch.object(board, "play") as play:
            out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"], out["all_merged"]), ([], 0, False))
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", f"waiting on you in: {a}"))
        play.assert_not_called()
        board.cmd_set(self.root, a, ["stage=done", "reason="])
        self.assertTrue(board.cmd_ready(self.root, parent)["all_merged"])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_bigboy_ready_unchanged_by_runall(self):
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3), self.ticket(4),
                           self.ticket(5, deps="T1, T2, T3, T4", exposure="yes"))
        c1, c2, c3, c4, c5 = board.cmd_plan_apply(self.root, parent)["children"]
        for k in (c1, c2, c3, c4):
            self.spec(k, f"src/{k}.py")
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), ([c1, c2, c3, c4], 4))
        for k in (c1, c2, c3):
            board.cmd_set(self.root, k, ["stage=done"])
        board.cmd_abort(self.root, c4, requeue=False)
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["merged"], out["all_merged"]), (3, False))
        self.assertTrue(self.child(parent)["reason"].startswith(f"bigboy blocked: {c4}. Fix: "))

    def test_cli_runall_start(self):
        run = lambda *a: subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), *a],
                                        capture_output=True, text=True)
        self.assertIn("runall-start", run("--help").stdout)
        out = run("runall-start")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"id": None, "children": []})
        (self.root / "backlog.md").write_text("- [ ] Dark mode\n")
        out = run("runall-start")
        self.assertEqual(json.loads(out.stdout), {"id": "001-run-all", "children": ["002-dark-mode"]})

    def test_diverged_reads_plan_md(self):
        parent, _ = self.three()
        board.cmd_set(self.root, parent, ["stage=running"])
        self.assertIs(self.child(parent)["diverged"], False)
        with open(self.root / "jobs" / parent / "plan.md", "a") as f:
            f.write("## Diverged\n- T3 said X → tracker narrowed it to Y — T1 already did X\n")
        board.cmd_set(self.root, parent, ["stage=running"])
        self.assertIs(self.child(parent)["diverged"], True)

    def test_set_unknown_job_fails(self):
        board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, "999-nope", ["stage=done"])

    def test_rejects_path_traversal_id(self):
        board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_sync(self.root, "../../etc")

    def test_corrupt_board_is_not_overwritten(self):
        job_id = board.cmd_new(self.root, "x")
        (self.root / "board.json").write_text("{not json")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, job_id, ["stage=done"])
        self.assertEqual((self.root / "board.json").read_text(), "{not json")

    # --- first_word ---
    def test_first_word_tolerates_decoration(self):
        allowed = ("PASS", "CHANGES")
        for text in ["VERDICT: PASS\n", "**VERDICT: PASS**", "# Verdict: pass", "\n\n  verdict:PASS — fine",
                     "﻿VERDICT: CHANGES"]:
            p = self.write("t/r.md", text)
            self.assertIn(board.first_word(p, allowed), allowed, text)

    def test_first_word_garbage_is_invalid_not_pass(self):
        p = self.write("t/r.md", "Looks good to me!\nVERDICT: PASS")
        self.assertEqual(board.first_word(p, ("PASS", "CHANGES")), "INVALID")
        p = self.write("t/e.md", "")
        self.assertEqual(board.first_word(p, ("PASS", "CHANGES")), "INVALID")

    def test_first_word_missing_file_is_none(self):
        self.assertIsNone(board.first_word(self.root / "nope.md", ("PASS",)))

    # --- sync ---
    def test_sync_incomplete_round_is_not_complete(self):
        job_id = board.cmd_new(self.root, "x")
        self.write(f"{job_id}/spec.md", "# spec")
        self.write(f"{job_id}/round-1/check.md", "CHECK: PASS")
        self.write(f"{job_id}/round-1/review-security.md", "VERDICT: PASS")
        self.write(f"{job_id}/round-1/review-ux.md", "VERDICT: CHANGES")
        status = board.cmd_sync(self.root, job_id)
        self.assertEqual(status["round"], 1)
        self.assertFalse(status["complete"])
        self.assertIsNone(status["verdict"])
        self.assertEqual(status["check"], "PASS")
        self.assertEqual(status["missing"], ["review-ui.md", "review-code.md"])
        job = self.jobs()[0]
        self.assertEqual(job["reviews"], {"security": "PASS", "ux": "CHANGES", "ui": "pending", "code": "pending"})
        self.assertIn("round-1/review-ux.md", job["files"])
        self.assertIn("spec.md", job["files"])

    def test_set_refreshes_files_from_job_folder(self):
        job_id = board.cmd_new(self.root, "x")
        self.write(f"{job_id}/spec.md", "# spec")
        self.write(f"{job_id}/feature.md", "x")
        board.cmd_set(self.root, job_id, ["stage=needs-human", "reason=obsolete: done"])
        self.assertEqual(self.jobs()[0]["files"], ["feature.md", "spec.md"])
        (self.root / "jobs" / job_id / "spec.md").unlink()
        (self.root / "jobs" / job_id / "feature.md").unlink()
        (self.root / "jobs" / job_id).rmdir()
        board.cmd_set(self.root, job_id, ["stage=needs-human"])  # missing folder: still succeeds
        self.assertEqual(self.jobs()[0]["files"], [])

    def test_diverged_flag_set_and_cleared(self):
        job_id = board.cmd_new(self.root, "x")
        self.write(f"{job_id}/spec.md", "# spec\n## Diverged\n- feature said X → did Y — because Z\n## Next\n")
        board.cmd_set(self.root, job_id, ["stage=build"])
        self.assertIs(self.jobs()[0]["diverged"], True)
        self.write(f"{job_id}/spec.md", "# spec\n")
        self.write(f"{job_id}/build.md", "STATUS: READY\n## Summary\n## Diverged\n- spec said A → did B — why\n")
        board.cmd_sync(self.root, job_id)
        self.assertIs(self.jobs()[0]["diverged"], True)
        self.write(f"{job_id}/build.md", "STATUS: READY\n## Summary\n")
        board.cmd_set(self.root, job_id, ["stage=check"])
        self.assertIs(self.jobs()[0]["diverged"], False)

    def test_diverged_edge_cases_false(self):
        job_id = board.cmd_new(self.root, "x")
        for text in ("## Diverged\n", "## Diverged\n\n## Next\n- not this\n", "## Diverged\n- none\n",
                     "## Diverged\n- None\n## Summary\n", "### Diverged\n- a\n", "## Diverged notes\n- a\n"):
            self.write(f"{job_id}/build.md", text)
            board.cmd_set(self.root, job_id, ["stage=build"])
            self.assertIs(self.jobs()[0]["diverged"], False, text)
        (self.root / "jobs" / job_id / "build.md").unlink()
        self.write(f"{job_id}/round-1/review-code.md", "VERDICT: PASS\n## Diverged\n- a\n")
        self.write(f"{job_id}/decision.md", "APPROVE\n## Diverged\n- a\n")
        board.cmd_sync(self.root, job_id)
        self.assertIs(self.jobs()[0]["diverged"], False)
        missing = board.cmd_new(self.root, "y")
        (self.root / "jobs" / missing).rmdir()
        board.cmd_set(self.root, missing, ["stage=build"])
        self.assertIs(self.jobs()[1]["diverged"], False)

    def test_diverged_ignores_fenced_code(self):
        job_id = board.cmd_new(self.root, "x")
        cases = {"```\n## Diverged\n- a\n```\n": False, "~~~md\n## Diverged\n- a\n~~~\n": False,
                 "## Diverged\n```\n- a\n```\n": False, "```\n## Diverged\n- a\n": False,
                 "  ```\n## Diverged\n- a\n  ```\n": False,
                 "```\n## Summary\n```\n## Diverged\n- a → b — c\n": True,
                 "## Diverged\n```\n- example\n```\n- a → b — c\n": True,
                 "````md\n```\nx\n```\n## Diverged\n- a\n````\n": False,
                 "````md\n```\nx\n```\n## Diverged\n- a\n````\n## Diverged\n- a → b — c\n": True,
                 "```\n~~~\n## Diverged\n- a\n```": False,
                 "```\n~~~\n## Diverged\n- a\n```\n## Diverged\n- b → c — d\n": True,
                 "~~~\n```\n## Diverged\n- a\n~~~": False,
                 "~~~\n```\n## Diverged\n- a\n~~~\n## Diverged\n- b → c — d\n": True,
                 "```\n```python\n## Diverged\n- a\n```\n": False,
                 "```\n```python\n```\n## Diverged\n- a → b — c\n": True}
        for text, want in cases.items():
            self.write(f"{job_id}/build.md", text)
            board.cmd_set(self.root, job_id, ["stage=build"])
            self.assertIs(self.jobs()[0]["diverged"], want, text)

    def test_sync_complete_rounds_and_verdicts(self):
        job_id = board.cmd_new(self.root, "x")
        for r in board.REVIEWERS:
            self.write(f"{job_id}/round-1/review-{r}.md", "VERDICT: CHANGES" if r == "code" else "VERDICT: PASS")
            self.write(f"{job_id}/round-2/review-{r}.md", "VERDICT: PASS")
        self.write(f"{job_id}/round-10/check.md", "CHECK: FAIL")  # sorted numerically, not as text
        status = board.cmd_sync(self.root, job_id)
        self.assertEqual(status["round"], 10)
        job = self.jobs()[0]
        self.assertEqual(job["rounds"][0]["code"], "CHANGES")
        self.assertEqual(job["rounds"][1]["code"], "PASS")
        self.assertEqual(job["rounds"][2]["check"], "FAIL")

    def test_sync_reports_pass_changes_and_invalid(self):
        job_id = board.cmd_new(self.root, "x")
        for r in board.REVIEWERS:
            self.write(f"{job_id}/round-1/review-{r}.md", "VERDICT: PASS")
        self.assertEqual(board.cmd_sync(self.root, job_id)["verdict"], "PASS")
        self.write(f"{job_id}/round-1/review-ui.md", "VERDICT: CHANGES")
        self.assertEqual(board.cmd_sync(self.root, job_id)["verdict"], "CHANGES")
        self.write(f"{job_id}/round-1/review-ux.md", "I think it's fine")
        status = board.cmd_sync(self.root, job_id)
        self.assertTrue(status["complete"])
        self.assertEqual((status["verdict"], status["invalid"]), ("INVALID", ["ux"]))
        self.assertEqual(status["missing"], [])

    def test_sync_e2e_changes_overrides_pass(self):
        job_id = board.cmd_new(self.root, "x")
        for r in board.REVIEWERS:
            self.write(f"{job_id}/round-1/review-{r}.md", "VERDICT: PASS")
        self.write(f"{job_id}/round-1/review-e2e.md", "VERDICT: CHANGES\n## Findings\n1. real bug")
        status = board.cmd_sync(self.root, job_id)
        self.assertTrue(status["complete"])
        self.assertEqual(status["verdict"], "CHANGES")
        self.assertEqual(status["invalid"], [])
        self.assertEqual(status["e2e"], "CHANGES")
        self.write(f"{job_id}/round-1/review-e2e.md", "VERDICT: PASS")
        self.assertEqual(board.cmd_sync(self.root, job_id)["verdict"], "PASS")
        self.assertEqual(self.jobs()[0]["reviews"], {"security": "PASS", "ux": "PASS", "ui": "PASS", "code": "PASS"})

    def test_sync_e2e_absent_is_not_missing(self):
        job_id = board.cmd_new(self.root, "x")
        for r in board.REVIEWERS:
            self.write(f"{job_id}/round-1/review-{r}.md", "VERDICT: PASS")
        status = board.cmd_sync(self.root, job_id)
        self.assertEqual((status["complete"], status["verdict"], status["missing"], status["invalid"]),
                         (True, "PASS", [], []))
        self.assertIsNone(status["e2e"])
        (self.root / "jobs" / job_id / "round-1" / "review-ui.md").unlink()
        status = board.cmd_sync(self.root, job_id)
        self.assertEqual((status["complete"], status["verdict"], status["missing"]), (False, None, ["review-ui.md"]))

    def test_sync_e2e_invalid(self):
        job_id = board.cmd_new(self.root, "x")
        for r in board.REVIEWERS:
            self.write(f"{job_id}/round-1/review-{r}.md", "VERDICT: PASS")
        self.write(f"{job_id}/round-1/review-e2e.md", "Looks fine to me")
        status = board.cmd_sync(self.root, job_id)
        self.assertEqual((status["verdict"], status["invalid"], status["e2e"]), ("INVALID", ["e2e"], "INVALID"))
        self.assertEqual(status["missing"], [])

    def test_sync_no_rounds_lists_all_missing(self):
        job_id = board.cmd_new(self.root, "x")
        status = board.cmd_sync(self.root, job_id)
        self.assertFalse(status["complete"])
        self.assertEqual(status["missing"], ["review-security.md", "review-ux.md", "review-ui.md", "review-code.md"])

    def test_sync_reads_decision(self):
        job_id = board.cmd_new(self.root, "x")
        self.assertIsNone(board.cmd_sync(self.root, job_id)["decision"])
        self.write(f"{job_id}/decision.md", "**ESCALATE**\nHard stop: auth")
        self.assertEqual(board.cmd_sync(self.root, job_id)["decision"], "ESCALATE")

    def test_cli_set_and_sync(self):
        run = lambda *a: subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), *a],
                                        capture_output=True, text=True)
        job_id = run("new", "cli job").stdout.strip()
        self.assertEqual(run("set", job_id, "stage=build").returncode, 0)
        out = run("sync", job_id)
        self.assertEqual(json.loads(out.stdout)["round"], 0)
        bad = run("set", job_id, "nope=1")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("nope", bad.stderr)

    # --- backlog ---
    def test_next_claims_first_unchecked_item_and_creates_job(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [x] old → 001-old\n- [ ] Add CSV export\n- [ ] Dark mode\n")
        out = board.cmd_next(self.root)
        self.assertEqual(out, {"id": "001-add-csv-export", "feature": "Add CSV export"})
        self.assertIn("- [x] Add CSV export → 001-add-csv-export", (self.root / "backlog.md").read_text())
        self.assertIn("- [ ] Dark mode", (self.root / "backlog.md").read_text())
        self.assertEqual(board.cmd_next(self.root)["feature"], "Dark mode")
        self.assertEqual(board.cmd_next(self.root), {"id": None, "feature": None})

    def test_concurrent_next_never_claims_the_same_item(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("".join(f"- [ ] item {i}\n" for i in range(6)))
        procs = [subprocess.Popen([sys.executable, str(BOARD_PY), "--dir", str(self.root), "next"],
                                  stdout=subprocess.PIPE, text=True) for _ in range(6)]
        features = [json.loads(p.communicate()[0])["feature"] for p in procs]
        self.assertEqual(sorted(features), [f"item {i}" for i in range(6)])

    def test_backlog_add_appends_unchecked_items(self):
        board.cmd_backlog_add(self.root, ["fix A (from 001-x)", "fix B (from 001-x)"])
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [ ] fix A (from 001-x)\n- [ ] fix B (from 001-x)\n")

    # --- manual-checks.md: follow-ups only a human can do ---
    def test_manual_add_appends_unchecked_items(self):
        items = ["check Safari login (from 001-x)", "check iPhone layout (from 001-x)"]
        self.assertEqual(board.cmd_manual_add(self.root, items), items)
        self.assertEqual((self.root / "manual-checks.md").read_text(),
                         "# Manual checks\n- [ ] check Safari login (from 001-x)\n- [ ] check iPhone layout (from 001-x)\n")
        (self.root / "manual-checks.md").write_text("# Manual checks\nTrevor's note\n- [x] old check\n")
        self.assertEqual(board.cmd_manual_add(self.root, items), items)
        self.assertEqual((self.root / "manual-checks.md").read_text(),
                         "# Manual checks\nTrevor's note\n- [x] old check\n"
                         "- [ ] check Safari login (from 001-x)\n- [ ] check iPhone layout (from 001-x)\n")
        self.assertFalse((self.root / "backlog.md").exists())

    def test_manual_add_skips_empty_and_duplicates(self):
        self.root.mkdir(parents=True)
        (self.root / "manual-checks.md").write_text("# Manual checks\n- [ ] open one\n- [x] ticked one\n")
        self.assertEqual(board.cmd_manual_add(self.root, ["  ", "<!-- -->", "open one", "open  one ", "ticked one",
                                                          "new", "new"]), ["ticked one", "new"])
        self.assertEqual((self.root / "manual-checks.md").read_text(),
                         "# Manual checks\n- [ ] open one\n- [x] ticked one\n- [ ] ticked one\n- [ ] new\n")
        (self.root / "manual-checks.md").unlink()
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "manual-add", "a", "a"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["a"])
        self.assertEqual((self.root / "manual-checks.md").read_text(), "# Manual checks\n- [ ] a\n")

    def test_manual_tick_marks_done(self):
        self.root.mkdir(parents=True)
        (self.root / "manual-checks.md").write_text("# Manual checks\nnote\n- [ ] one\n- [x] two\n- [ ] three\n")
        self.assertEqual(board.manual_tick(self.root, 2), [
            {"index": 0, "done": False, "text": "one"}, {"index": 1, "done": True, "text": "two"},
            {"index": 2, "done": True, "text": "three"}])
        self.assertEqual((self.root / "manual-checks.md").read_text(), "# Manual checks\nnote\n- [ ] one\n- [x] two\n- [x] three\n")
        for bad in (3, -1, True, "0", None):
            with self.assertRaises(SystemExit):
                board.manual_tick(self.root, bad)
        self.assertEqual((self.root / "manual-checks.md").read_text(), "# Manual checks\nnote\n- [ ] one\n- [x] two\n- [x] three\n")

    def triage(self, backlog, plan):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "backlog.md").write_text(backlog)
        tid = board.cmd_triage_start(self.root)["id"]
        (self.root / "triage" / tid / "plan.json").write_text(plan if isinstance(plan, str) else json.dumps(plan))
        return tid

    def test_triage_apply_moves_manual_items_to_checklist(self):
        tid = self.triage("# Backlog\n- [ ] Check Safari login (from 004-auth)\n- [ ] [3] Check iPhone layout <!-- est -->\n"
                          "- [ ] Dark mode\n",
                          {"manual": [{"item": "Check Safari login (from 004-auth)", "reason": "needs a real Safari"},
                                      {"item": "Check iPhone layout", "reason": "needs a device"}],
                           "estimate": [{"item": "Dark mode", "points": 2, "why": "one toggle"}]})
        res = board.cmd_triage_apply(self.root, tid)
        self.assertEqual(res, {"merged": 0, "retired": 0, "manual": 2, "estimated": 1, "depends": 0, "skipped": 0})
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [x] Check Safari login (from 004-auth) <!-- manual check: needs a real Safari -->\n"
                         "- [x] Check iPhone layout <!-- manual check: needs a device -->\n"
                         "- [ ] [2] Dark mode <!-- one toggle -->\n")
        self.assertEqual((self.root / "manual-checks.md").read_text(),
                         "# Manual checks\n- [ ] Check Safari login (from 004-auth)\n- [ ] Check iPhone layout\n")
        report = (self.root / "triage" / tid / "report.md").read_text()
        self.assertIn("\n## Manual\n- Check Safari login (from 004-auth) — needs a real Safari\n"
                      "- Check iPhone layout — needs a device\n\n## Estimated\n", report)

    def test_triage_apply_manual_skips_bad_entries(self):
        backlog = "# Backlog\n- [ ] Alpha\n- [ ] Beta\n- [ ] Gamma\n"
        tid = self.triage(backlog, {
            "retire": [{"item": "Alpha", "reason": "done in 009-a"}],
            "manual": [{"item": "Beta"}, {"item": "Beta", "reason": "  "}, {"item": "Nope", "reason": "r"},
                       {"item": "Alpha", "reason": "r"}, {"item": "Gamma", "reason": "device only"}],
            "estimate": [{"item": "Gamma", "points": 3, "why": "w"}]})
        res = board.cmd_triage_apply(self.root, tid)
        self.assertEqual(res, {"merged": 0, "retired": 1, "manual": 1, "estimated": 0, "depends": 0, "skipped": 5})
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [x] Alpha <!-- retired: done in 009-a -->\n- [ ] Beta\n"
                         "- [x] Gamma <!-- manual check: device only -->\n")
        self.assertEqual((self.root / "manual-checks.md").read_text(), "# Manual checks\n- [ ] Gamma\n")
        skipped = (self.root / "triage" / tid / "report.md").read_text().split("## Skipped\n", 1)[1]
        self.assertEqual(skipped,
                         '- manual "Beta" — no reason given\n'
                         '- manual "Beta" — no reason given\n'
                         '- manual "Nope" — no open item has the text "Nope"\n'
                         '- manual "Alpha" — already used by an earlier entry\n'
                         '- estimate "Gamma" — already used by an earlier entry\n')
        before = (self.root / "backlog.md").read_text()
        (self.root / "manual-checks.md").unlink()
        tid = board.cmd_triage_start(self.root)["id"]
        (self.root / "triage" / tid / "plan.json").write_text(json.dumps({"manual": {"item": "Beta", "reason": "r"}}))
        with self.assertRaises(SystemExit) as e:
            board.cmd_triage_apply(self.root, tid)
        self.assertIn("must be an object of", str(e.exception))
        self.assertEqual((self.root / "backlog.md").read_text(), before)
        self.assertFalse((self.root / "manual-checks.md").exists())

    def test_sync_counts_reworks_used(self):
        job_id = board.cmd_new(self.root, "x")
        self.assertEqual(board.cmd_sync(self.root, job_id)["reworks"], 0)
        self.write(f"{job_id}/round-2/decision.md", "REWORK\nfix-now: X")
        self.write(f"{job_id}/round-3/decision.md", "**REWORK**")
        self.write(f"{job_id}/decision.md", "REWORK")  # root copy is not double-counted
        self.assertEqual(board.cmd_sync(self.root, job_id)["reworks"], 2)

    # --- abort ---
    def test_abort_marks_job_and_blocks_further_orchestrator_writes(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_abort(self.root, job_id, requeue=False)
        job = self.jobs()[0]
        self.assertEqual(job["stage"], "aborted")
        self.assertTrue(job["reason"].startswith("Aborted by Trevor"))
        for call in (lambda: board.cmd_set(self.root, job_id, ["stage=review"]), lambda: board.cmd_sync(self.root, job_id)):
            with self.assertRaises(SystemExit) as e:
                call()
            self.assertIn("was aborted", str(e.exception))
        self.assertEqual(self.jobs()[0]["stage"], "aborted")

    def test_abort_requeues_full_feature_text(self):
        job_id = board.cmd_new(self.root, "Short title")
        (self.root / "jobs" / job_id / "feature.md").write_text("Short title\nwith the full details on line two\n")
        board.cmd_abort(self.root, job_id, requeue=True)
        items = board.backlog_items(self.root)
        self.assertEqual((items[-1]["done"], items[-1]["text"]), (False, "Short title with the full details on line two"))

    def test_abort_refuses_done_or_already_aborted_jobs(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=done"])
        with self.assertRaises(SystemExit):
            board.cmd_abort(self.root, job_id, requeue=False)
        aborted = board.cmd_new(self.root, "y")
        board.cmd_abort(self.root, aborted, requeue=False)
        with self.assertRaises(SystemExit):
            board.cmd_abort(self.root, aborted, requeue=False, reason="again")

    def test_abort_stores_custom_reason(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_abort(self.root, job_id, requeue=False, reason="obsolete: duplicate of #14")
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["reason"]), ("aborted", "obsolete: duplicate of #14"))
        cli = board.cmd_new(self.root, "y")
        board.main(["--dir", str(self.root), "abort", cli, "--requeue", "--reason", "obsolete: it's done"])
        job = next(j for j in self.jobs() if j["id"] == cli)
        self.assertEqual((job["stage"], job["reason"]), ("aborted", "obsolete: it's done"))
        self.assertEqual(board.backlog_items(self.root)[-1]["text"], "y")

    def test_abort_default_reason_unchanged(self):
        job_id = board.cmd_new(self.root, "x")
        board.main(["--dir", str(self.root), "abort", job_id])
        self.assertTrue(self.jobs()[0]["reason"].startswith("Aborted by Trevor "))

    # --- pause ---
    def test_pause_records_stage_in_reason_and_keeps_fields(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build", "round=2", "limit=3", "pr=https://x/1", "worktree=/wt/x",
                                          "builder=agent-1"])
        self.write(f"{job_id}/build.md", "STATUS: READY\n")
        before = self.jobs()[0]
        with mock.patch.object(board, "play") as play:
            self.assertEqual(board.cmd_pause(self.root, job_id), [job_id])
        play.assert_not_called()
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["reason"]),
                         ("needs-human", "stalled in build: paused by Trevor. Fix: click Play."))
        for key in ("worktree", "branch", "pr", "round", "limit", "builder", "files"):
            self.assertEqual(job[key], before[key], key)
        self.assertEqual((self.root / "jobs" / job_id / "build.md").read_text(), "STATUS: READY\n")

    def test_pause_refuses_job_not_in_progress(self):
        for stage in ("waiting", "done", "needs-human", "aborted"):
            job_id = board.cmd_new(self.root, f"x {stage}")
            if stage == "aborted":
                board.cmd_abort(self.root, job_id, requeue=False)
            else:
                board.cmd_set(self.root, job_id, [f"stage={stage}"])
            before = (self.root / "board.json").read_text()
            with self.assertRaises(SystemExit) as e:
                board.cmd_pause(self.root, job_id)
            self.assertEqual(str(e.exception), f"job {job_id} is {stage}; only a job in progress can be paused")
            self.assertEqual((self.root / "board.json").read_text(), before)

    def test_paused_job_refuses_writes_until_explicit_unpause(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=review"])
        board.cmd_pause(self.root, job_id)
        paused = "stalled in review: paused by Trevor. Fix: click Play."
        with mock.patch.object(board, "merge_refusal", return_value=None):  # the pause must refuse, not the PR guard
            for call in (lambda: board.cmd_set(self.root, job_id, ["stage=approve"]),
                         lambda: board.cmd_set(self.root, job_id, ["tty=ttys003"]),
                         lambda: board.cmd_sync(self.root, job_id),
                         lambda: board.cmd_set(self.root, job_id, ["stage=done", "reason="]),
                         lambda: board.cmd_set(self.root, job_id, ["stage=review", "reason="])):
                with self.assertRaises(SystemExit) as e:
                    call()
                self.assertEqual(str(e.exception), f"job {job_id} was paused by Trevor; stop working on it")
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["reason"]), ("needs-human", paused))
        board.cmd_set(self.root, job_id, ["stage=review", "reason="], unpause=True)
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["reason"]), ("review", None))
        board.cmd_set(self.root, job_id, ["stage=approve"])  # un-paused: writes work again
        self.assertEqual(self.jobs()[0]["stage"], "approve")

    def test_set_cli_unpause_flag(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        board.cmd_pause(self.root, job_id)
        with self.assertRaises(SystemExit) as e:
            board.main(["--dir", str(self.root), "set", job_id, "stage=review", "reason="])
        self.assertEqual(str(e.exception), f"job {job_id} was paused by Trevor; stop working on it")
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["reason"]),
                         ("needs-human", "stalled in build: paused by Trevor. Fix: click Play."))
        board.main(["--dir", str(self.root), "set", "--unpause", job_id, "stage=review", "reason="])
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["reason"]), ("review", None))
        board.main(["--dir", str(self.root), "set", job_id, "stage=approve"])
        self.assertEqual(self.jobs()[0]["stage"], "approve")
        # not paused: --unpause is harmless, the write applies as without it
        board.main(["--dir", str(self.root), "set", "--unpause", job_id, "stage=check", "reason=blocked: x"])
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["reason"]), ("check", "blocked: x"))
        board.cmd_abort(self.root, job_id, requeue=False)
        with self.assertRaises(SystemExit) as e:
            board.main(["--dir", str(self.root), "set", "--unpause", job_id, "stage=review", "reason="])
        self.assertEqual(str(e.exception), f"job {job_id} was aborted by Trevor; stop working on it")
        self.assertEqual(self.jobs()[0]["stage"], "aborted")

    def test_pause_parent_pauses_children_and_blocks_ready(self):
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3, deps="T1"),
                           self.ticket(4, deps="T1, T2, T3", parallel="no — last", exposure="yes"))
        c1, c2, c3, c4 = board.cmd_plan_apply(self.root, parent)["children"]
        board.cmd_set(self.root, c1, ["stage=done"])
        board.cmd_set(self.root, c2, ["stage=build"])
        self.assertEqual(sorted(board.cmd_pause(self.root, parent)), sorted([parent, c2]))
        stalled = {j["id"]: (j["stage"], j["reason"]) for j in self.jobs()}
        self.assertEqual(stalled[parent], ("needs-human", "stalled in running: paused by Trevor. Fix: click Play."))
        self.assertEqual(stalled[c2], ("needs-human", "stalled in build: paused by Trevor. Fix: click Play."))
        self.assertEqual((stalled[c1][0], stalled[c3][0], stalled[c4][0]), ("done", "waiting", "waiting"))
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])  # c3's only dependency is done
        after = {j["id"]: (j["stage"], j["reason"]) for j in self.jobs()}
        self.assertEqual(after[parent], stalled[parent])
        self.assertEqual(after[c3][0], "waiting")

    # --- reopen ---
    def test_reopen_creates_linked_job(self):
        old = board.cmd_new(self.root, "Modal title")
        board.cmd_set(self.root, old, ["stage=done", "reason=merged", "pr=https://github.com/x/y/pull/9"])
        before = next(j for j in self.jobs() if j["id"] == old)
        new = board.cmd_reopen(self.root, old, "  Modal title still wraps\non mobile  ")
        self.assertEqual(new, "002-reopen-001-modal-title-still-wraps-on-mo")
        jobs = {j["id"]: j for j in self.jobs()}
        self.assertEqual(jobs[new]["title"], "Reopen 001: Modal title still wraps on mobile")
        self.assertEqual((jobs[new]["stage"], jobs[new]["reopened_from"]), ("spec", "001-modal-title"))
        self.assertEqual({k: v for k, v in jobs[old].items() if k != "reopened_to"},
                         {k: v for k, v in before.items()})
        self.assertEqual(jobs[old]["reopened_to"], new)
        long = board.cmd_new(self.root, "z")
        board.cmd_abort(self.root, long, requeue=False)
        newer = board.cmd_reopen(self.root, long, "x" * 100)
        self.assertEqual(next(j for j in self.jobs() if j["id"] == newer)["title"], "Reopen 003: " + "x" * 48)

    def test_reopen_feature_carries_context(self):
        old = board.cmd_new(self.root, "Done one")
        board.cmd_set(self.root, old, ["stage=done", "pr=https://github.com/x/y/pull/9"])
        self.write(f"{old}/feature.md", "Make the title fit\n")
        self.write(f"{old}/spec.md", "# Spec\nCriteria here\n")
        self.write(f"{old}/decision.md", "DECISION: APPROVE\n## Why\nfine\n## Merge summary\nTitle now truncates.\nCSS only.\n## Later\nnope\n")
        new = board.cmd_reopen(self.root, old, "Still wraps on mobile")
        self.assertEqual((self.root / "jobs" / new / "feature.md").read_text(),
                         "Still wraps on mobile\n"
                         "Reopened from 001-done-one. PR: https://github.com/x/y/pull/9\n\n"
                         "## Original feature.md\n\nMake the title fit\n\n"
                         "## Original spec.md\n\n# Spec\nCriteria here\n\n"
                         "## Original Merge summary\n\nTitle now truncates.\nCSS only.\n")
        aborted = board.cmd_new(self.root, "Aborted one")
        board.cmd_abort(self.root, aborted, requeue=False)
        self.write(f"{aborted}/feature.md", "Try a thing\n")
        self.write(f"{aborted}/decision.md", "DECISION: ESCALATE\n## Why\nno summary here\n")
        new2 = board.cmd_reopen(self.root, aborted, "Try again")
        self.assertEqual((self.root / "jobs" / new2 / "feature.md").read_text(),
                         "Try again\nReopened from 003-aborted-one.\n\n## Original feature.md\n\nTry a thing\n")

    def test_reopen_refuses(self):
        live_job = board.cmd_new(self.root, "still going")
        board.cmd_set(self.root, live_job, ["stage=review"])
        done = board.cmd_new(self.root, "finished")
        board.cmd_set(self.root, done, ["stage=done"])
        board.cmd_reopen(self.root, done, "follow up")
        snapshot = lambda: ((self.root / "board.json").read_text(), sorted(p.name for p in (self.root / "jobs").iterdir()))
        before = snapshot()
        for job_id, note, msg in ((live_job, "x", "done or aborted"), (done, "y", "003-reopen-002-follow-up")):
            with self.assertRaises(SystemExit) as e:
                board.cmd_reopen(self.root, job_id, note)
            self.assertIn(msg, str(e.exception))
            self.assertEqual(snapshot(), before)
        other = board.cmd_new(self.root, "other")
        board.cmd_set(self.root, other, ["stage=done"])
        before = snapshot()
        for note in ("", "  \n ", "<!-- -->"):
            with self.assertRaises(SystemExit):
                board.cmd_reopen(self.root, other, note)
            self.assertEqual(snapshot(), before)

    # --- digest ---
    def done_jobs(self, n, stage="done"):
        ids = []
        for i in range(n):
            job_id = board.cmd_new(self.root, f"{stage} {i}")
            if stage == "aborted":
                board.cmd_abort(self.root, job_id, requeue=False)
            else:
                board.cmd_set(self.root, job_id, [f"stage={stage}"])
            ids.append(job_id)
        return ids

    def cli(self, *args):
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_digest_due_counts_only_undigested_done_jobs(self):
        done = self.done_jobs(9)
        self.done_jobs(2, "aborted")
        self.done_jobs(1, "review")
        self.done_jobs(1, "needs-human")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 9})
        done += self.done_jobs(1)
        self.assertEqual(self.cli("digest-due"), {"due": True, "undigested": 10})
        (self.root / "digests" / "001").mkdir(parents=True)
        (self.root / "digests" / "001" / "jobs.txt").write_text("\n".join(done[:4]) + "\n")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 6})
        self.assertEqual(board.digested_ids(self.root), set(done[:4]))

    def test_failed_digest_releases_its_jobs(self):
        a, b = self.done_jobs(2)
        d = self.root / "digests" / "001"
        d.mkdir(parents=True)
        (d / "jobs.txt").write_text(f"{a}\n{b}\n")
        self.assertEqual(board.digested_ids(self.root), {a, b})  # no error.md: still claimed
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0})
        (d / "error.md").write_text("digester produced no valid proposals\n")
        self.assertEqual(board.digested_ids(self.root), set())
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 2})
        self.assertEqual(self.cli("digest-start"), {"id": "002", "jobs": [a, b]})
        self.assertEqual(board.digested_ids(self.root), {a, b})
        self.assertTrue((d / "jobs.txt").exists())  # the failed digest stays as it was

    def test_digest_start_claims_jobs_once(self):
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": []})
        self.assertFalse((self.root / "digests").exists())
        done = self.done_jobs(3)
        aborted = self.done_jobs(1, "aborted")
        self.assertEqual(self.cli("digest-start"), {"id": "001", "jobs": done})
        self.assertEqual((self.root / "digests" / "001" / "jobs.txt").read_text(), "\n".join(done) + "\n")
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": []})
        self.assertEqual(sorted(p.name for p in (self.root / "digests").iterdir()), ["001"])
        more = self.done_jobs(1)
        self.assertEqual(self.cli("digest-start"), {"id": "002", "jobs": more})
        self.assertNotIn(aborted[0], (self.root / "digests" / "002" / "jobs.txt").read_text())
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0})

    def fill(self, job_id):
        for rel in ("feature.md", "spec.md", "decision.md", "build.md", "round-1/check.md", "round-1/review-ui.md",
                    "round-1/decision.md", "rework.md", "pr-body.txt"):
            self.write(f"{job_id}/{rel}", rel)

    def test_digest_trim_keeps_three_files_and_updates_board(self):
        a, b = self.done_jobs(2)
        for j in (a, b):
            self.fill(j)
        self.write(f"{a}/build.md", "## Diverged\n- spec said A → did B — why\n")
        board.cmd_sync(self.root, a)
        self.assertIn("round-1/check.md", self.jobs()[0]["files"])
        self.assertIs(self.jobs()[0]["diverged"], True)
        (self.root / "jobs" / b / "spec.md").unlink()  # a job with only some of the three keeps what it has
        out = self.cli("digest-start")
        self.assertEqual(board.cmd_digest_trim(self.root, out["id"]), [a, b])
        self.assertEqual(sorted(p.name for p in (self.root / "jobs" / a).iterdir()), ["decision.md", "feature.md", "spec.md"])
        self.assertEqual(sorted(p.name for p in (self.root / "jobs" / b).iterdir()), ["decision.md", "feature.md"])
        self.assertEqual((self.root / "jobs" / a / "spec.md").read_text(), "spec.md")
        files = {j["id"]: j["files"] for j in self.jobs()}
        self.assertEqual(files[a], ["decision.md", "feature.md", "spec.md"])
        self.assertEqual(files[b], ["decision.md", "feature.md"])
        self.assertIs(self.jobs()[0]["diverged"], False)  # build.md was trimmed away
        self.assertTrue((self.root / "digests" / "001" / "trimmed").exists())
        self.assertEqual(self.cli("digest-trim", "001"), [a, b])  # idempotent
        self.assertEqual(sorted(p.name for p in (self.root / "jobs" / a).iterdir()), ["decision.md", "feature.md", "spec.md"])
        for bad in ("1", "../x", "abc", "999"):
            with self.assertRaises(SystemExit, msg=bad):
                board.cmd_digest_trim(self.root, bad)

    def test_digest_trim_skips_non_done_and_unlisted(self):
        listed, unlisted = self.done_jobs(2)
        review = self.done_jobs(1, "review")[0]
        for j in (listed, unlisted, review):
            self.fill(j)
        d = self.root / "digests" / "001"
        d.mkdir(parents=True)
        (d / "jobs.txt").write_text(f"{listed}\n{review}\n../../etc\n999-not-on-board\n")
        self.assertEqual(board.cmd_digest_trim(self.root, "001"), [listed])
        self.assertEqual(len(list((self.root / "jobs" / unlisted).rglob("*"))), 10)
        self.assertEqual(len(list((self.root / "jobs" / review).rglob("*"))), 10)
        self.assertEqual(len(list((self.root / "jobs" / listed).rglob("*"))), 3)

    # --- watchdog ---
    def aged(self, title, minutes, **fields):
        """A new job with `fields` written straight into board.json and updatedAt `minutes` ago."""
        from datetime import datetime, timedelta, timezone
        job_id = board.cmd_new(self.root, title)
        data = json.loads((self.root / "board.json").read_text())
        job = next(j for j in data["jobs"] if j["id"] == job_id)
        job.update(fields, updatedAt=(datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds"))
        (self.root / "board.json").write_text(json.dumps(data))
        return job_id

    def get(self, job_id):
        return next(j for j in self.jobs() if j["id"] == job_id)

    def test_watchdog_flags_stalled_review_job(self):
        job_id = self.aged("Stuck review", 31, stage="review")
        old = self.get(job_id)["updatedAt"]
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [job_id])
        job = self.get(job_id)
        self.assertEqual(job["stage"], "needs-human")
        self.assertEqual(job["reason"], "stalled in review: no board update for 30 min and no live session. Fix: click Resume.")
        self.assertNotEqual(job["updatedAt"], old)
        for stage in ("build", "check", "approve"):
            other = self.aged(f"Stuck {stage}", 45, stage=stage)
            self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [other])
            self.assertTrue(self.get(other)["reason"].startswith(f"stalled in {stage}: "))

    def test_watchdog_skips_fresh_live_waiting_and_inactive_jobs(self):
        fresh = self.aged("Fresh", 29, stage="review")
        live = self.aged("Live", 31, stage="build")
        paused = self.aged("Paused", 31, stage="check", waiting="question: which one?")
        others = [self.aged(f"In {s}", 31, stage=s)
                  for s in ("merging", "running", "waiting", "needs-human", "done", "aborted")]
        before = self.jobs()
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: job["id"] == live), [])
        self.assertEqual(self.jobs(), before)
        stuck = self.aged("Stuck", 31, stage="approve")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: job["id"] == live), [stuck])
        flagged = self.jobs()
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: job["id"] == live), [])
        self.assertEqual(self.jobs(), flagged)
        self.assertEqual([self.get(j)["stage"] for j in (fresh, live, paused)], ["review", "build", "check"])
        self.assertEqual(len(others), 6)

    def test_watchdog_flags_stalled_spec_job(self):
        fresh = self.aged("Fresh spec", 1, stage="spec")
        stuck = self.aged("Stuck spec", 31, stage="spec")
        (self.root / "jobs" / stuck / "feature.md").write_text("Stuck spec\n")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [stuck])
        self.assertEqual(self.get(stuck)["stage"], "needs-human")
        self.assertEqual(self.get(stuck)["reason"],
                         "stalled in spec: no board update for 30 min and no live session. Fix: click Resume.")
        self.assertEqual(self.get(fresh)["stage"], "spec")

    def test_watchdog_requeues_orphaned_spec_claim_in_place(self):
        (self.root / "backlog-specs").mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] [3] Full item text, every detail {#ab12} <!-- why -->\n- [ ] Other\n")
        board.spec_path(self.root, "Full item text, every detail").write_text("pre-written spec")
        claimed = board.cmd_next(self.root)["id"]
        data = json.loads((self.root / "board.json").read_text())
        data["jobs"][0]["updatedAt"] = "2000-01-01T00:00:00+00:00"
        (self.root / "board.json").write_text(json.dumps(data))
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])
        self.assertEqual(self.get(claimed)["stage"], "aborted")
        self.assertEqual(self.get(claimed)["reason"], board.ORPHANED)
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [ ] [3] Full item text, every detail {#ab12} <!-- why -->\n- [ ] Other\n")
        self.assertEqual(board.spec_path(self.root, "Full item text, every detail").read_text(), "pre-written spec")

    def test_watchdog_never_flags_cloud_jobs(self):
        cloud = self.aged("In cloud", 120, stage="cloud")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])
        self.assertEqual(self.get(cloud)["stage"], "cloud")

    def test_watchdog_never_flags_lilguy_jobs(self):
        lil = self.aged("Lil change", 45, stage="build", lane="lilguy")
        std = self.aged("Std build", 45, stage="build", lane="standard")
        old = self.get(lil)["updatedAt"]
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [std])
        self.assertEqual((self.get(lil)["stage"], self.get(lil)["updatedAt"]), ("build", old))
        self.assertEqual(self.get(std)["stage"], "needs-human")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])
        self.assertEqual((self.get(lil)["stage"], self.get(lil)["updatedAt"]), ("build", old))

    def test_resume_blocker_matches_ready_rules(self):
        stalled = ["stage=needs-human", "reason=stalled in build: no board update for 30 min and no live session. Fix: click Resume."]
        # No parent: never blocked.
        solo = board.cmd_new(self.root, "Solo")
        board.cmd_set(self.root, solo, stalled)
        self.assertIsNone(board.resume_blocker(self.root, solo))
        # BigBoy, no cap: a, b, c parallel; d parallel=no.
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3), self.ticket(4, parallel="no — big"),
                           self.ticket(5, deps="T1, T2, T3, T4", exposure="yes"))
        a, b, c, d, e = board.cmd_plan_apply(self.root, parent)["children"]
        self.spec(a, "src/a.py", "src/shared.py")
        self.spec(b, "src/b.py")
        self.spec(c, "src/c.py", "src/shared.py")
        self.spec(d, "src/d.py")
        board.cmd_set(self.root, a, stalled)
        # No sibling in progress (all waiting/needs-human).
        self.assertIsNone(board.resume_blocker(self.root, a))
        # Disjoint parallel sibling in progress.
        board.cmd_set(self.root, b, ["stage=build"])
        self.assertIsNone(board.resume_blocker(self.root, a))
        # (a) shared Likely file.
        board.cmd_set(self.root, c, ["stage=review"])
        text = board.resume_blocker(self.root, a)
        self.assertEqual(text, f"sibling {c} shares src/shared.py")
        self.assertEqual(text.ids, [c])
        board.cmd_set(self.root, c, ["stage=done"])
        self.assertIsNone(board.resume_blocker(self.root, a))
        # (b) an in-progress sibling with parallel=no runs alone.
        board.cmd_set(self.root, d, ["stage=check"])
        text = board.resume_blocker(self.root, a)
        self.assertEqual((text, text.ids), (f"sibling {d} runs alone", [d]))
        board.cmd_set(self.root, d, ["stage=done"])
        # (b) the job itself has no readable Likely files: it runs alone beside any in-progress sibling.
        (self.root / "jobs" / a / "spec.md").unlink()
        text = board.resume_blocker(self.root, a)
        self.assertEqual((text, text.ids), ("this job runs alone", [b]))
        self.spec(a, "src/a.py")
        # The job itself never counts as a sibling, even when it is in progress.
        board.cmd_set(self.root, b, ["stage=done"])
        board.cmd_set(self.root, a, ["stage=build"])
        self.assertIsNone(board.resume_blocker(self.root, a))
        # (c) Run-all cap: RUNALL_MAX_IN_PROGRESS (3) with no pacing.
        _, kids = self.runall(5)
        for i, k in enumerate(kids):
            self.spec(k, f"src/r{i}.py")
        board.cmd_set(self.root, kids[0], stalled)
        for k in kids[1:4]:
            board.cmd_set(self.root, k, ["stage=build"])
        text = board.resume_blocker(self.root, kids[0])
        self.assertEqual((text, text.ids), ("3 siblings in progress (cap 3)", kids[1:4]))
        board.cmd_set(self.root, kids[3], ["stage=done"])
        self.assertIsNone(board.resume_blocker(self.root, kids[0]))
        # (c) a fresh usage.json with projected use >= 125% paces the cap down to 1 for Run-all and BigBoy alike.
        now = int(__import__("time").time())
        usage = Path(self.tmp.name) / "usage.json"
        usage.write_text(json.dumps({"rate_limits": {"five_hour": {"used_percentage": 100, "resets_at": now + 9000}},
                                     "written_at": now}))
        with mock.patch.dict(os.environ, {"SCRUM_USAGE": str(usage)}):
            text = board.resume_blocker(self.root, kids[0])
            self.assertEqual((text, text.ids), ("2 siblings in progress (cap 1)", kids[1:3]))
            board.cmd_set(self.root, b, ["stage=build"])
            board.cmd_set(self.root, a, stalled)
            text = board.resume_blocker(self.root, a)
            self.assertEqual((text, text.ids), ("1 siblings in progress (cap 1)", [b]))
        self.assertIsNone(board.resume_blocker(self.root, a))  # BigBoy without pacing has no cap

    # --- cloud lane ---
    def test_new_with_id_keeps_the_given_id(self):
        self.assertEqual(board.cmd_new(self.root, "From the Mac", "042-from-the-mac"), "042-from-the-mac")
        self.assertTrue((self.root / "jobs" / "042-from-the-mac").is_dir())
        self.assertEqual(board.cmd_new(self.root, "Next one"), "043-next-one")
        with self.assertRaises(SystemExit):
            board.cmd_new(self.root, "Again", "042-from-the-mac")
        with self.assertRaises(SystemExit):
            board.cmd_new(self.root, "Bad", "../evil")
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "new", "CLI", "--id", "007-cli"],
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, "007-cli")

    def test_cloud_stage_and_session_url(self):
        job_id = board.cmd_new(self.root, "Cloud job")
        url = "https://claude.ai/code/session_015Ay7Jys6es4B7j1mVWLisy"
        board.cmd_set(self.root, job_id, ["stage=cloud", f"cloud={url}"])
        self.assertEqual((self.get(job_id)["stage"], self.get(job_id)["cloud"]), ("cloud", url))
        self.assertNotIn("cloud", board.WATCHED)
        for bad in ("javascript:alert(1)", "https://evil.example/code/session_x", f"{url}\"x"):
            with self.assertRaises(SystemExit):
                board.cmd_set(self.root, job_id, [f"cloud={bad}"])
        self.assertEqual(self.get(job_id)["cloud"], url)

    def test_session_alive_ignores_claude_dir_paths(self):
        lines = ("??      node /Users/t/onewitharts/.claude/worktrees/scrum-024-x/node_modules/.bin/next dev -p 3024\n"
                 "ttys009 node /Users/t/onewitharts/.claude/worktrees/scrum-011-x/node_modules/.bin/next dev\n"
                 "ttys004 /Users/t/.local/bin/claude --resume\n"
                 "??      /Users/t/.local/bin/claude -p /trevskills-scrum start 005-headless\n"
                 "??      python3 local/run.py claude -p /trevskills-scrum start 009-local\n"
                 "??      node /opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js start 010-node\n")
        ps = mock.Mock(stdout=lines, returncode=0)
        with mock.patch.object(board.subprocess, "run", return_value=ps):
            alive = board.session_alive_fn()
            self.assertFalse(alive({"id": "024-x", "tty": None}))
            self.assertFalse(alive({"id": "011-x", "tty": "ttys009"}))
            self.assertTrue(alive({"id": "006-interactive", "tty": "ttys004"}))
            self.assertTrue(alive({"id": "005-headless", "tty": None}))
            self.assertTrue(alive({"id": "009-local", "tty": None}))
            self.assertTrue(alive({"id": "010-node", "tty": None}))
        job_id = self.aged("Orphan dev server", 31, stage="build")
        orphan = ps.stdout.replace("scrum-024-x", f"scrum-{job_id}")
        with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout=orphan, returncode=0)):
            self.assertEqual(board.cmd_watchdog(self.root), [job_id])

    def test_session_alive_matches_id_or_tty_and_fails_safe(self):
        lines = ("ttys003 -zsh\n"
                 "ttys004 /Users/t/.local/bin/claude --resume\n"
                 "??      /Users/t/.local/bin/claude -p /trevskills-scrum start 005-headless\n"
                 "??      python3 runner.py 007-plain-python\n")
        with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout=lines, returncode=0)) as run:
            alive = board.session_alive_fn()
            self.assertTrue(alive({"id": "005-headless", "tty": None}))
            self.assertTrue(alive({"id": "006-interactive", "tty": "ttys004"}))
            self.assertFalse(alive({"id": "007-plain-python"}))
            self.assertFalse(alive({"id": "008-shell-only", "tty": "ttys003"}))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["ps", "-axo", "tty=,command="])
        for err in (OSError("no ps"), subprocess.TimeoutExpired("ps", 5)):
            with mock.patch.object(board.subprocess, "run", side_effect=err):
                self.assertTrue(board.session_alive_fn()({"id": "007-plain-python", "tty": None}))
        denied = subprocess.CompletedProcess(["ps"], 1, stdout="", stderr="ps: Operation not permitted\n")
        with mock.patch.object(board.subprocess, "run", return_value=denied):  # e.g. a sandboxed Bash call
            self.assertTrue(board.session_alive_fn()({"id": "007-plain-python", "tty": None}))

    def test_watchdog_cli_prints_flagged(self):
        run = lambda: subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "watchdog"],
                                     capture_output=True, text=True)
        fresh = self.aged("Fresh one", 1, stage="build")
        before = (self.root / "board.json").read_text()
        out = run()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"flagged": []})
        self.assertEqual((self.root / "board.json").read_text(), before)
        stuck = self.aged("Zq watchdog cli probe", 40, stage="check")
        out = run()
        self.assertEqual(json.loads(out.stdout), {"flagged": [stuck]})
        self.assertEqual((self.get(stuck)["stage"], self.get(fresh)["stage"]), ("needs-human", "build"))

    # --- roadmap.md ---
    ROADMAP = ("ROADMAP: onewitharts cleanup\n"
               "Goal: clean up mixed v0/Cursor/Claude patterns, make it faster, ready to clone into billmeez.\n"
               "\n"
               "## Constraints\n"
               "- Zero behaviour change in splits.\n"
               "- `calculateBlankCostFromSizes` stays the single blank-cost function.\n"
               "\n"
               "## P1 Split giant files\n"
               "- [x] S1 bigboy 011-split-quote-builder-content-tsx-13-5k-li: Split quote-builder-content.tsx, part 1\n"
               "- [~] S2 bigboy 017-quote-builder-bigboy-2-move-state-and-ef: Quote builder part 2, state and effects into hooks\n"
               "- [ ] S3 bigboy: Quote builder part 3, <request>\n"
               "- [ ] S4 standard: Split garmentDesigner\n"
               "## P2 Speed\n"
               "- [ ] S1 standard: Profile and fix the order-progress endpoint (~3.3s)\n"
               "\n"
               "## Log\n"
               "- 2026-10-15 09:12 P1 S1 done: BIGBOY PASS\n")
    J2 = "017-quote-builder-bigboy-2-move-state-and-ef"
    LOG_RE = r"^- \d{4}-\d{2}-\d{2} \d{2}:\d{2} "

    def roadmap(self, text=None):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "roadmap.md").write_text(self.ROADMAP if text is None else text)

    def rm_text(self):
        return (self.root / "roadmap.md").read_text()

    def rm_cli(self, *args):
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_roadmap_show_parses_design_example(self):
        self.roadmap()
        want = {
            "name": "onewitharts cleanup",
            "phases": [
                {"n": 1, "title": "Split giant files", "steps": [
                    {"n": 1, "kind": "bigboy", "job": "011-split-quote-builder-content-tsx-13-5k-li", "status": "done",
                     "request": "Split quote-builder-content.tsx, part 1"},
                    {"n": 2, "kind": "bigboy", "job": self.J2, "status": "running",
                     "request": "Quote builder part 2, state and effects into hooks"},
                    {"n": 3, "kind": "bigboy", "job": None, "status": "todo", "request": "Quote builder part 3, <request>"},
                    {"n": 4, "kind": "standard", "job": None, "status": "todo", "request": "Split garmentDesigner"}]},
                {"n": 2, "title": "Speed", "steps": [
                    {"n": 1, "kind": "standard", "job": None, "status": "todo",
                     "request": "Profile and fix the order-progress endpoint (~3.3s)"}]}],
            "current": {"p": 1, "s": 2},
            "next": {"p": 1, "s": 3, "kind": "bigboy", "request": "Quote builder part 3, <request>"},
            "blocker": None}
        self.assertEqual(board.roadmap_show(self.root), want)
        self.assertEqual(self.rm_cli("roadmap-show"), want)
        # No [~]/[!] step: current falls back to the first todo step; none left at all = None.
        self.roadmap(self.ROADMAP.replace("[~] S2", "[x] S2"))
        self.assertEqual(board.roadmap_show(self.root)["current"], {"p": 1, "s": 3})
        self.roadmap("ROADMAP: x\n## P1 A\n- [x] S1 standard: a\n")
        got = board.roadmap_show(self.root)
        self.assertEqual((got["current"], got["next"]), (None, None))

    def test_roadmap_show_none_without_file(self):
        self.assertIsNone(board.roadmap_show(self.root))
        self.root.mkdir(parents=True)
        self.assertIsNone(self.rm_cli("roadmap-show"))

    def test_roadmap_show_blocker_from_needs_human_child(self):
        self.roadmap()
        jobs = [{"id": self.J2, "stage": "running", "reason": None},
                {"id": "020-other", "stage": "needs-human", "reason": "not related"},
                {"id": "021-child-ok", "parent": self.J2, "stage": "build", "reason": None},
                {"id": "022-child-stuck", "parent": self.J2, "stage": "needs-human", "reason": "tests fail"}]
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))
        want = {"job": "022-child-stuck", "reason": "tests fail"}
        self.assertEqual(board.roadmap_show(self.root)["blocker"], want)
        self.assertEqual(self.rm_cli("roadmap-show")["blocker"], want)
        jobs[0].update(stage="needs-human", reason=None)  # the step's own job wins, empty reason -> ""
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))
        self.assertEqual(board.roadmap_show(self.root)["blocker"], {"job": self.J2, "reason": ""})

    def test_roadmap_write_round_trips_unchanged(self):
        self.roadmap()
        lines, _ = board.read_roadmap(self.root)
        board.write_roadmap(self.root, lines)
        self.assertEqual(self.rm_text(), self.ROADMAP)
        board.cmd_roadmap_link(self.root, 2, 1, "030-profile")
        before, after = self.ROADMAP.split("\n"), self.rm_text().split("\n")
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[13], "- [~] S1 standard 030-profile: Profile and fix the order-progress endpoint (~3.3s)")
        self.assertRegex(after[17], self.LOG_RE + r"P2 S1 started: 030-profile$")
        self.assertEqual(after[:13] + after[14:17] + after[18:], before[:13] + before[14:])

    def test_roadmap_link_marks_running(self):
        self.roadmap()
        board.cmd_roadmap_link(self.root, 1, 3, "021-qb-part-3")
        step = board.roadmap_show(self.root)["phases"][0]["steps"][2]
        self.assertEqual((step["status"], step["job"]), ("running", "021-qb-part-3"))
        self.assertIn("- [~] S3 bigboy 021-qb-part-3: Quote builder part 3, <request>\n", self.rm_text())
        logs = (board.md_section(self.rm_text(), "Log") or "").strip().splitlines()
        self.assertEqual(len(logs), 2)
        self.assertRegex(logs[1], self.LOG_RE + r"P1 S3 started: 021-qb-part-3$")
        board.roadmap_show(self.root)  # still parses
        self.assertEqual(self.jobs(), [])  # board.json job data untouched

    def test_roadmap_stop_then_link_resumes(self):
        self.roadmap()
        board.cmd_roadmap_stop(self.root, self.J2, "tests flaky on CI")
        self.assertIn(f"- [!] S2 bigboy {self.J2}:", self.rm_text())
        self.assertRegex(self.rm_text().splitlines()[-1], self.LOG_RE + r"P1 S2 stopped: tests flaky on CI$")
        self.assertEqual(board.roadmap_show(self.root)["current"], {"p": 1, "s": 2})
        before = self.rm_text()
        with self.assertRaises(SystemExit):
            board.cmd_roadmap_stop(self.root, "099-not-in-roadmap", "x")
        self.assertEqual(self.rm_text(), before)
        board.cmd_roadmap_link(self.root, 1, 2, self.J2)
        self.assertIn(f"- [~] S2 bigboy {self.J2}:", self.rm_text())
        self.assertRegex(self.rm_text().splitlines()[-1], self.LOG_RE + rf"P1 S2 started: {self.J2}$")

    def test_roadmap_link_unknown_step_errors(self):
        self.roadmap()
        for args in ((9, 1, "030-x"), (1, 9, "030-x"), (1, 3, "Bad Id"), (1, 3, "../030-x")):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                board.cmd_roadmap_link(self.root, *args)
            self.assertEqual(self.rm_text(), self.ROADMAP)

    def test_roadmap_next_marks_done_and_returns_next(self):
        self.roadmap()
        got = self.rm_cli("roadmap-next", self.J2)
        self.assertEqual(got, {"p": 1, "s": 3, "kind": "bigboy", "request": "Quote builder part 3, <request>"})
        self.assertIn(f"- [x] S2 bigboy {self.J2}:", self.rm_text())
        self.assertRegex(self.rm_text().splitlines()[-1], self.LOG_RE + rf"P1 S2 done: {self.J2}$")

    def test_roadmap_next_last_step_returns_null(self):
        self.roadmap("ROADMAP: x\n## P1 A\n- [x] S1 standard 001-a: a\n## P2 B\n- [~] S1 bigboy 002-b: b\n")
        self.assertIsNone(board.cmd_roadmap_next(self.root, "002-b"))
        self.assertIn("- [x] S1 bigboy 002-b: b\n", self.rm_text())
        self.assertRegex(self.rm_text(), r"\n## Log\n" + self.LOG_RE[1:] + r"P2 S1 done: 002-b\n")

    def test_roadmap_next_unknown_job_is_noop(self):
        self.root.mkdir(parents=True)
        self.assertIsNone(self.rm_cli("roadmap-next", "099-nope"))
        self.assertFalse((self.root / "roadmap.md").exists())
        self.roadmap()
        self.assertIsNone(board.cmd_roadmap_next(self.root, "099-nope"))
        self.assertEqual(self.rm_text(), self.ROADMAP)

    def test_roadmap_insert_renumbers_rest_of_phase(self):
        self.roadmap()
        got = self.rm_cli("roadmap-insert", "1", "2", "standard", "Extract", "the", "pricing", "hook")
        self.assertEqual(got, {"p": 1, "s": 3, "kind": "standard", "request": "Extract the pricing hook"})
        self.assertIn("## P1 Split giant files\n"
                      "- [x] S1 bigboy 011-split-quote-builder-content-tsx-13-5k-li: Split quote-builder-content.tsx, part 1\n"
                      f"- [~] S2 bigboy {self.J2}: Quote builder part 2, state and effects into hooks\n"
                      "- [ ] S3 standard: Extract the pricing hook\n"
                      "- [ ] S4 bigboy: Quote builder part 3, <request>\n"
                      "- [ ] S5 standard: Split garmentDesigner\n"
                      "## P2 Speed\n"
                      "- [ ] S1 standard: Profile and fix the order-progress endpoint (~3.3s)\n", self.rm_text())
        self.assertRegex(self.rm_text().splitlines()[-1], self.LOG_RE + r"P1 S3 inserted: Extract the pricing hook$")
        self.assertEqual(board.cmd_roadmap_insert(self.root, 2, 0, "bigboy", "Tax"),
                         {"p": 2, "s": 1, "kind": "bigboy", "request": "Tax"})
        self.assertIn("## P2 Speed\n- [ ] S1 bigboy: Tax\n- [ ] S2 standard: Profile", self.rm_text())
        self.assertEqual(board.cmd_roadmap_insert(self.root, 2, 2, "standard", "Last"),
                         {"p": 2, "s": 3, "kind": "standard", "request": "Last"})
        self.assertIn("- [ ] S2 standard: Profile and fix the order-progress endpoint (~3.3s)\n- [ ] S3 standard: Last\n",
                      self.rm_text())

    def test_roadmap_insert_bad_kind_errors(self):
        self.roadmap()
        for args in ((1, 2, "epic", "x"), (9, 0, "standard", "x"), (1, 5, "standard", "x"), (1, 2, "standard", "  ")):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                board.cmd_roadmap_insert(self.root, *args)
            self.assertEqual(self.rm_text(), self.ROADMAP)

    def test_roadmap_malformed_line_reports_line_number(self):
        bad = {12: self.ROADMAP.replace("S4 standard:", "S4 epic:"),
               14: self.ROADMAP.replace("## P2 Speed\n", "## P2 Speed\nsome note\n"),
               1: "# Roadmap\n" + self.ROADMAP,
               2: "\n" + self.ROADMAP.replace("ROADMAP:", "ROADMAP")}
        cmds = (lambda: board.roadmap_show(self.root), lambda: board.cmd_roadmap_link(self.root, 1, 3, "030-x"),
                lambda: board.cmd_roadmap_next(self.root, self.J2), lambda: board.cmd_roadmap_stop(self.root, self.J2, "r"),
                lambda: board.cmd_roadmap_insert(self.root, 1, 0, "standard", "x"))
        for n, text in bad.items():
            self.roadmap(text)
            for cmd in cmds:
                with self.subTest(line=n), self.assertRaises(SystemExit) as e:
                    cmd()
                self.assertIn(f"roadmap.md line {n}", str(e.exception.code))
                self.assertEqual(self.rm_text(), text)

    # --- artifacts (Cloud lane: the job folder a cloud session pushes to scrum-artifacts/<id>) ---
    def artifacts(self, job_id):
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "artifacts", job_id],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return sorted(out.stdout.splitlines())

    def test_artifacts_lists_clean_files(self):
        self.write("001-x/spec.md", "# Spec\nthe token flow\n")
        self.write("001-x/round-1/review-code.md", "VERDICT: PASS\n")
        self.write("001-x/followups/a.md", "# A\n")
        stale = self.write("001-x/skipped-secrets.txt", "old.md\n")
        self.assertEqual(self.artifacts("001-x"),
                         ["jobs/001-x/followups/a.md", "jobs/001-x/round-1/review-code.md", "jobs/001-x/spec.md"])
        self.assertFalse(stale.exists())  # nothing skipped: no list, and a stale one is removed

    def test_artifacts_skips_secrets_and_writes_list(self):
        self.write("001-x/build.md", "STATUS: READY\n")
        self.write("001-x/round-1/check.md", "CHECK: PASS\nexport API_TOKEN=abc123\n")
        self.write("001-x/notes.md", "key: " + "ghp_" + "A1b2C3d4E5f6G7h8I9j0" + "\n")
        self.assertEqual(self.artifacts("001-x"), ["jobs/001-x/build.md", "jobs/001-x/skipped-secrets.txt"])
        listed = (self.root / "jobs" / "001-x" / "skipped-secrets.txt").read_text().splitlines()
        self.assertEqual(sorted(listed), ["notes.md", "round-1/check.md"])

    def test_artifacts_skips_oversize_and_binary(self):
        self.write("001-x/decision.md", "VERDICT: APPROVE\n")
        big = self.root / "jobs" / "001-x" / "big.log"
        big.write_text("a" * (1024 * 1024))
        (self.root / "jobs" / "001-x" / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
        self.assertEqual(self.artifacts("001-x"), ["jobs/001-x/decision.md", "jobs/001-x/skipped-secrets.txt"])
        listed = (self.root / "jobs" / "001-x" / "skipped-secrets.txt").read_text().splitlines()
        self.assertEqual(sorted(listed), ["big.log", "shot.png"])

    def test_secret_filter_matches(self):
        for text in ("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n", "-----BEGIN OPENSSH PRIVATE KEY-----",
                     "-----BEGIN PRIVATE KEY-----",
                     "use " + "sk-" + "abcdefghijklmnop1234", "sk-" + "proj-abcdefghijklmnopqr",
                     "ghp_" + "abcdefghijklmnop1234", "gho_" + "abcdefghijklmnop1234", "ghs_" + "abcdefghijklmnop1234",
                     "github_pat_" + "11ABCDEFG0123456789_x", "xoxb-" + "1234567890-abcdefgh",
                     "xoxp-" + "1234567890abcdefgh", "AKIA" + "ABCDEFGHIJKLMNOP",
                     "DATABASE_URL=postgres://" + "admin:hunter2@db:5432/app",
                     "url postgresql://" + "u:p@localhost/x",
                     "STRIPE_SECRET_KEY=sk_live_1", "export GITHUB_TOKEN=abc", "DB_PASSWORD=pw",
                     "  OPENAI_API_KEY = 'x'", "SECRET=1"):
            with self.subTest(text=text):
                self.assertTrue(board.secret_filter(text))

    def test_secret_filter_ignores_prose(self):
        for text in ("the token flow", "KEY=", "export API_KEY=", "sk-", "sk-short", "ghp_short",
                     "AKIAshort", "postgres://localhost/app", "postgresql://user@host/db",
                     "the password field is required", "api_token=abc", "MONKEY_PATH is unrelated",
                     "Set PRIVATE KEY in the vault", "TOKEN: see docs", ""):
            with self.subTest(text=text):
                self.assertFalse(board.secret_filter(text))


class HookTest(unittest.TestCase):
    """board.py hook: a Claude Code hook event on stdin sets or clears `waiting` on this tty's active job."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "repo" / "scrum"
        (base / "noboard" / "scrum").mkdir(parents=True)
        (base / "corrupt" / "scrum").mkdir(parents=True)
        (base / "corrupt" / "scrum" / "board.json").write_text("{")
        reg = base / "projects.json"
        reg.write_text(json.dumps([str(base / "noboard"), str(base / "corrupt"), str(base / "repo")]))
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg)})
        env.start()
        self.addCleanup(env.stop)
        guard = mock.patch.object(board, "merge_refusal", return_value=None)  # PR-less fixture jobs may go done
        guard.start()
        self.addCleanup(guard.stop)
        self.old = board.cmd_new(self.root, "older job")  # same tty, older: never the one picked
        board.cmd_set(self.root, self.old, ["stage=review", "tty=ttys004"])
        self.patch(self.old, updatedAt="2000-01-01T00:00:00+00:00")
        self.job = board.cmd_new(self.root, "paused job")
        board.cmd_set(self.root, self.job, ["stage=build", "tty=ttys004"])

    def tearDown(self):
        self.tmp.cleanup()

    def patch(self, job_id, **fields):
        path = self.root / "board.json"
        data = json.loads(path.read_text())
        next(j for j in data["jobs"] if j["id"] == job_id).update(fields)
        path.write_text(json.dumps(data))

    def get(self, job_id):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id)

    def hook(self, stdin, tty="ttys004"):
        out = io.StringIO()
        with mock.patch.object(board, "caller_tty", return_value=tty), mock.patch("sys.stdin", io.StringIO(stdin)), \
                redirect_stdout(out):
            code = board.main(["hook"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "")

    def test_caller_tty_walks_up_to_first_terminal(self):
        table = {100: "   50 ??", 50: "   40 ??", 40: "    1 ttys004"}  # pid -> "ppid tty", as ps prints it
        ps = lambda args, **kw: subprocess.CompletedProcess(args, 0, table.get(int(args[-1]), "") + "\n", "")
        with mock.patch.object(board.os, "getppid", return_value=100), mock.patch.object(board.subprocess, "run", ps):
            self.assertEqual(board.caller_tty(), "ttys004")
            table[40] = "    1 ??"
            self.assertEqual(board.caller_tty(), "??")
            table.update({n: f"{n + 1} ??" for n in range(100, 200)})  # a long chain stops after ~10 levels
            table[50] = "   40 ??"
            calls = []
            with mock.patch.object(board.subprocess, "run", lambda a, **kw: calls.append(a) or ps(a, **kw)):
                table[100] = "  101 ??"
                self.assertEqual(board.caller_tty(), "??")
            self.assertLessEqual(len(calls), 10)

    def test_hook_permission_sets_waiting(self):
        self.patch(self.job, updatedAt="2001-01-01T00:00:00+00:00")
        self.hook(json.dumps({"hook_event_name": "PermissionRequest", "tool_name": "Bash",
                              "tool_input": {"command": "npm test " + "x" * 100}}))
        job = self.get(self.job)
        self.assertEqual(job["waiting"], "permission: Bash: npm test " + "x" * 71)
        self.assertNotEqual(job["updatedAt"], "2001-01-01T00:00:00+00:00")
        self.assertNotIn("waiting", self.get(self.old))
        self.hook(json.dumps({"hook_event_name": "PermissionRequest", "tool_name": "Write", "tool_input": {"command": "x"}}))
        self.assertEqual(self.get(self.job)["waiting"], "permission: Write")

    def test_hook_question_sets_waiting(self):
        self.hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                              "tool_input": {"questions": [{"question": "Which lane?"}, {"question": "no"}]}}))
        self.assertEqual(self.get(self.job)["waiting"], "question: Which lane?")
        self.hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "tool_input": {}}))
        self.assertEqual(self.get(self.job)["waiting"], "question")

    def test_hook_stop_sets_waiting(self):
        self.hook(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "\n  \nShip it?\nMore text"}))
        self.assertEqual(self.get(self.job)["waiting"], "reply needed: Ship it?")
        self.hook(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "  "}))
        self.assertEqual(self.get(self.job)["waiting"], "reply needed")
        self.hook(json.dumps({"hook_event_name": "Stop"}))
        self.assertEqual(self.get(self.job)["waiting"], "reply needed")

    def test_hook_prompt_clears_waiting(self):
        self.patch(self.job, waiting="question: Which lane?")
        self.hook(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "fast"}))
        self.assertIsNone(self.get(self.job)["waiting"])
        self.patch(self.job, waiting="permission: Bash")
        self.hook(json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Read"}))
        self.assertIsNone(self.get(self.job)["waiting"])

    def test_hook_posttool_noop_does_not_write(self):
        self.patch(self.job, waiting=None, updatedAt="2001-01-01T00:00:00+00:00")
        path = self.root / "board.json"
        os.utime(path, (1_000_000, 1_000_000))
        self.hook(json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash"}))
        self.assertEqual(path.stat().st_mtime, 1_000_000)
        self.assertEqual(self.get(self.job)["updatedAt"], "2001-01-01T00:00:00+00:00")

    def assert_untouched(self, stdin, tty="ttys004"):
        path = self.root / "board.json"
        before = path.read_text()
        os.utime(path, (1_000_000, 1_000_000))
        self.hook(stdin, tty)
        self.assertEqual(path.read_text(), before)
        self.assertEqual(path.stat().st_mtime, 1_000_000)

    def test_hook_ignores_bad_input(self):
        stop = json.dumps({"hook_event_name": "Stop"})
        for stdin in ("", "{", "[]", json.dumps({"hook_event_name": "SessionStart"}),
                      json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash"})):
            self.assert_untouched(stdin)
        for tty in ("??", "", "ttys4; rm", "/dev/ttys004"):
            self.assert_untouched(stop, tty)
        with mock.patch.object(board, "caller_tty", side_effect=OSError("no ps")), mock.patch("sys.stdin", io.StringIO(stop)):
            self.assertEqual(board.main(["hook"]), 0)
        self.assertNotIn("waiting", self.get(self.job))

    def test_hook_funk_only_when_notifier_disabled(self):
        ask = {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion", "tool_input": {}}
        cases = {"1": True, "yes": True, "TRUE": True, None: False, "0": False, "false": False, "FALSE": False, "": False}
        for value, funk in cases.items():
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_NOTIFIER_DISABLE"}
            if value is not None:
                env["CLAUDE_NOTIFIER_DISABLE"] = value
            for tty in ("ttys004", "ttys099"):  # ttys099 matches no job
                with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(board, "play") as play, \
                        mock.patch.object(board, "sound", lambda kind: f"/clips/{kind}"):
                    board.cmd_hook(ask, tty)
                    board.cmd_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash"}, tty)
                    board.cmd_hook({"hook_event_name": "Stop"}, tty)
                self.assertEqual(play.call_args_list, [mock.call("/clips/question")] if funk else [],
                                 (value, tty))
        self.assertEqual(self.get(self.job)["waiting"], "reply needed")

    def test_hook_ignores_inactive_and_other_tty(self):
        board.cmd_set(self.root, self.old, ["stage=needs-human"])
        board.cmd_set(self.root, self.job, ["tty=ttys005"])
        done = board.cmd_new(self.root, "done job")
        board.cmd_set(self.root, done, ["stage=done", "tty=ttys004"])
        self.assert_untouched(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "hi"}))
        self.hook(json.dumps({"hook_event_name": "Stop"}), "ttys005")
        self.assertEqual(self.get(self.job)["waiting"], "reply needed")
        self.assertNotIn("waiting", self.get(self.old))


class DigestVerifyTest(unittest.TestCase):
    """board.py digest-verify: a job whose rules-file diff is exactly its cited, queued digest edits needs no human."""

    BUILDER = "# Builder\n\nRule one.\n\nRule two.\n"
    PLANNER = "# Planner\n\nPlan it.\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        self.root = self.repo / "scrum"
        self.wt = base / "wt"
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(base / "no-projects.json"),
                                           "SCRUM_USAGE": str(base / "no-usage.json")})
        env.start()
        self.addCleanup(env.stop)
        (self.repo / "agents").mkdir(parents=True)
        (self.repo / "agents" / "scrum-builder.md").write_text(self.BUILDER)
        (self.repo / "agents" / "scrum-planner.md").write_text(self.PLANNER)
        (self.repo / "README.md").write_text("readme\n")
        self.git(self.repo, "init", "-q", "-b", "main")
        self.git(self.repo, "add", "agents", "README.md")
        self.git(self.repo, "commit", "-q", "-m", "base")
        self.job = board.cmd_new(self.root, "Apply digest edits")
        self.git(self.repo, "worktree", "add", "-q", "-b", f"scrum/{self.job}", str(self.wt))
        board.cmd_set(self.root, self.job, [f"worktree={self.wt}", "base=main"])

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, cwd, *args):
        subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True)

    def proposals(self, digest, *props):
        d = self.root / "digests" / digest
        d.mkdir(parents=True, exist_ok=True)
        (d / "proposals.json").write_text(json.dumps({"proposals": [
            {"target": str(self.repo / "agents" / "scrum-builder.md"), "why": "w", "status": "queued", **p}
            for p in props]}))

    def feature(self, text):
        (self.root / "jobs" / self.job / "feature.md").write_text(text)

    def commit(self, rel, text):
        (self.wt / rel).write_text(text)
        self.git(self.wt, "add", rel)
        self.git(self.wt, "commit", "-q", "-m", "edit")

    def run_cli(self, *extra):
        out = io.StringIO()
        with redirect_stdout(out):
            code = board.main(["--dir", str(self.root), "digest-verify", self.job, *extra])
        return code or 0, json.loads(out.getvalue())

    def assert_fails(self, needle=None, *extra):
        code, out = self.run_cli(*extra)
        self.assertEqual(code, 1, out)
        self.assertFalse(out["ok"])
        if needle:
            self.assertIn(needle, out["error"])
        return out

    def test_digest_verify_passes_exact_replacement(self):
        self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper."},
                       {"id": "p2", "old": "Rule two.\n", "new": "Rule two.\n\nRule three.\n"})
        self.feature("Apply digest 006 p1 to agents/scrum-builder.md: see x\n\nAlso digest 006 p2 and digest 006 p1.\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n\nRule three.\n")
        self.commit("README.md", "readme changed too\n")  # non-rules files are ignored
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(out, {"ok": True, "files": ["agents/scrum-builder.md"],
                               "proposals": ["repo digest 006 p1", "repo digest 006 p2"]})

    def test_digest_verify_passes_shared_anchor_any_order(self):
        # Both append after the same anchor; the HEAD text is p2's line first, so only the reverse order reproduces it.
        self.proposals("006", {"id": "p1", "old": "Rule one.\n", "new": "Rule one.\nAdded A.\n"},
                       {"id": "p2", "old": "Rule one.\n", "new": "Rule one.\nAdded B.\n"})
        self.feature("Apply digest 006 p1 and digest 006 p2 to agents/scrum-builder.md\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one.\nAdded A.\nAdded B.\n\nRule two.\n")
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["proposals"], ["repo digest 006 p1", "repo digest 006 p2"])

    def test_digest_verify_fails_extra_line(self):
        self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper."})
        self.feature("Apply digest 006 p1 to agents/scrum-builder.md\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\nSneaky extra.\n")
        self.assert_fails("agents/scrum-builder.md")

    def test_digest_verify_fails_other_file(self):
        self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper."})
        self.feature("Apply digest 006 p1 to agents/scrum-builder.md\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
        self.commit("agents/scrum-planner.md", "# Planner\n\nPlan it well.\n")
        self.assert_fails("agents/scrum-planner.md")

    def test_digest_verify_fails_when_target_unchanged(self):
        self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper."},
                       {"id": "p2", "old": "Plan it.", "new": "Plan it well.",
                        "target": str(self.repo / "agents" / "scrum-planner.md")})
        self.feature("Apply digest 006 p1 and digest 006 p2\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
        self.assert_fails("agents/scrum-planner.md")

    def test_digest_verify_fails_unapproved_pid(self):
        self.feature("Apply digest 006 p1 to agents/scrum-builder.md\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
        for status in ("pending", "rejected", "applied", "approved"):
            with self.subTest(status=status):
                self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper.", "status": status})
                self.assert_fails("p1")
        with self.subTest("unknown pid"):
            self.proposals("006", {"id": "p9", "old": "Rule one.", "new": "Rule one, sharper."})
            self.assert_fails("p1")
        with self.subTest("skill"):
            self.proposals("006", {"id": "p1", "old": "", "new": "---\nname: x\n---\n", "kind": "skill"})
            self.assert_fails("p1")
        with self.subTest("target outside the repo"):
            self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper.",
                                   "target": str(Path(self.tmp.name) / "elsewhere" / "agents" / "scrum-builder.md")})
            self.assert_fails("p1")
        with self.subTest("relative target"):
            # From the repo root the relative path would resolve inside the repo; it must still be rejected.
            self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper.",
                                   "target": "agents/scrum-builder.md"})
            cwd = os.getcwd()
            os.chdir(self.repo)
            try:
                out = self.assert_fails("p1")
            finally:
                os.chdir(cwd)
            self.assertIn("not an absolute path", out["error"])

    def test_digest_verify_flags_override_board(self):
        self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper."})
        self.feature("Apply digest 006 p1 to agents/scrum-builder.md\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
        with self.subTest("board worktree unset"):
            board.cmd_set(self.root, self.job, ["worktree="])
            code, out = self.run_cli("--worktree", str(self.wt), "--base", "main")
            self.assertEqual(code, 0, out)
            self.assertEqual(out["files"], ["agents/scrum-builder.md"])
        with self.subTest("board worktree lacks the edit"):
            wt2 = Path(self.tmp.name) / "wt2"
            self.git(self.repo, "worktree", "add", "-q", "-b", "other", str(wt2))
            board.cmd_set(self.root, self.job, [f"worktree={wt2}"])
            self.assert_fails("no rules file")
            code, out = self.run_cli("--worktree", str(self.wt))
            self.assertEqual(code, 0, out)
            self.assertEqual(out["proposals"], ["repo digest 006 p1"])

    def test_digest_verify_base_flag_sets_range(self):
        self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper."})
        self.feature("Apply digest 006 p1 to agents/scrum-builder.md\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
        self.git(self.repo, "branch", "has-edit", f"scrum/{self.job}")
        self.assert_fails("the diff changes no rules file", "--base", "has-edit")
        code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["files"], ["agents/scrum-builder.md"])

    def test_digest_verify_empty_or_bad_flag_fails(self):
        self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper."})
        self.feature("Apply digest 006 p1 to agents/scrum-builder.md\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
        for flag, word in (("--worktree", "no worktree"), ("--base", "no base")):
            with self.subTest(flag=flag):
                out = self.assert_fails(word, flag, "")
                self.assertEqual(out["ok"], False)
        with self.subTest("dash base"):
            self.assert_fails("bad base", "--base=-x")
        code, out = self.run_cli()  # the board's own values still pass
        self.assertEqual(code, 0, out)

    def test_digest_verify_fails_missing_digest(self):
        self.feature("Apply digest 007 p1 to agents/scrum-builder.md\n")
        self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
        self.assert_fails("007")
        (self.root / "digests" / "007").mkdir(parents=True)
        self.assert_fails("007")

    def test_digest_verify_fails_without_citations(self):
        self.proposals("006", {"id": "p1", "old": "Rule one.", "new": "Rule one, sharper."})
        with self.subTest("no citation"):
            self.feature("Sharpen the builder's first rule\n")
            self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
            self.assert_fails("cites no digest proposal")
        self.feature("Apply digest 006 p1 to agents/scrum-builder.md\n")
        with self.subTest("no worktree"):
            board.cmd_set(self.root, self.job, ["worktree="])
            self.assert_fails("worktree")
        with self.subTest("no base"):
            board.cmd_set(self.root, self.job, [f"worktree={self.wt}", "base="])
            self.assert_fails("base")
        with self.subTest("no rules file changed"):
            other = board.cmd_new(self.root, "Readme only")
            wt2 = Path(self.tmp.name) / "wt2"
            self.git(self.repo, "worktree", "add", "-q", "-b", f"scrum/{other}", str(wt2))
            board.cmd_set(self.root, other, [f"worktree={wt2}", "base=main"])
            (self.root / "jobs" / other / "feature.md").write_text("Apply digest 006 p1 to agents/scrum-builder.md\n")
            (wt2 / "README.md").write_text("changed\n")
            self.git(wt2, "commit", "-q", "-am", "readme")
            self.job = other
            self.assert_fails("no rules file")

    def test_digest_verify_finds_a_registered_projects_digest(self):
        other = Path(self.tmp.name) / "onewitharts"
        (other / "scrum" / "digests" / "003").mkdir(parents=True)
        (other / "scrum" / "digests" / "003" / "proposals.json").write_text(json.dumps({"proposals": [
            {"id": "p4", "target": str(self.repo / "agents" / "scrum-builder.md"), "why": "w", "status": "queued",
             "old": "Rule one.", "new": "Rule one, sharper."}]}))
        reg = Path(self.tmp.name) / "projects.json"
        reg.write_text(json.dumps([str(other)]))
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg)}):
            self.feature("Merged: onewitharts digest 003 p4\n")
            self.commit("agents/scrum-builder.md", "# Builder\n\nRule one, sharper.\n\nRule two.\n")
            code, out = self.run_cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["proposals"], ["onewitharts digest 003 p4"])


class MoveRatioTest(unittest.TestCase):
    """board.py move-ratio: the share of a job's added lines that git marks as moved (SKILL.md Review MOVE_ONLY)."""

    BLOCK = "".join(f"def helper_{i}(value):  # moved helper number {i}\n" for i in range(20))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        self.root = base / "scrum"
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(base / "no-projects.json"),
                                           "SCRUM_USAGE": str(base / "no-usage.json")})
        env.start()
        self.addCleanup(env.stop)
        self.repo.mkdir()
        (self.repo / "a.py").write_text("# a\n" + self.BLOCK + "# end a\n")
        (self.repo / "b.py").write_text("# b\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", "a.py", "b.py")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "work")
        self.job = board.cmd_new(self.root, "Move helpers")
        board.cmd_set(self.root, self.job, [f"worktree={self.repo}", "base=main"])

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True)

    def commit(self, files):
        for rel, text in files.items():
            (self.repo / rel).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "edit")

    def move(self, extra=""):
        self.commit({"a.py": "# a\n# end a\n", "b.py": "# b\n" + self.BLOCK + extra})

    def run_cli(self, job=None):
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "move-ratio", job or self.job],
                           capture_output=True, text=True, timeout=60)
        self.assertNotIn("Traceback", r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1, r.stdout)
        return r.returncode, json.loads(lines[0])

    def test_pure_move_is_ratio_one(self):
        self.move()
        self.assertEqual(self.run_cli(), (0, {"added": 20, "moved": 20, "ratio": 1.0}))

    def test_mixed_diff_ratio(self):
        self.move("".join(f"brand_new_value_{i} = compute_something_fresh({i})\n" for i in range(20)))
        self.assertEqual(self.run_cli(), (0, {"added": 40, "moved": 20, "ratio": 0.5}))

    def test_ignores_user_color_config(self):
        self.git("config", "color.diff.newMoved", "magenta")
        self.git("config", "color.diff.new", "bold cyan")
        self.git("config", "color.diff.meta", "green")
        self.git("config", "diff.colorMoved", "no")
        self.move()
        self.assertEqual(self.run_cli(), (0, {"added": 20, "moved": 20, "ratio": 1.0}))

    def test_no_added_lines_is_zero(self):
        self.commit({"a.py": "# a\n# end a\n"})
        self.assertEqual(self.run_cli(), (0, {"added": 0, "moved": 0, "ratio": 0.0}))

    def test_missing_worktree_errors(self):
        self.move()
        cases = {"no worktree": (["worktree="], "no worktree"), "no base": (["base="], "no base"),
                 "dash base": (["base=--output=/tmp/x"], "bad base"), "git fails": (["base=no-such-branch"], "failed")}
        for label, (pairs, needle) in cases.items():
            with self.subTest(label):
                board.cmd_set(self.root, self.job, [f"worktree={self.repo}", "base=main"])
                board.cmd_set(self.root, self.job, pairs)
                code, out = self.run_cli()
                self.assertEqual(code, 1, out)
                self.assertFalse(out["ok"])
                self.assertIn(needle, out["error"])
        with self.subTest("unknown id"):
            code, out = self.run_cli("999-no-such-job")
            self.assertEqual(code, 1, out)
            self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
