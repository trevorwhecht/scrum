import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

PROJECT = "needs-repo"
BACKLOG = ("# Backlog\n"
           "- [x] Build the base API layer for every single order endpoint {#base} → 001-base\n"
           "- [x] Finished prerequisite {#done} → 002-done\n"
           "- [ ] Plain item\n"
           "- [ ] Waiting item {needs #base #gone}\n"
           "- [ ] Met item {needs #done}\n")

# Drives the real dashboard in headless Chromium against a real serve.py. Prints one JSON line: {"skip": why} when
# Playwright or Chromium is missing, else what WIDTH measured in the Backlog dialog.
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const width = +process.env.WIDTH;
    const page = await browser.newPage({viewport: {width, height: 844}});
    await page.goto(process.env.DASH_URL);
    await page.waitForSelector(".card[data-key]");
    await page.click("#backlogBtn");
    await page.waitForSelector("#blList li[data-i]");
    const row = i => `#blList li[data-i="${i}"]`;
    const got = await page.evaluate(() => {
      const rows = [...document.querySelectorAll("#blList li[data-i]")];
      const needs = li => { const n = li.querySelector(".needs"); return n && {text: n.textContent, title: n.title,
        muted: getComputedStyle(n).color === getComputedStyle(document.getElementById("status")).color,
        afterInput: n.previousElementSibling && n.previousElementSibling.tagName === "TEXTAREA"}; };
      const list = document.getElementById("blList"), dlg = document.getElementById("backlog");
      return {rows: rows.map(li => ({i: li.dataset.i, tags: [...li.children].map(c => c.tagName + (c.className ? "." + c.className.split(" ")[0] : "")),
                                     needs: needs(li)})),
              listScroll: list.scrollWidth, listClient: list.clientWidth,
              dlgScroll: dlg.scrollWidth, dlgClient: dlg.clientWidth,
              docScroll: document.documentElement.scrollWidth, docClient: document.documentElement.clientWidth};
    });
    await page.click(`${row(3)} button[data-do="run"]`);
    await page.click(`${row(3)} button[data-do="run"]`);
    await page.waitForFunction(() => document.getElementById("blError").textContent);
    got.blError = await page.evaluate(() => document.getElementById("blError").textContent);
    got.dialogOpen = await page.evaluate(() => document.getElementById("backlog").open);
    console.log(JSON.stringify(got));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DashboardBacklogNeedsBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "home"
        user, managed, self.repo = home / ".claude", Path(self.tmp.name) / "managed", home / PROJECT
        for d in (user, managed, self.repo / "scrum" / "jobs" / "001-base", self.repo / "scrum" / "jobs" / "002-done"):
            d.mkdir(parents=True)
        (home / ".claude.json").write_text("{}")
        (self.repo / "scrum" / "backlog.md").write_text(BACKLOG)
        (self.repo / "scrum" / "board.json").write_text(json.dumps({"jobs": [
            {"id": "001-base", "title": "Base", "stage": "build", "files": []},
            {"id": "002-done", "title": "Done", "stage": "done", "files": []}]}))
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text(json.dumps([str(self.repo)]))
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(user), CLAUDE_MANAGED_DIR=str(managed), SCRUM_REGISTRY=str(registry))
        patcher.start()
        self.addCleanup(patcher.stop)
        import serve  # noqa: E402
        status = mock.patch.object(serve.route, "status", return_value={"codex": {"5h": 1, "weekly": 1},
                                                                         "claude_exhausted_until": None})
        status.start()
        self.addCleanup(status.stop)
        spawn = mock.patch.object(serve, "spawn")
        self.spawn = spawn.start()
        self.addCleanup(spawn.stop)
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def browse(self, width):
        env = dict(os.environ, WIDTH=str(width), DASH_URL=f"http://127.0.0.1:{self.server.server_address[1]}/dashboard.html")
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
        rows = {r["i"]: r for r in got["rows"]}
        self.assertEqual(sorted(rows), ["2", "3", "4"], got)
        plain = rows["2"]
        self.assertIsNone(plain["needs"], got)
        self.assertEqual(plain["tags"], ["SPAN.grip", "SELECT.pts", "TEXTAREA", "BUTTON.btn", "BUTTON.btn", "BUTTON.btn", "BUTTON.btn"], got)
        waiting = rows["3"]["needs"]
        self.assertEqual(waiting["text"], "waits on: Build the base API layer for every sing…, #gone", got)
        self.assertEqual(waiting["title"], "Build the base API layer for every single order endpoint; #gone", got)
        self.assertTrue(waiting["afterInput"], got)
        self.assertFalse(waiting["muted"], got)
        met = rows["4"]["needs"]
        self.assertEqual(met["text"], "waits on: Finished prerequisite", got)
        self.assertTrue(met["muted"], got)
        self.assertEqual(got["blError"], "backlog item 3 waits on #base", got)
        self.assertTrue(got["dialogOpen"], got)
        self.spawn.assert_not_called()
        self.assertEqual((self.repo / "scrum" / "backlog.md").read_text(), BACKLOG)

    def test_backlog_needs_desktop(self):
        self.check(self.browse(1280))

    def test_backlog_needs_390px_no_horizontal_scroll(self):
        got = self.browse(390)
        self.check(got)
        self.assertLessEqual(got["listScroll"], got["listClient"], got)
        self.assertLessEqual(got["dlgScroll"], got["dlgClient"], got)
        self.assertLessEqual(got["docScroll"], got["docClient"], got)


if __name__ == "__main__":
    unittest.main()
