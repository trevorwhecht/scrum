import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

PROJECT = "urgency-repo"
BACKLOG = "# Backlog\n- [ ] Old first\n- [ ] Old second {p:4}\n"

# Drives the real dashboard in headless Chromium against a real serve.py: the Backlog add form's Urgency select.
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
    const page = await browser.newPage({viewport: {width: +process.env.WIDTH, height: 844}});
    const posts = [];
    page.on("request", r => { if (r.method() === "POST" && r.url().endsWith("/backlog")) posts.push(JSON.parse(r.postData())); });
    await page.goto(process.env.DASH_URL);
    await page.waitForSelector(".card[data-key]");
    await page.click("#backlogBtn");
    await page.waitForSelector("#blList li[data-i]");
    const sel = "#blAdd select[name=urgency]";
    const got = {};
    got.layout = await page.evaluate(() => {
      const form = document.getElementById("blAdd"), fr = form.getBoundingClientRect(), u = form.urgency;
      return {options: [...u.options].map(o => [o.value, o.textContent]), value: u.value, label: u.getAttribute("aria-label"),
              before: !!(u.compareDocumentPosition(form.points) & 4),
              tops: [...form.children].map(c => Math.round(c.getBoundingClientRect().top)),
              inside: [...form.children].every(c => { const r = c.getBoundingClientRect(); return r.left >= fr.left - 0.5 && r.right <= fr.right + 0.5; }),
              formScroll: form.scrollWidth, formClient: form.clientWidth,
              docScroll: document.documentElement.scrollWidth, docClient: document.documentElement.clientWidth,
              height: u.getBoundingClientRect().height, width: u.getBoundingClientRect().width, font: getComputedStyle(u).fontSize};
    });
    // A pick that was never submitted does not survive closing and reopening the dialog.
    await page.selectOption(sel, "now");
    await page.click("#backlog .close");
    await page.click("#backlogBtn");
    got.reopened = await page.$eval(sel, u => u.value);
    await page.selectOption(sel, "next");
    await page.fill("#blAdd textarea[name=text]", "Jump the queue");
    await page.click("#blAdd button[type=submit]");
    await page.waitForFunction(() => document.querySelector("#blAdd textarea[name=text]").value === "");
    await page.waitForFunction(() => document.querySelector("#blList li[data-i] textarea")?.value === "Jump the queue");
    got.afterNext = await page.evaluate(() => ({first: document.querySelector("#blList li[data-i] textarea").value,
      urgency: document.getElementById("blAdd").urgency.value, open: document.getElementById("backlog").open,
      blError: document.getElementById("blError").textContent}));
    await page.selectOption(sel, "now");
    await page.fill("#blAdd textarea[name=text]", "Start this now");
    await page.click("#blAdd button[type=submit]");
    await page.waitForFunction(() => !document.getElementById("backlog").open);
    got.afterNow = {blError: await page.$eval("#blError", e => e.textContent)};
    got.posts = posts;
    console.log(JSON.stringify(got));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DashboardBacklogUrgencyBrowserTest(unittest.TestCase):
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
        for name, value in (("estimate", None), ("spawn", None), ("heavy_refusal", None)):
            p = mock.patch.object(serve, name, return_value=value)
            setattr(self, name, p.start())
            self.addCleanup(p.stop)
        status = mock.patch.object(serve.route, "status", return_value={"codex": {"5h": 1, "weekly": 1},
                                                                         "claude_exhausted_until": None})
        status.start()
        self.addCleanup(status.stop)
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
        lay = got["layout"]
        self.assertEqual(lay["options"], [["later", "Later"], ["next", "Next"], ["now", "Now"]], got)
        self.assertEqual((lay["value"], lay["label"], lay["before"]), ("later", "Urgency", True), got)
        self.assertEqual(got["reopened"], "later", got)
        self.assertEqual(got["afterNext"], {"first": "Jump the queue", "urgency": "later", "open": True, "blError": ""}, got)
        self.assertEqual(got["afterNow"], {"blError": ""}, got)
        self.assertEqual(got["posts"], [{"op": "add", "text": "Jump the queue", "urgency": "next"},
                                        {"op": "add", "text": "Start this now", "urgency": "now"}], got)
        scrum = self.repo / "scrum"
        self.assertEqual((scrum / "backlog.md").read_text(), "# Backlog\n- [ ] Jump the queue {p:5}\n" + BACKLOG[len("# Backlog\n"):])
        job = json.loads((scrum / "board.json").read_text())["jobs"][-1]
        self.assertEqual((job["title"], job["stage"]), ("Start this now", "spec"), got)
        self.assertEqual((scrum / "jobs" / job["id"] / "feature.md").read_text(), "Start this now\n")
        self.assertEqual(self.spawn.call_args.args[2:], (job["id"], "start", f"/trevskills-scrum start {job['id']}"))
        self.assertIn(self.repo.name, self.spawn.call_args.args[0])
        self.assertTrue(self.estimate.called)  # Next with no points still gets the estimate
        self.assertTrue(lay["inside"], got)
        self.assertLessEqual(lay["formScroll"], lay["formClient"], got)
        self.assertLessEqual(lay["docScroll"], lay["docClient"], got)
        self.assertEqual(len(set(lay["tops"])), 1, got)  # urgency, points, input and + on one row
        return lay

    def test_urgency_desktop(self):
        self.check(self.browse(1440))

    def test_urgency_390px(self):
        lay = self.check(self.browse(390))
        self.assertGreaterEqual(lay["height"], 44, lay)
        self.assertGreaterEqual(lay["width"], 44, lay)
        self.assertEqual(lay["font"], "16px", lay)


if __name__ == "__main__":
    unittest.main()
