import json, os, shutil, subprocess, unittest

import test_dashboard_mobile_390_browser as base

IDS = ("cooldown", "rankBtn", "volume", "backlogBtn", "digestBtn", "agentsBtn", "aiBtn", "checksBtn")

# Same real-serve.py harness as test_dashboard_mobile_390_browser.py; this script waits for the full header, then runs
# the BODY snippet (an async function body given `page`) and prints what it returns as one JSON line.
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const page = await browser.newPage({viewport: {width: +process.env.WIDTH, height: 844}});
    page.setDefaultTimeout(120000);
    await page.goto(process.env.DASH_URL);
    await page.waitForSelector(".card[data-key]");
    await page.waitForFunction(() => !document.getElementById("cooldown").hidden && !document.getElementById("checksBtn").hidden
      && document.querySelectorAll("#aiUsage .grp").length === 2 && document.querySelectorAll("#machine .grp").length === 2);
    const out = await (new (Object.getPrototypeOf(async function () {}).constructor)("page", process.env.BODY))(page);
    console.log(JSON.stringify(out));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""

# Node-side helpers for BODY: `ev(fn, arg)` runs fn in the page; `shown()` says which menu buttons are visible.
SHOWN = """const ev = (f, a) => page.evaluate(f, a); const ids = %s;
  const shown = () => ev(ids => Object.fromEntries(ids.map(i => [i, document.getElementById(i).checkVisibility()])), ids);
  const exp = () => ev(() => document.getElementById("menuBtn").getAttribute("aria-expanded"));""" % json.dumps(IDS)


class HeaderMenu(unittest.TestCase):
    setUp = base.DashboardMobile390BrowserTest.setUp

    def run_js(self, width, body):
        body = SHOWN + body.replace(SHOWN, "")
        env = dict(os.environ, WIDTH=str(width), BODY=body, DASH_URL=f"http://127.0.0.1:{self.server.server_address[1]}/dashboard.html")
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

    def test_buttons_hidden_until_menu_open(self):
        got = self.run_js(390, SHOWN + """return {shown: await shown(), ...await ev(() => ({menuBtn: document.getElementById("menuBtn").checkVisibility(),
          filters: ["filter", "laneFilter", "machine", "aiUsage", "status"].map(i => document.getElementById(i).checkVisibility()),
          h1: document.querySelector("h1").checkVisibility(), scroll: document.documentElement.scrollWidth,
          menuBtnH: document.getElementById("menuBtn").getBoundingClientRect().height,
          attrs: ["aria-haspopup", "aria-expanded", "aria-controls"].map(a => document.getElementById("menuBtn").getAttribute(a))}))}""")
        self.assertEqual(set(got["shown"].values()), {False}, got)
        self.assertTrue(got["menuBtn"] and got["h1"] and all(got["filters"]), got)
        self.assertLessEqual(got["scroll"], 390, got)
        self.assertGreaterEqual(got["menuBtnH"], 44, got)
        self.assertEqual(got["attrs"], ["true", "false", "menu"], got)

    def test_menu_open_close_and_action(self):
        got = self.run_js(390, SHOWN + """const r = {};
          await page.click("#menuBtn");
          r.open = {exp: await exp(), shown: await shown(), ...await ev(ids => ({heights: ids.map(i => document.getElementById(i).getBoundingClientRect().height),
            tops: ids.map(i => document.getElementById(i).closest("#menu > *").getBoundingClientRect().top), scroll: document.documentElement.scrollWidth,
            rights: ids.map(i => document.getElementById(i).getBoundingClientRect().right)}), ids)};
          await page.click("#menuBtn"); r.toggled = {exp: await exp(), shown: await shown()};
          await page.click("#menuBtn"); await page.keyboard.press("Escape");
          r.escaped = {exp: await exp(), shown: await shown(), focus: await ev(() => document.activeElement.id)};
          await page.click("#menuBtn"); await page.click("#backlogBtn");
          r.action = {exp: await exp(), shown: await shown(), dialog: await ev(() => document.getElementById("backlog").open)};
          return r;""")
        self.assertEqual(got["open"]["exp"], "true", got)
        self.assertEqual(set(got["open"]["shown"].values()), {True}, got)
        self.assertTrue(all(h >= 44 for h in got["open"]["heights"]), got)
        self.assertEqual(len(set(got["open"]["tops"])), len(IDS), got)  # one per row
        self.assertTrue(all(r <= 390 for r in got["open"]["rights"]) and got["open"]["scroll"] <= 390, got)
        for k in ("toggled", "escaped", "action"):
            self.assertEqual((got[k]["exp"], set(got[k]["shown"].values())), ("false", {False}), (k, got))
        self.assertEqual(got["escaped"]["focus"], "menuBtn", got)
        self.assertTrue(got["action"]["dialog"], got)

    def test_desktop_has_no_hamburger(self):
        for width in (1400, 800):
            got = self.run_js(width, SHOWN + """return {shown: await shown(), ...await ev(() => ({menuBtn: document.getElementById("menuBtn").checkVisibility(),
              display: getComputedStyle(document.getElementById("menu")).display}))}""")
            self.assertFalse(got["menuBtn"], (width, got))
            self.assertEqual(got["display"], "contents", (width, got))
            self.assertEqual(set(got["shown"].values()), {True}, (width, got))

    def test_ai_usage_bars_aligned_390(self):
        got = self.run_js(390, """return await ev(() => { const box = el => { const r = el.getBoundingClientRect(); return [r.left, r.width, r.top]; };
          return {bars: [...document.querySelectorAll("#aiUsage .bar")].map(box),
            groups: [...document.querySelectorAll("#aiUsage .grp")].map(g => ({ttl: box(g.querySelector(".ttl")), reads: [...g.querySelectorAll(".rd")].map(box),
              firstBar: box(g.querySelector(".bar")), rows: [...g.querySelectorAll(".acct")].map(box)})),
            scroll: document.documentElement.scrollWidth}})""")
        self.assertEqual(len(got["bars"]), 4, got)
        for b in got["bars"]:
            self.assertAlmostEqual(b[0], got["bars"][0][0], delta=1, msg=got)
            self.assertAlmostEqual(b[1], got["bars"][0][1], delta=1, msg=got)
        for g in got["groups"]:
            self.assertGreater(len(g["reads"]), 1, got)
            self.assertEqual({round(r[0]) for r in g["reads"]}, {round(g["reads"][0][0])}, got)
            self.assertLessEqual(g["ttl"][2] + 1, g["firstBar"][2], got)  # the title sits above the first bar, clear of it
            self.assertEqual(len({round(r[2]) for r in g["rows"]}), len(g["rows"]), got)  # one account or window per line
        self.assertLessEqual(got["scroll"], 390, got)

    def test_meters_no_overlap_390(self):
        got = self.run_js(390, """return await ev(() => { const box = el => { const r = el.getBoundingClientRect(); return {id: el.className || el.id, l: r.left, r: r.right, t: r.top, b: r.bottom}; };
          const rings = [...document.querySelectorAll("#machine .grp:first-child .ring")].map(box);
          const vis = els => els.filter(e => e.getClientRects().length).map(box), grps = [...document.querySelectorAll("#machine .grp, #aiUsage .grp")];
          return {rings, sets: [vis(grps), ...grps.map(g => vis([...g.children]))]}})""")
        self.assertEqual(len(got["rings"]), 2, got)
        self.assertAlmostEqual(got["rings"][0]["t"], got["rings"][1]["t"], delta=1, msg=got)
        for kids in got["sets"]:  # siblings: the groups among themselves, then each group's own children
            for i, a in enumerate(kids):
                for b in kids[i + 1:]:
                    self.assertFalse(a["l"] < b["r"] - 0.5 and b["l"] < a["r"] - 0.5 and a["t"] < b["b"] - 0.5 and b["t"] < a["b"] - 0.5, (a, b))
