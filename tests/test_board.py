import json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
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
        for lane in ("fast", "standard", "debug", "bigboy"):
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

    def test_next_skips_bigboy_children(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Dark mode\n")
        parent, kids = self.three()
        self.assertEqual(board.cmd_next(self.root), {"id": "005-dark-mode", "feature": "Dark mode"})
        self.assertEqual(board.cmd_next(self.root), {"id": None, "feature": None})
        self.assertEqual([self.child(k)["stage"] for k in kids], ["waiting"] * 3)
        self.assertEqual(self.child(parent)["stage"], "running")

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


if __name__ == "__main__":
    unittest.main()
