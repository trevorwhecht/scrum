import json, os, random, re, shutil, subprocess, sys, tempfile, threading, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "skills" / "trevskills-scrum" / "dashboard.html"
BOARD_PY = ROOT / "skills" / "trevskills-scrum" / "board.py"


def node_eval(fn, args):
    """Run dashboard.html's esc and `fn` in node over each argument; return the list of results."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    start = text.index("const esc = ")
    esc = text[start:text.index("\n", start)]
    start = text.index(f"function {fn}(")
    body = text[start:text.index("\n}\n", start) + 2]
    script = f"{esc}\n{body}\nconsole.log(JSON.stringify({json.dumps(args)}.map(a => {fn}(a))));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


class RouteTags(unittest.TestCase):
    def test_one_tag_per_line_in_file_order(self):
        log = ('{"ts": "t", "role": "scrum-builder", "runner": "local", "model": "qwen2.5-coder:7b", "duration_s": 12.5, "outcome": "invalid-artifact"}\n'
               '{"ts": "t", "role": "scrum-builder", "runner": "cloud", "model": null, "duration_s": 300.0, "outcome": "fallback"}\n'
               '{"role": "codex-review", "runner": "skip"}\n')
        self.assertEqual(node_eval("routeTags", [log]), [
            '<span class="row">'
            '<span class="chip rt local" title="qwen2.5-coder:7b · 12.5s · invalid-artifact">builder local</span>'
            '<span class="chip rt cloud" title="— · 300s · fallback">builder cloud</span>'
            '<span class="chip rt" title="— · —s · —">codex-review skip</span>'
            '</span>'])

    def test_empty_or_malformed_log_renders_nothing(self):
        self.assertEqual(node_eval("routeTags", ["", "not json\n", "\n\n", "null\n42\n[]\n", '{"role": "x"}\n{"runner": "local"}\n']),
                         ["", "", "", "", ""])

    def test_skips_bad_lines_between_good_ones(self):
        log = 'garbage\n\n{"role": "estimator", "runner": "cloud", "model": "sonnet", "duration_s": 4.2, "outcome": "ok"}\n{"runner": "local"}\n'
        self.assertEqual(node_eval("routeTags", [log]),
                         ['<span class="row"><span class="chip rt cloud" title="sonnet · 4.2s · ok">estimator cloud</span></span>'])

    def test_values_are_escaped(self):
        log = json.dumps({"role": "<script>alert(1)</script>", "runner": '"><img src=x>', "model": "a&b", "duration_s": 1,
                          "outcome": "<b>"}) + "\n"
        self.assertEqual(node_eval("routeTags", [log]), [
            '<span class="row"><span class="chip rt" title="a&amp;b · 1s · &lt;b&gt;">'
            '&lt;script&gt;alert(1)&lt;/script&gt; &quot;&gt;&lt;img src=x&gt;</span></span>'])


class RoutingText(unittest.TestCase):
    def test_readout(self):
        self.assertEqual(node_eval("routingText", [
            {"codex": {"5h": 42, "weekly": 61.4}, "ollama": "up"},
            {"codex": {"5h": None, "weekly": None}, "ollama": "down"},
            {"ollama": "up"}]), [
            "Codex 5h 42% · wk 61% · Ollama up",
            "Codex 5h — · wk — · Ollama down",
            "Codex 5h — · wk — · Ollama up"])


# Drives the real dashboard in headless Chromium against a real serve.py. Prints one JSON line: {"skip": why} when
# Playwright or Chromium is missing, else the Done column's card ids and Load more state after each step.
COLUMNS_SCRIPT = r"""
let chromium;
try { ({chromium} = require("playwright")); } catch (e) { console.log(JSON.stringify({skip: "playwright module not found"})); process.exit(0); }
(async () => {
  let browser;
  try { browser = await chromium.launch(); } catch (e) { console.log(JSON.stringify({skip: "chromium failed to launch: " + String(e.message).split("\n")[0]})); return; }
  try {
    const page = await browser.newPage({viewport: {width: 1600, height: 900}});
    await page.goto(process.env.DASH_URL);
    await page.waitForSelector('[data-col="done"] .card');
    const look = () => page.evaluate(() => {
      const ids = col => [...document.querySelectorAll(`[data-col="${col}"] .card .id`)].map(e => e.textContent);
      return {done: ids("done"), build: ids("build"), more: !!document.querySelector('[data-col="done"] [data-more]'),
              header: document.querySelector('[data-col="done"] h2').textContent,
              focus: document.activeElement?.matches("[data-more]") ? "more" : document.activeElement?.querySelector?.(".id")?.textContent || ""};
    });
    const first = await look();
    await page.click('[data-col="done"] [data-more]');
    const second = await look();
    await page.waitForTimeout(2600);  // past one 2 s poll re-render
    const polled = await look();
    await page.click('[data-col="done"] [data-more]');
    const third = await look();
    console.log(JSON.stringify({first, second, polled, third}));
  } finally { await browser.close(); }
})().catch(e => { console.log(JSON.stringify({error: String(e.stack)})); });
"""


class ColumnsBrowserTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            raise unittest.SkipTest("node not on PATH")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(os.path.realpath(self.tmp.name)) / "home"
        self.user, managed, self.reg = home / ".claude", Path(self.tmp.name) / "managed", home / "reg"
        for d in (self.user, managed, self.reg / "scrum" / "jobs"):
            d.mkdir(parents=True)
        (home / ".claude.json").write_text("{}")
        registry = Path(self.tmp.name) / "projects.json"
        registry.write_text(json.dumps([str(self.reg)]))
        patcher = mock.patch.dict(os.environ, CLAUDE_HOME=str(self.user), CLAUDE_MANAGED_DIR=str(managed),
                                  SCRUM_REGISTRY=str(registry), SCRUM_MUTE="1")
        patcher.start()
        self.addCleanup(patcher.stop)
        sys.path.insert(0, str(BOARD_PY.parent))
        import serve  # noqa: E402
        self.server = serve.make_server(0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_columns_newest_first_and_done_load_more(self):
        # 25 finished jobs (every 5th aborted) and 3 in build, written to board.json in shuffled order.
        jobs = [{"id": f"{n:03d}-done", "title": f"Done {n}", "stage": "aborted" if n % 5 == 0 else "done",
                 "updatedAt": f"2026-01-01T00:{n:02d}:00Z"} for n in range(1, 26)]
        jobs += [{"id": f"{n:03d}-build", "title": f"Build {n}", "stage": "build",
                  "updatedAt": t} for n, t in ((26, "2026-01-02T10:00:00Z"), (27, "2026-01-02T12:00:00Z"), (28, "2026-01-02T11:00:00Z"))]
        random.Random(7).shuffle(jobs)
        (self.reg / "scrum" / "board.json").write_text(json.dumps({"jobs": jobs}))
        env = dict(os.environ, DASH_URL=f"http://127.0.0.1:{self.server.server_address[1]}/dashboard.html")
        if "NODE_PATH" not in env:
            npm = shutil.which("npm")
            root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip() if npm else ""
            env["NODE_PATH"] = root or "/opt/node22/lib/node_modules"
        out = subprocess.run([self.node, "-e", COLUMNS_SCRIPT], capture_output=True, text=True, env=env, timeout=120).stdout
        got = json.loads(out.strip().splitlines()[-1])
        if "skip" in got:
            raise unittest.SkipTest(got["skip"])
        newest = [f"{n:03d}-done" for n in range(25, 0, -1)]
        self.assertEqual(got["first"]["done"], newest[:10], got)
        self.assertEqual(got["first"]["build"], ["027-build", "028-build", "026-build"], got)
        self.assertTrue(got["first"]["more"], got)
        self.assertIn("· 25", got["first"]["header"])
        self.assertEqual((got["second"]["done"], got["second"]["more"], got["second"]["focus"]), (newest[:20], True, "more"), got)
        self.assertEqual((got["polled"]["done"], got["polled"]["more"]), (newest[:20], True), got)
        self.assertEqual((got["third"]["done"], got["third"]["more"]), (newest, False), got)
        self.assertEqual(got["third"]["focus"], "005-done", got)  # the first card the last click revealed
        self.assertIn("· 25", got["third"]["header"])

    def test_resume_prefixes_match_board(self):
        sys.path.insert(0, str(BOARD_PY.parent))
        import board  # noqa: E402
        m = re.search(r"^const RESUMABLE = (\[.*?\]);$", DASHBOARD.read_text(), re.M)
        self.assertIsNotNone(m)
        self.assertEqual(tuple(json.loads(m.group(1))), board.RESUMABLE)
        self.assertEqual(board.RESUMABLE, ("stalled in ", "bigboy off track", "bigboy review: main not updated",
                                           "bigboy blocked", "Base branch "))


if __name__ == "__main__":
    unittest.main()
