import json, re, shutil, subprocess, unittest

from test_dashboard_ai_focus import DASHBOARD

INTRO = "# Terminal batch: project .claude edits\n\nRun this in a Terminal window.\n\n"
TWO = INTRO + ("## From 101-add-rule: Add a rule\n- `.claude/rules/a.md`: add \"x\"\n\n"
               "## From 102-fix-hook: Fix: the hook\n```md\n## not a heading\n```\n### Sub\ntext\n")


def node_run(script):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


def chunk(text, start):
    i = text.index(start)
    return text[i:text.index("\n}\n", i) + 3]


def batch_edits(md):
    return node_run(chunk(DASHBOARD.read_text(), "function batchEdits(") + f"\nconsole.log(JSON.stringify(batchEdits({json.dumps(md)})));")


def render_script(body):
    """renderBatchEdits in node with stubbed $, fetch (resolved by hand) and a marking mdHtml stub."""
    text = DASHBOARD.read_text()
    esc = re.search(r"^const esc = .*$", text, re.M).group(0)
    title = re.search(r"^const TERMINAL_BATCH_TITLE = .*$", text, re.M).group(0)
    return esc + "\n" + title + "\n" + chunk(text, "function batchEdits(") + chunk(text, "let batchGen = ") + r"""
const els = {batchEdits: {innerHTML: "untouched"}, viewer: {dataset: {key: "k"}}};
const $ = id => els[id];
const enc = encodeURIComponent;
const mdHtml = s => `<MD>${s}</MD>`;
let pending = [];
const fetch = () => new Promise(res => pending.push(t => res({ok: true, text: async () => t})));
const settle = () => new Promise(r => setTimeout(r, 0));
const job = (key, title) => ({key, project: "p", id: "1", title, files: ["feature.md"]});
const BATCH = "Terminal batch: project .claude edits";
(async () => {
  const out = {};
""" + body + "\n  console.log(JSON.stringify(out));\n})();\n"


class BatchEditsTest(unittest.TestCase):
    def test_sections_parsed(self):
        self.assertEqual(batch_edits(TWO), [
            {"id": "101-add-rule", "title": "Add a rule", "body": "- `.claude/rules/a.md`: add \"x\""},
            {"id": "102-fix-hook", "title": "Fix: the hook", "body": "```md\n## not a heading\n```\n### Sub\ntext"},
        ])

    def test_other_heading_ends_section(self):
        md = INTRO + "## From 7-a: A\nbody a\n## Notes\nnot an edit\n"
        self.assertEqual(batch_edits(md), [{"id": "7-a", "title": "A", "body": "body a"}])

    def test_no_sections_empty(self):
        self.assertEqual(batch_edits(INTRO), [])
        out = node_run(render_script(r"""
  const p = renderBatchEdits(job("k", BATCH)); pending[0](""); await p; await settle();
  out.html = els.batchEdits.innerHTML;"""))
        self.assertEqual(out["html"], "")
        self.assertIn("#batchEdits:empty{display:none}", DASHBOARD.read_text())

    def test_other_job_untouched(self):
        out = node_run(render_script(r"""
  await renderBatchEdits(job("k", "Some other job"));
  out.html = els.batchEdits.innerHTML; out.fetches = pending.length;"""))
        self.assertEqual(out, {"html": "untouched", "fetches": 0})

    def test_stale_fetch_ignored(self):
        out = node_run(render_script(r"""
  // Two overlapping calls; the older one's fetch resolves last.
  const a = renderBatchEdits(job("k", BATCH)); const b = renderBatchEdits(job("k", BATCH));
  const [fa, fb] = pending; pending = [];
  fb("## From 2-new: New\nnew body"); await b; await settle();
  fa("## From 1-old: Old\nold body"); await a; await settle();
  out.overlap = els.batchEdits.innerHTML;
  // The modal moved to another job while the fetch was pending.
  els.batchEdits.innerHTML = "untouched";
  const c = renderBatchEdits(job("k", BATCH)); const [fc] = pending; pending = [];
  els.viewer.dataset.key = "other";
  fc("## From 3-moved: Moved\nmoved body"); await c; await settle();
  out.moved = els.batchEdits.innerHTML;"""))
        self.assertIn("new body", out["overlap"])
        self.assertNotIn("old body", out["overlap"])
        self.assertEqual(out["moved"], "untouched")

    def test_renders_body_markdown(self):
        out = node_run(render_script(r"""
  const p = renderBatchEdits(job("k", BATCH)); pending[0](""" + json.dumps(TWO) + r"""); await p; await settle();
  out.html = els.batchEdits.innerHTML;"""))
        html = out["html"]
        self.assertIn("<MD>- `.claude/rules/a.md`: add \"x\"</MD>", html)
        self.assertIn("<MD>```md\n## not a heading\n```\n### Sub\ntext</MD>", html)
        self.assertIn('<span class="id">101-add-rule</span> Add a rule', html)
        self.assertIn('<span class="id">102-fix-hook</span> Fix: the hook', html)

    def test_show_uses_shared_renderer(self):
        text = DASHBOARD.read_text()
        show = chunk(text, "async function show(")
        self.assertNotIn("const render = ", show)
        self.assertIn("mdHtml(rest.slice(cut))", show)
        self.assertIn('<div id="diverged"></div><div id="batchEdits"></div><div id="actions"></div>', text)

    def test_open_and_poll_call_it(self):
        text = DASHBOARD.read_text()
        self.assertIn("renderBatchEdits(job);", chunk(text, "function open("))
        self.assertIn("if (openJob) renderBatchEdits(openJob);", chunk(text, "async function poll("))


if __name__ == "__main__":
    unittest.main()
