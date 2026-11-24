"""Job 1454: a start Trevor or a chat queued by hand (board.hand_queued) launches before auto-resumes and new claims,
oldest play_queued first across projects (serve.hand_queue_tick), and board.finish_first holds every automatic new
claim while one is still queued."""
import io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "trevskills-scrum"))
os.environ["SCRUM_MUTE"] = "1"
os.environ["SCRUM_FREE_RAM"] = "100"
os.environ["SCRUM_VM_PRESSURE"] = "1"
os.environ["SCRUM_COOLDOWN"] = os.path.join(os.devnull, "no-cooldown")
os.environ["SCRUM_SWAP_PCT"] = "1"
os.environ["SCRUM_CPU_BUSY_PCT"] = "1"
os.environ["SCRUM_CPU_LOAD_PCT"] = "1"
os.environ["SCRUM_FREE_DISK_GB"] = "1000"
os.environ["SCRUM_SWAP_LOG"] = os.path.join(tempfile.mkdtemp(), "swap.json")
os.environ["SCRUM_PS"] = os.devnull
os.environ["SCRUM_IDLE_CLEANUP"] = "0"
os.environ["SCRUM_REGISTRY"] = os.path.join(tempfile.mkdtemp(), "projects.json")
os.environ.setdefault("SCRUM_PULSE", os.path.join(tempfile.mkdtemp(), "pulse.log"))
os.environ.setdefault("SCRUM_USAGE", os.path.join(os.devnull, "no-usage.json"))
import board  # noqa: E402
import serve  # noqa: E402


def start(job_id, queued="2026-11-24T22:50:00+00:00", **extra):
    """A parentless spec-stage job with a queued `start` launch."""
    return dict({"id": job_id, "stage": "spec", "play_queued": queued,
                 "queued_launch": {"action": "start", "prompt": f"/trevskills-scrum start {job_id}", "stage": "spec"}},
                **extra)


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.a, self.b = base / "a", base / "b"
        for r in (self.a, self.b):
            (r / "scrum" / "jobs").mkdir(parents=True)
            (r / "scrum" / "board.json").write_text(json.dumps({"jobs": []}))
        reg = base / "projects.json"
        reg.write_text(json.dumps([str(self.a), str(self.b)]))
        env = mock.patch.dict(os.environ, SCRUM_REGISTRY=str(reg), SCRUM_USAGE=str(base / "no-usage.json"))
        env.start()
        self.addCleanup(env.stop)
        term = mock.patch.object(serve, "run_terminal", side_effect=AssertionError("no Terminal under test"))
        term.start()
        self.addCleanup(term.stop)
        self.addCleanup(setattr, serve, "RESUME_ROOM", None)

    def put(self, repo, *jobs):
        (repo / "scrum" / "board.json").write_text(json.dumps({"jobs": list(jobs)}))

    def jobs(self, repo):
        return {j["id"]: j for j in board.read_board(repo / "scrum")["jobs"]}


class HandQueuedTest(Base):
    def test_hand_queued_cases(self):
        root = self.a / "scrum"
        hand = start("001-hand", started_by="hand")
        clicked = start("002-click", started_by="wake", play_queued_manual=True)
        self.assertTrue(board.hand_queued(root, hand))
        self.assertTrue(board.hand_queued(root, clicked))
        for name, job in [("wake", start("010", started_by="wake")),
                          ("serve", start("011", started_by="serve")),
                          ("runall", start("012", started_by="runall")),
                          ("no started_by", start("013")),
                          ("child", dict(hand, parent="099-parent")),
                          ("clicked child", dict(clicked, parent="099-parent")),
                          ("not queued", {k: v for k, v in hand.items() if k != "play_queued"}),
                          ("no launch", {k: v for k, v in hand.items() if k != "queued_launch"}),
                          ("resume", dict(hand, queued_launch={"action": "resume", "prompt": "p", "stage": "spec"})),
                          ("moved on", dict(hand, stage="build")),
                          ("paused", dict(hand, paused=True))]:
            self.assertFalse(board.hand_queued(root, job), name)
        (root / "jobs" / "001-hand").mkdir()
        (root / "jobs" / "001-hand" / "feature.md").write_text("# x\nRuns on: shop\n")
        self.assertFalse(board.hand_queued(root, hand), "tagged Runs on shop: shop_tick sends it")


class HandQueueTickTest(Base):
    def spawned(self, spawn):
        return [(c.args[0], c.args[2], c.args[3]) for c in spawn.call_args_list]

    def test_oldest_hand_start_first_across_projects(self):
        self.put(self.a, start("001-late", "2026-11-24T22:50:00+00:00", started_by="hand"))
        self.put(self.b, start("001-early", "2026-11-24T22:45:00+00:00", play_queued_manual=True))
        with mock.patch.object(serve, "spawn", return_value="log") as spawn:
            serve.RESUME_ROOM = 1
            self.assertEqual(serve.hand_queue_tick(), {"a", "b"})
        self.assertEqual(self.spawned(spawn), [("b", "001-early", "start")])
        self.assertEqual(serve.RESUME_ROOM, 0)
        self.assertTrue(self.jobs(self.a)["001-late"].get("play_queued"), "a's start waits for the next tick")
        self.assertTrue(spawn.call_args.kwargs["manual"], "play_queued_manual stays Trevor's click")
        with mock.patch.object(serve, "spawn", return_value="log") as spawn:
            serve.RESUME_ROOM = 2
            self.assertEqual(serve.hand_queue_tick(), {"a", "b"})
        self.assertEqual(self.spawned(spawn), [("b", "001-early", "start"), ("a", "001-late", "start")])
        self.assertFalse(spawn.call_args.kwargs["manual"], "a chat's start is gated as before")

    def test_held_hand_start_keeps_claims_off(self):
        self.put(self.a, start("001-held", "2026-11-24T22:40:00+00:00", started_by="hand"))
        self.put(self.b, start("001-next", "2026-11-24T22:45:00+00:00", started_by="hand"))
        with mock.patch.object(serve, "spawn", side_effect=[None, "log"]) as spawn:
            serve.RESUME_ROOM = 1
            self.assertEqual(serve.hand_queue_tick(), {"a", "b"})
        self.assertEqual(self.spawned(spawn), [("a", "001-held", "start"), ("b", "001-next", "start")])
        self.assertEqual(serve.RESUME_ROOM, 0, "the held start gave its room back; the next one spent it")
        self.assertTrue(self.jobs(self.a)["001-held"].get("play_queued"), "a held start stays queued")
        serve.RESUME_ROOM = None
        with self.tick_mocks() as m, mock.patch.object(serve, "spawn", return_value=None):
            serve.watchdog_tick()
        m["wake_waiting"].assert_not_called()
        m["auto_continue_tick"].assert_not_called()

    def test_machine_refusal_starts_nothing(self):
        self.put(self.a, start("001-hand", started_by="hand"))
        with mock.patch.object(serve, "spawn", return_value="log") as spawn, \
                mock.patch.object(board, "machine_ok", return_value="free RAM 10% (< 20%)"):
            serve.RESUME_ROOM = 3
            serve.hand_queue_tick()
        spawn.assert_not_called()
        self.assertEqual(serve.RESUME_ROOM, 0)
        self.assertTrue(self.jobs(self.a)["001-hand"].get("play_queued"))

    def test_play_queue_tick_leaves_hand_start_to_hand_pass(self):
        hand = start("001-hand", "2026-11-24T22:40:00+00:00", started_by="hand")
        other = start("002-wake", "2026-11-24T22:45:00+00:00", started_by="wake")
        self.put(self.a, hand, other)
        root = self.a / "scrum"
        with mock.patch.object(serve, "spawn", return_value="log") as spawn:
            serve.RESUME_ROOM = 2
            self.assertTrue(serve.play_queue_tick("a", root, [hand, other]))
        self.assertEqual(self.spawned(spawn), [("a", "002-wake", "start")])
        self.assertEqual(serve.RESUME_ROOM, 1)
        self.assertTrue(self.jobs(self.a)["001-hand"].get("play_queued"), "the hand pass owns it, never unqueued here")

    def test_moved_on_hand_start_unqueued(self):
        self.put(self.a, dict(start("001-moved", started_by="hand"), stage="build"))
        self.put(self.b, start("001-live", started_by="hand"))
        with mock.patch.object(serve, "spawn", return_value="log") as spawn, \
                mock.patch.object(serve, "running", side_effect=lambda p, j: (p, j) == ("b", "001-live")):
            serve.RESUME_ROOM = 2
            self.assertEqual(serve.hand_queue_tick(), set())
        spawn.assert_not_called()
        self.assertEqual(serve.RESUME_ROOM, 2)
        self.assertNotIn("play_queued", self.jobs(self.b)["001-live"])
        self.assertNotIn("queued_launch", self.jobs(self.b)["001-live"])
        # stage moved on: hand_queued no longer accepts it, so play_queue_tick unqueues it as on BASE
        moved = self.jobs(self.a)["001-moved"]
        with mock.patch.object(serve, "spawn", return_value="log") as spawn:
            serve.play_queue_tick("a", self.a / "scrum", [moved])
        spawn.assert_not_called()
        self.assertNotIn("play_queued", self.jobs(self.a)["001-moved"])

    # --- the whole tick ---
    def tick_mocks(self):
        names = ("window_tick", "weekly_tick", "cooldown_chime", "idle_cleanup", "stop_leftovers", "stop_two_sessions",
                 "stop_same_tests", "report_hogs", "e2e_lock_reap", "write_shop_room", "agent_links_tick",
                 "hot_stop_tick", "hard_stop_tick", "auto_continue_tick", "wake_waiting", "queue_ready_waiting",
                 "sweep_parents", "cloud_tick", "project_notes_tick", "shop_tick", "prune_worktrees",
                 "prod_errors_tick", "digest_retry_tick", "actions_alert", "e2e_full_tick", "ui_sweep_tick",
                 "main_ff_tick", "terminal_batch_tick", "claude_migrate", "respawn_exited", "record_outcomes",
                 "idle_claim", "auto_play", "start_ready")
        stack = mock.patch.multiple(serve, **{n: mock.DEFAULT for n in names})
        outer = self

        class Ctx:
            def __enter__(self):
                self.patches = [mock.patch.object(serve.board, "record_cpu_sample"),
                                mock.patch.object(serve.board, "cmd_watchdog", return_value=[]),
                                mock.patch.object(serve.board, "session_alive_fn", return_value=lambda j: False),
                                mock.patch.object(serve.board, "live_sessions", return_value=0),
                                mock.patch.object(serve, "resume_budget", return_value=1),
                                mock.patch("sys.stderr", new=io.StringIO())]
                for p in self.patches:
                    p.start()
                m = stack.start()
                for n in ("main_ff_tick", "idle_claim", "auto_play", "shop_tick"):
                    m[n].return_value = False
                return m

            def __exit__(self, *exc):
                stack.stop()
                for p in reversed(self.patches):
                    p.stop()
                outer.assertIsNone(serve.RESUME_ROOM)
                return False
        return Ctx()

    def test_hand_start_beats_auto_resume_in_earlier_project(self):
        self.put(self.a, {"id": "001-stall", "stage": "build", "stalled": True,
                          "reason": "stalled: no board update for 30 min and no live session"})
        self.put(self.b, start("001-hand", started_by="hand"))
        with self.tick_mocks(), mock.patch.object(serve, "spawn", return_value="log") as spawn:
            serve.watchdog_tick()
        self.assertEqual(self.spawned(spawn), [("b", "001-hand", "start")])


if __name__ == "__main__":
    unittest.main()
