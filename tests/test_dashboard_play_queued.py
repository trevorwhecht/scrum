"""A needs-human job whose Play click was queued (serve.py resume -> play_queued) waits on the machine, not on Trevor:
it sits in the waiting column with no red, no "Waiting on you" box, and no place in a parent's "Waiting on you in:".
A job file that 404s in the modal drops its tab instead of showing the error."""
import json, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"

# A stub DOM. #tabs holds real-ish button objects parsed from its innerHTML, so show() can find and remove a tab with
# querySelector / querySelectorAll / remove().
STUBS = r"""
const window = {}, localStorage = undefined;
const els = {};
const fileTab = file => ({dataset: {file}, attrs: {}, setAttribute(k, v) { this.attrs[k] = String(v); },
  getAttribute(k) { return this.attrs[k] ?? null; }, remove() { tabsEl.kids = tabsEl.kids.filter(b => b !== this); },
  click() {}, focus() {}});
const tabsEl = {id: "tabs", style: {}, dataset: {}, textContent: "", kids: [],
  set innerHTML(v) { this.kids = [...String(v).matchAll(/<button data-file="([^"]+)"/g)].map(m => fileTab(m[1])); },
  get innerHTML() { return this.kids.map(b => `<button data-file="${b.dataset.file}"></button>`).join(""); },
  querySelectorAll(s) { return s.startsWith("button[data-file") || s === "button" || s === "[data-file]" ? [...this.kids] : []; },
  querySelector(s) { const m = s.match(/data-file="([^"]+)"/); return m ? this.kids.find(b => b.dataset.file === m[1]) || null : this.kids[0] || null; }};
els.tabs = tabsEl;
const el = id => els[id] ??= {id, style: {}, dataset: {}, innerHTML: "", textContent: "", open: false,
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, showModal() { this.open = true; }};
const document = {activeElement: null, getElementById: el, querySelectorAll: () => [], addEventListener() {}};
const fetched = [];
let fetchImpl = async url => ({ok: true, status: 200, text: async () => "# hi"});
const fetch = async (url, opts) => { fetched.push(url); return fetchImpl(url, opts); };
"""


def run(tail):
    """Run tail (async) in node over dashboard.html from STAGES through render(), show()/open(), and the modal's action
    renderers, with a stub DOM and fetch. Returns the JSON values tail prints with out(...)."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    src = (text[text.index("const STAGES = "):text.index("function renderSelect(")]
           + text[text.index("async function show("):text.index("// Diverged bullets are read")]
           + text[text.index("// Abort works on any unfinished job"):text.index("const blProject = ")])
    script = (STUBS + src + "\nprojects = []; roadmaps = {}; filter = \"\"; laneFilter = \"\";\n"
              + "const out = v => console.log(JSON.stringify(v));\n(async () => { " + tail + " })();")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True)
    if res.returncode:
        raise AssertionError(res.stderr)
    return [json.loads(l) for l in res.stdout.splitlines()]


QUEUED = {"key": "p/200-q", "project": "p", "id": "200-q", "title": "Queued", "stage": "needs-human",
          "reason": "stalled in review: no board update for 30 min. Fix: click Resume.", "play_queued": "2026-10-25T10:00:00Z",
          "resumeRefusal": "swap used 28.1% of RAM (> 25%). Fix: close some apps.", "updatedAt": "2026-10-25T10:00:00Z"}
STUCK = {**QUEUED, "key": "p/201-s", "id": "201-s", "title": "Stuck", "play_queued": None, "resumeRefusal": None}


def column_of(html, key):
    for col, body in re.findall(r'data-col="([^"]+)">(.*?)</section>', html, re.S):
        if f'data-key="{key}"' in body:
            return col
    return None


class PlayQueued(unittest.TestCase):
    def test_play_queued_job_renders_in_waiting_column(self):
        cols, html, status, status_none, status_cpu = run(f"""
            const q = {json.dumps(QUEUED)}, s = {json.dumps(STUCK)};
            out([colOf(q), colOf(s), colOf({{stage: "aborted"}}), colOf({{stage: "build"}}), colOf({{stage: "needs-human"}})]);
            jobs = [q, s]; render(); out(els.board.innerHTML);
            out(statusLine(q)); out(statusLine({{...q, resumeRefusal: null}}));
            out(statusLine({{...q, resumeRefusal: "waiting: CPU busy 95% (> 90%). Fix: click Resume once memory or disk frees up."}}));""")
        self.assertEqual(cols, ["waiting", "needs-human", "done", "build", "needs-human"])
        self.assertEqual(column_of(html, "p/200-q"), "waiting")
        self.assertEqual(column_of(html, "p/201-s"), "needs-human")
        card = re.search(r'<button class="([^"]*)" data-key="p/200-q">(.*?)</button>', html, re.S)
        self.assertNotIn("human", card.group(1).split())
        self.assertNotRegex(card.group(2), r'class="bar[^"]* human')
        self.assertEqual(status, "Waiting for CPU/RAM: swap used 28.1% of RAM (> 25%).")
        self.assertEqual(status_none, "Queued, starts next")
        self.assertEqual(status_cpu, "Waiting for CPU/RAM: CPU busy 95% (> 90%).", "serve.py's waiting: prefix is not repeated")
        stuck = re.search(r'<button class="([^"]*)" data-key="p/201-s">', html)
        self.assertIn("human", stuck.group(1).split())

    def test_play_queued_modal_has_no_stop_box(self):
        box, html, viewer, stuck_box = run(f"""
            const q = {json.dumps(QUEUED)}; jobs = [q]; runs = {{}};
            out(stopBox(q)); renderActions(q); out(els.actions.innerHTML); out(els.viewerStatus.textContent);
            out(stopBox({json.dumps(STUCK)}));""")
        self.assertEqual(box, "")
        self.assertNotIn("Waiting on you", html)
        self.assertIn('<p class="note" role="status">queued, starts next</p>', html)
        self.assertEqual(viewer, "Waiting for CPU/RAM: swap used 28.1% of RAM (> 25%).")
        self.assertIn("<b>Waiting on you</b><p>no board update for 30 min.</p>", stuck_box)

    def test_play_queued_child_not_waiting_on_you(self):
        parent = {"key": "p/100-big", "project": "p", "id": "100-big", "stage": "running", "children": ["200-q", "201-s"],
                  "reason": "waiting on you in: 200-q, 201-s"}
        got = run(f"""jobs = [{json.dumps(parent)}, {json.dumps(QUEUED)}, {json.dumps(STUCK)}];
            out(needsYou(jobs[1])); out(needsYou(jobs[2])); out(waitingOn(jobs[0]));""")
        self.assertEqual(got, [False, True, ["201-s"]])

    def test_play_queued_new_shape_stalled(self):
        stall = {"stage": "build", "stalled": True, "reason": "stalled: no live session"}
        got = run(f"""out(playQueued({json.dumps({**stall, "play_queued": "2026-10-25T10:00:00Z"})}));
            out(playQueued({json.dumps(stall)})); out(playQueued({json.dumps({"stage": "build", "play_queued": "x"})}));""")
        self.assertEqual(got, [True, False, False])

    def test_missing_job_file_tab_hidden(self):
        job = {**STUCK, "files": ["feature.md", "plan.md"]}
        notfound = 'fetchImpl = async url => url.endsWith("feature.md") ? {ok: false, status: 404, text: async () => "nope"} : {ok: true, status: 200, text: async () => "# plan"};'
        tabs, doc, seen = run(f"""{notfound}
            els.tabs.innerHTML = '<button data-file="feature.md" aria-pressed="false">feature.md</button><button data-file="plan.md" aria-pressed="false">plan.md</button>';
            await show({json.dumps(job)}, "feature.md"); await new Promise(r => setTimeout(r, 20));
            out(els.tabs.kids.map(b => b.dataset.file)); out(els.doc.innerHTML); out(fetched);""")
        self.assertEqual(tabs, ["plan.md"])
        self.assertEqual(doc, "<pre># plan</pre>")
        self.assertNotIn("Couldn't load", doc)
        self.assertEqual(seen, ["p/p/jobs/201-s/feature.md", "p/p/jobs/201-s/plan.md"])
        # The only tab gone: the empty note.
        tabs, doc = run(f"""{notfound}
            els.tabs.innerHTML = '<button data-file="feature.md" aria-pressed="false">feature.md</button>';
            await show({json.dumps(job)}, "feature.md"); await new Promise(r => setTimeout(r, 20));
            out(els.tabs.kids.map(b => b.dataset.file)); out(els.doc.innerHTML);""")
        self.assertEqual(tabs, [])
        self.assertEqual(doc, '<p class="empty">No files yet.</p>')
        # A 500 and the roadmap viewer's 404 still say Couldn't load, and keep the tab.
        for fetch_impl, doc_job, want in (
                ('async () => ({ok: false, status: 500, text: async () => ""})', job, "Couldn't load feature.md (500)."),
                ('async () => ({ok: false, status: 404, text: async () => ""})', {"key": "p#roadmap", "project": "p", "id": "roadmap", "base": "p/p/"},
                 "Couldn't load feature.md (404).")):
            with self.subTest(want=want, roadmap="base" in doc_job):
                tabs, doc = run(f"""fetchImpl = {fetch_impl};
                    els.tabs.innerHTML = '<button data-file="feature.md" aria-pressed="false">feature.md</button>';
                    await show({json.dumps(doc_job)}, "feature.md"); await new Promise(r => setTimeout(r, 20));
                    out(els.tabs.kids.map(b => b.dataset.file)); out(els.doc.innerHTML);""")
                self.assertEqual(tabs, ["feature.md"])
                self.assertEqual(doc, f'<p class="empty">{want}</p>')


if __name__ == "__main__":
    unittest.main()
