"""Job 1398: an edit job waiting on Trevor's VIDEO_REVIEW shows its clip and pictures (serve.py `preview`) in the stop
box above the option buttons, and the box and its board card are green (`approve`), not red. A job with no preview
keeps the stop box it had; every other stop title stays red."""
import json, re, unittest

from test_dashboard_play_queued import DASHBOARD, run

ASK = {"key": "edit/010-cut", "project": "edit", "id": "010-cut", "title": "Reef ad", "stage": "needs-human",
       "lane": "edit", "reason": "video cut", "question": "Approve this cut, or send notes?", "stopTitle": "VIDEO_REVIEW",
       "options": [{"key": "a", "label": "Approve this cut", "command": "approve 010-cut"},
                   {"key": "b", "label": "Send back with a note", "command": "rework 010-cut \"notes\""},
                   {"key": "c", "label": "Remove this job", "command": "abort 010-cut --cascade"}],
       "recommend": {"key": "a", "why": "it passed review"}, "updatedAt": "2026-11-22T10:00:00Z"}
PREVIEW = [{"n": 0, "name": "v2 master.mp4", "type": "video"}, {"n": 1, "name": "sheet <1>.jpg", "type": "image"}]
BLOCKED = {**ASK, "key": "edit/011-blk", "id": "011-blk", "stopTitle": "BUILDER_BLOCKED"}


class EditPreview(unittest.TestCase):
    def test_stop_box_shows_video_and_image_above_buttons(self):
        html, = run(f"out(stopBox({json.dumps({**ASK, 'preview': PREVIEW})}));")
        self.assertIn('<video controls playsinline preload="metadata" src="api/p/edit/jobs/010-cut/preview/0"></video>', html)
        self.assertIn('<img alt="sheet &lt;1&gt;.jpg" src="api/p/edit/jobs/010-cut/preview/1">', html)
        self.assertLess(html.index("<video"), html.index("<img"))
        self.assertLess(html.index("<img"), html.index('<div class="acts">'))
        self.assertLess(html.index("Approve this cut, or send notes?"), html.index("<video"))

    def test_preview_src_encodes_project_and_id(self):
        html, = run(f"out(stopBox({json.dumps({**ASK, 'project': 'a b', 'id': '010/x', 'preview': PREVIEW[:1]})}));")
        self.assertIn('src="api/p/a%20b/jobs/010%2Fx/preview/0"', html)

    def test_no_preview_stop_box_unchanged(self):
        bare, empty, other = run(f"out(stopBox({json.dumps(BLOCKED)}));"
                                 f"out(stopBox({json.dumps({**BLOCKED, 'preview': []})}));"
                                 f"out(stopBox({json.dumps({**BLOCKED, 'stage': 'build', 'preview': PREVIEW})}));")
        self.assertTrue(bare.startswith('<div class="stop" role="status"'), bare)
        self.assertNotIn("<video", bare)
        self.assertNotIn("<img", bare)
        self.assertNotIn("preview", bare)
        self.assertEqual(empty, bare)
        self.assertEqual(other, "", "a job not waiting on Trevor has no stop box")

    def test_video_review_is_green(self):
        stop, blocked, card, blocked_card, built_card = run(
            f"out(stopBox({json.dumps(ASK)})); out(stopBox({json.dumps(BLOCKED)}));"
            f"out(card({json.dumps(ASK)})); out(card({json.dumps(BLOCKED)}));"
            f"out(card({json.dumps({**ASK, 'stage': 'build'})}));")
        self.assertTrue(stop.startswith('<div class="stop approve" role="status"'), stop)
        self.assertTrue(blocked.startswith('<div class="stop" role="status"'), blocked)
        self.assertRegex(card, r'^<button class="card human approve"')
        self.assertRegex(blocked_card, r'^<button class="card human"')
        self.assertNotIn("approve", re.match(r'<button class="([^"]*)"', blocked_card).group(1))
        self.assertNotIn("approve", re.match(r'<button class="([^"]*)"', built_card).group(1))

    def test_css_draws_approve_green(self):
        css = DASHBOARD.read_text()
        css = css[:css.index("</style>")]
        self.assertRegex(css, r"\.stop\.approve\{[^}]*border-color:var\(--pass\)[^}]*background:color-mix\(in srgb,var\(--pass\) 8%")
        self.assertRegex(css, r"\.stop\.approve b\{color:var\(--pass\)\}")
        self.assertRegex(css, r"\.card\.human\.approve\{[^}]*border-color:var\(--pass\)[^}]*var\(--pass\) 15%")
        self.assertRegex(css, r"\.stop \.preview video,\.stop \.preview img\{[^}]*max-width:100%")
        self.assertRegex(css, r"\.stop \.preview img\{[^}]*max-height:", "round 1: a tall picture never pushes Approve off a 1440 px screen")

    def test_sig_names_job_urls_and_rev(self):
        """Round 1: two jobs listing the same basenames, or a new cut under the same name, never share a signature, so
        keepPreview never puts one job's (or an old cut's) media into another stop box."""
        same = [{**e, "rev": "1-20"} for e in PREVIEW]
        other = {**ASK, "key": "edit/012-two", "id": "012-two", "preview": same}
        sigs = run(f"""
            const sig = j => stopBox(j).match(/class="preview" data-sig="([^"]*)"/)[1];
            const a = {json.dumps({**ASK, 'preview': same})}, b = {json.dumps(other)};
            const c = {json.dumps({**other, 'project': 'edit2', 'key': 'edit2/012-two'})};
            const d = {json.dumps({**other, 'preview': [{**e, 'rev': '2-31'} for e in PREVIEW]})};
            out([sig(a), sig(b), sig(c), sig(d), sig({{...a, question: "poll"}})]);""")[0]
        a, b, c, d, a_again = sigs
        self.assertEqual(len({a, b, c, d}), 4, sigs)
        self.assertEqual(a, a_again, "the same files on the same job keep their media")
        for part in ("010-cut", "api/p/edit/jobs/010-cut/preview/0", "api/p/edit/jobs/010-cut/preview/1", "1-20"):
            self.assertIn(part, a)
        self.assertIn("2-31", d)
        swapped = run(f"""
            const sig = j => stopBox(j).match(/class="preview" data-sig="([^"]*)"/)[1].replace(/&quot;/g, '"');
            const node = s => ({{dataset: {{sig: s}}, swapped: null, replaceWith(x) {{ this.swapped = x; }}}});
            const from = node(sig({json.dumps({**ASK, 'preview': same})})), to = node(sig({json.dumps(other)}));
            keepPreview(from, {{querySelector: () => to}}); out(to.swapped);""")[0]
        self.assertIsNone(swapped, "job B never gets job A's media")

    def test_rerender_keeps_playing_media(self):
        same, changed = run("""
            const node = sig => ({dataset: {sig}, swapped: null, replaceWith(x) { this.swapped = x; }});
            const old = node("a"), now = node("a"), next = node("b");
            keepPreview(old, {querySelector: s => s === ".stop .preview" ? now : null});
            keepPreview(old, {querySelector: () => next});
            keepPreview(null, {querySelector: () => next});
            keepPreview(old, {querySelector: () => null});
            out(now.swapped === old); out(next.swapped);""")
        self.assertTrue(same, "the same files keep the old, possibly playing, <video>")
        self.assertIsNone(changed, "a new cut renders its own media")


if __name__ == "__main__":
    unittest.main()
