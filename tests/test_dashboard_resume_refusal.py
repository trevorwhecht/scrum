"""A refused Play/Resume click (POST resume -> 409 {error}) shows its reason in #actions directly under the Play/Resume
button, before Pause and More, and keeps it across poll re-renders until the stage changes or a later POST succeeds."""
import json, unittest
from unittest import mock

import test_dashboard_stop_buttons as stop
from test_dashboard_stop_buttons import ASKED, DASHBOARD, js

MSG = "can't resume yet: 222. Fix: click Resume when 222 finish."
SHOWN = "can&#39;t resume yet: 222. Fix: click Resume when 222 finish."
ALERT = f'<p class="error" role="alert">{SHOWN}</p>'
PAUSED = {"key": "p/020-q", "project": "p", "id": "020-q", "stage": "build", "paused": True, "parent": "192-run-all",
          "reason": "stalled in build: paused by Trevor. Fix: click Play.", "updatedAt": "2026-01-01T00:00:00Z"}
STALLED = {**ASKED, "reason": "stalled in check: no board update for 30 min. Fix: click Resume."}
CASES = ((PAUSED, "Play"), (STALLED, "Resume"))
# A job stalled in its own stage (board `stalled` true) keeps its stage, so its panel takes the not-needs-human branch.
NEW_SHAPE = {"key": "p/020-q", "project": "p", "id": "020-q", "stage": "build", "stalled": True, "worktree": "/tmp/wt-021",
             "reason": "stalled: no live session. Fix: click Resume.", "updatedAt": "2026-01-01T00:00:00Z"}
SUBMIT = ('{ const btn = {dataset: {}, disabled: false}; window.btn = btn; await handlers.submit({preventDefault() {},'
          ' submitter: btn, target: {dataset: {act: "resume"}, querySelector: () => btn}}); }')

# The real post() over a stubbed fetch, so a 500 with no JSON and a network error go through the dashboard's own code.
_text = DASHBOARD.read_text()
REAL_POST = _text[_text.index("const post = (url, body) =>"):_text.index("return data; });", _text.index("const post = (url, body) =>")) + len("return data; });")]
REAL_HARNESS = (stop.HARNESS
                .replace(next(l for l in stop.HARNESS.splitlines() if l.startswith("const post = ")), REAL_POST)
                .replace(next(l for l in stop.HARNESS.splitlines() if l.startswith("const fetch = ")),
                         "let fetchImpl = null;\nconst fetch = async (url, opts) => { fetched.push(url); return fetchImpl(url, opts); };"))


def assert_inline(case, html, label, alert=ALERT):
    """The alert sits directly after the resume form, once, before any Pause form or More menu."""
    case.assertIn(f">{label}</button></form>{alert}", html)
    at = html.index(alert)
    for later in ('data-act="pause"', '<details class="more"'):
        if later in html:
            case.assertLess(at, html.index(later), html)
    case.assertEqual(html.count('role="alert"'), 1, html)


class RefusedResume(unittest.TestCase):
    def test_refused_resume_shows_reason_inline(self):
        offered, refused = js(f"""const n = {json.dumps(NEW_SHAPE)}; jobs = [n]; renderActions(n); out(els.actions.innerHTML);
            jobs = [{{...n, resumeRefusal: {json.dumps(MSG)}}}]; renderActions(jobs[0]); out(els.actions.innerHTML);""")
        self.assertIn('<form data-act="resume"><button class="btn primary tall" type="submit">Resume</button></form>', offered)
        for gone in ('data-act="approve"', 'data-act="rework"'):
            self.assertNotIn(gone, offered)
        self.assertNotIn('data-act="resume"', refused)
        for job, label in CASES + ((NEW_SHAPE, "Resume"),):
            with self.subTest(label=label):
                shown, viewer, disabled, html = js(f"""jobs = [{json.dumps(job)}]; renderActions(jobs[0]);
                    postFails = {json.dumps(MSG)}; {SUBMIT}
                    out(errP.textContent === {json.dumps(MSG)} || els.actions.innerHTML.includes({json.dumps(SHOWN)}));
                    out(els.viewer.open); out(window.btn.disabled);
                    renderActions(jobs[0]); out(els.actions.innerHTML);""")
                self.assertTrue(shown)
                self.assertTrue(viewer)  # the modal stays open
                self.assertFalse(disabled)  # Play/Resume is clickable again
                assert_inline(self, html, label)
        # A 500 with no JSON body and a network error show in the same place.
        for fetch, want in (('async () => ({ok: false, status: 500, json: async () => { throw new Error("not json"); }})', "HTTP 500"),
                            ('async () => { throw new TypeError("Failed to fetch"); }', "Failed to fetch")):
            for job, label in CASES:
                with self.subTest(label=label, want=want), mock.patch.object(stop, "HARNESS", REAL_HARNESS):
                    html, = js(f"""jobs = [{json.dumps(job)}]; renderActions(jobs[0]); fetchImpl = {fetch}; {SUBMIT}
                        renderActions(jobs[0]); out(els.actions.innerHTML);""")
                    assert_inline(self, html, label, f'<p class="error" role="alert">{want}</p>')

    def test_refused_resume_reason_survives_poll(self):
        for job, label in CASES:
            with self.subTest(label=label):
                again, waiting = js(f"""jobs = [{json.dumps(job)}]; renderActions(jobs[0]);
                    postFails = {json.dumps(MSG)}; {SUBMIT}
                    renderActions(jobs[0]); renderActions(jobs[0]); out(els.actions.innerHTML);
                    jobs[0] = {{...jobs[0], resumeRefusal: {json.dumps(MSG)}}}; renderActions(jobs[0]); out(els.actions.innerHTML);""")
                assert_inline(self, again, label)
                # The poll swapped the button out; only a paused job gets the "Waiting:" note (its status line hides the reason).
                # Either way the full reason is still there once.
                self.assertNotIn('data-act="resume"', waiting)
                note = '<p class="note" role="status">Waiting: can&#39;t resume yet: 222.</p>'
                if job is PAUSED: self.assertIn(f'{note}{ALERT}', waiting)
                else: self.assertNotIn(note, waiting)
                self.assertEqual(waiting.count(SHOWN), 1, waiting)

    def test_refused_resume_reason_clears(self):
        for job, label in CASES:
            with self.subTest(label=label):
                moved, ok = js(f"""jobs = [{json.dumps(job)}]; renderActions(jobs[0]);
                    postFails = {json.dumps(MSG)}; {SUBMIT}
                    renderActions({{...jobs[0], stage: "review"}}); out(els.actions.innerHTML);
                    {SUBMIT} postFails = null; {SUBMIT} renderActions(jobs[0]); out(els.actions.innerHTML);""")
                self.assertNotIn("resume yet", moved)
                self.assertNotIn("resume yet", ok)


if __name__ == "__main__":
    unittest.main()
