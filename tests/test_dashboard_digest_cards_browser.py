import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

# Drives the real dashboard in headless Chromium at a phone-sized 390x844 viewport, against a real serve.py. Prints one
# JSON line: {"skip": why} when Playwright or Chromium is missing, else what the digest card measured or showed.
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    await page.goto(process.env.DASH_URL);
    await page.waitForSelector(".dcard button[data-decide]");
    if (process.env.MODE === "layout") {
      const got = await page.evaluate(() => {
        const box = el => { const r = el.getBoundingClientRect(); return {left: r.left, right: r.right, height: r.height}; };
        const card = document.querySelector(".dcard");
        return {scrollWidth: document.documentElement.scrollWidth, cards: document.querySelectorAll(".dcard").length,
                card: box(card), target: card.querySelector(".kid").textContent,
                targetOverflow: card.querySelector(".kid").scrollWidth - card.querySelector(".kid").clientWidth,
                approve: box(card.querySelector('[data-decide="approve"]')), reject: box(card.querySelector('[data-decide="reject"]'))};
      });
      console.log(JSON.stringify(got));
      return;
    }
    await page.click('.dcard [data-decide="approve"]');
    await page.waitForFunction(() => document.querySelector(".dcard .error")?.textContent);
    const look = () => page.evaluate(() => {
      const card = document.querySelector(".dcard");
      return card && {cards: document.querySelectorAll(".dcard").length, role: card.querySelector(".error").getAttribute("role"),
        error: card.querySelector(".error").textContent, disabled: [...card.querySelectorAll("button")].map(b => b.disabled)};
    });
    const first = await look();
    await page.waitForTimeout(2600);  // past one 2 s poll cycle
    const later = await look();
    console.log(JSON.stringify({first, later}));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DigestCardsBrowserTest(unittest.TestCase):
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

    def propose(self, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("old line\n")
        self.proposals.write_text(json.dumps({"proposals": [{"id": "p1", "target": str(target), "why": "Seen in 001-a and 002-b.",
                                                             "old": "old line", "new": "new line", "obvious": False,
                                                             "obvious_reason": "one job only"}]}))

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

    def test_card_fits_390px(self):
        target = self.reg / "agents" / ("scrum-" + "very-long-agent-name-without-any-spaces-" * 3 + "x.md")
        self.assertGreaterEqual(len(str(target)), 80)
        self.assertNotIn(" ", str(target))
        self.propose(target)
        got = self.browse("layout")
        self.assertEqual((got.get("cards"), got.get("target")), (1, str(target)), got)
        self.assertLessEqual(got["scrollWidth"], 390, got)
        self.assertLessEqual(got["card"]["right"], 390, got)
        self.assertLessEqual(got["targetOverflow"], 0, got)  # the long path wraps inside the card, not clipped past it
        for name in ("approve", "reject"):
            self.assertGreaterEqual(got[name]["left"], 0, got)
            self.assertLessEqual(got[name]["right"], 390, got)
            self.assertGreaterEqual(got[name]["height"], 44, got)

    def test_failed_post_shows_error_and_reenables(self):
        self.propose(self.reg / ".claude" / "settings.json")
        got = self.browse("fail")
        expected = {"cards": 1, "role": "alert", "error": "target is not editable", "disabled": [False, False]}
        self.assertEqual(got.get("first"), expected, got)
        self.assertEqual(got.get("later"), expected, got)
        self.assertEqual([p.get("status", "pending") for p in json.loads(self.proposals.read_text())["proposals"]], ["pending"])
        self.assertEqual((self.reg / ".claude" / "settings.json").read_text(), "old line\n")


if __name__ == "__main__":
    unittest.main()
