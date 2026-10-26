"""Repro for job 429: a closed-question `resume` answer the machine guard refuses gets a 409 instead of being queued like
a Play click (play_queued), and the job modal's file tabs fetch `<git base>spec.md` (404) for any board job with a `base`."""
import json, os, unittest
from unittest import mock

import test_serve  # module import only: unittest must not collect ServeTest a second time from here
from test_dashboard_stop_buttons import ASKED, js
from test_dashboard_roadmap_card import run

# ServeTest's shared server and helpers (asked, stage_of, raw_post, ...) without its own test methods.
ServeBase = type("ServeBase", (unittest.TestCase,),
                 {k: v for k, v in vars(test_serve.ServeTest).items() if not k.startswith("test_")})

T1, T2 = "2026-10-25T10:00:00+00:00", "2026-10-25T11:00:00+00:00"
QUEUED = {"action": "answer", "command": "resume", "queued": True, "message": "queued, starts next"}


class AnswerResumeQueue(ServeBase):
    def asked_resume(self):
        job_id = self.serve.board.cmd_new(self.root, "Asked resume")
        opts = [{"key": "a", "label": "Keep my changes and carry on", "command": f"resume {job_id}"},
                {"key": "b", "label": "Remove this job", "command": f"abort {job_id} --cascade"}]
        self.edit_job(job_id, stage="needs-human", reason="blocked: uncommitted changes. Fix: pick one.",
                      question="Keep the changes?", options=opts)
        self.addCleanup(lambda: self.stage_of(job_id)["stage"] == "aborted"
                        or self.serve.board.cmd_abort(self.root, job_id, False))
        return job_id

    def picks(self, job_id):
        log = self.root / "questions.log"
        lines = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        return [l["pick"] for l in lines if l.get("job") == job_id and "pick" in l]

    def queue_by_answer(self, job_id):
        b = self.serve.board
        with mock.patch.dict(os.environ, SCRUM_FREE_RAM="14"), mock.patch.object(self.serve, "spawn") as spawn:
            with mock.patch.object(b, "now", return_value=T1):
                first = self.raw_post(f"/api/p/repo/jobs/{job_id}/answer", {"key": "a"})
            with mock.patch.object(b, "now", return_value=T2):
                second = self.raw_post(f"/api/p/repo/jobs/{job_id}/answer", {"key": "a"})
        return first, second, spawn

    def test_answer_resume_machine_refusal_queues(self):
        job_id = self.asked_resume()
        first, second, spawn = self.queue_by_answer(job_id)
        self.assertEqual(first, (202, {"id": job_id, **QUEUED}))
        self.assertEqual(second, (202, {"id": job_id, **QUEUED}))
        self.assertEqual(self.stage_of(job_id).get("play_queued"), T1, "the first click's time")
        self.assertIn("Keep my changes and carry on", self.picks(job_id))
        spawn.assert_not_called()

    def test_play_queue_tick_starts_answered_resume(self):
        job_id = self.asked_resume()
        self.queue_by_answer(job_id)
        jobs = json.loads((self.root / "board.json").read_text())["jobs"]
        with mock.patch.object(self.serve, "spawn") as spawn:
            self.serve.play_queue_tick("repo", self.root, jobs)
        self.assertEqual([c.args[2:] for c in spawn.call_args_list],
                         [(job_id, "resume", f"/trevskills-scrum resume {job_id}")])
        self.assertNotIn("play_queued", self.stage_of(job_id))

    def test_answer_abort_while_queued(self):
        job_id = self.asked_resume()
        self.queue_by_answer(job_id)
        self.assertEqual(self.stage_of(job_id).get("play_queued"), T1)
        with mock.patch.object(self.serve, "stop"), mock.patch.object(self.serve, "spawn"):
            code, out = self.raw_post(f"/api/p/repo/jobs/{job_id}/answer", {"key": "b"})
        self.assertEqual((code, out["stage"]), (200, "aborted"))
        self.assertNotIn("play_queued", self.stage_of(job_id))


OPTIONS = [{"key": "a", "label": "Keep my changes and carry on", "command": "resume 020-q"},
           {"key": "b", "label": "Remove this job", "command": "abort 020-q --cascade"}]


class DashboardRepro(unittest.TestCase):
    def test_stop_box_hides_options_when_queued(self):
        job = {**ASKED, "options": OPTIONS}
        queued, plain = js(f"out(stopBox({json.dumps({**job, 'play_queued': T1})})); out(stopBox({json.dumps(job)}));")
        self.assertNotIn("data-answer", queued)
        self.assertEqual(plain.count("data-answer="), 2, plain)

    def test_show_ignores_job_git_base(self):
        job = {"key": "p/403-x", "project": "p", "id": "403-x", "base": "origin/main"}
        got, = run(f'await show({json.dumps(job)}, "spec.md"); await show(roadmapDoc("p"), "roadmap.md");'
                   ' console.log(JSON.stringify(fetched));', {}, projects=("p",))
        self.assertEqual(got, ["p/p/jobs/403-x/spec.md", "p/p/roadmap.md"])


if __name__ == "__main__":
    unittest.main()
