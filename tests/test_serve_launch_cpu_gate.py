"""Job 643: serve.spawn also queues a non-manual GATED launch while the CPU load is above MAX_LAUNCH_CPU_LOAD_PCT (500)."""
import os, unittest
from unittest import mock

import test_serve  # module import only: unittest must not collect ServeTest a second time from here

ServeBase = type("ServeBase", (unittest.TestCase,),
                 {k: v for k, v in vars(test_serve.ServeTest).items() if not k.startswith("test_")})


class LaunchCpuGate(ServeBase):
    def needs_human(self, title, **fields):
        b = self.serve.board
        job_id = b.cmd_new(self.root, title)
        self.edit_job(job_id, stage="needs-human", **fields)
        self.addCleanup(lambda: self.serve.RUNS.pop(f"repo/{job_id}", None))
        self.addCleanup(lambda: self.stage_of(job_id)["stage"] == "aborted" or b.cmd_abort(self.root, job_id, False))
        return job_id

    def launch(self, cpu, job_id, call):
        b = self.serve.board

        def fake_spawn(root, jid, action, prompt=None, flags=()):
            proc = mock.Mock()
            proc.poll.return_value = None
            return proc, f"runs/{jid}-{action}.log"

        env = {"SCRUM_FREE_RAM": "90", "SCRUM_SWAP_PCT": "0"}
        if cpu is not None:
            env["SCRUM_CPU_LOAD_PCT"] = str(cpu)
        with mock.patch.dict(os.environ, env), mock.patch.object(b, "machine_ok", return_value=None), \
                mock.patch.object(b, "session_ages", return_value=[]), \
                mock.patch.object(b, "cpu_load_pct", wraps=b.cpu_load_pct) as load, \
                mock.patch.object(b, "spawn", side_effect=fake_spawn) as spawn:
            if cpu is None:
                load.side_effect = lambda: None
            return call(), spawn

    def approve(self, job_id):
        return self.serve.spawn("repo", self.root, job_id, "approve", f"/trevskills-scrum approve {job_id}")

    def test_launch_queued_above_500_cpu(self):
        job_id = self.needs_human("Cpu hot", reason="approve: ready to merge")
        out, spawn = self.launch(600, job_id, lambda: self.approve(job_id))
        self.assertIsNone(out)
        spawn.assert_not_called()
        job = self.stage_of(job_id)
        self.assertTrue(job.get("play_queued"), job)
        self.assertEqual(job["queued_launch"], {"action": "approve", "stage": "needs-human",
                                                "prompt": f"/trevskills-scrum approve {job_id}"})

    def test_launch_starts_at_400_cpu(self):
        job_id = self.needs_human("Cpu warm", reason="approve: ready to merge")
        out, spawn = self.launch(400, job_id, lambda: self.approve(job_id))
        self.assertIsNotNone(out)
        self.assertEqual(spawn.call_count, 1)
        job = self.stage_of(job_id)
        self.assertNotIn("play_queued", job)
        self.assertNotIn("queued_launch", job)

    def test_manual_resume_skips_cpu_gate(self):
        job_id = self.needs_human("Cpu manual", reason=f"{self.serve.board.STALL}no output for 20 min")
        out, spawn = self.launch(600, job_id, lambda: self.raw_post(f"/api/p/repo/jobs/{job_id}/resume", {"manual": True}))
        self.assertEqual(out[0], 202, out)
        self.assertEqual(spawn.call_count, 1)

    def test_queue_tick_waits_for_cpu(self):
        job_id = self.needs_human("Cpu tick", reason="approve: ready to merge")
        self.launch(600, job_id, lambda: self.approve(job_id))
        s = self.serve
        tick = lambda: s.play_queue_tick("repo", self.root, s.board.read_board(self.root)["jobs"])
        with mock.patch.object(s, "take_room", return_value=True):
            out, spawn = self.launch(600, job_id, tick)
            self.assertTrue(out)
            spawn.assert_not_called()
            out, spawn = self.launch(400, job_id, tick)
            self.assertEqual(spawn.call_count, 1)
        self.assertNotIn("play_queued", self.stage_of(job_id))

    def test_no_cpu_reading_does_not_queue(self):
        job_id = self.needs_human("Cpu unknown", reason="approve: ready to merge")
        out, spawn = self.launch(None, job_id, lambda: self.approve(job_id))
        self.assertIsNotNone(out)
        self.assertEqual(spawn.call_count, 1)


if __name__ == "__main__":
    unittest.main()
