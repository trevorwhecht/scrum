import json, os, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"

JOBS = [
    {"key": "p/005-big", "project": "p", "id": "005-big", "title": "Big", "stage": "running",
     "children": ["006-a", "007-b", "008-c", "009-gone"]},
    {"key": "p/006-a", "project": "p", "id": "006-a", "ticket": "T1", "stage": "done"},
    {"key": "p/007-b", "project": "p", "id": "007-b", "ticket": "T2", "stage": "needs-human"},
    {"key": "p/008-c", "project": "p", "id": "008-c", "ticket": "T3", "stage": "waiting", "setup": "pending"},
    {"key": "p/011-run", "project": "p", "id": "011-run", "title": "Run all", "stage": "running", "children": ["012-x"]},
    {"key": "p/012-x", "project": "p", "id": "012-x", "stage": "build"},
]


def run(expr, tz=None):
    """Evaluate expr in node over dashboard.html's esc and its job-modal helpers, with JOBS as the board."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = "\n".join(l for l in text.splitlines() if l.startswith(("const esc = ", "const when = ")))
    helpers = text[text.index("const setupWait = "):text.index("function bigboyLines(")] \
        + text[text.index("const abortForm = "):text.index("const termState = ")]
    script = f"{esc}\nlet jobs = {json.dumps(JOBS)};\n{helpers}\nconsole.log(JSON.stringify({expr}));"
    env = {**os.environ, "TZ": tz} if tz else None
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, env=env).stdout)


class JobModal(unittest.TestCase):
    def test_modal_header_shows_job_id(self):
        self.assertEqual(run('jobTitle({id: "005-big", title: "Big <b>"})'),
                         '<span class="id">005-big</span> Big &lt;b&gt;')
        self.assertEqual(run('jobTitle({id: "005-big"})'), '<span class="id">005-big</span> 005-big')
        text = DASHBOARD.read_text()
        self.assertIn('$("viewerTitle").innerHTML = jobTitle(job);', text[text.index("function open(job)"):])

    def test_parent_modal_lists_children(self):
        html = run("childLinks(jobs[0])")
        rows = re.findall(r'<form data-act="goto" data-key="([^"]+)"><button class="btn tall kid( human)?" type="submit">(.*?)</button></form>', html)
        self.assertEqual(rows, [
            ("p/006-a", "", 'T1 <span class="id">006-a</span> done'),
            ("p/007-b", " human", 'T2 <span class="id">007-b</span> needs-human'),
            ("p/008-c", " human", 'T3 <span class="id">008-c</span> waiting'),
        ])
        self.assertIn('<p class="note kid"><span class="id">009-gone</span> —</p>', html)
        self.assertNotIn('data-key="p/009-gone"', html)
        self.assertIn('Child <span class="id">012-x</span> build', run("childLinks(jobs[4])"))
        self.assertEqual(run("childLinks(jobs[1])"), "")
        text = DASHBOARD.read_text()
        body = text[text.index("function renderActions(job)"):text.index('$("actions").addEventListener("submit"')]
        self.assertEqual(body.count("kids +"), 3)  # every branch: run alive, not needs-human, needs-human

    def test_waiting_note_filters_live_children(self):
        reason = "waiting on you in: 006-a, 007-b, 008-c, 009-gone"
        self.assertEqual(run(f'waitingOn({{...jobs[0], reason: "{reason}"}})'), ["007-b", "008-c"])
        self.assertEqual(run(f'waitingOn({{...jobs[0], stage: "needs-human", reason: "{reason}"}})'), [])
        self.assertEqual(run('waitingOn({...jobs[0], reason: "waiting on you in: 006-a"})'), [])
        self.assertEqual(run('waitingOn({...jobs[0], reason: null})'), [])
        self.assertEqual(run(f'waitingNote({{...jobs[0], reason: "{reason}"}}, "meta")'),
                         '<span class="meta">Waiting on you in: 007-b, 008-c</span>')
        self.assertEqual(run('waitingNote({...jobs[0], reason: null}, "meta")'), "")

    def test_pause_and_play_buttons_render(self):
        pause = '<form data-act="pause"><button class="btn tall" type="submit">Pause</button></form>'
        for stage in ("spec", "build", "check", "review", "approve", "merging", "plan", "running"):
            self.assertEqual(run(f'pauseForm({{stage: "{stage}"}})'), pause, stage)
        for stage in ("waiting", "needs-human", "done", "aborted"):
            self.assertEqual(run(f'pauseForm({{stage: "{stage}"}})'), "", stage)
        resume = '<form data-act="resume"><button class="btn primary tall" type="submit">{}</button></form>'
        self.assertEqual(run('resumeForm("stalled in build: paused by Trevor. Fix: click Play.")'), resume.format("Play"))
        self.assertEqual(run('resumeForm("stalled in check: no board update for 30 min. Fix: click Resume.")'),
                         resume.format("Resume"))
        self.assertEqual(run('resumeForm("blocked: x. Fix: y")'), "")
        text = DASHBOARD.read_text()
        body = text[text.index("function renderActions(job)"):text.index('$("actions").addEventListener("submit"')]
        self.assertEqual(body.count("pauseForm(job) + abortForm(job)"), 2)  # run alive, and no run
        self.assertIn("resumeForm(reason)", body)
        self.assertIn("|stalled)/.test(reason)", body)  # Approve stays hidden for a paused (stalled) job
        submit = text[text.index('$("actions").addEventListener("submit"'):]
        self.assertIn('act === "resume" || act === "pause" || act === "setup-done" ? {}', submit)

    def actions_html(self, job, runs=None):
        """renderActions(job) evaluated in node with a stub #actions element; returns the HTML it wrote."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = "\n".join(l for l in text.splitlines() if l.startswith(("const esc = ", "const when = ")))
        helpers = text[text.index("const paused = "):text.index("function bigboyLines(")] \
            + text[text.index("const abortForm = "):text.index('$("actions").addEventListener("submit"')]
        script = (f"{esc}\nconst enc = encodeURIComponent;\nlet runs = {json.dumps(runs or {})};\nlet jobs = {json.dumps(JOBS)};\n"
                  "const el = {innerHTML: ''};\nconst $ = id => el;\n"
                  f"{helpers}\nrenderActions({json.dumps(job)});\nconsole.log(JSON.stringify(el.innerHTML));")
        return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_off_track_parent_shows_send_back(self):
        parent = {"key": "p/005-big", "project": "p", "id": "005-big", "title": "Big", "stage": "needs-human",
                  "children": ["006-a", "007-b"]}
        off = self.actions_html({**parent, "reason": "bigboy off track: x. Fix: read the latest track file, then click "
                                 "Resume to carry on with the plan or Send back with your decision to replan."})
        self.assertIn('<form data-act="rework"><textarea name="feedback"', off)
        self.assertIn('Send back to builder</button>', off)
        self.assertIn('<form data-act="resume"><button class="btn primary tall" type="submit">Resume</button></form>', off)
        blocked = self.actions_html({**parent, "reason": "bigboy blocked: y. Fix: click Resume to skip the children "
                                     "that depend on them and run the final review."})
        self.assertNotIn('data-act="rework"', blocked)
        self.assertNotIn('Send back to builder', blocked)
        self.assertIn('<form data-act="resume"><button class="btn primary tall" type="submit">Resume</button></form>', blocked)

    def test_ask_button_in_every_modal_branch(self):
        text = DASHBOARD.read_text()
        body = text[text.index("function renderActions(job)"):text.index('$("actions").addEventListener("submit"')]
        branches = re.findall(r"el\.innerHTML = (.*?)(?:;\n|;$)", body, re.S)
        self.assertEqual(len(branches), 3)  # run alive, not needs-human, needs-human
        for branch in branches:
            self.assertIn("askForm(job)", branch)
        submit = text[text.index('$("actions").addEventListener("submit"'):]
        self.assertIn('if (act === "ask") return askClaude(key);', submit)
        self.assertIn('post(`api/p/${enc(job.project)}/jobs/${enc(job.id)}/ask`, {})', text)
        self.assertIn("if (!askState[job.key]?.pending) delete askState[job.key];", text[text.index("function open(job)"):])
        form = text[text.index("const askState = "):text.index("const redrawAsk = ")]
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        esc = next(l for l in text.splitlines() if l.startswith("const esc = "))
        def ask(state):
            script = f"{esc}\n{form}\naskState.k = {json.dumps(state)};\nconsole.log(JSON.stringify(askForm({{key: 'k'}})));"
            return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        idle = ask({})
        self.assertTrue(idle.startswith('<form data-act="ask"><button class="btn" type="submit" data-agent-hint="'), idle)
        self.assertTrue(idle.endswith('">Ask Claude</button></form>'), idle)
        self.assertIn(" disabled>Ask Claude</button>", ask({"pending": True}))
        self.assertTrue(ask({"msg": "Claude opened in Ghostty."}).endswith(
            '</button><span class="note" role="status">Claude opened in Ghostty.</span></form>'))
        self.assertTrue(ask({"err": "no <Ghostty>"}).endswith(
            '</button><span class="error" role="alert">no &lt;Ghostty&gt;</span></form>'))

    def test_stale_uses_newest_activity(self):
        # 2026-01-01T00:00:00Z is 1767225600 s
        self.assertEqual(run('staleAt({updatedAt: "2026-01-01T00:00:00Z", activity: {at: 1767229200}})'), 1767229200000)
        self.assertEqual(run('staleAt({updatedAt: "2026-01-01T00:00:00Z", activity: {at: 1767222000}})'), 1767225600000)
        self.assertEqual(run('staleAt({updatedAt: "2026-01-01T00:00:00Z", activity: null})'), 1767225600000)
        text = DASHBOARD.read_text()
        card = text[text.index("function card(job)"):text.index("function digestCard(")]
        self.assertIn("Date.now() - staleAt(job) > STALE_MS", card)
        self.assertNotIn("Date.parse(job.updatedAt)", card)

    # --- closed questions (board.py ask): option buttons ---
    ASKED = {"key": "p/020-q", "project": "p", "id": "020-q", "title": "Asked", "stage": "needs-human", "worktree": "/w",
             "reason": "review: CHANGES after 3 rounds. Fix: pick one.", "updatedAt": "2026-01-01T00:00:00Z"}
    OPTIONS = [{"key": "c", "label": "Drop <it>", "command": "abort 020-q"},
               {"key": "a", "label": "Ship it", "command": "approve 020-q"},
               {"key": "b", "label": "Redo", "command": 'rework 020-q "again"'}]
    TODAY_ACTIONS = (
        '<div class="waiting" role="status"\n    data-agent-hint="This job stopped and needs Trevor. The first line is what is '
        'wrong; the second is the exact fix.">\n    <b>Waiting on you</b><p>review: CHANGES after 3 rounds.</p><p>Pick one.</p>'
        '</div><form data-act="approve">\n      \n      <button class="btn primary" type="submit">Approve &amp; merge</button>'
        '</form><form data-act="rework"><textarea name="feedback" required maxlength="2000" placeholder="What should the '
        'builder change?" aria-label="Feedback for the builder"></textarea>\n      <button class="btn" type="submit" '
        'data-act="discuss" formnovalidate data-agent-hint="Opens an interactive Claude session in a new Terminal window '
        'that explains why the job stopped and what a rework can or cannot fix, then runs the approve or rework you agree '
        'on.">Discuss first</button>\n      <button class="btn" type="submit">Send back to builder</button></form>'
        '<form data-act="ask"><button class="btn" type="submit" data-agent-hint="Opens a new interactive Claude session in '
        "the job's worktree (the repo's main checkout once that is gone), preloaded with the paths of the job's feature, "
        "spec, build, round and decision files and its board entry, to answer questions about the job.\">Ask Claude"
        '</button></form><form data-act="abort">\n    <label hidden><input type="checkbox" name="requeue"> Put back in '
        'backlog</label>\n    <button class="btn danger-outline" type="submit">Abort job</button></form>'
        '<p class="error" role="alert"></p>')
    TODAY_CARD = (
        '<button class="card human" data-key="p/020-q">\n    <span class="tag" style="--h:330">p</span><span class="lanechip">'
        'standard</span><span class="id">020-q</span><span class="title">Asked</span>\n    \n    \n    \n    \n    <span '
        'class="bar human" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="10" aria-label="Estimated '
        'progress" title="~10% (estimate)"><span style="width:10%"></span></span>\n    \n    <span class="reason">review: '
        'CHANGES after 3 rounds.</span>\n    \n    \n    \n    \n    \n    <span class="meta">T</span>\n  </button>')

    def card_js(self, tail):
        """Run tail in node over dashboard.html's top-level helpers, optionsRow, card and answer(), with $, post and poll
        stubbed: post calls land in `posted`, poll calls in `polls`. Prints what tail logs."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        src = (text[text.index("const STAGES = "):text.index("function roadmapLookup(")]
               + text[text.index("const splitReason = "):text.index("const waitingBanner = ")]
               + text[text.index("function card(job)"):text.index("function digestCard(")]
               + text[text.index("const ofJob = "):text.index("// answer() end")])
        src = src.replace("const $ = id => document.getElementById(id);", "const $ = id => stub;") \
            .replace("const post = (url, body) =>", "const realPost = (url, body) =>")
        script = ("const window = {}, document = {activeElement: null};\nconst stub = {open: false, dataset: {}, "
                  "querySelector: () => null, querySelectorAll: () => []};\nDate.prototype.toLocaleTimeString = () => 'T';\n"
                  "const posted = [], polls = [];\nlet postFails = null;\n"
                  "const post = async (url, body) => { posted.push([url, body]); if (postFails) throw new Error(postFails); return {}; };\n"
                  "const poll = async () => { polls.push(1); };\nconst renderActions = () => {};\n"
                  f"{src}\n(async () => {{ {tail} }})();")
        return [json.loads(l) for l in subprocess.run([node, "-e", script], capture_output=True, text=True,
                                                      check=True).stdout.splitlines()]

    def test_card_limit_hold_badge(self):
        old = "new Date(Date.now() - 2 * 3600 * 1000).toISOString()"
        base = '{key: "p/030-h", project: "p", id: "030-h", title: "Held", stage: "build", reason: null'
        [held, plain, human, stamp] = self.card_js(
            f"for (const extra of [', limitResetAt: 1800000000', '', ', stage: \"needs-human\", limitResetAt: 1800000000'])"
            f" console.log(JSON.stringify(card(eval(`({base}, updatedAt: {old}${{extra}}}})`))));"
            " console.log(JSON.stringify(when(1800000000)));")
        self.assertIn(f'<span class="badge">waiting for reset {stamp}</span>', held)
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertNotIn("stale since", held)
        self.assertIn("stale since", plain)  # the same 2-hour-old card without the hold is stale
        for html in (plain, human):
            self.assertNotIn("waiting for reset", html)
        text = DASHBOARD.read_text()
        self.assertIn("Date.now() - staleAt(job) > STALE_MS", text[text.index("function card(job)"):text.index("function digestCard(")])

    def test_no_options_unchanged(self):
        for extra in ({}, {"options": []}):
            with self.subTest(extra=extra):
                self.assertEqual(self.actions_html({**self.ASKED, **extra}), self.TODAY_ACTIONS)
                self.assertEqual(self.card_js(f"console.log(JSON.stringify(card({json.dumps({**self.ASKED, **extra})})));"),
                                 [self.TODAY_CARD])

    def test_options_replace_needs_human_row(self):
        html = self.actions_html({**self.ASKED, "question": "Which way?", "options": self.OPTIONS,
                                  "reason": "stalled in build: x. Fix: click Resume."})
        self.assertIn('<span class="reason">Which way?</span>', html)
        self.assertEqual(re.findall(r'<button class="btn tall" type="button" data-answer="(\w)">([^<]*)</button>', html),
                         [("a", "Ship it"), ("b", "Redo"), ("c", "Drop &lt;it&gt;")])
        for gone in ('data-act="resume"', 'data-act="approve"', "Discuss first", "Send back to builder"):
            self.assertNotIn(gone, html)
        for kept in (">Ask Claude</button>", ">Abort job</button>"):
            self.assertIn(kept, html)
        with_term = self.actions_html({**self.ASKED, "tty": "ttys001", "options": self.OPTIONS})
        self.assertIn(">Open terminal</button>", with_term)
        self.assertIn('<span class="reason">review: CHANGES after 3 rounds.</span>', with_term)  # no question: the problem line

    def test_option_buttons_post_answer(self):
        job = {**self.ASKED, "question": "Which way?", "options": self.OPTIONS}
        [html] = self.card_js(f"console.log(JSON.stringify(card({json.dumps(job)})));")
        self.assertTrue(html.startswith('<div class="card human" data-key="p/020-q" tabindex="0" role="button">'), html)
        self.assertTrue(html.endswith("</div>"), html)
        self.assertEqual(re.findall(r"<button[^>]*>", html),
                         ['<button class="btn tall" type="button" data-answer="a">',
                          '<button class="btn tall" type="button" data-answer="b">',
                          '<button class="btn tall" type="button" data-answer="c">'])
        self.assertIn('<span class="reason">Which way?</span>', html)
        self.assertNotIn("review: CHANGES after 3 rounds.", html)  # the question replaces the reason line
        setup = f"jobs = [{json.dumps(job)}];\nconst show = () => console.log(JSON.stringify([posted, polls.length, optionsRow(jobs[0])]));\n"
        approve = self.card_js(setup + 'await answer("p/020-q", "a"); show();')
        self.assertEqual(approve[0][:2], [[["api/p/p/jobs/020-q/answer", {"key": "a"}]], 1])
        armed = self.card_js(setup + 'await answer("p/020-q", "c"); show(); await answer("p/020-q", "c"); show();')
        self.assertEqual(armed[0][:2], [[], 0])  # the first click on an abort option only arms it
        self.assertIn('<button class="btn tall danger" type="button" data-answer="c">Confirm: Drop &lt;it&gt;</button>', armed[0][2])
        self.assertEqual(armed[1][:2], [[["api/p/p/jobs/020-q/answer", {"key": "c"}]], 1])
        self.assertNotIn("Confirm:", armed[1][2])
        failed = self.card_js(setup + 'postFails = "job isn\'t waiting <now>"; await answer("p/020-q", "b"); show();')
        self.assertEqual(failed[0][1], 0)
        self.assertIn('<p class="error" role="alert">job isn&#39;t waiting &lt;now&gt;</p>', failed[0][2])
        self.assertNotIn(" disabled", failed[0][2])  # re-enabled
        text = DASHBOARD.read_text()
        opener = text[text.rindex('$("board").addEventListener("click", e => {'):]
        self.assertIn('if (e.target.closest("button[data-answer]")) return;', opener)
        new = text[text.index("const answerState = "):text.index("const waitingBanner = ")] \
            + text[text.index("const ofJob = "):text.index("// answer() end")]
        self.assertIsNone(re.search(r"[^.\w](window\.)?(confirm|alert)\(", new))

    # --- needs-human: running line, outcome, feedback warning, Sent back list ---
    def test_running_line_shows_action_and_since(self):
        # 1767284460 s is 2026-01-01T16:21:00Z
        self.assertEqual(run('runLine({action: "rework", started: 1767284460, alive: true})', tz="UTC"),
                         "Rework running since 4:21 PM")
        self.assertEqual(run('runLine({action: "discuss", started: 1767229260.5, alive: true})', tz="UTC"),
                         "Discuss running since 1:01 AM")
        alive = {"rework": {"action": "rework", "started": 1767284460, "alive": True, "log": "runs/r.log"}}
        card = self.card_js(f"runs = {json.dumps({'p/020-q': alive['rework']})};"
                            f"console.log(JSON.stringify(card({json.dumps(self.ASKED)})));")[0]
        self.assertRegex(card, r'<span class="running">Rework running since \d{1,2}:21 [AP]M</span>')
        self.assertNotIn("running…", card)
        modal = self.actions_html(self.ASKED, runs={"p/020-q": alive["rework"]})
        self.assertRegex(modal, r'<p class="running">Rework running since \d{1,2}:21 [AP]M · <a href="p/p/runs/r.log"')
        discuss = self.actions_html(self.ASKED, runs={"p/020-q": {"action": "discuss", "started": 1767284460,
                                                                  "alive": True, "log": None}})
        self.assertRegex(discuss, r'<p class="running">Discuss running since \d{1,2}:21 [AP]M</p>')
        self.assertIn("Approve &amp; merge</button>", discuss)  # a Discuss session keeps the needs-human buttons
        self.assertNotIn("running…", DASHBOARD.read_text())

    def test_outcome_line_above_reason(self):
        line = "Approve refused at 4:21 PM: <b>budget</b>. Nothing changed."
        job = {**self.ASKED, "outcome": line}
        card = self.card_js(f"console.log(JSON.stringify(card({json.dumps(job)})));")[0]
        self.assertIn('<span class="meta" role="status">Approve refused at 4:21 PM: &lt;b&gt;budget&lt;/b&gt;. Nothing changed.'
                      '</span>\n    <span class="reason">review: CHANGES after 3 rounds.</span>', card)  # nothing between
        modal = self.actions_html(job)
        self.assertTrue(modal.startswith('<p class="note" role="status">Approve refused at 4:21 PM: &lt;b&gt;budget&lt;/b&gt;. '
                                         'Nothing changed.</p><div class="waiting" role="status"'), modal)
        for other in ({**self.ASKED, "outcome": None}, {**self.ASKED, "stage": "build", "outcome": line}):
            self.assertNotIn("Nothing changed", self.actions_html(other))
            other_card = self.card_js(f"console.log(JSON.stringify(card({json.dumps(other)})));")[0]
            self.assertNotIn("Nothing changed", other_card)
            self.assertNotIn("undefined", other_card)
        self.assertEqual(self.actions_html({**self.ASKED, "outcome": None}), self.TODAY_ACTIONS)

    def test_approve_warns_when_feedback_typed(self):
        warn = '<span class="error" role="alert">You typed feedback. Send it back instead?</span>'
        self.assertEqual(run('feedbackWarning("please fix the copy")'), warn)
        for empty in ('""', '"  \\n\\t "', "undefined"):
            self.assertEqual(run(f"feedbackWarning({empty})"), "", empty)
        text = DASHBOARD.read_text()
        submit = text[text.index('$("actions").addEventListener("submit"'):]
        armed = submit[submit.index('if (act === "approve" && !form.dataset.armed)'):submit.index('if (act === "abort"')]
        self.assertIn('btn.textContent = "Confirm: merge into main";', armed)
        self.assertIn("""feedbackWarning($("actions").querySelector('textarea[name="feedback"]')?.value)""", armed)

    def test_rework_entries_parse_and_render(self):
        md = "# Rework\nintro\n## 2026-01-01T16:21:00Z\nFirst <try>\nsecond line\n\n## not a date\nSecond\n## 2026-01-02T09:05:00Z\nThird\n"
        self.assertEqual(run(f"reworkEntries({json.dumps(md)})"), [
            {"at": "2026-01-02T09:05:00Z", "text": "Third"},
            {"at": "not a date", "text": "Second"},
            {"at": "2026-01-01T16:21:00Z", "text": "First <try>\nsecond line"}])
        self.assertEqual(run('reworkEntries("")'), [])
        self.assertEqual(run('reworkEntries("just text, no headings")'), [])
        job = {**self.ASKED, "files": ["spec.md", "rework.md"]}
        html = run(f"(reworkMd[{json.dumps(job['key'])}] = {json.dumps(md)}, reworkList({json.dumps(job)}))", tz="UTC")
        self.assertEqual(html, '<div class="sentback"><h3>Sent back</h3><ul>'
                               '<li><span class="note">2026-01-02 09:05</span> Third</li>'
                               '<li><span class="note">not a date</span> Second</li>'
                               '<li><span class="note">2026-01-01 16:21</span> First &lt;try&gt;\nsecond line</li></ul></div>')
        self.assertNotIn("Invalid Date", html)
        self.assertEqual(run(f"(reworkMd[{json.dumps(job['key'])}] = '', reworkList({json.dumps(job)}))"),
                         '<div class="sentback"></div>')
        self.assertEqual(run(f"reworkList({json.dumps(self.ASKED)})"), "")  # no rework.md in files
        self.assertEqual(run(f"reworkList({json.dumps({**job, 'stage': 'build'})})"), "")
        self.assertIn('<div class="sentback"></div><form data-act="ask">', self.actions_html(job))

if __name__ == "__main__":
    unittest.main()
