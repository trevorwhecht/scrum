"""Job 1232: a backlog row's "waits on:" tag (needsTag) names the item's {after repo:job} refs and the requeue loop guard
(board.py requeue_loop), not only its {needs #id} prerequisites."""
import json, shutil, subprocess, unittest

from test_dashboard_job_modal import DASHBOARD

LOOP_TITLE = "an edit: its last 3 claims were requeue aborts within 24 h"


def tag(it, all_items=()):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = next(l for l in text.splitlines() if l.startswith("const esc = "))
    fn = text[text.index("function needsTag("):text.index("function prioTag(")]
    script = f"{esc}\n{fn}\nconsole.log(JSON.stringify(needsTag({json.dumps(it)}, {json.dumps(list(all_items))})));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


class BacklogWaitsTag(unittest.TestCase):
    def test_after_ref_waiting(self):
        self.assertEqual(tag({"needs": [], "after": ["onewitharts:1600"], "waits": ["onewitharts:1600"]}),
                         '<span class="needs" title="onewitharts job 1600">waits on: onewitharts job 1600</span>')

    def test_after_ref_done_is_muted(self):
        self.assertEqual(tag({"needs": [], "after": ["onewitharts:1600"], "waits": []}),
                         '<span class="needs met" title="onewitharts job 1600">waits on: onewitharts job 1600</span>')

    def test_requeue_loop_says_edit_it(self):
        self.assertEqual(tag({"needs": [], "after": [], "waits": ["requeue loop"]}),
                         f'<span class="needs" title="{LOOP_TITLE}">waits on: an edit (3 requeues in 24 h)</span>')

    def test_needs_after_and_loop_together(self):
        it = {"needs": ["base"], "after": ["x:1"], "waits": ["base", "x:1", "requeue loop"]}
        self.assertEqual(tag(it, [{"id": "base", "text": "Base item"}]),
                         f'<span class="needs" title="Base item; x job 1; {LOOP_TITLE}">'
                         "waits on: Base item, x job 1, an edit (3 requeues in 24 h)</span>")

    def test_long_after_ref_cut_with_full_title(self):
        self.assertEqual(tag({"needs": [], "after": ["onewitharts:1600-a-very-long-job-slug-here"], "waits": []}),
                         '<span class="needs met" title="onewitharts job 1600-a-very-long-job-slug-here">'
                         "waits on: onewitharts job 1600-a-very-long-job-sl…</span>")  # its first 39 chars

    def test_nothing_to_wait_on_is_empty(self):
        self.assertEqual(tag({"needs": [], "after": [], "waits": []}), "")
        self.assertEqual(tag({"needs": [], "waits": []}), "")  # a list from a serve.py before the after field


if __name__ == "__main__":
    unittest.main()
