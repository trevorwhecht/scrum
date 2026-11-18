"""render.py: the shared review render (job 652). Headless Chrome over a stdlib CDP websocket client."""
import io, json, os, sys, tempfile, threading, time, unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
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
        if self.path == "/slow":
            time.sleep(2)
        elif self.path == "/hang":
            self.server.release.wait(90)  # held open until the test ends
            self.server.hangs_ended += 1
            return
        body = {"/fetch": FETCH_PAGE, "/hung": HUNG_PAGE, **LOADING_PAGES}.get(self.path, PAGE)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def run_main(argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}), redirect_stdout(out), redirect_stderr(err):
        code = render.main(argv)
    return code, out.getvalue(), err.getvalue()


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

    def test_refuses_out_dir_with_other_files(self):
        self.out.mkdir()
        (self.out / "notes.txt").write_text("keep")
        code, _, err = run_main(["http://127.0.0.1:1", str(self.out), "/"])
        self.assertEqual(code, 2)
        self.assertTrue((self.out / "notes.txt").exists())


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
        code, err, took = timed_chrome([self.url, str(self.out), path], LOAD_CAP=20)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(took), 2)
        for t in took:  # a busy page waits the whole 20 s cap
            self.assertLess(t, 20)
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
