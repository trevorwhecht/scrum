import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

AGENT = "---\nname: scrum-builder\ndescription: Builds the spec.\nmodel: opus\n---\n\n# Builder heading\n\nSome **bold** text.\n"

# Loads the real dashboard, served with its real Content-Security-Policy header, in headless Chromium and opens the
# Agents dialog on one agent, whose body goes through marked.parse. Prints one JSON line: {"skip": why} when Playwright
# or Chromium is missing, else every securitypolicyviolation seen and whether marked.js loaded.
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const page = await browser.newPage();
    await page.addInitScript(() => {
      window.__cspViolations = [];
      document.addEventListener("securitypolicyviolation", e => window.__cspViolations.push(
        {directive: e.violatedDirective, blocked: e.blockedURI, sample: e.sample}));
    });
    const failed = [];
    page.on("requestfailed", r => failed.push(r.url()));
    const res = await page.goto(process.env.DASH_URL, {waitUntil: "load"});
    const csp = res.headers()["content-security-policy"] || null;
    let stepError = null;  // a page the policy broke may never show the dialog; still report what the policy blocked
    try {
      await page.click("#agentsBtn", {timeout: 5000});
      await page.click('#flow [data-agent="scrum-builder"]', {timeout: 5000});
      await page.waitForSelector("#agDetail .md", {timeout: 5000});
      await page.waitForTimeout(200);
    } catch (e) { stepError = String(e.message).split("\n")[0]; }
    const got = await page.evaluate(() => ({violations: window.__cspViolations, marked: typeof window.marked !== "undefined",
      heading: document.querySelector("#agDetail .md h1")?.textContent ?? null}));
    console.log(JSON.stringify({...got, csp, stepError, cdnFailed: failed.some(u => u.includes("cdnjs.cloudflare.com"))}));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DashboardCspBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        agents = Path(self.tmp.name) / "agents"
        agents.mkdir()
        (agents / "scrum-builder.md").write_text(AGENT)
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text("[]")
        patcher = mock.patch.dict(os.environ, SCRUM_AGENTS_DIR=str(agents), SCRUM_REGISTRY=str(registry))
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

    def test_dashboard_and_agents_dialog_load_without_csp_violations(self):
        got = self.browse()
        self.assertNotIn("error", got, got)
        self.assertIn("script-src", got["csp"] or "", got)  # the policy under test was really in force
        self.assertEqual(got["violations"], [], got)
        self.assertIsNone(got["stepError"], got)
        if not got["cdnFailed"]:  # offline, marked.js can't load; a CSP block of it would still show as a violation
            self.assertTrue(got["marked"], got)
            self.assertEqual(got["heading"], "Builder heading", got)


if __name__ == "__main__":
    unittest.main()
