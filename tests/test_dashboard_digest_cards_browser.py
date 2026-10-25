import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

# Drives the real dashboard in headless Chromium at a phone-sized 390x844 viewport, against a real serve.py. Prints one
# JSON line: {"skip": why} when Playwright or Chromium is missing, else what the Digest dialog's row measured or showed.
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    await page.goto(process.env.DASH_URL);
    await page.waitForFunction(() => document.querySelector("#dgProject") && typeof loadDigests === "function");
    await page.click("#digestBtn");
    await page.waitForSelector("#dgList .prop button[data-revert]");
    if (process.env.MODE === "layout") {
      const got = await page.evaluate(() => {
        const box = el => { const r = el.getBoundingClientRect(); return {left: r.left, right: r.right, height: r.height}; };
        const row = document.querySelector("#dgList .prop"), path = row.querySelector(".path");
        return {scrollWidth: document.documentElement.scrollWidth, rows: document.querySelectorAll("#dgList .prop").length,
                row: box(row), target: path.textContent, targetOverflow: path.scrollWidth - path.clientWidth,
                revert: box(row.querySelector("button[data-revert]")), cards: document.querySelectorAll("#board .card").length};
      });
      console.log(JSON.stringify(got));
      return;
    }
    await page.click("#dgList .prop button[data-revert]");
    if (process.env.MODE === "ok") {
      await page.waitForSelector("#dgList .prop .chip.reverted");
      console.log(JSON.stringify(await page.evaluate(() => {
        const row = document.querySelector("#dgList .prop");
        return {chip: row.querySelector(".chip").textContent, buttons: row.querySelectorAll("button[data-revert]").length};
      })));
      return;
    }
    await page.waitForFunction(() => document.querySelector("#dgList .prop .error")?.textContent);
    const look = () => page.evaluate(() => {
      const row = document.querySelector("#dgList .prop"), b = row.querySelector("button[data-revert]");
      return {role: row.querySelector(".error").getAttribute("role"), error: row.querySelector(".error").textContent,
              disabled: b.disabled, chip: row.querySelector(".chip").textContent};
    });
    const first = await look();
    await page.waitForTimeout(2600);  // past one 2 s poll cycle
    const later = await look();
    console.log(JSON.stringify({first, later}));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""




class DigestLogBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "home"
        self.user, managed, self.reg = home / ".claude", Path(self.tmp.name) / "managed", home / "reg"
        for d in (self.user, managed, self.reg / "scrum" / "digests" / "001"):
            d.mkdir(parents=True)
        (home / ".claude.json").write_text("{}")
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text(json.dumps([str(self.reg)]))
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(self.user), CLAUDE_MANAGED_DIR=str(managed), SCRUM_REGISTRY=str(registry))
        patcher.start()
        self.addCleanup(patcher.stop)
        import serve  # noqa: E402
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.proposals = self.reg / "scrum" / "digests" / "001" / "proposals.json"

    def propose(self, target, text):
        """One applied proposal for target, whose file now holds text."""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        self.proposals.write_text(json.dumps({"proposals": [{"id": "p1", "target": str(target), "why": "Seen in 001-a and 002-b.",
                                                             "old": "old line", "new": "new line", "status": "applied"}]}))

    def browse(self, mode):
        env = dict(os.environ, MODE=mode, DASH_URL=f"http://127.0.0.1:{self.server.server_address[1]}/dashboard.html")
        if "NODE_PATH" not in env:
            npm = shutil.which("npm")
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip() if npm else ""
            env["NODE_PATH"] = root or "/opt/node22/lib/node_modules"
        out = subprocess.run([self.node, "-e", SCRIPT], capture_output=True, text=True, env=env, timeout=120).stdout
        got = json.loads(out.strip().splitlines()[-1])
        if "skip" in got:
            raise unittest.SkipTest(got["skip"])
        return got

    def test_row_fits_390px(self):
        target = self.user / "rules" / ("very-long-rule-name-without-any-spaces-" * 3 + "x.md")
        self.assertGreaterEqual(len(str(target)), 80)
        self.assertNotIn(" ", str(target))
        self.propose(target, "new line\n")
        got = self.browse("layout")
        self.assertEqual((got.get("rows"), got.get("target")), (1, str(target)), got)
        self.assertEqual(got["cards"], 0, got)  # no Digest card on the board
        self.assertLessEqual(got["scrollWidth"], 390, got)
        self.assertLessEqual(got["row"]["right"], 390, got)
        self.assertLessEqual(got["targetOverflow"], 0, got)  # the long path wraps inside the row, not clipped past it
        self.assertGreaterEqual(got["revert"]["left"], 0, got)
        self.assertLessEqual(got["revert"]["right"], 390, got)
        self.assertGreaterEqual(got["revert"]["height"], 44, got)

    def test_failed_revert_shows_error_and_reenables(self):
        target = self.user / "rules" / "x.md"
        self.propose(target, "edited since\n")
        got = self.browse("fail")
        expected = {"role": "alert", "error": "old text found 0 times", "disabled": False, "chip": "applied"}
        self.assertEqual(got.get("first"), expected, got)
        self.assertEqual(got.get("later"), expected, got)
        self.assertEqual([p["status"] for p in json.loads(self.proposals.read_text())["proposals"]], ["applied"])
        self.assertEqual(target.read_text(), "edited since\n")

    def test_revert_success_refreshes(self):
        target = self.user / "rules" / "x.md"
        self.propose(target, "keep\nnew line\n")
        self.assertEqual(self.browse("ok"), {"chip": "reverted", "buttons": 0})
        self.assertEqual(target.read_text(), "keep\nold line\n")
        self.assertEqual([p["status"] for p in json.loads(self.proposals.read_text())["proposals"]], ["reverted"])


if __name__ == "__main__":
    unittest.main()
