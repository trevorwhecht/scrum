"""The job modal subtitle shows a short line for a needs-human job whose red box holds the full reason."""
import json, re, unittest

from test_dashboard_job_modal import DASHBOARD
from test_dashboard_stop_buttons import ASKED, js

LONG = "Hard stop: schema — " + "The migration drops a column and rewrites every row. " * 3


class ModalStatusTest(unittest.TestCase):
    def run_js(self, jobs):
        return js(f"out({json.dumps(jobs)}.map(j => [modalStatus(j), statusLine(j), stopBox(j)]));")[0]

    def test_short_line_for_needs_human(self):
        a = {**ASKED, "reason": LONG, "stopTitle": "MERGE_BLOCKED"}
        b = {**ASKED, "reason": LONG}
        (s1, _, box), (s2, _, _) = self.run_js([a, b])
        self.assertEqual(s1, "Waiting on you: Merge blocked")
        self.assertEqual(s2, "Waiting on you: your decision")
        self.assertNotIn("migration", s1)
        self.assertIn("The migration drops a column", box)

    def test_other_jobs_keep_status_line(self):
        base = {**ASKED, "updatedAt": "2026-01-01T00:00:00Z"}
        jobs = [{**base, "stage": "build"}, {**base, "stage": "build", "paused": True}, {**base, "stage": "done"},
                {**base, "stage": "aborted"}, {**base, "stage": "build", "stalled": True, "reason": "stalled: x. Fix: y."},
                {**base, "stage": "build", "play_queued": "2026-01-01"}]
        for m, s, _ in self.run_js(jobs):
            self.assertEqual(m, s)

    def test_both_assignments_use_modal_status(self):
        text = DASHBOARD.read_text()
        self.assertEqual(len(re.findall(r'viewerStatus"?\)?\.textContent = modalStatus\(|status\.textContent = modalStatus\(', text)), 2)
        self.assertNotRegex(text, r'(viewerStatus"\)|status)\.textContent = statusLine\(')


if __name__ == "__main__":
    unittest.main()
