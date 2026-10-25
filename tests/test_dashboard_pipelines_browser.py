import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

# Drives the Pipelines modal in headless Chromium against a real serve.py (agents come from this repo's agents/).
# Prints one JSON line: {"skip": why} when Playwright or Chromium is missing, else what MODE measured.
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const mode = process.env.MODE;
    const page = await browser.newPage({viewport: mode === "phone" ? {width: 390, height: 844} : {width: 1440, height: 900}});
    await page.goto(process.env.DASH_URL);
    await page.click("#agentsBtn");
    await page.waitForSelector('#pipeTabs [data-tab="fast"]:visible');
    const open = async (tab, z) => {
      await page.click(`#pipeTabs [data-tab="${tab}"]`);
      await page.evaluate(z => setZoom(z), z);
      await page.waitForSelector('#flow [data-agent="scrum-builder"]');
      await page.waitForTimeout(50);
    };
    if (mode === "loop") {
      const out = [];
      for (const tab of ["fast", "standard"]) for (const z of [50, 80, 100, 150]) {
        await open(tab, z);
        out.push(await page.evaluate(([tab, z]) => {
          const flow = document.getElementById("flow"), loop = flow.querySelector(".loop");
          const node = n => flow.querySelector(`[data-agent="${n}"]`), from = node(loop.dataset.from);
          const mid = n => n.offsetTop + n.offsetHeight / 2;
          return {tab, z, from: loop.dataset.from, top: loop.offsetTop, bottom: loop.offsetTop + loop.offsetHeight,
                  builderMid: mid(node("scrum-builder")), fromMid: mid(from)};
        }, [tab, z]));
      }
      console.log(JSON.stringify(out));
      return;
    }
    await open("fast", 100);
    console.log(JSON.stringify(await page.evaluate(() => {
      const flow = document.getElementById("flow"), lanes = flow.querySelector(":scope>.lanes");
      const box = el => { const r = el.getBoundingClientRect(); return {left: r.left, right: r.right, top: r.top, width: r.width}; };
      const kids = [...lanes.children];
      return {check: box(kids.find(k => k.textContent.includes("Check gate"))), promote: box(kids.find(k => k.textContent.includes("→ Standard"))),
              row: box(lanes), builder: box(flow.querySelector('[data-agent="scrum-builder"]')), flow: box(flow),
              scrollWidth: flow.scrollWidth, clientWidth: flow.clientWidth};
    })));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DashboardPipelinesBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "home"
        user, managed, repo = home / ".claude", Path(self.tmp.name) / "managed", home / "proj"
        for d in (user, managed, repo / "scrum"):
            d.mkdir(parents=True)
        (home / ".claude.json").write_text("{}")
        (repo / "scrum" / "board.json").write_text(json.dumps({"jobs": []}))
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text(json.dumps([str(repo)]))
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(user), CLAUDE_MANAGED_DIR=str(managed), SCRUM_REGISTRY=str(registry),
                                  SCRUM_AGENTS_DIR=str(ROOT / "agents"))
        patcher.start()
        self.addCleanup(patcher.stop)
        import serve  # noqa: E402
        status = mock.patch.object(serve.route, "status", return_value={"codex": {"5h": 42, "weekly": 17},
                                                                         "claude_exhausted_until": None})
        status.start()
        self.addCleanup(status.stop)
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def browse(self, mode):
        env = dict(os.environ, MODE=mode, DASH_URL=f"http://127.0.0.1:{self.server.server_address[1]}/dashboard.html")
        if "NODE_PATH" not in env:
            npm = shutil.which("npm")
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip() if npm else ""
            env["NODE_PATH"] = root or "/opt/node22/lib/node_modules"
        out = subprocess.run([self.node, "-e", SCRIPT], capture_output=True, text=True, env=env, timeout=120).stdout
        got = json.loads(out.strip().splitlines()[-1])
        if isinstance(got, dict) and "skip" in got:
            raise unittest.SkipTest(got["skip"])
        self.assertNotIn("error", got, got)
        return got

    def test_fast_row_width_1440(self):
        got = self.browse("wide")
        for k in ("check", "promote"):
            self.assertLessEqual(got[k]["width"], 360, got)
        self.assertEqual(got["check"]["top"], got["promote"]["top"], got)  # side by side on one line
        self.assertLessEqual(got["check"]["right"], got["promote"]["left"], got)
        row_mid = (got["check"]["left"] + got["promote"]["right"]) / 2
        builder_mid = (got["builder"]["left"] + got["builder"]["right"]) / 2
        self.assertAlmostEqual(row_mid, builder_mid, delta=2, msg=got)

    def test_fast_row_390(self):
        got = self.browse("phone")
        self.assertLessEqual(got["scrollWidth"], got["clientWidth"], got)
        for k in ("check", "promote"):
            self.assertGreaterEqual(got[k]["left"], got["flow"]["left"] - 0.5, got)
            self.assertLessEqual(got[k]["right"], got["flow"]["right"] + 0.5, got)

    def test_loop_aligned_at_zooms(self):
        got = self.browse("loop")
        self.assertEqual([(g["tab"], g["z"]) for g in got],
                         [(t, z) for t in ("fast", "standard") for z in (50, 80, 100, 150)])
        for g in got:
            self.assertEqual(g["from"], {"fast": "scrum-review-code", "standard": "scrum-approver"}[g["tab"]], g)
            self.assertAlmostEqual(g["top"] + 1, g["builderMid"], delta=2, msg=g)
            self.assertAlmostEqual(g["bottom"] - 1, g["fromMid"], delta=2, msg=g)


if __name__ == "__main__":
    unittest.main()
