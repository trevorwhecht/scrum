"""render.py: the shared review render (job 652). Headless Chrome over a stdlib CDP websocket client."""
import io, json, os, sys, tempfile, threading, unittest
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
import render  # noqa: E402

PAGE = b"<!doctype html><title>t</title><h1>hi</h1><script>console.error('boom')</script>"
SENTINEL = "s3ntinel-cookie-value-652"


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.cookies.append(self.headers.get("Cookie", ""))
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *a):
        pass


def run_main(argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env or {}), redirect_stdout(out), redirect_stderr(err):
        code = render.main(argv)
    return code, out.getvalue(), err.getvalue()


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
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def test_renders_local_page(self):
        code, _, err = run_main([self.url, str(self.out), "/"])
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
        code, _, err = run_main([self.url, str(self.out), "--cookies", str(missing), "/"])
        self.assertEqual(code, 0, err)
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["cookies"], f"missing: {missing}")
        self.assertEqual(m["pages"][0]["status"], "ok")

    def test_cookie_values_never_written(self):
        auth = Path(self.tmp.name) / "auth.json"
        auth.write_text(json.dumps({"cookies": [{"name": "session-652", "value": SENTINEL, "domain": "127.0.0.1",
                                                 "path": "/", "expires": -1, "httpOnly": True, "secure": False,
                                                 "sameSite": "Lax"}], "origins": []}))
        code, out, err = run_main([self.url, str(self.out), "--cookies", str(auth), "/"])
        self.assertEqual(code, 0, err)
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["cookies"], "loaded 1")
        self.assertIn(f"session-652={SENTINEL}", self.srv.cookies)  # the page loaded signed in
        for blob in [out, err] + [p.read_bytes().decode("latin-1") for p in self.out.iterdir()]:
            self.assertNotIn(SENTINEL, blob)
            self.assertNotIn("session-652", blob)


if __name__ == "__main__":
    unittest.main()
