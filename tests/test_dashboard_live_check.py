"""Job 1496: a done job with a board `liveCheck` shows one `Live check: ...` line (serve.py liveCheckInfo) on its card
and in its modal, and a waiting one reads `Done, live check waiting`; a done job without the field renders as before."""
import json, os, unittest

from test_dashboard_play_queued import run

JOB = {"key": "p/1496-a", "project": "p", "id": "1496-a", "title": "Live job", "stage": "done",
       "updatedAt": "2026-11-18T10:00:00Z"}
NOON = 1_796_126_400  # 2026-12-01T12:00:00Z: the same local date from UTC-11 to UTC+11
WAITING = {"liveCheck": "waiting", "liveCheckInfo": {"state": "waiting", "until": NOON}}


def both(**kw):
    job = json.dumps({**JOB, **kw})
    return f"out(card({job})); out(actionsHtml({job}, '')); out(statusLine({job}));"


class LiveCheckLine(unittest.TestCase):
    def setUp(self):
        os.environ["TZ"] = "America/Los_Angeles"
        self.addCleanup(os.environ.pop, "TZ", None)

    def test_four_lines_on_card_and_modal(self):
        cases = [
            (WAITING, "Live check: waiting until 2026-12-01"),
            ({"liveCheck": "passed", "liveCheckInfo": {"state": "passed", "at": NOON}}, "Live check: passed 2026-12-01"),
            ({"liveCheck": "failed", "liveCheckInfo": {"state": "failed", "item": "Live check failed: 1496-a"}},
             "Live check: failed, see backlog &quot;Live check failed: 1496-a&quot;"),
            ({"liveCheck": "refused", "liveCheckInfo": {"state": "refused", "reason": "nope is not a package.json script"}},
             "Live check: refused, nope is not a package.json script"),
        ]
        for kw, line in cases:
            card, modal, _ = run(both(**kw))
            self.assertIn(f'<span class="meta">{line}</span>', card)
            self.assertIn(f'<p class="note">{line}</p>', modal)

    def test_waiting_status(self):
        self.assertEqual(run(both(**WAITING))[2], "Done, live check waiting")
        self.assertEqual(run(both(liveCheck="passed", liveCheckInfo={"state": "passed", "at": NOON}))[2], "Done")

    def test_done_without_field_unchanged(self):
        card, modal, status = run(both())
        self.assertEqual(status, "Done")
        self.assertNotIn("Live check", card)
        self.assertNotIn("Live check", modal)


if __name__ == "__main__":
    unittest.main()
