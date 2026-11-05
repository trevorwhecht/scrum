import json, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"

# A stub DOM: every id is one plain object; dataset and attributes behave like the real ones for these reads.
STUBS = """
const els = {};
const $ = id => els[id] ??= {id, hidden: true, disabled: false, innerHTML: "", textContent: "", title: "", value: "", dataset: {},
  attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; },
  removeAttribute(k) { delete this.attrs[k]; if (k === "title") this.title = ""; }};
"""


def line(text, start):
    i = text.index(start)
    return text[i:text.index("\n", i)]


def node_run(script):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=10).stdout
    return json.loads(out.strip().splitlines()[-1])


def backlog_script(tail):
    text = DASHBOARD.read_text()
    helpers = "\n".join(line(text, s) for s in ("const PTS = ", "const ptsOptions = ", "const esc = "))
    src = text[text.index("const blProject = "):text.index("async function backlogCall(")]
    return STUBS + helpers + "\nlet projects = [], manuals = {}, backlogs = {};\n" + src + "\n" + tail


def poll_script(tail):
    text = DASHBOARD.read_text()
    poll = text[text.index("async function poll()"):text.index('$("filter").addEventListener')]
    helpers = "\n".join(line(text, s) for s in ("const STALE = ", "const SLOW = ", "const setStatus = "))
    return (STUBS + helpers + "\nlet missed = 0, answer = null;\n"
            "const getJson = async () => null, renderMachine = () => {}, renderCooldown = () => {};\n"
            "const timed = async () => { if (answer instanceof Error) throw answer; return answer; };\n"
            + poll + "\n(async () => {" + tail + "})();")


class BacklogStates(unittest.TestCase):
    def test_backlog_error_vs_empty(self):
        got = node_run(backlog_script(
            "projects = ['p']; $('blProject').value = 'p';\n"
            "const out = [null, [], undefined].map(b => { backlogs = b === undefined ? {} : {p: b}; renderBacklog();"
            "  return [$('blList').innerHTML, $('blAdd').hidden]; });\n"
            "console.log(JSON.stringify(out));"))
        self.assertEqual(got, [['<li class="note">Couldn\'t load the backlog.</li>', False],
                               ['<li class="note">Backlog is empty.</li>', False],
                               ['<li class="note">Loading…</li>', False]])

    def test_backlog_no_projects_line(self):
        got = node_run(backlog_script(
            "renderBacklog(); const none = [$('blList').innerHTML, $('blList').dataset.agentHint, $('blAdd').hidden];\n"
            "projects = ['p']; $('blProject').value = 'p'; backlogs = {p: []}; renderBacklog();\n"
            "console.log(JSON.stringify([none, 'agentHint' in $('blList').dataset]));"))
        self.assertEqual(got, [['<li class="note">No projects yet.</li>', "Run /trevskills-scrum in a repo first.", True], False])
        text = DASHBOARD.read_text()
        self.assertIn('getJson(`api/p/${enc(p)}/backlog`, null, [])', text)
        self.assertIn("#blAdd[hidden]{display:none}", text, "the hidden attribute beats #blAdd{display:flex}")

    def test_backlog_button_dash_on_failed_read(self):
        text = DASHBOARD.read_text()
        render = text[text.index("function render()"):text.index("function renderSelect(")]
        body = render[render.index("  // A project whose backlog read failed"):render.rindex("}")]
        got = node_run(STUBS + line(text, "const setStatus = ") + "\nlet filter = '', projects = ['p', 'q'], backlogs;\n"
                       "const run = b => { backlogs = b;\n" + body + "\nreturn $('backlogBtn').textContent; };\n"
                       "console.log(JSON.stringify([run({p: null, q: [{done: false}]}), run({p: [], q: [{done: false}, {done: true}]})]));")
        self.assertEqual(got, ["Backlog · —", "Backlog · 1"])


class HeaderErrors(unittest.TestCase):
    def test_poll_status_copy(self):
        got = node_run(poll_script(
            "const out = [];\n"
            "for (const a of [{status: 500, ok: false}, new TypeError('Failed to fetch'), {status: 404, ok: false}]) {\n"
            "  answer = a; $('board').innerHTML = '<p class=\"empty\">Loading…</p>'; await poll();\n"
            "  out.push([$('status').textContent, $('status').title, $('board').innerHTML]); }\n"
            "boardLoaded = true; $('board').innerHTML = 'cards'; answer = {status: 503, ok: false}; await poll();\n"
            "out.push([$('status').textContent, $('board').innerHTML]);\n"
            "console.log(JSON.stringify(out));"))
        failed = '<p class="empty">Couldn\'t load the board.</p>'
        self.assertEqual(got, [["Server error (HTTP 500).", "Server error (HTTP 500).", failed],
                               ["Can't reach the server.", "Can't reach the server.", failed],
                               ["Dashboard server is out of date. Restart serve.py.", "Dashboard server is out of date. Restart serve.py.", failed],
                               ["Server error (HTTP 503).", "cards"]])
        text = DASHBOARD.read_text()
        status = re.search(r'<span id="status"[^>]*>', text).group(0)
        self.assertIn("Open the Trevskills Scrum app, or run python3 ~/.claude/skills/trevskills-scrum/serve.py".lower(), status.lower())
        self.assertIn('<main id="board"><p class="empty">Loading…</p></main>', text)
        self.assertIn("#colPick:empty{display:none}", text, "no empty stage picker before the first load")

    def test_routing_error_stays_visible(self):
        text = DASHBOARD.read_text()
        fn = text[text.index("async function loadRouting()"):]
        fn = fn[:fn.index("\n}\n") + 2]
        got = node_run(STUBS + "let usage = {old: 1};\nconst getJson = async () => null, routingText = () => 'x', usageRows = () => '';\n"
                       + fn + "\n(async () => { await loadRouting(); const r = $('routing');\n"
                       "console.log(JSON.stringify([r.hidden, r.innerHTML, r.title, usage])); })();")
        self.assertEqual(got, [False, '<span class="danger">Usage —</span>', "Couldn't load usage.", None])

    def test_machine_null_stays_visible(self):
        text = DASHBOARD.read_text()
        fn = text[text.index("function renderMachine("):]
        fn = fn[:fn.index("\n}\n") + 2]
        got = node_run(STUBS + fn + "\nrenderMachine(null); console.log(JSON.stringify([$('machine').hidden, $('machine').innerHTML]));")
        self.assertEqual(got, [False, '<span class="danger" title="Couldn\'t load machine status.">—</span>'])


class WriteErrors(unittest.TestCase):
    def test_fail_text_names_server_error_or_network(self):
        text = DASHBOARD.read_text()
        got = node_run(line(text, "const failText = ") + "\nconsole.log(JSON.stringify(["
                       "failText(\"Couldn't save\", Object.assign(new Error('disk full'), {status: 500})),"
                       "failText(\"Couldn't save\", new TypeError('Failed to fetch'))]));")
        self.assertEqual(got, ["Couldn't save: disk full", "Couldn't save. Can't reach the server."])
        self.assertNotIn("Is serve.py running?", text)


if __name__ == "__main__":
    unittest.main()
