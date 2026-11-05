"""Repro for job 624: approve/rework/resume/answer clicks on several needs-human jobs in one burst each start a session,
past board.ram_room. With SCRUM_FREE_RAM=30 (2 shares of SESSION_RAM_PCT above MIN_FREE_RAM_PCT) and no session running,
4 launches back to back must start only 2; the other 2 stay needs-human and queued."""
import json, os, unittest
from unittest import mock

import test_serve  # module import only: unittest must not collect ServeTest a second time from here

# ServeTest's shared server and helpers (stage_of, edit_job, raw_post, ...) without its own test methods.
ServeBase = type("ServeBase", (unittest.TestCase,),
                 {k: v for k, v in vars(test_serve.ServeTest).items() if not k.startswith("test_")})


class LaunchGate(ServeBase):
    def needs_human(self, title, **fields):
        b = self.serve.board
        job_id = b.cmd_new(self.root, title)
        self.edit_job(job_id, stage="needs-human", **fields)
        self.addCleanup(lambda: self.serve.RUNS.pop(f"repo/{job_id}", None))
        self.addCleanup(lambda: self.stage_of(job_id)["stage"] == "aborted" or b.cmd_abort(self.root, job_id, False))
        return job_id

    def test_resolving_n_needs_human_jobs_starts_at_most_ram_room(self):
        b = self.serve.board
        approve = self.needs_human("Gate approve", reason="approve: ready to merge")
        rework = self.needs_human("Gate rework", reason="approve: ready to merge")
        resume = self.needs_human("Gate resume", reason=f"{b.STALL}no output for 20 min")
        answer = self.needs_human("Gate answer", reason="blocked: pick one. Fix: answer.", question="Merge it?",
                                  options=[{"key": "a", "label": "Merge", "command": "approve PLACEHOLDER"}])
        self.edit_job(answer, options=[{"key": "a", "label": "Merge", "command": f"approve {answer}"}])

        ages = []  # every board.spawn adds one session ps would see, 0 s old

        def fake_spawn(root, job_id, action, prompt=None, flags=()):
            ages.append(0)
            proc = mock.Mock()
            proc.poll.return_value = None
            return proc, f"runs/{job_id}-{action}.log"

        with mock.patch.dict(os.environ, SCRUM_FREE_RAM="30", SCRUM_SWAP_PCT="0"), \
                mock.patch.object(b, "machine_ok", return_value=None), \
                mock.patch.object(b, "session_ages", side_effect=lambda: list(ages)), \
                mock.patch.object(b, "spawn", side_effect=fake_spawn) as spawn:
            replies = [
                self.raw_post(f"/api/p/repo/jobs/{approve}/approve", {}),
                self.raw_post(f"/api/p/repo/jobs/{rework}/rework", {"feedback": "Rename the button"}),
                self.raw_post(f"/api/p/repo/jobs/{resume}/resume", {"manual": True}),
                self.raw_post(f"/api/p/repo/jobs/{answer}/answer", {"key": "a"}),
            ]

        self.assertEqual([c.args[1:3] for c in spawn.call_args_list], [(approve, "approve"), (rework, "rework")],
                         f"only ram_room's 2 sessions may start; replies: {replies}")
        for code, out in replies[2:]:
            self.assertEqual(code, 202, out)
            self.assertEqual((out.get("queued"), out.get("message")), (True, "queued, starts next"), out)
        for job_id, action in ((resume, "resume"), (answer, "approve")):
            job = self.stage_of(job_id)
            self.assertEqual(job["stage"], "needs-human")
            self.assertTrue(job.get("play_queued"), job)
            self.assertEqual(job.get("queued_launch"), {"action": action, "stage": "needs-human",
                                                        "prompt": f"/trevskills-scrum {action} {job_id}"})


if __name__ == "__main__":
    unittest.main()
