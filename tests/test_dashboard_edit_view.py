"""Job 1363: a needs-human edit job with stopTitle EDIT_APPROVE is green; when serve.py found its View line (`view`) the
stop box has a View button beside the Approve option. VIDEO_REVIEW stays green with no View; View posts once, is
disabled while pending, shows a refusal in the modal's error line, and Approve still posts the `approve` answer."""
import json, re, unittest

from test_dashboard_edit_preview import ASK as PREVIEW_ASK
from test_dashboard_play_queued import run

ASK = {**PREVIEW_ASK, "key": "edit/020-cut", "id": "020-cut", "stopTitle": "EDIT_APPROVE", "view": True}
OPTIONS = ASK["options"]


class EditView(unittest.TestCase):
    def test_edit_approve_is_green_with_view_and_approve(self):
        box, card = run(f"out(stopBox({json.dumps(ASK)})); out(card({json.dumps(ASK)}));")
        self.assertTrue(box.startswith('<div class="stop approve" role="status"'), box)
        self.assertRegex(card, r'^<button class="card human approve"')
        self.assertEqual(box.count("data-view"), 1)
        self.assertIn(">View</button>", box)
        self.assertIn('data-answer="a"', box)
        self.assertIn("Approve this cut", box)
        self.assertLess(box.index("data-view"), box.index('data-answer="a"'))
        self.assertEqual(card.count("<button"), 1, "the card is one button, with no nested button")

    def test_no_view_without_line_or_other_title(self):
        video, other, plain, built = run(
            f"out(stopBox({json.dumps({**ASK, 'stopTitle': 'VIDEO_REVIEW'})}));"
            f"out(stopBox({json.dumps({**ASK, 'stopTitle': 'BUILDER_BLOCKED'})}));"
            f"out(stopBox({json.dumps({**ASK, 'view': False})}));"
            f"out(stopBox({json.dumps({**ASK, 'stage': 'build'})}));")
        self.assertNotIn("data-view", video)
        self.assertTrue(video.startswith('<div class="stop approve"'), "VIDEO_REVIEW stays green")
        self.assertNotIn("data-view", other)
        self.assertTrue(other.startswith('<div class="stop" role="status"'), "any other title is red")
        self.assertNotIn("data-view", plain)
        self.assertTrue(plain.startswith('<div class="stop approve"'))
        self.assertEqual(built, "")

    def test_view_posts_once_disables_and_shows_refusal(self):
        a, b, c, d, e = run(f"""
            const job = {json.dumps(ASK)};
            jobs = [job]; $("viewer").dataset.key = job.key; $("viewer").open = true;
            const sent = []; let release = null;
            fetchImpl = async (url, opts) => {{ sent.push([url, opts.method, opts.body]); await new Promise(r => release = r);
              return {{ok: true, status: 200, json: async () => ({{}})}}; }};
            const btn = () => stopBox(job).match(/<button[^>]*data-view[^>]*>[^<]*/)[0];
            const p = view(job.key); view(job.key);
            out(btn());
            while (!release) await new Promise(r => setTimeout(r, 1));
            release(); await p;
            out(sent); out(btn());
            const line = {{textContent: ""}};
            $("actions").querySelector = s => s === ":scope > .error" ? line : null;
            fetchImpl = async () => ({{ok: false, status: 409, json: async () => ({{error: "the file does not exist"}})}});
            await view(job.key);
            out(line.textContent); out(actionError[job.key].msg);""")
        self.assertIn(" disabled", a)
        self.assertIn("Opening…", a)
        self.assertEqual(b, [["api/p/edit/jobs/020-cut/view", "POST", "{}"]], "one POST for two clicks")
        self.assertNotIn(" disabled", c)
        self.assertIn(">View", c)
        self.assertEqual((d, e), ("the file does not exist", "the file does not exist"))

    def test_approve_still_posts_approve_answer(self):
        sent, = run(f"""
            const job = {json.dumps(ASK)};
            jobs = [job]; $("viewer").dataset.key = job.key; $("viewer").open = true;
            const sent = [];
            fetchImpl = async (url, opts) => {{ sent.push([url, opts.body]); return {{ok: true, status: 200, json: async () => ({{}})}}; }};
            await answer(job.key, "a"); out(sent.slice(0, 1));""")
        self.assertEqual(sent, [["api/p/edit/jobs/020-cut/answer", '{"key":"a"}']])

    def test_click_routes_view_button_to_view(self):
        text = (__import__("pathlib").Path(__file__).resolve().parent.parent / "skills/trevskills-scrum/dashboard.html").read_text()
        self.assertRegex(text, r'closest\("button\[data-answer\], button\[data-send\], button\[data-view\]"\)')
        self.assertIn('if (b && "view" in b.dataset) view(key);', text)


if __name__ == "__main__":
    unittest.main()
