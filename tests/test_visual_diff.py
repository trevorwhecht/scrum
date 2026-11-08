"""skills/trevskills-scrum/visual-diff.mjs: the Check gate's BASE-vs-HEAD capture and pixel diff (job 681)."""
import functools, http.server, json, os, shutil, subprocess, tempfile, threading, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "trevskills-scrum" / "visual-diff.mjs"
NODE = shutil.which("node")
PROJECT = os.environ.get("SCRUM_VISUAL_PROJECT")


def deps_present(d):
    return bool(d) and all((Path(d) / "node_modules" / p).is_dir() for p in ("playwright", "odiff-bin", "sharp"))


@unittest.skipUnless(NODE, "node not on PATH")
class VisualDiffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_script(self, *args, timeout=60):
        return subprocess.run([NODE, str(SCRIPT), *args], capture_output=True, text=True, timeout=timeout)

    def test_usage_error_exits_2(self):
        out = str(self.tmp / "round-1" / "visual")
        full = ["--base", "http://x", "--head", "http://y", "--out", out, "--project-dir", str(self.tmp)]
        cases = {"no args": [], "no path": full, "no --head": full[:2] + full[4:] + ["/"],
                 "dangling flag": full + ["/", "--mask"], "unknown flag": full + ["--nope", "/"]}
        for name, args in cases.items():
            with self.subTest(name):
                r = self.run_script(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("usage: node visual-diff.mjs --base <url>", r.stderr)
        self.assertFalse((self.tmp / "round-1").exists())

    def test_missing_deps_writes_skipped(self):
        proj = self.tmp / "proj"
        proj.mkdir()
        (proj / "package.json").write_text('{"name": "p"}\n')
        out = self.tmp / "round-2" / "visual"
        r = self.run_script("--base", "http://127.0.0.1:9", "--head", "http://127.0.0.1:9", "--out", str(out),
                            "--project-dir", str(proj), "/")
        self.assertEqual(r.returncode, 0, r.stderr)
        reason = f"playwright not installed in {proj}"
        self.assertEqual(json.loads((out / "results.json").read_text()),
                         {"status": "skipped", "reason": reason, "pairs": []})
        md = (self.tmp / "round-2" / "visual-diff.md").read_text()
        self.assertEqual(md.splitlines()[0], f"VISUAL: skipped — {reason}")

    @unittest.skipUnless(deps_present(PROJECT), "SCRUM_VISUAL_PROJECT has no playwright, odiff-bin and sharp")
    def test_capture_finds_changed_and_same_pairs(self):
        page = ('<!doctype html><html><body style="margin:0;font:16px sans-serif;background:#fff">'
                '<h1 style="color:#123">Title</h1><p>Some text here.</p>{}</body></html>')
        sites = {}
        for side, button in (("base", ""), ("head", '<button style="width:120px;height:44px">New</button>')):
            d = self.tmp / side
            d.mkdir()
            (d / "a").write_text(page.format(button))
            (d / "b").write_text(page.format(""))
            mark = '<p style="color:#c00">Changed</p>' if side == "head" else "<p>Same</p>"
            (d / "c").write_text(page.format(mark + '<div style="height:2400px"></div>' + mark))
            sites[side] = self.serve(d)
        out = self.tmp / "round-1" / "visual"
        r = self.run_script("--base", sites["base"], "--head", sites["head"], "--out", str(out),
                            "--project-dir", PROJECT, "/a", "/b", "/c", timeout=240)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads((out / "results.json").read_text())
        self.assertEqual(res["status"], "ok")
        got = {(p["path"], p["width"]): p for p in res["pairs"]}
        self.assertEqual(sorted(got), [("/a", 390), ("/a", 1440), ("/b", 390), ("/b", 1440), ("/c", 390), ("/c", 1440)])
        for w in (390, 1440):
            a, b = got[("/a", w)], got[("/b", w)]
            self.assertEqual(a["status"], "changed", a)
            self.assertEqual(a["crop"], str(out / f"a-{w}.png"))
            self.assertTrue(Path(a["crop"]).is_file())
            self.assertEqual(b["status"], "same", b)
            self.assertIsNone(b["crop"])
        for w in (390, 1440):  # changes 2400 px apart: the 1600 px crop cannot hold both, so reviewers must render it
            c = got[("/c", w)]
            self.assertEqual((c["status"], c["why"]), ("changed", "crop truncated"), c)
            self.assertTrue(Path(c["crop"]).is_file())
            self.assertEqual(self.png_height(c["crop"]), 1600)
        self.assertIsNone(got[("/a", 390)]["why"])
        md = (self.tmp / "round-1" / "visual-diff.md").read_text().splitlines()
        self.assertEqual(md[0], "VISUAL: changed")
        self.assertIn(f"- /a 390: changed — crop {out / 'a-390.png'}", md)
        self.assertIn("- /b 1440: same", md)
        self.assertIn(f"- /c 390: changed — crop truncated — crop {out / 'c-390.png'}", md)

    @staticmethod
    def png_height(path):
        return int.from_bytes(Path(path).read_bytes()[20:24], "big")

    def serve(self, d):
        class Quiet(http.server.SimpleHTTPRequestHandler):
            extensions_map = {"": "text/html"}

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(d)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":
    unittest.main()
