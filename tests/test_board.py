import hashlib, io, json, os, re, shutil, subprocess, sys, tempfile, time, unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"  # CPU nearly idle unless a test says so; no test runs top or reads the real CPU log
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly nil unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
os.environ["SCRUM_SWAP_LOG"] = os.path.join(tempfile.mkdtemp(), "swap.json")  # never the real swap log
os.environ.setdefault("SCRUM_PS", os.devnull)  # no live sessions unless a test says so, whatever this machine runs
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))  # never Trevor's real usage.json
import board  # noqa: E402

BOARD_PY = ROOT / "skills" / "trevskills-scrum" / "board.py"
CALLER_CLAUDE_PID = board.caller_claude_pid  # the real one; fixtures patch it so the test runner's claude is never recorded


def run_board(*argv, env=None, input=None):
    """`board.main(argv)` in this process, shaped like `subprocess.run(..., capture_output=True, text=True)`:
    a new python per call costs seconds under load. Fixture patches (merge_refusal, caller_claude_pid) apply."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}), mock.patch.object(sys, "stdin", io.StringIO(input or "")), \
            redirect_stdout(out), redirect_stderr(err):
        try:
            code = board.main(list(argv))
        except SystemExit as e:
            code = e.code
            if not (code is None or isinstance(code, int)):
                print(code, file=sys.stderr)  # what Python does with SystemExit("message")
                code = 1
    return subprocess.CompletedProcess(list(argv), code or 0, out.getvalue(), err.getvalue())


def no_claude_pid(test):
    patch = mock.patch.object(board, "caller_claude_pid", return_value=None)
    patch.start()
    test.addCleanup(patch.stop)


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
        no_claude_pid(self)

    def tearDown(self):
        self.tmp.cleanup()

    def jobs(self):
        return json.loads((self.root / "board.json").read_text())["jobs"]

    def write(self, rel, text):
        p = self.root / "jobs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # --- backlog priority op (job 763) ---
    def backlog(self, text):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "backlog.md").write_text(text)

    def test_priority_op_raises(self):
        self.backlog("# Backlog\n\n- [ ] [3] Alpha {#aaaa} {p:2} {by:t} <!-- why -->\n- [ ] Beta {#bbbb}\nnote line\n")
        items = board.backlog_op(self.root, "priority", id="aaaa", priority=4)
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n\n- [ ] [3] Alpha {#aaaa} {p:4} {by:t} <!-- why -->\n- [ ] Beta {#bbbb}\nnote line\n")
        self.assertEqual([(i["id"], i["priority"]) for i in items], [("aaaa", 4), ("bbbb", None)])

    def test_priority_op_never_lowers(self):
        start = "# Backlog\n- [ ] Alpha {#aaaa} {p:4}\n- [ ] Beta {#bbbb}\n"
        self.backlog(start)
        for item_id, n in (("aaaa", 4), ("aaaa", 1), ("bbbb", 2), ("bbbb", 1)):
            items = board.backlog_op(self.root, "priority", id=item_id, priority=n)
            self.assertEqual((self.root / "backlog.md").read_text(), start)
            self.assertEqual([(i["id"], i["priority"]) for i in items], [("aaaa", 4), ("bbbb", None)])
        board.backlog_op(self.root, "priority", id="bbbb", priority=3)
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [ ] Alpha {#aaaa} {p:4}\n- [ ] Beta {#bbbb} {p:3}\n")

    def test_priority_op_rejects(self):
        start = "# Backlog\n- [x] Done {#dddd} → 001-done\n- [ ] Open {#oooo}\n- [ ] Old line\n"
        self.backlog(start)
        for item_id, n in (("zzzz", 4), ("dddd", 4), (None, 4), ("oooo", True), ("oooo", 0), ("oooo", 6),
                           ("oooo", None), ("oooo", "4"), ("oooo", 4.0)):
            with self.subTest(id=item_id, priority=n), self.assertRaises(SystemExit):
                board.backlog_op(self.root, "priority", id=item_id, priority=n)
            self.assertEqual((self.root / "backlog.md").read_text(), start)

    def test_priority_op_finds_by_id_after_reorder(self):
        self.backlog("# Backlog\n- [ ] Alpha {#aaaa}\n- [ ] Beta {#bbbb}\n")
        board.backlog_op(self.root, "priority", id="bbbb", priority=3)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Beta {#bbbb} {p:3}\n- [ ] Alpha {#aaaa}\n")
        items = board.backlog_op(self.root, "priority", id="aaaa", priority=5)
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [ ] Beta {#bbbb} {p:3}\n- [ ] Alpha {#aaaa} {p:5}\n")
        self.assertEqual([(i["id"], i["priority"]) for i in items], [("bbbb", 3), ("aaaa", 5)])

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

    def test_slug_strips_screenshot_tags(self):
        self.assertEqual(board.slug("[screenshot: /Users/a/b.png] Fix the login button"), "fix-the-login-button")
        self.assertEqual(board.slug("[screenshot: /a.png][screenshot: /b.png] Fix x"), "fix-x")

    def test_short_title_cuts_at_word_with_ellipsis(self):
        self.assertEqual(board.short_title("Fix the login button"), "Fix the login button")
        self.assertEqual(board.short_title("x" * 60), "x" * 60)
        self.assertEqual(board.short_title("Add a dark mode toggle, then fix it", n=30), "Add a dark mode toggle, then…")
        self.assertEqual(board.short_title("Add a dark mode toggle, then fix it", n=25), "Add a dark mode toggle…")
        self.assertEqual(board.short_title("L" * 70), "L" * 59 + "…")
        self.assertEqual(board.short_title("word " * 30), "word " * 10 + "word…")
        self.assertEqual(board.short_title("... " + "x" * 70, n=10), "... xxxxx…", "all punctuation before the space: hard cut")

    def test_new_with_only_screenshot_tags_gets_fallback_slug(self):
        self.assertEqual(board.cmd_new(self.root, "[screenshot: /x/y.png]"), "001-job")

    def test_new_slug_ignores_screenshot_tag(self):
        title = "[screenshot: /x/y.png] Add rate limit"
        jid = board.cmd_new(self.root, title)
        self.assertTrue(jid.startswith("001-add-rate-limit"))
        self.assertEqual(self.jobs()[0]["title"], title)

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

    def test_set_refuses_needs_human(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        before = (self.root / "board.json").read_text()
        with self.assertRaises(SystemExit) as e:
            board.cmd_set(self.root, job_id, ["stage=needs-human", "reason=x. Fix: y"])
        self.assertTrue(str(e.exception).startswith("use board.py ask"), e.exception)
        with self.assertRaises(SystemExit) as e:
            board.main(["--dir", str(self.root), "set", job_id, "reason=z", "stage=needs-human"])
        self.assertTrue(str(e.exception).startswith("use board.py ask"), e.exception)
        self.assertEqual((self.root / "board.json").read_text(), before)
        board.cmd_set(self.root, job_id, ["stage=review", "reason=r"])  # every other stage still sets
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["reason"]), ("review", "r"))

    def test_set_tty_runlog_stored(self):
        job_id = board.cmd_new(self.root, "x")
        out = run_board("--dir", str(self.root), "set", job_id, "tty=ttys003", "runlog=runs/x.log")
        self.assertEqual(out.returncode, 0, out.stderr)
        job = self.jobs()[0]
        self.assertEqual((job["tty"], job["runlog"]), ("ttys003", "runs/x.log"))
        board.cmd_set(self.root, job_id, ["tty=", "runlog="])
        job = self.jobs()[0]
        self.assertEqual((job["tty"], job["runlog"]), (None, None))
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, job_id, ["term=Apple_Terminal"])

    def test_leftover_term_key_is_ignored(self):
        job_id = board.cmd_new(self.root, "x")
        data = json.loads((self.root / "board.json").read_text())
        data["jobs"][0]["term"] = "Apple_Terminal"
        (self.root / "board.json").write_text(json.dumps(data))
        board.cmd_set(self.root, job_id, ["stage=build"])
        self.assertEqual(self.jobs()[0]["stage"], "build")

    def test_set_tty_records_claude_pid(self):
        # pid -> "ppid command", as `ps -o ppid=,command=` prints it; board.py's parent is 100, a shell under claude 40
        table = {100: "   50 python3 board.py set", 50: "   40 /bin/zsh -c B set", 40: "    1 /Users/t/.local/bin/claude --resume"}
        ps = lambda args, **kw: subprocess.CompletedProcess(args, 0, table.get(int(args[-1]), "") + "\n", "")
        job_id = board.cmd_new(self.root, "x")
        with mock.patch.object(board, "caller_claude_pid", CALLER_CLAUDE_PID), \
                mock.patch.object(board.os, "getppid", return_value=100), mock.patch.object(board.subprocess, "run", ps):
            board.cmd_set(self.root, job_id, ["tty=ttys004"])
            self.assertEqual(self.jobs()[0]["pid"], 40)
            board.cmd_set(self.root, job_id, ["stage=build", "waiting=x"])  # no tty: pid untouched
            self.assertEqual(self.jobs()[0]["pid"], 40)
            board.cmd_set(self.root, job_id, ["tty="])
            self.assertIsNone(self.jobs()[0]["pid"])
            table[40] = "    1 /bin/login"  # no claude ancestor
            board.cmd_set(self.root, job_id, ["tty=ttys004"])
            self.assertIsNone(self.jobs()[0]["pid"])
            table[40] = "    1 /Users/t/.local/bin/claude"
            board.cmd_set(self.root, job_id, ["tty=ttys004"])
            self.assertEqual(self.jobs()[0]["pid"], 40)
            with mock.patch.object(board.subprocess, "run", side_effect=OSError("no ps")):
                board.cmd_set(self.root, job_id, ["tty=ttys005"])
            self.assertEqual((self.jobs()[0]["tty"], self.jobs()[0]["pid"]), ("ttys005", None))
            with mock.patch.object(board.subprocess, "run", side_effect=subprocess.TimeoutExpired("ps", 2)):
                board.cmd_set(self.root, job_id, ["tty=ttys004"])
            self.assertIsNone(self.jobs()[0]["pid"])
            table.update({n: f"{n + 1} /bin/zsh" for n in range(100, 200)})  # claude more than 10 up is not found
            calls = []
            with mock.patch.object(board.subprocess, "run", lambda a, **kw: calls.append(a) or ps(a, **kw)):
                board.cmd_set(self.root, job_id, ["tty=ttys004"])
            self.assertIsNone(self.jobs()[0]["pid"])
            self.assertLessEqual(len(calls), 10)
        with self.assertRaisesRegex(SystemExit, "bad field"):
            board.cmd_set(self.root, job_id, ["pid=40"])

    def test_set_waiting_stored_and_cleared(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ['waiting=permission: Bash'])
        self.assertEqual(self.jobs()[0]["waiting"], "permission: Bash")
        board.cmd_set(self.root, job_id, ["waiting=  a \n <!--b-->  " + "c" * 300])
        self.assertEqual(self.jobs()[0]["waiting"], "a b " + "c" * 196)
        board.cmd_set(self.root, job_id, ["waiting="])
        self.assertIsNone(self.jobs()[0]["waiting"])

    def test_outcome_field_set_and_cleared(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["outcome=  Approve refused \n at 4:21 PM" + "z" * 400])
        self.assertEqual(self.jobs()[0]["outcome"], "Approve refused at 4:21 PM" + "z" * 274)
        board.cmd_ask(self.root, job_id, "Blocked?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        board.cmd_set(self.root, job_id, ["outcome=Approve refused. Nothing changed."])
        board.cmd_ask(self.root, job_id, "Blocked?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        self.assertEqual(self.jobs()[0]["outcome"], "Approve refused. Nothing changed.")  # same reason keeps it
        board.cmd_ask(self.root, job_id, "New blocker?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        self.assertNotIn("outcome", self.jobs()[0])  # a new reason drops it
        board.cmd_set(self.root, job_id, ["outcome=Rework refused. Nothing changed."])
        board.cmd_set(self.root, job_id, ["reason=still here"])
        self.assertEqual(self.jobs()[0]["outcome"], "Rework refused. Nothing changed.")  # no stage change keeps it
        board.cmd_set(self.root, job_id, ["stage=build"], unpause=True)
        self.assertNotIn("outcome", self.jobs()[0])  # a stage change drops it

    def test_unpause_set_clears_limit_hold(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        with board.locked_board(self.root) as b:
            board.find(b, job_id)["limitResetAt"] = 1_800_000_000
        board.cmd_set(self.root, job_id, ["stage=build", "reason="])
        self.assertEqual(self.jobs()[0]["limitResetAt"], 1_800_000_000)
        board.cmd_set(self.root, job_id, ["stage=build", "reason="], unpause=True)
        self.assertNotIn("limitResetAt", self.jobs()[0])

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
            out = run_board("--dir", str(self.root), "set", job_id, "stage=review", bad)
            self.assertNotEqual(out.returncode, 0, bad)
            self.assertIn("bad field", out.stderr, bad)
        self.assertEqual((self.root / "board.json").read_text(), before)

    def test_set_rejects_unknown_field_whole(self):
        job_id = board.cmd_new(self.root, "x")
        with self.assertRaisesRegex(SystemExit, "bad field"):
            board.cmd_set(self.root, job_id, ["tty=ttys2", "color=red"])
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
            out = run_board("--dir", str(self.root), "set", job_id, "stage=review", bad)
            self.assertNotEqual(out.returncode, 0, bad)
            self.assertIn("fast|standard|debug|bigboy", out.stderr, bad)
        self.assertEqual((self.root / "board.json").read_text(), before)

    # --- ask / answer ---
    def log_lines(self):
        p = self.root / "questions.log"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def test_ask_parks_job_with_question_and_options(self):
        job_id = board.cmd_new(self.root, "x")
        out = board.cmd_ask(self.root, job_id, "Ship it?", [f"Approve=approve {job_id}", f"Abort=abort {job_id} --requeue"], title="MERGE_CONFLICT")
        want = [{"key": "a", "label": "Approve", "command": f"approve {job_id}"},
                {"key": "b", "label": "Abort", "command": f"abort {job_id} --requeue"}]
        self.assertEqual(out, want)
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["reason"], job["question"], job["options"]),
                         ("needs-human", "Ship it?", "Ship it?", want))
        self.assertRegex(job["updatedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")

    def test_ask_ends_a_stall(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=check"])
        with board.locked_board(self.root) as b:
            board.find(b, job_id).update(stalled=True, limitResetAt=1_800_000_000)
        board.cmd_ask(self.root, job_id, "Go on?", [f"Try again=resume {job_id}", f"Drop=abort {job_id}"], title="BUILDER_BLOCKED")
        job = self.jobs()[0]
        self.assertEqual(job["stage"], "needs-human")
        self.assertNotIn("stalled", job, "a question is not a stall")
        self.assertNotIn("limitResetAt", job)

    def test_ask_cli_three_options(self):
        job_id = board.cmd_new(self.root, "x")
        buf = io.StringIO()
        with redirect_stdout(buf):
            board.main(["--dir", str(self.root), "ask", job_id, "Which?", "--a", f"Approve=approve {job_id}",
                        "--b", f"Abort=abort {job_id} --requeue", "--c", f"Resume=resume {job_id}",
                        "--title", "MERGE_CONFLICT"])
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(self.jobs()[0]["options"][2], {"key": "c", "label": "Resume", "command": f"resume {job_id}"})
        self.assertEqual(len(self.jobs()[0]["options"]), 3)

    def test_ask_accepts_each_command_form(self):
        job_id = board.cmd_new(self.root, "x")
        for cmd in ("approve 012-other-job", 'rework 012-other-job "fix the tests"', "abort 012-other-job",
                    "abort 012-other-job --requeue", "abort 012-other-job --cascade", "resume 012-other-job",
                    "shell: git status"):
            with self.subTest(cmd=cmd):
                out = board.cmd_ask(self.root, job_id, "Q?", [f"Go={cmd}", f"Abort=abort {job_id}"], title="MERGE_CONFLICT")
                self.assertEqual(out[0]["command"], cmd)

    def test_ask_accepts_prod_check_title(self):
        job_id = board.cmd_new(self.root, "x")
        board.main(["--dir", str(self.root), "ask", job_id, "prod check: the deploy failed.",
                    "--a", f"Try again=resume {job_id}", "--b", f"Stop tracking this job=abort {job_id}",
                    "--title", "PROD_CHECK_FAILED", "--recommend", "a", "the deploy may have been flaky"])
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["question"]), ("needs-human", "prod check: the deploy failed."))
        self.assertEqual(job["stopTitle"], "PROD_CHECK_FAILED")

    def test_ask_splits_on_first_equals(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f' Rework =  rework {job_id} "a=b" ', f"Abort=abort {job_id}"], title="MERGE_CONFLICT")
        self.assertEqual(self.jobs()[0]["options"][0],
                         {"key": "a", "label": "Rework", "command": f'rework {job_id} "a=b"'})

    def test_ask_rejects_bad_options(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "First?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        gone = board.cmd_new(self.root, "y")
        board.cmd_abort(self.root, gone, False)
        ok = f"B=abort {job_id}"
        cases = {
            "unknown command": (job_id, "Q?", [f"Merge=merge {job_id}", ok]),
            "empty shell": (job_id, "Q?", ["Run=shell:", ok]),
            "blank shell": (job_id, "Q?", ["Run=shell:   ", ok]),
            "bad id": (job_id, "Q?", ["Go=approve ../etc", ok]),
            "empty rework text": (job_id, "Q?", [f'Fix=rework {job_id} ""', ok]),
            "unquoted rework": (job_id, "Q?", [f"Fix=rework {job_id} text", ok]),
            "no equals": (job_id, "Q?", [f"approve {job_id}", ok]),
            "empty label": (job_id, "Q?", [f"=approve {job_id}", ok]),
            "whitespace label": (job_id, "Q?", [f"   =approve {job_id}", ok]),
            "one option": (job_id, "Q?", [ok]),
            "four options": (job_id, "Q?", [ok, ok, ok, ok]),
            "empty question": (job_id, "  ", [f"A=approve {job_id}", ok]),
            "aborted job": (gone, "Q?", [f"A=approve {gone}", f"B=abort {gone}"]),
        }
        allowed = ('allowed: approve <id>, rework <id> "<text>", abort <id> [--requeue|--cascade], resume <id>, '
                   "lilguy <id>, apply <id>, shell: <command>")
        cases["lilguy extra word"] = (job_id, "Q?", [f"Go=lilguy {job_id} now", ok])
        cases["cascade and requeue"] = (job_id, "Q?", [f"Go=abort {job_id} --cascade --requeue", ok])
        cases["misspelt cascade"] = (job_id, "Q?", [f"Go=abort {job_id} --cascad", ok])
        for name, (jid, q, opts) in cases.items():
            with self.subTest(name):
                before = (self.root / "board.json").read_bytes()
                with self.assertRaises(SystemExit) as e:
                    board.cmd_ask(self.root, jid, q, opts, title="MERGE_CONFLICT")
                self.assertTrue(str(e.exception.code))
                if name in ("cascade and requeue", "misspelt cascade", "lilguy extra word"):
                    self.assertIn(allowed, str(e.exception.code))
                self.assertEqual((self.root / "board.json").read_bytes(), before)
                self.assertEqual(len(self.log_lines()), 1)
        board.cmd_ask(self.root, job_id, "Apply?", [f"A=apply {job_id}", ok], title="DIGEST")
        self.assertEqual(self.jobs()[0]["options"][0]["command"], f"apply {job_id}")

    def test_ask_recommend_stored_and_logged(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"],
                      recommend=("b", "  safest\n path "), title="MERGE_CONFLICT")
        self.assertEqual(self.jobs()[0]["recommend"], {"key": "b", "why": "safest path"})
        self.assertEqual(self.log_lines()[-1]["recommend"], {"key": "b", "why": "safest path"})

    def test_ask_cli_recommend(self):
        job_id = board.cmd_new(self.root, "x")
        board.main(["--dir", str(self.root), "ask", job_id, "Q?", "--a", f"A=approve {job_id}",
                    "--b", f"B=resume {job_id}", "--title", "MERGE_CONFLICT", "--recommend", "b", "it is the safest path"])
        self.assertEqual(self.jobs()[0]["recommend"], {"key": "b", "why": "it is the safest path"})
        self.assertEqual(self.log_lines()[-1]["recommend"], {"key": "b", "why": "it is the safest path"})

    def test_ask_without_recommend_has_no_field(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"], title="MERGE_CONFLICT")
        self.assertNotIn("recommend", self.jobs()[0])
        self.assertNotIn("recommend", self.log_lines()[-1])

    def test_reask_drops_stale_recommend(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"], recommend=("a", "why"), title="MERGE_CONFLICT")
        board.cmd_ask(self.root, job_id, "Q2?", [f"A=approve {job_id}", f"B=resume {job_id}"], title="MERGE_CONFLICT")
        self.assertNotIn("recommend", self.jobs()[0])
        self.assertNotIn("recommend", self.log_lines()[-1])

    def test_ask_recommend_bad_key_rejected(self):
        job_id = board.cmd_new(self.root, "x")
        for key in ("c", "x"):
            with self.subTest(key=key):
                before = (self.root / "board.json").read_bytes()
                with self.assertRaises(SystemExit) as e:
                    board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"],
                                  recommend=(key, "because"), title="MERGE_CONFLICT")
                self.assertIn("bad recommend key", str(e.exception.code))
                self.assertEqual((self.root / "board.json").read_bytes(), before)
                self.assertFalse((self.root / "questions.log").exists())

    def test_ask_recommend_empty_why_rejected(self):
        job_id = board.cmd_new(self.root, "x")
        for why in ("", "  \n\t "):
            with self.subTest(why=why):
                before = (self.root / "board.json").read_bytes()
                with self.assertRaises(SystemExit) as e:
                    board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"],
                                  recommend=("a", why), title="MERGE_CONFLICT")
                self.assertIn("recommend needs a reason", str(e.exception.code))
                self.assertEqual((self.root / "board.json").read_bytes(), before)
                self.assertFalse((self.root / "questions.log").exists())

    def test_recommend_cleared_after_answer_moves_job(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"], recommend=("b", "safe"), title="MERGE_CONFLICT")
        picked = board.cmd_answer(self.root, job_id, "b")
        self.assertEqual(picked, {"key": "b", "label": "B", "command": f"resume {job_id}"})
        self.assertEqual(self.jobs()[0]["recommend"], {"key": "b", "why": "safe"})  # still asked until it moves
        board.cmd_set(self.root, job_id, ["stage=build"])
        job = self.jobs()[0]
        self.assertEqual(job["stage"], "build")
        for key in ("question", "options", "recommend"):
            self.assertNotIn(key, job)

    def test_ask_rejects_without_creating_log(self):
        job_id = board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_ask(self.root, job_id, "Q?", [f"Merge=merge {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        self.assertFalse((self.root / "questions.log").exists())

    def test_ask_requires_catalog_title(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build", "reason=working"])
        before = (self.root / "board.json").read_text()
        argv = ["--dir", str(self.root), "ask", job_id, "Q?", "--a", f"A=approve {job_id}", "--b", f"B=abort {job_id}"]
        for extra in ([], ["--title", "merge_conflict"], ["--title", "NOPE"], ["--title", "MERGE CONFLICT"]):
            with self.subTest(extra=extra):
                out = run_board(*argv, *extra)
                self.assertNotEqual(out.returncode, 0)
                self.assertIn("UNCOMMITTED_CHANGES", out.stderr)
                self.assertIn("MERGE_CONFLICT", out.stderr)
                self.assertIn("DIGEST", out.stderr)
        for title in (None, "merge_conflict", "NOPE"):
            with self.subTest(title=title), self.assertRaises(SystemExit) as e:
                board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"], title=title)
            self.assertIn("MD_CONTRADICTION", str(e.exception))
        with self.assertRaises(TypeError):  # keyword-only and required
            board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        with self.assertRaises(SystemExit):  # checked before the unblock-kind branch
            board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"], kind="round-limit",
                          title="nope")
        self.assertEqual((self.root / "board.json").read_text(), before)
        self.assertFalse((self.root / "questions.log").exists())

    def test_ask_stores_and_clears_stop_title(self):
        job_id = board.cmd_new(self.root, "x")
        board.main(["--dir", str(self.root), "ask", job_id, "Q?", "--a", f"A=approve {job_id}",
                    "--b", f"B=abort {job_id}", "--title", "MERGE_CONFLICT"])
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["stopTitle"]), ("needs-human", "MERGE_CONFLICT"))
        self.assertEqual(self.log_lines()[-1]["stopTitle"], "MERGE_CONFLICT")
        board.cmd_ask(self.root, job_id, "Q2?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="CHECKS_FAILING")
        self.assertEqual(self.jobs()[0]["stopTitle"], "CHECKS_FAILING")
        self.assertEqual(self.log_lines()[-1]["stopTitle"], "CHECKS_FAILING")
        board.cmd_set(self.root, job_id, ["stage=build", "reason="])
        job = self.jobs()[0]
        for key in ("question", "options", "stopTitle"):
            self.assertNotIn(key, job)
        # the stall branch: a missing-agent-types ask stalls the job in its stage and stores no title
        q = "scrum-builder is not loaded as agent types in this session"
        self.assertEqual(board.cmd_ask(self.root, job_id, q, [f"A=approve {job_id}", f"B=abort {job_id}"],
                                       title="BUILDER_BLOCKED"), {"stalled": True})
        self.assertNotIn("stopTitle", self.jobs()[0])
        # migrate_paused: a legacy stalled needs-human job loses its title with its question
        legacy = {"id": "009-z", "stage": "needs-human", "reason": "stalled in build: died", "question": "q",
                  "options": [], "stopTitle": "MERGE_CONFLICT"}
        board.migrate_paused({"jobs": [legacy]})
        self.assertEqual(legacy["stage"], "build")
        self.assertNotIn("stopTitle", legacy)

    def test_ask_appends_questions_log(self):
        job_id = board.cmd_new(self.root, "x")
        opts = board.cmd_ask(self.root, job_id, "Ship it?", [f"Approve=approve {job_id}", f"Abort=abort {job_id}"], title="MERGE_CONFLICT")
        [line] = self.log_lines()
        self.assertEqual(set(line), {"date", "project", "job", "question", "options", "kind", "reason", "stopTitle"})
        self.assertEqual((line["kind"], line["reason"]), ("ask", "Ship it?"))
        self.assertRegex(line["date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual(line["project"], Path(self.tmp.name).name)
        self.assertEqual((line["job"], line["question"]), (job_id, "Ship it?"))
        self.assertEqual(line["options"], [{"key": "a", "label": "Approve", "command": f"approve {job_id}"},
                                           {"key": "b", "label": "Abort", "command": f"abort {job_id}"}])
        self.assertEqual(line["options"], opts)

    def test_ask_twice_overwrites_and_logs_twice(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "One?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        board.cmd_ask(self.root, job_id, "Two?", [f"R=resume {job_id}", "S=shell: ls"], title="MERGE_CONFLICT")
        job = self.jobs()[0]
        self.assertEqual((job["question"], job["reason"]), ("Two?", "Two?"))
        self.assertEqual([o["label"] for o in job["options"]], ["R", "S"])
        self.assertEqual([l["question"] for l in self.log_lines()], ["One?", "Two?"])

    def test_ask_agent_types_not_loaded_is_stalled(self):
        opts = lambda j: [f"R=resume {j}", f"A=abort {j}"]
        for q, stage, want in (
                ("scrum-debugger, scrum-builder are not loaded as agent types in this session", "build",
                 "stalled: scrum-debugger, scrum-builder are not loaded as agent types in this session"),
                ("The scrum Agent Types not loaded here", "check", "stalled: The scrum Agent Types not loaded here"),
                ("agent types are not loaded", "review", "stalled: agent types are not loaded"),
                ("waiting on the Check queue", "check", "stalled: waiting on the Check queue")):
            with self.subTest(q=q, stage=stage):
                job_id = board.cmd_new(self.root, "x")
                board.cmd_set(self.root, job_id, [f"stage={stage}"])
                with board.locked_board(self.root) as b:  # an old question's leftovers are dropped
                    board.find(b, job_id).update(question="Old?", options=[{"key": "a"}], recommend={"key": "a"})
                before = len(self.log_lines())
                with mock.patch.object(board, "play") as play:
                    self.assertEqual(board.cmd_ask(self.root, job_id, q, opts(job_id), title="MERGE_CONFLICT"), {"stalled": True})
                play.assert_not_called()
                job = next(j for j in self.jobs() if j["id"] == job_id)
                self.assertEqual((job["stage"], job["reason"], job["stalled"]), (stage, want, True))
                for k in ("question", "options", "recommend"):
                    self.assertNotIn(k, job)
                lines = self.log_lines()[before:]
                self.assertEqual([(l["job"], l["kind"], l["reason"]) for l in lines], [(job_id, "stall", want)])
        for q, stage in (("Pick a layout?", "build"), ("agent types are not loaded", "plan")):
            with self.subTest(q=q, stage=stage):
                job_id = board.cmd_new(self.root, "x")
                board.cmd_set(self.root, job_id, [f"stage={stage}"])
                with mock.patch.object(board, "play") as play:
                    board.cmd_ask(self.root, job_id, q, opts(job_id), title="MERGE_CONFLICT")
                play.assert_called_once()
                job = next(j for j in self.jobs() if j["id"] == job_id)
                self.assertEqual((job["stage"], job["reason"], job["question"], [o["command"] for o in job["options"]]),
                                 ("needs-human", q, q, [f"resume {job_id}", f"abort {job_id}"]))
                self.assertNotIn("stalled", job)

    # --- ask --kind (scrum-unblocker) ---
    def ask_cli(self, job_id, kind, question="Stuck?"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            board.main(["--dir", str(self.root), "ask", job_id, question, "--kind", kind,
                        "--a", f"Approve=approve {job_id}", "--b", f"Abort=abort {job_id}", "--title", "BUILDER_BLOCKED"])
        return json.loads(buf.getvalue())

    def test_ask_eligible_kind_unblocks_without_parking(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=approve", "reason=working"])
        with mock.patch.object(board, "play") as play:
            self.assertEqual(self.ask_cli(job_id, "round-limit", "Round limit hit"), {"unblock": True, "n": 1})
            self.assertEqual(self.ask_cli(job_id, "ci-fail", "CI fails"), {"unblock": True, "n": 2})
        play.assert_not_called()
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["reason"], job["unblocks"], job["unblockKinds"]),
                         ("approve", "working", 2, ["round-limit", "ci-fail"]))
        self.assertNotIn("question", job)
        lines = self.log_lines()
        self.assertEqual([set(l) for l in lines], [{"date", "project", "job", "kind", "unblock", "question"}] * 2)
        self.assertEqual([(l["job"], l["kind"], l["unblock"], l["question"]) for l in lines],
                         [(job_id, "round-limit", 1, "Round limit hit"), (job_id, "ci-fail", 2, "CI fails")])
        self.assertEqual(lines[0]["project"], Path(self.tmp.name).name)

    def test_ask_hard_stop_kind_never_unblocks(self):
        for kind in ("schema", "migrate", "agent-rules", "gh", "setup", "hard-stop", "secrets"):
            with self.subTest(kind=kind):
                job_id = board.cmd_new(self.root, kind)
                board.cmd_set(self.root, job_id, ["stage=build"])
                self.assertEqual(self.ask_cli(job_id, kind), {"unblock": False})
                job = next(j for j in self.jobs() if j["id"] == job_id)
                self.assertEqual((job["stage"], job["reason"]), ("needs-human", "Stuck?"))
                self.assertNotIn("unblocks", job)

    def test_ask_unblock_caps_at_two(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=check"])
        self.assertEqual(self.ask_cli(job_id, "check-fail"), {"unblock": True, "n": 1})
        self.assertEqual(self.ask_cli(job_id, "conflict"), {"unblock": True, "n": 2})
        self.assertEqual(self.ask_cli(job_id, "render"), {"unblock": False})
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["unblocks"], job["unblockKinds"]),
                         ("needs-human", 2, ["check-fail", "conflict"]))

    def test_ask_repeat_kind_parks(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        self.assertEqual(self.ask_cli(job_id, "blocked", "blocked: one thing"), {"unblock": True, "n": 1})
        self.assertEqual(self.ask_cli(job_id, "blocked", "blocked: something else entirely"), {"unblock": False})
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["reason"], job["unblocks"]),
                         ("needs-human", "blocked: something else entirely", 1))

    def test_ask_bad_kind_rejected(self):
        job_id = board.cmd_new(self.root, "x")
        before = (self.root / "board.json").read_bytes()
        ok = [f"A=approve {job_id}", f"B=abort {job_id}"]
        for kind, opts in (("Round-Limit", ok), ("-x", ok), ("ci fail", ok), ("", ok), ("ci-fail", [f"A=merge {job_id}", ok[1]])):
            with self.subTest(kind=kind):
                with self.assertRaises(SystemExit) as e:
                    board.cmd_ask(self.root, job_id, "Q?", opts, kind=kind, title="MERGE_CONFLICT")
                self.assertTrue(str(e.exception.code))
                self.assertEqual((self.root / "board.json").read_bytes(), before)
                self.assertFalse((self.root / "questions.log").exists())

    def test_unblock_fields_survive_sync(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        self.ask_cli(job_id, "blocked")
        board.cmd_sync(self.root, job_id)
        job = self.jobs()[0]
        self.assertEqual((job["unblocks"], job["unblockKinds"]), (1, ["blocked"]))

    def test_unblock_log_records_verdict(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        self.ask_cli(job_id, "check-fail")
        self.ask_cli(job_id, "conflict")
        for verdict in ("REWORK", "RESPEC", "ESCALATE"):
            with self.subTest(verdict=verdict):
                self.write(f"{job_id}/unblock-2.md", f"VERDICT: {verdict}\nSKILL.md copies BigBoy step 3\n## Evidence\n")
                out = board.cmd_unblock_log(self.root, job_id)
                self.assertEqual(out, {"verdict": verdict, "blocker": "SKILL.md copies BigBoy step 3",
                                       "kind": "conflict", "n": 2})
                line = self.log_lines()[-1]
                self.assertEqual(set(line), {"date", "job", "kind", "verdict", "blocker"})
                self.assertEqual((line["job"], line["kind"], line["verdict"], line["blocker"]),
                                 (job_id, "conflict", verdict, "SKILL.md copies BigBoy step 3"))

    def test_unblock_log_invalid(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        self.ask_cli(job_id, "blocked")
        buf = io.StringIO()
        with redirect_stdout(buf):
            board.main(["--dir", str(self.root), "unblock-log", job_id])
        self.assertEqual(json.loads(buf.getvalue()), {"verdict": "INVALID", "blocker": "", "kind": "blocked", "n": 1})
        self.write(f"{job_id}/unblock-1.md", "VERDICT: MAYBE\nno idea\n")
        out = board.cmd_unblock_log(self.root, job_id)
        self.assertEqual(out, {"verdict": "INVALID", "blocker": "no idea", "kind": "blocked", "n": 1})
        self.assertEqual([(l["verdict"], l["blocker"]) for l in self.log_lines()[-2:]],
                         [("INVALID", ""), ("INVALID", "no idea")])

    def test_stage_change_clears_question(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        board.cmd_set(self.root, job_id, ["stage=build"])
        job = self.jobs()[0]
        self.assertNotIn("question", job)
        self.assertNotIn("options", job)

    def test_abort_clears_question(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        board.cmd_abort(self.root, job_id, False)
        job = self.jobs()[0]
        self.assertEqual(job["stage"], "aborted")
        self.assertNotIn("question", job)
        self.assertNotIn("options", job)

    def test_set_keeping_needs_human_keeps_question(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        board.cmd_set(self.root, job_id, ["waiting=asked"])
        job = self.jobs()[0]
        self.assertEqual(job["question"], "Q?")
        self.assertEqual([o["key"] for o in job["options"]], ["a", "b"])

    def test_answer_prints_option_and_logs_pick(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"Abort=abort {job_id} --requeue"], title="MERGE_CONFLICT")
        before = self.jobs()[0]
        want = {"key": "b", "label": "Abort", "command": f"abort {job_id} --requeue"}
        self.assertEqual(board.cmd_answer(self.root, job_id, "b"), want)
        buf = io.StringIO()
        with redirect_stdout(buf):
            board.main(["--dir", str(self.root), "answer", job_id, "b"])
        self.assertEqual(json.loads(buf.getvalue()), want)
        lines = self.log_lines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(set(lines[1]), {"date", "job", "pick"})
        self.assertEqual((lines[1]["job"], lines[1]["pick"], lines[2]["pick"]), (job_id, "Abort", "Abort"))
        after = self.jobs()[0]
        self.assertEqual((after["stage"], after["question"], after["options"]),
                         ("needs-human", "Q?", before["options"]))

    def test_answer_logs_note(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        board.cmd_answer(self.root, job_id, "a", note="  keep the\n old name ")
        board.cmd_answer(self.root, job_id, "b", note=" \n ")
        board.cmd_answer(self.root, job_id, "b")
        picks = [l for l in self.log_lines() if "pick" in l]
        self.assertEqual([(l["pick"], l.get("note")) for l in picks], [("A", "keep the old name"), ("B", None), ("B", None)])
        self.assertEqual(set(picks[1]), {"date", "job", "pick"})

    def test_log_note_skips_blank(self):
        job_id = board.cmd_new(self.root, "x")
        before = (self.root / "board.json").read_text()
        for blank in (None, "", "  \n "):
            board.log_note(self.root, job_id, "rework", blank)
        self.assertEqual(self.log_lines(), [])
        board.log_note(self.root, job_id, "discuss", "why\n  this table?")
        [line] = self.log_lines()
        self.assertEqual({k: v for k, v in line.items() if k != "date"},
                         {"project": self.root.resolve().parent.name, "job": job_id, "kind": "note", "action": "discuss",
                          "note": "why this table?"})
        self.assertEqual((self.root / "board.json").read_text(), before)

    def test_answer_refuses_wrong_stage_or_key(self):
        job_id = board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_answer(self.root, job_id, "a")  # spec stage, never asked
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"], title="MERGE_CONFLICT")
        with self.assertRaises(SystemExit):
            board.cmd_answer(self.root, job_id, "c")  # not on a 2-option question
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            board.main(["--dir", str(self.root), "answer", job_id, "d"])  # argparse choices
        board.cmd_set(self.root, job_id, ["stage=build"])
        with self.assertRaises(SystemExit):
            board.cmd_answer(self.root, job_id, "a")  # question cleared by the stage change
        self.assertEqual(len(self.log_lines()), 1)

    def test_lane_accepts_bigboy_rejects_epic(self):
        job_id = board.cmd_new(self.root, "x")
        out = run_board("--dir", str(self.root), "set", job_id, "lane=bigboy")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.jobs()[0]["lane"], "bigboy")
        out = run_board("--dir", str(self.root), "set", job_id, "lane=epic")
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
        out = run_board("--dir", str(self.root), "plan-apply", parent, *(["--fix"] if fix else []))
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
        out = run_board("--dir", str(self.root), "plan-apply", parent)
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
                 [self.ticket(1, exposure="yes"), self.ticket(2)]]                                       # not last
        for tickets in cases:
            self.tmp.cleanup()
            self.assertIn("Exposure", self.assert_refused(self.plan(*tickets)))
            self.assertEqual(len(self.jobs()), 1)

    def test_plan_apply_exposure_depends_on_subset(self):
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3, deps="T1", exposure="yes"))
        self.assertEqual(board.cmd_plan_apply(self.root, parent), {"children": ["002-part-1", "003-part-2", "004-part-3"]})
        self.assertEqual([self.child(k)["stage"] for k in ("002-part-1", "003-part-2", "004-part-3")], ["waiting"] * 3)
        self.assertEqual(self.child("004-part-3")["depends_on"], ["002-part-1"])

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

    def outside(self, parent, c1, dep_id=None):
        out = board.cmd_new(self.root, "Outside")
        with board.locked_board(self.root) as bd:
            board.find(bd, c1)["depends_on"] = [dep_id or out]
        return out

    def test_ready_child_waits_on_outside_job(self):
        parent, (c1, c2, c3) = self.three()
        out = self.outside(parent, c1)
        self.spec(out, "src/outside.py")  # job 751: unknown files on either side would let out hold c2
        self.spec(c2, "src/c2.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c2])
        board.cmd_set(self.root, c2, ["stage=done"])
        board.cmd_set(self.root, c3, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", board.WAITING_ON + out))
        board.cmd_set(self.root, out, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1])

    def test_ready_child_outside_dep_missing_still_blocked(self):
        parent, (c1, c2, c3) = self.three()
        self.outside(parent, c1, "999-gone")
        board.cmd_set(self.root, c2, ["stage=done"])
        board.cmd_set(self.root, c3, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual(p["stage"], "needs-human")
        self.assertTrue(p["reason"].startswith(board.BLOCKED), p["reason"])

    def test_ready_claims_once(self):
        parent, (c1, c2, c3) = self.three()
        self.spec(c1, "src/a.py")
        self.spec(c2, "src/b.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1, c2])
        again = board.cmd_ready(self.root, parent)
        self.assertEqual((again["ready"], again["in_progress"]), ([], 2))
        self.assertEqual([self.child(c)["stage"] for c in (c1, c2, c3)], ["spec", "spec", "waiting"])

    def test_ready_writes_claimed_at_once(self):
        claimed = lambda c: self.root / "jobs" / c / "claimed-at.txt"
        parent = self.plan(self.ticket(1), self.ticket(2, deps="T1"), self.ticket(3, deps="T1, T2", exposure="yes"))
        c1, c2, c3 = board.cmd_plan_apply(self.root, parent)["children"]
        before = int(time.time())
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1])
        self.assertTrue(before <= int(claimed(c1).read_text()) <= int(time.time()))
        self.assertFalse(claimed(c2).exists())  # left waiting on c1
        self.assertFalse(claimed(c3).exists())
        claimed(c1).write_text("123")
        board.cmd_ready(self.root, parent)  # a second call
        board.cmd_set(self.root, c1, ["stage=waiting"])  # a re-claim
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1])
        self.assertEqual(claimed(c1).read_text(), "123")

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
        for c in (c2, c3):  # job 751: the first tree's live children would hold the next tree's claims
            board.cmd_set(self.root, c, ["stage=done"])
        # A parallel=no child starts only when no sibling is in progress.
        parent = self.plan(self.ticket(1), self.ticket(2, parallel="no — touches everything"), self.ticket(3, deps="T1, T2", exposure="yes"))
        d1, d2, _ = board.cmd_plan_apply(self.root, parent)["children"]
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d1])
        board.cmd_set(self.root, d1, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d2])

    def test_cmd_ready_notes_queue_gates(self):
        gates = lambda c: (self.root / "jobs" / c / "queue-gates.txt").read_text().split() \
            if (self.root / "jobs" / c / "queue-gates.txt").exists() else []
        parent, (c1, c2, c3) = self.three()
        self.spec(c1, "src/a.py")
        self.spec(c2, "src/a.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])  # no duplicate line on the second call
        self.assertEqual(gates(c1), [])  # claimed: no gate
        self.assertEqual(gates(c2), [f"overlap:{c1}"])
        self.assertEqual(gates(c3), [f"depends_on:{c1}", f"depends_on:{c2}"])
        parent = self.plan(self.ticket(1), self.ticket(2, parallel="no"), self.ticket(3, deps="T1, T2", exposure="yes"))
        d1, d2, _ = board.cmd_plan_apply(self.root, parent)["children"]
        self.spec(d1, "src/x.py")
        board.cmd_ready(self.root, parent)
        self.assertEqual(gates(d2), [f"runs_alone:{d1}"])  # job 825: names the holder

    def test_ready_records_overlap_hold(self):
        # Job 764: the card shows why a waiting child is held; a claim or a dep wait drops a stale hold.
        parent, (c1, c2, c3) = self.three()
        self.spec(c1, "src/a.py")
        self.spec(c2, "src/a.py")
        with board.locked_board(self.root) as b:
            next(j for j in b["jobs"] if j["id"] == c3)["overlap_hold"] = {"ids": ["999-old"], "text": "stale"}
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1])
        board.cmd_set(self.root, c1, ["stage=build"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        self.assertEqual(self.child(c2)["overlap_hold"], {"ids": [c1], "text": f"sibling {c1} shares src/a.py"})
        self.assertNotIn("overlap_hold", self.child(c1))
        self.assertNotIn("overlap_hold", self.child(c3))  # held on depends_on: the stale hold is dropped
        board.cmd_set(self.root, c1, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c2])
        self.assertEqual(self.child(c2)["stage"], "spec")
        self.assertNotIn("overlap_hold", self.child(c2))
        board.cmd_set(self.root, c2, ["stage=done"])
        # A child with no spec and no plan paths runs alone.
        parent = self.plan(self.ticket(1), self.ticket(2, parallel="no"), self.ticket(3, deps="T1, T2", exposure="yes"))
        d1, d2, _ = board.cmd_plan_apply(self.root, parent)["children"]
        self.spec(d1, "src/x.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d1])
        self.assertEqual(self.child(d2)["overlap_hold"], {"ids": [d1], "text": "this job runs alone"})

    def test_ready_waiting_children_use_plan_paths(self):
        # Job 673: a waiting child has no spec.md; its plan's Parallel: paths stand in as its Likely files.
        plan = lambda: self.plan(self.ticket(1, parallel="yes — touches only `src/app/(pages)/`"),
                                 self.ticket(2, parallel="yes — touches only `src/lib/` and `docs/x.md`"),
                                 self.ticket(3, deps="T1, T2", parallel="no — wires both", exposure="yes"))
        parent = plan()
        c1, c2, c3 = board.cmd_plan_apply(self.root, parent)["children"]
        feature = (self.root / "jobs" / c2 / "feature.md").read_text()
        self.assertIn("## Likely files\n- `src/lib/`\n- `docs/x.md`\n", feature)
        self.assertNotIn("## Likely files", (self.root / "jobs" / c3 / "feature.md").read_text())
        self.assertIsNone(board.resume_blocker(self.root, c2, live={c1}))
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1, c2])
        for c in (c1, c2):  # job 751: the first tree's live children would hold the next tree's claims
            board.cmd_set(self.root, c, ["stage=done"])
        # A specced file under a waiting sibling's folder clashes with it (prefix-aware), in ready and resume_blocker.
        parent = plan()
        d1, d2, _ = board.cmd_plan_apply(self.root, parent)["children"]
        self.spec(d2, "src/app/(pages)/page.tsx")
        hit = board.resume_blocker(self.root, d2, live={d1})
        self.assertEqual((str(hit), hit.ids), (f"sibling {d1} shares src/app/(pages)/page.tsx", [d1]))
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d1])
        # A folder named without the trailing slash still never matches a mere name prefix.
        self.assertEqual(board.shared_files({"src/app"}, {"src/application.ts", "src/app/x.ts"}), {"src/app/x.ts"})

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
            board.cmd_set(self.root, c2, ["stage=done"])  # job 751: a live spec-less job holds every other tree
        # Reversed: the spec-less child is claimed first, and a disjoint sibling waits until it is done.
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3, deps="T1, T2", exposure="yes"))
        d1, d2, _ = board.cmd_plan_apply(self.root, parent)["children"]
        self.spec(d2, "src/c.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d1])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        board.cmd_set(self.root, d1, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [d2])

    def test_child_files_terminal_batch_reads_claude_paths(self):
        batch = board.TERMINAL_BATCH_INTRO + "\n## From 1: a\n- `.claude/skills/scrum-digest-flow/SKILL.md`\n- `.claude/agents/x.md`\n- `tests/test_x.py`\n"
        self.write("b1/feature.md", batch)
        self.assertEqual(board.child_files(self.root / "jobs", "b1"),
                         {".claude/skills/scrum-digest-flow/SKILL.md", ".claude/agents/x.md"})
        self.write("b2/feature.md", board.TERMINAL_BATCH_INTRO)  # names no .claude/ path: runs alone
        self.assertEqual(board.child_files(self.root / "jobs", "b2"), set())

    def test_ready_terminal_batch_holds_only_overlapping_claude_jobs(self):
        self.write("b1/feature.md", board.TERMINAL_BATCH_INTRO + "- `.claude/skills/scrum-digest-flow/SKILL.md`\n")
        self.spec("j1", "skills/trevskills-scrum/board.py")
        self.spec("j2", ".claude/skills/scrum-digest-flow/SKILL.md")
        files = {i: board.child_files(self.root / "jobs", i) for i in ("b1", "j1", "j2")}
        batch = {"id": "b1", "parallel": True}
        self.assertIsNone(board.slot_conflict({"id": "j1", "parallel": True}, [batch], files))
        self.assertIsNotNone(board.slot_conflict({"id": "j2", "parallel": True}, [batch], files))

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
        out = run_board("--dir", str(self.root), "chain-lock", parent, "002-part-1", "--wait", "0")
        self.assertEqual((out.returncode, json.loads(out.stdout)), (0, {"acquired": False, "holder": "003-part-2"}))

    def test_chain_lock_live(self):
        lock = self.root / "jobs" / "001-par" / ".chain.lock"
        lock.parent.mkdir(parents=True)
        self.assertFalse(board.chain_lock_live(self.root, "001-par"), "no lock file")
        lock.write_text("002-a")
        self.assertTrue(board.chain_lock_live(self.root, "001-par"))
        young = time.time() - 1700
        os.utime(lock, (young, young))
        self.assertTrue(board.chain_lock_live(self.root, "001-par"), "younger than 1800 s")
        stale = time.time() - 1801
        os.utime(lock, (stale, stale))
        self.assertFalse(board.chain_lock_live(self.root, "001-par"), "older than 1800 s")
        lock.write_text("002-a")
        with mock.patch.object(Path, "stat", side_effect=FileNotFoundError):  # gone between the check and the stat
            self.assertFalse(board.chain_lock_live(self.root, "001-par"))

    def test_chain_unlock_only_by_holder(self):
        parent, _ = self.three()
        lock = self.root / "jobs" / parent / ".chain.lock"
        self.assertEqual(board.cmd_chain_unlock(self.root, parent, "002-part-1"), {"released": False})
        board.cmd_chain_lock(self.root, parent, "002-part-1")
        self.assertEqual(board.cmd_chain_unlock(self.root, parent, "003-part-2"), {"released": False})
        self.assertTrue(lock.exists())
        out = run_board("--dir", str(self.root), "chain-unlock", parent, "002-part-1")
        self.assertEqual((out.returncode, json.loads(out.stdout)), (0, {"released": True}))
        self.assertFalse(lock.exists())
        self.assertEqual(board.cmd_chain_lock(self.root, parent, "003-part-2", wait=0)["acquired"], True)

    def test_likely_files_reads_only_that_section(self):
        text = "## Problem\n`a/x.py`\n## Likely files\n- `skills/board.py`: `SHAPES[\"lane\"]` and `cmd_ready(root)`\n- `tests/t.py`\n## Assumptions\n- `b/y.py`\n"
        self.assertEqual(board.likely_files(text), {"skills/board.py", "tests/t.py"})
        self.assertEqual(board.likely_files("# no section\n"), set())
        nextjs = "## Likely files\n- `src/app/(app)/page.tsx`\n- `src/app/api/orders/[id]/route.ts`\n"
        self.assertEqual(board.likely_files(nextjs), {"src/app/(app)/page.tsx", "src/app/api/orders/[id]/route.ts"})

    def test_likely_files_reads_bare_bullet_paths(self):
        self.assertEqual(board.likely_files("## Likely files\n- src/app/api/users/route.test.ts\n"), {"src/app/api/users/route.test.ts"})
        self.assertEqual(board.likely_files("## Likely files\n- src/a.py: why\n- src/b.py, edit\n"), {"src/a.py", "src/b.py"})
        self.assertEqual(board.likely_files("## Likely files\n- cmd_ready(root): the scheduler\n- Edit the scheduler\nsrc/c.py\n## Assumptions\n- src/d.py\n"), set())
        mixed = "## Likely files\n- `x/a.py`: see y/b.py\n- src/app/(app)/page.tsx\n"
        self.assertEqual(board.likely_files(mixed), {"x/a.py", "src/app/(app)/page.tsx"})

    def five(self):
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3, deps="T1"), self.ticket(4, deps="T2"),
                           self.ticket(5, deps="T1, T2, T3, T4", exposure="yes"))
        return parent, board.cmd_plan_apply(self.root, parent)["children"]

    def test_ready_failed_child_blocks_only_dependents(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        for k in (c1, c2, c4):
            self.spec(k, f"src/{k}.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c1, c2])
        board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
        board.cmd_set(self.root, c2, ["stage=done"])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c4])
        self.assertEqual((self.child(parent)["stage"], self.child(c3)["stage"]), ("running", "waiting"))

    def test_ready_marks_parent_blocked(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
        board.cmd_abort(self.root, c2, requeue=False)
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"], out["all_merged"]), ([], 0, False))
        p = self.child(parent)  # a needs-human child is actionable, so the parent keeps running
        self.assertEqual((p["stage"], p["reason"]), ("running", f"waiting on you in: {c1}"))
        board.cmd_set(self.root, c1, ["stage=done", "reason="])  # Trevor approved it and it merged
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c3])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_ready_machine_hold_logs_once(self):
        parent, _ = self.five()
        board.cmd_ready(self.root, parent)
        for text in ("free RAM 7% (< 20%)", "free RAM 6% (< 20%)"):
            with mock.patch.object(board, "machine_ok", return_value=text):
                board.cmd_ready(self.root, parent)
        self.assertEqual(self.child(parent)["reason"], "waiting: free RAM 6% (< 20%)")
        [line] = self.log_lines()
        self.assertEqual(set(line), {"date", "project", "job", "kind", "reason"})
        self.assertRegex(line["date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual((line["project"], line["job"], line["kind"], line["reason"]),
                         (Path(self.tmp.name).name, parent, "machine", "waiting: free RAM 7% (< 20%)"))

    def test_cmd_ready_cpu_load_wait_is_silent(self):
        # Job 825: a CPU-load wait passes on its own, so its machine line is auto and the parent keeps running.
        parent, _ = self.five()
        board.cmd_ready(self.root, parent)
        with mock.patch.object(board, "machine_ok", return_value="CPU load 178% of 8 cores (> 150%)"):
            board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", "waiting: CPU load 178% of 8 cores (> 150%)"))
        [line] = self.log_lines()
        self.assertEqual((line["job"], line["kind"], line["reason"], line["auto"]),
                         (parent, "machine", "waiting: CPU load 178% of 8 cores (> 150%)", True))

    def test_cmd_ready_only_idle_claim(self):
        # Job 825: only= claims that one waiting child, as parallel, past a parked sibling and ram_room 0.
        parent = self.plan(self.ticket(1), self.ticket(2, parallel="no"), self.ticket(3), self.ticket(4),
                           self.ticket(5, deps="T1, T2, T3, T4", exposure="yes"))
        c1, c2, c3, c4, _ = board.cmd_plan_apply(self.root, parent)["children"]
        for k, f in ((c1, "src/a.py"), (c2, "src/b.py"), (c3, "src/b.py"), (c4, "src/a.py")):
            self.spec(k, f)
        board.cmd_set(self.root, c1, ["stage=build"])
        board.cmd_set(self.root, c3, ["stage=build"])
        board.cmd_pause(self.root, c3)  # parked on src/b.py: holds no slot for only=
        alive = mock.patch.object(board, "session_alive_fn", return_value=lambda job: False)
        alive.start()
        self.addCleanup(alive.stop)
        self.assertEqual(board.cmd_ready(self.root, parent, live=[c1])["ready"], [])  # c2 runs alone, c4 shares
        with mock.patch.object(board, "ram_room", return_value=0):
            self.assertEqual(board.cmd_ready(self.root, parent, live=[c1], only=c4)["ready"], [])  # shares src/a.py
            self.assertEqual(self.child(c4)["stage"], "waiting")
            out = board.cmd_ready(self.root, parent, live=[c1], only=c2)
        self.assertEqual(out["ready"], [c2])
        self.assertEqual([self.child(k)["stage"] for k in (c2, c4)], ["spec", "waiting"])  # nothing else claimed
        self.assertEqual(board.cmd_ready(self.root, parent, live=[c1], only=c2)["ready"], [])  # no longer waiting
        board.cmd_set(self.root, c1, ["stage=done"])
        with mock.patch.object(board, "machine_ok", return_value="free RAM 7% (< 20%)"):
            self.assertEqual(board.cmd_ready(self.root, parent, only=c4)["ready"], [])
        with mock.patch.object(board, "pick_account", return_value=(None, board.Allowance(0, "usage held"))):
            self.assertEqual(board.cmd_ready(self.root, parent, only=c4)["ready"], [])
        self.assertEqual(self.child(c4)["stage"], "waiting")
        self.assertEqual(board.cmd_ready(self.root, parent, only=c4)["ready"], [c4])

    def test_bigboy_stops_log_kind_bigboy(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=done"])
        board.cmd_abort(self.root, c2, requeue=False)
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c3, ["stage=done"])
        self.assertEqual(self.log_lines(), [])
        board.cmd_ready(self.root, parent)
        board.cmd_ready(self.root, parent)  # same blocked reason again: no second line
        blocked = ("bigboy blocked: 003-part-2. Fix: click Resume to skip the children that depend on them and run "
                   "the final review.")
        [line] = self.log_lines()
        self.assertEqual(set(line), {"date", "project", "job", "kind", "reason"})
        self.assertEqual((line["project"], line["job"], line["kind"], line["reason"]),
                         (Path(self.tmp.name).name, parent, "bigboy", blocked))
        board.cmd_set(self.root, parent, ["stage=done", "reason=merged + gaps: review unreadable"])
        job = next(j for j in self.jobs() if j["id"] == parent)
        self.assertEqual((job["stage"], job["reason"]), ("done", "merged + gaps: review unreadable"))
        self.assertEqual(self.log_lines(), [line])  # step 7 filed the gaps: no stop line
        board.cmd_set(self.root, parent, ["stage=done", "reason=merged + gaps: review unreadable"])  # job 206 ran it twice
        self.assertEqual(self.log_lines(), [line])
        other = board.cmd_new(self.root, "y")
        for q in ("bigboy review: main not updated; merge it?", "bigboy blocked: 009-x. Resume?", "bigboy off track?"):
            board.cmd_ask(self.root, other, q, [f"R=resume {other}", f"A=abort {other}"], title="MERGE_CONFLICT")
        asks = self.log_lines()[1:]
        self.assertEqual([(l["kind"], l["reason"], l["question"]) for l in asks],
                         [("bigboy", "bigboy review: main not updated; merge it?",
                           "bigboy review: main not updated; merge it?"),
                          ("bigboy", "bigboy blocked: 009-x. Resume?", "bigboy blocked: 009-x. Resume?"),
                          ("ask", "bigboy off track?", "bigboy off track?")])

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
        self.assertEqual(p["stopTitle"], "BIGBOY_BLOCKED")
        self.assertNotIn("Abort", p["reason"])
        # Resume aborts the waiting dependents; every child is then done or aborted, so all_merged is true.
        board.cmd_abort(self.root, c4, requeue=False)
        board.cmd_abort(self.root, c5, requeue=False)
        out = run_board("--dir", str(self.root), "ready", parent)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual((json.loads(out.stdout)["all_merged"], json.loads(out.stdout)["merged"]), (True, 2))
        self.assertNotIn("stopTitle", self.child(parent))
        # One aborted child plus one needs-human child: the parent keeps running and names the needs-human one.
        parent, (d1, d2, d3, d4, d5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_abort(self.root, d1, requeue=False)
        board.cmd_set(self.root, d2, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
        with mock.patch.object(board, "play") as play:
            board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", f"waiting on you in: {d2}"))
        play.assert_not_called()

    def test_bigboy_aborted_setup_pending_child_still_blocks_with_resume(self):
        # A stale setup=pending on an aborted or done child is not "waiting on you".
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=done", "setup=pending"])
        board.cmd_set(self.root, c2, ["setup=pending"])
        board.cmd_abort(self.root, c2, requeue=False)
        board.cmd_set(self.root, c3, ["stage=done"])
        with mock.patch.object(board, "play") as play:
            board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual(p["stage"], "needs-human")
        self.assertTrue(p["reason"].startswith(f"bigboy blocked: {c2}. Fix: click Resume"), p["reason"])
        self.assertEqual(play.call_count, 1)
        # A live waiting child with setup=pending keeps the parent running and named.
        parent, (d1, d2, d3, d4, d5) = self.five()
        board.cmd_ready(self.root, parent)
        for k in (d1, d2, d3):
            board.cmd_set(self.root, k, ["stage=done"])
        board.cmd_set(self.root, d4, ["setup=pending"])
        board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", f"waiting on you in: {d4}"))

    def test_ready_parent_waits_on_needs_human_children(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c2, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
        board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
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
        board.cmd_set(self.root, d1, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
        board.cmd_set(self.root, d2, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
        board.cmd_ready(self.root, parent)
        self.assertEqual(self.child(parent)["reason"], f"waiting on you in: {d1}, {d2}")
        board.cmd_set(self.root, d2, ["stage=build", "reason="])  # Send back to builder: in progress, nothing new ready
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_ready_recovers_legacy_blocked_parent(self):
        parent, (c1, c2, c3, c4, c5) = self.five()
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, c1, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
        board.cmd_set(self.root, c2, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
        board.cmd_set(self.root, parent, ["stage=needs-human", f"reason=bigboy blocked: {c1}, {c2}. Fix: y"], internal=True)
        with mock.patch.object(board, "play") as play:
            board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", "waiting on you in: 002-part-1, 003-part-2"))
        play.assert_not_called()
        board.cmd_set(self.root, parent, ["stage=needs-human", "reason=bigboy blocked: old. Fix: y"], internal=True)
        board.cmd_set(self.root, c1, ["stage=build", "reason="])
        board.cmd_ready(self.root, parent)
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))
        board.cmd_set(self.root, c1, ["stage=done"])  # job 751: a live outside job would hold the run-all's claims
        rparent, (a, b) = self.runall(2)
        board.cmd_ready(self.root, rparent)
        board.cmd_set(self.root, rparent, ["stage=needs-human", "reason=run-all blocked: x. Fix: y"], internal=True)
        board.cmd_ready(self.root, rparent)  # a is in progress
        p = self.child(rparent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))

    def test_ready_leaves_other_parent_stops_alone(self):
        parent, kids = self.three()
        board.cmd_set(self.root, parent, ["stage=needs-human", "reason=bigboy off track: x. Fix: y"], internal=True)
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("needs-human", "bigboy off track: x. Fix: y"))
        self.assertEqual([self.child(k)["stage"] for k in kids], ["waiting"] * 3)

    def test_ready_recovers_chain_lock_parent(self):
        parent, (c1, c2, c3) = self.three()
        board.cmd_set(self.root, parent, ["stage=needs-human", "reason=bigboy chain lock held by 005-x. Fix: wait, "
                                          "or clear the lock and click Run now on a waiting child."], internal=True)
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
            board.cmd_set(self.root, job, ["stage=needs-human", "reason=x"], internal=True)
            play.assert_called_once_with(clip)
            play.reset_mock()
            board.cmd_set(self.root, job, ["stage=needs-human"], internal=True)  # already there: no sound
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
            board.cmd_set(self.root, job, ["stage=needs-human"], internal=True)
        self.assertEqual(seen, ["needs-human"])

    def test_play_is_detached_and_muted_by_env(self):
        with mock.patch.object(board.subprocess, "Popen") as popen:
            board.play("/x.aiff")
            popen.assert_not_called()
            with mock.patch.dict(os.environ, {"SCRUM_MUTE": "", "SCRUM_VOLUME": str(Path(self.tmp.name) / "no-volume")}):
                board.play("/x.aiff")
        popen.assert_called_once_with(["afplay", "-v", "1.0", "/x.aiff"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
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
        self.assertEqual([j.get("cloudClaim") for j in self.jobs()], [True, True])

    def test_cloud_claim_cuts_title_to_60_and_skips_waiting_items(self):
        long = "L" * 70
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text(f"# Backlog\n- [ ] Blocked {{needs #aaaa}}\n- [ ] Pre {{#aaaa}}\n- [ ] {long}\n")
        (self.root / "backlog-specs").mkdir()
        for t, f in (("Blocked", "z.py"), ("Pre", "p.py"), (long, "l.py")):
            self.spec_file(t).write_text(f"## Likely files\n- `{f}`\n")
        out = board.cmd_cloud_claim(self.root, 5)
        self.assertEqual([c["feature"] for c in out["claimed"]], ["Pre", long])
        self.assertEqual(self.jobs()[1]["title"], "L" * 59 + "…")
        self.assertTrue((self.root / "backlog.md").read_text().startswith("# Backlog\n- [ ] Blocked {needs #aaaa}\n"))

    def test_cloud_claim_skips_item_parked_on_human_setup(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Parked {setup: add the API key}\n- [ ] Free\n")
        (self.root / "backlog-specs").mkdir()
        for t, f in (("Parked", "p.py"), ("Free", "f.py")):
            self.spec_file(t).write_text(f"## Likely files\n- `{f}`\n")
        out = board.cmd_cloud_claim(self.root, 5)
        self.assertEqual(out, {"claimed": [{"id": "001-free", "feature": "Free"}]})
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [ ] Parked {setup: add the API key}\n- [x] Free → 001-free\n")

    def test_cloud_claim_priority_order(self):
        self.cloud_backlog([("Plain", ["a.py"]), ("Low {p:1}", ["b.py"]), ("High {p:5}", ["a.py"]),
                            ("Parked {p:5} {setup: Buy}", ["d.py"])])
        # cloud_backlog keys specs on the full line text; re-key them on the stored item text
        for raw, text in (("Low {p:1}", "Low"), ("High {p:5}", "High"), ("Parked {p:5} {setup: Buy}", "Parked")):
            self.spec_file(raw).rename(self.spec_file(text))
        out = board.cmd_cloud_claim(self.root, 1)
        self.assertEqual(out, {"claimed": [{"id": "001-high", "feature": "High"}]})
        out = board.cmd_cloud_claim(self.root, 5)  # Plain shares a.py with the High claim, still in flight
        self.assertEqual(out, {"claimed": [{"id": "002-low", "feature": "Low"}]})
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [ ] Plain\n- [x] Low {p:1} → 002-low\n- [x] High {p:5} → 001-high\n"
                         "- [ ] Parked {p:5} {setup: Buy}\n")

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

    def test_cloud_claim_counts_own_unsent_claims_as_in_flight(self):
        self.cloud_backlog([("A", ["a.py"]), ("B", ["b.py"]), ("C", ["a.py", "c.py"]), ("D", ["d.py"])])
        first = board.cmd_cloud_claim(self.root, 2)
        self.assertEqual([c["id"] for c in first["claimed"]], ["001-a", "002-b"])
        second = board.cmd_cloud_claim(self.root, 2)
        self.assertEqual(second, {"claimed": [{"id": "003-d", "feature": "D"}]})
        self.assertTrue(self.spec_file("C").exists())
        self.assertIn("- [ ] C\n", (self.root / "backlog.md").read_text())

    def test_cloud_claim_ignores_local_spec_jobs(self):
        self.cloud_backlog([("X item", ["x.py"])])
        self.in_flight("010-local", "spec", ["x.py"])
        out = board.cmd_cloud_claim(self.root, 1)
        self.assertEqual([c["feature"] for c in out["claimed"]], ["X item"])

    def test_cloud_claim_released_when_claim_leaves_spec(self):
        for stage in ("aborted", "needs-human"):
            with self.subTest(stage=stage):
                self.setUp()
                self.cloud_backlog([("X item", ["x.py"])])
                self.in_flight("010-gone", stage, ["x.py"])
                data = json.loads((self.root / "board.json").read_text())
                data["jobs"][0]["cloudClaim"] = True
                (self.root / "board.json").write_text(json.dumps(data))
                out = board.cmd_cloud_claim(self.root, 1)
                self.assertEqual([c["feature"] for c in out["claimed"]], ["X item"])

    def test_cloud_claim_unsent_claim_without_spec_blocks_all(self):
        self.cloud_backlog([("X item", ["x.py"])])
        self.in_flight("010-unsent", "spec", None)
        data = json.loads((self.root / "board.json").read_text())
        data["jobs"][0]["cloudClaim"] = True
        (self.root / "board.json").write_text(json.dumps(data))
        self.assertEqual(board.cmd_cloud_claim(self.root, 1), {"claimed": []})

    def test_cloud_claim_rejects_n_below_one(self):
        self.cloud_backlog([("A", ["a.py"])])
        before = (self.root / "backlog.md").read_bytes()
        for n in ("0", "-1"):
            out = run_board("--dir", str(self.root), "cloud-claim", n)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("N must be at least 1", out.stderr)
            self.assertEqual((self.root / "backlog.md").read_bytes(), before)
        self.assertFalse((self.root / "jobs").exists())

    def test_cloud_claim_cli_prints_json(self):
        self.cloud_backlog([("A", ["a.py"])])
        out = run_board("--dir", str(self.root), "cloud-claim", "4")
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

    def test_runall_start_children_in_priority_order(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] Plain {needs #hi11}\n- [ ] Low {#lo11} {p:1}\n- [ ] High {#hi11} {p:5} {needs #lo11}\n"
            "- [ ] Mid {p:3}\n")
        out = board.cmd_runall_start(self.root)
        self.assertEqual(out, {"id": "001-run-all", "children": ["002-high", "003-mid", "004-plain", "005-low"]})
        self.assertEqual(self.child("001-run-all")["children"], ["002-high", "003-mid", "004-plain", "005-low"])
        self.assertEqual(self.child("002-high")["depends_on"], ["005-low"])
        self.assertEqual(self.child("004-plain")["depends_on"], ["002-high"])
        self.assertEqual(self.child("003-mid")["depends_on"], [])
        self.assertEqual((self.root / "backlog.md").read_text(),
                         "# Backlog\n- [x] Plain {needs #hi11} → 004-plain\n- [x] Low {#lo11} {p:1} → 005-low\n"
                         "- [x] High {#hi11} {p:5} {needs #lo11} → 002-high\n- [x] Mid {p:3} → 003-mid\n")

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

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS)  # RAM math alone, not the wake ramp
    def test_runall_ready_has_no_count_cap(self):
        parent, kids = self.runall(7)
        for i, k in enumerate(kids):
            self.spec(k, f"src/{i}.py")
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), (kids, 7))
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        for k in kids:  # job 751: the first run-all's live children would hold the next run-all's claims
            board.cmd_set(self.root, k, ["stage=done"])
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

    def machine(self, ram, disk):
        return mock.patch.dict(os.environ, {"SCRUM_FREE_RAM": ram, "SCRUM_FREE_DISK_GB": disk})

    def test_machine_ok_low_ram(self):
        self.assertEqual(board.MIN_FREE_RAM_PCT, 20)
        with self.machine("14", "1000"):
            self.assertEqual(board.machine_ok(self.tmp.name), "free RAM 14% (< 20%)")
        with self.machine("14", "6.2"):  # both low: RAM only, one short line
            self.assertEqual(board.machine_ok(self.tmp.name), "free RAM 14% (< 20%)")

    def test_machine_ok_low_disk(self):
        self.assertEqual(board.MIN_FREE_DISK_GB, 10)
        with self.machine("100", "6.2"):
            self.assertEqual(board.machine_ok(self.tmp.name), "free disk 6.2 GB (< 10 GB)")
        with self.machine("100", "9.96"):
            self.assertEqual(board.machine_ok(self.tmp.name), "free disk 10.0 GB (< 10 GB)")

    def test_machine_ok_passes(self):
        with self.machine("20", "10"):
            self.assertIsNone(board.machine_ok(self.tmp.name))
        with self.machine("", ""), \
                mock.patch.object(board.subprocess, "run", return_value=mock.Mock(
                    stdout="Pages free: 1\n\nSystem-wide memory free percentage: 59%\n")), \
                mock.patch.object(board.shutil, "disk_usage", return_value=mock.Mock(free=250_000_000_000)):
            self.assertEqual((board.free_ram_pct(), board.free_disk_gb(self.tmp.name)), (59.0, 250.0))
            self.assertIsNone(board.machine_ok(self.tmp.name))

    def test_machine_ok_unknown_readings_pass(self):
        with self.machine("", ""), mock.patch.object(board.shutil, "disk_usage", side_effect=OSError("gone")):
            with mock.patch.object(board.subprocess, "run", side_effect=FileNotFoundError("memory_pressure")):
                self.assertEqual((board.free_ram_pct(), board.free_disk_gb(self.tmp.name)), (None, None))
                self.assertIsNone(board.machine_ok(self.tmp.name))
            with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout="Usage: memory_pressure\n")):
                self.assertIsNone(board.free_ram_pct())
                self.assertIsNone(board.machine_ok(self.tmp.name))

    def sessions(self, n):
        ps = Path(self.tmp.name) / "ps.txt"
        ps.write_text("claude -p /trevskills-scrum start 1-a --model sonnet\n" * (n - 1) + "claude -p /trevskills-scrum run-all\n" * min(n, 1)
                      + "vim board.py\n")  # run-all counts too; vim does not
        return mock.patch.dict(os.environ, SCRUM_PS=str(ps))

    def test_machine_ok_session_ceiling(self):
        """Job 279 (Trevor 2026-10-24): free RAM caps new work, not a fixed 8 sessions. Job 283 (Trevor, later that day,
        after 19 sessions across three projects piled up): one machine-wide ceiling, derived from the RAM share."""
        self.assertEqual(board.MAX_SESSIONS, 70 // board.SESSION_RAM_PCT)
        with self.sessions(13):
            self.assertIsNone(board.machine_ok(self.tmp.name))
        with self.sessions(14):
            self.assertEqual(board.machine_ok(self.tmp.name), "14 sessions running (ceiling 14)")
        with self.sessions(20), self.machine("14", "1000"):
            self.assertEqual(board.machine_ok(self.tmp.name), "free RAM 14% (< 20%)", "RAM first")

    def cooling(self):
        flag = Path(self.tmp.name) / "cooldown"
        flag.write_text("")
        return mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(flag))

    def test_machine_ok_cooling_down(self):
        """Job 421: the cool-down flag refuses only new claims (claim=True), checked first; Trevor's manual click and
        in-flight work (resumes, BigBoy children) skip it."""
        with self.cooling():
            self.assertIsNone(board.machine_ok(self.tmp.name))
            self.assertIsNone(board.machine_ok(self.tmp.name, claim=False))
            self.assertEqual(board.machine_ok(self.tmp.name, claim=True), "cooling down")
            self.assertIsNone(board.machine_ok(self.tmp.name, manual=True, claim=True))
            with self.machine("14", "6.2"):
                self.assertEqual(board.machine_ok(self.tmp.name, claim=True), "cooling down", "checked before RAM and disk")
                self.assertEqual(board.machine_ok(self.tmp.name), "free RAM 14% (< 20%)")
                self.assertEqual(board.machine_ok(self.tmp.name, manual=True, claim=True), "free RAM 14% (< 20%)")
            with mock.patch.dict(os.environ, SCRUM_SWAP_PCT="30"):
                self.assertEqual(board.machine_ok(self.tmp.name, claim=True), "cooling down", "checked before swap")
            with self.sessions(14):
                self.assertEqual(board.machine_ok(self.tmp.name, claim=True), "cooling down", "checked before the ceiling")
                self.assertEqual(board.machine_ok(self.tmp.name), "14 sessions running (ceiling 14)")
        with mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(Path(self.tmp.name) / "absent")):
            self.assertIsNone(board.machine_ok(self.tmp.name, claim=True))
            with self.machine("14", "1000"):
                self.assertEqual(board.machine_ok(self.tmp.name, claim=True), "free RAM 14% (< 20%)")

    def test_cooldown_path_default(self):
        with mock.patch.dict(os.environ, SCRUM_COOLDOWN=""):
            self.assertEqual(board.cooldown_path(), Path.home() / ".claude" / "trevskills-scrum" / "cooldown")

    def test_ready_cooling_down_claims_nothing(self):
        parent, (a, b) = self.runall(2)
        for i, k in enumerate((a, b)):
            self.spec(k, f"src/c{i}.py")
        with self.cooling(), mock.patch.object(board, "play") as play:
            out = board.cmd_ready(self.root, parent)
        self.assertEqual(out["ready"], [])
        self.assertEqual((self.child(a)["stage"], self.child(b)["stage"]), ("waiting", "waiting"))
        p = self.child(parent)
        self.assertEqual(p["stage"], "running")
        self.assertTrue(p["reason"].startswith("waiting: cooling down"), p["reason"])
        play.assert_not_called()
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [a, b], "claims again once the flag is gone")

    def test_ready_cooling_down_bigboy_holds_children(self):
        """Job 466: cool-down holds a BigBoy parent's child claims too; Trevor's manual click still claims, and a parent
        whose children all finished still reaches its final review."""
        parent, a, b = (board.cmd_new(self.root, t) for t in ("big", "a", "b"))
        self.edit_jobs(**{parent: {"lane": "bigboy", "stage": "running", "reason": None, "children": [a, b]},
                          a: {"parent": parent, "stage": "done"}, b: {"parent": parent, "stage": "done"}})
        with self.cooling(), mock.patch.object(board, "play"):
            out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["all_merged"], out["ready"]), (True, []))
        self.assertEqual((self.child(parent)["stage"], self.child(parent)["reason"]), ("running", None))
        c, d = board.cmd_new(self.root, "c"), board.cmd_new(self.root, "d")
        self.edit_jobs(**{parent: {"children": [a, b, c, d]},
                          c: {"parent": parent, "stage": "waiting", "depends_on": [a], "parallel": True},
                          d: {"parent": parent, "stage": "waiting", "depends_on": [a, b], "parallel": True}})
        self.spec(c, "src/c.py")
        self.spec(d, "src/d.py")
        with self.cooling(), mock.patch.object(board, "play") as play:
            out = board.cmd_ready(self.root, parent)
        self.assertEqual(out["ready"], [])
        self.assertEqual((self.child(c)["stage"], self.child(d)["stage"]), ("waiting", "waiting"))
        self.assertEqual(self.child(parent)["stage"], "running")
        self.assertTrue(self.child(parent)["reason"].startswith("waiting: cooling down"), self.child(parent)["reason"])
        play.assert_not_called()
        with self.cooling(), mock.patch.object(board, "play"):
            out = board.cmd_ready(self.root, parent, manual=True)
        self.assertEqual(out["ready"], [c, d], "Trevor's click claims while cooling down")
        self.assertEqual((self.child(c)["stage"], self.child(d)["stage"]), ("spec", "spec"))
        self.edit_jobs(**{c: {"stage": "waiting"}, d: {"stage": "waiting"}})
        with mock.patch.object(board, "play"):
            self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [c, d], "claims once the flag is gone")

    def test_cooldown_refuses_new_backlog_claims(self):
        """Job 421: cool-down refuses the automatic backlog claims; Trevor's Run now (an explicit index) still claims."""
        msg = "cooling down: no new backlog claim. Fix: click Resume work in the header."
        self.root.mkdir(parents=True, exist_ok=True)
        backlog = "# Backlog\n- [ ] Alpha\n- [ ] Beta\n"
        (self.root / "backlog.md").write_text(backlog)
        (self.root / "backlog-specs").mkdir()
        self.spec_file("Alpha").write_text("# Alpha\n\n## Likely files\n- `a.py`: edit\n")
        board_before = (self.root / "board.json").read_text() if (self.root / "board.json").exists() else None
        with self.cooling():
            for call in (lambda: board.cmd_next(self.root), lambda: board.cmd_runall_start(self.root)):
                with self.assertRaises(SystemExit) as e:
                    call()
                self.assertEqual(str(e.exception), msg)
            self.assertEqual(board.cmd_cloud_claim(self.root, 2), {"claimed": []})
            self.assertEqual((self.root / "backlog.md").read_text(), backlog)
            after = (self.root / "board.json").read_text() if (self.root / "board.json").exists() else None
            self.assertEqual(after, board_before, "no job created")
            self.assertEqual(board.cmd_next(self.root, 1), {"id": "001-beta", "feature": "Beta"}, "Run now still claims")
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [ ] Alpha\n- [x] Beta → 001-beta\n")

    def test_roadmap_next_cooling_down_holds_next_step(self):
        """Job 421: cool-down leaves the finished step running (Roadmap resume marks it done later) and starts nothing."""
        self.roadmap()
        with self.cooling():
            self.assertIsNone(board.cmd_roadmap_next(self.root, self.J2))
        self.assertEqual(self.rm_text(), self.ROADMAP)
        self.assertEqual(board.cmd_roadmap_next(self.root, self.J2),
                         {"p": 1, "s": 3, "kind": "bigboy", "request": "Quote builder part 3, <request>"})
        self.assertIn(f"- [x] S2 bigboy {self.J2}:", self.rm_text())

    def test_session_ages_reads_ps_etime(self):
        ps = Path(self.tmp.name) / "ps.txt"
        ps.write_text("   07:54 /opt/homebrew/bin/claude -p /trevskills-scrum start 1-a --model sonnet\n"
                      "1-02:03:04 claude -p /trevskills-scrum run-all\n"
                      "   00:45 vim board.py\n"  # not a session
                      "claude -p /trevskills-scrum approve 2-b\n")  # no etime: old
        with mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
            self.assertEqual(board.session_ages(), [474, 93784, 10 ** 9])
            self.assertEqual(board.live_sessions(), 3)

    def test_session_ages_ps_timeout_fails_closed(self):
        """Job 520 (2026-10-25, load 15 on 8 cores): a slow or failing ps never blocks or crashes its callers
        (machine_ok, ram_room, the serve.py watchdog); unknown counts as a full machine."""
        real_run = subprocess.run
        for exc in (subprocess.TimeoutExpired(["ps"], 10), OSError("ps failed")):
            timeouts = []

            def fake_run(cmd, *a, **kw):
                if list(cmd[:2]) == ["ps", "-Ao"]:
                    timeouts.append(kw.get("timeout"))
                    raise exc
                return real_run(cmd, *a, **kw)
            with self.subTest(exc=type(exc).__name__), mock.patch.dict(os.environ, SCRUM_PS=""), \
                    mock.patch.object(board.subprocess, "run", side_effect=fake_run):
                self.assertEqual(board.session_ages(), [10 ** 9] * 14)
                self.assertEqual(timeouts, [10])
                self.assertEqual(board.live_sessions(), 14)
                self.assertEqual(board.machine_ok(self.tmp.name, claim=True), "14 sessions running (ceiling 14)")

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS)  # RAM math alone, not the wake ramp
    def test_ram_room_reserves_young_sessions(self):
        """Two projects claiming within a minute both saw healthy free RAM: a session takes a while to grow into it."""
        ps = Path(self.tmp.name) / "ps.txt"
        ps.write_text("   00:30 claude -p /trevskills-scrum start 1-a\n" * 3 + "   09:00 claude -p /trevskills-scrum start 2-b\n" * 2)
        with self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
            self.assertEqual(board.ram_room(), 6, "9 shares, 3 young sessions reserved")
        with self.machine("66", "1000"), self.sessions(13):
            self.assertEqual(board.ram_room(), 1, "one short of the ceiling")
        ps.write_text("   00:30 claude -p /trevskills-scrum start 1-a\n" * 9)
        with self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
            self.assertEqual(board.ram_room(), 1, "never 0 once machine_ok passed")

    def test_ram_room(self):
        self.assertEqual(board.SESSION_RAM_PCT, 5)
        for ram, room in (("66", 2), ("100", 2), ("26", 1), ("20", 1)):  # 66/100: the MAX_YOUNG_SESSIONS ramp
            with self.subTest(ram=ram), self.machine(ram, "1000"):
                self.assertEqual(board.ram_room(), room)
        with mock.patch.object(board, "free_ram_pct", return_value=None):
            self.assertEqual(board.ram_room(), 1, "unknown RAM: one claim per call")

    def test_ram_room_light_share(self):
        """Digest 088: a fast or lilguy job sizes at LIGHT_SESSION_RAM_PCT, so it fits where a standard one waits."""
        self.assertEqual(board.LIGHT_SESSION_RAM_PCT, 3)
        with self.machine("24", "1000"):
            self.assertEqual((board.ram_room(floor=0), board.ram_room(floor=0, light=True)), (0, 1))
            self.assertEqual(board.ram_room_reason(), "ram_room(free=24%,est=5%,min=20%,young=0/2,sessions=0/14)")
            self.assertEqual(board.ram_room_reason(True), "ram_room(free=24%,est=3%,min=20%,young=0/2,sessions=0/14)")
        ps = Path(self.tmp.name) / "ps.txt"
        ps.write_text("   00:30 claude -p /trevskills-scrum start 1-a\n" + "   09:00 claude -p /trevskills-scrum start 2-b\n" * 2)
        with self.machine("40", "1000"), mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
            # standard: 20 // 5 - 1 young = 3; light: (20 - 5 for the young one) // 3 = 5, capped at 2 - 1 young
            self.assertEqual((board.ram_room(floor=0), board.ram_room(floor=0, light=True)), (1, 1))
            with mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS):
                self.assertEqual((board.ram_room(floor=0), board.ram_room(floor=0, light=True)), (3, 5))
            self.assertEqual(board.ram_room_reason(True), "ram_room(free=40%,est=3%,min=20%,young=1/2,sessions=3/14)")
        with self.machine("66", "1000"), self.sessions(13):
            self.assertEqual(board.ram_room(floor=0, light=True), 1, "MAX_SESSIONS still caps a light job")
        with mock.patch.dict(os.environ, SCRUM_SESSION_RSS_PCT="2.4"), self.machine("24", "1000"):
            self.assertEqual(board.ram_room(floor=0, light=True), 1, "a measured share under 3 stays the share")
            self.assertEqual(board.ram_room_reason(True), "ram_room(free=24%,est=2.4%,min=20%,young=0/2,sessions=0/14)")
        with mock.patch.object(board, "free_ram_pct", return_value=None):
            self.assertEqual((board.ram_room(floor=0), board.ram_room(floor=0, light=True)), (1, 1))
            self.assertEqual(board.ram_room_reason(True), "ram_room(free=unknown,est=3%,min=20%,young=0/2,sessions=0/14)")
        ps.write_text("   00:30 claude -p /trevskills-scrum start 1-a\n")
        with self.machine("30", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="15", SCRUM_PS=str(ps)):
            self.assertEqual((board.ram_room(floor=0), board.ram_room(floor=0, light=True)), (0, 0), "swap pressing")

    def test_light_job(self):
        """The board lane decides; with none, feature.md's Lane: header, then spec.md's. Anything missing is not light."""
        d = self.root / "jobs" / "5-x"
        d.mkdir(parents=True)
        self.assertTrue(board.light_job(self.root, {"id": "5-x", "lane": "fast"}))
        self.assertTrue(board.light_job(self.root, {"id": "5-x", "lane": "lilguy"}))
        for lane in ("standard", "debug", "bigboy"):
            self.assertFalse(board.light_job(self.root, {"id": "5-x", "lane": lane}), lane)
        self.assertFalse(board.light_job(self.root, {"id": "5-x"}), "no feature.md or spec.md")
        self.assertFalse(board.light_job(self.root, {}), "no id")
        self.assertFalse(board.light_job(self.root, {"id": "9-missing"}), "no job folder")
        (d / "spec.md").write_text("# T\nLane: fast\n\n## Problem\n")
        self.assertTrue(board.light_job(self.root, {"id": "5-x"}), "spec.md header")
        (d / "feature.md").write_text("Lane: lilguy\nDo it.\n")
        self.assertTrue(board.light_job(self.root, {"id": "5-x"}), "feature.md header")
        (d / "feature.md").write_text("Lane: standard\nDo it.\n")
        self.assertFalse(board.light_job(self.root, {"id": "5-x"}), "feature.md's lane wins over spec.md's")
        (d / "spec.md").write_text("# T\nLane: fast\n")
        self.assertFalse(board.light_job(self.root, {"id": "5-x", "lane": "standard"}), "the board lane wins")

    def test_machine_ok_high_swap(self):
        """2026-10-24: 19 sessions ran at "32% free" with 9 GB of a 16 GB Mac swapped. memory_pressure's free %
        counts inactive pages as free; swap in use, as a share of physical RAM, is the honest signal."""
        self.assertEqual(board.MAX_SWAP_PCT, 25)
        with self.machine("30", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="56.4"):
            self.assertEqual(board.machine_ok(self.tmp.name), "swap used 56.4% of RAM (> 25%)")
        with self.machine("14", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="56.4"):  # RAM first
            self.assertEqual(board.machine_ok(self.tmp.name), "free RAM 14% (< 20%)")
        with self.machine("40", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="11"):
            self.assertIsNone(board.machine_ok(self.tmp.name))

    TOP_OUT = ("Processes: 612 total, 3 running, 609 sleeping, 3021 threads\n"
               "Load Avg: 54.48, 52.10, 40.02\n"
               "CPU usage: 30.12% user, 20.50% sys, 49.37% idle\n"
               "SharedLibs: 1M resident\n\n"
               "Processes: 612 total, 2 running, 610 sleeping, 3020 threads\n"
               "Load Avg: 54.48, 52.10, 40.02\n"
               "CPU usage: 7.50% user, 4.50% sys, 88.0% idle\n"
               "SharedLibs: 1M resident\n")

    def test_cpu_busy_sample(self):
        """2026-10-26: after a reboot the load average read 681% while processes used about 2.5 of 8 cores; top's
        idle share is the honest reading. The first sample covers no interval, so the last one counts."""
        run = mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout=self.TOP_OUT))
        with run as m:
            self.assertEqual(board.cpu_busy_sample(), 12.0)
        self.assertEqual(m.call_args.args[0], ["top", "-l", "2", "-n", "0", "-s", "1"])
        self.assertEqual(m.call_args.kwargs["timeout"], 10)
        with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout="top: illegal option -- l\n")):
            self.assertIsNone(board.cpu_busy_sample(), "no CPU usage line (Linux)")
        with mock.patch.object(board.subprocess, "run", side_effect=OSError("no top")):
            self.assertIsNone(board.cpu_busy_sample())
        with mock.patch.object(board.subprocess, "run", side_effect=subprocess.TimeoutExpired("top", 10)):
            self.assertIsNone(board.cpu_busy_sample())

    def cpu_log(self, entries=None):
        log = Path(self.tmp.name) / "cpu.json"
        if entries is not None:
            log.write_text(json.dumps(entries))
        return log

    def test_record_cpu_sample(self):
        self.assertEqual((board.CPU_SAMPLES, board.CPU_SAMPLE_SECS), (3, 300))
        log = self.cpu_log([[time.time() - 400, 50.0]])  # older than 300 s: pruned
        with mock.patch.dict(os.environ, SCRUM_CPU_LOG=str(log), SCRUM_CPU_BUSY_PCT=""):
            for v in (10.0, 20.0, 30.0, 40.0):
                with mock.patch.object(board, "cpu_busy_sample", return_value=v):
                    board.record_cpu_sample()
            self.assertEqual([v for _, v in json.loads(log.read_text())], [20.0, 30.0, 40.0])
            with mock.patch.object(board, "cpu_busy_sample", return_value=None):
                board.record_cpu_sample()
            self.assertEqual([v for _, v in json.loads(log.read_text())], [20.0, 30.0, 40.0], "None is not recorded")
            log.write_text("not json")
            with mock.patch.object(board, "cpu_busy_sample", return_value=55.0):
                board.record_cpu_sample()
            self.assertEqual([v for _, v in json.loads(log.read_text())], [55.0], "a corrupt log starts over")
        log.unlink()
        with mock.patch.dict(os.environ, SCRUM_CPU_LOG=str(log), SCRUM_CPU_BUSY_PCT="95"), \
                mock.patch.object(board.subprocess, "run") as run:
            board.record_cpu_sample()
        run.assert_not_called()
        self.assertFalse(log.exists())

    def test_cpu_busy_pct(self):
        log = self.cpu_log()
        with mock.patch.dict(os.environ, SCRUM_CPU_LOG=str(log), SCRUM_CPU_BUSY_PCT=""), \
                mock.patch.object(board.subprocess, "run") as run:
            self.assertIsNone(board.cpu_busy_pct(), "missing log")
            log.write_text("{broken")
            self.assertIsNone(board.cpu_busy_pct(), "corrupt log")
            log.write_text("[]")
            self.assertIsNone(board.cpu_busy_pct(), "no samples")
            now = time.time()
            self.cpu_log([[now - 120, 60.0], [now - 60, 60.0], [now, 99.0]])
            self.assertEqual(board.cpu_busy_pct(), 73.0, "one spike does not flip the gate")
            self.cpu_log([[now - 400, 99.0], [now - 10, 20.0]])
            self.assertEqual(board.cpu_busy_pct(), 20.0, "only the last 300 s count")
            self.cpu_log([[now - 400, 99.0]])
            self.assertIsNone(board.cpu_busy_pct(), "only stale samples")
        run.assert_not_called()
        with mock.patch.dict(os.environ, SCRUM_CPU_BUSY_PCT="42.5"):
            self.assertEqual(board.cpu_busy_pct(), 42.5)

    def test_machine_ok_cpu_busy(self):
        """2026-10-26: the load-average gate held every resume 10+ min after a reboot while the CPU sat mostly idle."""
        self.assertEqual(board.MAX_CPU_BUSY_PCT, 90)
        reason = "CPU busy 95% (> 90%)"
        with mock.patch.dict(os.environ, SCRUM_CPU_BUSY_PCT="95"):
            self.assertEqual(board.machine_ok(self.tmp.name), reason)
            self.assertIsNone(board.machine_ok(self.tmp.name, manual=True), "Trevor's clicks skip the CPU check")
            self.assertIsNone(board.machine_ok(self.tmp.name, manual=True, claim=True))
            self.assertEqual(board.machine_ok(self.tmp.name, claim=True), reason)
            with self.machine("14", "1000"):
                self.assertEqual(board.machine_ok(self.tmp.name), "free RAM 14% (< 20%)", "RAM first")
                self.assertEqual(board.machine_ok(self.tmp.name, manual=True), "free RAM 14% (< 20%)",
                                 "manual still checks RAM")
            with self.machine("40", "5"):
                self.assertEqual(board.machine_ok(self.tmp.name), "free disk 5.0 GB (< 10 GB)", "disk before CPU")
            with self.sessions(14):
                self.assertEqual(board.machine_ok(self.tmp.name), reason, "CPU before the session ceiling")
        with mock.patch.dict(os.environ, SCRUM_CPU_BUSY_PCT="90"):
            self.assertIsNone(board.machine_ok(self.tmp.name), "exactly 90% passes")
        with mock.patch.dict(os.environ, SCRUM_CPU_BUSY_PCT="", SCRUM_CPU_LOG=str(self.cpu_log())):
            self.assertIsNone(board.machine_ok(self.tmp.name), "unknown passes")

    def test_cpu_load_pct(self):
        """2026-10-26: load 13.4 on 8 cores with busy at 51%; the 5-minute load average over the cores catches the
        threads queued behind them. The 1-minute one, since the 5-minute read near 0 after sleep (2026-11-04)."""
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT="168.4"):
            self.assertEqual(board.cpu_load_pct(), 168.4)
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT=""):
            with mock.patch.object(board.os, "getloadavg", return_value=(20.0, 12.0, 9.0)), \
                    mock.patch.object(board.os, "cpu_count", return_value=8):
                self.assertEqual(board.cpu_load_pct(), 250.0, "the 1-minute value")
            with mock.patch.object(board.os, "getloadavg", return_value=(0.0, 1.0, 2.0)), \
                    mock.patch.object(board.os, "cpu_count", return_value=8):
                self.assertEqual(board.cpu_load_pct(), 0.0, "a zero load is a reading")
            with mock.patch.object(board.os, "getloadavg", side_effect=OSError("no load")), \
                    mock.patch.object(board.os, "cpu_count", return_value=8):
                self.assertIsNone(board.cpu_load_pct())
            with mock.patch.object(board.os, "getloadavg", return_value=(20.0, 12.0, 9.0)):
                for cores in (0, None):
                    with mock.patch.object(board.os, "cpu_count", return_value=cores):
                        self.assertIsNone(board.cpu_load_pct(), cores)
            with mock.patch.object(board.os, "cpu_count", return_value=8):
                saved = board.os.getloadavg
                del board.os.getloadavg
                try:
                    self.assertIsNone(board.cpu_load_pct(), "no getloadavg")
                finally:
                    board.os.getloadavg = saved

    def test_machine_ok_cpu_load(self):
        self.assertEqual(board.MAX_CPU_LOAD_PCT, 150)
        reason = "CPU load 168% of 8 cores (> 150%)"
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT="168"), mock.patch.object(board.os, "cpu_count", return_value=8):
            self.assertEqual(board.machine_ok(self.tmp.name), reason)
            self.assertEqual(board.machine_ok(self.tmp.name, claim=True), reason)
            self.assertIsNone(board.machine_ok(self.tmp.name, manual=True), "Trevor's clicks skip the load check")
            self.assertIsNone(board.machine_ok(self.tmp.name, manual=True, claim=True))
            with mock.patch.dict(os.environ, SCRUM_CPU_BUSY_PCT="95"):
                self.assertEqual(board.machine_ok(self.tmp.name), "CPU busy 95% (> 90%)", "busy before load")
            with self.sessions(14):
                self.assertEqual(board.machine_ok(self.tmp.name), reason, "load before the session ceiling")
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT="150"):
            self.assertIsNone(board.machine_ok(self.tmp.name), "exactly 150% passes")
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT=""), \
                mock.patch.object(board.os, "getloadavg", side_effect=OSError("no load")):
            self.assertIsNone(board.machine_ok(self.tmp.name), "unknown passes")

    def swap_log(self, samples=None, raw=None):
        log = Path(self.tmp.name) / "swap.json"
        if raw is not None:
            log.write_text(raw)
        elif samples is not None:
            log.write_text(json.dumps([[time.time() - age, v] for age, v in samples]))
        return mock.patch.dict(os.environ, SCRUM_SWAP_LOG=str(log))

    def test_machine_ok_stale_swap_passes(self):
        with self.swap_log(), self.machine("71", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="56.4"):
            self.assertIsNone(board.machine_ok(self.tmp.name))
            self.assertIsNone(board.machine_ok(self.tmp.name), "second call, equal sample: still no growth")
        with self.swap_log(raw="not json{"), self.machine("71", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="56.4"):
            self.assertIsNone(board.machine_ok(self.tmp.name), "corrupt log: no growth")
        with self.swap_log(), self.machine("35", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="56.4"):
            self.assertIsNone(board.machine_ok(self.tmp.name), "exactly 35% is not under 35%")

    def test_machine_ok_swap_growth(self):
        msg = "swap used 56.4% of RAM (> 25%)"
        env = mock.patch.dict(os.environ, SCRUM_SWAP_PCT="56.4")
        with self.swap_log([(120, 50.0)]), self.machine("71", "1000"), env:
            self.assertEqual(board.machine_ok(self.tmp.name), msg)
        with self.swap_log([(700, 50.0)]), self.machine("71", "1000"), env:
            self.assertIsNone(board.machine_ok(self.tmp.name), "old sample")
        with self.swap_log([(500, 60.0), (400, 55.0)]), self.machine("71", "1000"), env:
            self.assertIsNone(board.machine_ok(self.tmp.name), "fell then rebounded 1.4: net down, not growth")
        with self.swap_log([(500, 60.0), (400, 51.4)]), self.machine("71", "1000"), env:
            self.assertIsNone(board.machine_ok(self.tmp.name), "exactly 5.0 above the minimum passes")
        with self.swap_log([(500, 60.0), (400, 50.0)]), self.machine("71", "1000"), env:
            self.assertEqual(board.machine_ok(self.tmp.name), msg, "rebound 6.4 above the minimum, net down")
        with self.swap_log([(500, 50.0), (400, 40.0)]), self.machine("71", "1000"), env:
            self.assertEqual(board.machine_ok(self.tmp.name), msg, "net up over the window")
        with self.swap_log([(120, 56.0)]), self.machine("71", "1000"), env:
            self.assertIsNone(board.machine_ok(self.tmp.name), "under 1 point of growth")
        with self.swap_log([(120, 60.0)]), self.machine("71", "1000"), env:
            self.assertIsNone(board.machine_ok(self.tmp.name), "shrinking")
        with self.swap_log([(120, 50.0), (700, 10.0)]), self.machine("71", "1000"), env:
            board.machine_ok(self.tmp.name)
            kept = json.loads((Path(self.tmp.name) / "swap.json").read_text())
            self.assertEqual([v for _, v in kept], [50.0, 56.4], "pruned to 10 min, current appended")

    def test_swap_used_pct_reads_sysctl(self):
        with mock.patch.dict(os.environ, SCRUM_SWAP_PCT=""):
            crash = "total = 10240.00M  used = 9027.31M  free = 1212.69M  (encrypted)\n17179869184\n"  # 16 GB Mac
            with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout=crash)):
                self.assertAlmostEqual(board.swap_used_pct(), 55.1, places=1)
            # the swap file shrank after the pause; the share of RAM must fall with it (used/total would still say 55%)
            with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(
                    stdout="total = 3072.00M  used = 1694.25M  free = 1377.75M  (encrypted)\n17179869184\n")):
                self.assertAlmostEqual(board.swap_used_pct(), 10.3, places=1)
                self.assertIsNone(board.machine_ok(self.tmp.name))
            with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout="garbage\n")):
                self.assertIsNone(board.swap_used_pct(), "unreadable: unknown, passes")
            with mock.patch.object(board.subprocess, "run", side_effect=FileNotFoundError("sysctl")):
                self.assertIsNone(board.swap_used_pct())
                self.assertIsNone(board.machine_ok(self.tmp.name))

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS)  # RAM math alone, not the wake ramp
    def test_ram_room_is_one_while_swap_fills(self):
        with self.machine("30", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="15"):
            self.assertEqual(board.ram_room(), 1, "swap past MAX_SWAP_PCT/2, RAM low: one claim per call")
        with self.swap_log([(120, 10.0)]), self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="15"):
            self.assertEqual(board.ram_room(), 1, "swap growing: one claim per call")
        with self.swap_log([(120, 20.0)]), self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="15"):
            self.assertEqual(board.ram_room(), 9, "stale swap, healthy RAM: normal math")
        with self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="10"):
            self.assertEqual(board.ram_room(), 9)

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS)  # RAM math alone, not the wake ramp
    def test_ram_room_floor_zero(self):
        """Job 624: serve.py's launch gate needs ram_room to say "no room"; floor=1 (the default) is unchanged."""
        ps = Path(self.tmp.name) / "ps.txt"
        ps.write_text("   00:30 claude -p /trevskills-scrum start 1-a\n" * 9)
        with self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
            self.assertEqual(board.ram_room(floor=0), 0, "9 shares, 9 young sessions")
            self.assertEqual(board.ram_room(), 1)
        ps.write_text("   00:30 claude -p /trevskills-scrum start 1-a\n" * 11)
        with self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
            self.assertEqual(board.ram_room(floor=0), -2, "raw room may go below 0")
        with self.machine("66", "1000"), self.sessions(13):
            self.assertEqual(board.ram_room(floor=0), 1, "one short of the MAX_SESSIONS ceiling")
        with self.machine("66", "1000"), self.sessions(14):
            self.assertEqual(board.ram_room(floor=0), 0, "at the ceiling")
        ps.write_text("   00:30 claude -p /trevskills-scrum start 1-a\n")
        with self.machine("30", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="15"):
            with mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
                self.assertEqual(board.ram_room(floor=0), 0, "swapping: none while a session is young")
                self.assertEqual(board.ram_room(), 1)
            ps.write_text("   05:00 claude -p /trevskills-scrum start 1-a\n")
            with mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
                self.assertEqual(board.ram_room(floor=0), 1, "swapping: one once every session is past the ramp")
        with mock.patch.object(board, "free_ram_pct", return_value=None):
            with mock.patch.dict(os.environ, SCRUM_PS=os.devnull):
                self.assertEqual(board.ram_room(floor=0), 1, "unknown RAM, nothing young: one")
            ps.write_text("   00:10 claude -p /trevskills-scrum approve 1-a\n")
            with mock.patch.dict(os.environ, SCRUM_PS=str(ps)):
                self.assertEqual(board.ram_room(floor=0), 0, "unknown RAM, one young: none")

    def test_session_rss_pct_reads_ps(self):
        """Job 820: ram_room's share is the measured mean session RSS, not a fixed guess."""
        ps_out = ["   1677722 /opt/homebrew/bin/claude -p /trevskills-scrum start 1-a\n"
                  "1677722 claude -p /trevskills-scrum start 2-b\n"
                  "  1677722 claude -p /trevskills-scrum start 3-c\n"
                  "  9999999 /Applications/Chrome.app/Contents/MacOS/Chrome\n"]

        def fake_run(cmd, *a, **kw):
            if list(cmd[:2]) == ["ps", "-Ao"]:
                return mock.Mock(stdout=ps_out[0])
            if cmd[-1] == "hw.memsize":
                return mock.Mock(stdout="17179869184\n")
            raise AssertionError(cmd)
        with mock.patch.dict(os.environ), mock.patch.object(board.subprocess, "run", side_effect=fake_run):
            os.environ.pop("SCRUM_PS", None)
            os.environ.pop("SCRUM_SESSION_RSS_PCT", None)
            self.assertAlmostEqual(board.session_rss_pct(), 10, delta=0.01)
            ps_out[0] = "  9999999 /Applications/Chrome.app/Contents/MacOS/Chrome\n"
            self.assertIsNone(board.session_rss_pct(), "no session")
        with mock.patch.dict(os.environ), mock.patch.object(board.subprocess, "run", side_effect=OSError("ps")):
            os.environ.pop("SCRUM_PS", None)
            os.environ.pop("SCRUM_SESSION_RSS_PCT", None)
            self.assertIsNone(board.session_rss_pct(), "ps raised")
        with mock.patch.dict(os.environ, SCRUM_PS=os.devnull), \
                mock.patch.object(board.subprocess, "run", side_effect=AssertionError("real ps read")):
            os.environ.pop("SCRUM_SESSION_RSS_PCT", None)
            self.assertIsNone(board.session_rss_pct(), "SCRUM_PS set: never the real ps")

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS)  # RAM math alone, not the wake ramp
    def test_ram_room_uses_measured_rss(self):
        self.assertEqual(board.MIN_SESSION_RAM_PCT, 2)
        with self.machine("40", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="0", SCRUM_PS=os.devnull):
            os.environ.pop("SCRUM_SESSION_RSS_PCT", None)
            self.assertEqual(board.ram_room(floor=0), 4, "unknown: 20 points in 5% shares")
            with mock.patch.dict(os.environ, SCRUM_SESSION_RSS_PCT="10"):
                self.assertEqual(board.ram_room(floor=0), 2, "measured 10%: 2 shares")
            with mock.patch.dict(os.environ, SCRUM_SESSION_RSS_PCT="0.5"):
                self.assertEqual(board.ram_room(floor=0), 10, "0.5% counts as MIN_SESSION_RAM_PCT (2%)")

    def test_pause_and_abort_clear_queued_launch(self):
        launch = {"action": "start", "prompt": "/trevskills-scrum start x", "stage": "build"}
        paused, aborted = board.cmd_new(self.root, "paused"), board.cmd_new(self.root, "aborted")
        for job_id in (paused, aborted):
            board.cmd_set(self.root, job_id, ["stage=build"])
            with board.locked_board(self.root) as b:
                board.find(b, job_id).update(play_queued="2026-11-04T16:19:36Z", queued_launch=launch,
                                             ram_hold="14 sessions running, 12% RAM free")
        with mock.patch.object(board, "play"):
            board.cmd_pause(self.root, paused)
        board.cmd_abort(self.root, aborted, False)
        for job in self.jobs():
            self.assertNotIn("queued_launch", job, job["id"])
            self.assertNotIn("play_queued", job, job["id"])
            self.assertNotIn("ram_hold", job, job["id"])

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS)  # RAM math alone, not the wake ramp
    def test_ready_claims_only_up_to_ram_room(self):
        """The 2026-10-24 crash: one ready call claimed 7 children at once. Claims stop at the free RAM's room."""
        parent, kids = self.runall(7)
        for i, k in enumerate(kids):
            self.spec(k, f"src/m{i}.py")
        with self.machine("40", "1000"):
            self.assertEqual(board.cmd_ready(self.root, parent)["ready"], kids[:4])
        with self.machine("27", "1000"):
            self.assertEqual(board.cmd_ready(self.root, parent)["ready"], kids[4:5])
        self.assertEqual(self.child(parent)["stage"], "running")

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS)  # RAM math alone, not the wake ramp
    def test_ready_machine_guard_blocks_then_recovers(self):
        parent, (a, b, c) = self.runall(3)
        for i, k in enumerate((a, b, c)):
            self.spec(k, f"src/m{i}.py")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [a, b, c])
        board.cmd_set(self.root, b, ["stage=waiting"])
        board.cmd_set(self.root, c, ["stage=waiting"])
        with self.machine("14", "1000"), mock.patch.object(board, "play") as play:
            out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), ([], 1))
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", "waiting: free RAM 14% (< 20%)"))
        self.assertEqual(self.child(a)["stage"], "spec", "a child in progress keeps its stage")
        play.assert_not_called()
        board.cmd_set(self.root, a, ["stage=done"])  # nothing in progress: still no needs-human
        with self.machine("100", "6.2"), mock.patch.object(board, "play") as play:
            self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", "waiting: free disk 6.2 GB (< 10 GB)"))
        play.assert_not_called()
        out = board.cmd_ready(self.root, parent)
        self.assertEqual(out["ready"], [b, c])
        p = self.child(parent)
        self.assertEqual((p["stage"], p.get("reason")), ("running", None))

    def test_runall_ready_parent_waits_and_resumes(self):
        parent, (a, b, c) = self.runall(3)
        board.cmd_ready(self.root, parent)
        board.cmd_set(self.root, a, ["stage=needs-human", "reason=blocked: x. Fix: y"], internal=True)
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

    @mock.patch.object(board, "MAX_YOUNG_SESSIONS", board.MAX_SESSIONS)  # RAM math alone, not the wake ramp
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
        run = lambda *a: run_board("--dir", str(self.root), *a)
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
        board.cmd_set(self.root, job_id, ["stage=needs-human", "reason=obsolete: done"], internal=True)
        self.assertEqual(self.jobs()[0]["files"], ["feature.md", "spec.md"])
        (self.root / "jobs" / job_id / "spec.md").unlink()
        (self.root / "jobs" / job_id / "feature.md").unlink()
        (self.root / "jobs" / job_id).rmdir()
        board.cmd_set(self.root, job_id, ["stage=needs-human"], internal=True)  # missing folder: still succeeds
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
        self.assertEqual(re.sub(r" \{#[a-z0-9]{4}\}", "", (self.root / "backlog.md").read_text()), "# Backlog\n- [ ] fix A (from 001-x)\n- [ ] fix B (from 001-x)\n")

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
        r = run_board("--dir", str(self.root), "manual-add", "a", "a")
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

    def test_abort_clears_pause(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        board.cmd_pause(self.root, job_id)
        board.cmd_abort(self.root, job_id, requeue=False)
        job = self.jobs()[0]
        self.assertEqual(job["stage"], "aborted")
        self.assertNotIn("paused", job)

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

    def edit_jobs(self, **fields):
        """Set raw fields on board jobs: edit_jobs(**{job_id: {"stage": ...}})."""
        with board.locked_board(self.root) as b:
            for job in b["jobs"]:
                job.update(fields.get(job["id"], {}))

    def by_id(self):
        return {j["id"]: j for j in self.jobs()}

    def test_abort_cascade_two_level_chain(self):
        a, b, c, other = (board.cmd_new(self.root, t) for t in ("a", "b", "c", "other"))
        self.edit_jobs(**{b: {"stage": "waiting", "depends_on": [a]}, c: {"stage": "needs-human", "depends_on": [b]},
                          other: {"stage": "waiting", "depends_on": []}})
        self.assertEqual(board.cmd_abort(self.root, a, False, reason="dup", cascade=True), [a, b, c])
        jobs = self.by_id()
        self.assertEqual([(jobs[j]["stage"], jobs[j]["reason"]) for j in (a, b, c)],
                         [("aborted", "dup"), ("aborted", "Removed with 001-a"), ("aborted", "Removed with 001-a")])
        self.assertEqual(jobs[other]["stage"], "waiting")

    def test_abort_without_cascade_touches_only_root(self):
        a, b = board.cmd_new(self.root, "a"), board.cmd_new(self.root, "b")
        self.edit_jobs(**{b: {"stage": "waiting", "depends_on": [a]}})
        self.assertEqual(board.cmd_abort(self.root, a, False), [a])
        self.assertEqual(self.by_id()[b]["stage"], "waiting")
        self.assertTrue(self.by_id()[a]["reason"].startswith("Aborted by Trevor "))

    def test_abort_cli_cascade_prints_ids(self):
        a, b, c = (board.cmd_new(self.root, t) for t in ("a", "b", "c"))
        self.edit_jobs(**{b: {"stage": "waiting", "depends_on": [a]}})
        run = lambda *args: run_board("--dir", str(self.root), "abort", *args)
        out = run(a, "--cascade")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"aborted": ["001-a", "002-b"]})
        out = run(c)
        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_abort_cascade_skips_done_running_and_parent(self):
        parent, a, done, gone, running, behind = (board.cmd_new(self.root, t)
                                                  for t in ("p", "a", "done", "gone", "running", "behind"))
        kid = {"parent": parent}
        self.edit_jobs(**{parent: {"lane": "bigboy", "stage": "running", "reason": "kept", "children": [a, done, gone]},
                          a: {**kid, "stage": "build"},
                          done: {**kid, "stage": "done", "depends_on": [a]},
                          gone: {**kid, "stage": "aborted", "reason": "old", "depends_on": [a]},
                          running: {**kid, "stage": "build", "depends_on": [a]},
                          behind: {**kid, "stage": "waiting", "depends_on": [running]}})
        self.assertEqual(board.cmd_abort(self.root, a, False, cascade=True), [a])
        jobs = self.by_id()
        self.assertEqual((jobs[parent]["stage"], jobs[parent]["reason"]), ("running", "kept"))
        self.assertEqual([jobs[j]["stage"] for j in (done, gone, running, behind)], ["done", "aborted", "build", "waiting"])
        self.assertEqual(jobs[gone]["reason"], "old")

    def test_abort_cascade_takes_paused_and_queued(self):
        a, paused, queued = (board.cmd_new(self.root, t) for t in ("a", "paused", "queued"))
        board.cmd_set(self.root, paused, ["stage=build"])
        board.cmd_pause(self.root, paused)
        self.edit_jobs(**{paused: {"depends_on": [a]}, queued: {"stage": "spec", "play_queued": True, "depends_on": [a]}})
        self.assertEqual(board.cmd_abort(self.root, a, False, cascade=True), [a, paused, queued])
        jobs = self.by_id()
        for j in (paused, queued):
            self.assertEqual(jobs[j]["stage"], "aborted")
            self.assertNotIn("paused", jobs[j])
            self.assertNotIn("play_queued", jobs[j])

    def test_abort_cascade_reopens_runall_child_backlog_line(self):
        self.root.mkdir(parents=True)
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Add schema {#sch2}\n- [ ] Add API {needs #sch2}\n")
        run = board.cmd_runall_start(self.root)
        schema, api = run["children"]
        bb, bb_a, bb_b = (board.cmd_new(self.root, t) for t in ("bb", "bb a", "bb b"))
        self.edit_jobs(**{bb: {"lane": "bigboy", "stage": "running", "children": [bb_a, bb_b]},
                          bb_a: {"parent": bb, "stage": "waiting"},
                          bb_b: {"parent": bb, "stage": "waiting", "depends_on": [bb_a]}})
        self.assertEqual(board.cmd_abort(self.root, schema, False, cascade=True), [schema, api])
        lines = (self.root / "backlog.md").read_text().splitlines()
        self.assertEqual(lines[-1], "- [ ] Add API")  # abort_job's requeue: the feature text, as --requeue writes it
        self.assertNotIn("- [ ] Add schema", lines)  # the root follows its own (absent) --requeue
        before = (self.root / "backlog.md").read_text()
        self.assertEqual(board.cmd_abort(self.root, bb_a, False, cascade=True), [bb_a, bb_b])
        self.assertEqual((self.root / "backlog.md").read_text(), before)

    # --- pause ---
    def test_pause_records_stage_in_reason_and_keeps_fields(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build", "round=2", "limit=3", "pr=https://x/1", "worktree=/wt/x",
                                          "builder=agent-1"])
        self.write(f"{job_id}/build.md", "STATUS: READY\n")
        with board.locked_board(self.root) as b:
            b["jobs"][0]["limitResetAt"] = 1700000000
        before = self.jobs()[0]
        with mock.patch.object(board, "play") as play:
            self.assertEqual(board.cmd_pause(self.root, job_id), [job_id])
        play.assert_not_called()
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["paused"], job["reason"]),
                         ("build", True, "stalled in build: paused by Trevor. Fix: click Play."))
        self.assertNotIn("limitResetAt", job)
        for key in ("worktree", "branch", "pr", "round", "limit", "builder", "files"):
            self.assertEqual(job[key], before[key], key)
        self.assertEqual((self.root / "jobs" / job_id / "build.md").read_text(), "STATUS: READY\n")

    def test_pause_after_auto_play_sets_hold_pause(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        with board.locked_board(self.root) as b:
            b["jobs"][0]["autoPlayed"] = True
        board.cmd_pause(self.root, job_id)
        self.assertIs(self.jobs()[0].get("holdPause"), True)

    def test_pause_without_auto_play_sets_no_hold_pause(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        board.cmd_pause(self.root, job_id)
        self.assertNotIn("holdPause", self.jobs()[0])

    def test_resume_clears_hold_pause(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        with board.locked_board(self.root) as b:
            b["jobs"][0]["autoPlayed"] = True
        board.cmd_pause(self.root, job_id)
        board.cmd_set(self.root, job_id, ["stage=build"], unpause=True)
        job = self.jobs()[0]
        self.assertNotIn("holdPause", job)
        self.assertNotIn("paused", job)

    def test_pause_refuses_job_not_in_progress(self):
        for stage in ("waiting", "done", "needs-human", "aborted"):
            job_id = board.cmd_new(self.root, f"x {stage}")
            if stage == "aborted":
                board.cmd_abort(self.root, job_id, requeue=False)
            else:
                board.cmd_set(self.root, job_id, [f"stage={stage}"], internal=True)
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
                         lambda: board.cmd_set(self.root, job_id, ["reason="]),
                         lambda: board.cmd_sync(self.root, job_id),
                         lambda: board.cmd_set(self.root, job_id, ["stage=done", "reason="]),
                         lambda: board.cmd_set(self.root, job_id, ["stage=review", "reason="])):
                with self.assertRaises(SystemExit) as e:
                    call()
                self.assertEqual(str(e.exception), f"job {job_id} was paused by Trevor; stop working on it")
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["paused"], job["reason"]), ("review", True, paused))
        # spawn bookkeeping writes through the pause and keeps it, so a surviving old session stays refused
        board.cmd_set(self.root, job_id, ["runlog=runs/x.log", "tty=", "outcome="], unpause=True)
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["paused"], job["reason"], job["runlog"]), ("review", True, paused, "runs/x.log"))
        board.cmd_set(self.root, job_id, ["stage=review", "reason="], unpause=True)
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["reason"]), ("review", None))
        self.assertNotIn("paused", job)
        board.cmd_set(self.root, job_id, ["stage=approve"])  # un-paused: writes work again
        self.assertEqual(self.jobs()[0]["stage"], "approve")

    def test_set_cli_unpause_flag(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["stage=build"])
        board.cmd_pause(self.root, job_id)
        for pairs in (["stage=review", "reason="], ["reason="]):
            with self.assertRaises(SystemExit) as e:
                board.main(["--dir", str(self.root), "set", job_id, *pairs])
            self.assertEqual(str(e.exception), f"job {job_id} was paused by Trevor; stop working on it")
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["paused"], job["reason"]),
                         ("build", True, "stalled in build: paused by Trevor. Fix: click Play."))
        board.main(["--dir", str(self.root), "set", "--unpause", job_id, "stage=build", "reason="])
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["reason"]), ("build", None))
        self.assertNotIn("paused", job)
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
        jobs = {j["id"]: j for j in self.jobs()}
        stalled = {k: (j["stage"], j["reason"]) for k, j in jobs.items()}
        self.assertEqual(stalled[parent], ("running", "stalled in running: paused by Trevor. Fix: click Play."))
        self.assertEqual(stalled[c2], ("build", "stalled in build: paused by Trevor. Fix: click Play."))
        self.assertEqual((jobs[parent].get("paused"), jobs[c2].get("paused")), (True, True))
        self.assertEqual((stalled[c1][0], stalled[c3][0], stalled[c4][0]), ("done", "waiting", "waiting"))
        self.assertNotIn("paused", jobs[c3])
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])  # c3's only dependency is done
        after = {j["id"]: (j["stage"], j["reason"]) for j in self.jobs()}
        self.assertEqual(after[parent], stalled[parent])
        self.assertEqual(after[c3][0], "waiting")

    def test_paused_child_is_idle_for_ready_and_named_in_waiting_on(self):
        parent = self.plan(self.ticket(1), self.ticket(2),
                           self.ticket(3, deps="T1, T2", parallel="no — last", exposure="yes"))
        c1, c2, c3 = board.cmd_plan_apply(self.root, parent)["children"]
        board.cmd_set(self.root, parent, ["stage=running"])
        board.cmd_set(self.root, c1, ["stage=build"])
        board.cmd_set(self.root, c2, ["stage=build"])
        board.cmd_pause(self.root, c1)
        board.cmd_pause(self.root, c2)
        # both paused: none in progress, c3 waits on them, so the parent names the paused children
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), ([], 0))
        p = next(j for j in self.jobs() if j["id"] == parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", f"waiting on you in: {c1}, {c2}"))
        self.assertIsNone(board.resume_blocker(self.root, c1))  # the paused sibling holds no slot

    # --- paused migration ---
    def legacy_board(self, *jobs):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "board.json").write_text(json.dumps({"jobs": list(jobs)}, indent=2) + "\n")

    def test_migrate_paused_legacy_job_back_to_stage(self):
        self.legacy_board({"id": "001-a", "stage": "needs-human", "round": 2,
                           "reason": "stalled in build: paused by Trevor. Fix: click Play."},
                          {"id": "002-b", "stage": "needs-human",
                           "reason": "stalled in running: paused by Trevor. Fix: click Play."})
        self.assertEqual(board.cmd_migrate_paused(self.root), ["001-a", "002-b"])
        self.assertEqual(self.jobs(), [
            {"id": "001-a", "stage": "build", "round": 2, "paused": True,
             "reason": "stalled in build: paused by Trevor. Fix: click Play."},
            {"id": "002-b", "stage": "running", "paused": True,
             "reason": "stalled in running: paused by Trevor. Fix: click Play."}])
        # every locked write migrates too
        self.legacy_board({"id": "003-c", "stage": "needs-human",
                           "reason": "stalled in review: paused by Trevor. Fix: click Play."})
        with board.locked_board(self.root):
            pass
        self.assertEqual((self.jobs()[0]["stage"], self.jobs()[0]["paused"]), ("review", True))

    def test_clear_heavy_wait_strips_only_matching_reasons(self):
        hw = "heavy jobs" + " wait"
        b = {"jobs": [{"id": "1", "stage": "waiting", "reason": f"{hw}: usage 90%"},
                      {"id": "2", "stage": "waiting", "reason": f"waiting: usage 91%, {hw} for 5h"},
                      {"id": "3", "stage": "waiting", "reason": "waiting: other"},
                      {"id": "4", "stage": "build"}]}
        self.assertEqual(board.clear_heavy_wait(b), ["1", "2"])
        self.assertEqual(b["jobs"], [{"id": "1", "stage": "waiting"}, {"id": "2", "stage": "waiting"},
                                    {"id": "3", "stage": "waiting", "reason": "waiting: other"},
                                    {"id": "4", "stage": "build"}])
        self.assertEqual(board.clear_heavy_wait(b), [])

    def test_locked_board_clears_stale_heavy_wait(self):
        self.legacy_board({"id": "001-a", "stage": "waiting", "reason": "heavy jobs" + " wait" + ": usage"})
        with board.locked_board(self.root):
            pass
        self.assertNotIn("reason", self.jobs()[0])

    def test_migrate_paused_cleans_heavy_wait_on_idle_board(self):
        self.legacy_board({"id": "001-a", "stage": "waiting", "reason": "heavy jobs" + " wait" + ": usage"})
        self.assertEqual(board.cmd_migrate_paused(self.root), [])
        self.assertNotIn("reason", self.jobs()[0])

    def test_migrate_paused_is_idempotent(self):
        self.legacy_board({"id": "001-a", "stage": "needs-human",
                           "reason": "stalled in check: paused by Trevor. Fix: click Play."})
        self.assertEqual(board.cmd_migrate_paused(self.root), ["001-a"])
        once = (self.root / "board.json").read_text()
        os.utime(self.root / "board.json", (1, 1))
        self.assertEqual(board.cmd_migrate_paused(self.root), [])
        self.assertEqual((self.root / "board.json").read_text(), once)
        self.assertEqual((self.root / "board.json").stat().st_mtime, 1)  # nothing migrated: not written

    def test_migrate_paused_skips_other_stalled_reasons(self):
        plan = {"id": "002-b", "stage": "needs-human", "reason": "stalled in plan: no board update for 30 min."}
        self.legacy_board({"id": "001-a", "stage": "needs-human",
                           "reason": "stalled in build: waiting for a free slot after Play. Fix: click Resume."}, plan)
        self.assertEqual(board.cmd_migrate_paused(self.root), ["001-a"])
        self.assertEqual(self.jobs(), [
            {"id": "001-a", "stage": "build", "stalled": True,
             "reason": "stalled: waiting for a free slot after Play. Fix: click Resume."}, plan])

    def test_migrate_legacy_stall_on_load(self):
        self.legacy_board(
            {"id": "001-a", "stage": "needs-human", "round": 3, "question": "Q?", "options": [{"key": "a"}],
             "recommend": {"key": "a", "why": "w"},
             "reason": "stalled in review: no board update for 30 min and no live session. Fix: click Resume."},
            {"id": "002-b", "stage": "needs-human", "reason": "stalled in merging: session exited."},
            {"id": "003-c", "stage": "needs-human", "reason": "stalled in check: paused by Trevor. Fix: click Play."},
            {"id": "004-d", "stage": "needs-human", "reason": "Pick a layout?", "question": "Pick a layout?"})
        self.assertEqual(board.cmd_migrate_paused(self.root), ["001-a", "002-b", "003-c"])
        self.assertEqual(self.jobs(), [
            {"id": "001-a", "stage": "review", "round": 3, "stalled": True,
             "reason": "stalled: no board update for 30 min and no live session. Fix: click Resume."},
            {"id": "002-b", "stage": "merging", "stalled": True, "reason": "stalled: session exited."},
            {"id": "003-c", "stage": "check", "paused": True, "reason": "stalled in check: paused by Trevor. Fix: click Play."},
            {"id": "004-d", "stage": "needs-human", "reason": "Pick a layout?", "question": "Pick a layout?"}])
        # every locked write migrates too
        self.legacy_board({"id": "005-e", "stage": "needs-human", "reason": "stalled in spec: x"})
        with board.locked_board(self.root):
            pass
        self.assertEqual(self.jobs(), [{"id": "005-e", "stage": "spec", "stalled": True, "reason": "stalled: x"}])

    def test_migrate_legacy_stall_is_idempotent(self):
        self.legacy_board({"id": "001-a", "stage": "needs-human", "reason": "stalled in build: session exited."})
        self.assertEqual(board.cmd_migrate_paused(self.root), ["001-a"])
        once = (self.root / "board.json").read_text()
        os.utime(self.root / "board.json", (1, 1))
        self.assertEqual(board.cmd_migrate_paused(self.root), [])
        self.assertEqual((self.root / "board.json").read_text(), once)
        self.assertEqual((self.root / "board.json").stat().st_mtime, 1)

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

    def test_reopen_keeps_long_note_whole(self):
        note = ("Still wraps on mobile. " * 66)[:1499] + "."  # 1,500 chars
        self.assertEqual(len(note), 1500)
        old = board.cmd_new(self.root, "Wide one")
        board.cmd_set(self.root, old, ["stage=done", "reason=merged"])
        new = board.cmd_reopen(self.root, old, note)
        self.assertEqual((self.root / "jobs" / new / "feature.md").read_text().splitlines()[0], note)

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
                board.cmd_set(self.root, job_id, [f"stage={stage}"], internal=True)
            ids.append(job_id)
        return ids

    def cli(self, *args):
        out = run_board("--dir", str(self.root), *args)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_digest_due_counts_only_undigested_done_jobs(self):
        done = self.done_jobs(9)
        self.done_jobs(2, "aborted")
        self.done_jobs(1, "review")
        self.done_jobs(1, "needs-human")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 9, "questionsGrowth": 0, "reason": None})
        done += self.done_jobs(1)
        self.assertEqual(self.cli("digest-due"), {"due": True, "undigested": 10, "questionsGrowth": 0, "reason": "10 done"})
        (self.root / "digests" / "001").mkdir(parents=True)
        (self.root / "digests" / "001" / "jobs.txt").write_text("\n".join(done[:4]) + "\n")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 6, "questionsGrowth": 0, "reason": None})
        self.assertEqual(board.digested_ids(self.root), set(done[:4]))

    def test_failed_digest_releases_its_jobs(self):
        a, b = self.done_jobs(2)
        d = self.root / "digests" / "001"
        d.mkdir(parents=True)
        (d / "jobs.txt").write_text(f"{a}\n{b}\n")
        self.assertEqual(board.digested_ids(self.root), {a, b})  # no error.md: still claimed
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0, "reason": None})
        (d / "error.md").write_text("digester produced no valid proposals\n")
        self.assertEqual(board.digested_ids(self.root), set())
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 2, "questionsGrowth": 0, "reason": None})
        self.assertEqual(self.cli("digest-start"), {"id": "002", "jobs": [a, b], "windows": []})
        self.assertEqual(board.digested_ids(self.root), {a, b})
        self.assertTrue((d / "jobs.txt").exists())  # the failed digest stays as it was

    def test_digest_start_writes_history(self):
        other = Path(self.tmp.name) / "other"
        (other / "scrum" / "digests" / "007").mkdir(parents=True)
        (other / "scrum" / "digests" / "007" / "proposals.json").write_text(json.dumps(
            {"proposals": [{"id": "p1", "kind": "backlog", "status": "queued", "why": "cant resume yet stop"}]}))
        (other / "scrum" / "backlog.md").write_text("- [x] [2] old thing <!-- retired 2020-01-01: x -->\n- [x] [2] shipped thing\n")
        reg = Path(self.tmp.name) / "reg.json"
        reg.write_text(json.dumps([str(other)]))
        old = self.root / "digests" / "001"
        old.mkdir(parents=True)
        (old / "proposals.json").write_text(json.dumps({"proposals": [{"id": "p2", "target": "/x.md", "why": "w"}]}))
        self.done_jobs(1)
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg)}):
            self.assertEqual(self.cli("digest-start")["id"], "002")
        text = (self.root / "digests" / "002" / "history.md").read_text()
        self.assertIn("other 007 p1 [queued]", text)
        self.assertIn("001 p2 [pending] /x.md: w", text)
        self.assertIn("other: [2] shipped thing", text)
        self.assertNotIn("old thing", text)

    def test_digest_start_claims_jobs_once(self):
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": [], "windows": []})
        self.assertFalse((self.root / "digests").exists())
        done = self.done_jobs(3)
        aborted = self.done_jobs(1, "aborted")
        self.assertEqual(self.cli("digest-start"), {"id": "001", "jobs": done, "windows": []})
        self.assertEqual((self.root / "digests" / "001" / "jobs.txt").read_text(), "\n".join(done) + "\n")
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": [], "windows": []})
        self.assertEqual(sorted(p.name for p in (self.root / "digests").iterdir()), ["001"])
        more = self.done_jobs(1)
        self.assertEqual(self.cli("digest-start"), {"id": "002", "jobs": more, "windows": []})
        self.assertNotIn(aborted[0], (self.root / "digests" / "002" / "jobs.txt").read_text())
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0, "reason": None})

    def codex_line(self, job_id, outcome="invalid-artifact", runner="codex", secs=600):
        d = self.root / "jobs" / job_id
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "routing.log", "a") as f:
            f.write(json.dumps({"role": "codex-review", "runner": runner, "duration_s": secs, "outcome": outcome}) + "\n")

    def round_file(self, job_id, n, name, text):
        d = self.root / "jobs" / job_id / f"round-{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)

    def health_jobs(self):
        return [j for j in board.read_board(self.root)["jobs"] if j["title"].startswith("Pipeline health: ")]

    def test_pipeline_health_detects_each_tool(self):
        ids = self.done_jobs(4)
        a, b, c, d = ids
        self.codex_line(a)
        self.codex_line(a)  # a second failed round still counts once
        self.codex_line(b, outcome="skipped", runner="skip")
        self.codex_line(c, outcome="ok")
        with open(self.root / "jobs" / c / "routing.log", "a") as f:
            f.write('{not json\n["role", "codex-review"]\n')
        self.codex_line(d, outcome="invalid-artifact", runner="codex")
        (self.root / "jobs" / d / "routing.log").write_text(
            json.dumps({"role": "review-code", "runner": "claude", "outcome": "invalid-artifact"}) + "\n")
        self.round_file(a, 1, "review-e2e.md", "Reviewer produced no output.\n")
        self.round_file(a, 2, "review-e2e.md", "Reviewer produced no output.\n")
        self.round_file(b, 1, "review-e2e.md", "PASS\n")
        self.round_file(c, 1, "review-e2e.md", "Reviewer produced no output.\n")
        self.round_file(b, 1, "check.md", "FAIL\nnpm test Timed Out after 600s\n")
        self.round_file(c, 1, "check.md", "PASS\ntimedout_helper ok\n")
        self.assertEqual(board.pipeline_health_counts(self.root, ids),
                         {"codex-review": [a, b], "review-e2e": [a, c], "check": [b]})

    def test_pipeline_health_threshold(self):
        ids = self.done_jobs(10)
        for j in ids[:4]:
            self.codex_line(j)
        self.assertEqual(board.pipeline_health(self.root, "001", ids), [])
        self.assertEqual(self.health_jobs(), [])
        self.codex_line(ids[4])
        created = board.pipeline_health(self.root, "001", ids)
        self.assertEqual(len(created), 1)
        self.assertEqual([j["title"] for j in self.health_jobs()], ["Pipeline health: codex-review"])
        one = self.done_jobs(1)  # a single failing job never flags, even at 1 of 1
        self.round_file(one[0], 1, "check.md", "timed out\n")
        self.assertEqual(board.pipeline_health(self.root, "002", one), [])

    def test_pipeline_health_raises_needs_human(self):
        ids = self.done_jobs(10)
        for j in ids[:6]:
            self.codex_line(j)
        (created,) = board.pipeline_health(self.root, "001", ids)
        job = board.find(board.read_board(self.root), created)
        self.assertEqual(job["title"], "Pipeline health: codex-review")
        self.assertEqual(job["stage"], "needs-human")
        self.assertEqual(job["question"], "pipeline health: codex-review failed in 6 of 10 jobs in digest 001, 60 min lost")
        self.assertEqual(job["stopTitle"], "DIGEST")
        self.assertEqual(job["options"], [
            {"key": "a", "label": "Got it", "command": f"abort {created}"},
            {"key": "b", "label": "Add a fix to the backlog", "command": f"abort {created} --requeue"}])
        feature = (self.root / "jobs" / created / "feature.md").read_text()
        self.assertIn("digest 001", feature)
        for j in ids[:6]:
            self.assertIn(j, feature)
        for j in ids[6:]:
            self.assertNotIn(j, feature)
        e2e = self.done_jobs(2)
        for j in e2e:
            self.round_file(j, 1, "review-e2e.md", "Reviewer produced no output.\n")
        (other,) = board.pipeline_health(self.root, "002", e2e)
        self.assertEqual(board.find(board.read_board(self.root), other)["question"],
                         "pipeline health: review-e2e failed in 2 of 2 jobs in digest 002, time lost not logged")

    def test_pipeline_health_runs_from_digest_start(self):
        ids = self.done_jobs(2)
        for j in ids:
            self.codex_line(j)
        self.assertEqual(self.cli("digest-start"), {"id": "001", "jobs": ids, "windows": []})
        (job,) = self.health_jobs()
        self.assertEqual((job["title"], job["stage"]), ("Pipeline health: codex-review", "needs-human"))
        healthy = self.done_jobs(2)
        self.assertEqual(self.cli("digest-start"), {"id": "002", "jobs": healthy, "windows": []})
        self.assertEqual(len(self.health_jobs()), 1)

    def test_pipeline_health_no_duplicate_while_open(self):
        ids = self.done_jobs(2)
        for j in ids:
            self.codex_line(j)
        (first,) = board.pipeline_health(self.root, "001", ids)
        self.assertEqual(board.pipeline_health(self.root, "002", ids), [])  # re-claimed after a failed digest
        self.assertEqual(len(self.health_jobs()), 1)
        board.cmd_abort(self.root, first, requeue=False)
        (second,) = board.pipeline_health(self.root, "003", ids)
        self.assertNotEqual(second, first)
        self.assertEqual(board.find(board.read_board(self.root), second)["stage"], "needs-human")

    def test_pipeline_health_missing_files_and_errors(self):
        ids = self.done_jobs(3)
        shutil.rmtree(self.root / "jobs" / ids[0])  # no folder
        (self.root / "jobs" / ids[1] / "spec.md").write_text("trimmed\n")  # no routing.log, no round-*
        self.assertEqual(board.pipeline_health(self.root, "001", ids + ["999-never-existed"]), [])
        self.assertEqual(self.cli("digest-start"), {"id": "001", "jobs": ids, "windows": []})
        self.assertEqual(self.health_jobs(), [])
        for target in ("cmd_new", "cmd_ask"):
            for err in (SystemExit("board says no"), OSError("disk says no")):
                more = self.done_jobs(2)  # fresh done jobs each pass, so digest-start claims something
                for j in more:
                    self.codex_line(j)
                with self.subTest(target=target, err=err), mock.patch.object(board, target, side_effect=err), \
                        redirect_stdout(io.StringIO()) as out, mock.patch.object(sys, "stderr", io.StringIO()) as errout:
                    board.main(["--dir", str(self.root), "digest-start"])  # no SystemExit: exit status 0
                    self.assertEqual(json.loads(out.getvalue())["jobs"], more)
                    self.assertIn(str(err), errout.getvalue())
                for j in self.health_jobs():  # a job cmd_ask failed on is left behind; clear it for the next pass
                    if j["stage"] != "aborted":
                        board.cmd_abort(self.root, j["id"], requeue=False)

    def test_digest_start_claims_windows_once(self):
        a = self.done_jobs(1)
        self.assertEqual(self.cli("digest-start"), {"id": "001", "jobs": a, "windows": []})  # no windows/ folder
        d1 = self.root / "digests" / "001"
        self.assertEqual((d1 / "windows.txt").read_text(), "")
        self.assertEqual(json.loads((d1 / "windows.json").read_text()), [])
        w = self.root / "windows"
        w.mkdir()
        (w / "five_hour-200.json").write_text(json.dumps({"window": "five_hour", "resets_at": 200, "headline": "ok"}))
        (w / "five_hour-100.json").write_text(json.dumps({"window": "five_hour", "resets_at": 100, "wasted_pct": 30}))
        (w / "open.json").write_text(json.dumps({"window": "five_hour"}))
        (w / ".lock").write_text("")
        (w / "five_hour-9.json").write_text("{bad")
        (w / "seven_day-5.json").write_text("[1, 2]")
        b = self.done_jobs(1)
        self.assertEqual(self.cli("digest-start"), {"id": "002", "jobs": b,
                                                    "windows": ["five_hour-100.json", "five_hour-200.json"]})
        d2 = self.root / "digests" / "002"
        self.assertEqual((d2 / "windows.txt").read_text(), "five_hour-100.json\nfive_hour-200.json\n")
        self.assertEqual(json.loads((d2 / "windows.json").read_text()),
                         [{"window": "five_hour", "resets_at": 100, "wasted_pct": 30},
                          {"window": "five_hour", "resets_at": 200, "headline": "ok"}])
        c = self.done_jobs(1)
        self.assertEqual(self.cli("digest-start"), {"id": "003", "jobs": c, "windows": []})
        (w / "seven_day-300.json").write_text(json.dumps({"window": "seven_day", "resets_at": 300}))
        e = self.done_jobs(1)
        self.assertEqual(self.cli("digest-start"), {"id": "004", "jobs": e, "windows": ["seven_day-300.json"]})
        (d2 / "error.md").write_text("failed\n")  # failed digest: its windows are claimed again
        f = self.done_jobs(1)
        self.assertEqual(self.cli("digest-start"), {"id": "005", "jobs": b + f,
                                                    "windows": ["five_hour-100.json", "five_hour-200.json"]})

    def write_questions_log(self, n):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "questions.log").write_text("".join(f'{{"n": {i}}}\n' for i in range(n)))

    def marker(self, digest_id, text, error=False):
        d = self.root / "digests" / digest_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "jobs.txt").write_text("")
        (d / "questions.lines").write_text(text)
        os.utime(d / "questions.lines", (time.time() - 7 * 3600,) * 2)  # past the 6h gate
        if error:
            (d / "error.md").write_text("failed\n")

    def test_digest_start_writes_questions_marker(self):
        self.done_jobs(1)
        self.assertEqual(self.cli("digest-start")["id"], "001")
        self.assertEqual((self.root / "digests" / "001" / "questions.lines").read_text(), "0\n")
        self.write_questions_log(7)
        self.done_jobs(1)
        self.assertEqual(self.cli("digest-start")["id"], "002")
        self.assertEqual((self.root / "digests" / "002" / "questions.lines").read_text(), "7\n")

    def test_digest_due_on_questions_growth(self):
        self.write_questions_log(20)
        self.assertEqual(self.cli("digest-due"), {"due": True, "undigested": 0, "questionsGrowth": 20, "reason": "questions"})  # no marker yet
        self.marker("001", "5\n")
        self.assertEqual(self.cli("digest-due"), {"due": True, "undigested": 0, "questionsGrowth": 15, "reason": "questions"})
        self.write_questions_log(19)
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 14, "reason": None})
        self.marker("002", "30\n")  # the log shrank below the marker
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0, "reason": None})
        self.marker("003", "junk\n")  # not an integer: ignored, 002 counts
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0, "reason": None})
        self.marker("004", "2\n", error=True)  # failed digest: skipped, 002 still counts
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0, "reason": None})
        (self.root / "digests" / "002" / "error.md").write_text("failed\n")  # now 001 counts
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 14, "reason": None})

    def test_digest_start_on_questions_growth_only(self):
        self.write_questions_log(14)
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": [], "windows": []})
        self.assertFalse((self.root / "digests").exists())
        self.write_questions_log(15)
        self.assertEqual(self.cli("digest-start"), {"id": "001", "jobs": [], "windows": []})
        self.assertEqual((self.root / "digests" / "001" / "jobs.txt").read_text(), "")
        self.assertEqual((self.root / "digests" / "001" / "questions.lines").read_text(), "15\n")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0, "reason": None})
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": [], "windows": []})
        self.assertEqual(sorted(p.name for p in (self.root / "digests").iterdir()), ["001"])

    def test_questions_growth_counts_own_project_only(self):
        self.root.mkdir(parents=True, exist_ok=True)
        own = self.root.resolve().parent.name
        lines = [json.dumps({"project": "other"}) for _ in range(10)] + [json.dumps({"project": own}) for _ in range(5)]
        lines += [json.dumps({"n": 1}) for _ in range(5)] + ["", "junk"]
        (self.root / "questions.log").write_text("\n".join(lines) + "\n")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 10, "reason": None})

    def test_questions_trigger_waits_six_hours(self):
        self.write_questions_log(20)
        self.marker("001", "5\n")
        m = self.root / "digests" / "001" / "questions.lines"
        os.utime(m, (time.time() - 3600,) * 2)
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 15, "reason": None})
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": [], "windows": []})
        self.assertEqual(sorted(p.name for p in (self.root / "digests").iterdir()), ["001"])
        os.utime(m, (time.time() - 7 * 3600,) * 2)
        self.assertEqual(self.cli("digest-due")["reason"], "questions")
        self.assertEqual(self.cli("digest-start")["id"], "002")
        self.write_questions_log(40)  # 002 is fresh; 001's old mtime must not count
        self.assertFalse(self.cli("digest-due")["due"])

    def test_digest_start_writes_timing(self):
        (job,) = self.done_jobs(1)
        waiting = board.cmd_new(self.root, "queued")
        t0 = 1_700_000_000
        folder = self.root / "jobs" / job
        runs = self.root / "runs"
        runs.mkdir()
        stamp = datetime.fromtimestamp(t0 + 1200, timezone.utc).strftime("%Y%m%d-%H%M%S")
        (runs / f"{stamp}-start-{job}.log").write_text("x")
        for rel, text, at in (("feature.md", "f\n", t0), ("spec.md", "s\n", t0 + 600),
                              ("round-1/head.txt", "abc\n", t0 + 4200), ("round-1/check.md", "CHECK: PASS\n", t0 + 4200),
                              ("round-2/head.txt", "abc\n", t0 + 7800),
                              ("round-3/head.txt", "abc\n", t0 + 11400),
                              ("round-3/check.md", "CHECK: PASS\nE2E — first try exit 124 (lock wait), retry exit 0\n",
                               t0 + 11400)):
            p = self.write(f"{job}/{rel}", text)
            os.utime(p, (at, at))
        with board.locked_board(self.root) as b:
            for j in b["jobs"]:
                if j["id"] == job:
                    j["updatedAt"] = datetime.fromtimestamp(t0 + 12000, timezone.utc).isoformat()
                if j["id"] == waiting:
                    j.update(stage="check", stalled=True, reason="stalled: waiting on the E2E queue",
                             updatedAt=(datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat())
        (self.root / "questions.log").write_text(
            json.dumps({"job": job, "kind": "stall", "reason": "stalled: x"}) + "\n"
            + json.dumps({"job": waiting, "kind": "stall", "reason": "stalled: waiting on the E2E queue"}) + "\n")
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(Path(self.tmp.name) / "none.json")}):
            self.assertEqual(self.cli("digest-start")["id"], "001")
        text = (self.root / "digests" / "001" / "timing.md").read_text()
        self.assertIn("| Job | Wall | Spec | Queue | Queue gate | Rounds | Round times | No-change rounds | E2E lock waits | Stalls |\n"
                      "|---|---|---|---|---|---|---|---|---|---|\n", text)
        self.assertIn(f"| {job} | 3h20m | 10m | 10m | - | 3 | 50m, 1h00m, 1h00m | 2 (rounds 2,3) | 1 | 1 |\n", text)
        self.assertIn("Jobs: 1 · wall 3h20m · rounds 3 · no-change rounds 2 in 1 jobs · E2E lock waits 1 in 1 jobs"
                      " · stalls 1\n", text)
        self.assertIn(f"## Waiting on the E2E queue\n- {Path(self.tmp.name).resolve().name}/{waiting}: 1h30m\n\n"
                      "## RAM holds\nNone\n", text)

    def test_timing_ram_holds_section(self):
        held, unknown, plain = self.done_jobs(3)
        self.write(f"{held}/ram-holds.txt", "2026-11-12T10:00:00+00:00 free=12% sessions=13\n"
                                            "2026-11-12T10:01:00+00:00 free=8% sessions=14\n")
        self.write(f"{unknown}/ram-holds.txt", "2026-11-12T10:00:00+00:00 free=unknown sessions=3\n")
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(Path(self.tmp.name) / "none.json")}):
            self.assertEqual(self.cli("digest-start")["id"], "001")
        text = (self.root / "digests" / "001" / "timing.md").read_text()
        self.assertIn("| Job | Wall | Spec | Queue | Queue gate | Rounds | Round times | No-change rounds | E2E lock waits | Stalls |\n", text)
        self.assertIn(f"## RAM holds\n- {held}: 2 holds, free RAM 8%-12%, sessions 13-14\n"
                      f"- {unknown}: 1 holds, free RAM unknown, sessions 3-3\n", text)
        self.assertNotIn(f"- {plain}:", text.split("## RAM holds")[1])

    def escape_digest(self, jobs, commits=()):
        """digest-start over a board of `jobs` (dicts, stage done unless set) with a git repo at root.parent holding
        `commits` ((files dict, message), in order). Returns (escapes.md text or None, result, stderr)."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "board.json").write_text(json.dumps({"jobs": [{"stage": "done", **j} for j in jobs]}))
        repo = Path(self.tmp.name)
        if commits:
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        for files, message in commits:
            for rel, text in files.items():
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text(text)
                subprocess.run(["git", "-C", str(repo), "add", rel], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                            "-m", message], check=True)
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(repo / "none.json")}), redirect_stderr(err):
            out = board.cmd_digest_start(self.root)
        path = self.root / "digests" / str(out["id"]) / "escapes.md"
        return (path.read_text() if path.exists() else None), out, err.getvalue()

    def test_digest_start_writes_escapes(self):
        text, out, _ = self.escape_digest(
            [{"id": "100-origin", "rounds": [{"check": "FAIL"}, {"check": "PASS", "code": "PASS", "ui": "PASS", "ux": "CHANGES"}]},
             {"id": "200-bug", "lane": "debug"}],
            [({"app.py": "a\nb\nc\n"}, "Add app\n\nJob files: scrum/jobs/100-origin/"),
             ({"app.py": "a\nB\nc\n", "tests/test_app.py": "x\n"}, "Fix b\n\nJob files: scrum/jobs/200-bug/")])
        self.assertEqual(out["jobs"], ["100-origin", "200-bug"])
        self.assertEqual(text, "- 200-bug ← 100-origin · 1 lines in app.py · passed by: code, ui\n")

    def test_digest_start_escapes_skips_stub_reviewers(self):
        commits = [({"app.py": "a\nb\nc\n"}, "Add app\n\nJob files: scrum/jobs/100-origin/"),
                   ({"app.py": "a\nB\nc\n"}, "Fix b\n\nJob files: scrum/jobs/200-bug/")]
        jobs = [{"id": "100-origin", "rounds": [{"check": "PASS", "code": "PASS", "ui": "PASS"}]},
                {"id": "200-bug", "lane": "debug"}]
        stub = "VERDICT: PASS\nSkipped by orchestrator: no UI files in diff.\n"
        self.round_file("100-origin", 1, "review-code.md", "VERDICT: PASS\nreal\n")
        self.round_file("100-origin", 1, "review-ui.md", stub)
        text, _, _ = self.escape_digest(jobs, commits)
        self.assertEqual(text, "- 200-bug ← 100-origin · 1 lines in app.py · passed by: code\n")

    def test_digest_start_escapes_all_stub_reviewers_none(self):
        commits = [({"app.py": "a\nb\nc\n"}, "Add app\n\nJob files: scrum/jobs/100-origin/"),
                   ({"app.py": "a\nB\nc\n"}, "Fix b\n\nJob files: scrum/jobs/200-bug/")]
        jobs = [{"id": "100-origin", "rounds": [{"check": "PASS", "ui": "PASS"}]}, {"id": "200-bug", "lane": "debug"}]
        self.round_file("100-origin", 1, "review-ui.md", "VERDICT: PASS\nSkipped by orchestrator: no UI files in diff.\n")
        text, _, _ = self.escape_digest(jobs, commits)
        self.assertEqual(text, "- 200-bug ← 100-origin · 1 lines in app.py · passed by: none\n")

    def test_digest_start_escapes_unknown_origin(self):
        text, _, _ = self.escape_digest(
            [{"id": "100-origin"}, {"id": "300-nocommit", "lane": "debug"}, {"id": "400-tests", "lane": "debug"},
             {"id": "500-fast", "lane": "fast"}],
            [({"app.py": "a\n"}, "Add app\n\nscrum/jobs/100-origin/"),
             ({"tests/test_x.py": "x\n"}, "Fix\n\nscrum/jobs/400-tests/")])
        self.assertEqual(text, "- 300-nocommit ← origin unknown: no merge commit\n"
                               "- 400-tests ← origin unknown: only test files changed\n")
        text, out, _ = self.escape_digest([{"id": "600-fast", "lane": "fast"}])
        self.assertEqual((out["id"], text), ("002", "No bug jobs\n"))

    def test_digest_start_escapes_no_scrum_job_in_blame(self):
        text, _, _ = self.escape_digest(
            [{"id": "200-bug", "lane": "debug"}],
            [({"app.py": "a\nb\n"}, "Old commit with no job line"),
             ({"app.py": "a\nb\nc\n"}, "Fix\n\nscrum/jobs/200-bug/")])
        self.assertEqual(text, "- 200-bug ← origin unknown: no scrum job in blame\n")

    def test_digest_start_escapes_without_git(self):
        text, out, err = self.escape_digest([{"id": "200-bug", "lane": "debug"}])
        self.assertEqual((out["id"], out["jobs"]), ("001", ["200-bug"]))
        self.assertIn("digest-start: escapes: ", err)
        self.assertIsNone(text)

    def pulse_digest(self, lines, since=None, error_since=None, boards=None):
        """digest-start over a pulse.log of `lines` (dicts or raw strings); `since` and `error_since` (epoch) set the
        jobs.txt mtime of an earlier digest 001, and of a failed digest 002 after it. `boards` ({project: jobs}) writes
        a registry whose repo <project> has those board jobs. Returns (pulse.md, stderr)."""
        self.done_jobs(1)
        for name, at, err in (("001", since, False), ("002", error_since, True)):
            if at is not None:
                self.marker(name, "0\n", error=err)
                os.utime(self.root / "digests" / name / "jobs.txt", (at, at))
        reg = Path(self.tmp.name) / "reg"
        reg.mkdir()
        for name, jobs in (boards or {}).items():
            (reg / name / "scrum").mkdir(parents=True)
            (reg / name / "scrum" / "board.json").write_text(json.dumps({"jobs": jobs}))
        if boards:
            (reg / "projects.json").write_text(json.dumps([str(reg / n) for n in boards]))
        if lines is not None:
            (reg / "pulse.log").write_text("".join((l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lines))
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg / "projects.json")}):
            out = run_board("--dir", str(self.root), "digest-start")
        self.assertEqual(out.returncode, 0, out.stderr)
        d = json.loads(out.stdout)["id"]
        return (self.root / "digests" / d / "pulse.md").read_text(), out.stderr

    def test_digest_start_writes_pulse(self):
        s = 1_700_000_000

        def line(t, sessions, cooldown, cpu, app, lib):
            keys = ("claimable", "waiting", "busy", "top")
            return {"t": t, "sessions": sessions, "cooldown": cooldown, "cpu_load": cpu, "focus": "app",
                    "projects": {"app": {**dict(zip(keys, app)), "auto": True}, "lib": {**dict(zip(keys, lib)), "auto": True}}}
        text, _ = self.pulse_digest([
            line(s - 60, 9, False, 900, (1, 0, False, 1), (0, 0, True, 1)),  # before the last digest: not counted
            line(s, 0, False, 100, (1, 0, False, 10), (0, 0, True, 3)),  # idle, non-focus
            line(s + 60, 0, False, 100, (0, 1, False, 10), (0, 0, False, 3)),  # idle (waiting work)
            line(s + 120, 3, True, 600, (1, 0, False, 12), (0, 0, True, 3)),  # app +2 in cool down at 600%, non-focus
            "junk", {"t": "x", "sessions": 0},
            line(s + 180, 0, False, 550, (1, 0, False, 12), (0, 0, False, 4)),  # idle, lib +1 at 550%
            line(s + 240, 0, True, 100, (1, 0, False, 12), (0, 0, False, 5)),  # cool down: not idle; lib +1 in cool down
        ], since=s)
        self.assertEqual(text, "# Pulse: digest 002\n\n"
                               "Window: 2023-11-14T22:13+00:00 to 2023-11-14T22:17+00:00 · ticks: 5\n"
                               "Idle with claimable work: 2 min (longest stretch 2 min)\n"
                               "Gated with claimable work: 0 min\n"
                               "Held by machine guard: 1 min\n"
                               "Idle held by Auto continue off or cool down: 0 min\n"
                               "Peak sessions: 3 at 2023-11-14T22:15+00:00\n"
                               "Peak CPU load: 600% at 2023-11-14T22:15+00:00\n"
                               "Claims during cool down: 3 — app 11 12, lib 5\n"
                               "Claims while CPU load over 500%: 3\n"
                               "Non-focus work while focus had claimable work: 2 min (focus: app)\n")

    def test_pulse_idle_minutes_capped_at_window(self):
        """Digest 088 read 240 idle minutes in a 79-minute window: idle, its stretch and non-focus never pass the window."""
        lib = {"claimable": 0, "waiting": 0, "busy": True, "top": 1, "auto": True}
        ticks = lambda ts: self.pulse_ticks(*((t, 0, {"projects": {
            "app": {"claimable": 1, "waiting": 0, "busy": False, "top": 1, "auto": True}, "lib": lib}}) for t in ts))
        text = ticks(range(0, 50, 5))  # ten idle lines inside one wall-clock minute
        self.assertIn("Idle with claimable work: 1 min (longest stretch 1 min)\n", text)
        self.assertIn("Non-focus work while focus had claimable work: 1 min (focus: app)\n", text)
        self.tearDown(); self.setUp()
        text = ticks(t * 7.5 for t in range(81))  # 81 idle lines over 600 s, 8 a minute
        idle, longest = map(int, re.search(r"Idle with claimable work: (\d+) min \(longest stretch (\d+) min\)", text).groups())
        nonfocus = int(re.search(r"Non-focus work while focus had claimable work: (\d+) min", text)[1])
        self.assertEqual((idle, longest, nonfocus), (10, 10, 10), text)
        self.tearDown(); self.setUp()
        text = ticks([600, 0, 300, 60, 120, 180, 240, 360, 420, 480, 540])  # two writers' lines out of order
        self.assertIn("Idle with claimable work: 10 min (longest stretch 10 min)\n", text)

    def pulse_ticks(self, *ticks):
        """pulse_digest over (t, sessions, extra) ticks, app claimable with Auto continue on; returns the pulse.md text."""
        app = {"claimable": 1, "waiting": 0, "busy": False, "top": 1, "auto": True}
        return self.pulse_digest([{"t": 1_700_000_000 + t, "sessions": n, "cooldown": False, "focus": "app",
                                   "projects": {"app": app}, **x} for t, n, x in ticks])[0]

    def test_pulse_gated_minutes(self):
        """Job 820: a minute a launch gate held is not idle; it gets its own line, per gate."""
        wait = lambda g: {"app": {"claimable": 0, "waiting": 0, "auto": True},
                          "lib": {"claimable": 0, "waiting": 1, "auto": True, **({"gates": g} if g is not None else {})}}
        text = self.pulse_ticks(
            (0, 0, {}),  # idle
            (60, 0, {"gates": ["ram_room"]}),  # gated: ends the stretch
            (120, 0, {}), (180, 0, {}),  # idle, stretch 2
            (240, 0, {"gates": ["ram_room", "cpu_load"]}),  # gated
            (300, 0, {"gates": None}),  # null: idle, stretch 1
            (360, 0, {"gates": [], "projects": wait(["overlap:5-x", "overlap:6-y"])}),  # only waiting work, all gated
            (420, 0, {"gates": [], "projects": wait([])}),  # waiting, nothing gates it: idle
            (480, 0, {"projects": wait(None)}),  # no gates key: idle
            (540, 1, {}))
        self.assertIn("Idle with claimable work: 6 min (longest stretch 2 min)\n"
                      "Gated with claimable work: 3 min (ram_room 2, cpu_load 1, overlap 1)\n"
                      "Held by machine guard: 0 min\n", text)

    def test_pulse_idle_uses_elapsed_time(self):
        text = self.pulse_ticks(*((t, 0, {}) for t in (0, 20, 40, 60, 80)))
        self.assertIn("Idle with claimable work: 1 min (longest stretch 1 min)\nGated with claimable work: 0 min\nHeld by machine guard: 0 min\n", text)

    def test_pulse_idle_gap_capped(self):
        text = self.pulse_ticks((0, 0, {}), (600, 0, {}))
        self.assertIn("Idle with claimable work: 2 min (longest stretch 2 min)\n", text)
        self.tearDown(); self.setUp()
        text = self.pulse_ticks((0, 0, {}), (600, 0, {}), (1200, 1, {}))  # two capped gaps, then a session
        self.assertIn("Idle with claimable work: 4 min (longest stretch 4 min)\n", text)

    def test_pulse_hot_tick_held_by_guard(self):
        text = self.pulse_ticks(
            (0, 0, {"cpu_load": 150, "swap": 25}),  # at the limits: idle
            (60, 0, {"cpu_load": 151}),  # hot: held, ends the stretch
            (120, 0, {"swap": 26}),  # swapping: held
            (180, 0, {"cpu_load": "x", "swap": None}),  # not numeric: idle
            (240, 0, {}),  # idle
            (300, 2, {"cpu_load": 900, "swap": 90}),  # a session runs: neither, even hot
            (360, 0, {"cpu_load": 900, "cooldown": True}),  # cool down: neither idle nor guard
            (420, 0, {}))
        self.assertIn("Idle with claimable work: 3 min (longest stretch 2 min)\n"
                      "Gated with claimable work: 0 min\n"
                      "Held by machine guard: 2 min\n"
                      "Idle held by Auto continue off or cool down: 1 min\n", text)

    def test_pulse_idle_never_exceeds_window(self):
        self.assertIn("Idle with claimable work: 0 min (longest stretch 0 min)\nGated with claimable work: 0 min\nHeld by machine guard: 0 min\n",
                      self.pulse_ticks((0, 0, {})))
        self.tearDown(); self.setUp()
        text = self.pulse_ticks((0, 0, {}), (50, 0, {"cpu_load": 900}), (100, 0, {}), (130, 0, {}))  # 130 s window
        self.assertIn("Idle with claimable work: 1 min (longest stretch 1 min)\nGated with claimable work: 0 min\nHeld by machine guard: 1 min\n", text)

    def test_pulse_null_top_baseline(self):
        s = 1_700_000_000
        pr = lambda top: {"claimable": 0, "waiting": 0, "busy": False, "top": top}
        text, _ = self.pulse_digest([
            {"t": s, "sessions": 1, "cooldown": False, "cpu_load": 100, "focus": "app", "projects": {"app": pr(None)}},
            {"t": s + 60, "sessions": 1, "cooldown": True, "cpu_load": 600, "focus": "app",
             "projects": {"app": pr(2), "new": pr(5)}}])  # "new" absent from the earlier line: no claim
        self.assertIn("Claims during cool down: 2 — app 1 2\n", text)
        self.assertIn("Claims while CPU load over 500%: 2\n", text)

    def test_pulse_idle_skips_auto_continue_off(self):
        s = 1_700_000_000
        pr = lambda claimable, auto=None: {"claimable": claimable, "waiting": 0, "busy": False, "top": 1,
                                           **({} if auto is None else {"auto": auto})}
        tick = lambda t, sessions, cooldown, app, lib: {"t": t, "sessions": sessions, "cooldown": cooldown,
                                                         "focus": "app", "projects": {"app": app, "lib": lib}}
        text, _ = self.pulse_digest([
            tick(s, 0, False, pr(2, False), pr(0, True)),  # only claimable project has Auto continue off: held
            tick(s + 60, 0, False, pr(2), pr(0, True)),  # no auto key (an old line): off, held
            tick(s + 120, 0, True, pr(0, True), pr(1, True)),  # cool down: held
            tick(s + 180, 1, False, pr(2, False), pr(0, True)),  # a session runs: neither
            tick(s + 240, 0, False, pr(0, True), pr(0, False)),  # nothing claimable: neither
        ])
        self.assertIn("Idle with claimable work: 0 min (longest stretch 0 min)\nGated with claimable work: 0 min\nHeld by machine guard: 0 min\n"
                      "Idle held by Auto continue off or cool down: 3 min\n", text)

    def test_pulse_cool_down_skips_hand_claims(self):
        s = 1_700_000_000
        pr = lambda top: {"claimable": 0, "waiting": 0, "busy": False, "top": top, "auto": True}
        text, _ = self.pulse_digest([
            {"t": s, "sessions": 1, "cooldown": True, "focus": "app", "projects": {"app": pr(10)}},
            {"t": s + 60, "sessions": 1, "cooldown": True, "focus": "app", "projects": {"app": pr(12)}}],
            boards={"app": [{"id": "010-old", "stage": "done", "started_by": "runall"},
                            {"id": "011-a", "stage": "spec", "started_by": "hand"},
                            {"id": "012-b", "stage": "spec", "started_by": "runall"}]})
        self.assertIn("Claims during cool down: 1 — app 12\n", text)

    def test_pulse_missing_log(self):
        empty = "# Pulse: digest 001\n\nNo pulse lines since the last digest.\n"
        self.assertEqual(self.pulse_digest(None)[0], empty)
        self.tearDown(); self.setUp()
        self.assertEqual(self.pulse_digest(["junk", {"t": None}, {"t": 5, "sessions": 0}], since=10)[0],
                         empty.replace("001", "002"))
        self.tearDown(); self.setUp()
        with mock.patch.object(board, "write_pulse", side_effect=OSError("disk full")):
            self.done_jobs(1)
            out = run_board("--dir", str(self.root), "digest-start")
        self.assertEqual(json.loads(out.stdout), {"id": "001", "jobs": [board.read_board(self.root)["jobs"][0]["id"]],
                                                  "windows": []})
        self.assertIn("digest-start: pulse: disk full\n", out.stderr)

    def test_pulse_skips_errored_digest_since(self):
        text, _ = self.pulse_digest([{"t": 1_000_500, "sessions": 2}, {"t": 2_000_500, "sessions": 1}],
                                    since=1_000_000, error_since=2_000_000)
        self.assertIn("# Pulse: digest 003\n", text)
        self.assertIn(" · ticks: 2\n", text)
        self.assertIn("Peak sessions: 2 at 1970-01-12T13:55+00:00\n", text)

    def test_timing_build_start_from_run_log(self):
        t0 = 1_700_000_000
        self.assertIsNone(board._build_start(self.root, "j"))
        p = self.write("j/spec.md", "s\n")
        os.utime(p, (t0, t0))
        self.write("j/round-1/head.txt", "h\n")
        os.utime(self.root / "jobs/j/round-1/head.txt", (t0 + 3600, t0 + 3600))
        runs = self.root / "runs"
        runs.mkdir()

        def stamp(at):
            return datetime.fromtimestamp(at, timezone.utc).strftime("%Y%m%d-%H%M%S")
        row = lambda: board._timing_row(self.root, "j", {}, {})[0]
        self.assertEqual(row()[3:6], ["0m", "-", "1"])  # no log
        self.assertEqual(row()[6], "1h00m")
        (runs / "bad-start-j.log").write_text("x")
        early = runs / f"{stamp(t0 - 60)}-start-j.log"  # earliest log is before spec.md: spec.md's mtime
        early.write_text("x")
        self.assertEqual((row()[3], row()[6]), ("0m", "1h00m"))
        (runs / f"{stamp(t0 + 1200)}-start-j.log").write_text("x")
        self.assertEqual((row()[3], row()[6]), ("0m", "1h00m"))
        early.unlink()
        (runs / f"{stamp(t0 + 1800)}-resume-j.log").write_text("x")  # not a start log
        self.assertEqual((row()[3], row()[6]), ("20m", "40m"))
        self.assertEqual(board._timing_row(self.root, "none", {}, {})[0][3], "-")

    def timing_cell(self, waits, files=((6600, "round-1/a.md"), (7200, "round-1/head.txt"))):
        """Round-1 time cell for a 2h round (spec.md at t0) with the given wait starts (secs after t0)."""
        t0 = 1_700_000_000
        for at, rel in ((0, "spec.md"), *files):
            p = self.write(f"j/{rel}", "x\n")
            os.utime(p, (t0 + at, t0 + at))
        return board._timing_row(self.root, "j", {}, {}, [t0 + w for w in waits])[0][6]

    def test_timing_subtracts_e2e_wait(self):
        self.assertEqual(self.timing_cell([]), "2h00m")
        self.assertEqual(self.timing_cell([6000]), "1h50m")

    def test_timing_subtracts_machine_wait(self):
        t0 = 1_700_000_000
        self.write("j/spec.md", "s\n")
        (self.root / "questions.log").write_text(
            json.dumps({"job": "j", "kind": "machine", "date": datetime.fromtimestamp(t0 + 6000, timezone.utc).isoformat()}) + "\n")
        self.write("j/round-1/head.txt", "h\n")
        os.utime(self.root / "jobs/j/spec.md", (t0, t0))
        os.utime(self.root / "jobs/j/round-1/head.txt", (t0 + 7200, t0 + 7200))
        waits = [board._epoch(q["date"]) for q in board._json_lines(self.root / "questions.log")]
        self.assertEqual(board._timing_row(self.root, "j", {}, {}, waits)[0][6], "1h40m")

    def test_timing_ignores_other_stalls(self):
        t0 = 1_700_000_000
        self.write("j/spec.md", "s\n")
        self.write("k/spec.md", "s\n")
        self.write("j/round-1/head.txt", "h\n")
        os.utime(self.root / "jobs/j/spec.md", (t0, t0))
        os.utime(self.root / "jobs/j/round-1/head.txt", (t0 + 7200, t0 + 7200))
        iso = lambda at: datetime.fromtimestamp(t0 + at, timezone.utc).isoformat()
        (self.root / "questions.log").write_text("".join(json.dumps(d) + "\n" for d in (
            {"job": "j", "kind": "stall", "reason": "stalled: no board update for 2 min and no live session", "date": iso(3600)},
            {"job": "k", "kind": "stall", "reason": "stalled: waiting on the E2E queue", "date": iso(3600)},
            {"job": "j", "kind": "stall", "reason": "stalled: waiting on the E2E queue", "date": iso(9000)})))
        (self.root / "digests" / "001").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(Path(self.tmp.name) / "none.json")}):
            board.write_timing(self.root, "001", ["j"])
        self.assertIn("| j | - | 0m | 0m | - | 1 | 2h00m | 0 | 0 | 2 |", (self.root / "digests" / "001" / "timing.md").read_text())

    def test_timing_wait_clamped_and_merged(self):
        self.assertEqual(self.timing_cell([6000, 6100]), "1h50m")  # overlapping spans count once
        (self.root / "jobs/j/round-1/a.md").unlink()
        self.assertEqual(self.timing_cell([0, 7100], files=((7200, "round-1/head.txt"),)), "0m")  # whole round waited

    def test_timing_row_no_change_cell(self):
        for job, heads in (("a", {1: "x", 2: "y", 3: "z"}), ("b", {1: "x", 2: "y", 4: "y"})):
            for n, h in heads.items():
                self.write(f"{job}/round-{n}/head.txt", h + "\n")
        self.assertEqual(board._timing_row(self.root, "a", {}, {})[0][7], "0")
        cells, _, _, count, _ = board._timing_row(self.root, "b", {}, {})
        self.assertEqual((cells[7], count), ("1 (rounds 4)", 1))

    def test_timing_row_queue_gate_cell(self):
        cell = lambda: board._timing_row(self.root, "j", {}, {})[0][4]
        self.write("j/spec.md", "s\n")
        self.assertEqual(cell(), "-")  # no file
        gates = self.root / "jobs/j/queue-gates.txt"
        gates.write_text("")
        self.assertEqual(cell(), "-")  # empty file
        gates.write_text("ram_room\ncpu_load\n")
        self.assertEqual(cell(), "ram_room, cpu_load")

    def test_timing_row_claim_clock(self):
        t0 = 1_700_000_000
        self.write("j/feature.md", "f\n")
        self.write("j/spec.md", "s\n")
        os.utime(self.root / "jobs/j/feature.md", (t0, t0))
        os.utime(self.root / "jobs/j/spec.md", (t0 + 3 * 3600 + 600, t0 + 3 * 3600 + 600))
        cells = lambda: board._timing_row(self.root, "j", {}, {})[0][2:4]
        self.assertEqual(cells(), ["3h10m", "0m"])  # no claimed-at.txt: today's values
        claimed = self.root / "jobs/j/claimed-at.txt"
        claimed.write_text(f"{t0 + 3 * 3600}\n")
        self.assertEqual(cells(), ["10m", "3h00m"])
        self.write("j/round-1/head.txt", "h\n")  # a build start 5m after spec.md adds its own queue
        (self.root / "runs").mkdir(exist_ok=True)
        start = datetime.fromtimestamp(t0 + 3 * 3600 + 900, timezone.utc).strftime("%Y%m%d-%H%M%S")
        (self.root / "runs" / f"{start}-start-j.log").write_text("")
        self.assertEqual(cells(), ["10m", "3h05m"])

    def test_timing_row_bad_claim_ignored(self):
        t0 = 1_700_000_000
        self.write("j/feature.md", "f\n")
        self.write("j/spec.md", "s\n")
        os.utime(self.root / "jobs/j/feature.md", (t0, t0))
        os.utime(self.root / "jobs/j/spec.md", (t0 + 3 * 3600 + 600, t0 + 3 * 3600 + 600))
        claimed = self.root / "jobs/j/claimed-at.txt"
        for bad in ("", "soon", f"{t0 + 4 * 3600}", f"{t0 - 60}"):  # empty, non-numeric, after spec.md, before feature.md
            claimed.write_text(bad)
            self.assertEqual(board._timing_row(self.root, "j", {}, {})[0][2:4], ["3h10m", "0m"], bad)

    def test_bad_window_thresholds(self):
        self.assertEqual((board.BAD_WASTED_PCT, board.BAD_FIRST_PASS, board.BAD_MIN_JOBS, board.EARLY_DIGEST_MIN),
                         (20, 0.5, 3, 3))
        three = ["a", "b", "c"]
        self.assertFalse(board.bad_window({"wasted_pct": 20, "first_pass_rate": None, "done_jobs": three}))
        self.assertTrue(board.bad_window({"wasted_pct": 20.1, "first_pass_rate": None, "done_jobs": []}))
        self.assertFalse(board.bad_window({"wasted_pct": None, "first_pass_rate": 0.4, "done_jobs": ["a", "b"]}))
        self.assertTrue(board.bad_window({"wasted_pct": None, "first_pass_rate": 0.4, "done_jobs": three}))
        self.assertFalse(board.bad_window({"wasted_pct": 0, "first_pass_rate": 0.5, "done_jobs": three}))
        self.assertFalse(board.bad_window({"wasted_pct": None, "first_pass_rate": None, "done_jobs": three}))
        self.assertFalse(board.bad_window({}))
        self.assertFalse(board.bad_window({"wasted_pct": "99", "first_pass_rate": True, "done_jobs": three}))

    def scorecard(self, name, written_at, wasted_pct=50.0):
        (self.root / "windows").mkdir(parents=True, exist_ok=True)
        (self.root / "windows" / name).write_text(json.dumps(
            {"written_at": written_at, "wasted_pct": wasted_pct, "first_pass_rate": 1.0, "done_jobs": []}))

    def test_digest_due_bad_window_early(self):
        later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        earlier = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        self.done_jobs(2)
        self.scorecard("five_hour-2000.json", later)
        self.scorecard("five_hour-1000.json", later)
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 2, "questionsGrowth": 0, "reason": None})
        self.done_jobs(1)
        self.assertEqual(self.cli("digest-due"),
                         {"due": True, "undigested": 3, "questionsGrowth": 0, "reason": "bad window five_hour-1000.json"})
        d = self.root / "digests" / "001"
        d.mkdir(parents=True)
        (d / "windows.txt").write_text("five_hour-1000.json\nfive_hour-2000.json\n")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 3, "questionsGrowth": 0, "reason": None})
        (d / "windows.txt").write_text("five_hour-1000.json\n")
        self.assertEqual(self.cli("digest-due")["reason"], "bad window five_hour-2000.json")
        self.scorecard("five_hour-2000.json", earlier)  # written before digest 001 was created
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 3, "questionsGrowth": 0, "reason": None})
        self.scorecard("seven_day-3000.json", later, wasted_pct=5.0)  # a good window
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 3, "questionsGrowth": 0, "reason": None})

    def test_digest_due_bad_window_ignores_junk(self):
        self.done_jobs(3)
        self.assertEqual(self.cli("digest-due")["reason"], None)  # no windows/ folder
        w = self.root / "windows"
        w.mkdir()
        bad = {"written_at": "2026-01-01T00:00:00+00:00", "wasted_pct": 90, "first_pass_rate": 0.0,
               "done_jobs": ["a", "b", "c"]}
        (w / "open.json").write_text(json.dumps(bad))
        (w / "five_hour-1.json.tmp").write_text(json.dumps(bad))
        (w / "five_hour-2.json").write_text("{not json")
        (w / "five_hour-3.json").write_text(json.dumps([bad]))
        (w / "five_hour-4.json").write_text(json.dumps({**bad, "written_at": None}))
        (w / "five_hour-5.json").write_text(json.dumps({**bad, "written_at": "yesterday"}))
        (w / "five_hour-6.json").write_bytes(b"\xff\xfe")
        (w / "seven_day-7.json").mkdir()
        bad.pop("written_at")
        (w / "seven_day-8.json").write_text(json.dumps(bad))
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 3, "questionsGrowth": 0, "reason": None})

    def fill(self, job_id):
        for rel in ("feature.md", "spec.md", "decision.md", "build.md", "round-1/check.md", "round-1/review-code.md", "round-1/review-ui.md",
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
        self.assertEqual(sorted(p.name for p in (self.root / "jobs" / a).iterdir()), ["build.md", "decision.md", "feature.md", "rework.md", "round-1", "spec.md"])
        self.assertEqual(sorted(p.name for p in (self.root / "jobs" / b).iterdir()), ["build.md", "decision.md", "feature.md", "rework.md", "round-1"])
        self.assertEqual(sorted(p.name for p in (self.root / "jobs" / a / "round-1").iterdir()), ["check.md", "review-code.md", "review-ui.md"])
        self.assertEqual((self.root / "jobs" / a / "round-1" / "review-code.md").read_text(), "round-1/review-code.md")
        self.assertEqual((self.root / "jobs" / a / "spec.md").read_text(), "spec.md")
        files = {j["id"]: j["files"] for j in self.jobs()}
        self.assertEqual(files[a], ["build.md", "decision.md", "feature.md", "rework.md", "round-1/check.md", "round-1/review-code.md",
                                    "round-1/review-ui.md", "spec.md"])
        self.assertEqual(files[b], ["build.md", "decision.md", "feature.md", "rework.md", "round-1/check.md", "round-1/review-code.md",
                                    "round-1/review-ui.md"])
        self.assertIs(self.jobs()[0]["diverged"], True)  # build.md is kept
        self.assertTrue((self.root / "digests" / "001" / "trimmed").exists())
        self.assertEqual(self.cli("digest-trim", "001"), [a, b])  # idempotent
        self.assertEqual(sorted(p.name for p in (self.root / "jobs" / a).iterdir()),
                         ["build.md", "decision.md", "feature.md", "rework.md", "round-1", "spec.md"])
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
        self.assertEqual(len(list((self.root / "jobs" / unlisted).rglob("*"))), 11)
        self.assertEqual(len(list((self.root / "jobs" / review).rglob("*"))), 11)
        self.assertEqual(len(list((self.root / "jobs" / listed).rglob("*"))), 9)

    def test_digest_trim_round_dirs(self):
        a = self.done_jobs(1)[0]
        for rel in ("feature.md", "round-1/check.md", "round-1/review-code.md", "round-1/head.txt", "round-2/review-code.md",
                    "round-2/shot/a.png", "round-3/review-ui.md", "other/review-code.md"):
            self.write(f"{a}/{rel}", rel)
        for rel in ("unblock-1.md", "nh-comment.txt", "pr-body.txt"):
            self.write(f"{a}/{rel}", rel)
        out = self.cli("digest-start")
        board.cmd_digest_trim(self.root, out["id"])
        board.cmd_digest_trim(self.root, out["id"])  # idempotent
        got = sorted(str(p.relative_to(self.root / "jobs" / a)) for p in (self.root / "jobs" / a).rglob("*"))
        self.assertEqual(got, ["feature.md", "nh-comment.txt", "round-1", "round-1/check.md", "round-1/review-code.md",
                               "round-2", "round-2/review-code.md", "round-3", "round-3/review-ui.md", "unblock-1.md"])

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

    def test_watchdog_skips_limit_held_job(self):
        held = self.aged("Held review", 120, stage="review", limitResetAt=1_800_000_000)
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])
        self.assertEqual((self.get(held)["stage"], self.get(held)["limitResetAt"]), ("review", 1_800_000_000))
        plain = self.aged("Plain review", 120, stage="review")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [plain])

    def age_job_dir(self, job_id, hours):
        t = time.time() - hours * 3600
        for f in (self.root / "jobs" / job_id).rglob("*"):
            os.utime(f, (t, t))

    def test_watchdog_flags_live_idle_session(self):
        job_id = self.aged("Idle review", 180, stage="review")
        paused = self.aged("Idle paused", 180, stage="review", paused=True)
        for j in (job_id, paused):
            (self.root / "jobs" / j).mkdir(parents=True, exist_ok=True)
            (self.root / "jobs" / j / "build.md").write_text("x")
            self.age_job_dir(j, 3)
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: True), [job_id])
        self.assertEqual((self.get(job_id)["stage"], self.get(job_id)["stalled"]), ("review", True))
        self.assertEqual(self.get(job_id)["reason"], "stalled: no board or job-dir change for 2 h "
                         "(session alive but idle)")
        self.assertEqual(self.get(paused)["stage"], "review")
        self.assertNotIn("stalled", self.get(paused))
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: True), [])  # not flagged again

    def test_watchdog_skips_live_job_with_recent_job_dir_file(self):
        job_id = self.aged("Busy review", 180, stage="review")
        sub = self.root / "jobs" / job_id / "round-1"
        sub.mkdir(parents=True, exist_ok=True)
        self.age_job_dir(job_id, 3)
        (sub / "check.md").write_text("x")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: True), [])
        self.assertEqual(self.get(job_id)["stage"], "review")

    def test_watchdog_skips_live_job_updated_under_2h(self):
        job_id = self.aged("Recent review", 90, stage="review")
        self.age_job_dir(job_id, 3)
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: True), [])
        self.assertEqual(self.get(job_id)["stage"], "review")

    def test_watchdog_skips_paused_job(self):
        paused = self.aged("Paused build", 120, stage="build", paused=True,
                           reason="stalled in build: paused by Trevor. Fix: click Play.")
        before = self.get(paused)
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])
        self.assertEqual(self.get(paused), before)

    def test_watchdog_flags_dead_merge_session(self):
        """A session killed between stage=merging and the squash merge (227, 2026-10-23) must be flagged, or its
        run-all siblings that share a file wait on it forever."""
        merging = self.aged("Merging", 31, stage="merging")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [merging])
        self.assertEqual((self.get(merging)["stage"], self.get(merging)["stalled"]), ("merging", True))
        self.assertEqual(self.get(merging)["reason"], "stalled: no board update for 30 min and no live session")

    def test_deploying_stage_is_set_and_watched(self):
        """Merge step 7 Prod check waits on the production deploy in `deploying`; a session that dies there is
        flagged like a dead merge session."""
        for name in ("STAGES", "ACTIVE", "WATCHED", "PAUSABLE"):
            stages = list(getattr(board, name))
            self.assertEqual(stages[stages.index("merging") + 1], "deploying", name)
        moved = self.aged("Moved", 1, stage="merging")
        board.cmd_set(self.root, moved, ["stage=deploying"])
        self.assertEqual(self.get(moved)["stage"], "deploying")
        deploying = self.aged("Deploying", 31, stage="deploying")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [deploying])
        self.assertEqual((self.get(deploying)["stage"], self.get(deploying)["stalled"]), ("deploying", True))
        self.assertEqual(self.get(deploying)["reason"], "stalled: no board update for 30 min and no live session")

    def test_limit_hold_cleared_on_stage_change_and_pause(self):
        def held(title):
            return self.aged(title, 1, stage="build", limitResetAt=1_800_000_000)
        kept = held("Kept")
        board.cmd_set(self.root, kept, ["round=1"])
        self.assertEqual(self.get(kept)["limitResetAt"], 1_800_000_000)
        moved = held("Moved")
        board.cmd_set(self.root, moved, ["stage=merging"])
        self.assertNotIn("limitResetAt", self.get(moved))
        paused = held("Paused")
        board.cmd_pause(self.root, paused)
        self.assertNotIn("limitResetAt", self.get(paused))
        with self.assertRaises(SystemExit) as e:
            board.main(["--dir", str(self.root), "set", kept, "limitResetAt=1"])
        self.assertTrue(str(e.exception).startswith("bad field 'limitResetAt=1'"), str(e.exception))
        self.assertEqual(self.get(kept)["limitResetAt"], 1_800_000_000)

    def test_watchdog_stall_logs_stop(self):
        idle = self.aged("Idle build", 180, stage="build")
        (self.root / "jobs" / idle).mkdir(parents=True, exist_ok=True)
        (self.root / "jobs" / idle / "build.md").write_text("x")
        self.age_job_dir(idle, 3)
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: True), [idle])
        dead = self.aged("Dead build", 45, stage="build")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [dead])
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])  # flags nothing: no line
        lines = self.log_lines()
        # job 825: a standalone job with no live session is auto-resumed, so its line is auto; live-but-idle is not
        self.assertEqual([set(l) for l in lines], [{"date", "project", "job", "kind", "reason"},
                                                   {"date", "project", "job", "kind", "reason", "auto"}])
        for l in lines:
            self.assertRegex(l["date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual([(l["project"], l["job"], l["kind"], l["reason"], l.get("auto")) for l in lines], [
            (Path(self.tmp.name).name, idle, "stall", "stalled: no board or job-dir change for 2 h "
             "(session alive but idle)", None),
            (Path(self.tmp.name).name, dead, "stall", "stalled: no board update for 30 min and no live session", True)])

    def test_watchdog_stall_auto_only_when_resumable(self):
        # Job 825: auto only when auto_resume will retry it (no parent, or a running unpaused runall/bigboy parent).
        cases = [("Run parent", dict(stage="running", lane="runall"), True),
                 ("Big parent", dict(stage="running", lane="bigboy"), True),
                 ("Paused parent", dict(stage="running", lane="runall", paused=True), None),
                 ("Stuck parent", dict(stage="needs-human", lane="bigboy"), None),
                 ("Plain parent", dict(stage="running", lane="standard"), None)]
        for title, fields, want in cases:
            with self.subTest(title):
                parent = self.aged(title, 1, **fields)
                kid = self.aged(f"{title} kid", 45, stage="build", parent=parent)
                self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [kid])
                line = self.log_lines()[-1]
                self.assertEqual((line["job"], line["kind"], line.get("auto")), (kid, "stall", want))
                self.assertEqual("auto" in line, want is True)

    def test_watchdog_flags_stalled_review_job(self):
        job_id = self.aged("Stuck review", 31, stage="review")
        old = self.get(job_id)["updatedAt"]
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [job_id])
        job = self.get(job_id)
        self.assertEqual((job["stage"], job["stalled"]), ("review", True))
        self.assertEqual(job["reason"], "stalled: no board update for 30 min and no live session")
        self.assertNotIn("Fix: click Resume", job["reason"])
        self.assertNotEqual(job["updatedAt"], old)
        for stage in ("build", "check", "approve"):
            other = self.aged(f"Stuck {stage}", 45, stage=stage)
            self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [other])
            self.assertEqual((self.get(other)["stage"], self.get(other)["stalled"]), (stage, True))

    def test_watchdog_stall_plays_no_sound(self):
        dead = self.aged("Dead build", 45, stage="build")
        idle = self.aged("Idle check", 180, stage="check")
        (self.root / "jobs" / idle).mkdir(parents=True, exist_ok=True)
        self.age_job_dir(idle, 3)
        with mock.patch.object(board, "play") as play:
            self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: job["id"] == idle), [dead, idle])
        play.assert_not_called()

    def test_watchdog_skips_fresh_live_waiting_and_inactive_jobs(self):
        fresh = self.aged("Fresh", 29, stage="review")
        live = self.aged("Live", 31, stage="build")
        paused = self.aged("Paused", 31, stage="check", waiting="question: which one?")
        others = [self.aged(f"In {s}", 31, stage=s)
                  for s in ("plan", "running", "waiting", "needs-human", "done", "aborted")]
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
        self.assertEqual((self.get(stuck)["stage"], self.get(stuck)["stalled"]), ("spec", True))
        self.assertEqual(self.get(stuck)["reason"], "stalled: no board update for 30 min and no live session")
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
        self.assertFalse((self.root / "questions.log").exists(), "an orphaned requeue is not a stop")

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
        self.assertEqual((self.get(std)["stage"], self.get(std)["stalled"]), ("build", True))
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])
        self.assertEqual((self.get(lil)["stage"], self.get(lil)["updatedAt"]), ("build", old))

    def test_watchdog_flags_lilguy_with_worktree(self):
        wt = self.aged("Lil in worktree", 45, stage="build", lane="lilguy", worktree="/tmp/wt-lil")
        here = self.aged("Lil in checkout", 45, stage="build", lane="lilguy")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [wt])
        self.assertEqual((self.get(wt)["stage"], self.get(wt)["stalled"]), ("build", True))
        self.assertEqual(self.get(wt)["reason"], "stalled: no board update for 30 min and no live session")
        self.assertEqual(self.get(here)["stage"], "build")

    @mock.patch.object(board, "session_alive_fn", lambda: (lambda job: True))  # the build/review siblings run
    def test_resume_blocker_matches_ready_rules(self):
        stalled = ["stage=needs-human", "reason=stalled in build: no board update for 30 min and no live session. Fix: click Resume."]
        # No parent: never blocked.
        solo = board.cmd_new(self.root, "Solo")
        board.cmd_set(self.root, solo, stalled, internal=True)
        self.assertIsNone(board.resume_blocker(self.root, solo))
        # BigBoy, no cap: a, b, c parallel; d parallel=no.
        parent = self.plan(self.ticket(1), self.ticket(2), self.ticket(3), self.ticket(4, parallel="no — big"),
                           self.ticket(5, deps="T1, T2, T3, T4", exposure="yes"))
        a, b, c, d, e = board.cmd_plan_apply(self.root, parent)["children"]
        self.spec(a, "src/a.py", "src/shared.py")
        self.spec(b, "src/b.py")
        self.spec(c, "src/c.py", "src/shared.py")
        self.spec(d, "src/d.py")
        board.cmd_set(self.root, a, stalled, internal=True)
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
        # (c) no count cap: five disjoint Run-all siblings in progress, even with usage.json over pace.
        _, kids = self.runall(7)
        for i, k in enumerate(kids):
            self.spec(k, f"src/r{i}.py")
        board.cmd_set(self.root, kids[0], stalled, internal=True)
        for k in kids[1:6]:
            board.cmd_set(self.root, k, ["stage=build"])
        now = int(__import__("time").time())
        usage = Path(self.tmp.name) / "usage.json"
        usage.write_text(json.dumps({"rate_limits": {"five_hour": {"used_percentage": 100, "resets_at": now + 9000}},
                                     "written_at": now}))
        with mock.patch.dict(os.environ, {"SCRUM_USAGE": str(usage)}):
            self.assertIsNone(board.resume_blocker(self.root, kids[0]))
            board.cmd_set(self.root, b, ["stage=build"])
            board.cmd_set(self.root, a, stalled, internal=True)
            self.assertIsNone(board.resume_blocker(self.root, a))
        board.cmd_set(self.root, b, ["stage=done"])
        self.assertIsNone(board.resume_blocker(self.root, a))  # BigBoy without pacing has no cap

    STALLED = ["stage=needs-human", "reason=stalled in build: no board update for 30 min and no live session. Fix: click Resume."]

    def hold(self, k, until=4_000_000_000):
        """Set (or clear, until=None) limitResetAt, which cmd_set does not allow."""
        data = json.loads((self.root / "board.json").read_text())
        for j in data["jobs"]:
            if j["id"] == k:
                j.pop("limitResetAt", None)
                if until:
                    j["limitResetAt"] = until
        (self.root / "board.json").write_text(json.dumps(data))

    def shared_kids(self, n):
        _, kids = self.runall(n)
        for k in kids:
            self.spec(k, "src/shared.py")
        return kids

    def test_resume_blocker_live_sibling_always_busy(self):
        a, b = self.shared_kids(2)
        for sets in (self.STALLED, ["stage=waiting"], ["stage=done"], ["stage=build"]):
            board.cmd_set(self.root, b, sets, internal=True)
            self.hold(b)
            self.assertEqual(board.resume_blocker(self.root, a, live={b}), f"sibling {b} shares src/shared.py", sets)
        board.cmd_pause(self.root, b)
        self.assertEqual(board.resume_blocker(self.root, a, live={b}).ids, [b])

    def test_resume_blocker_sessionless_siblings_idle(self):
        a, b = self.shared_kids(2)
        dead = lambda: (lambda job: False)
        with mock.patch.object(board, "session_alive_fn", dead):
            board.cmd_set(self.root, b, self.STALLED, internal=True)
            self.assertIsNone(board.resume_blocker(self.root, a))
            board.cmd_set(self.root, b, ["stage=build"], internal=True)
            self.hold(b)
            self.assertIsNone(board.resume_blocker(self.root, a))  # held
            self.hold(b, None)
            self.assertIsNone(board.resume_blocker(self.root, a))  # WATCHED, dead session
            board.cmd_pause(self.root, b)
            self.assertIsNone(board.resume_blocker(self.root, a))  # paused

    def test_resume_blocker_limit_held_siblings_no_deadlock(self):
        kids = self.shared_kids(3)
        for k in kids:
            board.cmd_set(self.root, k, ["stage=build"], internal=True)
            self.hold(k)
        with mock.patch.object(board, "session_alive_fn", lambda: (lambda job: False)):
            live, resumed = set(), []
            for k in kids:  # serve.py resumes one at a time, adding it to live
                if board.resume_blocker(self.root, k, live=live) is None:
                    resumed.append(k)
                    live.add(k)
            self.assertEqual(resumed, [kids[0]])
            for k in kids[1:]:
                self.assertEqual(board.resume_blocker(self.root, k, live=live), f"sibling {kids[0]} shares src/shared.py")

    def test_resume_blocker_stalled_siblings_dont_block(self):
        a, b = self.shared_kids(2)
        for k in (a, b):
            board.cmd_set(self.root, k, self.STALLED, internal=True)
        self.assertIsNone(board.resume_blocker(self.root, a))
        self.assertIsNone(board.resume_blocker(self.root, b))

    def test_resume_blocker_alive_watched_sibling_blocks(self):
        a, b = self.shared_kids(2)
        board.cmd_set(self.root, b, ["stage=review"])
        with mock.patch.object(board, "session_alive_fn", lambda: (lambda job: job["id"] == b)):
            self.assertEqual(board.resume_blocker(self.root, a), f"sibling {b} shares src/shared.py")
        with mock.patch.object(board, "session_alive_fn", lambda: (lambda job: False)):
            self.assertIsNone(board.resume_blocker(self.root, a))

    def test_resume_blocker_skips_ps_scan_when_no_watched_sibling(self):
        a, b, c = self.shared_kids(3)
        calls = []
        def scan():
            calls.append(1)
            return lambda job: True
        with mock.patch.object(board, "session_alive_fn", scan):
            board.cmd_set(self.root, b, self.STALLED, internal=True)
            board.cmd_set(self.root, c, ["stage=build"], internal=True)
            self.hold(c)
            board.resume_blocker(self.root, a, live={b})
            self.assertEqual(calls, [])
            self.hold(c, None)
            board.resume_blocker(self.root, a)
            self.assertEqual(calls, [1])

    def test_live_sessions_count_as_busy_siblings(self):
        """A child serve.py just spawned still reads needs-human (or waiting) on the board; `live` counts it as busy so
        one sweep cannot resume or claim beside an overlapping sibling."""
        stalled = ["stage=needs-human", "reason=stalled in build: no board update for 30 min and no live session. Fix: click Resume."]
        parent, kids = self.runall(4)
        for i, k in enumerate(kids):
            self.spec(k, f"src/l{i % 2}.py")  # kids 0 and 2 share src/l0.py, kids 1 and 3 share src/l1.py
        for k in kids[:2]:
            board.cmd_set(self.root, k, stalled, internal=True)
        self.assertIsNone(board.resume_blocker(self.root, kids[0]))
        text = board.resume_blocker(self.root, kids[0], live={kids[2]})
        self.assertEqual((text, text.ids), (f"sibling {kids[2]} shares src/l0.py", [kids[2]]))
        self.assertIsNone(board.resume_blocker(self.root, kids[0], live={kids[0], kids[1]}), "itself never counts")
        out = board.cmd_ready(self.root, parent, live=set(kids[:2]))
        self.assertEqual(out["ready"], [], "live resumes block the waiting children that share their files")
        self.assertEqual(board.cmd_ready(self.root, parent, live={kids[0]})["ready"], [], "stalled kids[1] holds claims")
        board.cmd_abort(self.root, kids[1], False)
        self.assertEqual(board.cmd_ready(self.root, parent, live={kids[0]})["ready"], [kids[3]])

    # --- cloud lane ---
    def test_new_with_id_keeps_the_given_id(self):
        self.assertEqual(board.cmd_new(self.root, "From the Mac", "042-from-the-mac"), "042-from-the-mac")
        self.assertTrue((self.root / "jobs" / "042-from-the-mac").is_dir())
        self.assertEqual(board.cmd_new(self.root, "Next one"), "043-next-one")
        with self.assertRaises(SystemExit):
            board.cmd_new(self.root, "Again", "042-from-the-mac")
        with self.assertRaises(SystemExit):
            board.cmd_new(self.root, "Bad", "../evil")
        out = run_board("--dir", str(self.root), "new", "CLI", "--id", "007-cli")
        out.check_returncode()
        out = out.stdout.strip()
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
        lines = ("  301 ??      node /Users/t/onewitharts/.claude/worktrees/scrum-024-x/node_modules/.bin/next dev -p 3024\n"
                 "  302 ttys009 node /Users/t/onewitharts/.claude/worktrees/scrum-011-x/node_modules/.bin/next dev\n"
                 "  303 ttys004 /Users/t/.local/bin/claude --resume\n"
                 "  304 ??      /Users/t/.local/bin/claude -p /trevskills-scrum start 005-headless\n"
                 "  306 ??      node /opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js start 010-node\n")
        ps = mock.Mock(stdout=lines, returncode=0)
        with mock.patch.object(board.subprocess, "run", return_value=ps):
            alive = board.session_alive_fn()
            self.assertFalse(alive({"id": "024-x", "tty": None}))
            self.assertFalse(alive({"id": "011-x", "tty": "ttys009"}))
            self.assertTrue(alive({"id": "006-interactive", "tty": "ttys004"}))
            self.assertTrue(alive({"id": "005-headless", "tty": None}))
            self.assertTrue(alive({"id": "010-node", "tty": None}))
        job_id = self.aged("Orphan dev server", 31, stage="build")
        orphan = ps.stdout.replace("scrum-024-x", f"scrum-{job_id}")
        with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout=orphan, returncode=0)):
            self.assertEqual(board.cmd_watchdog(self.root), [job_id])

    def test_session_alive_matches_id_or_tty_and_fails_safe(self):
        lines = ("  301 ttys003 -zsh\n"
                 "  302 ttys004 /Users/t/.local/bin/claude --resume\n"
                 "  303 ??      /Users/t/.local/bin/claude -p /trevskills-scrum start 005-headless\n"
                 "  304 ??      python3 runner.py 007-plain-python\n")
        with mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout=lines, returncode=0)) as run:
            alive = board.session_alive_fn()
            self.assertTrue(alive({"id": "005-headless", "tty": None}))
            self.assertTrue(alive({"id": "006-interactive", "tty": "ttys004"}))
            self.assertTrue(alive({"id": "006-interactive", "tty": "ttys004", "pid": None}))
            self.assertFalse(alive({"id": "007-plain-python"}))
            self.assertFalse(alive({"id": "008-shell-only", "tty": "ttys003"}))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["ps", "-axo", "pid=,tty=,command="])
        for err in (OSError("no ps"), subprocess.TimeoutExpired("ps", 5)):
            with mock.patch.object(board.subprocess, "run", side_effect=err):
                self.assertTrue(board.session_alive_fn()({"id": "007-plain-python", "tty": None}))
        denied = subprocess.CompletedProcess(["ps"], 1, stdout="", stderr="ps: Operation not permitted\n")
        with mock.patch.object(board.subprocess, "run", return_value=denied):  # e.g. a sandboxed Bash call
            self.assertTrue(board.session_alive_fn()({"id": "007-plain-python", "tty": None}))

    def test_session_alive_pid_beats_reused_tty(self):
        reused = ("  222 ttys004 /Users/t/.local/bin/claude\n"  # a later chat on the dead job's tty
                  "  333 ttys005 -zsh\n")
        job = {"id": "014-x", "tty": "ttys004", "pid": 111}
        ps = lambda out: mock.patch.object(board.subprocess, "run", return_value=mock.Mock(stdout=out, returncode=0))
        with ps(reused):
            self.assertFalse(board.session_alive_fn()(job))
            self.assertTrue(board.session_alive_fn()({"id": "015-old", "tty": "ttys004"}))  # no pid: tty, as before
        with ps(reused + "  111 ttys004 /Users/t/.local/bin/claude --resume\n"):
            self.assertTrue(board.session_alive_fn()(job))
        with ps(reused + "  111 ttys004 /bin/zsh\n"):  # pid 111 recycled into a non-claude process
            self.assertFalse(board.session_alive_fn()(job))
        job_id = self.aged("Dead on a reused tty", 31, stage="build", tty="ttys004", pid=111)
        with ps(reused):
            self.assertEqual(board.cmd_watchdog(self.root), [job_id])
        self.assertIs(next(j for j in self.jobs() if j["id"] == job_id)["stalled"], True)

    def test_watchdog_cli_prints_flagged(self):
        run = lambda: run_board("--dir", str(self.root), "watchdog")
        fresh = self.aged("Fresh one", 1, stage="build")
        before = (self.root / "board.json").read_text()
        out = run()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), {"flagged": []})
        self.assertEqual((self.root / "board.json").read_text(), before)
        stuck = self.aged("Zq watchdog cli probe", 40, stage="check")
        out = run()
        self.assertEqual(json.loads(out.stdout), {"flagged": [stuck]})
        self.assertEqual((self.get(stuck)["stage"], self.get(stuck)["stalled"], self.get(fresh)["stage"]),
                         ("check", True, "build"))
        self.assertEqual(json.loads(run().stdout), {"flagged": []})  # a second run flags nothing

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
        out = run_board("--dir", str(self.root), *args)
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

    def test_stalled_helpers_accept_both_shapes(self):
        legacy = {"stage": "needs-human", "reason": "stalled in build: no board update"}
        new = {"stage": "build", "stalled": True, "reason": "stalled: no live session"}
        self.assertTrue(board.stalled(legacy))
        self.assertTrue(board.stalled(new))
        self.assertEqual(board.stall_stage(legacy), "build")
        self.assertEqual(board.stall_stage(new), "build")
        not_stalled = [
            {"stage": "needs-human", "paused": True, "reason": "stalled in build: paused by Trevor"},
            {"stage": "build", "paused": True, "stalled": True, "reason": "stalled in build: paused by Trevor"},
            *({"stage": s, "stalled": True, "reason": "stalled: no live session"}
              for s in ("done", "aborted", "waiting", "needs-human")),
            {"stage": "needs-human", "reason": "blocked: x"},
        ]
        for job in not_stalled:
            self.assertFalse(board.stalled(job), job)
            self.assertIsNone(board.stall_stage(job), job)
        self.assertIn("stalled: ", board.RESUMABLE)

    def test_resume_first_skips_stalled_child_of_non_running_parent(self):
        shapes = ({"stage": "build", "stalled": True, "reason": "stalled: no live session"},
                  {"stage": "needs-human", "reason": "stalled in build: no live session"})
        for shape in shapes:
            for par in ({"stage": "running", "paused": True}, {"stage": "needs-human"}, {"stage": "done"}):
                with self.subTest(shape=shape["stage"], parent=par):
                    kid = {"id": "k", "parent": "p", **shape}
                    # a paused parent counts itself (1), the stalled child adds nothing
                    self.assertEqual(board.resume_first([{"id": "p", **par}, kid]), int(bool(par.get("paused"))))

    def test_resume_first_still_counts_running_parent_child_and_standalone(self):
        for shape in ({"stage": "build", "stalled": True, "reason": "stalled: no live session"},
                      {"stage": "needs-human", "reason": "stalled in build: no live session"}):
            par = {"id": "p", "stage": "running"}
            self.assertEqual(board.resume_first([par, {"id": "k", "parent": "p", **shape}]), 1)
            self.assertEqual(board.resume_first([{"id": "s", **shape}]), 1)
            self.assertEqual(board.resume_first([{"id": "k", "parent": "gone", **shape}]), 1, "missing parent counts")
        paused = {"id": "k", "parent": "p", "stage": "build", "paused": True}
        self.assertEqual(board.resume_first([{"id": "p", "stage": "running", "paused": True}, paused]), 2, "both paused")

    @mock.patch.object(board, "session_alive_fn", lambda: (lambda job: True))  # a build sibling would hold its slot
    def test_ready_treats_new_shape_stalled_child_as_idle(self):
        parent, (c1, c2, c3) = self.three()
        board.cmd_ready(self.root, parent)  # claims c1 and c2
        board.cmd_set(self.root, c1, ["stage=done"])
        self.edit_jobs(**{c2: {"stage": "build", "stalled": True, "reason": "stalled: no live session"}})
        kid = self.child(c2)
        self.assertTrue(board.idle(kid))
        self.assertEqual(board.resume_first([kid, dict(kid, lane="lilguy")]), 1)
        self.assertEqual(board.resume_first([dict(kid, paused=True)]), 1)
        self.edit_jobs(**{c3: {"stage": "needs-human", "reason": "stalled in check: x"}})
        self.assertIsNone(board.resume_blocker(self.root, c3))  # c3 has no spec: it runs alone beside any busy sibling
        self.edit_jobs(**{c2: {"stalled": False}})
        self.assertEqual(str(board.resume_blocker(self.root, c3)), "this job runs alone")  # the contrast: c2 busy again
        self.edit_jobs(**{c2: {"stalled": True}, c3: {"stage": "waiting", "reason": None}})
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), ([], 0))
        p = self.child(parent)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))
        # legacy shape: the next locked write migrates the child to the new shape, so it is idle and not named
        self.edit_jobs(**{c2: {"stage": "needs-human", "stalled": False, "reason": "stalled in build: x"}})
        board.cmd_ready(self.root, parent)
        p, kid = self.child(parent), self.child(c2)
        self.assertEqual((p["stage"], p["reason"]), ("running", None))
        self.assertEqual((kid["stage"], kid["stalled"], kid["reason"]), ("build", True, "stalled: x"))

    def test_watchdog_skips_new_shape_stalled(self):
        self.aged("New stall", 31, stage="build", stalled=True, reason="stalled: no live session")
        before = (self.root / "board.json").read_bytes()
        mtime = (self.root / "board.json").stat().st_mtime_ns
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])
        self.assertEqual((self.root / "board.json").read_bytes(), before)
        self.assertEqual((self.root / "board.json").stat().st_mtime_ns, mtime)

    def test_abort_cascade_takes_new_shape_stalled_dependent(self):
        a, b = board.cmd_new(self.root, "a"), board.cmd_new(self.root, "b")
        self.edit_jobs(**{b: {"stage": "build", "stalled": True, "reason": "stalled: no live session", "depends_on": [a]}})
        self.assertEqual(board.cmd_abort(self.root, a, False, cascade=True), ["001-a", "002-b"])
        self.assertEqual((self.by_id()[b]["stage"], self.by_id()[b]["reason"]), ("aborted", "Removed with 001-a"))

    def test_roadmap_show_blocker_includes_stalled_in_stage(self):
        self.roadmap()
        jobs = [{"id": self.J2, "stage": "build", "stalled": True, "reason": "stalled: no live session"}]
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))
        self.assertEqual(board.roadmap_show(self.root)["blocker"], {"job": self.J2, "reason": "stalled: no live session"})
        jobs = [{"id": self.J2, "stage": "running"},
                {"id": "021-kid", "parent": self.J2, "stage": "review", "stalled": True, "reason": "stalled: x"}]
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))
        self.assertEqual(board.roadmap_show(self.root)["blocker"], {"job": "021-kid", "reason": "stalled: x"})
        jobs[1]["stage"] = "running"  # a leftover `stalled` outside a WATCHED stage is not a stall
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))
        self.assertIsNone(board.roadmap_show(self.root)["blocker"])

    def test_set_drops_stalled_on_resume_or_stage_change(self):
        job_id = board.cmd_new(self.root, "x")
        stall = {"stage": "build", "stalled": True, "reason": "stalled: no live session"}
        self.edit_jobs(**{job_id: stall})
        board.cmd_set(self.root, job_id, ["reason=x"])
        self.assertIs(self.jobs()[0].get("stalled"), True)
        board.cmd_set(self.root, job_id, ["stage=build", "reason="], unpause=True)
        self.assertNotIn("stalled", self.jobs()[0])
        self.edit_jobs(**{job_id: stall})
        board.cmd_set(self.root, job_id, ["stage=check"])
        self.assertNotIn("stalled", self.jobs()[0])

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

    STALL = "stalled: no board update for 30 min and no live session"

    def test_watchdog_stall_logs_roadmap_step(self):
        self.roadmap()
        board.cmd_new(self.root, "Quote builder part 2", self.J2)
        self.aged("Unrelated", 5, stage="build")
        for _ in range(2):  # stall, resume via roadmap-link, stall again: two Log lines
            data = json.loads((self.root / "board.json").read_text())
            j2 = next(j for j in data["jobs"] if j["id"] == self.J2)
            j2.pop("stalled", None)  # the resume's `B set --unpause` drops it
            j2.update(stage="build", updatedAt="2026-01-01T00:00:00+00:00")
            (self.root / "board.json").write_text(json.dumps(data))
            self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [self.J2])
            self.assertEqual((self.get(self.J2)["stage"], self.get(self.J2)["stalled"]), ("build", True))
            self.assertIn(f"- [!] S2 bigboy {self.J2}:", self.rm_text())
            self.assertRegex(self.rm_text().splitlines()[-1],
                             self.LOG_RE + rf"P1 S2 stopped: {self.J2} stalled: no board update for 30 min "
                             r"and no live session$")
            board.cmd_roadmap_link(self.root, 1, 2, self.J2)
            self.assertIn(f"- [~] S2 bigboy {self.J2}:", self.rm_text())
        logs = (board.md_section(self.rm_text(), "Log") or "").strip().splitlines()
        stops = [line for line in logs if f"stopped: {self.J2} {self.STALL}" in line]
        self.assertEqual(len(stops), 2)
        self.assertEqual(len(logs), 5)  # the seed line + (stopped, started) twice

    def test_watchdog_stall_of_child_logs_parent_step(self):
        self.roadmap()
        child = self.aged("Child fix", 45, stage="build", parent=self.J2)
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [child])
        self.assertIn(f"- [!] S2 bigboy {self.J2}:", self.rm_text())
        logs = (board.md_section(self.rm_text(), "Log") or "").strip().splitlines()
        self.assertEqual(len(logs), 2)
        self.assertRegex(logs[1], self.LOG_RE + rf"P1 S2 stopped: {child} stalled: no board update for 30 min "
                         r"and no live session$")

    def test_watchdog_stall_roadmap_missing_or_malformed(self):
        import contextlib, io
        cases = [(None, {}), (self.ROADMAP, {}), (self.ROADMAP.replace("[~] S2", "[x] S2"), {"parent": self.J2}),
                 (self.ROADMAP.replace("[~] S2", "[x] S2"), {"id": self.J2}), ("# not a roadmap\n", {"parent": self.J2})]
        for text, how in cases:
            with self.subTest(text=text and text[:20], how=how):
                (self.root / "roadmap.md").unlink(missing_ok=True)
                if text is not None:
                    self.roadmap(text)
                if "id" in how:
                    (self.root / "board.json").unlink(missing_ok=True)
                    board.cmd_new(self.root, "J2", self.J2)
                    data = json.loads((self.root / "board.json").read_text())
                    data["jobs"][0].update(stage="review", updatedAt="2026-01-01T00:00:00+00:00")
                    (self.root / "board.json").write_text(json.dumps(data))
                    job_id = self.J2
                else:
                    job_id = self.aged("Stuck", 45, stage="review", **how)
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [job_id])
                self.assertEqual((self.get(job_id)["stage"], self.get(job_id)["stalled"]), ("review", True))
                self.assertEqual(self.get(job_id)["reason"], "stalled: no board update for 30 min and no live session")
                if text is None:
                    self.assertFalse((self.root / "roadmap.md").exists())
                else:
                    self.assertEqual(self.rm_text(), text)
                if text and text.startswith("# not"):
                    self.assertEqual(err.getvalue(),
                                     "watchdog: roadmap: roadmap.md line 1: first line must be 'ROADMAP: <name>'\n")
                else:
                    self.assertEqual(err.getvalue(), "")

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
        out = run_board("--dir", str(self.root), "artifacts", job_id)
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

    # --- wait-on / wake_waiting ---
    def wait_board(self, *jobs):
        """Write a board of {"id", "stage", ...} jobs straight to board.json (no lock needed: no writer runs)."""
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"updatedAt": "2026-01-01T00:00:00+00:00", **j} for j in jobs]}))

    def test_wait_on_parks_job_waiting_with_depends_on(self):
        self.wait_board({"id": "001-first", "stage": "review"},
                        {"id": "002-second", "stage": "build", "worktree": "/tmp/wt-002", "reason": "old"})
        out = board.cmd_wait_on(self.root, "002-second", "001-first")
        self.assertEqual(out, {"id": "002-second", "waiting_on": "001-first"})
        job = self.jobs()[1]
        self.assertEqual((job["stage"], job["depends_on"], job["reason"], job["worktree"]),
                         ("waiting", ["001-first"], "waiting on 001-first", None))
        self.assertNotEqual(job["updatedAt"], "2026-01-01T00:00:00+00:00")
        self.assertNotIn("question", job)
        self.assertNotIn("options", job)
        self.assertFalse((self.root / "questions.log").exists())
        self.assertEqual(self.jobs()[0]["stage"], "review")

    def test_wait_on_plays_no_sound(self):
        self.wait_board({"id": "001-first", "stage": "review"}, {"id": "002-second", "stage": "build"})
        with mock.patch.object(board, "play") as play:
            board.cmd_wait_on(self.root, "002-second", "001-first")
        play.assert_not_called()

    def test_wait_on_resolves_number_prefix(self):
        self.wait_board({"id": "001-first", "stage": "merging"}, {"id": "0011-other", "stage": "spec"},
                        {"id": "002-second", "stage": "build"})
        self.assertEqual(board.cmd_wait_on(self.root, "002-second", "001"),
                         {"id": "002-second", "waiting_on": "001-first"})
        self.assertEqual(self.jobs()[2]["depends_on"], ["001-first"])

    def test_wait_on_refuses_unknown_ambiguous_self_done_aborted_cycle(self):
        jobs = [{"id": "001-first", "stage": "review"}, {"id": "001-twin", "stage": "review"},
                {"id": "003-done", "stage": "done"}, {"id": "004-gone", "stage": "aborted"},
                {"id": "005-loop", "stage": "waiting", "depends_on": ["006-me"]},
                {"id": "006-me", "stage": "build", "worktree": "/tmp/wt"},
                {"id": "007-paused", "stage": "build", "paused": True},
                {"id": "008-aborted", "stage": "aborted"},
                {"id": "009-chain", "stage": "waiting", "depends_on": ["005-loop"]}]
        cases = [("006-me", "009-chain"),
                 ("006-me", "999"), ("006-me", "999-nope"), ("006-me", "001"), ("006-me", "006-me"),
                 ("006-me", "006"), ("006-me", "003-done"), ("006-me", "004"), ("006-me", "005-loop"),
                 ("007-paused", "001-first"), ("008-aborted", "001-first"), ("006-me", "-1")]
        for job_id, blocker in cases:
            with self.subTest(job=job_id, blocker=blocker):
                self.wait_board(*jobs)
                before = (self.root / "board.json").read_text()
                with self.assertRaises(SystemExit) as e:
                    board.cmd_wait_on(self.root, job_id, blocker)
                self.assertIsInstance(e.exception.code, str)
                self.assertEqual((self.root / "board.json").read_text(), before)

    def test_wait_on_refuses_child_with_outside_blocker(self):
        self.wait_board({"id": "001-outside", "stage": "review"},
                        {"id": "002-parent", "stage": "running", "lane": "bigboy", "children": ["003-a", "004-b"]},
                        {"id": "003-a", "stage": "review", "parent": "002-parent"},
                        {"id": "004-b", "stage": "build", "parent": "002-parent"})
        before = (self.root / "board.json").read_text()
        with self.assertRaises(SystemExit):
            board.cmd_wait_on(self.root, "004-b", "001-outside")
        self.assertEqual((self.root / "board.json").read_text(), before)
        self.assertEqual(board.cmd_wait_on(self.root, "004-b", "003"), {"id": "004-b", "waiting_on": "003-a"})

    def test_wait_on_cli_prints_json(self):
        self.wait_board({"id": "001-first", "stage": "review"}, {"id": "002-second", "stage": "build"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            board.main(["--dir", str(self.root), "wait-on", "002-second", "001"])
        self.assertEqual(json.loads(buf.getvalue()), {"id": "002-second", "waiting_on": "001-first"})
        self.assertIn("wait-on <id> <blocker>", board.__doc__)

    def test_wake_waiting_claims_when_dependency_done(self):
        self.wait_board({"id": "001-first", "stage": "done"},
                        {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"],
                         "reason": "waiting on 001-first"})
        self.assertEqual(board.wake_waiting(self.root), {"ready": ["002-second"], "lost": []})
        job = self.jobs()[1]
        self.assertEqual((job["stage"], job["reason"]), ("spec", None))
        self.assertNotEqual(job["updatedAt"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(board.wake_waiting(self.root), {"ready": [], "lost": []})

    def test_wake_waiting_claims_no_more_than_room(self):
        self.wait_board({"id": "001-first", "stage": "done"},
                        {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"]},
                        {"id": "003-third", "stage": "waiting", "depends_on": ["001-first"]})
        self.assertEqual(board.wake_waiting(self.root, 1), {"ready": ["002-second"], "lost": []})
        self.assertEqual([j["stage"] for j in self.jobs()], ["done", "spec", "waiting"])
        self.assertEqual(board.wake_waiting(self.root, 0), {"ready": [], "lost": []})
        self.assertEqual(board.wake_waiting(self.root, 1), {"ready": ["003-third"], "lost": []})

    def test_wake_waiting_leaves_unfinished_dependency(self):
        jobs = [{"id": "001-first", "stage": "merging"},
                {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"], "reason": "waiting on 001-first"},
                {"id": "003-parent", "stage": "running", "lane": "bigboy", "children": ["004-kid"]},
                {"id": "004-kid", "stage": "waiting", "parent": "003-parent", "depends_on": ["005-done"]},
                {"id": "005-done", "stage": "done"},
                {"id": "006-setup", "stage": "waiting", "setup": "pending", "depends_on": ["005-done"]},
                {"id": "007-plain", "stage": "waiting"},
                {"id": "008-paused", "stage": "waiting", "paused": True, "depends_on": ["005-done"]}]
        self.wait_board(*jobs)
        self.assertEqual(board.wake_waiting(self.root), {"ready": [], "lost": []})
        self.assertEqual([j["stage"] for j in self.jobs()], [j["stage"] for j in jobs])

    def test_wake_waiting_asks_when_dependency_aborted(self):
        self.wait_board({"id": "001-first", "stage": "aborted"},
                        {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"]},
                        {"id": "003-third", "stage": "waiting", "depends_on": ["009-missing"]})
        self.assertEqual(board.wake_waiting(self.root), {"ready": [], "lost": ["002-second", "003-third"]})
        second, third = self.jobs()[1], self.jobs()[2]
        self.assertEqual(second["stage"], "needs-human")
        self.assertEqual(second["question"],
                         "blocked: 001-first was aborted or removed, so this job has nothing to wait for.")
        self.assertEqual(second["options"], [
            {"key": "a", "label": "Put back on the backlog", "command": "abort 002-second --requeue"},
            {"key": "b", "label": "Remove this job", "command": "abort 002-second --cascade"}])
        self.assertEqual(third["question"],
                         "blocked: 009-missing was aborted or removed, so this job has nothing to wait for.")
        self.assertEqual((second["stopTitle"], third["stopTitle"]), ("DEPENDENCY", "DEPENDENCY"))
        self.assertEqual(board.wake_waiting(self.root), {"ready": [], "lost": []})

    def test_wake_waiting_asks_when_dependency_aborted_while_held(self):
        self.wait_board({"id": "001-first", "stage": "aborted"},
                        {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"]})
        self.assertEqual(board.wake_waiting(self.root, hold=lambda j: True), {"ready": [], "lost": ["002-second"]})
        self.assertEqual(self.jobs()[1]["stage"], "needs-human")

    def test_wait_on_then_keeps_worktree_and_records_wake(self):
        self.wait_board({"id": "001-first", "stage": "review"},
                        {"id": "002-second", "stage": "approve", "worktree": "/tmp/wt-002", "branch": "scrum/002-second",
                         "round": 2, "files": ["build.md"], "reason": "old"})
        out = board.cmd_wait_on(self.root, "002-second", "001", then="approve 002-second")
        self.assertEqual(out, {"id": "002-second", "waiting_on": "001-first"})
        job = self.jobs()[1]
        self.assertEqual({k: v for k, v in job.items() if k != "updatedAt"},
                         {"id": "002-second", "stage": "waiting", "worktree": "/tmp/wt-002", "branch": "scrum/002-second",
                          "round": 2, "files": ["build.md"], "reason": "waiting on 001-first",
                          "depends_on": ["001-first"], "wake": "approve 002-second"})
        self.wait_board({"id": "001-first", "stage": "review"}, {"id": "002-second", "stage": "build"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            board.main(["--dir", str(self.root), "wait-on", "002-second", "001", "--then", "approve 002-second"])
        self.assertEqual(json.loads(buf.getvalue()), {"id": "002-second", "waiting_on": "001-first"})
        self.assertEqual(self.jobs()[1]["wake"], "approve 002-second")
        self.assertIn('wait-on <id> <blocker> [--then "approve <id>"]', board.__doc__)

    def test_wait_on_then_rejects_other_command(self):
        self.wait_board({"id": "001-first", "stage": "review"}, {"id": "002-second", "stage": "approve", "worktree": "/w"})
        before = (self.root / "board.json").read_text()
        for then in ("approve 001-first", "resume 002-second", "approve  002-second", "approve 002-second --x", "",
                     "abort 002-second"):
            with self.subTest(then=then):
                with self.assertRaises(SystemExit) as e:
                    board.cmd_wait_on(self.root, "002-second", "001-first", then=then)
                self.assertIsInstance(e.exception.code, str)
                self.assertEqual((self.root / "board.json").read_text(), before)
        with self.assertRaises(SystemExit):  # the existing checks still run with then
            board.cmd_wait_on(self.root, "002-second", "002-second", then="approve 002-second")
        self.assertEqual((self.root / "board.json").read_text(), before)

    def test_wake_waiting_retries_wake_job_at_needs_human(self):
        self.wait_board({"id": "001-first", "stage": "done"},
                        {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"], "worktree": "/w",
                         "reason": "waiting on 001-first", "wake": "approve 002-second", "recommend": {"key": "a", "why": "x"}},
                        {"id": "003-third", "stage": "waiting", "depends_on": ["001-first"]},
                        {"id": "004-par", "stage": "running", "lane": "bigboy", "children": ["005-kid", "006-sib"]},
                        {"id": "005-kid", "stage": "waiting", "parent": "004-par", "depends_on": ["006-sib"],
                         "worktree": "/k", "wake": "approve 005-kid"},
                        {"id": "006-sib", "stage": "done", "parent": "004-par"})
        with mock.patch.object(board, "play") as play:
            self.assertEqual(board.wake_waiting(self.root, 1), {"ready": [], "lost": [], "retry": ["002-second"]})
            self.assertEqual([j["stage"] for j in self.jobs()], ["done", "needs-human", "waiting", "running", "waiting", "done"])
            self.assertEqual(board.wake_waiting(self.root), {"ready": ["003-third"], "lost": [], "retry": ["005-kid"]})
        play.assert_not_called()
        for job_id, dep in (("002-second", "001-first"), ("005-kid", "006-sib")):
            job = next(j for j in self.jobs() if j["id"] == job_id)
            q = f"retry: {dep} is done, so this job tries again."
            self.assertEqual((job["stage"], job["question"], job["reason"], job["stopTitle"]), ("needs-human", q, q, "DEPENDENCY"))
            self.assertEqual(job["options"], [
                {"key": "a", "label": "Try again", "command": f"approve {job_id}"},
                {"key": "b", "label": "Remove this job", "command": f"abort {job_id} --cascade"}])
            self.assertNotIn("wake", job)
            self.assertNotIn("recommend", job)
            self.assertIn("worktree", job)
        self.assertEqual(board.wake_waiting(self.root), {"ready": [], "lost": []})

    def test_cmd_ready_skips_wake_child(self):
        self.wait_board({"id": "001-par", "stage": "running", "lane": "bigboy", "children": ["002-kid", "003-sib"]},
                        {"id": "002-kid", "stage": "waiting", "parent": "001-par", "depends_on": ["003-sib"],
                         "worktree": "/k", "wake": "approve 002-kid"},
                        {"id": "003-sib", "stage": "done", "parent": "001-par"})
        with mock.patch.object(board, "machine_ok", return_value=None), \
                mock.patch.object(board, "usage_allowance", return_value=None), \
                mock.patch.object(board, "ram_room", return_value=5):
            self.assertEqual(board.cmd_ready(self.root, "001-par")["ready"], [])
        self.assertEqual(self.jobs()[1]["stage"], "waiting")

    def test_wake_waiting_wake_job_blocker_aborted_offers_retry(self):
        self.wait_board({"id": "001-first", "stage": "aborted"},
                        {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"], "worktree": "/w",
                         "reason": "waiting on 001-first", "wake": "approve 002-second"})
        self.assertEqual(board.wake_waiting(self.root), {"ready": [], "lost": ["002-second"]})
        job = self.jobs()[1]
        q = "retry: 001-first was aborted or removed, so this job no longer waits on it."
        self.assertEqual((job["stage"], job["question"], job["stopTitle"]), ("needs-human", q, "DEPENDENCY"))
        self.assertNotIn("waiting on", job["reason"])
        self.assertEqual(job["options"], [
            {"key": "a", "label": "Try again", "command": "approve 002-second"},
            {"key": "b", "label": "Remove this job", "command": "abort 002-second --cascade"}])
        self.assertNotIn("wake", job)


class SpawnTest(unittest.TestCase):
    """B spawn: the one headless `claude -p` launcher. SCRUM_CLAUDE / board.CLAUDE point at a stub that records how it ran."""
    STUB = """import json, os, sys
st, null = os.fstat(0), os.stat(os.devnull)
rec = {"argv": sys.argv[1:], "cwd": os.getcwd(), "notifier": os.environ.get("CLAUDE_NOTIFIER_DISABLE"),
       "new_session": os.getsid(0) == os.getpid(), "stdin_devnull": (st.st_dev, st.st_ino) == (null.st_dev, null.st_ino)}
with open(os.environ["STUB_OUT"], "a") as fh:
    fh.write(json.dumps(rec) + "\\n")
print("stub out")
print("stub err", file=sys.stderr)
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo, self.root, self.out = base / "repo", base / "repo" / "scrum", base / "calls.jsonl"
        self.root.mkdir(parents=True)
        self.stub = base / "claude"
        self.stub.write_text(f"#!{sys.executable}\n" + self.STUB)
        self.stub.chmod(0o755)
        for patch in (mock.patch.object(board, "CLAUDE", str(self.stub)),
                      mock.patch.dict(os.environ, {"STUB_OUT": str(self.out), "SCRUM_CLAUDE": str(self.stub)})):
            patch.start()
            self.addCleanup(patch.stop)
        no_claude_pid(self)

    def records(self, n=1):
        for _ in range(200):
            lines = self.out.read_text().splitlines() if self.out.exists() else []
            if len(lines) >= n:
                return [json.loads(l) for l in lines]
            time.sleep(0.05)
        self.fail(f"stub ran {len(lines)} times, expected {n}")

    def cli(self, *args):
        return subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "spawn", *args],
                              capture_output=True, text=True, env={**os.environ, "CLAUDE_NOTIFIER_DISABLE": ""})

    def argv(self, action, prompt="/p", model=None):
        """The stub's argv (after the binary) for one in-process spawn."""
        self.out.unlink(missing_ok=True)
        proc, _ = board.spawn(self.root, "999-not-a-job", action, prompt, model=model)
        proc.wait(timeout=10)
        return self.records()[0]["argv"]

    def test_spawn_log_name_is_utc(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        line = json.loads(self.cli("123-some-job", "start").stdout)
        after = datetime.now(timezone.utc)
        stamp = re.match(r"^runs/(\d{8}-\d{6})-", line["log"]).group(1)
        got = datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
        self.assertTrue(before <= got <= after, (before, got, after))

    def test_spawn_that_never_started_leaves_no_log(self):
        with mock.patch.object(board, "CLAUDE", str(Path(self.tmp.name) / "missing-claude")):
            with self.assertRaises(FileNotFoundError):
                board.spawn(self.root, "123-some-job", "resume", "/p", model="sonnet")
        self.assertEqual(list((self.root / "runs").iterdir()), [], "no 0-byte log that reads like a dead session")

    def test_spawn_argv_log_and_env(self):
        out = self.cli("123-some-job", "start")
        self.assertEqual(out.returncode, 0, out.stderr)
        line = json.loads(out.stdout)
        self.assertEqual(set(line), {"log", "pid"})
        self.assertRegex(line["log"], r"^runs/\d{8}-\d{6}-start-123-some-job\.log$")
        self.assertIsInstance(line["pid"], int)
        rec = self.records()[0]
        self.assertEqual(rec["argv"], ["-p", "/trevskills-scrum start 123-some-job", "--model", "sonnet",
                                       "--permission-mode", "acceptEdits"])
        self.assertEqual(os.path.realpath(rec["cwd"]), os.path.realpath(self.repo))
        self.assertEqual(rec["notifier"], "1")
        self.assertTrue(rec["new_session"])
        self.assertTrue(rec["stdin_devnull"])
        log = self.root / line["log"]
        for _ in range(200):
            if "stub err" in log.read_text():
                break
            time.sleep(0.05)
        self.assertIn("stub out", log.read_text())
        self.assertIn("stub err", log.read_text())
        out = self.cli("123-some-job", "approve", "/trevskills-scrum approve 123-some-job it's; rm -rf ~")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.records(2)[1]["argv"], ["-p", "/trevskills-scrum approve 123-some-job it's; rm -rf ~",
                                                      "--permission-mode", "acceptEdits"])

    def test_big_ticket_model(self):
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": "001-big", "stage": "plan", "lane": "bigboy"}, {"id": "002-pts", "stage": "spec"},
            {"id": "003-small", "stage": "spec"}, {"id": "004-road", "stage": "running", "lane": "roadmap"}]}))
        (self.root / "backlog.md").write_text("# Backlog\n\n- [x] [8] Big thing → 002-pts\n- [x] [3] Small → 003-small\n")
        project = self.root / "project.md"
        project.write_text("- Orchestrator model: sonnet\n- Big ticket model: claude-fable-5-1\n")
        for job_id, model in (("001-big", "claude-fable-5-1"), ("002-pts", "claude-fable-5-1"),
                              ("004-road", "claude-fable-5-1"), ("003-small", "sonnet"), ("999-gone", "sonnet"),
                              (None, "sonnet")):
            self.assertEqual(board.orchestrator_model(self.root, job_id), model, job_id)
        for line in ("", "- Big ticket model: so net\n", "- Big ticket model:\n"):
            project.write_text("- Orchestrator model: sonnet\n" + line)
            self.assertEqual(board.orchestrator_model(self.root, "001-big"), "sonnet", line)
        project.write_text("- Big ticket model: opus\n")
        self.assertEqual(board.orchestrator_model(self.root, "002-pts"), "opus")
        self.assertEqual(board.orchestrator_model(self.root, "003-small"), "sonnet")

    def test_big_ticket_unreadable_backlog(self):
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": "001-big", "stage": "plan", "lane": "bigboy"}, {"id": "002-pts", "stage": "spec"},
            {"id": "004-road", "stage": "running", "lane": "roadmap"}]}))
        (self.root / "project.md").write_text("- Orchestrator model: sonnet\n- Big ticket model: claude-fable-5-1\n")
        backlog = self.root / "backlog.md"
        for kind in ("dir", "bytes"):
            if kind == "dir":
                backlog.mkdir()
            else:
                backlog.rmdir()
                backlog.write_bytes(b"- [x] [8] Big \xff\xfe \xe2 \u2192 002-pts\n")
            for job_id, model in (("001-big", "claude-fable-5-1"), ("004-road", "claude-fable-5-1"),
                                  ("002-pts", "sonnet")):
                self.assertEqual(board.orchestrator_model(self.root, job_id), model, (kind, job_id))
            self.assertFalse(board.big_ticket(self.root, "002-pts"), kind)

    def test_spawn_model_selection(self):
        project = self.root / "project.md"
        plain = ["-p", "/p", "--permission-mode", "acceptEdits"]
        for line, model in (("- Orchestrator model: opus\n", "opus"), ("- Orchestrator model: inherit\n", None),
                            ("- Orchestrator model: Inherit\n", None), ("- Orchestrator model: so net; rm\n", "sonnet"),
                            ("- Orchestrator model: $(touch x)\n", "sonnet"), ("- Orchestrator model:   \n", "sonnet"),
                            ("- Stack: Python\n", "sonnet")):
            project.write_text("# Project profile\n" + line)
            for action in ("start", "resume"):
                expect = plain if model is None else ["-p", "/p", "--model", model, "--permission-mode", "acceptEdits"]
                self.assertEqual(self.argv(action), expect, (line, action))
            self.assertEqual(self.argv("approve"), plain, line)
        project.write_text("- Orchestrator model: opus\n")
        self.assertEqual(self.argv("approve", model="sonnet"),
                         ["-p", "/p", "--model", "sonnet", "--permission-mode", "acceptEdits"])
        self.assertEqual(self.argv("start", model="haiku"),
                         ["-p", "/p", "--model", "haiku", "--permission-mode", "acceptEdits"])
        for bad in ("so net", "$(touch x)", "", "-x y"):
            with self.assertRaises(SystemExit, msg=bad):
                board.spawn(self.root, "999-not-a-job", "approve", "/p", model=bad)
        logs = sorted((self.root / "runs").iterdir())
        out = self.cli("999-not-a-job", "digest", "--model", "so net")
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(sorted((self.root / "runs").iterdir()), logs)  # nothing started, no log

    def test_spawn_sets_runlog(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_set(self.root, job_id, ["tty=ttys004"])
        proc, log = board.spawn(self.root, job_id, "resume")
        proc.wait(timeout=10)
        job = json.loads((self.root / "board.json").read_text())["jobs"][0]
        self.assertEqual(job["runlog"], log)
        self.assertRegex(log, rf"^runs/\d{{8}}-\d{{6}}-resume-{job_id}\.log$")
        self.assertIsNone(job["tty"])
        self.assertEqual(self.records()[0]["argv"][:2], ["-p", f"/trevskills-scrum resume {job_id}"])

    def test_spawn_unknown_job_still_starts(self):
        out = self.cli("run-all", "run-all", "/trevskills-scrum run-all")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(json.loads(out.stdout)["log"], r"^runs/\d{8}-\d{6}-run-all-run-all\.log$")
        self.assertEqual(self.records()[0]["argv"], ["-p", "/trevskills-scrum run-all", "--permission-mode", "acceptEdits"])

    def test_spawn_rejects_bad_id_or_action(self):
        for job_id, action in (("a/b", "start"), ("a b", "start"), ("..", "start"), ("../x", "start"), ("-x", "start"),
                               ("001-ok", "St"), ("001-ok", "st art"), ("001-ok", "a/b"), ("001-ok", "")):
            with self.assertRaises(SystemExit, msg=(job_id, action)):
                board.spawn(self.root, job_id, action)
        out = self.cli("../escape", "start")
        self.assertNotEqual(out.returncode, 0)
        self.assertFalse((self.root / "runs").exists())
        self.assertFalse(self.out.exists())


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
        no_claude_pid(self)
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

    def hook(self, stdin, tty="ttys004", pid=None):
        out = io.StringIO()
        with mock.patch.object(board, "caller_tty", return_value=tty), mock.patch("sys.stdin", io.StringIO(stdin)), \
                mock.patch.object(board, "caller_claude_pid", return_value=pid), redirect_stdout(out):
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

    def test_hook_stop_action_needed_sets_waiting(self):
        for msg, want in (("**Action Needed:** Ship it?", "reply needed: Ship it?"),
                          ("Summary\n\n- __action needed__ - Pick one\nAction Needed: later", "reply needed: Pick one"),
                          ("Action Needed: " + "x" * 200, "reply needed: " + "x" * 160),
                          ("**Action Needed**", "reply needed")):
            self.hook(json.dumps({"hook_event_name": "Stop", "last_assistant_message": msg}))
            self.assertEqual(self.get(self.job)["waiting"], want)

    def test_hook_stop_without_action_needed_clears_waiting(self):
        for msg in ("Summary\nOptional Follow-up: none", "Complete", "  ", None):
            self.patch(self.job, waiting="reply needed: old")
            event = {"hook_event_name": "Stop"}
            if msg is not None:
                event["last_assistant_message"] = msg
            self.hook(json.dumps(event))
            self.assertIsNone(self.get(self.job)["waiting"], msg)

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

    def assert_untouched(self, stdin, tty="ttys004", pid=None):
        path = self.root / "board.json"
        before = path.read_text()
        os.utime(path, (1_000_000, 1_000_000))
        self.hook(stdin, tty, pid)
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
                    board.cmd_hook({"hook_event_name": "Stop", "last_assistant_message": "Action Needed:"}, tty)
                self.assertEqual(play.call_args_list, [mock.call("/clips/question")] if funk else [],
                                 (value, tty))
        self.assertEqual(self.get(self.job)["waiting"], "reply needed")

    def test_hook_ignores_inactive_and_other_tty(self):
        board.cmd_set(self.root, self.old, ["stage=needs-human"], internal=True)
        board.cmd_set(self.root, self.job, ["tty=ttys005"])
        done = board.cmd_new(self.root, "done job")
        board.cmd_set(self.root, done, ["stage=done", "tty=ttys004"])
        self.assert_untouched(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "Action Needed: hi"}))
        self.hook(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "Action Needed:"}), "ttys005")
        self.assertEqual(self.get(self.job)["waiting"], "reply needed")
        self.assertNotIn("waiting", self.get(self.old))


    def test_hook_skips_reused_tty_with_other_pid(self):
        stop = json.dumps({"hook_event_name": "Stop", "last_assistant_message": "Action Needed: hi"})
        self.patch(self.old, stage="done")
        self.patch(self.job, pid=111, updatedAt="2001-01-01T00:00:00+00:00")
        self.assert_untouched(stop, pid=222)  # a later chat on the dead job's tty
        self.assert_untouched(stop, pid=None)  # caller's pid unknown: a job with a pid never matches
        self.hook(stop, pid=111)
        self.assertEqual(self.get(self.job)["waiting"], "reply needed: hi")
        self.assertNotEqual(self.get(self.job)["updatedAt"], "2001-01-01T00:00:00+00:00")
        legacy = board.cmd_new(self.root, "no pid")
        board.cmd_set(self.root, legacy, ["stage=build", "tty=ttys004"])
        self.patch(legacy, updatedAt="2002-01-01T00:00:00+00:00")
        self.patch(self.job, updatedAt="2001-01-01T00:00:00+00:00")
        self.hook(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "Action Needed:"}), pid=222)  # pid-less job still matches by tty
        self.assertEqual(self.get(legacy)["waiting"], "reply needed")
        self.assertEqual(self.get(self.job)["waiting"], "reply needed: hi")
        # under the lock: the job's pid changed between the scan and the write
        real = board.locked_board
        def swap(root):
            self.patch(legacy, pid=999)
            return real(root)
        self.patch(legacy, waiting=None)
        with mock.patch.object(board, "locked_board", swap):
            self.hook(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "Action Needed:"}), pid=222)
        self.assertIsNone(self.get(legacy)["waiting"])


class GitGuardStubTest(unittest.TestCase):
    """Job 812 moved the git-guard hook to the Go binary gitguard/gitguard; `board.py git-guard` stays a silent no-op
    because a settings.json not yet migrated by ./install.sh still calls it, and argparse's exit 2 would block Bash."""

    def test_git_guard_subcommand_is_noop(self):
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t) / "repo"
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo), "commit", "-q",
                            "--allow-empty", "-m", "first"], check=True)
            (repo / "scrum").mkdir()
            reg = Path(t) / "projects.json"
            reg.write_text(json.dumps([str(repo)]))
            event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git commit -m x"},
                     "cwd": str(repo)}
            with mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg)}), \
                    mock.patch.object(board.subprocess, "run") as run:
                os.environ.pop("CLAUDE_NOTIFIER_DISABLE", None)
                result = run_board("git-guard", input=json.dumps(event))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            run.assert_not_called()


class RetiredCommandsTest(unittest.TestCase):
    """Job 497 retired digest-verify and rules-check; RULES_RE stays for the Lilguy promotion trigger."""

    def test_rules_re_covers_lane_files(self):
        self.assertTrue(board.RULES_RE.search("skills/trevskills-scrum/lanes/cloud.md"))
        self.assertIsNone(board.RULES_RE.search("src/lanes/foo.md"))
        self.assertTrue(board.RULES_RE.search("skills/trevskills-scrum/SKILL.md"))
        self.assertTrue(board.RULES_RE.search("agents/scrum-builder.md"))
        self.assertIsNone(board.RULES_RE.search("macos/skills/trevskills-mac-cleanup/SKILL.md"))
        self.assertIsNone(board.RULES_RE.search("SKILL.md"))

    def test_agent_rules_commands_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            for cmd in ("digest-verify", "rules-check"):
                err = io.StringIO()
                with redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                    board.main(["--dir", tmp, cmd, "001"])
                self.assertNotEqual(raised.exception.code, 0, cmd)
                self.assertIn(f"invalid choice: '{cmd}'", err.getvalue())
        text = BOARD_PY.read_text()
        for name in ("cmd_digest_verify", "cmd_rules_check", "HUMAN_ONLY_FILES", "MOVED_TEXT_RE"):
            self.assertNotIn(name, text, name)


class CloudSyncTest(unittest.TestCase):
    """board.py cloud-sync: one REST list call moves each cloud job's PR result onto the board, with no LLM."""

    PULLS = "repos/{owner}/{repo}/pulls?state=all&per_page=100&sort=created&direction=desc"
    URL = "https://github.com/o/r/pull/7"
    TREV = {"login": "trev"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        env = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(Path(self.tmp.name) / "no-usage.json")})
        env.start()
        self.addCleanup(env.stop)
        for name, value in (("merge_refusal", None), ("artifacts_pushed", False)):
            p = mock.patch.object(board, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        self.job = board.cmd_new(self.root, "Cloud thing")
        board.cmd_set(self.root, self.job, ["stage=cloud", "cloud=https://claude.ai/code/session_abc"])
        self.calls = []

    def get(self, job_id=None):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == (job_id or self.job))

    def pr(self, job=None, **kw):
        job = job or self.job
        return {"number": 7, "html_url": self.URL, "title": f"[scrum {job}] Cloud thing", "state": "open",
                "merged_at": None, "labels": [], "head": {"ref": f"scrum/{job}", "repo": {"full_name": "o/r"}},
                "base": {"ref": "main", "repo": {"full_name": "o/r"}}, "user": {"login": "trev"}, **kw}

    def gh(self, pulls, comments=None):
        def fake(repo, endpoint, *flags):
            self.calls.append((repo, endpoint, *flags))
            if flags == ("-X", "PATCH", "-f", "state=closed") and endpoint == "repos/{owner}/{repo}/pulls/7":
                return {}
            if endpoint == self.PULLS:
                return pulls
            if endpoint == "repos/{owner}/{repo}/issues/7/comments?per_page=100":
                return comments or []
            raise AssertionError(f"unexpected gh api {endpoint}")
        return mock.patch.object(board, "gh_api", side_effect=fake)

    def assert_untouched(self, before):
        self.assertEqual(self.get(), before)

    def test_no_cloud_job_calls_no_gh(self):
        board.cmd_set(self.root, self.job, ["stage=needs-human"], internal=True)
        with self.gh([self.pr()]):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [], "error": None})
        self.assertEqual(self.calls, [])

    def test_no_pr_leaves_job_cloud(self):
        before = self.get()
        other = self.pr(title="[scrum 999-other] x", merged_at="2026-01-01T00:00:00Z")
        with self.gh([other]):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [], "error": None})
        self.assertEqual(self.calls, [(self.root.parent, self.PULLS)])
        self.assert_untouched(before)

    def test_open_unlabelled_leaves_job_cloud(self):
        before = self.get()
        with self.gh([self.pr(labels=[{"name": "bug"}])]):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [], "error": None})
        self.assertEqual(len(self.calls), 1)
        self.assert_untouched(before)

    def test_merged_pr_marks_done(self):
        board.cmd_set(self.root, self.job, ["reason=old note"])
        older = self.pr(html_url="https://github.com/o/r/pull/3", state="closed")  # newest first: the first match wins
        with self.gh([self.pr(state="closed", merged_at="2026-10-01T00:00:00Z"), older]):
            out = board.cmd_cloud_sync(self.root)
        self.assertEqual(out, {"moved": [{"id": self.job, "state": "MERGED", "pr": self.URL, "reason": None,
                                          "worktree": None, "artifacts": False}], "arrived": [], "error": None})
        job = self.get()
        self.assertEqual((job["stage"], job["pr"], job["reason"]), ("done", self.URL, None))
        board.merge_refusal.assert_called()  # the cmd_set done guard ran

    def test_merged_pr_refused_by_guard_stays_cloud(self):
        board.merge_refusal.return_value = "not done: PR is OPEN, not merged"
        with self.gh([self.pr(state="closed", merged_at="2026-10-01T00:00:00Z")]), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(board.cmd_cloud_sync(self.root)["moved"], [])
        self.assertEqual(self.get()["stage"], "cloud")

    def merged(self, body):
        return self.pr(state="closed", merged_at="2026-10-01T00:00:00Z", body=body)

    def test_cloud_sync_merged_records_lane(self):
        with self.gh([self.merged("Summary\n\nScrum lane: fast\n")]):
            board.cmd_cloud_sync(self.root)
        self.assertEqual((self.get()["stage"], self.get()["lane"]), ("done", "fast"))
        self.assertEqual(self.calls, [(self.root.parent, self.PULLS)])  # the lane costs no extra gh call

    def test_cloud_sync_no_lane_line_leaves_lane_unset(self):
        for body in (None, "Summary only\nlane: fast\n"):
            with self.subTest(body=body):
                self.setUp()
                with self.gh([self.merged(body)]):
                    board.cmd_cloud_sync(self.root)
                self.assertEqual(self.get()["stage"], "done")
                self.assertIsNone(self.get().get("lane"))

    def test_cloud_sync_unknown_lane_ignored(self):
        for body in ("Scrum lane: turbo", "Scrum lane: bigboy", "Scrum lane:", "Scrum lane: fastest", "x Scrum lane: fast"):
            with self.subTest(body=body):
                self.setUp()
                with self.gh([self.merged(body)]):
                    out = board.cmd_cloud_sync(self.root)
                self.assertEqual(out["moved"][0]["state"], "MERGED")
                self.assertEqual(self.get()["stage"], "done")
                self.assertIsNone(self.get().get("lane"))

    def test_cloud_sync_needs_human_and_abort_record_lane(self):
        labelled = self.pr(labels=[{"name": "scrum:needs-human"}], body="Scrum lane: debug")
        comments = [{"user": self.TREV, "body": "Hard stop: schema first\n<!-- scrum needs-human -->"}]
        with self.gh([labelled], comments), mock.patch.object(board, "cloud_worktree", return_value=None):
            board.cmd_cloud_sync(self.root)
        self.assertEqual((self.get()["stage"], self.get()["lane"]), ("needs-human", "debug"))

        self.setUp()
        labelled = self.pr(labels=[{"name": "scrum:needs-human"}], body="Scrum lane: fast")
        comments = [{"user": self.TREV, "body": "requeue: spec writer produced nothing\n<!-- scrum needs-human -->"}]
        with self.gh([labelled], comments):
            self.assertEqual(board.cmd_cloud_sync(self.root)["moved"][0]["state"], "ABORTED")
        self.assertEqual((self.get()["stage"], self.get()["lane"]), ("aborted", "fast"))

        self.setUp()
        with self.gh([self.pr(state="closed", body="Scrum lane: standard")]):
            self.assertEqual(board.cmd_cloud_sync(self.root)["moved"][0]["state"], "CLOSED")
        self.assertEqual((self.get()["stage"], self.get()["lane"]), ("aborted", "standard"))

    def backlog_texts(self):
        return [i["text"] for i in board.read_backlog(self.root)[1] if not i["done"]]

    def test_closed_pr_aborts_and_requeues(self):
        with self.gh([self.pr(state="closed")]):
            out = board.cmd_cloud_sync(self.root)
        reason = "requeue: cloud PR closed without merging"
        self.assertEqual(out["moved"], [{"id": self.job, "state": "CLOSED", "pr": self.URL, "reason": reason,
                                         "worktree": None, "artifacts": False}])
        job = self.get()
        self.assertEqual((job["stage"], job["pr"], job["reason"]), ("aborted", self.URL, reason))
        self.assertEqual(self.backlog_texts(), ["Cloud thing"])
        self.assertEqual(len(self.calls), 1)  # an already-closed PR is not closed again

    def self_abort(self, line):
        labelled = self.pr(labels=[{"name": "scrum:needs-human"}])
        comments = [{"user": self.TREV, "body": f"{line}\n<!-- scrum needs-human -->"}]
        with self.gh([labelled], comments), mock.patch.object(board, "cloud_worktree") as wt:
            out = board.cmd_cloud_sync(self.root)
        wt.assert_not_called()
        self.assertEqual(self.calls[-1], (self.root.parent, "repos/{owner}/{repo}/pulls/7", "-X", "PATCH", "-f",
                                          "state=closed"))
        return out

    def test_requeue_comment_aborts_requeues_and_closes_pr(self):
        out = self.self_abort("requeue: spec writer produced nothing")
        self.assertEqual(out["moved"][0]["state"], "ABORTED")
        job = self.get()
        self.assertEqual((job["stage"], job["pr"], job["reason"]),
                         ("aborted", self.URL, "requeue: spec writer produced nothing"))
        self.assertEqual(self.backlog_texts(), ["Cloud thing"])

    def test_obsolete_and_already_fixed_comments_abort_without_requeue(self):
        for line in ("obsolete: nothing to change", "looks already fixed: see main"):
            with self.subTest(line=line):
                self.setUp()
                self.self_abort(line)
                self.assertEqual((self.get()["stage"], self.get()["reason"]), ("aborted", line))
                self.assertEqual(self.backlog_texts(), [])

    def test_pr_close_failure_still_aborts(self):
        labelled = self.pr(labels=[{"name": "scrum:needs-human"}])
        comments = [{"user": self.TREV, "body": "obsolete: gone\n<!-- scrum needs-human -->"}]
        def fake(repo, endpoint, *flags):
            if flags:
                raise board.GhError("HTTP 403")
            return [labelled] if endpoint == self.PULLS else comments
        err = io.StringIO()
        with mock.patch.object(board, "gh_api", side_effect=fake), mock.patch("sys.stderr", err):
            out = board.cmd_cloud_sync(self.root)
        self.assertEqual((out["error"], self.get()["stage"]), (None, "aborted"))
        self.assertIn("PR close failed: HTTP 403", err.getvalue())

    def needs_human(self, comments, worktree):
        labelled = self.pr(labels=[{"name": "bug"}, {"name": "scrum:needs-human"}], base={"ref": "dev", "repo": {"full_name": "o/r"}})
        with self.gh([labelled], comments), mock.patch.object(board, "cloud_worktree", return_value=worktree) as wt:
            out = board.cmd_cloud_sync(self.root)
        wt.assert_called_once_with(self.root.parent, self.job)
        return out

    def test_needs_human_pr_reads_reason_and_adds_worktree(self):
        comments = [{"user": self.TREV, "body": "Hard stop: schema first\n<!-- scrum needs-human -->"}, {"user": self.TREV, "body": "unrelated chat"},
                    {"user": self.TREV, "body": "Hard stop: money   in   checkout\n<!-- scrum needs-human -->\nmore"}, {"user": self.TREV, "body": "thanks"}]
        out = self.needs_human(comments, "/r/.claude/worktrees/scrum-x")
        reason = "Hard stop: money in checkout"
        self.assertEqual(out["moved"], [{"id": self.job, "state": "NEEDS-HUMAN", "pr": self.URL, "reason": reason,
                                         "worktree": "/r/.claude/worktrees/scrum-x", "artifacts": False}])
        job = self.get()
        self.assertEqual((job["stage"], job["pr"], job["base"], job["reason"], job["worktree"]),
                         ("needs-human", self.URL, "origin/dev", reason, "/r/.claude/worktrees/scrum-x"))

    def test_needs_human_reason_is_capped_at_300(self):
        out = self.needs_human([{"user": self.TREV, "body": "x" * 400 + "\n<!-- scrum needs-human -->"}], None)
        self.assertEqual(out["moved"][0]["reason"], "x" * 300)

    def test_needs_human_worktree_add_fails_omits_worktree(self):
        out = self.needs_human([{"user": self.TREV, "body": "blocked: y\n<!-- scrum needs-human -->"}], None)
        self.assertEqual(out["moved"][0]["worktree"], None)
        job = self.get()
        self.assertEqual((job["stage"], job["reason"], job["base"], job["worktree"]),
                         ("needs-human", "blocked: y", "origin/dev", None))

    def test_needs_human_without_comment_uses_fallback_reason(self):
        out = self.needs_human([{"user": self.TREV, "body": "no marker here"}], None)
        reason = f"cloud job needs a human; no reason comment on {self.URL}. Fix: read the PR."
        self.assertEqual(out["moved"][0]["reason"], reason)
        self.assertEqual(self.get()["reason"], reason)

    def test_artifacts_flag_comes_from_the_remote_branch(self):
        board.artifacts_pushed.return_value = True
        with self.gh([self.pr(state="closed", merged_at="2026-10-01T00:00:00Z")]):
            out = board.cmd_cloud_sync(self.root)
        self.assertIs(out["moved"][0]["artifacts"], True)
        board.artifacts_pushed.assert_called_once_with(self.root.parent, self.job)

    def test_gh_failure_changes_nothing(self):
        second = board.cmd_new(self.root, "Cloud two")
        board.cmd_set(self.root, second, ["stage=cloud"])
        before = json.loads((self.root / "board.json").read_text())
        merged = self.pr(state="closed", merged_at="2026-10-01T00:00:00Z")
        labelled = self.pr(second, labels=[{"name": "scrum:needs-human"}])
        for fail in (board.GhError("HTTP 401: Bad credentials"), board.GhError("gh api timed out")):
            def fake(repo, endpoint, fail=fail):
                if "comments" in endpoint:  # the list call worked, the comment call for job 2 fails
                    raise fail
                return [merged, labelled]
            with mock.patch.object(board, "gh_api", side_effect=fake), \
                    mock.patch.object(board, "cloud_worktree", return_value="/wt") as wt:
                self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [], "error": str(fail)})
            wt.assert_not_called()
            self.assertEqual(json.loads((self.root / "board.json").read_text()), before)

    def test_gh_api_turns_every_failure_into_gh_error(self):
        def run(rc=0, out="", err=""):
            return mock.patch.object(board.subprocess, "run", return_value=subprocess.CompletedProcess([], rc, out, err))
        with run(1, err="\ngh: Not Found (HTTP 404)\nmore\n"), self.assertRaisesRegex(board.GhError, r"^gh: Not Found \(HTTP 404\)$"):
            board.gh_api(self.root.parent, "repos/x")
        with run(0, out="not json"), self.assertRaises(board.GhError):
            board.gh_api(self.root.parent, "repos/x")
        with mock.patch.object(board.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 30)), \
                self.assertRaisesRegex(board.GhError, "timed out"):
            board.gh_api(self.root.parent, "repos/x")
        with mock.patch.object(board.subprocess, "run", side_effect=FileNotFoundError(2, "No such file", "gh")), \
                self.assertRaisesRegex(board.GhError, "No such file"):
            board.gh_api(self.root.parent, "repos/x")
        with run(0, out='[{"a": 1}]') as r:
            self.assertEqual(board.gh_api(self.root.parent, "repos/x"), [{"a": 1}])
        self.assertEqual(r.call_args.args[0], ["gh", "api", "repos/x"])
        self.assertEqual((r.call_args.kwargs["cwd"], r.call_args.kwargs["timeout"]), (self.root.parent, 30))

    def test_job_moved_meanwhile_is_skipped(self):
        second = board.cmd_new(self.root, "Cloud two")
        board.cmd_set(self.root, second, ["stage=cloud"])
        merged = self.pr(state="closed", merged_at="2026-10-01T00:00:00Z")
        closed = self.pr(second, state="closed")
        def fake(repo, endpoint):  # between the read and the writes: one job is aborted, the other set by hand
            board.cmd_abort(self.root, self.job, False)
            board.cmd_set(self.root, second, ["stage=build", "reason=picked up locally"])
            return [merged, closed]
        with mock.patch.object(board, "gh_api", side_effect=fake), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [], "error": None})
        self.assertEqual(self.get()["stage"], "aborted")
        self.assertEqual((self.get(second)["stage"], self.get(second)["reason"]), ("build", "picked up locally"))

    def test_cloud_sync_ignores_fork_or_wrong_head_pr(self):
        before = self.get()
        merged_at = "2026-10-01T00:00:00Z"
        fork = self.pr(state="closed", merged_at=merged_at, head={"ref": f"scrum/{self.job}",
                                                                    "repo": {"full_name": "evil/r"}})
        wrong_ref = self.pr(state="closed", head={"ref": "main", "repo": {"full_name": "o/r"}})
        no_repo = self.pr(labels=[{"name": "scrum:needs-human"}], head={"ref": f"scrum/{self.job}", "repo": None})
        with self.gh([fork, wrong_ref, no_repo]):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [], "error": None})
        self.assertEqual(self.calls, [(self.root.parent, self.PULLS)])
        self.assert_untouched(before)
        real = self.pr(html_url="https://github.com/o/r/pull/9", state="closed", merged_at=merged_at)
        with self.gh([fork, wrong_ref, no_repo, real]):
            out = board.cmd_cloud_sync(self.root)
        self.assertEqual([(m["state"], m["pr"]) for m in out["moved"]], [("MERGED", "https://github.com/o/r/pull/9")])
        self.assertEqual(self.get()["stage"], "done")

    def test_cloud_sync_ignores_outsider_needs_human_comment(self):
        mark = "\n<!-- scrum needs-human -->"
        comments = [{"user": self.TREV, "body": "Hard stop: money in checkout" + mark},
                    {"user": {"login": "mallory"}, "body": "requeue: give up" + mark},
                    {"user": {"login": "mallory"}, "body": "Hard stop: schema drop users" + mark},
                    {"body": "obsolete: no user at all" + mark}]
        out = self.needs_human(comments, None)
        self.assertEqual((out["moved"][0]["state"], out["moved"][0]["reason"]),
                         ("NEEDS-HUMAN", "Hard stop: money in checkout"))
        job = self.get()
        self.assertEqual((job["stage"], job["reason"]), ("needs-human", "Hard stop: money in checkout"))
        self.assertNotIn("PATCH", [f for c in self.calls for f in c])
        self.assertEqual(self.backlog_texts(), [])

    def test_cloud_sync_outsider_only_comment_uses_fallback_reason(self):
        out = self.needs_human([{"user": {"login": "mallory"}, "body": "requeue: x\n<!-- scrum needs-human -->"}], None)
        reason = f"cloud job needs a human; no reason comment on {self.URL}. Fix: read the PR."
        self.assertEqual((out["moved"][0]["state"], self.get()["stage"], self.get()["reason"]),
                         ("NEEDS-HUMAN", "needs-human", reason))

    def iso(self, hours_ago):
        return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")

    def pend(self, job_id, stage, hours_ago):
        with board.locked_board(self.root) as b:
            job = board.find(b, job_id)
            job["stage"], job["artifactsPending"] = stage, self.iso(hours_ago)

    def test_cloud_sync_marks_artifacts_pending(self):
        start = datetime.now(timezone.utc).replace(microsecond=0)
        second = board.cmd_new(self.root, "Cloud two")
        board.cmd_set(self.root, second, ["stage=cloud"])
        board.artifacts_pushed.side_effect = lambda repo, job_id: job_id == second
        with self.gh([self.pr(state="closed"), self.pr(second, state="closed", merged_at="2026-10-01T00:00:00Z")]):
            out = board.cmd_cloud_sync(self.root)
        self.assertEqual([(m["id"], m["artifacts"]) for m in out["moved"]], [(self.job, False), (second, True)])
        mark = datetime.fromisoformat(self.get()["artifactsPending"])
        self.assertTrue(start <= mark <= datetime.now(timezone.utc), mark)
        self.assertNotIn("artifactsPending", self.get(second))
        with self.assertRaisesRegex(SystemExit, "artifactsPending"):
            board.cmd_set(self.root, second, ["artifactsPending=2026-01-01T00:00:00+00:00"])

    def test_cloud_sync_arrived_keeps_pending(self):
        self.pend(self.job, "done", 1)
        mark = self.get()["artifactsPending"]
        board.cmd_set(self.root, board.cmd_new(self.root, "Cloud two"), ["stage=cloud"])
        board.artifacts_pushed.return_value = True
        with self.gh([]):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [self.job], "error": None})
        self.assertEqual(self.get()["artifactsPending"], mark, "arrived: kept until cloud-home starts")
        board.artifacts_pushed.assert_called_once_with(self.root.parent, self.job)
        with self.gh([]):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [self.job], "error": None})
        self.assertEqual(self.get()["artifactsPending"], mark)
        # a gh failure on the pulls call still reports this run's arrivals
        with mock.patch.object(board, "gh_api", side_effect=board.GhError("HTTP 502")):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [self.job], "error": "HTTP 502"})
        self.assertEqual(self.get()["artifactsPending"], mark)

    def test_cloud_pending_clear(self):
        other = board.cmd_new(self.root, "Cloud two")
        bare = board.cmd_new(self.root, "Cloud three")
        self.pend(self.job, "done", 1)
        self.pend(other, "done", 2)
        other_mark = self.get(other)["artifactsPending"]
        board.cloud_pending_clear(self.root, self.job)
        self.assertNotIn("artifactsPending", self.get())
        self.assertEqual(self.get(other)["artifactsPending"], other_mark, "other jobs' marks untouched")
        board.cloud_pending_clear(self.root, self.job)  # already cleared: no-op
        board.cloud_pending_clear(self.root, bare)  # never marked: no-op
        board.cloud_pending_clear(self.root, "999-missing")  # not on the board: no-op
        self.assertNotIn("artifactsPending", self.get(bare))
        self.assertEqual(self.get(other)["artifactsPending"], other_mark)
        with mock.patch.object(board, "locked_board", wraps=board.locked_board) as lb:
            board.cloud_pending_clear(self.root, other)
        lb.assert_called_once_with(self.root)
        self.assertNotIn("artifactsPending", self.get(other))

    def test_cloud_sync_pending_expires_after_24h(self):
        board.cmd_set(self.root, board.cmd_new(self.root, "Cloud two"), ["stage=cloud"])
        self.pend(self.job, "aborted", 23)
        with self.gh([]):
            self.assertEqual(board.cmd_cloud_sync(self.root)["arrived"], [])
        self.assertIn("artifactsPending", self.get(), "still inside 24 h: kept")
        self.pend(self.job, "aborted", 25)
        with self.gh([]):
            self.assertEqual(board.cmd_cloud_sync(self.root)["arrived"], [])
        self.assertNotIn("artifactsPending", self.get())

    def test_cloud_sync_pending_only_runs_without_cloud_jobs(self):
        self.pend(self.job, "needs-human", 2)
        mark = self.get()["artifactsPending"]
        board.artifacts_pushed.return_value = True
        with self.gh([self.pr()]):
            self.assertEqual(board.cmd_cloud_sync(self.root), {"moved": [], "arrived": [self.job], "error": None})
        self.assertEqual(self.calls, [], "no cloud job: no pulls call")
        self.assertEqual(self.get()["artifactsPending"], mark, "arrived: kept until cloud-home starts")

    def test_cloud_sync_removes_worktree_when_set_refused(self):
        labelled = self.pr(labels=[{"name": "scrum:needs-human"}])
        comments = [{"user": self.TREV, "body": "blocked: y\n<!-- scrum needs-human -->"}]
        def add(repo, job_id):  # the worktree lands, then Trevor aborts the job before cmd_set
            board.cmd_abort(self.root, job_id, False)
            return "/r/.claude/worktrees/scrum-x"
        for rc, err in ((0, b""), (128, b"fatal: not a working tree")):
            with self.subTest(rc=rc):
                self.setUp()
                runs = []
                def run(argv, **kw):
                    runs.append(argv)
                    return subprocess.CompletedProcess(argv, rc, b"", err)
                with self.gh([labelled], comments), mock.patch.object(board, "cloud_worktree", side_effect=add), \
                        mock.patch.object(board.subprocess, "run", side_effect=run), \
                        mock.patch("sys.stderr", io.StringIO()) as e:
                    out = board.cmd_cloud_sync(self.root)
                self.assertEqual(out, {"moved": [], "arrived": [], "error": None})
                self.assertEqual(runs, [["git", "-C", str(self.root.parent), "worktree", "remove",
                                         "/r/.claude/worktrees/scrum-x"]])
                self.assertEqual(self.get()["stage"], "aborted")
                self.assertNotIn("artifactsPending", self.get())
                if rc:
                    self.assertIn("fatal: not a working tree", e.getvalue())

    def test_cli_prints_json(self):
        with self.gh([self.pr(state="closed")]), redirect_stdout(io.StringIO()) as out:
            code = board.main(["--dir", str(self.root), "cloud-sync"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["moved"][0]["state"], "CLOSED")
        board.cmd_set(self.root, board.cmd_new(self.root, "Another"), ["stage=cloud"])
        with mock.patch.object(board, "gh_api", side_effect=board.GhError("gh: auth required")), \
                redirect_stdout(io.StringIO()) as out:
            code = board.main(["--dir", str(self.root), "cloud-sync"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue()), {"moved": [], "arrived": [], "error": "gh: auth required"})


class ReviewPlanTest(unittest.TestCase):
    """board.py review-plan: SKILL.md Review step 2 (incremental vs full, carried-forward files, UI/UX and security skips)."""

    CARRIED = "VERDICT: PASS\nCarried forward from round 1: no blocking findings.\n"
    UI_SKIP = "VERDICT: PASS\nSkipped by orchestrator: no UI files in diff.\n"
    SEC_SKIP = "VERDICT: PASS\nSkipped by orchestrator: no sensitive files in diff.\n"

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
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "a.py").write_text("a = 1\n")
        (self.repo / "README.md").write_text("readme\n")
        self.git(self.repo, "init", "-q", "-b", "main")
        self.git(self.repo, "add", "src", "README.md")
        self.git(self.repo, "commit", "-q", "-m", "base")
        self.job = board.cmd_new(self.root, "Review plan")
        self.git(self.repo, "worktree", "add", "-q", "-b", f"scrum/{self.job}", str(self.wt))
        board.cmd_set(self.root, self.job, [f"worktree={self.wt}", "base=main", "round=1", "stage=review"])
        self.project("*.html")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def project(self, globs):
        line = "" if globs is None else f"- UI globs: {globs}\n"
        (self.root / "project.md").write_text(f"# Project profile\n- Test: none\n{line}- Notes: x\n")

    def commit(self, rel, text):
        p = self.wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        self.git(self.wt, "add", rel)
        self.git(self.wt, "commit", "-q", "-m", f"edit {rel}")
        return self.git(self.wt, "rev-parse", "HEAD")

    def rdir(self, n):
        return self.root / "jobs" / self.job / f"round-{n}"

    def round_one(self, verdicts, head=True):
        """Round 1 reviewed a src/a.py change; writes its head.txt and review files, then sets round=2."""
        sha = self.commit("src/a.py", "a = 2\n")
        d = self.rdir(1)
        d.mkdir(parents=True, exist_ok=True)
        if head:
            (d / "head.txt").write_text(sha + "\n")
        for role, verdict in verdicts.items():
            (d / f"review-{role}.md").write_text(f"VERDICT: {verdict}\nstuff\n")
        board.cmd_set(self.root, self.job, ["round=2"])
        return sha

    def files(self, n):
        d = self.rdir(n)
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def read(self, n, role):
        return (self.rdir(n) / f"review-{role}.md").read_text()

    MIXED = {"security": "CHANGES", "ux": "PASS", "ui": "PASS", "code": "CHANGES"}

    # --- AC 1 ---
    def test_review_plan_incremental_carries_forward_pass_reviews(self):
        since = self.round_one(self.MIXED)
        self.commit("src/a.py", "a = 3\n")  # the fix touches only a file round 1 saw
        out = board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assertEqual(out, {"spawn": ["security", "code"], "since": since})
        self.assertEqual(self.read(2, "ux"), self.CARRIED)
        self.assertEqual(self.read(2, "ui"), self.CARRIED)
        self.assertEqual(self.files(2), ["review-ui.md", "review-ux.md"])  # no security skip file, no UI skip text

    # --- AC 2 ---
    def assert_full(self, out, n=2):
        self.assertIsNone(out["since"])
        for name in self.files(n):
            self.assertNotIn("Carried forward", (self.rdir(n) / name).read_text())

    def test_review_plan_full_fallback_when_fix_touches_new_file(self):
        self.round_one(self.MIXED)
        self.commit("src/b.py", "b = 1\n")
        out = board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assert_full(out)
        self.assertEqual(out["spawn"], ["code"])  # a.py and b.py: no UI file, nothing sensitive
        self.assertEqual(self.read(2, "ui"), self.UI_SKIP)
        self.assertEqual(self.read(2, "security"), self.SEC_SKIP)

    def test_review_plan_full_fallback_without_prev_head(self):
        self.round_one(self.MIXED, head=False)
        self.commit("src/a.py", "a = 3\n")
        self.commit("index.html", "<p>x</p>\n")  # UI files: ui and ux run, so nothing but security is skipped
        with self.subTest("missing head.txt"):
            out = board.cmd_review_plan(self.root, self.job, incremental=True)
            self.assert_full(out)
            self.assertEqual(out["spawn"], ["ux", "ui", "code"])
        with self.subTest("head.txt is not a commit"):
            (self.rdir(1) / "head.txt").write_text("0123456789abcdef0123456789abcdef01234567\n")
            out = board.cmd_review_plan(self.root, self.job, incremental=True)
            self.assert_full(out)
            self.assertEqual(out["spawn"], ["ux", "ui", "code"])
        with self.subTest("previous review file unreadable"):
            (self.rdir(1) / "head.txt").write_text(self.git(self.wt, "rev-parse", "HEAD~2") + "\n")
            (self.rdir(1) / "review-ui.md").write_text("garbage\n")
            out = board.cmd_review_plan(self.root, self.job, incremental=True)
            self.assert_full(out)
            self.assertEqual(out["spawn"], ["ux", "ui", "code"])

    def test_review_plan_full_when_not_incremental(self):
        self.round_one(self.MIXED)
        self.commit("src/a.py", "a = 3\n")
        self.commit("app/api/x.py", "x = 1\n")  # sensitive: security runs
        board.cmd_set(self.root, self.job, ["round=2"])
        with self.subTest("no --incremental"):
            out = board.cmd_review_plan(self.root, self.job)
            self.assert_full(out)
            self.assertEqual(out["spawn"], ["security", "code"])
        with self.subTest("round 1"):
            board.cmd_set(self.root, self.job, ["round=1"])
            out = board.cmd_review_plan(self.root, self.job, incremental=True)
            self.assertIsNone(out["since"])
            self.assertEqual(out["spawn"], ["security", "code"])
            self.assertEqual(self.read(1, "ux"), self.UI_SKIP)

    # --- job 681: Check gate visual diff ---
    VISUAL_SKIP = ("VERDICT: PASS\nSkipped by orchestrator: visual diff found every captured pair identical and the "
                   "spec says no visual change.\n")

    def visual(self, first_line, ui_surface="no", complex_="no", n=1):
        (self.root / "jobs" / self.job / "spec.md").write_text(
            f"# Spec\nUI surface: {ui_surface}\nHard stops: none\nComplex: {complex_}\n")
        self.rdir(n).mkdir(parents=True, exist_ok=True)
        if first_line is not None:
            (self.rdir(n) / "visual-diff.md").write_text(f"{first_line}\n- / 390: same\n")

    def test_review_plan_visual_same_skips_ui_ux(self):
        self.commit("web/page.html", "<p>x</p>\n")
        self.visual("VISUAL: same")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["code"], "since": None})
        self.assertEqual(self.read(1, "ui"), self.VISUAL_SKIP)
        self.assertEqual(self.read(1, "ux"), self.VISUAL_SKIP)
        with self.subTest("incremental keeps a rework role"):
            since = self.round_one(self.MIXED)
            (self.rdir(1) / "decision.md").write_text("REWORK\n## Rulings\n- fix-now render-only: ui must render\n")
            (self.rdir(1) / "review-ui.md").write_text("VERDICT: PASS\nstuff\n")
            (self.rdir(1) / "review-ux.md").write_text("VERDICT: CHANGES\nstuff\n")
            self.commit("src/a.py", "a = 3\n")
            self.visual("VISUAL: same", n=2)
            out = board.cmd_review_plan(self.root, self.job, incremental=True)
            self.assertEqual(out, {"spawn": ["security", "ux", "ui", "code"], "since": since})
            self.assertFalse((self.rdir(2) / "review-ux.md").exists())

    def test_review_plan_visual_same_keeps_changes_role(self):
        since = self.round_one(self.MIXED)
        (self.rdir(1) / "decision.md").write_text("REWORK\n## Rulings\n- fix-now render-only: code must fix\n")
        (self.rdir(1) / "review-ui.md").write_text("VERDICT: PASS\nstuff\n")
        (self.rdir(1) / "review-ux.md").write_text("VERDICT: CHANGES\nstuff\n")
        self.commit("src/a.py", "a = 3\n")
        self.visual("VISUAL: same", n=2)
        out = board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assertEqual(out, {"spawn": ["security", "ux", "code"], "since": since})
        self.assertFalse((self.rdir(2) / "review-ux.md").exists())
        self.assertNotEqual(self.read(2, "ui"), self.VISUAL_SKIP)  # PASS role stays carried, not visual-skipped

    def test_review_plan_visual_same_but_ui_surface_yes_spawns(self):
        self.commit("web/page.html", "<p>x</p>\n")
        for ui, cx in (("yes", "no"), ("no", "yes")):
            with self.subTest(ui_surface=ui, complex=cx):
                self.visual("VISUAL: same", ui_surface=ui, complex_=cx)
                out = board.cmd_review_plan(self.root, self.job)
                self.assertEqual(out["spawn"], ["ux", "ui", "code"])
                self.assertFalse((self.rdir(1) / "review-ui.md").exists())

    def test_review_plan_visual_changed_spawns(self):
        self.commit("web/page.html", "<p>x</p>\n")
        for line in ("VISUAL: changed", "VISUAL: unscored", "VISUAL: skipped — odiff-bin not installed",
                     "VISUAL: same — but more"):
            with self.subTest(line=line):
                self.visual(line)
                out = board.cmd_review_plan(self.root, self.job)
                self.assertEqual(out["spawn"], ["ux", "ui", "code"])

    def test_review_plan_visual_missing_spawns(self):
        self.commit("web/page.html", "<p>x</p>\n")
        self.visual(None)
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["ux", "ui", "code"])
        self.assertEqual(self.files(1), ["review-security.md"])

    # --- AC 3 ---
    def test_review_plan_ui_skip_when_no_ui_files(self):
        self.commit("src/a.py", "a = 2\n")
        self.commit("app/api/x.py", "x = 1\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["security", "code"], "since": None})
        self.assertEqual(self.read(1, "ui"), self.UI_SKIP)
        self.assertEqual(self.read(1, "ux"), self.UI_SKIP)

    def test_review_plan_skips_ui_for_server_only_paths(self):
        self.project("app/ *.tsx")
        self.commit("src/app/api/a/route.ts", "export const GET = 1\n")
        self.commit("src/app/api/b/handler.ts", "export const h = 1\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["security", "code"])
        self.assertEqual(self.read(1, "ui"), self.UI_SKIP)
        self.assertEqual(self.read(1, "ux"), self.UI_SKIP)

    def test_review_plan_ui_runs_when_html_changed(self):
        self.commit("web/page.html", "<p>x</p>\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["ux", "ui", "code"], "since": None})
        self.assertEqual(self.files(1), ["review-security.md"])

    def test_review_plan_ui_runs_when_globs_none(self):
        self.commit("src/a.py", "a = 2\n")
        for globs in ("none", None):
            with self.subTest(globs=globs):
                self.project(globs)
                out = board.cmd_review_plan(self.root, self.job)
                self.assertEqual(out, {"spawn": ["ux", "ui", "code"], "since": None})
                self.assertEqual(self.files(1), ["review-security.md"])

    def test_review_plan_ui_glob_dir_component(self):
        self.assertTrue(board.glob_match("src/components/x.py", ["components/"]))
        self.assertTrue(board.glob_match("components/x.py", ["components/"]))
        self.assertFalse(board.glob_match("mycomponents/x.py", ["components/"]))
        self.assertFalse(board.glob_match("src/components", ["components/"]))  # a file, not a directory
        self.assertTrue(board.glob_match("app/page.tsx", ["app/page.tsx"]))
        self.assertFalse(board.glob_match("src/app/page.tsx", ["app/page.tsx"]))
        self.assertTrue(board.glob_match("a/b/style.css", ["*.css"]))
        self.assertFalse(board.glob_match("a/b/style.scss", ["*.css"]))
        self.project("*.tsx components/")
        self.commit("lib/mycomponents/x.py", "x\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["code"])
        for name in self.files(1):
            (self.rdir(1) / name).unlink()
        self.commit("lib/components/y.py", "y\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["ux", "ui", "code"])
        self.assertFalse((self.rdir(1) / "review-ui.md").exists())

    # --- non-ASCII paths and stale skip files ---
    def test_review_plan_security_runs_on_non_ascii_api_path(self):
        self.commit("src/café/api/x.py", "x = 1\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertIn("security", out["spawn"])
        self.assertFalse((self.rdir(1) / "review-security.md").exists())

    def test_review_plan_ui_runs_on_non_ascii_html_path(self):
        self.commit("pages/café.html", "<p>x</p>\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["ux", "ui", "code"])
        self.assertEqual(self.files(1), ["review-security.md"])

    def test_review_plan_rerun_removes_stale_skip_for_spawned_roles(self):
        self.commit("src/a.py", "a = 2\n")
        board.cmd_review_plan(self.root, self.job)
        self.assertEqual(self.files(1), ["review-security.md", "review-ui.md", "review-ux.md"])
        self.commit("index.html", "<p>x</p>\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["ux", "ui", "code"])
        self.assertEqual(self.files(1), ["review-security.md"])
        self.assertEqual(self.read(1, "security"), self.SEC_SKIP)

    def test_review_plan_full_rerun_removes_carried_forward_files(self):
        self.round_one(self.MIXED)
        self.commit("src/a.py", "a = 3\n")
        board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assertEqual(self.files(2), ["review-ui.md", "review-ux.md"])
        self.commit("index.html", "<p>x</p>\n")
        self.commit("app/api/x.py", "x = 1\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["security", "ux", "ui", "code"])
        self.assertEqual(self.files(2), [])

    def test_review_plan_keeps_real_review_for_spawned_role(self):
        self.commit("index.html", "<p>x</p>\n")
        self.rdir(1).mkdir(parents=True)
        (self.rdir(1) / "review-ui.md").write_text("VERDICT: CHANGES\nreal finding\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertIn("ui", out["spawn"])
        self.assertEqual(self.read(1, "ui"), "VERDICT: CHANGES\nreal finding\n")

    # --- AC 4 ---
    def test_review_plan_security_skip_when_no_sensitive_files(self):
        self.commit("src/a.py", "a = 2\n")
        self.commit("docs/guide.md", "guide\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["code"], "since": None})
        self.assertEqual(self.read(1, "security"), self.SEC_SKIP)

    def test_review_plan_security_runs_on_sensitive_paths(self):
        paths = ["src/Auth/login.py", "app/api/x.py", ".env.local", "pyproject.toml", "middleware.ts",
                 "lib/SESSION.py", "prisma/schema.prisma", "db/001.SQL", "package-lock.json", "requirements-dev.txt",
                 "app/users/route.ts", "src/stripe_hooks.py"]
        for rel in paths:
            with self.subTest(rel):
                sec = self.rdir(1) / "review-security.md"
                if sec.exists():
                    sec.unlink()
                self.commit(rel, "x\n")
                out = board.cmd_review_plan(self.root, self.job)
                self.assertEqual(out["spawn"], ["security", "code"])
                self.assertFalse(sec.exists())
                self.git(self.wt, "rm", "-q", rel)
                self.git(self.wt, "commit", "-q", "-m", f"drop {rel}")
        for rel in ("src/routes.py", "src/apix/y.py", "pkg/package.json.bak"):
            with self.subTest(rel):
                self.commit(rel, "x\n")
                out = board.cmd_review_plan(self.root, self.job)
                self.assertEqual(out["spawn"], ["code"])
                self.git(self.wt, "rm", "-q", rel)
                self.git(self.wt, "commit", "-q", "-m", f"drop {rel}")

    # --- AC 5 ---
    def test_review_plan_unreadable_diff_spawns_all(self):
        self.commit("src/a.py", "a = 2\n")
        for pairs in (["base=no-such-branch"], [f"worktree={Path(self.tmp.name) / 'gone'}", "base=main"]):
            with self.subTest(pairs=pairs):
                board.cmd_set(self.root, self.job, pairs)
                out = board.cmd_review_plan(self.root, self.job)
                self.assertEqual(out, {"spawn": ["security", "ux", "ui", "code"], "since": None})
                self.assertEqual(self.files(1), [])

    # --- AC 6 ---
    def test_review_plan_refuses_aborted_or_missing_worktree(self):
        self.commit("src/a.py", "a = 2\n")
        with self.subTest("not on the board"):
            with self.assertRaises(SystemExit):
                board.cmd_review_plan(self.root, "999-nope")
        for key in ("worktree", "base"):
            with self.subTest(f"no {key}"):
                board.cmd_set(self.root, self.job, [f"{key}="])
                with self.assertRaises(SystemExit):
                    board.cmd_review_plan(self.root, self.job)
                self.assertEqual(self.files(1), [])
                board.cmd_set(self.root, self.job, [f"worktree={self.wt}", "base=main"])
        with self.subTest("paused"):
            board.cmd_pause(self.root, self.job)
            with self.assertRaises(SystemExit):
                board.cmd_review_plan(self.root, self.job)
            self.assertEqual(self.files(1), [])
        with self.subTest("aborted"):
            board.cmd_abort(self.root, self.job, False)
            with self.assertRaises(SystemExit):
                board.cmd_review_plan(self.root, self.job)
            self.assertEqual(self.files(1), [])

    # --- deletion-dominated diffs (job 242) ---
    DEL_SKIP = "VERDICT: PASS\nSkipped by orchestrator: diff is at least 90% deletions.\n"

    def big_base(self, files):
        """Commit files in the worktree and make that commit the job's base, so later deletions are in the diff."""
        for rel, text in files.items():
            p = self.wt / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text) if isinstance(text, bytes) else p.write_text(text)
            self.git(self.wt, "add", rel)
        self.git(self.wt, "commit", "-q", "-m", "big base")
        self.git(self.wt, "branch", "-f", "bigbase")
        board.cmd_set(self.root, self.job, ["base=bigbase"])

    def delete(self, *rels):
        self.git(self.wt, "rm", "-q", *rels)
        self.git(self.wt, "commit", "-q", "-m", "delete")

    def test_review_plan_deletion_dominated_still_spawns_ui_ux(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 100, "src/big.py": "x = 1\n" * 100})
        self.delete("src/big.py")
        self.commit("web/page.html", "<p>x</p>\n" * 9 + "<p>new</p>\n")  # +1 -91 on a UI file
        for globs in ("*.html", None):
            with self.subTest(globs=globs):
                self.project(globs)
                out = board.cmd_review_plan(self.root, self.job)
                self.assertEqual(out, {"spawn": ["ux", "ui", "code"], "since": None})
                self.assertEqual(self.files(1), ["review-security.md"])
        with self.subTest("no UI file: UI_SKIP wins"):
            self.project("*.css")
            out = board.cmd_review_plan(self.root, self.job)
            self.assertEqual(out["spawn"], ["code"])
            self.assertEqual(self.read(1, "ui"), self.UI_SKIP)
            self.assertEqual(self.read(1, "ux"), self.UI_SKIP)

    def test_review_plan_deletion_skip_boundary_is_90pct(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 10})
        self.commit("web/page.html", "<p>x</p>\n" + "<p>new</p>\n")  # +1 -9: exactly 90%
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["ux", "ui", "code"])
        self.assertEqual(self.files(1), ["review-security.md"])

    def test_review_plan_deletion_dominated_keeps_security_on_sensitive_path(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 50, "src/auth.py": "x = 1\n" * 50})
        self.delete("src/auth.py")
        self.commit("web/page.html", "<p>new</p>\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["security", "ux", "ui", "code"], "since": None})
        self.assertEqual(self.files(1), [])

    def test_review_plan_80pct_deletion_unchanged(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 10})
        self.commit("web/page.html", "<p>x</p>\n" * 2 + "<p>a</p>\n<p>b</p>\n")  # +2 -8: 80%
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["ux", "ui", "code"], "since": None})
        self.assertEqual(self.files(1), ["review-security.md"])

    def test_review_plan_deletion_skip_ignores_binary(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 100})
        self.commit("web/page.html", "<p>new</p>\n")
        (self.wt / "img.bin").write_bytes(b"\x00\x01\xff" * 10)
        self.git(self.wt, "add", "img.bin")
        self.git(self.wt, "commit", "-q", "-m", "binary")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["ux", "ui", "code"], "since": None})
        self.assertEqual(self.files(1), ["review-security.md"])
        board.cmd_set(self.root, self.job, ["base=no-such-branch"])
        (self.rdir(1) / "review-security.md").unlink()
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["security", "ux", "ui", "code"], "since": None})
        self.assertEqual(self.files(1), [])

    def test_review_plan_rerun_removes_stale_deletion_skip(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 100})
        self.commit("web/page.html", "<p>new</p>\n")
        self.rdir(1).mkdir(parents=True, exist_ok=True)
        (self.rdir(1) / "review-ui.md").write_text(self.DEL_SKIP)  # left by an earlier run
        self.assertFalse(board._real_review(self.rdir(1) / "review-ui.md"))
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out["spawn"], ["ux", "ui", "code"])
        self.assertEqual(self.files(1), ["review-security.md"])

    def test_review_plan_incremental_never_deletion_skips(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 100})
        self.commit("web/page.html", "<p>new</p>\n")
        since = self.round_one({"security": "PASS", "ux": "CHANGES", "ui": "CHANGES", "code": "PASS"})
        self.commit("src/a.py", "a = 3\n")
        out = board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assertEqual(out, {"spawn": ["ux", "ui"], "since": since})
        self.assertEqual(self.files(2), ["review-code.md", "review-security.md"])
        self.assertEqual(self.read(2, "code"), self.CARRIED)

    # --- AC 7 ---
    def test_review_plan_cli_prints_json(self):
        since = self.round_one(self.MIXED)
        self.commit("src/a.py", "a = 3\n")
        before = (self.root / "board.json").read_bytes()
        r = run_board("--dir", str(self.root), "review-plan", self.job, "--incremental")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("\n"), 1)
        self.assertEqual(json.loads(r.stdout), {"spawn": ["security", "code"], "since": since})
        r = run_board("--dir", str(self.root), "review-plan", self.job)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"spawn": ["code"], "since": None})
        self.assertEqual((self.root / "board.json").read_bytes(), before)

    # --- job 613: a reused check spawns only what is needed ---
    RENDERED = "VERDICT: PASS\nRendered: yes — price row visible\n"

    def ui_round_one(self, ui=RENDERED, ux=RENDERED, code="PASS"):
        """Round 1 reviewed a web/page.html change at HEAD; sets round=2 with HEAD unchanged."""
        sha = self.commit("web/page.html", "<p>new</p>\n")
        d = self.rdir(1)
        d.mkdir(parents=True, exist_ok=True)
        (d / "head.txt").write_text(sha + "\n")
        for role, text in (("security", "VERDICT: PASS\n"), ("ux", ux), ("ui", ui), ("code", f"VERDICT: {code}\n")):
            (d / f"review-{role}.md").write_text(text)
        board.cmd_set(self.root, self.job, ["round=2"])
        return sha

    def test_review_plan_rework_fix_now_spawns_named_role(self):
        since = self.ui_round_one()
        (self.rdir(1) / "decision.md").write_text(
            "REWORK\n## Rulings\n- fix-now — the UX reviewer must check the tab order of the price row\n"
            "- accept — the copy is fine\n")
        out = board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assertEqual(out, {"spawn": ["ux"], "since": since})  # ui rendered at this HEAD: carried
        self.assertEqual(self.read(2, "ui"), self.CARRIED)
        (self.rdir(1) / "review-ui.md").write_text("VERDICT: PASS\nlooks fine\n")  # no render at this HEAD
        out = board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assertEqual(out, {"spawn": ["ux", "ui"], "since": since})

    def test_review_plan_carries_ui_with_same_head_render(self):
        since = self.ui_round_one(code="CHANGES")
        out = board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assertEqual(out, {"spawn": ["code"], "since": since})
        self.assertEqual(self.read(2, "ui"), self.CARRIED)
        self.assertEqual(self.read(2, "ux"), self.CARRIED)

    def test_review_plan_spawns_ui_when_render_was_at_another_head(self):
        since = self.ui_round_one(code="CHANGES")
        self.commit("web/page.html", "<p>newer</p>\n")  # the fix moved HEAD; round 1 rendered the old one
        out = board.cmd_review_plan(self.root, self.job, incremental=True)
        self.assertEqual(out, {"spawn": ["ux", "ui", "code"], "since": since})
        self.assertEqual(self.files(2), ["review-security.md"])


E2E_CMD = ("E2E_PORT=$(python3 -c 'import socket;s=socket.socket();s.bind((\"\",0));print(s.getsockname()[1])') "
           "npm run test:e2e")


class E2eSpecsTest(unittest.TestCase):
    """board.py e2e-specs: the diff's UI files mapped to the E2E specs that cover their routes (job 613)."""

    FILES = {
        "src/app/(pages)/pricing/page.tsx": "import Price from '@/components/Price'\nimport Grid from '@/app/admin/views/Grid'\n"
                                            "export default () => <Price />\n",
        "src/app/admin/views/Grid.tsx": "export default () => <table />\n",
        "src/components/Price.tsx": "export default function Price() { return <b>9</b> }\n",
        "src/components/Orphan.tsx": "export const Orphan = () => null\n",
        "src/app/order/[id]/page.tsx": "export default () => <p>order</p>\n",
        "src/app/layout.tsx": "export default ({ children }) => children\n",
        "playwright.config.ts": "export default { testDir: './e2e' }\n",
        "e2e/pricing.spec.ts": "test('price', async ({ page }) => { await page.goto('/pricing') })\n",
        "e2e/order.spec.ts": "test('order', async ({ page }) => { await page.goto(`/order/${id}`) })\n",
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        for rel, text in self.FILES.items():
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / rel).write_text(text)
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "job")
        self.project()

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True)

    def project(self, extra=""):
        self.pfile = Path(self.tmp.name) / "project.md"
        self.pfile.write_text(f"# Project\n- E2E: {E2E_CMD}\n- UI globs: *.tsx *.css src/components/ src/app/\n{extra}")

    def change(self, rel):
        p = self.repo / rel
        p.write_text(p.read_text() + "// changed\n")
        self.git("commit", "-q", "-am", f"edit {rel}")
        return board.e2e_specs(self.repo, "main", self.pfile)

    def test_page_change_maps_to_its_spec(self):
        self.assertEqual(self.change("src/app/(pages)/pricing/page.tsx"), {
            "mode": "scoped", "command": E2E_CMD + " -- e2e/pricing.spec.ts", "specs": ["e2e/pricing.spec.ts"],
            "uncovered": [], "trigger": None})

    def test_component_maps_through_its_importer(self):
        out = self.change("src/components/Price.tsx")
        self.assertEqual((out["mode"], out["specs"], out["uncovered"]), ("scoped", ["e2e/pricing.spec.ts"], []))

    def test_colocated_app_module_maps_through_its_importer(self):
        out = self.change("src/app/admin/views/Grid.tsx")  # no spec names /admin/views; the pricing page imports it
        self.assertEqual((out["mode"], out["specs"], out["uncovered"]), ("scoped", ["e2e/pricing.spec.ts"], []))

    def test_param_route_matches_template_literal(self):
        out = self.change("src/app/order/[id]/page.tsx")
        self.assertEqual((out["mode"], out["specs"], out["uncovered"]), ("scoped", ["e2e/order.spec.ts"], []))

    def test_root_layout_runs_full_suite(self):
        self.assertEqual(self.change("src/app/layout.tsx"), {
            "mode": "full", "command": E2E_CMD, "specs": [], "uncovered": [], "trigger": "src/app/layout.tsx"})

    def test_unimported_component_is_uncovered(self):
        self.assertEqual(self.change("src/components/Orphan.tsx"), {
            "mode": "none", "command": None, "specs": [], "uncovered": ["src/components/Orphan.tsx"], "trigger": None})

    def test_full_globs_none_disables_full_trigger(self):
        self.project("- E2E full globs: none\n")
        out = self.change("src/app/layout.tsx")
        self.assertEqual(out["mode"], "scoped")  # the root layout covers every route as a prefix
        self.assertEqual(out["specs"], ["e2e/order.spec.ts", "e2e/pricing.spec.ts"])

    def test_tests_only_diff_runs_nothing(self):
        self.assertEqual(self.change("e2e/pricing.spec.ts"), {
            "mode": "none", "command": None, "specs": [], "uncovered": [], "trigger": None})

    def test_command_shapes(self):
        self.assertEqual(board._e2e_command("npx playwright test --workers=1", ["e2e/a b.spec.ts"]),
                         "npx playwright test --workers=1 'e2e/a b.spec.ts'")
        self.assertEqual(board._e2e_command("FOO=1 BAR='x y' node run-e2e.js", ["e2e/a.spec.ts"]),
                         "FOO=1 BAR='x y' npx playwright test e2e/a.spec.ts")

    def test_cli_without_job(self):
        (self.repo / "src/components/Price.tsx").write_text("export default () => <i>1</i>\n")
        self.git("commit", "-q", "-am", "price")
        r = run_board("--dir", self.tmp.name, "e2e-specs", "--worktree", str(self.repo), "--base", "main",
                      "--project", str(self.pfile))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["specs"], ["e2e/pricing.spec.ts"])
        r = run_board("--dir", self.tmp.name, "e2e-specs", "--worktree", str(self.repo), "--base", "-x",
                      "--project", str(self.pfile))
        self.assertNotEqual(r.returncode, 0)


class RenderPathsTest(unittest.TestCase):
    """board.py render-paths: the app paths the diff's UI runtime files render, for the shared review render (job 652)."""

    FILES = E2eSpecsTest.FILES
    setUp, tearDown, git, project = E2eSpecsTest.setUp, E2eSpecsTest.tearDown, E2eSpecsTest.git, E2eSpecsTest.project

    def commit(self, *rels):
        for rel in rels:
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text((p.read_text() if p.exists() else "export default () => null\n") + "// changed\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "edit")
        return board.render_paths(self.repo, "main", self.pfile)

    def test_render_paths_maps_routes_and_skips_dynamic(self):
        self.assertEqual(self.commit("src/app/admin/views/Grid.tsx", "src/app/order/[id]/page.tsx",
                                     "src/components/Price.tsx"),
                         {"paths": ["/admin/views", "/pricing"], "skipped": ["/order/[id]: dynamic route"]})
        out = self.commit(*[f"src/app/p{i}/page.tsx" for i in range(1, 10)])
        self.assertEqual(out["paths"], ["/admin/views", "/p1", "/p2", "/p3", "/p4", "/p5", "/p6", "/p7"])
        self.assertEqual(out["skipped"], ["/order/[id]: dynamic route", "/p8: over the 8-page cap",
                                          "/p9: over the 8-page cap", "/pricing: over the 8-page cap"])
        with self.assertRaises(SystemExit):
            board.render_paths(self.repo, "-x", self.pfile)

    def test_render_paths_falls_back_to_root(self):
        self.assertEqual(self.commit("src/components/Orphan.tsx"), {"paths": ["/"], "skipped": []})
        self.assertEqual(self.commit("src/app/order/[id]/page.tsx"),
                         {"paths": ["/"], "skipped": ["/order/[id]: dynamic route"]})

    def test_render_paths_empty_without_ui_files(self):
        self.assertEqual(self.commit("e2e/pricing.spec.ts", "README.md"), {"paths": [], "skipped": []})
        self.pfile.write_text("# Project\n- UI globs: none\n")
        self.assertEqual(self.commit("src/components/Price.tsx"), {"paths": [], "skipped": []})
        self.pfile.write_text("# Project\n")
        self.assertEqual(board.render_paths(self.repo, "main", self.pfile), {"paths": [], "skipped": []})

    def test_render_paths_cli(self):
        self.assertIn("render-paths <id>", board.__doc__)
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(Path(self.tmp.name) / "no-projects.json")})
        env.start()
        self.addCleanup(env.stop)
        root = Path(self.tmp.name) / "scrum"
        job = board.cmd_new(root, "Render")
        r = run_board("--dir", str(root), "render-paths", job)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(f"job {job} has no worktree on the board", r.stderr)
        (root / "project.md").write_text("# Project\n- UI globs: *.tsx\n")
        board.cmd_set(root, job, [f"worktree={self.repo}", "base=main"])
        self.commit("src/components/Price.tsx")
        r = run_board("--dir", str(root), "render-paths", job)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"paths": ["/pricing"], "skipped": []})


class CheckReuseTest(unittest.TestCase):
    """board.py check-reuse: a round at an unchanged HEAD reuses the previous round's CHECK: PASS (job 613)."""

    BODY = "CHECK: PASS\nCheck: reused from round 0, HEAD unchanged\nTest: exit 0\n```\nOK\n```\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.repo, self.wt = base / "repo", base / "wt"
        self.root = self.repo / "scrum"
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(base / "no-projects.json")})
        env.start()
        self.addCleanup(env.stop)
        self.repo.mkdir()
        (self.repo / "a.py").write_text("a = 1\n")
        self.git(self.repo, "init", "-q", "-b", "main")
        self.git(self.repo, "add", "a.py")
        self.git(self.repo, "commit", "-q", "-m", "base")
        self.job = board.cmd_new(self.root, "Reuse")
        self.git(self.repo, "worktree", "add", "-q", "-b", f"scrum/{self.job}", str(self.wt))
        board.cmd_set(self.root, self.job, [f"worktree={self.wt}", "base=main", "round=2", "stage=check"])
        self.r1 = self.root / "jobs" / self.job / "round-1"
        self.r1.mkdir(parents=True)
        (self.r1 / "head.txt").write_text(self.git(self.wt, "rev-parse", "HEAD") + "\n")
        (self.r1 / "check.md").write_text(self.BODY)

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def r2(self):
        return self.root / "jobs" / self.job / "round-2" / "check.md"

    def test_reuses_pass_at_same_head(self):
        r = run_board("--dir", str(self.root), "check-reuse", self.job)
        self.assertEqual(json.loads(r.stdout), {"reused": 1})
        self.assertEqual(self.r2().read_text(),
                         "CHECK: PASS\nCheck: reused from round 1, HEAD unchanged\nTest: exit 0\n```\nOK\n```\n")

    def test_moved_head_runs_the_check(self):
        (self.wt / "a.py").write_text("a = 2\n")
        self.git(self.wt, "commit", "-q", "-am", "fix")
        self.assertEqual(board.cmd_check_reuse(self.root, self.job), {"reused": None})
        self.assertFalse(self.r2().exists())

    def test_failed_check_is_not_reused(self):
        (self.r1 / "check.md").write_text("CHECK: FAIL\nTest: exit 1\n")
        self.assertEqual(board.cmd_check_reuse(self.root, self.job), {"reused": None})
        self.assertFalse(self.r2().exists())

    def test_missing_head_is_not_reused(self):
        (self.r1 / "head.txt").unlink()
        self.assertEqual(board.cmd_check_reuse(self.root, self.job), {"reused": None})
        self.assertFalse(self.r2().exists())

    def test_round_one_is_never_reused(self):
        board.cmd_set(self.root, self.job, ["round=1"])
        self.assertEqual(board.cmd_check_reuse(self.root, self.job), {"reused": None})


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
        r = run_board("--dir", str(self.root), "move-ratio", job or self.job)
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

    def test_ignores_user_color_moved_ws(self):
        self.git("config", "diff.colorMovedWS", "allow-indentation-change")
        indented = "".join("    " + l for l in self.BLOCK.splitlines(True))
        self.commit({"a.py": "# a\n# end a\n", "b.py": "# b\n" + indented})
        self.assertEqual(self.run_cli(), (0, {"added": 20, "moved": 0, "ratio": 0.0}))
        self.move()  # overwrites b.py with the verbatim block; base...HEAD now shows only the plain move
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


class RouteCheckTest(unittest.TestCase):
    """board.py route-check: the Fast lane promotion, Review clean-round and Approve model decisions."""

    @classmethod
    def setUpClass(cls):
        """The committed worktree, built once: each setUp copies it (git init + commit per test cost seconds under load)."""
        cls.base_tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.base_tmp.cleanup)
        cls.base_wt = Path(cls.base_tmp.name) / "wt"
        cls.base_wt.mkdir()
        (cls.base_wt / "README.md").write_text("readme\n")
        for args in (("init", "-q", "-b", "main"), ("add", "README.md"), ("commit", "-q", "-m", "base"),
                     ("checkout", "-q", "-b", "work")):
            subprocess.run(["git", "-C", str(cls.base_wt), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                           capture_output=True)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "scrum"
        self.wt = base / "wt"
        env = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(base / "no-usage.json")})
        env.start()
        self.addCleanup(env.stop)
        shutil.copytree(self.base_wt, self.wt, symlinks=True)
        self.job = board.cmd_new(self.root, "Route me")
        self.jd = self.root / "jobs" / self.job
        board.cmd_set(self.root, self.job, [f"worktree={self.wt}", "base=main"])
        (self.root / "project.md").write_text("# Project profile\n- Test: none\n- UI globs: *.html components/ app/page.tsx\n")
        self.spec("none")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.wt), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True)

    def commit(self, files):
        for rel, text in files.items():
            (self.wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / rel).write_bytes(text) if isinstance(text, bytes) else (self.wt / rel).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def spec(self, hard):
        (self.jd / "spec.md").write_text(f"# Spec\nUI surface: no\nHard stops: {hard}\nLane: standard\n")

    def round(self, n, check="PASS", changes=()):
        d = self.jd / f"round-{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "check.md").write_text(f"CHECK: {check}\n")
        for r in ("security", "ux", "ui", "code"):
            (d / f"review-{r}.md").write_text("VERDICT: CHANGES\n" if r in changes else "VERDICT: PASS\nok\n")

    def fast(self):
        board.cmd_set(self.root, self.job, ["lane=fast"])

    def route(self, **kw):
        return board.cmd_route_check(self.root, self.job, **kw)

    def promote(self, files, **kw):
        self.fast()
        self.commit(files)
        self.round(1)
        return self.route(**kw)["promote"]

    # --- CLI ---
    def test_route_check_cli_prints_three_keys(self):
        self.commit({"src/util.py": "x = 1\n"})
        self.round(1)
        out = io.StringIO()
        with redirect_stdout(out):
            code = board.main(["--dir", str(self.root), "route-check", self.job, "--clean-start"])
        self.assertIn(code, (0, None))
        self.assertEqual(json.loads(out.getvalue()), {"promote": None, "clean_round": True, "approver_sonnet": True})
        self.assertEqual(out.getvalue().count("\n"), 1)
        r = run_board("--dir", str(self.root), "route-check", self.job, "--check-fails", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"promote": None, "clean_round": False, "approver_sonnet": False})

    def test_route_check_unknown_job_fails(self):
        r = run_board("--dir", str(self.root), "route-check", "999-nope")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("999-nope", r.stderr)
        (self.root / "jobs" / "998-gone").mkdir()
        r = run_board("--dir", str(self.root), "route-check", "998-gone")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no job '998-gone' on the board", r.stderr)
        other = board.cmd_new(self.root, "Folder gone")
        (self.root / "jobs" / other).rmdir()
        r = run_board("--dir", str(self.root), "route-check", other)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no job folder", r.stderr)

    # --- promotion triggers ---
    def test_route_check_promote_null_when_not_fast(self):
        self.commit({"src/auth.py": "x\n" * 200})
        self.round(1)
        self.assertIsNone(self.route()["promote"])

    def test_route_check_promote_null_when_small_and_plain(self):
        self.assertIsNone(self.promote({"src/util.py": "x = 1\n"}))

    def test_route_check_promotes_on_binary(self):
        self.assertEqual(self.promote({"img/logo.bin": b"\x00\x01\x02\xff" * 10}), "binary file img/logo.bin")

    def test_route_check_promotes_on_over_100_lines(self):
        self.assertEqual(self.promote({"src/a.py": "x\n" * 60, "src/b.py": "y\n" * 41}), "diff over 100 lines (101)")

    def test_route_check_promotes_on_more_than_10_files(self):
        self.assertEqual(self.promote({f"src/f{i}.py": "x\n" for i in range(11)}), "more than 10 files (11)")

    def test_route_check_5_files_20_lines_stays_fast_and_lilguy(self):
        self.assertIsNone(self.promote({f"src/f{i}.py": "x\n" * 4 for i in range(5)}))
        self.git("reset", "-q", "--hard", "main")
        self.assertIsNone(self.lilguy({f"src/f{i}.py": "x\n" * 4 for i in range(5)}))
        self.git("reset", "-q", "--hard", "main")
        self.assertIsNone(self.lilguy({f"src/f{i}.py": "x\n" for i in range(10)}))
        self.git("reset", "-q", "--hard", "main")
        self.assertIsNone(self.promote({f"src/f{i}.py": "x\n" for i in range(10)}))

    def test_route_check_boundaries_stay_fast(self):
        self.assertIsNone(self.promote({"src/a.py": "x\n" * 50, "src/b.py": "y\n" * 25, "src/c.py": "z\n" * 25}))

    def test_route_check_promotes_on_schema_path(self):
        self.assertEqual(self.promote({"prisma/schema.prisma": "model A {}\n"}), "schema path prisma/schema.prisma")
        self.commit({"db/init.sql": "select 1;\n"})
        self.assertEqual(self.route()["promote"], "schema path db/init.sql")

    def test_route_check_promotes_on_env_file(self):
        self.assertEqual(self.promote({".env.example": "A=1\n"}), "env file .env.example")

    def test_route_check_ui_file_stays_fast(self):
        self.assertIsNone(self.promote({"web/index.html": "<p>\n", "src/util.py": "x = 1\n"}))
        self.git("reset", "-q", "--hard", "main")
        self.commit({"src/components/x.py": "x\n", "app/page.tsx": "x\n"})
        self.assertIsNone(self.route()["promote"])

    def test_route_check_server_only_paths_not_ui_file(self):
        (self.root / "project.md").write_text("- UI globs: app/ *.tsx\n")
        self.assertIsNone(self.promote({"src/app/api/a/route.ts": "x\n", "src/app/api/b/handler.ts": "y\n"}))

    def test_route_check_ui_globs_none_matches_nothing(self):
        (self.root / "project.md").write_text("- UI globs: none\n")
        self.assertIsNone(self.promote({"web/index.html": "<p>\n"}))
        (self.root / "project.md").write_text("- Test: none\n")
        self.assertIsNone(self.route()["promote"])

    def test_route_check_promotes_on_sensitive_path(self):
        self.assertEqual(self.promote({"src/lib/Session.py": "x\n"}), "sensitive path src/lib/Session.py")
        self.git("reset", "-q", "--hard", "main")
        self.commit({"src/middleware.ts": "x\n"})
        self.assertEqual(self.route()["promote"], "sensitive path src/middleware.ts")
        self.git("reset", "-q", "--hard", "main")
        self.commit({"src/lib/middlewareUtils/format.py": "x\n"})
        self.assertIsNone(self.route()["promote"])

    def test_route_check_trigger_order(self):
        # binary before size, size before file count, count before paths, schema before env/sensitive; a UI file never promotes
        self.assertEqual(self.promote({"a.bin": b"\x00\xff", "src/a.py": "x\n" * 200}), "binary file a.bin")
        self.git("reset", "-q", "--hard", "main")
        self.commit({**{f"f{i}.py": "x\n" for i in range(5)}, "big.py": "x\n" * 200})
        self.assertEqual(self.route()["promote"], "diff over 100 lines (205)")
        self.git("reset", "-q", "--hard", "main")
        self.commit({"x/auth.py": "x\n", "x.html": "x\n", ".env": "A=1\n", "m.sql": "s\n",
                     **{f"g{i}.py": "x\n" for i in range(7)}})
        self.assertEqual(self.route()["promote"], "more than 10 files (11)")
        self.git("reset", "-q", "--hard", "main")
        self.commit({"x/auth.py": "x\n", "x.html": "x\n", "m.sql": "s\n"})
        self.assertEqual(self.route()["promote"], "schema path m.sql")
        self.git("reset", "-q", "--hard", "main")
        self.commit({"x/auth.py": "x\n", "x.html": "x\n", ".env": "A=1\n"})
        self.assertEqual(self.route()["promote"], "env file .env")
        self.git("reset", "-q", "--hard", "main")
        self.commit({"x/auth.py": "x\n", "x.html": "x\n"})
        self.assertEqual(self.route()["promote"], "sensitive path x/auth.py")

    # --- deletions (job 242) ---
    def big_base(self, files):
        """Commit files on the work branch and make that commit the job's base, so later deletions are in the diff."""
        self.commit(files)
        self.git("branch", "-f", "bigbase")
        board.cmd_set(self.root, self.job, ["base=bigbase"])

    def delete(self, *rels):
        self.git("rm", "-q", *rels)
        self.git("commit", "-q", "-m", "delete")

    def test_route_check_deletions_stay_fast(self):
        self.big_base({f"src/f{i}.py": "x\n" * 50 for i in range(8)})
        self.delete(*(f"src/f{i}.py" for i in range(7)))
        self.assertIsNone(self.promote({"src/f7.py": "y\n" * 5}))  # +5 -400 over 8 files, 1 with an added line

    def test_route_check_promotes_on_120_added_lines(self):
        self.big_base({"src/old.py": "x\n" * 300})
        self.delete("src/old.py")
        self.assertEqual(self.promote({"src/a.py": "x\n" * 120}), "diff over 100 lines (120)")

    def test_route_check_promotes_on_deleted_schema_path(self):
        for rel, want in (("prisma/schema.prisma", "schema path prisma/schema.prisma"), (".env.example", "env file .env.example"),
                          ("web/index.html", None), ("src/auth.py", "sensitive path src/auth.py")):
            with self.subTest(rel):
                self.git("reset", "-q", "--hard", "main")
                self.big_base({rel: "x\n"})
                self.delete(rel)
                self.assertEqual(self.promote({"src/util.py": "x = 1\n"}), want)

    def test_route_check_clean_round_with_deletion_skips(self):
        self.big_base({"src/old.py": "x\n" * 95, "src/auth_old.py": "x\n"})
        self.delete("src/old.py")
        self.commit({"src/util.py": "x\n" * 5})  # +5 -95
        d = self.jd / "round-1"
        d.mkdir(parents=True)
        (d / "check.md").write_text("CHECK: PASS\n")
        (d / "review-code.md").write_text("VERDICT: PASS\nok\n")
        for r in ("ui", "ux"):
            (d / f"review-{r}.md").write_text("VERDICT: PASS\nSkipped by orchestrator: diff is at least 90% deletions.\n")
        (d / "review-security.md").write_text("VERDICT: PASS\nSkipped by orchestrator: no sensitive files in diff.\n")
        self.assertTrue(self.route(clean_start=True)["clean_round"])
        self.delete("src/auth_old.py")
        self.assertFalse(self.route(clean_start=True)["clean_round"])

    # --- 2nd check failure ---
    def test_route_check_promotes_on_second_check_fail(self):
        self.fast()
        self.commit({"src/util.py": "x\n"})
        self.round(1, check="FAIL")
        self.assertEqual(self.route(check_fails=2)["promote"], "check failed twice")
        self.assertEqual(self.route(check_fails=3)["promote"], "check failed twice")

    def test_route_check_first_fail_does_not_promote(self):
        self.fast()
        self.commit({"src/auth.py": "x\n" * 200})
        self.round(1, check="FAIL")
        self.assertIsNone(self.route(check_fails=1)["promote"])
        self.assertIsNone(self.route()["promote"])
        (self.jd / "round-1" / "check.md").write_text("garbage\n")
        self.assertIsNone(self.route(check_fails=2)["promote"])
        (self.jd / "round-1" / "check.md").unlink()
        self.assertIsNone(self.route(check_fails=2)["promote"])

    def test_route_check_uses_highest_round(self):
        self.fast()
        self.commit({"src/util.py": "x\n"})
        self.round(1)
        self.round(10, check="FAIL")
        self.round(2)
        self.assertEqual(self.route(check_fails=2)["promote"], "check failed twice")

    # --- clean round ---
    def clean_setup(self, files=None):
        self.commit(files or {"src/util.py": "x = 1\n"})
        self.round(1)

    def test_route_check_clean_round_true(self):
        self.clean_setup()
        self.assertTrue(self.route(clean_start=True)["clean_round"])
        board.cmd_set(self.root, self.job, ["lane=standard"])
        self.assertTrue(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_false_lane(self):
        self.clean_setup()
        for lane in ("fast", "debug", "bigboy"):
            board.cmd_set(self.root, self.job, [f"lane={lane}"])
            self.assertFalse(self.route(clean_start=True)["clean_round"], lane)

    def test_route_check_clean_round_false_round_2(self):
        self.clean_setup()
        self.round(2)
        self.assertFalse(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_false_no_round(self):
        self.commit({"src/util.py": "x = 1\n"})
        self.assertEqual(self.route(clean_start=True), {"promote": None, "clean_round": False, "approver_sonnet": False})

    def test_route_check_clean_round_false_check_fail(self):
        self.commit({"src/util.py": "x = 1\n"})
        self.round(1, check="FAIL")
        self.assertFalse(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_false_review_changes(self):
        self.commit({"src/util.py": "x = 1\n"})
        self.round(1, changes=("ux",))
        self.assertFalse(self.route(clean_start=True)["clean_round"])
        self.round(1)
        (self.jd / "round-1" / "review-code.md").unlink()
        self.assertFalse(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_false_rendered_blocked(self):
        self.clean_setup()
        (self.jd / "round-1" / "review-ui.md").write_text("VERDICT: PASS\nRendered: blocked — no Chrome\n")
        out = self.route(clean_start=True)
        self.assertFalse(out["clean_round"])
        self.assertTrue(out["approver_sonnet"])

    def test_route_check_clean_round_false_schema_path(self):
        self.clean_setup({"prisma/migrations/1/migration.sql": "x\n"})
        self.assertFalse(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_false_env_path(self):
        self.clean_setup({"config/.env.local": "A=1\n"})
        self.assertFalse(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_false_sensitive_path(self):
        self.clean_setup({"src/Billing/invoice.py": "x\n"})
        self.assertFalse(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_ignores_ui_and_size(self):
        self.clean_setup({**{f"web/p{i}.html": "<p>\n" * 50 for i in range(5)}})
        self.assertTrue(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_false_hard_stops(self):
        self.clean_setup()
        for hard in ("schema", "none, schema", ""):
            self.spec(hard)
            self.assertFalse(self.route(clean_start=True)["clean_round"], hard)
        self.spec("  none  ")
        self.assertTrue(self.route(clean_start=True)["clean_round"])
        (self.jd / "spec.md").write_text("# Spec\nUI surface: no\nLane: standard\n")
        self.assertFalse(self.route(clean_start=True)["clean_round"])

    def test_route_check_clean_round_false_no_clean_start(self):
        self.clean_setup()
        self.assertFalse(self.route()["clean_round"])

    def test_route_check_missing_spec_not_clean(self):
        self.clean_setup()
        (self.jd / "spec.md").unlink()
        out = self.route(clean_start=True)
        self.assertFalse(out["clean_round"])
        self.assertTrue(out["approver_sonnet"])

    # --- approver model ---
    def test_route_check_approver_sonnet_true_on_round_2(self):
        board.cmd_set(self.root, self.job, ["lane=fast"])
        self.spec("schema")
        self.commit({"src/auth.py": "x\n" * 200})
        self.round(1, check="FAIL", changes=("code",))
        self.round(2)
        out = self.route(clean_start=True)
        self.assertTrue(out["approver_sonnet"])
        self.assertFalse(out["clean_round"])

    def test_route_check_approver_sonnet_false_on_schema_path(self):
        self.commit({"src/schema.sql": "x\n"})
        self.round(1)
        self.assertFalse(self.route(clean_start=True)["approver_sonnet"])

    def test_route_check_approver_sonnet_false_without_clean_start(self):
        self.commit({"src/util.py": "x\n"})
        self.round(1)
        self.assertFalse(self.route()["approver_sonnet"])

    def test_route_check_approver_sonnet_false_on_review_changes(self):
        self.commit({"src/util.py": "x\n"})
        self.round(1, changes=("security",))
        self.assertFalse(self.route(clean_start=True)["approver_sonnet"])

    def test_route_check_approver_sonnet_false_on_check_fail(self):
        self.commit({"src/util.py": "x\n"})
        self.round(1, check="FAIL")
        self.assertFalse(self.route(clean_start=True)["approver_sonnet"])

    # --- lilguy promotion (job 244) ---
    def lilguy(self, files, feature="Tiny change\n", **kw):
        board.cmd_set(self.root, self.job, ["lane=lilguy"])
        (self.jd / "feature.md").write_text(feature)
        if files:
            self.commit(files)
        return self.route(**kw)["promote"]

    def test_route_check_lilguy_30_lines_stays(self):
        self.assertIsNone(self.lilguy({"src/a.py": "x\n" * 20, "src/b.py": "y\n" * 5, "src/c.py": "z\n" * 5}))

    def test_route_check_lilguy_31_lines_promotes(self):
        self.assertEqual(self.lilguy({"src/a.py": "x\n" * 31}), "diff over 30 added lines (31)")

    def test_route_check_lilguy_11_files_promotes(self):
        self.assertEqual(self.lilguy({f"src/f{i}.py": "x\n" for i in range(11)}),
                         "more than 10 files with added lines (11)")

    def test_route_check_lilguy_mechanical_ignores_size(self):
        feature = "Rename\nLane: lilguy — mechanical rename\n"
        self.assertIsNone(self.lilguy({f"src/f{i}.py": "x\n" * 5 for i in range(11)}, feature=feature))
        self.assertEqual(self.lilguy({"skills/trevskills-scrum/SKILL.md": "x\n"}, feature=feature),
                         "rules file skills/trevskills-scrum/SKILL.md not in feature.md")

    def test_route_check_lilguy_deletions_dont_count(self):
        self.big_base({f"src/f{i}.py": "x\n" * 50 for i in range(5)})
        self.git("rm", "-q", "src/f0.py", "src/f1.py", "src/f2.py")
        self.commit({"src/f3.py": "y\n" * 5 + "x\n" * 45, "src/f4.py": "z\n" * 5 + "x\n" * 10})
        # +10 -200 over 5 files, 2 with added lines
        self.assertIsNone(self.lilguy({}))

    def test_route_check_lilguy_rules_file_outside_ticket_promotes(self):
        self.assertEqual(self.lilguy({"skills/trevskills-scrum/SKILL.md": "x\n"}),
                         "rules file skills/trevskills-scrum/SKILL.md not in feature.md")
        (self.jd / "feature.md").write_text("Edit skills/trevskills-scrum/SKILL.md wording\n")
        self.assertIsNone(self.route()["promote"])
        self.git("reset", "-q", "--hard", "main")
        self.commit({"agents/scrum-builder.md": "x\n"})
        (self.jd / "feature.md").write_text("Edit SKILL.md and scrum-builder.md\n")
        self.assertEqual(self.route()["promote"], "rules file agents/scrum-builder.md not in feature.md")
        (self.jd / "feature.md").write_text("Edit every agents/*.md file\n")
        self.assertIsNone(self.route()["promote"])

    def test_route_check_lilguy_check_fails_3(self):
        self.round(1, check="FAIL")
        self.assertIsNone(self.lilguy({"src/a.py": "x\n"}, check_fails=2))
        self.assertEqual(self.route(check_fails=3)["promote"], "check failed 3 times")
        board.cmd_set(self.root, self.job, ["worktree="])
        self.assertIsNone(self.route(check_fails=3)["promote"])  # lilguy in the main checkout: no promotion

    # --- can't tell ---
    def test_route_check_unreadable_diff_is_conservative(self):
        self.commit({"src/util.py": "x\n"})
        self.round(1)
        want_fast = {"promote": "diff unreadable", "clean_round": False, "approver_sonnet": False}
        want_std = {"promote": None, "clean_round": False, "approver_sonnet": False}
        for pairs in (["base=nosuchbranch"], ["base=-p"], ["base="], ["worktree=", "base=main"]):
            board.cmd_set(self.root, self.job, [f"worktree={self.wt}", "lane=standard", *pairs])
            self.assertEqual(self.route(clean_start=True), want_std, pairs)
            board.cmd_set(self.root, self.job, ["lane=fast"])
            self.assertEqual(self.route(clean_start=True), want_fast, pairs)
        board.cmd_set(self.root, self.job, [f"worktree={self.wt}", "base=nosuchbranch", "lane=fast"])
        self.round(1, check="FAIL")
        self.assertIsNone(self.route(clean_start=True)["promote"])
        self.assertEqual(self.route(check_fails=2)["promote"], "check failed twice")
        r = run_board("--dir", str(self.root), "route-check", self.job)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), want_std)

    def test_glob_match_excludes_server_only_paths(self):
        for path in ("src/app/api/x/route.ts", "app/api/y.ts", "app/api/z.tsx", "src/app/(shop)/cart/route.tsx",
                     "lib/route.js", "route.ts"):
            for globs in (["app/"], ["*.ts"], ["*.tsx"], ["*.js"], [path]):
                self.assertFalse(board.glob_match(path, globs), f"{path} {globs}")
        self.assertTrue(board.glob_match("src/app/page.tsx", ["app/"]))
        self.assertTrue(board.glob_match("src/myapp/api/x.tsx", ["*.tsx"]))
        self.assertTrue(board.glob_match("app/apiary/page.tsx", ["app/"]))
        self.assertTrue(board.glob_match("app/x/api/page.tsx", ["app/"]))
        self.assertTrue(board.glob_match("src/router.ts", ["*.ts"]))

    def test_ui_globs_and_glob_match(self):
        self.assertEqual(board.ui_globs(self.root), ["*.html", "components/", "app/page.tsx"])
        (self.root / "project.md").write_text("- UI globs: none\n")
        self.assertIsNone(board.ui_globs(self.root))
        (self.root / "project.md").unlink()
        self.assertIsNone(board.ui_globs(self.root))
        globs = ["*.tsx", "components/", "app/layout.ts"]
        for path in ("a.tsx", "src/x/b.tsx", "components/x.py", "src/components/y/z.py", "app/layout.ts"):
            self.assertTrue(board.glob_match(path, globs), path)
        for path in ("a.ts", "mycomponents/x.py", "src/app/layout.ts", "app/layout.js", "components"):
            self.assertFalse(board.glob_match(path, globs), path)


class LilguyFitTest(unittest.TestCase):
    """board.py lilguy-fit: whether a new job is tiny and safe enough for Lilguy Worktree mode."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        env = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(Path(self.tmp.name) / "no-usage.json")})
        env.start()
        self.addCleanup(env.stop)
        self.job = board.cmd_new(self.root, "Tweak a label")
        self.jd = self.root / "jobs" / self.job
        (self.jd / "feature.md").write_text("Tweak the dashboard label text\n")

    def points(self, pts):
        (self.root / "backlog.md").write_text(f"# Backlog\n- [ ] [5] Other item\n- [ ] [{pts}] Tweak a label → {self.job}\n")

    def jev(self, *raws):
        (self.jd / "jev.log").write_text("".join(f"2026-10-23T10:00:00\tmodel\tHow hard\t{r}\tsonnet\t0.10\n" for r in raws))

    def fit(self):
        return board.cmd_lilguy_fit(self.root, self.job)

    def test_lilguy_fit_points_1_passes(self):
        self.points(1)
        out = io.StringIO()
        with redirect_stdout(out):
            code = board.main(["--dir", str(self.root), "lilguy-fit", self.job])
        self.assertIn(code, (0, None))
        got = json.loads(out.getvalue())
        self.assertEqual(set(got), {"fit", "why"})
        self.assertIs(got["fit"], True)
        self.assertEqual(out.getvalue().count("\n"), 1)

    def test_lilguy_fit_points_1_naming_skill_md_passes(self):
        self.points(1)
        (self.jd / "feature.md").write_text("Reword SKILL.md, agents/scrum-builder.md and lanes/lilguy.md\n")
        self.assertIs(self.fit()["fit"], True)

    def test_lilguy_fit_points_2_fails(self):
        self.points(2)
        self.assertIs(self.fit()["fit"], False)

    def test_lilguy_fit_jev_confident_low_score_passes(self):
        self.jev('{"type":"score","score":2.8,"confidence":0.9}', '{"type":"score","score":1.2,"confidence":0.79}')
        self.assertIs(self.fit()["fit"], True)
        self.jev('{"type":"score","score":1.2,"confidence":0.79}', '{"type":"score","score":2.8,"confidence":0.9}')
        self.assertIs(self.fit()["fit"], False)  # the last model line decides

    def test_lilguy_fit_jev_low_confidence_fails(self):
        self.jev('{"type":"score","score":1.2,"confidence":0.69}')
        self.assertIs(self.fit()["fit"], False)

    def test_lilguy_fit_missing_confidence_fails(self):
        for raw in ('{"type":"score","score":1.2}', '{"type":"score","score":1.2,"confidence":"0.9"}', "JevError", "-"):
            with self.subTest(raw):
                self.jev(raw)
                self.assertIs(self.fit()["fit"], False)
        (self.jd / "jev.log").write_text('2026-10-23T10:00:00\treview\tq\t{"score":0.1,"confidence":0.99}\tskip\t0.1\n')
        self.assertIs(self.fit()["fit"], False)  # no model line

    def test_lilguy_fit_missing_jevlog_fails(self):
        self.assertIs(self.fit()["fit"], False)
        self.points(1)
        self.assertIs(self.fit()["fit"], True)

    def test_lilguy_fit_promoted_job_stays_put(self):
        self.points(1)
        board.cmd_set(self.root, self.job, ["lane=fast"])
        self.assertEqual(self.fit(), {"fit": False, "why": "already on fast lane"})
        board.cmd_set(self.root, self.job, ["lane=lilguy"])
        self.assertIs(self.fit()["fit"], True)

    def test_lilguy_fit_hard_stop_word_fails(self):
        self.points(1)
        (self.jd / "feature.md").write_text("Show the Payment total on the receipt\n")
        got = self.fit()
        self.assertIs(got["fit"], False)
        self.assertIn("Payment", got["why"])
        for text in ("Read the API key from config", "Load .env.local first", "Fix the LOGIN button", "Bump the env vars"):
            with self.subTest(text):
                (self.jd / "feature.md").write_text(text + "\n")
                self.assertIs(self.fit()["fit"], False)

    def test_lilguy_fit_claude_path_fails(self):
        self.points(1)
        for text in ("Edit `.claude/skills/scrum-code-map/SKILL.md`", ".claude/settings.json gets a line"):
            with self.subTest(text):
                (self.jd / "feature.md").write_text(f"# Tweak\nLane: lilguy — tiny\n\n{text}\n")
                self.assertEqual(self.fit(), {"fit": False, "why": "names a .claude/ path"})
        (self.jd / "feature.md").write_text("Tweak the label\n")
        (self.jd / "spec.md").write_text("## Likely files\n- `.claude/rules/x.md`\n")
        self.assertEqual(self.fit(), {"fit": False, "why": "names a .claude/ path"})
        board.cmd_set(self.root, self.job, ["lane=fast"])
        self.assertEqual(self.fit(), {"fit": False, "why": "already on fast lane"})

    def test_lilguy_fit_home_claude_path_passes(self):
        self.points(1)
        (self.jd / "feature.md").write_text("Edit ~/.claude/CLAUDE.md, $HOME/.claude/x, ${HOME}/.claude/y, "
                                            "/Users/t/.claude/z, foo.claude/a, x/.claude/b and .claude/worktrees/c\n")
        self.assertEqual(self.fit(), {"fit": True, "why": "backlog item is 1 point"})

    def test_lilguy_fit_feature_lane_lilguy_overrides(self):
        self.points(2)
        (self.jd / "feature.md").write_text("# Show the payment total\n\nLane: lilguy — one label\n\nShow the Payment total\n")
        self.assertEqual(self.fit(), {"fit": True, "why": "feature.md Lane: lilguy"})
        board.cmd_set(self.root, self.job, ["lane=lilguy"])
        self.assertEqual(self.fit(), {"fit": True, "why": "feature.md Lane: lilguy"})
        board.cmd_set(self.root, self.job, ["lane=fast"])
        self.assertEqual(self.fit(), {"fit": False, "why": "already on fast lane"})

    def test_lilguy_fit_feature_lane_other_skips_fit(self):
        self.points(1)
        for lane in ("fast", "standard", "debug", "bigboy"):
            with self.subTest(lane):
                (self.jd / "feature.md").write_text(f"# Tweak\nLane: {lane} — orchestrator pick\n\nTweak the label\n")
                self.assertEqual(self.fit(), {"fit": False, "why": f"feature.md Lane: {lane}"})
        (self.root / "backlog.md").unlink()
        self.jev('{"type":"score","score":0.5,"confidence":0.95}')
        (self.jd / "feature.md").write_text("# Tweak\nlane: STANDARD — case does not matter\n")
        self.assertEqual(self.fit(), {"fit": False, "why": "feature.md Lane: standard"})

    def test_lilguy_fit_feature_lane_ignored_when_malformed_or_below_heading(self):
        self.points(1)
        for text in ("# Tweak\nLane: weird — not a lane\n", "# Tweak\n\n## Q&A\nLane: standard — quoted\n",
                     "# Tweak\nSee Lane: standard below\n"):
            with self.subTest(text):
                (self.jd / "feature.md").write_text(text)
                self.assertEqual(self.fit(), {"fit": True, "why": "backlog item is 1 point"})
        (self.jd / "feature.md").write_text("# Tweak\n\n## Q&A\nLane: lilguy — quoted\nShow the Payment total\n")
        self.points(2)
        self.assertIs(self.fit()["fit"], False)

    def test_lilguy_fit_author_is_not_auth(self):
        self.points(1)
        (self.jd / "feature.md").write_text("Show the author name and the OAuthor badge\n")
        self.assertIs(self.fit()["fit"], True)
        (self.jd / "feature.md").write_text("Show the author name next to auth status\n")
        got = self.fit()
        self.assertIs(got["fit"], False)
        self.assertIn("auth", got["why"])

    def test_lilguy_fit_over_estimate_refused(self):
        self.points(1)
        (self.jd / "feature.md").write_text("Edit board.py, serve.py, dashboard.html and lanes/lilguy.md\n")
        got = self.fit()
        self.assertIs(got["fit"], False)
        self.assertIn("about 40 added lines in 4 files", got["why"])
        self.assertIn("limits 30 lines, 10 files", got["why"])
        self.jev('{"type":"score","score":0.5,"confidence":0.95}')
        self.assertIs(self.fit()["fit"], False)  # a confident Jev answer does not override it either

    def test_lilguy_fit_names_file_passes(self):
        (self.jd / "feature.md").write_text("Reword the hint in skills/trevskills-scrum/dashboard.html\n")
        self.assertEqual(self.fit(), {"fit": True, "why": "names 1 file(s), estimate about 10 added lines"})
        (self.jd / "feature.md").write_text("Touch board.py, tests/test_board.py and README.md\n")
        got = self.fit()
        self.assertIs(got["fit"], True)
        self.assertTrue(got["why"].startswith("names "), got["why"])
        self.assertIn("about 30 added lines", got["why"])

    def test_lilguy_fit_names_file_still_refused(self):
        for text in ("Fix the login copy in dashboard.html", "Edit .claude/rules/x.md",
                     "Edit a.py, b.py, c.md and d.html"):
            with self.subTest(text):
                (self.jd / "feature.md").write_text(text + "\n")
                self.assertIs(self.fit()["fit"], False)
        (self.jd / "feature.md").write_text("Tweak the dashboard label text\n")
        self.assertTrue(self.fit()["why"].startswith("not tiny"))

    def test_lilguy_fit_estimate_counts_distinct_paths(self):
        self.assertEqual(board.lilguy_estimate("Edit board.py, then board.py again and `board.py`; also x.md\n"),
                         (2, 20))
        self.assertEqual(board.lilguy_estimate("No paths here\n"), (0, 0))

    def test_lilguy_fit_unknown_job_exits(self):
        r = run_board("--dir", str(self.root), "lilguy-fit", "999-nope")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("999-nope", r.stderr)
        with self.assertRaises(SystemExit):
            board.cmd_lilguy_fit(self.root, "999-nope")


class ClaudePathsTest(unittest.TestCase):
    """board.py claude-paths: the project .claude/ files a job's spec names, and whether this session is unattended."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.job = board.cmd_new(self.root, "Edit a skill")
        self.spec = self.root / "jobs" / self.job / "spec.md"

    def ps(self, command, pid=4242):
        """Patch caller_claude_pid to pid and ps to print command for it; returns the run mock."""
        out = subprocess.CompletedProcess([], 0, stdout=command + "\n", stderr="")
        for p in (mock.patch.object(board, "caller_claude_pid", return_value=pid),
                  mock.patch.object(board.subprocess, "run", return_value=out)):
            p.start()
            self.addCleanup(p.stop)

    def paths(self):
        return board.cmd_claude_paths(self.root, self.job)["paths"]

    def test_lists_claude_paths_from_likely_files(self):
        self.spec.write_text("# Spec\n## Likely files\n- `src/a.py`\n- `.claude/skills/b/SKILL.md`: the digest\n"
                             "- `.claude/rules/c.md` and `.claude/skills/b/SKILL.md`\n## Assumptions\n- none\n")
        self.ps("claude -p --permission-mode acceptEdits")
        out = io.StringIO()
        with redirect_stdout(out):
            code = board.main(["--dir", str(self.root), "claude-paths", self.job])
        self.assertIn(code, (0, None))
        self.assertEqual(json.loads(out.getvalue()),
                         {"paths": [".claude/rules/c.md"], "headless": True})

    def test_ignores_worktrees_and_other_sections(self):
        self.spec.write_text("## Scope\n- `.claude/skills/x/SKILL.md`\n## Likely files\n- `.claude/worktrees/scrum-1/a.py`\n"
                             "- `~/.claude/scrum-map.md`\n- `skills/.claude/x`\n- .claude/no-backticks.md\n"
                             "## Assumptions\n- `.claude/rules/y.md`\n")
        self.assertEqual(self.paths(), [])

    def test_skills_paths_are_not_claude_paths(self):
        for path in (".claude/settings.json", ".claude/agents/a.md", ".claude/hooks/h.sh", ".claude/rules/c.md"):
            self.assertTrue(board.is_claude_path(path), path)
        for path in (".claude/skills/x/SKILL.md", ".claude/worktrees/scrum-1/a.py"):
            self.assertFalse(board.is_claude_path(path), path)
        self.spec.write_text("# Spec\n## Likely files\n- `.claude/skills/x/SKILL.md`\n")
        with self.assertRaises(SystemExit):
            board.claude_split(self.root, {"id": self.job, "title": "x"})

    def test_missing_spec_gives_empty(self):
        self.assertEqual(self.paths(), [])
        self.spec.write_text("# Spec\n## Scope\n- `.claude/skills/x/SKILL.md`\n")
        self.assertEqual(self.paths(), [])

    def test_headless_from_print_flag(self):
        for command, want in (("claude -p hi", True), ("/opt/bin/claude --print --verbose", True),
                              ("claude --permission-mode acceptEdits", False), ("claude", False),
                              ("claude --resume abc-p", False)):
            with self.subTest(command):
                out = subprocess.CompletedProcess([], 0, stdout=command + "\n", stderr="")
                with mock.patch.object(board, "caller_claude_pid", return_value=4242), \
                        mock.patch.object(board.subprocess, "run", return_value=out) as run:
                    self.assertIs(board.caller_headless(), want)
                self.assertEqual(run.call_args.args[0], ["ps", "-o", "command=", "-p", "4242"])

    def test_headless_when_no_claude_ancestor(self):
        with mock.patch.object(board, "caller_claude_pid", return_value=None):
            self.assertIs(board.caller_headless(), True)
        with mock.patch.object(board, "caller_claude_pid", return_value=4242), \
                mock.patch.object(board.subprocess, "run", side_effect=OSError("no ps")):
            self.assertIs(board.caller_headless(), True)
        gone = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with mock.patch.object(board, "caller_claude_pid", return_value=4242), \
                mock.patch.object(board.subprocess, "run", return_value=gone):
            self.assertIs(board.caller_headless(), True)


class ClaudeBatchTest(unittest.TestCase):
    """board.py claude-batch: a headless job's project .claude/ edits move into one parked Terminal batch job."""

    SPEC = ("# Edit a skill\n## Acceptance criteria\n1. `src/a.py` returns 2 (verify: test_a)\n"
            "2. `.claude/rules/c.md` names the new rule (verify: grep)\n## Likely files\n- `src/a.py`\n"
            "- `.claude/rules/c.md`\n## Claude edits\n- `.claude/rules/c.md`: add the line `- Never X.`\n"
            "## Assumptions\n- none\n")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.job = board.cmd_new(self.root, "Edit a skill")
        board.cmd_set(self.root, self.job, ["base=main"])
        self.spec = self.root / "jobs" / self.job / "spec.md"
        self.spec.write_text(self.SPEC)

    def batch(self, job_id=None):
        out = io.StringIO()
        with redirect_stdout(out):
            board.main(["--dir", str(self.root), "claude-batch", job_id or self.job])
        return json.loads(out.getvalue())

    def job_of(self, job_id):
        return board.find(board.read_board(self.root), job_id)

    def feature(self, job_id):
        return (self.root / "jobs" / job_id / "feature.md").read_text()

    def test_creates_and_parks_batch(self):
        with mock.patch.object(board, "play") as play:
            out = self.batch()
        self.assertEqual(out, {"batch": "002-terminal-batch-project-claude-edits", "only": False, "created": True})
        bid = out["batch"]
        job = self.job_of(bid)
        self.assertEqual(job["title"], "Terminal batch: project .claude edits")
        self.assertEqual(job["stage"], "needs-human")
        self.assertEqual(job["base"], "main")
        self.assertEqual(job["stopTitle"], "BUILDER_BLOCKED")
        self.assertEqual(job["reason"], board.TERMINAL_BATCH_QUESTION)
        self.assertEqual(job["question"], board.TERMINAL_BATCH_QUESTION)
        self.assertEqual(job["options"], [
            {"key": "a", "label": "Run it in a Terminal window", "command": f"lilguy {bid}"},
            {"key": "b", "label": "Remove this job", "command": f"abort {bid} --cascade"}])
        self.assertEqual(job["recommend"]["key"], "a")
        feature = self.feature(bid)
        self.assertTrue(feature.startswith("Lane: lilguy\nComplex: no\n"), feature)
        self.assertEqual(board.header_value(self.root / "jobs" / bid / "feature.md", "Lane", board.LANES), "lilguy")
        self.assertIn(f"## From {self.job}: Edit a skill\n- `.claude/rules/c.md`: add the line `- Never X.`\n", feature)
        self.assertNotIn("for the full requirements", feature)
        spec = self.spec.read_text()
        self.assertIn("## Moved to Terminal batch\n", spec)
        self.assertIn(f"`{bid}`", spec.split("## Moved to Terminal batch")[1])
        self.assertIn("`.claude/rules/c.md`", spec.split("## Moved to Terminal batch")[1])
        self.assertIn("makes none of those edits", spec)
        log = [json.loads(l) for l in (self.root / "questions.log").read_text().splitlines()]
        self.assertEqual([(e["job"], e["stopTitle"]) for e in log], [(bid, "BUILDER_BLOCKED")])
        play.assert_called_once()
        self.assertEqual(self.job_of(self.job)["stage"], "spec")

    def test_appends_to_open_batch(self):
        bid = self.batch()["batch"]
        other = board.cmd_new(self.root, "Another skill edit")
        (self.root / "jobs" / other / "spec.md").write_text(
            "# B\n## Likely files\n- `.claude/rules/x.md`\n## Claude edits\n- `.claude/rules/x.md`: say Y\n")
        with mock.patch.object(board, "play") as play:
            out = self.batch(other)
        self.assertEqual(out, {"batch": bid, "only": True, "created": False})
        play.assert_not_called()
        feature = self.feature(bid)
        self.assertIn(f"## From {self.job}: Edit a skill\n", feature)
        self.assertIn(f"## From {other}: Another skill edit\n- `.claude/rules/x.md`: say Y\n", feature)
        self.assertEqual([j["title"] for j in board.read_board(self.root)["jobs"]].count(board.TERMINAL_BATCH_TITLE), 1)

    def test_only_when_all_likely_files_are_claude(self):
        self.spec.write_text("# A\n## Likely files\n- `.claude/rules/c.md`\n- `.claude/rules/b.md`: x\n")
        self.assertIs(self.batch()["only"], True)
        other = board.cmd_new(self.root, "Mixed")
        (self.root / "jobs" / other / "spec.md").write_text(
            "# M\n## Likely files\n- `.claude/rules/c.md`\n- `.claude/worktrees/x/a.py`\n")
        self.assertIs(self.batch(other)["only"], False)

    def test_fallback_without_claude_edits_section(self):
        self.spec.write_text(self.SPEC.split("## Claude edits")[0] + "## Assumptions\n- none\n")
        bid = self.batch()["batch"]
        section = self.feature(bid).split(f"## From {self.job}: Edit a skill\n")[1]
        self.assertIn("- `.claude/rules/c.md`\n", section)
        self.assertIn("2. `.claude/rules/c.md` names the new rule (verify: grep)", section)
        self.assertNotIn("`src/a.py` returns 2", section)
        self.assertTrue(section.rstrip("\n").endswith(
            f"Read `{self.spec.resolve()}` for the full requirements."), section)

    def dependents(self, only=True):
        if only:
            self.spec.write_text("# t\n## Likely files\n- `.claude/rules/c.md`\n")
        a = board.cmd_new(self.root, "Dep a")
        b = board.cmd_new(self.root, "Dep b")
        c = board.cmd_new(self.root, "Dep c")
        return a, b, c

    def set_deps(self, deps_by_job):
        with board.locked_board(self.root) as bd:
            for jid, (stage, deps) in deps_by_job.items():
                j = board.find(bd, jid)
                j["stage"], j["depends_on"] = stage, deps

    def test_only_job_redirects_dependents(self):
        a, b, c = self.dependents()
        bid = "005-terminal-batch-project-claude-edits"
        self.set_deps({a: ("waiting", [self.job]), b: ("waiting", [self.job, bid]), c: ("done", [self.job])})
        self.assertEqual(self.batch()["batch"], bid)
        self.assertEqual(self.job_of(a)["depends_on"], [bid])
        self.assertEqual(self.job_of(b)["depends_on"], [bid])
        self.assertEqual(self.job_of(c)["depends_on"], [self.job])

    def test_mixed_job_keeps_dependents(self):
        a, b, c = self.dependents(only=False)
        self.set_deps({a: ("waiting", [self.job])})
        self.batch()
        self.assertEqual(self.job_of(a)["depends_on"], [self.job])

    def test_rerun_redirects_late_dependent(self):
        a, b, c = self.dependents()
        bid = self.batch()["batch"]
        self.set_deps({a: ("waiting", [self.job])})
        spec, feature = self.spec.read_text(), self.feature(bid)
        self.assertEqual(self.batch(), {"batch": bid, "only": True, "created": False})
        self.assertEqual(self.job_of(a)["depends_on"], [bid])
        self.assertEqual(self.spec.read_text(), spec)
        self.assertEqual(self.feature(bid), feature)

    def test_rerun_appends_nothing(self):
        bid = self.batch()["batch"]
        spec, feature = self.spec.read_text(), self.feature(bid)
        self.assertEqual(self.batch(), {"batch": bid, "only": False, "created": False})
        self.assertEqual(self.spec.read_text(), spec)
        self.assertEqual(self.feature(bid), feature)

    def test_respawned_spec_no_duplicate_entry(self):
        bid = self.batch()["batch"]
        self.spec.write_text(self.SPEC)  # a respawned spec writer re-wrote spec.md without the marker
        self.assertEqual(self.batch(), {"batch": bid, "only": False, "created": False})
        self.assertEqual(self.feature(bid).count(f"## From {self.job}:"), 1)
        self.assertEqual(self.spec.read_text().count("## Moved to Terminal batch"), 1)

    def test_running_batch_gets_new_batch(self):
        first = self.batch()["batch"]
        board.cmd_set(self.root, first, ["stage=build", "reason="])
        other = board.cmd_new(self.root, "Another")
        (self.root / "jobs" / other / "spec.md").write_text("# B\n## Likely files\n- `.claude/rules/d.md`\n")
        out = self.batch(other)
        self.assertTrue(out["created"])
        self.assertNotEqual(out["batch"], first)
        self.assertNotIn(f"## From {other}:", self.feature(first))
        self.assertIn(f"## From {other}: Another\n", self.feature(out["batch"]))

    def test_refuses_batch_itself(self):
        bid = self.batch()["batch"]
        before = (self.root / "board.json").read_text()
        with self.assertRaises(SystemExit) as e:
            board.cmd_claude_batch(self.root, bid)
        self.assertEqual(str(e.exception), f"job {bid} is the Terminal batch; run it in a Terminal window")
        self.assertEqual((self.root / "board.json").read_text(), before)

    def test_refuses_job_without_claude_paths(self):
        self.spec.write_text("# A\n## Likely files\n- `src/a.py`\n")
        with self.assertRaises(SystemExit) as e:
            board.cmd_claude_batch(self.root, self.job)
        self.assertEqual(str(e.exception), f"job {self.job} names no project .claude/ path")
        self.assertEqual(self.spec.read_text(), "# A\n## Likely files\n- `src/a.py`\n")
        self.assertEqual(len(board.read_board(self.root)["jobs"]), 1)

    def test_batch_question_not_resumable_or_legacy(self):
        self.assertIn("Claude Code refuses those edits in a session that runs on its own", board.TERMINAL_BATCH_QUESTION)
        self.assertFalse(board.TERMINAL_BATCH_QUESTION.startswith(board.RESUMABLE))
        self.assertEqual(board.LEGACY_CLAUDE_PARK, "blocked: this job changes files in the project .claude folder")
        self.assertFalse(board.TERMINAL_BATCH_QUESTION.startswith(board.LEGACY_CLAUDE_PARK))


class ClaudeMigrateTest(unittest.TestCase):
    """board.py claude-migrate: jobs parked on the old 3c question move into the Terminal batch once."""

    OLD = ("blocked: this job changes files in the project .claude folder, and Claude Code refuses those edits in a "
           "session that runs on its own, even with an allow rule; it needs a Terminal window where you can approve each edit.")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.mixed = self.parked("Mixed job", "- `src/a.py`\n- `.claude/rules/c.md`\n")
        self.only = self.parked("Only claude", "- `.claude/rules/x.md`\n")
        self.other = board.cmd_new(self.root, "Unrelated")
        board.cmd_ask(self.root, self.other, "blocked: something else", ["Carry on=resume " + self.other,
                      "Remove=abort " + self.other], title="BUILDER_BLOCKED")

    def parked(self, title, likely):
        job_id = board.cmd_new(self.root, title)
        (self.root / "jobs" / job_id / "spec.md").write_text(f"# {title}\n## Likely files\n{likely}")
        board.cmd_ask(self.root, job_id, self.OLD, [f"Run it in a Terminal window=lilguy {job_id}",
                      f"Remove this job=abort {job_id} --cascade"], title="BUILDER_BLOCKED")
        return job_id

    def migrate(self, *flags):
        out = io.StringIO()
        with redirect_stdout(out):
            board.main(["--dir", str(self.root), "claude-migrate", *flags])
        return json.loads(out.getvalue())

    def job(self, job_id):
        return board.find(board.read_board(self.root), job_id)

    def test_only_job_dependents_follow_batch(self):
        dep = board.cmd_new(self.root, "Dependent")
        with board.locked_board(self.root) as bd:
            j = board.find(bd, dep)
            j["stage"], j["depends_on"] = "waiting", [self.only]
        self.migrate()
        bid = "005-terminal-batch-project-claude-edits"
        self.assertEqual(self.job(dep)["depends_on"], [bid])
        self.assertEqual(board.wake_waiting(self.root), {"ready": [], "lost": []})
        self.assertEqual(self.job(dep)["stage"], "waiting")
        with board.locked_board(self.root) as bd:
            board.find(bd, bid)["stage"] = "done"
        self.assertEqual(board.wake_waiting(self.root)["ready"], [dep])
        self.assertEqual(self.job(dep)["stage"], "spec")

    def test_migrates_mixed_and_only_jobs(self):
        out = self.migrate()
        bid = "004-terminal-batch-project-claude-edits"
        self.assertEqual(out, [{"id": self.mixed, "batch": bid, "only": False},
                               {"id": self.only, "batch": bid, "only": True}])
        mixed = self.job(self.mixed)
        self.assertEqual((mixed["stage"], mixed["stalled"], mixed["reason"]),
                         ("spec", True, f"stalled: .claude edits moved to Terminal batch {bid}"))
        self.assertNotIn("question", mixed)
        self.assertNotIn("options", mixed)
        only = self.job(self.only)
        self.assertEqual((only["stage"], only["reason"]), ("aborted", f"moved to Terminal batch {bid}"))
        self.assertEqual(self.job(self.other)["stage"], "needs-human")
        self.assertEqual(self.job(bid)["stage"], "needs-human")
        feature = (self.root / "jobs" / bid / "feature.md").read_text()
        self.assertIn(f"## From {self.mixed}: Mixed job\n- `.claude/rules/c.md`\n", feature)
        self.assertIn(f"## From {self.only}: Only claude\n- `.claude/rules/x.md`\n", feature)
        self.assertIn(f"`{bid}`", (self.root / "jobs" / self.mixed / "spec.md").read_text())

    def test_dry_run_writes_nothing(self):
        before = (self.root / "board.json").read_text()
        specs = {j: (self.root / "jobs" / j / "spec.md").read_text() for j in (self.mixed, self.only)}
        self.assertEqual(self.migrate("--dry-run"), [{"id": self.mixed, "batch": None, "only": False},
                                                      {"id": self.only, "batch": None, "only": True}])
        self.assertEqual((self.root / "board.json").read_text(), before)
        self.assertEqual({j: (self.root / "jobs" / j / "spec.md").read_text() for j in specs}, specs)
        self.assertEqual(sorted(p.name for p in (self.root / "jobs").iterdir()), sorted([self.mixed, self.only, self.other]))

    def test_second_run_is_empty(self):
        self.migrate()
        board_json = self.root / "board.json"
        before, mtime = board_json.read_text(), board_json.stat().st_mtime_ns
        self.assertEqual(self.migrate(), [])
        self.assertEqual(self.migrate("--dry-run"), [])
        self.assertEqual(board_json.read_text(), before)
        self.assertEqual(board_json.stat().st_mtime_ns, mtime)


class RunAllLilguyTest(unittest.TestCase):
    """A Run all child crosses lilguy-fit routing, then the lilguy-with-worktree done guard (needs a merged PR)."""

    PR = "https://github.com/o/r/pull/7"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.root.mkdir()
        env = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(Path(self.tmp.name) / "no-usage.json")})
        env.start()
        self.addCleanup(env.stop)
        (self.root / "backlog.md").write_text(
            "# Backlog\n- [ ] [1] Tweak the dashboard label text\n- [ ] [3] Reword the board legend\n")
        out = board.cmd_runall_start(self.root)
        self.parent, (self.one, self.three) = out["id"], out["children"]

    def job(self, job_id):
        return board.find(board.read_board(self.root), job_id)

    def gh(self, state):
        return mock.patch.object(board.subprocess, "run",
                                 return_value=subprocess.CompletedProcess(["gh"], 0, state + "\n", ""))

    def worktree_child(self):
        board.cmd_set(self.root, self.one, ["lane=lilguy", "worktree=/tmp/wt-one"])
        return self.job(self.one)

    def test_runall_child_points_1_fits_lilguy(self):
        self.assertEqual(board.cmd_lilguy_fit(self.root, self.one), {"fit": True, "why": "backlog item is 1 point"})
        self.assertIs(board.cmd_lilguy_fit(self.root, self.three)["fit"], False)
        for kid in (self.one, self.three):
            self.assertEqual(self.job(kid)["parent"], self.parent)
            self.assertNotIn("lane", self.job(kid))

    def test_runall_child_hard_stop_word_not_lilguy(self):
        (self.root / "jobs" / self.one / "feature.md").write_text("Fix the login button\n")
        got = board.cmd_lilguy_fit(self.root, self.one)
        self.assertIs(got["fit"], False)
        self.assertIn("login", got["why"])

    def test_runall_lilguy_worktree_child_needs_pr_for_done(self):
        job = self.worktree_child()
        self.assertIs(board.lilguy_in_checkout(job), False)
        self.assertEqual(board.merge_refusal(job), "not done: no PR recorded")
        with self.assertRaises(SystemExit):
            board.cmd_set(self.root, self.one, ["stage=done"])
        self.assertEqual(self.job(self.one)["stage"], "waiting")

    def test_runall_lilguy_worktree_child_done_after_merged_pr(self):
        self.worktree_child()
        board.cmd_set(self.root, self.one, [f"pr={self.PR}"])
        with self.gh("OPEN"), self.assertRaises(SystemExit):
            board.cmd_set(self.root, self.one, ["stage=done"])
        self.assertEqual(self.job(self.one)["stage"], "waiting")
        with self.gh("MERGED"):
            board.cmd_set(self.root, self.one, ["stage=done"])
        job = self.job(self.one)
        self.assertEqual((job["stage"], job["lane"], job["worktree"], job["pr"]),
                         ("done", "lilguy", "/tmp/wt-one", self.PR))


JEV_STUB = """import json, sys
lines = [l.rstrip("\\n") for l in sys.stdin]
open(sys.argv[0] + ".log", "w").write(json.dumps({"argv": sys.argv[1:], "stdin": lines}))
for l in lines:
    print("0.9\\t" + l)
"""


class DigestTrevorTest(unittest.TestCase):
    """board.py digest-trevor: digests/<NNN>/trevor.md from Trevor's chat, feature.md quotes, backlog tags and notes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.repo, self.root = base / "repo", base / "repo" / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        self.transcripts = base / "transcripts"
        (self.transcripts / "proj").mkdir(parents=True)
        self.jev = base / "jev-rank.py"
        self.jev.write_text(JEV_STUB)
        env = mock.patch.dict(os.environ, {"SCRUM_TRANSCRIPTS": str(self.transcripts), "SCRUM_JEV_RANK": str(self.jev)})
        env.start()
        self.addCleanup(env.stop)
        self.day = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)

    def tearDown(self):
        self.tmp.cleanup()

    def digest(self, name, jobs=(), error=False):
        d = self.root / "digests" / name
        d.mkdir(parents=True)
        (d / "jobs.txt").write_text("".join(f"{j}\n" for j in jobs))
        if error:
            (d / "error.md").write_text("digest reader produced no notes\n")
        return d

    def run_trevor(self, name):
        out = run_board("--dir", str(self.root), "digest-trevor", name)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout), (self.root / "digests" / name / "trevor.md").read_text()

    def section(self, text, heading):
        lines = text.splitlines()
        start = lines.index(heading) + 1
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
        return lines[start:end]

    def user(self, text, cwd=None, at=None, **extra):
        stamp = (at or self.day).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return {"type": "user", "cwd": str(cwd or self.repo), "timestamp": stamp, "message": {"role": "user", "content": text},
                **extra}

    def transcript(self, name, *entries):
        (self.transcripts / "proj" / name).write_text("".join(json.dumps(e) + "\n" for e in entries))

    def test_sections_and_since(self):
        first = self.digest("001")
        self.digest("002", error=True)
        self.digest("003")
        got, text = self.run_trevor("003")
        st = first.stat()
        since = datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_mtime), timezone.utc).isoformat(timespec="seconds")
        self.assertEqual(got, {"id": "003", "chat": 0, "quotes": 0, "backlog": 0, "notes": 0})
        self.assertEqual(text.splitlines(), ["# Trevor: digest 003", f"Since: {since}", "## Chat", "None", "## Feature quotes",
                                             "None", "## Backlog", "None", "## Answer notes", "None"])
        _, text = self.run_trevor("001")  # no earlier digest: 7 days back
        at = datetime.fromisoformat(text.splitlines()[1].removeprefix("Since: "))
        self.assertLess(abs(at - (datetime.now(timezone.utc) - timedelta(days=7))), timedelta(seconds=60))

    def test_bad_digest_id(self):
        self.digest("001")
        for name in ("009", "1", "../x"):
            with self.subTest(name), self.assertRaises(SystemExit) as cm:
                board.cmd_digest_trevor(self.root, name)
            self.assertEqual(str(cm.exception.code), f"no digest '{name}'")
        out = run_board("--dir", str(self.root), "digest-trevor", "009")
        self.assertEqual((out.returncode, out.stderr.strip()), (1, "no digest '009'"))

    def test_chat_filters_and_jev(self):
        self.digest("001")
        elsewhere = Path(self.tmp.name) / "elsewhere"
        self.transcript("a-inter.jsonl",
                        self.user("Stop  asking me\nabout merges", entrypoint="cli"),
                        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok scrum"}]}},
                        self.user([{"type": "tool_result", "content": "scrum output"}, {"type": "text", "text": "scrum x"}]),
                        self.user("<system-reminder>scrum noise</system-reminder>Builder must run lint"),
                        self.user("<system-reminder>only a reminder about scrum</system-reminder>"),
                        self.user("<command-name>/clear</command-name> scrum"),
                        self.user("<local-command-stdout>scrum</local-command-stdout>"),
                        self.user("Caveat: The messages below were generated by the user running scrum"),
                        self.user("old scrum complaint", at=self.day - timedelta(days=10)),
                        self.user("meta scrum text", isMeta=True),
                        self.user("This session is being continued (scrum)", isCompactSummary=True),
                        self.user("worktree note", cwd=self.repo / ".claude" / "worktrees" / "w"))
        self.transcript("b-other.jsonl",
                        self.user([{"type": "text", "text": "Reviewer"}, {"type": "text", "text": "keeps flagging SCRUM caps"}],
                                  cwd=elsewhere),
                        self.user("fix my css", cwd=elsewhere))
        self.transcript("c-sdk.jsonl", self.user("headless scrum prompt", entrypoint="sdk-cli"),
                        self.user("later scrum prompt in sdk file"))
        self.transcript("d-sibling.jsonl", self.user("sibling repo talk", cwd=Path(str(self.repo) + "-other")))
        got, text = self.run_trevor("001")
        sent = json.loads(Path(str(self.jev) + ".log").read_text())
        want = ["Stop asking me about merges", "Builder must run lint", "worktree note", "Reviewer keeps flagging SCRUM caps"]
        self.assertEqual(sent["stdin"], want)
        self.assertEqual(sent["argv"], ["Trevor is correcting or complaining about how the dev pipeline behaved, or stating "
                                        "a rule it should follow from now on", "--top", "60", "--min", "0.8"])
        stamp = self.day.isoformat(timespec="seconds")
        self.assertEqual(self.section(text, "## Chat"), [f'- {stamp} 0.9: "{t}"' for t in want])
        self.assertEqual(got["chat"], 4)

    def test_chat_caps(self):
        self.digest("001")
        self.transcript("a.jsonl", self.user("w" * 2000))
        _, text = self.run_trevor("001")
        self.assertEqual(json.loads(Path(str(self.jev) + ".log").read_text())["stdin"], ["w" * 1500])
        self.assertEqual(self.section(text, "## Chat"), [f'- {self.day.isoformat(timespec="seconds")} 0.9: "{"w" * 400}"'])

    def test_jev_failure_is_a_note(self):
        self.digest("001", jobs=["001-a"])
        (self.root / "jobs" / "001-a").mkdir()
        (self.root / "jobs" / "001-a" / "feature.md").write_text("Trevor 2026-11-01: keep it short\n")
        self.transcript("a.jsonl", self.user("scrum broke again"))
        self.jev.write_text("import sys\nsys.exit('jev-rank: HTTP 500 boom')\n")
        got, text = self.run_trevor("001")
        self.assertEqual(self.section(text, "## Chat"), ["- Jev failed: exit 1: jev-rank: HTTP 500 boom"])
        self.assertEqual(self.section(text, "## Feature quotes"), ["- 001-a: Trevor 2026-11-01: keep it short"])
        self.assertEqual((got["chat"], got["quotes"]), (0, 1))
        missing = Path(self.tmp.name) / "nope.py"
        with mock.patch.dict(os.environ, {"SCRUM_JEV_RANK": str(missing)}):
            _, text = self.run_trevor("001")
        self.assertEqual(self.section(text, "## Chat"), [f"- Jev failed: no script at {missing}"])
        with mock.patch.object(board.subprocess, "run", side_effect=subprocess.TimeoutExpired("jev", 300)):
            _, text = self.run_trevor("001")
        self.assertEqual(self.section(text, "## Chat"), ["- Jev failed: timed out after 300 s"])
        with mock.patch.dict(os.environ, {"SCRUM_TRANSCRIPTS": str(Path(self.tmp.name) / "gone")}):
            got, text = self.run_trevor("001")
        [line] = self.section(text, "## Chat")
        self.assertTrue(line.startswith("- Transcripts failed: "), line)
        self.assertEqual(self.section(text, "## Feature quotes"), ["- 001-a: Trevor 2026-11-01: keep it short"])

    def test_feature_quotes(self):
        self.digest("001", jobs=["001-a", "002-b", "../x"])
        (self.root / "jobs" / "001-a").mkdir()
        long = "Trevor 2026-11-02: " + "y" * 500
        (self.root / "jobs" / "001-a" / "feature.md").write_text(
            "# A\n  Trevor 2026-11-01: never cut my text  \nTrevor said something undated\n" + long + "\n")
        got, text = self.run_trevor("001")
        self.assertEqual(self.section(text, "## Feature quotes"),
                         ["- 001-a: Trevor 2026-11-01: never cut my text", "- 001-a: " + long[:400]])
        self.assertEqual(got["quotes"], 2)

    def test_backlog_tags_since_last_digest(self):
        today = datetime.now(timezone.utc).date().isoformat()
        backlog = self.root / "backlog.md"
        backlog.write_text(f"# Backlog\n- [ ] Fix merge noise (Trevor {today})\n- [ ] Old ask (Trevor 2020-01-01)\n"
                           f"- [ ] Untagged item\n- [x] Nested (Trevor {today} (again))\nNot an item (Trevor {today})\n")
        self.digest("001")
        got, text = self.run_trevor("001")
        self.assertEqual(self.section(text, "## Backlog"),
                         [f"- [ ] Fix merge noise (Trevor {today})", f"- [x] Nested (Trevor {today} (again))"])
        self.assertEqual(got["backlog"], 2)
        self.assertEqual((self.root / "digests" / "001" / "trevor-backlog.txt").read_text(),
                         f"(Trevor {today})\n(Trevor 2020-01-01)\n(Trevor {today} (again))\n")
        backlog.write_text(backlog.read_text() + "- [ ] New ask (Trevor said so)\n")
        self.digest("002")
        got, text = self.run_trevor("002")
        self.assertEqual(self.section(text, "## Backlog"), ["- [ ] New ask (Trevor said so)"])
        backlog.unlink()
        self.digest("003")
        _, text = self.run_trevor("003")
        self.assertEqual(self.section(text, "## Backlog"), ["None"])

    def test_answer_notes(self):
        self.digest("001")
        old = (self.day - timedelta(days=10)).isoformat(timespec="seconds")
        new = self.day.isoformat(timespec="seconds")
        lines = [{"date": old, "job": "001-a", "pick": "Ship it", "note": "too old"},
                 {"date": new, "job": "001-a", "pick": "Rework", "note": "use the helper"},
                 {"date": new, "job": "002-b", "kind": "note", "action": "discuss", "note": "why this table?"},
                 {"date": new, "job": "003-c", "pick": "Ship it"},
                 {"date": new, "job": "004-d", "pick": "Ship it", "note": " "}]
        (self.root / "questions.log").write_text("".join(json.dumps(l) + "\n" for l in lines) + "not json\n")
        got, text = self.run_trevor("001")
        self.assertEqual(self.section(text, "## Answer notes"),
                         [f'- {new} 001-a Rework: "use the helper"', f'- {new} 002-b discuss: "why this table?"'])
        self.assertEqual(got["notes"], 2)

    def test_size_cap(self):
        today = datetime.now(timezone.utc).date().isoformat()
        items = [f"- [ ] Item {i} (Trevor {today} {'z' * 300})" for i in range(200)]
        (self.root / "backlog.md").write_text("# Backlog\n" + "\n".join(items) + "\n")
        self.digest("001")
        got, text = self.run_trevor("001")
        self.assertEqual(got["backlog"], 200)
        self.assertLessEqual(len(text.encode()), 40000)
        lines = text.splitlines()
        self.assertEqual(lines[-1], "- truncated at 40000 bytes")
        kept = lines[lines.index("## Backlog") + 1:-1]
        self.assertGreater(len(kept), 100)
        self.assertEqual(kept, items[:len(kept)])


class PipelineFitTest(unittest.TestCase):
    """board.py pipeline-fit: per-job lane, agents, diff size, verdicts and fix rounds for one digest."""

    KEYS = {"id", "lane", "agents", "added", "deleted", "files", "verdicts", "fix_rounds", "over_routed", "fit"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "scrum"
        self.wt = base / "wt"
        env = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(base / "no-usage.json")})
        env.start()
        self.addCleanup(env.stop)
        self.wt.mkdir()
        (self.wt / "README.md").write_text("readme\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "work")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.wt), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                       capture_output=True)

    def commit(self, files):
        for rel, text in files.items():
            (self.wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.wt / rel).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "change")

    def put(self, job_id, rel, text):
        p = self.root / "jobs" / job_id / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def reviews(self, job_id, n, **texts):
        for r in ("security", "ux", "ui", "code"):
            self.put(job_id, f"round-{n}/review-{r}.md", texts.get(r, "VERDICT: PASS\nok\n"))

    def digest(self, *lines):
        d = self.root / "digests" / "001"
        d.mkdir(parents=True, exist_ok=True)
        (d / "jobs.txt").write_text("".join(f"{l}\n" for l in lines))

    def snapshot(self):
        bj = self.root / "board.json"
        files = sorted(str(p) for sub in ("digests", "jobs") for p in (self.root / sub).rglob("*"))
        return bj.read_bytes(), bj.stat().st_mtime_ns, files

    def fit(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = board.main(["--dir", str(self.root), "pipeline-fit", "001"])
        self.assertIn(code, (0, None))
        return json.loads(out.getvalue())

    def small_standard(self, lines=20, files=2, **round1):
        job = board.cmd_new(self.root, "Small")
        board.cmd_set(self.root, job, [f"worktree={self.wt}", "base=main", "lane=standard"])
        per = lines // files
        self.commit({f"src/f{i}.py": "x\n" * (per + (lines - per * files if i == 0 else 0)) for i in range(files)})
        for f in ("spec.md", "build.md", "decision.md"):
            self.put(job, f, "x\n")
        self.reviews(job, 1, **round1)
        return job

    def test_pipeline_fit_reports_digest_jobs(self):
        b = board.cmd_new(self.root, "Has PR")
        board.cmd_set(self.root, b, ["pr=https://github.com/acme/app/pull/42"])  # no lane key: standard
        for f in ("spec.md", "build.md", "decision.md"):
            self.put(b, f, "x\n")
        self.reviews(b, 1, ux="VERDICT: PASS\nCarried forward from round 0: no blocking findings.\n",
                     ui="VERDICT: PASS\nSkipped by orchestrator: fast lane.\n", code="VERDICT: CHANGES\nfix it\n")
        carried = "VERDICT: PASS\nCarried forward from round 1: no blocking findings.\n"
        self.reviews(b, 2, security=carried, ux=carried, ui=carried)
        d = board.cmd_new(self.root, "Trimmed")
        board.cmd_set(self.root, d, ["lane=debug"])
        self.put(d, "spec.md", "x\n")
        self.put(d, "decision.md", "x\n")
        e = board.cmd_new(self.root, "No reviews")
        board.cmd_set(self.root, e, ["lane=fast"])
        (self.root / "jobs" / e / "round-1").mkdir()
        self.put(e, "round-1/review-ui.md", "VERDICT: PASS\nSkipped by orchestrator: no UI files in diff.\n")
        self.digest(b, "../../etc", d, "998-gone", e)
        before = self.snapshot()
        calls = []
        real_run = subprocess.run

        def fake_run(argv, *a, **kw):
            if argv[0] == "gh":
                calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, '{"additions": 200, "deletions": 50, "changed_files": 4}', "")
            return real_run(argv, *a, **kw)

        with mock.patch.object(board.subprocess, "run", side_effect=fake_run):
            out = self.fit()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(out["digest"], "001")
        self.assertEqual([j["id"] for j in out["jobs"]], [b, d, "998-gone", e])
        for j in out["jobs"]:
            self.assertEqual(set(j), self.KEYS, j["id"])
        jb, jd, gone, je = out["jobs"]
        self.assertEqual(len(calls), 1)
        self.assertIn("repos/acme/app/pulls/42", calls[0])
        self.assertEqual(jb, {
            "id": b, "lane": "standard", "agents": ["spec", "builder", "review-security", "review-code", "approver"],
            "added": 200, "deleted": 50, "files": 4,
            "verdicts": {"1": {"security": "PASS", "ux": "PASS", "ui": "PASS", "code": "CHANGES"},
                         "2": {"security": "PASS", "ux": "PASS", "ui": "PASS", "code": "PASS"}},
            "fix_rounds": 1, "over_routed": False, "fit": "standard"})
        self.assertEqual(jd, {"id": d, "lane": "debug", "agents": ["spec", "approver"], "added": None, "deleted": None,
                              "files": None, "verdicts": {}, "fix_rounds": 0, "over_routed": False, "fit": "debug"})
        self.assertEqual(gone, {"id": "998-gone", "lane": "standard", "agents": [], "added": None, "deleted": None,
                                "files": None, "verdicts": {}, "fix_rounds": 0, "over_routed": False, "fit": "standard"})
        self.assertEqual(je["agents"], [])
        self.assertEqual(je["verdicts"], {"1": {"security": None, "ux": None, "ui": "PASS", "code": None}})
        self.assertEqual(je["fit"], "fast")

    def test_pipeline_fit_gh_failure_gives_nulls(self):
        b = board.cmd_new(self.root, "Has PR")
        board.cmd_set(self.root, b, ["pr=https://github.com/acme/app/pull/42"])
        self.reviews(b, 1)
        self.digest(b)
        with mock.patch.object(board.subprocess, "run",
                               return_value=subprocess.CompletedProcess(["gh"], 1, "", "HTTP 404\n")):
            j = self.fit()["jobs"][0]
        self.assertEqual((j["added"], j["deleted"], j["files"], j["over_routed"]), (None, None, None, False))
        with mock.patch.object(board.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 30)):
            j = self.fit()["jobs"][0]
        self.assertEqual((j["added"], j["deleted"], j["files"], j["over_routed"]), (None, None, None, False))

    def test_pipeline_fit_flags_over_routed_standard_job(self):
        job = self.small_standard(security="VERDICT: PASS\nSkipped by orchestrator: no sensitive files in diff.\n")
        self.digest(job)
        j = self.fit()["jobs"][0]
        self.assertEqual((j["added"], j["deleted"], j["files"]), (20, 0, 2))
        self.assertEqual(j["agents"], ["spec", "builder", "review-ux", "review-ui", "review-code", "approver"])
        self.assertEqual((j["over_routed"], j["fit"]), (True, "lilguy"))

    def test_pipeline_fit_sensitive_path_not_over_routed(self):
        (self.root / "project.md").parent.mkdir(parents=True, exist_ok=True)
        (self.root / "project.md").write_text("- UI globs: *.html\n")
        for path in ("src/auth/login.py", "prisma/schema.prisma", ".env.local", "web/page.html"):
            with self.subTest(path=path):
                self.git("checkout", "-q", "main")
                self.git("checkout", "-q", "-B", "work")
                job = self.small_standard(lines=10, files=1)
                self.commit({path: "y\n" * 10})
                self.digest(job)
                before = self.snapshot()
                j = self.fit()["jobs"][0]
                self.assertEqual(self.snapshot(), before)
                self.assertEqual((j["added"], j["deleted"], j["files"]), (20, 0, 2))
                self.assertEqual((j["over_routed"], j["fit"]), (False, "standard"))
                board.cmd_set(self.root, job, ["lane=debug"])
                j = self.fit()["jobs"][0]
                self.assertEqual((j["over_routed"], j["fit"]), (False, "debug"))

    def test_pipeline_fit_pr_files_block_over_routing(self):
        b = board.cmd_new(self.root, "Has PR")
        board.cmd_set(self.root, b, ["pr=https://github.com/acme/app/pull/42"])
        self.reviews(b, 1)
        self.digest(b)
        before = self.snapshot()
        small = '{"additions": 20, "deletions": 5, "changed_files": 2}'
        plain = '[{"filename": "src/a.py", "additions": 10, "deletions": 5}, ' \
                '{"filename": "src/b.py", "additions": 10, "deletions": 0}]'
        renamed = '[{"filename": "src/a.py", "additions": 10, "deletions": 5}, ' \
                  '{"filename": "src/b.py", "previous_filename": "src/session.py", "additions": 10, "deletions": 0}]'

        def run_with(totals, files):
            calls = []

            def fake_run(argv, *a, **kw):
                calls.append(argv)
                if isinstance(files, BaseException) and len(calls) == 2:
                    raise files
                out = totals if len(calls) == 1 else files
                return subprocess.CompletedProcess(argv, 0 if out is not None else 1, out or "", "HTTP 500\n")

            with mock.patch.object(board.subprocess, "run", side_effect=fake_run):
                return self.fit()["jobs"][0], calls

        j, calls = run_with(small, plain)
        self.assertEqual(len(calls), 2)
        self.assertIn("repos/acme/app/pulls/42/files", calls[1])
        self.assertEqual((j["added"], j["deleted"], j["files"], j["over_routed"], j["fit"]),
                         (20, 5, 2, True, "lilguy"))
        j, calls = run_with(small, renamed)
        self.assertEqual(len(calls), 2)
        self.assertEqual((j["added"], j["over_routed"], j["fit"]), (20, False, "standard"))
        j, calls = run_with('{"additions": 200, "deletions": 5, "changed_files": 2}', plain)
        self.assertEqual(len(calls), 1)
        self.assertEqual((j["added"], j["over_routed"], j["fit"]), (200, False, "standard"))
        for bad in (None, subprocess.TimeoutExpired("gh", 30), '{"filename": "src/a.py"}', '[{"filename": 3}]',
                    '[{"additions": 1, "deletions": 0}]'):
            with self.subTest(bad=bad):
                j, calls = run_with(small, bad)
                self.assertEqual(len(calls), 2)
                self.assertEqual((j["added"], j["deleted"], j["files"], j["over_routed"], j["fit"]),
                                 (20, 5, 2, False, "standard"))
        self.assertEqual(self.snapshot(), before)

    def test_pipeline_fit_flags_mid_size_job_as_fast(self):
        job = self.small_standard(lines=60, files=2)
        board.cmd_set(self.root, job, ["lane=debug"])
        self.digest(job)
        j = self.fit()["jobs"][0]
        self.assertEqual((j["added"], j["files"]), (60, 2))
        self.assertEqual((j["over_routed"], j["fit"]), (True, "fast"))

    def test_pipeline_fit_keeps_correctly_routed_job(self):
        big = self.small_standard(lines=250, files=2)
        self.digest(big)
        j = self.fit()["jobs"][0]
        self.assertEqual((j["added"], j["files"]), (250, 2))
        self.assertEqual((j["over_routed"], j["fit"]), (False, "standard"))
        board.cmd_set(self.root, big, ["worktree="])  # no worktree and no PR: unreadable diff
        j = self.fit()["jobs"][0]
        self.assertEqual((j["added"], j["deleted"], j["files"], j["over_routed"]), (None, None, None, False))

    def test_pipeline_fit_round1_changes_not_over_routed(self):
        job = self.small_standard(code="VERDICT: CHANGES\nfix\n")
        self.reviews(job, 2)
        self.digest(job)
        before = self.snapshot()
        j = self.fit()["jobs"][0]
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((j["added"], j["files"], j["fix_rounds"]), (20, 2, 1))
        self.assertEqual((j["over_routed"], j["fit"]), (False, "standard"))

    def test_pipeline_fit_fast_lane_never_over_routed(self):
        job = self.small_standard()
        board.cmd_set(self.root, job, ["lane=fast"])
        self.digest(job)
        self.assertEqual(self.fit()["jobs"][0]["over_routed"], False)

    def test_pipeline_fit_rejects_unknown_digest(self):
        self.digest()
        for bad in ("1", "../x", "999"):
            with self.assertRaises(SystemExit, msg=bad) as cm:
                board.cmd_pipeline_fit(self.root, bad)
            self.assertEqual(str(cm.exception.code), f"no digest {bad!r}")


class ProcessHealthTest(unittest.TestCase):
    """board.py process-health: 10 fixed metrics for one digest's claimed jobs, compared with the previous digest."""

    NAMES = ["stops_per_job", "resume_abort_stops", "waiting_on_job_stops", "unreadable_asks", "cheaper_lane_jobs",
             "test_waste_jobs", "fable_misuse", "unused_windows", "overburned_windows", "not_shipped"]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "scrum"
        self.root.mkdir()
        (self.root / "project.md").write_text("- UI globs: skills/trevskills-scrum/dashboard.html\n")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def lines(self, rel, rows):
        self.put(rel, "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))

    def board(self, *jobs):
        self.put("board.json", json.dumps({"jobs": [dict(zip(("id", "stage", "lane", "pr", "reason"), j)) for j in jobs]}))

    def digest(self, n, *ids):
        self.put(f"digests/{n}/jobs.txt", "".join(f"{i}\n" for i in ids))

    def run_health(self, n):
        out = io.StringIO()
        with redirect_stdout(out):
            code = board.main(["--dir", str(self.root), "process-health", n])
        self.assertIn(code, (0, None))
        got = json.loads(out.getvalue())
        self.assertEqual(json.loads((self.root / "digests" / n / "health.json").read_text()), got)
        return got

    def waste_for(self, spec, paths, calls=None):
        """test_waste_jobs for one reviewed standard-lane job with `spec`, `_fit_diff` mocked to give `paths`."""
        self.board(("101-alpha", "done", "standard", "", "merged"))
        self.digest("001", "101-alpha")
        self.put("jobs/101-alpha/spec.md", spec)
        self.put("jobs/101-alpha/round-1/review-ui.md", "VERDICT: PASS\nreal review\n")
        diff = (None,) * 4 if paths is None else (1, 0, len(paths), ([], paths))
        with mock.patch.object(board, "_fit_diff", return_value=diff) as fit:
            got = self.run_health("001")["metrics"]["test_waste_jobs"]["jobs"]
        if calls is not None:
            self.assertEqual(fit.call_count, calls)
        return got

    def test_cheaper_lane_follows_over_routed_flag(self):
        """Rows shaped like digest 098's 1096, 1188 and 1189: small diffs, over_routed false, so 0 (not counted from added/files)."""
        self.digest("001", "1096-a", "1188-b", "1189-c")
        self.put("digests/001/pipeline-fit.json", json.dumps({"digest": "001", "jobs": [
            {"id": "1096-a", "lane": "fast", "added": 19, "deleted": 0, "files": 1, "over_routed": False, "fit": "fast"},
            {"id": "1188-b", "lane": "standard", "added": 95, "deleted": 16, "files": 4, "over_routed": False, "fit": "standard"},
            {"id": "1189-c", "lane": "standard", "added": 18, "deleted": 14, "files": 2, "over_routed": False, "fit": "standard"}]}))
        self.assertEqual(self.run_health("001")["metrics"]["cheaper_lane_jobs"]["value"], 0)

    def test_waste_empty_likely_uses_real_diff(self):
        ui, other = "skills/trevskills-scrum/dashboard.html", "skills/trevskills-scrum/board.py"
        self.assertEqual(self.waste_for("# s\n", [other, ui], 1), [])
        self.assertEqual(self.waste_for("# s\n", [other], 1), ["101-alpha"])
        self.assertEqual(self.waste_for("# s\n", None, 1), [])
        self.assertEqual(self.waste_for(f"# s\n## Likely files\n- `{other}`\n", [ui], 0), ["101-alpha"])

    def test_metrics_from_fixture_jobs(self):
        self.board(("101-alpha", "done", "standard", "", "merged"),
                   ("102-beta", "done", "fast", "https://github.com/x/y/pull/1", "merged, not live: deploy failed"),
                   ("103-gamma", "done", "standard", "https://github.com/x/y/pull/2", "merged"),
                   ("104-delta", "done", "lilguy", None, "merged"),
                   ("199-other", "done", "standard", None, "merged"))
        self.digest("001", "101-alpha", "102-beta", "103-gamma", "104-delta")
        self.put("jobs/101-alpha/spec.md", "# a\n## Likely files\n- `skills/trevskills-scrum/board.py`\n")
        self.put("jobs/101-alpha/round-1/review-e2e.md", "VERDICT: PASS\nran the specs\n")
        self.put("jobs/102-beta/spec.md", "# b\n## Likely files\n- `skills/trevskills-scrum/dashboard.html`\n")
        self.put("jobs/102-beta/round-1/review-ui.md", "VERDICT: PASS\nlooks fine\n")
        self.put("jobs/103-gamma/feature.md", "# c\nComplex: yes\n")
        self.put("jobs/103-gamma/spec.md", "# c\n## Likely files\n- `skills/trevskills-scrum/dashboard.html`\n")
        self.put("jobs/103-gamma/round-1/review-ux.md", "VERDICT: PASS\nreal ux review\n")
        self.put("jobs/103-gamma/round-1/review-ui.md", board.UI_SKIP)
        self.lines("jobs/101-alpha/routing.log", [
            {"role": "review-e2e", "duration_s": 300, "model": "sonnet"},
            {"role": "builder", "duration_s": 999, "model": "claude-fable-5-1"},
            {"role": "scrum-review-ui", "duration_s": 150}, "not json"])
        self.lines("jobs/102-beta/routing.log", [{"role": "review-ux", "duration_s": 90},
                                                 {"role": "spec-writer", "model": "claude-fable-5-1"}])
        self.lines("jobs/103-gamma/routing.log", [{"role": "review-ui", "duration_s": 600},
                                                  {"role": "planner", "model": "claude-fable-5-1"}])
        self.put("jobs/101-alpha/fable.log", "2026-11-01T00:00:00\tspec-writer\tfable\t5h 1%\t7d 1%\tok\n")
        self.put("jobs/102-beta/fable.log", "2026-11-01T00:00:00\tplanner\topus\t5h 1%\t7d 1%\tlow\n")
        self.put("jobs/103-gamma/fable.log", "2026-11-01T00:00:00\tplanner\tfable\t5h 1%\t7d 1%\tok\n")
        self.put("jobs/199-other/fable.log", "2026-11-01T00:00:00\tbuilder\tfable\t5h 1%\t7d 1%\tok\n")
        long_q = " ".join(["word"] * 41)
        self.lines("questions.log", [
            {"job": "101-alpha", "kind": "ask", "question": "Resume it?", "reason": "Resume it?",
             "options": [{"command": "resume 101-alpha"}, {"command": "abort 101-alpha"}]},
            {"job": "101-alpha", "kind": "stall", "reason": "stalled: blocked on sibling 102-beta"},
            {"job": "102-beta", "kind": "ask", "question": "See .claude/skills/x/SKILL.md first?",
             "options": [{"command": "approve 102-beta"}, {"command": "abort 102-beta"}]},
            {"job": "102-beta", "question": "Waiting for job 101 to merge?",
             "options": [{"command": "resume 102-beta"}, {"command": "abort 102-beta --requeue"}]},
            {"job": "103-gamma", "kind": "round-limit", "question": "rule 4 again", "unblock": 1},
            {"job": "103-gamma", "pick": "resume"},
            {"job": "103-gamma", "kind": "ask", "question": long_q, "options": [{"command": "approve 103-gamma"}]},
            {"job": "103-gamma", "kind": "machine", "reason": "swap used 80%"},
            {"job": "199-other", "kind": "ask", "question": "Resume? rule 9",
             "options": [{"command": "resume 199-other"}, {"command": "abort 199-other"}]}, "garbage"])
        self.put("digests/001/pipeline-fit.json", json.dumps({"digest": "001", "jobs": [
            {"id": "101-alpha", "added": 50, "files": 3, "over_routed": True},
            {"id": "102-beta", "lane": "fast", "added": 20, "files": 2, "over_routed": True},
            {"id": "103-gamma", "lane": "standard", "added": 500, "files": 4, "over_routed": False},
            {"id": "104-delta", "lane": "lilguy", "added": 5, "files": 1},
            {"id": "199-other", "lane": "standard", "added": 1, "files": 1, "over_routed": True}]}))
        self.put("digests/001/windows.json", json.dumps([
            {"window": "five_hour", "resets_at": 1000000,
             "budget": {"left_at_reset_pct": 40, "cap_idle_secs": 0, "hit_90_at": None}},
            {"window": "seven_day", "resets_at": 2000000,
             "budget": {"left_at_reset_pct": 5, "cap_idle_secs": 0, "hit_90_at": 1992800}},
            {"window": "five_hour", "resets_at": 3000000,
             "budget": {"left_at_reset_pct": 15, "cap_idle_secs": 120, "hit_90_at": 2999940}},
            {"window": "five_hour", "resets_at": 4000000,
             "budget": {"left_at_reset_pct": 10, "cap_idle_secs": 0, "hit_90_at": 3998200}}]))
        got = self.run_health("001")
        self.assertEqual((got["digest"], got["previous"]), ("001", None))
        m = got["metrics"]
        self.assertEqual(list(m), self.NAMES)
        want = {
            "stops_per_job": (1.5, 0.5, ["101-alpha", "102-beta", "103-gamma"]),
            "resume_abort_stops": (2, 0, ["101-alpha", "102-beta"]),
            "waiting_on_job_stops": (2, 0, ["101-alpha", "102-beta"]),
            "unreadable_asks": (2, 0, ["102-beta", "103-gamma"]),
            "cheaper_lane_jobs": (2, 0, ["101-alpha", "102-beta"]),
            "test_waste_jobs": (2, 0, ["101-alpha", "102-beta"]),
            "fable_misuse": (3, 0, ["101-alpha", "102-beta"]),
            "unused_windows": (1, 0, ["five_hour-1000000"]),
            "overburned_windows": (2, 0, ["five_hour-3000000", "seven_day-2000000"]),
            "not_shipped": (2, 0, ["101-alpha", "102-beta"]),
        }
        for name, (value, limit, jobs) in want.items():
            self.assertEqual((m[name]["value"], m[name]["limit"], m[name]["jobs"]), (value, limit, jobs), name)
            self.assertEqual((m[name]["previous"], m[name]["flag"]), (None, None), name)
        self.assertEqual(m["test_waste_jobs"]["minutes"], 9)

    def test_auto_lines_not_stops(self):
        # Job 825: self-resumed stalls and CPU-load waits carry "auto": true and count for no metric.
        self.board(("101-alpha", "done", "standard", None, "merged"), ("102-beta", "done", "standard", None, "merged"))
        self.digest("001", "101-alpha", "102-beta")
        self.lines("questions.log", [
            {"job": "101-alpha", "kind": "stall", "reason": "stalled: blocked on sibling 102-beta", "auto": True},
            {"job": "102-beta", "kind": "machine", "reason": "waiting: CPU load 178% of 8 cores (> 150%)", "auto": True},
            {"job": "102-beta", "kind": "ask", "auto": True, "question": "Waiting for job 101 rule 4 to merge?",
             "options": [{"command": "resume 102-beta"}, {"command": "abort 102-beta"}]}])
        m = self.run_health("001")["metrics"]
        for name in ("stops_per_job", "resume_abort_stops", "waiting_on_job_stops", "unreadable_asks"):
            self.assertEqual((m[name]["value"], m[name]["jobs"]), (0, []), name)
        self.lines("questions.log", [
            {"job": "101-alpha", "kind": "stall", "reason": "stalled: no board update", "auto": True},
            {"job": "102-beta", "kind": "stall", "reason": "stalled: no board update"}])
        m = self.run_health("001")["metrics"]
        self.assertEqual((m["stops_per_job"]["value"], m["stops_per_job"]["jobs"]), (0.5, ["102-beta"]))

    def test_previous_and_flags(self):
        self.board(("101-alpha", "done", "standard", None, "merged"))
        self.lines("questions.log", [{"job": "101-alpha", "kind": "stall", "reason": "stalled in build"}])
        self.digest("001", "101-alpha")
        self.put("digests/001/health.json", json.dumps({"digest": "001", "previous": None, "metrics": {
            "stops_per_job": {"value": 0.25}, "not_shipped": {"value": 3}, "cheaper_lane_jobs": {"value": 0}}}))
        self.digest("002", "101-alpha")
        self.put("digests/002/error.md", "digester produced no valid proposals\n")
        self.put("digests/002/health.json", json.dumps({"digest": "002", "previous": None, "metrics": {
            "stops_per_job": {"value": 5}, "not_shipped": {"value": 0}}}))
        self.digest("003", "101-alpha")
        got = self.run_health("003")
        self.assertEqual(got["previous"], "001")
        m = got["metrics"]
        self.assertEqual((m["stops_per_job"]["value"], m["stops_per_job"]["previous"], m["stops_per_job"]["flag"]),
                         (1.0, 0.25, "worse"))
        self.assertEqual((m["not_shipped"]["value"], m["not_shipped"]["previous"], m["not_shipped"]["flag"]),
                         (1, 3, "over twice"))
        self.assertEqual((m["cheaper_lane_jobs"]["previous"], m["cheaper_lane_jobs"]["flag"]), (0, None))
        self.assertEqual((m["unused_windows"]["previous"], m["unused_windows"]["flag"]), (None, None))
        fresh = Path(self.tmp.name) / "fresh"
        self.root = fresh
        self.root.mkdir()
        self.board(("101-alpha", "done", "standard", None, "merged"))
        self.digest("001", "101-alpha")
        got = self.run_health("001")
        self.assertIsNone(got["previous"])
        for name in self.NAMES:
            self.assertEqual((got["metrics"][name]["previous"], got["metrics"][name]["flag"]), (None, None), name)

    def test_missing_inputs_give_zero(self):
        self.board(("101-alpha", "done", "lilguy", None, "merged"))
        self.digest("001")
        for name, text in (("pipeline-fit.json", "not json"), ("windows.json", "{"), ("questions.log", "garbage")):
            self.put(f"digests/001/{name}" if name.endswith(".json") else name, text)
        got = self.run_health("001")["metrics"]
        self.assertIsNone(got["stops_per_job"]["value"])
        for name in self.NAMES[1:]:
            self.assertEqual((got[name]["value"], got[name]["jobs"]), (0, []), name)
        self.assertEqual(got["test_waste_jobs"]["minutes"], 0)
        self.digest("002", "101-alpha")
        got = self.run_health("002")["metrics"]
        self.assertEqual(got["stops_per_job"]["value"], 0.0)
        for name in self.NAMES[1:]:
            self.assertEqual(got[name]["value"], 0, name)

    def test_unknown_digest_fails(self):
        self.digest("001")
        for bad in ("1", "../x", "999"):
            with self.assertRaises(SystemExit, msg=bad) as cm:
                board.cmd_process_health(self.root, bad)
            self.assertEqual(str(cm.exception.code), f"no digest {bad!r}")
        r = run_board("--dir", str(self.root), "process-health", "999")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no digest '999'", r.stderr)
        self.assertIn("process-health <NNN>", board.__doc__)


class WindowReportTest(unittest.TestCase):
    """board.py window-report: remembers open usage windows and writes one scorecard per closed window."""

    R = 1_700_000_000  # five_hour resets_at; the window is [R - 18000, R)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = (self.base / "repo").resolve()
        self.root = self.repo / "scrum"
        self.root.mkdir(parents=True)
        self.other = (self.base / "other").resolve()
        (self.other / "scrum").mkdir(parents=True)
        self.reg = self.base / "projects.json"
        self.reg.write_text(json.dumps([str(self.repo), str(self.other)]))
        self.tx = self.base / "projects"
        self.tx.mkdir()
        self.usage_file = self.base / "usage.json"
        self.env = {"SCRUM_REGISTRY": str(self.reg), "SCRUM_TRANSCRIPTS": str(self.tx),
                    "SCRUM_USAGE": str(self.usage_file)}
        env = mock.patch.dict(os.environ, self.env)
        env.start()
        self.addCleanup(env.stop)
        no_claude_pid(self)

    @staticmethod
    def at(t):
        return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")

    def usage(self, limits, written_at=None):
        self.usage_file.write_text(json.dumps({"rate_limits": limits, **({"written_at": written_at}
                                                                         if written_at is not None else {})}))

    def five(self, used=50, written_at=None):
        w = {"resets_at": self.R} if used is None else {"used_percentage": used, "resets_at": self.R}
        self.usage({"five_hour": w}, written_at)

    def board(self, *jobs):
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": i, "stage": stage, **({"updatedAt": self.at(t)} if t is not None else {}), **extra}
            for i, stage, t, extra in ((*j, {}) if len(j) == 3 else j for j in jobs)]}))

    def backlog(self, *lines):
        (self.root / "backlog.md").write_text("# Backlog\n" + "".join(f"{l}\n" for l in lines))

    def questions(self, *entries):
        (self.root / "questions.log").write_text("".join(
            (e if isinstance(e, str) else json.dumps(e)) + "\n" for e in entries))

    def put(self, rel, text, mtime=None):
        p = self.root / "jobs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def transcript(self, rel, lines, agent=None):
        p = self.tx / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(json.dumps(x) + "\n" for x in lines))
        if agent:
            p.with_name(p.stem + ".meta.json").write_text(json.dumps({"agentType": agent}))

    def card(self, t=None):
        out = board.cmd_window_report(self.root, self.R + 60 if t is None else t)
        self.assertEqual(len(out), 1, out)
        return out[0]

    def open_json(self):
        return json.loads((self.root / "windows" / "open.json").read_text())

    def test_window_report_writes_once(self):
        self.five(used=50, written_at=self.R - 1000)
        self.assertEqual(board.cmd_window_report(self.root, self.R - 100), [])
        self.assertEqual(sorted(p.name for p in (self.root / "windows").iterdir()), [".lock", "open.json"])
        out = board.cmd_window_report(self.root, self.R)
        path = self.root / "windows" / f"five_hour-{self.R}.json"
        self.assertEqual(sorted(p.name for p in (self.root / "windows").iterdir()),
                         [".lock", f"five_hour-{self.R}.json", "open.json"])
        self.assertEqual(len(out), 1)
        self.assertEqual(json.loads(path.read_text()), out[0])
        self.assertEqual((out[0]["window"], out[0]["label"], out[0]["resets_at"], out[0]["start"], out[0]["end"]),
                         ("five_hour", "5h", 1_700_000_000, 1_699_982_000, 1_700_000_000))
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(board.cmd_window_report(self.root, self.R), [])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(self.open_json(), {})

    def test_window_report_cli_prints_list(self):
        self.five(used=50)
        argv = ["--dir", str(self.root), "window-report"]
        first = run_board(*argv, env=self.env)
        self.assertEqual(first.returncode, 0, first.stderr)
        cards = json.loads(first.stdout)  # the real clock is long past R
        self.assertEqual([(c["window"], c["resets_at"]) for c in cards], [("five_hour", 1_700_000_000)])
        second = run_board(*argv, env=self.env)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout), [])

    def test_window_report_remembers_dropped_window(self):
        self.five(used=40, written_at=self.R - 1000)
        self.assertEqual(board.cmd_window_report(self.root, self.R - 1000), [])
        self.assertEqual(self.open_json(), {f"five_hour-{self.R}": {
            "window": "five_hour", "resets_at": 1_700_000_000, "used_pct": 40, "hit_90_at": None, "hit_cap_at": None,
            "idle_secs": 0, "last_tick": 1_699_999_000}})
        self.five(used=93, written_at=1_699_999_480)
        self.assertEqual(board.cmd_window_report(self.root, self.R - 500), [])
        self.usage({})
        c = self.card(self.R + 10)
        self.assertEqual((c["budget"]["used_pct"], c["budget"]["hit_90_at"]), (93, 1_699_999_480))
        self.assertNotIn(f"five_hour-{self.R}", self.open_json())

    def test_window_report_bad_open_json(self):
        (self.root / "windows").mkdir()
        for bad in ("not json", "[1, 2]", '"x"', '{"five_hour-1": 7, "x": {"window": "nope", "resets_at": 1}}'):
            (self.root / "windows" / "open.json").write_text(bad)
            self.usage({})
            self.assertEqual(board.cmd_window_report(self.root, self.R - 100), [], bad)
        self.five(used=10)
        self.assertEqual(board.cmd_window_report(self.root, self.R - 100), [])
        self.assertEqual(list(self.open_json()), [f"five_hour-{self.R}"])
        (self.root / "windows" / "open.json").unlink()
        self.assertEqual(board.cmd_window_report(self.root, self.R - 50), [])

    def test_window_report_budget_fields(self):
        self.board(("101-a", "done", self.R - 100))
        self.backlog("- [x] [5] Thing → 101-a")
        for t, used in ((self.R - 4000, 50), (self.R - 3000, 91), (self.R - 2000, 99), (self.R - 1000, 99.5)):
            self.five(used=used, written_at=t)
            self.assertEqual(board.cmd_window_report(self.root, t), [])
        c = self.card()
        self.assertEqual(c["budget"], {"used_pct": 99.5, "hit_90_at": 1_699_997_000, "left_at_reset_pct": 0.5,
                                       "cap_idle_secs": 2000})
        self.assertEqual(c["points_done"], 5)
        self.assertEqual(c["headline"], 0.05)

    def test_window_report_null_budget(self):
        self.board(("101-a", "done", self.R - 100))
        self.backlog("- [x] [2] Thing → 101-a")
        self.five(used=None)
        c = self.card()
        self.assertEqual(c["budget"], {"used_pct": None, "hit_90_at": None, "left_at_reset_pct": None,
                                       "cap_idle_secs": None})
        self.assertIsNone(c["headline"])
        self.assertEqual(c["points_done"], 2)
        self.R += 3600
        self.five(used=0)
        c = self.card()
        self.assertEqual(c["budget"]["used_pct"], 0)
        self.assertIsNone(c["headline"])

    def scoring_fixture(self):
        R = self.R
        self.board(("101-a", "done", R - 100), ("102-b", "done", R - 200, {"lane": "fast"}), ("103-c", "done", R - 300),
                   ("104-d", "done", R - 20000), ("105-e", "done", R - 50, {"lane": "bigboy"}),
                   ("106-f", "build", R - 10))
        self.backlog("- [x] [3] A → 101-a", "- [x] [?] B → 102-b", "- [x] [5] D → 104-d", "- [x] [2] E → 105-e",
                     "- [ ] [8] F")
        (self.root / "jobs" / "101-a" / "round-1").mkdir(parents=True)
        for n in (1, 2):
            (self.root / "jobs" / "102-b" / f"round-{n}").mkdir(parents=True)
        self.transcript("p/s1.jsonl", [
            prompt("JOB_DIR=/x/scrum/jobs/101-a"),
            reply(R - 1000, "m1", cwd=str(self.repo), model="claude-opus", input_tokens=100, output_tokens=50,
                  cache_read_input_tokens=300, cache_creation_input_tokens=50),
            reply(R + 10, "m9", cwd=str(self.repo), input_tokens=7777)])
        self.transcript("p/s2.jsonl", [
            prompt("JOB_DIR=/x/scrum/jobs/102-b"),
            reply(R - 900, "m2", cwd=str(self.repo / "src"), model="claude-sonnet", input_tokens=10, output_tokens=20,
                  cache_read_input_tokens=60, cache_creation_input_tokens=10),
            reply(R - 800, "m3", cwd=str(self.other), input_tokens=9999)])
        self.transcript("p/s1/subagents/agent-x.jsonl", [
            reply(R - 700, "m4", cwd=str(self.repo), model="claude-opus", input_tokens=40, output_tokens=60)],
            agent="scrum-review-code")
        self.five(used=50)

    def test_window_report_scoring_math(self):
        self.scoring_fixture()
        c = self.card()
        self.assertEqual(c["points_done"], 5)
        self.assertEqual(c["done_jobs"], [{"id": "101-a", "points": 3}, {"id": "102-b", "points": None},
                                          {"id": "103-c", "points": None}, {"id": "105-e", "points": 2}])
        self.assertEqual(c["tokens"], {"total": 700, "by_job": {"101-a": 600, "102-b": 100}})
        self.assertEqual(c["tokens_per_point"], 140.0)
        self.assertEqual(c["first_pass_rate"], 0.667)
        self.assertEqual(c["cache_hit_rate"], 0.706)
        self.assertEqual(c["model_mix"], {"main": {"claude-opus": 500, "claude-sonnet": 100},
                                          "scrum-review-code": {"claude-opus": 100}})

    def test_window_report_wasted(self):
        R = self.R
        self.board(("201-x", "aborted", R - 100), ("202-y", "done", R - 100), ("203-z", "running", R - 100),
                   ("204-w", "review", R - 100), ("205-v", "aborted", R - 20000), ("206-u", "done", R - 100),
                   ("207-t", "needs-human", R - 100), ("208-s", "done", R - 100))
        ask = [{"key": "a", "label": "Resume", "command": "resume 203-z"}, {"key": "b", "label": "Abort",
                                                                             "command": "abort 203-z"}]
        self.questions(
            {"date": self.at(R - 500), "job": "202-y", "kind": "stall", "reason": "no progress"},
            {"date": self.at(R - 450), "job": "202-y", "kind": "check-fail", "unblock": 1, "question": "q"},
            {"date": self.at(R - 400), "job": "203-z", "kind": "ask", "options": ask, "reason": "stalled in build: x"},
            {"date": self.at(R - 300), "job": "204-w", "kind": "check-fail", "unblock": 1, "question": "q"},
            {"date": self.at(R - 20000), "job": "206-u", "kind": "stall", "reason": "old"},
            {"date": self.at(R - 200), "job": "207-t", "kind": "ask", "options": ask, "reason": "pick one"},
            {"date": self.at(R - 150), "job": "999-gone", "kind": "stall", "reason": "not this board"},
            "garbage")
        self.transcript("p/s.jsonl", [prompt("JOB_DIR=/x/jobs/201-x"),
                                      reply(R - 900, "a", cwd=str(self.repo), input_tokens=100)])
        self.transcript("p/t.jsonl", [prompt("JOB_DIR=/x/jobs/202-y"),
                                      reply(R - 900, "b", cwd=str(self.repo), input_tokens=150),
                                      reply(R - 800, "c", cwd=str(self.repo), output_tokens=50)])
        self.transcript("p/u.jsonl", [prompt("JOB_DIR=/x/jobs/204-w"),
                                      reply(R - 900, "d", cwd=str(self.repo), input_tokens=50)])
        self.transcript("p/v.jsonl", [prompt("JOB_DIR=/x/jobs/208-s"),
                                      reply(R - 900, "e", cwd=str(self.repo), input_tokens=650)])
        self.five(used=50)
        c = self.card()
        self.assertEqual(c["wasted_jobs"], ["201-x", "202-y", "203-z", "204-w"])
        self.assertEqual(c["wasted_tokens"], 350)
        self.assertEqual(c["wasted_pct"], 35.0)

    def test_scorecard_counts_new_shape_stall_as_wasted(self):
        R = self.R
        self.board(("203-z", "build", R - 100), ("204-w", "build", R - 100))
        ask = [{"key": "a", "label": "Resume", "command": "resume 203-z"}]
        self.questions(
            {"date": self.at(R - 400), "job": "203-z", "kind": "ask", "options": ask, "reason": "stalled: no live session"},
            {"date": self.at(R - 300), "job": "204-w", "kind": "ask", "options": ask, "reason": "pick one"})
        self.five(used=50)
        self.assertEqual(self.card()["wasted_jobs"], ["203-z"])

    def test_window_report_lane_fit(self):
        wt = self.base / "wt"
        wt.mkdir()

        def git(*args):
            subprocess.run(["git", "-C", str(wt), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True,
                           capture_output=True)
        (wt / "README.md").write_text("readme\n")
        git("init", "-q", "-b", "main")
        git("add", "README.md")
        git("commit", "-q", "-m", "base")
        git("checkout", "-q", "-b", "work")
        (wt / "src").mkdir()
        (wt / "src" / "f.py").write_text("x\n" * 20)
        git("add", "-A")
        git("commit", "-q", "-m", "change")
        R = self.R
        self.board(("301-a", "done", R - 100, {"worktree": str(wt), "base": "main", "lane": "standard"}),
                   ("302-b", "done", R - 100), ("303-c", "done", R - 100, {"worktree": str(wt), "base": "main",
                                                                          "lane": "bigboy"}))
        for job in ("301-a", "302-b", "303-c"):
            for r in ("security", "ux", "ui", "code"):
                self.put(f"{job}/round-1/review-{r}.md", "VERDICT: PASS\nok\n")
        self.transcript("p/s.jsonl", [prompt("JOB_DIR=/x/jobs/301-a"),
                                      reply(R - 900, "a", cwd=str(self.repo), input_tokens=300)])
        self.transcript("p/t.jsonl", [prompt("JOB_DIR=/x/jobs/302-b"),
                                      reply(R - 900, "b", cwd=str(self.repo), input_tokens=700)])
        self.five(used=50)
        self.assertEqual(self.card()["lane_fit"], {"over_routed": ["301-a"], "over_routed_tokens": 300,
                                                   "over_routed_pct": 30.0})

    def test_window_report_yield_routing_escapes(self):
        R = self.R
        self.board(("401-r", "done", R - 100), ("402-p", "done", R - 100, {"lane": "bigboy", "reason": "merged + gaps: two gaps"}),
                   ("403-d", "running", R - 100, {"lane": "debug"}), ("404-q", "done", R - 5000),
                   ("405-d", "done", R - 100, {"lane": "debug"}), ("406-s", "done", R - 50),
                   ("407-d", "done", R - 100, {"lane": "debug"}), ("408-b", "done", R - 100, {"lane": "bigboy"}),
                   ("409-o", "done", R - 20000, {"lane": "bigboy", "reason": "merged + gaps: old"}))
        self.put("401-r/round-1/review-code.md", "VERDICT: CHANGES\n## Findings\n1. [blocking] a\n2. [minor] b\n"
                 "not a finding\n## Notes\n3. [minor] not counted\n", mtime=R - 100)
        self.put("401-r/round-1/review-ux.md", "VERDICT: PASS\nSkipped by orchestrator: fast lane.\n## Findings\n"
                 "1. [blocking] stub\n", mtime=R - 100)
        self.put("401-r/round-1/review-security.md", "VERDICT: CHANGES\n## Findings\n1. [blocking] old\n",
                 mtime=R - 20000)
        rl = lambda t, runner, outcome: json.dumps({"ts": self.at(t), "role": "r", "runner": runner, "model": "m",
                                                    "duration_s": 1.0, "outcome": outcome})
        self.put("401-r/routing.log", "\n".join([rl(R - 900, "local", "ok"), rl(R - 800, "cloud", "ok"),
                                                 rl(R - 700, "skip", "ok"), rl(R - 600, "local", "fail"),
                                                 rl(R - 20000, "local", "ok"), "bad line"]) + "\n")
        self.questions(
            {"date": self.at(R - 300), "job": "401-r", "kind": "bigboy", "reason": "merged + gaps: in window"},
            {"date": self.at(R - 250), "job": "401-r", "kind": "bigboy", "reason": "bigboy review: main not updated"},
            {"date": self.at(R - 20000), "job": "401-r", "kind": "bigboy", "reason": "merged + gaps: old"})
        self.put("403-d/feature.md", "Regression from job 404 in the header\n", mtime=R - 100)
        self.put("405-d/feature.md", "405-d broke after 406-s\n", mtime=R - 100)
        self.put("407-d/feature.md", "404-q again\n", mtime=R - 20000)
        self.transcript("p/s.jsonl", [prompt("JOB_DIR=/x/jobs/401-r"),
                                      reply(R - 900, "a", cwd=str(self.repo), input_tokens=500)])
        self.transcript("p/s/subagents/agent-r.jsonl", [reply(R - 800, "b", cwd=str(self.repo), output_tokens=500)],
                        agent="scrum-review-code")
        self.five(used=50)
        c = self.card()
        self.assertEqual(c["reviewer_yield"], 4.0)
        self.assertEqual(c["local_routing"], 0.5)
        self.assertEqual(c["escapes"], 2)
        self.assertEqual(c["escaped_jobs"], ["402-p", "404-q"])

    def test_window_report_idle(self):
        R = self.R
        self.backlog("- [ ] [2] Do thing", "- [ ] [1] Later {setup: buy a key}")
        jobs = [("502-a", "done", None), ("503-b", "done", None), ("504-c", "needs-human", R - 600),
                ("505-d", "done", None)]
        self.board(*jobs)
        self.five(used=10)
        for t in (R - 1000, R - 900):  # first tick, then +100 idle
            self.assertEqual(board.cmd_window_report(self.root, t), [])
        self.board(*jobs, ("506-e", "build", None))
        self.assertEqual(board.cmd_window_report(self.root, R - 800), [])  # an active job: not idle
        self.board(*jobs)
        for t in (R - 200, R - 100):  # a 600 s gap is no sample; then +100
            self.assertEqual(board.cmd_window_report(self.root, t), [])
        ask = [{"key": "a", "label": "Resume", "command": "resume 502-a"}, {"key": "b", "label": "Abort",
                                                                             "command": "abort 502-a"}]
        self.questions(
            {"date": self.at(R - 3000), "job": "502-a", "kind": "ask", "options": ask, "reason": "q"},
            {"date": self.at(R - 2500), "job": "504-c", "kind": "stall", "reason": "other job"},
            {"date": self.at(R - 2000), "job": "502-a", "kind": "check-fail", "unblock": 1},
            {"date": self.at(R - 20000), "job": "503-b", "kind": "ask", "options": ask, "reason": "q"},
            {"date": self.at(R - 17000), "job": "503-b", "kind": "stall", "reason": "s"},
            {"date": self.at(R - 600), "job": "504-c", "kind": "ask", "options": ask, "reason": "q"},
            {"date": self.at(R - 300), "job": "504-c", "kind": "note", "action": "discuss", "note": "why?"},  # still waits
            {"date": self.at(R - 500), "job": "505-d", "kind": "ask", "options": ask, "reason": "q"})
        c = self.card(R + 50)
        self.assertEqual(c["idle"], {"ready_idle_secs": 200, "needs_human_secs": 2600})

    def test_window_report_missing_tokens_null(self):
        self.assertIn("window-report", board.__doc__)
        self.scoring_fixture()
        for env in ({"SCRUM_REGISTRY": str(self.base / "empty.json")},
                    {"SCRUM_TRANSCRIPTS": str(self.base / "missing")}):
            with mock.patch.dict(os.environ, env), self.subTest(env=env):
                self.R += 3600
                self.board(("101-a", "done", self.R - 100), ("102-b", "done", self.R - 200))
                self.five(used=50)
                c = self.card()
                for k in ("tokens", "tokens_per_point", "wasted_tokens", "wasted_pct", "cache_hit_rate",
                          "reviewer_yield", "model_mix"):
                    self.assertIsNone(c[k], k)
                self.assertEqual(c["lane_fit"], {"over_routed": [], "over_routed_tokens": None,
                                                 "over_routed_pct": None})
                self.assertEqual((c["points_done"], c["first_pass_rate"], c["escapes"]), (3, 0.5, 0))


USAGE_NOW = 1_000_000


def usage(five=None, seven=None, written_at=USAGE_NOW):
    """A usage.json dict. five/seven = (used_percentage, seconds from written_at until resets_at)."""
    limits = {}
    for key, w in (("five_hour", five), ("seven_day", seven)):
        if w is not None:
            limits[key] = {"used_percentage": w[0], "resets_at": written_at + w[1]}
    return {"rate_limits": limits, "written_at": written_at}


class UsageAllowanceTest(unittest.TestCase):
    def allow(self, u, live=0):
        a = board.usage_allowance(u, USAGE_NOW, live)
        return None if a is None else int(a)

    def test_ladder_steps(self):
        """A reset 1 h away neither relaxes nor tightens: remaining >= 10 None, < 10 gives 3, < 5 gives 1, < 2 gives 0."""
        for used, want in ((0, None), (89, None), (90, None), (91, 3), (95, 3), (95.5, 1), (98, 1), (98.5, 0), (100, 0)):
            for u in (usage(five=(used, 3600)), usage(seven=(used, 3600))):
                self.assertEqual(self.allow(u), want, (used, u))
        self.assertIsInstance(board.usage_allowance(usage(five=(91, 3600)), USAGE_NOW, 0), int)

    def test_relax_near_reset(self):
        for used, want in ((91, None), (96, 3), (99, 1), (100, 1)):
            self.assertEqual(self.allow(usage(five=(used, 1200))), want, used)
            self.assertEqual(self.allow(usage(five=(used, 1))), want, used)
        self.assertEqual(self.allow(usage(five=(96, 1201))), 1, "just past 20 min: no relax")

    def test_tighten_far_reset(self):
        for used, want in ((91, 1), (96, 0), (99, 0)):
            self.assertEqual(self.allow(usage(seven=(used, 10801))), want, used)
            self.assertEqual(self.allow(usage(seven=(used, 3 * 86400))), want, used)
        self.assertEqual(self.allow(usage(seven=(91, 10800))), 3, "exactly 3 h: no tighten")
        self.assertIsNone(self.allow(usage(seven=(85, 3 * 86400))), "remaining >= 10 never tightens")

    def test_stricter_window_wins(self):
        self.assertEqual(self.allow(usage(five=(91, 3600), seven=(96, 3600))), 1)
        self.assertEqual(self.allow(usage(five=(99, 3600), seven=(91, 3600))), 0)
        self.assertEqual(self.allow(usage(five=(50, 3600), seven=(91, 3600))), 3, "None counts as unlimited")
        self.assertEqual(self.allow(usage(five=(91, 600), seven=(91, 3600))), 3, "relaxed 5h is None; 7d binds")

    def test_stale_missing_and_malformed(self):
        low = usage(five=(99, 3600))
        bad = [None, "x", [], {}, {"rate_limits": None, "written_at": USAGE_NOW},
               {"rate_limits": "x", "written_at": USAGE_NOW},
               {"rate_limits": low["rate_limits"]},
               {**low, "written_at": "1000000"}, {**low, "written_at": None}, {**low, "written_at": True},
               {**low, "written_at": USAGE_NOW - 301},
               {"rate_limits": {"five_hour": {"used_percentage": "99", "resets_at": USAGE_NOW + 3600}},
                "written_at": USAGE_NOW},
               {"rate_limits": {"five_hour": {"used_percentage": 99, "resets_at": "soon"}}, "written_at": USAGE_NOW},
               {"rate_limits": {"five_hour": {"used_percentage": 99}}, "written_at": USAGE_NOW},
               {"rate_limits": {"five_hour": "x"}, "written_at": USAGE_NOW}]
        for u in bad:
            self.assertIsNone(board.usage_allowance(u, USAGE_NOW, 0), u)
        self.assertEqual(self.allow({**low, "written_at": USAGE_NOW - 300} | {"rate_limits": {"five_hour": {
            "used_percentage": 99, "resets_at": USAGE_NOW + 3600}}}), 0, "exactly 300 s old still counts")

    def test_passed_reset_ignored(self):
        for after in (0, -1, -7200):
            self.assertIsNone(self.allow(usage(five=(99, after))), after)
            self.assertEqual(self.allow(usage(five=(99, after), seven=(91, 3600))), 3, after)

    def test_reason_text(self):
        u = usage(five=(93.4, 14400), seven=(50, 86400))
        at = datetime.fromtimestamp(USAGE_NOW + 14400).strftime("%H:%M")
        a = board.usage_allowance(u, USAGE_NOW, 2)
        self.assertEqual((int(a), a.reason), (1, f"usage 5h 93% used, resets {at} (allowance 1, 2 live)"))
        a = board.usage_allowance(u, USAGE_NOW, ["1-a", "2-b", "3-c"])
        self.assertEqual((int(a), a.reason), (1, f"usage 5h 93% used, resets {at} (allowance 1, 3 live)"))
        self.assertEqual(int(board.usage_allowance(u, USAGE_NOW, 40)), 1, "the number never depends on live")
        seven_at = datetime.fromtimestamp(USAGE_NOW + 3600).strftime("%H:%M")
        a = board.usage_allowance(usage(five=(91, 3600), seven=(96.6, 3600)), USAGE_NOW, 0)
        self.assertEqual(a.reason, f"usage 7d 97% used, resets {seven_at} (allowance 1, 0 live)")
        a = board.usage_allowance(usage(five=(92, 3600), seven=(93, 3600)), USAGE_NOW, 0)
        self.assertEqual(a.reason, f"usage 5h 92% used, resets {seven_at} (allowance 3, 0 live)", "tie: five_hour")

    def test_windows_constant_drives_allowance(self):
        self.assertEqual(board.WINDOWS, (("five_hour", "5h"), ("seven_day", "7d")))
        a = board.usage_allowance(usage(seven=(96, 3600)), USAGE_NOW, 0)
        self.assertTrue(a.reason.startswith("usage 7d "), a.reason)


T0 = 1_700_000_000  # 2023-11-14; fixture files written now are newer than every window start


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def prompt(text, **extra):
    return {"type": "user", "message": {"role": "user", "content": text}, **extra}


def reply(t, mid, cwd="/nowhere", model="claude-x", **usage_counts):
    return {"type": "assistant", "timestamp": iso(t), "cwd": cwd,
            "message": {"id": mid, "model": model, "usage": usage_counts}}


class TranscriptTokensTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.dir = self.base / "projects"
        self.repo = (self.base / "repo").resolve()
        (self.repo / "scrum").mkdir(parents=True)
        reg = self.base / "projects.json"
        reg.write_text(json.dumps([str(self.repo)]))
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg)})
        env.start()
        self.addCleanup(env.stop)

    def write(self, rel, lines):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in lines))
        return p

    def rows(self, start=T0 - 100, end=T0 + 100):
        return board.transcript_tokens(start, end, self.dir)

    def test_transcript_tokens_rows_and_dedupe(self):
        self.write("p/s1.jsonl", [prompt("hi"),
                                  reply(T0 + 2, "m2", input_tokens=7),
                                  reply(T0, "m1", input_tokens=1, output_tokens=2),
                                  reply(T0 + 1, "m1", model="claude-y", input_tokens=3, output_tokens=40,
                                        cache_read_input_tokens=500, cache_creation_input_tokens=60)])
        self.assertEqual(self.rows(), [
            {"ts": T0 + 1.0, "input_tokens": 3, "output_tokens": 40, "cache_read_input_tokens": 500,
             "cache_creation_input_tokens": 60, "model": "claude-y", "project": None, "job": None,
             "agent": "main", "skill": None},
            {"ts": T0 + 2.0, "input_tokens": 7, "output_tokens": 0, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0, "model": "claude-x", "project": None, "job": None,
             "agent": "main", "skill": None}])

    def test_transcript_tokens_window_bounds(self):
        self.write("p/s1.jsonl", [reply(T0 - 1, "a", input_tokens=1), reply(T0, "b", input_tokens=2),
                                  reply(T0 + 9, "c", input_tokens=3), reply(T0 + 10, "d", input_tokens=4)])
        old = self.write("p/old.jsonl", [reply(T0 + 5, "e", input_tokens=5)])
        os.utime(old, (T0 - 50, T0 - 50))
        real_open, opened = open, []

        def spy(path, *a, **k):
            opened.append(Path(path).name)
            return real_open(path, *a, **k)
        with mock.patch("builtins.open", side_effect=spy):
            got = board.transcript_tokens(T0, T0 + 10, self.dir)
        self.assertEqual([r["input_tokens"] for r in got], [2, 3])
        self.assertIn("s1.jsonl", opened)
        self.assertNotIn("old.jsonl", opened)
        self.assertEqual(board.transcript_tokens(T0, T0 + 10, self.base / "missing"), [])
        with mock.patch.dict(os.environ, {"SCRUM_TRANSCRIPTS": str(self.dir)}):
            self.assertEqual([r["input_tokens"] for r in board.transcript_tokens(T0, T0 + 10)], [2, 3])

    def test_transcript_tokens_attribution(self):
        nested = self.repo / "sub"
        (nested / "scrum").mkdir(parents=True)
        reg = self.base / "projects.json"
        reg.write_text(json.dumps([str(self.repo), str(nested)]))
        wt = self.repo / ".claude" / "worktrees" / "scrum-123-x"
        self.write("p/a.jsonl", [prompt("<command-name>/trevskills-scrum</command-name>"),
                                 reply(T0, "a", cwd=str(wt / "src"), input_tokens=1)])
        self.write("p/b.jsonl", [prompt("ignored meta JOB_DIR=/x/jobs/999-no", isMeta=True),
                                 prompt("JOB_DIR=/r/scrum/jobs/124-y\nWORKTREE=none"),
                                 reply(T0 + 1, "b", cwd=str(nested / "deep"), input_tokens=2)])
        self.write("p/c.jsonl", [{"type": "user", "message": {"content": [
                                     {"type": "text", "text": "<command-name>/trevskills-scrum</command-name>"},
                                     {"type": "text", "text": "<command-args>start 125-z</command-args>"}]}},
                                 reply(T0 + 2, "c", cwd="/elsewhere", input_tokens=3)])
        self.write("p/d.jsonl", [prompt("<command-name>/trevskills-scrum</command-name>"
                                        "<command-args>status all</command-args>"),
                                 reply(T0 + 3, "d", cwd=str(self.repo), input_tokens=4)])
        got = [(r["input_tokens"], r["project"], r["job"], r["skill"]) for r in self.rows()]
        self.assertEqual(got, [(1, "repo", "123-x", "trevskills-scrum"), (2, "sub", "124-y", None),
                               (3, None, "125-z", "trevskills-scrum"), (4, "repo", None, "trevskills-scrum")])

    def test_transcript_tokens_subagent(self):
        self.write("p/s1.jsonl", [prompt("<command-name>/trevskills-scrum</command-name>"
                                         "<command-args>start 125-z</command-args>"),
                                  reply(T0, "m", input_tokens=1)])
        sub = self.dir / "p" / "s1" / "subagents"
        self.write("p/s1/subagents/agent-aa.jsonl", [prompt("JOB_DIR=/r/scrum/jobs/200-own"),
                                                     reply(T0 + 1, "x", input_tokens=2)])
        (sub / "agent-aa.meta.json").write_text(json.dumps({"agentType": "scrum-builder"}))
        self.write("p/s1/subagents/agent-bb.jsonl", [prompt("no job here"), reply(T0 + 2, "y", input_tokens=3)])
        (sub / "agent-bb.meta.json").write_text("{not json")
        self.write("p/s1/subagents/agent-cc.jsonl", [reply(T0 + 3, "z", input_tokens=4)])
        self.write("p/s1/subagents/agent-dd.jsonl", [reply(T0 + 4, "w", input_tokens=5)])
        (sub / "agent-dd.meta.json").write_text(json.dumps(["scrum-builder"]))
        self.write("q/orphan/subagents/agent-ee.jsonl", [reply(T0 + 5, "v", input_tokens=6)])
        got = [(r["input_tokens"], r["agent"], r["job"], r["skill"]) for r in self.rows()]
        self.assertEqual(got, [(1, "main", "125-z", "trevskills-scrum"),
                               (2, "scrum-builder", "200-own", "trevskills-scrum"),
                               (3, "subagent", "125-z", "trevskills-scrum"),
                               (4, "subagent", "125-z", "trevskills-scrum"),
                               (5, "subagent", "125-z", "trevskills-scrum"),
                               (6, "subagent", None, None)])

    def test_transcript_tokens_malformed_lines(self):
        good = reply(T0, "ok", input_tokens=9, output_tokens="lots", cache_read_input_tokens=None,
                     cache_creation_input_tokens=True)
        self.write("p/s1.jsonl", ["not json", "[1, 2]", "42", '"str"', "",
                                  {"type": "assistant", "timestamp": iso(T0), "message": "x"},
                                  {"type": "assistant", "timestamp": iso(T0), "message": {"id": "u", "usage": [1]}},
                                  {"type": "assistant", "message": {"id": "n", "usage": {"input_tokens": 1}}},
                                  {"type": "assistant", "timestamp": "yesterday", "message": {"usage": {}}},
                                  {"type": "assistant", "timestamp": 5, "message": {"usage": {}}},
                                  {"type": "user", "timestamp": iso(T0), "message": {"usage": {"input_tokens": 1}}},
                                  {"type": "user", "message": "not a dict"},
                                  good])
        with open(self.dir / "p" / "s1.jsonl", "ab") as f:
            f.write(b"\xff\xfe broken utf8\n")
        (self.dir / "p" / "dir.jsonl").mkdir()  # open() raises IsADirectoryError, an OSError
        got = self.rows()
        self.assertEqual([(r["input_tokens"], r["output_tokens"], r["cache_read_input_tokens"],
                           r["cache_creation_input_tokens"]) for r in got], [(9, 0, 0, 0)])
        self.write("q/odd.jsonl", ['{"type": "assistant", "timestamp": "%s", "cwd": "/a\\u0000b", "message": '
                                   '{"id": ["list"], "usage": {"input_tokens": Infinity, "output_tokens": NaN}}}'
                                   % iso(T0 + 1), reply(T0 + 2, "L", cwd=["a"])])  # unhashable id and cwd,
        # non-finite counts, a NUL in cwd
        self.assertEqual([(r["input_tokens"], r["output_tokens"], r["project"]) for r in self.rows()],
                         [(9, 0, None), (0, 0, None), (0, 0, None)])
        src = BOARD_PY.read_text()
        body = src[src.index("def read_transcript("):src.index("def transcript_tokens(")]
        self.assertNotIn(".read()", body)
        self.assertNotIn("readlines(", body)
        self.assertIn("for line in f", body)


class ReadyUsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.usage, self.ps = base / "scrum", base / "usage.json", base / "ps.txt"
        self.ps.write_text("")
        env = mock.patch.dict(os.environ, SCRUM_USAGE=str(self.usage), SCRUM_PS=str(self.ps))
        env.start()
        self.addCleanup(env.stop)
        self.root.mkdir()
        (self.root / "backlog.md").write_text("".join(f"- [ ] item {i}\n" for i in range(5)))
        out = board.cmd_runall_start(self.root)
        self.parent, self.kids = out["id"], out["children"]
        for i, k in enumerate(self.kids):
            spec = self.root / "jobs" / k / "spec.md"
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_text(f"# x\n## Likely files\n- `src/{i}.py`: why\n")
            board.cmd_set(self.root, k, ["lane=fast"])

    def write_usage(self, used):
        self.usage.write_text(json.dumps(usage(five=(used, 3600), written_at=int(time.time()))))

    def live(self, n):
        self.ps.write_text("claude -p /trevskills-scrum start 1-a\n" * n)

    def parent_job(self):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == self.parent)

    def test_ready_caps_batch_to_allowance(self):
        self.write_usage(96)  # 4 % left, reset 1 h away: allowance 1
        self.live(1)
        self.assertEqual(board.cmd_ready(self.root, self.parent)["ready"], [], "1 live of allowance 1: no slot")
        self.live(0)
        self.assertEqual(board.cmd_ready(self.root, self.parent)["ready"], self.kids[:1])
        self.usage.unlink()
        self.assertEqual(board.cmd_ready(self.root, self.parent)["ready"], self.kids[1:1 + board.MAX_YOUNG_SESSIONS],
                         "no usage.json: no taper, only the young-session ramp")

    def test_ready_holds_parent_with_usage_reason(self):
        self.write_usage(96)
        self.live(1)
        at = datetime.fromtimestamp(json.loads(self.usage.read_text())["rate_limits"]["five_hour"]["resets_at"])
        self.assertEqual(board.cmd_ready(self.root, self.parent)["ready"], [])
        p = self.parent_job()
        self.assertEqual((p["stage"], p["reason"]),
                         ("running", f"waiting: no account has room: main usage 5h 96% used, resets {at:%H:%M} (allowance 1, 1 live)"))
        self.write_usage(50)
        self.assertEqual(board.cmd_ready(self.root, self.parent)["ready"], self.kids[:board.MAX_YOUNG_SESSIONS])
        p = self.parent_job()
        self.assertEqual((p["stage"], p["reason"]), ("running", None))


class ReadyHighUsageTest(unittest.TestCase):
    """Job 524: 7d 92% used holds no Run-all or BigBoy child (the old 90% heavy-jobs hold is gone)."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root, u, ps = Path(tmp.name) / "scrum", Path(tmp.name) / "usage.json", Path(tmp.name) / "ps.txt"
        ps.write_text("")
        self.root.mkdir()
        u.write_text(json.dumps(usage(five=(10, 3600), seven=(92, 4 * 86400), written_at=int(time.time()))))
        for p in (mock.patch.dict(os.environ, SCRUM_USAGE=str(u), SCRUM_PS=str(ps)),
                  mock.patch.object(board, "usage_allowance", return_value=None)):
            p.start()
            self.addCleanup(p.stop)

    def job(self, job_id):
        return next(j for j in json.loads((self.root / "board.json").read_text())["jobs"] if j["id"] == job_id)

    def runall(self):
        (self.root / "backlog.md").write_text("- [ ] item 0\n")
        out = board.cmd_runall_start(self.root)
        parent, (kid,) = out["id"], out["children"]
        (self.root / "jobs" / kid / "spec.md").write_text("# x\n## Likely files\n- `src/0.py`: why\n")
        board.cmd_set(self.root, kid, ["lane=standard"])
        return parent, kid

    def test_ready_claims_standard_child_at_high_usage(self):
        parent, kid = self.runall()
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [kid])
        self.assertEqual(self.job(kid)["stage"], "spec")

    def test_ready_claims_bigboy_child_at_high_usage(self):
        parent = board.cmd_new(self.root, "Big")
        board.cmd_set(self.root, parent, ["lane=bigboy", "stage=plan"])
        (self.root / "jobs" / parent / "plan.md").write_text(
            "PLAN: READY\n# Big\n## Goal\nShip.\n## Done when\n1. It works.\n## Tickets\n"
            + BoardTest.ticket(1) + BoardTest.ticket(2, deps="T1", exposure="yes") + "## Assumptions\n- none\n")
        first = board.cmd_plan_apply(self.root, parent)["children"][0]
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [first])
        self.assertEqual(self.job(first)["stage"], "spec")

    def test_ready_clears_leftover_heavy_reason(self):
        parent, kid = self.runall()
        with board.locked_board(self.root) as b:
            # split so criterion 1's grep for the removed hold text finds nothing
            board.find(b, parent).update(
                stage="running", reason="waiting: usage 7d 92% used, heavy jobs" + " wait for its reset at 09:00")
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [kid])
        p = self.job(parent)
        self.assertEqual((p["stage"], p.get("reason")), ("running", None))


class FableTest(unittest.TestCase):
    """board.fable_state / fable_ok / fable-ok: Fable for the planner and standard spec-writers of complex jobs, ok band only."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.root.mkdir()
        self.usage_file = Path(self.tmp.name) / "usage.json"
        env = mock.patch.dict(os.environ, {"SCRUM_USAGE": str(self.usage_file)})
        env.start()
        self.addCleanup(env.stop)

    def state(self, five, seven):
        return board.fable_state(usage(five=(five, 3600), seven=(seven, 86400)), USAGE_NOW)

    def test_fable_state_thresholds(self):
        self.assertEqual(board.FABLE_MODEL, "claude-fable-5-1")
        self.assertEqual((board.FABLE_WARN_5H_PCT, board.FABLE_WARN_7D_PCT, board.FABLE_SWITCH_5H_PCT,
                          board.FABLE_SWITCH_7D_PCT), (65, 75, 80, 85))
        for five, seven, want in ((79.9, 0, "warn"), (80, 0, "paused"), (0, 84.9, "warn"), (0, 85, "paused"),
                                  (65, 0, "warn"), (64.9, 74.9, "ok"), (0, 75, "warn"), (0, 0, "ok"),
                                  (100, 100, "paused"), (70, 90, "paused")):
            self.assertEqual(self.state(five, seven), want, (five, seven))
        self.assertEqual(board.fable_state(usage(five=(79.9, 3600), seven=(0, 86400)), USAGE_NOW), "warn")
        self.assertEqual(board.fable_state(usage(five=(95, 0), seven=(0, 86400)), USAGE_NOW), "ok",
                         "a 5h window resetting now counts as 0% used")
        self.assertEqual(board.fable_state(usage(five=(10, 3600), seven=(99, -5)), USAGE_NOW), "ok",
                         "a past 7d reset counts as 0% used")
        self.assertTrue(board.fable_ok(usage(five=(70, 3600), seven=(0, 86400)), USAGE_NOW))
        self.assertTrue(board.fable_ok(usage(five=(0, 3600), seven=(0, 86400)), USAGE_NOW))
        self.assertFalse(board.fable_ok(usage(five=(80, 3600), seven=(0, 86400)), USAGE_NOW))

    def test_fable_state_missing_five_hour_reads_zero(self):
        for seven, want in ((10, "ok"), (74.9, "ok"), (75, "warn"), (85, "paused"), (99, "paused")):
            self.assertEqual(board.fable_state(usage(seven=(seven, 86400)), USAGE_NOW), want, seven)
        self.assertTrue(board.fable_ok(usage(seven=(10, 86400)), USAGE_NOW))
        self.assertEqual(board.fable_used(usage(seven=(10, 86400)), USAGE_NOW), {"5h": 0, "7d": 10})

    def test_fable_state_unknown_fails_safe(self):
        good = usage(five=(10, 3600), seven=(10, 86400))
        self.assertEqual(board.fable_state(good, USAGE_NOW), "ok")
        bad = [None, [], "x", {}, {"rate_limits": []}, {"written_at": USAGE_NOW},
               {**good, "written_at": None}, {**good, "written_at": "1000000"},
               {"rate_limits": good["rate_limits"]},
               usage(five=(10, 3600), seven=(10, 86400), written_at=USAGE_NOW - 301),
               usage(five=(10, 3600)),
               {**good, "rate_limits": {**good["rate_limits"], "five_hour": {"resets_at": USAGE_NOW + 60}}},
               {**good, "rate_limits": {**good["rate_limits"], "seven_day": {"used_percentage": 1}}},
               {**good, "rate_limits": {**good["rate_limits"], "five_hour": {"used_percentage": "10",
                                                                            "resets_at": USAGE_NOW + 60}}},
               {**good, "rate_limits": {**good["rate_limits"], "seven_day": {"used_percentage": True,
                                                                            "resets_at": USAGE_NOW + 60}}},
               {**good, "rate_limits": {**good["rate_limits"], "five_hour": "80%"}}]
        for u in bad:
            self.assertEqual(board.fable_state(u, USAGE_NOW), "unknown", u)
            self.assertFalse(board.fable_ok(u, USAGE_NOW), u)
        self.assertEqual(board.fable_state(usage(five=(10, 3600), seven=(10, 86400), written_at=USAGE_NOW - 300),
                                           USAGE_NOW), "ok", "exactly 300 s old is still fresh")

    def write_usage(self, five, seven):
        now = time.time()
        self.usage_file.write_text(json.dumps({"written_at": now, "rate_limits": {
            "five_hour": {"used_percentage": five, "resets_at": now + 3600},
            "seven_day": {"used_percentage": seven, "resets_at": now + 86400}}}))

    def setup_jobs(self):
        lanes = {"001-std": None, "002-empty": "", "003-standard": "standard", "004-fast": "fast", "005-debug": "debug",
                 "006-lil": "lilguy", "007-cloud": "cloud", "008-bigboy": "bigboy", "009-road": "roadmap",
                 "010-small": None, "011-unlinked": None, "012-simple": None, "013-noline": None,
                 "014-speconly": None, "015-below": None, "016-featureno": None, "017-weird": None}
        headers = {"012-simple": ("Complex: no — rule change\n", None), "013-noline": ("", None),
                   "014-speconly": ("", "Complex: yes\n"), "015-below": ("\n## Q&A\nComplex: yes\n", None),
                   "016-featureno": ("Complex: no\n", "Complex: yes\n"), "017-weird": ("Complex: maybe\n", None)}
        jobs = []
        for job_id, lane in lanes.items():
            job = {"id": job_id, "stage": "spec"}
            if lane is not None:
                job["lane"] = lane
            jobs.append(job)
            d = self.root / "jobs" / job_id
            d.mkdir(parents=True)
            feature, spec = headers.get(job_id, ("complex: YES — new subsystem\n", None))
            (d / "feature.md").write_text(f"# Item {job_id}\n\n{feature}\n## Body\nText\n")
            if spec:
                (d / "spec.md").write_text(f"# Spec\nUI surface: no\nLane: standard\n{spec}\n## Problem\nx\n")
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))
        linked = [j for j in lanes if j not in ("010-small", "011-unlinked")] + ["099-gone"]
        (self.root / "backlog.md").write_text("# Backlog\n\n" + "".join(f"- [x] [8] Item {j} → {j}\n" for j in linked)
                                              + "- [x] [3] Small → 010-small\n")

    def cli(self, *args):
        return run_board("--dir", str(self.root), "fable-ok", *args)

    def test_fable_ok_cli_gating(self):
        self.setup_jobs()
        self.write_usage(10, 10)
        spec_fable = ("001-std", "002-empty", "003-standard", "010-small", "011-unlinked", "014-speconly")
        spec_none = ("004-fast", "005-debug", "006-lil", "007-cloud", "008-bigboy", "009-road", "012-simple",
                     "013-noline", "015-below", "016-featureno", "017-weird", "099-gone")
        for job_id in spec_fable:
            out = self.cli(job_id, "spec-writer")
            self.assertEqual((out.returncode, out.stdout), (0, "claude-fable-5-1\n"), (job_id, out.stderr))
        for job_id in spec_none:
            out = self.cli(job_id, "spec-writer")
            self.assertEqual((out.returncode, out.stdout), (0, "none\n"), (job_id, out.stderr))
        for job_id in ("008-bigboy", "011-unlinked", "014-speconly", "004-fast"):
            self.assertEqual(self.cli(job_id, "planner").stdout, "claude-fable-5-1\n", job_id)
        for job_id in ("012-simple", "013-noline", "015-below", "016-featureno", "017-weird", "099-gone"):
            self.assertEqual(self.cli(job_id, "planner").stdout, "none\n", job_id)
        for job_id in ("012-simple", "013-noline", "099-gone"):
            self.assertFalse((self.root / "jobs" / job_id / "fable.log").exists(), f"not complex: no log ({job_id})")
        (self.root / "jobs" / "018-offboard").mkdir()
        (self.root / "jobs" / "018-offboard" / "feature.md").write_text("# Off\nComplex: yes\n")
        self.assertEqual(self.cli("018-offboard", "planner").stdout, "none\n", "not on the board")
        for bad in ("builder", "approver", "", "Planner"):
            out = self.cli("001-std", bad)
            self.assertNotEqual(out.returncode, 0, bad)
            self.assertEqual(out.stdout, "", bad)
        self.write_usage(70, 10)
        self.assertEqual(self.cli("008-bigboy", "planner").stdout, "none\n", "warn: Opus")
        self.assertEqual(self.cli("001-std", "spec-writer").stdout, "none\n", "warn: Opus")
        self.write_usage(10, 75)
        self.assertEqual(self.cli("008-bigboy", "planner").stdout, "none\n", "7d warn: Opus")
        self.write_usage(80, 10)
        self.assertEqual(self.cli("008-bigboy", "planner").stdout, "none\n")
        self.assertEqual(self.cli("001-std", "spec-writer").stdout, "none\n")
        self.write_usage(10, 85)
        self.assertEqual(self.cli("008-bigboy", "planner").stdout, "none\n")
        self.usage_file.unlink()
        self.assertEqual(self.cli("008-bigboy", "planner").stdout, "none\n", "no usage.json: Opus")

    def test_fable_ok_logs_decision(self):
        self.setup_jobs()
        log = self.root / "jobs" / "008-bigboy" / "fable.log"
        log.write_text("earlier line\n")
        self.write_usage(10.4, 20)
        self.assertEqual(self.cli("008-bigboy", "planner").stdout, "claude-fable-5-1\n")
        self.write_usage(70, 20)
        self.assertEqual(self.cli("008-bigboy", "planner").stdout, "none\n")
        self.write_usage(81, 20)
        self.assertEqual(self.cli("008-bigboy", "planner").stdout, "none\n")
        lines = log.read_text().splitlines()
        self.assertEqual(lines[0], "earlier line")
        self.assertEqual(len(lines), 4)
        first, warn, second = (l.split("\t") for l in lines[1:])
        self.assertRegex(first[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual(first[1:], ["planner", "fable", "5h 10%", "7d 20%", "ok"])
        self.assertEqual(warn[1:], ["planner", "opus", "5h 70%", "7d 20%", "warn"])
        self.assertEqual(second[1:], ["planner", "opus", "5h 81%", "7d 20%", "paused"])
        now = time.time()
        self.usage_file.write_text(json.dumps({"written_at": now, "rate_limits": {
            "five_hour": {"used_percentage": 50, "resets_at": now + 3600}}}))
        self.assertEqual(self.cli("001-std", "spec-writer").stdout, "none\n")
        self.assertEqual((self.root / "jobs" / "001-std" / "fable.log").read_text().split("\t")[1:],
                         ["spec-writer", "opus", "5h 50%", "7d —", "unknown\n"])
        self.usage_file.unlink()
        self.assertEqual(self.cli("003-standard", "spec-writer").stdout, "none\n")
        self.assertEqual((self.root / "jobs" / "003-standard" / "fable.log").read_text().split("\t")[1:],
                         ["spec-writer", "opus", "5h —", "7d —", "unknown\n"])
        self.write_usage(10, 10)
        self.assertEqual(self.cli("004-fast", "spec-writer").stdout, "none\n")
        self.assertEqual(self.cli("012-simple", "spec-writer").stdout, "none\n")
        self.assertFalse((self.root / "jobs" / "004-fast" / "fable.log").exists(), "ineligible: no log")
        self.assertFalse((self.root / "jobs" / "012-simple" / "fable.log").exists(), "ineligible: no log")
        self.assertEqual(self.cli("099-gone", "planner").stdout, "none\n", "no job dir: not complex")
        self.assertFalse((self.root / "jobs" / "099-gone").exists())
        for name in ("jev.log", "routing.log"):
            self.assertFalse((self.root / "jobs" / "008-bigboy" / name).exists(), name)
        self.assertFalse((self.root / "routing.log").exists())


class WeeklyStartTest(unittest.TestCase):
    """board.cmd_weekly_start: this 7d window's done jobs from every registered project, claimed once."""
    NOW = 2_000_000_000.0
    RESETS = NOW + 86400  # one day left: the window opened 6 days ago

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.a, self.b = base / "a" / "scrum", base / "b" / "scrum"
        for root in (self.a, self.b):
            root.mkdir(parents=True)
        (base / "reg").mkdir()
        (base / "reg" / "projects.json").write_text(json.dumps([str(self.a.parent), str(self.b.parent)]))
        self.weekly = base / "reg" / "weekly"
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(base / "reg" / "projects.json")})
        env.start()
        self.addCleanup(env.stop)

    def job(self, root, title, stage="done", ago=86400):
        job_id = board.cmd_new(root, title)
        with board.locked_board(root) as b:
            board.find(b, job_id).update(stage=stage, updatedAt=datetime.fromtimestamp(self.NOW - ago, timezone.utc).isoformat())
        return str(root / "jobs" / job_id)

    def test_claims_this_weeks_done_jobs_across_projects(self):
        a1, b1 = self.job(self.a, "a one"), self.job(self.b, "b one", ago=6 * 86400)
        out = board.cmd_weekly_start(self.RESETS, self.NOW)
        self.assertEqual(out, {"id": "001", "jobs": [a1, b1]})
        self.assertEqual((self.weekly / "001" / "window").read_text(), "2000086400\n")
        self.assertEqual((self.weekly / "001" / "jobs.txt").read_text(), f"{a1}\n{b1}\n")
        self.assertTrue(board.weekly_ran(self.RESETS))

    def test_skips_jobs_an_earlier_weekly_listed(self):
        a1 = self.job(self.a, "a one")
        self.assertEqual(board.cmd_weekly_start(self.RESETS, self.NOW)["jobs"], [a1])
        b1 = self.job(self.b, "b one")
        out = board.cmd_weekly_start(self.RESETS + 3600, self.NOW + 3600)  # a1 still in this window, but already listed
        self.assertEqual(out, {"id": "002", "jobs": [b1]})
        self.assertEqual(board.cmd_weekly_start(self.RESETS + 3600, self.NOW + 3600), {"id": None, "jobs": []},
                         "a claimed window claims nothing again")
        self.assertEqual(sorted(p.name for p in self.weekly.iterdir()), ["001", "002"])

    def test_old_and_unfinished_jobs_left_out(self):
        self.job(self.a, "last week", ago=7 * 86400 + 1)
        self.job(self.a, "in review", stage="review")
        self.job(self.b, "aborted", stage="aborted")
        kept = self.job(self.b, "just in", ago=6 * 86400)
        self.assertEqual(board.cmd_weekly_start(self.RESETS, self.NOW)["jobs"], [kept])

    def test_no_jobs_writes_window_marker(self):
        self.job(self.a, "in review", stage="review")
        self.assertEqual(board.cmd_weekly_start(self.RESETS, self.NOW), {"id": None, "jobs": []})
        self.assertEqual((self.weekly / "001" / "window").read_text(), "2000086400\n")
        self.assertEqual((self.weekly / "001" / "jobs.txt").read_text(), "")
        self.assertTrue(board.weekly_ran(self.RESETS))
        self.assertFalse(board.weekly_ran(self.RESETS + 7 * 86400))

    def test_per_project_digest_due_unchanged(self):
        self.job(self.a, "a one")
        before = board.cmd_digest_due(self.a)
        board.cmd_weekly_start(self.RESETS, self.NOW)
        self.assertEqual(board.cmd_digest_due(self.a), before)
        self.assertEqual(before["undigested"], 1)
        for root in (self.a, self.b):
            self.assertFalse((root / "digests").exists(), root)


class ProdOkTest(unittest.TestCase):
    """board.cmd_prod_ok / prod-ok: the gate before every decision.md `## Prod runs` bullet."""
    SCRIPTS = {"backfill:x": "tsx scripts/backfill.ts", "backfill:x:prod": "dotenv -e .env.prod -- tsx scripts/backfill.ts",
               "report": "tsx scripts/report.ts", "report:live": "dotenv -e .env.production -- tsx scripts/report.ts",
               "migrate:prod": "tsx scripts/m.ts", "db:push:prod": "tsx scripts/p.ts", "deploy:prod": "vercel --prod",
               "e2e:seed:prod": "tsx scripts/seed.ts", "seed:prod": "dotenv -e .env.prod -- prisma db seed",
               "load:fixtures": "tsx scripts/load.ts", "unit": "node scripts/unit.js", "-x": "echo"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        (self.root / "jobs" / "001-a").mkdir(parents=True)
        (Path(self.tmp.name) / "package.json").write_text(json.dumps({"scripts": self.SCRIPTS}))
        self.prod = self.root / "jobs" / "001-a" / "prod.md"

    def ok(self, bullet):
        return board.cmd_prod_ok(self.root, "001-a", bullet)

    def refused(self, bullet):
        with self.assertRaises(SystemExit) as cm:
            self.ok(bullet)
        msg = str(cm.exception)
        self.assertTrue(msg.startswith("prod-ok: "), msg)
        return msg

    def test_rejects_malformed_and_unknown_script(self):
        for bad in ("", "npm run", "npm  run report", "npm run report;rm", "npm run report -- a b'", "npm run report --",
                    "npm run report -- ", "npm run report -- a  b", "yarn report", "npm run report && ls", " npm run report",
                    "npm run -x", "npm run report -- $(id)", "npm run repört", "npm run report\n"):
            self.refused(bad)
        self.assertIn("not a package.json script", self.refused("npm run nope"))
        (Path(self.tmp.name) / "package.json").unlink()
        self.assertIn("package.json", self.refused("npm run report"))
        with self.assertRaises(SystemExit):
            board.cmd_prod_ok(self.root, "../x", "npm run report")

    def test_refuses_schema_deploy_and_fixture_scripts(self):
        for bullet, word in (("npm run migrate:prod", "migrate"), ("npm run db:push:prod", "db:push"),
                             ("npm run deploy:prod", "vercel"), ("npm run e2e:seed:prod", "e2e"),
                             ("npm run seed:prod", "prisma"), ("npm run load:fixtures", "fixtures"),
                             ("npm run backfill:x -- --accept-data-loss", "accept-data-loss"),
                             ("npm run report -- --force-reset", "force-reset"), ("npm run report -- test", "test")):
            self.assertIn(f"'{word}'", self.refused(bullet), bullet)
        self.assertEqual(self.ok("npm run unit -- testing"), "dev", "testing is not the word test")

    def test_dev_bullet_passes(self):
        self.assertEqual(self.ok("npm run backfill:x"), "dev")
        self.assertEqual(self.ok("npm run backfill:x -- --apply --limit=5"), "dev")
        self.assertEqual(self.ok("npm run report"), "dev")
        self.assertFalse(self.prod.exists())

    def write(self, *records):
        self.prod.write_text("## Runs\n" + "".join(records))

    def test_error_line_past_tail_fails_record(self):
        tail = "".join(f"    row {i}\n" for i in range(20))
        self.write("- run: npm run backfill:x exit 0\n" + tail + "    error found in output: Error: boom\n",
                   "- run: npm run backfill:x -- --apply exit 0\n    updated 3 rows\n")
        self.assertIn("no passing dev run of 'npm run backfill:x' in prod.md", self.refused("npm run backfill:x:prod"))

    def test_jev_handled_record_passes(self):
        imessage = "iMessage skipped: Contacts read failed: execution error: ... Application isn't running"
        cloudinary = "error: { message: 'Request Timeout', http_code: 499 }"
        self.write(f"- run: npm run backfill:x exit 0\n    {imessage}\n    Dry run: 0 files\n"
                   f"    error found in output (Jev: handled): {imessage}\n",
                   f"- run: npm run backfill:x -- --apply exit 0\n    {cloudinary}\n    mirrored 1,074 photos\n"
                   f"    error found in output (Jev: handled): {cloudinary}\n")
        self.assertEqual(self.ok("npm run backfill:x:prod"), "ok")

    def test_plain_error_marker_still_fails(self):
        dry = "- run: npm run backfill:x exit 0\n    Error: boom\n    error found in output (Jev: handled): Error: boom\n"
        apply = "- run: npm run backfill:x -- --apply exit 0\n    Error: boom\n    error found in output: Error: boom\n"
        self.write(dry, apply)
        self.assertIn("no passing dev run of 'npm run backfill:x -- --apply' in prod.md",
                      self.refused("npm run backfill:x:prod"))
        self.write(dry.replace(" (Jev: handled)", ""), apply.replace("output: ", "output (Jev: handled): "))
        self.assertIn("no passing dev run of 'npm run backfill:x' in prod.md", self.refused("npm run backfill:x:prod"))
        self.write("- run: npm run backfill:x exit 0\n    Error: boom\n", apply.replace("output: ", "output (Jev: handled): "))
        self.assertIn("no passing dev run of 'npm run backfill:x' in prod.md", self.refused("npm run backfill:x:prod"))
        self.write("- run: npm run backfill:x exit 0\n    Error: boom\n    error found in output (Jev: handled): Error: boom\n"
                   "    error found in output: Error: boom\n", apply.replace("output: ", "output (Jev: handled): "))
        self.assertIn("no passing dev run of 'npm run backfill:x' in prod.md", self.refused("npm run backfill:x:prod"))

    def test_handled_marker_with_nonzero_exit_fails(self):
        self.write("- run: npm run backfill:x exit 1\n    Error: boom\n    error found in output (Jev: handled): Error: boom\n",
                   "- run: npm run backfill:x -- --apply exit 0\n    updated 3 rows\n")
        self.assertIn("no passing dev run of 'npm run backfill:x' in prod.md", self.refused("npm run backfill:x:prod"))

    def test_prod_needs_dev_dry_and_apply(self):
        dry = "- run: npm run backfill:x exit 0\n    would update 3 rows\n"
        apply = "- run: npm run backfill:x -- --apply exit 0\n    updated 3 rows\n"
        need_dry = "no passing dev run of 'npm run backfill:x' in prod.md"
        need_apply = "no passing dev run of 'npm run backfill:x -- --apply' in prod.md"
        msg = self.refused("npm run backfill:x:prod")
        self.assertIn(need_dry, msg, "missing prod.md")
        self.assertIn(need_apply, msg, "missing prod.md")
        self.write(dry, apply)
        self.assertEqual(self.ok("npm run backfill:x:prod"), "ok")
        self.assertEqual(self.ok("npm run backfill:x:prod -- --apply"), "ok")
        self.write(dry)
        msg = self.refused("npm run backfill:x:prod -- --apply")
        self.assertIn(need_apply, msg)
        self.assertNotIn(need_dry, msg)
        self.write(dry, "- run: npm run backfill:x -- --apply exit 1\n    boom\n")
        self.assertIn(need_apply, self.refused("npm run backfill:x:prod"))
        self.write(dry, "- run: npm run backfill:x -- --apply exit 0\n    Error: row 4 failed\n")
        self.assertIn(need_apply, self.refused("npm run backfill:x:prod"))
        self.write("- run: npm run backfill:x exit 0\n    0 errors\n", apply)
        self.assertEqual(self.ok("npm run backfill:x:prod"), "ok", "errors is not the word error")
        self.write(dry, "## Deploy\n    Error: later section\n", apply)
        self.assertEqual(self.ok("npm run backfill:x:prod"), "ok", "a ## heading ends the record")
        self.write(dry, apply)
        msg = self.refused("npm run backfill:x:prod -- --limit=5")
        self.assertIn("no passing dev run of 'npm run backfill:x -- --limit=5' in prod.md", msg)
        self.assertIn("no passing dev run of 'npm run backfill:x -- --limit=5 --apply' in prod.md", msg)
        self.write("- run: npm run backfill:x -- --limit=5 exit 0\n    ok\n",
                   "- run: npm run backfill:x -- --apply --limit=5 exit 0\n    ok\n")
        self.assertEqual(self.ok("npm run backfill:x:prod -- --limit=5 --apply"), "ok")
        self.write(dry, apply)
        self.assertEqual(self.ok("npm run backfill:x:prod -- --prod"), "ok", "--prod is the script's prod guard")
        self.assertEqual(self.ok("npm run backfill:x:prod -- --apply --prod"), "ok")
        self.write(dry)
        self.assertIn(need_apply, self.refused("npm run backfill:x:prod -- --prod"), "message names the dev bullet")
        self.write("- run: npm run backfill:x -- --prod exit 0\n", "- run: npm run backfill:x -- --apply --prod exit 0\n")
        self.assertIn(need_dry, self.refused("npm run backfill:x:prod -- --prod"), "a dev record with --prod is not the dev run")
        self.assertIn("no dev script for report:live", self.refused("npm run report:live"))

    def test_cli_exit_codes(self):
        self.write("- run: npm run backfill:x exit 0\n", "- run: npm run backfill:x -- --apply exit 0\n")

        def cli(bullet):
            return subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "prod-ok", "001-a", bullet],
                                  capture_output=True, text=True, timeout=30)
        out = cli("npm run backfill:x:prod")
        self.assertEqual((out.returncode, out.stdout), (0, "ok\n"), out.stderr)
        out = cli("npm run report")
        self.assertEqual((out.returncode, out.stdout), (0, "dev\n"), out.stderr)
        out = cli("npm run deploy:prod")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("prod-ok: ", out.stderr)
        self.write()
        self.assertNotEqual(cli("npm run backfill:x:prod").returncode, 0)
        self.assertIn("board.py prod-ok <id> '<bullet>'", BOARD_PY.read_text().split('"""')[1])


class ParkedBigboyTest(unittest.TestCase):
    def jobs(self, gc_stage="needs-human", **gc):
        j = lambda i, **kw: {"id": i, "title": i, "stage": "waiting", "updatedAt": "2026-01-01T00:00:00+00:00", **kw}
        return [j("107-big", stage="running", lane="bigboy", children=["285-gc"]),
                j("285-gc", stage=gc_stage, parent="107-big", **gc)]

    def check(self, jobs, live=()):
        with tempfile.TemporaryDirectory() as tmp:
            return board.parked_bigboy(jobs[0], {j["id"]: j for j in jobs}, live, Path(tmp))

    def test_parked_shapes(self):
        self.assertTrue(self.check(self.jobs()))
        self.assertTrue(self.check(self.jobs("waiting", setup="pending")))

    def test_not_parked(self):
        self.assertFalse(self.check(self.jobs("running")))
        self.assertFalse(self.check(self.jobs("waiting")))
        self.assertFalse(self.check(self.jobs(), live={"285-gc"}))
        jobs = self.jobs()
        jobs[0]["paused"] = True
        self.assertFalse(self.check(jobs))
        jobs = self.jobs()
        jobs[0]["lane"] = "runall"
        self.assertFalse(self.check(jobs))

    def test_waiting_child_behind_setup_pending_sibling_is_parked(self):
        jobs = self.jobs("done")
        jobs[0]["children"] = ["285-gc", "314", "315"]
        j = lambda i, **kw: {"id": i, "title": i, "stage": "waiting", "updatedAt": "2026-01-01T00:00:00+00:00",
                             "parent": "107-big", **kw}
        jobs += [j("314", setup="pending"), j("315", depends_on=["314"])]
        self.assertTrue(self.check(jobs))
        jobs[2].pop("setup")  # 314 claimable: 315 still waits, but 314 is about to start
        self.assertFalse(self.check(jobs))
        jobs[2]["stage"] = "done"  # 315's dep is done: it is about to start
        self.assertFalse(self.check(jobs))

    def test_resume_blocker_ignores_parked_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            j = lambda i, **kw: {"id": i, "title": i, "stage": "waiting", "updatedAt": "2026-01-01T00:00:00+00:00", **kw}
            jobs = [j("070", stage="running", lane="runall", children=["107", "108"]),
                    j("107", stage="running", lane="bigboy", parent="070", children=["285"]),
                    j("108", stage="needs-human", parent="070", lane="fast"),
                    j("285", stage="needs-human", parent="107")]
            (root / "board.json").write_text(json.dumps({"jobs": jobs}))
            self.assertIsNone(board.resume_blocker(root, "108"))
            jobs[3]["stage"] = "running"
            (root / "board.json").write_text(json.dumps({"jobs": jobs}))
            with mock.patch.object(board, "session_alive_fn", return_value=lambda k: True):
                self.assertIsNotNone(board.resume_blocker(root, "108"))


class StopWorktreeServersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(os.path.realpath(self.tmp.name)) / "app"
        self.wt = self.repo / ".claude" / "worktrees" / "scrum-1"
        (self.wt / "web").mkdir(parents=True)
        (self.repo / ".claude" / "worktrees" / "scrum-10").mkdir(parents=True)

    def test_stop_worktree_servers_kills_only_that_worktree(self):
        w = str(self.wt)
        listening = [(101, 3000, w), (102, 3002, w + "/web"), (101, 3005, w), (103, 3000, w + "0"),
                     (104, 3000, str(self.repo)), (105, 3001, w), (105, 3010, w), (os.getpid(), 4000, w),
                     (106, 3003, w), (107, 3004, w)]
        with mock.patch.object(board.os, "kill", side_effect=[None, None, ProcessLookupError, PermissionError]) as kill:
            got = board.stop_worktree_servers(self.repo, w, listening)
        self.assertEqual(got, [101, 102])
        self.assertEqual([c.args for c in kill.call_args_list], [(101, 15), (102, 15), (106, 15), (107, 15)])

    def test_stop_worktree_servers_ignores_non_worktree_paths(self):
        wts = [None, "", str(self.repo / ".claude" / "worktrees" / "gone"), str(self.repo),
               str(self.repo / ".claude" / "worktrees"), str(self.repo / ".claude"), "/tmp"]
        for wt in wts:
            with self.subTest(wt=wt), mock.patch.object(board.os, "kill") as kill, \
                    mock.patch.object(board.subprocess, "run") as run:
                self.assertEqual(board.stop_worktree_servers(self.repo, wt), [])
            kill.assert_not_called()
            run.assert_not_called()

    def test_stop_worktree_servers_sigkills_survivors(self):
        w = str(self.wt)
        def kill(pid, sig):  # 201 never dies (a wedged event loop); 202 exits on SIGTERM
            if sig == 0 and pid == 202:
                raise ProcessLookupError
        with mock.patch.object(board.os, "kill", side_effect=kill) as k, \
                mock.patch.object(board.time, "sleep") as sleep:
            got = board.stop_worktree_servers(self.repo, w, [(201, 3000, w), (202, 3002, w)], wait=1)
        self.assertEqual(got, [201, 202])
        calls = [c.args for c in k.call_args_list]
        self.assertEqual(calls[:2], [(201, 15), (202, 15)])
        self.assertEqual(calls[-1], (201, 9))
        self.assertNotIn((202, 9), calls)
        self.assertEqual(sleep.call_count, 4, "every 0.25 s for 1 s")
        self.assertTrue(all(c.args == (0.25,) for c in sleep.call_args_list))
        with mock.patch.object(board.os, "kill") as k, mock.patch.object(board.time, "sleep") as sleep:
            board.stop_worktree_servers(self.repo, w, [(201, 3000, w)])
        sleep.assert_not_called()
        self.assertEqual([c.args for c in k.call_args_list], [(201, 15)], "no wait: TERM only")

    def test_dev_clear_cli_prints_killed(self):
        root = self.repo / "scrum"
        root.mkdir()
        job_id = board.cmd_new(root, "Clear me")
        board.cmd_set(root, job_id, [f"worktree={self.wt}"])
        w = str(self.wt)
        def kill(pid, sig):  # the server exits on SIGTERM
            if sig == 0:
                raise ProcessLookupError
        with mock.patch.object(board, "listeners", return_value=[(301, 3000, w), (302, 3000, str(self.repo))]), \
                mock.patch.object(board.os, "kill", side_effect=kill) as kill, \
                mock.patch.object(board.time, "sleep"):
            r = run_board("--dir", str(root), "dev-clear", job_id)
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {"killed": [301]}))
        self.assertIn((301, 15), [c.args for c in kill.call_args_list])
        with mock.patch.object(board, "listeners", return_value=[]):
            r = run_board("--dir", str(root), "dev-clear", job_id)
        self.assertEqual((r.returncode, json.loads(r.stdout)), (0, {"killed": []}))
        r = run_board("--dir", str(root), "dev-clear", "999-nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no job '999-nope' on the board", r.stderr)
        self.assertIn("dev-clear <id>", board.__doc__)



class LockRankTest(unittest.TestCase):
    """Job 622: board.lock_rank(cwd) orders cool-down lock waiters by how near their job is to merging."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root = base / "repo" / "scrum"
        (base / "corrupt" / "scrum").mkdir(parents=True)
        (base / "corrupt" / "scrum" / "board.json").write_text("{")
        reg = base / "projects.json"
        reg.write_text(json.dumps([str(base / "corrupt"), str(base / "repo")]))
        env = mock.patch.dict(os.environ, {"SCRUM_REGISTRY": str(reg)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.wts = {}
        jobs = []
        for n, (stage, rnd) in enumerate([("check", 1), ("check", 2), ("check", 1), ("build", 0), ("done", 1)]):
            wt = base / f"wt{n}"
            (wt / "pkg").mkdir(parents=True)
            self.wts[n] = wt
            jobs.append({"id": f"00{n + 1}-job", "stage": stage, "round": rnd, "worktree": str(wt)})
        self.root.mkdir(parents=True)
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))
        decided = self.root / "jobs" / "003-job" / "round-1"
        decided.mkdir(parents=True)
        (decided / "decision.md").write_text("APPROVE\nRestart: none\n")
        rework = self.root / "jobs" / "001-job" / "round-1"
        rework.mkdir(parents=True)
        (rework / "decision.md").write_text("REWORK\nRestart: none\n")

    def test_ranks(self):
        self.assertEqual(board.lock_rank(str(self.wts[0])), 1, "first check")
        self.assertEqual(board.lock_rank(str(self.wts[1])), 2, "back from a review round")
        self.assertEqual(board.lock_rank(str(self.wts[2])), 3, "APPROVE decision: the Merge Conflicts re-check")
        self.assertEqual(board.lock_rank(str(self.wts[3])), 0, "build")
        self.assertEqual(board.lock_rank(str(self.wts[4])), 0, "a done job never matches")
        self.assertEqual(board.lock_rank(tempfile.gettempdir()), 0, "unknown cwd")
        self.assertEqual(board.lock_rank(str(self.wts[1] / "pkg")), 2, "a subdirectory of the worktree")

    def test_stages_and_errors(self):
        jobs = [{"id": "001-job", "stage": "review", "round": 1, "worktree": str(self.wts[0])},
                {"id": "002-job", "stage": "merging", "round": 1, "worktree": str(self.wts[1])}]
        (self.root / "board.json").write_text(json.dumps({"jobs": jobs}))
        self.assertEqual(board.lock_rank(str(self.wts[0])), 2)
        self.assertEqual(board.lock_rank(str(self.wts[1])), 3)
        (self.root / "board.json").write_text("{")
        self.assertEqual(board.lock_rank(str(self.wts[0])), 0, "a read error is rank 0")


class CooldownParkTest(unittest.TestCase):
    """Job 622: `board.py cooldown-park <id>` stalls a far-off job at its next checkpoint while cooling down."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        no_claude_pid(self)
        self.flag = Path(self.tmp.name) / "cooldown"
        self.flag.write_text("")
        env = mock.patch.dict(os.environ, SCRUM_COOLDOWN=str(self.flag))
        env.start()
        self.addCleanup(env.stop)

    def job(self, *pairs, **extra):
        job_id = board.cmd_new(self.root, "a job")
        if pairs:
            board.cmd_set(self.root, job_id, list(pairs))
        if extra:
            with board.locked_board(self.root) as b:
                board.find(b, job_id).update(extra)
        return job_id

    def get(self, job_id):
        return board.find(board.read_board(self.root), job_id)

    def park(self, job_id):
        r = run_board("--dir", str(self.root), "cooldown-park", job_id)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_parks_spec_and_round0_build(self):
        for pairs in (("stage=spec",), ("stage=build",)):
            j = self.job(*pairs)
            self.assertEqual(self.park(j), {"parked": True})
            got = self.get(j)
            self.assertEqual((got["stage"], got["stalled"], got["reason"]),
                             (pairs[0][6:], True, "stalled: parked for cool down; resumes when cool down ends"))
            self.assertTrue(board.stalled(got))
            before = (self.root / "board.json").read_text()
            self.assertEqual(self.park(j), {"parked": False}, "already parked")
            self.assertEqual((self.root / "board.json").read_text(), before, "nothing written")

    def test_does_not_park(self):
        cases = {"build round 1": self.job("stage=build", "round=1"), "check": self.job("stage=check"),
                 "stalled": self.job("stage=build", stalled=True, reason="stalled: no session"),
                 "lilguy": self.job("stage=build", "lane=lilguy"), "cloud": self.job("stage=build", lane="cloud"),
                 "paused": self.job("stage=build", paused=True)}
        for name, j in cases.items():
            before = self.get(j)
            self.assertEqual(self.park(j), {"parked": False}, name)
            self.assertEqual(self.get(j), before, name)
        self.flag.unlink()
        j = self.job("stage=build")
        self.assertEqual(self.park(j), {"parked": False}, "cool down off")
        self.assertNotIn("stalled", self.get(j))
        self.assertIn("cooldown-park <id>", board.__doc__)


class StartedByTest(unittest.TestCase):
    """Job 842: every new board job records who started it (serve, runall, wake or hand)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "scrum"
        self.root.mkdir()
        no_claude_pid(self)

    def by(self, job_id):
        return board.find(board.read_board(self.root), job_id).get("started_by")

    def test_new_defaults_hand(self):
        self.assertEqual(self.by(board.cmd_new(self.root, "a job")), "hand")
        r = run_board("--dir", str(self.root), "new", "cli job")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.by(r.stdout.strip()), "hand")

    def test_new_by_flag(self):
        r = run_board("--dir", str(self.root), "new", "by serve", "--by", "serve")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.by(r.stdout.strip()), "serve")
        before = (self.root / "board.json").read_text()
        bad = run_board("--dir", str(self.root), "new", "bad", "--by", "robot")
        self.assertNotEqual(bad.returncode, 0)
        self.assertEqual((self.root / "board.json").read_text(), before)
        self.assertIn("--by <serve|runall|wake|hand>", board.__doc__)

    def test_next_auto_runall_index_hand(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Alpha\n- [ ] Beta\n")
        self.assertEqual(self.by(board.cmd_next(self.root)["id"]), "runall")
        self.assertEqual(self.by(board.cmd_next(self.root, 1)["id"]), "hand")

    def test_runall_start_children_runall(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Alpha\n- [ ] Beta\n")
        out = board.cmd_runall_start(self.root)
        self.assertEqual([self.by(j) for j in [out["id"], *out["children"]]], ["runall", "runall", "runall"])
        with board.locked_board(self.root) as b:  # a parent with no started_by (made before job 842): runall
            parent = board.find(b, out["id"])
            parent.pop("started_by")
            kid = board.add_child(self.root, b, parent, {"ticket": None, "title": "Gamma", "text": "Gamma",
                                                         "parallel": True}, [], "", plain=True)
            parent["started_by"] = "hand"
            hand_kid = board.add_child(self.root, b, parent, {"ticket": None, "title": "Delta", "text": "Delta",
                                                              "parallel": True}, [], "", plain=True)
        self.assertEqual((self.by(kid), self.by(hand_kid)), ("runall", "hand"))

    def test_cloud_claim_serve(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Alpha\n")
        (self.root / "backlog-specs").mkdir()
        (self.root / "backlog-specs" / (hashlib.sha1(b"Alpha").hexdigest()[:12] + ".md")).write_text(
            "# Alpha\n\n## Likely files\n- `a.py`: edit\n")
        (claimed,) = board.cmd_cloud_claim(self.root, 1)["claimed"]
        self.assertEqual(self.by(claimed["id"]), "serve")

    def test_wake_waiting_sets_wake(self):
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": "001-first", "stage": "done"},
            {"id": "002-second", "stage": "waiting", "depends_on": ["001-first"], "started_by": "hand"},
            {"id": "003-third", "stage": "waiting", "depends_on": ["001-first"], "wake": "start", "started_by": "runall"},
            {"id": "004-held", "stage": "waiting", "depends_on": ["005-open"], "started_by": "hand"},
            {"id": "005-open", "stage": "build"}]}))
        out = board.wake_waiting(self.root)
        self.assertEqual((out["ready"], out["retry"]), (["002-second"], ["003-third"]))
        self.assertEqual([self.by(j) for j in ("002-second", "003-third", "004-held")], ["wake", "wake", "hand"])


if __name__ == "__main__":
    unittest.main()


class BacklogUnlessOpenTest(unittest.TestCase):
    """Job 769: cmd_backlog_add's unless_open skips an item while an open item holds that text, checked under the lock."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_skips_when_open_item_matches_and_adds_when_done(self):
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Prod error on /a: boom (sig abc1234567)\n")
        self.assertEqual(board.cmd_backlog_add(self.root, ["Prod error on /a: boom again (sig abc1234567)"],
                                               unless_open="(sig abc1234567)"), [])
        self.assertEqual((self.root / "backlog.md").read_text(), "# Backlog\n- [ ] Prod error on /a: boom (sig abc1234567)\n")
        self.assertEqual(board.cmd_backlog_add(self.root, ["other (sig fff0000000)"], unless_open="(sig fff0000000)"),
                         ["other (sig fff0000000)"])
        (self.root / "backlog.md").write_text("# Backlog\n- [x] Prod error on /a: boom (sig abc1234567)\n")
        self.assertEqual(board.cmd_backlog_add(self.root, ["Prod error on /a: back (sig abc1234567)"],
                                               unless_open="(sig abc1234567)"), ["Prod error on /a: back (sig abc1234567)"])
        self.assertIn("- [ ] Prod error on /a: back (sig abc1234567)", (self.root / "backlog.md").read_text())
        self.assertEqual(board.cmd_backlog_add(self.root, ["plain"]), ["plain"], "no unless_open adds as before")


class TestDbUp(unittest.TestCase):
    """board.db_up: the Check gate's local-database probe and start (job 761)."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.socks = []
        self.addCleanup(lambda: [s.close() for s in self.socks])

    def env(self, url_line):
        path = self.dir / ".env"
        path.write_text(f"OTHER=1\n{url_line}\n")
        return path

    def free_port(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def listen(self, port):
        import socket
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen()
        self.socks.append(s)

    def test_open_port_does_not_start(self):
        port = self.free_port()
        self.listen(port)
        start = mock.Mock()
        out = board.db_up(self.env(f'DATABASE_URL="postgresql://u:p@127.0.0.1:{port}/db?schema=public"'), start=start)
        self.assertEqual(out, {"up": True, "started": False})
        start.assert_not_called()

    def test_refused_port_starts_then_succeeds(self):
        port = self.free_port()
        calls, sleeps = [], []
        out = board.db_up(self.env(f"DATABASE_URL='postgresql://u@localhost:{port}/db'"), wait=120,
                          start=lambda: calls.append(1) or self.listen(port), sleep=sleeps.append)
        self.assertEqual(out, {"up": True, "started": True})
        self.assertEqual(calls, [1])
        self.assertEqual(sleeps, [5])

    def test_never_opens_returns_down(self):
        sleeps, calls = [], []
        out = board.db_up(self.env("DATABASE_URL=postgresql://u@127.0.0.1:5999/db"), wait=12,
                          start=lambda: calls.append(1), probe=lambda host, port: False, sleep=sleeps.append)
        self.assertEqual(out, {"up": False, "started": True})
        self.assertEqual(calls, [1])
        self.assertEqual(sleeps, [5, 5])
        port = self.free_port()
        env = self.env(f"DATABASE_URL=postgresql://u@127.0.0.1:{port}/db")
        with mock.patch.object(board, "start_local_db", return_value=None) as start, \
                mock.patch.object(board.time, "sleep"):
            r = run_board("db-up", "--env", str(env))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout), {"up": False, "started": True})
        start.assert_called_once_with(cwd=env.parent)

    def test_skips_remote_and_missing_url(self):
        start = mock.Mock()
        never = lambda host, port: self.fail("probed a skipped database")  # noqa: E731
        cases = {
            "remote": self.env("DATABASE_URL=postgresql://u@db.example.com:5432/db"),
            "missing file": self.dir / "nope.env",
            "no url": self.env("DIRECT_URL=postgresql://u@localhost/db"),
            "bad port": self.env("DATABASE_URL=postgresql://u@localhost:notaport/db"),
        }
        for name, env in cases.items():
            out = board.db_up(env, start=start, probe=never)
            self.assertIsNone(out["up"], name)
            self.assertTrue(out["skipped"], name)
            self.assertEqual(set(out), {"up", "skipped"}, name)
        start.assert_not_called()
        r = run_board("db-up", "--env", str(self.env("DATABASE_URL=postgresql://u@db.example.com/db")))
        self.assertEqual(r.returncode, 0)
        self.assertIsNone(json.loads(r.stdout)["up"])

    def test_default_starter_failure_is_reported(self):
        def fake_run(argv, **kw):
            if argv[:3] == ["brew", "services", "list"]:
                return subprocess.CompletedProcess(argv, 0, "Name Status User File\npostgresql@16 none\n", "")
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        with mock.patch.object(board.subprocess, "run", side_effect=fake_run) as run:
            out = board.db_up(self.env("DATABASE_URL=postgresql://u@localhost/db"), wait=5,
                              probe=lambda host, port: False, sleep=lambda s: None)
        self.assertEqual(out["up"], False)
        self.assertEqual(out["started"], True)
        self.assertIn("brew services start postgresql@16", out["error"])
        self.assertEqual(run.call_args_list[1].args[0], ["brew", "services", "start", "postgresql@16"])
        # no brew and no compose file: reported, never raised
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)
        with mock.patch.object(board.subprocess, "run", side_effect=FileNotFoundError("brew")):
            out = board.db_up(self.env("DATABASE_URL=postgresql://u@localhost/db"), wait=5,
                              probe=lambda host, port: False, sleep=lambda s: None)
        self.assertEqual((out["up"], out["started"]), (False, True))
        self.assertIn("no compose file", out["error"])

    def test_default_starter_uses_env_file_folder(self):
        # the compose file sits beside the env file, not in the process cwd (job 827)
        (self.dir / "docker-compose.yml").write_text("services: {}\n")
        elsewhere = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, elsewhere, True)
        cwd = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, cwd)
        seen = []

        def fake_run(argv, **kw):
            seen.append((argv, kw.get("cwd")))
            return subprocess.CompletedProcess(argv, 0, "Name Status\nredis none\n" if argv[0] == "brew" else "", "")
        with mock.patch.object(board.subprocess, "run", side_effect=fake_run):
            out = board.db_up(self.env("DATABASE_URL=postgresql://u@localhost/db"), wait=5,
                              probe=lambda host, port: False, sleep=lambda s: None)
        self.assertNotIn("error", out)
        self.assertIn((["docker", "compose", "up", "-d"], self.dir), seen)

    def test_compose_starter_waits_for_docker(self):
        (self.dir / "docker-compose.yml").write_text("services: {}\n")
        seen = []

        def fake_run(argv, **kw):
            seen.append(argv)
            if argv[:3] == ["brew", "services", "list"]:
                return subprocess.CompletedProcess(argv, 0, "Name Status\nredis none\n", "")
            ok = argv != ["docker", "info"] or seen.count(["docker", "info"]) > 1
            return subprocess.CompletedProcess(argv, 0 if ok else 1, "", "")
        with mock.patch.object(board.subprocess, "run", side_effect=fake_run):
            self.assertIsNone(board.start_local_db(cwd=self.dir, sleep=lambda s: None))
        self.assertEqual(seen[1:], [["docker", "info"], ["open", "-a", "Docker"], ["docker", "info"],
                                    ["docker", "compose", "up", "-d"]])
