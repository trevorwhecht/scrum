import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

PROJECT = "setup-repo"
BACKLOG = ("# Backlog\n"
           "- [x] Finished → 001-done\n"
           "- [ ] Plain item\n"
           "- [ ] Send SMS alerts with a very long description that keeps going on narrow phones"
           " {setup: Buy a Twilio number; Add <b>TWILIO_TOKEN</b> to .env}\n")
AFTER = "# Backlog\n- [x] Finished → 001-done\n- [ ] Plain item\n" \
        "- [ ] Send SMS alerts with a very long description that keeps going on narrow phones\n"

# Drives the real dashboard in headless Chromium against a real serve.py. Prints one JSON line: {"skip": why} when
# Playwright or Chromium is missing, else what WIDTH measured in the Backlog dialog before and after Setup done.
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
    const snap = () => page.evaluate(() => {
      const rows = [...document.querySelectorAll("#blList > li[data-i]")];
      const list = document.getElementById("blList"), dlg = document.getElementById("backlog");
      const changes = getComputedStyle(document.documentElement).getPropertyValue("--changes").trim();
      const probe = document.createElement("span"); probe.style.color = changes; document.body.append(probe);
      const changesRgb = getComputedStyle(probe).color; probe.remove();
      return {changesRgb,
              rows: rows.map(li => {
                const box = li.querySelector(".setup-box"), ul = li.querySelector("ul.setup-list");
                return {i: li.dataset.i, cls: li.className, border: getComputedStyle(li).borderLeftColor,
                        tags: [...li.children].map(c => c.tagName + (c.className ? "." + c.className.split(" ")[0] : "")),
                        buttons: [...li.querySelectorAll("button")].map(b => b.dataset.do + ":" + b.textContent),
                        label: box && box.firstChild.textContent,
                        steps: ul && [...ul.children].map(s => s.textContent),
                        stepHtml: ul && [...ul.children].map(s => s.children.length),
                        boxBelowInput: box && box.getBoundingClientRect().top >= li.querySelector("textarea").getBoundingClientRect().bottom};
              }),
              listScroll: list.scrollWidth, listClient: list.clientWidth,
              dlgScroll: dlg.scrollWidth, dlgClient: dlg.clientWidth,
              docScroll: document.documentElement.scrollWidth, docClient: document.documentElement.clientWidth};
    });
    const got = {before: await snap()};
    const btn = '#blList li[data-i="2"] button[data-do="setup-done"]';
    await page.click(btn);
    got.armed = await page.evaluate(b => document.querySelector(b).textContent, btn);
    await new Promise(r => setTimeout(r, 300));
    got.backlogWhileArmed = await (await fetch(process.env.BACKLOG_URL)).text();
    await page.click(btn);
    await page.waitForFunction(() => !document.querySelector("#blList li.setup"));
    got.after = await snap();
    got.blError = await page.evaluate(() => document.getElementById("blError").textContent);
    console.log(JSON.stringify(got));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DashboardBacklogSetupBrowserTest(unittest.TestCase):
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
        spawn = mock.patch.object(serve, "spawn")
        self.spawn = spawn.start()
        self.addCleanup(spawn.stop)
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def browse(self, width):
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        env = dict(os.environ, WIDTH=str(width), DASH_URL=f"{base}/dashboard.html",
                   BACKLOG_URL=f"{base}/p/{PROJECT}/backlog.md")
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
        before = {r["i"]: r for r in got["before"]["rows"]}
        self.assertEqual(sorted(before), ["1", "2"], got)
        plain = before["1"]
        self.assertEqual(plain["cls"], "", got)
        self.assertEqual(plain["tags"], ["SPAN.grip", "SELECT.pts", "TEXTAREA", "BUTTON.btn", "BUTTON.btn", "BUTTON.btn", "BUTTON.btn"], got)
        self.assertEqual(plain["buttons"], ["up:↑", "down:↓", "run:▶", "delete:✕"], got)
        marked = before["2"]
        self.assertEqual(marked["cls"], "setup", got)
        self.assertEqual(got["before"]["changesRgb"], "rgb(196, 82, 15)", got)
        self.assertEqual(marked["border"], "rgb(196, 82, 15)", got)
        self.assertEqual(marked["buttons"], ["up:↑", "down:↓", "setup-done:Setup done", "delete:✕"], got)
        self.assertEqual(marked["label"], "waiting on you:", got)
        self.assertEqual(marked["steps"], ["Buy a Twilio number", "Add <b>TWILIO_TOKEN</b> to .env"], got)
        self.assertEqual(marked["stepHtml"], [0, 0], got)  # escaped: no <b> element
        self.assertTrue(marked["boxBelowInput"], got)
        self.assertEqual(got["armed"], "Setup done?", got)
        self.assertEqual(got["backlogWhileArmed"], BACKLOG, got)
        after = {r["i"]: r for r in got["after"]["rows"]}
        self.assertEqual(after["2"]["cls"], "", got)
        self.assertEqual(after["2"]["buttons"], ["up:↑", "down:↓", "run:▶", "delete:✕"], got)
        self.assertIsNone(after["2"]["steps"], got)
        self.assertEqual(got["blError"], "", got)
        self.assertEqual((self.repo / "scrum" / "backlog.md").read_text(), AFTER)
        self.spawn.assert_not_called()

    def test_backlog_setup_desktop(self):
        self.check(self.browse(1280))

    def test_backlog_setup_390px_no_horizontal_scroll(self):
        got = self.browse(390)
        self.check(got)
        for snap in (got["before"], got["after"]):
            self.assertLessEqual(snap["listScroll"], snap["listClient"], got)
            self.assertLessEqual(snap["dlgScroll"], snap["dlgClient"], got)
            self.assertLessEqual(snap["docScroll"], snap["docClient"], got)


if __name__ == "__main__":
    unittest.main()
