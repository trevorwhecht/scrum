"""The job modal's one stop box (A/B/C buttons, recommended first, a note on rework), the More menu, the plain status
line on cards and in the modal, refused POSTs that survive a poll re-render, and the file tab URL."""
import json, re, shutil, subprocess, unittest

from test_dashboard_job_modal import DASHBOARD

HARNESS = """
const window = {}, document = {activeElement: null};
const handlers = {}, posted = [], fetched = [];
let postFails = null, stopHtml = null, noteValue = null;
const errP = {textContent: ""};
const els = {
  viewer: {open: true, dataset: {key: "p/020-q"}},
  viewerStatus: {textContent: ""},
  doc: {innerHTML: ""},
  tabs: {querySelectorAll: () => []},
  actions: {innerHTML: "", addEventListener: (ev, fn) => { handlers[ev] = fn; },
    querySelector: s => s === ".stop" ? {set outerHTML(v) { stopHtml = v; }, contains: () => false}
      : s === ":scope > .error" ? errP : s.includes("textarea") && noteValue !== null ? {value: noteValue, disabled: false, focus() {}} : null,
    querySelectorAll: () => []},
};
const $ = id => els[id];
const enc = encodeURIComponent;
const post = async (url, body) => { posted.push([url, body]); if (postFails) throw new Error(postFails); return {}; };
const poll = async () => {};
const open = () => {};
const fetch = async url => { fetched.push(url); return {ok: true, text: async () => "# hi"}; };
let runs = {}, jobs = [];
"""


def js(tail):
    """Run tail (async) in node over dashboard.html's job-modal code with $, post, poll and fetch stubbed. Returns the
    JSON values tail prints with out(...)."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = "\n".join(l for l in text.splitlines() if l.startswith(("const esc = ", "const when = ")))
    src = (text[text.index("const paused = "):text.index("function bigboyLines(")]
           + text[text.index("async function show(job, file)"):text.index("function open(job)")]
           + text[text.index("// Abort works on any unfinished job"):text.index("const blProject = ")])
    script = f"{esc}\n{HARNESS}\n{src}\nconst out = v => console.log(JSON.stringify(v));\n(async () => {{ {tail} }})();"
    res = subprocess.run([node, "-e", script], capture_output=True, text=True)
    if res.returncode:
        raise AssertionError(res.stderr)
    return [json.loads(l) for l in res.stdout.splitlines()]


ASKED = {"key": "p/020-q", "project": "p", "id": "020-q", "title": "Asked", "stage": "needs-human", "worktree": "/w",
         "reason": "Hard stop: schema — The migration drops a column. Fix: read spec.md, then pick one.",
         "updatedAt": "2026-01-01T00:00:00Z"}
OPTIONS = [{"key": "c", "label": "Drop it", "command": "abort 020-q"},
           {"key": "a", "label": "Ship it", "command": "approve 020-q"},
           {"key": "b", "label": "Redo", "command": 'rework 020-q "again"'}]
ANSWER = "api/p/p/jobs/020-q/answer"


def answers(html):
    return re.findall(r'data-answer="(\w)"', html)


class StopBox(unittest.TestCase):
    def test_stop_box_single_reason(self):
        text = DASHBOARD.read_text()
        for gone in ("waitingBanner", "optionsRow", "Click Discuss first.", "const splitReason"):
            self.assertNotIn(gone, text, gone)
        for job in ({**ASKED}, {**ASKED, "options": OPTIONS}):
            with self.subTest(options="options" in job):
                html, = js(f"jobs = [{json.dumps(job)}]; renderActions(jobs[0]); out(els.actions.innerHTML);")
                self.assertEqual(html.count('class="stop"'), 1, html)
                self.assertEqual(html.count("The migration drops a column."), 1, html)
                self.assertNotIn("Hard stop", html)
                self.assertIn("<p>The migration drops a column.</p>", html)
                # Without options the fix stays as the second line; with options the buttons are the way forward.
                self.assertEqual("<p>Read spec.md, then pick one.</p>" in html, "options" not in job, html)
        got = js('out(["Hard stop: schema — The migration drops a column.", "blocked: needs /Users/t/repo/scrum/x.md fixed. Fix: y",'
                 ' "stalled in build: no board update for 30 min. Fix: click Resume.", "Which way do we go?", "", null]'
                 '.map(stopIssue));')
        self.assertEqual(got[0], ["The migration drops a column.", "needs x.md fixed.", "no board update for 30 min.",
                                  "Which way do we go?", "No reason recorded.", "No reason recorded."])
        question, = js(f'jobs = [{json.dumps({**ASKED, "question": "Keep the column?", "options": OPTIONS})}]; out(stopBox(jobs[0]));')
        self.assertIn("<p>Keep the column?</p>", question)
        self.assertNotIn("drops a column", question)

    def test_stop_buttons_recommended_order(self):
        job = {**ASKED, "options": OPTIONS, "recommend": {"key": "b", "why": "Small fix"}}
        html, = js(f"jobs = [{json.dumps(job)}]; out(stopBox(jobs[0]));")
        self.assertEqual(answers(html), ["b", "a", "c"])
        self.assertEqual(html.count("Recommended"), 1)
        first = html[html.index('data-answer="b"'):html.index('data-answer="a"')]
        self.assertIn('Redo <span class="badge">Recommended</span></button><p class="note">Small fix</p>', first)
        two, = js(f'jobs = [{json.dumps({**job, "options": OPTIONS[1:]})}]; out(stopBox(jobs[0]));')
        self.assertEqual(answers(two), ["b", "a"])

    def test_stop_buttons_no_recommend(self):
        html, = js(f'jobs = [{json.dumps({**ASKED, "options": OPTIONS})}]; out(stopBox(jobs[0]));')
        self.assertEqual(answers(html), ["a", "b", "c"])
        self.assertNotIn("Recommended", html)
        for b in re.findall(r"<button[^>]*>", html):
            self.assertIn("btn tall", b)

    def test_rework_option_sends_note(self):
        setup = f'jobs = [{json.dumps({**ASKED, "options": OPTIONS})}];'
        opened, sent, empty = js(setup + ' await answer("p/020-q", "b"); out([posted.length, stopHtml]);'
                                 ' noteValue = "keep <the> column"; await handlers.click({target: {closest: () => ({dataset: {send: "b"}})}});'
                                 ' out(posted.splice(0));'
                                 ' await answer("p/020-q", "b"); noteValue = ""; await handlers.click({target: {closest: () => ({dataset: {send: "b"}})}});'
                                 ' out(posted);')
        self.assertEqual(opened[0], 0)  # the rework option does not post at once
        self.assertIn('<textarea name="note" maxlength="2000"', opened[1])
        self.assertIn('data-send="b">Send back</button>', opened[1])
        self.assertEqual(sent, [[ANSWER, {"key": "b", "note": "keep <the> column"}]])
        self.assertEqual(empty, [[ANSWER, {"key": "b", "note": ""}]])
        plain, = js(setup + ' await handlers.click({target: {closest: () => ({dataset: {answer: "a"}})}}); out(posted);')
        self.assertEqual(plain, [[ANSWER, {"key": "a"}]])

    def test_abort_option_arms_first(self):
        setup = f'jobs = [{json.dumps({**ASKED, "options": OPTIONS})}];'
        armed, done = js(setup + ' await answer("p/020-q", "c"); out([posted.length, stopHtml]);'
                         ' await answer("p/020-q", "c"); out(posted);')
        self.assertEqual(armed[0], 0)
        self.assertIn('<button class="btn tall danger" type="button" data-answer="c">Confirm: Drop it</button>', armed[1])
        self.assertEqual(done, [[ANSWER, {"key": "c"}]])

    def test_abort_only_in_more(self):
        more = re.compile(r'<details class="more" data-key="p/020-q"><summary>More</summary><form data-act="abort">.*?Abort job</button></form></details>', re.S)
        cases = [({**ASKED, "options": OPTIONS}, {}), ({**ASKED}, {}),
                 ({**ASKED, "stage": "build", "reason": None}, {"p/020-q": {"action": "build", "started": 1767284460, "alive": True}})]
        for job, runs in cases:
            with self.subTest(stage=job["stage"], options="options" in job):
                html, = js(f"runs = {json.dumps(runs)}; jobs = [{json.dumps(job)}]; renderActions(jobs[0]); out(els.actions.innerHTML);")
                self.assertEqual(html.count("Abort job"), 1, html)
                self.assertEqual(len(more.findall(html)), 1, html)
                outside = more.sub("", html)
                self.assertNotIn('data-act="abort"', outside)
                for gone in (">Keep<", ">Discard<"):
                    self.assertNotIn(gone, html)
        plain, = js(f"jobs = [{json.dumps(ASKED)}]; renderActions(jobs[0]); out(els.actions.innerHTML);")
        for kept in ("Approve &amp; merge</button>", ">Discuss first</button>", ">Send back to builder</button>"):
            self.assertIn(kept, plain)
        for stage in ("done", "aborted"):
            html, = js(f'renderActions({json.dumps({**ASKED, "stage": stage})}); out(els.actions.innerHTML);')
            self.assertNotIn("<details", html)

    def test_status_line_cases(self):
        twelve = "new Date(Date.now() - 12 * 60000 - 5000).toISOString()"
        got, = js(f"""const at = {twelve}, j = extra => ({{key: "p/1", project: "p", id: "1", stage: "build", updatedAt: at, ...extra}});
          out([j({{stage: "done", paused: true}}), j({{stage: "aborted", paused: true, waitingOn: {{ids: ["9"], why: "x"}}}}), j({{paused: true, waitingOn: {{ids: ["9"], why: "x"}}}}),
            j({{paused: true}}), j({{paused: true, waitingOn: null}}),
            j({{waitingOn: {{ids: ["222", "223"], why: "shares SKILL.md"}}, resumeRefusal: "can't resume yet: 222. Fix: wait."}}),
            j({{resumeRefusal: "can't resume yet: 222. Fix: click Resume when 222 finish."}}),
            j({{stage: "needs-human", reason: "Hard stop: schema — The migration drops a column. Fix: x"}}),
            j({{stage: "needs-human", reason: "blocked: x", question: "Ship /a/b/spec.md now?"}}),
            j({{waiting: "permission: Bash"}}), j({{stage: "waiting", setup: "pending"}}),
            j({{}}), j({{stage: "spec"}}), j({{stage: "cloud"}}), j({{stage: "waiting"}}), j({{stage: "odd"}}),
            j({{updatedAt: new Date(Date.now() + 60000).toISOString()}})].map(statusLine));""")
        self.assertEqual(got, ["Done", "Aborted", "Waiting on 9 (x)", "Paused by you", "Paused by you", "Waiting on 222, 223 (shares SKILL.md)",
                               "Waiting: can't resume yet: 222.", "Waiting on you: The migration drops a column.",
                               "Waiting on you: Ship spec.md now?", "Waiting on you: permission: Bash",
                               "Waiting on you: setup", "Building, 12 min", "Writing spec, 12 min", "Running in cloud, 12 min",
                               "Queued, 12 min", "odd, 12 min", "Building, 0 min"])
        for line in got:
            self.assertNotIn("/", line)
        text = DASHBOARD.read_text()
        card = text[text.index("function card(job)"):text.index("function render(")]
        self.assertIn('<span class="status">${esc(statusLine(job))}</span>', card)
        self.assertNotIn("Human setup:", card)
        self.assertNotIn("esc(job.waiting)", card)
        actions = text[text.index("function renderActions(job)"):text.index("function actionsHtml(")]
        self.assertIn("statusLine(", actions)
        dialog = next(l for l in text.splitlines() if '<dialog id="viewer"' in l)
        self.assertLess(dialog.index('id="viewerTitle"'), dialog.index('id="viewerStatus"'))
        status, = js(f"renderActions({json.dumps(ASKED)}); out(els.viewerStatus.textContent);")
        self.assertEqual(status, "Waiting on you: The migration drops a column.")

    def test_play_hidden_when_refused(self):
        paused = {"key": "p/030-p", "project": "p", "id": "030-p", "stage": "build", "paused": True,
                  "reason": "stalled in build: paused by Trevor. Fix: click Play.", "updatedAt": "2026-01-01T00:00:00Z"}
        stalled = {**ASKED, "reason": "stalled in check: no board update for 30 min. Fix: click Resume."}
        refusal = "can't resume yet: 222. Fix: click Resume when 222 finish."
        # The note names what blocks the click, even for a job Trevor paused (whose status line says "Paused by you").
        for job, label, want in ((paused, "Play", "Waiting: can&#39;t resume yet: 222."), (stalled, "Resume", "Waiting: can&#39;t resume yet: 222.")):
            with self.subTest(label=label):
                for missing in ({}, {"resumeRefusal": None}):
                    html, = js(f"renderActions({json.dumps({**job, **missing})}); out(els.actions.innerHTML);")
                    self.assertIn(f'<form data-act="resume"><button class="btn primary tall" type="submit">{label}</button></form>', html)
                html, = js(f"renderActions({json.dumps({**job, 'resumeRefusal': refusal})}); out(els.actions.innerHTML);")
                self.assertNotIn('data-act="resume"', html)
                self.assertNotIn(f">{label}</button>", html)
                self.assertIn(f'<p class="note" role="status">{want}</p>', html)

    def test_more_menu_open_state_stays_with_its_job(self):
        a, b = {**ASKED, "stage": "build", "reason": None}, {**ASKED, "key": "p/021-r", "id": "021-r", "stage": "build", "reason": None}
        # Before each render the old menu (job a's, open) is in #actions; after it, a fresh closed one from the new markup.
        same, other = js(f"""const real = els.actions.querySelector; let fresh = null;
            const run = job => {{ let calls = 0; fresh = {{open: false}};
              els.actions.querySelector = s => s !== "details.more" ? real(s) : calls++ ? fresh : {{open: true, dataset: {{key: "p/020-q"}}}};
              renderActions(job); return fresh.open; }};
            out(run({json.dumps(a)})); out(run({json.dumps(b)}));""")
        self.assertTrue(same)  # a poll re-render of the same job keeps it open
        self.assertFalse(other)  # another job's menu starts closed

    def test_status_minutes_tick_without_board_change(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        tick = text[text.index("const tickAgo = "):text.index("const paused = ")]
        got, = js(f"""const ago = () => ""; const card = {{textContent: "Building, 0 min", parentElement: {{dataset: {{key: "p/1"}}}}}};
            document.querySelectorAll = s => s.includes(".status") ? [card] : [];
            jobs = [{{key: "p/1", stage: "build", updatedAt: new Date(Date.now() - 7 * 60000 - 5000).toISOString()}}];
            els.viewer.dataset.key = "p/1"; {tick}; tickAgo(); out([card.textContent, els.viewerStatus.textContent]);""")
        self.assertEqual(got, ["Building, 7 min", "Building, 7 min"])

    def test_note_textarea_16px_on_mobile(self):
        text = DASHBOARD.read_text()
        mobile = [l for l in text.splitlines() if l.startswith("@media (max-width:640px)")]
        self.assertTrue(any(re.search(r"#actions textarea[^{]*\{font-size:16px", l) for l in mobile))

    def test_post_error_survives_rerender(self):
        msg = "can't resume yet: 222. Fix: click Resume when 222 finish."
        shown = msg.replace("'", "&#39;")
        job = {**ASKED, "reason": "stalled in check: no board update for 30 min. Fix: click Resume."}
        submit = ('{ const btn = {dataset: {}, disabled: false}; await handlers.submit({preventDefault() {}, submitter: btn,'
                  ' target: {dataset: {act: "resume"}, querySelector: () => btn}}); }')
        first, again, other, moved = js(f"""jobs = [{json.dumps(job)}]; postFails = {json.dumps(msg)}; {submit}
            out(errP.textContent); renderActions(jobs[0]); out(els.actions.innerHTML);
            postFails = null; {submit} renderActions(jobs[0]); out(els.actions.innerHTML);
            postFails = {json.dumps(msg)}; {submit} jobs[0] = {{...jobs[0], stage: "build"}}; renderActions(jobs[0]); out(els.actions.innerHTML);""")
        self.assertEqual(first, msg)
        self.assertIn(f'<p class="error" role="alert">{shown}</p>', again)
        self.assertIn('<p class="error" role="alert"></p>', other)  # cleared by the next POST that succeeds
        self.assertIn('<p class="error" role="alert"></p>', moved)  # cleared when the stage changes
        answered, = js(f"""jobs = [{json.dumps({**ASKED, "options": OPTIONS})}]; postFails = {json.dumps(msg)};
            await answer("p/020-q", "a"); renderActions(jobs[0]); out(els.actions.innerHTML);""")
        self.assertIn(f'<p class="error" role="alert">{shown}</p>', answered)
        self.assertNotIn(" disabled", answered)

    def test_file_tab_url(self):
        got, = js('const j = {key: "parent/folder/086-x", project: "parent/folder", id: "086-x"};'
                  ' await show(j, "spec.md"); await show(j, "decision.md"); out(fetched);')
        self.assertEqual(got, ["p/parent%2Ffolder/jobs/086-x/spec.md", "p/parent%2Ffolder/jobs/086-x/decision.md"])


if __name__ == "__main__":
    unittest.main()
