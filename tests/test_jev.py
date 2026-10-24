import http.client, importlib.util, io, json, os, socket, subprocess, sys, tempfile, unittest, urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
import jev  # noqa: E402

KEY = "sk-secret-test"


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def answers(q):
    return Resp(json.dumps({"answers": {"q": q}}).encode())


def http_error(code, body=b"", reason="Err"):
    return urllib.error.HTTPError(jev.URL, code, reason, {}, io.BytesIO(body))


class JevTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": KEY})
        env.start()
        self.addCleanup(env.stop)
        sleep = mock.patch("jev.time.sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def urlopen(self, *results):
        """Patch urlopen; each call takes the next result (raised when an exception). Records (req, timeout)."""
        self.calls = []
        it = iter(results)

        def fake(req, timeout=None):
            self.calls.append((req, timeout))
            r = next(it)
            if isinstance(r, BaseException):
                raise r
            return r
        p = mock.patch("jev.urllib.request.urlopen", side_effect=fake)
        p.start()
        self.addCleanup(p.stop)

    def sent(self, i=0):
        req = self.calls[i][0]
        return req, json.loads(req.data)

    def check_headers(self, req):
        self.assertEqual(req.full_url, "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-secret-test")
        self.assertEqual(req.get_header("Content-type"), "application/json")

    def test_noul_request_and_parse(self):
        self.urlopen(answers({"type": "noul", "noul": 0.75, "confidence": 0.9}))
        value, raw = jev.noul({"a": 1}, "is good")
        self.assertEqual(value, 0.75)
        self.assertIsInstance(value, float)
        self.assertEqual(raw, {"type": "noul", "noul": 0.75, "confidence": 0.9})
        self.assertEqual(len(self.calls), 1)
        req, body = self.sent()
        self.check_headers(req)
        self.assertEqual(body, {"model": "jev-latest", "state": {"a": 1},
                                "questions": {"q": {"type": "noul", "instructions": "is good"}}})

    def test_score_request_and_parse(self):
        self.urlopen(answers({"type": "score", "score": 1.43}))
        value, raw = jev.score("s", "how good", ["bad", "ok", "great"])
        self.assertEqual(value, 1.43)
        self.assertEqual(raw, {"type": "score", "score": 1.43})
        req, body = self.sent()
        self.check_headers(req)
        self.assertEqual(body, {"model": "jev-latest", "state": "s", "questions": {
            "q": {"type": "score", "instructions": "how good", "criteria": ["bad", "ok", "great"]}}})

    def test_choice_request_and_parse(self):
        self.urlopen(answers({"type": "choice", "choice": "red"}))
        value, raw = jev.choice("s", "which", {"red": "warm", "blue": "cold"})
        self.assertEqual(value, "red")
        self.assertEqual(raw, {"type": "choice", "choice": "red"})
        req, body = self.sent()
        self.check_headers(req)
        self.assertEqual(body, {"model": "jev-latest", "state": "s", "questions": {
            "q": {"type": "choice", "instructions": "which", "criteria": {"red": "warm", "blue": "cold"}}}})

    def test_choice_criteria_sent_as_dict(self):
        # The Jev API 422s a list of choice criteria; a list of option names must go out as {name: name}.
        kind = lambda a: Resp(json.dumps({"answers": {"kind": a}}).encode())
        questions = {"kind": {"type": "choice", "instructions": "i", "criteria": ["bug", "feature"]}}
        self.urlopen(kind({"choice": "bug"}), kind({"choice": "nope"}))
        value, raw = jev.ask_many("s", questions)["kind"]
        self.assertEqual((value, raw), ("bug", {"choice": "bug"}))
        self.assertEqual(self.sent()[1]["questions"]["kind"]["criteria"], {"bug": "bug", "feature": "feature"})
        self.assertEqual(questions["kind"]["criteria"], ["bug", "feature"])
        with self.assertRaises(jev.JevError):
            jev.ask_many("s", questions)

        self.urlopen(answers({"choice": "red"}), answers({"choice": "green"}))
        self.assertEqual(jev.choice("s", "which", ["red", "blue"])[0], "red")
        self.assertEqual(self.sent()[1]["questions"]["q"]["criteria"], {"red": "red", "blue": "blue"})
        with self.assertRaises(jev.JevError):
            jev.choice("s", "which", ["red", "blue"])

    def test_bad_answers_raise(self):
        levels, options = ["a", "b", "c"], {"x": "1", "y": "2"}
        cases = [
            (lambda: jev.noul("s", "i"), Resp(b"<html>not json")),
            (lambda: jev.noul("s", "i"), Resp(b'{"nope": 1}')),
            (lambda: jev.noul("s", "i"), Resp(b'{"answers": {"other": {"noul": 0.5}}}')),
            (lambda: jev.noul("s", "i"), answers({"noul": 1.5})),
            (lambda: jev.noul("s", "i"), answers({"noul": -0.1})),
            (lambda: jev.noul("s", "i"), answers({"noul": "0.5"})),
            (lambda: jev.noul("s", "i"), answers({})),
            (lambda: jev.score("s", "i", levels), answers({"score": 2.5})),
            (lambda: jev.score("s", "i", levels), answers({"score": -1})),
            (lambda: jev.score("s", "i", levels), answers({"score": None})),
            (lambda: jev.choice("s", "i", options), answers({"choice": "z"})),
            (lambda: jev.choice("s", "i", options), answers({})),
        ]
        for call, resp in cases:
            with self.subTest(resp=resp.getvalue()):
                self.urlopen(resp)
                with self.assertRaises(jev.JevError):
                    call()

    def test_bad_arguments_raise_without_request(self):
        self.urlopen()
        for call in (lambda: jev.score("s", "i", ["only"]), lambda: jev.score("s", "i", []),
                     lambda: jev.choice("s", "i", {"only": "one"}), lambda: jev.choice("s", "i", {})):
            with self.assertRaises(jev.JevError):
                call()
        self.assertEqual(self.calls, [])

    def test_retry_then_success(self):
        self.urlopen(http_error(429), http_error(529), answers({"noul": 0.2}))
        self.assertEqual(jev.noul("s", "i")[0], 0.2)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual([c.args for c in self.sleep.call_args_list], [(1,), (2,)])

    def test_retry_exhausted_raises(self):
        self.urlopen(*[http_error(429) for _ in range(5)])
        with self.assertRaises(jev.JevError) as e:
            jev.noul("s", "i")
        self.assertIn("429", str(e.exception))
        self.assertEqual(len(self.calls), 4)
        self.assertEqual([c.args for c in self.sleep.call_args_list], [(1,), (2,), (4,)])

    def test_other_http_error_no_retry(self):
        for code in (400, 500, 503):
            with self.subTest(code=code):
                self.urlopen(http_error(code, b"bad thing"), answers({"noul": 0.5}))
                with self.assertRaises(jev.JevError) as e:
                    jev.noul("s", "i")
                self.assertIn(str(code), str(e.exception))
                self.assertIn("bad thing", str(e.exception))
                self.assertEqual(len(self.calls), 1)
        self.sleep.assert_not_called()

    def test_missing_key_raises(self):
        self.urlopen()
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), \
                mock.patch("jev.subprocess.run", return_value=subprocess.CompletedProcess([], 44, "", "")) as run:
            with self.assertRaises(jev.JevError) as e:
                jev.noul("s", "i")
        self.assertEqual(str(e.exception), "no TYPESAFE_API_KEY and no Keychain item TypeSafe/typesafe")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/security", "find-generic-password",
                                                 "-s", "TypeSafe", "-a", "typesafe", "-w"])
        self.assertEqual(self.calls, [])

    def test_keychain_key_used(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), \
                mock.patch("jev.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "kc-key\n", "")):
            self.assertEqual(jev.api_key(), "kc-key")

    def test_missing_security_binary_raises(self):
        self.urlopen()
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}), \
                mock.patch("jev.subprocess.run", side_effect=FileNotFoundError("security")):
            with self.assertRaises(jev.JevError) as e:
                jev.noul("s", "i")
        self.assertEqual(str(e.exception), "no TYPESAFE_API_KEY and no Keychain item TypeSafe/typesafe")
        self.assertEqual(self.calls, [])

    def test_timeout_raises(self):
        self.assertEqual(jev.TIMEOUT, 90)
        for exc in (socket.timeout("timed out"), TimeoutError("timed out")):
            self.urlopen(exc)
            with self.assertRaises(jev.JevError):
                jev.noul("s", "i")
        # each urlopen gets the time left of the 90 s budget
        self.urlopen(answers({"noul": 0.5}))
        jev.noul("s", "i")
        self.assertTrue(0 < self.calls[0][1] <= 90, self.calls[0][1])
        # a retry sleep that would pass the deadline raises instead of sleeping
        self.sleep.reset_mock()
        self.urlopen(http_error(429), answers({"noul": 0.5}))
        with self.assertRaises(jev.JevError):
            jev.noul("s", "i", timeout=0.5)
        self.assertEqual(len(self.calls), 1)
        self.sleep.assert_not_called()

    def test_urlerror_raises(self):
        self.urlopen(urllib.error.URLError("nodename nor servname provided"))
        with self.assertRaises(jev.JevError) as e:
            jev.noul("s", "i")
        self.assertIn("nodename", str(e.exception))

    def read_fails(self, exc):
        class Bad(Resp):
            def read(self, *a):
                raise exc
        self.urlopen(Bad())
        with self.assertRaises(jev.JevError) as e:
            jev.noul("s", "i")
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("sk-secret-test", str(e.exception))
        return str(e.exception)

    def test_incomplete_read_raises(self):
        self.assertIn("IncompleteRead", self.read_fails(http.client.IncompleteRead(b"partial")))

    def test_connection_reset_raises(self):
        self.assertIn("ConnectionResetError", self.read_fails(ConnectionResetError("reset sk-secret-test")))

    def test_key_never_in_output(self):
        paths = [
            (http_error(401, b'{"error": "bad key sk-secret-test"}', "Unauthorized"),),
            tuple(http_error(429, b"slow down sk-secret-test") for _ in range(4)),
            (urllib.error.URLError("refused for sk-secret-test"),),
            (socket.timeout("timed out"),),
            (Resp(b"not json sk-secret-test"),),
            (answers({"noul": "sk-secret-test"}),),
        ]
        for results in paths:
            out, err = io.StringIO(), io.StringIO()
            self.urlopen(*results)
            with redirect_stdout(out), redirect_stderr(err), self.assertRaises(jev.JevError) as e:
                jev.noul("s", "i")
            for text in (out.getvalue(), err.getvalue(), str(e.exception)):
                self.assertNotIn("sk-secret-test", text)
        self.urlopen(http_error(401, b"bad key sk-secret-test", "Unauthorized"))
        with self.assertRaises(jev.JevError) as e:
            jev.noul("s", "i")
        self.assertIn("401", str(e.exception))
        self.assertIn("Unauthorized", str(e.exception))
        self.assertIn("bad key ***", str(e.exception))


def load_rank():
    spec = importlib.util.spec_from_file_location("jev_rank", SKILL / "jev-rank.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class JevRankTest(unittest.TestCase):
    def run_main(self, argv, stdin):
        rank = load_rank()
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["jev-rank.py", *argv]), mock.patch.object(sys, "stdin", io.StringIO(stdin)), \
                redirect_stdout(out):
            rank.main()
        return out.getvalue()

    def test_jev_rank_output_matches(self):
        lines = [f"line {i} " + "x" * (2000 if i == 3 else 0) for i in range(25)]
        sent = []

        def fake_ask(state, questions, timeout=jev.TIMEOUT, key=None):
            sent.append((state, questions, key))
            # score = (global index) / 100, so line 24 is best
            base = int(state["items"]["0"].split()[1])
            return {q: {"type": "noul", "noul": (base + int(q[1:])) / 100} for q in questions}

        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": KEY}), mock.patch.object(jev, "ask", side_effect=fake_ask):
            out = self.run_main(["the query", "--top", "3", "--min", "0.22"], "\n".join(lines[:10]) + "\n\n  \n" +
                                "\n".join(lines[10:]) + "\n")
        self.assertEqual(out, f"0.24\t{lines[24]}\n0.23\t{lines[23]}\n0.22\t{lines[22]}\n")
        sent.sort(key=lambda s: len(s[1]), reverse=True)
        self.assertEqual([len(s[1]) for s in sent], [20, 5])
        state, questions, key = sent[0]
        self.assertEqual(key, KEY)
        self.assertEqual(state["query"], "the query")
        self.assertEqual(state["items"]["0"], "line 0 ")
        self.assertEqual(state["items"]["3"], ("line 3 " + "x" * 2000)[:1500])
        self.assertEqual(len(state["items"]["3"]), 1500)
        self.assertEqual(questions["q7"], {"type": "noul",
                                           "instructions": "Item 7 is relevant to the query and worth reading in full"})
        self.assertEqual(sent[1][0]["items"], {str(i): f"line {20 + i} " for i in range(5)})
        # --min filter: nothing at or above 0.5
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": KEY}), mock.patch.object(jev, "ask", side_effect=fake_ask):
            self.assertEqual(self.run_main(["q", "--min", "0.5"], "\n".join(lines) + "\n"), "")

    def test_jev_rank_error_exits_nonzero(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": KEY}), \
                mock.patch.object(jev, "ask", side_effect=jev.JevError("HTTP 500 boom")):
            with self.assertRaises(SystemExit) as e:
                self.run_main(["q"], "a\nb\n")
        self.assertEqual(e.exception.code, "jev-rank: HTTP 500 boom")

    def test_jev_rank_empty_stdin_skips_key_lookup(self):
        with mock.patch.object(jev, "api_key", side_effect=AssertionError("key looked up")) as key, \
                mock.patch.object(jev, "ask", side_effect=AssertionError("request sent")):
            self.assertEqual(self.run_main(["q"], "\n \n"), "")
        key.assert_not_called()

    def test_jev_rank_via_symlink_empty_stdin(self):
        with tempfile.TemporaryDirectory() as t:
            link = Path(t) / "jev-rank.py"
            link.symlink_to(SKILL / "jev-rank.py")
            env = {k: v for k, v in os.environ.items() if k != "TYPESAFE_API_KEY"}
            r = subprocess.run([sys.executable, str(link), "anything"], input="\n  \n", capture_output=True,
                               text=True, env=env, cwd=t)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))


if __name__ == "__main__":
    unittest.main()
