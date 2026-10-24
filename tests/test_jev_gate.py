import importlib.util, io, os, re, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
import board, jev  # noqa: E402

REAL_ASK = jev.ask

KEY = "sk-secret-test"
SECURITY_Q = "This diff needs a security review"
UI_Q = "This diff needs a UI review"
APPROVER_Q = "This diff changes payment, pricing, billing, authentication, session, role or permission logic"
DUPE_Q = "Item {i} is the same task as the query"
BACKLOG = ("# Backlog\n\n- [ ] [3] Add dark mode {#ab12} → 012-dark <!-- big -->\n- [x] Done thing\n"
           "- [ ] Fix login bug\n")


def load_gate():
    spec = importlib.util.spec_from_file_location("jev_gate", SKILL / "jev-gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def noul_ask(value):
    return lambda state, questions, timeout=jev.TIMEOUT, key=None: {q: {"type": "noul", "noul": value} for q in questions}


class JevGateTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.job = self.root / "jobs" / "001-x"
        self.job.mkdir(parents=True)
        env = mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": KEY})
        env.start()
        self.addCleanup(env.stop)
        self.sent = []

    def run_gate(self, argv, stdin="", ask=None):
        """Run main in-process with jev.ask stubbed. ask: callable, an exception to raise, REAL_ASK (the real client),
        or None (must not be called)."""
        def fake(state, questions, timeout=jev.TIMEOUT, key=None):
            self.sent.append((state, questions))
            if ask is None:
                raise AssertionError("Jev was called")
            if ask is REAL_ASK:
                return REAL_ASK(state, questions, timeout, key)
            if isinstance(ask, BaseException):
                raise ask
            return ask(state, questions, timeout, key)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(jev, "ask", side_effect=fake), mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                redirect_stdout(out), redirect_stderr(err):
            code = load_gate().main(argv)
        return code, out.getvalue(), err.getvalue()

    def log(self):
        p = self.job / "jev.log"
        return p.read_text().splitlines() if p.exists() else []

    def gate(self, step, stdin="", ask=None):
        """Run one step; assert the shared contract and return (stdout line, the one log line's fields)."""
        code, out, err = self.run_gate([step, str(self.job)], stdin, ask)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("\n"), 1, out)
        lines = self.log()
        self.assertEqual(len(lines), 1, lines)
        fields = lines[0].split("\t")
        self.assertEqual(len(fields), 6, fields)
        (self.job / "jev.log").unlink()
        return out.rstrip("\n"), fields

    def test_log_line_shape(self):
        out, f = self.gate("reviewer-ui", "a\tdiff\nsummary", noul_ask(0.9))
        self.assertEqual(out, "add")
        self.assertRegex(f[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual(f[1:5], ["reviewer-ui", UI_Q, '{"type":"noul","noul":0.9}', "add"])
        self.assertRegex(f[5], r"^\d+\.\d\d$")
        # tabs and newlines inside a field become spaces
        out, f = self.gate("promote", "CHECK:\tFAIL\nmore\n")
        self.assertEqual(f[1:5], ["promote", "-", "CHECK: FAIL more", "opus"])
        # appends, never truncates
        self.gate("promote", "x")
        self.run_gate(["promote", str(self.job)], "one")
        self.run_gate(["promote", str(self.job)], "two")
        self.assertEqual([l.split("\t")[3] for l in self.log()], ["one", "two"])

    def test_unknown_step_exits_nonzero(self):
        for argv in (["nope", str(self.job)], ["model"], ["model", str(self.job), "extra"], []):
            with self.subTest(argv=argv):
                code, out, err = self.run_gate(argv)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("usage: jev-gate.py", err)
                self.assertEqual(self.log(), [])

    def test_fallbacks(self):
        (self.job / "feature.md").write_text("# Feature\nDo a thing")
        (self.root / "backlog.md").write_text(BACKLOG)
        bad = {"model": {"q": {"score": 7}}, "dupe": {"q0": {"noul": "high"}, "q1": {"noul": 0.1}},
               "approver": {"q": {"noul": "high"}}, "reviewer-security": {"q": {"noul": 1.5}},
               "reviewer-ui": {"q": {"noul": "high"}}}
        fallback = {"model": "opus", "dupe": "add", "approver": "opus", "reviewer-security": "skip",
                    "reviewer-ui": "skip"}
        for step, want in fallback.items():
            kinds = {"nokey": (None, "JevError"), "timeout": (TimeoutError("timed out"), "TimeoutError"),
                     "other": (RuntimeError("boom"), "RuntimeError"),
                     "unparseable": (lambda *a, b=bad[step]: b, "JevError")}
            for kind, (ask, raw) in kinds.items():
                with self.subTest(step=step, kind=kind):
                    if kind == "nokey":
                        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), \
                                mock.patch.object(jev, "api_key", side_effect=jev.JevError("no key")), \
                                mock.patch("jev.urllib.request.urlopen", side_effect=AssertionError("network")):
                            out, f = self.gate(step, "new item text", REAL_ASK)
                    else:
                        out, f = self.gate(step, "new item text", ask)
                    self.assertEqual(out, want)
                    self.assertEqual((f[1], f[3], f[4]), (step, raw, want))

    def test_decide_fails_before_jev_call_logs_dash(self):
        (self.job / "feature.md").mkdir()  # exists but unreadable as text
        out, f = self.gate("model")
        self.assertEqual((out, f[1:5]), ("opus", ["model", "-", "IsADirectoryError", "opus"]))
        with mock.patch.object(board, "read_backlog", side_effect=OSError("denied")):
            out, f = self.gate("dupe", "new item text")
        self.assertEqual((out, f[1:5]), ("add", ["dupe", "-", "OSError", "add"]))
        self.assertEqual(self.sent, [])

    def test_model_cutoffs(self):
        (self.job / "feature.md").write_text("# Feature\nAdd a button")
        for score, want in ((0, "sonnet"), (1, "sonnet"), (2, "opus"), (3, "opus")):
            with self.subTest(score=score):
                self.sent.clear()
                out, f = self.gate("model", ask=lambda s, q, *a, v=score: {"q": {"type": "score", "score": v}})
                self.assertEqual(out, want)
                self.assertEqual(f[4], want)
                state, questions = self.sent[0]
                self.assertEqual(state, "# Feature\nAdd a button")
                self.assertEqual(questions["q"]["type"], "score")
                self.assertEqual(len(questions["q"]["criteria"]), 4)

    def test_model_missing_feature(self):
        out, f = self.gate("model")
        self.assertEqual((out, f[2], f[3], f[4]), ("opus", "-", "-", "opus"))
        (self.job / "feature.md").write_text(" \n")
        out, f = self.gate("model")
        self.assertEqual((out, f[2], f[3], f[4]), ("opus", "-", "-", "opus"))
        self.assertEqual(self.sent, [])

    def test_promote_logs_reason(self):
        out, f = self.gate("promote", "  VERDICT: CHANGES\n")
        self.assertEqual((out, f[1], f[2], f[3], f[4]), ("opus", "promote", "-", "VERDICT: CHANGES", "opus"))
        out, f = self.gate("promote", "  \n")
        self.assertEqual((out, f[3]), ("opus", "-"))
        self.assertEqual(self.sent, [])

    def test_dupe_cutoffs(self):
        (self.root / "backlog.md").write_text(BACKLOG)
        for top, want in ((0.8, "dupe Add dark mode"), (0.79, "add")):
            with self.subTest(top=top):
                self.sent.clear()
                out, f = self.gate("dupe", "dark theme toggle\n",
                                   lambda s, q, *a, v=top: {"q0": {"noul": v}, "q1": {"noul": 0.1}})
                self.assertEqual(out, want)
                self.assertEqual((f[2], f[4]), (DUPE_Q, want))
                self.assertEqual(self.sent, [({"query": "dark theme toggle", "items": {"0": "Add dark mode",
                                                                                       "1": "Fix login bug"}},
                                              {"q0": {"type": "noul", "instructions": "Item 0 is the same task as the query"},
                                               "q1": {"type": "noul", "instructions": "Item 1 is the same task as the query"}})])
        # the top item wins even when it is not first
        out, _ = self.gate("dupe", "login", lambda s, q, *a: {"q0": {"noul": 0.2}, "q1": {"noul": 0.95}})
        self.assertEqual(out, "dupe Fix login bug")

    def test_dupe_empty_backlog_no_call(self):
        out, f = self.gate("dupe", "anything")  # no backlog.md
        self.assertEqual((out, f[2], f[3]), ("add", "-", "-"))
        (self.root / "backlog.md").write_text("# Backlog\n- [x] Done thing\n")
        self.assertEqual(self.gate("dupe", "anything")[0], "add")
        (self.root / "backlog.md").write_text(BACKLOG)
        self.assertEqual(self.gate("dupe", " \n")[0], "add")
        self.assertEqual(self.sent, [])

    def test_dupe_leaves_backlog_untouched(self):
        p = self.root / "backlog.md"
        p.write_bytes(BACKLOG.encode())
        self.gate("dupe", "dark", lambda s, q, *a: {"q0": {"noul": 0.9}, "q1": {"noul": 0.1}})
        self.gate("dupe", "dark", RuntimeError("boom"))
        self.assertEqual(p.read_bytes(), BACKLOG.encode())

    def test_approver_cutoffs(self):
        for v, want in ((0.29, "sonnet"), (0.3, "opus")):
            with self.subTest(v=v):
                self.sent.clear()
                out, f = self.gate("approver", "3 files changed\nspec: thing", noul_ask(v))
                self.assertEqual((out, f[2]), (want, APPROVER_Q))
                self.assertEqual(self.sent[0][0], "3 files changed\nspec: thing")

    def test_reviewer_cutoffs(self):
        for step, q in (("reviewer-security", SECURITY_Q), ("reviewer-ui", UI_Q)):
            for v, want in ((0.7, "add"), (0.69, "skip")):
                with self.subTest(step=step, v=v):
                    out, f = self.gate(step, "diff summary", noul_ask(v))
                    self.assertEqual((out, f[2]), (want, q))

    def test_key_never_leaks(self):
        (self.job / "feature.md").write_text("feature")
        (self.root / "backlog.md").write_text(BACKLOG)
        good = {"model": lambda s, q, *a: {"q": {"score": 1, "echo": KEY}},
                "dupe": lambda s, q, *a: {"q0": {"noul": 0.1, "echo": KEY}, "q1": {"noul": 0.2}},
                "approver": noul_ask(0.5), "reviewer-security": noul_ask(0.9), "reviewer-ui": noul_ask(0.1),
                "promote": None}
        for step, ok in good.items():
            for ask in (ok, jev.JevError(f"HTTP 401 bad key {KEY}"), RuntimeError(f"boom {KEY}")):
                with self.subTest(step=step, ask=ask):
                    code, out, err = self.run_gate([step, str(self.job)], f"summary {KEY}" if step == "promote" else "x",
                                                   ask)
                    self.assertEqual(code, 0)
                    for text in (out, err, (self.job / "jev.log").read_text()):
                        self.assertNotIn(KEY, text)


    # --- rank ---
    def rank_ask(self, importance=2, necessity=2, progress=0.9, kind="bug"):
        return lambda s, q, *a: {"importance": {"type": "score", "score": importance},
                                 "necessity": {"type": "score", "score": necessity},
                                 "progress": {"type": "noul", "noul": progress},
                                 "kind": {"type": "choice", "choice": kind}}

    def test_rank_prints_priority_and_kind(self):
        (self.root / "roadmap.md").write_text("ROADMAP: x\nGoal: Ship the billing page\n\n## P1 a\n")
        out, f = self.gate("rank", "  Fix the refund rounding bug\n", self.rank_ask(3.8, 2, 0.9, "bug"))
        self.assertEqual(out, "p5 bug")
        self.assertEqual((f[1], f[4]), ("rank", "p5 bug"))
        self.assertEqual(len(self.sent), 1)
        state, qs = self.sent[0]
        self.assertEqual(state, {"ticket": "Fix the refund rounding bug", "goal": "Ship the billing page"})
        self.assertEqual(sorted(qs), ["importance", "kind", "necessity", "progress"])
        self.assertEqual(qs["importance"]["type"], "score")
        self.assertEqual([c.split(" (")[0] for c in qs["importance"]["criteria"]],
                         ["Trivial", "Minor", "Moderate", "High", "Critical"])
        self.assertEqual(qs["necessity"]["type"], "score")
        self.assertEqual([c.split(" (")[0] for c in qs["necessity"]["criteria"]],
                         ["Unnecessary", "Optional", "Should do eventually", "Needed"])
        self.assertEqual(qs["progress"], {"type": "noul", "instructions":
                         "Doing this ticket moves the project meaningfully closer to completing its stated goal / "
                         "current roadmap, rather than being side work"})
        self.assertEqual(qs["kind"]["type"], "choice")
        self.assertEqual(qs["kind"]["criteria"], ["bug", "security", "feature", "ui-polish", "ux-a11y", "refactor-dedupe",
                                                  "dead-code-lint", "tests", "docs-rules", "ops-manual"])

    def test_rank_mapping(self):
        (self.root / "project.md").write_text("- Notes: Make the app fast\n")
        cases = [((3.8, 2, 0.9, "bug"), "p5 bug"), ((0.2, 0.4, 0.9, "bug"), "p1 bug"),
                 ((2, 2, 0.2, "ui-polish"), "p2 ui-polish"), ((2, 2, 0.2, "feature"), "p3 feature"),
                 ((2, 0.5, 0.2, "dead-code-lint"), "p2 dead-code-lint"), ((4, 3, 0.1, "ux-a11y"), "p4 ux-a11y"),
                 ((1, 3, 0.6, "ux-a11y"), "p2 ux-a11y")]
        for args, want in cases:
            with self.subTest(args=args):
                self.assertEqual(self.gate("rank", "ticket", self.rank_ask(*args))[0], want)

    def test_rank_goal_source_fallback(self):
        (self.root / "project.md").write_text("# Project\n- Stack: x\n- Notes: Notes goal here\n")
        for roadmap, want in ((None, "Notes goal here"), ("ROADMAP: r\nGoal:   \n## P1 a\n", "Notes goal here"),
                              ("ROADMAP: r\n## P1 a\n", "Notes goal here"),
                              ("ROADMAP: r\nGoal: Roadmap goal\n## P1 a\n", "Roadmap goal")):
            with self.subTest(roadmap=roadmap):
                (self.root / "roadmap.md").unlink(missing_ok=True)
                if roadmap is not None:
                    (self.root / "roadmap.md").write_text(roadmap)
                self.sent.clear()
                self.assertEqual(self.gate("rank", "ticket", self.rank_ask())[0], "p3 bug")
                self.assertEqual(self.sent[0][0]["goal"], want)

    def test_rank_none_fallback(self):
        (self.root / "project.md").write_text("- Notes: The goal\n")
        for stdin in ("", " \n\t"):
            with self.subTest(stdin=stdin):
                out, f = self.gate("rank", stdin)  # ask=None: a Jev call fails the test
                self.assertEqual((out, f[1], f[2], f[4]), ("none", "rank", "-", "none"))
        bad = {"timeout": TimeoutError("t"), "jeverror": jev.JevError("x"),
               "importance": self.rank_ask(importance=4.5), "necessity": self.rank_ask(necessity=-1),
               "progress": self.rank_ask(progress=1.2), "kind": self.rank_ask(kind="chore"),
               "missing": lambda s, q, *a: {"importance": {"score": 2}}}
        for name, ask in bad.items():
            with self.subTest(case=name):
                out, f = self.gate("rank", "ticket", ask)
                self.assertEqual((out, f[4]), ("none", "none"))
        n = len(self.sent)
        for project in ("- Notes:   \n", "# no notes\n", None):
            with self.subTest(project=project):
                (self.root / "project.md").unlink(missing_ok=True)
                if project is not None:
                    (self.root / "project.md").write_text(project)
                self.assertEqual(self.gate("rank", "ticket")[0], "none")
        self.assertEqual(len(self.sent), n)

    def test_usage_lists_rank(self):
        code, out, err = self.run_gate([])
        self.assertEqual(code, 2)
        self.assertIn("rank", err.split("<")[1])

if __name__ == "__main__":
    unittest.main()
