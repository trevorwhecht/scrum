import json, os, re, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

PROJECT = "prio-repo"
SAME = "Same text for the height check"
BACKLOG = ("# Backlog\n"
           f"- [ ] {SAME} {{p:5}}\n"
           f"- [ ] {SAME} {{p:2}}\n"
           f"- [ ] {SAME}\n")

SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const page = await browser.newPage({viewport: {width: +process.env.WIDTH, height: 844}});
    await page.goto(process.env.DASH_URL);
    await page.waitForSelector(".card[data-key]");
    await page.click("#backlogBtn");
    await page.waitForSelector("#blList li[data-i]");
    const got = await page.evaluate(() => {
      const list = document.getElementById("blList");
      return {rows: [...list.querySelectorAll(":scope > li[data-i]")].map(li => ({
                chips: [...li.querySelectorAll(".badge,.lanechip")].map(c => ({tag: c.tagName, cls: c.className, text: c.textContent})),
                value: li.querySelector("textarea").value, height: li.getBoundingClientRect().height,
                chipBeforeTextarea: (c => !c || !!(c.compareDocumentPosition(li.querySelector("textarea")) & 4))(li.querySelector(".badge,.lanechip")),
                chipAfterSelect: (c => !c || !!(li.querySelector("select").compareDocumentPosition(c) & 4))(li.querySelector(".badge,.lanechip"))})),
              bad: [0, 6, "3", 2.5, null, undefined].map(p => prioTag({priority: p})),
              listScroll: list.scrollWidth, listClient: list.clientWidth};
    });
    console.log(JSON.stringify(got));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DashboardBacklogPriorityBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "home"
        user, managed, repo = home / ".claude", Path(self.tmp.name) / "managed", home / PROJECT
        for d in (user, managed, repo / "scrum" / "jobs" / "001-done"):
            d.mkdir(parents=True)
        (home / ".claude.json").write_text("{}")
        (repo / "scrum" / "backlog.md").write_text(BACKLOG)
        (repo / "scrum" / "board.json").write_text(json.dumps({"jobs": [
            {"id": "001-done", "title": "Done", "stage": "done", "files": []}]}))
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text(json.dumps([str(repo)]))
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(user), CLAUDE_MANAGED_DIR=str(managed), SCRUM_REGISTRY=str(registry))
        patcher.start()
        self.addCleanup(patcher.stop)
        import serve  # noqa: E402
        status = mock.patch.object(serve.route, "status", return_value={"codex": {"5h": 1, "weekly": 1},
                                                                         "claude_exhausted_until": None})
        status.start()
        self.addCleanup(status.stop)
        spawn = mock.patch.object(serve, "spawn")
        spawn.start()
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

    def check(self, width):
        got = self.browse(width)
        five, two, none = got["rows"]
        self.assertEqual(five["chips"], [{"tag": "SPAN", "cls": "badge", "text": "P5"}], got)
        self.assertEqual(two["chips"], [{"tag": "SPAN", "cls": "lanechip", "text": "P2"}], got)
        self.assertEqual(none["chips"], [], got)
        for r in got["rows"]:
            self.assertEqual(r["value"], SAME, got)  # chip text never enters the textarea
            self.assertTrue(r["chipBeforeTextarea"] and r["chipAfterSelect"], got)
        self.assertLessEqual(five["height"], none["height"], got)
        self.assertLessEqual(two["height"], none["height"], got)
        self.assertLessEqual(got["listScroll"], got["listClient"], got)
        self.assertEqual(got["bad"], [""] * 6, got)

    def test_chip_rendered_for_rated_only(self):
        self.check(1440)

    def test_chip_rated_row_no_taller_at_390px(self):
        self.check(390)

    def test_no_new_hex_colour_in_chip_css(self):
        css = "\n".join(l for l in (ROOT / "skills/trevskills-scrum/dashboard.html").read_text().splitlines()
                        if "#blList .badge" in l)
        self.assertIn("flex:none", css)
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b(?!\s*[.,>{\[:])", css.replace("#blList", "")), css)


if __name__ == "__main__":
    unittest.main()
