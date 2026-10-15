import io, json, os, subprocess, sys, tempfile, unittest
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
        p = self.child(parent)
        self.assertEqual(p["stage"], "needs-human")
        self.assertTrue(p["reason"].startswith(f"bigboy blocked: {c1}, {c2}. Fix: "), p["reason"])
        board.cmd_set(self.root, c1, ["stage=done", "reason="])  # Trevor approved it and it merged
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c3])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_ready_leaves_other_parent_stops_alone(self):
        parent, kids = self.three()
        board.cmd_set(self.root, parent, ["stage=needs-human", "reason=bigboy off track: x. Fix: y"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("needs-human", "bigboy off track: x. Fix: y"))
        self.assertEqual([self.child(k)["stage"] for k in kids], ["waiting"] * 3)

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
            board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"])
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

    def test_runall_ready_marks_parent_blocked_and_resumes(self):
        parent, (a, b, c) = self.runall(3)
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, a, ["stage=needs-human", "reason=blocked: x. Fix: y"])
        board.cmd_abort(self.root, b, requeue=False)
        board.cmd_set(self.root, c, ["stage=done"])
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"], out["all_merged"]), ([], 0, False))
        p = self.child(parent)
        self.assertEqual(p["stage"], "needs-human")
        self.assertTrue(p["reason"].startswith(f"run-all blocked: {a}. Fix: "), p["reason"])
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
                 "## Diverged\n```\n- example\n```\n- a → b — c\n": True}
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
                  for s in ("spec", "merging", "running", "waiting", "needs-human", "done", "aborted")]
        before = self.jobs()
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: job["id"] == live), [])
        self.assertEqual(self.jobs(), before)
        stuck = self.aged("Stuck", 31, stage="approve")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: job["id"] == live), [stuck])
        flagged = self.jobs()
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: job["id"] == live), [])
        self.assertEqual(self.jobs(), flagged)
        self.assertEqual([self.get(j)["stage"] for j in (fresh, live, paused)], ["review", "build", "check"])
        self.assertEqual(len(others), 7)

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


if __name__ == "__main__":
    unittest.main()
