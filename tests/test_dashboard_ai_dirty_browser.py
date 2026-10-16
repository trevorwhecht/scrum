import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

WARN = "Unsaved changes. Press again to discard."

# Drives the real dashboard in headless Chromium, where the <dialog> cancel event and its close-watcher rules are the
# real ones. Prints one JSON line: {"skip": why} when Playwright or Chromium is missing, else what each Escape left.
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const page = await browser.newPage();
    await page.goto(process.env.DASH_URL);
    await page.click("#aiBtn");
    await page.click('#aiCats button[data-cat="commands"]');
    await page.click("#aiList button[data-id]");
    await page.waitForSelector("#aiText");
    await page.click("#aiText");
    await page.keyboard.press("End");
    await page.keyboard.type(" edited");
    const look = () => page.evaluate(() => ({open: document.getElementById("aiSettings").open,
      error: document.getElementById("aiError").textContent, text: document.getElementById("aiText")?.value ?? null}));
    await page.keyboard.press("Escape"); await page.waitForTimeout(100);
    const first = await look();
    await page.keyboard.press("Escape"); await page.waitForTimeout(100);
    const second = await look();
    console.log(JSON.stringify({first, second}));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class AiSettingsDirtyBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "home"
        self.user, managed = home / ".claude", Path(self.tmp.name) / "managed"
        for d in (self.user / "commands", managed):
            d.mkdir(parents=True)
        self.cmd = self.user / "commands" / "c.md"
        self.cmd.write_text("user c")
        (home / ".claude.json").write_text("{}")
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text("[]")
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(self.user), CLAUDE_MANAGED_DIR=str(managed), SCRUM_REGISTRY=str(registry))
        patcher.start()
        self.addCleanup(patcher.stop)
        import serve  # noqa: E402
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def browse(self):
        env = dict(os.environ, DASH_URL=f"http://127.0.0.1:{self.server.server_address[1]}/dashboard.html")
        if "NODE_PATH" not in env:
            npm = shutil.which("npm")
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip() if npm else ""
            env["NODE_PATH"] = root or "/opt/node22/lib/node_modules"
        out = subprocess.run([self.node, "-e", SCRIPT], capture_output=True, text=True, env=env, timeout=120).stdout
        got = json.loads(out.strip().splitlines()[-1])
        if "skip" in got:
            raise unittest.SkipTest(got["skip"])
        return got

    def test_escape_dirty_editor_warns_once_then_closes(self):
        got = self.browse()
        self.assertEqual(got.get("first"), {"open": True, "error": WARN, "text": "user c edited"}, got)
        self.assertEqual(got["second"]["open"], False, got)
        self.assertEqual(self.cmd.read_text(), "user c")


if __name__ == "__main__":
    unittest.main()
