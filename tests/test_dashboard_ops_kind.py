"""Job 1426: a card for an ops or knowledge job shows its kind in the coloured project tag (keeping `data-project` and the
project's colour) and renders in the existing columns with no PR link and no review control."""
import json, re, unittest

from test_dashboard_play_queued import run

JOB = {"key": "shop/310-run", "project": "shop", "id": "310-run", "title": "Prod data run", "stage": "build",
       "lane": "ops", "updatedAt": "2026-11-22T10:00:00Z"}
TAG = re.compile(r'<span class="tag" data-project="([^"]*)" style="([^"]*)">([^<]*)</span>')


class OpsKindTag(unittest.TestCase):
    def test_card_tag_shows_kind(self):
        plain = run(f"out(card({json.dumps(JOB)}));")[0]
        plain_style = TAG.findall(plain)[0][1]
        for kind in ("ops-data", "ops-content", "knowledge"):
            html = run(f"out(card({json.dumps({**JOB, 'kind': kind})}));")[0]
            tags = TAG.findall(html)
            self.assertEqual(len(tags), 1, html)
            self.assertEqual((tags[0][0], tags[0][2]), ("shop", kind))
            self.assertEqual(tags[0][1], plain_style, "the kind tag keeps the project's colour")

    def test_ops_stages_render_with_no_pr_or_review_control(self):
        for stage in ("spec", "build", "shipping", "needs-human", "done"):
            html = run(f"out(card({json.dumps({**JOB, 'kind': 'ops-data', 'stage': stage})}));")[0]
            self.assertIn("310-run", html, stage)
            self.assertNotIn("PR ready", html, stage)
        with_pr = run(f"out(card({json.dumps({**JOB, 'kind': 'ops-data', 'pr': 'https://github.com/a/b/pull/5'})}));")[0]
        self.assertIn("PR ready", with_pr)  # the check above can fail: a PR-less job simply has none


if __name__ == "__main__":
    unittest.main()
