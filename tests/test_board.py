import hashlib, io, json, os, subprocess, sys, tempfile, time, unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound
os.environ["SCRUM_FREE_RAM"] = "100"  # machine_ok passes unless a test says so; no test runs memory_pressure
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")  # never Trevor's real cool-down flag
os.environ["SCRUM_SWAP_PCT"] = "1"  # swap nearly empty unless a test says so; no test runs sysctl
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"  # load nearly idle unless a test says so; no test reads the real load average
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
os.environ["SCRUM_SWAP_LOG"] = os.path.join(tempfile.mkdtemp(), "swap.json")  # never the real swap log
os.environ.setdefault("SCRUM_PS", os.devnull)  # no live sessions unless a test says so, whatever this machine runs
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))  # never Trevor's real usage.json
import board  # noqa: E402

BOARD_PY = ROOT / "skills" / "trevskills-scrum" / "board.py"
CALLER_CLAUDE_PID = board.caller_claude_pid  # the real one; fixtures patch it so the test runner's claude is never recorded


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
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "set", job_id,
                              "tty=ttys003", "runlog=runs/x.log"], capture_output=True, text=True)
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
        board.cmd_ask(self.root, job_id, "Blocked?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        board.cmd_set(self.root, job_id, ["outcome=Approve refused. Nothing changed."])
        board.cmd_ask(self.root, job_id, "Blocked?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        self.assertEqual(self.jobs()[0]["outcome"], "Approve refused. Nothing changed.")  # same reason keeps it
        board.cmd_ask(self.root, job_id, "New blocker?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        self.assertNotIn("outcome", self.jobs()[0])  # a new reason drops it
        board.cmd_set(self.root, job_id, ["outcome=Rework refused. Nothing changed."])
        board.cmd_set(self.root, job_id, ["reason=still here"])
        self.assertEqual(self.jobs()[0]["outcome"], "Rework refused. Nothing changed.")  # no stage change keeps it
        board.cmd_set(self.root, job_id, ["stage=build"], unpause=True)
        self.assertNotIn("outcome", self.jobs()[0])  # a stage change drops it

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
            out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "set", job_id, "stage=review", bad],
                                 capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0, bad)
            self.assertIn("fast|standard|debug|bigboy", out.stderr, bad)
        self.assertEqual((self.root / "board.json").read_text(), before)

    # --- ask / answer ---
    def log_lines(self):
        p = self.root / "questions.log"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def test_ask_parks_job_with_question_and_options(self):
        job_id = board.cmd_new(self.root, "x")
        out = board.cmd_ask(self.root, job_id, "Ship it?", [f"Approve=approve {job_id}", f"Abort=abort {job_id} --requeue"])
        want = [{"key": "a", "label": "Approve", "command": f"approve {job_id}"},
                {"key": "b", "label": "Abort", "command": f"abort {job_id} --requeue"}]
        self.assertEqual(out, want)
        job = self.jobs()[0]
        self.assertEqual((job["stage"], job["reason"], job["question"], job["options"]),
                         ("needs-human", "Ship it?", "Ship it?", want))
        self.assertRegex(job["updatedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")

    def test_ask_cli_three_options(self):
        job_id = board.cmd_new(self.root, "x")
        buf = io.StringIO()
        with redirect_stdout(buf):
            board.main(["--dir", str(self.root), "ask", job_id, "Which?", "--a", f"Approve=approve {job_id}",
                        "--b", f"Abort=abort {job_id} --requeue", "--c", f"Resume=resume {job_id}"])
        self.assertEqual(buf.getvalue(), "")
        self.assertEqual(self.jobs()[0]["options"][2], {"key": "c", "label": "Resume", "command": f"resume {job_id}"})
        self.assertEqual(len(self.jobs()[0]["options"]), 3)

    def test_ask_accepts_each_command_form(self):
        job_id = board.cmd_new(self.root, "x")
        for cmd in ("approve 012-other-job", 'rework 012-other-job "fix the tests"', "abort 012-other-job",
                    "abort 012-other-job --requeue", "abort 012-other-job --cascade", "resume 012-other-job",
                    "shell: git status"):
            with self.subTest(cmd=cmd):
                out = board.cmd_ask(self.root, job_id, "Q?", [f"Go={cmd}", f"Abort=abort {job_id}"])
                self.assertEqual(out[0]["command"], cmd)

    def test_ask_splits_on_first_equals(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f' Rework =  rework {job_id} "a=b" ', f"Abort=abort {job_id}"])
        self.assertEqual(self.jobs()[0]["options"][0],
                         {"key": "a", "label": "Rework", "command": f'rework {job_id} "a=b"'})

    def test_ask_rejects_bad_options(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "First?", [f"A=approve {job_id}", f"B=abort {job_id}"])
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
                   "shell: <command>")
        cases["cascade and requeue"] = (job_id, "Q?", [f"Go=abort {job_id} --cascade --requeue", ok])
        cases["misspelt cascade"] = (job_id, "Q?", [f"Go=abort {job_id} --cascad", ok])
        for name, (jid, q, opts) in cases.items():
            with self.subTest(name):
                before = (self.root / "board.json").read_bytes()
                with self.assertRaises(SystemExit) as e:
                    board.cmd_ask(self.root, jid, q, opts)
                self.assertTrue(str(e.exception.code))
                if name in ("cascade and requeue", "misspelt cascade"):
                    self.assertIn(allowed, str(e.exception.code))
                self.assertEqual((self.root / "board.json").read_bytes(), before)
                self.assertEqual(len(self.log_lines()), 1)

    def test_ask_recommend_stored_and_logged(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"],
                      recommend=("b", "  safest\n path "))
        self.assertEqual(self.jobs()[0]["recommend"], {"key": "b", "why": "safest path"})
        self.assertEqual(self.log_lines()[-1]["recommend"], {"key": "b", "why": "safest path"})

    def test_ask_cli_recommend(self):
        job_id = board.cmd_new(self.root, "x")
        board.main(["--dir", str(self.root), "ask", job_id, "Q?", "--a", f"A=approve {job_id}",
                    "--b", f"B=resume {job_id}", "--recommend", "b", "it is the safest path"])
        self.assertEqual(self.jobs()[0]["recommend"], {"key": "b", "why": "it is the safest path"})
        self.assertEqual(self.log_lines()[-1]["recommend"], {"key": "b", "why": "it is the safest path"})

    def test_ask_without_recommend_has_no_field(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"])
        self.assertNotIn("recommend", self.jobs()[0])
        self.assertNotIn("recommend", self.log_lines()[-1])

    def test_reask_drops_stale_recommend(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"], recommend=("a", "why"))
        board.cmd_ask(self.root, job_id, "Q2?", [f"A=approve {job_id}", f"B=resume {job_id}"])
        self.assertNotIn("recommend", self.jobs()[0])
        self.assertNotIn("recommend", self.log_lines()[-1])

    def test_ask_recommend_bad_key_rejected(self):
        job_id = board.cmd_new(self.root, "x")
        for key in ("c", "x"):
            with self.subTest(key=key):
                before = (self.root / "board.json").read_bytes()
                with self.assertRaises(SystemExit) as e:
                    board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"],
                                  recommend=(key, "because"))
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
                                  recommend=("a", why))
                self.assertIn("recommend needs a reason", str(e.exception.code))
                self.assertEqual((self.root / "board.json").read_bytes(), before)
                self.assertFalse((self.root / "questions.log").exists())

    def test_recommend_cleared_after_answer_moves_job(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=resume {job_id}"], recommend=("b", "safe"))
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
            board.cmd_ask(self.root, job_id, "Q?", [f"Merge=merge {job_id}", f"B=abort {job_id}"])
        self.assertFalse((self.root / "questions.log").exists())

    def test_ask_appends_questions_log(self):
        job_id = board.cmd_new(self.root, "x")
        opts = board.cmd_ask(self.root, job_id, "Ship it?", [f"Approve=approve {job_id}", f"Abort=abort {job_id}"])
        [line] = self.log_lines()
        self.assertEqual(set(line), {"date", "project", "job", "question", "options", "kind", "reason"})
        self.assertEqual((line["kind"], line["reason"]), ("ask", "Ship it?"))
        self.assertRegex(line["date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual(line["project"], Path(self.tmp.name).name)
        self.assertEqual((line["job"], line["question"]), (job_id, "Ship it?"))
        self.assertEqual(line["options"], [{"key": "a", "label": "Approve", "command": f"approve {job_id}"},
                                           {"key": "b", "label": "Abort", "command": f"abort {job_id}"}])
        self.assertEqual(line["options"], opts)

    def test_ask_twice_overwrites_and_logs_twice(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "One?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        board.cmd_ask(self.root, job_id, "Two?", [f"R=resume {job_id}", "S=shell: ls"])
        job = self.jobs()[0]
        self.assertEqual((job["question"], job["reason"]), ("Two?", "Two?"))
        self.assertEqual([o["label"] for o in job["options"]], ["R", "S"])
        self.assertEqual([l["question"] for l in self.log_lines()], ["One?", "Two?"])

    def test_ask_agent_types_not_loaded_is_stalled(self):
        opts = lambda j: [f"R=resume {j}", f"A=abort {j}"]
        for q, stage, want in (
                ("scrum-debugger, scrum-builder are not loaded as agent types in this session", "build",
                 "stalled in build: scrum-debugger, scrum-builder are not loaded as agent types in this session"),
                ("The scrum Agent Types not loaded here", "check", "stalled in check: The scrum Agent Types not loaded here"),
                ("agent types are not loaded", "review", "stalled in review: agent types are not loaded"),
                ("Pick a layout?", "build", "Pick a layout?"),
                ("agent types are not loaded", "plan", "agent types are not loaded")):
            with self.subTest(q=q, stage=stage):
                job_id = board.cmd_new(self.root, "x")
                board.cmd_set(self.root, job_id, [f"stage={stage}"])
                board.cmd_ask(self.root, job_id, q, opts(job_id))
                job = next(j for j in self.jobs() if j["id"] == job_id)
                self.assertEqual((job["stage"], job["reason"], job["question"], [o["command"] for o in job["options"]]),
                                 ("needs-human", want, q, [f"resume {job_id}", f"abort {job_id}"]))

    # --- ask --kind (scrum-unblocker) ---
    def ask_cli(self, job_id, kind, question="Stuck?"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            board.main(["--dir", str(self.root), "ask", job_id, question, "--kind", kind,
                        "--a", f"Approve=approve {job_id}", "--b", f"Abort=abort {job_id}"])
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
                    board.cmd_ask(self.root, job_id, "Q?", opts, kind=kind)
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
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        board.cmd_set(self.root, job_id, ["stage=build"])
        job = self.jobs()[0]
        self.assertNotIn("question", job)
        self.assertNotIn("options", job)

    def test_abort_clears_question(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        board.cmd_abort(self.root, job_id, False)
        job = self.jobs()[0]
        self.assertEqual(job["stage"], "aborted")
        self.assertNotIn("question", job)
        self.assertNotIn("options", job)

    def test_set_keeping_needs_human_keeps_question(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"])
        board.cmd_set(self.root, job_id, ["waiting=asked"])
        job = self.jobs()[0]
        self.assertEqual(job["question"], "Q?")
        self.assertEqual([o["key"] for o in job["options"]], ["a", "b"])

    def test_answer_prints_option_and_logs_pick(self):
        job_id = board.cmd_new(self.root, "x")
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"Abort=abort {job_id} --requeue"])
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

    def test_answer_refuses_wrong_stage_or_key(self):
        job_id = board.cmd_new(self.root, "x")
        with self.assertRaises(SystemExit):
            board.cmd_answer(self.root, job_id, "a")  # spec stage, never asked
        board.cmd_ask(self.root, job_id, "Q?", [f"A=approve {job_id}", f"B=abort {job_id}"])
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
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "chain-unlock", parent, "002-part-1"],
                             capture_output=True, text=True)
        self.assertEqual((out.returncode, json.loads(out.stdout)), (0, {"released": True}))
        self.assertFalse(lock.exists())
        self.assertEqual(board.cmd_chain_lock(self.root, parent, "003-part-2", wait=0)["acquired"], True)

    def test_likely_files_reads_only_that_section(self):
        text = "## Problem\n`a/x.py`\n## Likely files\n- `skills/board.py`: `SHAPES[\"lane\"]` and `cmd_ready(root)`\n- `tests/t.py`\n## Assumptions\n- `b/y.py`\n"
        self.assertEqual(board.likely_files(text), {"skills/board.py", "tests/t.py"})
        self.assertEqual(board.likely_files("# no section\n"), set())
        nextjs = "## Likely files\n- `src/app/(app)/page.tsx`\n- `src/app/api/orders/[id]/route.ts`\n"
        self.assertEqual(board.likely_files(nextjs), {"src/app/(app)/page.tsx", "src/app/api/orders/[id]/route.ts"})

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
        self.assertEqual({k: self.log_lines()[1][k] for k in ("job", "kind", "reason")},
                         {"job": parent, "kind": "bigboy", "reason": "merged + gaps: review unreadable"})
        other = board.cmd_new(self.root, "y")
        for q in ("bigboy review: main not updated; merge it?", "bigboy blocked: 009-x. Resume?", "bigboy off track?"):
            board.cmd_ask(self.root, other, q, [f"R=resume {other}", f"A=abort {other}"])
        asks = self.log_lines()[2:]
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
        self.assertEqual(self.jobs()[1]["title"], "L" * 60)
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

    def test_runall_ready_has_no_count_cap(self):
        parent, kids = self.runall(7)
        for i, k in enumerate(kids):
            self.spec(k, f"src/{i}.py")
        out = board.cmd_ready(self.root, parent)
        self.assertEqual((out["ready"], out["in_progress"]), (kids, 7))
        self.assertEqual(board.cmd_ready(self.root, parent)["ready"], [])
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

    def test_ready_cooling_down_bigboy_claims_and_finishes(self):
        """Job 421: a BigBoy parent's children already exist, so cool-down lets it claim them and reach its final review."""
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
        with self.cooling(), mock.patch.object(board, "play"):
            out = board.cmd_ready(self.root, parent)
        self.assertEqual(out["ready"], [c, d])
        self.assertEqual((self.child(c)["stage"], self.child(d)["stage"]), ("spec", "spec"))
        self.assertEqual(self.child(parent)["reason"], None)

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
        for ram, room in (("66", 9), ("100", 14), ("26", 1), ("20", 1)):  # 100: the MAX_SESSIONS ceiling
            with self.subTest(ram=ram), self.machine(ram, "1000"):
                self.assertEqual(board.ram_room(), room)
        with mock.patch.object(board, "free_ram_pct", return_value=None):
            self.assertEqual(board.ram_room(), 1, "unknown RAM: one claim per call")

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

    def test_cpu_load_pct(self):
        self.assertEqual(board.MAX_CPU_LOAD_PCT, 150)
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT=""):
            with mock.patch.object(board.os, "getloadavg", return_value=(9.0, 12.0, 3.0)), \
                    mock.patch.object(board.os, "cpu_count", return_value=8):
                self.assertEqual(board.cpu_load_pct(), 150.0, "the 5-min reading, over all cores")
            with mock.patch.object(board.os, "getloadavg", side_effect=OSError("no load")), \
                    mock.patch.object(board.os, "cpu_count", return_value=8):
                self.assertIsNone(board.cpu_load_pct())
            with mock.patch.object(board.os, "getloadavg", return_value=(9.0, 12.0, 3.0)):
                for cores in (None, 0):
                    with self.subTest(cores=cores), mock.patch.object(board.os, "cpu_count", return_value=cores):
                        self.assertIsNone(board.cpu_load_pct())
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT="42.5"):
            self.assertEqual(board.cpu_load_pct(), 42.5)

    def test_machine_ok_cpu_load(self):
        """2026-10-25: 5-min load ~15 on 8 cores with healthy RAM; nothing held new work back."""
        reason = "CPU load 190% of 8 cores, limit 150%"
        cores = mock.patch.object(board.os, "cpu_count", return_value=8)
        high = mock.patch.object(board.os, "getloadavg", return_value=(1, 15.2, 1))
        with mock.patch.dict(os.environ, SCRUM_CPU_LOAD_PCT=""), cores:
            with high:
                self.assertEqual(board.machine_ok(self.tmp.name), reason)
                self.assertIsNone(board.machine_ok(self.tmp.name, manual=True), "Trevor's clicks skip the CPU check")
                self.assertIsNone(board.machine_ok(self.tmp.name, manual=True, claim=True))
                self.assertEqual(board.machine_ok(self.tmp.name, claim=True), reason)
                with self.machine("14", "1000"):
                    self.assertEqual(board.machine_ok(self.tmp.name), "free RAM 14% (< 20%)", "RAM first")
                    self.assertEqual(board.machine_ok(self.tmp.name, manual=True), "free RAM 14% (< 20%)",
                                     "manual still checks RAM")
                with self.sessions(14):
                    self.assertEqual(board.machine_ok(self.tmp.name), reason, "CPU before the session ceiling")
            with mock.patch.object(board.os, "getloadavg", return_value=(1, 12.0, 1)):
                self.assertIsNone(board.machine_ok(self.tmp.name), "exactly 150% passes")
            with mock.patch.object(board.os, "getloadavg", side_effect=OSError("no load")):
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

    def test_ram_room_is_one_while_swap_fills(self):
        with self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="15"):
            self.assertEqual(board.ram_room(), 1, "swap past MAX_SWAP_PCT/2: one claim per call")
        with self.machine("66", "1000"), mock.patch.dict(os.environ, SCRUM_SWAP_PCT="10"):
            self.assertEqual(board.ram_room(), 9)

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
        run = lambda *args: subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "abort", *args],
                                           capture_output=True, text=True)
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
        job = {"id": "001-a", "stage": "needs-human",
               "reason": "stalled in build: waiting for a free slot after Play. Fix: click Resume."}
        self.legacy_board(job)
        self.assertEqual(board.cmd_migrate_paused(self.root), [])
        self.assertEqual(self.jobs(), [job])

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
        out = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_digest_due_counts_only_undigested_done_jobs(self):
        done = self.done_jobs(9)
        self.done_jobs(2, "aborted")
        self.done_jobs(1, "review")
        self.done_jobs(1, "needs-human")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 9, "questionsGrowth": 0})
        done += self.done_jobs(1)
        self.assertEqual(self.cli("digest-due"), {"due": True, "undigested": 10, "questionsGrowth": 0})
        (self.root / "digests" / "001").mkdir(parents=True)
        (self.root / "digests" / "001" / "jobs.txt").write_text("\n".join(done[:4]) + "\n")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 6, "questionsGrowth": 0})
        self.assertEqual(board.digested_ids(self.root), set(done[:4]))

    def test_failed_digest_releases_its_jobs(self):
        a, b = self.done_jobs(2)
        d = self.root / "digests" / "001"
        d.mkdir(parents=True)
        (d / "jobs.txt").write_text(f"{a}\n{b}\n")
        self.assertEqual(board.digested_ids(self.root), {a, b})  # no error.md: still claimed
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0})
        (d / "error.md").write_text("digester produced no valid proposals\n")
        self.assertEqual(board.digested_ids(self.root), set())
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 2, "questionsGrowth": 0})
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
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0})

    def write_questions_log(self, n):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "questions.log").write_text("".join(f'{{"n": {i}}}\n' for i in range(n)))

    def marker(self, digest_id, text, error=False):
        d = self.root / "digests" / digest_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "jobs.txt").write_text("")
        (d / "questions.lines").write_text(text)
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
        self.assertEqual(self.cli("digest-due"), {"due": True, "undigested": 0, "questionsGrowth": 20})  # no marker yet
        self.marker("001", "5\n")
        self.assertEqual(self.cli("digest-due"), {"due": True, "undigested": 0, "questionsGrowth": 15})
        self.write_questions_log(19)
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 14})
        self.marker("002", "30\n")  # the log shrank below the marker
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0})
        self.marker("003", "junk\n")  # not an integer: ignored, 002 counts
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0})
        self.marker("004", "2\n", error=True)  # failed digest: skipped, 002 still counts
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0})
        (self.root / "digests" / "002" / "error.md").write_text("failed\n")  # now 001 counts
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 14})

    def test_digest_start_on_questions_growth_only(self):
        self.write_questions_log(14)
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": []})
        self.assertFalse((self.root / "digests").exists())
        self.write_questions_log(15)
        self.assertEqual(self.cli("digest-start"), {"id": "001", "jobs": []})
        self.assertEqual((self.root / "digests" / "001" / "jobs.txt").read_text(), "")
        self.assertEqual((self.root / "digests" / "001" / "questions.lines").read_text(), "15\n")
        self.assertEqual(self.cli("digest-due"), {"due": False, "undigested": 0, "questionsGrowth": 0})
        self.assertEqual(self.cli("digest-start"), {"id": None, "jobs": []})
        self.assertEqual(sorted(p.name for p in (self.root / "digests").iterdir()), ["001"])

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
        self.assertEqual(self.get(job_id)["stage"], "needs-human")
        self.assertEqual(self.get(job_id)["reason"], "stalled in review: no board or job-dir change for 2 h "
                         "(session alive but idle). Fix: click Resume.")
        self.assertEqual(self.get(paused)["stage"], "review")

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
        self.assertEqual(self.get(merging)["stage"], "needs-human")
        self.assertTrue(self.get(merging)["reason"].startswith("stalled in merging: "))

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
        self.assertEqual([set(l) for l in lines], [{"date", "project", "job", "kind", "reason"}] * 2)
        for l in lines:
            self.assertRegex(l["date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertEqual([(l["project"], l["job"], l["kind"], l["reason"]) for l in lines], [
            (Path(self.tmp.name).name, idle, "stall", "stalled in build: no board or job-dir change for 2 h "
             "(session alive but idle). Fix: click Resume."),
            (Path(self.tmp.name).name, dead, "stall", "stalled in build: no board update for 30 min and no live "
             "session. Fix: click Resume.")])

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
        self.assertEqual(self.get(std)["stage"], "needs-human")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [])
        self.assertEqual((self.get(lil)["stage"], self.get(lil)["updatedAt"]), ("build", old))

    def test_watchdog_flags_lilguy_with_worktree(self):
        wt = self.aged("Lil in worktree", 45, stage="build", lane="lilguy", worktree="/tmp/wt-lil")
        here = self.aged("Lil in checkout", 45, stage="build", lane="lilguy")
        self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [wt])
        self.assertEqual(self.get(wt)["stage"], "needs-human")
        self.assertTrue(self.get(wt)["reason"].startswith("stalled in build"), self.get(wt)["reason"])
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
        self.assertEqual(next(j for j in self.jobs() if j["id"] == job_id)["stage"], "needs-human")

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

    STALL = "stalled in build: no board update for 30 min and no live session. Fix: click Resume."

    def test_watchdog_stall_logs_roadmap_step(self):
        self.roadmap()
        board.cmd_new(self.root, "Quote builder part 2", self.J2)
        self.aged("Unrelated", 5, stage="build")
        for _ in range(2):  # stall, resume via roadmap-link, stall again: two Log lines
            data = json.loads((self.root / "board.json").read_text())
            next(j for j in data["jobs"] if j["id"] == self.J2).update(stage="build", updatedAt="2026-01-01T00:00:00+00:00")
            (self.root / "board.json").write_text(json.dumps(data))
            self.assertEqual(board.cmd_watchdog(self.root, alive=lambda job: False), [self.J2])
            self.assertEqual(self.get(self.J2)["stage"], "needs-human")
            self.assertIn(f"- [!] S2 bigboy {self.J2}:", self.rm_text())
            self.assertRegex(self.rm_text().splitlines()[-1],
                             self.LOG_RE + rf"P1 S2 stopped: {self.J2} stalled in build: no board update for 30 min "
                             r"and no live session\. Fix: click Resume\.$")
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
        self.assertRegex(logs[1], self.LOG_RE + rf"P1 S2 stopped: {child} stalled in build: ")

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
                self.assertEqual(self.get(job_id)["stage"], "needs-human")
                self.assertTrue(self.get(job_id)["reason"].startswith("stalled in review: "))
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
        self.assertEqual(board.wake_waiting(self.root), {"ready": [], "lost": []})


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


class DigestVerifyTest(unittest.TestCase):
    """board.py digest-verify: a job whose rules-file diff is exactly its cited, queued digest edits needs no human."""

    def test_rules_re_covers_lane_files(self):
        self.assertTrue(board.RULES_RE.search("skills/trevskills-scrum/lanes/cloud.md"))
        self.assertIsNone(board.RULES_RE.search("src/lanes/foo.md"))

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

    def test_review_plan_deletion_dominated_skips_ui_ux(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 100, "src/big.py": "x = 1\n" * 100})
        self.delete("src/big.py")
        self.commit("web/page.html", "<p>x</p>\n" * 9 + "<p>new</p>\n")  # +1 -91 on a UI file
        for globs in ("*.html", None):
            with self.subTest(globs=globs):
                self.project(globs)
                out = board.cmd_review_plan(self.root, self.job)
                self.assertEqual(out, {"spawn": ["code"], "since": None})
                self.assertEqual(self.read(1, "ui"), self.DEL_SKIP)
                self.assertEqual(self.read(1, "ux"), self.DEL_SKIP)
                self.assertEqual(self.read(1, "security"), self.SEC_SKIP)
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
        self.assertEqual(out["spawn"], ["code"])
        self.assertEqual(self.read(1, "ui"), self.DEL_SKIP)

    def test_review_plan_deletion_dominated_keeps_security_on_sensitive_path(self):
        self.big_base({"web/page.html": "<p>x</p>\n" * 50, "src/auth.py": "x = 1\n" * 50})
        self.delete("src/auth.py")
        self.commit("web/page.html", "<p>new</p>\n")
        out = board.cmd_review_plan(self.root, self.job)
        self.assertEqual(out, {"spawn": ["security", "code"], "since": None})
        self.assertEqual(self.read(1, "ui"), self.DEL_SKIP)
        self.assertFalse((self.rdir(1) / "review-security.md").exists())

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
        board.cmd_review_plan(self.root, self.job)
        self.assertEqual(self.read(1, "ui"), self.DEL_SKIP)
        self.assertFalse(board._real_review(self.rdir(1) / "review-ui.md"))
        self.commit("src/more.py", "y = 1\n" * 100)  # +101 -100: no longer deletion-dominated
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
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "review-plan", self.job,
                            "--incremental"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("\n"), 1)
        self.assertEqual(json.loads(r.stdout), {"spawn": ["security", "code"], "since": since})
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "review-plan", self.job],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"spawn": ["code"], "since": None})
        self.assertEqual((self.root / "board.json").read_bytes(), before)



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
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "route-check", self.job,
                            "--check-fails", "2"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"promote": None, "clean_round": False, "approver_sonnet": False})

    def test_route_check_unknown_job_fails(self):
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "route-check", "999-nope"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("999-nope", r.stderr)
        (self.root / "jobs" / "998-gone").mkdir()
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "route-check", "998-gone"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no job '998-gone' on the board", r.stderr)
        other = board.cmd_new(self.root, "Folder gone")
        (self.root / "jobs" / other).rmdir()
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "route-check", other],
                           capture_output=True, text=True)
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

    def test_route_check_promotes_on_more_than_3_files(self):
        self.assertEqual(self.promote({f"src/f{i}.py": "x\n" for i in range(4)}), "more than 3 files (4)")

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
        self.commit({"x/auth.py": "x\n", "x.html": "x\n", ".env": "A=1\n", "m.sql": "s\n"})
        self.assertEqual(self.route()["promote"], "more than 3 files (4)")
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

    def test_route_check_lilguy_4_files_promotes(self):
        self.assertEqual(self.lilguy({f"src/f{i}.py": "x\n" for i in range(4)}), "more than 3 files with added lines (4)")

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
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "route-check", self.job],
                           capture_output=True, text=True)
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

    def test_lilguy_fit_author_is_not_auth(self):
        self.points(1)
        (self.jd / "feature.md").write_text("Show the author name and the OAuthor badge\n")
        self.assertIs(self.fit()["fit"], True)
        (self.jd / "feature.md").write_text("Show the author name next to auth status\n")
        got = self.fit()
        self.assertIs(got["fit"], False)
        self.assertIn("auth", got["why"])

    def test_lilguy_fit_unknown_job_exits(self):
        r = subprocess.run([sys.executable, str(BOARD_PY), "--dir", str(self.root), "lilguy-fit", "999-nope"],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("999-nope", r.stderr)
        with self.assertRaises(SystemExit):
            board.cmd_lilguy_fit(self.root, "999-nope")


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
        argv = [sys.executable, str(BOARD_PY), "--dir", str(self.root), "window-report"]
        env = {**os.environ, **self.env}
        first = subprocess.run(argv, capture_output=True, text=True, env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        cards = json.loads(first.stdout)  # the real clock is long past R
        self.assertEqual([(c["window"], c["resets_at"]) for c in cards], [("five_hour", 1_700_000_000)])
        second = subprocess.run(argv, capture_output=True, text=True, env=env)
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
        self.board(("401-r", "done", R - 100), ("402-p", "done", R - 100, {"lane": "bigboy"}),
                   ("403-d", "running", R - 100, {"lane": "debug"}), ("404-q", "done", R - 5000),
                   ("405-d", "done", R - 100, {"lane": "debug"}), ("406-s", "done", R - 50),
                   ("407-d", "done", R - 100, {"lane": "debug"}))
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
            {"date": self.at(R - 300), "job": "402-p", "kind": "bigboy", "reason": "merged + gaps: two gaps"},
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
        self.assertEqual(board.cmd_ready(self.root, self.parent)["ready"], self.kids[1:], "no usage.json: no taper")

    def test_ready_holds_parent_with_usage_reason(self):
        self.write_usage(96)
        self.live(1)
        at = datetime.fromtimestamp(json.loads(self.usage.read_text())["rate_limits"]["five_hour"]["resets_at"])
        self.assertEqual(board.cmd_ready(self.root, self.parent)["ready"], [])
        p = self.parent_job()
        self.assertEqual((p["stage"], p["reason"]),
                         ("running", f"waiting: usage 5h 96% used, resets {at:%H:%M} (allowance 1, 1 live)"))
        self.write_usage(50)
        self.assertEqual(board.cmd_ready(self.root, self.parent)["ready"], self.kids)
        p = self.parent_job()
        self.assertEqual((p["stage"], p["reason"]), ("running", None))


if __name__ == "__main__":
    unittest.main()
