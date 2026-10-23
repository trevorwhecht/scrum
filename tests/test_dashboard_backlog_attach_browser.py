import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

PROJECT = "attach-repo"
BACKLOG = "# Backlog\n- [x] Finished → 001-done\n- [ ] Plain item\n"
PNG_HASH = "f04916f6f069"  # first 12 hex chars of sha1(b"\x89PNG\r\n\x1a\nbrowser drop"), the bytes SCRIPT drops

# Drives the real dashboard in headless Chromium against a real serve.py. Prints one JSON line: {"skip": why} when
# Playwright or a browser is missing, else what WIDTH measured in the Backlog add form around a drop and an add.
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); }
  catch (e) {
    try { browser = await chromium.launch({channel: "chrome"}); }
    catch (e2) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  }
  try {
    const width = +process.env.WIDTH;
    const page = await browser.newPage({viewport: {width, height: 844}});
    await page.goto(process.env.DASH_URL);
    await page.waitForSelector(".card[data-key]");
    await page.click("#backlogBtn");
    await page.waitForSelector("#blList li[data-i]");
    const got = {};
    got.layout = await page.evaluate(() => {
      const form = document.getElementById("blAdd"), fr = form.getBoundingClientRect(), sel = form.points;
      return {tags: [...form.children].map(c => c.tagName), options: [...sel.options].map(o => o.textContent), value: sel.value,
              tops: [...form.children].map(c => Math.round(c.getBoundingClientRect().top)),
              inside: [...form.children].every(c => { const r = c.getBoundingClientRect(); return r.left >= fr.left - 0.5 && r.right <= fr.right + 0.5; }),
              formScroll: form.scrollWidth, formClient: form.clientWidth,
              docScroll: document.documentElement.scrollWidth, docClient: document.documentElement.clientWidth,
              selHeight: sel.getBoundingClientRect().height, selFont: getComputedStyle(sel).fontSize};
    });
    await page.fill("#blAdd input[name=text]", "Header broken");
    // Watch the + button: it must go disabled while the upload is in flight and come back afterwards.
    await page.evaluate(() => {
      window.__seenDisabled = false;
      const b = document.querySelector("#blAdd button[type=submit]");
      new MutationObserver(() => { if (b.disabled) window.__seenDisabled = true; }).observe(b, {attributes: true});
    });
    const drop = (bytes, name, type) => page.evaluate(([bytes, name, type]) => {
      const dt = new DataTransfer();
      dt.items.add(new File([new Uint8Array(bytes)], name, {type}));
      const ev = new DragEvent("drop", {dataTransfer: dt, bubbles: true, cancelable: true});
      return !document.querySelector("#blAdd input[name=text]").dispatchEvent(ev);  // true = default (navigation) prevented
    }, [bytes, name, type]);
    const png = [...Buffer.from("\x89PNG\r\n\x1a\nbrowser drop", "latin1")];
    got.pngPrevented = await drop(png, "shot.png", "image/png");
    await page.waitForFunction(() => document.querySelector("#blAdd input[name=text]").value.includes("[screenshot:"));
    await page.waitForFunction(() => !document.querySelector("#blAdd button[type=submit]").disabled);
    got.afterPng = await page.evaluate(() => ({value: document.querySelector("#blAdd input[name=text]").value,
      seenDisabled: window.__seenDisabled, blError: document.getElementById("blError").textContent, url: location.href}));
    got.textPrevented = await drop([...Buffer.from("hello")], "notes.txt", "text/plain");
    await page.waitForFunction(() => document.getElementById("blError").textContent !== "");
    got.afterText = await page.evaluate(() => ({value: document.querySelector("#blAdd input[name=text]").value,
      blError: document.getElementById("blError").textContent}));
    await page.selectOption("#blAdd select[name=points]", "8");
    got.pickedClass = await page.evaluate(() => document.querySelector("#blAdd select").className);
    await page.click("#blAdd button[type=submit]");
    await page.waitForFunction(() => document.querySelector("#blAdd input[name=text]").value === "");
    got.afterAdd = await page.evaluate(() => ({points: document.querySelector("#blAdd select").value,
      cls: document.querySelector("#blAdd select").className, blError: document.getElementById("blError").textContent}));
    console.log(JSON.stringify(got));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DashboardBacklogAttachBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "home"
        user, managed, self.repo = home / ".claude", Path(self.tmp.name) / "managed", home / PROJECT
        for d in (user, managed, self.repo / "scrum" / "jobs" / "001-done"):
            d.mkdir(parents=True)
        (home / ".claude.json").write_text("{}")
        (self.repo / "scrum" / "backlog.md").write_text(BACKLOG)
        (self.repo / "scrum" / "board.json").write_text(json.dumps({"jobs": [
            {"id": "001-done", "title": "Done", "stage": "done", "files": []}]}))
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text(json.dumps([str(self.repo)]))
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(user), CLAUDE_MANAGED_DIR=str(managed), SCRUM_REGISTRY=str(registry))
        patcher.start()
        self.addCleanup(patcher.stop)
        import serve  # noqa: E402
        status = mock.patch.object(serve.route, "status", return_value={"codex": {"5h": 1, "weekly": 1}, "ollama": "down",
                                                                         "claude_exhausted_until": None})
        status.start()
        self.addCleanup(status.stop)
        estimate = mock.patch.object(serve, "estimate")
        self.estimate = estimate.start()
        self.addCleanup(estimate.stop)
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def browse(self, width):
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        env = dict(os.environ, WIDTH=str(width), DASH_URL=f"{base}/dashboard.html")
        if "NODE_PATH" not in env:
            npm = shutil.which("npm")
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip() if npm else ""
            env["NODE_PATH"] = root or "/opt/node22/lib/node_modules"
        out = subprocess.run([self.node, "-e", SCRIPT], capture_output=True, text=True, env=env, timeout=120).stdout
        got = json.loads(out.strip().splitlines()[-1])
        if "skip" in got:
            raise unittest.SkipTest(got["skip"])
        self.assertNotIn("error", got, got)
        return got

    def check(self, got):
        shot = self.repo / "scrum" / "attachments" / f"{PNG_HASH}.png"
        self.assertEqual(got["layout"]["tags"], ["SELECT", "INPUT", "BUTTON"], got)
        self.assertEqual(got["layout"]["options"], ["?", "1", "2", "3", "5", "8", "13"], got)
        self.assertEqual(got["layout"]["value"], "", got)
        self.assertTrue(got["pngPrevented"], got)
        self.assertEqual(got["afterPng"]["value"], f"Header broken [screenshot: {shot}]", got)
        self.assertTrue(got["afterPng"]["seenDisabled"], got)
        self.assertEqual(got["afterPng"]["blError"], "", got)
        self.assertTrue(got["afterPng"]["url"].endswith("/dashboard.html"), got)
        self.assertEqual(shot.read_bytes(), b"\x89PNG\r\n\x1a\nbrowser drop")
        self.assertTrue(got["textPrevented"], got)
        self.assertEqual(got["afterText"]["value"], got["afterPng"]["value"], got)
        self.assertEqual(got["afterText"]["blError"], "Only images can be attached", got)
        self.assertEqual(got["pickedClass"], "pts p8", got)
        self.assertEqual(got["afterAdd"], {"points": "", "cls": "pts px", "blError": ""}, got)
        self.assertEqual((self.repo / "scrum" / "backlog.md").read_text(),
                         BACKLOG + f"- [ ] [8] Header broken [screenshot: {shot}]\n")
        self.estimate.assert_not_called()

    def test_backlog_attach_desktop(self):
        self.check(self.browse(1280))

    def test_backlog_attach_390px_one_row(self):
        got = self.browse(390)
        self.check(got)
        lay = got["layout"]
        self.assertEqual(len(set(lay["tops"])), 1, got)  # select, input and + on one row
        self.assertTrue(lay["inside"], got)
        self.assertLessEqual(lay["formScroll"], lay["formClient"], got)
        self.assertLessEqual(lay["docScroll"], lay["docClient"], got)
        self.assertGreaterEqual(lay["selHeight"], 44, got)
        self.assertEqual(lay["selFont"], "16px", got)


if __name__ == "__main__":
    unittest.main()
