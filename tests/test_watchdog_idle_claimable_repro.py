"""Job 1219 repro: digest 128 logged 422 idle minutes with claimable work, sessions 0, `gates: []` and no `held:`
token, while the shop Mac ran one job at a time. A watchdog_tick on that state must either start local work
(spawn `start` or `run-all`) or name the hold that skipped it in the next pulse line.

The state that stays silent: a stalled job sits in its auto-resume window (a network-error stall serve.py resumed
one tick ago, its next try NET_RETRY_EVERY away). auto_resume returns True for that wait ("waits"), watchdog_tick
reads it as `pending`, so claim is False: no auto_continue_tick, no start_ready, no wake_waiting, and no note_hold.
Every gate (machine_ok, finish_first, cpu_hot, pick_account) passes, so the run-all should start."""
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
sys.path.insert(0, str(ROOT / "tests"))
tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_REGISTRY"] = os.path.join(tempfile.mkdtemp(), "projects.json")
os.environ["SCRUM_PULSE"] = os.path.join(tempfile.mkdtemp(), "pulse.log")
os.environ["SCRUM_IDLE_CLEANUP"] = "0"
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_VM_PRESSURE"] = "1"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))

import serve  # noqa: E402


class WatchdogIdleClaimableReproTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.repo = self.base / "app"
        self.root = self.repo / "scrum"
        (self.root / "jobs").mkdir(parents=True)
        (self.root / "project.md").write_text("# Project\n- Test: x\n- Auto continue: 1\n")
        (self.root / "backlog.md").write_text("# Backlog\n- [ ] Open item one\n- [ ] Open item two\n")
        now = serve.board.now()
        (self.root / "board.json").write_text(json.dumps({"jobs": [
            {"id": "1617-shop", "stage": "cloud", "shop": "4242", "worker": "shopmac", "account": "main",
             "started_by": "shop", "updatedAt": now, "reason": None},
            {"id": "1600-net", "stage": "build", "stalled": True, "reason": "stalled: no live session",
             "runlog": "runs/1600-net.log", "updatedAt": now}]}))
        (self.root / "runs").mkdir()
        (self.root / "runs" / "1600-net.log").write_text("working...\nError: getaddrinfo ENOTFOUND api.anthropic.com\n")
        self.pulse = self.base / "pulse.log"
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=str(self.base / "projects.json"), SCRUM_PULSE=str(self.pulse),
                              SCRUM_USAGE=str(self.base / "no-usage.json"))
        env.start(); self.addCleanup(env.stop)
        serve.PULSE_HOLDS.clear(); serve.SWEEP_SEEN.clear(); serve.SWEEP_HELD.clear(); serve.IDLE_SINCE.clear()
        serve.AUTO_RESUME.pop("app/1600-net", None)
        self.addCleanup(serve.AUTO_RESUME.pop, "app/1600-net", None)
        self.addCleanup(serve.PULSE_HOLDS.clear)
        self.addCleanup(lambda: [serve.RUNS.pop(k, None) for k in list(serve.RUNS) if k.startswith("app/")])

    def tick(self):
        b = serve.board
        with mock.patch.object(b, "projects", return_value={"app": self.repo}), \
                mock.patch.object(b, "session_alive_fn", return_value=lambda job: False), \
                mock.patch.object(b, "live_sessions", return_value=0), \
                mock.patch.object(b, "machine_ok", return_value=None), \
                mock.patch.object(b, "finish_first", return_value=None), \
                mock.patch.object(b, "pick_account", return_value=("main", None)), \
                mock.patch.object(b, "cmd_cloud_sync", return_value={"moved": [], "error": None}), \
                mock.patch.object(serve.shop, "ended", return_value=None), \
                mock.patch.object(serve, "cpu_hot", return_value=False), \
                mock.patch.object(serve, "shop_tick", return_value=False), \
                mock.patch.object(serve, "run_terminal"), \
                mock.patch.object(serve, "spawn", return_value="runs/x.log") as spawn:
            serve.watchdog_tick()
        return spawn

    def test_watchdog_tick_idle_with_claimable_work_starts_or_notes_hold(self):
        first = self.tick()  # resumes the network-error stall: a real launch, so no claim this tick is right
        self.assertEqual([c.args[2:4] for c in first.call_args_list if c.args[3] == "resume"], [("1600-net", "resume")])
        self.assertEqual(serve.AUTO_RESUME["app/1600-net"][0], 1, "one try spent; the next waits NET_RETRY_EVERY")
        spawn = self.tick()  # nothing to resume yet (its retry is minutes away), every gate passes
        starts = [c.args for c in spawn.call_args_list if c.args[3] in ("start", "run-all")]
        lines = [json.loads(l) for l in self.pulse.read_text().splitlines()] if self.pulse.exists() else []
        gates = (lines[-1]["projects"].get("app") or {}).get("gates") if lines else None
        self.assertTrue(starts, f"no local start (spawn calls {[c.args[:4] for c in spawn.call_args_list]}) "
                                f"and gates {gates!r}: idle with claimable work, no hold named")


if __name__ == "__main__":
    unittest.main()
