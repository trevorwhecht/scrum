import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"  # no test run makes a sound

PROJECT = "a-very-long-project-name-for-the-phone-test"  # >= 30 characters, shown as a #filter option
FILES = ["feature.md", "spec.md", "build.md", "round-1/check.md", "round-1/review-code.md", "round-1/review-ui.md",
         "round-1/review-ux.md", "decision.md"]

# Drives the real dashboard in headless Chromium against a real serve.py. Prints one JSON line: {"skip": why} when
# Playwright or Chromium is missing, else what MODE measured (header, tabs, actions or desktop).
SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const mode = process.env.MODE, wide = mode === "desktop";
    const page = await browser.newPage({viewport: wide ? {width: 1280, height: 800} : {width: +process.env.WIDTH || 390, height: 844}});
    await page.goto(process.env.DASH_URL);
    await page.waitForSelector(".card[data-key]");
    if (mode === "header") {
      await page.waitForFunction(() => { const r = document.getElementById("routing"); return !r.hidden && r.textContent; });
      const got = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        routing: document.getElementById("routing").textContent,
        options: [...document.getElementById("filter").options].map(o => o.textContent),
        children: [...document.querySelector("header").children].filter(el => el.getClientRects().length)
          .map(el => { const r = el.getBoundingClientRect(); return {id: el.id || el.tagName, left: r.left, right: r.right}; })}));
      console.log(JSON.stringify(got));
      return;
    }
    if (mode === "options") {  // the modal's stop box (opened by clicking the card's title); cards carry no option buttons
      const boxes = sel => page.evaluate(s => [...document.querySelectorAll(s)].map(b => {
        const r = b.getBoundingClientRect(); return {text: b.textContent, top: r.top, left: r.left, right: r.right, bottom: r.bottom, height: r.height};
      }), sel);
      const card = await boxes(".card button");
      await page.click(".card[data-key] .title");
      await page.waitForFunction(() => document.getElementById("viewer").open && document.querySelector("#actions .stop button"));
      const modal = await boxes("#actions .stop button[data-answer], #actions .stop .note, #actions .stop > p");
      const fit = await page.evaluate(() => { const s = document.querySelector("#actions .stop"), v = document.getElementById("viewer");
        return {stop: s.scrollWidth <= s.clientWidth, viewer: v.scrollWidth <= v.clientWidth, right: s.getBoundingClientRect().right, width: innerWidth}; });
      console.log(JSON.stringify({card, modal, fit}));
      return;
    }
    if (mode === "kids") {  // a 12-child parent: its card's Load more, empty columns hidden, then the modal's own Load more
      const key = process.env.PARENT, sel = `.card[data-key="${key}"]`;
      const state = () => page.evaluate(s => {
        const more = document.querySelector("#board [data-kids-more]");
        return {lines: document.querySelectorAll(`${s} .meta.kid`).length, more: !!more,
                sibling: !!more && more.previousElementSibling === document.querySelector(s) && more.parentElement.matches(".col"),
                focused: !!document.activeElement?.matches("[data-kids-more]"), viewer: document.getElementById("viewer").open,
                build: document.querySelector('[data-col="build"]').getClientRects().length,
                running: document.querySelector('[data-col="running"]').getClientRects().length};
      }, sel);
      const board = [await state()];
      await page.click("#board [data-kids-more]");
      board.push(await state());
      await page.click("#board [data-kids-more]");
      board.push(await state());
      await page.reload();
      await page.waitForSelector(sel);
      await page.click(`${sel} .title`);
      await page.waitForFunction(() => document.getElementById("viewer").open && document.querySelector("#actions .kids"));
      const modal = () => page.evaluate(() => ({rows: document.querySelectorAll("#actions .kids .kid").length,
        more: !!document.querySelector("#actions .kids [data-kids-more]"), open: document.getElementById("viewer").open,
        key: document.getElementById("viewer").dataset.key}));
      const before = await modal();
      await page.click("#actions [data-kids-more]");
      console.log(JSON.stringify({board, modal: [before, await modal()]}));
      return;
    }
    await page.click(".card[data-key]");
    await page.waitForFunction(() => document.getElementById("viewer").open && document.querySelector("#tabs .close"));
    const measure = () => page.evaluate(() => {
      const tabs = document.getElementById("tabs"), close = tabs.querySelector(".close"), c = close.getBoundingClientRect();
      return {overflow: tabs.scrollWidth > tabs.clientWidth, paddingRight: getComputedStyle(tabs).paddingRight,
              marginLeft: getComputedStyle(close).marginLeft, position: getComputedStyle(close).position,
              tabsRight: tabs.getBoundingClientRect().right, build: document.querySelector('[data-col="build"]').getClientRects().length, close: {width: c.width, height: c.height, right: c.right},
              actions: [...document.querySelectorAll("#actions .btn, #actions summary")].filter(b => b.checkVisibility())
                .map(b => { const r = b.getBoundingClientRect(); return {text: b.textContent.trim(), height: r.height, width: r.width}; })};
    });
    const before = await measure();
    await page.evaluate(() => { const t = document.getElementById("tabs"); t.scrollLeft = t.scrollWidth; });
    await page.waitForTimeout(100);
    const after = await measure();
    console.log(JSON.stringify({before, after}));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class DashboardMobile390BrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "home"
        user, managed, repo = home / ".claude", Path(self.tmp.name) / "managed", home / PROJECT
        job = repo / "scrum" / "jobs" / "007-human"
        for d in (user, managed, job / "round-1"):
            d.mkdir(parents=True)
        for f in FILES:
            (job / f).write_text(f"# {f}\n")
        (home / ".claude.json").write_text("{}")
        self.board_path = repo / "scrum" / "board.json"
        self.board_path.write_text(json.dumps({"jobs": [
            {"id": "007-human", "title": "Needs a human", "stage": "needs-human", "reason": "review: CHANGES after 3 rounds",
             "worktree": str(repo), "tty": "ttys001", "files": FILES}]}))
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text(json.dumps([str(repo)]))
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(user), CLAUDE_MANAGED_DIR=str(managed), SCRUM_REGISTRY=str(registry),
                                  SCRUM_USAGE=str(home / "no-usage.json"))
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

    def browse(self, mode, width=None, **extra):
        env = dict(os.environ, **extra, MODE=mode, WIDTH=str(width or ""), DASH_URL=f"http://127.0.0.1:{self.server.server_address[1]}/dashboard.html")
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

    def test_header_fits_390px(self):
        got = self.browse("header")
        self.assertEqual(got["routing"], "Claude 5h — · wk — · Codex 5h 42% · wk 17%", got)
        self.assertIn(PROJECT, got["options"], got)
        self.assertGreaterEqual(len(PROJECT), 30)
        self.assertLessEqual(got["scrollWidth"], 390, got)
        ids = [c["id"] for c in got["children"]]
        for want in ("H1", "status", "routing", "filter", "laneFilter", "backlogBtn", "digestBtn", "agentsBtn", "aiBtn"):
            self.assertIn(want, ids, got)
        for c in got["children"]:
            self.assertGreaterEqual(c["left"], 0, c)
            self.assertLessEqual(c["right"], 390, c)

    def test_viewer_tabs_close_44_flush_right(self):
        got = self.browse("tabs")
        self.assertTrue(got["before"]["overflow"], got)
        for when in ("before", "after"):
            m = got[when]
            self.assertEqual(m["paddingRight"], "0px", (when, m))
            self.assertGreaterEqual(m["close"]["width"], 44, (when, m))
            self.assertGreaterEqual(m["close"]["height"], 44, (when, m))
            self.assertAlmostEqual(m["close"]["right"], m["tabsRight"], delta=1, msg=(when, m))

    def test_viewer_action_buttons_44px(self):
        actions = self.browse("actions")["before"]["actions"]
        self.assertEqual([a["text"] for a in actions],
                         ["Approve & merge", "Discuss first", "Send back to builder", "More"], actions)  # Abort sits inside More
        for a in actions:
            self.assertGreaterEqual(a["height"], 44, a)
            self.assertGreaterEqual(a["width"], 44, a)

    def test_viewer_tabs_desktop_unchanged(self):
        m = self.browse("desktop")["before"]
        self.assertEqual(m["paddingRight"], "10px", m)
        self.assertEqual(m["position"], "static", m)
        self.assertGreater(float(m["marginLeft"].removesuffix("px")), 0, m)  # margin-left:auto pushes the ✕ right
        self.assertAlmostEqual(m["close"]["right"], m["tabsRight"] - 10, delta=1, msg=m)  # 10 px padding after the ✕
        self.assertGreater(m["build"], 0, m)  # an empty column stays visible above 640 px

    def test_parent_card_load_more_390(self):
        board = json.loads(self.board_path.read_text())
        kids = [f"{n:03d}-kid" for n in range(21, 33)]
        board["jobs"] += [{"id": "020-run-all", "title": "Run all", "stage": "running", "children": kids, "files": ["feature.md"]}] + [
            {"id": k, "title": k, "stage": "waiting", "parent": "020-run-all", "depends_on": []} for k in kids]
        self.board_path.write_text(json.dumps(board))
        (self.board_path.parent / "jobs" / "020-run-all").mkdir()
        (self.board_path.parent / "jobs" / "020-run-all" / "feature.md").write_text("# feature\n")
        key = f"{PROJECT}/020-run-all"
        got = self.browse("kids", PARENT=key)
        first, second, third = got["board"]
        self.assertEqual((first["lines"], first["more"], first["sibling"], first["viewer"]), (5, True, True, False), got)
        self.assertEqual((first["build"], first["running"] > 0), (0, True), got)  # empty column hidden at 390 px
        self.assertEqual((second["lines"], second["more"], second["focused"], second["viewer"]), (10, True, True, False), got)
        self.assertEqual((third["lines"], third["more"], third["viewer"]), (12, False, False), got)
        before, after = got["modal"]
        self.assertEqual((before["rows"], before["more"]), (5, True), got)
        self.assertEqual((after["rows"], after["more"], after["open"], after["key"]), (10, True, True, key), got)

    def test_option_buttons_390px(self):
        board = json.loads(self.board_path.read_text())
        board["jobs"] = [{**board["jobs"][0], "id": "008-asked", "question": "Which way?", "reason": "blocked: pick one",
                          "recommend": {"key": "b", "why": "Small fix"},
                          "options": [{"key": "a", "label": "Ship it", "command": "approve 008-asked"},
                                      {"key": "b", "label": "Send it back with a much longer label", "command": 'rework 008-asked "again"'},
                                      {"key": "c", "label": "Drop it", "command": "abort 008-asked"}]}]
        self.board_path.write_text(json.dumps(board))
        for width in (390, 1440):
            with self.subTest(width=width):
                got = self.browse("options", width)
                self.assertEqual(got["card"], [])
                boxes = got["modal"]
                self.assertEqual([b["text"] for b in boxes], ["Which way?", "Send it back with a much longer label Recommended",
                                                              "Small fix", "Ship it", "Drop it"])
                self.assertTrue(got["fit"]["stop"] and got["fit"]["viewer"], got["fit"])
                self.assertLessEqual(got["fit"]["right"], got["fit"]["width"], got["fit"])
                for i, a in enumerate(boxes):
                    if a["text"] in ("Ship it", "Drop it") or a["text"].endswith(" Recommended"):
                        self.assertGreaterEqual(a["height"], 44, a)
                    for b in boxes[i + 1:]:
                        overlap = a["left"] < b["right"] and b["left"] < a["right"] and a["top"] < b["bottom"] and b["top"] < a["bottom"]
                        self.assertFalse(overlap, (a, b))

if __name__ == "__main__":
    unittest.main()
