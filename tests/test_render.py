"""render.py: the shared review render (job 652). Headless Chrome over a stdlib CDP websocket client."""
import io, json, os, signal, subprocess, sys, tempfile, threading, time, unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_SWAP_PCT"] = "0"  # no swap: main()'s hold (job 1227) never reads this machine's swap
os.environ["SCRUM_CPU_LOAD_PCT"] = "0"  # no load: main()'s hold never waits on this machine's load
os.environ["SCRUM_VM_PRESSURE"] = "1"  # kernel memory pressure normal: main()'s hold never runs sysctl
os.environ["SCRUM_CLOUDINARY_CACHE"] = tempfile.mkdtemp(prefix="render-cld-")  # never the real cache
import render  # noqa: E402

PAGE = b"<!doctype html><title>t</title><h1>hi</h1><script>console.error('boom')</script>"
SENTINEL = "s3ntinel-cookie-value-652"
FETCH_PAGE = b"<!doctype html><title>f</title><script>fetch('/slow').then(() => console.error('fetched'))</script>"
HUNG_PAGE = b"<!doctype html><title>h</title><script>fetch('/hang')</script>"
MARKERS = {"role": '<div role="status">Loading</div>', "busy": '<div aria-busy="true">x</div>',
           "text": "<p>Loading...</p>"}
LOADING_JS = "<script>setTimeout(() => {{ document.querySelector('{sel}').remove(); console.error('ready') }}, 2000)</script>"
LOADING_PAGES = {f"/load-{k}": (f"<!doctype html><title>l</title>{m}" + LOADING_JS.format(sel=sel)).encode()
                 for (k, m), sel in zip(MARKERS.items(), ("div", "div", "p"))}
LOADING_PAGES["/load-skeleton"] = ("<!doctype html><title>l</title><div class=\"animate-pulse\">x</div>"
                                   + LOADING_JS.format(sel="div")).encode()
LOADING_PAGES["/load-never"] = f"<!doctype html><title>l</title>{MARKERS['role']}".encode()
LOADING_PAGES["/load-empty"] = ("<!doctype html><title>l</title><div role=\"status\"></div>"
                                + LOADING_JS.format(sel="div")).encode()
LOADING_PAGES["/status-permanent"] = b'<!doctype html><title>s</title><div role="status">Payment overdue</div>'
LOADING_PAGES["/status-hidden"] = b'<!doctype html><title>s</title><div role="status" style="display:none">Loading</div>'
CLICK_PAGES = {
    "/click-modal": b"<!doctype html><title>c</title><button id=open onclick=\"fetch('/hit-open');"
                    b"document.getElementById('modal').style.display='block'\">Open</button>"
                    b"<div id=modal style=\"display:none;position:fixed;inset:0;background:red\">Modal</div>",
    "/click-two": b"<!doctype html><title>c</title><button id=first onclick=\"fetch('/hit-first');"
                  b"document.body.insertAdjacentHTML('beforeend','<button id=second onclick=&quot;fetch(\\'/hit-second\\')"
                  b"&quot;>Two</button>')\">One</button>",
}
REDIRECTS = {"/q?view=leads": "/q?view=orders", "/a": "/other", "/t/": "/t"}


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.cookies.append(self.headers.get("Cookie", ""))
        if self.path in REDIRECTS:
            self.send_response(302)
            self.send_header("Location", REDIRECTS[self.path])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/hit-"):
            self.server.hits.append(self.path)
        if self.path == "/slow":
            time.sleep(2)
        elif self.path == "/hang":
            self.server.release.wait(90)  # held open until the test ends
            self.server.hangs_ended += 1
            return
        body = {"/fetch": FETCH_PAGE, "/hung": HUNG_PAGE, **LOADING_PAGES, **CLICK_PAGES}.get(self.path, PAGE)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


REAL_REAP = render.reap


def run_main(argv, env=None):
    """render.main(argv); (exit code, stdout, stderr). render.reap returns [] unless a test patched it already, so no
    test reads this machine's real process list (job 1451)."""
    out, err = io.StringIO(), io.StringIO()
    unpatched = render.reap is REAL_REAP
    reap = mock.patch.object(render, "reap", return_value=[]) if unpatched else nullcontext()
    with mock.patch.dict(os.environ, env or {}), reap, redirect_stdout(out), redirect_stderr(err):
        code = render.main(argv)
    return code, out.getvalue(), err.getvalue()


def gone(pid, within):
    """True once pid no longer exists, polled up to `within` seconds."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.05)
    return False


def kill_quietly(*pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


CHILD = ("import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); "
         "time.sleep(120)")
# The fake Chrome leader: argv[1] "exit" exits once its child is up, "wait" sleeps (and dies on SIGTERM), "orphan"
# starts its own session, ignores SIGTERM and writes "<pid> <child pid>" to argv[2]. The child ignores SIGTERM.
LEADER = f"""import os, signal, subprocess, sys, time
if sys.argv[1] == "orphan":
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", {CHILD!r}], stdout=subprocess.PIPE)
child.stdout.readline()
if sys.argv[1] == "orphan":
    tmp = sys.argv[2] + ".tmp"
    open(tmp, "w").write(f"{{os.getpid()}} {{child.pid}}")
    os.replace(tmp, sys.argv[2])
else:
    print(child.pid, flush=True)
if sys.argv[1] == "exit":
    os._exit(0)
time.sleep(120)
"""


class RenderCloudinaryCacheTest(unittest.TestCase):
    URL = "https://res.cloudinary.com/demo/v1/mockup.png"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="render-cld-test-")
        p = mock.patch.dict(os.environ, {"SCRUM_CLOUDINARY_CACHE": self.dir})
        p.start()
        self.addCleanup(p.stop)

    def test_miss_downloads_once_then_hits(self):
        calls = []

        def fetch(url):
            calls.append(url)
            return b"PNGDATA", "image/png"
        self.assertEqual(render.cached_image(self.URL, fetch), (b"PNGDATA", "image/png"))
        self.assertEqual(render.cached_image(self.URL, fetch), (b"PNGDATA", "image/png"))
        self.assertEqual(calls, [self.URL])
        self.assertEqual(len(list(Path(self.dir).glob("*.body"))), 1)
        self.assertEqual(len(list(Path(self.dir).glob("*.json"))), 1)

    def test_non_200_or_error_is_not_stored(self):
        self.assertIsNone(render.cached_image(self.URL, lambda u: (None, "")))
        self.assertIsNone(render.cached_image(self.URL, mock.Mock(side_effect=OSError("down"))))
        self.assertEqual(list(Path(self.dir).iterdir()), [])

    def test_paused_request_is_fulfilled_from_cache(self):
        render.cached_image(self.URL, lambda u: (b"abc", "image/png"))
        cdp = render.CDP(mock.Mock())
        msg = {"method": "Fetch.requestPaused", "params": {"requestId": "r1", "request": {"url": self.URL, "method": "GET"}}}
        self.assertTrue(cdp._paused(msg))
        sent = json.loads(cdp.ws.send.call_args[0][0])
        self.assertEqual(sent["method"], "Fetch.fulfillRequest")
        self.assertEqual(sent["params"]["responseCode"], 200)
        self.assertEqual(cdp.n, 0)  # a Fetch reply never takes a call() id
        self.assertFalse(cdp._paused({"method": "Page.loadEventFired"}))


class RenderKillTest(unittest.TestCase):
    """Job 1451: _kill stops Chrome's whole process group, even when the leader went first."""

    def leader(self, mode):
        proc = subprocess.Popen([sys.executable, "-c", LEADER, mode], stdout=subprocess.PIPE, text=True,
                                start_new_session=True)
        child = int(proc.stdout.readline())
        proc.stdout.close()
        self.addCleanup(kill_quietly, proc.pid, child)
        self.addCleanup(lambda: proc.poll() is None and proc.wait(5))
        return proc, child

    def test_kill_stops_term_ignoring_child(self):
        proc, child = self.leader("wait")
        render._kill(proc)
        self.assertIsNotNone(proc.poll(), "the leader is stopped")
        self.assertTrue(gone(child, 5), "the SIGTERM-ignoring child in Chrome's group is gone")

    def test_kill_after_leader_exited(self):
        proc, child = self.leader("exit")
        proc.wait(30)
        render._kill(proc)
        self.assertTrue(gone(child, 5), "the child left in Chrome's group is gone")

    def test_kill_terms_then_kills_the_group(self):
        proc = mock.Mock(pid=4321)
        proc.poll.return_value = None
        with mock.patch.object(render.os, "killpg", side_effect=[None, ProcessLookupError()]) as killpg:
            render._kill(proc)
        self.assertEqual(killpg.call_args_list, [mock.call(4321, signal.SIGTERM), mock.call(4321, signal.SIGKILL)])
        proc.wait.assert_any_call(5)

    def test_kill_none_is_noop(self):
        with mock.patch.object(render.os, "killpg", side_effect=AssertionError("signalled")):
            self.assertIsNone(render._kill(None))

    def test_main_handles_sighup(self):
        before, seen = signal.getsignal(signal.SIGHUP), []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(render.buildlock, "board_module", return_value=None), \
                mock.patch.object(render, "render",
                                  side_effect=lambda *a: seen.append(signal.getsignal(signal.SIGHUP)) or {"pages": []}):
            code, _, _ = run_main(["http://127.0.0.1:1", str(Path(tmp) / "out"), "/"])
        self.assertEqual(code, 0)
        self.assertEqual(len(seen), 1)
        self.assertNotIn(seen[0], (signal.SIG_DFL, signal.SIG_IGN, None))
        self.assertIs(signal.getsignal(signal.SIGHUP), before)
        with self.assertRaises(SystemExit) as cm:
            seen[0](signal.SIGHUP, None)
        self.assertEqual(cm.exception.code, 1)


class RenderReapTest(unittest.TestCase):
    """Job 1451: reap() stops each scrum-render Chrome whose render.py is gone (ppid 1) and removes its temp dir."""

    def test_selects_only_orphaned_render_chrome(self):
        tmp = "/var/folders/xy/T"
        ps_out = "\n".join([
            "  501     1   501 /Applications/Chrome --headless=new --user-data-dir=/var/folders/xy/T/scrum-render-ab_1/profile --no-first-run",
            "  602  4242   602 /Applications/Chrome --headless=new --user-data-dir=/var/folders/xy/T/scrum-render-live/profile",
            "  503   501   501 /Applications/Chrome Helper --type=renderer --user-data-dir=/var/folders/xy/T/scrum-render-ab_1/profile",
            "  704     1   704 /Applications/Chrome --user-data-dir=/var/folders/xy/T/other-dir/profile",
            "  805     1   805 /Applications/Chrome --user-data-dir=/var/folders/zz/T/scrum-render-x/profile",
            "  906     1   906 /Applications/Chrome --user-data-dir=/var/folders/xy/T/scrum-render-a/b/profile",
            "garbage line",
            ""])
        signalled = []

        def kill(pid, sig):
            if sig == 0:
                raise ProcessLookupError()
            signalled.append(("kill", pid, sig))

        with mock.patch.object(render.os, "kill", side_effect=kill), \
                mock.patch.object(render.os, "killpg", side_effect=lambda g, s: signalled.append(("killpg", g, s))), \
                mock.patch.object(render.shutil, "rmtree") as rmtree, \
                mock.patch.object(render.subprocess, "run", side_effect=AssertionError("ran ps")):
            got = render.reap(tmp=tmp, ps_out=ps_out)
        self.assertEqual(got, [501])
        self.assertEqual(signalled, [("killpg", 501, signal.SIGTERM), ("killpg", 501, signal.SIGKILL)])
        rmtree.assert_called_once_with("/var/folders/xy/T/scrum-render-ab_1", ignore_errors=True)

    def test_signals_only_pid_when_not_group_leader(self):
        ps_out = "  501     1   77 /c --user-data-dir=/t/scrum-render-q/profile\n"
        signalled = []

        def kill(pid, sig):
            if sig == 0:
                raise ProcessLookupError()
            signalled.append(("kill", pid, sig))

        with mock.patch.object(render.os, "kill", side_effect=kill), \
                mock.patch.object(render.os, "killpg", side_effect=AssertionError("killpg")), \
                mock.patch.object(render.shutil, "rmtree"):
            self.assertEqual(render.reap(tmp="/t", ps_out=ps_out), [501])
        self.assertEqual(signalled, [("kill", 501, signal.SIGTERM), ("kill", 501, signal.SIGKILL)])

    def test_ps_failure_returns_empty(self):
        with mock.patch.object(render.subprocess, "run", side_effect=OSError("no ps")), \
                mock.patch.object(render.os, "kill", side_effect=AssertionError("signalled")), \
                mock.patch.object(render.os, "killpg", side_effect=AssertionError("signalled")):
            self.assertEqual(render.reap(tmp="/t"), [])

    def test_reaps_spawned_orphan(self):
        with tempfile.TemporaryDirectory() as root:
            tmp = os.path.join(root, "T")
            run_dir = os.path.join(tmp, "scrum-render-fake1")
            os.makedirs(os.path.join(run_dir, "profile"))
            script, pids_file = os.path.join(root, "leader.py"), os.path.join(root, "pids")
            Path(script).write_text(LEADER)
            subprocess.run(["sh", "-c", 'exec "$1" "$2" orphan "$3" "$4" >/dev/null 2>&1 </dev/null &', "sh",
                            sys.executable, script, pids_file, f"--user-data-dir={run_dir}/profile"],
                           check=True, timeout=30)
            deadline = time.monotonic() + 30
            while not os.path.exists(pids_file) and time.monotonic() < deadline:
                time.sleep(0.05)
            leader, child = map(int, Path(pids_file).read_text().split())
            self.addCleanup(kill_quietly, leader, child)
            ppid = subprocess.run(["ps", "-o", "ppid=", "-p", str(leader)], capture_output=True, text=True,
                                  timeout=30).stdout.strip()
            if ppid != "1":
                raise unittest.SkipTest(f"the fake leader's ppid is {ppid!r}, not 1 (a subreaper)")
            got = render.reap(tmp=tmp)
            self.assertEqual(got, [leader])
            self.assertTrue(gone(leader, 10), "the SIGTERM-ignoring leader is gone")
            self.assertTrue(gone(child, 10), "its group child is gone")
            self.assertFalse(os.path.exists(run_dir))

    def test_reap_flag(self):
        with mock.patch.object(render, "reap", return_value=[11]):
            self.assertEqual(run_main(["--reap"]), (0, '{"reaped": [11]}\n', ''))
        self.assertEqual(run_main(["--bogus", "x", "/"])[0], 2)

    def test_main_reaps_before_hold(self):
        parent = mock.Mock()
        parent.reap.return_value = []
        parent.machine_hold.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "out")
            with mock.patch.object(render, "reap", parent.reap), \
                    mock.patch.object(render.buildlock, "machine_hold", parent.machine_hold), \
                    mock.patch.object(render.buildlock, "board_module", return_value=object()):
                code, _, _ = run_main(["http://127.0.0.1:1", out, "/"], {"SCRUM_CHROME": str(Path(tmp) / "no-chrome")})
                self.assertEqual(code, 1)
                self.assertEqual([c[0] for c in parent.mock_calls], ["reap", "machine_hold"])
                parent.reset_mock()
                self.assertEqual(run_main(["http://127.0.0.1:1", out])[0], 2)
                parent.reap.assert_not_called()


def run_chrome(argv, env=None, took=None):
    """run_main for a Chrome run, retried once when it exits non-zero or a page timed out (a loaded machine
    can starve Chrome). took, when given, is cleared before each try so it holds the last try only."""
    for _ in range(2):
        if took is not None:
            took.clear()
        code, out, err = run_main(argv, env)
        manifest = Path(argv[1]) / "manifest.json"
        pages = json.loads(manifest.read_text()).get("pages", []) if manifest.exists() else []
        if code == 0 and all(p["status"] != "timeout" for p in pages):
            break
    if code == 1 and manifest.exists():
        why = json.loads(manifest.read_text()).get("error") or ""
        if why.startswith("Chrome failed to start") or (not why and any(p["status"] == "timeout" for p in pages)):
            raise unittest.SkipTest("Chrome start or page-load timeout after one retry (loaded machine): " + (why or "page timeout"))
    return code, out, err + (manifest.read_text() if code and manifest.exists() else "")


def timed_chrome(argv, **caps):
    """run_chrome with render's caps patched; (code, err, seconds each _load call took on the last try)."""
    load, took = render._load, []

    def timed(*a):
        t0 = time.monotonic()
        try:
            return load(*a)
        finally:
            took.append(time.monotonic() - t0)

    with mock.patch.multiple(render, _load=timed, **caps):
        code, _, err = run_chrome(argv, took=took)
    return code, err, took


class RenderChromeSkipTest(unittest.TestCase):
    """run_chrome's skip rule, with run_main mocked (needs no Chrome)."""

    def go(self, results):
        """results: one (exit code, manifest dict or None) per try; returns (run_chrome outcome, run_main calls)."""
        out = Path(tempfile.mkdtemp())
        tries = iter(results)

        def fake(argv, env=None):
            code, manifest = next(tries)
            if manifest is None:
                (out / "manifest.json").unlink(missing_ok=True)
            else:
                (out / "manifest.json").write_text(json.dumps(manifest))
            return code, "", ""

        with mock.patch(f"{__name__}.run_main", side_effect=fake) as m:
            try:
                return run_chrome(["http://x", str(out)]), m.call_count
            except unittest.SkipTest:
                return "skipped", m.call_count

    def test_start_failure_skips(self):
        res, calls = self.go([(1, {"error": "Chrome failed to start: boom", "pages": []})] * 2)
        self.assertEqual((res, calls), ("skipped", 2))

    def test_page_timeout_skips(self):
        res, _ = self.go([(1, {"pages": [{"status": "ok"}, {"status": "timeout"}]})] * 2)
        self.assertEqual(res, "skipped")

    def test_other_failures_not_skipped(self):
        for code, manifest in [(1, {"error": "no Chrome found", "pages": []}), (1, None),
                               (2, {"pages": [{"status": "timeout"}]}), (0, {"pages": [{"status": "timeout"}]})]:
            with self.subTest(code=code, manifest=manifest):
                res, _ = self.go([(code, manifest)] * 2)
                self.assertEqual(res[0], code)

    def test_retry_once_then_pass(self):
        res, calls = self.go([(1, {"error": "Chrome failed to start: x", "pages": []}), (0, {"pages": []})])
        self.assertEqual((res[0], calls), (0, 2))


class RenderUnitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "render"

    def test_slug(self):
        self.assertEqual(render.slug("/"), "root")
        self.assertEqual(render.slug("/admin/views"), "admin-views")
        self.assertEqual(render.slug("/pricing"), "pricing")

    def test_ws_frame_round_trip(self):
        for n in (5, 125, 126, 300, 65535, 70000):
            data = bytes(i % 251 for i in range(n))
            frame = render.encode_frame(data)
            self.assertEqual(frame[1] & 0x80, 0x80)  # a client frame is masked
            self.assertEqual(render.decode_frame(frame + b"rest"), (1, data, len(frame)))
            self.assertIsNone(render.decode_frame(frame[:-1]))  # incomplete
        self.assertEqual(render.decode_frame(b"\x81\x02hi"), (1, b"hi", 4))  # server frames are unmasked

    def test_no_paths_is_usage_error(self):
        code, _, err = run_main(["http://127.0.0.1:1", str(self.out)])
        self.assertEqual(code, 2)
        self.assertIn("usage: render.py <url> <out_dir> [--cookies <file>] <path>...", err)

    def test_missing_chrome_writes_error_manifest(self):
        (self.out).mkdir()
        (self.out / "old-390.png").write_bytes(b"x")
        code, _, _ = run_main(["http://127.0.0.1:1", str(self.out), "/"],
                              {"SCRUM_CHROME": str(Path(self.tmp.name) / "no-chrome")})
        self.assertEqual(code, 1)
        self.assertFalse((self.out / "old-390.png").exists())
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["pages"], [])
        self.assertEqual(m["error"], f"no Chrome found at {Path(self.tmp.name) / 'no-chrome'}")

    def test_click_usage_errors(self):
        base = ["http://127.0.0.1:1", str(self.out), "/", "/b"]
        for extra in (["--click"], ["--click", "/"], ["--click", "/=" ], ["--click", "/nope=#x"], ["--click", "#x"]):
            code, _, err = run_main(base + extra)
            self.assertEqual(code, 2, extra)
            self.assertIn("usage: render.py <url> <out_dir>", err, extra)
            self.assertIn("--click <path>=<selector>", err, extra)

    def test_refuses_out_dir_with_other_files(self):
        self.out.mkdir()
        (self.out / "notes.txt").write_text("keep")
        code, _, err = run_main(["http://127.0.0.1:1", str(self.out), "/"])
        self.assertEqual(code, 2)
        self.assertTrue((self.out / "notes.txt").exists())


class RenderHoldTest(unittest.TestCase):
    """Job 1227: main() waits while buildlock.machine_hold gives a reason, HOLD_CAP s at most, before render() starts
    Chrome. A fake clock: time.sleep advances what time.monotonic reads."""
    LOAD = "CPU load 400% of 8 cores (> 300%)"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name) / "out"
        self.calls, self.clock = [], [1000.0]

    def main(self, *reasons, board=None):
        """main() with machine_hold giving `reasons` in turn (the last for ever after); (exit code, stdout, stderr)."""
        given = list(reasons)

        def machine_hold(b):
            self.calls.append(("hold", b))
            return given.pop(0) if len(given) > 1 else given[0]

        def sleep(s):
            self.calls.append(("sleep", s))
            self.clock[0] += s
        board = object() if board is None else board
        with mock.patch.object(render.buildlock, "machine_hold", side_effect=machine_hold), \
                mock.patch.object(render.buildlock, "board_module", return_value=board), \
                mock.patch.object(render.time, "sleep", side_effect=sleep), \
                mock.patch.object(render.time, "monotonic", side_effect=lambda: self.clock[0]), \
                mock.patch.object(render, "render", side_effect=lambda *a: self.calls.append(("render",)) or {
                    "pages": [{"path": "/", "status": "ok"}]}):
            return run_main(["http://127.0.0.1:1", str(self.out), "/"])

    def test_hold_then_render(self):
        self.assertEqual((render.HOLD_CAP, render.HOLD_POLL), (300, 5))
        board = object()
        got = self.main(self.LOAD, self.LOAD, None, board=board)
        self.assertEqual(got, (0, '{"pages": [{"path": "/", "status": "ok"}], "error": null}\n',
                               f"render.py: holding for the machine: {self.LOAD}\n"))
        self.assertEqual(self.calls, [("hold", board), ("sleep", 5), ("hold", board), ("sleep", 5), ("hold", board),
                                      ("render",)])

    def test_hold_cap_renders_anyway(self):
        code, out, err = self.main(self.LOAD)
        self.assertEqual((code, err), (0, f"render.py: holding for the machine: {self.LOAD}\n"))
        self.assertEqual(self.calls[-1], ("render",))
        self.assertEqual(self.calls.count(("render",)), 1)
        self.assertEqual([c for c in self.calls if c[0] == "sleep"], [("sleep", 5)] * 60, "300 s cap, 5 s polls")

    def test_no_board_no_hold(self):
        with mock.patch.object(render.buildlock, "board_module", return_value=None), \
                mock.patch.object(render.time, "sleep", side_effect=AssertionError("held")), \
                mock.patch.object(render, "render", side_effect=lambda *a: {"pages": []}):
            self.assertEqual(run_main(["http://127.0.0.1:1", str(self.out), "/"]), (0, '{"pages": [], "error": null}\n',
                                                                                      ""))


@unittest.skipUnless(render.find_chrome(), "no Chrome found")
class RenderChromeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "render"
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Page)
        self.srv.cookies = []
        self.srv.release = threading.Event()
        self.srv.hangs_ended = 0
        self.srv.hits = []
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.release.set)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def test_renders_local_page(self):
        code, _, err = run_chrome([self.url, str(self.out), "/"])
        self.assertEqual(code, 0, err)
        self.assertTrue((self.out / "root-390.png").read_bytes().startswith(b"\x89PNG"))
        self.assertTrue((self.out / "root-1440.png").read_bytes().startswith(b"\x89PNG"))
        self.assertIn("/ 390 error: boom", (self.out / "console.log").read_text().splitlines())
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["cookies"], None)
        self.assertEqual(len(m["pages"]), 1)
        page = m["pages"][0]
        self.assertEqual((page["path"], page["status"], page["http_status"], page["shots"], page["console_errors"]),
                         ("/", "ok", 200, ["root-390.png", "root-1440.png"], 2))

    def test_click_opens_modal(self):
        code, _, err = run_chrome([self.url, str(self.out), "--click", "/click-modal=#open", "/click-modal"])
        self.assertEqual(code, 0, err)
        for n in ("click-modal-390", "click-modal-1440", "click-modal-clicked-390", "click-modal-clicked-1440"):
            self.assertTrue((self.out / f"{n}.png").read_bytes().startswith(b"\x89PNG"), n)
        self.assertNotEqual((self.out / "click-modal-390.png").read_bytes(),
                            (self.out / "click-modal-clicked-390.png").read_bytes())
        page = json.loads((self.out / "manifest.json").read_text())["pages"][0]
        self.assertEqual(page["shots"], ["click-modal-390.png", "click-modal-clicked-390.png",
                                         "click-modal-1440.png", "click-modal-clicked-1440.png"])
        self.assertEqual((page["status"], page["clicks"]), ("ok", ["#open"]))
        self.assertEqual(self.srv.hits, ["/hit-open", "/hit-open"])

    def test_clicks_run_in_order(self):
        code, _, err = run_chrome([self.url, str(self.out), "--click", "/click-two=#first",
                                   "--click", "/click-two=#second", "/click-two"])
        self.assertEqual(code, 0, err)
        page = json.loads((self.out / "manifest.json").read_text())["pages"][0]
        self.assertEqual((page["status"], page["clicks"]), ("ok", ["#first", "#second"]))
        self.assertEqual(len(page["shots"]), 4)
        self.assertEqual(self.srv.hits, ["/hit-first", "/hit-second"] * 2)

    def test_click_selector_missing(self):
        code, _, err = run_chrome([self.url, str(self.out), "--click", "/click-modal=#nope", "/click-modal"])
        self.assertEqual(code, 0, err)
        page = json.loads((self.out / "manifest.json").read_text())["pages"][0]
        self.assertEqual((page["status"], page["clicks"], page["shots"]),
                         ("click_failed", ["#nope"], ["click-modal-390.png", "click-modal-1440.png"]))
        self.assertFalse(list(self.out.glob("*clicked*")))

    def test_cookie_file_missing_is_noted(self):
        missing = Path(self.tmp.name) / "auth.json"
        code, _, err = run_chrome([self.url, str(self.out), "--cookies", str(missing), "/"])
        self.assertEqual(code, 0, err)
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["cookies"], f"missing: {missing}")
        self.assertEqual(m["pages"][0]["status"], "ok")

    def test_cookie_values_never_written(self):
        auth = Path(self.tmp.name) / "auth.json"
        auth.write_text(json.dumps({"cookies": [{"name": "session-652", "value": SENTINEL, "domain": "127.0.0.1",
                                                 "path": "/", "expires": -1, "httpOnly": True, "secure": False,
                                                 "sameSite": "Lax"}], "origins": []}))
        code, out, err = run_chrome([self.url, str(self.out), "--cookies", str(auth), "/"])
        self.assertEqual(code, 0, err)
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["cookies"], "loaded 1")
        self.assertIn(f"session-652={SENTINEL}", self.srv.cookies)  # the page loaded signed in
        for blob in [out, err] + [p.read_bytes().decode("latin-1") for p in self.out.iterdir()]:
            self.assertNotIn(SENTINEL, blob)
            self.assertNotIn("session-652", blob)

    def test_waits_for_network_idle(self):
        code, _, err = run_chrome([self.url, str(self.out), "/fetch"])
        self.assertEqual(code, 0, err)
        lines = (self.out / "console.log").read_text().splitlines()
        self.assertIn("/fetch 390 error: fetched", lines)
        self.assertIn("/fetch 1440 error: fetched", lines)

    def test_waits_for_loading_indicator(self):
        for k in MARKERS:
            with self.subTest(k):
                code, _, err = run_chrome([self.url, str(self.out), f"/load-{k}"])
                self.assertEqual(code, 0, err)
                lines = (self.out / "console.log").read_text().splitlines()
                self.assertIn(f"/load-{k} 390 error: ready", lines)
                self.assertIn(f"/load-{k} 1440 error: ready", lines)

    def test_loading_indicator_cap(self):
        code, err, took = timed_chrome([self.url, str(self.out), "/load-never"], LOAD_CAP=3)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(took), 2)
        for t in took:  # stops at the 3 s cap, well before the default 60 s LOAD_CAP or the 240 s BUDGET
            self.assertGreaterEqual(t, 3)
            self.assertLess(t, 45)
        page = json.loads((self.out / "manifest.json").read_text())["pages"][0]
        self.assertEqual((page["status"], page["shots"]), ("ok", ["load-never-390.png", "load-never-1440.png"]))

    def test_empty_status_is_busy(self):
        code, _, err = run_chrome([self.url, str(self.out), "/load-empty"])
        self.assertEqual(code, 0, err)
        lines = (self.out / "console.log").read_text().splitlines()
        self.assertIn("/load-empty 390 error: ready", lines)
        self.assertIn("/load-empty 1440 error: ready", lines)

    def test_skeleton_is_busy(self):
        code, _, err = run_chrome([self.url, str(self.out), "/load-skeleton"])
        self.assertEqual(code, 0, err)
        lines = (self.out / "console.log").read_text().splitlines()
        self.assertIn("/load-skeleton 390 error: ready", lines)

    def assert_not_busy(self, path):
        busy, real = [], render._busy

        def recorder(cdp):
            busy.append(real(cdp))
            return busy[-1]

        with mock.patch.object(render, "_busy", recorder):
            code, err, took = timed_chrome([self.url, str(self.out), path], LOAD_CAP=120)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(took), 2)
        self.assertGreaterEqual(len(busy), 2)  # once per width
        self.assertNotIn(True, busy)  # the page was never treated as busy
        page = json.loads((self.out / "manifest.json").read_text())["pages"][0]
        self.assertEqual(page["status"], "ok")

    def test_permanent_status_not_busy(self):
        self.assert_not_busy("/status-permanent")

    def test_hidden_status_not_busy(self):
        self.assert_not_busy("/status-hidden")

    def test_quiet_is_half_second(self):
        self.assertEqual(render.QUIET, 0.5)

    def test_settle_cap_bounds_hung_request(self):
        code, err, took = timed_chrome([self.url, str(self.out), "/hung"], SETTLE_CAP=2)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(took), 2)
        for t in took:
            self.assertGreaterEqual(t, 2)
        self.assertEqual(self.srv.hangs_ended, 0)  # each width stopped at the cap while /hang was still held open
        page = json.loads((self.out / "manifest.json").read_text())["pages"][0]
        self.assertEqual((page["status"], page["shots"]), ("ok", ["hung-390.png", "hung-1440.png"]))

    def test_redirect_compares_path_and_query(self):
        paths = ["/p?view=leads", "/q?view=leads", "/a", "/t/"]
        code, _, err = run_chrome([self.url, str(self.out), *paths])
        self.assertEqual(code, 0, err)
        pages = json.loads((self.out / "manifest.json").read_text())["pages"]
        self.assertEqual([(p["path"], p["status"]) for p in pages],
                         [("/p?view=leads", "ok"), ("/q?view=leads", "redirected"), ("/a", "redirected"),
                          ("/t/", "ok")])


if __name__ == "__main__":
    unittest.main()
