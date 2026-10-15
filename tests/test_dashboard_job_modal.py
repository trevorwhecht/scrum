import json, re, shutil, subprocess, unittest
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


def run(expr):
    """Evaluate expr in node over dashboard.html's esc and its job-modal helpers, with JOBS as the board."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = next(l for l in text.splitlines() if l.startswith("const esc = "))
    helpers = text[text.index("const setupWait = "):text.index("function bigboyLines(")] \
        + text[text.index("const abortForm = "):text.index("const termState = ")]
    script = f"{esc}\nlet jobs = {json.dumps(JOBS)};\n{helpers}\nconsole.log(JSON.stringify({expr}));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


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

    def test_stale_uses_newest_activity(self):
        # 2026-01-01T00:00:00Z is 1767225600 s
        self.assertEqual(run('staleAt({updatedAt: "2026-01-01T00:00:00Z", activity: {at: 1767229200}})'), 1767229200000)
        self.assertEqual(run('staleAt({updatedAt: "2026-01-01T00:00:00Z", activity: {at: 1767222000}})'), 1767225600000)
        self.assertEqual(run('staleAt({updatedAt: "2026-01-01T00:00:00Z", activity: null})'), 1767225600000)
        text = DASHBOARD.read_text()
        card = text[text.index("function card(job)"):text.index("function digestCard(")]
        self.assertIn("Date.now() - staleAt(job) > STALE_MS", card)
        self.assertNotIn("Date.parse(job.updatedAt)", card)


if __name__ == "__main__":
    unittest.main()
