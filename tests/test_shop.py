import ast, contextlib, hashlib, io, json, os, shutil, stat, subprocess, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "trevskills-scrum"
WRAPPER = ROOT / "skills" / "trevskills-e2e" / "channel.config.mjs"
sys.path.insert(0, str(SKILL))
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
        shop._cache = shop._ready = None
        self.addCleanup(setattr, shop, "_cache", None)
        self.addCleanup(setattr, shop, "_ready", None)

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


TOKEN = "gho_FAKE962TOKEN"
ENV_LINE = b"SECRET_962=abc962xyz\n"
NOISE = "remote-noise-962"  # every faked remote stdout/stderr carries it; no setup output may
LOCAL = "local"  # an answer that runs the remote command in a local sh under self.home, as the shop would
HAVE_ALL = "{ 1.00 0.50 0.25 }\n4\n/u/.local/bin/node\n/u/.local/bin/gh\n/u/.local/bin/claude\n"
DONE = (("sysctl", 0, HAVE_ALL), ("gh auth status", 0, ""),
        ("credential.https://github.com.helper", 0, "\n!/u/.local/bin/gh auth git-credential\n"),
        ('mkdir -p "$HOME/.claude-owa"', 0, ""), ("python3 -", 0, "same\n"), ("claude -p", 0, "ok\n"))
ALL_OK = ["node: ok", "gh: ok", "gh login: ok", "gh git: ok", "owa links: ok", "permissions: ok", "account main: ok",
          "account owa: ok"]
GH_LOGIN = ("gh auth login --hostname github.com --git-protocol https --with-token --insecure-storage"
            " && chmod 600 ~/.config/gh/hosts.yml")
CHECK = "claude -p 'Reply with the single word ok' --model haiku --max-turns 1"
HINT = " (run claude setup-token in the shop GUI)"


class SetupCase(ShopCase):
    def setUp(self):
        super().setUp()
        self.home = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)

    def shop(self, *answers, token=(0, TOKEN + "\n")):
        """Fake ssh and this Mac's `gh auth token` under subprocess.run, so run() itself is exercised. Each remote
        command gets the first answer (key, rc, stdout) whose key it contains, else exit 0; rc LOCAL runs it here
        under self.home, an exception rc is raised. self.calls holds every (remote command, timeout, input)."""
        self.calls, self.argv = [], []

        def fake(argv, **kw):
            self.argv.append(list(argv))
            if argv[0] == "gh":
                self.assertEqual((argv, kw), (["gh", "auth", "token"], {"capture_output": True, "text": True,
                                                                         "timeout": 60}))
                if isinstance(token, BaseException):
                    raise token
                return subprocess.CompletedProcess(argv, token[0], token[1], "")
            self.assertEqual(argv[:6], ARGV)
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
        shop._cache = (shop.time.monotonic(), {"up": True, "load": 1.0, "tools": {t: True for t in shop.TOOLS}})
        self.shop(("sysctl", 255, ""))
        self.assertEqual(self.setup_out(), ({"shop": "failed"}, ["shop: down"]))
        self.assertEqual([c[0] for c in self.calls], [shop.PROBE_CMD])  # the stale up cache was dropped
        self.assertEqual(self.setup_out(cli=True), (1, ["shop: down"]))
        self.assertEqual(len(self.calls), 2)

    def test_output_lines_and_exit_code(self):
        answers = (("sysctl", 0, "{ 1.00 0.50 0.25 }\n4\n/u/.local/bin/gh\n/u/.local/bin/claude\n"),
                   ("nodejs.org", 0, ""), (shop.GIT_HELPER, 1, ""), ("setup-git", 1, ""),
                   ('mkdir -p "$HOME/.claude-owa"', 0, "agents\nskills\n"), ("python3 -", 0, "changed\n"),
                   (".claude-owa/oauth-token", 3, ""), ("claude -p", 0, "Ok.\n"), ("gh auth status", 0, ""))
        self.shop(*answers)
        got, lines = self.setup_out()
        self.assertEqual(lines, ["node: ok (changed)", "gh: ok", "gh login: ok", "gh git: failed (exit 1)",
                                 "owa links: ok (changed)", "permissions: ok (changed)", "account main: ok",
                                 "account owa: not ready (run claude setup-token in the shop GUI)"])
        self.assertEqual(got, {"node": "changed", "gh": "ok", "gh login": "ok", "gh git": "failed",
                               "owa links": "changed", "permissions": "changed", "account main": "ok",
                               "account owa": "not ready"})
        self.assertEqual(list(got), ["node", "gh", "gh login", "gh git", "owa links", "permissions", "account main",
                                     "account owa"])
        self.assertEqual([(c[0].split()[0], c[1]) for c in self.calls[1:]],
                         [("d=$(mktemp", 600), ("gh", 60), ("git", 60), ("gh", 60), ("mkdir", 60), ("ln", 60),
                          ("python3", 60), ("[", 120), ("[", 120)])
        self.assertEqual(self.setup_out(cli=True)[0], 1)
        self.shop(("setup-git", 0, ""), *answers)
        self.assertEqual(self.setup_out(cli=True), (0, [
            "node: ok (changed)", "gh: ok", "gh login: ok", "gh git: ok (changed)", "owa links: ok (changed)",
            "permissions: ok (changed)", "account main: ok",
            "account owa: not ready (run claude setup-token in the shop GUI)"]))

    def test_second_run_unchanged(self):
        self.shop(*DONE)
        got, lines = self.setup_out()
        self.assertEqual(lines, ALL_OK)
        self.assertEqual(set(got.values()), {"ok"})
        for key in ("curl", "gh auth login", "ln -s", "setup-git", 'mkdir -p "$HOME/.local'):
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

    @unittest.skipUnless(shutil.which("shasum") and shutil.which("unzip"), "needs shasum and unzip")
    def test_checksum_checked_before_install(self):
        """Run both install commands in a local sh with a fake curl: a wrong checksum installs nothing, the right one
        installs, and the temp dir is gone either way."""
        work = Path(self.home)
        (work / "bin").mkdir()
        curl = work / "bin" / "curl"
        curl.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done\n'
                        'cp "$FAKE_DOWNLOAD" "$out"\n')
        curl.chmod(0o755)
        script = b"#!/bin/sh\necho fake-962\n"
        tgz, gz = work / "node.tgz", work / "gh.zip"
        with tarfile.open(tgz, "w:gz") as tar:
            for b in ("node", "npm", "npx"):
                info = tarfile.TarInfo(f"node-v24.22.3-darwin-x64/bin/{b}")
                info.size, info.mode = len(script), 0o755
                tar.addfile(info, io.BytesIO(script))
        with zipfile.ZipFile(gz, "w") as z:
            info = zipfile.ZipInfo("gh_2.103.3_macOS_amd64/bin/gh")
            info.external_attr = 0o100755 << 16
            z.writestr(info, script)
        for name, cmd, fixture, sha in (("node", shop.NODE_INSTALL, tgz, shop.NODE_SHA256),
                                        ("gh", shop.GH_INSTALL, gz, shop.GH_SHA256)):
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
        self.assertEqual(self.setup_out()[1][4], "owa links: ok (changed)")
        self.assertEqual(self.cmds("ln -s")[0][0], 'ln -s "$HOME/.claude/CLAUDE.md" "$HOME/.claude-owa/CLAUDE.md" && '
                         'ln -s "$HOME/.claude/rules" "$HOME/.claude-owa/rules" && ln -s "$HOME/.claude/settings.json" '
                         '"$HOME/.claude-owa/settings.json"')
        links = {p.name: os.readlink(p) for p in owa.iterdir() if p.is_symlink()}
        self.assertEqual(links, {"agents": f"{h}/.claude/agents", "skills": f"{h}/gone",
                                 "CLAUDE.md": f"{h}/.claude/CLAUDE.md", "rules": f"{h}/.claude/rules",
                                 "settings.json": f"{h}/.claude/settings.json"})
        self.assertEqual(((owa / "commands").read_text(), (owa / ".claude.json").read_text(),
                          (owa / ".credentials.json").read_text()), ("a file\n", '{"oauthAccount": 1}\n', "{}\n"))
        self.assertEqual(self.setup_out()[1][4], "owa links: ok")
        self.assertEqual(len(self.cmds("ln -s")), 1)  # the second run linked nothing
        shutil.rmtree(owa)
        self.shop(('mkdir -p "$HOME/.claude-owa"', LOCAL, ""), ("ln -s", LOCAL, ""), *DONE)
        self.assertEqual(self.setup_out()[1][4], "owa links: ok (changed)")  # mkdir -p made it first
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
        self.assertEqual(self.setup_out()[1][6:], ["account main: not ready (run claude setup-token in the shop GUI)",
                                                   "account owa: ok"])
        self.assertEqual((h / "calls").read_text(),
                         f"{h}/.claude-owa|tok-owa-962|-p Reply with the single word ok --model haiku --max-turns 1\n")
        (h / ".claude").mkdir()
        (h / ".claude" / "oauth-token").write_text("tok-main-962\n")
        self.assertEqual(self.setup_out()[1][6:], ["account main: ok", "account owa: ok"])
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
                self.assertEqual(lines[6:], ["account main: not ready", owa_line])


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
        self.assertEqual(json.loads(self.file.read_text()), {"permissions": {
            "allow": ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "WebSearch", "WebFetch", "Skill",
                      f"Read(/{h}/**)", "Read(//tmp/**)", "Read(//private/tmp/**)", f"Edit(/{h}/.claude/**/*.md)",
                      f"Edit(/{h}/.claude-owa/**/*.md)"],
            "deny": ["Bash(git reset:*)", "Bash(git rebase:*)", "Bash(git push --force:*)",
                     "Bash(git push --force-with-lease:*)", "Bash(git push -f:*)", "Bash(prisma migrate reset:*)",
                     "Bash(npx prisma migrate reset:*)"],
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

    def test_keeps_other_keys(self):
        other = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo é"}]}]},
                 "statusLine": {"type": "command", "command": "~/s.sh"}, "env": {"A": "1"}, "theme": "dark"}
        self.file.parent.mkdir()
        self.file.write_text(json.dumps({**other, "permissions": {"defaultMode": "acceptEdits", "allow": ["Read"]}},
                                        indent=2, ensure_ascii=False) + "\n")
        before = self.file.read_text()
        self.assertEqual(self.merge().stdout, "changed\n")
        after = self.file.read_text()
        for key, value in other.items():  # each key's own lines, as Claude Code writes them, are in both files
            block = json.dumps({key: value}, indent=2, ensure_ascii=False)[2:-2]
            self.assertIn(block, before, key)
            self.assertIn(block, after, key)
        self.assertIn('    "defaultMode": "acceptEdits",\n', after)
        self.assertIn('"command": "echo é"', after)

    def test_malformed_json_not_written(self):
        self.file.parent.mkdir()
        for bad in ("{ not json", '{"permissions": []}', '{"permissions": {"allow": "Bash"}}', "[]", ""):
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
                shop._cache = shop._ready = None
                self.shop(*extra, (".claude-owa/oauth-token", 3, ""), *DONE)
                self.assertEqual(self.ready(), want)

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

    def load(self, files, channel="chrome"):
        for name, text in files.items():
            Path(self.repo, name).write_text(text)
        env = {k: v for k, v in os.environ.items() if k != "SCRUM_PW_CHANNEL"}
        if channel is not None:
            env["SCRUM_PW_CHANNEL"] = channel
        return REAL_RUN(["node", "--input-type=module", "-e",
                         "const m = await import(process.argv[1]); console.log(JSON.stringify(m.default))",
                         WRAPPER.as_uri()], cwd=self.repo, env=env, capture_output=True, text=True)

    def config(self, files, channel="chrome"):
        r = self.load(files, channel)
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
        self.assertEqual([line for line in text.splitlines() if line.startswith("## ")],
                         ["## Transport and probe", "## Setup", "## Ready", "## Env copy", "## E2E channel"])
        setup = text[text.index("## Setup"):text.index("## Ready")]
        self.assertIn("gh always uses file storage (mode 600) because the shop's login keychain is locked over SSH",
                      setup)

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
