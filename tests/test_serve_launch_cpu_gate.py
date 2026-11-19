"""Job 643: serve.spawn also queues a non-manual GATED launch while the CPU load is above MAX_LAUNCH_CPU_LOAD_PCT (500)."""
import json, os, shutil, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
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

    def cpu_held_job(self, title, lane, queued_at, gate="cpu_load(600%)", **fields):
        """A needs-human job spawn's CPU gate queued: play_queued, queued_launch in its stage, `gate` in queue-gates.txt."""
        job_id = self.needs_human(title, reason="approve: ready to merge", lane=lane, play_queued=queued_at,
                                  queued_launch={"action": "start", "prompt": "/trevskills-scrum start x",
                                                 "stage": "needs-human"}, **fields)
        (self.root / "jobs" / job_id / "queue-gates.txt").write_text(gate + "\n")
        return job_id

    def test_play_queue_tick_light_job_first(self):
        std = self.needs_human("Cpu std", reason="approve: ready to merge", lane="standard")
        fast = self.needs_human("Cpu fast", reason="approve: ready to merge", lane="fast")
        self.launch(600, std, lambda: self.approve(std))
        self.launch(600, fast, lambda: self.approve(fast))
        self.edit_job(std, play_queued="2026-11-16T00:00:00+00:00")
        self.edit_job(fast, play_queued="2026-11-16T05:00:00+00:00")
        s = self.serve
        tick = lambda: s.play_queue_tick("repo", self.root, s.board.read_board(self.root)["jobs"])
        with mock.patch.object(s, "take_room", return_value=True):
            _, spawn = self.launch(400, fast, tick)
        self.assertEqual([c.args[1] for c in spawn.call_args_list], [fast, std])

    def test_play_queue_tick_cpu_held_before_cpu_queue(self):
        """Review round 1: a newer fast cpu_queue-only launch never stands in front of the older CPU-held standard one."""
        held = self.cpu_held_job("Cpu held std", "standard", "2020-01-01T00:00:00+00:00")
        fresh = self.cpu_held_job("Cpu queue fast", "fast", "2026-11-16T05:00:00+00:00", gate="cpu_queue")
        s = self.serve
        tick = lambda: s.play_queue_tick("repo", self.root, s.board.read_board(self.root)["jobs"])
        with mock.patch.object(s, "take_room", return_value=True):
            _, spawn = self.launch(400, held, tick)
        self.assertEqual([c.args[1] for c in spawn.call_args_list], [held, fresh])

    def test_cpu_first_orders_across_projects(self):
        b, base = self.serve.board, Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base)
        gate = {"cpu": "cpu_load(600%)", "ram": "ram_room(free=5%)"}

        def project(name, *jobs):  # jobs: (id, lane, play_queued, gate key, extra fields)
            root = base / name / "scrum"
            for job_id, lane, at, g, extra in jobs:
                (root / "jobs" / job_id).mkdir(parents=True)
                (root / "jobs" / job_id / "queue-gates.txt").write_text(gate[g] + "\n")
            (root / "board.json").write_text(json.dumps({"jobs": [
                {"id": i, "stage": "spec", "lane": lane, "play_queued": at, **extra,
                 "queued_launch": {"action": "start", "prompt": "p", "stage": "spec"}} for i, lane, at, g, extra in jobs]}))
            return base / name

        repos = {"a": project("a", ("1-new", "fast", "2026-11-16T05:00:00+00:00", "cpu", {}),
                              ("2-manual", "fast", "2026-11-16T00:00:00+00:00", "cpu", {"play_queued_manual": True}),
                              ("3-std", "standard", "2026-11-15T00:00:00+00:00", "cpu", {})),
                 "b": project("b", ("4-old", "lilguy", "2026-11-16T03:00:00+00:00", "cpu", {}),
                              ("5-ram", "fast", "2026-11-16T01:00:00+00:00", "ram", {}))}
        with mock.patch.object(b, "projects", return_value=repos), mock.patch.object(b, "ram_room", return_value=1):
            self.assertEqual(tuple(self.serve.cpu_first()), ("b", "4-old"))
        with mock.patch.object(b, "projects", return_value={"a": repos["a"]}), mock.patch.object(b, "ram_room", return_value=1):
            self.assertEqual(tuple(self.serve.cpu_first()), ("a", "1-new"))
        with mock.patch.object(b, "projects", return_value={}):
            self.assertIsNone(self.serve.cpu_first())

    def test_cpu_first_light_memory_held_leads(self):
        std = self.cpu_held_job("Mem std", "standard", "2020-01-01T00:00:00+00:00")
        light = self.cpu_held_job("Mem fast", "fast", "2021-01-01T00:00:00+00:00", gate="vm_pressure")
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base)
        (base / "scrum").symlink_to(self.root)
        b = self.serve.board
        with mock.patch.object(b, "projects", return_value={"repo": base}), mock.patch.object(b, "ram_room", return_value=1):
            self.assertEqual(tuple(self.serve.cpu_first()), ("repo", light))
            (self.root / "jobs" / light / "queue-gates.txt").write_text("swap(30%)\n")
            self.assertEqual(tuple(self.serve.cpu_first()), ("repo", light))
            self.edit_job(light, lane="standard")
            self.assertEqual(tuple(self.serve.cpu_first()), ("repo", std))

    def waiting_child_with_gate(self, gate, age_secs):
        """A light waiting child of a running run-all parent whose queue-gates.txt holds `gate`, last noted age_secs ago."""
        b = self.serve.board
        parent = b.cmd_new(self.root, "Runall parent")
        self.edit_job(parent, stage="running", lane="runall")
        child = b.cmd_new(self.root, "Light waiting child")
        self.edit_job(child, stage="waiting", parent=parent, lane="fast")
        path = self.root / "jobs" / child / "queue-gates.txt"
        path.write_text(gate + "\n")
        old = path.stat().st_mtime - age_secs
        os.utime(path, (old, old))
        return child

    def cpu_first_here(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base)
        (base / "scrum").symlink_to(self.root)
        b = self.serve.board
        with mock.patch.object(b, "projects", return_value={"repo": base}), mock.patch.object(b, "ram_room", return_value=1):
            return self.serve.cpu_first()

    def test_cpu_first_ignores_stale_memory_gate(self):
        """Job 1222: a waiting child's vm_pressure line from an earlier launch (hours old) is no current hold."""
        child = self.waiting_child_with_gate("vm_pressure(80%)", 20 * 3600)
        self.assertIsNone(self.cpu_first_here())
        self.serve.note_queue_gate(self.root, child, "vm_pressure(70%)")  # held again now: the line is current
        self.assertEqual(tuple(self.cpu_first_here()), ("repo", child))

    def ram_blocked_setup(self):
        """A standard CPU-held job older than a fast one; board.projects() names this test's board as project repo."""
        std = self.cpu_held_job("Ram std", "standard", "2020-01-01T00:00:00+00:00")
        fast = self.cpu_held_job("Ram fast", "fast", "2021-01-01T00:00:00+00:00")
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base)
        (base / "scrum").symlink_to(self.root)
        return std, fast, mock.patch.object(self.serve.board, "projects", return_value={"repo": base})

    def test_cpu_first_skips_ram_blocked_leader(self):
        std, fast, projects = self.ram_blocked_setup()
        b = self.serve.board
        with projects:
            for std_room, light_room, want in ((1, 1, fast), (1, 0, std), (0, 1, fast)):  # held_order: light first
                with mock.patch.object(b, "ram_room", side_effect=lambda floor=0, light=False: light_room if light else std_room):
                    self.assertEqual(tuple(self.serve.cpu_first()), ("repo", want))

    def test_cpu_first_none_when_all_ram_blocked(self):
        _, _, projects = self.ram_blocked_setup()
        with projects, mock.patch.object(self.serve.board, "ram_room", return_value=0):
            self.assertIsNone(self.serve.cpu_first())

    def test_spawn_light_passes_ram_blocked_leader(self):
        self.cpu_held_job("Ram std", "standard", "2020-01-01T00:00:00+00:00")
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base)
        (base / "scrum").symlink_to(self.root)
        projects, b = mock.patch.object(self.serve.board, "projects", return_value={"repo": base}), self.serve.board
        light_job = self.needs_human("Ram light", reason="approve: ready to merge", lane="fast")
        with projects, mock.patch.object(b, "ram_room", side_effect=lambda floor=0, light=False: 1 if light else 0):
            out, spawn = self.launch(400, light_job, lambda: self.start(light_job))
        self.assertIsNotNone(out)
        self.assertEqual([c.args[1] for c in spawn.call_args_list], [light_job])
        self.assertNotIn("play_queued", self.stage_of(light_job))

    def start(self, job_id, manual=False):
        return self.serve.spawn("repo", self.root, job_id, "start", f"/trevskills-scrum start {job_id}", manual=manual)

    def test_spawn_defers_to_longest_held(self):
        held = self.cpu_held_job("Cpu held", "fast", "2020-01-01T00:00:00+00:00")
        other = self.needs_human("Cpu fresh", reason="approve: ready to merge", lane="fast")
        out, spawn = self.launch(400, other, lambda: self.start(other))
        self.assertIsNone(out)
        spawn.assert_not_called()
        self.assertTrue(self.stage_of(other).get("play_queued"))
        self.assertIn("cpu_queue", (self.root / "jobs" / other / "queue-gates.txt").read_text().split())
        out, spawn = self.launch(400, held, lambda: self.start(held))
        self.assertIsNotNone(out)
        self.assertEqual([c.args[1] for c in spawn.call_args_list], [held])

    def test_spawn_manual_and_empty_queue_unchanged(self):
        held = self.cpu_held_job("Cpu held manual", "fast", "2020-01-01T00:00:00+00:00")
        other = self.needs_human("Cpu click", reason="approve: ready to merge")
        out, spawn = self.launch(400, other, lambda: self.start(other, manual=True))
        self.assertIsNotNone(out)
        self.assertEqual(spawn.call_count, 1)
        self.serve.board.cmd_abort(self.root, held, False)
        self.serve.RUNS.pop(f"repo/{other}", None)
        fresh = self.needs_human("Cpu no queue", reason="approve: ready to merge")
        out, spawn = self.launch(400, fresh, lambda: self.start(fresh))
        self.assertIsNotNone(out)
        self.assertEqual(spawn.call_count, 1)

    def test_board_with_activity_cpu_held_secs(self):
        at = (datetime.now(timezone.utc) - timedelta(seconds=7800)).isoformat(timespec="seconds")
        held = self.cpu_held_job("Cpu held secs", "standard", at)
        ram = self.cpu_held_job("Cpu held ram", "standard", at, ram_hold="14 sessions running, 12% RAM free")
        plain = self.needs_human("Cpu not queued", reason="approve: ready to merge")
        jobs = {j["id"]: j for j in self.serve.board_with_activity(self.root, "repo")["jobs"]}
        self.assertTrue(7795 <= jobs[held]["cpuHeldSecs"] <= 7900, jobs[held].get("cpuHeldSecs"))
        self.assertNotIn("cpuHeldSecs", jobs[ram])
        self.assertNotIn("cpuHeldSecs", jobs[plain])


if __name__ == "__main__":
    unittest.main()
