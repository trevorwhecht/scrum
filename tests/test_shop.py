import ast, contextlib, datetime, hashlib, io, json, os, shutil, stat, subprocess, sys, tarfile, tempfile, time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
WRAPPER = ROOT / "skills" / "trevskills-e2e" / "channel.config.mjs"
sys.path.insert(0, str(SKILL))
# workers.txt never the real one
os.environ.setdefault("SCRUM_REGISTRY", os.path.join(tempfile.mkdtemp(), "projects.json"))
import shop  # noqa: E402

REAL_RUN = subprocess.run  # ShopCase patches the subprocess module's run; local-shell checks use this one

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
        shop._cache.clear()
        shop._ready.clear()
        self.addCleanup(shop._cache.clear)
        self.addCleanup(shop._ready.clear)

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

    def test_alias_in_argv_and_bad_alias_refused(self):
        self.answer(0, b"hi\n")
        shop.run("echo hi", 7, alias="newmac.local")
        self.assertEqual(self.sp.call_args.args,
                         (["ssh", "newmac.local", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                           'export PATH="$HOME/.local/bin:$PATH"; echo hi'],))
        self.sp.reset_mock()
        for bad in ("-oProxyCommand=x", "user@host", "", "a b", ".hidden", "new mac", "x\n"):
            with self.subTest(alias=bad):
                r = shop.run("echo hi", 7, alias=bad)
                self.assertEqual((r.returncode, r.stdout), (127, ""))
        self.sp.assert_not_called()

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


class UnreachableWorkerTest(ShopCase):
    """Job 1650: the first failed ssh marks the worker down, so later steps cost no ssh call."""
    UP_CACHED = {"up": True, "load": 1.0, "tools": {t: True for t in shop.TOOLS}}

    def hang(self):
        self.ssh = []

        def fake(argv, **kw):
            self.ssh.append(argv[6])
            raise subprocess.TimeoutExpired(argv, kw["timeout"])
        self.sp.side_effect = fake

    def test_timeout_counts_as_unreachable(self):
        shop._cache["shopmac"] = (time.monotonic(), self.UP_CACHED)
        self.hang()
        self.assertEqual(shop.run("true", 5, alias="shopmac").returncode, 124)
        self.assertFalse(shop._cache["shopmac"][1]["up"])
        self.assertEqual(shop.run("true", 5, alias="shopmac").returncode, 255)
        self.assertEqual(len(self.ssh), 1)

    def test_ssh_failure_and_start_failure_count_as_unreachable(self):
        for how in (subprocess.CompletedProcess([], 255, b"", b"refused"), FileNotFoundError("ssh")):
            with self.subTest(how=how):
                shop._cache.clear()
                self.sp.reset_mock()
                self.sp.side_effect = [how] if isinstance(how, BaseException) else None
                self.sp.return_value = how
                shop.run("true", 5, alias="shopmac")
                self.assertFalse(shop._cache["shopmac"][1]["up"])

    def test_remote_127_leaves_worker_up(self):
        shop._cache["shopmac"] = (time.monotonic(), self.UP_CACHED)
        self.answer(127, b"", b"gh: not found")
        self.assertEqual(shop.run("gh x", 5, alias="shopmac").returncode, 127)
        self.assertTrue(shop._cache["shopmac"][1]["up"])

    def test_midpass_ssh_failure_stops_later_steps(self):
        shop._cache["shopmac"] = (time.monotonic(), self.UP_CACHED)
        self.hang()
        self.assertFalse(shop.ready("shopmac")["ready"])
        shop.run("git clone x", 60, alias="shopmac")
        self.assertEqual(len(self.ssh), 1, self.ssh)

    def test_backoff_after_unreachable_worker(self):
        shop._cache["shopmac"] = (time.monotonic(), self.UP_CACHED)
        self.hang()
        shop.run("x", 5, alias="shopmac")
        self.assertFalse(shop.probe("shopmac")["up"])  # cached down: no probe ssh within DOWN_TTL
        self.assertEqual(len(self.ssh), 1)

    def test_recovered_worker_dispatches(self):
        shop._cache["shopmac"] = (time.monotonic() - shop.DOWN_TTL - 1, {"up": False, "load": None, "tools": {}})
        self.answer(0, b"{ 1.00 0.50 0.25 }\n4\n")
        self.assertTrue(shop.probe("shopmac")["up"])
        self.assertEqual(shop.run("true", 5, alias="shopmac").returncode, 0)


class UnittestGuardTest(unittest.TestCase):
    def test_real_run_never_starts_ssh_under_unittest(self):
        # No ShopCase patch here: a watchdog test that reaches shop_tick must never ssh the real shop Mac.
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "ssh-ran"
            fake = Path(tmp) / "ssh"
            fake.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
            fake.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": f"{tmp}:{os.environ['PATH']}"}):
                r = shop.run("true", 5)
            self.assertEqual(r.returncode, 127)
            self.assertFalse(marker.exists(), "ssh started under unittest")


class WorkersTest(unittest.TestCase):
    def workers(self, text=None, registry=None):
        """shop.workers() with SCRUM_REGISTRY in a temp dir whose workers.txt holds `text` (None: no file)."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        reg = tmp / "sub" / "projects.json"
        reg.parent.mkdir()
        if isinstance(text, bytes):
            (reg.parent / "workers.txt").write_bytes(text)
        elif text is not None:
            (reg.parent / "workers.txt").write_text(text)
        with mock.patch.dict(os.environ, SCRUM_REGISTRY=str(reg)):
            return shop.workers()

    def test_missing_file_is_shopmac_default(self):
        got = self.workers()
        self.assertEqual(got, [("shopmac", 2, ("owa", "main"))])
        self.assertEqual((got[0].alias, got[0].max, got[0].accounts), ("shopmac", 2, ("owa", "main")))

    def test_lines_parsed_and_bad_lines_skipped(self):
        text = ("# alias max accounts\n"
                "shopmac 2 owa,main\n"
                "newmac\t1   main   # the second Mac\n"
                "\n   \n"
                "too few\n"
                "one two three four\n"
                "-oProxyCommand=x 1 main\n"
                "user@host 1 main\n"
                "zero 0 main\n"
                "neg -1 main\n"
                "half 2.5 main\n"
                "lead 02 main\n"
                "empty 1 main,,owa\n"
                "trail 1 main,\n"
                "twice 1 main,main\n"
                "work 1 main,work\n"
                "newmac 3 owa\n"
                "third 10 owa\n")
        self.assertEqual(self.workers(text), [("shopmac", 2, ("owa", "main")), ("newmac", 1, ("main",)),
                                              ("third", 10, ("owa",))])
        with self.subTest("default path: ~/.claude/trevskills-scrum/workers.txt"):
            home = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, home, True)
            (home / ".claude" / "trevskills-scrum").mkdir(parents=True)
            (home / ".claude" / "trevskills-scrum" / "workers.txt").write_text("homemac 3 main\n")
            with mock.patch.dict(os.environ, HOME=str(home)):
                os.environ.pop("SCRUM_REGISTRY")
                self.assertEqual(shop.workers(), [("homemac", 3, ("main",))])

    def test_no_valid_line_no_workers(self):
        for why, text in (("empty", ""), ("comments and bad lines", "# none yet\n\nzero 0 main\n-x 1 main\n"),
                          ("not UTF-8", b"newmac 1 main\n\xff\xfe\n")):
            with self.subTest(why):
                self.assertEqual(self.workers(text), [])
        with self.subTest("a folder, not a file"):
            tmp = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, tmp, True)
            (tmp / "workers.txt").mkdir()
            with mock.patch.dict(os.environ, SCRUM_REGISTRY=str(tmp / "projects.json")):
                self.assertEqual(shop.workers(), [])


class ProbeTest(ShopCase):
    def test_parses_live_sample(self):
        run = self.fake_run(0, LIVE)
        self.assertEqual(shop.probe(), UP)
        run.assert_called_once_with("sysctl -n vm.loadavg hw.ncpu; command -v node gh claude; true", 10,
                                    alias="shopmac")
        shop._cache.clear()
        run.return_value = subprocess.CompletedProcess([], 0, "{ 1.00 0.50 0.25 }\n3\n/usr/local/bin/node\n", "")
        self.assertEqual(shop.probe(), {"up": True, "load": 33.3, "tools": {"node": True, "gh": False, "claude": False}})

    def test_garbled_output_up_with_unknowns(self):
        run = self.fake_run(0)
        for out in ("", "load: high\nmany cores\n", "{ 1.50 1.20 1.00 }\n0\n","��\n"):
            with self.subTest(out=out):
                shop._cache.clear()
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
                shop._cache.clear()
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

    def test_cache_per_alias(self):
        hosts = []

        def ssh(argv, **kw):
            hosts.append(argv[1])
            return subprocess.CompletedProcess(argv, 255 if argv[1] == "newmac" else 0,
                                               LIVE.encode() if argv[1] == "shopmac" else b"", b"")
        self.sp.side_effect = ssh
        self.assertEqual(shop.probe(), UP)
        self.assertEqual(shop.probe(alias="newmac"), DOWN)
        self.assertEqual((shop.probe(), shop.probe(alias="newmac")), (UP, DOWN))
        self.assertEqual(hosts, ["shopmac", "newmac"], "each alias probed once, then cached")
        ready = {"ready": True}
        shop._ready.update(shopmac=(shop.time.monotonic(), ready), newmac=(shop.time.monotonic(), ready))
        shop._cache["newmac"] = (shop.time.monotonic(), UP)  # a stale up result setup must drop
        shopmac = shop._cache["shopmac"]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(shop.setup(alias="newmac"), {"shop": "failed"})
        self.assertEqual(out.getvalue(), "shop: down\n")
        self.assertEqual(hosts, ["shopmac", "newmac", "newmac"], "setup re-probed newmac only")
        self.assertIs(shop._cache["shopmac"], shopmac)
        self.assertEqual(shop._ready, {"shopmac": (shop._ready["shopmac"][0], ready)}, "newmac's ready cache dropped")
        self.assertEqual(shop.probe(), UP)
        self.assertEqual(hosts, ["shopmac", "newmac", "newmac"])

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

    def test_alias_argument(self):
        tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        Path(tmp, ".claude").mkdir()
        Path(tmp, ".claude", "CLAUDE.md").write_text("rules\n")
        env = mock.patch.dict(os.environ, {"HOME": tmp, "SCRUM_REGISTRY": os.path.join(tmp, "projects.json")})
        env.start()
        self.addCleanup(env.stop)
        hosts = []

        def ssh(argv, **kw):
            hosts.append(argv[1])
            return subprocess.CompletedProcess(argv, 255, b"", b"")  # down: every command prints its down line
        self.sp.side_effect = ssh
        workers = Path(tmp, "workers.txt")
        for why, text, argv, want, out, code in (
                ("setup to a named alias", None, ["setup", "newmac"], "newmac", "shop: down\n", 1),
                ("probe to a named alias", None, ["probe", "newmac"], "newmac", json.dumps(DOWN) + "\n", 0),
                ("md-sync to a named alias", None, ["md-sync", "newmac"], "newmac", "shop: down\n", 1),
                ("no file: shopmac", None, ["setup"], "shopmac", "shop: down\n", 1),
                ("first workers.txt line", "first 1 main\nsecond 1 owa\n", ["probe"], "first",
                 json.dumps(DOWN) + "\n", 0),
                ("no valid line: shopmac", "# none\n", ["md-sync"], "shopmac", "shop: down\n", 1)):
            with self.subTest(why):
                shop._cache.clear()
                hosts.clear()
                workers.unlink(missing_ok=True)
                if text is not None:
                    workers.write_text(text)
                self.assertEqual(self.main(argv), (code, out))
                self.assertEqual(set(hosts), {want})
        self.assertEqual(self.main(["probe", "x"])[0], 0)  # an alias not in workers.txt is still asked
        self.assertEqual(hosts[-1], "x")

    def test_md_sync_one_line(self):
        home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        Path(home, ".claude").mkdir()
        Path(home, ".claude", "CLAUDE.md").write_text("rules\n")
        env = mock.patch.dict(os.environ, {"HOME": home, "SCRUM_REGISTRY": os.path.join(home, "none.json")})
        env.start()
        self.addCleanup(env.stop)
        for fail, rc, want, code in ((None, 0, "md-sync: ok\n", 0), ("pull --ff-only", 1, "md-sync: failed\n", 1),
                                     ("tar -xf", 255, "md-sync: failed\n", 1), ("sysctl", 255, "shop: down\n", 1)):
            with self.subTest(fail=fail):
                shop._cache.clear()
                self.sp.side_effect = lambda argv, **kw: subprocess.CompletedProcess(
                    argv, rc if fail and fail in argv[-1] else 0, NOISE.encode(), NOISE.encode())
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    got = self.main(["md-sync"])
                self.assertEqual((got, err.getvalue()), ((code, want), ""))


TOKEN = "gho_FAKE962TOKEN"
ENV_LINE = b"SECRET_962=abc962xyz\n"
NOISE = "remote-noise-962"  # every faked remote stdout/stderr carries it; no setup output may
LOCAL = "local"  # an answer that runs the remote command in a local sh under self.home, as the shop would
HAVE_ALL = "{ 1.00 0.50 0.25 }\n4\n/u/.local/bin/node\n/u/.local/bin/gh\n/u/.local/bin/claude\n"
DONE = (("sysctl", 0, HAVE_ALL), ("gh auth status", 0, ""),
        ("credential.https://github.com.helper", 0, "\n!/u/.local/bin/gh auth git-credential\n"),
        ('mkdir -p "$HOME/.claude-owa"', 0, ""), ("python3 -", 0, "same\n"), ("claude -p", 0, "ok\n"))
ALL_OK = ["node: ok", "gh: ok", "gh login: ok", "gh git: ok", "permissions: ok", "owa links: ok", "account main: ok",
          "account owa: ok", "codex: ok", "codex login: ok", "ruff: ok", "chrome: ok", "jev key: ok"]
CODEX_HINT = " (save a Codex access token to ~/.codex/access-token or run codex login on the shop)"
GH_LOGIN = ("gh auth login --hostname github.com --git-protocol https --with-token --insecure-storage"
            " && chmod 600 ~/.config/gh/hosts.yml")
CHECK = "claude -p 'Reply with the single word ok' --model haiku --max-turns 1"
HINT = " (run claude setup-token in the shop GUI)"
JEV = "tsk_FAKE1075KEY"  # this Mac's Keychain TypeSafe key in every faked read
KEYCHAIN = ["/usr/bin/security", "find-generic-password", "-s", "TypeSafe", "-a", "typesafe", "-w"]
JEV_CHECK = '[ -s "$HOME/.config/typesafe/key" ]'
JEV_WRITE = ("umask 077 && mkdir -p ~/.config/typesafe && cat > ~/.config/typesafe/key.tmp"
             " && mv -f ~/.config/typesafe/key.tmp ~/.config/typesafe/key")


class SetupCase(ShopCase):
    def setUp(self):
        super().setUp()
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.alias = "shopmac"  # every faked ssh call must go to this alias

    def worker_file(self, text):
        """Point SCRUM_REGISTRY at self.home and write its workers.txt."""
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=os.path.join(self.home, "projects.json"))
        env.start()
        self.addCleanup(env.stop)
        Path(self.home, "workers.txt").write_text(text)

    def shop(self, *answers, token=(0, TOKEN + "\n"), keychain=(0, JEV + "\n")):
        """Fake ssh, this Mac's `gh auth token` and its Keychain TypeSafe read under subprocess.run, so run() itself is
        exercised. Each remote command gets the first answer (key, rc, stdout) whose key it contains, else exit 0; rc
        LOCAL runs it here under self.home, an exception rc is raised. self.calls holds every (remote command, timeout,
        input)."""
        self.calls, self.argv = [], []

        def fake(argv, **kw):
            self.argv.append(list(argv))
            if argv[0] != "ssh":  # a local read: gh's token or the Keychain key
                want, answer = (["gh", "auth", "token"], token) if argv[0] == "gh" else (KEYCHAIN, keychain)
                self.assertEqual((argv, kw), (want, {"capture_output": True, "text": True, "timeout": 60}))
                if isinstance(answer, BaseException):
                    raise answer
                return subprocess.CompletedProcess(argv, answer[0], answer[1], "")
            self.assertEqual(argv[:6], ["ssh", self.alias, *ARGV[2:]])
            self.assertTrue(argv[6].startswith(shop.PATH_PREFIX), argv[6])
            cmd = argv[6][len(shop.PATH_PREFIX):]
            self.calls.append((cmd, kw["timeout"], kw.get("input")))
            for key, rc, out in answers:
                if key in cmd:
                    if rc == LOCAL:
                        r = REAL_RUN(["/bin/sh", "-c", argv[6]], input=kw.get("input"), capture_output=True,
                                     env={"HOME": self.home, "PATH": "/usr/bin:/bin"})
                        return subprocess.CompletedProcess(argv, r.returncode, r.stdout, r.stderr)
                    if isinstance(rc, BaseException):
                        raise rc
                    return subprocess.CompletedProcess(argv, rc, (out + NOISE).encode(), (out + NOISE).encode())
            return subprocess.CompletedProcess(argv, 0, NOISE.encode(), NOISE.encode())
        self.sp.side_effect = fake

    def setup_out(self, cli=False):
        """(setup()'s result, or main(["setup"])'s exit code; its stdout lines). Nothing reaches stderr."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = shop.main(["setup"]) if cli else shop.setup()
        self.assertEqual(err.getvalue(), "")
        self.assertNotIn(NOISE, out.getvalue())
        return got, out.getvalue().splitlines()

    def cmds(self, key):
        return [c for c in self.calls if key in c[0]]


class SetupTest(SetupCase):
    def test_down_runs_no_step(self):
        shop._cache["shopmac"] = (shop.time.monotonic(),
                                  {"up": True, "load": 1.0, "tools": {t: True for t in shop.TOOLS}})
        self.shop(("sysctl", 255, ""))
        self.assertEqual(self.setup_out(), ({"shop": "failed"}, ["shop: down"]))
        self.assertEqual([c[0] for c in self.calls], [shop.PROBE_CMD])  # the stale up cache was dropped
        self.assertEqual(self.setup_out(cli=True), (1, ["shop: down"]))
        self.assertEqual(len(self.calls), 2)

    def test_output_lines_and_exit_code(self):
        answers = (("sysctl", 0, "{ 1.00 0.50 0.25 }\n4\n/u/.local/bin/gh\n/u/.local/bin/claude\n"),
                   ("nodejs.org", 0, ""), (shop.GIT_HELPER, 1, ""), ("setup-git", 1, ""),
                   ('mkdir -p "$HOME/.claude-owa"', 0, "agents\nskills\n"), ("python3 -", 0, "changed\n"),
                   (".claude-owa/oauth-token", 3, ""), ("claude -p", 0, "Ok.\n"), ("gh auth status", 0, ""),
                   ("command -v codex", 1, ""), ("codex login status", 1, ""), ("--with-access-token", 3, ""))
        self.shop(*answers)
        got, lines = self.setup_out()
        self.assertEqual(lines, ["node: ok (changed)", "gh: ok", "gh login: ok", "gh git: failed (exit 1)",
                                 "permissions: ok (changed)", "owa links: ok (changed)", "account main: ok",
                                 "account owa: not ready (run claude setup-token in the shop GUI)", "codex: ok (changed)",
                                 "codex login: not ready" + CODEX_HINT, "ruff: ok", "chrome: ok", "jev key: ok"])
        self.assertEqual(got, {"node": "changed", "gh": "ok", "gh login": "ok", "gh git": "failed",
                               "permissions": "changed", "owa links": "changed", "account main": "ok",
                               "account owa": "not ready", "codex": "changed", "codex login": "not ready",
                               "ruff": "ok", "chrome": "ok", "jev key": "ok"})
        self.assertEqual(list(got), ["node", "gh", "gh login", "gh git", "permissions", "owa links", "account main",
                                     "account owa", "codex", "codex login", "ruff", "chrome", "jev key"])
        self.assertEqual([(c[0].split()[0], c[1]) for c in self.calls[1:]],
                         [("d=$(mktemp", 600), ("gh", 60), ("git", 60), ("gh", 60), ("python3", 60), ("mkdir", 60),
                          ("ln", 60), ("[", 120), ("[", 120), ("command", 60), ("npm", 600), ("codex", 60),
                          ('f="$HOME/.codex/access-token";', 60), ("command", 60), ("[", 60), ("[", 60)])
        self.assertEqual(self.calls[-1], (JEV_CHECK, 60, None))
        self.assertEqual(self.setup_out(cli=True)[0], 1)
        self.shop(("setup-git", 0, ""), *answers)
        self.assertEqual(self.setup_out(cli=True), (0, [
            "node: ok (changed)", "gh: ok", "gh login: ok", "gh git: ok (changed)", "permissions: ok (changed)",
            "owa links: ok (changed)", "account main: ok",
            "account owa: not ready (run claude setup-token in the shop GUI)", "codex: ok (changed)",
            "codex login: not ready" + CODEX_HINT, "ruff: ok", "chrome: ok", "jev key: ok"]))

    def test_worker_accounts_only(self):
        self.worker_file("shopmac 2 owa,main\nnewmac 1 owa\n")
        base = ["node: ok", "gh: ok", "gh login: ok", "gh git: ok", "permissions: ok", "owa links: ok"]
        for alias, accounts in (("newmac", ["owa"]), ("shopmac", ["main", "owa"]), ("other", ["main", "owa"])):
            with self.subTest(alias=alias):
                self.alias = alias
                self.shop(*DONE)
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    got = shop.setup(alias=alias)
                self.assertEqual(out.getvalue().splitlines(),
                                 base + [f"account {n}: ok" for n in accounts]
                                 + ["codex: ok", "codex login: ok", "ruff: ok", "chrome: ok", "jev key: ok"])
                self.assertEqual([k for k in got if k.startswith("account ")], [f"account {n}" for n in accounts])
                self.assertEqual(len(self.cmds("claude -p")), len(accounts))
                self.assertEqual({a[1] for a in self.argv if a[0] == "ssh"}, {alias})

    def test_second_run_unchanged(self):
        self.shop(*DONE)
        got, lines = self.setup_out()
        self.assertEqual(lines, ALL_OK)
        self.assertEqual(set(got.values()), {"ok"})
        for key in ("curl", "gh auth login", "ln -s", "setup-git", 'mkdir -p "$HOME/.local', "npm install",
                    "--with-access-token"):
            self.assertEqual(self.cmds(key), [], key)
        self.assertEqual(len(self.cmds("python3 -")), 1)  # the merge script writes only on a change (PermissionsMergeTest)
        self.assertNotIn(["gh", "auth", "token"], self.argv)
        self.assertEqual(self.setup_out(cli=True), (0, ALL_OK))

    def test_node_install_pinned(self):
        self.assertEqual((shop.NODE_VERSION, shop.NODE_SHA256),
                         ("24.22.3", "977614af0504c81045e7fd85596dbca0e5f951b96681516dadafedcca8c447f7"))
        self.shop(("sysctl", 0, "{ 1 1 1 }\n4\n/u/gh\n/u/claude\n"), *DONE)
        self.assertEqual(self.setup_out()[1][0], "node: ok (changed)")
        [(cmd, timeout, given)] = self.cmds("nodejs.org")
        self.assertEqual((timeout, given), (600, None))
        self.assertEqual(cmd, 'd=$(mktemp -d) || exit 1; (cd "$d" && curl -fsSL -o node.tgz '
                         'https://nodejs.org/dist/v24.22.3/node-v24.22.3-darwin-x64.tar.gz && echo '
                         "'977614af0504c81045e7fd85596dbca0e5f951b96681516dadafedcca8c447f7  node.tgz' | shasum -a 256"
                         ' -c - && mkdir -p "$HOME/.local/share" "$HOME/.local/bin" && tar -xzf node.tgz -C '
                         '"$HOME/.local/share" && ln -sf "$HOME/.local/share/node-v24.22.3-darwin-x64/bin/node" '
                         '"$HOME/.local/bin/node" && ln -sf "$HOME/.local/share/node-v24.22.3-darwin-x64/bin/npm" '
                         '"$HOME/.local/bin/npm" && ln -sf "$HOME/.local/share/node-v24.22.3-darwin-x64/bin/npx" '
                         '"$HOME/.local/bin/npx"); rc=$?; rm -rf "$d"; exit $rc')
        self.shop(("nodejs.org", 1, ""), ("sysctl", 0, "{ 1 1 1 }\n4\n/u/gh\n/u/claude\n"), *DONE)
        self.assertEqual(self.setup_out()[1][0], "node: failed (exit 1)")

    def test_gh_install_pinned(self):
        self.assertEqual((shop.GH_VERSION, shop.GH_SHA256),
                         ("2.103.3", "a2f86418f4350ae6e9ec60d5000bdf7665728436946a97fc27fe50e6ae752682"))
        self.shop(("sysctl", 0, "{ 1 1 1 }\n4\n/u/node\n/u/claude\n"), *DONE)
        self.assertEqual(self.setup_out()[1][:2], ["node: ok", "gh: ok (changed)"])
        [(cmd, timeout, given)] = self.cmds("github.com/cli")
        self.assertEqual((timeout, given), (600, None))
        self.assertEqual(cmd, 'd=$(mktemp -d) || exit 1; (cd "$d" && curl -fsSL -o gh.zip '
                         'https://github.com/cli/cli/releases/download/v2.103.3/gh_2.103.3_macOS_amd64.zip && echo '
                         "'a2f86418f4350ae6e9ec60d5000bdf7665728436946a97fc27fe50e6ae752682  gh.zip' | shasum -a 256"
                         ' -c - && unzip -q gh.zip && mkdir -p "$HOME/.local/bin" && cp gh_2.103.3_macOS_amd64/bin/gh '
                         '"$HOME/.local/bin/gh"); rc=$?; rm -rf "$d"; exit $rc')

    def test_chrome_install_pinned(self):
        self.assertEqual((shop.CFT_VERSION, shop.CFT_SHA256),
                         ("150.0.7871.125", "b580eef196e0607f5942cfa621c6976b8fd0de96ba30fa1a57341c9b9cc9a9eb"))
        self.assertNotIn("chrome", shop.OPTIONAL_STEPS)  # a failed chrome step holds the dispatch
        self.shop(("[ -x", 1, ""), *DONE)
        got, lines = self.setup_out()
        self.assertEqual((lines[-2], got["chrome"]), ("chrome: ok (changed)", "changed"))
        self.assertEqual(self.cmds("[ -x"), [('[ -x "$HOME/.local/share/chrome-for-testing-150.0.7871.125/chrome-mac-x64/'
                                              'Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" ]',
                                              60, None)])
        [(cmd, timeout, given)] = self.cmds("storage.googleapis.com")
        self.assertEqual((timeout, given), (600, None))
        self.assertEqual(cmd, 'd=$(mktemp -d) || exit 1; (cd "$d" && curl -fsSL -o chrome.zip '
                         'https://storage.googleapis.com/chrome-for-testing-public/150.0.7871.125/mac-x64/'
                         "chrome-mac-x64.zip && echo 'b580eef196e0607f5942cfa621c6976b8fd0de96ba30fa1a57341c9b9cc9a9eb"
                         "  chrome.zip' | shasum -a 256 -c - && unzip -q chrome.zip && rm -rf "
                         '"$HOME/.local/share/chrome-for-testing-150.0.7871.125" && mkdir -p '
                         '"$HOME/.local/share/chrome-for-testing-150.0.7871.125" && mv chrome-mac-x64 '
                         '"$HOME/.local/share/chrome-for-testing-150.0.7871.125/"); rc=$?; rm -rf "$d"; exit $rc')
        self.shop(("[ -x", 1, ""), ("storage.googleapis.com", 7, ""), *DONE)
        rc, lines = self.setup_out(cli=True)
        self.assertEqual((rc, lines[-2]), (1, "chrome: failed (exit 7)"))

    @unittest.skipUnless(shutil.which("shasum") and shutil.which("unzip"), "needs shasum and unzip")
    def test_checksum_checked_before_install(self):
        """Run each install command in a local sh with a fake curl: a wrong checksum installs nothing, the right one
        installs, and the temp dir is gone either way."""
        work = Path(self.home)
        (work / "bin").mkdir()
        curl = work / "bin" / "curl"
        curl.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
                        'cp "$FAKE_DOWNLOAD" "$out"\n')
        curl.chmod(0o755)
        script = b"#!/bin/sh\necho fake-962\n"
        tgz, gz, cz = work / "node.tgz", work / "gh.zip", work / "chrome.zip"
        app = "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        with tarfile.open(tgz, "w:gz") as tar:
            for b in ("node", "npm", "npx"):
                info = tarfile.TarInfo(f"node-v24.22.3-darwin-x64/bin/{b}")
                info.size, info.mode = len(script), 0o755
                tar.addfile(info, io.BytesIO(script))
        with zipfile.ZipFile(gz, "w") as z:
            info = zipfile.ZipInfo("gh_2.103.3_macOS_amd64/bin/gh")
            info.external_attr = 0o100755 << 16
            z.writestr(info, script)
        with zipfile.ZipFile(cz, "w") as z:
            info = zipfile.ZipInfo(app)
            info.external_attr = 0o100755 << 16
            z.writestr(info, script)
        for name, cmd, fixture, sha in (("node", shop.NODE_INSTALL, tgz, shop.NODE_SHA256),
                                        ("gh", shop.GH_INSTALL, gz, shop.GH_SHA256),
                                        ("chrome", shop.CFT_INSTALL, cz, shop.CFT_SHA256)):
            with self.subTest(name=name):
                home, tmp = work / f"home-{name}", work / f"tmp-{name}"
                home.mkdir()
                tmp.mkdir()
                env = {"HOME": str(home), "PATH": f"{work / 'bin'}:/usr/bin:/bin", "TMPDIR": str(tmp),
                       "FAKE_DOWNLOAD": str(fixture)}
                bad = REAL_RUN(["/bin/sh", "-c", shop.PATH_PREFIX + cmd], env=env, capture_output=True)
                self.assertNotEqual(bad.returncode, 0)
                self.assertEqual((os.listdir(home), os.listdir(tmp)), ([], []))
                good = cmd.replace(sha, hashlib.sha256(fixture.read_bytes()).hexdigest())
                ok = REAL_RUN(["/bin/sh", "-c", shop.PATH_PREFIX + good], env=env, capture_output=True)
                self.assertEqual(ok.returncode, 0, ok.stderr)
                self.assertEqual(os.listdir(tmp), [])
                if name == "chrome":
                    share = home / ".local" / "share" / "chrome-for-testing-150.0.7871.125"
                    self.assertEqual(REAL_RUN([str(share / app)], capture_output=True).stdout, b"fake-962\n")
                    self.assertEqual(REAL_RUN(["/bin/sh", "-c", f'[ -x "{shop.CFT_BIN}" ]'], env=env).returncode, 0)
                    again = REAL_RUN(["/bin/sh", "-c", shop.PATH_PREFIX + good], env=env, capture_output=True)
                    self.assertEqual((again.returncode, os.listdir(share), os.listdir(tmp)), (0, ["chrome-mac-x64"], []))
                    continue
                bins = ["node", "npm", "npx"] if name == "node" else ["gh"]
                self.assertEqual(sorted(os.listdir(home / ".local" / "bin")), bins)
                for b in bins:
                    self.assertEqual(REAL_RUN([str(home / ".local" / "bin" / b)], capture_output=True).stdout,
                                     b"fake-962\n")
                if name == "node":
                    self.assertEqual(os.readlink(home / ".local" / "bin" / "npx"),
                                     f"{home}/.local/share/node-v24.22.3-darwin-x64/bin/npx")

    def test_present_tools_not_reinstalled(self):
        self.shop(*DONE)
        self.assertEqual(self.setup_out()[1][:2], ["node: ok", "gh: ok"])
        self.assertEqual([c[0] for c in self.calls if "curl" in c[0] or c[1] == 600], [])

    def test_gh_login_token_on_stdin_only(self):
        self.shop(("gh auth status", 1, ""), *DONE)
        self.assertEqual(self.setup_out()[1][2], "gh login: ok (changed)")
        self.assertIn(["gh", "auth", "token"], self.argv)
        self.assertEqual(self.cmds("gh auth login"), [(GH_LOGIN, 60, b"gho_FAKE962TOKEN")])
        self.assertFalse([a for a in self.argv if TOKEN in " ".join(a)])
        self.shop(("gh auth login", 1, ""), ("gh auth status", 1, ""), *DONE)
        self.assertEqual(self.setup_out()[1][2], "gh login: failed (exit 1)")

    def test_gh_login_skipped_when_logged_in(self):
        self.shop(*DONE)
        self.assertEqual(self.setup_out()[1][2], "gh login: ok")
        self.assertEqual(self.cmds("gh auth status"), [("gh auth status", 60, None)])
        self.assertEqual(self.cmds("gh auth login"), [])
        self.assertNotIn(["gh", "auth", "token"], self.argv)

    def test_local_token_failure_no_remote_call(self):
        for token, line in (((1, ""), "gh login: failed (exit 1)"), ((0, " \n"), "gh login: failed (exit 1)"),
                            (FileNotFoundError(2, "No such file or directory", "gh"), "gh login: failed (exit 127)"),
                            (subprocess.TimeoutExpired(["gh"], 60), "gh login: failed (exit 124)")):
            with self.subTest(token=token):
                self.shop(("gh auth status", 1, ""), *DONE, token=token)
                self.assertEqual(self.setup_out()[1][2], line)
                self.assertIn(["gh", "auth", "token"], self.argv)
                self.assertEqual(self.cmds("gh auth login"), [])

    def test_ruff_installed_into_local_when_missing(self):
        self.shop(("command -v ruff", 1, ""), *DONE)
        got, lines = self.setup_out()
        self.assertEqual((lines[-3], got["ruff"]), ("ruff: ok (changed)", "changed"))
        [(cmd, timeout, _)] = self.cmds("pip install")
        self.assertEqual((cmd, timeout), (shop.RUFF_INSTALL, 600))
        self.assertIn('PYTHONUSERBASE="$HOME/.local"', cmd)
        self.assertIn("/usr/bin/python3 -m pip install --user", cmd)  # never the shop's uv-managed ~/.local/bin/python3
        self.shop(("command -v ruff", 1, ""), ("pip install", 1, "error: externally-managed-environment"), *DONE)
        got, lines = self.setup_out()
        self.assertEqual((lines[-3], got["ruff"]), ("ruff: failed (exit 1)", "failed"))
        self.assertEqual(shop.OPTIONAL_STEPS, {"ruff", "codex", "codex login"})

    def test_codex_steps_optional(self):
        self.assertEqual(shop.OPTIONAL_STEPS, {"ruff", "codex", "codex login"})  # never holds a dispatch
        self.shop(("codex login status", 1, ""), ("--with-access-token", 3, ""), *DONE)
        self.assertEqual(self.setup_out(cli=True), (0, ALL_OK[:9] + ["codex login: not ready" + CODEX_HINT]
                                                    + ALL_OK[10:]))
        self.shop(("command -v codex", 1, ""), ("npm install", 1, ""), *DONE)
        self.assertEqual(self.setup_out(cli=True), (1, ALL_OK[:8] + ["codex: failed (exit 1)"] + ALL_OK[9:]))

    def test_codex_installed_into_local_when_missing(self):
        self.assertEqual(shop.CODEX_VERSION, "0.166.0")
        self.shop(*DONE)  # `command -v codex` exits 0: nothing else runs
        got, lines = self.setup_out()
        self.assertEqual((lines[8], got["codex"]), ("codex: ok", "ok"))
        self.assertEqual(self.cmds("command -v codex"), [("command -v codex", 60, None)])
        self.assertEqual(self.cmds("npm install"), [])
        self.shop(("command -v codex", 1, ""), *DONE)
        got, lines = self.setup_out()
        self.assertEqual((lines[8], got["codex"]), ("codex: ok (changed)", "changed"))
        self.assertEqual(self.cmds("npm install"),
                         [('npm install -g --prefix "$HOME/.local" @openai/codex@0.166.0', 600, None)])
        self.shop(("command -v codex", 1, ""), ("npm install", 1, ""), *DONE)
        rc, lines = self.setup_out(cli=True)
        self.assertEqual((rc, lines[8]), (1, "codex: failed (exit 1)"))
        self.assertEqual(len(self.cmds("npm install")), 1)

    def test_codex_login_states(self):
        login = 'f="$HOME/.codex/access-token"; [ -r "$f" ] || exit 3; codex login --with-access-token < "$f"'
        hint = " (save a Codex access token to ~/.codex/access-token or run codex login on the shop)"
        for name, status, write, result, line in (
                ("logged in", 0, None, "ok", "codex login: ok"),
                ("token login", 1, 0, "changed", "codex login: ok (changed)"),
                ("no token file", 1, 3, "not ready", "codex login: not ready" + hint),
                ("login fails", 1, 1, "failed", "codex login: failed (exit 1)"),
                ("ssh fails", 1, 255, "failed", "codex login: failed (exit 255)"),
                ("timeout", 1, subprocess.TimeoutExpired(["ssh"], 60), "failed", "codex login: failed (exit 124)")):
            with self.subTest(name=name):
                self.shop(("codex login status", status, ""), ("--with-access-token", write, ""), *DONE)
                got, lines = self.setup_out()
                self.assertEqual((lines[9], got["codex login"]), (line, result))
                self.assertEqual(self.cmds("codex login"), [("codex login status", 60, None)]
                                 + ([] if write is None else [(login, 60, None)]))  # no input: no token from this Mac
                self.assertEqual([a for a in self.argv if a[0] != "ssh"], [])  # no local read of any kind

    def test_codex_login_reads_shop_token_file(self):
        """The login call runs in a local sh under a temp home with a fake codex, as the shop would."""
        h = Path(self.home)
        (h / ".local" / "bin").mkdir(parents=True)
        codex = h / ".local" / "bin" / "codex"
        codex.write_text('#!/bin/sh\n[ "$2" = status ] && exit 1\necho "$*" > "$HOME/args"\ncat > "$HOME/stdin"\n')
        codex.chmod(0o755)
        self.shop(("codex login", LOCAL, ""), *DONE)
        self.assertEqual(self.setup_out()[1][9], "codex login: not ready (save a Codex access token to "
                                                 "~/.codex/access-token or run codex login on the shop)")
        self.assertEqual(sorted(os.listdir(h)), [".local"])  # exit 3 before codex login ran
        (h / ".codex").mkdir()
        (h / ".codex" / "access-token").write_text("cdx-tok-1245\n")
        self.assertEqual(self.setup_out()[1][9], "codex login: ok (changed)")
        self.assertEqual(((h / "args").read_text(), (h / "stdin").read_text()),
                         ("login --with-access-token\n", "cdx-tok-1245\n"))
        self.assertFalse([a for a in self.argv if "cdx-tok" in " ".join(a)])

    def test_jev_key_skipped_when_file_exists(self):
        self.shop((JEV_CHECK, 0, ""), *DONE)
        got, lines = self.setup_out()
        self.assertEqual((lines[-1], got["jev key"]), ("jev key: ok", "ok"))
        self.assertEqual(self.cmds(".config/typesafe"), [(JEV_CHECK, 60, None)])  # no write
        self.assertNotIn(KEYCHAIN, self.argv)  # no Keychain read here

    def test_jev_key_sent_on_stdin(self):
        self.shop((JEV_CHECK, 1, ""), ("cat > ~/.config/typesafe", 0, f"wrote {JEV}\n"), *DONE)
        got, lines = self.setup_out()
        self.assertEqual((lines[-1], got["jev key"]), ("jev key: ok (changed)", "changed"))
        self.assertEqual(self.argv.count(KEYCHAIN), 1)
        self.assertEqual(self.cmds(".config/typesafe"), [(JEV_CHECK, 60, None), (JEV_WRITE, 60, b"tsk_FAKE1075KEY")])
        self.assertFalse([a for a in self.argv if JEV in " ".join(a)], "key in an argv or remote command")
        self.assertNotIn(JEV, "\n".join(lines))

    def test_jev_key_local_read_fails(self):
        for keychain, line in (((44, ""), "jev key: failed (exit 44)"), ((0, " \n\t"), "jev key: failed (exit 1)"),
                               ((36, JEV + "\n"), "jev key: failed (exit 36)"),
                               (FileNotFoundError(2, "No such file or directory", "/usr/bin/security"),
                                "jev key: failed (exit 127)"),
                               (subprocess.TimeoutExpired(KEYCHAIN, 60), "jev key: failed (exit 124)")):
            with self.subTest(keychain=keychain):
                self.shop((JEV_CHECK, 1, ""), *DONE, keychain=keychain)
                rc, lines = self.setup_out(cli=True)
                self.assertEqual((rc, lines), (1, ALL_OK[:-1] + [line]))
                self.assertIn(KEYCHAIN, self.argv)
                self.assertEqual(self.cmds(".config/typesafe"), [(JEV_CHECK, 60, None)])  # no remote write
        for write in (1, 255, subprocess.TimeoutExpired(["ssh"], 60, output=JEV.encode())):
            with self.subTest(write=write):
                self.shop((JEV_CHECK, 1, ""), ("cat > ~/.config/typesafe", write, f"bad key {JEV}\n"), *DONE)
                rc, lines = self.setup_out(cli=True)
                code = 124 if isinstance(write, BaseException) else write
                self.assertEqual((rc, lines[-1]), (1, f"jev key: failed (exit {code})"))
                self.assertNotIn(JEV, "\n".join(lines))
                self.assertEqual(len(self.cmds("cat > ~/.config/typesafe")), 1)

    def test_jev_key_file_mode_600_second_run_unchanged(self):
        """The check and the write run in a local sh under a temp home, as the shop would."""
        key = Path(self.home) / ".config" / "typesafe" / "key"
        self.shop((JEV_CHECK, LOCAL, ""), ("cat > ~/.config/typesafe", LOCAL, ""), *DONE)
        self.assertEqual(self.setup_out()[1][-1], "jev key: ok (changed)")
        self.assertEqual((key.read_text(), os.listdir(key.parent)), (JEV, ["key"]))
        self.assertEqual((stat.S_IMODE(key.stat().st_mode), stat.S_IMODE(key.parent.stat().st_mode)), (0o600, 0o700))
        got, lines = self.setup_out()  # the file is there now
        self.assertEqual((lines, got["jev key"]), (ALL_OK, "ok"))
        self.assertEqual(self.argv.count(KEYCHAIN), 1)
        self.assertEqual(len(self.cmds("cat > ~/.config/typesafe")), 1)
        key.write_text("")  # an empty file is rewritten, and a loose mode does not survive
        key.chmod(0o644)
        self.assertEqual(self.setup_out()[1][-1], "jev key: ok (changed)")
        self.assertEqual((key.read_text(), stat.S_IMODE(key.stat().st_mode)), (JEV, 0o600))

    def test_setup_git_only_when_missing(self):
        for helper, line, runs in (("\n!/u/.local/bin/gh auth git-credential\n", "gh git: ok", 0),
                                   ("osxkeychain\n", "gh git: ok (changed)", 1), (None, "gh git: ok (changed)", 1)):
            with self.subTest(helper=helper):
                self.shop((shop.GIT_HELPER, 0 if helper else 1, helper or ""), *DONE)
                self.assertEqual(self.setup_out()[1][3], line)
                self.assertEqual(self.cmds("git config"),
                                 [("git config --global --get-all credential.https://github.com.helper", 60, None)])
                self.assertEqual(self.cmds("setup-git"), [("gh auth setup-git", 60, None)] * runs)

    def test_owa_links_only_missing(self):
        """The check and the links run in a local sh against a temp home laid out like the shop's."""
        self.assertEqual(shop.OWA_LINKS, ("agents", "CLAUDE.md", "commands", "history.jsonl", "hooks", "plugins",
                                          "projects", "rules", "scripts", "settings.json", "settings.local.json",
                                          "skills"))
        h = Path(self.home)
        for d in ("agents", "commands", "skills", "rules"):
            (h / ".claude" / d).mkdir(parents=True)
        (h / ".claude" / "CLAUDE.md").write_text("main\n")
        (h / ".claude" / "settings.json").write_text("{}\n")
        owa = h / ".claude-owa"
        owa.mkdir()
        (owa / "agents").symlink_to(h / ".claude" / "agents")  # already linked
        (owa / "skills").symlink_to(h / "gone")  # a broken link is left alone
        (owa / "commands").write_text("a file\n")  # so is a file
        (owa / ".claude.json").write_text('{"oauthAccount": 1}\n')
        (owa / ".credentials.json").write_text("{}\n")
        self.shop(('mkdir -p "$HOME/.claude-owa"', LOCAL, ""), ("ln -s", LOCAL, ""), *DONE)
        self.assertEqual(self.setup_out()[1][5], "owa links: ok (changed)")
        self.assertEqual(self.cmds("ln -s")[0][0], 'ln -s "$HOME/.claude/CLAUDE.md" "$HOME/.claude-owa/CLAUDE.md" && '
                         'ln -s "$HOME/.claude/rules" "$HOME/.claude-owa/rules" && ln -s "$HOME/.claude/settings.json" '
                         '"$HOME/.claude-owa/settings.json"')
        links = {p.name: os.readlink(p) for p in owa.iterdir() if p.is_symlink()}
        self.assertEqual(links, {"agents": f"{h}/.claude/agents", "skills": f"{h}/gone",
                                 "CLAUDE.md": f"{h}/.claude/CLAUDE.md", "rules": f"{h}/.claude/rules",
                                 "settings.json": f"{h}/.claude/settings.json"})
        self.assertEqual(((owa / "commands").read_text(), (owa / ".claude.json").read_text(),
                          (owa / ".credentials.json").read_text()), ("a file\n", '{"oauthAccount": 1}\n', "{}\n"))
        self.assertEqual(self.setup_out()[1][5], "owa links: ok")
        self.assertEqual(len(self.cmds("ln -s")), 1)  # the second run linked nothing
        shutil.rmtree(owa)
        self.shop(('mkdir -p "$HOME/.claude-owa"', LOCAL, ""), ("ln -s", LOCAL, ""), *DONE)
        self.assertEqual(self.setup_out()[1][5], "owa links: ok (changed)")  # mkdir -p made it first
        self.assertEqual(sorted(p.name for p in owa.iterdir()),
                         ["CLAUDE.md", "agents", "commands", "rules", "settings.json", "skills"])

    def test_account_check_loads_token_file_remotely(self):
        self.assertEqual(shop.account_env("main"), '[ -r "$HOME/.claude/oauth-token" ] && export '
                         'CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude/oauth-token")"; ')
        self.assertEqual(shop.account_env("owa"), 'export CLAUDE_CONFIG_DIR="$HOME/.claude-owa"; [ -r '
                         '"$HOME/.claude-owa/oauth-token" ] && export CLAUDE_CODE_OAUTH_TOKEN="$(cat '
                         '"$HOME/.claude-owa/oauth-token")"; ')
        h = Path(self.home)
        (h / ".local" / "bin").mkdir(parents=True)
        claude = h / ".local" / "bin" / "claude"
        claude.write_text('#!/bin/sh\nprintf "%s|%s|%s\\n" "${CLAUDE_CONFIG_DIR-unset}" "$CLAUDE_CODE_OAUTH_TOKEN" '
                          '"$*" >> "$HOME/calls"\necho OK\n')
        claude.chmod(0o755)
        (h / ".claude-owa").mkdir()
        (h / ".claude-owa" / "oauth-token").write_text("tok-owa-962\n")
        self.shop(("claude -p", LOCAL, ""), *DONE)
        self.assertEqual(self.setup_out()[1][6:8], ["account main: not ready (run claude setup-token in the shop GUI)",
                                                   "account owa: ok"])
        self.assertEqual((h / "calls").read_text(),
                         f"{h}/.claude-owa|tok-owa-962|-p Reply with the single word ok --model haiku --max-turns 1\n")
        (h / ".claude").mkdir()
        (h / ".claude" / "oauth-token").write_text("tok-main-962\n")
        self.assertEqual(self.setup_out()[1][6:8], ["account main: ok", "account owa: ok"])
        self.assertEqual((h / "calls").read_text().splitlines()[1:], [
            "unset|tok-main-962|-p Reply with the single word ok --model haiku --max-turns 1",
            f"{h}/.claude-owa|tok-owa-962|-p Reply with the single word ok --model haiku --max-turns 1"])
        self.assertEqual(self.cmds("claude -p")[-2:], [
            ('[ -r "$HOME/.claude/oauth-token" ] || exit 3; [ -r "$HOME/.claude/oauth-token" ] && export '
             'CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude/oauth-token")"; ' + CHECK, 120, None),
            ('[ -r "$HOME/.claude-owa/oauth-token" ] || exit 3; export CLAUDE_CONFIG_DIR="$HOME/.claude-owa"; [ -r '
             '"$HOME/.claude-owa/oauth-token" ] && export CLAUDE_CODE_OAUTH_TOKEN="$(cat '
             '"$HOME/.claude-owa/oauth-token")"; ' + CHECK, 120, None)])
        self.assertFalse([a for a in self.argv if "tok-" in " ".join(a)])

    def test_account_not_ready_is_not_failure(self):
        for main, owa, owa_line in (((1, ""), (3, ""), "account owa: not ready" + HINT),
                                    ((0, "Not logged in · Please run /login\n"), (124, ""), "account owa: not ready")):
            with self.subTest(main=main, owa=owa):
                self.shop((".claude-owa/oauth-token", *owa), ("claude -p", *main), *DONE)
                rc, lines = self.setup_out(cli=True)
                self.assertEqual(rc, 0)
                self.assertEqual(lines[6:8], ["account main: not ready", owa_line])


class PermissionsMergeTest(unittest.TestCase):
    """Runs _permissions_script() here with this Python against a temp HOME, as the shop's `python3 -` would."""

    def setUp(self):
        self.home = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.home, True)
        self.file = self.home / ".claude" / "settings.json"

    def merge(self):
        return REAL_RUN([sys.executable, "-I", "-"], input=shop._permissions_script(), capture_output=True, text=True,
                        env={"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")})

    def test_merge_union_and_idempotent(self):
        h = str(self.home)
        r = self.merge()  # no settings.json at all: {}
        self.assertEqual((r.returncode, r.stdout), (0, "changed\n"), r.stderr)
        self.assertEqual(json.loads(self.file.read_text()), {"hooks": {"PostToolUse": [{
            "matcher": "Edit|Write|MultiEdit", "hooks": [{"type": "command", "timeout": 60, "command":
                "if [ -f skills/trevskills-scrum/edit-check.py ]; then python3 skills/trevskills-scrum/edit-check.py; fi"}]}]},
            "permissions": {
            "allow": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebSearch", "WebFetch", "Skill",
                      f"Read(/{h}/**)", "Read(//tmp/**)", "Read(//private/tmp/**)", f"Edit(/{h}/.claude/**/*.md)",
                      f"Edit(/{h}/.claude-owa/**/*.md)"],
            "deny": ["Bash(git reset:*)", "Bash(git rebase:*)", "Bash(git push --force:*)",
                     "Bash(git push --force-with-lease:*)", "Bash(git push -f:*)", "Bash(prisma migrate reset:*)",
                     "Bash(npx prisma migrate reset:*)", f"Edit(/{h}/.claude/CLAUDE.md)", f"Edit(/{h}/.claude/rules/**)",
                     f"Edit(/{h}/.claude/projects/*/memory/**)", f"Edit(/{h}/.claude-owa/CLAUDE.md)",
                     f"Edit(/{h}/.claude-owa/rules/**)", f"Edit(/{h}/.claude-owa/projects/*/memory/**)"],
            "ask": ["Bash(prisma db push:*)", "Bash(npx prisma db push:*)"],
            "additionalDirectories": ["/private/tmp", f"{h}/scrum-work", f"{h}/.claude", f"{h}/.claude-owa"]}})
        self.file.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)", "Read"], "deny": ["Bash(rm:*)"],
                                                          "additionalDirectories": [f"{h}/.claude"]}}, indent=2))
        self.assertEqual(self.merge().stdout, "changed\n")
        perms = json.loads(self.file.read_text())["permissions"]
        self.assertEqual(perms["allow"][:4], ["Bash(ls:*)", "Read", "Bash", "Edit"])
        self.assertEqual(len(perms["allow"]), 15)
        self.assertEqual(perms["deny"][:2], ["Bash(rm:*)", "Bash(git reset:*)"])
        self.assertEqual(perms["ask"], ["Bash(prisma db push:*)", "Bash(npx prisma db push:*)"])
        self.assertEqual(perms["additionalDirectories"], [f"{h}/.claude", "/private/tmp", f"{h}/scrum-work",
                                                          f"{h}/.claude-owa"])
        before, st = self.file.read_bytes(), self.file.stat()
        r = self.merge()
        self.assertEqual((r.returncode, r.stdout), (0, "same\n"))
        after = self.file.stat()
        self.assertEqual((self.file.read_bytes(), after.st_ino, after.st_mtime_ns), (before, st.st_ino, st.st_mtime_ns))
        self.assertEqual(os.listdir(self.file.parent), ["settings.json"])

    def test_merge_adds_edit_check_hook(self):
        self.assertEqual(self.merge().stdout, "changed\n")
        post = json.loads(self.file.read_text())["hooks"]["PostToolUse"]
        self.assertEqual(len(post), 1)
        self.assertEqual(post[0]["matcher"], "Edit|Write|MultiEdit")
        self.assertEqual(post[0]["hooks"], [{"type": "command", "command": shop.EDIT_CHECK_CMD, "timeout": 60}])
        before = self.file.read_bytes()
        r = self.merge()
        self.assertEqual((r.returncode, r.stdout, self.file.read_bytes()), (0, "same\n", before))

    def test_merge_keeps_existing_post_hooks(self):
        other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
        self.file.parent.mkdir()
        self.file.write_text(json.dumps({"hooks": {"PostToolUse": [other]}}))
        self.merge()
        self.assertEqual(json.loads(self.file.read_text())["hooks"]["PostToolUse"][0], other)
        self.assertEqual(len(json.loads(self.file.read_text())["hooks"]["PostToolUse"]), 2)
        mine = {"hooks": [{"type": "command", "command": "python3 x/edit-check.py"}]}
        self.file.write_text(json.dumps({"hooks": {"PostToolUse": [other, mine]}}))
        self.merge()
        self.assertEqual(json.loads(self.file.read_text())["hooks"]["PostToolUse"], [other, mine])

    def test_edit_check_cmd_noop_without_script(self):
        r = REAL_RUN(["sh", "-c", shop.EDIT_CHECK_CMD], cwd=self.home, capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_keeps_other_keys(self):
        stop = {"Stop": [{"hooks": [{"type": "command", "command": "echo é"}]}]}
        other = {"statusLine": {"type": "command", "command": "~/s.sh"}, "env": {"A": "1"}, "theme": "dark"}
        self.file.parent.mkdir()
        self.file.write_text(json.dumps({**other, "hooks": stop, "permissions": {"defaultMode": "acceptEdits", "allow": ["Read"]}},
                                        indent=2, ensure_ascii=False) + "\n")
        before = self.file.read_text()
        self.assertEqual(self.merge().stdout, "changed\n")
        after = self.file.read_text()
        for key, value in other.items():  # each key's own lines, as Claude Code writes them, are in both files
            block = json.dumps({key: value}, indent=2, ensure_ascii=False)[2:-2]
            self.assertIn(block, before, key)
            self.assertIn(block, after, key)
        self.assertEqual(json.loads(after)["hooks"]["Stop"], stop["Stop"])  # the hooks key gains PostToolUse beside it
        self.assertIn('    "defaultMode": "acceptEdits",\n', after)
        self.assertIn('"command": "echo é"', after)

    def test_malformed_json_not_written(self):
        self.file.parent.mkdir()
        for bad in ("{ not json", '{"permissions": []}', '{"permissions": {"allow": "Bash"}}', "[]", "",
                    '{"hooks": []}', '{"hooks": {"PostToolUse": {}}}'):
            with self.subTest(bad=bad):
                self.file.write_text(bad)
                r = self.merge()
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout, "")
                self.assertEqual(self.file.read_text(), bad)
                self.assertEqual(os.listdir(self.file.parent), ["settings.json"])

    def test_no_local_only_entries(self):
        text = json.dumps(shop.SHOP_PERMISSIONS)
        for bad in ("mcp__", "ClaudeInChromeDomain", ".env.prod", "/opt/homebrew", "gh pr merge", "safe-reset",
                    "trevorhecht", "/Users/"):
            self.assertNotIn(bad, text, bad)


class ReadyTest(SetupCase):
    def ready(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            got = shop.ready()
        self.assertEqual(out.getvalue(), "")
        return got

    def test_shape(self):
        no_node = "{ 1 1 1 }\n4\n/u/gh\n/u/claude\n"
        cases = (((), {"ready": True, "up": True, "gh": True, "node": True, "claude": True,
                       "accounts": {"main": True, "owa": False}}),
                 ((("gh auth status", 1, ""),), {"ready": False, "up": True, "gh": False, "node": True, "claude": True,
                                                 "accounts": {"main": True, "owa": False}}),
                 ((("sysctl", 0, no_node),), {"ready": False, "up": True, "gh": True, "node": False, "claude": True,
                                              "accounts": {"main": True, "owa": False}}),
                 ((("claude -p", 1, ""),), {"ready": False, "up": True, "gh": True, "node": True, "claude": True,
                                            "accounts": {"main": False, "owa": False}}))
        for extra, want in cases:
            with self.subTest(extra=extra):
                shop._cache.clear()
                shop._ready.clear()
                self.shop(*extra, (".claude-owa/oauth-token", 3, ""), *DONE)
                self.assertEqual(self.ready(), want)

    def test_worker_accounts_only(self):
        self.worker_file("newmac 1 owa\nboth 2 owa,main\n")
        for alias, accounts in (("newmac", {"owa": True}), ("both", {"main": True, "owa": True}),
                                ("other", {"main": True, "owa": True})):
            with self.subTest(alias=alias):
                self.alias = alias
                self.shop(*DONE)
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    got = shop.ready(alias=alias)
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(got, {"ready": True, "up": True, "gh": True, "node": True, "claude": True,
                                       "accounts": accounts})
                self.assertEqual(list(got["accounts"]), list(accounts), "SHOP_ACCOUNTS order")
                self.assertEqual(len(self.cmds("claude -p")), len(accounts))
        self.alias = "newmac"
        shop._cache.clear()
        self.shop(("sysctl", 255, ""))
        self.assertEqual(shop.ready(alias="newmac")["accounts"], {"owa": False}, "down: the worker's accounts")

    def test_down_no_extra_ssh(self):
        self.shop(("sysctl", 255, ""))
        want = {"ready": False, "up": False, "gh": False, "node": False, "claude": False,
                "accounts": {"main": False, "owa": False}}
        self.assertEqual(self.ready(), want)
        self.assertEqual(self.ready(), want)
        self.assertEqual([c[0] for c in self.calls], [shop.PROBE_CMD])

    def test_cached_and_cleared_by_setup(self):
        self.assertEqual(shop.READY_TTL, 600)
        self.shop(*DONE)
        with mock.patch.object(shop, "time") as clock:
            clock.monotonic.return_value = 1000.0
            first = self.ready()
            self.assertTrue(first["ready"])
            self.assertEqual(len(self.cmds("gh auth status")), 1)
            for later, checks in ((30, 1), (599, 1), (601, 2)):
                clock.monotonic.return_value = 1000.0 + later
                self.assertEqual(self.ready(), first)
                self.assertEqual(len(self.cmds("gh auth status")), checks, later)
            with contextlib.redirect_stdout(io.StringIO()):
                shop.setup()
            self.assertEqual(len(self.cmds("gh auth status")), 3)  # setup's own gh login check
            self.ready()
            self.assertEqual(len(self.cmds("gh auth status")), 4)  # setup dropped the ready() cache


class SetupCacheTest(SetupCase):
    def test_setup_clears_caches_at_end(self):
        self.shop(*DONE)
        with contextlib.redirect_stdout(io.StringIO()):
            shop.setup()
        shop.ready()
        self.assertIn("shopmac", shop._cache)
        self.assertIn("shopmac", shop._ready)
        with contextlib.redirect_stdout(io.StringIO()):
            shop.setup()
        self.assertEqual((shop._cache, shop._ready), ({}, {}))

    def test_first_setup_links_settings_json_made_by_permissions(self):
        h = Path(self.home)
        (h / ".claude").mkdir()
        self.shop(('mkdir -p "$HOME/.claude-owa"', LOCAL, ""), ("ln -s", LOCAL, ""), ("python3 -", LOCAL, ""), *DONE)
        self.assertFalse((h / ".claude" / "settings.json").exists())
        got, lines = self.setup_out()
        self.assertEqual(got["owa links"], "changed")
        self.assertEqual(os.readlink(h / ".claude-owa" / "settings.json"), f"{h}/.claude/settings.json")


class EnvCopyTest(SetupCase):
    def setUp(self):
        super().setUp()
        self.repo = Path(self.home) / "repo"
        self.repo.mkdir()
        (self.repo / ".env.local").write_bytes(ENV_LINE)

    def copy(self, project="onewitharts", repo=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            got = shop.env_copy(project, str(repo or self.repo))
        self.assertEqual(out.getvalue(), "")
        return got

    def test_copied_via_stdin_umask(self):
        self.shop(("scrum-work", LOCAL, ""), *DONE)
        self.assertEqual(self.copy(), "copied")
        self.assertEqual(self.calls[1:], [(
            "umask 077 && mkdir -p ~/scrum-work/onewitharts && cat > ~/scrum-work/onewitharts/.env.local.tmp && "
            "mv -f ~/scrum-work/onewitharts/.env.local.tmp ~/scrum-work/onewitharts/.env.local", 60,
            b"SECRET_962=abc962xyz\n")])
        dest = Path(self.home) / "scrum-work" / "onewitharts"
        self.assertEqual(((dest / ".env.local").read_bytes(), os.listdir(dest)),
                         (b"SECRET_962=abc962xyz\n", [".env.local"]))
        self.assertEqual((stat.S_IMODE(dest.stat().st_mode), stat.S_IMODE((dest / ".env.local").stat().st_mode)),
                         (0o700, 0o600))
        self.shop(("scrum-work", 1, ""), *DONE)
        self.assertEqual(self.copy(), "failed")

    def test_missing_file_none(self):
        self.shop(*DONE)
        self.assertEqual(self.copy(repo=Path(self.home)), "none")
        self.assertEqual(self.argv, [])

    def test_bad_project_name(self):
        self.shop(*DONE)
        for name in ("-x", "../x", ".hidden", "", "a b", "a/b", "x;rm -rf ~", "$(id)", "é", "x\n"):
            with self.subTest(name=name):
                self.assertEqual(self.copy(name), "failed")
        self.assertEqual(self.argv, [])

    def test_down_failed(self):
        self.shop(("sysctl", 255, ""))
        self.assertEqual(self.copy(), "failed")
        self.assertEqual([c[0] for c in self.calls], [shop.PROBE_CMD])


AUTH = b'{"cookies": [{"name": "next-auth.session-token", "value": "sess1069xyz"}]}\n'
AUTH_CMD = ("umask 077 && mkdir -p ~/scrum-work/onewitharts/playwright/.auth && cat > "
            "~/scrum-work/onewitharts/playwright/.auth/admin.json.tmp && mv -f "
            "~/scrum-work/onewitharts/playwright/.auth/admin.json.tmp ~/scrum-work/onewitharts/playwright/.auth/admin.json")
GIT_EXCLUDE = b"# git ls-files --others --exclude-from=.git/info/exclude\n# *~\n"
# This Mac's Conventions files by home-relative path; .claude/rules/performance.md is a link on this Mac.
CONV = [("Developer/repos/CLAUDE.md", b"# repos conventions 1245\n"),
        ("Developer/repos/.claude/rules/debugging.md", b"# debugging rule 1245\n"),
        (".claude/rules/performance.md", b"# performance rule 1245\n")]
CONV_CMDS = ["umask 077 && mkdir -p ~/Developer/repos && cat > ~/Developer/repos/CLAUDE.md.tmp"
             " && mv -f ~/Developer/repos/CLAUDE.md.tmp ~/Developer/repos/CLAUDE.md",
             "umask 077 && mkdir -p ~/Developer/repos/.claude/rules && cat > ~/Developer/repos/.claude/rules/debugging.md.tmp"
             " && mv -f ~/Developer/repos/.claude/rules/debugging.md.tmp ~/Developer/repos/.claude/rules/debugging.md",
             "umask 077 && mkdir -p ~/.claude/rules && cat > ~/.claude/rules/performance.md.tmp"
             " && mv -f ~/.claude/rules/performance.md.tmp ~/.claude/rules/performance.md"]


class ProfileCopyTest(SetupCase):
    """This Mac's HOME and the shop's are two temp dirs; LOCAL runs every remote call in a local sh under the shop's
    HOME, as the shop would. The repo is reached through a symlink, so str(repo) and its realpath differ."""

    def setUp(self):
        super().setUp()
        base = Path(self.home)
        self.mac, self.sh = base / "mac_home.1", base / "shop_home.2"
        self.home = str(self.sh)  # SetupCase's LOCAL answer runs under self.home
        self.real = self.mac / "repos" / "onewitharts"
        (self.real / "scrum").mkdir(parents=True)
        self.link = self.mac / "link-onewitharts"
        self.link.symlink_to(self.real)
        self.clone = self.sh / "scrum-work" / "onewitharts"
        (self.clone / ".git" / "info").mkdir(parents=True)
        (self.clone / ".git" / "info" / "exclude").write_bytes(GIT_EXCLUDE)
        env = mock.patch.dict(os.environ, {"HOME": str(self.mac)})
        env.start()
        self.addCleanup(env.stop)

    def profile(self, text):
        (self.real / "scrum" / "project.md").write_bytes(text.encode())

    def copy(self, project="onewitharts", repo=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            got = shop.profile_copy(project, str(repo or self.link))
        self.assertEqual(out.getvalue(), "")
        return got

    def shop_profile(self):
        return (self.clone / "scrum" / "project.md").read_bytes()

    def write_shop_profile(self, data):
        (self.clone / "scrum").mkdir(exist_ok=True)
        (self.clone / "scrum" / "project.md").write_bytes(data)

    def mac_conventions(self):
        """Write CONV under this Mac's home; performance.md is a link into a skills clone, as on Trevor's Mac."""
        target = self.mac / "code" / "trevorhecht-skills" / "rules" / "performance.md"
        for rel, data in CONV:
            path = target if rel == ".claude/rules/performance.md" else self.mac / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.mac / ".claude" / "rules").mkdir(parents=True)
        (self.mac / ".claude" / "rules" / "performance.md").symlink_to(target)

    def test_paths_rewritten_to_shop_home(self):
        m, r, l = self.mac, self.real, self.link
        self.profile(
            "# Project profile\n"
            f"- Conventions to read: {l}/CLAUDE.md {m}/.claude/CLAUDE.md, {r}/AGENTS.md {m}/Developer/repos/CLAUDE.md\n"
            "- E2E: E2E_PORT=$(python3 -c 'import socket') npm run test:e2e\r\n"
            "- Test sign-in: admin a@b.test / pw|&\\1 (Ünïcode)\n"
            "- Render auth: ../../../playwright/.auth/admin.json\n"
            "- Visual mask: [data-visual-mask]\n"
            f"- Notes: {m}/repos/onewitharts-old/x, {m}/repos/onewitharts.bak, \"{r}\" `{l}`; {r}:{l}\n"
            f"- Other home: /Users/someone/x {m}x/y\n"
            f"Ends on {r}")
        sh = self.sh
        want = ("# Project profile\n"
                f"- Conventions to read: {sh}/scrum-work/onewitharts/CLAUDE.md {sh}/.claude/CLAUDE.md, "
                f"{sh}/scrum-work/onewitharts/AGENTS.md {sh}/Developer/repos/CLAUDE.md\n"
                "- E2E: E2E_PORT=$(python3 -c 'import socket') npm run test:e2e\r\n"
                "- Test sign-in: admin a@b.test / pw|&\\1 (Ünïcode)\n"
                "- Render auth: ../../../playwright/.auth/admin.json\n"
                "- Visual mask: [data-visual-mask]\n"
                f"- Notes: {sh}/repos/onewitharts-old/x, {sh}/repos/onewitharts.bak, \"{sh}/scrum-work/onewitharts\" "
                f"`{sh}/scrum-work/onewitharts`; {sh}/scrum-work/onewitharts:{sh}/scrum-work/onewitharts\n"
                f"- Other home: /Users/someone/x {m}x/y\n"
                f"Ends on {sh}/scrum-work/onewitharts").encode()
        self.write_shop_profile(b"".join(b"- shop line %d\n" % i for i in range(14)))  # a stale shop-written profile
        self.shop(("scrum-work", LOCAL, ""), *DONE)
        self.assertEqual(self.copy(), "copied")
        self.assertEqual(self.shop_profile(), want)
        self.assertEqual(sorted(os.listdir(self.clone / "scrum")), ["project.md"])  # the tmp file is gone
        [(cmd, timeout, given)] = self.cmds("project.md")
        self.assertEqual(timeout, 60)
        self.assertNotIn(str(m), cmd)
        self.assertFalse([a for a in self.argv if "Test sign-in" in " ".join(a)])
        self.assertIn(b"- Test sign-in: admin a@b.test", given)
        self.profile("- Test: second\n")
        self.assertEqual(self.copy(), "copied")
        self.assertEqual(self.shop_profile(), b"- Test: second\n")

    def test_exclude_lines_added_once(self):
        self.profile("- Test: x\n")
        exclude = self.clone / ".git" / "info" / "exclude"
        self.shop(("scrum-work", LOCAL, ""), *DONE)
        for before, after in ((GIT_EXCLUDE, GIT_EXCLUDE + b"scrum/\n.claude/worktrees/\n"),
                              (b"# mine\nscrum/", b"# mine\nscrum/\n.claude/worktrees/\n"),
                              (None, b"scrum/\n.claude/worktrees/\n")):
            with self.subTest(before=before):
                if before is None:
                    shutil.rmtree(exclude.parent)
                else:
                    exclude.write_bytes(before)
                self.assertEqual(self.copy(), "copied")
                self.assertEqual(exclude.read_bytes(), after)
                self.assertEqual(self.copy(), "copied")
                self.assertEqual(exclude.read_bytes(), after)

    def test_no_clone_writes_nothing(self):
        self.profile("- Render auth: ../../../a.json\n")
        (self.real / "a.json").write_bytes(AUTH)
        shutil.rmtree(self.clone / ".git")
        self.shop(("scrum-work", LOCAL, ""), *DONE)
        for gitfile in (False, True):
            with self.subTest(gitfile=gitfile):
                if gitfile:
                    (self.clone / ".git").write_text("gitdir: /elsewhere\n")
                before = tree(self.sh)
                self.assertEqual(self.copy(), "failed")
                self.assertEqual(tree(self.sh), before)
                self.assertEqual(sorted(os.listdir(self.clone)), [".git"] if gitfile else [])
                self.assertEqual(self.cmds("a.json"), [])
        shutil.rmtree(self.sh / "scrum-work")
        self.assertEqual(self.copy(), "failed")
        self.assertEqual(os.listdir(self.sh), [])

    def test_render_auth_copied_mode_600(self):
        self.profile("- Render auth: ../../../playwright/.auth/admin.json\n")
        (self.real / "playwright" / ".auth").mkdir(parents=True)
        (self.real / "playwright" / ".auth" / "admin.json").write_bytes(AUTH)
        (self.real / "playwright" / ".auth" / "customer.json").write_bytes(b"{}\n")
        dest = self.clone / "playwright" / ".auth" / "admin.json"
        self.shop(("scrum-work", LOCAL, ""), *DONE)
        self.assertEqual(self.copy(), "copied")
        self.assertEqual([c[0] for c in self.calls[2:]], [AUTH_CMD])
        self.assertEqual(self.calls[2][1:], (60, AUTH))
        self.assertEqual((dest.read_bytes(), sorted(os.listdir(dest.parent))), (AUTH, ["admin.json"]))
        self.assertEqual([stat.S_IMODE(p.stat().st_mode) for p in (self.clone / "playwright", dest.parent, dest)],
                         [0o700, 0o700, 0o600])
        dest.chmod(0o644)
        (self.real / "playwright" / ".auth" / "admin.json").write_bytes(b"fresh\n")
        self.assertEqual(self.copy(), "copied")
        self.assertEqual((dest.read_bytes(), stat.S_IMODE(dest.stat().st_mode)), (b"fresh\n", 0o600))
        self.profile("  -  Render auth:   ../../../root.json  \n")  # at the repo root: an empty folder
        (self.real / "root.json").write_bytes(AUTH)
        self.assertEqual(self.copy(), "copied")
        self.assertEqual(((self.clone / "root.json").read_bytes(), stat.S_IMODE((self.clone / "root.json").stat().st_mode)),
                         (AUTH, 0o600))

    def test_render_auth_skipped(self):
        for rel in ("../x.json", ".claude/worktrees/scrum-x/admin.json", ".claude/settings.json", "a b.json"):
            (self.real / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.real / rel).write_bytes(AUTH)  # each exists here, so only the path check refuses it
        self.shop(("scrum-work", LOCAL, ""), *DONE)
        for line in ("", "- Render auth: ../../../playwright/.auth/missing.json\n", "- Render auth: ../../../../x.json\n",
                     "- Render auth: admin.json\n", "- Render auth: ../../settings.json\n",
                     "- Render auth: ../../../a b.json\n", "- Render auth:\n", "- Render auth: ../../..\n",
                     "- Render auth: ../../../scrum\n"):
            with self.subTest(line=line):
                shop._cache.clear()
                self.calls.clear()
                self.profile(f"- Test: x\n{line}")
                self.assertEqual(self.copy(), "copied")
                self.assertEqual([c[0] for c in self.calls][:1], [shop.PROBE_CMD])
                self.assertEqual(len(self.calls), 2, self.calls)
                self.assertIn("project.md", self.calls[1][0])
                self.assertNotIn(b"sess1069xyz", self.calls[1][2])
                self.assertEqual(self.shop_profile(), f"- Test: x\n{line}".encode())
        self.assertEqual(sorted(os.listdir(self.clone)), [".git", "scrum"])

    def test_conventions_copied_to_shop_home(self):
        self.mac_conventions()
        m = self.mac
        self.shop(("scrum-work", LOCAL, ""), ("umask 077", LOCAL, ""), *DONE)
        for sep in (",", ", ", " "):
            with self.subTest(sep=sep):
                shop._cache.clear()
                self.calls.clear()
                self.argv.clear()
                for d in ("Developer", ".claude"):
                    shutil.rmtree(self.sh / d, ignore_errors=True)
                self.profile(f"- Test: x\n- Conventions to read: {m}/Developer/repos/CLAUDE.md{sep}"
                             f"{m}/Developer/repos/.claude/rules/debugging.md{sep}{m}/.claude/rules/performance.md{sep}"
                             f"{m}/Developer/./repos/CLAUDE.md\n")  # the last one is the first again: copied once
                self.assertEqual(self.copy(), "copied")
                self.assertEqual(self.calls[0][0], shop.PROBE_CMD)
                self.assertIn('"$d/scrum/project.md.tmp"', self.calls[1][0])  # the profile call, then the auth-less tail
                self.assertEqual(self.calls[2:], [(CONV_CMDS[0], 60, b"# repos conventions 1245\n"),
                                                  (CONV_CMDS[1], 60, b"# debugging rule 1245\n"),
                                                  (CONV_CMDS[2], 60, b"# performance rule 1245\n")])
                for rel, data in (("Developer/repos/CLAUDE.md", b"# repos conventions 1245\n"),
                                  ("Developer/repos/.claude/rules/debugging.md", b"# debugging rule 1245\n"),
                                  (".claude/rules/performance.md", b"# performance rule 1245\n")):
                    dest = self.sh / rel
                    self.assertEqual((dest.read_bytes(), stat.S_IMODE(dest.stat().st_mode), dest.is_symlink()),
                                     (data, 0o600, False), rel)
                self.assertEqual(sorted(os.listdir(self.sh / "Developer" / "repos")), [".claude", "CLAUDE.md"])
                self.assertEqual(os.listdir(self.sh / ".claude" / "rules"), ["performance.md"])
                for argv in self.argv:
                    for word in ("repos conventions 1245", "debugging rule 1245", "performance rule 1245"):
                        self.assertNotIn(word, " ".join(argv))
        fake = self.sp.side_effect

        def mac_files_gone(argv, **kw):  # every Conventions file was read before the first ssh call
            for d in ("Developer", ".claude", "code"):
                shutil.rmtree(m / d, ignore_errors=True)
            return fake(argv, **kw)
        self.sp.side_effect = mac_files_gone
        shop._cache.clear()
        for d in ("Developer", ".claude"):
            shutil.rmtree(self.sh / d)
        self.assertEqual(self.copy(), "copied")
        self.assertEqual([(self.sh / rel).read_bytes() for rel in ("Developer/repos/CLAUDE.md",
                                                                   ".claude/rules/performance.md")],
                         [b"# repos conventions 1245\n", b"# performance rule 1245\n"])

    def test_conventions_skipped(self):
        m, outside = self.mac, self.sh.parent  # outside: neither this Mac's home nor the shop's
        real = m / "Developer" / "repos" / "proj"
        (real / "scrum").mkdir(parents=True)
        (m / "Developer" / "link-proj").symlink_to(real)
        (m / "Developer" / "other-link").symlink_to(real)
        (self.sh / "scrum-work" / "proj" / ".git" / "info").mkdir(parents=True)
        # A home as long as this Mac's, and Developer/y.md exists here too: only the home rule refuses it.
        sibling = outside / "mac_home.2" / "Developer" / "y.md"
        for path in (real / "CLAUDE.md", m / ".claude" / "CLAUDE.md", m / "Developer" / "x.txt", outside / "x.md", sibling,
                     m / "code" / "x.md", m / ".ssh" / "x.md", m / "Developer" / "a$b.md", m / "Developer" / "y.md"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"# convention 1245\n")  # each exists here, so only the keep rule refuses it
        self.shop(("scrum-work", LOCAL, ""), ("umask 077", LOCAL, ""), *DONE)

        def copied(line):
            """(the call count, every shop file but project.md) after one profile_copy through the repo's link."""
            shop._cache.clear()
            self.calls.clear()
            for d in set(os.listdir(self.sh)) - {"scrum-work"}:  # what an earlier subtest wrote never fails this one
                shutil.rmtree(self.sh / d)
            (real / "scrum" / "project.md").write_text(f"- Test: x\n{line}")
            self.assertEqual(self.copy("proj", m / "Developer" / "link-proj"), "copied")
            return len(self.calls), {k: v for k, v in tree(self.sh).items() if not k.endswith("project.md")}
        without = copied("")
        self.assertEqual(without[0], 2)  # the probe and the profile call
        for name, token in (("in repo, through the link", f"{m}/Developer/link-proj/CLAUDE.md"),
                            ("in repo, real path", f"{real}/CLAUDE.md"),
                            ("in repo, through another link", f"{m}/Developer/other-link/CLAUDE.md"),
                            ("home CLAUDE.md", f"{m}/.claude/CLAUDE.md"), ("not .md", f"{m}/Developer/x.txt"),
                            ("outside home", f"{outside}/x.md"), ("a sibling home", str(sibling)),
                            ("off the two folders", f"{m}/code/x.md"),
                            ("dot-dot out of Developer", f"{m}/Developer/../.ssh/x.md"),
                            ("odd character", f"{m}/Developer/a$b.md"), ("relative", "~/Developer/y.md"),
                            ("missing", f"{m}/Developer/missing.md")):
            with self.subTest(name):
                self.assertEqual(copied(f"- Conventions to read: {token}\n"), without)
        self.assertFalse((self.sh / "Developer").exists() or (self.sh / ".claude").exists() or (self.sh / ".ssh").exists())

    def test_conventions_replace_shop_symlink(self):
        self.mac_conventions()
        self.profile(f"- Conventions to read: {self.mac}/Developer/repos/CLAUDE.md\n")
        old = self.sh / "Developer" / "repos" / "trevorhecht-skills" / "CLAUDE.md"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"# the shop's own file\n")
        dest = self.sh / "Developer" / "repos" / "CLAUDE.md"
        dest.symlink_to(old)
        self.shop(("scrum-work", LOCAL, ""), ("umask 077", LOCAL, ""), *DONE)
        for n in (1, 2):
            with self.subTest(copy=n):
                self.assertEqual(self.copy(), "copied")
                self.assertFalse(dest.is_symlink())
                self.assertEqual((dest.read_bytes(), stat.S_IMODE(dest.stat().st_mode)),
                                 (b"# repos conventions 1245\n", 0o600))
                self.assertEqual(old.read_bytes(), b"# the shop's own file\n")
                self.assertEqual(sorted(os.listdir(dest.parent)), ["CLAUDE.md", "trevorhecht-skills"])
                self.assertEqual(len(self.cmds("CLAUDE.md.tmp")), n)

    def test_missing_profile_none(self):
        self.shop(*DONE)
        self.assertEqual(self.copy(), "none")
        self.assertEqual(self.argv, [])

    def test_bad_project_name(self):
        self.profile("- Test: x\n")
        self.shop(*DONE)
        for name in ("-x", "../x", ".hidden", "", "a b", "a/b", "x;rm -rf ~", "$(id)", "é", "x\n"):
            with self.subTest(name=name):
                self.assertEqual(self.copy(name), "failed")
        self.assertEqual(self.argv, [])

    def test_down_failed(self):
        self.profile("- Test: x\n")
        self.shop(("sysctl", 255, ""), ("scrum-work", LOCAL, ""))
        self.assertEqual(self.copy(), "failed")
        self.assertEqual([c[0] for c in self.calls], [shop.PROBE_CMD])

    def test_remote_failure_failed(self):
        self.mac_conventions()
        self.profile("- Render auth: ../../../a.json\n"
                     f"- Conventions to read: {self.mac}/Developer/repos/CLAUDE.md {self.mac}/.claude/rules/performance.md\n")
        (self.real / "a.json").write_bytes(AUTH)
        for fail, ran, auth in (("project.md", 1, False), ("a.json", 2, False), ("Developer/repos/CLAUDE.md", 3, True)):
            for rc in (1, 255, subprocess.TimeoutExpired(["ssh"], 60)):
                with self.subTest(fail=fail, rc=rc):
                    shop._cache.clear()
                    self.shop((fail, rc, ""), ("scrum-work", LOCAL, ""), ("umask 077", LOCAL, ""), *DONE)
                    self.assertEqual(self.copy(), "failed")
                    self.assertEqual(len(self.calls), 1 + ran)
                    self.assertEqual(self.cmds("performance.md"), [])  # no later Conventions call
                    self.assertEqual((self.clone / "a.json").exists(), auth)
                    (self.clone / "a.json").unlink(missing_ok=True)
        self.assertEqual(sorted(os.listdir(self.sh)), ["scrum-work"])


class SecretTest(SetupCase):
    def assert_clean(self, secret, text):
        self.assertFalse([a for a in self.argv if secret in " ".join(a)], "secret in argv")
        self.assertNotIn(secret, text)

    def test_token_never_in_argv_or_output(self):
        echo = f"error validating token {TOKEN}\n"  # a remote that echoes the token back on both streams
        for login in ((1, echo), (subprocess.TimeoutExpired(["ssh"], 60, output=TOKEN.encode()), "")):
            with self.subTest(login=login):
                self.shop(("gh auth login", *login), ("gh auth status", 1, echo), *DONE)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    got = shop.setup()
                    rc = shop.main(["setup"])
                self.assertEqual((got["gh login"], rc), ("failed", 1))
                self.assert_clean(TOKEN, out.getvalue() + err.getvalue())
                self.assertEqual([c[0] for c in self.calls if c[2] and TOKEN.encode() in c[2]], [GH_LOGIN, GH_LOGIN])

    def test_env_value_never_in_argv_or_output(self):
        repo = Path(self.home)
        (repo / ".env.local").write_bytes(ENV_LINE)
        for rc in (0, 1, subprocess.TimeoutExpired(["ssh"], 60, output=ENV_LINE)):
            with self.subTest(rc=rc):
                self.shop(("scrum-work", rc, ENV_LINE.decode()), *DONE)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    got = shop.env_copy("onewitharts", str(repo))
                self.assertEqual(got, "copied" if rc == 0 else "failed")
                self.assert_clean("abc962xyz", out.getvalue() + err.getvalue())
                self.assertEqual([c[2] for c in self.calls if c[2]], [b"SECRET_962=abc962xyz\n"])

    def test_auth_value_never_in_argv_or_output(self):
        repo = Path(self.home) / "onewitharts"
        (repo / "scrum").mkdir(parents=True)
        (repo / "scrum" / "project.md").write_text("- Render auth: ../../../playwright/.auth/admin.json\n")
        (repo / "playwright" / ".auth").mkdir(parents=True)
        (repo / "playwright" / ".auth" / "admin.json").write_bytes(AUTH)
        for rc in (0, 1, subprocess.TimeoutExpired(["ssh"], 60, output=AUTH)):
            with self.subTest(rc=rc):
                shop._cache.clear()
                self.shop(("admin.json", rc, AUTH.decode()), *DONE)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    got = shop.profile_copy("onewitharts", str(repo))
                self.assertEqual(got, "copied" if rc == 0 else "failed")
                self.assert_clean("sess1069xyz", out.getvalue() + err.getvalue())
                self.assertEqual([c[0] for c in self.calls if c[2] and b"sess1069xyz" in c[2]], [AUTH_CMD])
                self.assertEqual(self.cmds("admin.json")[0][2], AUTH)


PULL = "git -C ~/code/scrum pull --ff-only && git -C ~/code/trevorhecht-skills pull --ff-only"
IMPORT = b"@~/code/scrum/skills/trevskills-scrum/shop/machine-notes-shopmac.md\n"
SYNC = (("pull --ff-only", 0, ""), (".md-sync-cleanup-done", LOCAL, ""), ("tar -xf", LOCAL, ""))  # no git here


def key(path):
    """Claude Code's projects/ dir name for `path`, written out apart from shop.memory_key."""
    return "".join(c if c.isascii() and c.isalnum() else "-" for c in str(path))


def tree(root):
    """{path relative to `root`: bytes} for every file under `root`."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


class MdSyncTest(SetupCase):
    """This Mac's HOME and the shop's are two temp dirs whose paths hold `/`, `.` and `_`. LOCAL runs the cleanup and
    copy calls in a local sh under the shop's HOME, as the shop would."""

    def setUp(self):
        super().setUp()
        base = Path(self.home)
        self.mac, self.sh = base / "mac_home.1", base / "shop_home.2"
        self.home = str(self.sh)  # SetupCase's LOCAL answer runs under self.home
        (self.mac / ".claude").mkdir(parents=True)
        self.sh.mkdir()
        (self.mac / ".claude" / "CLAUDE.md").write_bytes(b"# rules 963\nno trailing newline")
        self.registry, self.paths = base / "projects.json", [7, "/nowhere/gone"]
        self.registry.write_text(json.dumps(self.paths))
        env = mock.patch.dict(os.environ, {"HOME": str(self.mac), "SCRUM_REGISTRY": str(self.registry)})
        env.start()
        self.addCleanup(env.stop)

    def backups(self, h):
        """The md-sync-backup-* folder names under h, sorted."""
        return sorted(n for n in os.listdir(h) if n.startswith("md-sync-backup-"))

    def repo(self, rel, scrum=True, memory=None):
        """Register <mac>/repos/<rel> (with a scrum/ dir when `scrum`) and give it local memory files {name: bytes}."""
        repo = self.mac / "repos" / rel
        (repo / "scrum" if scrum else repo).mkdir(parents=True)
        self.paths.append(str(repo))
        self.registry.write_text(json.dumps(self.paths))
        if memory is not None:
            self.write(self.mac / ".claude" / "projects" / key(repo) / "memory", memory)

    def write(self, folder, files):
        Path(folder).mkdir(parents=True, exist_ok=True)
        for name, data in files.items():
            (Path(folder) / name).write_bytes(data)

    def sync(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            got = shop.md_sync()
        self.assertEqual(out.getvalue(), "")
        return got

    def shop_key(self, name):
        return key(f"{self.sh}/scrum-work/{name}")

    def test_down_no_ssh(self):
        self.shop(("sysctl", 255, ""), *SYNC)
        self.assertIs(self.sync(), False)
        self.assertEqual([c[0] for c in self.calls], [shop.PROBE_CMD])

    def test_pulls_first_and_failure_stops(self):
        self.shop()  # every remote call exits 0 and prints noise
        self.assertIs(self.sync(), True)
        self.assertEqual(self.calls[0][0], shop.PROBE_CMD)
        self.assertEqual(self.calls[1], (PULL, 60, None))
        self.assertEqual([(c[1], c[2] is None) for c in self.calls[1:]], [(60, True), (60, True), (60, False)])
        self.assertIn(".md-sync-cleanup-done", self.calls[2][0])
        self.assertIn("tar -xf", self.calls[3][0])
        for fail, ran in (("pull --ff-only", 1), (".md-sync-cleanup-done", 2), ("tar -xf", 3)):
            for rc in (1, 255, subprocess.TimeoutExpired(["ssh"], 60)):
                with self.subTest(fail=fail, rc=rc):
                    shop._cache.clear()
                    self.shop((fail, rc, ""))
                    self.assertIs(self.sync(), False)
                    self.assertEqual(len(self.calls), 1 + ran)

    def test_claude_md_copied_with_import(self):
        claude = self.sh / ".claude"
        claude.mkdir()
        target = self.sh / "linked.md"
        target.write_bytes(b"shop own 963\n")
        (claude / "CLAUDE.md").symlink_to(target)
        self.shop(*SYNC)
        self.assertIs(self.sync(), True)
        want = b"# rules 963\nno trailing newline\n" + IMPORT
        self.assertFalse((claude / "CLAUDE.md").is_symlink())
        self.assertEqual(((claude / "CLAUDE.md").read_bytes(), target.read_bytes()), (want, b"shop own 963\n"))
        [(_, timeout, given)] = self.cmds("tar -xf")
        self.assertEqual(timeout, 60)
        with tarfile.open(fileobj=io.BytesIO(given)) as tar:
            self.assertEqual(tar.extractfile("CLAUDE.md").read(), want)
        self.assertFalse([a for a in self.argv if "rules 963" in " ".join(a)])
        (self.mac / ".claude" / "CLAUDE.md").write_bytes(b"# rules 963\n")  # a trailing newline gets no second one
        self.assertIs(self.sync(), True)
        self.assertEqual((claude / "CLAUDE.md").read_bytes(), b"# rules 963\n" + IMPORT)
        os.remove(self.mac / ".claude" / "CLAUDE.md")
        shop._cache.clear()
        self.shop(*SYNC)
        self.assertIs(self.sync(), False)
        self.assertEqual(self.argv, [])  # not even the probe

    def test_memory_mapped_and_replaced(self):
        self.assertEqual(shop.memory_key("/Users/a.b_c/scrum-work/my_app.web"), "-Users-a-b-c-scrum-work-my-app-web")
        self.repo("web/my_app.web", memory={"MEMORY.md": b"index 963\n", "note_a.md": b"fact a\n"})
        self.repo("api-two")  # registered, no local memory dir
        self.repo("plain", scrum=False, memory={"x.md": b"no scrum dir\n"})
        self.repo("a/dup", memory={"d.md": b"a\n"})
        self.repo("b/dup", memory={"d.md": b"b\n"})  # a folder name used twice syncs neither
        self.repo("_bad", memory={"b.md": b"bad name\n"})
        projects = self.sh / ".claude" / "projects"
        web, two, other = (projects / self.shop_key("my_app.web"), projects / self.shop_key("api-two"),
                           projects / "-Users-someone")
        self.assertTrue(web.name.endswith("-shop-home-2-scrum-work-my-app-web"), web.name)
        self.write(web / "memory", {"MEMORY.md": b"old\n", "stale.md": b"a shop session wrote this\n"})
        self.write(two / "memory", {"x.md": b"x\n"})
        self.write(other / "memory", {"MEMORY.md": b"m\n"})
        self.write(web, {"s1.jsonl": b"{}\n"})
        self.write(other, {"s2.jsonl": b"{}\n"})
        self.shop(*SYNC)
        self.assertIs(self.sync(), True)
        self.assertEqual(sorted(str(p.relative_to(projects)) for p in projects.glob("*/memory")),
                         [f"{web.name}/memory"])
        self.assertEqual(tree(projects), {f"{web.name}/memory/MEMORY.md": b"index 963\n",
                                          f"{web.name}/memory/note_a.md": b"fact a\n",
                                          f"{web.name}/s1.jsonl": b"{}\n", "-Users-someone/s2.jsonl": b"{}\n"})

    def test_colliding_keys_sync_neither(self):
        self.repo("x/app.one", memory={"MEMORY.md": b"dot\n"})
        self.repo("y/app-one", memory={"MEMORY.md": b"dash\n"})  # a different name, the same key on the shop
        self.repo("z/Solo", memory={"MEMORY.md": b"solo\n"})
        self.repo("w/a b", memory={"MEMORY.md": b"bad name\n"})  # fails PROJECT_RE, so it shares no key with a-b
        self.repo("v/a-b", memory={"MEMORY.md": b"ab\n"})
        self.shop(*SYNC)
        self.assertIs(self.sync(), True)
        solo, ab = self.shop_key("Solo"), self.shop_key("a-b")
        self.assertEqual(tree(self.sh / ".claude" / "projects"),
                         {f"{solo}/memory/MEMORY.md": b"solo\n", f"{ab}/memory/MEMORY.md": b"ab\n"})

    def test_second_sync_same_files(self):
        self.repo("app.one", memory={"MEMORY.md": b"index\n", "b_note.md": b"b\n"})
        self.shop(*SYNC)
        self.assertIs(self.sync(), True)
        claude = self.sh / ".claude"
        first = tree(claude)
        k = self.shop_key("app.one")
        self.assertEqual(first, {"CLAUDE.md": b"# rules 963\nno trailing newline\n" + IMPORT,
                                 f"projects/{k}/memory/MEMORY.md": b"index\n", f"projects/{k}/memory/b_note.md": b"b\n"})
        self.assertIs(self.sync(), True)
        self.assertEqual(tree(claude), first)
        self.assertEqual(sorted(os.listdir(claude)), ["CLAUDE.md", "projects"])  # the copy's temp dir is gone

    def test_skill_folders_copied(self):
        here, there = self.mac / ".claude" / "skills", self.sh / ".claude" / "skills"
        self.shop(*SYNC)
        self.assertIs(self.sync(), True)
        self.assertEqual(sorted(os.listdir(self.sh / ".claude")), ["CLAUDE.md", "projects"])  # no skills dir here
        email = here / "trevskills-email"
        self.write(email / "profiles" / "owa", {"customers.md": b"owa customers\n"})
        self.write(email, {"SKILL.md": b"email skill\n", "ai-tells.md": b"tells\n"})
        (email / "customers.md").symlink_to("profiles/owa/customers.md")  # arrives as a file
        (email / "gone.md").symlink_to("nowhere.md")  # broken: skipped
        self.write(self.mac / "shared", {"x.md": b"via dir link\n"})
        (email / "linked").symlink_to(self.mac / "shared")  # a directory link: its files arrive
        (email / "profiles" / "up").symlink_to("..")  # a cycle back up the tree: walked once
        self.write(here / "trevskills-backlog", {"SKILL.md": b"backlog here\n"})
        self.write(here / "synced", {"big.md": b"never sent\n"})
        self.write(here / "_private", {"SKILL.md": b"off PROJECT_RE\n"})
        self.write(self.mac / "clone" / "trevskills-scrum", {"SKILL.md": b"scrum here\n"})
        (here / "trevskills-scrum").symlink_to(self.mac / "clone" / "trevskills-scrum")  # a link here: not sent
        (here / "notes.md").write_bytes(b"a file, not a folder\n")
        shop_clone = self.sh / "code" / "trevorhecht-skills" / "trevskills-backlog"
        self.write(shop_clone, {"SKILL.md": b"shop clone\n"})
        there.mkdir()
        (there / "trevskills-backlog").symlink_to(shop_clone)  # a shop link this Mac's folder replaces
        self.write(there / "trevskills-email", {"SKILL.md": b"older copy\n", "stale.md": b"older copy\n"})
        self.write(there / "trevskills-mine", {"SKILL.md": b"shop only\n"})
        (there / "trevskills-scrum").symlink_to(self.sh / "code" / "scrum" / "skills" / "trevskills-scrum")
        self.assertIs(self.sync(), True)
        with tarfile.open(fileobj=io.BytesIO(self.cmds("tar -xf")[-1][2])) as tar:
            self.assertEqual(sorted(n for n in tar.getnames() if n.startswith("skills")),
                             ["skills/trevskills-backlog/SKILL.md", "skills/trevskills-email/SKILL.md",
                              "skills/trevskills-email/ai-tells.md", "skills/trevskills-email/customers.md",
                              "skills/trevskills-email/linked/x.md",
                              "skills/trevskills-email/profiles/owa/customers.md"])
        want = {"trevskills-backlog/SKILL.md": b"backlog here\n", "trevskills-email/SKILL.md": b"email skill\n",
                "trevskills-email/ai-tells.md": b"tells\n", "trevskills-email/customers.md": b"owa customers\n",
                "trevskills-email/profiles/owa/customers.md": b"owa customers\n",
                "trevskills-email/linked/x.md": b"via dir link\n",
                "trevskills-mine/SKILL.md": b"shop only\n"}
        for _ in range(2):  # a second sync leaves the same tree
            self.assertEqual(tree(there), want)
            self.assertEqual(sorted(os.listdir(there)),
                             ["trevskills-backlog", "trevskills-email", "trevskills-mine", "trevskills-scrum"])
            self.assertFalse((there / "trevskills-backlog").is_symlink())
            self.assertFalse((there / "trevskills-email" / "customers.md").is_symlink())
            self.assertEqual(os.readlink(there / "trevskills-scrum"),
                             str(self.sh / "code" / "scrum" / "skills" / "trevskills-scrum"))
            self.assertEqual(tree(shop_clone), {"SKILL.md": b"shop clone\n"})  # the link went, not its target
            self.assertEqual(sorted(os.listdir(self.sh / ".claude")), ["CLAUDE.md", "projects", "skills"])
            self.assertIs(self.sync(), True)

    def test_first_sync_backs_up_then_deletes(self):
        h = self.sh
        self.write(h, {"MACHINES.md": b"avoid heavy builds\n"})  # every other item missing: skipped
        self.shop(*SYNC)
        self.assertIs(self.sync(), True)
        (name,) = self.backups(h)
        self.assertRegex(name, r"^md-sync-backup-\d{4}-\d\d-\d\d-\d{6}$")
        self.assertEqual(tree(h / name), {"MACHINES.md": b"avoid heavy builds\n"})
        shutil.rmtree(h)
        h.mkdir()
        self.write(h / ".claude", {"CLAUDE.md": b"shop own 963\n"})
        self.write(h / ".claude" / "projects" / "-Users-shop" / "memory", {"machines-registry.md": b"registry\n"})
        self.write(h / ".claude" / "projects" / "-private-tmp" / "memory", {"MEMORY.md": b"tmp\n"})
        self.write(h, {"MACHINES.md": b"avoid heavy builds\n"})
        self.write(h / "code", {"scrum-multi-machine-spec.md": b"per-machine boards\n", "keep.md": b"k\n"})
        self.write(h / "scrum-probe", {"package.json": b"{}\n"})
        (h / "scrum-probe" / "node_modules").mkdir()
        self.assertIs(self.sync(), True)
        (name,) = self.backups(h)
        backup = h / name
        self.assertEqual(tree(backup), {"CLAUDE.md": b"shop own 963\n", "MACHINES.md": b"avoid heavy builds\n",
                                        "projects/-Users-shop/memory/machines-registry.md": b"registry\n",
                                        "projects/-private-tmp/memory/MEMORY.md": b"tmp\n",
                                        "scrum-multi-machine-spec.md": b"per-machine boards\n",
                                        "scrum-probe/package.json": b"{}\n"})
        self.assertTrue((backup / "scrum-probe" / "node_modules").is_dir())
        self.assertEqual(sorted(os.listdir(h)), [".claude", ".md-sync-cleanup-done", "code", name])
        self.assertEqual(os.listdir(h / "code"), ["keep.md"])
        self.assertEqual((h / ".claude" / "CLAUDE.md").read_bytes(), b"# rules 963\nno trailing newline\n" + IMPORT)
        self.assertEqual(list((h / ".claude" / "projects").glob("*/memory")), [])

    def test_backup_folder_unique_per_run(self):
        h = self.sh
        old = h / f"md-sync-backup-{datetime.date.today().isoformat()}"
        self.write(old, {"keep.txt": b"k\n"})
        self.write(old / "scrum-probe", {"old.json": b"{}\n"})
        self.write(h / "scrum-probe", {"package.json": b"{}\n"})
        self.shop(*SYNC)
        self.assertIs(self.sync(), True)
        (new,) = [n for n in self.backups(h) if n != old.name]
        self.assertEqual(tree(h / new), {"scrum-probe/package.json": b"{}\n"})
        self.assertEqual(tree(old), {"keep.txt": b"k\n", "scrum-probe/old.json": b"{}\n"})

    def test_backup_failure_deletes_nothing(self):
        h = self.sh
        self.write(h / ".claude", {"CLAUDE.md": b"shop own 963\n"})
        self.write(h / ".claude" / "projects" / "-Users-shop" / "memory", {"MEMORY.md": b"m\n"})
        self.write(h, {"MACHINES.md": b"avoid heavy builds\n"})
        self.write(h / "code", {"scrum-multi-machine-spec.md": b"draft\n"})
        self.write(h / "scrum-probe", {"package.json": b"{}\n"})
        before = tree(h)
        h.chmod(0o555)  # the backup folder cannot be made
        self.addCleanup(h.chmod, 0o755)
        self.shop(*SYNC)
        self.assertIs(self.sync(), False)
        self.assertEqual(tree(h), before)
        self.assertEqual(self.cmds("tar -xf"), [])

    def test_cleanup_runs_once(self):
        h = self.sh
        self.shop(*SYNC)
        self.assertIs(self.sync(), True)  # writes the marker
        for n in self.backups(h):
            shutil.rmtree(h / n)
        self.write(h, {"MACHINES.md": b"m\n"})
        self.write(h / "code", {"scrum-multi-machine-spec.md": b"d\n"})
        self.write(h / "scrum-probe", {"package.json": b"{}\n"})
        self.assertIs(self.sync(), True)
        self.assertEqual(sorted(os.listdir(h)), [".claude", ".md-sync-cleanup-done", "MACHINES.md", "code",
                                                 "scrum-probe"])
        self.assertEqual(len(self.cmds(".md-sync-cleanup-done")), 2)

    def test_machine_notes(self):
        self.assertEqual(shop.notes_import("shopmac"), IMPORT.decode().strip())
        self.assertEqual(shop.notes_import("mac2"), IMPORT.decode().strip().replace("shopmac", "mac2"))
        notes = SKILL / "shop" / "machine-notes-shopmac.md"
        self.assertEqual(ROOT / IMPORT.decode().strip()[len("@~/code/scrum/"):], notes)  # ~/code/scrum: this repo
        text = notes.read_text()
        for phrase in ("macOS 12", "No Homebrew", "Python 3.12 is `~/.local/bin/python3`", "`/usr/bin/python3` is older",
                       "Node 24", "darwin-x64", "`~/.local`", '`channel: "chrome"`', "`SCRUM_PW_CHANNEL`",
                       "Full builds and full test suites are fine here",
                       "never write memory notes, rules or CLAUDE.md, even where other instructions say to save a note",
                       "follow-ups", '"${C}:refs/heads/', "zsh", "## Cannot run", "VectorCraft",
                       "runs Chrome for Testing at `$SCRUM_CHROME`, never the Google Chrome app"):  # job 1227
            self.assertIn(phrase, text, phrase)
        for bad in ("trevorhecht", "onewitharts"):
            self.assertNotIn(bad, text, bad)
        src = (SKILL / "shop.py").read_text()
        self.assertNotIn("onewitharts", src)
        self.assertNotIn("/Users/", src)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class ChannelConfigTest(unittest.TestCase):
    """Imports channel.config.mjs with local node from a temp repo holding a plain-object playwright config."""

    PROJECTS = """export default {
  use: { baseURL: "http://localhost:1" },
  projects: [
    { name: "setup" },
    { name: "chromium", use: { browserName: "chromium" } },
    { name: "desktop", use: { defaultBrowserType: "chromium", viewport: { width: 1 } } },
    { name: "firefox", use: { browserName: "firefox" } },
    { name: "webkit", use: { defaultBrowserType: "webkit" }, testDir: "wk", outputDir: "/abs/out", snapshotDir: "s" },
  ],
};
"""

    def setUp(self):
        self.repo = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)

    def load(self, files, channel="chrome", chrome=None):
        for name, text in files.items():
            Path(self.repo, name).write_text(text)
        env = {k: v for k, v in os.environ.items() if k not in ("SCRUM_PW_CHANNEL", "SCRUM_CHROME")}
        if channel is not None:
            env["SCRUM_PW_CHANNEL"] = channel
        if chrome is not None:
            env["SCRUM_CHROME"] = chrome
        return REAL_RUN(["node", "--input-type=module", "-e",
                         "const m = await import(process.argv[1]); console.log(JSON.stringify(m.default))",
                         WRAPPER.as_uri()], cwd=self.repo, env=env, capture_output=True, text=True)

    def config(self, files, channel="chrome", chrome=None):
        r = self.load(files, channel, chrome)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_chromium_projects_get_channel(self):
        got = self.config({"playwright.config.mjs": self.PROJECTS})
        self.assertEqual(got["use"], {"baseURL": "http://localhost:1"})
        self.assertEqual([p.get("use") for p in got["projects"]], [
            {"channel": "chrome"}, {"browserName": "chromium", "channel": "chrome"},
            {"defaultBrowserType": "chromium", "viewport": {"width": 1}, "channel": "chrome"},
            {"browserName": "firefox"}, {"defaultBrowserType": "webkit"}])
        self.assertEqual("respectGitIgnore" in got, False)  # set per project: webkit has its own testDir
        self.assertEqual([p.get("respectGitIgnore") for p in got["projects"]], [True, True, True, True, None])
        # A top-level browserName wins over a project's defaultBrowserType, as in Playwright's merged `use`.
        got = self.config({"playwright.config.mjs": self.PROJECTS.replace('baseURL: "http://localhost:1"',
                                                                         'browserName: "firefox"')})
        self.assertEqual([p.get("use") for p in got["projects"]][:3], [
            None, {"browserName": "chromium", "channel": "chrome"},
            {"defaultBrowserType": "chromium", "viewport": {"width": 1}}])
        bare = self.config({"playwright.config.mjs": "export default { use: { headless: true } };\n"}, " msedge ")
        self.assertEqual(bare["use"], {"headless": True, "channel": "msedge"})
        for channel in (None, "", "  "):
            unset = self.config({"playwright.config.mjs": self.PROJECTS}, channel)
            self.assertEqual([p.get("use") for p in unset["projects"]][:2], [None, {"browserName": "chromium"}])
        # .js comes before .mjs; a CommonJS module.exports and a transpiled exports.default both load.
        got = self.config({"playwright.config.js": 'module.exports = { testDir: "from-js" };\n'})
        self.assertEqual(got["testDir"], f"{self.repo}/from-js")
        os.remove(Path(self.repo, "playwright.config.js"))
        os.remove(Path(self.repo, "playwright.config.mjs"))
        got = self.config({"playwright.config.cjs": 'exports.__esModule = true;\nexports.default = { testDir: "c" };\n'})
        self.assertEqual(got["testDir"], f"{self.repo}/c")

    def test_chrome_path_overrides_channel(self):
        """Job 1227: a non-blank SCRUM_CHROME (a worker's Chrome for Testing) launches that binary on chromium
        projects, keeping their launchOptions, with no channel; blank or unset leaves today's channel output."""
        bin_ = "/h/.local/share/cft/Google Chrome for Testing"
        files = {"playwright.config.mjs": self.PROJECTS.replace(
            'use: { baseURL: "http://localhost:1" }', 'use: { baseURL: "http://localhost:1", launchOptions: { args: ["--a"] } }'
        ).replace('{ name: "setup" }', '{ name: "setup", use: { launchOptions: { slowMo: 5 } } }')}
        got = self.config(files, chrome=f"  {bin_} ")
        self.assertEqual(got["use"], {"baseURL": "http://localhost:1", "launchOptions": {"args": ["--a"]}})
        self.assertEqual([p.get("use") for p in got["projects"]], [
            {"launchOptions": {"slowMo": 5, "executablePath": bin_}},
            {"browserName": "chromium", "launchOptions": {"args": ["--a"], "executablePath": bin_}},
            {"defaultBrowserType": "chromium", "viewport": {"width": 1},
             "launchOptions": {"args": ["--a"], "executablePath": bin_}},
            {"browserName": "firefox"}, {"defaultBrowserType": "webkit"}])
        bare = "export default { use: { headless: true, launchOptions: { args: ['--b'] } } };\n"
        self.assertEqual(self.config({"playwright.config.mjs": bare}, None, bin_)["use"],
                         {"headless": True, "launchOptions": {"args": ["--b"], "executablePath": bin_}})
        self.assertEqual(self.config({"playwright.config.mjs": "export default {};\n"}, chrome=bin_)["use"],
                         {"launchOptions": {"executablePath": bin_}})
        for chrome in ("", "  "):
            with self.subTest(chrome=chrome):
                self.assertEqual(self.config(files, chrome=chrome), self.config(files))
        self.assertEqual([p.get("use") for p in self.config(files)["projects"]][:2], [
            {"launchOptions": {"slowMo": 5}, "channel": "chrome"}, {"browserName": "chromium", "channel": "chrome"}])

    def test_custom_reporter_resolved_from_repo(self):
        r = self.repo
        mod = Path(r, "node_modules", "my-reporter")
        mod.mkdir(parents=True)
        (mod / "index.js").write_text("module.exports = class {};\n")
        got = self.config({"package.json": "{}", "playwright.config.mjs": """export default {
  reporter: [["my-reporter", {}], ["./rep.js"], ["missing-reporter"], ["list"], ["html"], ["json"], ["junit"],
             ["line"], ["dot"], ["null"], ["github"], ["blob"]],
};
"""})
        self.assertEqual(got["reporter"], [
            [f"{r}/node_modules/my-reporter/index.js", {}], [f"{r}/rep.js", {}], ["missing-reporter", {}],
            ["list", {}], ["html", {"outputFolder": f"{r}/playwright-report"}], ["json", {}], ["junit", {}],
            ["line", {}], ["dot", {}], ["null", {}], ["github", {}], ["blob", {}]])

    def test_top_level_respect_git_ignore_kept(self):
        got = self.config({"playwright.config.mjs": "export default { respectGitIgnore: false, projects: [{ name: 'a' }] };\n"})
        self.assertIs(got["respectGitIgnore"], False)
        self.assertEqual([p.get("respectGitIgnore") for p in got["projects"]], [None])

    def test_paths_resolved_to_repo(self):
        r = self.repo
        got = self.config({"playwright.config.mjs": """export default {
  testDir: "e2e", outputDir: "out", snapshotDir: "./snaps", globalSetup: "./setup.ts",
  globalTeardown: ["./a.ts", "/abs/b.ts"], tsconfig: "./tsconfig.e2e.json",
  reporter: [["html"], ["json", { outputFile: "r/report.json" }], ["junit", { outputFile: "/abs/j.xml" }], ["list"]],
  webServer: [{ command: "a" }, { command: "b", cwd: "web" }],
  projects: [{ name: "c", testDir: "pc", outputDir: "po", snapshotDir: "ps" }, { name: "d" }],
};
"""})
        self.assertEqual({k: got[k] for k in ("testDir", "outputDir", "snapshotDir", "globalSetup", "globalTeardown",
                                              "tsconfig", "reporter", "webServer")}, {
            "testDir": f"{r}/e2e", "outputDir": f"{r}/out", "snapshotDir": f"{r}/snaps", "globalSetup": f"{r}/setup.ts",
            "globalTeardown": [f"{r}/a.ts", "/abs/b.ts"], "tsconfig": f"{r}/tsconfig.e2e.json",
            "reporter": [["html", {"outputFolder": f"{r}/playwright-report"}],
                         ["json", {"outputFile": f"{r}/r/report.json"}], ["junit", {"outputFile": "/abs/j.xml"}],
                         ["list", {}]],
            "webServer": [{"command": "a", "cwd": r}, {"command": "b", "cwd": f"{r}/web"}]})
        self.assertEqual(got["projects"], [
            {"name": "c", "testDir": f"{r}/pc", "outputDir": f"{r}/po", "snapshotDir": f"{r}/ps",
             "use": {"channel": "chrome"}},
            {"name": "d", "use": {"channel": "chrome"}}])
        self.assertNotIn("respectGitIgnore", got)
        os.remove(Path(r, "playwright.config.mjs"))
        got = self.config({"playwright.config.mjs": 'export default { reporter: "html", webServer: { command: "a" } };\n'})
        self.assertEqual(got, {"reporter": [["html", {"outputFolder": f"{r}/playwright-report"}]],
                               "webServer": {"command": "a", "cwd": r}, "testDir": r, "outputDir": f"{r}/test-results",
                               "respectGitIgnore": True, "use": {"channel": "chrome"}})

    def test_missing_config_throws(self):
        r = self.load({})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(f"Error: channel.config.mjs: no playwright.config.* in {self.repo}", r.stderr)


URL = "https://github.com/trevorwhecht/onewitharts.git"
PROMPT = f"/trevskills-scrum cloud-job 964-shop-x Build it.\n$(touch pwned) `touch pwned2` {TOKEN}\n"
START = ('cd ~/scrum-work/onewitharts && (umask 077 && mkdir -p .git/scrum-shop && cat > .git/scrum-shop/964-shop-x.prompt)'
         ' || exit 1; export CLAUDE_CONFIG_DIR="$HOME/.claude-owa"; [ -r "$HOME/.claude-owa/oauth-token" ] && export '
         'CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude-owa/oauth-token")"; [ -r "$HOME/.config/typesafe/key" ] && export '
         'TYPESAFE_API_KEY="$(cat "$HOME/.config/typesafe/key")"; export SCRUM_PW_CHANNEL=chrome SCRUM_CHROME='
         '"$HOME/.local/share/chrome-for-testing-150.0.7871.125/chrome-mac-x64/Google Chrome for Testing.app/Contents/'
         'MacOS/Google Chrome for Testing" SCRUM_SHOP=1 '
         'CLAUDE_NOTIFIER_DISABLE=1 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0; nohup claude -p "$(cat '
         '.git/scrum-shop/964-shop-x.prompt)" --permission-mode acceptEdits --model \'claude-opus-4-5[1m]\' < /dev/null > '
         '.git/scrum-shop/964-shop-x.log 2>&1 & echo $!')
CLONE = ('d="$HOME/scrum-work/onewitharts"; if [ -d "$d/.git" ]; then [ "$(git -C "$d" config --get remote.origin.url)" '
         '= https://github.com/trevorwhecht/onewitharts.git ] || exit 3; git -C "$d" fetch -q origin && git -C "$d" checkout '
         '-q "$(git -C "$d" symbolic-ref --short refs/remotes/origin/HEAD | sed "s,^origin/,,")" && git -C "$d" merge '
         '--ff-only refs/remotes/origin/HEAD; else mkdir -p "$HOME/scrum-work" && git clone -- '
         'https://github.com/trevorwhecht/onewitharts.git "$d"; fi && ' + shop.TRUST)
ENDED = ('ps -p 4242 -o command= | grep -q claude && exit 3; f="$HOME/scrum-work/onewitharts/.git/scrum-shop/964-shop-x.log";'
         ' [ -f "$f" ] || exit 0; tail -c 8192 "$f"')


class DispatchTest(SetupCase):
    """clone, start and ended run their remote commands in a local sh under the shop's temp HOME (LOCAL), with a fake
    `claude` on the shop's PATH and GitHub URLs pointed at local bare repos by that HOME's git insteadOf."""

    def git(self, *args, cwd=None):
        r = REAL_RUN(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True,
                     text=True, env={"HOME": self.home, "PATH": "/usr/bin:/bin"})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def origin(self, url=URL):
        """(work tree, bare repo) of a one-commit origin that `url` reaches here."""
        name = url.rsplit("/", 1)[1]
        work, bare = Path(self.home) / "origins" / f"{name}-work", Path(self.home) / "origins" / f"{name}-bare.git"
        self.git("init", "-q", "--bare", "-b", "main", str(bare))
        self.git("init", "-q", "-b", "main", str(work))
        self.commit(work, bare, "one")
        with open(Path(self.home) / ".gitconfig", "a") as f:
            f.write(f'[url "{bare.as_uri()}"]\n\tinsteadOf = {url}\n')
        return work, bare

    def commit(self, work, bare, message):
        self.git("commit", "-q", "--allow-empty", "-m", message, cwd=work)
        self.git("push", "-q", str(bare), "main", cwd=work)

    def head(self, repo, ref="HEAD"):
        return self.git("rev-parse", ref, cwd=repo)

    def test_start_prompt_only_on_stdin(self):
        h = Path(self.home)
        clone = h / "scrum-work" / "onewitharts"
        (clone / ".git").mkdir(parents=True)
        (h / ".local" / "bin").mkdir(parents=True)
        claude = h / ".local" / "bin" / "claude"
        claude.write_text('#!/bin/sh\necho $$ > "$HOME/pid"\nprintf "%s|%s|%s|%s|%s|%s|%s|%s|%s\\n" "$CLAUDE_CONFIG_DIR" '
                          '"$CLAUDE_CODE_OAUTH_TOKEN" "${TYPESAFE_API_KEY-unset}" "$SCRUM_PW_CHANNEL" "$SCRUM_CHROME" "$SCRUM_SHOP" '
                          '"$CLAUDE_NOTIFIER_DISABLE" "$CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS" "$PWD" > "$HOME/env"\n'
                          'for a in "$@"; do printf "%s\\n--\\n" "$a"; done > "$HOME/args"\necho session-out\n'
                          'touch "$HOME/done"\n')
        claude.chmod(0o755)
        (h / ".claude-owa").mkdir()
        (h / ".claude-owa" / "oauth-token").write_text("tok-owa-964\n")
        jev_key = h / ".config" / "typesafe" / "key"
        jev_key.parent.mkdir(parents=True)
        jev_key.write_text("tsk-1075\n")

        def start():
            (h / "done").unlink(missing_ok=True)
            self.shop(("nohup claude", LOCAL, ""))
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                pid = shop.start("onewitharts", "964-shop-x", PROMPT, "owa", model="claude-opus-4-5[1m]")
            deadline = time.monotonic() + 10
            while not (h / "done").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual(out.getvalue(), "")
            return pid
        cft = f"{h}/.local/share/chrome-for-testing-150.0.7871.125/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        pid = start()
        self.assertEqual(self.calls, [(START, 60, PROMPT.encode())])
        self.assertFalse([a for a in self.argv if TOKEN in " ".join(a) or "touch" in " ".join(a)])
        self.assertFalse([a for a in self.argv if "tsk-1075" in " ".join(a)])
        self.assertEqual((h / "pid").read_text(), f"{pid}\n")
        self.assertEqual((h / "args").read_text(),
                         "-p\n--\n/trevskills-scrum cloud-job 964-shop-x Build it.\n$(touch pwned) `touch pwned2` "
                         f"{TOKEN}\n--\n--permission-mode\n--\nacceptEdits\n--\n--model\n--\nclaude-opus-4-5[1m]\n--\n")
        self.assertEqual((h / "env").read_text(), f"{h}/.claude-owa|tok-owa-964|tsk-1075|chrome|{cft}|1|1|0|{clone}\n")
        jev_key.unlink()  # no key file: nothing exported, and the session still starts
        pid = start()
        self.assertEqual((h / "pid").read_text(), f"{pid}\n")
        self.assertEqual((h / "env").read_text(), f"{h}/.claude-owa|tok-owa-964|unset|chrome|{cft}|1|1|0|{clone}\n")
        self.assertEqual(sorted(p.name for p in h.rglob("pwned*")), [])
        logs = clone / ".git" / "scrum-shop"
        self.assertEqual(((logs / "964-shop-x.prompt").read_text(), (logs / "964-shop-x.log").read_text()),
                         (PROMPT, "session-out\n"))
        self.assertEqual((stat.S_IMODE(logs.stat().st_mode), stat.S_IMODE((logs / "964-shop-x.prompt").stat().st_mode)),
                         (0o700, 0o600))
        for answer in ((1, "4242\n"), (0, ""), (255, "")):
            with self.subTest(answer=answer):
                self.shop(("nohup claude", *answer))
                self.assertIsNone(shop.start("onewitharts", "964-shop-x", PROMPT, "main"))
                self.assertIn("--permission-mode acceptEdits < /dev/null > ", self.calls[0][0])
                self.assertTrue(self.calls[0][0].startswith(
                    "cd ~/scrum-work/onewitharts && (umask 077 && mkdir -p .git/scrum-shop && cat > "
                    '.git/scrum-shop/964-shop-x.prompt) || exit 1; [ -r "$HOME/.claude/oauth-token" ] && '), self.calls)

    def test_start_refuses_bad_names(self):
        self.shop()
        for project, job, account in (("-x", "964-a", "main"), ("../x", "964-a", "main"), ("a b", "964-a", "main"),
                                      ("x;id", "964-a", "main"), ("onewitharts", "964", "main"),
                                      ("onewitharts", "96-a", "main"), ("onewitharts", "964-A", "main"),
                                      ("onewitharts", "-964-a", "main"), ("onewitharts", "964-a;id", "main"),
                                      ("onewitharts", "964-a\n", "main"), ("onewitharts", "964-a/../x", "main"),
                                      ("onewitharts", "964-a", "other"), ("onewitharts", "964-a", ""),
                                      ("onewitharts", "964-a", "OWA")):
            with self.subTest(project=project, job=job, account=account):
                self.assertIsNone(shop.start(project, job, PROMPT, account))
        self.assertEqual(self.argv, [])

    def test_clone_or_fast_forward(self):
        work, bare = self.origin()
        dest = Path(self.home) / "scrum-work" / "onewitharts"
        self.shop(("scrum-work", LOCAL, ""))
        self.assertTrue(shop.clone("onewitharts", URL)[0])
        self.assertEqual((self.head(dest), self.git("config", "--get", "remote.origin.url", cwd=dest)),
                         (self.head(work), URL))
        self.commit(work, bare, "two")
        self.assertTrue(shop.clone("onewitharts", URL)[0])
        self.assertEqual(self.head(dest), self.head(work))
        self.git("commit", "-q", "--allow-empty", "-m", "shop only", cwd=dest)  # not on origin: no fast-forward
        mine = self.head(dest)
        self.commit(work, bare, "three")
        self.assertFalse(shop.clone("onewitharts", URL)[0])
        self.assertEqual((self.head(dest), self.head(dest, "refs/remotes/origin/main")), (mine, self.head(work)))
        self.assertEqual(self.calls, [(CLONE, 600, None)] * 3)

    def test_clone_returns_to_default_branch(self):
        work, bare = self.origin()
        dest = Path(self.home) / "scrum-work" / "onewitharts"
        self.shop(("scrum-work", LOCAL, ""))
        self.assertTrue(shop.clone("onewitharts", URL)[0])
        self.git("checkout", "-q", "-b", "scrum/081-x", cwd=dest)  # a lilguy job's branch, squash-merged so not an ancestor
        self.git("commit", "-q", "--allow-empty", "-m", "branch work", cwd=dest)
        self.commit(work, bare, "two")
        self.assertTrue(shop.clone("onewitharts", URL)[0])
        self.assertEqual((self.git("symbolic-ref", "--short", "HEAD", cwd=dest), self.head(dest)), ("main", self.head(work)))

    def test_clone_marks_work_folder_trusted(self):
        h = Path(self.home)
        self.origin()
        self.shop(("scrum-work", LOCAL, ""))
        (h / ".claude-owa").mkdir()
        (h / ".claude-owa" / ".claude.json").write_text('{"projects": {"/x": {"a": 1}}}')
        (h / ".claude.json").write_text("{}")
        for _ in range(2):  # idempotent
            self.assertTrue(shop.clone("onewitharts", URL)[0])
        for f in (h / ".claude-owa" / ".claude.json", h / ".claude.json"):
            self.assertTrue(json.loads(f.read_text())["projects"][str(h / "scrum-work" / "onewitharts")]
                            ["hasTrustDialogAccepted"])
            self.assertEqual(f.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads((h / ".claude-owa" / ".claude.json").read_text())["projects"]["/x"], {"a": 1})

    def test_clone_refuses_other_origin_or_url(self):
        self.shop(("scrum-work", LOCAL, ""))
        for url in ("http://github.com/trevorwhecht/onewitharts.git", "https://gitlab.com/trevorwhecht/onewitharts",
                    "https://github.com/trevorwhecht/onewitharts/x", "https://github.com/-x/onewitharts",
                    "git@github.com:trevorwhecht/onewitharts.git", URL + "\n", "https://github.com/trevorwhecht/a;id",
                    "https://github.com/trevorwhecht/..", "https://github.com/trevorwhecht/a b", "--upload-pack=x", ""):
            with self.subTest(url=url):
                self.assertFalse(shop.clone("onewitharts", url)[0])
        for name in ("-x", "../x", "a b", "", "x\n"):
            with self.subTest(name=name):
                self.assertFalse(shop.clone(name, URL)[0])
        self.assertEqual(self.argv, [])
        work, bare = self.origin()
        other = "https://github.com/trevorwhecht/other"  # no .git: accepted
        self.origin(other)
        dest = Path(self.home) / "scrum-work" / "onewitharts"
        self.assertTrue(shop.clone("onewitharts", URL)[0])
        fetched = self.head(dest, "refs/remotes/origin/main")
        self.commit(work, bare, "two")
        self.assertFalse(shop.clone("onewitharts", other)[0])
        self.assertEqual((self.head(dest, "refs/remotes/origin/main"), self.git("config", "--get", "remote.origin.url",
                                                                              cwd=dest)), (fetched, URL))
        self.assertTrue(shop.clone("other", other)[0])
        self.assertEqual(self.git("config", "--get", "remote.origin.url", cwd=Path(self.home) / "scrum-work" / "other"),
                         other)

    def test_clone_reports_git_error_on_dirty_clone(self):
        """Job 1415: clone() says why it failed: git's stderr on one line (cut to 300), `exit <code>` with none, the
        origin it refused, or a refused name or URL with no ssh."""
        self.shop()
        self.assertEqual(shop.clone("-x", URL), (False, "bad project or URL"))
        self.assertEqual(shop.clone("onewitharts", "--upload-pack=x"), (False, "bad project or URL"))
        self.assertEqual(self.argv, [])
        for answer, why in (((3, ""), "origin is not https://github.com/trevorwhecht/onewitharts.git"),
                            ((128, "fatal:   one\n\ttwo  "), "fatal: one two remote-noise-962"),
                            ((1, "x" * 400), "x" * 300)):
            with self.subTest(answer=answer):
                self.shop(("scrum-work", *answer))
                self.assertEqual(shop.clone("onewitharts", URL), (False, why))
        with mock.patch.object(shop, "run", return_value=subprocess.CompletedProcess([], 255, "", " \n")):
            self.assertEqual(shop.clone("onewitharts", URL), (False, "exit 255"))
        work, bare = self.origin()
        (work / "a.txt").write_text("one\n")
        self.git("add", "a.txt", cwd=work)
        self.commit(work, bare, "add a")
        dest = Path(self.home) / "scrum-work" / "onewitharts"
        self.shop(("scrum-work", LOCAL, ""))
        self.assertEqual(shop.clone("onewitharts", URL), (True, ""))
        (dest / "a.txt").write_text("shop edit\n")
        mine = self.head(dest)
        (work / "a.txt").write_text("two\n")
        self.git("add", "a.txt", cwd=work)
        self.commit(work, bare, "change a")
        ok, why = shop.clone("onewitharts", URL)
        self.assertFalse(ok)
        self.assertIn("would be overwritten", why)
        self.assertTrue(why.startswith("error: "), why)
        self.assertNotIn("\n", why)
        self.assertLessEqual(len(why), 300)
        self.assertEqual(((dest / "a.txt").read_text(), self.head(dest)), ("shop edit\n", mine))

    def test_stash_dirty_sets_tracked_changes_aside(self):
        """Job 1415: stash_dirty() sets the clone's modified tracked files aside with one git stash push named for the
        job, returns their paths, leaves untracked files, and the next clone() fast-forwards."""
        self.shop()
        for project, job in (("-x", "1415-a"), ("../x", "1415-a"), ("onewitharts", "1415"), ("onewitharts", "1415-a;id"),
                             ("onewitharts", "-1415-a"), ("onewitharts", "1415-a\n")):
            with self.subTest(project=project, job=job):
                self.assertIsNone(shop.stash_dirty(project, job))
        self.assertEqual(self.argv, [])
        self.shop(("scrum-work", LOCAL, ""))
        self.assertIsNone(shop.stash_dirty("onewitharts", "1415-a"), "no clone there")
        work, bare = self.origin()
        for name in ("a.txt", "b.txt"):
            (work / name).write_text("one\n")
        self.git("add", "a.txt", "b.txt", cwd=work)
        self.commit(work, bare, "add a, b")
        dest = Path(self.home) / "scrum-work" / "onewitharts"
        self.assertEqual(shop.clone("onewitharts", URL), (True, ""))
        self.calls.clear()
        self.assertEqual(shop.stash_dirty("onewitharts", "1415-a"), [], "a clean clone")
        self.assertEqual(self.git("stash", "list", cwd=dest), "")
        self.assertEqual(len(self.calls), 1)
        self.assertNotRegex(self.calls[0][0], r"reset|clean|checkout|drop|stash -u|--include-untracked|pop|apply")
        (dest / "a.txt").write_text("shop edit\n")
        (dest / "b.txt").write_text("shop edit\n")
        (dest / "new.txt").write_text("untracked\n")
        (work / "a.txt").write_text("two\n")
        self.git("add", "a.txt", cwd=work)
        self.commit(work, bare, "change a")
        self.assertFalse(shop.clone("onewitharts", URL)[0])
        before = time.time()
        self.assertEqual(shop.stash_dirty("onewitharts", "1415-a"), ["a.txt", "b.txt"])
        stashes = self.git("stash", "list", "--format=%s", cwd=dest).splitlines()
        self.assertEqual(len(stashes), 1, stashes)
        self.assertRegex(stashes[0], r"scrum 1415-a: set aside by shop dispatch \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        stamp = datetime.datetime.strptime(stashes[0][-20:], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        self.assertLessEqual(abs(stamp.timestamp() - before), 5)
        self.assertEqual((dest / "new.txt").read_text(), "untracked\n", "untracked files stay")
        self.assertEqual(shop.clone("onewitharts", URL), (True, ""))
        self.assertEqual(((dest / "a.txt").read_text(), (dest / "b.txt").read_text(), self.head(dest)),
                         ("two\n", "one\n", self.head(work)))
        self.assertEqual(len(self.git("stash", "list", cwd=dest).splitlines()), 1, "never dropped")
        with mock.patch.object(shop, "run", return_value=subprocess.CompletedProcess([], 0, "motd\nSTASHED\nx y.ts\n", "")):
            self.assertEqual(shop.stash_dirty("onewitharts", "1415-a"), ["x y.ts"], "shell startup output is skipped")
        for r in (subprocess.CompletedProcess([], 1, "STASHED\na\n", ""), subprocess.CompletedProcess([], 0, "a\n", "")):
            with mock.patch.object(shop, "run", return_value=r):
                self.assertIsNone(shop.stash_dirty("onewitharts", "1415-a"))

    def test_ended_states(self):
        h = Path(self.home)
        logs = h / "scrum-work" / "onewitharts" / ".git" / "scrum-shop"
        logs.mkdir(parents=True)
        self.shop(("sysctl", 255, ""))
        self.assertIsNone(shop.ended("onewitharts", "964-shop-x", 4242))
        self.assertEqual([c[0] for c in self.calls], [shop.PROBE_CMD])
        shop._cache.clear()
        self.shop(("ps -p 4242", 0, ""), ("ps -p", LOCAL, ""), *DONE)
        self.assertEqual((shop.ended("onewitharts", "964-shop-x", 4242), self.calls[1:]),
                         (NOISE, [(ENDED, 60, None)]))
        # `ps -o command=` of the first reads "/bin/sh -c sleep 30; : claude"; `; :` keeps sh from exec'ing sleep
        procs = {name: subprocess.Popen(argv, start_new_session=True)
                 for name, argv in (("claude", ["/bin/sh", "-c", "sleep 30; :", "claude"]), ("other", ["/bin/sleep", "30"]))}
        for proc in procs.values():
            self.addCleanup(proc.wait)
            self.addCleanup(os.killpg, proc.pid, 9)
        gone = subprocess.Popen(["/usr/bin/true"])
        gone.wait()
        self.assertIsNone(shop.ended("onewitharts", "964-shop-x", procs["claude"].pid))
        self.assertEqual(shop.ended("onewitharts", "964-shop-x", gone.pid), "")
        (logs / "964-shop-x.log").write_bytes(b"x" * 100 + b"y" * 8192)
        self.assertEqual(shop.ended("onewitharts", "964-shop-x", gone.pid), "y" * 8192)
        self.assertEqual(shop.ended("onewitharts", "964-shop-x", procs["other"].pid), "y" * 8192)
        self.shop(("ps -p", 255, ""), *DONE)
        self.assertIsNone(shop.ended("onewitharts", "964-shop-x", gone.pid))
        self.shop(*DONE)
        for project, job in (("-x", "964-shop-x"), ("onewitharts", "964-a\n"), ("onewitharts", "../x")):
            self.assertIsNone(shop.ended(project, job, 4242))
        self.assertEqual(self.argv, [])


RECLAIM = ('d="$HOME/scrum-work/onewitharts"; if [ ! -d "$d/.git" ]; then echo RECLAIMED 0; exit 0; fi; cd "$d" || exit 1;'
           ' n=0; while read -r j pid; do w=".claude/worktrees/scrum-$j"; if [ ! -d "$w" ] || [ -L "$w" ]; then continue; fi;'
           ' if [ "$pid" -gt 0 ] && ps -p "$pid" -o command= | grep -q claude; then continue; fi;'
           ' git worktree remove --force -- "$w" > /dev/null 2>&1 && n=$((n + 1)); done; git worktree prune; echo RECLAIMED $n')


class ReclaimTest(SetupCase):
    """Job 1550: reclaim() removes finished jobs' worktrees under the shop clone's .claude/worktrees/ in one ssh call."""

    def git(self, *args, cwd=None):
        r = REAL_RUN(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True,
                     text=True, env={"HOME": self.home, "PATH": "/usr/bin:/bin"})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_command_stdin_and_count(self):
        run = self.fake_run(0, "shell noise\nRECLAIMED 2\n")
        self.assertEqual(shop.reclaim("onewitharts", [("964-a", 4242), ("965-b", 0), ("-966", 1), ("967-c;id", 2),
                                                      ("968-d\n", 3)]), 2)
        self.assertEqual(run.call_args_list, [mock.call(RECLAIM, 600, input="964-a 4242\n965-b 0\n", alias="shopmac")])
        run.reset_mock()
        self.assertEqual(shop.reclaim("onewitharts", [("964-a", 0)], alias="mac2"), 2)
        self.assertEqual(run.call_args.kwargs["alias"], "mac2")
        for project in ("-x", "../x", "a b", "x;id"):
            with self.subTest(project=project):
                run.reset_mock()
                self.assertIsNone(shop.reclaim(project, [("964-a", 0)]))
                run.assert_not_called()
        for answer in ((1, "RECLAIMED 2\n"), (124, ""), (0, "no count\n")):
            with self.subTest(answer=answer):
                run.return_value = subprocess.CompletedProcess([], *answer, "")
                self.assertIsNone(shop.reclaim("onewitharts", [("964-a", 0)]))

    def test_removes_only_ended_worktrees_and_keeps_branches(self):
        h = Path(self.home)
        self.shop(("RECLAIMED", LOCAL, ""))
        self.assertEqual(shop.reclaim("onewitharts", [("964-a", 0)]), 0, "no clone there")
        clone = h / "scrum-work" / "onewitharts"
        self.git("init", "-q", "-b", "main", str(clone))
        self.git("commit", "-q", "--allow-empty", "-m", "one", cwd=clone)
        wts = clone / ".claude" / "worktrees"
        for j in ("964-a", "965-b", "966-c"):
            self.git("worktree", "add", "-q", "-b", f"scrum/{j}", str(wts / f"scrum-{j}"), cwd=clone)
        outside = h / "elsewhere"
        outside.mkdir()
        (wts / "scrum-967-d").symlink_to(outside)
        live = subprocess.Popen(["/bin/sh", "-c", "sleep 30; :", "claude"], start_new_session=True)
        self.addCleanup(live.wait)
        self.addCleanup(os.killpg, live.pid, 9)
        self.assertEqual(shop.reclaim("onewitharts", [("964-a", 0), ("965-b", live.pid), ("967-d", 0), ("968-e", 0)]), 1)
        self.assertEqual(sorted(p.name for p in wts.iterdir()), ["scrum-965-b", "scrum-966-c", "scrum-967-d"])
        self.assertTrue(outside.is_dir())
        self.assertIn("scrum/964-a", self.git("branch", "--list", "scrum/964-a", cwd=clone), "branches stay")


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
                       "60 s", "300 s", "prints nothing and raises nothing", "`python3 shop.py probe`",
                       "`workers.txt`", "`worker=<alias>`", "**Runs on.**", "shop-room.json"):
            self.assertIn(phrase, text, phrase)
        self.assertEqual([line for line in text.splitlines() if line.startswith("## ")],
                         ["## Transport and probe", "## Setup", "## Ready", "## Env copy", "## E2E channel",
                          "## MD sync", "## Dispatch"])
        setup = text[text.index("## Setup"):text.index("## Ready")]
        self.assertIn("gh always uses file storage (mode 600) because the shop's login keychain is locked over SSH",
                      setup)
        chrome = setup[setup.index("- **chrome.**"):setup.index("- **jev key.**")]  # job 1227
        for phrase in (shop.CFT_SHA256, "`~/.local/share/chrome-for-testing-150.0.7871.125/`", "`SCRUM_CHROME`",
                       "a checksum mismatch installs nothing", "not in `OPTIONAL_STEPS`"):
            self.assertIn(phrase, chrome, phrase)
        self.assertIn("a non-blank `SCRUM_CHROME`", text[text.index("## E2E channel"):text.index("## MD sync")])
        pool = text[text.index("- **Pool.**"):]
        self.assertIn("A hand start (Run now, Start now, a chat `board.spawn` start) that `board.hand_hold` holds on this "
                      "Mac is such a queued `start` launch (`board.queue_start`, job 1312).", pool.split("\n")[0])
        self.assertIn("`SCRUM_PW_CHANNEL=chrome`, `SCRUM_CHROME` (setup's **chrome** binary)", text)
        self.assertIn("an account or `codex login` that is `not ready` never fails it", setup)
        self.assertLess(setup.index("- **account main, account owa.**"), setup.index("- **codex.**"))
        self.assertLess(setup.index("- **codex.**"), setup.index("- **ruff.**"))
        codex = setup[setup.index("- **codex.**"):setup.index("- **ruff.**")]  # job 1245
        for phrase in ("- **codex login.**", "`CODEX_VERSION`", '`--prefix "$HOME/.local"`', "`~/.codex/access-token`",
                       "`codex login --with-access-token`", "`OPTIONAL_STEPS`"):
            self.assertIn(phrase, codex, phrase)
        jev = setup[setup.index("- **jev key.**"):]  # the last step
        for phrase in ("`[ -s ~/.config/typesafe/key ]`", "no Keychain read here", "goes on stdin to",
                       "so the file is mode 600", 'export TYPESAFE_API_KEY="$(cat F)"'):
            self.assertIn(phrase, jev, phrase)
        copy = text[text.index("## Env copy"):text.index("## E2E channel")]
        for phrase in ("`profile_copy(project, repo)`", "`scrum/` and `.claude/worktrees/`", "`- Render auth:`",
                       "`posixpath.normpath(\".claude/worktrees/scrum-x/\" + <path>)`", "is not under `.claude/`",
                       "It returns `copied` when", "`none` (no `scrum/project.md` here; no ssh)",
                       "one more 60 s call per Conventions file"):
            self.assertIn(phrase, copy, phrase)
        self.assertLess(copy.index("- **Conventions.**"), copy.index("- **Result.**"))
        conventions = copy[copy.index("- **Conventions.**"):copy.index("- **Result.**")]  # job 1245
        for phrase in ("`- Conventions to read:`", "`CONVENTIONS_DIRS`", "`[A-Za-z0-9._/-]+`",
                       "outside the repo, both as given and as its realpath", "replaced by the file, not written through"):
            self.assertIn(phrase, conventions, phrase)
        self.assertIn("every Conventions call", copy[copy.index("- **Result.**"):])
        self.assertIn("`clone(<repo folder>, <origin URL>)`, `env_copy()` (copied or none), `profile_copy()` (copied or "
                      "none) and `start()`", text[text.index("## Dispatch"):])
        self.assertIn("creates `cooldown-<alias>` beside the cool-down flag", text[text.index("## Dispatch"):],
                      "each worker's own cool-down (job 1185)")
        self.assertIn("On a shop run (`SCRUM_SHOP` set), dispatch has already written `$F/project.md` from the main "
                      "Mac's: keep it, and still run first-run setup steps 1–3, which skip what is already there.",
                      (SKILL / "lanes" / "cloud.md").read_text())
        sync = text[text.index("## MD sync"):text.index("## Dispatch")]
        for phrase in ("`python3 shop.py md-sync`", "--ff-only", "`~/.md-sync-cleanup-done`",
                       "`~/md-sync-backup-<YYYY-MM-DD-HHMMSS>`", "`memory_key()`", "`Edit(/{home}/.claude/rules/**)`",
                       "`CLAUDE_CODE_DISABLE_AUTO_MEMORY`", "`~/.claude/skills/<name>`"):
            self.assertIn(phrase, sync, phrase)

    def test_channel_documented(self):
        newjob = (SKILL / "lanes" / "newjob.md").read_text()
        rule = newjob[newjob.index("**Debug exception:**"):newjob.index("When **E2E lanes** allows it")]
        self.assertIn('With `SCRUM_PW_CHANNEL` set, the debug exception\'s `npx playwright test` also takes `--config '
                      '"$HOME/.claude/skills/trevskills-e2e/channel.config.mjs"`.', rule)
        e2e = (ROOT / "skills" / "trevskills-e2e" / "SKILL.md").read_text()
        after_inputs = e2e[e2e.index("\nInputs:"):e2e.index("**The E2E/test directory**")]
        for text in (rule, after_inputs):
            self.assertIn("channel.config.mjs", text)
            self.assertIn("SCRUM_PW_CHANNEL", text)


if __name__ == "__main__":
    unittest.main()
