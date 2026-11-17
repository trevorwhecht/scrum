import ast, contextlib, io, json, subprocess, sys, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
sys.path.insert(0, str(SKILL))
import shop  # noqa: E402

ARGV = ["ssh", "shopmac", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
LIVE = "{ 2.96 2.42 2.26 }\n8\n/Users/x/.local/bin/gh\n/Users/x/.local/bin/claude\n"  # measured on the shop Mac 2026-11-17
UP = {"up": True, "load": 37.0, "tools": {"node": False, "gh": True, "claude": True}}
DOWN = {"up": False, "load": None, "tools": {"node": False, "gh": False, "claude": False}}


class ShopCase(unittest.TestCase):
    def setUp(self):
        # Hermetic: any real subprocess.run under these tests fails the test, so no real ssh ever starts.
        patcher = mock.patch.object(shop.subprocess, "run", side_effect=AssertionError("real ssh under unittest"))
        self.sp = patcher.start()
        self.addCleanup(patcher.stop)
        shop._cache = None
        self.addCleanup(setattr, shop, "_cache", None)

    def answer(self, returncode, stdout=b"", stderr=b""):
        self.sp.side_effect = None
        self.sp.return_value = subprocess.CompletedProcess([], returncode, stdout, stderr)

    def fake_run(self, returncode, stdout="", stderr=""):
        """Patch shop.run itself; returns the mock so a test can count probe's calls."""
        patcher = mock.patch.object(shop, "run", autospec=True,
                                    return_value=subprocess.CompletedProcess([], returncode, stdout, stderr))
        self.addCleanup(patcher.stop)
        return patcher.start()


class RunTest(ShopCase):
    def test_argv_alias_first_and_path_prefix(self):
        self.answer(0, b"hi\n")
        r = shop.run("echo hi", 7)
        self.sp.assert_called_once()
        args, kwargs = self.sp.call_args
        self.assertEqual(args, (ARGV + ['export PATH="$HOME/.local/bin:$PATH"; echo hi'],))
        self.assertEqual(kwargs["timeout"], 7)
        self.assertIs(kwargs["stdout"], subprocess.PIPE)
        self.assertIs(kwargs["stderr"], subprocess.PIPE)
        self.assertIsInstance(r, subprocess.CompletedProcess)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "hi\n", ""))

    def test_no_input_reads_devnull(self):
        self.answer(0)
        shop.run("true", 5)
        kwargs = self.sp.call_args.kwargs
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertNotIn("input", kwargs)

    def test_input_goes_to_stdin_not_argv(self):
        self.answer(0)
        shop.run("cat > token", 5, input="s3cret-tokén")
        args, kwargs = self.sp.call_args
        self.assertEqual(kwargs["input"], b"s3cret-tok\xc3\xa9n")
        self.assertNotIn("stdin", kwargs)  # subprocess.run refuses stdin together with input
        self.assertFalse(any("s3cret" in a for a in args[0]), args[0])
        shop.run("tar -x", 5, input=b"\x00\xffraw")
        self.assertEqual(self.sp.call_args.kwargs["input"], b"\x00\xffraw")

    def test_timeout_returns_124(self):
        self.sp.side_effect = subprocess.TimeoutExpired(cmd=["ssh"], timeout=3)
        r = shop.run("sleep 9", 3)
        self.assertEqual((r.returncode, r.stdout), (124, ""))
        self.assertIn("timed out after 3 s", r.stderr)

    def test_missing_ssh_returns_127(self):
        self.sp.side_effect = FileNotFoundError(2, "No such file or directory", "ssh")
        r = shop.run("true", 5)
        self.assertEqual((r.returncode, r.stdout), (127, ""))
        self.assertIn("No such file or directory", r.stderr)

    def test_ssh_255_passed_through(self):
        self.answer(255, stderr=b"ssh: Could not resolve hostname shopmac.local\r\n")
        r = shop.run("true", 5)
        self.assertEqual(r.returncode, 255)
        self.assertEqual(r.stderr, "ssh: Could not resolve hostname shopmac.local\r\n")

    def test_non_utf8_output_does_not_raise(self):
        self.answer(0, b"ok\xff", b"\xfe")
        r = shop.run("true", 5)
        self.assertEqual((r.stdout, r.stderr), ("ok�", "�"))


class ProbeTest(ShopCase):
    def test_parses_live_sample(self):
        run = self.fake_run(0, LIVE)
        self.assertEqual(shop.probe(), UP)
        run.assert_called_once_with("sysctl -n vm.loadavg hw.ncpu; command -v node gh claude; true", 10)
        shop._cache = None
        run.return_value = subprocess.CompletedProcess([], 0, "{ 1.00 0.50 0.25 }\n3\n/usr/local/bin/node\n", "")
        self.assertEqual(shop.probe(), {"up": True, "load": 33.3, "tools": {"node": True, "gh": False, "claude": False}})

    def test_garbled_output_up_with_unknowns(self):
        run = self.fake_run(0)
        for out in ("", "load: high\nmany cores\n", "{ 1.50 1.20 1.00 }\n0\n","��\n"):
            with self.subTest(out=out):
                shop._cache = None
                run.return_value = subprocess.CompletedProcess([], 0, out, "")
                self.assertEqual(shop.probe(), {"up": True, "load": None,
                                                "tools": {"node": False, "gh": False, "claude": False}})

    def test_down_is_silent(self):
        failures = {255: dict(return_value=subprocess.CompletedProcess([], 255, b"", b"ssh: connect to host port 22: Connection refused\r\n"),
                              side_effect=None),
                    124: dict(side_effect=subprocess.TimeoutExpired(cmd=["ssh"], timeout=10)),
                    127: dict(side_effect=FileNotFoundError(2, "No such file or directory", "ssh"))}
        for code, how in failures.items():
            with self.subTest(code=code):
                shop._cache = None
                self.sp.configure_mock(**how)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    got = shop.probe()
                self.assertEqual(got, DOWN)
                self.assertEqual((out.getvalue(), err.getvalue()), ("", ""))

    def cached(self, returncode, stdout, fresh, stale):
        run = self.fake_run(returncode, stdout)
        with mock.patch.object(shop, "time") as clock:
            clock.monotonic.return_value = 1000.0
            first = shop.probe()
            clock.monotonic.return_value = 1000.0 + fresh
            self.assertEqual(shop.probe(), first)
            self.assertEqual(run.call_count, 1)
            clock.monotonic.return_value = 1000.0 + stale
            shop.probe()
            self.assertEqual(run.call_count, 2)

    def test_up_cached_60s(self):
        self.cached(0, LIVE, 59, 61)

    def test_down_cached_300s(self):
        self.cached(255, "", 299, 301)


class CliTest(ShopCase):
    def main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = shop.main(argv)
        return rc, out.getvalue()

    def test_probe_prints_one_json_line(self):
        self.fake_run(0, LIVE)
        rc, out = self.main(["probe"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertEqual(json.loads(out), UP)

    def test_probe_down_prints_one_json_line(self):
        self.sp.side_effect = subprocess.TimeoutExpired(cmd=["ssh"], timeout=10)
        rc, out = self.main(["probe"])
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.splitlines()), 1, out)
        self.assertEqual(json.loads(out), DOWN)

    def test_missing_or_unknown_subcommand_is_usage_error(self):
        for argv in ([], ["nope"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(SystemExit) as cm:
                    shop.main(argv)
                self.assertEqual(cm.exception.code, 2)
                self.assertIn("usage:", err.getvalue())
        self.sp.assert_not_called()


class StructureTest(unittest.TestCase):
    def test_stdlib_only(self):
        tree = ast.parse((SKILL / "shop.py").read_text())
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "relative import")
                names.append(node.module)
        self.assertTrue(names)
        for name in names:
            self.assertIn(name.split(".")[0], sys.stdlib_module_names, name)

    def test_lane_file_sections(self):
        text = (SKILL / "lanes" / "shop.md").read_text()
        self.assertTrue(text.startswith("# Shop Mac\n\n## Transport and probe\n"), text[:60])
        for phrase in ("`ssh shopmac`", 'export PATH="$HOME/.local/bin:$PATH";', "`input`", "`124`", "`127`",
                       "60 s", "300 s", "prints nothing and raises nothing", "`python3 shop.py probe`"):
            self.assertIn(phrase, text, phrase)


if __name__ == "__main__":
    unittest.main()
